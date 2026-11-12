"""Near-live, and light (0.18, roadmap L3): each copy looks in the shared folder for new shared work every couple of
minutes, by itself.

One thread in the app's server process wakes every few seconds and, for each project whose round is due, starts one
round of the shared folder (`folder.sync_now`) as an ordinary job of kind `folder.JOB`, marked `background`. It holds no
connection to anything between rounds and runs no process of its own: a round is the same job *Sync now* starts.

When a round is due:
- about 15 seconds after the app starts, then every `sync_every_minutes` (Settings, default 2) after the last round
  ended (a round by hand counts too);
- about 20 seconds after the last change made through the app in the project (any POST, PUT or DELETE under
  /api/projects/<p>/, such as sharing or unsharing, and the end of any other job of the project), so sharing reaches
  colleagues soon; the wait starts again with each change, so typing never sets a round off;
- never while paused (`sync_paused` for the whole app, `sync_paused_projects` per project), never for a project without
  a shared folder, never two at once for one project (one job per project, `unique`), and never beside a job it may not
  run beside (adding documents, the new reader, another round: api_common.LANES): then the round waits, without
  queueing a job, and starts at the first look after that job ended (state "busy").

Offline: a round whose problems are all `unreachable` (the drive is not connected, the folder was moved) means the
folder cannot be reached. The next try waits twice as long each time (2, 4, 8, 16, then 30 minutes with the default
interval) and changes in the project do not bring it forward; the first round that reaches the folder brings the
normal interval back.

What came in: every merge from the folder is kept in the project's `sync_log` (with `via: "folder"`, as sync.merge
writes it), so "what came in since the person last looked" is the folder's entries after the mark kept in the project's
`meta` (`sync_came_in_seen`, this copy's only: `meta` never goes to a colleague). It survives a restart.

Tests drive it without a thread and without real minutes: `Poller(app, clock=…, wall=…)` and `step()`.
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Callable

from .. import home
from ..sync import folder
from .api_common import Job

TICK = 5.0              # seconds between two looks of the thread
START_DELAY = 15.0      # the first round, after the app starts
DEBOUNCE = 20.0         # a round after the last change made in the project
MAX_BACKOFF = 30 * 60   # offline: the longest wait between two tries (unless the interval itself is longer)
TITLE = "Working together: the shared folder"   # as api_folder names a round by hand
SEEN = "sync_came_in_seen"                       # meta: the last sync_log entry the person has seen
EVERY = "sync_every_minutes"
PAUSED = "sync_paused"
PAUSED_PROJECTS = "sync_paused_projects"
ROUNDS_SHOWN = 30                                # came_in.rounds: at most this many, newest first


def _iso(t: float | None) -> str | None:
    if t is None:
        return None
    return datetime.fromtimestamp(t, timezone.utc).replace(microsecond=0).isoformat()


def _int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _n(v: Any) -> int:
    return len(v) if isinstance(v, (list, tuple, dict)) else _int(v)


def things(report: dict | None) -> int:
    """How many things a merge brought in, for a count to show: new and updated documents, results, sets of themes and
    codebooks, judgements, notes and research log entries, items their owner withdrew, and sync clashes (not labels,
    links or other rows, which come by the hundred and say little on their own)."""
    if not isinstance(report, dict):
        return 0
    d, c, t = report.get("documents") or {}, report.get("checks") or {}, report.get("themes") or {}
    cb, sh = report.get("codebooks") or {}, report.get("shares") or {}
    return (_n(d.get("new")) + _n(d.get("clash")) + _n(d.get("other_reading"))
            + _n(c.get("new")) + _n(c.get("updated")) + _n(c.get("clash"))
            + _n(t.get("new")) + _n(t.get("updated")) + _n(t.get("clash"))
            + _n(cb.get("new")) + _n(cb.get("updated")) + _n(cb.get("merged")) + _n(cb.get("clash"))
            + _n(report.get("judgements")) + _n(report.get("notes")) + _n(report.get("log")) + _n(sh.get("withdrawn")))


def offline(result: Any) -> bool:
    """A round whose problems are all `unreachable`, and the folder itself among them (a problem of no colleague's):
    the folder could not be reached. One colleague's file that could not be read is not the folder away: the next
    round tries again at the usual pace."""
    probs = result.get("problems") if isinstance(result, dict) else None
    return bool(probs) and all(isinstance(x, dict) and x.get("kind") == "unreachable" for x in probs) and \
        any(not x.get("person") for x in probs)


def _round(ws, job: Job) -> dict | None:
    """One round as a job. Stopped (the person stops it, the app quits), it ends between two steps of the round
    (`folder.sync_now`'s `should_stop`) and returns None, so the job ends as cancelled ("Last round stopped")."""
    def progress(step: str, message: str, info: dict) -> None:
        job.progress = {"step": step, "message": message, **info}

    out = folder.sync_now(ws, progress, should_stop=job.cancel.is_set)
    return None if out.get("stopped") else out


class _Project:
    """What the poller knows of one project (all times on the poller's clock)."""

    def __init__(self, first: float):
        self.first = first                    # the first round after the app started
        self.last_end: float | None = None    # when the last round (or the last look, without a folder) ended
        self.touched: float | None = None     # the last change made through the app
        self.touched_wall: float | None = None  # the same, on the computer's clock (time.time, as a job's `started`)
        self.failures = 0                     # rounds in a row that could not reach the folder
        self.offline_since: float | None = None   # wall clock
        self.last: dict | None = None         # the last round's summary
        self.round: Job | None = None         # the round the poller started or found, until it ends
        self.min_every = 0.0                  # 0.18.0rc2 (L6): a storage space is looked at every 10 minutes at most


class Poller:
    def __init__(self, app, clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time,
                 tick: float = TICK, start_delay: float = START_DELAY, debounce: float = DEBOUNCE,
                 max_backoff: float = MAX_BACKOFF):
        self.app = app
        self.clock, self.wall = clock, wall
        self.tick, self.start_delay, self.debounce, self.max_backoff = tick, start_delay, debounce, max_backoff
        self.lock = threading.Lock()
        self._starting = threading.Lock()   # a round's start, as one step with the look whether the poller stopped
        self._pausing = threading.Lock()    # one change of the pauses at a time (they are read, changed, written)
        self.projects: dict[str, _Project] = {}
        self.born = clock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        app.jobs.ended.append(self._ended)

    # -- settings -------------------------------------------------------------------------------------------------
    def every(self) -> float:
        """The interval between two rounds, in seconds (Settings: `sync_every_minutes`)."""
        return 60.0 * max(1, min(60, _int(self.app.settings().get(EVERY)) or 2))

    def paused_all(self) -> bool:
        return bool(self.app.settings().get(PAUSED))

    def paused(self, name: str) -> bool:
        return name in (self.app.settings().get(PAUSED_PROJECTS) or [])

    def set_paused(self, name: str | None, paused: bool) -> None:
        """Pause (or resume) the rounds of one project, or of the whole app (`name` None). Resumed, a round comes soon."""
        with self._pausing:
            if name is None:
                home.update_settings({PAUSED: bool(paused)})
                with self.lock:
                    names = list(self.projects)
            else:
                now = [n for n in (self.app.settings().get(PAUSED_PROJECTS) or []) if n != name]
                home.update_settings({PAUSED_PROJECTS: now + [name] if paused else now})
                names = [name]
        if not paused:
            for n in names:
                self.touched(n)

    # -- the thread -----------------------------------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="shared-folder-poller")
        self._thread.start()

    def stop(self, wait: float = 5.0) -> None:
        """Stop looking (the app quits): no round starts once this returns (a round being started now is in the list
        of jobs by then, so quitting stops it and waits for it); a round already running ends as a job does."""
        self._stop.set()
        with self._starting:
            pass
        t = self._thread
        if t is not None and t is not threading.current_thread() and wait:
            t.join(wait)

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def _loop(self) -> None:
        while not self._stop.wait(self.tick):
            try:
                self.step()
            except Exception:  # noqa: BLE001 - one bad look never ends the poller
                traceback.print_exc()

    # -- one look ---------------------------------------------------------------------------------------------------
    def _project(self, name: str) -> _Project:
        p = self.projects.get(name)
        if p is None:
            p = self.projects[name] = _Project(self.born + self.start_delay)
        return p

    def _wait(self, p: _Project) -> float:
        every = max(self.every(), p.min_every)
        if p.failures <= 0:
            return every
        return min(every * 2 ** min(p.failures - 1, 16), max(self.max_backoff, every))   # (weeks offline: no overflow)

    def _due(self, p: _Project) -> float:
        due = p.first if p.last_end is None else p.last_end + self._wait(p)
        if p.touched is not None and p.failures == 0:
            due = min(due, p.touched + self.debounce)
        return due

    def step(self) -> list[Job]:
        """Start the rounds that are due now; returns the jobs started (the thread calls it every few seconds; tests
        call it with their own clock)."""
        if self._stop.is_set():
            return []
        names = home.list_projects()
        if self.paused_all():
            return []
        paused = set(self.app.settings().get(PAUSED_PROJECTS) or [])
        started = []
        for name in names:
            if self._stop.is_set():
                break
            with self.lock:
                p = self._project(name)
                if name in paused or (p.round is not None and p.round.state in ("queued", "running")):
                    continue
                if self.clock() < self._due(p):
                    continue
            job = self._start_round(name, p)
            if job is not None:
                started.append(job)
        with self.lock:
            for gone in set(self.projects) - set(names):
                self.projects.pop(gone, None)
        return started

    def _start_round(self, name: str, p: _Project) -> Job | None:
        try:
            from ..sync import space

            ws = home.open_project(name)
            has = folder.chosen(ws) is not None
            with self.lock:
                p.min_every = float(space.MIN_EVERY) if space.configured(ws) is not None else 0.0
        except Exception:  # noqa: BLE001 - a project that cannot be opened has no round now
            has = False
        if not has:  # nothing to do: looked at again after an interval (choosing a folder is a change: sooner)
            with self.lock:
                p.last_end, p.touched = self.clock(), None
            return None
        with self._starting:
            if self._stop.is_set():
                return None
            job = self.app.jobs.start(folder.JOB, TITLE, name, lambda job: _round(ws, job), uses_model=False,
                                      unique=True, background=True, if_free=True)
        if job is None:
            return None  # another job of the project holds it back: still due, tried again at the next look
        with self.lock:
            if job.state in ("queued", "running"):  # (one that ended already was counted when it ended: `_ended`)
                p.round = job
        return job if job.background else None

    # -- what happens when jobs end -------------------------------------------------------------------------------
    def _ended(self, job: Job) -> None:
        if job.project is None:
            return
        if job.kind == folder.JOB:
            with self.lock:
                self._account(self._project(job.project), job)
        elif not job.background:
            self.touched(job.project)  # its work may have changed something shared

    def _account(self, p: _Project, job: Job) -> None:
        """A round ended (the poller's or one by hand): the next one, offline or not, and its summary."""
        if p.last is not None and p.last.get("job") == job.id:
            return
        p.last_end = self.clock()
        if p.touched_wall is not None and job.started is not None and p.touched_wall <= job.started:
            p.touched = p.touched_wall = None  # the round began after the last change: it carried it
        res = job.result if isinstance(job.result, dict) else {}
        off = job.state == "done" and offline(res)
        if off:
            p.failures += 1
            p.offline_since = p.offline_since or self.wall()
        elif job.state == "done":
            p.failures, p.offline_since = 0, None
        p.last = {"job": job.id, "background": job.background, "state": job.state, "finished_at": _iso(job.finished),
                  "offline": off, "problems": res.get("problems") or [],
                  "came_in": sum(things(e.get("report")) for e in res.get("read") or [] if isinstance(e, dict)),
                  "error": job.error}
        if p.round is job:
            p.round = None

    def touched(self, name: str) -> None:
        """Something changed in the project through the app: a round soon (debounced)."""
        with self.lock:
            p = self._project(name)
            p.touched, p.touched_wall = self.clock(), time.time()

    # -- what the Team tab shows ----------------------------------------------------------------------------------
    def _job_now(self, name: str) -> Job | None:
        for j in self.app.jobs.all():
            if j.kind == folder.JOB and j.project == name and j.state in ("queued", "running"):
                return j
        return None

    def state(self, name: str) -> dict:
        """The project's state (docs/API.md, GET /api/projects/<p>/sync-poller)."""
        ws = home.open_project(name)
        has = folder.chosen(ws) is not None
        paused_all, paused = self.paused_all(), self.paused(name)
        now_job = self._job_now(name)
        with self.lock:
            p = self._project(name)
            t, wall = self.clock(), self.wall()
            due = self._due(p)
            wait = self._wait(p)
            failures, since, last = p.failures, p.offline_since, dict(p.last) if p.last else None
        busy = None
        if has and not paused and not paused_all and now_job is None and due <= t:
            b = self.app.jobs.holder(name, folder.JOB)
            if b is not None:
                busy = {"id": b.id, "kind": b.kind, "title": b.title,
                        "message": f"Waits until “{b.title}” has finished"}
        if not has:
            state = "off"
        elif paused or paused_all:
            state = "paused"
        elif now_job is not None:
            state = "running"
        elif busy is not None:
            state = "busy"
        elif failures:
            state = "offline"
        elif due <= t:
            state = "due"
        else:
            state = "waiting"
        scheduled = has and not paused and not paused_all and now_job is None
        return {"project": name, "folder": has, "paused": paused, "paused_all": paused_all, "state": state,
                "every_seconds": int(self.every()),
                "next_round_at": _iso(wall + max(0.0, due - t)) if scheduled else None,
                "next_round_in": int(max(0.0, due - t) + 0.5) if scheduled else None,
                "offline": {"since": _iso(since), "failures": failures, "retry_seconds": int(wait)} if failures else None,
                "busy": busy, "round": now_job.view(full=False) if now_job is not None else None,
                "last_round": last, "came_in": self.came_in(ws)}

    def overview(self) -> dict:
        """The whole app: the interval, the pause, whether the poller runs, and every project with a shared folder."""
        out = []
        for name in home.list_projects():
            try:
                if folder.chosen(home.open_project(name)) is None:
                    continue
                out.append(self.state(name))
            except Exception:  # noqa: BLE001 - a project that cannot be opened is left out
                continue
        return {"every_minutes": int(self.every() // 60), "paused": self.paused_all(), "running": self.running(),
                "projects": out}

    # -- what came in -----------------------------------------------------------------------------------------------
    @staticmethod
    def came_in(ws) -> dict:
        """What came in through the shared folder since the person last looked: {"count", "seen_through", "rounds":
        [{"id", "at", "from", "bundles", "lines", "count"}]} (newest first; merges that brought nothing to count are
        left out)."""
        seen = _int(ws.meta(SEEN, 0))
        rounds, total = [], 0
        for r in ws.query("SELECT log_id, at, report_json FROM sync_log WHERE log_id > ? ORDER BY log_id DESC "
                          "LIMIT 500", (seen,)):
            try:
                rep = json.loads(r["report_json"] or "{}")
            except ValueError:
                continue
            if not isinstance(rep, dict) or rep.get("via") != "folder":
                continue
            n = things(rep)
            if not n:
                continue
            total += n
            if len(rounds) < ROUNDS_SHOWN:
                rounds.append({"id": r["log_id"], "at": r["at"], "from": rep.get("from") or {},
                               "bundles": rep.get("bundles"), "lines": rep.get("lines") or [], "count": n})
        return {"count": total, "seen_through": seen, "rounds": rounds}

    @staticmethod
    def mark_seen(ws, through: int | None = None) -> None:
        """The person has seen what came in, up to the entry `through` (all of it when None). A mark never goes back."""
        top = _int(ws.scalar("SELECT MAX(log_id) FROM sync_log"))
        upto = top if through is None else max(0, min(_int(through), top))
        if upto > _int(ws.meta(SEEN, 0)):
            ws.set_meta(SEEN, upto)
