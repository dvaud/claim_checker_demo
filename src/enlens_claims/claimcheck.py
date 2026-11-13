"""Check hypotheses and claims, typed by a person, against the documents of a project.

A hypothesis is checked in these steps:

0. (optional) A model splits the hypothesis into the claims that must all hold for it to be true ("decompose"),
   so each part is searched and graded on its own. Without this step the hypothesis is one claim.
1. (optional) For each claim, a model writes search terms: synonyms, related technical words and the words a source
   would use to state the opposite. Keyword ranking misses evidence worded differently; this narrows that gap.
2. The best passages are picked by BM25 on the claim and its terms (fused with semantic search when the project
   has embeddings), at most `per_doc` from one document first so one long report cannot crowd out the others.
3. A model grades each passage that bears on the claim: supports, partially supports or refutes, with a quote.
   Quotes are checked against the passage like every other answer.
4. Each claim gets a status from its grades; a decomposed hypothesis gets one from its parts (see `aggregate`).

Everything is stored like any other task (tasks, results, verifications), so a check can be audited later.
A check started by a model outside this program (Claude in a chat, through the connector) uses `open_check`,
`submit_grades` and `more_passages` instead of a backend.
"""
from __future__ import annotations

import bisect
import csv
import inspect
import io
import json
import uuid
from typing import Any, Callable

from . import __version__, access, frameworks, routing, schema, tasks
from .reread import is_tombstone  # noqa: F401  (still importable from here)
from .search import neighbours, passage_index, rank_passages  # noqa: F401  (re-exported for callers)
from .store import Workspace, now
from .textutil import find_quote, find_selection  # noqa: F401  (still importable from here)

# the statuses live in verdicts.py (pure, imports nothing from here); every name stays importable from here
from .verdicts import (  # noqa: F401
    PERSON, STATUS_TEXT, WAITING_LOCAL, WAITING_YOU, STATUS_HELP, STATUS_NEXT, GRADES, USER_VERDICTS,
    effective, changed_by_person, first_reading, stronger_eligible, _before_stronger, _graded,
    _waits_for_person, claim_status, balance, who_says_what, aggregate, _queued_open, _status_of_rounds,
)

Progress = Callable[..., None]  # progress(step, message) or progress(step, message, info)

CHAT_MODEL = "claude (chat)"


def _new_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:12]


def _adapt(progress: Progress | None) -> Callable[[str, str, dict], None]:
    """Accept both progress(step, message) and progress(step, message, info)."""
    if progress is None:
        return lambda step, msg, info: None
    try:
        params = inspect.signature(progress).parameters.values()
        three = sum(p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) for p in params) >= 3 or \
            any(p.kind == p.VAR_POSITIONAL for p in params)
    except (TypeError, ValueError):
        three = False
    def call(s: str, m: str, i: dict) -> None:
        try:
            progress(s, m, i) if three else progress(s, m)
        except Exception:  # a display problem must never stop a check
            pass

    return call


# ---------------------------------------------------------------------------------------------
# creating checks
# ---------------------------------------------------------------------------------------------
def _clean(text: str) -> str:
    text = " ".join((text or "").split())
    if len(text) < 10:
        raise ValueError("Write the claim as a sentence (at least 10 characters).")
    if len(text) > 2000:
        raise ValueError("Keep the hypothesis under 2,000 characters; split a longer text into several hypotheses.")
    return text


def create_hypothesis(ws: Workspace, text: str, framework: str | None = None, code: str | None = None,
                      options: dict | None = None, batch_id: str | None = None, hyp_id: str | None = None,
                      origin: str | None = None, origin_id: str | None = None) -> str:
    """A hypothesis record (not checked yet); returns its id. 0.13.6: `origin` says where it comes from ("batch" for
    Check several, or an add-on's own kind) and `origin_id` the id of what it comes from there, so an add-on that
    makes hypotheses needs no column or argument of its own."""
    text = _clean(text)
    fw, code, _desc, _label = frameworks.resolve(ws, framework, code)
    hid = hyp_id or _new_id("h")
    if origin is None and batch_id:
        origin, origin_id = "batch", batch_id
    with ws.connect() as cx:
        cx.execute("INSERT INTO hypotheses(hyp_id, text, framework, code, options_json, decomposed, created_at, batch_id, "
                   "origin, origin_id, app_version) VALUES (?,?,?,?,?,0,?,?,?,?,?)",
                   (hid, text, fw, code, json.dumps(options or {}), now(), batch_id, origin, origin_id, __version__))
        from . import researchlog  # 0.16

        researchlog.record(cx, "check-added", f"Checked the hypothesis {researchlog.quoted(text, 200)}"
                                              + (" (one of a set)." if batch_id else "."), "check", hid, text,
                           data={"batch_id": batch_id} if batch_id else None)
    return hid


new_hypothesis = create_hypothesis  # the name before 0.13.6


def new_claim(ws: Workspace, text: str, target: str | None = None, options: dict | None = None,
              hyp_id: str | None = None, part: int = 0, role: str | None = None, framework: str | None = None,
              claim_id: str | None = None) -> str:
    """One claim to check. Without `hyp_id` it is a hypothesis of its own (same id), as in 0.4."""
    text = _clean(text)
    fw, code, _desc, _label = frameworks.resolve(ws, framework or ("sdg" if target else None), target)
    cid = claim_id or _new_id("u")
    with ws.connect() as cx:
        if hyp_id is None:
            cx.execute("INSERT INTO hypotheses(hyp_id, text, framework, code, options_json, decomposed, created_at, "
                       "app_version) VALUES (?,?,?,?,?,0,?,?)",
                       (cid, text, fw, code, json.dumps(options or {}), now(), __version__))
            hyp_id = cid
        cx.execute("INSERT INTO user_claims(claim_id, text, target, options_json, created_at, hyp_id, part, role, framework) "
                   "VALUES (?,?,?,?,?,?,?,?,?)", (cid, text, code, json.dumps(options or {}), now(), hyp_id, part, role, fw))
    return cid


def _add_task(ws: Workspace, task_id: str, kind: str, model: str, payload: dict) -> None:
    with ws.connect() as cx:
        tasks._insert_task(cx, task_id, kind, model, payload)


# ---------------------------------------------------------------------------------------------
# 0.11: a round of excerpts split by who may read them. The excerpts of a round are grouped by their documents'
# AI settings: those the main model may read go into the round's task (`check:{cid}` or `check:{cid}:r{n}`), those
# only a local AI may read (when the main model is Claude) into `…:local` for the local model, and those no AI may
# read (or local ones without a local model) into `…:person`, which no model answers: they wait for a person's
# judgement. The round is still shown as one; each excerpt says who read it.
# ---------------------------------------------------------------------------------------------
PART_SUFFIXES = tasks.PART_SUFFIXES
round_base = tasks.round_base
ROUTE_NAMES = routing.ROUTE_NAMES


def _rounds(ws: Workspace, cid: str) -> list[list]:
    """The check's rounds in order, each the list of its parts (task rows)."""
    return _group_rounds(_check_tasks(ws, cid))


def _main_part(parts: list):
    return next((t for t in parts if t["task_id"] == round_base(t["task_id"])), None)


def _group_rounds(task_rows: list) -> list[list]:
    """Task rows of one claim grouped into rounds (each the list of its parts), in order."""
    groups: dict[str, list] = {}
    for t in task_rows:
        groups.setdefault(round_base(t["task_id"]), []).append(t)
    return list(groups.values())


def _round_waiting(parts: list) -> bool:
    """Whether a round still waits: in the queue for Claude Code, or a `:local` part not read yet (the same rule for
    the result page, the Results list and the map, 0.11.1)."""
    return any(_queued_open(t) or (t["task_id"].endswith(":local") and t["status"] in ("pending", "retry"))
               for t in parts)


def _round_status(parts: list) -> str:
    """A round's status from the parts a model answers. 0.14.3: a part no model answers (`:person`, born done) is
    neutral; it made a round whose main part failed count as done, which hid the failure ("No evidence found"). A
    model part still waiting makes the round wait; otherwise the main part decides (a `:local` part that failed
    beside an answered main part is shown on its own, see `local_failed`); a round without a main part is done when
    one of its model parts is. A round of person parts only is done: nothing is left for a model."""
    sts = [t["status"] for t in parts if not _is_person(t)]
    if not sts:
        return "done" if parts else "pending"
    for s in ("retry", "pending"):
        if s in sts:
            return s
    main = _main_part(parts)
    if main is not None and not _is_person(main):
        return main["status"]
    if "done" in sts:
        return "done"
    return "failed" if "failed" in sts else sts[-1]


def _counting(groups: list[list], statuses: list[str] | None = None) -> tuple[Callable, set[str]]:
    """0.14.3: which judgements of a check may count as evidence, as (counts(verification row) -> bool, the excerpts
    of rounds that failed). In a round whose check failed none of the AI's judgements count, a local model's for the
    same round neither: the answer says the check did not work, and the evidence must not say otherwise. A person's
    own judgement there counts when another round of the check was answered (when every round failed, nothing counts:
    the check did not work). Rows need `passage_id` and `user_verdict`; task rows need `payload_json`."""
    sts = statuses if statuses is not None else [_round_status(g) for g in groups]
    failed: set[str] = set()
    for g, st in zip(groups, sts):
        if st == "failed":
            for t in g:
                failed.update(x[0] for x in _excerpts(t))
    if not failed:
        return (lambda v: True), failed
    people_count = "done" in sts
    return (lambda v: v["passage_id"] not in failed or (people_count and bool(v["user_verdict"]))), failed


def _excerpts(t) -> list[tuple]:
    """(passage id, document id, …) of each excerpt a check task shows: from a light row (`_light_checks`), else from
    its payload."""
    if isinstance(t, dict) and "excerpts" in t:
        return t["excerpts"]
    return [(p["passage_id"], p["doc_id"]) for p in json.loads(t["payload_json"])["passages"]]


def _light_checks(ws: Workspace, claim_ids: list[str] | None = None, titles: bool = False) -> dict[str, list[dict]]:
    """The check tasks of these claims (of every claim, with None) by claim, each in the order they were made, as
    light rows: task_id, status, queued, model, `excerpts`, the (passage id, document id[, title]) of each excerpt,
    and `n`, its place among them all.
    SQLite reads the payloads (json_each) and hands over only those ids: a list of every check held each check's
    whole text in memory to count its excerpts."""
    cols = "json_extract(j.value, '$.passage_id'), json_extract(j.value, '$.doc_id')" + (
        ", json_extract(j.value, '$.title')" if titles else "")
    sql = (f"SELECT t.task_id, t.status, t.queued, t.model, CASE WHEN json_valid(t.payload_json) THEN (SELECT "
           f"json_group_array(json_array({cols})) FROM json_each(t.payload_json, '$.passages') j) END AS ex "
           "FROM tasks t WHERE ")
    if claim_ids is None:
        rows = ws.query(sql + "t.kind='check' ORDER BY t.created_at, t.rowid")
    else:
        rows = []
        for cid in claim_ids:
            cond, args = tasks.check_task_ids_sql(cid)
            rows += ws.query(sql + f"+t.kind='check' AND {cond.replace('task_id', 't.task_id')} "
                             "ORDER BY t.created_at, t.rowid", args)
    out: dict[str, list[dict]] = {}
    for n, r in enumerate(rows):
        if r["ex"] is None:  # a payload SQLite cannot read: read (and fail) as before
            ex = [tuple(x) for x in _excerpts(ws.query("SELECT payload_json FROM tasks WHERE task_id=?",
                                                       (r["task_id"],))[0])]
        else:
            ex = [tuple(x) for x in json.loads(r["ex"])]
        out.setdefault(r["task_id"].split(":")[1], []).append(
            {"task_id": r["task_id"], "status": r["status"], "queued": r["queued"], "model": r["model"], "excerpts": ex,
             "n": n})
    return out


def _only_local(claims: list, rounds_of: Callable[[str], list]) -> bool:
    """`only_local_waits` from a hypothesis's claims ({claim_id, stage}) and their check tasks (`rounds_of`)."""
    if not claims or any(c["stage"] not in ("judge", "done", None) for c in claims):
        return False
    open_ = [t for c in claims for t in rounds_of(c["claim_id"]) if t["status"] in ("pending", "retry")]
    return bool(open_) and all(t["task_id"].endswith(":local") for t in open_)


def _is_person(t) -> bool:
    return (t["model"] or "") == PERSON


def _person_rows(cx, task_id: str, cid: str, passages: list[dict]) -> None:
    """The excerpts of a part no model reads: each waits for a person's judgement (no AI verdict)."""
    for p in passages:
        vid = f"v{tasks._h(task_id, p['passage_id'])}"
        cx.execute("INSERT OR REPLACE INTO verifications(ver_id, subject_kind, subject_id, passage_id, doc_id, verdict, "
                   "confidence, quote, start, end, page, model, prompt_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (vid, "user_claim", cid, p["passage_id"], p["doc_id"], "not_enough_info", None, None, None, None,
                    p.get("page"), PERSON, None))


def _add_round(ws: Workspace, cid: str, base: str, payload: dict, model: str, main_levels=("cloud",),
               local_reader: bool = False, cx=None) -> dict[str, str]:
    """Create the parts of one round (see above). Returns {"main"|"local"|"person": task id} for the parts made."""
    if cx is None:
        with ws.connect() as c:
            return _add_round(ws, cid, base, payload, model, main_levels, local_reader, c)
    lv = access.levels(cx, [p["doc_id"] for p in payload["passages"]])
    # 0.13.7: an add-on's floor for the check's own text (access.register_floor) goes with every excerpt, so each is
    # read by a model allowed to read both, and not by the main model on its document's setting alone
    beside = access.floor(cx, payload)
    main, local, person = [], [], []
    for p in payload["passages"]:
        level = access.most([lv.get(p["doc_id"], "none"), beside])
        if level in main_levels:
            main.append(p)
        elif level == "local" and local_reader:
            local.append(p)
        else:
            person.append(p)
    total = len(payload["passages"])
    out: dict[str, str] = {}
    for key, tid, ps in (("main", base, main), ("local", base + ":local", local), ("person", base + ":person", person)):
        if not ps:
            continue
        pl = {**payload, "passages": ps}
        if len(ps) < total and key != "person":
            pl["read_elsewhere"] = total - len(ps)  # told to the model, so a summary does not speak for them
        if key == "person":
            if cx.execute("SELECT 1 FROM tasks WHERE task_id=?", (tid,)).fetchone():
                continue
            cx.execute("INSERT INTO tasks(task_id, kind, model, prompt_version, payload_json, status, attempts, created_at, "
                       "queued, access) VALUES (?,?,?,?,?,'done',0,?,0,'none')",
                       (tid, "check", PERSON, None, json.dumps(pl, ensure_ascii=False), now()))
            _person_rows(cx, tid, cid, ps)
        else:
            tasks._insert_task(cx, tid, "check", model, pl)
        out[key] = tid
    return out


def _to_person(ws: Workspace, task_id: str) -> None:
    """A local part whose local model is not there: its excerpts wait for a person's judgement instead."""
    with ws.connect() as cx:
        t = cx.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if t is None or t["status"] == "done":
            return
        payload = json.loads(t["payload_json"])
        cid = payload["subject_id"]
        cx.execute("DELETE FROM results WHERE task_id=?", (task_id,))
        cx.execute("UPDATE tasks SET status='done', model=?, attempts=0, queued=0, claimed_by=NULL WHERE task_id=?",
                   (PERSON, task_id))
        _person_rows(cx, task_id, cid, payload["passages"])


def _part_counts(ws: Workspace, parts: dict[str, str]) -> dict[str, int]:
    out = {}
    for key, tid in parts.items():
        pl = ws.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (tid,))
        out[key] = len(json.loads(pl)["passages"]) if pl else 0
    return out


def _grade_text(n: dict[str, int], main_is_claude: bool) -> str:
    who = "Claude" if main_is_claude else "The AI"
    bits = []
    if n.get("main"):
        bits.append(f"{who} is reading the {n['main']} excerpts" if not (n.get("local") or n.get("person"))
                    else f"{who} is reading {n['main']} {'excerpt' if n['main'] == 1 else 'excerpts'}")
    if n.get("local"):
        bits.append(f"the local model reads {n['local']} from documents marked Only a local AI")
    if n.get("person"):
        bits.append(f"{n['person']} {'waits' if n['person'] == 1 else 'wait'} for your judgement")
    text = "; ".join(bits)
    return text[:1].upper() + text[1:] if text else ""


def _run_round(ws: Workspace, parts: dict[str, str], backend, model: str, readers, say=lambda *a, **k: None) -> bool:
    """Answer the parts of a round: the main one with the main model, the local one with the local model (or, when
    it cannot be reached, it waits for a person). Returns whether the main part's answer was accepted (True when
    there is none). Backend errors of the main model propagate."""
    from .llm import BackendError, MemoryShort

    ok = True
    if "main" in parts:
        ok, _errs = tasks.run_one(ws, parts["main"], backend, model)
    if "local" in parts:
        got = readers.local() if readers is not None else None
        if got is not None and readers.memory_short:
            pass  # 0.13.11: no room for the local model earlier in this check: these excerpts wait as well
        elif got is None:
            _to_person(ws, parts["local"])
            if readers is not None and readers.local_problem:
                say("note", f"The local model could not be used ({readers.local_problem}); those excerpts wait for "
                            "your judgement", {})
        else:
            n = _part_counts(ws, {"local": parts["local"]})["local"]
            try:
                lok, _errs = tasks.run_one(ws, parts["local"], got[0], got[1])
                readers.read += 1
                if not lok:  # 0.11.1: said on the progress and the result, instead of passing in silence
                    say("note", "The local model's answers for the excerpts of documents marked Only a local AI could "
                                "not be used; they are shown without a judgement", {})
            except MemoryShort as e:
                # 0.13.11: not loaded on a computer without room for it; the excerpts wait ("Read them now")
                readers.memory_short = e
                say("note", f"{e} {_waiting_words(n)}", {"keep": True})
            except BackendError as e:
                if readers.stopped():
                    raise
                _to_person(ws, parts["local"])
                say("note", f"The local model could not be reached ({e}); those excerpts wait for your judgement", {})
    return ok


def _waiting_words(n: int) -> str:
    return (f"The {n} {'excerpt' if n == 1 else 'excerpts'} from documents marked Only a local AI "
            f"{'waits' if n == 1 else 'wait'}: the result has Read them now, or judge {'it' if n == 1 else 'them'} "
            "yourself.")


def local_waiting(ws: Workspace, hyp_ids: list[str] | None = None, retry_failed: bool = False) -> list[dict]:
    """The local parts of rounds that wait for the local model ({"task_id", "status", "passages"}): made by a check
    by queue or in a Claude chat, or left waiting when the computer had no room for the model (0.13.11). With
    `retry_failed`, also those whose answers could not be used."""
    # the open check tasks (the index on kind and status finds them), each with its hypothesis in the same query and
    # its excerpts counted by SQLite, not one parse and one query per part
    sts = "'pending', 'retry'" + (", 'failed'" if retry_failed else "")
    rows = ws.query("SELECT t.task_id, t.status, json_array_length(t.payload_json, '$.passages') AS n, u.hyp_id "
                    "FROM tasks t LEFT JOIN user_claims u ON u.claim_id=json_extract(t.payload_json, '$.subject_id') "
                    f"WHERE t.kind='check' AND t.status IN ({sts}) AND substr(t.task_id, -6) = ':local'")
    out = [{"task_id": r["task_id"], "status": r["status"], "passages": int(r["n"] or 0)} for r in rows
           if hyp_ids is None or r["hyp_id"] in hyp_ids]
    return out + _mix_waiting(ws, hyp_ids)


def _mix_waiting(ws: Workspace, hyp_ids: list[str] | None = None) -> list[dict]:
    """0.18.1 (I1): the tasks of these checks the AI mix gives the local model first (search words, splitting, or
    judging excerpts under Mostly local) and that wait for it, as `local_waiting` rows ("mix": True)."""
    from .home import load_settings

    kinds = sorted(routing.mix_kinds(load_settings()) & {"decompose", "expand", "check"})
    if not kinds:
        return []
    rows = ws.query(f"SELECT t.task_id, t.status, t.kind, json_array_length(t.payload_json, '$.passages') AS n, "
                    "COALESCE(u.hyp_id, h.hyp_id) AS hyp_id FROM tasks t "
                    "LEFT JOIN user_claims u ON u.claim_id=json_extract(t.payload_json, '$.subject_id') "
                    "LEFT JOIN hypotheses h ON t.task_id='decompose:' || h.hyp_id "
                    f"WHERE t.kind IN ({','.join('?' * len(kinds))}) AND t.status IN ('pending', 'retry') "
                    "AND COALESCE(t.step, 0)=0 AND t.forced_model IS NULL AND COALESCE(t.access, 'cloud')='cloud' "
                    "AND (t.claimed_by IS NULL OR t.claimed_by='') AND substr(t.task_id, -6) NOT IN (':local', 'person')",
                    kinds)
    if hyp_ids is not None:
        wanted = set(hyp_ids)
        rows = [r for r in rows if r["hyp_id"] in wanted]
    return [{"task_id": r["task_id"], "status": r["status"], "passages": max(1, int(r["n"] or 0)), "mix": True}
            for r in rows]


def run_local_parts(ws: Workspace, hyp_ids: list[str] | None = None, readers=None, retry_failed: bool = False,
                    on_start: Callable[[str, int], None] | None = None) -> int:
    """Answer the local parts of rounds that wait (made by a check by queue or in a Claude chat), with the local model
    for restricted documents; without one they wait for a person. With `retry_failed` ("Read them now" on the
    result, 0.11.1) a local part whose answers could not be used is tried again. Returns the number of parts handled.

    0.13.11: the model is not loaded when this computer has clearly too little memory free for it: the parts keep
    waiting, and `readers.memory_short` says why. `on_start(model, excerpts)` is called before the model starts."""
    from .llm import BackendError, MemoryShort

    if readers is None:
        readers = access.Readers(None, "")
    rows = local_waiting(ws, hyp_ids, retry_failed)
    if not rows:
        return 0
    got = readers.local()
    if got is not None:
        try:
            if hasattr(got[0], "check_memory"):
                got[0].check_memory(got[1])
        except MemoryShort as e:
            readers.memory_short = e
            return 0
        except BackendError:
            pass  # said by the task itself, below
        if on_start is not None:
            on_start(got[1], sum(r["passages"] for r in rows))
    n = 0
    for r in rows:
        if r.get("mix"):  # 0.18.1 (I1, I2): the local model first; Claude when it is unsure, or when there is none
            if got is None:
                with ws.connect() as cx:
                    cx.execute("UPDATE tasks SET step=1 WHERE task_id=? AND COALESCE(step, 0)=0", (r["task_id"],))
                    tasks.mark_queued(cx, [r["task_id"]])
                readers.to_claude += 1
            else:
                try:
                    how = tasks.answer_locally_first(ws, r["task_id"], got[0], got[1])
                    if how == "retry":  # no answer of the local model passed: Claude Code answers it
                        readers.to_claude += 1
                    else:  # it stands, or counts until Claude has read it again
                        readers.mix_read += 1
                except MemoryShort as e:
                    readers.memory_short = e
                    return n
            n += 1
            continue
        with ws.connect() as cx:
            if r["status"] == "failed":
                cx.execute("UPDATE tasks SET status='pending', attempts=0 WHERE task_id=?", (r["task_id"],))
            # the setting of its documents now: one marked No AI since it was made goes to the person, not the model
            access.relabel(cx, [r["task_id"]])
            lv = cx.execute("SELECT access FROM tasks WHERE task_id=?", (r["task_id"],)).fetchone()
        if got is None or (lv and lv[0] == "none"):
            _to_person(ws, r["task_id"])
        else:
            try:
                tasks.run_one(ws, r["task_id"], got[0], got[1])
                readers.read += 1
            except MemoryShort as e:
                readers.memory_short = e
                return n
            except access.AccessError:  # the guard stopped this part: no model may read it; the others go on
                _to_person(ws, r["task_id"])
            except BackendError as e:
                if readers.stopped():
                    raise  # 0.13.11: stopped, the part keeps waiting for the local model
                readers.local_problem = str(e)  # said on the progress
                _to_person(ws, r["task_id"])
        n += 1
    return n


def only_local_waits(ws: Workspace, hyp_id: str) -> bool:
    """0.13.11: whether all a check still waits for is the local model (the excerpts of documents marked Only a local
    AI): Claude (Code) has done its part. A check by queue counts once its parts are past choosing excerpts."""
    claims = ws.query("SELECT claim_id, stage FROM user_claims WHERE hyp_id=?", (hyp_id,))
    return _only_local(claims, lambda cid: _check_tasks(ws, cid))


def _readers(backend, model: str, readers=None):
    return readers if readers is not None else access.Readers(backend, model)


def _used(backend, model: str) -> str:
    return "baseline" if getattr(backend, "name", "") == "baseline" else model


def _stopper(should_stop: Callable[[], bool] | None) -> Callable[[], None]:
    def check() -> None:
        if should_stop and should_stop():
            from .llm import BackendError

            raise BackendError("Stopped.")
    return check


MAX_PARTS = 6


clean_terms = schema.clean_terms


def _given_parts(parts, text: str) -> list[dict]:
    """Parts a person reviewed before the check ("Look before checking"): each a sentence of its own."""
    out = []
    for i, p in enumerate(parts or []):
        t = p.get("text") if isinstance(p, dict) else p
        t = " ".join(str(t or "").split())
        if not t:
            continue
        try:
            t = _clean(t)
        except ValueError:
            raise ValueError(f"Part {i + 1} is too short: write each part as a sentence (at least 10 characters).") from None
        role = p.get("role") if isinstance(p, dict) else None
        from .schema import PART_ROLES

        out.append({"text": t, "role": role if role in PART_ROLES else None})
    if not out:
        raise ValueError("Give at least one part to check.")
    if len(out) > MAX_PARTS:
        raise ValueError(f"At most {MAX_PARTS} parts.")
    if len(out) == 1:
        return [{"text": out[0]["text"], "role": None, "part": 0}]
    return [{**p, "part": i} for i, p in enumerate(out, 1)]


def check_hypothesis(ws: Workspace, text: str, backend, model: str, framework: str | None = None,
                     code: str | None = None, k: int = 8, per_doc: int = 2, expand: bool = True,
                     decompose: bool = False, doc_ids: list[str] | None = None, progress: Progress | None = None,
                     embedder=None, batch_id: str | None = None, should_stop: Callable[[], bool] | None = None,
                     parts: list | None = None, terms: list | None = None, edited: dict | None = None,
                     second_pass: bool = False, origin: str | None = None, origin_id: str | None = None,
                     readers=None) -> str:
    """Run a full check and return the hypothesis id; read the outcome with `hypothesis_result`.

    `parts` (sentences, or {"text", "role"}) are the parts to check, as a person saw and edited them with
    `prepare_check`: the model does not split the hypothesis then. `terms` (one list of search words per part; a
    flat list for a hypothesis checked as one claim) replace the model's extra search words; an empty list
    searches with the hypothesis's own words only. `edited` ({"parts": bool, "terms": bool}) records whether the
    person changed what the AI proposed. `second_pass` sorts the best candidates again (see search.rerank).

    Backend errors propagate, and a check stopped by one (or by `should_stop`, checked before every model call)
    leaves nothing behind.
    """
    say = _adapt(progress)
    stop = _stopper(should_stop)
    if not ws.scalar("SELECT COUNT(*) FROM passages WHERE section='body'"):
        raise ValueError("This project has no readable documents yet. Add sources first.")
    text = _clean(text)
    fw, code, _desc, _label = frameworks.resolve(ws, framework, code)
    given = _given_parts(parts, text) if parts is not None else None
    if terms is not None and terms and not isinstance(terms[0], (list, tuple)):
        terms = [terms]  # one flat list: the words of a hypothesis checked as one claim
    given_terms = [clean_terms(t) if t is not None else None for t in terms] if terms is not None else None
    used = _used(backend, model)
    options = {"k": k, "per_doc": per_doc, "expand": expand, "decompose": decompose, "doc_ids": doc_ids or [],
               "backend": getattr(backend, "name", ""), "model": used,
               "search": "keywords+meaning" if embedder is not None else "keywords",
               "embed_model": getattr(embedder, "model", None), "second_pass": bool(second_pass)}
    if given is not None or given_terms is not None:  # "Look before checking": what the person saw and chose
        options["prepared"] = {"parts": given is not None, "terms": given_terms is not None,
                               "edited_parts": bool((edited or {}).get("parts")),
                               "edited_terms": bool((edited or {}).get("terms"))}
        if given is not None:
            options["decompose"] = len(given) > 1
    hid = _new_id("h")
    create_hypothesis(ws, text, fw, code, options, batch_id, hyp_id=hid, origin=origin, origin_id=origin_id)
    own = readers is None  # 0.13.11: a batch shares one, so the local model is loaded once for all its checks
    readers = access.Readers(backend, model) if own else readers
    try:
        plan = [{"text": text, "role": None, "part": 0}]
        if given is not None:
            plan = given
            if len(plan) > 1:
                with ws.connect() as cx:
                    cx.execute("UPDATE hypotheses SET parts_json=?, decomposed=1 WHERE hyp_id=?",
                               (json.dumps([{"text": p["text"], "role": p["role"]} for p in plan], ensure_ascii=False), hid))
            say("decompose_done", f"Checked in the {len(plan)} parts you chose" if len(plan) > 1
                else "Checked as written, as you chose", {"parts": [p["text"] for p in plan]})
        elif decompose:
            stop()
            say("decompose", "Splitting your hypothesis into parts that can be checked one by one", {})
            got = _decompose(ws, hid, text, backend, model, used)
            if len(got) > 1:
                plan = [{"text": p["text"], "role": p.get("role"), "part": i} for i, p in enumerate(got, 1)]
                say("decompose_done", f"Split into {len(plan)} parts", {"parts": [p["text"] for p in plan]})
            else:
                say("decompose_done", "It is already one simple statement, so it is checked as written" if got is not None
                    else "It could not be split, so it is checked as written", {"parts": [text]})
        for i, p in enumerate(plan):
            cid = new_claim(ws, p["text"], code, options, hyp_id=hid, part=p["part"], role=p["role"], framework=fw,
                            claim_id=hid if p["part"] == 0 else None)
            info = {"part": p["part"], "parts": len(plan), "claim": p["text"]} if len(plan) > 1 else {}
            mine = given_terms[i] if given_terms is not None and i < len(given_terms) else None
            _run_check(ws, cid, backend, model, used, k, per_doc, expand, doc_ids,
                       lambda s, m, extra=None, _i=info: say(s, m, {**_i, **(extra or {})}), embedder,
                       context=text if p["part"] else None, stop=stop, given_terms=mine, second_pass=second_pass,
                       readers=readers)
        stop()
        with ws.connect() as cx:
            cx.execute("UPDATE hypotheses SET model=? WHERE hyp_id=?", (used, hid))
    except BaseException:
        delete_hypothesis(ws, hid, unmade=True)  # a check stopped by a connection or key problem should not linger in the history
        raise
    finally:
        if own:
            _let_go(readers)
    return hid


def _let_go(readers) -> None:
    """0.13.11: free the memory of the local model for restricted documents once it has read (see Readers)."""
    try:
        readers.free_memory()
    except Exception:  # noqa: BLE001 - freeing memory early is a kindness, never a reason to fail
        pass


def _decompose(ws: Workspace, hid: str, text: str, backend, model: str, used: str) -> list[dict] | None:
    """The parts the model splits a hypothesis into ([] when it gives one part); None when its answers failed."""
    tid = f"decompose:{hid}"
    _add_task(ws, tid, "decompose", used, {"hyp_id": hid, "hypothesis": text})
    ok, _errs = tasks.run_one(ws, tid, backend, model)
    if not ok:
        return None
    got = json.loads(ws.scalar("SELECT parts_json FROM hypotheses WHERE hyp_id=?", (hid,)) or "[]")
    return got if len(got) > 1 else []


def _expand(ws: Workspace, cid: str, claim: str, backend, model: str, used: str, context: str | None) -> list[str]:
    payload = {"claim_id": cid, "claim": claim}
    if context:
        payload["context"] = context
    _add_task(ws, f"expand:{cid}", "expand", used, payload)
    ok, _errs = tasks.run_one(ws, f"expand:{cid}", backend, model)
    return json.loads(ws.scalar("SELECT terms_json FROM user_claims WHERE claim_id=?", (cid,)) or "[]") if ok else []


def prepare_check(ws: Workspace, text: str, backend, model: str, decompose: bool = False, expand: bool = True,
                  framework: str | None = None, code: str | None = None, progress: Progress | None = None,
                  should_stop: Callable[[], bool] | None = None) -> dict:
    """What a check would do before it reads anything ("Look before checking"): the parts the model splits the
    hypothesis into and the extra search words it proposes for each, for a person to edit and pass to
    `check_hypothesis` as `parts` and `terms`. Nothing is kept in the project.

    Returns {"parts": [{"text", "role"}], "terms": [[...] per part], "split": bool}.
    """
    say = _adapt(progress)
    stop = _stopper(should_stop)
    text = _clean(text)
    frameworks.resolve(ws, framework, code)
    used = _used(backend, model)
    for (old,) in ws.query("SELECT hyp_id FROM hypotheses WHERE hyp_id LIKE 'prep%'"):
        delete_hypothesis(ws, old, unmade=True)  # left by an earlier one that was interrupted
    hid = _new_id("prep")
    new_hypothesis(ws, text, None, None, {"prepare": True}, None, hyp_id=hid)
    try:
        parts = [{"text": text, "role": None}]
        split = False
        if decompose:
            stop()
            say("decompose", "Splitting your hypothesis into parts that can be checked one by one", {})
            got = _decompose(ws, hid, text, backend, model, used)
            if got:
                parts, split = [{"text": p["text"], "role": p.get("role")} for p in got], True
            say("decompose_done", f"Split into {len(parts)} parts" if split else "It is one simple statement",
                {"parts": [p["text"] for p in parts]})
        terms: list[list[str]] = []
        for i, p in enumerate(parts, 1):
            if not expand:
                terms.append([])
                continue
            stop()
            info = {"part": i, "parts": len(parts), "claim": p["text"]} if split else {}
            say("terms", "Thinking of other words your documents might use", info)
            cid = new_claim(ws, p["text"], None, {"prepare": True}, hyp_id=hid, part=i if split else 0)
            got = _expand(ws, cid, p["text"], backend, model, used, text if split else None)
            new = [t for t in got if t.lower() not in p["text"].lower()]
            terms.append(new)
            say("terms_done", f"Proposed: {', '.join(new[:8])}{'…' if len(new) > 8 else ''}" if new
                else "No other words proposed", {**info, "terms": got, "new_terms": new})
        return {"parts": parts, "terms": terms, "split": split}
    finally:
        delete_hypothesis(ws, hid, unmade=True)


# ---------------------------------------------------------------------------------------------
# 0.8: a check by queue. The search and the choice of excerpts run here at once; only the model's steps wait in the
# queue (the split into parts, the search words, the judging), for Claude Code. Each step is taken whenever the
# answer before it arrives (`advance_queued`), in whichever program stores it: the app, or the connector Claude
# Code talks to. Nothing is lost when the app is closed meanwhile.
# ---------------------------------------------------------------------------------------------
def queue_check(ws: Workspace, text: str, router, framework: str | None = None, code: str | None = None, k: int = 8,
                per_doc: int = 2, expand: bool = True, decompose: bool = False, doc_ids: list[str] | None = None,
                embed_model: str | None = None, batch_id: str | None = None, parts: list | None = None,
                terms: list | None = None, edited: dict | None = None, second_pass: bool = False,
                origin: str | None = None, origin_id: str | None = None) -> str:
    """Prepare a check whose model steps Claude Code answers through the queue; returns the hypothesis id. Its
    status is "waiting" until the excerpts are judged; read it with `hypothesis_result` as any other check."""
    if not ws.scalar("SELECT COUNT(*) FROM passages WHERE section='body'"):
        raise ValueError("This project has no readable documents yet. Add sources first.")
    text = _clean(text)
    fw, code, _desc, _label = frameworks.resolve(ws, framework, code)
    given = _given_parts(parts, text) if parts is not None else None
    if terms is not None and terms and not isinstance(terms[0], (list, tuple)):
        terms = [terms]
    given_terms = [clean_terms(t) if t is not None else None for t in terms] if terms is not None else None
    model = (router.model("check") if router is not None else None) or "opus"
    options = {"k": k, "per_doc": per_doc, "expand": expand, "decompose": decompose, "doc_ids": doc_ids or [],
               "backend": "claude_code", "model": model, "queue": True,
               "search": "keywords+meaning" if embed_model else "keywords", "embed_model": embed_model,
               "second_pass": bool(second_pass)}
    if given is not None or given_terms is not None:
        options["prepared"] = {"parts": given is not None, "terms": given_terms is not None,
                               "edited_parts": bool((edited or {}).get("parts")),
                               "edited_terms": bool((edited or {}).get("terms"))}
        if given is not None:
            options["decompose"] = len(given) > 1
    if given_terms is not None:
        options["queue_terms"] = given_terms
    hid = _new_id("h")
    create_hypothesis(ws, text, fw, code, options, batch_id, hyp_id=hid, origin=origin, origin_id=origin_id)
    with ws.connect() as cx:
        cx.execute("UPDATE hypotheses SET queue='waiting', model=? WHERE hyp_id=?", (model, hid))
        if given is not None:  # also one part, which a person may have reworded (0.11.1: that edit was lost)
            cx.execute("UPDATE hypotheses SET parts_json=?, decomposed=? WHERE hyp_id=?",
                       (json.dumps([{"text": p["text"], "role": p["role"]} for p in given], ensure_ascii=False),
                        int(len(given) > 1), hid))
    if given is None and decompose:
        with tasks.queueing():
            _add_task(ws, f"decompose:{hid}", "decompose", (router.model("decompose") if router else None) or "sonnet",
                      {"hyp_id": hid, "hypothesis": text})
    advance_queued(ws, [hid])
    return hid


def _queue_embedder(ws: Workspace, model: str | None):
    if not model:
        return None
    try:
        from . import embed
        from .home import load_settings, make_embedder

        emb = make_embedder(load_settings())
        if emb is None or emb.model != model or not embed.status(ws, model)["embedded"]:
            return None
        return emb
    except Exception:  # noqa: BLE001 - search by words alone when the embedding server is not there
        return None


def advance_queued(ws: Workspace, hyp_ids: list[str] | None = None) -> list[str]:
    """Take every next step of the checks by queue that their answers allow. Returns the ids still waiting.

    Steps per part: `terms` (search words waiting), `rank` (search and choose the excerpts, here and now), `judge`
    (the judging waits), `done`. A step is taken by one program only: the change of stage and the task it creates
    are written together, and a program that finds the stage already changed leaves it."""
    sql = "SELECT * FROM hypotheses WHERE queue='waiting'"
    args: list = []
    if hyp_ids:
        sql += f" AND hyp_id IN ({','.join('?' * len(hyp_ids))})"
        args = list(hyp_ids)
    waiting = []
    rows = ws.query(sql, args)
    r = _queue_router() if rows else None  # once per call (0.11.1: the settings were read per hypothesis per poll)
    with tasks.queueing():
        for h in rows:
            try:
                if _advance_one(ws, dict(h), r):
                    waiting.append(h["hyp_id"])
            except (KeyError, ValueError):
                continue  # the hypothesis was deleted meanwhile
    return waiting


def _queue_router():
    """The router of the Claude Code route from the settings (None when they cannot be read)."""
    from .routing import from_settings

    try:
        from .home import load_settings

        return from_settings(load_settings(), route="claude_code")
    except Exception:  # noqa: BLE001
        return None


def _advance_one(ws: Workspace, h: dict, r=None) -> bool:
    hid, text = h["hyp_id"], h["text"]
    opts = json.loads(h["options_json"] or "{}")
    claims = ws.query("SELECT * FROM user_claims WHERE hyp_id=? ORDER BY part, rowid", (hid,))
    if not claims:
        plan = [{"text": text, "role": None, "part": 0}]
        if opts.get("prepared", {}).get("parts") and h.get("parts_json"):
            got = json.loads(h["parts_json"])
            plan = ([{"text": got[0]["text"], "role": None, "part": 0}] if len(got) == 1 else
                    [{"text": p["text"], "role": p.get("role"), "part": i} for i, p in enumerate(got, 1)])
        elif opts.get("decompose") and not opts.get("prepared", {}).get("parts"):
            t = ws.query("SELECT status FROM tasks WHERE task_id=?", (f"decompose:{hid}",))
            if t and t[0]["status"] in ("pending", "retry"):
                return True
            got = json.loads(ws.scalar("SELECT parts_json FROM hypotheses WHERE hyp_id=?", (hid,)) or "[]")
            if t and t[0]["status"] == "done" and len(got) > 1:
                plan = [{"text": p["text"], "role": p.get("role"), "part": i} for i, p in enumerate(got, 1)]
        given_terms = opts.get("queue_terms")
        with ws.connect() as cx:
            if cx.execute("SELECT 1 FROM user_claims WHERE hyp_id=?", (hid,)).fetchone():
                return True  # another program made the parts just now
            for i, p in enumerate(plan):
                cid = new_claim(ws, p["text"], h["code"], opts, hyp_id=hid, part=p["part"], role=p["role"],
                                framework=h["framework"], claim_id=hid if p["part"] == 0 else None)
                mine = given_terms[i] if given_terms is not None and i < len(given_terms) else None
                if mine is not None:
                    cx.execute("UPDATE user_claims SET terms_json=?, stage='rank' WHERE claim_id=?",
                               (json.dumps(mine, ensure_ascii=False), cid))
                else:
                    cx.execute("UPDATE user_claims SET stage=? WHERE claim_id=?",
                               ("terms" if opts.get("expand", True) else "rank", cid))
        claims = ws.query("SELECT * FROM user_claims WHERE hyp_id=? ORDER BY part, rowid", (hid,))
    open_ = False
    for c in claims:
        cid, stage = c["claim_id"], c["stage"]
        if stage == "terms":
            tid = f"expand:{cid}"
            st = ws.scalar("SELECT status FROM tasks WHERE task_id=?", (tid,))
            if st is None:
                payload = {"claim_id": cid, "claim": c["text"]}
                if c["part"]:
                    payload["context"] = text
                _add_task(ws, tid, "expand", (r.model("expand") if r else None) or "sonnet", payload)
                open_ = True
                continue
            if st in ("pending", "retry"):
                open_ = True
                continue
            with ws.connect() as cx:
                if st == "failed":
                    cx.execute("UPDATE user_claims SET terms_json=COALESCE(terms_json, '[]') WHERE claim_id=?", (cid,))
                cx.execute("UPDATE user_claims SET stage='rank' WHERE claim_id=? AND stage='terms'", (cid,))
            stage = "rank"
        if stage == "rank":
            terms = json.loads(ws.scalar("SELECT terms_json FROM user_claims WHERE claim_id=?", (cid,)) or "[]")
            picked = rank_passages(ws, c["text"], terms, k=int(opts.get("k", 8)), per_doc=int(opts.get("per_doc", 2)),
                                   doc_ids=opts.get("doc_ids") or None,
                                   embedder=_queue_embedder(ws, opts.get("embed_model")),
                                   second_pass=bool(opts.get("second_pass")))
            with ws.connect() as cx:
                moved = cx.execute("UPDATE user_claims SET stage=? WHERE claim_id=? AND stage='rank'",
                                   ("judge" if picked else "done", cid)).rowcount
                if moved and picked:
                    payload = _payload(ws, cid, c["text"], c["target"], c["framework"], picked, terms)
                    _add_round(ws, cid, f"check:{cid}", payload, (r.model("check") if r else None) or "opus",
                               ("cloud",), _local_configured(), cx)
            if picked:
                open_ = True
            continue
        if stage == "judge":
            sts = [t["status"] for t in _check_tasks(ws, cid)]
            if any(st in ("pending", "retry") for st in sts):  # the local part too (the app reads it, see _follow)
                open_ = True
                continue
            with ws.connect() as cx:
                cx.execute("UPDATE user_claims SET stage='done', model=COALESCE(model, ?) WHERE claim_id=? AND "
                           "stage='judge'", (opts.get("model"), cid))
    if not open_:
        with ws.connect() as cx:
            cx.execute("UPDATE hypotheses SET queue='done' WHERE hyp_id=? AND queue='waiting'", (hid,))
    return open_


def _local_configured() -> bool:
    """Whether a local model is chosen for restricted documents (a check by queue or in a chat: Claude reads the rest)."""
    try:
        from .home import load_settings, restricted_choice

        return bool(restricted_choice(load_settings()))
    except Exception:  # noqa: BLE001 - without settings, a person judges them
        return False


def queue_stage(ws: Workspace, hyp_id: str) -> dict:
    """Where a check by queue stands, for its progress line: the step that waits and for how many parts."""
    h = ws.query("SELECT queue, options_json FROM hypotheses WHERE hyp_id=?", (hyp_id,))
    if not h:
        return {"state": "gone"}
    claims = ws.query("SELECT part, stage, text FROM user_claims WHERE hyp_id=? ORDER BY part", (hyp_id,))
    if h[0]["queue"] != "waiting":
        return {"state": "done", "parts": len(claims)}
    if not claims:
        return {"state": "waiting", "step": "decompose", "parts": 0}
    stages = [c["stage"] for c in claims]
    step = "terms" if "terms" in stages else "grade" if "judge" in stages else "rank"
    return {"state": "waiting", "step": step, "parts": len(claims), "stages": stages,
            "texts": [c["text"] for c in claims]}


def check_claim(ws: Workspace, text: str, backend, model: str, target: str | None = None, k: int = 8, per_doc: int = 2,
                expand: bool = True, doc_ids: list[str] | None = None, progress: Progress | None = None,
                framework: str | None = None, embedder=None) -> str:
    """Check one claim as written (no decomposition) and return its id; read the outcome with `result`."""
    return check_hypothesis(ws, text, backend, model, framework=framework or ("sdg" if target else None), code=target,
                            k=k, per_doc=per_doc, expand=expand, doc_ids=doc_ids, progress=progress, embedder=embedder)


def _run_check(ws, cid, backend, model, used, k, per_doc, expand, doc_ids, say, embedder=None, context=None,
               stop=lambda: None, given_terms: list[str] | None = None, second_pass: bool = False,
               readers=None) -> None:
    uc = ws.query("SELECT text, target, framework FROM user_claims WHERE claim_id=?", (cid,))[0]
    claim = uc["text"]
    terms: list[str] = []
    if given_terms is not None:  # the words a person chose before the check
        terms = list(given_terms)
        with ws.connect() as cx:
            cx.execute("UPDATE user_claims SET terms_json=? WHERE claim_id=?", (json.dumps(terms, ensure_ascii=False), cid))
        new = [t for t in terms if t.lower() not in claim.lower()]
        say("terms_done", f"Also searching for the words you chose: {', '.join(new[:8])}{'…' if len(new) > 8 else ''}"
            if new else "Searching with the words of the hypothesis only, as you chose", {"terms": terms, "new_terms": new})
    elif expand:
        stop()
        say("terms", "Thinking of other words your documents might use")
        terms = _expand(ws, cid, claim, backend, model, used, context)
        new = [t for t in terms if t.lower() not in claim.lower()]  # the hypothesis's own words are searched anyway
        say("terms_done", f"Also searching for: {', '.join(new[:8])}{'…' if len(new) > 8 else ''}" if new
            else "Searching with the words of the hypothesis only", {"terms": terms, "new_terms": new})
    say("rank", "Looking through your documents for relevant excerpts")
    picked = rank_passages(ws, claim, terms, k=k, per_doc=per_doc, doc_ids=doc_ids, embedder=embedder,
                           second_pass=second_pass)
    if not picked:
        say("rank_done", "No excerpt in your documents matches this hypothesis", {"passages": 0, "documents": 0})
        return
    n_docs = len({p["doc_id"] for p in picked})
    say("rank_done", f"Found {len(picked)} excerpts in {n_docs} {'document' if n_docs == 1 else 'documents'}", {"passages": len(picked), "documents": n_docs})
    stop()
    readers = _readers(backend, model, readers)
    parts = _add_round(ws, cid, f"check:{cid}", _payload(ws, cid, claim, uc["target"], uc["framework"], picked, terms),
                       used, tuple(readers.main_levels), readers.local_configured())
    n = _part_counts(ws, parts)
    say("grade", _grade_text(n, access.is_cloud(backend)), {"split": n} if len(n) > 1 else {})
    ok = _run_round(ws, parts, backend, model, readers, say)
    graded = ws.scalar("SELECT COUNT(*) FROM verifications WHERE subject_kind='user_claim' AND subject_id=? "
                       "AND verdict != 'not_enough_info'", (cid,)) or 0
    attempts = ws.scalar("SELECT attempts FROM tasks WHERE task_id=?", (f"check:{cid}",)) or 1
    waiting = ws.scalar("SELECT COUNT(*) FROM verifications WHERE subject_kind='user_claim' AND subject_id=? AND "
                        "model=? AND user_verdict IS NULL", (cid, PERSON)) or 0
    say("grade_done", (f"{graded} of {len(picked)} excerpts are about the hypothesis; every quote was checked against "
                       "the document" if ok else "The AI's answers could not be used, even after three tries")
        + (f" ({attempts} tries)" if attempts > 1 and ok else "")
        + (f"; {waiting} {'waits' if waiting == 1 else 'wait'} for your judgement" if waiting else ""),
        {"graded": graded, "ok": ok, "waiting_for_you": waiting})


def _payload(ws: Workspace, cid: str, claim: str, code: str | None, framework: str | None, picked: list[dict],
             terms: list[str] | None = None) -> dict:
    desc = label = None
    if code:
        _fw, code, desc, label = frameworks.resolve(ws, framework or "sdg", code)
    from .references import context_before

    passages = []
    for p in picked:
        item = {"passage_id": p["passage_id"], "doc_id": p["doc_id"], "title": p["title"], "page": p["page"],
                "text": p["text"], **({"found_by": p["found_by"]} if p.get("found_by") else {}),
                **({"matched": p["matched"]} if p.get("matched") else {}),
                # 0.15: an excerpt kept from an earlier reading, read again: where it is in the document now
                **({"anchor": p["anchor"]} if p.get("anchor") else {})}
        ctx, ctx_start = context_before(ws, p["passage_id"])  # check-v4: the text before, for refers_to
        if ctx:
            item.update(context=ctx, context_start=ctx_start)
        passages.append(item)
    out = {"subject_kind": "user_claim", "subject_id": cid, "claim": claim, "target": code or None,
           "target_description": desc, "passages": passages}
    if label and label != "SDG target":
        out["framework_label"] = label
    if terms is not None:
        out["terms"] = list(terms)  # the words this round searched for (shown with the round's excerpts)
    return out


def continue_check(ws: Workspace, cid: str, backend, model: str, k: int = 8, terms: list[str] | None = None,
                   embedder=None, progress: Progress | None = None, should_stop: Callable[[], bool] | None = None,
                   doc_ids: list[str] | None = None, readers=None) -> dict:
    """Read the next best passages for a claim (none shown before) and grade them, as a new round of its check.
    `doc_ids` limits the round to those documents (see `more_passages`)."""
    say = _adapt(progress)
    _stopper(should_stop)()
    used = _used(backend, model)
    say("rank", "Looking for further excerpts not read yet", {})
    readers = _readers(backend, model, readers)
    r = more_passages(ws, cid, k=k, model=used, terms=terms, embedder=embedder, doc_ids=doc_ids,
                      main_levels=tuple(readers.main_levels), local_reader=readers.local_configured())
    if not r["passages"]:
        say("rank_done", "No further excerpts match", {"passages": 0})
        return r
    say("rank_done", f"Found {len(r['passages'])} more excerpts", {"passages": len(r["passages"])})
    parts = r.pop("parts", {})
    say("grade", _grade_text(_part_counts(ws, parts), access.is_cloud(backend)), {})
    try:
        ok = _run_round(ws, parts, backend, model, readers, say)
    except BaseException:
        with ws.connect() as cx:  # a round stopped by a backend problem is removed, so it can be asked again
            for tid in parts.values():
                pl = cx.execute("SELECT payload_json FROM tasks WHERE task_id=?", (tid,)).fetchone()
                for p in (json.loads(pl[0])["passages"] if pl else []):
                    cx.execute("DELETE FROM verifications WHERE ver_id=?", (f"v{tasks._h(tid, p['passage_id'])}",))
                cx.execute("DELETE FROM results WHERE task_id=?", (tid,))
                cx.execute("DELETE FROM tasks WHERE task_id=?", (tid,))
        raise
    say("grade_done", "Read; every quote was checked against the document" if ok else "The AI's answers could not be used, even after three tries", {"ok": ok})
    return {**r, "ok": ok}


# ---------------------------------------------------------------------------------------------
# a check graded step by step by a model outside this program (Claude in a chat, through the connector)
# ---------------------------------------------------------------------------------------------
def chat_rules() -> str:
    """The grading rules of the `check` prompt, without its answer format (the connector's tool defines that)."""
    from . import prompts

    return prompts.system_prompt("check").split("\nOutput format")[0].strip()


def _check_tasks(ws: Workspace, cid: str) -> list:
    cond, args = tasks.check_task_ids_sql(cid)  # on the key: called per part on every look at the queue
    return ws.query(f"SELECT * FROM tasks WHERE +kind='check' AND {cond} ORDER BY created_at, rowid", args)


def _shown(payload: dict) -> list[dict]:
    return [{"n": i, "document": p["title"] or "untitled", "page": p["page"], "text": p["text"]}
            for i, p in enumerate(payload["passages"], 1)]


def open_check(ws: Workspace, text: str, terms: list[str] | None = None, target: str | None = None, k: int = 8,
               per_doc: int = 2, doc_ids: list[str] | None = None, model: str = CHAT_MODEL,
               framework: str | None = None) -> dict:
    """Pick the passages for a claim and return them; the grades come back through `submit_grades`."""
    if not ws.scalar("SELECT COUNT(*) FROM passages WHERE section='body'"):
        raise ValueError("This project has no readable documents yet. Add sources first.")
    terms = clean_terms(terms)
    cid = new_claim(ws, text, target, {"k": k, "per_doc": per_doc, "expand": bool(terms), "doc_ids": doc_ids or [],
                                       "backend": "chat", "model": model}, framework=framework)
    with ws.connect() as cx:
        cx.execute("UPDATE user_claims SET terms_json=?, model=? WHERE claim_id=?", (json.dumps(terms), model, cid))
        cx.execute("UPDATE hypotheses SET model=? WHERE hyp_id=?", (model, cid))
    uc = ws.query("SELECT text, target, framework FROM user_claims WHERE claim_id=?", (cid,))[0]
    picked = rank_passages(ws, uc["text"], terms, k=k, per_doc=per_doc, doc_ids=doc_ids)
    if not picked:
        return {"check_id": cid, "round": 1, "passages": []}
    payload = _payload(ws, cid, uc["text"], uc["target"], uc["framework"], picked, terms)
    parts = _add_round(ws, cid, f"check:{cid}", payload, model, ("cloud",), _local_configured())
    return {"check_id": cid, "round": 1, **_chat_round(ws, parts)}


def _chat_round(ws: Workspace, parts: dict[str, str]) -> dict:
    """The excerpts of a round a Claude chat may read (the main part), and how many others there are (0.11)."""
    main = ws.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (parts["main"],)) if "main" in parts else None
    shown = _shown(json.loads(main)) if main else []
    if main:
        with ws.connect() as cx:
            # the chat sees the excerpts alone (`_shown`): no context passage enters the ledger (0.11.1)
            access.record_sent(cx, parts["main"], json.loads(main), access.ROUTE_NAMES["chat"], "check", context=False)
    n = _part_counts(ws, {k: v for k, v in parts.items() if k != "main"})
    out: dict = {"passages": shown}
    if n:
        out["restricted_passages"] = sum(n.values())
        out["restricted_note"] = (f"{sum(n.values())} further excerpts come from documents the user keeps on this "
                                  "computer: " + ", ".join(
                                      ([f"{n['local']} are read by the local model"] if n.get("local") else []) +
                                      ([f"{n['person']} wait for the user's own judgement"] if n.get("person") else []))
                                  + ". They are not shown to you; say so when you report the result.")
    return out


def more_passages(ws: Workspace, cid: str, k: int = 8, model: str = CHAT_MODEL, terms: list[str] | None = None,
                  embedder=None, doc_ids: list[str] | None = None, main_levels=("cloud",),
                  local_reader: bool | None = None) -> dict:
    """The next best passages, none of them shown before, as a new round of the same check.

    With `terms`, the ranking uses these new search terms (with the claim) instead of the earlier ones, and only
    passages containing at least one of them qualify, so a person or a model can reformulate the search; the terms
    are added to the check's record. With `doc_ids`, only those documents are read (for example the documents
    added since the check); otherwise the documents the check was limited to, if any.
    """
    uc = ws.query("SELECT * FROM user_claims WHERE claim_id=?", (cid,))
    if not uc:
        raise KeyError(cid)
    uc = dict(uc[0])
    groups = _rounds(ws, cid)
    last_main = _main_part(groups[-1]) if groups else None
    if last_main is not None and last_main["status"] not in ("done", "failed"):
        raise ValueError("Grade the passages already shown first (submit_grades), then ask for more.")
    rounds = [t for g in groups for t in g]
    seen = {p["passage_id"] for r in rounds for p in json.loads(r["payload_json"])["passages"]}
    opts = json.loads(uc["options_json"] or "{}")
    old_terms = json.loads(uc["terms_json"] or "[]")
    new_terms = clean_terms(terms)
    if new_terms:
        with ws.connect() as cx:
            merged = old_terms + [t for t in new_terms if t not in old_terms]
            cx.execute("UPDATE user_claims SET terms_json=? WHERE claim_id=?", (json.dumps(merged), cid))
    picked = rank_passages(ws, uc["text"], new_terms or old_terms, k=k, per_doc=int(opts.get("per_doc", 2)),
                           doc_ids=(doc_ids if doc_ids is not None else opts.get("doc_ids")) or None, exclude=seen,
                           embedder=embedder, require_terms=bool(new_terms), second_pass=bool(opts.get("second_pass")))
    n = len(groups) + 1
    if not picked:
        return {"check_id": cid, "round": n, "passages": []}
    payload = _payload(ws, cid, uc["text"], uc["target"], uc.get("framework"), picked, new_terms or old_terms)
    parts = _add_round(ws, cid, f"check:{cid}:r{n}" if groups else f"check:{cid}", payload, model, tuple(main_levels),
                       _local_configured() if local_reader is None else local_reader)
    if model == CHAT_MODEL:  # a Claude chat (the connector): it is shown the excerpts it may read
        return {"check_id": cid, "round": n, **_chat_round(ws, parts)}
    return {"check_id": cid, "round": n, "passages": _shown(payload), "parts": parts}


_HELPER_HOLDS = ("This round waits in ENLENS's queue for a helper of Claude Code (/enlens-run), or a helper is "
                 "grading it now: its grades will be stored from there, so they are not taken from this chat. Read "
                 "the result later with get_check.")


def submit_grades(ws: Workspace, cid: str, grades: list[dict], summary: str | None = None,
                  model: str = CHAT_MODEL) -> dict:
    """Validate and store the grades for the open round. Problems come back so they can be fixed and resent."""
    groups = _rounds(ws, cid)
    if not groups:
        if not ws.query("SELECT 1 FROM user_claims WHERE claim_id=?", (cid,)):
            raise KeyError(cid)
        raise ValueError("This check has no passages to grade.")
    t = _main_part(groups[-1])
    if t is None:
        raise ValueError("The excerpts of this round all come from documents kept on this computer, so there is "
                         "nothing for you to grade. Ask for more_passages to read further.")
    if t["status"] == "done":
        raise ValueError("These passages are already graded. Ask for more_passages to read further.")
    if t["status"] == "failed":
        raise ValueError("This round failed three times. Start a new check.")
    try:  # whether a helper holds the round is checked where the grades are written, so none takes it in between
        ok, errors = tasks.ingest_result(ws, t["task_id"], {"evidence": grades, "rationale": summary}, model=model,
                                         free=True)
    except tasks.NotHeld as e:
        raise ValueError(_HELPER_HOLDS if e.reason == "queued" else
                         "These passages are already graded. Ask for more_passages to read further.") from None
    if not ok:
        left = tasks.MAX_ATTEMPTS - int(ws.scalar("SELECT attempts FROM tasks WHERE task_id=?", (t["task_id"],)) or 0)
        return {"accepted": False, "problems": errors, "attempts_left": max(0, left)}
    return {"accepted": True}


def read_new_documents(ws: Workspace, hyp_id: str, backend, model: str, k: int = 8, embedder=None,
                       progress: Progress | None = None, should_stop: Callable[[], bool] | None = None) -> dict:
    """Read the documents added since a check, for every part, as a further round restricted to them (the check
    is not run again, so a person's reviews are kept). Documents without a matching excerpt are only marked as
    looked at. Returns {"hyp_id", "documents", "matching", "passages", "rounds"}."""
    say = _adapt(progress)
    new = new_documents(ws, hyp_id)
    docs = [d["doc_id"] for d in new if d["matching"]]
    total, rounds = 0, []
    if docs:
        for c in ws.query("SELECT claim_id FROM user_claims WHERE hyp_id=? ORDER BY part, rowid", (hyp_id,)):
            r = continue_check(ws, c["claim_id"], backend, model, k=k, embedder=embedder, should_stop=should_stop,
                               doc_ids=docs, progress=lambda s, m, i=None: say(s, m, i or {}))
            total += len(r["passages"])
            rounds.append({"claim_id": c["claim_id"], "round": r["round"], "passages": len(r["passages"]),
                           "ok": r.get("ok")})
    with ws.connect() as cx:
        cx.execute("UPDATE hypotheses SET docs_checked_at=? WHERE hyp_id=?", (now(), hyp_id))
    return {"hyp_id": hyp_id, "documents": len(new), "matching": len(docs), "passages": total, "rounds": rounds}


def second_opinion(ws: Workspace, hyp_ids: list[str], backend, main_model: str, second_model: str,
                   progress: Progress | None = None, should_stop: Callable[[], bool] | None = None) -> dict:
    """Let a second model grade every excerpt the checks of these hypotheses already read, with the same prompt,
    to see where two models disagree. The answers are kept apart (they never change an answer).

    Only one model is in memory at a time: the main model is unloaded first (where the server allows it: Ollama),
    and the second model when it is done. Excerpts the second model already graded are not asked again.
    Returns {"hypotheses", "rounds", "graded", "skipped", "failed", "unloaded": [...]}.
    """
    say = _adapt(progress)
    stop = _stopper(should_stop)
    if not second_model:
        raise ValueError("Choose a model for second opinions in Settings first.")
    if second_model == main_model and getattr(backend, "name", "") not in ("claude_code", "anthropic"):
        # on Claude the auditor gives the second opinion; it may run on the same model as the checker (Opus)
        raise ValueError("The model for second opinions must be another model than the main one.")
    todo = []
    restricted = 0
    may = access.backend_levels(backend)
    for hid in hyp_ids:
        for c in ws.query("SELECT claim_id FROM user_claims WHERE hyp_id=? ORDER BY part, rowid", (hid,)):
            for t in _check_tasks(ws, c["claim_id"]):
                if _is_person(t):
                    continue  # no model may read these excerpts
                with ws.connect() as cx:  # the setting of its documents now (it may have changed since)
                    lv = access.label_payload(cx, json.loads(t["payload_json"]))
                if lv not in may:  # 0.11: a local excerpt has a second opinion only from a second local model
                    restricted += len(json.loads(t["payload_json"])["passages"])
                    continue
                todo.append((hid, t))
    out = {"hypotheses": len(hyp_ids), "rounds": len(todo), "graded": 0, "skipped": 0, "failed": 0, "unloaded": [],
           "restricted": restricted}
    if not todo:
        return out
    unload = getattr(backend, "unload", None)
    if unload and main_model and unload(main_model):  # free its memory before the second model loads
        out["unloaded"].append(main_model)
    # every task first (0.8): with Claude Code they all wait in the queue at once
    plan = []
    for hid, t in todo:
        tid = f"second:{t['task_id']}:{second_model}"
        st = ws.scalar("SELECT status FROM tasks WHERE task_id=?", (tid,))
        if st == "done":
            out["skipped"] += 1
            continue
        payload = json.loads(t["payload_json"])
        payload["second_model"] = second_model
        with ws.connect() as cx:
            if st is not None:  # asked again after a failure: three new attempts
                cx.execute("UPDATE tasks SET status='pending', attempts=0 WHERE task_id=?", (tid,))
                access.relabel(cx, [tid])  # with its documents' settings of now, not of its first try
                if tasks.queue_mode():
                    tasks.mark_queued(cx, [tid])
            else:
                tasks._insert_task(cx, tid, "second", second_model, payload)
        plan.append((tid, payload))
    try:
        for n, (tid, payload) in enumerate(plan, 1):
            stop()
            say("grade", f"The second opinion is reading {len(payload['passages'])} excerpts ({n} of {len(plan)})",
                {"index": n, "total": len(plan)})
            ok, _errs = tasks.run_one(ws, tid, backend, second_model)
            out["graded" if ok else "failed"] += 1
    finally:
        if unload and unload(second_model):
            out["unloaded"].append(second_model)
    say("grade_done", f"The second opinion read the excerpts of {len(hyp_ids)} "
        f"{'hypothesis' if len(hyp_ids) == 1 else 'hypotheses'}", {"ok": not out["failed"]})
    return out


def history(ws: Workspace, threshold: float | None = None, limit: int | None = None, query: str | None = None,
            status: str | None = None, batch_id: str | None = None, _checks: dict | None = None) -> list[dict]:
    """Every hypothesis checked in the project, newest first, with its status (computed in a few queries).

    `supports`, `partly`, `refutes` count the excerpts whose judgement counts at this threshold; `uncounted` the
    judged excerpts below it; `docs_*` count documents as on the result page. With `limit`, the checks and
    judgements of each hypothesis are read as it is reached, so a short list does not read every check.
    `_checks`: every claim's check tasks already read (`_light_checks`, by `evidence_map`).
    """
    thr = _threshold(ws, threshold)
    hyps = ws.query("SELECT * FROM hypotheses ORDER BY created_at DESC, rowid DESC")
    claims: dict[str, list] = {}
    for r in ws.query("SELECT claim_id, hyp_id, part, model, options_json, stage FROM user_claims ORDER BY part, rowid"):
        claims.setdefault(r["hyp_id"] or r["claim_id"], []).append(r)
    rounds: dict[str, list] = _checks if _checks is not None else {}
    ver: dict[str, list] = {}
    ai_of: dict[tuple[str, str], str | None] = {}
    first_of: dict[str, list] = {}  # 0.11.2: the excerpts as the first model judged them, where a stronger one read again
    from .people import me as _me

    me = _me()

    def load(cids: list[str] | None) -> None:
        """The check tasks and judgements of these claims (of all, with None)."""
        if _checks is None:
            rounds.update(_light_checks(ws, cids))
        sql = ("SELECT subject_id, passage_id, verdict, confidence, doc_id, user_verdict, model, ai_history_json, "
               "user_by FROM verifications WHERE subject_kind='user_claim'")
        if cids is None:
            vs = ws.query(sql)
        else:
            vs = [v for cid in cids for v in ws.query(sql + " AND subject_id=?", (cid,))]
        for v in vs:
            f = first_reading(v)
            if f is not None:
                first_of.setdefault(v["subject_id"], []).append(effective(f))
            e = effective(v)
            # 0.14.3: "changed by you" counts your own changes only (a colleague's judgement counts where you made none)
            e["_mine"] = bool(v["user_verdict"]) and (v["user_by"] or me) == me
            e["_changed"] = changed_by_person(v) and e["_mine"]
            e["_ai_judged"] = v["verdict"] in ("supports", "partially_supports", "refutes")
            ver.setdefault(v["subject_id"], []).append(e)
            ai_of[(v["subject_id"], v["passage_id"])] = v["verdict"] if v["verdict"] in GRADES else None

    if not limit:
        load(None)
    second: dict[tuple[str, str], str | None] = {}  # the latest second-model grade of each excerpt
    for r in ws.query("SELECT subject_id, passage_id, verdict FROM second_opinions ORDER BY at, rowid"):
        second[(r["subject_id"], r["passage_id"])] = r["verdict"] if r["verdict"] in GRADES else None
    added = sorted((r["added_at"] or "", r["doc_id"]) for r in ws.query("SELECT doc_id, added_at FROM documents"))
    q = (query or "").lower().strip()
    labels: dict[str, str] = {}

    def label(fw: str | None) -> str:
        if fw not in labels:
            try:
                f = frameworks.get(fw or "sdg", ws)
                labels[fw] = f.label if f else ""
            except ValueError:
                labels[fw] = ""
        return labels[fw]

    out = []
    for h in hyps:
        if h["hyp_id"].startswith("prep"):  # a "Look before checking" in progress, not a check
            continue
        if q and q not in (h["text"] or "").lower():
            continue
        if batch_id and h["batch_id"] != batch_id:
            continue
        parts = claims.get(h["hyp_id"], [])
        if limit:
            load([c["claim_id"] for c in parts])
        st, st_any, st_first, counts, read = [], [], [], {"supports": 0, "partially_supports": 0, "refutes": 0}, 0
        all_vs = []
        uncounted = corrected = reviewed = to_review = disagree = 0
        shown_docs: set[str] = set()
        limited = False
        for_you: list[bool] = []  # 0.14.3: per part, whether all it waits for is your own judgement
        for c in parts:
            rs = rounds.get(c["claim_id"], [])
            groups = _group_rounds(rs)  # by round, as the result page does (0.11.1: the two disagreed on "waiting")
            sts = [_round_status(g) for g in groups]
            counts_, _failed = _counting(groups, sts)  # 0.14.3: not the AI's judgements of a round that failed
            vs = [v for v in ver.get(c["claim_id"], []) if counts_(v)]
            all_vs += vs
            wt = bool(groups) and _round_waiting(groups[-1])
            st.append(_status_of_rounds(sts, vs, thr, c["stage"], wt))
            for_you.append(st[-1] == "not_checked" and "done" in sts and any(_waits_for_person(v) for v in vs))
            st_any.append(_status_of_rounds(sts, vs, 0.0, c["stage"], wt))
            if c["claim_id"] in first_of:  # the stepped-up excerpts as first judged, the others as they are
                firsts = {(x["passage_id"]) for x in first_of[c["claim_id"]]}
                vf = [x for x in first_of[c["claim_id"]] if counts_(x)] + [x for x in vs if x["passage_id"] not in firsts]
                st_first.append(_status_of_rounds(sts, vf, thr, c["stage"], wt))
            else:
                st_first.append(st[-1])
            for r in rs:
                shown = _excerpts(r)
                read += len(shown)
                for pid, did, *_title in shown:
                    shown_docs.add(did)
                    key = (c["claim_id"], pid)
                    if key in second and second[key] != ai_of.get(key):
                        disagree += 1
            limited = limited or bool(json.loads(c["options_json"] or "{}").get("doc_ids"))
            for v in ver.get(c["claim_id"], []):
                corrected += v["_changed"]
                reviewed += v["_mine"]  # 0.14.3: your own judgements, as on the result and in Excel
                if v["verdict"] in counts and counts_(v):
                    if (v["confidence"] or 0) >= thr:
                        counts[v["verdict"]] += 1
                    else:
                        uncounted += 1
        if not parts and h["queue"] != "waiting":
            continue
        if not parts:  # a check by queue waiting for its parts (0.8)
            st, st_any = ["waiting"], ["waiting"]
        to_review = max(0, read - reviewed)
        s = st[0] if len(st) == 1 else aggregate(st)
        s_first = (st_first[0] if len(st_first) == 1 else aggregate(st_first)) if st_first else s
        if status and s != status:
            continue
        first = parts[0] if parts else {"claim_id": h["hyp_id"], "model": None, "options_json": h["options_json"]}
        model = h["model"] or first["model"] or json.loads(first["options_json"] or "{}").get("model", "")
        bal = balance(all_vs, thr)
        cutoff = max(h["created_at"] or "", h["docs_checked_at"] or "")
        since = 0 if limited else sum(1 for at, d in added[bisect.bisect_right(added, (cutoff, "\uffff")):]
                                      if d not in shown_docs)
        st_text = None
        if s == "waiting" and _only_local([c for c in parts if c["hyp_id"] == h["hyp_id"]],
                                          lambda cid: rounds.get(cid, [])):  # only_local_waits, from what is read
            st_text = WAITING_LOCAL
        elif s == "not_checked" and any(for_you) and all(y for y, x in zip(for_you, st) if x == "not_checked"):
            st_text = WAITING_YOU
        out.append({"hyp_id": h["hyp_id"], "claim_id": first["claim_id"], "created_at": h["created_at"],
                    "claim": h["text"], "text": h["text"], "framework": h["framework"] or "", "target": h["code"] or "",
                    "code": h["code"] or "", "code_label": label(h["framework"]) if h["code"] else "", "status": s,
                    "status_text": st_text,
                    "status_any": st_any[0] if len(st_any) == 1 else aggregate(st_any),
                    "supports": counts["supports"], "partly": counts["partially_supports"], "refutes": counts["refutes"],
                    "uncounted": uncounted, "corrected": corrected, "reviewed": reviewed, "to_review": to_review,
                    "docs_supporting": bal["docs_supporting"],
                    "docs_partly": bal["docs_partly"], "docs_refuting": bal["docs_refuting"],
                    "passages_read": read, "parts": len(parts), "model": model, "batch_id": h["batch_id"] or "",
                    "origin": h["origin"] or "", "origin_id": h["origin_id"] or "",
                    "lean": bal["lean"], "note": h["note"] or "", "docs_added_since": since,
                    "disagreements": disagree,
                    "status_before_stronger": s_first if s_first != s else None})
        if limit and len(out) >= limit:
            break
    if batch_id:
        out.reverse()  # a set reads in the order it was typed
    return out


# ---------------------------------------------------------------------------------------------
# frameworks and batches
# ---------------------------------------------------------------------------------------------
def suggest_targets(text: str, n: int = 5, framework: str = "sdg", ws: Workspace | None = None) -> list[dict]:
    """Codes of a framework (by default the SDG targets) whose wording is closest to the claim: a starting point."""
    fw = frameworks.get(framework, ws)
    out = fw.suggest(text, n) if fw else []
    for x in out:
        x["goal"] = int(x["group"]) if framework == "sdg" and str(x.get("group", "")).isdigit() else x.get("group")
    return out


BATCH_COLUMNS = ("hypothesis", "claim", "text", "statement")


def parse_batch(text: str) -> list[dict]:
    """Hypotheses from CSV text (a column hypothesis, claim, text or statement; optional framework and code or
    target; comma, semicolon or tab separated, as spreadsheets save them) or from plain text, one hypothesis per
    line (blank lines and lines starting with # are skipped)."""
    text = (text or "").lstrip("\ufeff")
    lines = text.splitlines()
    first = lines[0] if lines else ""
    delim = max(",;\t", key=first.count) if first else ","
    head = [x.strip().strip('"').lower() for x in first.split(delim)] if first.count(delim) else []
    items: list[dict] = []
    if any(c in head for c in BATCH_COLUMNS):
        reader = csv.DictReader(io.StringIO(text), delimiter=delim)
        cols = {c.strip().lower(): c for c in (reader.fieldnames or []) if c}
        col = next(cols[c] for c in BATCH_COLUMNS if c in cols)
        for r in reader:
            t = " ".join((r.get(col) or "").split())
            if not t:
                continue
            code = (r.get(cols.get("code", ""), "") or r.get(cols.get("target", ""), "") or "").strip()
            fw = (r.get(cols.get("framework", ""), "") or "").strip()
            items.append({"text": t, "framework": fw or ("sdg" if code else None), "code": code or None})
    else:
        for line in lines:
            t = " ".join(line.split())
            if t and not t.startswith("#"):
                items.append({"text": t, "framework": None, "code": None})
    if len(items) > 500:
        raise ValueError("At most 500 hypotheses per batch.")
    return items


def check_batch(ws: Workspace, items: list[dict], backend, model: str, progress: Progress | None = None,
                should_stop: Callable[[], bool] | None = None, **options: Any) -> dict:
    """Check several hypotheses one after the other. A problem with one is recorded and the next is checked; a
    problem with the model service stops the batch (what was done is kept)."""
    readers = access.Readers(backend, model)  # 0.13.11: one local model for the whole batch, let go at its end
    try:
        return _check_each(ws, items, backend, model, _adapt(progress), should_stop, readers, options)
    finally:
        _let_go(readers)


def _check_each(ws, items, backend, model, say, should_stop, readers, options) -> dict:
    from .llm import BackendError

    batch_id = _new_id("b")
    done: list[str] = []
    errors: list[dict] = []
    stopped = None
    for i, it in enumerate(items, 1):
        if should_stop and should_stop():
            stopped = "Stopped."
            break
        say("item", f"Hypothesis {i} of {len(items)}", {"index": i, "total": len(items), "text": it["text"]})
        try:
            hid = check_hypothesis(ws, it["text"], backend, model, framework=it.get("framework"), code=it.get("code"),
                                   batch_id=batch_id, progress=lambda s, m, info=None, _i=i: say(s, m, {**(info or {}),
                                                                                                    "index": _i}),
                                   should_stop=should_stop, readers=readers, **options)
            done.append(hid)
        except BackendError as e:
            stopped = str(e)
            break
        except ValueError as e:
            errors.append({"index": i, "text": it["text"], "error": str(e)})
    return {"batch_id": batch_id, "checked": done, "errors": errors, "stopped": stopped, "total": len(items)}


# ---------------------------------------------------------------------------------------------
# moved to their own modules (roadmap H6); imported last, so they can reach everything above through `_cc.`
# ---------------------------------------------------------------------------------------------
from .check_results import (  # noqa: E402,F401
    _threshold, certainty_word, _locations, locate, _breaks, _round_notes, _readers_of, _opens_with_pronoun,
    _reference_locations, _in_excerpt, _place_kept, result, _result, hypothesis_result, MODEL_ROLES,
    models_used, models_text, _second_opinions, _shown_docs, new_documents,
)
from .check_exports import (  # noqa: E402,F401
    evidence_map, document_answers, MAP_SYMBOL, map_table, CALIBRATION_BINS, calibration, export_rows, hypothesis_rows,
    _assessment_text, JUDGEMENT_TEXT, _local_dt, ResultCache, export_table, not_read_text, _part_text,
    _earlier, strictness_text, summary_table, write_xlsx,
)
from .judgements import (  # noqa: E402,F401
    _KEEP, set_judgement, _set_judgement, reread_excerpt, more_available, delete_claim, delete_hypothesis,
    _note_removed, _log_removed, set_note,
)
