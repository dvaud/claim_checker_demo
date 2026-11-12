"""Setting up: the endpoints of Handler for the state, settings and keys, quitting, the model servers, Ollama,
Claude Code setup, the bibliography (Zotero or a file) and moving to another computer.

Split out of server.py in 0.16: `Handler` takes this class as a base, so the names in ROUTES
still resolve on it."""
from __future__ import annotations

import io
import sys
import threading
import time
from pathlib import Path

from .api_common import ApiError, Job, XLSX, _csv, _disposition, _filename, _int, _str
from .. import access, bibliography, claimcheck, home, ollama_setup, taskqueue
from ..claude_setup import setup_info as claude_setup_info


class SetupApi:
    def get_state(self, q):
        return self.app.state()

    def put_settings(self, q):
        body = self._body()
        s = home.update_settings(body)
        if "update_channel" in body:
            self.app.update_seen = None  # 0.15: another channel, another answer: the next look asks again
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
        poller = getattr(self.app, "poller", None)
        if poller is not None:  # 0.18 (L3): no round of the shared folder starts while the app stops (one being
            poller.stop(wait=0)  # started now is listed below, so it is stopped and waited for with the others)
        running = [j for j in self.app.jobs.all() if j.state in ("queued", "running")]
        for j in running:
            self.app.jobs.cancel(j)  # 0.18 (M6): the jobs waiting for their turn leave at once
        self._stop_claude_runs()

        def later():
            t0 = time.time()
            time.sleep(0.4)
            while any(j.state in ("queued", "running") for j in running) and time.time() - t0 < 20:
                time.sleep(0.2)
            finish()

        threading.Thread(target=later, daemon=True).start()
        return len(running)

    def _stop_claude_runs(self) -> None:
        """0.14.3: Claude Code runs started from the app live in their own session, so they outlive it: stop them
        before the app quits or restarts (a run left behind keeps using the researcher's Claude plan, and the next app
        could not stop it). The batches they had taken go back to the queue, as Stop does."""
        from .. import claude_setup

        try:
            stopped = claude_setup.stop_all_runs()
        except Exception as e:  # noqa: BLE001 - never in the way of quitting
            print(f"Could not stop Claude Code: {e}", file=sys.stderr)
            return
        for r in stopped:
            self._release_run_claims(r["project"], r["started_at"])

    def _release_run_claims(self, name: str, started_at: str) -> None:
        """The batches a stopped run had taken go back to the queue at once instead of after 30 minutes."""
        if not started_at:
            return
        try:
            ws = self.app.ws(name)
            for c in ws.query("SELECT claim_id, claimed_at FROM task_claims WHERE finished_at IS NULL"):
                if str(c["claimed_at"] or "") >= started_at:
                    try:
                        taskqueue.release(ws, c["claim_id"])
                    except Exception:  # noqa: BLE001
                        pass
        except Exception:  # noqa: BLE001 - e.g. the project was removed meanwhile
            pass

    def get_technical_details(self, q):
        """0.15: `{"text": "..."}`, a short block for a problem report: version, how installed, system, Python, AI
        route, --local-only, update channel. No path, project or document name, user name or key."""
        from .. import installation

        return {"text": installation.technical_details()}

    def get_servers(self, q):
        return self.app.servers()

    def post_test(self, q):
        return self.app.test_backend()

    def get_ollama(self, q):
        """0.15.6: before Ollama is installed from the app: how big the download is on this kind of computer, the free
        space it needs and the free space there is (asks ollama.com for the size)."""
        return ollama_setup.plan()

    def post_ollama_install(self, q):
        """0.15.6: install Ollama (a job; Windows and macOS), after the person saw the size; on Linux, open a terminal
        window running Ollama's own line ({"terminal": ...}). Ollama on this computer already is started instead."""
        self._body()
        running = self.app.ollama_install_job()
        if running:
            return {"job": running.view()}
        st = ollama_setup.status()
        if st["how"] == "terminal" and not st["installed"]:
            return {"terminal": ollama_setup.open_terminal()}
        if st["installed"] and st["how"] == "terminal":
            return self._start_ollama()
        return {"job": self.app.install_ollama().view()}

    def post_ollama_start(self, q):
        """0.15.6: start the Ollama that is on this computer (hidden; the page notices it within a few seconds). While
        an install runs, its job instead: Ollama's files are still being written, and the installer starts it itself."""
        self._body()
        running = self.app.ollama_install_job()
        if running:
            return {"job": running.view()}
        return self._start_ollama()

    def _start_ollama(self) -> dict:
        """0.18.0rc2: also what the card does by itself when Ollama is on the computer but does not answer, so a second
        call while it starts, or one when it already answers, starts nothing."""
        try:
            return ollama_setup.start_once((self.app.settings().get("ollama_url") or "").strip() or None)
        except ValueError as e:
            raise ApiError(409, str(e)) from e

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
