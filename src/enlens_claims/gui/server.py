"""The hypothesis checker's local web app: a small HTTP server (standard library only) and one static page.

    enlens-gui                       # http://127.0.0.1:8765 in your browser
    enlens-gui --home D:/enlens      # keep projects and settings in another folder

Local first:
- It listens on 127.0.0.1 only (another address only with --host, at your own risk).
- Every API call needs the access token and a Host header naming this computer, so other web sites open in the same
  browser cannot use it (no CORS, DNS rebinding blocked). 0.17.2: the page does not carry the token, so another
  account on the same computer cannot fetch it: the app opens its link with the token after `#` (never sent to a
  server), and keeps it in a file only this account can read (launcher.token_path) for the icon and the command line.
- The page loads nothing from the internet: no CDN, no fonts, no analytics.
- Text goes only to the model service chosen in Settings: a local server by default; the Claude API only after
  cloud models are allowed.

The API is described in docs/API.md. Long work (checks, batches, adding sources, building the semantic index)
runs as a job in a background thread; the page polls /api/jobs/<id> for its progress.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
import traceback
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .. import __version__, access, addons, bibliography, claimcheck, embed, frameworks, home, ingest, taskqueue
from .. import sync
from .. import tasks as tasks_mod
from .. import llm, modeladvice, ollama_setup
from ..llm import BackendError, detect_local
from ..store import now as _now
from ..sources import document_overview
from .progress import Tracker
from .api_checks import ChecksApi
from .api_documents import DocumentsApi
from .api_explore import ExploreApi
from .api_record import RecordApi
from .api_setup import SetupApi
from .api_folder import FolderApi
from .api_space import SpaceApi
from .api_poller import PollerApi  # 0.18 (L3)
from .api_owner import OwnerApi  # 0.18 (L2)
from .api_sharing import SharingApi
from . import api_checks_extra, api_corpus  # 0.18.1: part B's and part A's routes, built side by side
from .api_checks_extra import ChecksExtraApi
from .api_corpus import CorpusApi
from .app_library import LibraryMixin
from .app_queue import QueueMixin
from .api_common import (  # noqa: F401 - the names are importable from here as before
    ApiError,
    Cancelled,
    Job,
    Jobs,
    MAX_JSON,
    MAX_UPLOAD,
    XLSX,
    _PDFIUM_LOCK,
    _body_int,
    _bool,
    _cell,
    _check_options,
    _csv,
    _disposition,
    _filename,
    _float,
    _installation,
    _int,
    _list,
    _str,
    _text_with_quote,
    _usable_embedder,
    _xlsx_with_provenance,
    benchmark_table,
    page_images_available,
    reading_report,
    render_page,
)

STATIC = Path(__file__).with_name("static")
FOLLOW_POLL = 2.0  # seconds between two looks at checks that wait for Claude Code (`follow_queued`; tests shorten it)




# ---------------------------------------------------------------------------------------------
# the application
# ---------------------------------------------------------------------------------------------
class App(LibraryMixin, QueueMixin):
    def __init__(self, token: str | None = None):
        self.token = token or secrets.token_urlsafe(24)
        # 0.17.2: which run of the app served a page (not a secret): the page that waits for a restart knows the new
        # copy by it, now that the token no longer changes in the page (a restart keeps it: _restart)
        self.run_id = secrets.token_hex(6)
        self.jobs = Jobs()
        self.session_key = ""      # a Claude API key given for this session only
        self.allowed_hosts: set[str] = set()
        self.any_host = False
        self.port = 0
        self.host = "127.0.0.1"    # 0.15.4: the address it listens on (the hand-over starts it again there)
        self.launcher = False      # started from the ENLENS icon (launcher.py)
        self.stop = None           # stops the server ("Quit ENLENS"); set by serve()
        self.restart = None        # 0.13.1: stops the server and starts the version on disk in its place (serve())
        self.updating = threading.Lock()  # 0.13.1: one "Update and restart" at a time
        self.update_seen: dict | None = None  # 0.13.6: the last look for a newer version (GET /api/update)
        self.update_looking = threading.Lock()  # one look at a time: the tabs that ask together share it
        # 0.14.3: the page's own files (index.html, the scripts, the style sheets), read once when the app starts
        # (serve()), so a copy that keeps running after an update on disk serves the page code that fits its API, not
        # the new one. None (tests, tools/dev_server.py): read from disk on every request, so page code can be edited
        # without a restart.
        self.frozen_static: dict[str, bytes] | None = None
        # 0.18 (L3): looks in each project's shared folder every couple of minutes; started by serve(), not by tests
        from .poller import Poller

        self.poller = Poller(self)
        # 0.18 (L2): a new reading the owner accepted is made here after the round that brought the decision in
        from . import api_owner

        self.jobs.ended.append(lambda job: api_owner.after_job(self, job))

    def freeze_static(self) -> None:
        self.frozen_static = {f.relative_to(STATIC).as_posix(): f.read_bytes()
                              for f in STATIC.rglob("*") if f.is_file()}

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
            n = ws.scalar(f"SELECT COUNT(*) FROM tasks WHERE {taskqueue.WAITING}") or 0  # the partial index alone
        except Exception:  # noqa: BLE001
            return None
        return {"waiting": int(n)}

    def servers(self) -> dict:
        s = self.settings()
        found = detect_local(ollama_url=s.get("ollama_url"), extra=[s.get("openai_url") or ""], cache_seconds=3)
        for srv in found:
            srv["chat_models"] = [m for m in srv["models"] if not re.search(r"embed|bge-|e5-|minilm|rerank", m, re.I)]
            srv["embedding_models"] = [m for m in srv["models"] if re.search(r"embed|bge-|e5-|minilm", m, re.I)]
        # 0.13.7: the models the page offers to download into Ollama with one button; 0.15.6: whether Ollama is on
        # this computer (running or not), for the button that installs or starts it
        # 0.18.0rc2 (M8): the models suggested are those that fit THIS computer (modeladvice), with a smaller and a larger
        # one beside them in `advice`; `suggested` keeps its old shape for the one-button download
        try:
            advice = modeladvice.advise(modeladvice.computer(str(home.home())))
        except Exception:  # noqa: BLE001 - the advice is a convenience: the card works without it
            advice = None
        return {"servers": found, "suggested": modeladvice.suggested(advice) if advice else [dict(m) for m in llm.SUGGESTED_MODELS],
                "advice": advice, "ollama_app": ollama_setup.status()}

    _OLLAMA_INSTALL = threading.Lock()   # two presses (two tabs) never start two downloads of 1.7 GB

    def ollama_install_job(self) -> Job | None:
        """0.15.6: the install of Ollama that is running, if any."""
        return next((j for j in self.jobs.all() if j.kind == "ollama-install" and j.state in ("queued", "running")), None)

    def install_ollama(self) -> Job:
        """0.15.6: download Ollama's installer, check that it is Ollama's, install it for this user and start it (a
        job that can be stopped while it downloads). Ollama on this computer already is only started."""
        with self._OLLAMA_INSTALL:
            running = self.ollama_install_job()
            if running:
                return running
            return self._start_ollama_install()

    def _start_ollama_install(self) -> Job:
        def is_running() -> bool:   # where Settings says Ollama listens (localhost:11434 unless changed)
            return any(x["kind"] == "ollama" for x in detect_local(ollama_url=self.settings().get("ollama_url"),
                                                                   cache_seconds=0))

        def run(job: Job):
            def tick(p: dict) -> None:
                job.progress = p

            r = ollama_setup.install(on_progress=tick, should_stop=job.cancel.is_set, is_running=is_running)
            llm._DETECTED.clear()   # the next look at the servers finds it
            return None if r.get("stopped") else r

        return self.jobs.start("ollama-install", "Installing Ollama", None, run, uses_model=False)

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
        # 0.18 (L2): a document that is only proposed to the owner (or that the owner declined) says so: `proposal`
        # {"state": "proposed" | "declined" | "waiting", "text"} or None
        from .. import ownership

        waits = ownership.document_marks(ws)
        for d in docs:
            d["proposal"] = waits.get(d["doc_id"])
        return {"documents": docs, "ai_access": access.project_info(ws), "new_reader": ingest.READER,  # 0.15.7
                "restricted_model": home.restricted_choice(s),
                "search": embed.status(ws, s.get("embed_model"),
                                       home.make_embedder(s))}

    def document(self, name: str, doc_id: str, offset: int, limit: int, view: str = "") -> dict:
        ws = self.ws(name)
        d = ws.query("SELECT doc_id, title, file_title, path, kind, n_pages, n_chars, doi, added_at, "
                     "COALESCE(reader, 1) AS reader, reading_json FROM documents WHERE doc_id=?", (doc_id,))
        if not d:
            raise ApiError(404, "No such document.")
        out = dict(d[0])
        # 0.15: how the document was read (the reading report, A5) and whether it has the new reader's blocks
        out["reading"] = reading_report(ws, doc_id, out.pop("reading_json"), out["reader"])
        out["new_reader"] = ingest.READER
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
        out["page_images"] = bool(info["available"] and out["kind"] == "pdf" and page_images_available())
        out["tables"] = int(ws.scalar("SELECT COUNT(*) FROM doc_tables WHERE doc_id=?", (doc_id,)) or 0)
        out["paragraphs"] = int(ws.scalar("SELECT COUNT(*) FROM paragraphs WHERE doc_id=?", (doc_id,)) or 0)
        out.update(App.reading_now(ws, doc_id))
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
        if ws.scalar("SELECT 1 FROM blocks WHERE doc_id=? LIMIT 1", (doc_id,)):
            return App.reading_blocks(ws, doc_id, text, offset, limit)
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

    @staticmethod
    def reading_now(ws, doc_id: str) -> dict:
        """0.15: a document's reading as it stands now (Restore and Leave out change it): what is left out, by kind,
        and the passages read. 0.16: also sent back by Restore, Leave out and the text's start and end, so the
        reading view shows them without being drawn again."""
        left_out = {r[0]: r[1] for r in ws.query("SELECT kind, COUNT(*) FROM blocks WHERE doc_id=? AND included=0 "
                                                  "GROUP BY kind ORDER BY COUNT(*) DESC", (doc_id,))}
        read = int(ws.scalar("SELECT COUNT(*) FROM passages WHERE doc_id=? AND section='body'", (doc_id,)) or 0)
        every = int(ws.scalar("SELECT COUNT(*) FROM passages WHERE doc_id=?", (doc_id,)) or 0)
        return {"left_out": left_out, "passages_read": read, "passages_all": every}

    @staticmethod
    def reading_blocks(ws, doc_id: str, text: str, offset: int, limit: int,
                       only: set[int] | None = None) -> tuple[list[dict], int]:
        """0.15 (A4): a document read by the new reader, block by block in reading order: what each block is
        (a heading, a paragraph, a caption, a table, a running head...), whether searches, codes, themes and checks
        read it, a table's rows, and its box on the page. Paragraphs are numbered per page as quotes are cited.
        0.16: `only`: just these blocks (by n), wherever they are in the document (offset and limit aside)."""
        from .. import reader as reader2

        rows = ws.query("SELECT n, page, start, end, kind, included, x0, y0, x1, y1 FROM blocks WHERE doc_id=? "
                        "ORDER BY n", (doc_id,))
        tables = {r["block"]: r for r in ws.query("SELECT n, block, caption, rows_json FROM doc_tables WHERE doc_id=?",
                                                  (doc_id,))}
        paras: dict[int | None, list[int]] = {}
        for r in ws.query("SELECT start, page FROM paragraphs WHERE doc_id=? ORDER BY start", (doc_id,)):
            paras.setdefault(r["page"], []).append(r["start"])
        first = max(0, offset)
        chosen = ([(i, r) for i, r in enumerate(rows) if r["n"] in only] if only is not None
                  else list(enumerate(rows[first:first + max(1, min(limit, 1000))], first)))
        # 0.15.1: how many other blocks look the same (a running head, a page number: "All like this"), and where the
        # person said the text starts and ends
        shapes = App.block_shapes(text, rows)
        alike = Counter(x for x in shapes if x)
        fps = [reader2.block_fp(text[r["start"]:r["end"]]) for r in rows]
        choices = {r["fp"]: r["included"] for r in ws.query("SELECT fp, included FROM block_choices WHERE doc_id=?",
                                                             (doc_id,))}
        marks = {side: reader2.bound_index(choices, side, fps) for side in reader2.BOUNDS}
        out = []
        for idx, r in chosen:
            kind, pg = r["kind"], r["page"]
            starts = paras.get(pg, [])
            para = sum(1 for s0 in starts if s0 <= r["start"]) if kind in reader2.INCLUDED else None
            joined = False
            if r["start"] in starts:  # a paragraph begins here
                label = f"Page {pg}, paragraph {para}" if pg else f"Paragraph {para}"
            elif kind in reader2.INCLUDED:
                label, joined = "", True  # the paragraph above goes on (under its heading, or across a column)
            elif kind == "furniture":
                label = reader2.furniture_label(text[r["start"]:r["end"]])
            else:
                label = reader2.KIND_LABEL.get(kind) or reader2.KIND_TEXT.get(kind, kind).capitalize()
            b = {"n": r["n"], "label": label, "page": pg, "paragraph": para, "kind": kind,
                 "kind_text": reader2.KIND_TEXT.get(kind, kind), "included": bool(r["included"]),
                 "start": r["start"], "end": r["end"], "text": text[r["start"]:r["end"]],
                 "headings": [{"at": 0, "end": r["end"] - r["start"], "text": text[r["start"]:r["end"]]}]
                 if kind in ("heading", "title") else [],
                 "changed": bool(r["included"]) != (kind in reader2.INCLUDED) or fps[idx] in choices, "joined": joined,
                 "box": [r["x0"], r["y0"], r["x1"], r["y1"]] if r["x0"] is not None else None,
                 "alike": alike[shapes[idx]] - 1 if shapes[idx] else 0,
                 "share": round(idx / max(1, len(rows) - 1), 3),
                 "bound": next((side for side, at in marks.items() if at == idx), None)}
            t = tables.get(r["n"])
            if t is not None:
                b["table"] = {"n": t["n"], "caption": t["caption"], "rows": json.loads(t["rows_json"] or "[]")}
            out.append(b)
        return out, len(rows)

    @staticmethod
    def block_shapes(text: str, rows) -> list[str | None]:
        """0.15.1: each block's shape for *All like this*: short blocks only (running heads, page numbers, labels),
        their numbers aside ("TIS final pgs 12" and "TIS final pgs 13" look the same)."""
        from .. import reader3

        out: list[str | None] = []
        for r in rows:
            t = text[r["start"]:r["end"]]
            out.append(reader3.shape(t) if 0 < len(t.strip()) <= 200 else None)
        return out

    def set_block(self, name: str, doc_id: str, n: int, included: bool, alike: bool = False) -> dict:
        """0.15 (A4): *Restore* or *Leave out* a block. Blocks that share a passage (a heading and its paragraph,
        short paragraphs put together) go together; the choice is kept by the blocks' text, so it holds when the
        document is read again. 0.15.1: with `alike`, every block that looks the same (`block_shapes`) too."""
        from .. import people
        from .. import reader as reader2

        ws = self.ws(name)
        with ws.connect() as cx:
            text = cx.execute("SELECT text FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
            row = cx.execute("SELECT start, end FROM blocks WHERE doc_id=? AND n=?", (doc_id, n)).fetchone()
            if not text or not row:
                raise ApiError(404, "No such block in this document.")
            text = text[0]
            targets = [tuple(row)]
            if alike:
                rows = [dict(zip(("n", "start", "end"), r)) for r in
                        cx.execute("SELECT n, start, end FROM blocks WHERE doc_id=? ORDER BY n", (doc_id,))]
                shapes = App.block_shapes(text, rows)
                mine = next((shapes[i] for i, r in enumerate(rows) if r["n"] == n), None)
                if mine:
                    targets = [(r["start"], r["end"]) for r, sh in zip(rows, shapes) if sh == mine]
            group = []
            seen: set[int] = set()
            for a, z in targets:
                # the passages this block is in, and every block in those passages
                ps = cx.execute("SELECT start, end FROM passages WHERE doc_id=? AND start < ? AND end > ?",
                                (doc_id, z, a)).fetchall()
                lo, hi = min([a] + [p[0] for p in ps]), max([z] + [p[1] for p in ps])
                for g in cx.execute("SELECT n, start, end, kind FROM blocks WHERE doc_id=? AND start < ? AND end > ? "
                                    "ORDER BY n", (doc_id, hi, lo)).fetchall():
                    if g[0] not in seen:
                        seen.add(g[0])
                        group.append(g)
            # 0.15.1: what each block would be without a choice of its own: its kind, and where the person said the
            # text starts and ends (a paragraph restored after the end needs a choice of its own)
            all_rows = cx.execute("SELECT n, start, end, kind FROM blocks WHERE doc_id=? ORDER BY n", (doc_id,)).fetchall()
            marks = {r[0]: r[1] for r in cx.execute("SELECT fp, included FROM block_choices WHERE doc_id=? AND "
                                                    "(fp LIKE 'start:%' OR fp LIKE 'end:%')", (doc_id,))}
            plain = dict(zip((r[0] for r in all_rows),
                             reader2.choose_inclusion([(text[r[1]:r[2]], r[3]) for r in all_rows], marks)))
            fps = set()
            for gn, ga, gz, kind in group:
                fp = reader2.block_fp(text[ga:gz])
                fps.add(fp)
                if bool(included) == bool(plain.get(gn, kind in reader2.INCLUDED)):
                    cx.execute("DELETE FROM block_choices WHERE doc_id=? AND fp=?", (doc_id, fp))
                else:
                    cx.execute("INSERT OR REPLACE INTO block_choices(doc_id, fp, included, kind, person_id, at) "
                               "VALUES (?,?,?,?,?,?)", (doc_id, fp, 1 if included else 0, kind, people.me(), _now()))
            moved = reader2.apply_choices(cx, doc_id)
            ws.bump_corpus(cx)
        mine = {g[0] for g in group}
        # 0.16: each block as it is now, wherever it is in the document (the first 1000 only before), and the
        # reading's figures, so the reading view shows the change where it happened instead of drawing itself again.
        # A choice is kept by the block's words, so blocks elsewhere with the same words change with it (a title
        # repeated on every page): they are sent too, with those whose mark ("left out by you") changed
        same = {r[0] for r in all_rows if reader2.block_fp(text[r[1]:r[2]]) in fps}
        blocks, _total = App.reading_blocks(ws, doc_id, text, 0, 0, only=mine | set(moved) | same)
        return {"blocks": blocks, "group": sorted(mine), "together": len(mine), "alike": len(targets),
                "doc": App.reading_now(ws, doc_id)}

    def set_bound(self, name: str, doc_id: str, side: str, n: int | None) -> dict:
        """0.15.1: *Text starts here* or *Text ends here* at block n (None: no longer). What comes before the start,
        or after the end, is left out of searches, codes, themes and checks; a block the person restored there still
        counts. Kept by the block's words, so it holds when the document is read again."""
        from .. import people
        from .. import reader as reader2

        if side not in reader2.BOUNDS:
            raise ApiError(400, "side must be start or end.")
        ws = self.ws(name)
        with ws.connect() as cx:
            text = cx.execute("SELECT text FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
            rows = cx.execute("SELECT n, start, end FROM blocks WHERE doc_id=? ORDER BY n", (doc_id,)).fetchall()
            if not text or not rows:
                raise ApiError(404, "This document has no blocks to mark (it was read before 0.15).")
            text = text[0]
            idx = next((i for i, r in enumerate(rows) if r[0] == n), None) if n is not None else None
            if n is not None and idx is None:
                raise ApiError(404, "No such block in this document.")
            fps = [reader2.block_fp(text[a:z]) for _n, a, z in rows]
            other = {r[0]: r[1] for r in cx.execute("SELECT fp, included FROM block_choices WHERE doc_id=? AND fp LIKE ?",
                                                    (doc_id, ("end" if side == "start" else "start") + ":%"))}
            at_other = reader2.bound_index(other, "end" if side == "start" else "start", fps)
            if idx is not None and at_other is not None and ((side == "start" and idx > at_other)
                                                             or (side == "end" and idx < at_other)):
                raise ApiError(400, "The text cannot start after it ends: move or undo the other mark first.")
            before = {r[0]: r[1] for r in cx.execute("SELECT n, included FROM blocks WHERE doc_id=?", (doc_id,))}
            mine = {r[0]: r[1] for r in cx.execute("SELECT fp, included FROM block_choices WHERE doc_id=? AND fp LIKE ?",
                                                   (doc_id, side + ":%"))}
            was = reader2.bound_index(mine, side, fps)   # where this mark was (its block changes too)
            cx.execute("DELETE FROM block_choices WHERE doc_id=? AND fp LIKE ?", (doc_id, side + ":%"))
            if idx is not None:
                cx.execute("INSERT OR REPLACE INTO block_choices(doc_id, fp, included, kind, person_id, at) "
                           "VALUES (?,?,?,?,?,?)", (doc_id, reader2.bound_key(side, fps, idx), 0, "bound", people.me(), _now()))
            reader2.apply_choices(cx, doc_id)
            after = {r[0]: r[1] for r in cx.execute("SELECT n, included FROM blocks WHERE doc_id=?", (doc_id,))}
            ws.bump_corpus(cx)
        changed = [k for k, v in after.items() if before.get(k) != v]
        # 0.16: the blocks as they are now (those that changed and those that carry or carried the mark), and the
        # reading's figures, so the reading view shows the change in place
        marked = {rows[i][0] for i in (was, idx) if i is not None}
        blocks, _total = App.reading_blocks(ws, doc_id, text, 0, 0, only=set(changed) | marked)
        return {"side": side, "block": n, "changed": len(changed),
                "left_out": sum(1 for k in changed if not after[k]), "restored": sum(1 for k in changed if after[k]),
                "blocks": blocks, "doc": App.reading_now(ws, doc_id)}

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

    def follow_queued(self, job: Job, ws, hyp_ids: list[str], tracker: Tracker, poll: float | None = None) -> None:
        """Follow checks by queue until Claude Code has answered their steps; their steps are taken as the answers
        arrive (here, or in the connector). Stop withdraws the checks that are still waiting. (0.13.6: public;
        `_follow_queued` before.) It looks every FOLLOW_POLL seconds (2026-11-12: tests shorten it)."""
        poll = FOLLOW_POLL if poll is None else poll
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
                    claimcheck.delete_hypothesis(ws, hid, unmade=True)  # a stopped check leaves nothing behind, as in 0.7
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




# ---------------------------------------------------------------------------------------------
# 0.15.1: the "what's new" note, shown once after an update. After 0.17.2: read only when asked (What's new)
# ---------------------------------------------------------------------------------------------
WHATS_NEW_FILE = Path(__file__).resolve().parent / "static" / "whats-new.md"
_whats_new_lock = threading.Lock()


def parse_whats_new(text: str) -> dict | None:
    """`# 0.15.1: Title`, `*subtitle*` and lines starting with `-` as points; blank lines ignored. Anything else
    (no heading, no subtitle, no points) is no note: never an error."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) < 3:
        return None
    m = re.fullmatch(r"#\s*(\d+\.\d+\.\d+\S*)\s*:\s*(.+)", lines[0])
    sub = re.fullmatch(r"\*([^*].*?)\*", lines[1])
    if not m or not sub:
        return None
    points = []
    for ln in lines[2:]:
        if not ln.startswith("-") or not ln[1:].strip():
            return None
        points.append(ln[1:].strip())
    return {"version": m.group(1), "title": m.group(2).strip(), "subtitle": sub.group(1).strip(), "points": points}


UPDATE_PROBLEMS = {  # 0.15.4: what to do when the hand-over on Windows did not finish (handover.py's hints)
    "in_use": ["Another program was still using ENLENS's files, most likely Claude Code with ENLENS connected",
               "Close Claude Code, then press Update again"],
    "not_quit": ["ENLENS did not quit in time, so nothing was installed",
                 "Press Update again when nothing is running in ENLENS"],
}
UPDATE_PROBLEM_OTHER = ["The details are in logs/update.log in the data folder",
                        "Press Update again, or run the install line again (it is on the release page)"]


def update_note() -> dict | None:
    """0.15.4: once, after an update on Windows that did not finish (the result handover.py left), what happened and
    what to do; the result is removed the moment it is read, and one that says the update worked is only removed."""
    from .. import update as upd

    p = upd.result_path()
    with _whats_new_lock:
        try:
            res = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        try:
            p.unlink()
        except OSError:
            pass
    if not isinstance(res, dict) or res.get("ok"):
        return None
    version = str(res.get("version") or "the new version")
    return {"kind": "problem", "version": __version__, "title": f"The update to {version} did not finish",
            "subtitle": f"ENLENS {__version__} is running. Your projects and results are kept.",
            "points": UPDATE_PROBLEMS.get(str(res.get("hint") or ""), UPDATE_PROBLEM_OTHER)}


def whats_new_note() -> tuple[dict | None, bool]:
    """The note when it is for the running version (else None), and whether it is unread: an update brought it and
    this person has not opened it yet. After 0.17.2 nothing is shown by itself any more, so serving it marks nothing
    (What's new marks it read when it is opened: mark_whats_new_read). A new installation (no project yet, or
    no settings file) is marked read at once, so it never offers the note of a version it did not update to."""
    try:
        note = parse_whats_new(WHATS_NEW_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return None, False
    if not note or note["version"] != __version__:
        return None, False
    from ..installation import REPO

    note["url"] = f"https://github.com/{REPO}/releases/tag/v{__version__}"  # every change, on the release page
    with _whats_new_lock, home.LOCK:  # (home.LOCK: read and written back as one step, as every change of settings)
        try:
            settings = home.load_settings()
            if settings.get("whats_new_seen") == __version__:
                return note, False
            if not home.list_projects() or not (home.home() / "settings.json").exists():
                settings["whats_new_seen"] = __version__
                home.save_settings(settings)
                return note, False
        except (OSError, ValueError):
            return note, False
    return note, True


def mark_whats_new_read() -> None:
    """The note of the running version has been opened: the sidebar no longer offers it."""
    with _whats_new_lock, home.LOCK:
        settings = home.load_settings()
        if settings.get("whats_new_seen") != __version__:
            settings["whats_new_seen"] = __version__
            home.save_settings(settings)


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
    ("GET", r"/api/whats-new", "get_whats_new"),
    ("POST", r"/api/whats-new/read", "post_whats_new_read"),
    ("POST", r"/api/update", "post_update"),
    ("GET", r"/api/technical-details", "get_technical_details"),
    ("GET", r"/api/servers", "get_servers"),
    ("POST", r"/api/servers/test", "post_test"),
    ("POST", r"/api/servers/pull", "post_pull"),
    # 0.15.6: Ollama installed (or started) from the app, as Claude Code is
    ("GET", r"/api/ollama", "get_ollama"),
    ("POST", r"/api/ollama/install", "post_ollama_install"),
    ("POST", r"/api/ollama/start", "post_ollama_start"),
    ("GET", r"/api/projects", "get_projects"),
    ("POST", r"/api/projects", "post_project"),
    ("POST", r"/api/projects/link", "post_link"),
    ("POST", r"/api/projects/import", "post_import"),
    # roles-P3: the answer to a move zip's question, and *Use both computers* (DESIGN-roles §4.11, §5.5, §5.6)
    ("POST", r"/api/move", "post_move"),
    ("POST", r"/api/second-computer", "post_second_computer"),
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
    ("PUT", rf"/api/projects/{P}/documents/{P}/blocks/{P}", "put_block"),
    ("PUT", rf"/api/projects/{P}/documents/{P}/bounds", "put_bounds"),
    ("GET", rf"/api/projects/{P}/documents/{P}/reread", "get_reread"),
    ("POST", rf"/api/projects/{P}/documents/{P}/reread", "post_reread_document"),
    ("POST", rf"/api/projects/{P}/new-reader", "post_new_reader_many"),
    ("POST", rf"/api/projects/{P}/new-reader/preview", "post_new_reader_preview"),
    ("PUT", rf"/api/projects/{P}/documents/{P}/reading-checked", "put_reading_checked"),
    ("GET", rf"/api/projects/{P}/documents/{P}/pages/{P}\.png", "get_page_image"),
    ("GET", rf"/api/projects/{P}/documents/{P}/tables/{P}\.xlsx", "get_table_export"),
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
    ("POST", rf"/api/projects/{P}/hypotheses/similar", "post_similar"),  # 0.18: near-duplicate hypotheses (N1)
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
    ("GET", rf"/api/projects/{P}/terms/words", "get_terms_words"),
    ("PUT", rf"/api/projects/{P}/terms/words", "put_terms_words"),
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
    # 0.16: the research log, notes and highlights, earlier versions, your own codebooks (api_record.py)
    ("GET", rf"/api/projects/{P}/log", "get_log"),
    ("POST", rf"/api/projects/{P}/log", "post_log"),
    ("GET", rf"/api/projects/{P}/log\.(md|xlsx)", "get_log_export"),
    ("PUT", rf"/api/projects/{P}/log/{P}", "put_log"),
    ("DELETE", rf"/api/projects/{P}/log/{P}", "delete_log"),
    ("GET", rf"/api/projects/{P}/notes", "get_notes"),
    ("POST", rf"/api/projects/{P}/notes", "post_note"),
    ("GET", rf"/api/projects/{P}/notes\.(md|xlsx)", "get_notes_export"),
    ("PUT", rf"/api/projects/{P}/notes/{P}", "put_note_item"),
    ("DELETE", rf"/api/projects/{P}/notes/{P}", "delete_note_item"),
    ("POST", rf"/api/projects/{P}/notes/{P}/evidence", "post_note_evidence"),
    ("GET", rf"/api/projects/{P}/documents/{P}/notes", "get_document_notes"),
    ("GET", rf"/api/projects/{P}/history/(themes|check|codebook)/{P}", "get_versions"),
    ("GET", rf"/api/projects/{P}/history/(themes|check|codebook)/{P}/{P}", "get_version"),
    ("POST", rf"/api/projects/{P}/history/(themes|check|codebook)/{P}/{P}/restore", "post_restore"),
    ("GET", rf"/api/projects/{P}/codebooks", "get_codebooks"),
    ("POST", rf"/api/projects/{P}/codebooks", "post_codebook"),
    ("GET", rf"/api/projects/{P}/codebooks/sources", "get_codebook_sources"),
    ("POST", rf"/api/projects/{P}/codebooks/example", "post_codebook_example"),
    ("GET", rf"/api/projects/{P}/codebooks/{P}\.csv", "get_codebook_csv"),
    ("GET", rf"/api/projects/{P}/codebooks/{P}", "get_codebook"),
    ("PUT", rf"/api/projects/{P}/codebooks/{P}", "put_codebook"),
    ("DELETE", rf"/api/projects/{P}/codebooks/{P}", "delete_codebook"),
    ("POST", rf"/api/projects/{P}/codebooks/{P}/move", "post_codebook_move"),
    ("POST", rf"/api/projects/{P}/codebooks/{P}/copy-here", "post_codebook_copy_here"),
    ("POST", rf"/api/projects/{P}/codebooks/{P}/try", "post_codebook_try"),
    ("POST", rf"/api/projects/{P}/codebooks/{P}/relabel", "post_codebook_relabel"),
    ("POST", rf"/api/projects/{P}/codebooks/{P}/clashes/{P}", "post_codebook_clash"),  # 0.18
    # 0.18 (L1): private until shared (api_sharing.py)
    ("GET", rf"/api/projects/{P}/sharing", "get_sharing"),
    ("GET", rf"/api/projects/{P}/sharing/(check|themes|codebook|note|log|link)/{P}", "get_sharing_item"),
    ("POST", rf"/api/projects/{P}/sharing/share", "post_share"),
    ("POST", rf"/api/projects/{P}/sharing/unshare", "post_unshare"),
    # 0.18 (L5): the shared folder (api_folder.py)
    ("GET", rf"/api/projects/{P}/shared-folder", "get_shared_folder"),
    ("PUT", rf"/api/projects/{P}/shared-folder", "put_shared_folder"),
    ("DELETE", rf"/api/projects/{P}/shared-folder", "delete_shared_folder"),
    ("PUT", rf"/api/projects/{P}/shared-folder/keep-out", "put_shared_folder_keep_out"),
    ("POST", rf"/api/projects/{P}/shared-folder/sync", "post_shared_folder_sync"),
    # 0.18.0rc2 (L6): a storage space of the team's own (api_space.py)
    ("GET", r"/api/space/links", "get_space_links"),
    ("POST", r"/api/join-team", "post_join_team"),
    ("POST", rf"/api/projects/{P}/space/b2", "post_space_b2"),
    ("POST", rf"/api/projects/{P}/space/r2", "post_space_r2"),
    ("POST", rf"/api/projects/{P}/space/dir", "post_space_dir"),
    ("POST", rf"/api/projects/{P}/space/invites", "post_space_invites"),
    ("DELETE", rf"/api/projects/{P}/space/invites/(m[0-9a-f]{{12}})", "delete_space_invite"),
    ("DELETE", rf"/api/projects/{P}/space/members/(m[0-9a-f]{{12}})", "delete_space_member"),
    ("POST", rf"/api/projects/{P}/space/move", "post_space_move"),
    ("POST", rf"/api/projects/{P}/space/join", "post_space_join"),
    ("DELETE", rf"/api/projects/{P}/space", "delete_space"),
    # 0.18.0rc2 (L7): an easier shared folder (api_folder.py)
    ("GET", r"/api/cloud-folders", "get_cloud_folders"),
    ("POST", r"/api/choose-folder", "post_choose_folder"),
    ("GET", rf"/api/projects/{P}/shared-folder/find", "get_shared_folder_find"),
    # 0.18 (L3): the poller (api_poller.py)
    ("GET", r"/api/sync-poller", "get_sync_poller"),
    ("PUT", r"/api/sync-poller", "put_sync_poller"),
    ("GET", rf"/api/projects/{P}/sync-poller", "get_project_sync_poller"),
    ("PUT", rf"/api/projects/{P}/sync-poller", "put_project_sync_poller"),
    ("POST", rf"/api/projects/{P}/sync-poller/seen", "post_project_sync_poller_seen"),
    # 0.18 (L2): one owner, proposals by severity (api_owner.py)
    ("GET", rf"/api/projects/{P}/owner", "get_owner"),
    ("POST", rf"/api/projects/{P}/owner/claim", "post_owner_claim"),
    ("POST", rf"/api/projects/{P}/owner/hand-over", "post_owner_hand_over"),
    ("POST", rf"/api/projects/{P}/owner/take-over", "post_owner_take_over"),
    ("PUT", rf"/api/projects/{P}/owner/settings", "put_owner_settings"),
    ("POST", rf"/api/projects/{P}/owner/apply", "post_owner_apply"),
    ("POST", rf"/api/projects/{P}/owner/proposals/{P}/accept", "post_proposal_accept"),
    ("POST", rf"/api/projects/{P}/owner/proposals/{P}/decline", "post_proposal_decline"),
    ("POST", rf"/api/projects/{P}/owner/proposals/{P}/take-back", "post_proposal_take_back"),
    # roles (DESIGN-roles §7 P4): roles, questions about the owner, offers, removals, clashes, refused rows (api_owner.py)
    ("PUT", rf"/api/projects/{P}/owner/roles/{P}", "put_owner_role"),
    ("POST", rf"/api/projects/{P}/owner/questions/{P}", "post_owner_question"),
    ("POST", rf"/api/projects/{P}/owner/loosening", "post_owner_loosening"),
    ("POST", rf"/api/projects/{P}/owner/removed/{P}/restore", "post_owner_restore"),
    ("POST", rf"/api/projects/{P}/owner/clashes/{P}", "post_owner_clash"),
    ("POST", rf"/api/projects/{P}/owner/take-back", "post_owner_take_back"),
    ("POST", rf"/api/projects/{P}/owner/refused/{P}/{P}/dismiss", "post_owner_refused_dismiss"),
    ("GET", rf"/api/projects/{P}/codebooks/{P}/offer", "get_codebook_offer"),
    ("POST", rf"/api/projects/{P}/codebooks/{P}/follow", "post_codebook_follow"),
] + api_corpus.ROUTES + api_checks_extra.ROUTES]
# 0.18 (L3): changes after which the poller does not bring a round forward (they are rounds, uploads, or its own)
NOT_A_CHANGE = {"post_choose_folder", "post_shared_folder_sync", "post_upload", "put_project_sync_poller", "post_project_sync_poller_seen"}
NOT_A_CHANGE |= api_corpus.NOT_A_CHANGE | api_checks_extra.NOT_A_CHANGE
DOWNLOADS = {"get_hypothesis_export", "get_export", "get_document_file", "get_project_zip", "get_annotated", "get_flexiconc",
             "get_page_image",  # 0.15: a picture of a page, in an <img>
             "get_annotated_zip", "get_search_export", "get_profile_export", "get_themes_export", "get_move_zip",
             "get_ai_sent_csv", "get_bibliography_export",
             "get_log_export", "get_notes_export", "get_codebook_csv"}  # 0.16
DOWNLOADS |= api_corpus.DOWNLOADS | api_checks_extra.DOWNLOADS
# (these may take the token as ?token=, for plain links)


class Handler(BaseHTTPRequestHandler, DocumentsApi, ExploreApi, ChecksApi, SetupApi, RecordApi, SharingApi,
              FolderApi, SpaceApi, PollerApi, OwnerApi, CorpusApi, ChecksExtraApi):
    app: App
    server_version = f"enlens/{__version__}"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet: the terminal shows only problems
        pass

    # -- plumbing --------------------------------------------------------------------------------
    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(status)
        # one header of each name: an endpoint's own (`extra`) takes the place of the default. Sent after it, as a
        # second header, `Cache-Control: private, max-age=3600` lost to `no-store`, so every picture of a page was
        # drawn again each time it was shown
        headers = {"Content-Type": ctype, "Content-Length": str(len(body)), "Cache-Control": "no-store",
                   "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"}
        headers.update(extra or {})
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _stream(self, path: Path, ctype: str, extra: dict | None = None, chunk: int = 1 << 16) -> None:
        """Send a file in chunks (never held in memory as a whole)."""
        size = path.stat().st_size
        self.send_response(200)
        headers = {"Content-Type": ctype, "Content-Length": str(size), "Cache-Control": "no-store",
                   "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}
        headers.update(extra or {})
        for k, v in headers.items():
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

    def _length(self) -> int:
        """The request body's length as the client gave it; what is no whole number, or below 0, is no body (a
        negative length read until the client hung up, and a word in its place stopped the request with an error
        the terminal printed)."""
        try:
            return max(0, int(self.headers.get("Content-Length") or 0))
        except ValueError:
            return 0

    def _body(self) -> dict:
        self._consumed = True
        n = self._length()
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
        n = self._length()
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
                        raise ApiError(401, "Missing or wrong token. Open ENLENS from its icon (or run enlens-gui).")
                    args = [unquote(g) for g in mt.groups()]
                    out = getattr(self, name)(*args, q=q) if isinstance(name, str) else name(self, *args, q=q)
                    if method != "GET" and args and path.startswith("/api/projects/") and path.count("/") > 3 \
                            and name not in NOT_A_CHANGE:  # 0.18 (L3): a change in the project: a round soon
                        self.app.poller.touched(args[0])
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
        except PermissionError as e:  # 0.16: a colleague's note or log entry, which only they can change
            self._json(403, {"error": str(e), "kind": "request"})
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
            frozen = self.app.frozen_static
            page = (frozen["index.html"] if frozen is not None else (STATIC / "index.html").read_bytes()).decode("utf-8")
            # 0.17.2: the page never carries the token (any local account can fetch it): it comes in the link the app
            # opens, or that the terminal shows (#token=)
            page = page.replace("{{ENLENS_RUN}}", self.app.run_id)
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
        frozen = self.app.frozen_static
        target = (STATIC / rel).resolve()
        if frozen is not None:  # 0.14.3: the files as they were when this copy started
            body = frozen.get(rel) if ".." not in rel.split("/") else None
            if body is None:
                raise ApiError(404, "Not found.")
        else:
            if not target.is_relative_to(STATIC.resolve()) or not target.is_file():
                raise ApiError(404, "Not found.")
            body = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "image/svg+xml"):
            ctype += "; charset=utf-8"
        self._send(200, body, ctype)

    # -- endpoints -------------------------------------------------------------------------------
    def post_restart(self, q):
        """0.13.1: stop the app and start the version on disk in its place, on the same port (the page reloads)."""
        self._body()
        if self.app.restart is None:
            raise ApiError(409, "This app was not started in a way that can restart itself. Stop it and start it again.")
        return {"restarting": True, "jobs_stopped": self._stop_jobs_then(self.app.restart)}

    def get_whats_new(self, q):
        """`{"note", "changes", "unread"}`. `note`: once, an update on Windows that did not finish (0.15.4,
        `"kind": "problem"`, update_note), else null. `changes` (after 0.17.2; until then `note` was this, shown once
        by itself): what is new in the running version, `{version, title, subtitle, points, url}`, or null; `unread`:
        an update brought it and this person has not opened it (never on a new installation)."""
        changes, unread = whats_new_note()
        return {"note": update_note(), "changes": changes, "unread": unread}

    def post_whats_new_read(self, q):
        """What's new was opened (after 0.17.2): `{"unread": false}`."""
        self._body()
        mark_whats_new_read()
        return {"unread": False}

    def get_update(self, q):
        """0.13.1: whether a newer ENLENS waits: the latest GitHub release (the one-line install), or new commits on
        the branch a git copy follows. A newer version already on disk (updated while this copy ran) counts.
        0.13.6: the page asks every two minutes; the answer (or the reason there is none) is kept for
        UPDATE_LOOK_EVERY seconds, so the open tabs share one look. `?fresh=1` (Settings → Check for updates) looks
        again now."""
        from .. import update as upd

        installed = _installed_version()
        if upd.version_tuple(installed) > upd.version_tuple(__version__):
            return {"available": True, "on_disk": True, "version": __version__, "latest": installed,
                    "candidate": upd.is_candidate(installed)}
        if self.app.updating.locked():  # 0.14.3: no `git fetch` beside the update's own git commands (lock files)
            seen = self.app.update_seen
            if seen and "answer" in seen:
                return {**seen["answer"], "updating": True}
            return {"available": True, "on_disk": False, "version": __version__, "latest": None, "changes": None,
                    "updating": True}
        with self.app.update_looking:
            seen = self.app.update_seen
            if _bool(q, "fresh") or not seen or time.time() - seen["at"] >= UPDATE_LOOK_EVERY:
                try:
                    r = upd.update(check_only=True, quick=True)
                    waiting = r.get("waiting")
                    seen = {"at": time.time(), "answer": {
                        "available": bool(waiting), "on_disk": False, "version": __version__,
                        "latest": waiting if isinstance(waiting, str) else None,
                        "changes": waiting if isinstance(waiting, int) else None,
                        "candidate": isinstance(waiting, str) and upd.is_candidate(waiting)}}
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
                cmd = handover_command(self.app)
                try:
                    r = upd.update(**({"restart": cmd, "token": self.app.token} if cmd else {}))
                except upd.UpdateError as e:
                    raise ApiError(409, str(e)) from e
            if not r.get("updated"):
                return {"updated": False, "restarting": False, "version": __version__}
            # 0.15.4: on Windows the install waits for this app to quit (handover.py), which then starts it again
            handover = bool(r.get("handover"))
            stopped = self._stop_jobs_then(self.app.stop if handover else self.app.restart)
            restarting = True
            return {"updated": True, "restarting": True, "handover": handover, "from": r.get("from", __version__),
                    "version": r["version"], "jobs_stopped": stopped}
        finally:
            if not restarting:  # kept while restarting: a second click must not update again
                self.app.updating.release()

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
            raise ApiError(409, "No Ollama is running on this computer just now. Open the Ollama app (or press Start "
                                "Ollama in Settings → AI) and try again.")
        return {"job": self.app.pull_models(models, srv["url"], use).view()}


# 0.13.6: how long a look for a newer version is kept (the page asks every 120 s; a little less, so each ask looks)
UPDATE_LOOK_EVERY = 100


def _installed_version() -> str:
    """0.10.2: the version now on disk. It differs from the running __version__ when ENLENS was updated (git pull,
    the install line, enlens update) while this copy kept running; the page then says to quit and reopen."""
    try:  # 0.18.1: the version is in the package's metadata (made from the tag), which is read afresh each time
        from importlib import metadata

        return metadata.version("enlens-claims")
    except Exception:  # noqa: BLE001 - not installed as a package: an older copy wrote it in __init__.py
        pass
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


class QuickServer(ThreadingHTTPServer):
    """A ThreadingHTTPServer that starts without looking up this computer's full name. Python's own server_bind asks
    for it (socket.getfqdn), which waits 35 s (70 s for 0.0.0.0) on a Mac whose name the network does not answer for
    (GitHub's Mac runners, 2026-11-12), and ENLENS never uses that name."""

    def server_bind(self) -> None:
        import socketserver

        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name, self.server_port = str(host), port


def make_server(host: str = "127.0.0.1", port: int = 8765, app: App | None = None) -> tuple[ThreadingHTTPServer, App]:
    """The server (not started) and its app. Port 0 picks a free port."""
    app = app or App()
    handler = type("BoundHandler", (Handler,), {"app": app})
    srv = QuickServer((host, port), handler)
    srv.daemon_threads = True
    real = srv.server_address[1]
    app.port = real
    app.allowed_hosts = {f"127.0.0.1:{real}", f"localhost:{real}", f"[::1]:{real}"}
    app.any_host = host not in ("127.0.0.1", "localhost", "::1")
    if app.any_host:
        import socket

        app.allowed_hosts |= {f"{h.lower()}:{real}" for h in (host, socket.gethostname()) if h and h not in ("0.0.0.0", "::")}
    return srv, app


RESTART_TOKEN = "ENLENS_RESTART_TOKEN"  # 0.17.2: the token a restart carries over (_restart, handover.py)


def carried_token() -> str | None:
    """The token of the copy this one restarts (after an update), taken out of the environment so the programs this
    copy starts do not inherit it. None on an ordinary start: every start has a new token."""
    tok = os.environ.pop(RESTART_TOKEN, "")
    return tok if re.fullmatch(r"[A-Za-z0-9_-]{32,}", tok) else None


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True, launcher: bool = False) -> int:
    """Run the app until Ctrl+C or "Quit ENLENS" (`POST /api/quit`). `launcher`: started from the ENLENS icon
    (see launcher.py): the address is recorded so a second double-click opens this one."""
    carried = carried_token()
    app = App(token=carried)
    for attempt in range(10):
        try:
            srv, app = make_server(host, port + attempt if port else 0, app)
            break
        except OSError:
            continue
    else:
        print(f"Ports {port} to {port + 9} are all in use. Choose another with --port.", file=sys.stderr)
        return 1
    if carried and port and app.port != port:
        # the open tabs keep the token for the address they were on; whatever answers there now (another program
        # took the port during the restart) must not find tabs that hold a token that works here
        app.token = secrets.token_urlsafe(24)
    app.launcher = launcher
    app.host = host
    app.freeze_static()
    app.stop = lambda: threading.Thread(target=srv.shutdown, daemon=True).start()
    again = threading.Event()

    def restart():  # 0.13.1: stop, then start the version on disk in this one's place (after serve_forever)
        again.set()
        app.stop()

    app.restart = restart
    url = f"http://{'127.0.0.1' if host in ('127.0.0.1', '0.0.0.0', '::') else host}:{srv.server_address[1]}/"
    from . import launcher as _l

    if launcher and host == "127.0.0.1":
        _l.write_info(url, srv.server_address[1])
    # 0.17.2: the page does not hand out the token: the browser opens this link, and the icon and the command line
    # find the token in a file only this account can read
    link = _l.link(url, app.token)
    try:
        _l.write_token(url, srv.server_address[1], app.token)
    except OSError as e:  # never in the way of starting: the link below still opens the app
        print(f"Could not write the token file: {e}", file=sys.stderr)
    # started from the icon, what is printed goes to a log file (launcher.log_to_file): the link with the token is
    # not written there
    print(f"ENLENS hypothesis checker {__version__} at {url if launcher else link}  (data folder: {home.home()})")
    if app.any_host:
        print("Warning: listening beyond this computer. Open the link above (it carries the access token); anyone "
              "with that link and access to this address can use the app and read your projects.", file=sys.stderr)
    print("Stop it with Quit ENLENS in the app." if launcher else "Stop it with Ctrl+C (or Quit ENLENS in the app).")
    threading.Thread(target=_repair_plugin, daemon=True, name="plugin-repair").start()
    ollama_setup.clear_downloads()   # 0.15.6: what an install cut short by quitting left behind (no job runs yet)
    threading.Thread(target=_repair_icons, daemon=True, name="icon-repair").start()
    if open_browser:
        threading.Timer(0.6, lambda: _l.browse(link)).start()
    app.poller.start()  # 0.18 (L3)
    try:
        srv.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        app.poller.stop()  # 0.18 (L3): no round starts once the app stops
        srv.server_close()
        if launcher:
            _l.clear_info()
        _l.clear_token(app.port)
    if again.is_set():
        _restart(restart_command(host, app.port, launcher), app.token)
    print("ENLENS stopped.")
    return 0


def restart_command(host: str, port: int, launcher: bool) -> list[str]:
    """0.13.1: how the app starts again after "Update and restart": the same Python (the update installed into it),
    address and port, no new browser tab (the open page reloads itself), and as the icon started it if it did."""
    cmd = [sys.executable, "-m", "enlens_claims.gui.launch", "--host", host, "--port", str(port), "--headless"]
    if launcher:
        cmd += ["--launcher", "--no-start-ollama"]  # Ollama, if it was needed, is running already
    return cmd


def handover_command(app: App) -> list[str] | None:
    """0.15.4: on Windows, the command handover.py starts the app again with after installing an update (as
    restart_command); None elsewhere, where the update installs in place and the app restarts itself."""
    return restart_command(app.host, app.port, app.launcher) if os.name == "nt" else None


def _restart(cmd: list[str], token: str | None = None) -> None:
    """Start the new version. On macOS and Linux this process becomes it (os.execv: same process, same terminal,
    same Ctrl+C); Windows has no real exec, so there the new one is started beside this one, which then ends. The
    data folder and local-only setting carry over in the environment (ENLENS_HOME, ENLENS_LOCAL_ONLY). 0.17.2: so does
    the token (RESTART_TOKEN), so the open tabs, which keep it, reach the new copy."""
    if token:
        os.environ[RESTART_TOKEN] = token
    print("Restarting ENLENS with the version now installed…", flush=True)
    from .. import ingest

    ingest.end_reading_processes()  # 0.16: os.execv runs no exit handlers, and the new version starts afresh
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except (OSError, ValueError):
        pass
    try:
        if os.name == "nt":
            import subprocess

            # console: the same Python: pythonw (the icon's) has none; python in a terminal writes on in it
            subprocess.Popen(cmd, close_fds=True)
            return
        os.execv(cmd[0], cmd)
    except OSError as e:
        print(f"Could not start ENLENS again ({e}). Open it again from its icon or with enlens-gui.", file=sys.stderr)
