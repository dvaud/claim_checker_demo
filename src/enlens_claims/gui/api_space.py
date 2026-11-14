"""A storage space of the team's own (0.18.0rc2, roadmap L6): the endpoints of Handler for a project's storage space
(sync/space.py). The Team tab is built on them (views/team-space.js): the owner's set-up at Backblaze, Cloudflare or
the institution's drive over WebDAV (as a job: several calls to the service), invites, removing a colleague, moving
the team, and joining from a link, in a project of one's own or as a new project under Projects. What the space holds and each round's state come with
GET …/shared-folder (`folder.status`'s "space"), and *Sync now* is the folder's (one round is one job, either way).

`Handler` takes this class as a base, so the names in ROUTES resolve on it."""
from __future__ import annotations

import os

from .api_common import ApiError
from ..sync import folder, space

SETUP_JOB = "space-setup"
LINKS = {
    # roadmap L6a: the sign-up page opens from a plain link; the region is chosen on its form (EU Central)
    "b2_signup": "https://www.backblaze.com/sign-up/b2-cloud-storage-backup-archive",
    "b2_keys": "https://secure.backblaze.com/app_keys.htm",
    "b2_caps": "https://secure.backblaze.com/b2_caps_alerts.htm",
    # roadmap L6b: typed, not linked from a page (a link opened signed out led to an error on sign-up)
    "r2_signup": "https://dash.cloudflare.com/sign-up",
    "r2_dashboard": "https://dash.cloudflare.com/?to=/:account/r2/overview",
    # 14 November 2026: a drive over WebDAV (sync/webdav.py has the sources)
    "webdav_surfdrive": "https://surfdrive.surf.nl/files/remote.php/nonshib-webdav/",
    "webdav_nextcloud": "https://<host>/remote.php/dav/files/<user>/",
}


def _problem(e: space.SpaceProblem) -> ApiError:
    return ApiError(400, str(e), getattr(e, "kind", "request") or "request", getattr(e, "extra", None))


def _drive(body: dict) -> dict | None:
    """A colleague's own account at the team's drive, as the join dialog sends it ("confirmed": they said the drive
    at this address is their institution's, `space._drive_for_join`)."""
    d = body.get("drive")
    if not isinstance(d, dict):
        return None
    return {**{k: str(d.get(k) or "").strip() for k in ("user", "password", "address", "folder")},
            "confirmed": d.get("confirmed") is True}


class SpaceApi:
    def _space_status(self, name: str) -> dict:
        return self._folder_status(name)   # (api_folder.FolderApi: the folder's state, with "space")

    def get_space_links(self, q):
        """The pages the owner opens during the set-up (the services' own sign-up and key pages)."""
        from ..sync import r2

        return {**LINKS, "r2_token": getattr(r2, "TOKEN_LINK", None)}

    def _setup_job(self, name: str, title: str, fn):
        ws = self.app.ws(name)

        def run(job):
            def progress(step, message, info):
                job.progress = {"step": step, "message": message, **(info or {})}
            return fn(ws, progress)   # (a SpaceProblem is a ValueError: the job's error, in its own words)

        job = self.app.jobs.start(SETUP_JOB, title, name, run, uses_model=False, unique=True, lane="sync")
        return {"job": job.view()}

    def post_space_b2(self, name, q):
        """The owner's set-up at Backblaze B2: {"key_id", "app_key"} (a master application key, kept only until
        ENLENS has made a key of its own). A job; its result is the space's state, with "warnings"."""
        body = self._body()
        key_id, app_key = str(body.get("key_id") or "").strip(), str(body.get("app_key") or "").strip()
        if not key_id or not app_key:
            raise ApiError(400, "Paste both the keyID and the applicationKey that Backblaze showed.")
        self._not_set_up(name)
        return self._setup_job(name, "Setting up the storage space at Backblaze",
                               lambda ws, progress: space.setup_b2(ws, key_id, app_key, progress))

    def post_space_r2(self, name, q):
        """The owner's set-up at Cloudflare R2: {"token", "account_id"?}. A job; when the token reaches several
        accounts and none is named, its result has "accounts" to choose from (nothing is set up)."""
        body = self._body()
        token = str(body.get("token") or "").strip()
        account = str(body.get("account_id") or "").strip() or None
        if not token:
            raise ApiError(400, "Paste the token Cloudflare showed after Create Token.")
        self._not_set_up(name)
        return self._setup_job(name, "Setting up the storage space at Cloudflare",
                               lambda ws, progress: space.setup_r2(ws, token, account, progress))

    def post_space_webdav(self, name, q):
        """The owner's set-up in the institution's drive over WebDAV: {"address", "user", "password"} (an app
        password, kept in the keychain). A job; its result is the space's state, with "warnings"."""
        body = self._body()
        address, user = str(body.get("address") or "").strip(), str(body.get("user") or "").strip()
        password = str(body.get("password") or "").strip()
        if not address or not user or not password:
            raise ApiError(400, "Enter the drive's WebDAV address, your user name there and an app password.")
        self._not_set_up(name)
        return self._setup_job(name, "Setting up the storage space in your drive",
                               lambda ws, progress: space.setup_webdav(ws, address, user, password, progress))

    def put_space_drive_password(self, name, q):
        """A new app password for the drive: {"user", "password"}; checked before it is kept."""
        body = self._body()
        try:
            space.set_drive_password(self.app.ws(name), str(body.get("user") or ""), str(body.get("password") or ""))
        except space.SpaceProblem as e:
            raise _problem(e) from e
        return self._space_status(name)

    def post_space_peek(self, q):
        """What an invite link is for, before joining: {"link"} → {"service", "host", "folder", "address", "known",
        "project", "from"} (no keys; `space.peek`)."""
        try:
            return space.peek(str(self._body().get("link") or ""))
        except space.SpaceProblem as e:
            raise _problem(e) from e

    def post_space_dir(self, name, q):
        """A space in a folder on this computer, sealed as at a service: for trying the Team tab without an account
        (ENLENS_TRY_SPACES=1 only)."""
        if os.environ.get("ENLENS_TRY_SPACES") != "1":
            raise ApiError(404, "Not found.")
        body = self._body()
        self._not_set_up(name)
        try:
            space.setup_dir(self.app.ws(name), str(body.get("path") or ""))
        except (space.SpaceProblem, OSError) as e:
            raise ApiError(400, str(e)) from e
        return self._space_status(name)

    def _not_set_up(self, name: str) -> None:
        if space.configured(self.app.ws(name)) is not None:
            raise ApiError(409, "This project has a storage space already. To use another one, choose Move to another "
                                "storage space.")

    def post_space_invites(self, name, q):
        """*Invite a colleague*: {"label"?, "drive_user"?} → {"link", "message", "part", "status"}; in a drive also
        "shared" and "share_note" (`space.invite`). The owner's copy only."""
        body = self._body()
        try:
            out = space.invite(self.app.ws(name), str(body.get("label") or "") or None,
                               str(body.get("drive_user") or "").strip() or None)
        except space.SpaceProblem as e:
            raise _problem(e) from e
        return {**out, "status": self._space_status(name)}

    def delete_space_invite(self, name, part, q):
        """Withdraw an invite not used yet: its storage keys are deleted."""
        try:
            out = space.cancel_invite(self.app.ws(name), part)
        except space.SpaceProblem as e:
            raise _problem(e) from e
        return {**self._space_status(name), "warnings": (out or {}).get("warnings") or []}

    def delete_space_member(self, name, part, q):
        """Remove a colleague from the storage space (their keys go; the project's key is replaced)."""
        try:
            out = space.remove_member(self.app.ws(name), part)
        except space.SpaceProblem as e:
            raise _problem(e) from e
        return {**self._space_status(name), "warnings": (out or {}).get("warnings") or []}

    def post_space_move(self, name, q):
        """*Move to another storage space*: {"service": "b2", "key_id", "app_key"}, {"service": "r2", "token",
        "account_id"?} or {"service": "webdav", "address", "user", "password"}. A job; its result says how many
        colleagues were told where the team went."""
        body = self._body()
        service = body.get("service")
        if service == "b2":
            key_id, app_key = str(body.get("key_id") or "").strip(), str(body.get("app_key") or "").strip()
            if not key_id or not app_key:
                raise ApiError(400, "Paste both the keyID and the applicationKey that Backblaze showed.")
            start = lambda w, ident: space.setup_b2(w, key_id, app_key, ident=ident)   # noqa: E731
        elif service == "r2":
            token = str(body.get("token") or "").strip()
            account = str(body.get("account_id") or "").strip() or None
            if not token:
                raise ApiError(400, "Paste the token Cloudflare showed after Create Token.")
            start = lambda w, ident: space.setup_r2(w, token, account, ident=ident)   # noqa: E731
        elif service == "webdav":
            address, user = str(body.get("address") or "").strip(), str(body.get("user") or "").strip()
            password = str(body.get("password") or "").strip()
            if not address or not user or not password:
                raise ApiError(400, "Enter the drive's WebDAV address, your user name there and an app password.")
            start = lambda w, ident: space.setup_webdav(w, address, user, password, ident=ident)   # noqa: E731
        else:
            raise ApiError(400, "Choose Backblaze, Cloudflare or your institution's drive.")
        return self._setup_job(name, "Moving the team to another storage space",
                               lambda ws, progress: space.move(ws, start))

    def delete_space(self, name, q):
        """Stop using the storage space on this computer (nothing in it is removed; what came in stays)."""
        space.leave(self.app.ws(name))
        return self._space_status(name)

    def post_space_join(self, name, q):
        """Join a team's storage space from an invite link, in this project: {"link", "drive"?} ("drive": in a team
        that works in a drive, {"user", "password", "address"?, "folder"?}; without it such a link answers with kind
        "drive_needed", and "folder_not_found" carries "folders" to choose from)."""
        body = self._body()
        ws = self.app.ws(name)
        if space.configured(ws) is not None:
            raise ApiError(409, "This project works through a storage space already.")
        try:
            space.join(ws, str(body.get("link") or ""), _drive(body))
        except space.SpaceProblem as e:
            raise _problem(e) from e
        return self._space_status(name)

    def post_join_team(self, q):
        """*Join a team* under Projects: {"link", "name"?, "drive"?} → {"project"}: a new project, joined to the team's
        storage space; its first round brings the team's shared work and documents. "drive": as for …/space/join."""
        body = self._body()
        try:
            project = space.join_new_project(str(body.get("link") or ""), str(body.get("name") or "") or None,
                                             _drive(body))
        except space.SpaceProblem as e:
            raise _problem(e) from e
        except ValueError as e:
            raise ApiError(400, str(e)) from e
        from .. import home

        home.update_settings({"project": project})   # (the current project, as after Import a project)
        poller = getattr(self.app, "poller", None)
        if poller is not None and hasattr(poller, "touched"):
            poller.touched(project)
        return {"project": project}
