"""Working together through a shared folder (0.18, roadmap L5): the endpoints of Handler for a project's shared folder
(sync/folder.py). The Team tab is built on them: choosing the folder, what it shows of each colleague, the switch for
documents marked Only a local AI or No AI, and *Sync now*, which runs as a job (one per project at a time).

`Handler` takes this class as a base, so the names in ROUTES resolve on it."""
from __future__ import annotations

from .api_common import ApiError
from .poller import TITLE, _round  # one round, by hand or by the poller, is the same job
from ..sync import cloud_folders, folder
from . import folder_picker


class FolderApi:
    def _folder_jobs(self, name: str) -> tuple[dict | None, dict | None]:
        """(the round running or waiting to run for the project, the last round done since the app started), as job
        views; the last one with its result (`folder.sync_now`'s report) or its error."""
        running = last = None
        for j in self.app.jobs.all():  # newest first
            if j.kind != folder.JOB or j.project != name:
                continue
            if j.state in ("queued", "running"):
                running = running or j.view()
            elif last is None:
                last = j.view()
        return running, last

    def _folder_status(self, name: str) -> dict:
        out = folder.status(self.app.ws(name))
        out["job"], out["last_round"] = self._folder_jobs(name)
        return out

    def get_shared_folder(self, name, q):
        """The project's shared folder and what is in it (`folder.status`), with the round running now, if any, and
        the last round's report."""
        return self._folder_status(name)

    def put_shared_folder(self, name, q):
        """Choose the shared folder: {"path", "keep_out"?}. 400 in plain words when it cannot be used (no such folder,
        not writable, inside the project's own folder). Without "keep_out" the project's switch stays as it is. The
        switch is turned on before the folder is chosen and off only after, so a round that falls due in between never
        runs with it off when it should be on."""
        body = self._body()
        ws = self.app.ws(name)
        keep = body.get("keep_out") if "keep_out" in body else None
        if keep:
            folder.set_keep_out(ws, True)
        try:
            folder.set_folder(ws, body.get("path"))
        except folder.FolderProblem as e:
            raise ApiError(400, str(e)) from e
        if keep is not None and not keep:
            folder.set_keep_out(ws, False)
        return self._folder_status(name)

    def delete_shared_folder(self, name, q):
        """Stop using the shared folder (nothing in it is removed; what came in stays)."""
        self._body()
        folder.clear_folder(self.app.ws(name))
        return self._folder_status(name)

    def put_shared_folder_keep_out(self, name, q):
        """The switch: {"keep_out": true} keeps documents marked Only a local AI or No AI out of the shared folder."""
        body = self._body()
        if not isinstance(body.get("keep_out"), bool):
            raise ApiError(400, "Send {\"keep_out\": true} or {\"keep_out\": false}.")
        folder.set_keep_out(self.app.ws(name), body["keep_out"])
        return self._folder_status(name)

    def post_shared_folder_sync(self, name, q):
        """*Sync now*: one round (bring in what colleagues wrote, write what changed) as a job. A round already
        running for the project is returned instead of a second one."""
        self._body()
        ws = self.app.ws(name)
        if folder.chosen(ws) is None:
            raise ApiError(400, "Choose a shared folder for this project first.")
        job = self.app.jobs.start(folder.JOB, TITLE, name, lambda job: _round(ws, job), uses_model=False, unique=True)
        return {"job": job.view()}

    # 0.18.0rc2 (L7): an easier shared folder
    def get_cloud_folders(self, q):
        """The cloud folders this computer has (OneDrive, Google Drive, Box, Dropbox...): {"folders": [{"name", "path",
        "service"}], "picker": whether this
        computer has a folder window to open (POST /api/choose-folder)}."""
        return {"folders": cloud_folders.offered(), "picker": folder_picker.available()}

    def get_shared_folder_find(self, name, q):
        """The shared folders among the cloud folders that already hold this project's team folder (a colleague set it
        up): {"found": [paths of the folders to choose], "team": the team folder's name}. Looks a few levels down for about two seconds at most."""
        team = folder.team_name(self.app.ws(name))
        return {"found": cloud_folders.find_team(team), "team": team}

    def post_choose_folder(self, q):
        """Open the system's folder picker and wait for it: {"prompt"?, "start"?} -> {"path": the folder or null (cancelled
        or no picker), "available": whether this computer has a picker}. 409 while another dialog is open."""
        body = self._body()
        if not folder_picker.available():
            return {"path": None, "available": False}
        prompt = body.get("prompt") if isinstance(body.get("prompt"), str) else ""
        start = body.get("start") if isinstance(body.get("start"), str) else None
        try:
            path = folder_picker.choose_folder(prompt.strip()[:200] or "Choose the shared folder", start)
        except folder_picker.Busy:
            raise ApiError(409, "A folder window is already open. Finish or close it first.") from None
        return {"path": path, "available": True}
