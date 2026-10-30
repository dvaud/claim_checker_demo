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

import json
import time
import uuid
from datetime import datetime, timedelta, timezone

from . import access, prompts, routing, runs
from .store import Workspace, now

CLAIM_MINUTES = 30
PAUSED_AFTER = 180          # seconds without an answer, nothing claimed and work waiting: the run has paused
TOKEN_BUDGET = 15000        # the most a batch's prompts may hold (well under the connector's 25,000-token output cap)
CONNECTOR_CAP = 25000       # the connector's output cap: the system prompt and the task prompts of a batch together
BATCH = {"label": 20, "link": 10, "theme": 5, "expand": 5, "decompose": 5, "resolve": 4, "check": 1, "reread": 1,
         "second": 1,
         # the SDG pack (0.8.1): its system prompts are sent once a batch; extract's holds the 169 targets (~11,000
         # tokens), so its batch is bounded by CONNECTOR_CAP as well
         "split": 5, "extract": 8, "verify": 10, "verify_set": 3}
# the researcher's own requests first, then small jobs, then the bulk; the SDG pack's batch pipeline last
ORDER = ("decompose", "expand", "check", "reread", "second", "theme", "link", "label", "resolve",
         "split", "verify_set", "verify", "extract")
KINDS = ORDER

NOUN = {"label": ("passage to label", "passages to label"), "link": ("pair of terms", "pairs of terms"),
        "theme": ("theme to name", "themes to name"), "expand": ("set of search words", "sets of search words"),
        "decompose": ("hypothesis to split", "hypotheses to split"),
        "resolve": ("window of references", "windows of references"),
        "check": ("set of excerpts to judge", "sets of excerpts to judge"),
        "reread": ("excerpt to read again", "excerpts to read again"),
        "second": ("set of excerpts for a second opinion", "sets of excerpts for a second opinion"),
        "split": ("justification to split", "justifications to split"),
        "extract": ("passage to extract claims from", "passages to extract claims from"),
        "verify": ("claim and passage to check", "claims and passages to check"),
        "verify_set": ("VCA claim to check", "VCA claims to check")}
SHORT = {"label": "labels", "link": "pairs of terms", "theme": "theme names", "expand": "sets of search words",
         "decompose": "hypotheses to split", "resolve": "windows of references", "check": "sets of excerpts",
         "reread": "excerpts to read again", "second": "second opinions", "split": "justifications to split",
         "extract": "passages to extract", "verify": "claims to check", "verify_set": "VCA claims to check"}
KIND_TITLE = {"label": "Codebook labels", "link": "How concepts relate", "theme": "Theme names",
              "expand": "Search words", "decompose": "Splitting hypotheses", "resolve": "References in documents",
              "check": "Judging excerpts", "reread": "Reading an excerpt again", "second": "Second opinions",
              "split": "SDG pack: splitting justifications", "extract": "SDG pack: extracting claims",
              "verify": "SDG pack: checking claims", "verify_set": "SDG pack: checking VCA claims"}

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


# a task waits when it is queued and not answered (or answered and to be read again by the stronger model), and not
# held by a claim that is still open
_WAITING = ("COALESCE(t.queued, 0)=1 AND COALESCE(t.access, 'cloud')='cloud' AND "
            "(t.status IN ('pending', 'retry') OR (t.status='done' AND t.again=1))")
_FREE = "(t.claimed_by IS NULL OR t.claimed_at < ?)"


def effective_model(t, r: routing.Router) -> str:
    return t["forced_model"] or r.model(routing.task_kind(t), int(t["step"] or 0)) or t["model"] or ""


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
def _waiting_rows(ws: Workspace, kind: str | None = None):
    sql = (f"SELECT t.task_id, t.kind, t.role, t.step, t.forced_model, t.model, t.queued_at, t.attempts, t.status, "
           f"t.again "
           f"FROM tasks t WHERE {_WAITING} AND {_FREE}")
    args: list = [_cutoff()]
    if kind:
        sql += " AND t.kind=?"
        args.append(kind)
    return ws.query(sql + " ORDER BY t.again DESC, t.queued_at, t.task_id", args)


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


def status(ws: Workspace, project: str | None = None, parallel: int = 2) -> dict:
    """The queue of one project: per kind what waits, is being answered, is done or failed; the groups a run hands
    to the helpers (kind, model, helper); estimates; and whether the work has paused."""
    r = router(ws)
    o, held = order(ws)
    cutoff = _cutoff()
    rows = ws.query("SELECT t.task_id, t.kind, t.role, t.status, t.again, t.step, t.forced_model, t.model, t.claimed_by, "
                    "t.claimed_at, t.queued_at FROM tasks t WHERE COALESCE(t.queued, 0)=1 AND COALESCE(t.access, 'cloud')='cloud'")
    per: dict[str, dict] = {}
    groups: dict[tuple, dict] = {}
    for t in rows:
        k = t["kind"]
        d = per.setdefault(k, {"kind": k, "title": KIND_TITLE.get(k, k), "waiting": 0, "being_answered": 0, "done": 0,
                               "failed": 0, "stronger_model": 0, "first_queued": None, "run_total": 0, "run_done": 0})
        waiting = t["status"] in ("pending", "retry") or (t["status"] == "done" and t["again"])
        claimed = bool(t["claimed_by"]) and (t["claimed_at"] or "") >= cutoff
        if waiting and claimed:
            d["being_answered"] += 1
        elif waiting:
            d["waiting"] += 1
            m, hp = effective_model(t, r), effective_helper(t, r)
            g = groups.setdefault((k, m, hp), {"kind": k, "model": m, "helper": hp, "waiting": 0})
            g["waiting"] += 1
        elif t["status"] == "done":
            d["done"] += 1
        elif t["status"] == "failed":
            d["failed"] += 1
        if waiting and t["step"]:
            d["stronger_model"] += 1
        if waiting and (d["first_queued"] is None or (t["queued_at"] or "") < d["first_queued"]):
            d["first_queued"] = t["queued_at"]
    # the current run of a kind: the tasks queued since its oldest one still open, for "Paused at 340 of 7,868"
    for k, d in per.items():
        if d["first_queued"]:
            n = ws.query("SELECT COUNT(*), SUM(status IN ('done', 'failed') AND again=0) FROM tasks WHERE "
                         "COALESCE(queued, 0)=1 AND kind=? AND queued_at >= ?", (k, d["first_queued"]))[0]
            d["run_total"], d["run_done"] = int(n[0] or 0), int(n[1] or 0)
    last = ws.scalar("SELECT MAX(received_at) FROM results WHERE route='Claude Code'")
    open_claims = ws.scalar("SELECT COUNT(*) FROM task_claims WHERE finished_at IS NULL AND expires_at > ?", (now(),))
    waiting_total = sum(d["waiting"] for d in per.values())
    active = sum(d["being_answered"] for d in per.values())
    newest = max((d["first_queued"] or "" for d in per.values()), default="")
    since = max(_ts(last) or 0, _ts(newest) or 0)
    paused = bool(waiting_total and not active and not open_claims and since and time.time() - since > PAUSED_AFTER)
    kinds = []
    for k in [x for x in o if x in per] + [x for x in per if x not in o]:
        d = per[k]
        model = r.model(k) or ""
        est = estimate_seconds(ws, k, model, d["waiting"] + d["being_answered"], parallel)
        d.update(model=model, step_up=r.step_up(k), helper=r.helper(k), held=k in held,
                 estimate_seconds=round(est) if est is not None else None,
                 estimate=_estimate_text(k, d["waiting"] + d["being_answered"], est))
        d.pop("first_queued")
        if d["waiting"] or d["being_answered"] or d["failed"] or d["done"]:
            kinds.append(d)
    rank = {k: i for i, k in enumerate(o)}
    gl = sorted((g for g in groups.values() if g["kind"] not in held),
                key=lambda g: (rank.get(g["kind"], 99), g["model"], g["helper"]))
    name = project or ws.root.name
    out = {"project": name, "kinds": kinds, "groups": gl, "order": o, "held": held, "waiting": waiting_total,
           "being_answered": active, "paused": paused, "last_answer_at": last, "privacy": PRIVACY_LINE,
           "local_only": local_only(), "command": f"/enlens-run {_quote_name(name)}", "claim_minutes": CLAIM_MINUTES,
           "parallel": parallel}
    if paused:
        k = next((x for x in kinds if x["waiting"]), None)
        if k:
            out["paused_text"] = (f"Paused at {k['run_done']:,} of {k['run_total']:,} {SHORT.get(k['kind'], 'tasks')}. "
                                  f"To go on, type {out['command']} in Claude Code.")
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
    kinds = [kind] if kind else [k for k in o if k not in held]
    if kind and kind not in KINDS:
        raise ValueError(f"Unknown kind of task {kind!r}. Kinds: {', '.join(KINDS)}.")
    for k in kinds:
        cand = [t for t in _waiting_rows(ws, k) if (model is None or effective_model(t, r) == model)
                and (helper is None or effective_helper(t, r) == helper)]
        if not cand:
            continue
        m = effective_model(cand[0], r)
        hp = effective_helper(cand[0], r)
        cand = [t for t in cand if effective_model(t, r) == m and effective_helper(t, r) == hp]
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
            for t in cand:
                if len(picked) >= size:
                    break
                full = cx.execute("SELECT * FROM tasks WHERE task_id=?", (t["task_id"],)).fetchone()
                _sys, user = render(ws, full)
                cost = estimate_tokens(user)
                if picked and budget + cost > cap:
                    break
                got = cx.execute("UPDATE tasks SET claimed_by=?, claimed_at=? WHERE task_id=? AND COALESCE(queued, 0)=1 "
                                 "AND COALESCE(access, 'cloud')='cloud' "
                                 "AND (claimed_by IS NULL OR claimed_at < ?) AND (status IN ('pending', 'retry') OR "
                                 "(status='done' AND again=1))", (cid, at, t["task_id"], _cutoff())).rowcount
                if got:
                    picked.append({"task_id": t["task_id"], "prompt": user})
                    budget += cost
                    # 0.11: the passages of this task leave the computer now, with the batch
                    access.record_sent(cx, t["task_id"], json.loads(full["payload_json"]), "Claude Code", k)
            if not picked:
                continue
            cx.execute("INSERT INTO task_claims(claim_id, kind, model, helper, route, taken_by, task_ids_json, claimed_at, "
                       "expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
                       (cid, k, m, hp, "Claude Code", (taken_by or "")[:120],
                        json.dumps([p["task_id"] for p in picked]), at, expires))
        left = len(_waiting_rows(ws, k))
        return {"claim": cid, "kind": k, "model": m, "helper": hp, "prompt_version": prompts.VERSIONS[k],
                "system": system, "tasks": picked, "expires_at": expires,
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
    from .routing import STEP_UP_BELOW, certainty
    from .tasks import MAX_ATTEMPTS, ingest_result, parse_json

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
        ok, errors = ingest_result(ws, tid, raw, model=model, provenance=prov, route="Claude Code", helper=helper,
                                   claimed_at=c["claimed_at"])
        after = ws.query("SELECT * FROM tasks WHERE task_id=?", (tid,))[0]
        item = {"task_id": tid, "stored": ok, "problems": errors if not ok else [],
                "attempts_left": max(0, MAX_ATTEMPTS - int(after["attempts"]))}
        moved = False
        rk = routing.task_kind(t)
        if not int(t["step"] or 0) and not t["forced_model"] and r.step_up(rk) and not (t["status"] == "done"):
            if ok:
                try:
                    conf = certainty(t["kind"], parse_json(raw))
                except ValueError:
                    conf = None
                if conf is not None and conf < STEP_UP_BELOW:
                    with ws.connect() as cx:
                        cx.execute("UPDATE tasks SET step=1, again=1, attempts=0, claimed_by=NULL, claimed_at=NULL "
                                   "WHERE task_id=?", (tid,))
                    item["read_again_by"] = r.step_up(rk)
                    item["note"] = (f"Stored. The answer was unsure (certainty {conf:.2f}), so a stronger model "
                                    f"({item['read_again_by']}) reads this task once more; it is no longer yours.")
                    moved = True
            elif after["status"] == "retry" and int(after["attempts"]) >= MAX_ATTEMPTS - 1:
                with ws.connect() as cx:
                    cx.execute("UPDATE tasks SET step=1, claimed_by=NULL, claimed_at=NULL WHERE task_id=?", (tid,))
                item["moved_to"] = r.step_up(rk)
                item["note"] = (f"Two answers were rejected, so the last attempt goes to a stronger model "
                                f"({item['moved_to']}); it is no longer yours.")
                item["attempts_left"] = 0
                moved = True
        if not moved and (ok or after["status"] in ("failed", "done")):
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
        for _ in range(stored):
            runs.timing(ws, c["kind"], c["model"], per_task)
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


def withdraw(ws: Workspace, kinds: list[str] | None = None, since: str | None = None,
             task_ids: list[str] | None = None) -> int:
    """Take waiting tasks out of the queue (Stop, or Remove in the queue panel): tasks not answered yet and not held
    by an open claim are deleted; answered tasks waiting for a second reading keep their first answer."""
    cond = [_WAITING, _FREE]
    args: list = [_cutoff()]
    if kinds:
        cond.append(f"t.kind IN ({','.join('?' * len(kinds))})")
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
    with ws.connect() as cx:
        for r0 in rows:
            if r0["status"] == "done":
                cx.execute("UPDATE tasks SET again=0, step=0, claimed_by=NULL WHERE task_id=?", (r0["task_id"],))
            else:
                cx.execute("DELETE FROM results WHERE task_id=?", (r0["task_id"],))
                cx.execute("DELETE FROM tasks WHERE task_id=?", (r0["task_id"],))
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
def wait_for(ws: Workspace, task_id: str, backend, poll: float = 1.5) -> tuple[bool, list[str]]:
    """Wait until Claude Code has answered a task (through the connector, in another program): the app's own runs
    call this instead of a model. Stop (`backend.should_stop`) ends the wait; the progress line says what waits."""
    from .llm import BackendError
    from .tasks import mark_queued

    with ws.connect() as cx:
        mark_queued(cx, [task_id])
    last_report = 0.0
    t0 = time.time()
    while True:
        r0 = ws.query("SELECT kind, status, again FROM tasks WHERE task_id=?", (task_id,))
        if not r0:
            return False, ["the task was withdrawn"]
        st = r0[0]
        if st["status"] == "done" and not st["again"]:
            return True, []
        if st["status"] == "failed":
            err = ws.query("SELECT errors_json FROM results WHERE task_id=? ORDER BY attempt DESC LIMIT 1", (task_id,))
            return False, json.loads(err[0][0]) if err else []
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
    """The line a page shows while it waits: "Waiting for Claude Code: 120 passages to label · about 25 minutes"."""
    q = status(ws)
    k = next((x for x in q["kinds"] if x["kind"] == kind), None) or {}
    n = k.get("waiting", 0) + k.get("being_answered", 0)
    text = f"Waiting for Claude Code: {noun(kind, n)}" if n else "Waiting for Claude Code"
    est = k.get("estimate_seconds")
    if est:
        text += f" · {_duration(est)}"
    return {"text": text, "waiting": n, "being_answered": k.get("being_answered", 0), "paused": q["paused"],
            "paused_text": q.get("paused_text"), "command": q["command"], "estimate": k.get("estimate"),
            "privacy": PRIVACY_LINE}


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
    total = sum(len(_waiting_rows(ws, k)) for k in todo_kinds)
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
                cx.execute("UPDATE tasks SET claimed_by='here', claimed_at=? WHERE task_id=?", (now(), tid))
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
def answer_on_copy(ws: Workspace, items: list[tuple[str, str, dict, str]], backend, purpose: str = "test",
                   should_stop=None) -> tuple[dict, dict]:
    """Have Claude Code answer tasks without storing anything in `ws`: they wait in the queue of a scratch copy of
    the project (its documents, no tasks or answers), each kept on its model, and the copy is removed afterwards.

    `items`: [(task_id, kind, payload, model alias)]. While it waits the progress line names the copy, so the
    researcher types `/enlens-run "<copy>"`. Returns ({task_id: the first answer as given (raw JSON text), or None
    when there was none}, {(kind, model): median seconds per task as Claude Code took them, or None}).
    A stop (`backend.should_stop`) raises BackendError, as any wait does; the copy is removed then too."""
    import shutil
    import statistics

    from . import home
    from .evaluation import _copy
    from .tasks import _insert_task

    if local_only():
        raise ValueError("This installation keeps everything on this computer (local only): nothing is handed to "
                         "Claude Code here.")
    name = home.unique_project_name(home.safe_name(f"{ws.root.name} {purpose}") or "model test")
    copy = _copy(ws, name)
    try:  # a copy left behind by a crash goes to the trash with the quick looks
        q = home._quicklooks()
        q[name] = {"created_at": time.time(), "file": "", "from": ws.root.name, "scratch": purpose}
        home._save_quicklooks(q)
    except Exception:  # noqa: BLE001 - removed below in any case
        pass
    try:
        # 0.11: only tasks whose documents Claude may read go to the copy's queue; the others get no answer. Their
        # passages are written to this project's ledger now (the copy and its own ledger are removed afterwards)
        with ws.connect() as wcx:
            items = [it for it in items if access.label_payload(wcx, it[2]) == "cloud"]
            for tid, kind, payload, _model in items:
                access.record_sent(wcx, None, payload, "Claude Code", f"{kind} ({purpose})")
        with copy.connect() as cx:
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
        shutil.rmtree(copy.root, ignore_errors=True)
        try:
            q = home._quicklooks()
            q.pop(name, None)
            home._save_quicklooks(q)
        except Exception:  # noqa: BLE001
            pass
