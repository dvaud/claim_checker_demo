"""The task queue of the app (App's 0.8 section: Claude Code works through it).

Split out of server.py in 0.16: `App` takes this class as a base; the public methods are the same."""
from __future__ import annotations

import re
from pathlib import Path

from .api_common import ONE_START, ApiError, Cancelled, Job, _body_int, _bool, _list, _str, benchmark_table
from .progress import Tracker
from .. import addons, claimcheck, frameworks, home, runs as runs_mod, taskqueue, tasks as tasks_mod
from ..claude_setup import setup_info as claude_setup_info
from ..llm import BackendError


class QueueMixin:
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
        # 0.18.1 (N2): how much thought Claude gives the tasks, chosen beside Start Claude Code and kept
        out["thought"] = {"chosen": self.settings().get("claude_thought") or "balanced",
                          "options": dict(taskqueue.routing.THOUGHT_TITLES)}
        out["runner"] = claude_setup.run_state(name)
        out["at_limit"] = self._at_limit(name, ws, out["runner"])  # 0.18.1 (I4)
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
            # 0.16: notes, the research log, your own codebooks
            "notes": n("SELECT COUNT(*) FROM notes"),
            "log": n("SELECT COUNT(*) FROM research_log"),
            "codebooks": sum(1 for f in frameworks.available(ws).values() if f.source != "bundled"),
            "waiting": (self._queue_summary(name) or {}).get("waiting", 0),
            # 0.15 (J4.2): which ENLENS version made what, so the page can say what came from an older one
            "made_with": runs_mod.made_with(ws),
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

    # -- 0.18.1 (I1, I4): the local model's share of the queue ---------------------------------------------------
    def _local_queue_job(self, name: str, what: str, kinds: list[str] | None = None, background: bool = False) -> Job:
        """A job in which the local model (Settings' local model for restricted documents) answers the queue's tasks
        here: `what` "mix" (the kinds the AI mix gives it first, unsure ones going up to Claude) or "limit" (every
        waiting task, after Claude Code reached the plan's usage limit)."""
        from .. import access

        ws = self.ws(name)

        def run(job: Job):
            job.progress = {"done": 0, "total": 0}
            prog = lambda d, n: job.progress.update(done=d, total=n)  # noqa: E731
            readers = access.Readers(None, "", should_stop=job.cancel.is_set)
            got = readers.local()
            if got is None:
                raise ApiError(400, readers.local_problem or "No local model is chosen in Settings → AI.")
            try:
                if what == "mix":
                    return tasks_mod.answer_mix_waiting(ws, got[0], got[1], should_stop=job.cancel.is_set,
                                                        progress=prog)
                return taskqueue.run_here(ws, got[0], kinds, should_stop=job.cancel.is_set, progress=prog,
                                          model=got[1])
            finally:
                taskqueue.advance(ws)
                claimcheck._let_go(readers)

        title = ("Your local model answers its share of the queue" if what == "mix" else
                 "Your local model answers the queue while Claude Code waits for the plan's limit")
        return self.jobs.start(f"queue-local-{what}", title, name, run, uses_model=True, unique=True,
                               background=background)

    def _at_limit(self, name: str, ws, runner: dict) -> dict | None:
        """0.18.1 (I4): whether Claude Code, started from the app, stopped at the plan's usage limit, and what happens
        now, as the person chose (Settings' at_limit): the queue waits for the next start, or the local model answers
        what waits (started once per stop)."""
        said = taskqueue.limit_reached(runner)
        if not said:
            return None
        s = self.settings()
        choice = s.get("at_limit") or "wait"
        local = bool(s.get("restricted_server") and s.get("restricted_model")) and not home.local_only()
        out = {"said": said, "choice": choice, "local_possible": local, "started": False}
        key = f"{runner.get('started_at')}"
        if choice == "local" and local and ws.meta("limit_handled") != key and taskqueue.status(ws, name)["waiting"]:
            ws.set_meta("limit_handled", key)  # once per stop of Claude Code, even if the job is stopped
            self._local_queue_job(name, "limit", background=True)
            out["started"] = True
        return out

    def start_queue_run(self, name: str, body: dict) -> Job:
        """Answer what waits in the queue here, with the AI model of Settings (a local server or the Claude API),
        kind by kind. 0.18.1: with Claude Code in Settings, the local model answers here what the AI mix gives it
        first (`{"local": "mix"}`, the default), or every waiting task it may (`{"local": "all"}`, as at the plan's
        limit)."""
        ws = self.ws(name)
        if self.queue_mode():
            what = "limit" if body.get("local") == "all" else "mix"
            if what == "mix" and not taskqueue.mix_kinds():
                raise ApiError(400, "Settings name Claude Code: it answers the queue itself. Choose a mix of local "
                                    "and Claude in Settings → AI, or another AI model, to answer it here.")
            kinds = [k for k in (body.get("kinds") or []) if k in taskqueue.KINDS] or None
            return self._local_queue_job(name, what, kinds)
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
        pids = body.get("passage_ids")  # 0.16: only these passages (a code labelled again after its wording changed)
        if pids is not None and not (isinstance(pids, list) and all(isinstance(p, str) for p in pids)):
            raise ApiError(400, "passage_ids must be a list of passage ids.")
        job = self._model_job("label", f"The AI labels passages ({fw})", name, lambda job, be, model, prog:
                               profile.run_labels(ws, fw, be, model, docs, bool(body.get("all_passages")), limit,
                                                  progress=prog, should_stop=job.cancel.is_set, passage_ids=pids))
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

        return self.jobs.start("terms", "Building the glossary", name, run, uses_model=False, unique=True)

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
        # 0.18 (M6): one at a time per set of themes (two would take the same passages): a second waits its turn
        # (`serial`) instead of being refused; the same removed theme asked for again gets the job already there
        words = {"vectors": "reading the passages", "search": "looking where a new theme fits",
                 "name": "naming it by its key terms"}

        def run(job: Job):
            if ws.scalar("SELECT 1 FROM themes WHERE run_id=? AND replaces=?", (run_id, replaces)):
                raise ValueError("A new theme was found in place of this one already.")
            job.progress = {"done": 0, "total": 0, "phase": "vectors", "message": words["vectors"]}
            tid = themes.new_theme(ws, run_id, replaces, progress=lambda phase, d, n: job.progress.update(
                phase=phase, done=d, total=n, message=words.get(phase, "")), should_stop=job.cancel.is_set)
            return {"theme_id": tid, "replaces": replaces}

        with ONE_START:
            same = [j for j in self.jobs.all() if j.kind == "theme-new" and j.project == name and j.scope == run_id
                    and j.state in ("queued", "running") and getattr(j, "replaces", None) == replaces]
            if same:
                return same[0]
            job = self.jobs.start("theme-new", "Finding a new theme", name, run, uses_model=False, scope=run_id,
                                  serial=f"theme-new:{run_id}")
            job.replaces = replaces
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
