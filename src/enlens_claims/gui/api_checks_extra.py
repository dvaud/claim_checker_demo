"""0.18.1 part B (the AI mix, checks and retractions): the endpoints of Handler that part adds, kept out of
server.py so the two parts of 0.18.1, built side by side, never edit the same lines.


`Handler` takes this class as a base, so the names in ROUTES resolve on it. server.py adds ROUTES after its own
(the first pattern that matches wins), DOWNLOADS to the routes that may take the token as ?token=, and NOT_A_CHANGE to
the changes after which the shared folder's poller does not bring a round forward."""
from __future__ import annotations

from .api_common import ApiError, _body_int, _int, _str
from .. import benchmark, claimcheck, home, retractions

P = r"([^/]+)"  # one path segment, as in server.py

# (method, pattern without ^ and $, handler name), e.g. ("GET", rf"/api/projects/{P}/…", "get_…")
ROUTES: list[tuple[str, str, str]] = [
    # B5: retractions and corrections, looked up in Crossref when the person asks
    ("GET", rf"/api/projects/{P}/retractions", "get_retractions"),
    ("POST", rf"/api/projects/{P}/retractions/check", "post_retractions_check"),
    # I5: the local model and Claude answer the same sample; Cohen's kappa per kind of task
    ("GET", rf"/api/projects/{P}/agreement/plan", "get_agreement_plan"),
    ("POST", rf"/api/projects/{P}/agreement", "post_agreement"),
]
DOWNLOADS: set[str] = set()
NOT_A_CHANGE: set[str] = {"post_retractions_check", "post_agreement"}  # a lookup is not a change of the work a team shares


class ChecksExtraApi:
    def get_retractions(self, name, q):
        """What the last lookups found (`retractions.status`) and what a new one would do: {"plan": {"ask", "no_ai"
        (counts)}, ...status}."""
        ws = self.app.ws(name)
        p = retractions.plan(ws)
        return {**retractions.status(ws), "plan": {"ask": len(p["ask"]), "no_ai": len(p["no_ai"])}}

    def post_retractions_check(self, name, q):
        """*Check for retractions*: a lookup of the DOIs in Crossref, as a job (one per project at a time). Refused
        under local-only, and when there is no DOI to ask about."""
        self._body()
        ws = self.app.ws(name)
        if home.local_only():
            raise ApiError(400, "Online lookups are off on this computer (local-only), so nothing was sent.")
        if not retractions.plan(ws)["ask"]:
            raise ApiError(400, "There is no DOI to look up: the works of the bibliography and the documents have none, "
                                "or their documents are marked No AI.")

        def run(job):
            def progress(**kw):
                job.progress = kw
            return retractions.lookup(ws, progress=progress, should_stop=job.cancel.is_set)

        job = self.app.jobs.start("retractions", "Checking for retractions", name, run, uses_model=False, unique=True)
        return {"job": job.view()}


    # -- I5: agreement between routes -------------------------------------------------------------------------------
    def _agreement_ready(self) -> str | None:
        """Why an agreement run cannot start (a sentence), or None: it needs Claude as the main route and a local
        model in Settings, and nothing may be local-only."""
        s = self.app.settings()
        if home.local_only():
            return "This installation keeps everything on this computer (local only): Claude is never asked here."
        if s.get("backend") not in ("claude_code", "anthropic"):
            return "Choose Claude Code or the Claude API as the main AI in Settings → AI first."
        if not (s.get("restricted_server") and s.get("restricted_model")):
            return "Choose a local model in Settings → AI first."
        return None

    def get_agreement_plan(self, name, q):
        """What *Compare the routes* would do: {"kinds": [{kind, answered, name, noun}] (the kinds with a decision to
        compare and answered tasks), "problem": why it cannot start or null, and with `kind` (and `n`, 10 to 100,
        default 30) "plan": {kind, n, ask_local, ask_claude, left_out}}. Answers a task already has are reused."""
        ws = self.app.ws(name)
        kinds = benchmark.agreement_kinds(ws)
        out = {"kinds": kinds, "problem": self._agreement_ready(), "plan": None,
               "claude": self.app.settings().get("backend")}
        kind = _str(q, "kind")
        if kind:
            if kind not in [k["kind"] for k in kinds]:
                raise ApiError(400, "There is no decision to compare for this kind of task, or no task of it is answered yet.")
            out["plan"] = benchmark.agreement_plan(ws, kind, _int(q, "n", 30, 10, 100))
        return out

    def post_agreement(self, name, q):
        """*Compare the routes*, as a job: `{"kind", "n"}`. The local model and Claude answer a sample of answered
        tasks of that kind (Claude only those whose documents it may read); the job's result is
        `benchmark.agreement`'s: {kind, n, compared, failed, kappa, agree, verdict, left_out, asked, items, ...}.
        Nothing is stored in the project; Claude Code's share uses the plan."""
        body = self._body()
        ws = self.app.ws(name)
        problem = self._agreement_ready()
        if problem:
            raise ApiError(400, problem)
        kind = str(body.get("kind") or "")
        if kind not in [k["kind"] for k in benchmark.agreement_kinds(ws)]:
            raise ApiError(400, "There is no decision to compare for this kind of task, or no task of it is answered yet.")
        n = _body_int(body, "n", 30, 10, 100)

        def run(job, be, model, prog):
            from .. import access

            readers = access.Readers(None, "", should_stop=job.cancel.is_set)
            try:
                got = readers.local()
                if got is None:
                    raise ApiError(400, readers.local_problem or "No local model is chosen in Settings → AI.")
                return benchmark.agreement(ws, kind, n, got, be, progress=prog, should_stop=job.cancel.is_set,
                                           claude_model=None if self.app.queue_mode() else model)
            finally:
                claimcheck._let_go(readers)

        job = self.app._model_job("agreement", f"Comparing the local model with Claude on {n} {kind} tasks", name, run)
        return {"job": job.view()}
