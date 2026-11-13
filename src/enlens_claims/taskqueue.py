"""The task queue (0.8, G1, G4): work ENLENS prepares for an AI outside this program, Claude Code on the
researcher's own plan.

ENLENS prepares the tasks (the same planning its own runs do) and checks every answer; Claude Code, started by the
researcher, only reads. It takes small batches through the connector (`next_tasks`), answers them with a helper agent
on the model the router names for each kind, and hands the answers back (`submit_answers`): each one goes through
the same quote check as any other answer, a rejected one comes back with its problems listed.

- A task is in the queue when `tasks.queued` is 1. Tasks of 0.7 and of the SDG pack are never in it unless someone
  puts them there: for the SDG pack that is `enlens prepare extract|split|verify-vca|verify-claims|audit-vca`
  (0.8.1), and `/enlens-run` then answers them like any other kind, with the extractor, checker or auditor helper.
- A batch handed out is a claim (`task_claims`): who took it, when, which model and helper. A claim not answered in
  CLAIM_MINUTES lapses and its tasks are handed out again, so a stop (a usage limit, a closed laptop) costs at most
  one batch, and two sessions never answer the same task.
- The researcher's own requests come first (checks, reading again), then small jobs (theme names, links), then the
  bulk (labels, references). A kind can be moved to the front or held (`set_order`).
- `status` gives the counts per kind, the model and helper, an estimate from the measured seconds per task, and
  whether the work has paused ("Paused at 340 of 7,868 labels").

The app's jobs wait on their tasks with `wait_for` (through the Claude Code backend), so a page shows progress while
the answers come from another program. A check by queue advances on its own whenever answers arrive (`advance`),
in whichever program stores them.
"""
from __future__ import annotations

import itertools
import json
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

from . import access, prompts, routing, runs, taskkinds
from .store import Workspace, now

CLAIM_MINUTES = 30
PAUSED_AFTER = 180          # seconds without an answer, nothing claimed and work waiting: the run has paused
TOKEN_BUDGET = 15000        # the most a batch's prompts may hold (well under the connector's 25,000-token output cap)
CONNECTOR_CAP = 25000       # the connector's output cap: the system prompt and the task prompts of a batch together
PARALLEL = 2                # helpers at once when nothing else is said (0.13.10: the speed "normal")
MAX_PARALLEL = 8            # the most helpers one run starts at once
MAX_PER_HELPER = 4          # the most helpers of one kind at once, when the helpers are named one by one
SPEEDS = {"slower": 1, "normal": 2, "faster": 4}   # 0.13.10: Settings' claude_speed, as helpers at once
# 0.13.6: views of the registry (taskkinds.py): the batch a claim takes, the order the queue is answered in (the
# researcher's own requests first, then small jobs, then the bulk; the SDG pack's batch pipeline last), and the
# names the queue panel uses
BATCH = taskkinds.Table("batch")
ORDER = taskkinds.Names(lambda k: k.task and k.batch is not None and k.order is not None, key=lambda k: k.order)
KINDS = ORDER

NOUN = taskkinds.Table("noun")
SHORT = taskkinds.Table("short")
KIND_TITLE = taskkinds.Table("title")

PRIVACY_LINE = ("Claude Code sends the passages inside the tasks it takes to Anthropic; your documents, results and "
                "reviews stay on this computer.")


def noun(kind: str, n: int) -> str:
    one, many = NOUN.get(kind, ("task", "tasks"))
    return f"{n:,} {one if n == 1 else many}"


def _ts(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).timestamp()
    except ValueError:
        return None


def _cutoff() -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=CLAIM_MINUTES)).replace(microsecond=0).isoformat()


def local_only() -> bool:
    from .home import local_only as _lo

    return _lo()


def router(ws: Workspace | None = None) -> routing.Router:
    """The Claude Code route's models, from Settings (per-task choices, Fable)."""
    from .home import load_settings

    return routing.from_settings(load_settings(), route="claude_code")


# a task waits when it is in the queue (only tasks whose documents Claude may read enter it) and not answered, or
# answered and to be read again by the stronger model. Written once for every place that asks (the queue, the
# sidebar's count, the connector): store.INDEXES has a partial index with this very condition (ix_tasks_waiting), and
# SQLite uses such an index only for a query that repeats its condition word for word. `OPEN` is the part about the
# answer alone (`access.relabel` looks at every open task, in the queue or not).
OPEN = "(status IN ('pending', 'retry') OR (status='done' AND again=1))"
WAITING = f"COALESCE(queued, 0)=1 AND COALESCE(access, 'cloud')='cloud' AND {OPEN}"
_WAITING = WAITING
# not held by a claim that is still open, and held by one (the index on claimed_by, ix_tasks_claimed, finds those)
_FREE = "(t.claimed_by IS NULL OR t.claimed_at < ?)"
_HELD = "t.claimed_by IS NOT NULL AND t.claimed_by != '' AND t.claimed_at >= ?"
# the test of _HELD as a value, 1 or 0 (being answered or not), to count by in `status`
CLAIMED = "(COALESCE(t.claimed_by, '') != '' AND COALESCE(t.claimed_at, '') >= ?)"


def effective_model(t, r: routing.Router) -> str:
    k = routing.task_kind(t)
    # 0.18.1 (I2): a task the local model of the AI mix passed up to Claude has step 1 even where the kind has no
    # stronger Claude model: then the kind's own model reads it
    return t["forced_model"] or r.model(k, int(t["step"] or 0)) or (r.first(k) if t["step"] else None) or \
        t["model"] or ""


# 0.18.1 (I4): the words Claude Code ends with when the plan's usage limit is reached ("Claude AI usage limit
# reached", "You've hit your limit · resets 3pm", "5-hour limit reached ∙ resets 2am"), and the time it names
LIMIT_RE = re.compile(r"usage limit reached|hit your (?:usage )?limit|(?:5-hour|weekly|session) limit reached|"
                      r"limit reached\W+resets", re.I)
RESETS_RE = re.compile(r"resets\s+(?:at\s+)?([^\n.|]{1,40})", re.I)


def limit_reached(runner: dict | None) -> str | None:
    """Whether Claude Code, started from the app, stopped at the plan's usage limit: the sentence for the page
    ("Claude Code reached your plan's usage limit (it resets 3pm).") or None."""
    if not runner or runner.get("running") or not runner.get("report"):
        return None
    tail = str(runner["report"])
    if not LIMIT_RE.search(tail):
        return None
    m = RESETS_RE.search(tail)
    return "Claude Code reached your plan's usage limit" + (f" (it resets {m.group(1).strip()})" if m else "") + "."


def mix_kinds() -> frozenset[str]:
    """0.18.1 (I1): the kinds the AI mix gives the local model first; Claude Code's helpers take them only once the
    local model has passed them up (step 1)."""
    from .home import load_settings

    return routing.mix_kinds(load_settings())


def _lent(t, lent: frozenset[str]) -> bool:
    """A waiting task the local model of the AI mix answers first (not Claude Code's yet)."""
    return bool(lent) and routing.task_kind(t) in lent and not int(t["step"] or 0) and not t["forced_model"]


def effective_helper(t, r: routing.Router) -> str:
    k = routing.task_kind(t)
    return r.helper(k, int(t["step"] or 0)) or routing.HELPERS.get(k, "")


# ---------------------------------------------------------------------------------------------
# order of work
# ---------------------------------------------------------------------------------------------
def order(ws: Workspace) -> tuple[list[str], list[str]]:
    """(the kinds in the order they are handed out, the kinds held)."""
    o = [k for k in (ws.meta("queue_order") or []) if k in KINDS]
    o += [k for k in ORDER if k not in o]
    held = [k for k in (ws.meta("queue_held") or []) if k in KINDS]
    return o, held


def set_order(ws: Workspace, kind: str, action: str) -> dict:
    """`first`: hand this kind out before the others; `hold` / `go`: stop or resume handing it out; `reset`."""
    if action == "reset":
        ws.set_meta("queue_order", [])
        ws.set_meta("queue_held", [])
        return {"order": list(ORDER), "held": []}
    if kind not in KINDS:
        raise ValueError(f"Unknown kind of task {kind!r}.")
    o, held = order(ws)
    if action == "first":
        o = [kind] + [k for k in o if k != kind]
    elif action == "hold":
        held = sorted(set(held) | {kind})
    elif action == "go":
        held = [k for k in held if k != kind]
    else:
        raise ValueError("action must be first, hold, go or reset.")
    ws.set_meta("queue_order", o)
    ws.set_meta("queue_held", held)
    return {"order": o, "held": held}


# ---------------------------------------------------------------------------------------------
# what waits
# ---------------------------------------------------------------------------------------------
def _waiting_rows(ws: Workspace, kind: str | None = None, limit: int | None = None):
    sql = (f"SELECT t.task_id, t.kind, t.role, t.step, t.forced_model, t.model, t.queued_at, t.attempts, t.status, "
           f"t.again "
           f"FROM tasks t WHERE {_WAITING} AND {_FREE}")
    args: list = [_cutoff()]
    if kind:
        sql += " AND t.kind=?"
        args.append(kind)
    sql += " ORDER BY t.again DESC, t.queued_at, t.task_id"
    if limit:
        sql += " LIMIT ?"
        args.append(int(limit))
    return ws.query(sql, args)


PAGE = 500  # the tasks that wait `next_tasks` reads first, in the queue's order: a batch takes 50 at most


def _waiting_count(ws: Workspace, kind: str) -> int:
    """len(_waiting_rows(ws, kind)) without reading the rows: those of the kind that wait (the partial index alone),
    less those a claim holds (not `_FREE`: held, or with no time; few, found by the index on claimed_by)."""
    n = ws.scalar(f"SELECT COUNT(*) FROM tasks t WHERE {WAITING} AND t.kind=?", (kind,)) or 0
    taken = ws.scalar(f"SELECT COUNT(*) FROM tasks t WHERE t.claimed_by IS NOT NULL AND (t.claimed_at >= ? OR "
                      f"t.claimed_at IS NULL) AND {WAITING} AND +t.kind=?", (_cutoff(), kind)) or 0
    return int(n) - int(taken)


def estimate_seconds(ws: Workspace, kind: str, model: str, n: int, parallel: int = 2) -> float | None:
    sec = runs.seconds_per_task(ws, kind, model)
    if sec is None or not n:
        return None
    return sec * n / max(1, parallel)


def _duration(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    m = seconds / 60
    if m < 1.5:
        return "about a minute"
    if m < 90:
        return f"about {round(m):,} minutes"
    return f"about {round(m / 60, 1):g} hours"


ANSWERING_GAP = 120         # seconds since Claude Code's last answer that still count as answering (between batches)


def answering(ws: Workspace) -> bool:
    """0.12: whether a Claude Code session is working on this project's queue now: a batch taken and not finished, a
    task claimed, or an answer stored in the last two minutes (a session between two batches). Claude Code started
    from the app is asked separately (claude_setup.run_state)."""
    if ws.scalar("SELECT COUNT(*) FROM task_claims WHERE finished_at IS NULL AND expires_at > ?", (now(),)):
        return True
    if ws.scalar(f"SELECT 1 FROM tasks t WHERE {_HELD} AND {WAITING} LIMIT 1", (_cutoff(),)):
        return True
    last = _ts(_last_answer(ws))
    return bool(last and time.time() - last < ANSWERING_GAP)


def _last_answer(ws: Workspace) -> str | None:
    return ws.scalar("SELECT MAX(received_at) FROM results WHERE route='Claude Code'")


def _paused(ws: Workspace, waiting: int, active: int, newest: str | None, last: str | None) -> bool:
    """Whether the work has paused: tasks wait, none is being answered or claimed, and nothing has been answered or
    queued for PAUSED_AFTER seconds."""
    if not waiting or active:
        return False
    if ws.scalar("SELECT COUNT(*) FROM task_claims WHERE finished_at IS NULL AND expires_at > ?", (now(),)):
        return False
    since = max(_ts(last) or 0, _ts(newest) or 0)
    return bool(since and time.time() - since > PAUSED_AFTER)


def _run_counts(ws: Workspace, kind: str, first_queued: str) -> tuple[int, int]:
    """The current run of a kind: (the tasks queued since its oldest one still open, those of them finished), for
    "Paused at 340 of 7,868"."""
    n = ws.query("SELECT COUNT(*), SUM(status IN ('done', 'failed') AND again=0) FROM tasks WHERE "
                 "COALESCE(queued, 0)=1 AND kind=? AND queued_at >= ?", (kind, first_queued))[0]
    return int(n[0] or 0), int(n[1] or 0)


def _paused_text(kind: str, run_done: int, run_total: int, command: str) -> str:
    return (f"Paused at {run_done:,} of {run_total:,} {SHORT.get(kind, 'tasks')}. "
            f"To go on, type {command} in Claude Code.")


def _kind_order(ws: Workspace, o: list[str], kinds) -> list[str]:
    """Kinds in the queue's order; a kind the order does not name (none normally) after them, in the order its
    tasks were first made."""
    rest = [k for k in kinds if k not in o]
    if len(rest) > 1:
        rest.sort(key=lambda k: ws.scalar("SELECT MIN(rowid) FROM tasks WHERE COALESCE(queued, 0)=1 AND "
                                          "COALESCE(access, 'cloud')='cloud' AND kind=?", (k,)) or 0)
    return [k for k in o if k in kinds] + rest


def status(ws: Workspace, project: str | None = None, parallel: int = PARALLEL, helpers: dict | None = None,
           kind: str | None = None) -> dict:
    """The queue of one project: per kind what waits, is being answered, is done or failed; the groups a run hands
    to the helpers (kind, model, helper, and how many helpers to start for each: `start`); estimates; and whether
    the work has paused. `parallel`, `helpers` (clean_helpers) and `kind` are a run's plan (0.13.10): the groups of
    other kinds, or of helpers the plan leaves out, are not in `groups` (the latter are in `not_this_run`)."""
    r = router(ws)
    o, held = order(ws)
    cutoff = _cutoff()
    lent = mix_kinds()
    per: dict[str, dict] = {}
    # every kind with a task in the queue, in the order its tasks were first made (the order of a kind the queue's
    # order does not name), with its answered and failed tasks
    for row in ws.query("SELECT kind, SUM(status='done' AND COALESCE(again, 0)=0), SUM(status='failed') FROM tasks "
                        "WHERE COALESCE(queued, 0)=1 AND COALESCE(access, 'cloud')='cloud' GROUP BY kind "
                        "ORDER BY MIN(rowid)"):
        k = row[0]
        per[k] = {"kind": k, "title": KIND_TITLE.get(k, k), "waiting": 0, "being_answered": 0, "done": int(row[1] or 0),
                  "failed": int(row[2] or 0), "stronger_model": 0, "first_queued": None, "run_total": 0, "run_done": 0,
                  "for_local": 0}
    groups: dict[tuple, dict] = {}
    # the tasks that wait, counted in SQL per what decides their model and helper (the router is asked once per
    # group, not twice per task), and whether a claim holds them now
    for g0 in ws.query(f"SELECT t.kind, t.role, t.step, t.forced_model, t.model, {CLAIMED} AS claimed, COUNT(*) AS n, "
                       f"MIN(t.queued_at) AS first FROM tasks t WHERE {WAITING} "
                       "GROUP BY t.kind, t.role, t.step, t.forced_model, t.model, claimed", (cutoff,)):
        k, n = g0["kind"], int(g0["n"])
        d = per[k]
        if not g0["claimed"] and _lent(g0, lent):
            d["for_local"] += n  # 0.18.1 (I1): the local model of the AI mix answers these first
            continue
        if g0["claimed"]:
            d["being_answered"] += n
        else:
            d["waiting"] += n
            m, hp = effective_model(g0, r), effective_helper(g0, r)
            g = groups.setdefault((k, m, hp), {"kind": k, "model": m, "helper": hp, "waiting": 0})
            g["waiting"] += n
        if g0["step"]:
            d["stronger_model"] += n
        if g0["first"] is not None and (d["first_queued"] is None or g0["first"] < d["first_queued"]):
            d["first_queued"] = g0["first"]
    for k, d in per.items():
        if d["first_queued"]:
            d["run_total"], d["run_done"] = _run_counts(ws, k, d["first_queued"])
    last = _last_answer(ws)
    waiting_total = sum(d["waiting"] for d in per.values())
    active = sum(d["being_answered"] for d in per.values())
    newest = max((d["first_queued"] or "" for d in per.values()), default="")
    paused = _paused(ws, waiting_total, active, newest, last)
    kinds = []
    for k in [x for x in o if x in per] + [x for x in per if x not in o]:
        d = per[k]
        model = r.model(k) or ""
        est = estimate_seconds(ws, k, model, d["waiting"] + d["being_answered"], parallel)
        d.update(model=model, step_up=r.step_up(k), helper=r.helper(k), held=k in held,
                 estimate_seconds=round(est) if est is not None else None,
                 estimate=_estimate_text(k, d["waiting"] + d["being_answered"], est))
        d.pop("first_queued")
        d["effort"] = r.effort(k)  # 0.18.1 (N2): the effort to ask of the kind's helper, when one is asked
        if d["waiting"] or d["being_answered"] or d["failed"] or d["done"] or d["for_local"]:
            kinds.append(d)
    rank = {k: i for i, k in enumerate(o)}
    gl = sorted((g for g in groups.values() if g["kind"] not in held and (kind is None or g["kind"] == kind)),
                key=lambda g: (rank.get(g["kind"], 99), g["model"], g["helper"]))
    left_out = plan_helpers(gl, parallel, helpers)
    gl = [g for g in gl if all(g is not x for x in left_out)]
    name = project or ws.root.name
    out = {"project": name, "kinds": kinds, "groups": gl, "order": o, "held": held, "waiting": waiting_total,
           "being_answered": active, "paused": paused, "last_answer_at": last, "privacy": PRIVACY_LINE,
           "local_only": local_only(), "command": f"/enlens-run {_quote_name(name)}", "claim_minutes": CLAIM_MINUTES,
           "parallel": parallel, "for_local": sum(d["for_local"] for d in per.values()),
           # 0.18.1 (N2, I1): how much thought Claude gives the tasks, and the mix of routes
           "thought": r.thought, "effort": routing.THOUGHT_EFFORT.get(r.thought), "mix_kinds": sorted(lent)}
    if helpers is not None:
        out["helpers"] = {short_helper(h): n for h, n in helpers.items()}
        out["not_this_run"] = left_out
    if paused:
        k = next((x for x in kinds if x["waiting"]), None)
        if k:
            out["paused_text"] = _paused_text(k["kind"], k["run_done"], k["run_total"], out["command"])
    return out


def _estimate_text(kind: str, n: int, seconds: float | None) -> str:
    if not n:
        return ""
    if seconds is None:
        return "the time is not known yet (it is measured as answers arrive)"
    text = f"{_duration(seconds)} for {noun(kind, n)}"
    if seconds > 2 * 3600:
        text += "; it may take more than one session on a Pro plan"
    return text


def _quote_name(name: str) -> str:
    return f'"{name}"' if any(c.isspace() for c in name) else name


# ---------------------------------------------------------------------------------------------
# 0.13.10: how many helpers a run starts at once, and which. The researcher picks a speed beside Start Claude Code
# (one, two or four helpers at once); "For this run" can name the helpers one by one instead. `/enlens-run` passes
# its --parallel and --helpers to queue_status, and each group then says how many helpers to start for it (`start`):
# the sums are done here, not by the orchestrating model. (PARALLEL, MAX_PARALLEL, MAX_PER_HELPER: at the top.)
# ---------------------------------------------------------------------------------------------
def short_helper(helper: str) -> str:
    """The name a person types for a helper: "checker" for enlens-checker (an add-on's helper keeps its name)."""
    return helper[len("enlens-"):] if helper.startswith("enlens-") else helper


def helper_name(name: str) -> str:
    """A helper's full name from what a person may type: "checker", "Checker" or "enlens-checker"."""
    n = str(name or "").strip().lower()
    known = list(routing.HELPER_MODEL)
    for h in (n, f"enlens-{n}"):
        if h in known:
            return h
    raise ValueError(f"Unknown helper {name!r}. Helpers: {', '.join(short_helper(h) for h in known)}.")


def _whole(value) -> int | None:
    """A whole number from an int, a float without a fraction or its text; None for anything else (true, 2.5, "x")."""
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def clean_parallel(value) -> int:
    """How many helpers at once: a whole number from 1 to MAX_PARALLEL."""
    n = _whole(value)
    if n is None or not 1 <= n <= MAX_PARALLEL:
        raise ValueError(f"parallel must be a whole number from 1 to {MAX_PARALLEL}.")
    return n


def clean_helpers(value) -> dict[str, int] | None:
    """The helpers named for one run, {full helper name: how many at once, 0 to MAX_PER_HELPER}, from
    {"checker": 2, "labeller": 1} or the command's form "checker=2,labeller=1". None when none is named. A helper
    left out, or given 0, does nothing in that run."""
    if value is None or value == "" or value == {}:
        return None
    if isinstance(value, str):
        pairs = []
        for part in value.replace(";", ",").split(","):
            part = part.strip()
            if part:
                name, sep, n = part.replace(":", "=").partition("=")
                pairs.append((name, n.strip() if sep else "1"))
    elif isinstance(value, dict):
        pairs = list(value.items())
    else:
        raise ValueError('helpers must name helpers with how many of each, for example "checker=2,labeller=1".')
    out: dict[str, int] = {}
    for name, n in pairs:
        h = helper_name(name)
        k = _whole(n)
        if k is None or not 0 <= k <= MAX_PER_HELPER:
            raise ValueError(f"{short_helper(h)}: say how many at once, a whole number from 0 to {MAX_PER_HELPER}.")
        out[h] = k
    if not any(out.values()):
        raise ValueError("Name at least one helper with 1 or more.")
    return out


def helpers_arg(helpers: dict[str, int]) -> str:
    """The command's form of a run's helpers: "checker=2,labeller=1" (the ones given 0 left out)."""
    return ",".join(f"{short_helper(h)}={n}" for h, n in helpers.items() if n)


def speed_parallel(speed: str | None = None) -> int:
    """Helpers at once for a speed: slower 1, normal 2, faster 4 (the speed chosen in Settings when none is given)."""
    from .home import load_settings

    return SPEEDS.get(speed or load_settings().get("claude_speed") or "normal", PARALLEL)


def run_plan(parallel=None, helpers=None) -> dict:
    """A run's plan, checked: {"parallel": helpers at once, "helpers": {helper: how many} or None}. With the helpers
    named one by one, `parallel` is their sum (at most MAX_PARALLEL) unless given; with neither, the speed chosen in
    Settings (so a typed /enlens-run goes at the speed chosen in the app). `parallel` is never more than the helpers
    named add up to, so the run says how many it can really have at once."""
    chosen = clean_helpers(helpers)
    if parallel is not None:
        n = clean_parallel(parallel)
    elif chosen:
        n = MAX_PARALLEL
    else:
        n = speed_parallel()
    if chosen:
        n = min(n, sum(chosen.values()))
    return {"parallel": n, "helpers": chosen}


def run_status(ws: Workspace, project: str, kind: str | None = None, parallel=None, helpers=None) -> dict:
    """The queue as one run of /enlens-run sees it (the connector's queue_status): `kind`, `parallel` and `helpers`
    as the command was given them; each group says how many helpers to start for it (`start`)."""
    if kind and kind not in KINDS:
        raise ValueError(f"Unknown kind of task {kind!r}. Kinds: {', '.join(KINDS)}.")
    plan = run_plan(parallel, helpers)
    advance(ws)
    return status(ws, project, parallel=plan["parallel"], helpers=plan["helpers"], kind=kind or None)


def helper_rows(groups: list[dict], kinds: list[dict]) -> list[dict]:
    """The helpers that have work waiting, for "For this run" in the app: per helper its models, the kinds of task it
    would answer (titles), how many tasks wait and in how many batches (more helpers than batches do nothing)."""
    titles = {k["kind"]: k["title"] for k in kinds}
    rows: dict[str, dict] = {}
    for g in groups:
        r = rows.setdefault(g["helper"], {"helper": g["helper"], "name": short_helper(g["helper"]), "models": [],
                                          "kinds": [], "waiting": 0, "batches": 0})
        if g["model"] not in r["models"]:
            r["models"].append(g["model"])
        title = titles.get(g["kind"], g["kind"])
        if title not in r["kinds"]:
            r["kinds"].append(title)
        r["waiting"] += g["waiting"]
        r["batches"] += -(-g["waiting"] // max(1, BATCH.get(g["kind"], 5)))
    return list(rows.values())


def plan_helpers(groups: list[dict], parallel: int, helpers: dict[str, int] | None = None) -> list[dict]:
    """Set each group's `start`: how many helpers to start for it now, `parallel` in all. One per group in the
    queue's order first, then more for the groups with work for more (a helper takes a batch at a time, so a group
    never gets more helpers than it has batches). With `helpers`, only the helpers named start, each at most as many
    times as named (over its groups together). Returns the groups with nothing to start because of `helpers`."""
    left = parallel if helpers is None else min(parallel, sum(helpers.values()))
    used: dict[str, int] = {}
    for g in groups:
        g["start"] = 0
    mine = [g for g in groups if helpers is None or helpers.get(g["helper"], 0) > 0]
    while left > 0:
        added = False
        for g in mine:
            if left <= 0:
                break
            batches = -(-g["waiting"] // max(1, BATCH.get(g["kind"], 5)))
            if g["start"] >= batches or (helpers is not None and used.get(g["helper"], 0) >= helpers[g["helper"]]):
                continue
            g["start"] += 1
            used[g["helper"]] = used.get(g["helper"], 0) + 1
            left -= 1
            added = True
        if not added:
            break
    chosen = {id(g) for g in mine}
    return [g for g in groups if id(g) not in chosen]


# ---------------------------------------------------------------------------------------------
# handing out and taking back
# ---------------------------------------------------------------------------------------------
def next_tasks(ws: Workspace, kind: str | None = None, n: int | None = None, model: str | None = None,
               taken_by: str | None = None, helper: str | None = None) -> dict:
    """Claim a batch: tasks of one kind for one model (and helper, when given), as many as BATCH says (or `n`)
    within TOKEN_BUDGET, and with the system prompt within CONNECTOR_CAP.

    Returns {"claim", "kind", "model", "helper", "prompt_version", "system", "tasks": [{"task_id", "prompt"}],
    "expires_at", ...}, or {"claim": None, "note"} when nothing of that kind and model waits."""
    from .tasks import render

    if local_only():
        raise ValueError("This installation keeps everything on this computer (local only): the queue does not hand "
                         "tasks to Claude Code here.")
    r = router(ws)
    o, held = order(ws)
    lent = mix_kinds()
    kinds = [kind] if kind else [k for k in o if k not in held]
    if kind and kind not in KINDS:
        raise ValueError(f"Unknown kind of task {kind!r}. Kinds: {', '.join(KINDS)}.")
    for k in kinds:
        # the first PAGE tasks that wait, in order: a batch is nearly always filled from them; the others are read
        # only when it is not (a queue of a hundred thousand tasks is not read whole for a batch of five)
        rows = _waiting_rows(ws, k, PAGE)
        whole = len(rows) < PAGE
        cand = [t for t in rows if (model is None or effective_model(t, r) == model)
                and (helper is None or effective_helper(t, r) == helper) and not _lent(t, lent)]
        if not cand and not whole:
            rows, whole = _waiting_rows(ws, k), True
            cand = [t for t in rows if (model is None or effective_model(t, r) == model)
                    and (helper is None or effective_helper(t, r) == helper) and not _lent(t, lent)]
        if not cand:
            continue
        # 0.18.1 (H4): a task whose question was answered before (another task id, the same text, the same model) is
        # answered from that answer here, if it fits this text, instead of going to Claude Code
        from .tasks import answer_from_cache

        kept = [t for t in cand[:max(2 * int(n or BATCH.get(k, 5)), 20)] if not t["attempts"] and t["status"] != "done"
                and answer_from_cache(ws, t["task_id"], effective_model(t, r), "Claude Code")]
        if kept:
            gone = {t["task_id"] for t in kept}
            cand = [t for t in cand if t["task_id"] not in gone]
            after_store(ws, {k})
            if not cand:
                continue
        m = effective_model(cand[0], r)
        hp = effective_helper(cand[0], r)
        cand = [t for t in cand if effective_model(t, r) == m and effective_helper(t, r) == hp]
        seen = {t["task_id"] for t in rows}

        def rest(m=m, hp=hp, seen=seen, whole=whole, k=k):
            """The tasks after the first page, in the same order, for the same model and helper."""
            if not whole:
                for t in _waiting_rows(ws, k):
                    if t["task_id"] not in seen and effective_model(t, r) == m and effective_helper(t, r) == hp \
                            and not _lent(t, lent):
                        yield t
        size = max(1, min(int(n or BATCH.get(k, 5)), 50))
        cid = "q" + uuid.uuid4().hex[:12]
        at = now()
        expires = (datetime.now(timezone.utc) + timedelta(minutes=CLAIM_MINUTES)).replace(microsecond=0).isoformat()
        picked: list[dict] = []
        budget = 0
        from .llm import estimate_tokens

        system = prompts.system_prompt(k)
        cap = min(TOKEN_BUDGET, CONNECTOR_CAP - 2000 - estimate_tokens(system))
        with ws.connect() as cx:
            dflt = access._default_from_cx(cx)  # once per batch, not per task
            for t in itertools.chain(cand, rest()):
                if len(picked) >= size:
                    break
                full = cx.execute("SELECT * FROM tasks WHERE task_id=?", (t["task_id"],)).fetchone()
                if full is None:
                    continue
                # the setting worked out again as the text leaves, not trusted from the column: a document's cap
                # counts the tasks of this batch recorded just before; one that is no longer `cloud` leaves the
                # queue and waits for the local model or the person
                if access.recheck(cx, t["task_id"], dflt) != "cloud":
                    continue
                _sys, user = render(ws, full)
                cost = estimate_tokens(user)
                if picked and budget + cost > cap:
                    break
                got = cx.execute(f"UPDATE tasks SET claimed_by=?, claimed_at=? WHERE task_id=? AND {WAITING} AND "
                                 f"{_FREE.replace('t.', '')}", (cid, at, t["task_id"], _cutoff())).rowcount
                if got:
                    picked.append({"task_id": t["task_id"], "prompt": user, "payload_json": full["payload_json"]})
                    budget += cost
                    # 0.11: the passages of this task leave the computer now, with the batch
                    access.record_sent(cx, t["task_id"], json.loads(full["payload_json"]), "Claude Code", k)
            if not picked:
                continue
            cx.execute("INSERT INTO task_claims(claim_id, kind, model, helper, route, taken_by, task_ids_json, claimed_at, "
                       "expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
                       (cid, k, m, hp, "Claude Code", (taken_by or "")[:120],
                        json.dumps([p["task_id"] for p in picked]), at, expires))
        # 0.18.1 (H4): a small codebook once per batch: the codes' descriptions go with the batch's instruction, and
        # each passage names only its candidate codes
        shared = prompts.shared_codebook(k, [json.loads(p.pop("payload_json")) for p in picked])
        if shared:
            system = f"{system}\n\n{shared['codebook']}"
            for p, user in zip(picked, shared["prompts"]):
                p["prompt"] = user
        else:
            for p in picked:
                p.pop("payload_json", None)
        left = _waiting_count(ws, k)
        return {"claim": cid, "kind": k, "model": m, "helper": hp, "prompt_version": prompts.VERSIONS[k],
                "system": system, "tasks": picked, "expires_at": expires, "codebook_once": bool(shared),
                "still_waiting": left,
                "how_to_answer": ("Answer every task as the system instruction says: one JSON object per task, quotes "
                                  "copied exactly from that task's text. Then call submit_answers with this claim and "
                                  "[{task_id, answer}] for each task.")}
    what = f" of kind {kind}" if kind else ""
    by = f" for {model}" if model else ""
    return {"claim": None, "note": f"Nothing{what}{by} is waiting in the queue."}


def _find(ws: Workspace, claim_id: str):
    r = ws.query("SELECT * FROM task_claims WHERE claim_id=?", (claim_id,))
    if not r:
        raise KeyError(f"no claim {claim_id}")
    return r[0]


def submit(ws: Workspace, claim_id: str, answers: list[dict]) -> dict:
    """Store the answers of a claim. Each answer is checked like any other (quotes against the text); a rejected one
    comes back with its problems and stays with this claim to be fixed, unless it goes up to the stronger model."""
    from .tasks import MAX_ATTEMPTS, NotHeld, ingest_result, step_up

    c = _find(ws, claim_id)
    mine = set(json.loads(c["task_ids_json"] or "[]"))
    r = router(ws)
    results = []
    stored = problems = 0
    kinds_stored: set[str] = set()
    for a in answers or []:
        if not isinstance(a, dict):
            results.append({"task_id": None, "stored": False, "problems": ["each answer must be an object with "
                                                                           "task_id and answer"]})
            continue
        tid = str(a.get("task_id") or "")
        raw = a.get("answer", a.get("output"))
        if tid not in mine:
            results.append({"task_id": tid, "stored": False, "problems": ["this task is not in this claim"]})
            continue
        t = ws.query("SELECT * FROM tasks WHERE task_id=?", (tid,))
        if not t:
            results.append({"task_id": tid, "stored": False, "problems": ["this task no longer exists (it was "
                                                                          "withdrawn in ENLENS)"]})
            continue
        t = t[0]
        if t["claimed_by"] != claim_id:
            msg = ("already answered" if t["status"] == "done" and not t["again"] else
                   "this claim lapsed and the task was handed to another session; leave it")
            results.append({"task_id": tid, "stored": False, "problems": [msg], "attempts_left": 0})
            continue
        if raw is None:
            results.append({"task_id": tid, "stored": False, "problems": ["no answer given"],
                            "attempts_left": MAX_ATTEMPTS - int(t["attempts"])})
            continue
        model = effective_model(t, r)
        helper = effective_helper(t, r)
        prov = {"digest": None, "seed": None,
                "settings": {"backend": "claude_code", "route": "Claude Code", "helper": helper, "model_as_set": model}}
        try:  # stored only while this claim still holds the task, checked where the answer is written
            ok, errors = ingest_result(ws, tid, raw, model=model, provenance=prov, route="Claude Code", helper=helper,
                                       claimed_at=c["claimed_at"], claim=claim_id)
        except NotHeld as e:
            msg = ("already answered" if e.reason == "answered" else
                   "this claim lapsed and the task was handed to another session; leave it")
            results.append({"task_id": tid, "stored": False, "problems": [msg], "attempts_left": 0})
            continue
        after = ws.query("SELECT * FROM tasks WHERE task_id=?", (tid,))[0]
        item = {"task_id": tid, "stored": ok, "problems": errors if not ok else [],
                "attempts_left": max(0, MAX_ATTEMPTS - int(after["attempts"]))}
        moved = False
        rk = routing.task_kind(t)
        # the step-up rule of the app's runs (tasks.step_up); a task the stronger model is reading again already (an
        # answered one) does not step up; one that does is no longer this claim's
        how, conf = step_up(ws, t, r, ok, raw) if t["status"] != "done" else (None, None)
        if how:
            with ws.connect() as cx:
                cx.execute("UPDATE tasks SET claimed_by=NULL, claimed_at=NULL WHERE task_id=?", (tid,))
            moved = True
        if how == "again":
            item["read_again_by"] = r.step_up(rk)
            item["note"] = (f"Stored. The answer was unsure (certainty {conf:.2f}), so a stronger model "
                            f"({item['read_again_by']}) reads this task once more; it is no longer yours.")
        elif how == "retry":
            item["moved_to"] = r.step_up(rk)
            item["note"] = (f"Two answers were rejected, so the last attempt goes to a stronger model "
                            f"({item['moved_to']}); it is no longer yours.")
            item["attempts_left"] = 0
        # 0.14.3: a stronger model's rejected answer leaves the task done (the first answer counts meanwhile) with
        # `again` still set: it stays with this claim to be fixed, as any rejected answer does
        finished = ok or after["status"] == "failed" or (after["status"] == "done" and not after["again"])
        if not moved and finished:
            with ws.connect() as cx:
                cx.execute("UPDATE tasks SET claimed_by=NULL, claimed_at=NULL WHERE task_id=? AND claimed_by=?",
                           (tid, claim_id))
        if ok:
            stored += 1
            kinds_stored.add(t["kind"])
        else:
            problems += 1
        results.append(item)
    open_ids = [r0[0] for r0 in ws.query("SELECT task_id FROM tasks WHERE claimed_by=?", (claim_id,))]
    with ws.connect() as cx:
        cx.execute("UPDATE task_claims SET stored=stored+?, problems=problems+?, finished_at=? WHERE claim_id=?",
                   (stored, problems, None if open_ids else now(), claim_id))
    if stored:
        secs = time.time() - (_ts(c["claimed_at"]) or time.time())
        per_task = secs / max(1, stored + len(open_ids))
        runs.timing(ws, c["kind"], c["model"], per_task, times=stored)  # one write for the batch
        after_store(ws, kinds_stored)
    out = {"claim": claim_id, "results": results, "stored": stored, "with_problems": problems, "open": open_ids}
    out["next"] = ("Fix exactly the problems listed for the tasks still open and call submit_answers again."
                   if open_ids else "This batch is finished. Call next_tasks for another one.")
    return out


def release(ws: Workspace, claim_id: str) -> dict:
    """Give a claim's unanswered tasks back to the queue at once (instead of after CLAIM_MINUTES)."""
    _find(ws, claim_id)
    with ws.connect() as cx:
        n = cx.execute("UPDATE tasks SET claimed_by=NULL, claimed_at=NULL WHERE claimed_by=?", (claim_id,)).rowcount
        cx.execute("UPDATE task_claims SET finished_at=? WHERE claim_id=? AND finished_at IS NULL", (now(), claim_id))
    return {"claim": claim_id, "returned": n}


def checks_waiting_on(ws: Workspace, kind: str) -> list[str]:
    """The checks by queue that taking `kind` (decompose, expand or check) out of the queue takes back whole: those
    with a task of that kind waiting in the queue, and none of whose tasks a claim holds now (the rule of `withdraw`,
    which leaves a held task alone: its helper is answering it)."""
    out = []
    cut = _cutoff()
    for (hid,) in ws.query("SELECT hyp_id FROM hypotheses WHERE queue='waiting'"):
        cids = [r[0] for r in ws.query("SELECT claim_id FROM user_claims WHERE hyp_id=?", (hid,))]
        ids = [f"decompose:{hid}"] + [f"{k}:{c}" for c in cids for k in ("expand", "check")]
        cond = [f"t.task_id IN ({','.join('?' * len(ids))})"]
        args: list = [cut, *ids]
        for c in cids:  # the further rounds and parts of a check: check:<claim>:r2, :local, ... (a range on the key)
            cond.append("(t.task_id >= ? AND t.task_id < ?)")
            args += [f"check:{c}:", f"check:{c};"]
        rows = ws.query(f"SELECT t.kind, ({_WAITING}) AS waiting, NOT {_FREE} AS held FROM tasks t WHERE "
                        + " OR ".join(cond), args)
        if any(r["held"] for r in rows):
            continue
        if any(r["waiting"] and r["kind"] == kind for r in rows):
            out.append(hid)
    return out


def withdraw(ws: Workspace, kinds: list[str] | None = None, since: str | None = None,
             task_ids: list[str] | None = None) -> int:
    """Take waiting tasks out of the queue (Stop, or Remove in the queue panel): tasks not answered yet and not held
    by an open claim are deleted; answered tasks waiting for a second reading keep their first answer."""
    cond = [_WAITING, _FREE]
    args: list = [_cutoff()]
    if kinds:
        # with the tasks named, a `+` keeps SQLite on their keys (the kind's index would read every task that waits)
        cond.append(f"{'+' if task_ids else ''}t.kind IN ({','.join('?' * len(kinds))})")
        args += kinds
    if since:
        cond.append("t.queued_at >= ?")
        args.append(since)
    if task_ids is not None:
        if not task_ids:
            return 0
        cond.append(f"t.task_id IN ({','.join('?' * len(task_ids))})")
        args += task_ids
    rows = ws.query("SELECT t.task_id, t.status FROM tasks t WHERE " + " AND ".join(cond), args)
    # a few statements over hundreds of tasks each, in one transaction, not three per task
    done = [r[0] for r in rows if r[1] == "done"]
    gone = [r[0] for r in rows if r[1] != "done"]
    with ws.connect() as cx:
        for i in range(0, len(done), 500):
            chunk = done[i:i + 500]
            cx.execute(f"UPDATE tasks SET again=0, step=0, claimed_by=NULL WHERE task_id IN "
                       f"({','.join('?' * len(chunk))})", chunk)
        for i in range(0, len(gone), 500):
            chunk = gone[i:i + 500]
            marks = ",".join("?" * len(chunk))
            cx.execute(f"DELETE FROM results WHERE task_id IN ({marks})", chunk)
            cx.execute(f"DELETE FROM tasks WHERE task_id IN ({marks})", chunk)
    return len(rows)


# ---------------------------------------------------------------------------------------------
# after answers arrive
# ---------------------------------------------------------------------------------------------
def after_store(ws: Workspace, kinds: set[str] | list[str]) -> None:
    """What the app's own runs do after their loop, done whenever answers arrive from the queue: concepts are
    rebuilt after links; a check by queue moves on after its search words, parts or judgements."""
    kinds = set(kinds)
    if "link" in kinds:
        from .terms import rebuild_concepts

        rebuild_concepts(ws)
    if kinds & {"decompose", "expand", "check"}:
        advance(ws)
    if "theme" in kinds:
        with ws.connect() as cx:
            cx.execute("UPDATE theme_runs SET chat_model=COALESCE(chat_model, 'Claude Code') WHERE run_id IN (SELECT "
                       "json_extract(payload_json, '$.run_id') FROM tasks WHERE kind='theme' AND COALESCE(queued, 0)=1)")


def advance(ws: Workspace, hyp_ids: list[str] | None = None) -> list[str]:
    """Move every check by queue on as far as its answers allow (see claimcheck.advance_queued). Returns the ids of
    the hypotheses still waiting."""
    from .claimcheck import advance_queued

    return advance_queued(ws, hyp_ids)


# ---------------------------------------------------------------------------------------------
# waiting in the app
# ---------------------------------------------------------------------------------------------
QUEUE_POLL = 1.5  # seconds between two looks at a task Claude Code has not answered yet (2026-11-12: tests shorten it)


def wait_for(ws: Workspace, task_id: str, backend, poll: float | None = None) -> tuple[bool, list[str]]:
    """Wait until Claude Code has answered a task (through the connector, in another program): the app's own runs
    call this instead of a model. Stop (`backend.should_stop`) ends the wait; the progress line says what waits."""
    poll = QUEUE_POLL if poll is None else poll
    from .llm import BackendError
    from .tasks import mark_queued

    with ws.connect() as cx:
        mark_queued(cx, [task_id])
    last_report = 0.0
    t0 = time.time()
    while True:
        r0 = ws.query("SELECT kind, status, again, queued, access FROM tasks WHERE task_id=?", (task_id,))
        if not r0:
            return False, ["the task was withdrawn"]
        st = r0[0]
        if st["status"] == "done" and not st["again"]:
            return True, []
        if st["status"] == "failed":
            err = ws.query("SELECT errors_json FROM results WHERE task_id=? ORDER BY attempt DESC LIMIT 1", (task_id,))
            return False, json.loads(err[0][0]) if err else []
        if not st["queued"] or (st["access"] or "cloud") != "cloud":
            # 0.11.1: taken out of the queue meanwhile (a document's AI setting changed, or the document was removed):
            # Claude Code will never see it, so waiting on would never end
            return False, ["the AI setting of a document in this task changed while it waited: it is no longer handed "
                           "to Claude Code (a local model or you can read it)"]
        if backend.should_stop and backend.should_stop():
            raise BackendError("Stopped.")
        if backend.progress and time.time() - last_report >= 3:
            last_report = time.time()
            try:
                backend.progress({"phase": "queue", "task": st["kind"], "seconds": time.time() - t0,
                                  **queue_info(ws, st["kind"])})
            except Exception:  # noqa: BLE001 - a display problem must never stop the wait
                pass
        time.sleep(poll)


def queue_info(ws: Workspace, kind: str) -> dict:
    """The line a page shows while it waits: "Waiting for Claude Code: 120 passages to label · about 25 minutes".
    Asked every few seconds by each job that waits, so it counts only what the line says, from the two partial
    indexes (the same numbers as `status`, which works out every kind's models and runs)."""
    cutoff = _cutoff()
    total: dict[str, int] = {}
    first: dict[str, str | None] = {}
    for row in ws.query(f"SELECT kind, COUNT(*), MIN(queued_at) FROM tasks t WHERE {WAITING} GROUP BY kind"):
        total[row[0]], first[row[0]] = int(row[1]), row[2]
    held: dict[str, int] = {}
    for (k,) in ws.query(f"SELECT t.kind FROM tasks t WHERE {_HELD} AND {WAITING}", (cutoff,)):
        held[k] = held.get(k, 0) + 1
    n, being = total.get(kind, 0), held.get(kind, 0)
    command = f"/enlens-run {_quote_name(ws.root.name)}"
    est = estimate = None
    if n or ws.scalar("SELECT 1 FROM tasks WHERE COALESCE(queued, 0)=1 AND COALESCE(access, 'cloud')='cloud' AND "
                      "kind=? AND (status='failed' OR (status='done' AND COALESCE(again, 0)=0)) LIMIT 1", (kind,)):
        # the kind is listed in the queue (as `status` lists it): its estimate, "" when nothing of it waits
        sec = estimate_seconds(ws, kind, router(ws).model(kind) or "", n, PARALLEL)
        est = round(sec) if sec is not None else None
        estimate = _estimate_text(kind, n, sec)
    text = f"Waiting for Claude Code: {noun(kind, n)}" if n else "Waiting for Claude Code"
    if est:
        text += f" · {_duration(est)}"
    waiting = sum(total.values()) - sum(held.values())
    newest = max((f or "" for f in first.values()), default="")
    paused = _paused(ws, waiting, sum(held.values()), newest, _last_answer(ws) if waiting and not held else None)
    paused_text = None
    if paused:
        o, _held = order(ws)
        k = next((x for x in _kind_order(ws, o, total) if total[x] - held.get(x, 0) > 0), None)
        if k:
            run_total, run_done = _run_counts(ws, k, first[k]) if first[k] else (0, 0)
            paused_text = _paused_text(k, run_done, run_total, command)
    return {"text": text, "waiting": n, "being_answered": being, "paused": paused, "paused_text": paused_text,
            "command": command, "estimate": estimate, "privacy": PRIVACY_LINE}


# ---------------------------------------------------------------------------------------------
# answering the queue here (a local server or the Claude API: the shared installation, unattended)
# ---------------------------------------------------------------------------------------------
def run_here(ws: Workspace, backend, kinds: list[str] | None = None, limit: int | None = None,
             should_stop=None, progress=None, model: str | None = None) -> dict:
    """Answer the tasks waiting in the queue with this backend, kind by kind (so each model is loaded once), with
    the backend's routed models. For a shared installation with the team's Claude API key, or a local server."""
    from .tasks import run_one, run_stepups

    o, held = order(ws)
    todo_kinds = [k for k in o if k not in held and (not kinds or k in kinds)]
    out: dict = {"answered": 0, "failed": 0, "kinds": {}}
    may = access.backend_levels(backend)
    dflt = access.default(ws)
    total = sum(_waiting_count(ws, k) for k in todo_kinds)
    i = 0
    for k in todo_kinds:
        ids = [t["task_id"] for t in _waiting_rows(ws, k)]
        if limit:
            ids = ids[: max(0, limit - out["answered"] - out["failed"])]
        for tid in ids:
            if should_stop and should_stop():
                return out
            i += 1
            if progress:
                progress(i, total)
            with ws.connect() as cx:  # taken by this program, so a Claude Code session does not take it meanwhile
                # the setting worked out again first: a document's cap counts what the tasks before this one sent
                if access.recheck(cx, tid, dflt) not in may:
                    continue  # left for a model that may read it, or the person
                got = cx.execute(f"UPDATE tasks SET claimed_by='here', claimed_at=? WHERE task_id=? AND "
                                 f"{_FREE.replace('t.', '')}", (now(), tid, _cutoff())).rowcount
            if not got:  # a Claude Code session took it since the list was made (0.11.1): leave it to that session
                continue
            t0 = time.time()
            try:
                ok, _e = run_one(ws, tid, backend, model)
                t = ws.query("SELECT kind, role, forced_model, step, model FROM tasks WHERE task_id=?", (tid,))
                if t:
                    from .tasks import model_for

                    runs.timing(ws, k, model_for(t[0], backend, model), time.time() - t0)
            finally:
                with ws.connect() as cx:
                    cx.execute("UPDATE tasks SET claimed_by=NULL, claimed_at=NULL WHERE task_id=? AND claimed_by='here'",
                               (tid,))
            out["answered" if ok else "failed"] += 1
            out["kinds"][k] = out["kinds"].get(k, 0) + 1
        if ids:
            after_store(ws, {k})
    if getattr(getattr(backend, "router", None), "route", "") == "local":
        out["stepped_up"] = run_stepups(ws, backend, todo_kinds, should_stop, queued=True)
    advance(ws)
    return out


# ---------------------------------------------------------------------------------------------
# 0.8.1: model tests by queue (label compare, the model test): asked on a scratch copy, nothing stored
# ---------------------------------------------------------------------------------------------
def remove_copy(copy: Workspace, tries: int | None = None, windows: bool | None = None) -> bool:
    """Remove a scratch copy of a project (answer_on_copy); True when it is gone. 0.15.7: every connection to it is
    closed first, in every thread (also the ones open_project keeps), or Windows keeps the copy: its database is open.
    0.16.0rc2: a helper that reads the copy at that moment (Claude Code's connector in the middle of a call) opens it
    again before it is gone, and Windows keeps it then too: there, closing and removing are tried again for a few
    seconds. 2026-11-12: on Windows for about 8 seconds (12 tries) instead of 3.6, which a busy computer did not always
    give the helper; and on macOS and Linux too, for about a second (4 tries): opening the copy just then makes its
    database file again, so its folder is not empty when it is removed (seen on Linux under load)."""
    import os
    import shutil

    from . import home

    windows = os.name == "nt" if windows is None else windows
    tries = max(1, (12 if windows else 4) if tries is None else tries)
    for attempt in range(tries):
        copy.close_all()
        home.close_project(copy.root)
        shutil.rmtree(copy.root, ignore_errors=True)
        if not copy.root.exists():
            break
        if attempt + 1 < tries:
            time.sleep(0.1 * (attempt + 1))
    return not copy.root.exists()


def answer_on_copy(ws: Workspace, items: list[tuple[str, str, dict, str]], backend, purpose: str = "test",
                   should_stop=None) -> tuple[dict, dict]:
    """Have Claude Code answer tasks without storing anything in `ws`: they wait in the queue of a scratch copy of
    the project (its documents, no tasks or answers), each kept on its model, and the copy is removed afterwards.

    `items`: [(task_id, kind, payload, model alias)]. While it waits the progress line names the copy, so the
    researcher types `/enlens-run "<copy>"`. Returns ({task_id: the first answer as given (raw JSON text), or None
    when there was none}, {(kind, model): median seconds per task as Claude Code took them, or None}).
    A stop (`backend.should_stop`) raises BackendError, as any wait does; the copy is removed then too."""
    import statistics

    from . import home
    from .evaluation import _copy
    from .tasks import _insert_task

    if local_only():
        raise ValueError("This installation keeps everything on this computer (local only): nothing is handed to "
                         "Claude Code here.")
    name = home.unique_project_name(home.safe_name(f"{ws.root.name} {purpose}") or "model test")
    copy = _copy(ws, name)
    try:  # a copy left behind by a crash goes to the trash with the quick looks (noted under the data folder's lock)
        home.mark_temporary(name, file="", **{"from": ws.root.name, "scratch": purpose})
    except Exception:  # noqa: BLE001 - removed below in any case
        pass
    try:
        # 0.11: only tasks whose documents Claude may read go to the copy's queue; the others get no answer. The
        # copy's own ledger starts empty: what Claude Code actually takes from it is written there (next_tasks) and
        # carried into this project's ledger below, so a test stopped before a batch left records nothing (0.11.1)
        with ws.connect() as wcx:
            items = [it for it in items if access.label_payload(wcx, it[2]) == "cloud"]
        with copy.connect() as cx:
            cx.execute("DELETE FROM ai_sent")
            for tid, kind, payload, model in items:
                _insert_task(cx, tid, kind, model, payload)
                cx.execute("UPDATE tasks SET forced_model=?, model=?, queued=1, queued_at=?, status='pending', "
                           "attempts=0, access='cloud' WHERE task_id=?", (model, model, now(), tid))
        for tid, *_rest in items:
            if should_stop and should_stop():
                break
            wait_for(copy, tid, backend)
        raws = {}
        for tid, *_rest in items:
            r = copy.query("SELECT raw_json FROM results WHERE task_id=? ORDER BY attempt LIMIT 1", (tid,))
            raws[tid] = r[0][0] if r else None
        secs = {}
        for _tid, kind, _p, model in items:
            xs = copy.meta(f"seconds:{kind}:{model}") or []
            secs[(kind, model)] = round(statistics.median(xs), 1) if xs else None
        return raws, secs
    finally:
        try:
            sent = copy.query("SELECT passage_id, doc_id, route, task_id, sent_at, feature FROM ai_sent")
            if sent:
                with ws.connect() as wcx:
                    wcx.executemany("INSERT INTO ai_sent(passage_id, doc_id, route, task_id, sent_at, feature) "
                                    "VALUES (?,?,?,?,?,?)",
                                    [(r[0], r[1], r[2], None, r[4], f"{r[5]} ({purpose})") for r in sent])
        except Exception:  # noqa: BLE001 - the ledger must not stop the clean-up below
            pass
        remove_copy(copy)
        if not copy.root.exists():  # 0.15.7: still there (a file held): moved to the trash later, as a quick look
            try:
                home.forget_temporary(name)
            except Exception:  # noqa: BLE001
                pass
