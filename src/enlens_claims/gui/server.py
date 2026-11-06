"""The hypothesis checker's local web app: a small HTTP server (standard library only) and one static page.

    enlens-gui                       # http://127.0.0.1:8765 in your browser
    enlens-gui --home D:/enlens      # keep projects and settings in another folder

Local first:
- It listens on 127.0.0.1 only (another address only with --host, at your own risk).
- Every API call needs the token embedded in the page it served, and a Host header naming this computer, so other
  web sites open in the same browser cannot use it (no CORS, DNS rebinding blocked).
- The page loads nothing from the internet: no CDN, no fonts, no analytics.
- Text goes only to the model service chosen in Settings: a local server by default; the Claude API only after
  cloud models are allowed.

The API is described in docs/API.md. Long work (checks, batches, adding sources, building the semantic index)
runs as a job in a background thread; the page polls /api/jobs/<id> for its progress.
"""
from __future__ import annotations

import csv
import io
import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

from .. import __version__, access, addons, bibliography, claimcheck, embed, frameworks, home, ingest, taskqueue
from .. import sync
from .. import tasks as tasks_mod
from .. import llm
from ..llm import BackendError, detect_local
from ..claude_setup import setup_info as claude_setup_info
from ..store import now as _now
from ..sources import document_overview
from .progress import Tracker

STATIC = Path(__file__).with_name("static")
MAX_UPLOAD = 2 * 1024 ** 3   # bytes per file
MAX_JSON = 20 * 1024 ** 2    # bytes per JSON body (a batch of hypotheses, a codebook)


class ApiError(Exception):
    def __init__(self, status: int, message: str, kind: str = "request", extra: dict | None = None):
        super().__init__(message)
        self.status, self.message, self.kind, self.extra = status, message, kind, extra or {}


class Cancelled(Exception):
    pass


# ---------------------------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------------------------
class Job:
    def __init__(self, kind: str, title: str, project: str | None):
        self.id = uuid.uuid4().hex[:12]
        self.kind, self.title, self.project = kind, title, project
        self.state = "queued"
        self.created = time.time()
        self.started: float | None = None
        self.finished: float | None = None
        self.progress: Any = {}
        self.tracker: Tracker | None = None
        self.result: Any = None
        self.error: str | None = None
        self.error_kind: str | None = None
        self.scope: str | None = None   # 0.7: what a job is about within its project (a document id), to find it again
        self.queue = False              # 0.8: its tasks wait in the queue for Claude Code
        self.cancel = threading.Event()

    def view(self, full: bool = True) -> dict:
        end = self.finished or time.time()
        out = {"id": self.id, "kind": self.kind, "title": self.title, "project": self.project, "state": self.state,
               "created_at": self.created, "started_at": self.started, "finished_at": self.finished,
               "seconds": round(end - (self.started or end), 1), "error": self.error, "error_kind": self.error_kind,
               "scope": self.scope, "queue": self.queue}
        if full:
            out["progress"] = self.tracker.state() if self.tracker else self.progress
            out["result"] = self.result
        return out

    def waits_on_queue(self) -> bool:
        """0.12: its work waits in the queue for Claude Code right now (not its own steps on this computer)."""
        if not self.queue or self.state not in ("queued", "running"):
            return False
        if self.tracker is not None:
            return ((self.tracker.model or {}).get("phase")) == "queue"
        return isinstance(self.progress, dict) and bool(self.progress.get("queue"))


class Jobs:
    """Background work. Jobs that use the chat model run one at a time (a local model serves one request well);
    the others (adding sources, embeddings) run beside them."""

    KEEP = 50

    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.model_lock = threading.Lock()

    def start(self, kind: str, title: str, project: str | None, fn: Callable[[Job], Any], uses_model: bool) -> Job:
        job = Job(kind, title, project)
        with self.lock:
            self.jobs[job.id] = job
            done = [j for j in self.jobs.values() if j.state in ("done", "error", "cancelled")]
            for j in sorted(done, key=lambda j: j.created)[:-self.KEEP or None] if len(done) > self.KEEP else []:
                self.jobs.pop(j.id, None)

        def run():
            lock = self.model_lock if uses_model else None
            try:
                if lock:
                    while not lock.acquire(timeout=0.5):
                        if job.cancel.is_set():
                            raise Cancelled()
                try:
                    if job.cancel.is_set():
                        raise Cancelled()
                    job.state, job.started = "running", time.time()
                    job.result = fn(job)
                    job.state = "cancelled" if job.cancel.is_set() and job.result is None else "done"
                finally:
                    if lock:
                        lock.release()
            except Cancelled:
                job.state = "cancelled"
            except llm.MemoryShort as e:  # 0.13.11: in plain words, not as "the AI model is not answering"
                job.state, job.error, job.error_kind = "error", str(e), "memory"
            except BackendError as e:
                stopped = job.cancel.is_set() and str(e).startswith("Stopped")
                job.state, job.error, job.error_kind = ("cancelled", None, None) if stopped else ("error", str(e), "backend")
            except (ValueError, KeyError, FileNotFoundError) as e:
                job.state, job.error, job.error_kind = "error", (e.args[0] if isinstance(e, KeyError) and e.args
                                                                 else str(e)), "request"
            except Exception as e:  # pragma: no cover - a bug: keep the app running and show it
                traceback.print_exc()
                job.state, job.error, job.error_kind = "error", f"Unexpected problem: {e}", "internal"
            finally:
                job.finished = time.time()
                if job.tracker is not None:
                    job.tracker.finish()

        threading.Thread(target=run, daemon=True, name=f"job-{kind}-{job.id}").start()
        return job

    def all(self) -> list[Job]:
        with self.lock:
            return sorted(self.jobs.values(), key=lambda j: -j.created)

    def get(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise ApiError(404, "No such job (jobs are kept until the app is closed).")
        return job


# ---------------------------------------------------------------------------------------------
# the application
# ---------------------------------------------------------------------------------------------
class App:
    def __init__(self, token: str | None = None):
        self.token = token or secrets.token_urlsafe(24)
        self.jobs = Jobs()
        self.session_key = ""      # a Claude API key given for this session only
        self.allowed_hosts: set[str] = set()
        self.any_host = False
        self.port = 0
        self.launcher = False      # started from the ENLENS icon (launcher.py)
        self.stop = None           # stops the server ("Quit ENLENS"); set by serve()
        self.restart = None        # 0.13.1: stops the server and starts the version on disk in its place (serve())
        self.updating = threading.Lock()  # 0.13.1: one "Update and restart" at a time
        self.update_seen: dict | None = None  # 0.13.6: the last look for a newer version (GET /api/update)
        self.update_looking = threading.Lock()  # one look at a time: the tabs that ask together share it

    # -- helpers ---------------------------------------------------------------------------------
    def settings(self) -> dict:
        return home.load_settings()

    def api_key(self) -> str:
        return self.session_key or home.env_key() or home.stored_key()

    def ws(self, name: str):
        if name not in home.list_projects():
            raise ApiError(404, f"No project called {name!r}.")
        try:
            return home.open_project(name)
        except Exception as e:
            raise ApiError(409, f"Could not open project {name!r}: {e}") from e

    def backend(self, kinds: tuple[str, ...] = ("check", "expand", "decompose", "reread"), k: int | None = None):
        """The main model. `k`: the excerpts a request reads at once, when more than Settings says (the automatic
        context length must hold them)."""
        s = self.settings()
        if k and k > int(s.get("k") or 8):
            s = {**s, "k": k}
        be, model = home.make_backend(s, self.api_key(), kinds=kinds)
        return be, model

    def queue_mode(self) -> bool:
        """0.8: Claude Code (the researcher's own plan) answers: the AI buttons prepare tasks and wait for them."""
        return self.settings().get("backend") == "claude_code"

    # -- 0.13.6: the public interface for add-ons (docs/EXTENDING.md). The old private names keep working. -----------
    def start_job(self, kind: str, title: str, name: str | None, fn, uses_model: bool = True,
                  withdraw: tuple[str, ...] = (), ws=None) -> Job:
        """A job; by queue (Claude Code) its tasks wait in the queue and it does not hold the model's turn. Stopping
        it takes its tasks that no session has taken yet back out of the queue (`withdraw`: their kinds).

        `fn(job)` does the work and returns the job's result; it checks `job.cancel.is_set()` to stop. The job shows
        in GET /api/jobs and the sidebar, can be stopped (POST /api/jobs/<id>/cancel), and is "not running"
        (`on_hold`) while its tasks wait in the queue with nothing answering them."""
        q = self.queue_mode()
        since = _now()

        def run(job: Job):
            with tasks_mod.queueing(q):
                try:
                    return fn(job)
                finally:
                    if q and job.cancel.is_set() and withdraw and ws is not None:
                        taskqueue.withdraw(ws, list(withdraw), since=since)

        job = self.jobs.start(kind, title, name, run, uses_model=uses_model and not q)
        job.queue = q
        return job

    _job = start_job  # the name before 0.13.6

    def job_views(self, active_only: bool = False) -> list[dict]:
        """The jobs for the page, each with `on_hold` (0.12): its work waits in the queue for Claude Code and nothing
        answers it (Claude Code not started from ENLENS, no session typed in Claude Code taking or answering a batch),
        so it is not running, whatever its state says. Asked once per project."""
        answering: dict[str, bool] = {}
        out = []
        for j in self.jobs.all():
            if active_only and j.state not in ("queued", "running"):
                continue
            v = j.view(full=False)
            v["on_hold"] = False
            if j.project and j.waits_on_queue():
                if j.project not in answering:
                    answering[j.project] = self.queue_answering(j.project)
                v["on_hold"] = not answering[j.project]
            out.append(v)
        return out

    def queue_answering(self, name: str) -> bool:
        """0.12: whether something answers the project's queue now: Claude Code started from ENLENS, or a session
        typed in Claude Code. When that cannot be told, the work is not called on hold."""
        from .. import claude_setup

        try:
            return bool(claude_setup.run_state(name).get("running")) or taskqueue.answering(home.open_project(name))
        except Exception:  # noqa: BLE001 - a project that cannot be opened: say nothing rather than "on hold"
            return True

    def project_summary(self, name: str) -> dict:
        try:
            ws = home.open_project(name)
            docs = int(ws.scalar("SELECT COUNT(*) FROM documents") or 0)
            hyps = int(ws.scalar("SELECT COUNT(*) FROM hypotheses") or 0)
            ok = True
        except Exception:
            docs = hyps = 0
            ok = False
        return {"name": name, "linked": home.is_linked(name), "documents": docs, "hypotheses": hyps, "ok": ok,
                "path": str(home.project_path(name)), "temporary": home.is_temporary(name)}

    # -- read-only views -------------------------------------------------------------------------
    def state(self) -> dict:
        try:
            home.cleanup_quicklooks()  # quick looks not kept go to the trash after a week
        except OSError:
            pass
        s = self.settings()
        projects = [self.project_summary(n) for n in home.list_projects()]
        names = [p["name"] for p in projects]
        current = s.get("project") if s.get("project") in names else None
        if current is None and s.get("project") and names:  # the project was removed: open another one
            current = next((p["name"] for p in projects if not p.get("temporary")), names[0])
            home.update_settings({"project": current})
        out = {"version": __version__, "installed_version": _installed_version(), "home": str(home.home()), "settings": s,
               "brand": addons.brand(),   # 0.13.5: the app's name and words (static/brand.json and add-ons)
               "addon_pages": addons.page_modules(),   # 0.13.6: add-on packages' page modules
               "backend_label": home.backend_label(s), "backend_labels": home.BACKEND_LABELS,
               "projects": projects, "project": current, "local_only": home.local_only(),
               "launcher": self.launcher, "can_quit": self.stop is not None,
               "can_restart": self.restart is not None,
               "context": home.context_plan(s),
               "restricted": home.restricted_choice(s),   # 0.11: the local model for restricted documents
               "ocr": ingest.ocr_status(),
               "installation": _installation(),
               "key": {"session": bool(self.session_key), "env": bool(home.env_key()), "stored": bool(home.stored_key())},
               "statuses": [{"status": k, "text": v, "help": claimcheck.STATUS_HELP.get(k, ""),
                             "next": claimcheck.STATUS_NEXT.get(k, "")} for k, v in claimcheck.STATUS_TEXT.items()],
               "jobs": self.job_views(active_only=True),
               "queue": self._queue_summary(current)}
        out.update(addons.state(self, set(out)))  # 0.13.6: an add-on's keys, never in place of ENLENS's
        return out

    def _queue_summary(self, name: str | None) -> dict | None:
        """What waits in the current project's queue, for the sidebar (0.8)."""
        if not name:
            return None
        try:
            ws = home.open_project(name)
            n = ws.scalar("SELECT COUNT(*) FROM tasks WHERE COALESCE(queued, 0)=1 AND COALESCE(access, 'cloud')='cloud' "
                          "AND (status IN ('pending', 'retry') OR (status='done' AND again=1))") or 0
        except Exception:  # noqa: BLE001
            return None
        return {"waiting": int(n)}

    def servers(self) -> dict:
        s = self.settings()
        found = detect_local(ollama_url=s.get("ollama_url"), extra=[s.get("openai_url") or ""], cache_seconds=3)
        for srv in found:
            srv["chat_models"] = [m for m in srv["models"] if not re.search(r"embed|bge-|e5-|minilm|rerank", m, re.I)]
            srv["embedding_models"] = [m for m in srv["models"] if re.search(r"embed|bge-|e5-|minilm", m, re.I)]
        # 0.13.7: the models the page offers to download into Ollama with one button
        return {"servers": found, "suggested": [dict(m) for m in llm.SUGGESTED_MODELS]}

    # 0.13.7: what a downloaded model is for, and the settings that choose it (applied when the download is done)
    PULL_USES = {"ai": ("backend", "ollama_url", "ollama_model", "embed_backend", "embed_model", "embed_url"),
                 "restricted": ("restricted_server", "restricted_model"),
                 "embed": ("embed_backend", "embed_model", "embed_url")}

    def pull_models(self, models: list[str], url: str, use: str = "") -> Job:
        """0.13.7: download models into the Ollama on this computer, one after the other (a job that can be stopped).
        Ollama fetches them from ollama.com itself; nothing of the person's is sent. With `use` ("ai": the AI that
        reads the documents; "restricted": the local model for documents marked Only a local AI; "embed": search by
        meaning) the downloaded models are chosen when the download is done, even if the page was closed meanwhile,
        unless those settings were changed in the meantime."""
        running = [j for j in self.jobs.all() if j.kind == "model-pull" and j.state in ("queued", "running")]
        if running:
            return running[0]
        keys = self.PULL_USES.get(use, ())
        before = {k: self.settings().get(k) for k in keys}

        def choose(listed: dict) -> dict | None:
            is_embed = lambda m: bool(re.search(r"embed|bge-|e5-|minilm", m, re.I))  # noqa: E731 - as servers() sorts
            chat = next((v for v in listed.values() if not is_embed(v)), "")
            emb = next((v for v in listed.values() if is_embed(v)), "")
            changes: dict = {}
            if use == "ai" and chat:
                changes = {"backend": "ollama", "ollama_url": url, "ollama_model": chat}
            elif use == "restricted" and chat:
                changes = {"restricted_server": "ollama", "restricted_model": chat}
            if emb and use in ("ai", "embed"):
                changes.update({"embed_backend": "ollama", "embed_model": emb, "embed_url": ""})
            now = self.settings()
            if not changes or any(now.get(k) != before.get(k) for k in keys):
                return None   # nothing to choose, or the person chose something else meanwhile: theirs stands
            home.update_settings(changes)
            return changes

        def run(job: Job):
            be = llm.OllamaBackend(base_url=url, stall_timeout=600)
            got: list[str] = []
            for i, model in enumerate(models):
                job.progress = {"model": model, "index": i, "count": len(models), "status": "", "done": 0, "total": 0}

                def tick(info, model=model, i=i):
                    job.progress = {"model": model, "index": i, "count": len(models), **info}

                if be.pull(model, on_progress=tick, should_stop=job.cancel.is_set) == "stopped":
                    return None
                got.append(model)
                llm._DETECTED.clear()   # the next look at the servers lists it
            # the names as Ollama lists them (a name without a tag gets ":latest"), to choose them in Settings
            listed = {m: m if ":" in m.rsplit("/", 1)[-1] else f"{m}:latest" for m in got}
            return {"url": url, "models": got, "listed": listed, "chosen": choose(listed) if use else None}

        return self.jobs.start("model-pull", "Downloading " + " and ".join(models), None, run, uses_model=False)

    def test_backend(self) -> dict:
        s = self.settings()
        be, model = home.make_backend(s, self.api_key())
        info = be.check(model)
        out = {"ok": True, "backend": getattr(be, "name", ""), "model": model,
               "model_available": info.get("model_available", True), "details": info.get("model") or {},
               "warning": info.get("warning") or getattr(be, "model_note", None)}
        if getattr(be, "num_ctx", None):
            out["context"] = {**home.context_plan(s), "num_ctx": be.num_ctx}
        if out["backend"] == "ollama":
            out["message"] = (f"Ollama {info.get('version', '')} is running. {model}: "
                              f"{(info.get('model') or {}).get('parameters') or '?'} parameters, "
                              f"{(info.get('model') or {}).get('quantization') or '?'}." if out["model_available"]
                              else f"Ollama is running, but {model} is not installed. Choose one of its models in Settings → AI, "
                                   f"or download one there.")
        elif out["backend"] == "local":
            out["message"] = (f"The server at {info.get('url')} answers and offers {model}." if out["model_available"]
                              else f"The server answers, but does not list {model}.")
        elif out["backend"] == "claude_code":
            from .. import claude_setup

            st = claude_setup.status(refresh=True)
            out["model_available"] = bool(st["ready"])
            out["claude"] = st
            out["message"] = ("Claude Code is set up: " + (st.get("version") or "found") + ", with the ENLENS plugin. "
                              "Press Start Claude Code where work waits." if st["ready"] else
                              "Claude Code is not on this computer yet. Install it, then press Set up Claude Code."
                              if not st["found"] else "Claude Code is found, but the ENLENS plugin is not added to it "
                              "yet: press Set up Claude Code.")
            if st.get("signed_in") is False:
                out["warning"] = "Claude Code is not signed in: open a terminal, type claude and sign in once."
        elif out["backend"] == "anthropic":
            out["message"] = (f"Connected to the Claude API. {model} is available." if out["model_available"]
                              else f"Connected, but {model} is not in this key's model list.")
        else:
            out["message"] = "The offline demo grades by word overlap. Its results are not findings."
        emb = home.make_embedder(s)
        if emb is not None:
            try:
                vec = emb.embed(["test"])[0]
                out["embedding"] = {"ok": True, "model": emb.model, "dimensions": len(vec)}
            except BackendError as e:
                out["embedding"] = {"ok": False, "model": emb.model, "error": str(e)}
        return out

    def project(self, name: str) -> dict:
        ws = self.ws(name)
        s = self.settings()
        out = self.project_summary(name)
        out["passages"] = int(ws.scalar("SELECT COUNT(*) FROM passages WHERE section='body'") or 0)
        out["search"] = embed.status(ws, s.get("embed_model"),
                                     home.make_embedder(s))
        out["ai_access"] = access.project_info(ws)
        out["frameworks"] = [fw.info() for fw in frameworks.available(ws).values()]
        return out

    def documents(self, name: str) -> dict:
        ws = self.ws(name)
        s = self.settings()
        docs = document_overview(ws)
        acc = access.documents_view(ws)  # 0.11: who may read each one with AI, and how much Claude has read
        cites = bibliography.doc_citations(ws)  # 0.13: the work of the bibliography each document is
        clash = sync.copies_of(ws, "document")  # 0.14: a colleague's reading of a file you have too
        for d in docs:
            d.update(acc.get(d["doc_id"], {}))
            d["bib"] = cites.get(d["doc_id"])
            d["clash"] = clash.get(d["doc_id"])
        return {"documents": docs, "ai_access": access.project_info(ws),
                "restricted_model": home.restricted_choice(s),
                "search": embed.status(ws, s.get("embed_model"),
                                       home.make_embedder(s))}

    def document(self, name: str, doc_id: str, offset: int, limit: int, view: str = "") -> dict:
        ws = self.ws(name)
        d = ws.query("SELECT doc_id, title, file_title, path, kind, n_pages, n_chars, doi, added_at FROM documents "
                     "WHERE doc_id=?", (doc_id,))
        if not d:
            raise ApiError(404, "No such document.")
        out = dict(d[0])
        out["file_title"] = bibliography.file_title(d[0])  # 0.13.3: the title read from the file, if replaced
        out["file"] = re.sub(r".*[/\\]", "", out.pop("path") or "")
        out["total_passages"] = int(ws.scalar("SELECT COUNT(*) FROM passages WHERE doc_id=?", (doc_id,)) or 0)
        # the blocks view (the document viewer) reads by page or paragraph and never the passages (0.11.1)
        out["passages"] = [] if view == "blocks" else [dict(r) for r in ws.query(
            "SELECT passage_id, seq, page, section, start, end, text FROM passages WHERE doc_id=? ORDER BY seq LIMIT ? OFFSET ?",
            (doc_id, max(1, min(limit, 200)), max(0, offset)))]
        out["offset"] = offset
        out["bib"] = bibliography.doc_citations(ws).get(doc_id)  # 0.13
        info = self.original(ws, doc_id)
        out["original"] = {"available": info["available"], "reason": info["reason"], "name": info["name"]}
        if view == "blocks":  # the document as a reader cites it: by page, or by paragraph for files without pages
            out["blocks"], out["total_blocks"] = self.blocks(ws, doc_id, offset, limit)
        return out

    @staticmethod
    def original(ws, doc_id: str) -> dict:
        from ..sources import original_file

        try:
            return original_file(ws, doc_id)
        except KeyError:
            raise ApiError(404, "No such document.") from None

    @staticmethod
    def blocks(ws, doc_id: str, offset: int, limit: int) -> tuple[list[dict], int]:
        """The document as a reader cites it: by paragraph within each page for PDFs added from 0.6 on ("Page 2,
        paragraph 3"), by page for older ones, by paragraph for files without pages. Each block lists its headings
        (offsets local to the block's text), to show them as headings."""
        text = ws.scalar("SELECT text FROM documents WHERE doc_id=?", (doc_id,)) or ""
        pages = ws.query("SELECT page, start, end FROM pages WHERE doc_id=? ORDER BY page", (doc_id,))
        paras = ws.query("SELECT start, page FROM paragraphs WHERE doc_id=? ORDER BY n", (doc_id,))
        heads = [(r["start"], r["end"]) for r in ws.query("SELECT start, end FROM headings WHERE doc_id=? ORDER BY start",
                                                           (doc_id,))]

        spans: list[tuple[str, int, int | None, int | None, int, int]] = []  # label, n, page, paragraph, start, end
        if pages:
            by_page: dict[int, list[int]] = {}
            for r in paras:
                if r["page"] is not None:
                    by_page.setdefault(r["page"], []).append(r["start"])
            for r in pages:
                starts = sorted(by_page.get(r["page"], []))
                if not starts:
                    spans.append((f"Page {r['page']}", r["page"], r["page"], None, r["start"], r["end"]))
                    continue
                bounds = [r["start"]] + starts[1:] + [r["end"]]
                for j in range(len(starts)):
                    spans.append((f"Page {r['page']}, paragraph {j + 1}", 0, r["page"], j + 1, bounds[j], bounds[j + 1]))
        else:
            starts = [r["start"] for r in paras]
            bounds = ([0] + starts[1:] + [len(text)]) if starts else []
            spans = ([(f"Paragraph {i}", i, None, i, bounds[i - 1], bounds[i]) for i in range(1, len(starts) + 1)]
                     or [("The whole text", 1, None, None, 0, len(text))])
        spans = [(lab, n or i, pg, pa, a, b) for i, (lab, n, pg, pa, a, b) in enumerate(spans, 1)]
        chosen = spans[max(0, offset):max(0, offset) + max(1, min(limit, 500))]
        out = []
        for lab, n, pg, pa, s0, e0 in chosen:
            raw = text[s0:e0]
            lead = len(raw) - len(raw.lstrip())
            body = raw.strip()
            hs = [{"at": h0 - s0 - lead, "end": min(h1, e0) - s0 - lead, "text": text[h0:h1]}
                  for h0, h1 in heads if s0 <= h0 < e0 and h0 - s0 - lead >= 0]
            out.append({"label": lab, "n": n, "page": pg, "paragraph": pa, "start": s0 + lead, "end": s0 + lead + len(body),
                        "text": body, "headings": hs})
        return out, len(spans)

    def hypotheses(self, name: str, q: dict) -> dict:
        ws = self.ws(name)
        thr = _float(q, "threshold", self.settings()["threshold"])
        # one pass over the project (0.11.1: a filtered list ran the five whole-table reads of history twice), the
        # counts over every hypothesis, the rows filtered here by the same rules
        text, status, batch = (_str(q, "q") or "").lower().strip(), _str(q, "status"), _str(q, "batch")
        rows = claimcheck.history(ws, thr)
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        if text or status or batch:
            rows = [r for r in rows if (not text or text in (r["text"] or "").lower())
                    and (not status or r["status"] == status) and (not batch or r["batch_id"] == batch)]
            if batch:
                rows.reverse()  # a set reads in the order it was typed
        limit = int(_float(q, "limit", 0))
        rows = rows[:limit] if limit else rows
        clash = sync.copies_of(ws, "check")  # 0.14: a colleague's version of a check you both changed
        for r in rows:
            r["clash"] = clash.get(r["hyp_id"])
        return {"hypotheses": rows, "counts": counts, "threshold": thr}

    # -- jobs ------------------------------------------------------------------------------------
    def wire(self, job: Job, be, tracker: Tracker | None = None) -> None:
        """Let the backend `be` see the job's Stop and report its progress (0.13.6: public; `_wire` before)."""
        if hasattr(be, "should_stop"):
            be.should_stop = job.cancel.is_set
        if tracker is not None and hasattr(be, "progress"):
            be.progress = tracker.model_report
        # 0.13.11: for the local model that reads the documents marked Only a local AI beside this one (access.Readers),
        # also when this one reports nothing itself (the Claude API)
        try:
            be.local_should_stop = job.cancel.is_set
            if tracker is not None:
                be.local_progress = tracker.model_report
        except AttributeError:
            pass

    _wire = wire  # the name before 0.13.6

    def start_check(self, name: str, body: dict) -> Job:
        ws = self.ws(name)
        s = self.settings()
        text = str(body.get("text") or "")
        claimcheck._clean(text)  # the plain mistakes are reported at once, not as a failed job
        fw, code = body.get("framework") or None, body.get("code") or None
        frameworks.resolve(ws, fw, code)
        opts = _check_options(body, s)
        prepared = {}
        if body.get("parts") is not None:  # "Look before checking": the parts and words the person chose
            if not isinstance(body["parts"], list):
                raise ApiError(400, "parts must be a list of sentences.")
            claimcheck._given_parts(body["parts"], text)  # plain mistakes are reported at once
            prepared["parts"] = body["parts"]
        if body.get("terms") is not None:
            if not isinstance(body["terms"], list):
                raise ApiError(400, "terms must be a list (one list of words per part).")
            prepared["terms"] = body["terms"]
        if prepared:
            prepared["edited"] = body.get("edited") if isinstance(body.get("edited"), dict) else {}
        be, model = self.backend(k=opts["k"])
        emb = home.make_embedder(s) if opts.pop("semantic", True) else None
        if self.queue_mode():
            def qrun(job: Job):
                tracker = Tracker(expand=opts["expand"] and "terms" not in prepared)
                job.tracker = tracker
                hid = claimcheck.queue_check(ws, text, getattr(be, "router", None), framework=fw, code=code,
                                             embed_model=getattr(_usable_embedder(ws, emb), "model", None),
                                             **opts, **prepared)
                self._follow_queued(job, ws, [hid], tracker)
                return {"hyp_id": hid, "status": claimcheck.hypothesis_result(ws, hid, s["threshold"])["status"]}

            return self._job("check", text[:120], name, qrun)

        def run(job: Job):
            tracker = Tracker(expand=opts["expand"] and "terms" not in prepared)
            job.tracker = tracker
            self._wire(job, be, tracker)
            hid = claimcheck.check_hypothesis(ws, text, be, model, framework=fw, code=code, progress=tracker.step,
                                              embedder=_usable_embedder(ws, emb), should_stop=job.cancel.is_set,
                                              **opts, **prepared)
            return {"hyp_id": hid, "status": claimcheck.hypothesis_result(ws, hid, s["threshold"])["status"]}

        return self.jobs.start("check", text[:120], name, run, uses_model=True)

    def follow_queued(self, job: Job, ws, hyp_ids: list[str], tracker: Tracker, poll: float = 2.0) -> None:
        """Follow checks by queue until Claude Code has answered their steps; their steps are taken as the answers
        arrive (here, or in the connector). Stop withdraws the checks that are still waiting. (0.13.6: public;
        `_follow_queued` before.)"""
        shown: dict[str, str] = {}
        t0 = time.time()
        # 0.11: the local model for restricted documents (Claude reads the rest). 0.13.11: it shows what it does and
        # sees Stop; it is not started when the computer has no room for it; and its memory is freed at the end.
        readers = access.Readers(None, "", progress=tracker.model_report, should_stop=job.cancel.is_set)
        try:
            self._follow_loop(job, ws, hyp_ids, tracker, readers, shown, t0, poll)
        finally:
            claimcheck._let_go(readers)

    def _read_local_now(self, ws, hyp_ids: list[str], tracker: Tracker, readers) -> bool:
        """0.13.11: read the excerpts that wait for the local model, saying so (they were read in silence, under
        "Waiting for Claude Code")."""
        if readers.memory_short:
            return False  # said once; they wait for "Read them now"
        waiting = claimcheck.local_waiting(ws, hyp_ids)
        if not waiting:
            return False

        def started(model: str, n: int) -> None:
            tracker.say(f"Your local model ({model}) is reading {n} {'excerpt' if n == 1 else 'excerpts'} from "
                        "documents marked Only a local AI, on this computer")

        n = sum(w["passages"] for w in waiting)
        before = readers.read
        try:
            done = claimcheck.run_local_parts(ws, hyp_ids, readers, on_start=started)
        except BackendError:
            if readers.stopped():
                return False  # Stop: the follower withdraws the checks
            raise
        if readers.memory_short:
            tracker.step("note", f"{readers.memory_short} {claimcheck._waiting_words(n)}", {"keep": True})
        elif done and readers.read > before:
            tracker.step("note", f"Your local model read {n} {'excerpt' if n == 1 else 'excerpts'} from documents "
                                 "marked Only a local AI, on this computer", {})
        elif done:
            tracker.step("note", (f"The local model could not be used ({readers.local_problem}); " if
                                  readers.local_problem else "No local model read them; ") +
                         f"the {n} {'excerpt' if n == 1 else 'excerpts'} from documents marked Only a local AI "
                         f"{'waits' if n == 1 else 'wait'} for your judgement", {})
        return True

    def _follow_loop(self, job: Job, ws, hyp_ids: list[str], tracker: Tracker, readers, shown: dict, t0: float,
                     poll: float) -> None:
        while True:
            left = taskqueue.advance(ws, hyp_ids)
            self._show_stages(ws, hyp_ids, tracker, shown)
            # 0.13.11: the steps are shown first, so the page says which excerpts the local model reads
            if self._read_local_now(ws, hyp_ids, tracker, readers):
                left = taskqueue.advance(ws, hyp_ids)
                self._show_stages(ws, hyp_ids, tracker, shown)
            if not left:
                return
            if job.cancel.is_set():
                for hid in left:
                    claimcheck.delete_hypothesis(ws, hid)  # a stopped check leaves nothing behind, as in 0.7
                raise Cancelled()
            if readers.memory_short and all(claimcheck.only_local_waits(ws, hid) for hid in left):
                return  # 0.13.11: Claude Code is done; the local excerpts wait for "Read them now" on the result
            kind = {"decompose": "decompose", "terms": "expand"}.get(claimcheck.queue_stage(ws, left[0]).get("step"),
                                                                      "check")
            tracker.model_report({"phase": "queue", "seconds": time.time() - t0, **taskqueue.queue_info(ws, kind)})
            time.sleep(poll)

    def _show_stages(self, ws, hyp_ids: list[str], tracker: Tracker, shown: dict) -> None:
        """The steps of checks by queue, as far as they have come (said once per change)."""
        for i, hid in enumerate(hyp_ids, 1):
            st = claimcheck.queue_stage(ws, hid)
            info = {"index": i, "total": len(hyp_ids)} if len(hyp_ids) > 1 else {}
            key = f"{st.get('state')}:{st.get('step')}:{st.get('stages')}"
            if shown.get(hid) == key:
                continue
            shown[hid] = key
            if len(hyp_ids) > 1 and st.get("state") == "waiting":
                tracker.step("item", f"Hypothesis {i} of {len(hyp_ids)}",
                             {**info, "text": ws.scalar("SELECT text FROM hypotheses WHERE hyp_id=?", (hid,))})
            if st.get("step") == "decompose":
                tracker.step("decompose", "Waiting for Claude Code to split the hypothesis into parts", info)
            for n, (stage, text) in enumerate(zip(st.get("stages") or [], st.get("texts") or [])):
                pinfo = {**info, **({"part": n + 1, "parts": len(st["stages"]), "claim": text}
                                    if len(st["stages"]) > 1 else {})}
                if stage == "terms":
                    tracker.step("terms", "Waiting for Claude Code to propose other words", pinfo)
                elif stage in ("judge", "done"):
                    tracker.step("terms_done", "Search words ready", pinfo)
                    tracker.step("rank_done", "Excerpts chosen in your documents", pinfo)
                    if stage == "judge":
                        tracker.step("grade", "Waiting for Claude Code to read the excerpts", pinfo)
                    else:
                        tracker.step("grade_done", "Read; every quote was checked against the document", pinfo)

    _follow_queued = follow_queued

    def start_prepare(self, name: str, body: dict) -> Job:
        """The parts and extra search words a check would use, for the person to look at and edit first."""
        ws = self.ws(name)
        s = self.settings()
        text = str(body.get("text") or "")
        claimcheck._clean(text)
        fw, code = body.get("framework") or None, body.get("code") or None
        frameworks.resolve(ws, fw, code)
        decompose = bool(body["decompose"]) if "decompose" in body else bool(s["decompose"])
        expand = bool(body["expand"]) if "expand" in body else bool(s["expand"])
        be, model = self.backend()

        def run(job: Job):
            tracker = Tracker(expand=expand, steps=("terms",))
            job.tracker = tracker
            self._wire(job, be, tracker)
            return claimcheck.prepare_check(ws, text, be, model, decompose=decompose, expand=expand, framework=fw,
                                            code=code, progress=tracker.step, should_stop=job.cancel.is_set)

        return self._job("prepare", text[:120], name, run, withdraw=("decompose", "expand"), ws=ws)

    def start_reread(self, name: str, claim_id: str, passage_id: str, body: dict) -> Job:
        ws = self.ws(name)
        if not ws.scalar("SELECT 1 FROM user_claims WHERE claim_id=?", (claim_id,)):
            raise ApiError(404, "No such claim.")
        if not any(p["passage_id"] == passage_id for t in claimcheck._check_tasks(ws, claim_id)
                   for p in json.loads(t["payload_json"])["passages"]):
            raise ApiError(404, "This excerpt was not read for this claim.")
        note = body.get("note") if "note" in body else None
        if note is not None and not isinstance(note, str):
            raise ApiError(400, "note must be text.")
        be, model = self.backend()
        doc = ws.scalar("SELECT doc_id FROM passages WHERE passage_id=?", (passage_id,))
        level = access.levels(ws, [doc]).get(doc, "none") if doc else "none"
        if level == "none" or (level == "local" and not access.Readers(be, model).local_configured()):
            raise ApiError(409, "This excerpt's document is marked No AI: no model may read it. Give your own "
                                "judgement instead." if level == "none" else
                                "This excerpt's document is marked Only a local AI, and no local model is chosen for "
                                "such documents. Choose one in Settings → AI, or give your own judgement.")

        def run(job: Job):
            tracker = Tracker(expand=False, steps=("grade",))
            job.tracker = tracker
            self._wire(job, be, tracker)
            r = claimcheck.reread_excerpt(ws, claim_id, passage_id, be, model, note=note, progress=tracker.step,
                                          should_stop=job.cancel.is_set)
            r["hyp_id"] = ws.scalar("SELECT hyp_id FROM user_claims WHERE claim_id=?", (claim_id,))
            return r

        return self._job("reread", "Reading one excerpt again", name, run, withdraw=("reread",), ws=ws)

    def start_read_local(self, name: str, hyp_id: str, force: bool = False) -> Job:
        """0.11: read the excerpts of a check that wait for the local model (made in a Claude chat, or while the app
        was closed), with the local model for restricted documents; without one they wait for a person. 0.13.11:
        `force` starts the model even when this computer seems to have too little memory free for it (the person
        chose "Start it anyway")."""
        ws = self.ws(name)
        if not ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (hyp_id,)):
            raise ApiError(404, "No such hypothesis.")
        be, model = self.backend()

        def run(job: Job):
            # 0.13.11: with progress and Stop, and not started when the computer has no room for the model
            tracker = Tracker(expand=False, steps=("grade",))
            job.tracker = tracker
            self._wire(job, be, tracker)  # a local main model reads them itself
            readers = access.Readers(be, model, progress=tracker.model_report, should_stop=job.cancel.is_set,
                                     check_memory=not force)
            try:
                n = claimcheck.run_local_parts(
                    ws, [hyp_id], readers, retry_failed=True,
                    on_start=lambda m, k: tracker.say(f"Your local model ({m}) is reading {k} "
                                                      f"{'excerpt' if k == 1 else 'excerpts'} on this computer"))
            finally:
                claimcheck._let_go(readers)
            if readers.memory_short:
                raise readers.memory_short
            taskqueue.advance(ws, [hyp_id])
            return {"hyp_id": hyp_id, "parts": n,
                    "status": claimcheck.hypothesis_result(ws, hyp_id, self.settings()["threshold"])["status"]}

        job = self.jobs.start("read-local", "Reading excerpts with the local model", name, run, uses_model=True)
        job.scope = hyp_id  # 0.13.11: the result page that started it follows it again after a reload
        return job

    def start_batch(self, name: str, body: dict) -> Job:
        ws = self.ws(name)
        s = self.settings()
        items = body.get("items")
        if not items:
            items = claimcheck.parse_batch(str(body.get("text") or ""))
        items = [{"text": str(i.get("text") or ""), "framework": i.get("framework") or None, "code": i.get("code") or None}
                 for i in items if isinstance(i, dict)]
        if not items:
            raise ApiError(400, "No hypotheses found. Give one per line, or a CSV with a 'hypothesis' column.")
        opts = _check_options(body, s)
        be, model = self.backend(k=opts["k"])
        emb = home.make_embedder(s) if opts.pop("semantic", True) else None
        if self.queue_mode():
            def qrun(job: Job):
                tracker = Tracker(expand=opts["expand"])
                job.tracker = tracker
                batch_id = claimcheck._new_id("b")
                done, errors = [], []
                for i, it in enumerate(items, 1):  # every check prepared at once; Claude Code reads them in turn
                    try:
                        done.append(claimcheck.queue_check(ws, it["text"], getattr(be, "router", None),
                                                           framework=it.get("framework"),
                                                           code=it.get("code"), batch_id=batch_id,
                                                           embed_model=getattr(_usable_embedder(ws, emb), "model", None),
                                                           **opts))
                    except ValueError as e:
                        errors.append({"index": i, "text": it["text"], "error": str(e)})
                self._follow_queued(job, ws, done, tracker)
                return {"batch_id": batch_id, "checked": done, "errors": errors, "stopped": None, "total": len(items)}

            return self._job("batch", f"{len(items)} hypotheses", name, qrun)

        def run(job: Job):
            tracker = Tracker(expand=opts["expand"])
            job.tracker = tracker
            self._wire(job, be, tracker)
            return claimcheck.check_batch(ws, items, be, model, progress=tracker.step, should_stop=job.cancel.is_set,
                                          embedder=_usable_embedder(ws, emb), **opts)

        return self.jobs.start("batch", f"{len(items)} hypotheses", name, run, uses_model=True)

    def start_more(self, name: str, claim_id: str, body: dict) -> Job:
        ws = self.ws(name)
        s = self.settings()
        if not ws.scalar("SELECT 1 FROM user_claims WHERE claim_id=?", (claim_id,)):
            raise ApiError(404, "No such claim.")
        k = _body_int(body, "k", int(s["k"]), 1, 100)
        terms = [str(t) for t in (body.get("terms") or []) if str(t).strip()] or None
        if isinstance(body.get("terms"), str):
            terms = [t.strip() for t in body["terms"].split(",") if t.strip()] or None
        be, model = self.backend(k=max(1, min(k, 20)))
        emb = home.make_embedder(s)

        def run(job: Job):
            tracker = Tracker(expand=False)
            job.tracker = tracker
            self._wire(job, be, tracker)
            r = claimcheck.continue_check(ws, claim_id, be, model, k=max(1, min(k, 20)), terms=terms,
                                          embedder=_usable_embedder(ws, emb), progress=tracker.step,
                                          should_stop=job.cancel.is_set)
            hyp = ws.scalar("SELECT hyp_id FROM user_claims WHERE claim_id=?", (claim_id,))
            return {"claim_id": claim_id, "hyp_id": hyp, "round": r["round"], "passages": len(r["passages"]),
                    "ok": r.get("ok")}

        return self._job("more", "Reading more passages", name, run)

    def _hyp_ids(self, ws, body: dict) -> list[str]:
        """The hypotheses a request is about: `hyp_ids`, or every hypothesis of one set (`batch`)."""
        if body.get("hyp_ids") is not None:
            ids = body["hyp_ids"]
            if not (isinstance(ids, list) and all(isinstance(i, str) for i in ids)):
                raise ApiError(400, "hyp_ids must be a list of hypothesis ids.")
            known = {r[0] for r in ws.query("SELECT hyp_id FROM hypotheses")}
            missing = [i for i in ids if i not in known]
            if missing:
                raise ApiError(404, f"No hypothesis {missing[0]!r}.")
            return list(dict.fromkeys(ids))
        if body.get("batch"):
            ids = [h["hyp_id"] for h in claimcheck.history(ws, batch_id=str(body["batch"]))]
            if not ids:
                raise ApiError(404, "No such set of hypotheses.")
            return ids
        raise ApiError(400, "Say which hypotheses: hyp_ids, or batch.")

    def start_read_new(self, name: str, hyp_ids: list[str]) -> Job:
        """Read the documents added since each check, one hypothesis after the other (their reviews are kept)."""
        ws = self.ws(name)
        s = self.settings()
        be, model = self.backend()
        emb = home.make_embedder(s)

        def run(job: Job):
            tracker = Tracker(expand=False)
            job.tracker = tracker
            self._wire(job, be, tracker)
            done = []
            for i, hid in enumerate(hyp_ids, 1):
                if job.cancel.is_set():
                    break
                tracker.step("item", f"Hypothesis {i} of {len(hyp_ids)}", {"index": i, "total": len(hyp_ids),
                                                                            "text": ws.scalar("SELECT text FROM hypotheses WHERE hyp_id=?", (hid,))})
                done.append(claimcheck.read_new_documents(ws, hid, be, model, k=int(s["k"]),
                                                          embedder=_usable_embedder(ws, emb),
                                                          progress=lambda st, m, info=None, _i=i: tracker.step(
                                                              st, m, {**(info or {}), "index": _i}),
                                                          should_stop=job.cancel.is_set))
            return {"hypotheses": done, "passages": sum(d["passages"] for d in done)}

        title = "Reading the new documents" + (f" for {len(hyp_ids)} hypotheses" if len(hyp_ids) > 1 else "")
        return self._job("read-new", title, name, run)

    def start_second_opinion(self, name: str, body: dict) -> Job:
        """A second model grades the excerpts already read, keeping only one model in memory at a time."""
        from .. import prompts
        from ..llm import OUTPUT_CAP, THINK_ALLOWANCE, estimate_tokens, fit_context

        ws = self.ws(name)
        s = self.settings()
        ids = self._hyp_ids(ws, body)
        main_be, main = self.backend()
        be, second = home.make_second_backend(s, self.api_key())
        if second == main and not getattr(be, "router", None):
            raise ApiError(400, "The model for second opinions is the same as the main model. Choose another one in Settings.")
        if str(s.get("num_ctx", "auto")).lower() == "auto" and hasattr(be, "num_ctx"):
            # just long enough for the longest set of excerpts these checks read
            system = estimate_tokens(prompts.system_prompt("second"))
            need = 0
            for hid in ids:
                for c in ws.query("SELECT claim_id FROM user_claims WHERE hyp_id=?", (hid,)):
                    for t in claimcheck._check_tasks(ws, c["claim_id"]):
                        need = max(need, system + estimate_tokens(prompts.user_prompt("second", json.loads(t["payload_json"])))
                                   + 1600 // 3)
            thinks = s.get("think") != "off"
            budget = int(getattr(be, "think_budget", 0) or 0)
            room = (2 * budget + 64 if budget else THINK_ALLOWANCE) if thinks else 0
            be.num_ctx = max(fit_context(need + OUTPUT_CAP["second"] + room), 8192)

        def run(job: Job):
            tracker = Tracker(expand=False, steps=("grade",))
            job.tracker = tracker
            self._wire(job, be, tracker)
            return claimcheck.second_opinion(ws, ids, be, main, second, progress=tracker.step,
                                             should_stop=job.cancel.is_set)

        return self._job("second-opinion", f"Second opinion from {second} on {len(ids)} "
                         f"{'hypothesis' if len(ids) == 1 else 'hypotheses'}", name, run, withdraw=("second",), ws=ws)

    def start_ingest(self, name: str, body: dict, paths: list[Path] | None = None, title: str = "Adding sources") -> Job:
        """Add documents: an upload batch, a folder or file path typed by the person, or (0.13) the files the
        bibliography has for works without a document (`paths`)."""
        ws = self.ws(name)
        inputs: list[Path] = list(paths or [])
        if body.get("batch"):
            folder = ws.root / "uploads" / re.sub(r"[^A-Za-z0-9_-]", "", str(body["batch"]))
            if not folder.is_dir():
                raise ApiError(400, "Nothing was uploaded in that batch.")
            inputs.append(folder)
        if body.get("path"):
            p = Path(str(body["path"])).expanduser()
            if not p.exists():
                raise ApiError(400, f"Nothing at {p}. Give the full path of a folder, a zip or a file on this computer.")
            inputs.append(p)
        if not inputs:
            raise ApiError(400, "Upload files or give a folder path first.")
        exclude = str(body.get("exclude") or "").split() or None
        s = self.settings()
        level = body.get("ai_access") or None  # 0.11: "Who may read these documents with AI?"
        if level is not None:
            try:
                level = access.clean(level)
            except ValueError as e:
                raise ApiError(400, str(e)) from None
            if level == "cloud" and home.local_only():
                raise ApiError(400, "Cloud models are switched off on this computer.")
        note = str(body.get("ai_note") or "").strip() or None

        def run(job: Job):
            job.progress = {"done": 0, "total": 0, "file": ""}

            def prog(i, n, fname):
                job.progress = {"done": i, "total": n, "file": fname}

            before = {r[0] for r in ws.query("SELECT doc_id FROM documents")}
            stats = ingest.ingest(ws, inputs, exclude=exclude, progress=prog, should_stop=job.cancel.is_set,
                                  ocr=ingest.OcrOptions(s.get("ocr", "auto"), s.get("ocr_lang") or "eng"),
                                  ai_access=level, ai_note=note)
            stats["documents_added"] = [d for d in document_overview(ws) if d["doc_id"] not in before]
            emb = home.make_embedder(s)
            if emb is not None and stats["added"] and not job.cancel.is_set():
                job.progress = {"done": 0, "total": 0, "file": "", "phase": "embedding"}
                try:
                    r = embed.build(ws, emb, progress=lambda d, n: job.progress.update(done=d, total=n),
                                    should_stop=job.cancel.is_set)
                    stats["semantic_index"] = r
                except BackendError as e:
                    stats["semantic_index_error"] = str(e)
            if stats["added"] and not job.cancel.is_set():
                self._after_adding(ws, job, stats, [d["doc_id"] for d in stats["documents_added"]], s)
            if stats["added"] and bibliography.has(ws):  # 0.13: which works of the bibliography the new ones are
                try:
                    bibliography.match(ws)
                    stats["bibliography"] = bibliography.new_links(ws, {d["doc_id"] for d in stats["documents_added"]})
                except Exception as e:  # noqa: BLE001 - the documents are added; the links can be made again
                    stats["bibliography_error"] = str(e)
            return stats

        return self.jobs.start("ingest", title, name, run, uses_model=False)

    # -- 0.13: the bibliography (Zotero, or an exported file) -----------------------------------------------------
    def start_bibliography(self, name: str, body: dict) -> Job:
        ws = self.ws(name)
        z, f = body.get("zotero"), body.get("file")
        if body.get("update"):
            src = ws.meta("bibliography") or {}
            if src.get("kind") != "zotero":
                raise ApiError(400, "Only a bibliography read from Zotero can be updated: for a file, add the newer "
                                    "file instead.")
            z = {"library": src.get("library"), "collection": src.get("collection"),
                 "subcollections": src.get("subcollections", True), "items": src.get("items")}

        def progress(job: Job):
            return lambda **kw: setattr(job, "progress", kw)

        if isinstance(f, dict):
            fname = str(f.get("name") or "bibliography")[:200]
            fmt, works = bibliography.parse_file(fname, str(f.get("text") or ""))
            if not works:
                raise ApiError(400, f"No works were found in {fname}.")

            def run(job: Job):
                return bibliography.save(ws, works, {"kind": "file", "name": fname, "format": fmt},
                                         progress=progress(job))
        elif isinstance(z, dict):
            library = str(z.get("library") or "user")
            collection = str(z["collection"]) if z.get("collection") else None
            if not bibliography.LIBRARY_RE.match(library) or (collection and not bibliography.KEY_RE.match(collection)):
                raise ApiError(400, "Choose a library and a collection of your Zotero.")
            items = z.get("items")  # 0.13.9: the works chosen one by one (their Zotero keys)
            if items is not None and (not isinstance(items, list) or not 0 < len(items) <= bibliography.MAX_CHOSEN
                                      or not all(isinstance(k, str) and bibliography.KEY_RE.match(k) for k in items)):
                raise ApiError(400, f"Choose between 1 and {bibliography.MAX_CHOSEN} works of your Zotero.")

            def run(job: Job):
                works, src = bibliography.pull_zotero(library, collection, bool(z.get("subcollections", True)),
                                                      progress=progress(job), should_stop=job.cancel.is_set,
                                                      items=items)
                if job.cancel.is_set():
                    return None
                libs = {x["id"]: x["name"] for x in bibliography.zotero_status().get("libraries") or []}
                src["library_name"] = libs.get(library) or ("My Library" if library == "user" else "Group library")
                return bibliography.save(ws, works, src, progress=progress(job))
        else:
            raise ApiError(400, "Choose a Zotero collection or an exported file.")
        return self.jobs.start("bibliography", "Bringing in the bibliography", name, run, uses_model=False)

    def start_bibliography_files(self, name: str, body: dict) -> Job:
        """Add the files the bibliography has (Zotero's PDFs) for works without a document: read where they are."""
        ws = self.ws(name)
        keys = body.get("item_keys")
        paths = bibliography.files_to_add(ws, [str(k) for k in keys] if isinstance(keys, list) else None)
        if not paths:
            raise ApiError(400, "There is no file to add: every work with a file in Zotero has its document already.")
        return self.start_ingest(name, {"ai_access": body.get("ai_access"), "ai_note": body.get("ai_note")}, paths,
                                 "Adding Zotero's files")

    def _after_adding(self, ws, job: Job, stats: dict, new_docs: list[str], s: dict) -> None:
        """After documents are added (0.7): the glossary (F3) is rebuilt and the codebook's keyword pass (F2) reads
        the new documents. Neither uses the chat model; a problem with either is reported, not fatal."""
        from .. import profile, terms

        emb = _usable_embedder(ws, home.make_embedder(s))
        job.progress = {"done": 0, "total": 0, "file": "", "phase": "glossary"}
        try:
            stats["glossary"] = terms.build(ws, progress=lambda d, n: job.progress.update(done=d, total=n),
                                            should_stop=job.cancel.is_set, embedder=emb)
        except BackendError as e:
            stats["glossary_error"] = str(e)
        if job.cancel.is_set():
            return
        job.progress = {"done": 0, "total": 0, "file": "", "phase": "codes"}
        fw = s.get("profile_framework") or "sdg"
        try:
            frameworks.get(fw, ws)
            stats["codes"] = profile.keyword_pass(ws, fw, emb, doc_ids=new_docs if profile.pass1_status(ws, fw)["done"]
                                                  else None, progress=lambda d, n: job.progress.update(done=d, total=n))
        except (ValueError, BackendError) as e:
            stats["codes_error"] = str(e)

    def start_index(self, name: str) -> Job:
        ws = self.ws(name)
        emb = home.make_embedder(self.settings())
        if emb is None:
            raise ApiError(400, "Choose a model for search by meaning first (Settings → Documents, where Ollama can download nomic-embed-text).")

        def run(job: Job):
            job.progress = {"done": 0, "total": 0}
            return embed.build(ws, emb, progress=lambda d, n: job.progress.update(done=d, total=n),
                               should_stop=job.cancel.is_set)

        return self.jobs.start("index", f"Semantic index with {emb.model}", name, run, uses_model=False)


    # -- 0.7: search, profiles, concepts, themes, references, highlights, quick look -----------------
    def _embedder_for(self, ws):
        s = self.settings()
        if s.get("embed_backend") == "off":
            return None
        try:
            return _usable_embedder(ws, home.make_embedder(s))
        except BackendError:
            return None

    MODEL_JOB_KINDS = {"label": ("label",), "link": ("link",), "wordings": ("expand",), "theme-names": ("theme",),
                       "resolve": ("resolve",)}  # the task kinds Stop withdraws from the queue; others: none

    def start_queued_job(self, kind: str, title: str, name: str, fn, steps=("grade",),
                         withdraw: tuple[str, ...] | None = None) -> Job:
        """A job that uses the chat model: progress as done/total, the model's own progress, Stop. By queue (0.8)
        the progress also says what waits for Claude Code, and the job is "not running" while nothing answers.

        `fn(job, backend, model, progress)` does the work; `progress(done, total)` updates the bar. Stop takes the
        tasks of the kinds in `withdraw` that wait in the queue back out (0.13.6: public; `_model_job` before)."""
        be, model = self.backend()  # one context length for every kind: Ollama never reloads the model

        def run(job: Job):
            job.progress = {"done": 0, "total": 0}
            self._wire(job, be)
            if hasattr(be, "progress"):
                be.progress = lambda info: job.progress.update(queue=info) if info.get("phase") == "queue" else \
                    job.progress.update(model=info)
            return fn(job, be, model, lambda d, n: job.progress.update(done=d, total=n))

        return self.start_job(kind, title, name, run,
                              withdraw=self.MODEL_JOB_KINDS.get(kind, ()) if withdraw is None else tuple(withdraw),
                              ws=self._ws_or_none(name))

    _model_job = start_queued_job  # the name before 0.13.6

    def _ws_or_none(self, name: str | None):
        try:
            return self.ws(name) if name else None
        except ApiError:
            return None

    # -- 0.8: the queue ----------------------------------------------------------------------------
    def queue(self, name: str) -> dict:
        from .. import claude_setup  # 0.9: Claude Code started from the app, and whether it can be

        ws = self.ws(name)
        taskqueue.advance(ws)  # checks by queue move on here too, even when Claude Code's session stored the answers
        speed = self.settings().get("claude_speed") or "normal"
        out = taskqueue.status(ws, name, parallel=taskqueue.speed_parallel(speed))
        out["route"] = self.settings().get("backend")
        out["setup"] = claude_setup_info()
        # 0.13.10: how many helpers a start runs at once (the speed beside Start Claude Code), and the limits of
        # "For this run"
        out["speed"] = {"chosen": speed, "options": dict(taskqueue.SPEEDS), "max_parallel": taskqueue.MAX_PARALLEL,
                        "max_per_helper": taskqueue.MAX_PER_HELPER,
                        "helpers": taskqueue.helper_rows(out["groups"], out["kinds"]),
                        "all_helpers": list(taskqueue.routing.HELPER_MODEL)}
        out["runner"] = claude_setup.run_state(name)
        if out["route"] == "claude_code" and not home.local_only():
            st = claude_setup.status()
            out["can_start"] = bool(st["found"])
            out["claude"] = {k: st[k] for k in ("found", "signed_in", "installed", "ready")}
        return out

    def overview(self, name: str) -> dict:
        """0.9: what has been made in a project, for the Overview page: one cheap count per feature."""
        ws = self.ws(name)

        def n(sql: str, args: tuple = ()) -> int:
            try:
                return int(ws.scalar(sql, args) or 0)
            except Exception:  # noqa: BLE001 - an older project without the table
                return 0

        fw = self.settings().get("profile_framework") or "sdg"
        runs = n("SELECT COUNT(*) FROM theme_runs")
        run = ws.query("SELECT run_id FROM theme_runs ORDER BY created_at DESC LIMIT 1") if runs else []
        out = {
            "documents": n("SELECT COUNT(*) FROM documents"),
            "passages": n("SELECT COUNT(*) FROM passages WHERE section='body'"),
            "profile": {"framework": fw, "keyword": n("SELECT COUNT(*) FROM labels WHERE framework=? AND source='keyword'", (fw,)),
                        "labels": n("SELECT COUNT(*) FROM labels WHERE framework=?", (fw,)),
                        "documents": n("SELECT COUNT(DISTINCT doc_id) FROM labels WHERE framework=?", (fw,))},
            "concepts": {"terms": n("SELECT COUNT(*) FROM terms"), "concepts": n("SELECT COUNT(*) FROM concepts")},
            "themes": {"runs": runs,
                       "themes": n("SELECT COUNT(*) FROM themes WHERE run_id=? AND removed_at IS NULL",
                                   (run[0]["run_id"],)) if run else 0,
                       "latest": run[0]["run_id"] if run else None},
            "references": n("SELECT COUNT(DISTINCT doc_id) FROM mentions"),
            "hypotheses": n("SELECT COUNT(*) FROM hypotheses"),
            "waiting": (self._queue_summary(name) or {}).get("waiting", 0),
        }
        out.update(addons.overview(ws, set(out)))  # 0.13.6: an add-on's counts, never in place of ENLENS's
        return out

    def start_stronger(self, name: str, task_id: str) -> Job:
        """"Ask a stronger model" on one answered task (a round of a check): read again once by the model it steps
        up to on this route."""
        from .. import routing

        ws = self.ws(name)
        t = ws.query("SELECT kind, status, step FROM tasks WHERE task_id=?", (task_id,))
        if not t:
            raise ApiError(404, "No such task.")
        # the route's router from the settings (0.11.1: building a backend here probed the model server once for
        # the check and once more for the job)
        s = self.settings()
        r = (routing.from_settings(s, large=s.get("ollama_model") or s.get("openai_model") or "")
             if s.get("routing", True) and s.get("backend") != "baseline" else None)
        if r is None or not r.step_up(t[0]["kind"]):
            raise ApiError(400, "There is no stronger model for this on the AI model chosen in Settings.")
        with tasks_mod.queueing(self.queue_mode()):
            tasks_mod.ask_stronger(ws, task_id)
        stronger = r.step_up(t[0]["kind"])
        job = self._model_job("stronger", f"A stronger model ({stronger}) reads it again", name,
                              lambda job, be2, model, prog: {"task_id": task_id, "counts": tasks_mod.answer_again(
                                  ws, task_id, be2), "model": stronger})
        job.scope = task_id
        return job

    def start_stronger_all(self, name: str, hyp_id: str) -> Job:
        """"Ask a stronger model" for a whole result (0.11.2): every search a model answered and no stronger model
        read yet is read again once by the model checks step up to; its judgements replace the first ones."""
        from .. import routing

        ws = self.ws(name)
        try:
            res = claimcheck.hypothesis_result(ws, hyp_id)
        except KeyError:
            raise ApiError(404, "No such hypothesis.") from None
        s = self.settings()
        r = (routing.from_settings(s, large=s.get("ollama_model") or s.get("openai_model") or "")
             if s.get("routing", True) and s.get("backend") != "baseline" else None)
        stronger = r.step_up("check") if r else None
        if not stronger:
            raise ApiError(400, "There is no stronger model for this on the AI model chosen in Settings.")
        ids = [rd["task_id"] for part in res["parts"] for rd in part.get("rounds_info", [])
               if claimcheck.stronger_eligible(rd)]
        if not ids:
            raise ApiError(400, "A stronger model has already read every search of this result.")
        with tasks_mod.queueing(self.queue_mode()):
            for tid in ids:
                tasks_mod.ask_stronger(ws, tid)

        def fn(job, be2, model, prog):
            counts = 0
            for i, tid in enumerate(ids):
                prog(i, len(ids))
                counts += bool(tasks_mod.answer_again(ws, tid, be2))
                if job.cancel.is_set():
                    break
            prog(len(ids), len(ids))
            return {"hyp_id": hyp_id, "task_ids": ids, "answered": counts, "model": stronger}

        job = self._model_job("stronger", f"A stronger model ({stronger}) reads the excerpts again", name, fn)
        job.scope = hyp_id
        return job

    def start_queue_run(self, name: str, body: dict) -> Job:
        """Answer what waits in the queue here, with the AI model of Settings (a local server or the Claude API),
        kind by kind."""
        ws = self.ws(name)
        if self.queue_mode():
            raise ApiError(400, "Settings name Claude Code: it answers the queue itself. Choose another AI model to "
                                "answer it here.")
        kinds = [k for k in (body.get("kinds") or []) if k in taskqueue.KINDS] or None
        return self._model_job("queue-run", "Answering the queue here", name, lambda job, be, model, prog:
                               taskqueue.run_here(ws, be, kinds, should_stop=job.cancel.is_set, progress=prog,
                                                  model=model))


    def start_keyword_pass(self, name: str, body: dict) -> Job:
        from .. import profile

        ws = self.ws(name)
        fw = str(body.get("framework") or self.settings().get("profile_framework") or "sdg")
        frameworks.get(fw, ws)
        emb = self._embedder_for(ws)

        def run(job: Job):
            job.progress = {"done": 0, "total": 0}
            return profile.keyword_pass(ws, fw, emb, progress=lambda d, n: job.progress.update(done=d, total=n))

        return self.jobs.start("keywords", f"Codes by keywords and meaning ({fw})", name, run, uses_model=False)

    def label_plan(self, name: str, q: dict) -> dict:
        from .. import profile, runs

        ws = self.ws(name)
        fw = _str(q, "framework") or self.settings().get("profile_framework") or "sdg"
        frameworks.get(fw, ws)
        docs = _list(q, "docs")
        plan = profile.label_plan(ws, fw, docs, _bool(q, "all"))
        plan.pop("passage_ids")
        try:
            be, model = self.backend(("label",))
            rp = runs.plan(ws, "label", fw, be, model)
        except (BackendError, ValueError) as e:
            rp = {"error": str(e), "changed": [], "seconds_per_task": None, "now": {}}
        sec = rp.get("seconds_per_task")
        return {**plan, "run": rp, "estimate_seconds": round(sec * plan["to_read"]) if sec else None}

    def start_labels(self, name: str, body: dict) -> Job:
        from .. import profile

        ws = self.ws(name)
        fw = str(body.get("framework") or self.settings().get("profile_framework") or "sdg")
        frameworks.get(fw, ws)
        docs = body.get("doc_ids") or None
        if docs is not None and not (isinstance(docs, list) and all(isinstance(d, str) for d in docs)):
            raise ApiError(400, "doc_ids must be a list of document ids.")
        if not profile.pass1_status(ws, fw)["done"]:
            raise ApiError(409, "Find the codes by keywords first (it takes seconds): the AI reads the passages they found.")
        limit = _body_int(body, "limit", None, 1, 10 ** 7)
        job = self._model_job("label", f"The AI labels passages ({fw})", name, lambda job, be, model, prog:
                               profile.run_labels(ws, fw, be, model, docs, bool(body.get("all_passages")), limit,
                                                  progress=prog, should_stop=job.cancel.is_set))
        job.scope = ",".join(docs) if docs else fw
        return job

    def start_label_compare(self, name: str, body: dict) -> Job:
        from .. import profile

        ws = self.ws(name)
        fw = str(body.get("framework") or self.settings().get("profile_framework") or "sdg")
        frameworks.get(fw, ws)  # a plain mistake is reported at once, not as a failed job (0.11.1)
        if not ws.scalar("SELECT 1 FROM labels WHERE framework=? AND source='model' LIMIT 1", (fw,)):
            raise ApiError(409, "No passage has AI labels yet in this codebook: there is nothing to compare with.")
        n = _body_int(body, "n", 50, 5, 200)

        def compare(job, be, model, prog):
            if self.queue_mode():  # 0.8.1: by queue, on a scratch copy; labels are read by the label model
                from ..routing import ALIASES

                model = body.get("model") if body.get("model") in ALIASES else (
                    be.router.model("label") if getattr(be, "router", None) else "haiku")
            return profile.compare_sample(ws, fw, be, model, n, progress=prog, should_stop=job.cancel.is_set)

        return self._model_job("label-compare", f"Labelling {n} passages again to compare", name, compare)

    def start_terms(self, name: str) -> Job:
        from .. import terms

        ws = self.ws(name)
        emb = self._embedder_for(ws)

        def run(job: Job):
            job.progress = {"done": 0, "total": 0}
            return terms.build(ws, progress=lambda d, n: job.progress.update(done=d, total=n),
                               should_stop=job.cancel.is_set, embedder=emb)

        return self.jobs.start("terms", "Building the glossary", name, run, uses_model=False)

    def start_judge_links(self, name: str, body: dict) -> Job:
        from .. import terms

        ws = self.ws(name)
        pairs = body.get("pairs")
        if pairs:
            if not (isinstance(pairs, list) and all(isinstance(p, list) and len(p) == 2 for p in pairs)):
                raise ApiError(400, "pairs must be a list of [term_id, term_id].")
            pairs = [tuple(p) for p in pairs][:200]
        else:
            pairs = terms.proposed_pairs(ws)
        if not pairs:
            raise ApiError(400, "There is no pair of terms to judge.")
        return self._model_job("link", f"The AI judges {len(pairs)} {'pair' if len(pairs) == 1 else 'pairs'} of terms",
                               name, lambda job, be, model, prog: terms.judge_links(ws, pairs, be, model, prog,
                                                                                    job.cancel.is_set))

    def start_wordings(self, name: str, term: str) -> Job:
        from .. import terms

        ws = self.ws(name)
        if not ws.scalar("SELECT 1 FROM terms WHERE term_id=?", (term,)):
            raise ApiError(404, "No such term.")
        return self._model_job("wordings", "The AI proposes other wordings", name,
                               lambda job, be, model, prog: {"suggested": terms.propose_wordings(ws, term, be, model)})

    def start_themes(self, name: str, body: dict) -> Job:
        from .. import themes

        ws = self.ws(name)
        s = self.settings()
        k = _body_int(body, "k", int(s.get("themes_k") or 20), 2, 60)
        seed = _body_int(body, "seed", 0, 0, 10 ** 9)
        mode = str(body.get("mode") or "auto")
        emb = home.make_embedder(s)
        embed_model = getattr(emb, "model", None)
        themes.choose_mode(ws, mode, embed_model)  # a plain mistake (no embeddings for "meaning") is reported at once

        def run(job: Job):
            job.progress = {"done": 0, "total": 0, "phase": "terms"}
            rid = themes.run(ws, k, seed, mode, embed_model,
                             progress=lambda phase, d, n: job.progress.update(phase=phase, done=d, total=n),
                             should_stop=job.cancel.is_set)
            return {"run_id": rid}

        return self.jobs.start("themes", f"Finding {k} themes", name, run, uses_model=False)

    def start_theme_names(self, name: str, run_id: str) -> Job:
        from .. import themes

        ws = self.ws(name)
        if not ws.scalar("SELECT 1 FROM theme_runs WHERE run_id=?", (run_id,)):
            raise ApiError(404, "No such set of themes.")
        return self._model_job("theme-names", "The AI names the themes", name,
                               lambda job, be, model, prog: themes.name_with_model(ws, run_id, be, model, prog,
                                                                                   job.cancel.is_set))

    def start_new_theme(self, name: str, run_id: str, body: dict) -> Job:
        """A new theme in place of a removed one (themes.new_theme): on this computer, no AI."""
        from .. import themes

        ws = self.ws(name)
        if not ws.scalar("SELECT 1 FROM theme_runs WHERE run_id=?", (run_id,)):
            raise ApiError(404, "No such set of themes.")
        replaces = body.get("replaces")
        if isinstance(replaces, bool) or not isinstance(replaces, int):
            raise ApiError(400, "Say which removed theme the new one takes the place of (replaces).")
        row = ws.query("SELECT removed_at, replaces FROM themes WHERE run_id=? AND theme_id=?", (run_id, replaces))
        if not row:
            raise ApiError(404, "No such theme.")
        if not row[0]["removed_at"]:
            raise ApiError(400, "A new theme is found in place of a removed one: remove this theme first.")
        if ws.scalar("SELECT 1 FROM themes WHERE run_id=? AND replaces=?", (run_id, replaces)):
            raise ApiError(400, "A new theme was found in place of this one already.")
        if any(j.kind == "theme-new" and j.project == name and j.scope == run_id and j.state in ("queued", "running")
               for j in self.jobs.all()):   # one at a time: two would take the same passages
            raise ApiError(409, "A new theme is being found for these themes already. Wait until it is ready.")

        words = {"vectors": "reading the passages", "search": "looking where a new theme fits",
                 "name": "naming it by its key terms"}

        def run(job: Job):
            job.progress = {"done": 0, "total": 0, "phase": "vectors", "message": words["vectors"]}
            tid = themes.new_theme(ws, run_id, replaces, progress=lambda phase, d, n: job.progress.update(
                phase=phase, done=d, total=n, message=words.get(phase, "")), should_stop=job.cancel.is_set)
            return {"theme_id": tid, "replaces": replaces}

        job = self.jobs.start("theme-new", "Finding a new theme", name, run, uses_model=False)
        job.scope = run_id
        return job

    def start_resolve(self, name: str, doc_id: str, body: dict) -> Job:
        from .. import references

        ws = self.ws(name)
        if not ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc_id,)):
            raise ApiError(404, "No such document.")
        who = (str(body.get("name") or "").strip() or None)
        if who and not references.windows(ws, doc_id, who):
            raise ApiError(400, f"No passage of this document mentions {who!r}.")
        title = f"Following references to {who}" if who else "Following references in a document"
        job = self._model_job("resolve", title, name, lambda job, be, model, prog: references.resolve_document(
            ws, doc_id, be, model, who, prog, job.cancel.is_set))
        job.scope = doc_id
        return job

    def start_quicklook(self, filename: str, path: Path) -> tuple[str, Job]:
        """A temporary project named after the file; its ingest job ends with the glossary and the codes."""
        import shutil

        ws = home.create_quicklook(filename, self.settings().get("project"))
        name = ws.root.name
        folder = home.upload_folder(ws, "quicklook")
        target = folder / (re.sub(r'[\x00-\x1f<>:"|?*/\\]', "_", Path(filename).name).strip(" .") or "document.pdf")
        try:
            shutil.move(str(path), str(target))  # 0.11.1: a data folder on another disk than the temp folder
        except OSError:  # no empty quick look is left behind
            home.keep_project(name)
            shutil.rmtree(ws.root, ignore_errors=True)
            raise
        home.update_settings({"project": name})
        job = self.start_ingest(name, {"batch": "quicklook"})
        job.kind = "quicklook"
        return name, job

    def start_benchmark(self, body: dict) -> Job:
        from .. import benchmark as bench
        from ..store import Workspace

        ref = str(body.get("reference") or "").strip()
        if not ref:
            raise ApiError(400, "Give the folder of a reference workspace (for example the pilot folder).")
        try:
            rws = Workspace.open(Path(ref).expanduser())
        except FileNotFoundError as e:
            raise ApiError(400, str(e)) from e
        kinds = tuple(k for k in (body.get("kinds") or ["verify_set"]) if k in ("verify_set", "extract", "split", "label")) \
            or ("verify_set",)
        n = _body_int(body, "n", 10, 1, 100)
        be, model = self.backend(kinds)
        q = self.queue_mode()
        if q:  # 0.8.1: by queue, on a scratch copy of the reference; each kind on its routed model unless one is chosen
            from ..routing import ALIASES

            model = body.get("model") if body.get("model") in ALIASES else None
        home.update_settings({"benchmark_reference": ref})

        def run(job: Job):
            tracker = Tracker(expand=False)
            job.progress = {"done": 0, "total": n * len(kinds), "task": ""}
            self._wire(job, be)
            if hasattr(be, "progress"):
                be.progress = (lambda info: job.progress.update(queue=info) if info.get("phase") == "queue" else
                               tracker.model_report(info)) if q else tracker.model_report

            def started(i, total, tid):
                if job.cancel.is_set():
                    raise Cancelled()
                job.progress = {"done": i - 1, "total": total, "task": tid, "model": tracker.state()["model"]}

            res = bench.run(rws, be, model, kinds=kinds, sample=n, progress=started)
            if res.get("models"):  # by queue: each kind's seconds under the model that answered it
                for k, m in res["models"].items():
                    home.record_benchmark(m, {k: res["kinds"][k]})
            else:
                home.record_benchmark(model, res["kinds"])
            res["verdict"] = bench.verdict(res)
            res["table"] = benchmark_table(res)
            res.pop("tasks", None)
            return res

        title = f"Test of {model}" if model else "Test of the models of each task (Claude Code)"
        return self.jobs.start("benchmark", title, None, run, uses_model=not q)


def benchmark_table(res: dict) -> list[dict]:
    """Measures as rows, task kinds as columns, in words."""
    rows = [("Tasks run", "tasks", "n"), ("Failed to answer (errors)", "errors", "n"),
            ("Usable answers on the first try", "usable", "%"), ("Valid JSON", "valid_json", "%"),
            ("Answers with a quote not in the text", "quote_problems", "%"),
            ("Same status as the reference", "same_status", "%"),
            ("Grounded or not: agreement beyond chance (κ)", "grounded_kappa", "k"),
            ("Same grade per passage", "same_passage_grade", "%"),
            ("Has a claim or not: agreement beyond chance (κ)", "claims_kappa", "k"),
            ("Code present or not: agreement beyond chance (κ)", "codes_kappa", "k"),
            ("Passages with exactly the same codes", "same_codes", "%"),
            ("Overlap of SDG targets named", "target_overlap", "%"), ("Same direction on shared targets", "same_direction", "%"),
            ("Median seconds per task", "seconds_median", "n")]
    names = {"verify_set": "Checking claims", "extract": "Extracting claims", "split": "Splitting justifications",
             "label": "Labelling with codes"}
    out = []
    for label, key, fmt in rows:
        vals = {names.get(k, k): v.get(key) for k, v in res["kinds"].items()}
        if all(v is None for v in vals.values()):
            continue
        out.append({"measure": label, **{k: ("–" if v is None else f"{v:.0%}" if fmt == "%" else f"{v:.2f}" if fmt == "k"
                                              else f"{v:g}") for k, v in vals.items()}})
    return out


def _text_with_quote(path: Path, quote: str, name: str) -> bytes | None:
    """A text file as it is, in a page that marks the quote (found as quotes are: line breaks and typography do not
    matter) with the id "quote", so a link to …#quote scrolls to it. None when the quote is not in the file."""
    import html

    from ..textutil import find_quote

    raw = path.read_bytes().decode("utf-8", errors="replace")
    hit = find_quote(raw, quote[:2000])
    if not hit:
        return None
    a, b = hit[0], hit[1]
    body = (html.escape(raw[:a]) + '<mark id="quote">' + html.escape(raw[a:b]) + "</mark>" + html.escape(raw[b:]))
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" "
            "content=\"width=device-width, initial-scale=1\"><meta name=\"color-scheme\" content=\"light dark\">"
            f"<title>{html.escape(name)}</title><style>"
            "body{margin:0;font:15px/1.55 ui-serif,Georgia,serif;background:#fbfaf6;color:#1d1d1b}"
            "header{position:sticky;top:0;padding:10px 16px;font:13px/1.4 system-ui,sans-serif;background:#efece3;"
            "border-bottom:1px solid #ddd8cc}"
            "pre{white-space:pre-wrap;word-wrap:break-word;font:inherit;margin:0;padding:16px;max-width:46rem}"
            "mark{background:#ffe08a;color:inherit;padding:1px 0;scroll-margin-top:30vh}"
            "@media (prefers-color-scheme: dark){body{background:#1b1c1a;color:#e8e6df}"
            "header{background:#262724;border-color:#3a3b37}mark{background:#7a6215}}"
            f"</style></head><body><header>{html.escape(name)} · the original file; the quote from ENLENS is "
            f"highlighted</header><pre>{body}</pre></body></html>").encode()


def _usable_embedder(ws, emb):
    """Use semantic search only when the project has vectors from this model."""
    if emb is None:
        return None
    # one row is enough (0.11.1: the full status, three counts over the embeddings, ran per check and per result page)
    return emb if ws.scalar("SELECT 1 FROM embeddings WHERE model=? LIMIT 1", (emb.model,)) else None


def _check_options(body: dict, s: dict) -> dict:
    def num(key, lo, hi):
        try:
            v = int(body.get(key) if body.get(key) is not None else s[key])
        except (TypeError, ValueError):
            raise ApiError(400, f"{key} must be a whole number.") from None
        return max(lo, min(v, hi))

    doc_ids = body.get("doc_ids") or None
    if doc_ids is not None and not (isinstance(doc_ids, list) and all(isinstance(d, str) for d in doc_ids)):
        raise ApiError(400, "doc_ids must be a list of document ids.")
    return {"k": num("k", 1, 20), "per_doc": num("per_doc", 1, 10),
            "expand": bool(body["expand"]) if "expand" in body else bool(s["expand"]),
            "decompose": bool(body["decompose"]) if "decompose" in body else bool(s["decompose"]),
            "doc_ids": doc_ids, "semantic": bool(body.get("semantic", True)),
            "second_pass": bool(body["second_pass"]) if "second_pass" in body else bool(s.get("second_pass"))}


def _list(q: dict, key: str) -> list[str] | None:
    """A list from a query parameter: repeated (?docs=a&docs=b) or comma-separated (?docs=a,b)."""
    v = q.get(key)
    if not v:
        return None
    items = [x.strip() for part in (v if isinstance(v, list) else [v]) for x in str(part).split(",") if x.strip()]
    return items or None


def _bool(q: dict, key: str) -> bool:
    return (_str(q, key) or "").lower() in ("1", "true", "yes", "on")


def _body_int(body: dict, key: str, default: int | None, lo: int, hi: int) -> int | None:
    """A whole number from a JSON body, in plain language when it is not one (0.11.1: Python's own message was
    shown). `default` when the key is absent or empty (None stays None)."""
    v = body.get(key)
    if v is None or v == "":
        return default
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise ApiError(400, f"{key} must be a whole number.") from None
    return max(lo, min(v, hi))


def _int(q: dict, key: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(_float(q, key, default))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(v, hi))


def _xlsx_with_provenance(ws, sheets: list[tuple[str, list[dict]]], task_ids=None, kinds=None) -> bytes:
    """An Excel file of these sheets with "How these results were made" at the end (models, digests, prompts, seeds)."""
    from ..runs import provenance_table

    buf = io.BytesIO()
    first_name, first_rows = sheets[0]
    claimcheck.write_xlsx(first_rows, buf, first_name,
                          extra=list(sheets[1:]) + [("How these results were made", provenance_table(ws, task_ids, kinds))])
    return buf.getvalue()


def _str(q: dict, key: str) -> str | None:
    v = q.get(key)
    return (v[0] if isinstance(v, list) else v) or None


def _float(q: dict, key: str, default: float) -> float:
    v = _str(q, key)
    try:
        return float(v) if v not in (None, "") else float(default)
    except ValueError:
        raise ApiError(400, f"{key} must be a number.") from None


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _filename(stem: str, ext: str) -> str:
    """A readable file name: the words of the stem, without characters file systems refuse."""
    clean = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', " ", stem)
    return re.sub(r"\s+", " ", clean).strip(" .")[:120] + "." + ext


def _disposition(fname: str) -> str:
    from urllib.parse import quote

    ascii_name = fname.encode("ascii", "replace").decode().replace("?", "_").replace('"', "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(fname)}"


def _installation() -> dict:
    """0.10: how this ENLENS was installed (installation.py), for Settings → Technical and the help text."""
    from .. import installation

    try:
        i = installation.info()  # one description of the installation (0.11.1: the app kept its own copy)
        return {"kind": i["kind"], "system": installation.system(), "line": i["install_line"],
                "releases": i["releases"], "updates": i["updates"]}
    except Exception:  # noqa: BLE001
        return {"kind": "pip", "system": installation.system(), "line": "", "releases": ""}


def _repair_plugin() -> None:
    """0.10: on start, when the Claude Code plugin names a Python that is not this one (ENLENS moved or was installed
    again), write it again and add it to Claude Code again, quietly, in the background."""
    try:
        from .. import claude_setup

        r = claude_setup.repair()
        if r.get("repaired"):
            print(f"The Claude Code plugin was brought up to date ({r.get('reason')}).")
        # 0.13.10: which Claude plan Claude Code is signed in with, so the recommended models follow it from the start
        if home.load_settings().get("backend") == "claude_code" and not home.local_only():
            claude_setup.status(refresh=True)
    except Exception as e:  # noqa: BLE001 - never stop the app over this
        print(f"Could not bring the Claude Code plugin up to date: {e}", file=sys.stderr)


def _csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------------------------
P = r"([^/]+)"  # one path segment
ROUTES: list[tuple[str, re.Pattern, str]] = [(m, re.compile("^" + p + "$"), h) for m, p, h in [
    ("GET", r"/api/state", "get_state"),
    ("PUT", r"/api/settings", "put_settings"),
    ("POST", r"/api/settings/key", "post_key"),
    ("DELETE", r"/api/settings/key", "delete_key"),
    ("POST", r"/api/quit", "post_quit"),
    ("POST", r"/api/restart", "post_restart"),
    ("GET", r"/api/update", "get_update"),
    ("POST", r"/api/update", "post_update"),
    ("GET", r"/api/servers", "get_servers"),
    ("POST", r"/api/servers/test", "post_test"),
    ("POST", r"/api/servers/pull", "post_pull"),
    ("GET", r"/api/projects", "get_projects"),
    ("POST", r"/api/projects", "post_project"),
    ("POST", r"/api/projects/link", "post_link"),
    ("POST", r"/api/projects/import", "post_import"),
    ("GET", rf"/api/projects/{P}", "get_project"),
    ("DELETE", rf"/api/projects/{P}", "delete_project"),
    ("GET", rf"/api/projects/{P}/documents", "get_documents"),
    ("DELETE", rf"/api/projects/{P}/documents", "delete_documents"),
    ("PUT", rf"/api/projects/{P}/documents/ai-access", "put_documents_access"),
    ("PUT", rf"/api/projects/{P}/ai-access", "put_project_access"),
    ("GET", rf"/api/projects/{P}/ai-sent\.csv", "get_ai_sent_csv"),
    ("GET", rf"/api/projects/{P}/documents/{P}/ai-sent", "get_document_sent"),
    ("POST", rf"/api/projects/{P}/hypotheses/{P}/read-local", "post_read_local"),
    ("GET", rf"/api/projects/{P}/documents/{P}", "get_document"),
    ("DELETE", rf"/api/projects/{P}/documents/{P}", "delete_document"),
    ("GET", rf"/api/projects/{P}/documents/{P}/file", "get_document_file"),
    ("POST", rf"/api/projects/{P}/uploads", "post_upload"),
    ("POST", rf"/api/projects/{P}/ingest", "post_ingest"),
    ("POST", rf"/api/projects/{P}/index", "post_index"),
    ("GET", rf"/api/projects/{P}/passages/{P}", "get_passage"),
    ("GET", rf"/api/projects/{P}/frameworks", "get_frameworks"),
    ("POST", rf"/api/projects/{P}/frameworks", "post_framework"),
    ("GET", rf"/api/projects/{P}/frameworks/{P}", "get_framework"),
    ("DELETE", rf"/api/projects/{P}/frameworks/{P}", "delete_framework"),
    ("GET", rf"/api/projects/{P}/suggest", "get_suggest"),
    ("POST", rf"/api/projects/{P}/checks", "post_check"),
    ("POST", rf"/api/projects/{P}/prepare", "post_prepare"),
    ("POST", rf"/api/projects/{P}/batches/preview", "post_batch_preview"),
    ("POST", rf"/api/projects/{P}/batches", "post_batch"),
    ("GET", rf"/api/projects/{P}/hypotheses", "get_hypotheses"),
    ("GET", rf"/api/projects/{P}/hypotheses/{P}", "get_hypothesis"),
    ("DELETE", rf"/api/projects/{P}/hypotheses/{P}", "delete_hypothesis"),
    ("PUT", rf"/api/projects/{P}/hypotheses/{P}/note", "put_note"),
    ("GET", rf"/api/projects/{P}/hypotheses/{P}/export\.(csv|json|xlsx)", "get_hypothesis_export"),
    ("POST", rf"/api/projects/{P}/claims/{P}/more", "post_more"),
    ("PUT", rf"/api/projects/{P}/claims/{P}/judgements/{P}", "put_judgement"),
    ("POST", rf"/api/projects/{P}/claims/{P}/reread/{P}", "post_reread"),
    ("GET", rf"/api/projects/{P}/export\.(csv|xlsx)", "get_export"),
    ("GET", rf"/api/projects/{P}/export\.zip", "get_project_zip"),
    ("POST", rf"/api/projects/{P}/bring-in", "post_bring_in"),
    ("GET", rf"/api/projects/{P}/together", "get_together"),
    ("GET", rf"/api/projects/{P}/map", "get_map"),
    ("GET", rf"/api/projects/{P}/calibration", "get_calibration"),
    ("POST", rf"/api/projects/{P}/hypotheses/{P}/read-new", "post_read_new_one"),
    ("POST", rf"/api/projects/{P}/read-new", "post_read_new"),
    ("POST", rf"/api/projects/{P}/second-opinion", "post_second_opinion"),
    ("GET", r"/api/jobs", "get_jobs"),
    ("GET", rf"/api/jobs/{P}", "get_job"),
    ("POST", rf"/api/jobs/{P}/cancel", "post_cancel"),
    ("POST", r"/api/benchmark", "post_benchmark"),
    # 0.7
    ("POST", r"/api/servers/repeatable", "post_repeatable"),
    ("POST", r"/api/quicklook", "post_quicklook"),
    ("POST", rf"/api/projects/{P}/keep", "post_keep"),
    ("GET", rf"/api/projects/{P}/search", "get_search"),
    ("GET", rf"/api/projects/{P}/search\.(csv|xlsx)", "get_search_export"),
    ("GET", rf"/api/projects/{P}/collocates", "get_collocates"),
    ("GET", rf"/api/projects/{P}/profile", "get_profile"),
    ("GET", rf"/api/projects/{P}/profile/plan", "get_profile_plan"),
    ("POST", rf"/api/projects/{P}/profile/keywords", "post_profile_keywords"),
    ("POST", rf"/api/projects/{P}/profile/label", "post_profile_label"),
    ("POST", rf"/api/projects/{P}/profile/compare", "post_profile_compare"),
    ("GET", rf"/api/projects/{P}/profile/calibration", "get_profile_calibration"),
    ("GET", rf"/api/projects/{P}/profile\.xlsx", "get_profile_export"),
    ("GET", rf"/api/projects/{P}/documents/{P}/profile", "get_document_profile"),
    ("POST", rf"/api/projects/{P}/labels", "post_label"),
    ("PUT", rf"/api/projects/{P}/labels/{P}", "put_label"),
    ("GET", rf"/api/projects/{P}/terms", "get_terms"),
    ("POST", rf"/api/projects/{P}/terms/build", "post_terms_build"),
    ("GET", rf"/api/projects/{P}/concepts", "get_concept_lookup"),
    ("PUT", rf"/api/projects/{P}/concepts/links", "put_concept_link"),
    ("POST", rf"/api/projects/{P}/concepts/judge", "post_concepts_judge"),
    ("GET", rf"/api/projects/{P}/concepts/{P}", "get_concept"),
    ("POST", rf"/api/projects/{P}/concepts/{P}/wordings", "post_concept_wordings"),
    ("GET", rf"/api/projects/{P}/documents/{P}/terms", "get_document_terms"),
    ("GET", rf"/api/projects/{P}/passages/{P}/terms", "get_passage_terms"),
    ("GET", rf"/api/projects/{P}/themes", "get_themes"),
    ("POST", rf"/api/projects/{P}/themes", "post_themes"),
    ("GET", rf"/api/projects/{P}/themes/{P}", "get_theme_run"),
    ("DELETE", rf"/api/projects/{P}/themes/{P}", "delete_theme_run"),
    ("GET", rf"/api/projects/{P}/themes/{P}/export\.xlsx", "get_themes_export"),
    ("PUT", rf"/api/projects/{P}/themes/{P}/edit", "put_theme_edit"),
    ("POST", rf"/api/projects/{P}/themes/{P}/name", "post_theme_names"),
    ("POST", rf"/api/projects/{P}/themes/{P}/new", "post_new_theme"),
    ("GET", rf"/api/projects/{P}/themes/{P}/{P}", "get_theme"),
    ("GET", rf"/api/projects/{P}/documents/{P}/references", "get_references"),
    ("POST", rf"/api/projects/{P}/documents/{P}/references", "post_references"),
    ("GET", rf"/api/projects/{P}/documents/{P}/annotated\.pdf", "get_annotated"),
    ("GET", rf"/api/projects/{P}/hypotheses/{P}/annotated\.zip", "get_annotated_zip"),
    ("GET", rf"/api/projects/{P}/flexiconc\.sqlite", "get_flexiconc"),
    # 0.8: the task queue (Claude Code), model routing, the plugin's set-up
    ("GET", rf"/api/projects/{P}/queue", "get_queue"),
    ("POST", rf"/api/projects/{P}/queue/order", "post_queue_order"),
    ("POST", rf"/api/projects/{P}/queue/withdraw", "post_queue_withdraw"),
    ("POST", rf"/api/projects/{P}/queue/run", "post_queue_run"),
    ("POST", rf"/api/projects/{P}/queue/claude-code", "post_claude_code_start"),
    ("POST", rf"/api/projects/{P}/queue/claude-code/stop", "post_claude_code_stop"),
    ("GET", rf"/api/projects/{P}/overview", "get_overview"),
    ("POST", rf"/api/projects/{P}/tasks/{P}/stronger", "post_stronger"),
    ("POST", rf"/api/projects/{P}/hypotheses/{P}/stronger", "post_stronger_all"),
    ("GET", r"/api/routing", "get_routing"),
    ("GET", r"/api/claude-setup", "get_claude_setup"),
    ("POST", r"/api/claude-setup", "post_claude_setup"),
    # 0.10: set-up and moving
    ("POST", r"/api/claude-setup/claude-code", "post_install_claude_code"),
    ("POST", r"/api/claude-setup/sign-in", "post_claude_sign_in"),
    ("GET", r"/api/move\.zip", "get_move_zip"),
    # 0.13: the bibliography (Zotero, read on this computer, or an exported file)
    ("GET", r"/api/zotero", "get_zotero"),
    ("GET", r"/api/zotero/collections", "get_zotero_collections"),
    ("GET", r"/api/zotero/works", "get_zotero_works"),
    ("GET", rf"/api/projects/{P}/bibliography", "get_bibliography"),
    ("POST", rf"/api/projects/{P}/bibliography", "post_bibliography"),
    ("DELETE", rf"/api/projects/{P}/bibliography", "delete_bibliography"),
    ("PUT", rf"/api/projects/{P}/bibliography/links", "put_bibliography_link"),
    ("POST", rf"/api/projects/{P}/bibliography/confirm-all", "post_bibliography_confirm_all"),
    ("POST", rf"/api/projects/{P}/bibliography/files", "post_bibliography_files"),
    ("GET", rf"/api/projects/{P}/bibliography/to-find\.(csv|xlsx)", "get_bibliography_export"),
]]
DOWNLOADS = {"get_hypothesis_export", "get_export", "get_document_file", "get_project_zip", "get_annotated", "get_flexiconc",
             "get_annotated_zip", "get_search_export", "get_profile_export", "get_themes_export", "get_move_zip",
             "get_ai_sent_csv", "get_bibliography_export"}
# (these may take the token as ?token=, for plain links)


class Handler(BaseHTTPRequestHandler):
    app: App
    server_version = f"enlens/{__version__}"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet: the terminal shows only problems
        pass

    # -- plumbing --------------------------------------------------------------------------------
    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _stream(self, path: Path, ctype: str, extra: dict | None = None, chunk: int = 1 << 16) -> None:
        """Send a file in chunks (never held in memory as a whole)."""
        size = path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as f:
            while True:
                data = f.read(chunk)
                if not data:
                    break
                self.wfile.write(data)

    def _json(self, status: int, obj: Any) -> None:
        extra = None
        if status >= 400:  # the request body may be unread: do not reuse this connection
            self.close_connection = True
            extra = {"Connection": "close"}
        self._send(status, json.dumps(obj, ensure_ascii=False, default=str).encode(), "application/json; charset=utf-8",
                   extra)

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        if host in self.app.allowed_hosts:
            return True
        if self.app.any_host:  # reachable from the network: an IP address of this computer, never a domain name
            name = host.rsplit(":", 1)[0].strip("[]") if host.count(":") <= 1 or host.startswith("[") else host
            try:
                import ipaddress

                ipaddress.ip_address(name)
                return host.endswith(f":{self.app.port}")
            except ValueError:
                return False  # a domain name could be a DNS-rebinding page
        return False

    def _body(self) -> dict:
        self._consumed = True
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_JSON:
            raise ApiError(413, "The request is too large.")
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            raise ApiError(400, "The request body is not valid JSON.") from None
        if not isinstance(obj, dict):
            raise ApiError(400, "The request body must be a JSON object.")
        return obj

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _drain(self) -> None:
        """Read a request body no handler used, so it cannot be taken for the next request on this connection."""
        if getattr(self, "_consumed", True):
            return
        self._consumed = True
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_JSON:
            self.close_connection = True
        elif n:
            self.rfile.read(n)

    def _dispatch(self, method: str) -> None:
        url = urlparse(self.path)
        path = url.path
        q = parse_qs(url.query)
        self._consumed = False
        try:
            self._route(method, path, q)
        finally:
            try:
                self._drain()
            except OSError:
                self.close_connection = True

    def _route(self, method: str, path: str, q: dict) -> None:
        try:
            if not self._host_ok():
                raise ApiError(403, "This app answers only to requests for this computer (127.0.0.1 / localhost).")
            if not path.startswith("/api/"):
                if method != "GET":
                    raise ApiError(405, "Method not allowed.")
                return self._static(path)
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).netloc.lower() != (self.headers.get("Host") or "").lower():
                raise ApiError(403, "Requests from other web sites are not accepted.")
            routes = ROUTES + addons.routes()  # 0.13.6: an add-on's routes come after ENLENS's own
            downloads = DOWNLOADS | addons.downloads()
            for m, rx, name in routes:
                mt = rx.match(path)
                if mt and m == method:
                    hname = addons.handler_name(name)
                    token = self.headers.get("X-Enlens-Token") or (_str(q, "token") if hname in downloads else None)
                    if not token or not secrets.compare_digest(token, self.app.token):
                        raise ApiError(401, "Missing or wrong token. Reload the page.")
                    args = [unquote(g) for g in mt.groups()]
                    out = getattr(self, name)(*args, q=q) if isinstance(name, str) else name(self, *args, q=q)
                    if out is not None:
                        self._json(200, out)
                    return
            if any(rx.match(path) for _m, rx, _n in routes):
                raise ApiError(405, "Method not allowed.")
            raise ApiError(404, "No such API endpoint.")
        except ApiError as e:
            self._json(e.status, {"error": e.message, "kind": e.kind, **e.extra})
        except BackendError as e:
            self._json(502, {"error": str(e), "kind": "backend"})
        except KeyError as e:
            self._json(404, {"error": f"Not found: {e.args[0] if e.args else e}", "kind": "request"})
        except (ValueError, FileNotFoundError) as e:
            self._json(400, {"error": str(e), "kind": "request"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # pragma: no cover - a bug: report it without stopping the server
            traceback.print_exc()
            try:
                self._json(500, {"error": f"Unexpected problem: {e}", "kind": "internal"})
            except Exception:
                pass

    def _static(self, path: str) -> None:
        if path in ("/", "/index.html") or not Path(path).suffix:
            page = (STATIC / "index.html").read_text(encoding="utf-8")
            # on the network the page does not carry the token: it comes in the link printed in the terminal (#token=)
            page = page.replace("{{ENLENS_TOKEN}}", "" if self.app.any_host else self.app.token)
            page = page.replace("{{ENLENS_VERSION}}", __version__)
            csp = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
                   "connect-src 'self'; font-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            return self._send(200, page.encode(), "text/html; charset=utf-8", {"Content-Security-Policy": csp})
        rel = path.lstrip("/")
        if rel.startswith("static/"):
            rel = rel[len("static/"):]
        if rel == "site.css":  # 0.13.5: the installation's own look, then each add-on's
            return self._send(200, addons.site_css(), "text/css; charset=utf-8")
        if rel.startswith("addons/"):  # 0.13.5: an add-on package's page files
            target = addons.static_file(rel[len("addons/"):])
            if target is None:
                raise ApiError(404, "Not found.")
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "image/svg+xml"):
                ctype += "; charset=utf-8"
            return self._send(200, target.read_bytes(), ctype)
        target = (STATIC / rel).resolve()
        if not target.is_relative_to(STATIC.resolve()) or not target.is_file():
            raise ApiError(404, "Not found.")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "image/svg+xml"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    # -- endpoints -------------------------------------------------------------------------------
    def get_state(self, q):
        return self.app.state()

    def put_settings(self, q):
        body = self._body()
        s = home.update_settings(body)
        return {"settings": s, "backend_label": home.backend_label(s)}

    def post_key(self, q):
        if home.local_only():  # 0.11.1: the one cloud setting that did not honour it
            raise ApiError(403, "Cloud models are switched off on this computer by whoever installed ENLENS: a Claude "
                                "API key cannot be used here.")
        body = self._body()
        key = str(body.get("key") or "").strip()
        if not key:
            raise ApiError(400, "Give the API key.")
        self.app.session_key = key
        if body.get("remember"):
            home.remember_key(key)
        return {"key": {"session": True, "env": bool(home.env_key()), "stored": bool(home.stored_key())}}

    def delete_key(self, q):
        self.app.session_key = ""
        home.forget_key()
        return {"key": {"session": False, "env": bool(home.env_key()), "stored": False}}

    def post_quit(self, q):
        """Stop the app ("Quit ENLENS"). Running jobs stop with it; a stopped check leaves nothing behind."""
        self._body()
        if self.app.stop is None:
            raise ApiError(409, "This app was not started in a way that can be stopped from here.")
        return {"stopping": True, "jobs_stopped": self._stop_jobs_then(self.app.stop)}

    def _stop_jobs_then(self, finish) -> int:
        """Stop the running jobs, then call `finish` (stop or restart the app) once this answer has gone out and the
        stopped jobs have cleaned up (at most 20 s). Returns how many jobs were stopped."""
        running = [j for j in self.app.jobs.all() if j.state in ("queued", "running")]
        for j in running:
            j.cancel.set()

        def later():
            t0 = time.time()
            time.sleep(0.4)
            while any(j.state in ("queued", "running") for j in running) and time.time() - t0 < 20:
                time.sleep(0.2)
            finish()

        threading.Thread(target=later, daemon=True).start()
        return len(running)

    def post_restart(self, q):
        """0.13.1: stop the app and start the version on disk in its place, on the same port (the page reloads)."""
        self._body()
        if self.app.restart is None:
            raise ApiError(409, "This app was not started in a way that can restart itself. Stop it and start it again.")
        return {"restarting": True, "jobs_stopped": self._stop_jobs_then(self.app.restart)}

    def get_update(self, q):
        """0.13.1: whether a newer ENLENS waits: the latest GitHub release (the one-line install), or new commits on
        the branch a git copy follows. A newer version already on disk (updated while this copy ran) counts.
        0.13.6: the page asks every two minutes; the answer (or the reason there is none) is kept for
        UPDATE_LOOK_EVERY seconds, so the open tabs share one look. `?fresh=1` (Settings → Check for updates) looks
        again now."""
        from .. import update as upd

        installed = _installed_version()
        if upd.version_tuple(installed) > upd.version_tuple(__version__):
            return {"available": True, "on_disk": True, "version": __version__, "latest": installed}
        with self.app.update_looking:
            seen = self.app.update_seen
            if _bool(q, "fresh") or not seen or time.time() - seen["at"] >= UPDATE_LOOK_EVERY:
                try:
                    r = upd.update(check_only=True, quick=True)
                    waiting = r.get("waiting")
                    seen = {"at": time.time(), "answer": {
                        "available": bool(waiting), "on_disk": False, "version": __version__,
                        "latest": waiting if isinstance(waiting, str) else None,
                        "changes": waiting if isinstance(waiting, int) else None}}
                except upd.UpdateError as e:
                    seen = {"at": time.time(), "error": str(e)}
                self.app.update_seen = seen
        if "error" in seen:
            raise ApiError(409, seen["error"])
        return dict(seen["answer"])

    def post_update(self, q):
        """0.13.1, "Update and restart": install the newest ENLENS the way this one was installed (update.py), then
        restart into it. Nothing restarts when ENLENS is up to date or the update fails."""
        from .. import update as upd

        self._body()
        if self.app.restart is None:
            raise ApiError(409, "This app was not started in a way that can restart itself. Run `enlens update` in a "
                                "terminal, then start ENLENS again.")
        if not self.app.updating.acquire(blocking=False):
            raise ApiError(409, "ENLENS is already being updated.")
        self.app.update_seen = None  # 0.13.6: whatever happens, the next GET /api/update looks again
        restarting = False
        try:
            installed = _installed_version()
            if upd.version_tuple(installed) > upd.version_tuple(__version__):  # on disk already: a restart is all
                r = {"updated": True, "from": __version__, "version": installed}
            else:
                try:
                    r = upd.update()
                except upd.UpdateError as e:
                    raise ApiError(409, str(e)) from e
            if not r.get("updated"):
                return {"updated": False, "restarting": False, "version": __version__}
            stopped = self._stop_jobs_then(self.app.restart)
            restarting = True
            return {"updated": True, "restarting": True, "from": r.get("from", __version__), "version": r["version"],
                    "jobs_stopped": stopped}
        finally:
            if not restarting:  # kept while restarting: a second click must not update again
                self.app.updating.release()

    def get_servers(self, q):
        return self.app.servers()

    def post_test(self, q):
        return self.app.test_backend()

    def post_pull(self, q):
        """0.13.7: download models into the Ollama running on this computer (a job). Body: {"models": [names]}
        (or {"model": name}), optionally {"url": the Ollama's address, as GET /api/servers lists it} and {"use":
        "ai" | "restricted" | "embed"}: what to choose them for when the download is done."""
        body = self._body()
        use = str(body.get("use") or "")
        if use and use not in App.PULL_USES:
            raise ApiError(400, "use must be ai, restricted or embed.")
        models = body.get("models") if body.get("models") is not None else [body.get("model")]
        if (not isinstance(models, list) or not 1 <= len(models) <= 4
                or not all(isinstance(m, str) and llm.valid_model_name(m.strip()) for m in models)):
            raise ApiError(400, "Name the model to download, as Ollama's library writes it (for example qwen3:8b).")
        models = list(dict.fromkeys(m.strip() for m in models))
        url = str(body.get("url") or "").rstrip("/")
        s = self.app.settings()
        found = [x for x in detect_local(ollama_url=s.get("ollama_url"), cache_seconds=0) if x["kind"] == "ollama"]
        srv = next((x for x in found if not url or x["url"].rstrip("/") == url), None)
        if srv is None:  # only an Ollama that answers on this computer (or at the address in Settings) is asked
            raise ApiError(409, "No Ollama is running on this computer just now. Open the Ollama app (ollama.com) "
                                "and try again.")
        return {"job": self.app.pull_models(models, srv["url"], use).view()}

    def get_projects(self, q):
        return {"projects": [self.app.project_summary(n) for n in home.list_projects()]}

    def post_project(self, q):
        body = self._body()
        ws = home.create_project(str(body.get("name") or ""))
        home.update_settings({"project": ws.root.name})
        return {"project": self.app.project_summary(ws.root.name)}

    def post_link(self, q):
        body = self._body()
        name = home.link_existing(str(body.get("path") or ""), body.get("name") or None)
        home.update_settings({"project": name})
        return {"project": self.app.project_summary(name)}

    def get_project(self, name, q):
        return self.app.project(name)

    def delete_project(self, name, q):
        body = self._body()
        if body.get("confirm") != name:
            raise ApiError(400, "Confirm by sending the project's name as 'confirm'.")
        if name not in home.list_projects():
            raise ApiError(404, f"No project called {name!r}.")
        return {"result": home.remove_project(name)}

    def get_documents(self, name, q):
        return self.app.documents(name)

    # -- 0.11: per-document AI settings and the ledger of what Claude has read --------------------------------
    def put_documents_access(self, name, q):
        body = self._body()
        ws = self.app.ws(name)
        ids = body.get("doc_ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(x, str) for x in ids):
            raise ApiError(400, "doc_ids must be a list of document ids.")
        kw = {}
        if "ai_access" in body:
            kw["setting"] = body.get("ai_access") or None
        if "note" in body:
            kw["note"] = body.get("note")
        if "budget" in body:
            kw["budget"] = body.get("budget")
        if not kw:
            raise ApiError(400, "Give ai_access, note or budget.")
        r = access.set_documents(ws, ids, **kw)
        return {**r, **self.app.documents(name)}

    def put_project_access(self, name, q):
        body = self._body()
        ws = self.app.ws(name)
        if body.get("default"):
            access.set_default(ws, body["default"])
        if body.get("dismiss_banner"):
            access.dismiss_banner(ws)
        return {"ai_access": access.project_info(ws)}

    def get_document_sent(self, name, doc_id, q):
        ws = self.app.ws(name)
        if not ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc_id,)):
            raise ApiError(404, "No such document.")
        return access.document_ledger(ws, doc_id)

    def get_ai_sent_csv(self, name, q):
        rows = [{"Sent at": r["sent_at"], "Route": r["route"], "Feature": r["feature"], "Document": r["title"],
                 "Document id": r["doc_id"], "Passage id": r["passage_id"], "Page": r["page"] if r["page"] else "",
                 "Task": r["task_id"]} for r in access.ledger(self.app.ws(name))]
        if not rows:
            rows = [{"Sent at": "", "Route": "", "Feature": "", "Document": "Nothing has been sent to Claude from this "
                     "project.", "Document id": "", "Passage id": "", "Page": "", "Task": ""}]
        stem = _filename(f"ENLENS sent to Claude - {name} - {time.strftime('%Y-%m-%d')}", "csv")
        return self._send(200, _csv(rows), "text/csv; charset=utf-8", {"Content-Disposition": _disposition(stem)})

    def post_read_local(self, name, hyp_id, q):
        body = self._body()
        return {"job": self.app.start_read_local(name, hyp_id, force=bool(body.get("force"))).view()}

    def delete_documents(self, name, q):
        body = self._body()
        if body.get("confirm") is not True:
            raise ApiError(400, "Confirm with {\"confirm\": true}: this removes every document and every check.")
        ws = self.app.ws(name)
        pipeline = {"extracted claims": ws.scalar("SELECT COUNT(*) FROM claims"),
                    "VCA verifications": ws.scalar("SELECT COUNT(*) FROM verifications WHERE subject_kind != 'user_claim'"),
                    "pipeline tasks": ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind IN ('extract','verify','verify_set')")}
        held = ", ".join(f"{n:,} {what}" for what, n in pipeline.items() if n)
        if held:
            raise ApiError(409, f"This project also holds results of the SDG pipeline ({held}); removing all documents "
                                f"would delete them too. Remove documents one by one, or run `enlens --ws \"{ws.root}\" "
                                "reset-corpus --yes` if that is what you want.")
        return {"removed": ws.reset_corpus()}

    def get_document(self, name, doc_id, q):
        return self.app.document(name, doc_id, int(_float(q, "offset", 0)), int(_float(q, "limit", 50)),
                                 _str(q, "view") or "")

    def get_document_file(self, name, doc_id, q):
        """The original file of a document, for reading it as it looks (a PDF opens at #page=N in the browser)."""
        ws = self.app.ws(name)
        info = self.app.original(ws, doc_id)
        if _str(q, "check"):
            return {k: info[k] for k in ("doc_id", "kind", "name", "available", "reason")}
        if not info["available"]:  # say so plainly, and show the text the app read
            text = ws.scalar("SELECT text FROM documents WHERE doc_id=?", (doc_id,)) or ""
            body = f"{info['reason']}\n\n{info['title'] or ''}\n\n{text}".encode()
            return self._send(200, body, "text/plain; charset=utf-8",
                              {"Content-Security-Policy": "default-src 'none'; sandbox"})
        path = Path(info["path"])
        ext = path.suffix.lower()
        disp = _disposition(info["name"] or path.name).replace("attachment;", "inline;", 1)
        if ext == ".pdf":
            return self._stream(path, "application/pdf", {"Content-Disposition": disp})
        if ext == ".docx":  # 0.8: a Word file opens in Word (or whatever the computer opens it with)
            return self._stream(path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                {"Content-Disposition": disp.replace("inline;", "attachment;", 1)})
        if ext in (".html", ".htm"):  # no scripts, no internet, and a unique origin that cannot reach this app
            csp = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:"
            return self._stream(path, "text/html; charset=utf-8", {"Content-Security-Policy": csp,
                                                                     "Content-Disposition": disp})
        quote = _str(q, "quote")
        if quote and path.stat().st_size <= 20 * 1024 ** 2:  # a text file, with the quote marked: link to …#quote
            page = _text_with_quote(path, quote, info["name"] or path.name)
            if page is not None:
                return self._send(200, page, "text/html; charset=utf-8", {
                    "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'"})
        return self._stream(path, "text/plain; charset=utf-8", {"Content-Security-Policy": "default-src 'none'; sandbox",
                                                                "Content-Disposition": disp})

    def delete_document(self, name, doc_id, q):
        return {"removed": self.app.ws(name).remove_document(doc_id)}

    def _body_size(self) -> int:
        """The size of a raw upload, refused above MAX_UPLOAD (the connection is closed: the body is not read)."""
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_UPLOAD:
            self.close_connection = True
            raise ApiError(413, "Files larger than 2 GB are not accepted.")
        return n

    def _save_body(self, target: Path, n: int, allow_empty: bool = False) -> None:
        """Stream the raw request body of `n` bytes into `target` (one copy of this for the three uploads, 0.11.1)."""
        self._consumed = True
        left = n
        with open(target, "wb") as f:
            while left > 0:
                chunk = self.rfile.read(min(left, 1 << 20))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if left or (not n and not allow_empty):
            target.unlink(missing_ok=True)
            raise ApiError(400, "The upload was cut off.")

    def post_upload(self, name, q):
        ws = self.app.ws(name)
        raw = _str(q, "name") or unquote(self.headers.get("X-Filename") or "") or "upload"  # each decoded once
        fname = re.split(r"[/\\]", raw)[-1]
        fname = re.sub(r'[\x00-\x1f<>:"|?*]', "_", fname).strip(" .") or "upload"
        if fname.startswith("."):
            fname = "_" + fname
        n = self._body_size()
        folder = home.upload_folder(ws, _str(q, "batch"))
        target = folder / fname
        if not target.resolve().is_relative_to(folder.resolve()):
            raise ApiError(400, "That file name is not accepted.")
        self._save_body(target, n, allow_empty=True)
        return {"batch": folder.name, "name": fname, "size": n}

    def post_ingest(self, name, q):
        return {"job": self.app.start_ingest(name, self._body()).view()}

    # -- 0.13: the bibliography ------------------------------------------------------------------
    def get_zotero(self, q):
        return bibliography.zotero_status()

    def get_zotero_collections(self, q):
        try:
            return {"collections": bibliography.zotero_collections(_str(q, "library") or "user")}
        except bibliography.ZoteroError as e:
            raise ApiError(409, str(e), f"zotero_{e.kind}") from None

    def get_zotero_works(self, q):
        """0.13.9: the works of a library or collection, to choose from one by one."""
        try:
            return bibliography.zotero_works(_str(q, "library") or "user", _str(q, "collection"), _str(q, "q") or "",
                                             _int(q, "limit", 100, 1, 200))
        except bibliography.ZoteroError as e:
            raise ApiError(409, str(e), f"zotero_{e.kind}") from None

    @staticmethod
    def _bib(ws) -> dict:
        """The page's view of the bibliography, with the project's AI choice (for adding Zotero's files)."""
        return {**bibliography.view(ws), "ai_access": access.project_info(ws)}

    def get_bibliography(self, name, q):
        return self._bib(self.app.ws(name))

    def post_bibliography(self, name, q):
        return {"job": self.app.start_bibliography(name, self._body()).view()}

    def delete_bibliography(self, name, q):
        self._body()
        ws = self.app.ws(name)
        return {**bibliography.remove(ws), **self._bib(ws)}

    def put_bibliography_link(self, name, q):
        body = self._body()
        ws = self.app.ws(name)
        bibliography.decide(ws, str(body.get("item_key") or ""), str(body.get("doc_id") or ""),
                            str(body.get("decision") or ""))
        return self._bib(ws)

    def post_bibliography_confirm_all(self, name, q):
        self._body()
        ws = self.app.ws(name)
        n = bibliography.confirm_all(ws)
        return {"confirmed": n, **self._bib(ws)}

    def post_bibliography_files(self, name, q):
        return {"job": self.app.start_bibliography_files(name, self._body()).view()}

    def get_bibliography_export(self, name, fmt, q):
        ws = self.app.ws(name)
        rows = bibliography.to_find_rows(ws) or [{"Title": "Every work of the bibliography has its document.",
                                                 "Authors": "", "Year": "", "Type": "", "Published in": "", "DOI": "",
                                                 "DOI link": "", "Web address": "", "Open in Zotero": "",
                                                 "File in Zotero": ""}]
        stem = _filename(f"ENLENS works to find - {name} - {time.strftime('%Y-%m-%d')}", fmt)
        if fmt == "xlsx":
            buf = io.BytesIO()
            claimcheck.write_xlsx(rows, buf, "Works to find")
            return self._send(200, buf.getvalue(), XLSX, {"Content-Disposition": _disposition(stem)})
        return self._send(200, _csv(rows), "text/csv; charset=utf-8", {"Content-Disposition": _disposition(stem)})

    def post_index(self, name, q):
        return {"job": self.app.start_index(name).view()}

    def get_passage(self, name, passage_id, q):
        around = max(0, min(int(_float(q, "around", 1)), 5))
        return claimcheck.neighbours(self.app.ws(name), passage_id, around, around)

    def get_frameworks(self, name, q):
        return {"frameworks": [fw.info() for fw in frameworks.available(self.app.ws(name)).values()]}

    def post_framework(self, name, q):
        body = self._body()
        fw = frameworks.save(self.app.ws(name), str(body.get("name") or ""), str(body.get("csv") or ""),
                             body.get("title") or None, body.get("label") or None, bool(body.get("directional")))
        return {"framework": fw.info()}

    def get_framework(self, name, fw_name, q):
        fw = frameworks.get(fw_name, self.app.ws(name))
        return {"framework": fw.info(with_codes=True)}

    def delete_framework(self, name, fw_name, q):
        if fw_name in frameworks.BUNDLED:
            raise ApiError(400, "The SDG codebooks ship with the app and cannot be removed.")
        frameworks.delete(self.app.ws(name), fw_name)
        return {"deleted": fw_name}

    def get_suggest(self, name, q):
        text = _str(q, "text") or ""
        fw = _str(q, "framework") or "sdg"
        if len(text.strip()) < 10:
            return {"codes": []}
        return {"codes": claimcheck.suggest_targets(text, int(_float(q, "n", 5)), framework=fw, ws=self.app.ws(name))}

    def post_check(self, name, q):
        return {"job": self.app.start_check(name, self._body()).view()}

    def post_prepare(self, name, q):
        return {"job": self.app.start_prepare(name, self._body()).view()}

    def post_reread(self, name, claim_id, passage_id, q):
        return {"job": self.app.start_reread(name, claim_id, passage_id, self._body()).view()}

    def post_batch_preview(self, name, q):
        items = claimcheck.parse_batch(str(self._body().get("text") or ""))
        return {"items": items, "count": len(items)}

    def post_batch(self, name, q):
        return {"job": self.app.start_batch(name, self._body()).view()}

    def get_hypotheses(self, name, q):
        return self.app.hypotheses(name, q)

    def get_hypothesis(self, name, hyp_id, q):
        ws = self.app.ws(name)
        s = self.app.settings()
        res = claimcheck.hypothesis_result(ws, hyp_id, _float(q, "threshold", s["threshold"]))
        try:  # with smart search every excerpt not read yet can still be found; without it only keyword matches
            semantic = _usable_embedder(ws, home.make_embedder(s)) is not None
        except BackendError:
            semantic = False
        for part in res["parts"]:  # can "look for more evidence" still find anything?
            try:
                part["more_available"] = claimcheck.more_available(ws, part["claim_id"], semantic=semantic)
            except Exception:
                part["more_available"] = True
        from .. import routing  # 0.8: "Ask a stronger model": the model a check steps up to on the route of Settings

        res["stronger_model"] = (routing.from_settings(s, large=s.get("ollama_model") or s.get("openai_model") or "")
                                 .step_up("check") if s.get("routing", True) and s.get("backend") != "baseline" else None)
        res["queue_command"] = f"/enlens-run {taskqueue._quote_name(name)}"
        # 0.14: a sync-clash copy says whose version it is; the original lists the colleagues' versions of it
        copies = sync.copies_of(ws, "check")
        res["clash"] = copies.get(hyp_id)
        if res["clash"]:
            res["clash"]["of_text"] = ws.scalar("SELECT text FROM hypotheses WHERE hyp_id=?", (res["clash"]["of"],))
        res["clash_copies"] = [{"hyp_id": k, **v} for k, v in copies.items() if v["of"] == hyp_id]
        return res

    def delete_hypothesis(self, name, hyp_id, q):
        ws = self.app.ws(name)
        if not ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (hyp_id,)):
            raise ApiError(404, "No such hypothesis.")
        claimcheck.delete_hypothesis(ws, hyp_id)
        return {"deleted": hyp_id}

    def put_note(self, name, hyp_id, q):
        claimcheck.set_note(self.app.ws(name), hyp_id, str(self._body().get("note") or ""))
        return {"saved": True}

    def get_hypothesis_export(self, name, hyp_id, fmt, q):
        ws = self.app.ws(name)
        thr = _float(q, "threshold", self.app.settings()["threshold"])
        res = claimcheck.hypothesis_result(ws, hyp_id, thr)
        if fmt == "xlsx":
            from ..runs import hypothesis_task_ids, provenance_table

            buf = io.BytesIO()
            cache = claimcheck.ResultCache(ws, thr)
            cache._results[hyp_id] = res
            claimcheck.write_xlsx(claimcheck.export_table(ws, thr, [hyp_id], every_excerpt=True, cache=cache), buf,
                                  "Excerpts", summary=claimcheck.summary_table(ws, thr, [hyp_id], cache=cache),
                                  extra=[("How these results were made",
                                          provenance_table(ws, hypothesis_task_ids(ws, [hyp_id])))])
            fname = _filename(f"ENLENS - {res['text'][:60]}", "xlsx")
            return self._send(200, buf.getvalue(), XLSX, {"Content-Disposition": _disposition(fname)})
        if fmt == "json":
            body, ctype = json.dumps(res, indent=2, ensure_ascii=False).encode(), "application/json; charset=utf-8"
        else:
            body, ctype = _csv(claimcheck.hypothesis_rows(res)), "text/csv; charset=utf-8"
        self._send(200, body, ctype, {"Content-Disposition": f'attachment; filename="hypothesis_{hyp_id}.{fmt}"'})

    def post_more(self, name, claim_id, q):
        return {"job": self.app.start_more(name, claim_id, self._body()).view()}

    def get_export(self, name, fmt, q):
        ws = self.app.ws(name)
        thr = _float(q, "threshold", self.app.settings()["threshold"])
        if fmt == "xlsx":
            from ..runs import provenance_table
            from ..terms import key_terms_table

            buf = io.BytesIO()
            cache = claimcheck.ResultCache(ws, thr)  # the history and every result once, for all the sheets
            claimcheck.write_xlsx(claimcheck.export_table(ws, thr, cache=cache), buf, "Excerpts",
                                  summary=claimcheck.summary_table(ws, thr, cache=cache),
                                  extra=[("Map", claimcheck.map_table(claimcheck.evidence_map(ws, thr, cache=cache))),
                                         ("Key terms per document", key_terms_table(ws)),
                                         ("How these results were made",
                                          provenance_table(ws, kinds=("check", "reread", "second", "expand",
                                                                      "decompose")))])
            fname = _filename(f"ENLENS results - {name} - {time.strftime('%Y-%m-%d')}", "xlsx")
            return self._send(200, buf.getvalue(), XLSX, {"Content-Disposition": _disposition(fname)})
        rows = claimcheck.export_rows(ws, thr)
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", name)
        self._send(200, _csv(rows), "text/csv; charset=utf-8",
                   {"Content-Disposition": f'attachment; filename="checks_{safe}.csv"'})

    def get_project_zip(self, name, q):
        """The whole project as one zip (see bundle.py), built in a temporary file and sent in chunks."""
        import tempfile

        from .. import bundle

        ws = self.app.ws(name)
        tmp = Path(tempfile.mkdtemp(prefix="enlens-zip-"))
        try:
            out = tmp / "project.zip"
            bundle.export_project(ws, out)
            fname = _filename(f"ENLENS project - {name} - {time.strftime('%Y-%m-%d')}", "zip")
            self._stream(out, "application/zip", {"Content-Disposition": _disposition(fname)})
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    def post_bring_in(self, name, q):
        """0.14: a colleague's project zip (raw body) merged into this copy of the project (sync.py). 409 with
        `not_this_project` when the file is not known to be this project; `?anyway=1` brings it in all the same."""
        import tempfile

        from .. import sync

        ws = self.app.ws(name)
        n = self._body_size()
        with tempfile.TemporaryDirectory(prefix="enlens-bring-in-") as tmp:
            path = Path(tmp) / "in.zip"
            self._save_body(path, n)
            try:
                report = sync.bring_in(ws, path, anyway=_str(q, "anyway") in ("1", "true", "yes"))
            except sync.NotThisProject as e:
                raise ApiError(409, str(e), extra={"not_this_project": e.info}) from e
            except ValueError as e:
                raise ApiError(400, str(e)) from e
        return {"report": report, "project": self.app.project_summary(name)}

    def get_together(self, name, q):
        """0.14: who works on this project, the work brought in, the open sync clashes and how often you agreed."""
        from .. import people, sync

        out = sync.overview(self.app.ws(name))
        out["me"] = {"id": people.me(), "name": people.my_name()}
        return out

    def post_import(self, q):
        """A project zip (raw body) becomes a new project: `?name=` or the name it had."""
        import tempfile
        import zipfile

        from .. import bundle

        n = self._body_size()
        with tempfile.TemporaryDirectory(prefix="enlens-import-") as tmp:
            path = Path(tmp) / "in.zip"
            self._save_body(path, n)
            if bundle.is_move_zip(path):  # 0.10: everything from another computer
                try:
                    moved = bundle.import_all(path)
                except ValueError as e:
                    raise ApiError(400, str(e)) from e
                return {"moved": moved, "project": self.app.project_summary(moved["current"]) if moved["current"] else None}
            wanted = _str(q, "name")
            if not wanted:
                try:
                    with zipfile.ZipFile(path) as zf:
                        wanted = json.loads(zf.read("bundle.json")).get("name")
                except (KeyError, ValueError, zipfile.BadZipFile, OSError):
                    wanted = None
                name = home.unique_project_name(wanted or "Imported project")
            else:
                name = home.safe_name(wanted)
                if not name:
                    raise ApiError(400, "Give the project a name (letters, digits, spaces, dots, dashes).")
                if name in home.list_projects() or (home.home() / "projects" / name).exists():
                    raise ApiError(409, f"A project called {name!r} already exists. Choose another name.")
            bundle.import_project(path, home.home() / "projects" / name)
        home.update_settings({"project": name})
        return {"project": self.app.project_summary(name)}

    def get_map(self, name, q):
        ws = self.app.ws(name)
        thr = _float(q, "threshold", self.app.settings()["threshold"])
        return claimcheck.evidence_map(ws, thr, batch_id=_str(q, "batch"))

    def get_calibration(self, name, q):
        out = claimcheck.calibration(self.app.ws(name))
        out["threshold"] = self.app.settings()["threshold"]
        return out

    def post_read_new_one(self, name, hyp_id, q):
        ws = self.app.ws(name)
        if not ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (hyp_id,)):
            raise ApiError(404, "No such hypothesis.")
        return {"job": self.app.start_read_new(name, [hyp_id]).view()}

    def post_read_new(self, name, q):
        ws = self.app.ws(name)
        body = self._body()
        ids = self.app._hyp_ids(ws, body) if (body.get("hyp_ids") is not None or body.get("batch")) else \
            [h["hyp_id"] for h in claimcheck.history(ws) if h["docs_added_since"]]
        if not ids:
            raise ApiError(400, "No hypothesis has documents added since its check.")
        return {"job": self.app.start_read_new(name, ids).view()}

    def post_second_opinion(self, name, q):
        return {"job": self.app.start_second_opinion(name, self._body()).view()}

    # -- 0.7 ------------------------------------------------------------------------------------
    def post_repeatable(self, q):
        from ..llm import repeatable

        self._body()
        be, model = self.app.backend()
        return {"model": model, **repeatable(be, model)}

    def post_quicklook(self, q):
        """One document (raw body, ?name=file name) becomes a temporary project; returns the project and its job."""
        import tempfile

        raw = _str(q, "name") or unquote(self.headers.get("X-Filename") or "") or "document.pdf"
        fname = re.split(r"[/\\]", raw)[-1] or "document.pdf"
        if not re.search(r"\.(pdf|docx|html?|txt|md)$", fname, re.I):
            raise ApiError(400, "A quick look reads one PDF, Word (.docx), web page (HTML), text or Markdown file.")
        n = self._body_size()
        with tempfile.TemporaryDirectory(prefix="enlens-quick-") as tmp:
            path = Path(tmp) / "upload"
            self._save_body(path, n)
            name, job = self.app.start_quicklook(fname, path)
        return {"project": self.app.project_summary(name), "job": job.view()}

    def post_keep(self, name, q):
        self._body()
        self.app.ws(name)
        return {"kept": home.keep_project(name), "project": self.app.project_summary(name)}

    # search (F1)
    def _search_args(self, q) -> dict:
        return {"mode": _str(q, "mode") or "any", "docs": _list(q, "docs"), "exact": _bool(q, "exact"),
                "near": _int(q, "near", 5, 1, 50), "all_sections": _bool(q, "all"), "code": _str(q, "code")}

    def get_search(self, name, q):
        from .. import concordance

        ws = self.app.ws(name)
        text = _str(q, "q") or ""
        if (_str(q, "mode") or "") == "meaning":
            emb = self.app._embedder_for(ws)
            if emb is None:
                raise ApiError(400, "Search by meaning is not set up for this project (Settings → Advanced).")
            return concordance.meaning(ws, text, emb, k=_int(q, "limit", 20, 1, 100), docs=_list(q, "docs"))
        return concordance.search(ws, text, sort=_str(q, "sort") or "doc", offset=_int(q, "offset", 0, 0, 10 ** 7),
                                  limit=_int(q, "limit", 200, 1, 1000), width=_int(q, "width", 60, 20, 300),
                                  **self._search_args(q))

    def get_search_export(self, name, fmt, q):
        from .. import concordance

        ws = self.app.ws(name)
        text = _str(q, "q") or ""
        res = concordance.search(ws, text, sort=_str(q, "sort") or "doc", offset=0, limit=None, **self._search_args(q))
        rows = concordance.table(res)
        stem = _filename(f"ENLENS search - {text[:40]}", fmt)
        if fmt == "xlsx":
            col = concordance.collocates(ws, text, **{k: v for k, v in self._search_args(q).items()})
            body = _xlsx_with_provenance(ws, [("Lines", rows), ("Per document", [
                {"Document": d["title"], "Hits": d["hits"], "Passages": d["passages"]} for d in res["per_doc"]]),
                ("Words around it", [{"Word": w["word"], "Near the hits": w["count"], "In the corpus": w["corpus"],
                                      "PMI": w["pmi"]} for w in col["words"]])], task_ids=[])
            return self._send(200, body, XLSX, {"Content-Disposition": _disposition(stem)})
        return self._send(200, _csv(rows), "text/csv; charset=utf-8", {"Content-Disposition": _disposition(stem)})

    def get_collocates(self, name, q):
        from .. import concordance

        order = _str(q, "order") or "typical"
        if order not in ("typical", "often"):
            raise ApiError(400, "order must be typical or often.")
        return concordance.collocates(self.app.ws(name), _str(q, "q") or "", window=_int(q, "window", 5, 1, 15),
                                      order=order, **self._search_args(q))

    # profiles (F2)
    def _fw(self, ws, q) -> str:
        fw = _str(q, "framework") or self.app.settings().get("profile_framework") or "sdg"
        frameworks.get(fw, ws)
        return fw

    def get_profile(self, name, q):
        from .. import profile

        ws = self.app.ws(name)
        fw = self._fw(ws, q)
        level = _str(q, "level") or "code"
        if level not in ("code", "group"):
            raise ApiError(400, "level must be code or group.")
        out = {"framework": fw, "pass1": profile.pass1_status(ws, fw), "frameworks": [f.info() for f in
                                                                                      frameworks.available(ws).values()]}
        if out["pass1"]["done"]:
            out["grid"] = profile.grid(ws, fw, _list(q, "docs"), level)
            out["stats"] = profile.stats(ws, fw)
            out["read_by_model"] = int(ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind='label' AND status='done' AND "
                                                 "substr(task_id, 1, ?) = ?", (len(f"label:{fw}:"), f"label:{fw}:")) or 0)
        return out

    def get_profile_plan(self, name, q):
        return self.app.label_plan(name, q)

    def post_profile_keywords(self, name, q):
        return {"job": self.app.start_keyword_pass(name, self._body()).view()}

    def post_profile_label(self, name, q):
        return {"job": self.app.start_labels(name, self._body()).view()}

    def post_profile_compare(self, name, q):
        return {"job": self.app.start_label_compare(name, self._body()).view()}

    def get_profile_calibration(self, name, q):
        from .. import profile

        ws = self.app.ws(name)
        return profile.calibration(ws, _str(q, "framework"))

    def get_profile_export(self, name, q):
        from .. import profile
        from ..terms import key_terms_table

        ws = self.app.ws(name)
        fw = self._fw(ws, q)
        level = _str(q, "level") or "code"
        g = profile.grid(ws, fw, _list(q, "docs"), level if level in ("code", "group") else "code")
        sheets = [("Documents by code", profile.grid_table(g)), ("Labels", profile.labels_table(ws, fw, _list(q, "docs"))),
                  ("Key terms per document", key_terms_table(ws))]
        body = _xlsx_with_provenance(ws, sheets, kinds=("label",))
        fname = _filename(f"ENLENS profile - {name} - {fw} - {time.strftime('%Y-%m-%d')}", "xlsx")
        return self._send(200, body, XLSX, {"Content-Disposition": _disposition(fname)})

    def get_document_profile(self, name, doc_id, q):
        from .. import profile

        ws = self.app.ws(name)
        return profile.doc_profile(ws, self._fw(ws, q), doc_id)

    def post_label(self, name, q):
        from .. import profile

        body = self._body()
        ws = self.app.ws(name)
        lid = profile.add_label(ws, str(body.get("framework") or "sdg"), str(body.get("passage_id") or ""),
                                str(body.get("code") or ""), body.get("quote") or None,
                                str(body.get("relevance") or "main"), str(body.get("direction") or "not_stated"),
                                body.get("note"))
        return {"label_id": lid}

    def put_label(self, name, label_id, q):
        from .. import profile

        body = self._body()
        profile.set_label(self.app.ws(name), label_id, str(body.get("decision") or ""), body.get("relevance") or None,
                          body.get("direction") or None, body.get("note"))
        return {"saved": True}

    # concepts (F3) and key terms (F6)
    def get_terms(self, name, q):
        from .. import terms

        return terms.glossary(self.app.ws(name), _str(q, "q"), _int(q, "offset", 0, 0, 10 ** 7),
                              _int(q, "limit", 100, 1, 500), _str(q, "sort") or "docs")

    def post_terms_build(self, name, q):
        self._body()
        return {"job": self.app.start_terms(name).view()}

    def get_concept_lookup(self, name, q):
        from .. import terms

        ws = self.app.ws(name)
        text = _str(q, "name") or ""
        tid = terms.find_term(ws, text) if text.strip() else None
        if not tid:
            raise ApiError(404, f"No term of the glossary matches {text!r}.")
        return {"term_id": tid}

    def get_concept(self, name, term, q):
        from .. import terms

        return terms.card(self.app.ws(name), term, _int(q, "offset", 0, 0, 10 ** 7), _int(q, "limit", 50, 1, 500),
                          with_references=_bool(q, "refs"))

    def put_concept_link(self, name, q):
        from .. import terms

        body = self._body()
        terms.set_link(self.app.ws(name), str(body.get("a") or ""), str(body.get("b") or ""),
                       str(body.get("decision") or ""), body.get("relation") or None, note=body.get("note"))
        return {"saved": True}

    def post_concepts_judge(self, name, q):
        return {"job": self.app.start_judge_links(name, self._body()).view()}

    def post_concept_wordings(self, name, term, q):
        self._body()
        return {"job": self.app.start_wordings(name, term).view()}

    def get_document_terms(self, name, doc_id, q):
        from .. import terms

        ws = self.app.ws(name)
        return {**terms.key_term_spans(ws, doc_id, _int(q, "n", 15, 1, 50)), "status": terms.status(ws)}

    def get_passage_terms(self, name, passage_id, q):
        from .. import terms

        ws = self.app.ws(name)
        if not ws.scalar("SELECT 1 FROM passages WHERE passage_id=?", (passage_id,)):
            raise ApiError(404, "No such passage.")
        return {"terms": terms.key_terms(ws, passage_id=passage_id, n=_int(q, "n", 5, 1, 20))}

    # themes (F4)
    def get_themes(self, name, q):
        from .. import themes

        ws = self.app.ws(name)
        s = self.app.settings()
        emb = home.make_embedder(s)
        try:
            mode, why = themes.choose_mode(ws, "auto", getattr(emb, "model", None))
        except ValueError as e:
            mode, why = "words", str(e)
        runs = themes.runs(ws)
        clash = sync.copies_of(ws, "themes")  # 0.14: a colleague's version of a run you both changed
        for r in runs:
            r["clash"] = clash.get(r["run_id"])
        return {"runs": runs, "auto_mode": mode, "auto_why": why, "k": s.get("themes_k") or 20}

    def post_themes(self, name, q):
        return {"job": self.app.start_themes(name, self._body()).view()}

    def get_theme_run(self, name, run_id, q):
        from .. import themes

        ws = self.app.ws(name)
        fw = _str(q, "framework")
        if fw:
            frameworks.get(fw, ws)
        return themes.view(ws, run_id, fw)

    def delete_theme_run(self, name, run_id, q):
        from .. import themes

        themes.delete_run(self.app.ws(name), run_id)
        return {"deleted": run_id}

    def get_themes_export(self, name, run_id, q):
        from .. import themes

        ws = self.app.ws(name)
        fw = _str(q, "framework")
        sheets = themes.tables(ws, run_id, fw)
        body = _xlsx_with_provenance(ws, sheets, task_ids=[r[0] for r in ws.query(
            "SELECT task_id FROM tasks WHERE kind='theme' AND substr(task_id, 1, ?) = ?", (len(f"theme:{run_id}:"),
                                                                                         f"theme:{run_id}:"))])
        fname = _filename(f"ENLENS themes - {name} - {time.strftime('%Y-%m-%d')}", "xlsx")
        return self._send(200, body, XLSX, {"Content-Disposition": _disposition(fname)})

    def put_theme_edit(self, name, run_id, q):
        from .. import themes

        body = self._body()
        tid = body.get("theme_id")
        themes.edit(self.app.ws(name), run_id, str(body.get("what") or ""), int(tid) if tid is not None else None,
                    body.get("value"), body.get("passage_id") or None)
        return {"saved": True}

    def post_theme_names(self, name, run_id, q):
        self._body()
        return {"job": self.app.start_theme_names(name, run_id).view()}

    def post_new_theme(self, name, run_id, q):
        return {"job": self.app.start_new_theme(name, run_id, self._body()).view()}

    def get_theme(self, name, run_id, theme_id, q):
        from .. import themes

        try:
            tid = int(theme_id)
        except ValueError:
            raise ApiError(404, "No such theme.") from None
        return themes.theme_passages(self.app.ws(name), run_id, tid, _int(q, "offset", 0, 0, 10 ** 7),
                                     _int(q, "limit", 50, 1, 200))

    # references (F5)
    def get_references(self, name, doc_id, q):
        from .. import references

        ws = self.app.ws(name)
        if not ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (doc_id,)):
            raise ApiError(404, "No such document.")
        if _str(q, "start") is not None:
            ch = references.chain_at(ws, doc_id, _int(q, "start", 0, 0, 10 ** 9), _int(q, "end", 0, 0, 10 ** 9))
            return {"chain": ch}
        return {"chains": references.chains(ws, doc_id), "status": references.status(ws, doc_id)}

    def post_references(self, name, doc_id, q):
        return {"job": self.app.start_resolve(name, doc_id, self._body()).view()}

    # highlighted copies (F7)
    def _layers(self, q) -> tuple[str, ...]:
        from ..annotate import LAYERS

        got = tuple(_list(q, "layers") or ["judgements"])
        bad = [x for x in got if x not in LAYERS]
        if bad:
            raise ApiError(400, f"Unknown layer {bad[0]!r}: use {', '.join(LAYERS)}.")
        return got

    def get_annotated(self, name, doc_id, q):
        from .. import annotate

        ws = self.app.ws(name)
        hyp = _list(q, "hyp")
        r = annotate.annotate_document(ws, doc_id, hyp, self._layers(q), _str(q, "framework") or
                                       self.app.settings().get("profile_framework") or "sdg", _str(q, "concept"),
                                       threshold=_float(q, "threshold", self.app.settings()["threshold"]))
        disp = _disposition(r["name"])
        extra = {"Content-Disposition": disp, "X-Enlens-Placed": f"{r['placed']}/{r['marks']}"}
        if r["content_type"].startswith("text/html"):
            extra["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'"
        return self._send(200, r["body"], r["content_type"], extra)

    def get_flexiconc(self, name, q):
        """The project in the FlexiConc layout of the Cross-Doc SDG Explorer (one SQLite file)."""
        import tempfile

        from .. import flexiconc_export

        ws = self.app.ws(name)
        with tempfile.TemporaryDirectory(prefix="enlens-fc-") as tmp:
            out = Path(tmp) / "flexiconc.sqlite"
            emb = self.app.settings().get("embed_model") if self.app.settings().get("embed_backend") != "off" else None
            flexiconc_export.export(ws, out, framework=_str(q, "framework") or self.app.settings().get("profile_framework")
                                    or "sdg", embed_model=emb or None, embeddings=bool(emb))
            # streamed from the file (0.11.1): with embeddings the export of a large project is hundreds of MB
            self._stream(out, "application/vnd.sqlite3",
                         {"Content-Disposition": _disposition(_filename(f"{name} - FlexiConc", "sqlite"))})

    def get_annotated_zip(self, name, hyp_id, q):
        from .. import annotate

        ws = self.app.ws(name)
        body, summary = annotate.annotate_hypothesis_zip(ws, hyp_id, self._layers(q),
                                                         threshold=_float(q, "threshold", self.app.settings()["threshold"]))
        text = ws.scalar("SELECT text FROM hypotheses WHERE hyp_id=?", (hyp_id,)) or hyp_id
        fname = _filename(f"ENLENS highlighted - {text[:60]}", "zip")
        return self._send(200, body, "application/zip", {"Content-Disposition": _disposition(fname),
                                                         "X-Enlens-Placed": f"{summary['placed']}/{summary['marks']}"})

    def put_judgement(self, name, claim_id, passage_id, q):
        body = self._body()
        verdict = body.get("verdict") or None
        extra = {"quote": body.get("quote")} if "quote" in body else {}
        claimcheck.set_judgement(self.app.ws(name), claim_id, passage_id, verdict, body.get("note"), **extra)
        return {"saved": True, "verdict": verdict}

    def get_jobs(self, q):
        return {"jobs": self.app.job_views()}

    def get_job(self, job_id, q):
        return self.app.jobs.get(job_id).view()

    def post_cancel(self, job_id, q):
        job = self.app.jobs.get(job_id)
        job.cancel.set()
        return {"job": job.view(full=False)}

    def post_benchmark(self, q):
        return {"job": self.app.start_benchmark(self._body()).view()}

    # -- 0.8 ------------------------------------------------------------------------------------
    def get_queue(self, name, q):
        return self.app.queue(name)

    def post_queue_order(self, name, q):
        body = self._body()
        return taskqueue.set_order(self.app.ws(name), str(body.get("kind") or ""), str(body.get("action") or ""))

    def post_queue_withdraw(self, name, q):
        body = self._body()
        kind = str(body.get("kind") or "")
        if kind not in taskqueue.KINDS:
            raise ApiError(400, "Say which kind of task to take out of the queue.")
        ws = self.app.ws(name)
        removed = 0
        if kind in ("decompose", "expand", "check"):
            # a check waiting for Claude Code is taken back whole, as a stopped check (it leaves nothing behind);
            # 0.13.11: not one Claude Code has finished, whose local excerpts wait for "Read them now"
            for (hid,) in ws.query("SELECT hyp_id FROM hypotheses WHERE queue='waiting'"):
                if claimcheck.only_local_waits(ws, hid):
                    continue
                claimcheck.delete_hypothesis(ws, hid)
                removed += 1
        n = taskqueue.withdraw(ws, [kind])
        return {"withdrawn": n, "checks_removed": removed}

    def post_queue_run(self, name, q):
        return {"job": self.app.start_queue_run(name, self._body()).view()}

    def post_stronger_all(self, name, hyp_id, q):
        self._body()
        return {"job": self.app.start_stronger_all(name, hyp_id).view()}

    def post_stronger(self, name, task_id, q):
        self._body()
        return {"job": self.app.start_stronger(name, task_id).view()}

    def get_routing(self, q):
        from .. import routing

        s = self.app.settings()
        route = routing.route_of(s.get("backend", "auto"))
        large = ""
        if route == "local":
            large = s.get("ollama_model") or s.get("openai_model") or ""
        r = routing.from_settings(s, route=route, large=large or "the main model")
        detected = s.get("claude_plan_detected") or ""
        return {"route": route, "route_name": routing.ROUTE_NAMES.get(route, route), "rows": r.table(),
                "aliases": list(routing.ALIASES), "fable": bool(s.get("use_fable")),
                "local_small_model": s.get("local_small_model") or "", "second_model": s.get("second_model") or "",
                "step_up_below": routing.STEP_UP_BELOW, "routing": bool(s.get("routing", True)),
                # 0.13.10: the plan the recommendations follow on Claude Code
                "plan": {"tier": r.tier, "chosen": s.get("claude_plan") or "auto", "detected": detected,
                         "titles": dict(routing.TIER_TITLES)}}

    def get_claude_setup(self, q):
        from .. import claude_setup

        out = claude_setup_info()
        if not home.local_only():
            # 0.10: the query's values are lists: 0.9 compared "['1']" and never read the status again
            out["status"] = claude_setup.status(refresh=(_str(q, "refresh") or "") in ("1", "true"))
        return out

    def post_claude_setup(self, q):
        """0.9: one button: prepare the plugin and add it to Claude Code (when Claude Code is on this computer)."""
        from .. import claude_setup

        body = self._body()
        if home.local_only():
            raise ApiError(403, "Cloud models are switched off on this computer: the Claude Code plugin is not available.")
        if body.get("write_only"):
            claude_setup.write_plugin()
            return {**claude_setup_info(), "problems": claude_setup.check_files()}
        r = claude_setup.install(check=bool(body.get("check")))
        return {**claude_setup_info(), **r, "problems": [x["text"] for x in r["steps"][:1] if not x["ok"]]}

    def get_overview(self, name, q):
        return self.app.overview(name)

    def post_claude_code_start(self, name, q):
        from .. import claude_setup

        body = self._body()
        self.app.ws(name)  # 404 for a project that does not exist
        if self.app.settings().get("backend") != "claude_code":
            raise ApiError(400, "Choose Claude Code as the AI in Settings first.")
        try:
            # 0.13.10: "For this run": the helpers named one by one ({helper: how many at once}); else the speed of
            # Settings (claude_speed) says how many helpers at once
            return claude_setup.start_run(name, parallel=body.get("parallel"), helpers=body.get("helpers"))
        except ValueError as e:
            raise ApiError(400, str(e)) from e

    def post_claude_code_stop(self, name, q):
        from .. import claude_setup

        self._body()
        before = claude_setup.run_state(name)
        out = claude_setup.stop_run(name)
        if before.get("running") and before.get("started_at"):
            # the batches it had taken go back to the queue at once instead of after 30 minutes
            ws = self.app.ws(name)
            for c in ws.query("SELECT claim_id, claimed_at FROM task_claims WHERE finished_at IS NULL"):
                if str(c["claimed_at"] or "") >= before["started_at"]:
                    try:
                        taskqueue.release(ws, c["claim_id"])
                    except Exception:  # noqa: BLE001
                        pass
        return out

    # -- 0.10 ------------------------------------------------------------------------------------
    def post_install_claude_code(self, q):
        """Install Claude Code with Anthropic's installer, after the person confirmed the command shown (a job)."""
        from .. import claude_setup

        self._body()
        if home.local_only():
            raise ApiError(403, "Cloud models are switched off on this computer: Claude Code is not available.")
        if claude_setup.find_claude():
            raise ApiError(409, "Claude Code is already on this computer.")
        running = [j for j in self.app.jobs.all() if j.kind == "claude-install" and j.state in ("queued", "running")]
        if running:
            return {"job": running[0].view()}

        def run(job: Job):
            r = claude_setup.install_claude_code()
            if not r["ok"]:
                raise ValueError("Claude Code could not be installed. " + (r["text"][-600:] or ""))
            return r

        return {"job": self.app.jobs.start("claude-install", "Installing Claude Code", None, run, uses_model=False).view()}

    def post_claude_sign_in(self, q):
        """Open a terminal window running `claude`, for the one-time sign-in (ENLENS never sees the login)."""
        from .. import claude_setup

        self._body()
        try:
            return claude_setup.open_sign_in()
        except ValueError as e:
            raise ApiError(400, str(e)) from e

    def get_move_zip(self, q):
        """Every project and the settings in one zip, for another computer (never a saved cloud key)."""
        import shutil
        import tempfile

        from .. import bundle

        tmp = Path(tempfile.mkdtemp(prefix="enlens-move-"))
        try:
            out = tmp / "everything.zip"
            bundle.export_all(out)
            fname = _filename(f"ENLENS - all projects and settings - {time.strftime('%Y-%m-%d')}", "zip")
            self._stream(out, "application/zip", {"Content-Disposition": _disposition(fname)})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# 0.13.6: how long a look for a newer version is kept (the page asks every 120 s; a little less, so each ask looks)
UPDATE_LOOK_EVERY = 100


def _installed_version() -> str:
    """0.10.2: the version now on disk. It differs from the running __version__ when ENLENS was updated (git pull,
    the install line, enlens update) while this copy kept running; the page then says to quit and reopen."""
    try:
        text = (Path(__file__).resolve().parent.parent / "__init__.py").read_text(encoding="utf-8")
    except OSError:
        return __version__
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
    return m.group(1) if m else __version__


def _repair_icons() -> None:
    """0.10.2: an ENLENS icon made without a picture (before 0.10.2, when Pillow was missing) gets the shipped one."""
    try:
        from . import launcher as _l

        for p in _l.repair_icons():
            print(f"Gave the ENLENS icon its picture: {p}")
    except Exception as e:  # noqa: BLE001 - never in the way of starting
        print(f"Could not repair the ENLENS icon: {e}", file=sys.stderr)


def make_server(host: str = "127.0.0.1", port: int = 8765, app: App | None = None) -> tuple[ThreadingHTTPServer, App]:
    """The server (not started) and its app. Port 0 picks a free port."""
    app = app or App()
    handler = type("BoundHandler", (Handler,), {"app": app})
    srv = ThreadingHTTPServer((host, port), handler)
    srv.daemon_threads = True
    real = srv.server_address[1]
    app.port = real
    app.allowed_hosts = {f"127.0.0.1:{real}", f"localhost:{real}", f"[::1]:{real}"}
    app.any_host = host not in ("127.0.0.1", "localhost", "::1")
    if app.any_host:
        import socket

        app.allowed_hosts |= {f"{h.lower()}:{real}" for h in (host, socket.gethostname()) if h and h not in ("0.0.0.0", "::")}
    return srv, app


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True, launcher: bool = False) -> int:
    """Run the app until Ctrl+C or "Quit ENLENS" (`POST /api/quit`). `launcher`: started from the ENLENS icon
    (see launcher.py): the address is recorded so a second double-click opens this one."""
    for attempt in range(10):
        try:
            srv, app = make_server(host, port + attempt if port else 0)
            break
        except OSError:
            continue
    else:
        print(f"Ports {port} to {port + 9} are all in use. Choose another with --port.", file=sys.stderr)
        return 1
    app.launcher = launcher
    app.stop = lambda: threading.Thread(target=srv.shutdown, daemon=True).start()
    again = threading.Event()

    def restart():  # 0.13.1: stop, then start the version on disk in this one's place (after serve_forever)
        again.set()
        app.stop()

    app.restart = restart
    url = f"http://{'127.0.0.1' if host in ('127.0.0.1', '0.0.0.0', '::') else host}:{srv.server_address[1]}/"
    if launcher and host == "127.0.0.1":
        from . import launcher as _l

        _l.write_info(url, srv.server_address[1])
    if app.any_host:
        url += f"#token={app.token}"  # the page does not hand out the token on the network: open this link
    print(f"ENLENS hypothesis checker {__version__} at {url}  (data folder: {home.home()})")
    if app.any_host:
        print("Warning: listening beyond this computer. Open the link above (it carries the access token); anyone "
              "with that link and access to this address can use the app and read your projects.", file=sys.stderr)
    print("Stop it with Quit ENLENS in the app." if launcher else "Stop it with Ctrl+C (or Quit ENLENS in the app).")
    threading.Thread(target=_repair_plugin, daemon=True, name="plugin-repair").start()
    threading.Thread(target=_repair_icons, daemon=True, name="icon-repair").start()
    if open_browser:
        import webbrowser

        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        srv.server_close()
        if launcher:
            from . import launcher as _l

            _l.clear_info()
    if again.is_set():
        _restart(restart_command(host, app.port, launcher))
    print("ENLENS stopped.")
    return 0


def restart_command(host: str, port: int, launcher: bool) -> list[str]:
    """0.13.1: how the app starts again after "Update and restart": the same Python (the update installed into it),
    address and port, no new browser tab (the open page reloads itself), and as the icon started it if it did."""
    cmd = [sys.executable, "-m", "enlens_claims.gui.launch", "--host", host, "--port", str(port), "--headless"]
    if launcher:
        cmd += ["--launcher", "--no-start-ollama"]  # Ollama, if it was needed, is running already
    return cmd


def _restart(cmd: list[str]) -> None:
    """Start the new version. On macOS and Linux this process becomes it (os.execv: same process, same terminal,
    same Ctrl+C); Windows has no real exec, so there the new one is started beside this one, which then ends. The
    data folder and local-only setting carry over in the environment (ENLENS_HOME, ENLENS_LOCAL_ONLY)."""
    print("Restarting ENLENS with the version now installed…", flush=True)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except (OSError, ValueError):
        pass
    try:
        if os.name == "nt":
            import subprocess

            subprocess.Popen(cmd, close_fds=True)
            return
        os.execv(cmd[0], cmd)
    except OSError as e:
        print(f"Could not start ENLENS again ({e}). Open it again from its icon or with enlens-gui.", file=sys.stderr)
