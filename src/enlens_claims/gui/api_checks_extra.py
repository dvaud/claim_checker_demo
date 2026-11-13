"""0.18.1 part B (the AI mix, checks and retractions): the endpoints of Handler that part adds, kept out of
server.py so the two parts of 0.18.1, built side by side, never edit the same lines.


`Handler` takes this class as a base, so the names in ROUTES resolve on it. server.py adds ROUTES after its own
(the first pattern that matches wins), DOWNLOADS to the routes that may take the token as ?token=, and NOT_A_CHANGE to
the changes after which the shared folder's poller does not bring a round forward."""
from __future__ import annotations

from .api_common import ApiError
from .. import home, retractions

P = r"([^/]+)"  # one path segment, as in server.py

# (method, pattern without ^ and $, handler name), e.g. ("GET", rf"/api/projects/{P}/…", "get_…")
ROUTES: list[tuple[str, str, str]] = [
    # B5: retractions and corrections, looked up in Crossref when the person asks
    ("GET", rf"/api/projects/{P}/retractions", "get_retractions"),
    ("POST", rf"/api/projects/{P}/retractions/check", "post_retractions_check"),
]
DOWNLOADS: set[str] = set()
NOT_A_CHANGE: set[str] = {"post_retractions_check"}  # a lookup is not a change of the work a team shares


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
