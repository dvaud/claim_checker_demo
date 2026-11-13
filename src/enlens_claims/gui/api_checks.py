"""Checking: the endpoints of Handler for hypotheses and their checks, exports, bringing results in, the map,
calibration, the jobs, the queue and the Claude Code runs.

Split out of server.py in 0.16: `Handler` takes this class as a base, so the names in ROUTES
still resolve on it."""
from __future__ import annotations

import io
import json
import re
import time
from pathlib import Path

from .api_common import ApiError, XLSX, _csv, _disposition, _filename, _float, _str, _usable_embedder
from .. import claimcheck, home, sync, taskqueue
from ..llm import BackendError


class ChecksApi:
    def post_read_local(self, name, hyp_id, q):
        body = self._body()
        return {"job": self.app.start_read_local(name, hyp_id, force=bool(body.get("force"))).view()}

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

    def post_similar(self, name, q):
        """0.18 (roadmap N1): lines of the box that say nearly the same, and hypotheses checked before that do."""
        from .. import nearduplicates

        lines = self._body().get("lines")
        if not isinstance(lines, list) or not all(isinstance(x, str) for x in lines):
            raise ApiError(400, "lines must be a list of hypotheses.")
        if len(lines) > 500:
            raise ApiError(400, "At most 500 hypotheses per batch.")
        return nearduplicates.similar(self.app.ws(name), [x[:2000] for x in lines])

    def get_hypotheses(self, name, q):
        """The answers of the project. 0.18.1 (H5): with `offset` the rows come a page at a time (`limit` per page,
        100 when not given) and the answer says `total` (the rows after the filters), `offset` and `limit`; `counts`
        stay those of every hypothesis. Without `offset` the answer is what it always was (`limit` alone still cuts
        the list)."""
        if _str(q, "offset") is None:
            return self.app.hypotheses(name, q)
        offset = max(0, int(_float(q, "offset", 0)))
        limit = max(1, min(int(_float(q, "limit", 100)), 1000))
        whole = self.app.hypotheses(name, {k: v for k, v in q.items() if k not in ("offset", "limit")})
        rows = whole["hypotheses"]
        return {**whole, "hypotheses": rows[offset:offset + limit], "total": len(rows), "offset": offset, "limit": limit}

    def _has_hypothesis(self, project, hyp_id):
        try:
            return bool(self.app.ws(project).scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (hyp_id,)))
        except Exception:
            return False

    def get_hypothesis(self, name, hyp_id, q):
        ws = self.app.ws(name)
        if not ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (hyp_id,)):
            # 0.14.3: another window may have switched the project: say which project holds the result
            other = next((n for n in home.list_projects() if n != name and self._has_hypothesis(n, hyp_id)), None)
            raise ApiError(404, "No such result.", extra={"in_project": other} if other else None)
        s = self.app.settings()
        res = claimcheck.hypothesis_result(ws, hyp_id, _float(q, "threshold", s["threshold"]))
        from .. import runs  # 0.18.1 (J4.2): the version that started this check, on its own page

        res["made_with"] = runs.made_with_one(ws.scalar("SELECT app_version FROM hypotheses WHERE hyp_id=?", (hyp_id,)))
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

        router = routing.from_settings(s, large=s.get("ollama_model") or s.get("openai_model") or "")
        off = not s.get("routing", True) or s.get("backend") == "baseline"
        res["stronger_model"] = None if off else router.step_up("check")
        # 0.14.3: why there is none, for the page to say it right: "model_per_task_off" (the setting is off, or demo
        # mode), "top_model" (Claude already runs it on the strongest model), "one_local_model", or "none"
        res["stronger_reason"] = None if res["stronger_model"] else (
            "model_per_task_off" if off else "top_model" if router.route in ("claude_code", "anthropic")
            else "one_local_model" if router.route == "local" else "none")
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
        why = _str(q, "why") or self._body().get("why")
        claimcheck.delete_hypothesis(ws, hyp_id, why=str(why or "") or None)  # 0.16: the reason goes into the log
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
        """The whole project as one zip (see bundle.py), built in a temporary file and sent in chunks. 0.18:
        `?scope=shared` holds only what you shared, to send to a colleague (sharing.py)."""
        import tempfile

        from .. import bundle

        ws = self.app.ws(name)
        scope = _str(q, "scope") or "all"
        if scope not in bundle.SCOPES:
            raise ApiError(400, "scope is all (the whole project) or shared (what you shared).")
        tmp = Path(tempfile.mkdtemp(prefix="enlens-zip-"))
        try:
            out = tmp / "project.zip"
            bundle.export_project(ws, out, scope=scope)
            what = "ENLENS shared work" if scope == "shared" else "ENLENS project"
            fname = _filename(f"{what} - {name} - {time.strftime('%Y-%m-%d')}", "zip")
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
        from .api_owner import start_due  # 0.18 L2: a new reading the owner accepted is made here, in the queue

        try:
            start_due(self.app, name)
        except Exception:  # noqa: BLE001 - never the zip's fault: it is tried again after the next round or zip
            import traceback

            traceback.print_exc()
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
                # roles (DESIGN-roles §4.11, §5.5): it always asks first who this computer is. The upload waits under
                # a token for the answer (`post_move`)
                try:
                    peek = bundle.peek_move(path)
                except ValueError as e:
                    raise ApiError(400, str(e)) from e
                return {"move": peek, "token": _MOVES._keep(path)}
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

    def post_move(self, q):
        """roles (DESIGN-roles §4.11): the answer to a move zip's question, {token, mode: "moving" | "both", name,
        settings, servers: [setting keys]}. The upload is kept until it is brought in."""
        from .. import bundle

        body = self._body()
        token = str(body.get("token") or "")
        path = _MOVES._get(token)
        if path is None:
            raise ApiError(410, "The file is no longer here: choose it again.")
        servers = body.get("servers") or []
        if not isinstance(servers, list) or not all(isinstance(x, str) for x in servers):
            raise ApiError(400, "servers must be a list of setting names.")
        try:
            moved = bundle.import_all(path, str(body.get("mode") or ""), settings=bool(body.get("settings")),
                                      servers=servers, name=(str(body.get("name") or "").strip() or None))
        except ValueError as e:
            raise ApiError(400, str(e)) from e
        _MOVES._drop(token)
        return {"moved": moved, "project": self.app.project_summary(moved["current"]) if moved["current"] else None}

    def post_second_computer(self, q):
        """roles (DESIGN-roles §5.6): *Use both computers*: this computer becomes a person of its own, {name}."""
        from .. import people

        body = self._body()
        try:
            pid = home.new_identity(str(body.get("name") or ""))
        except ValueError as e:
            raise ApiError(400, str(e)) from e
        return {"person": {"id": pid, "name": people.my_name()}}

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

    def post_repeatable(self, q):
        from ..llm import repeatable

        self._body()
        be, model = self.app.backend()
        return {"model": model, **repeatable(be, model)}

    def put_judgement(self, name, claim_id, passage_id, q):
        body = self._body()
        verdict = body.get("verdict") or None
        extra = {"quote": body.get("quote")} if "quote" in body else {}
        if body.get("threshold") is not None:  # 0.18.1: the strictness the page shows, for the sentence of what moved
            try:
                extra["threshold"] = min(1.0, max(0.0, float(body["threshold"])))
            except (TypeError, ValueError):
                raise ApiError(400, "threshold must be a number from 0 to 1.") from None
        moved = claimcheck.set_judgement(self.app.ws(name), claim_id, passage_id, verdict, body.get("note"), **extra)
        # 0.18.1 (N4): the answer before and after, and the sentence naming this judgement when it moved the answer
        return {"saved": True, "verdict": verdict, "status_before": moved["before"], "status": moved["after"],
                "moved": moved["moved"]}

    def get_jobs(self, q):
        return {"jobs": self.app.job_views()}

    def get_job(self, job_id, q):
        return self.app.jobs.get(job_id).view()

    def post_cancel(self, job_id, q):
        job = self.app.jobs.get(job_id)
        self.app.jobs.cancel(job)  # 0.18 (M6): a job waiting for its turn leaves the queue at once
        return {"job": job.view(full=False)}

    def post_benchmark(self, q):
        return {"job": self.app.start_benchmark(self._body()).view()}

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
            # only the checks that wait for this kind, and none whose task a helper holds now (taskqueue.withdraw
            # leaves those tasks alone, so the check is left whole too)
            for hid in taskqueue.checks_waiting_on(ws, kind):
                if claimcheck.only_local_waits(ws, hid):
                    continue
                claimcheck.delete_hypothesis(ws, hid, unmade=True)
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
            self.app.ws(name)  # 404 for a project that does not exist
            self._release_run_claims(name, before["started_at"])
        return out


class _Uploads:
    """roles (DESIGN-roles §4.11): move zips waiting for the answer to their question, each under a random token, in a
    folder of their own; one not answered within an hour goes. (Its methods start with "_": an `api_*.py` class's
    public names are the endpoints' handlers, test_0_16_0_history.)"""

    TTL = 3600

    def __init__(self) -> None:
        import threading

        self._lock = threading.Lock()
        self._kept: dict[str, tuple[float, Path]] = {}

    def _keep(self, path: Path) -> str:
        import secrets
        import shutil
        import tempfile

        self._expire()
        token = secrets.token_urlsafe(16)
        folder = Path(tempfile.mkdtemp(prefix="enlens-move-wait-"))
        dest = folder / "move.zip"
        shutil.copyfile(path, dest)
        with self._lock:
            self._kept[token] = (time.time(), dest)
        return token

    def _get(self, token: str) -> Path | None:
        self._expire()
        with self._lock:
            hit = self._kept.get(token)
        return hit[1] if hit and hit[1].is_file() else None

    def _drop(self, token: str) -> None:
        import shutil

        with self._lock:
            hit = self._kept.pop(token, None)
        if hit:
            shutil.rmtree(hit[1].parent, ignore_errors=True)

    def _expire(self) -> None:
        now = time.time()
        with self._lock:
            old = [t for t, (at, _p) in self._kept.items() if now - at > self.TTL]
        for t in old:
            self._drop(t)


_MOVES = _Uploads()
