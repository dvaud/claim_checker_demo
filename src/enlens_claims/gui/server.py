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

from .. import __version__, claimcheck, embed, frameworks, home, ingest, taskqueue
from .. import tasks as tasks_mod
from ..llm import BackendError, detect_local
from ..claude_setup import setup_info as claude_setup_info
from ..store import now as _now
from ..sources import document_overview
from .progress import Tracker

STATIC = Path(__file__).with_name("static")
MAX_UPLOAD = 2 * 1024 ** 3   # bytes per file
MAX_JSON = 20 * 1024 ** 2    # bytes per JSON body (a batch of hypotheses, a codebook)


class ApiError(Exception):
    def __init__(self, status: int, message: str, kind: str = "request"):
        super().__init__(message)
        self.status, self.message, self.kind = status, message, kind


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

    def _job(self, kind: str, title: str, name: str | None, fn, uses_model: bool = True,
             withdraw: tuple[str, ...] = (), ws=None) -> Job:
        """A job; by queue (Claude Code) its tasks wait in the queue and it does not hold the model's turn. Stopping
        it takes its tasks that no session has taken yet back out of the queue (`withdraw`: their kinds)."""
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
        return {"version": __version__, "home": str(home.home()), "settings": s,
                "backend_label": home.backend_label(s), "backend_labels": home.BACKEND_LABELS,
                "projects": projects, "project": current, "local_only": home.local_only(),
                "launcher": self.launcher, "can_quit": self.stop is not None,
                "context": home.context_plan(s),
                "ocr": ingest.ocr_status(),
                "key": {"session": bool(self.session_key), "env": bool(home.env_key()), "stored": bool(home.stored_key())},
                "statuses": [{"status": k, "text": v, "help": claimcheck.STATUS_HELP.get(k, ""),
                              "next": claimcheck.STATUS_NEXT.get(k, "")} for k, v in claimcheck.STATUS_TEXT.items()],
                "jobs": [j.view(full=False) for j in self.jobs.all() if j.state in ("queued", "running")],
                "queue": self._queue_summary(current)}

    def _queue_summary(self, name: str | None) -> dict | None:
        """What waits in the current project's queue, for the sidebar (0.8)."""
        if not name:
            return None
        try:
            ws = home.open_project(name)
            n = ws.scalar("SELECT COUNT(*) FROM tasks WHERE COALESCE(queued, 0)=1 AND (status IN ('pending', 'retry') "
                          "OR (status='done' AND again=1))") or 0
        except Exception:  # noqa: BLE001
            return None
        return {"waiting": int(n)}

    def servers(self) -> dict:
        s = self.settings()
        found = detect_local(ollama_url=s.get("ollama_url"), extra=[s.get("openai_url") or ""], cache_seconds=3)
        for srv in found:
            srv["chat_models"] = [m for m in srv["models"] if not re.search(r"embed|bge-|e5-|minilm|rerank", m, re.I)]
            srv["embedding_models"] = [m for m in srv["models"] if re.search(r"embed|bge-|e5-|minilm", m, re.I)]
        return {"servers": found}

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
                              else f"Ollama is running, but {model} is not installed. Run: ollama pull {model}")
        elif out["backend"] == "local":
            out["message"] = (f"The server at {info.get('url')} answers and offers {model}." if out["model_available"]
                              else f"The server answers, but does not list {model}.")
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
        out["search"] = embed.status(ws, s.get("embed_model") if s.get("embed_backend") != "off" else None)
        out["frameworks"] = [fw.info() for fw in frameworks.available(ws).values()]
        return out

    def documents(self, name: str) -> dict:
        ws = self.ws(name)
        s = self.settings()
        return {"documents": document_overview(ws),
                "search": embed.status(ws, s.get("embed_model") if s.get("embed_backend") != "off" else None)}

    def document(self, name: str, doc_id: str, offset: int, limit: int, view: str = "") -> dict:
        ws = self.ws(name)
        d = ws.query("SELECT doc_id, title, path, kind, n_pages, n_chars, doi, added_at FROM documents WHERE doc_id=?",
                     (doc_id,))
        if not d:
            raise ApiError(404, "No such document.")
        out = dict(d[0])
        out["file"] = re.sub(r".*[/\\]", "", out.pop("path") or "")
        out["total_passages"] = int(ws.scalar("SELECT COUNT(*) FROM passages WHERE doc_id=?", (doc_id,)) or 0)
        out["passages"] = [dict(r) for r in ws.query(
            "SELECT passage_id, seq, page, section, start, end, text FROM passages WHERE doc_id=? ORDER BY seq LIMIT ? OFFSET ?",
            (doc_id, max(1, min(limit, 200)), max(0, offset)))]
        out["offset"] = offset
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
        rows = claimcheck.history(ws, thr, query=_str(q, "q"), status=_str(q, "status"), batch_id=_str(q, "batch"))
        counts: dict[str, int] = {}
        for r in claimcheck.history(ws, thr) if (_str(q, "q") or _str(q, "status") or _str(q, "batch")) else rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        limit = int(_float(q, "limit", 0))
        return {"hypotheses": rows[:limit] if limit else rows, "counts": counts, "threshold": thr}

    # -- jobs ------------------------------------------------------------------------------------
    def _wire(self, job: Job, be, tracker: Tracker | None = None) -> None:
        if hasattr(be, "should_stop"):
            be.should_stop = job.cancel.is_set
        if tracker is not None and hasattr(be, "progress"):
            be.progress = tracker.model_report

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

    def _follow_queued(self, job: Job, ws, hyp_ids: list[str], tracker: Tracker, poll: float = 2.0) -> None:
        """Follow checks by queue until Claude Code has answered their steps; their steps are taken as the answers
        arrive (here, or in the connector). Stop withdraws the checks that are still waiting."""
        shown: dict[str, str] = {}
        t0 = time.time()
        while True:
            left = taskqueue.advance(ws, hyp_ids)
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
            if not left:
                return
            if job.cancel.is_set():
                for hid in left:
                    claimcheck.delete_hypothesis(ws, hid)  # a stopped check leaves nothing behind, as in 0.7
                raise Cancelled()
            kind = {"decompose": "decompose", "terms": "expand"}.get(claimcheck.queue_stage(ws, left[0]).get("step"),
                                                                      "check")
            tracker.model_report({"phase": "queue", "seconds": time.time() - t0, **taskqueue.queue_info(ws, kind)})
            time.sleep(poll)

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

        def run(job: Job):
            tracker = Tracker(expand=False, steps=("grade",))
            job.tracker = tracker
            self._wire(job, be, tracker)
            r = claimcheck.reread_excerpt(ws, claim_id, passage_id, be, model, note=note, progress=tracker.step,
                                          should_stop=job.cancel.is_set)
            r["hyp_id"] = ws.scalar("SELECT hyp_id FROM user_claims WHERE claim_id=?", (claim_id,))
            return r

        return self._job("reread", "Reading one excerpt again", name, run, withdraw=("reread",), ws=ws)

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
        k = int(body.get("k") or s["k"])
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
            raise ApiError(400, "The second model is the same as the main model. Choose another one in Settings.")
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

        return self._job("second-opinion", f"Second model {second} on {len(ids)} "
                         f"{'hypothesis' if len(ids) == 1 else 'hypotheses'}", name, run, withdraw=("second",), ws=ws)

    def start_ingest(self, name: str, body: dict) -> Job:
        ws = self.ws(name)
        inputs: list[Path] = []
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

        def run(job: Job):
            job.progress = {"done": 0, "total": 0, "file": ""}

            def prog(i, n, fname):
                job.progress = {"done": i, "total": n, "file": fname}

            before = {r[0] for r in ws.query("SELECT doc_id FROM documents")}
            stats = ingest.ingest(ws, inputs, exclude=exclude, progress=prog, should_stop=job.cancel.is_set,
                                  ocr=ingest.OcrOptions(s.get("ocr", "auto"), s.get("ocr_lang") or "eng"))
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
            return stats

        return self.jobs.start("ingest", "Adding sources", name, run, uses_model=False)

    def _after_adding(self, ws, job: Job, stats: dict, new_docs: list[str], s: dict) -> None:
        """After documents are added (0.7): the glossary (F3) is rebuilt and the codebook's keyword pass (F2) reads
        the new documents. Neither uses the chat model; a problem with either is reported, not fatal."""
        from .. import profile, terms

        emb = _usable_embedder(ws, home.make_embedder(s)) if s.get("embed_backend") != "off" else None
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
            raise ApiError(400, "Choose an embedding model in Settings first (for example: ollama pull nomic-embed-text).")

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
                       "resolve": ("resolve",), "stronger": (), "queue-run": ()}

    def _model_job(self, kind: str, title: str, name: str, fn, steps=("grade",)) -> Job:
        """A job that uses the chat model: progress as done/total, the model's own progress, Stop. By queue (0.8)
        the progress also says what waits for Claude Code."""
        be, model = self.backend()  # one context length for every kind: Ollama never reloads the model

        def run(job: Job):
            job.progress = {"done": 0, "total": 0}
            self._wire(job, be)
            if hasattr(be, "progress"):
                be.progress = lambda info: job.progress.update(queue=info) if info.get("phase") == "queue" else \
                    job.progress.update(model=info)
            return fn(job, be, model, lambda d, n: job.progress.update(done=d, total=n))

        return self._job(kind, title, name, run, withdraw=self.MODEL_JOB_KINDS.get(kind, ()), ws=self._ws_or_none(name))

    def _ws_or_none(self, name: str | None):
        try:
            return self.ws(name) if name else None
        except ApiError:
            return None

    # -- 0.8: the queue ----------------------------------------------------------------------------
    def queue(self, name: str) -> dict:
        ws = self.ws(name)
        taskqueue.advance(ws)  # checks by queue move on here too, even when Claude Code's session stored the answers
        out = taskqueue.status(ws, name)
        out["route"] = self.settings().get("backend")
        out["setup"] = claude_setup_info()
        return out

    def start_stronger(self, name: str, task_id: str) -> Job:
        """"Ask a stronger model" on one answered task (a round of a check): read again once by the model it steps
        up to on this route."""
        ws = self.ws(name)
        t = ws.query("SELECT kind, status, step FROM tasks WHERE task_id=?", (task_id,))
        if not t:
            raise ApiError(404, "No such task.")
        be, _model = self.backend((t[0]["kind"],))
        r = getattr(be, "router", None)
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
        limit = int(body["limit"]) if body.get("limit") else None
        job = self._model_job("label", f"The AI labels passages ({fw})", name, lambda job, be, model, prog:
                               profile.run_labels(ws, fw, be, model, docs, bool(body.get("all_passages")), limit,
                                                  progress=prog, should_stop=job.cancel.is_set))
        job.scope = ",".join(docs) if docs else fw
        return job

    def start_label_compare(self, name: str, body: dict) -> Job:
        from .. import profile

        ws = self.ws(name)
        fw = str(body.get("framework") or self.settings().get("profile_framework") or "sdg")
        n = max(5, min(int(body.get("n") or 50), 200))
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
        k = int(body.get("k") or s.get("themes_k") or 20)
        seed = int(body.get("seed") or 0)
        mode = str(body.get("mode") or "auto")
        emb = home.make_embedder(s) if s.get("embed_backend") != "off" else None
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
        ws = home.create_quicklook(filename, self.settings().get("project"))
        name = ws.root.name
        folder = home.upload_folder(ws, "quicklook")
        target = folder / (re.sub(r'[\x00-\x1f<>:"|?*/\\]', "_", Path(filename).name).strip(" .") or "document.pdf")
        path.replace(target)
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
        n = max(1, min(int(body.get("n") or 10), 100))
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
    st = embed.status(ws, emb.model)
    return emb if st["embedded"] else None


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
    ("GET", r"/api/servers", "get_servers"),
    ("POST", r"/api/servers/test", "post_test"),
    ("GET", r"/api/projects", "get_projects"),
    ("POST", r"/api/projects", "post_project"),
    ("POST", r"/api/projects/link", "post_link"),
    ("POST", r"/api/projects/import", "post_import"),
    ("GET", rf"/api/projects/{P}", "get_project"),
    ("DELETE", rf"/api/projects/{P}", "delete_project"),
    ("GET", rf"/api/projects/{P}/documents", "get_documents"),
    ("DELETE", rf"/api/projects/{P}/documents", "delete_documents"),
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
    ("POST", rf"/api/projects/{P}/tasks/{P}/stronger", "post_stronger"),
    ("GET", r"/api/routing", "get_routing"),
    ("GET", r"/api/claude-setup", "get_claude_setup"),
    ("POST", r"/api/claude-setup", "post_claude_setup"),
]]
DOWNLOADS = {"get_hypothesis_export", "get_export", "get_document_file", "get_project_zip", "get_annotated", "get_flexiconc",
             "get_annotated_zip", "get_search_export", "get_profile_export", "get_themes_export"}
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
            for m, rx, name in ROUTES:
                mt = rx.match(path)
                if mt and m == method:
                    token = self.headers.get("X-Enlens-Token") or (_str(q, "token") if name in DOWNLOADS else None)
                    if not token or not secrets.compare_digest(token, self.app.token):
                        raise ApiError(401, "Missing or wrong token. Reload the page.")
                    args = [unquote(g) for g in mt.groups()]
                    out = getattr(self, name)(*args, q=q)
                    if out is not None:
                        self._json(200, out)
                    return
            if any(rx.match(path) for _m, rx, _n in ROUTES):
                raise ApiError(405, "Method not allowed.")
            raise ApiError(404, "No such API endpoint.")
        except ApiError as e:
            self._json(e.status, {"error": e.message, "kind": e.kind})
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
        running = [j for j in self.app.jobs.all() if j.state in ("queued", "running")]
        for j in running:
            j.cancel.set()

        def later():  # after this answer has gone out, and once stopped jobs have cleaned up (at most 20 s)
            t0 = time.time()
            time.sleep(0.4)
            while any(j.state in ("queued", "running") for j in running) and time.time() - t0 < 20:
                time.sleep(0.2)
            self.app.stop()

        threading.Thread(target=later, daemon=True).start()
        return {"stopping": True, "jobs_stopped": len(running)}

    def get_servers(self, q):
        return self.app.servers()

    def post_test(self, q):
        return self.app.test_backend()

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

    def post_upload(self, name, q):
        ws = self.app.ws(name)
        raw = _str(q, "name") or unquote(self.headers.get("X-Filename") or "") or "upload"  # each decoded once
        fname = re.split(r"[/\\]", raw)[-1]
        fname = re.sub(r'[\x00-\x1f<>:"|?*]', "_", fname).strip(" .") or "upload"
        if fname.startswith("."):
            fname = "_" + fname
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_UPLOAD:
            self.close_connection = True
            raise ApiError(413, "Files larger than 2 GB are not accepted.")
        self._consumed = True
        folder = home.upload_folder(ws, _str(q, "batch"))
        target = folder / fname
        if not target.resolve().is_relative_to(folder.resolve()):
            raise ApiError(400, "That file name is not accepted.")
        left = n
        with open(target, "wb") as f:
            while left > 0:
                chunk = self.rfile.read(min(left, 1 << 20))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if left:
            target.unlink(missing_ok=True)
            raise ApiError(400, "The upload was cut off.")
        return {"batch": folder.name, "name": fname, "size": n}

    def post_ingest(self, name, q):
        return {"job": self.app.start_ingest(name, self._body()).view()}

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
            claimcheck.write_xlsx(claimcheck.export_table(ws, thr, [hyp_id], every_excerpt=True), buf, "Excerpts",
                                  summary=claimcheck.summary_table(ws, thr, [hyp_id]),
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
            claimcheck.write_xlsx(claimcheck.export_table(ws, thr), buf, "Excerpts",
                                  summary=claimcheck.summary_table(ws, thr),
                                  extra=[("Map", claimcheck.map_table(claimcheck.evidence_map(ws, thr))),
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

    def post_import(self, q):
        """A project zip (raw body) becomes a new project: `?name=` or the name it had."""
        import tempfile
        import zipfile

        from .. import bundle

        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_UPLOAD:
            self.close_connection = True
            raise ApiError(413, "Files larger than 2 GB are not accepted.")
        self._consumed = True
        tmp = Path(tempfile.mkdtemp(prefix="enlens-import-"))
        try:
            path = tmp / "in.zip"
            left = n
            with open(path, "wb") as f:
                while left > 0:
                    chunk = self.rfile.read(min(left, 1 << 20))
                    if not chunk:
                        break
                    f.write(chunk)
                    left -= len(chunk)
            if left or not n:
                raise ApiError(400, "The upload was cut off.")
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
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)
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
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_UPLOAD:
            self.close_connection = True
            raise ApiError(413, "Files larger than 2 GB are not accepted.")
        self._consumed = True
        tmp = Path(tempfile.mkdtemp(prefix="enlens-quick-"))
        path = tmp / "upload"
        left = n
        with open(path, "wb") as f:
            while left > 0:
                chunk = self.rfile.read(min(left, 1 << 20))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if left or not n:
            raise ApiError(400, "The upload was cut off.")
        try:
            name, job = self.app.start_quicklook(fname, path)
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)
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
        res = concordance.search(ws, text, sort=_str(q, "sort") or "doc", offset=0, limit=1000, **self._search_args(q))
        rows = concordance.table(res)
        if res["total"] > 1000:  # the rest, page by page
            for off in range(1000, min(res["total"], 50000), 1000):
                rows += concordance.table(concordance.search(ws, text, sort=_str(q, "sort") or "doc", offset=off,
                                                             limit=1000, **self._search_args(q)))
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

        return {"terms": terms.key_terms(self.app.ws(name), passage_id=passage_id, n=_int(q, "n", 5, 1, 20))}

    # themes (F4)
    def get_themes(self, name, q):
        from .. import themes

        ws = self.app.ws(name)
        s = self.app.settings()
        emb = home.make_embedder(s) if s.get("embed_backend") != "off" else None
        try:
            mode, why = themes.choose_mode(ws, "auto", getattr(emb, "model", None))
        except ValueError as e:
            mode, why = "words", str(e)
        return {"runs": themes.runs(ws), "auto_mode": mode, "auto_why": why, "k": s.get("themes_k") or 20}

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
        tmp = Path(tempfile.mkdtemp(prefix="enlens-fc-"))
        try:
            out = tmp / "flexiconc.sqlite"
            emb = self.app.settings().get("embed_model") if self.app.settings().get("embed_backend") != "off" else None
            flexiconc_export.export(ws, out, framework=_str(q, "framework") or self.app.settings().get("profile_framework")
                                    or "sdg", embed_model=emb or None, embeddings=bool(emb))
            body = out.read_bytes()
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)
        return self._send(200, body, "application/vnd.sqlite3",
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
        return {"jobs": [j.view(full=False) for j in self.app.jobs.all()]}

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
            # a check waiting for Claude Code is taken back whole, as a stopped check (it leaves nothing behind)
            for (hid,) in ws.query("SELECT hyp_id FROM hypotheses WHERE queue='waiting'"):
                claimcheck.delete_hypothesis(ws, hid)
                removed += 1
        n = taskqueue.withdraw(ws, [kind])
        return {"withdrawn": n, "checks_removed": removed}

    def post_queue_run(self, name, q):
        return {"job": self.app.start_queue_run(name, self._body()).view()}

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
        return {"route": route, "route_name": routing.ROUTE_NAMES.get(route, route), "rows": r.table(),
                "aliases": list(routing.ALIASES), "fable": bool(s.get("use_fable")),
                "local_small_model": s.get("local_small_model") or "", "second_model": s.get("second_model") or "",
                "step_up_below": routing.STEP_UP_BELOW, "routing": bool(s.get("routing", True))}

    def get_claude_setup(self, q):
        return claude_setup_info()

    def post_claude_setup(self, q):
        from .. import claude_setup

        self._body()
        if home.local_only():
            raise ApiError(403, "Cloud models are switched off on this computer: the Claude Code plugin is not available.")
        claude_setup.write_plugin()
        return {**claude_setup_info(), "problems": claude_setup.check_files()}


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
    print("ENLENS stopped.")
    return 0
