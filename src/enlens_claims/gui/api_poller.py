"""Near-live, and light (0.18, roadmap L3): the endpoints of Handler for the poller (gui/poller.py), which looks in each
project's shared folder every couple of minutes by itself. The Team tab shows its state: the next round, paused or not,
offline with its back-off, the last round, and what came in since the person last looked (with a way to mark it seen).

`Handler` takes this class as a base, so the names in ROUTES resolve on it."""
from __future__ import annotations

from .api_common import ApiError
from .. import home
from .poller import EVERY


class PollerApi:
    def get_sync_poller(self, q):
        """The whole app: {"every_minutes", "paused", "running", "projects": [each project with a shared folder]}."""
        return self.app.poller.overview()

    def put_sync_poller(self, q):
        """{"paused"?: bool, "every_minutes"?: 1–60}: pause (or resume) every project's rounds, and how often they come."""
        body = self._body()
        if "paused" in body and not isinstance(body["paused"], bool):
            raise ApiError(400, "Send {\"paused\": true} or {\"paused\": false}.")
        if "every_minutes" in body:
            v = body["every_minutes"]
            if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 60:
                raise ApiError(400, "every_minutes must be a whole number of minutes from 1 to 60.")
            home.update_settings({EVERY: v})
        if "paused" in body:
            self.app.poller.set_paused(None, body["paused"])
        return self.app.poller.overview()

    def get_project_sync_poller(self, name, q):
        """The project's poller state (docs/API.md)."""
        self.app.ws(name)  # 404 for a project that is not there
        return self.app.poller.state(name)

    def put_project_sync_poller(self, name, q):
        """{"paused": bool}: pause (or resume) this project's rounds on this computer. *Sync now* still works."""
        body = self._body()
        self.app.ws(name)
        if not isinstance(body.get("paused"), bool):
            raise ApiError(400, "Send {\"paused\": true} or {\"paused\": false}.")
        self.app.poller.set_paused(name, body["paused"])
        return self.app.poller.state(name)

    def post_project_sync_poller_seen(self, name, q):
        """{"through"?: id}: the person has seen what came in, up to that entry of `came_in.rounds` (all without it)."""
        body = self._body()
        through = body.get("through")
        if through is not None and (isinstance(through, bool) or not isinstance(through, int)):
            raise ApiError(400, "through must be the id of an entry of came_in.rounds.")
        self.app.poller.mark_seen(self.app.ws(name), through)
        return self.app.poller.state(name)
