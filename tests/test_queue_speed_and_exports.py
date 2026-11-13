"""The task queue and the checks without whole-table reads, and spreadsheets whose text never runs, after a review
of 0.17.0.

- the tasks of one claim's check (and its readings again, its second opinions) are found by a range on the primary
  key, not by LIKE over every check task: the same tasks as before;
- "waiting in the queue" is written once, and two partial indexes answer the queue's questions (what waits, what a
  claim holds); the queue's counts per kind, the line a waiting page shows and the connector's count of the projects
  with work give the same numbers as before;
- the list of answers reads only the ids of each check's excerpts, and reads a short list's checks only; a result of
  several parts does not read its rounds and judgements twice;
- a changed setting still relabels every open task (an add-on's floor may depend on a document a task's text does
  not name), with the same results as working each task out on its own;
- taking tasks out of the queue, the first tasks of a kind, the local parts that wait, the measured seconds of a
  batch, the step-up rule and the note of a model test's scratch copy: the same results in fewer statements;
- a CSV or Excel file ENLENS writes never holds text a spreadsheet would run as a formula.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from openpyxl import Workbook, load_workbook

from enlens_claims import access, claimcheck, review, runs, store, taskqueue, tasks
from enlens_claims import home as core
from test_app import api, home  # noqa: F401  (fixtures)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    return core.create_project("Speed")


def _iso(minutes: float = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()


def _task(cx, tid, kind="label", status="pending", queued=1, access_="cloud", again=0, step=0, claimed_by=None,
          claimed_at=None, model="sonnet", forced_model=None, role=None, queued_at=None, payload=None,
          created_at="2026-01-01T00:00:00"):
    cx.execute("INSERT INTO tasks(task_id, kind, model, prompt_version, payload_json, status, attempts, created_at, "
               "queued, queued_at, claimed_by, claimed_at, access, again, step, forced_model, role) "
               "VALUES (?,?,?,?,?,?,0,?,?,?,?,?,?,?,?,?,?)",
               (tid, kind, model, "1", json.dumps(payload or {}), status, created_at, queued,
                queued_at or (_iso(-1) if queued else None), claimed_by, claimed_at, access_, again, step,
                forced_model, role))


def _plan(ws, sql, args=()) -> str:
    return " | ".join(r[3] for r in ws.query("EXPLAIN QUERY PLAN " + sql, args))


# ---------------------------------------------------------------------------------------------
# a check's tasks on the primary key
# ---------------------------------------------------------------------------------------------
CIDS = ["u0a1b2c3d4e5f", "u0a1b2c3d4e50", "u9f8e7d6c5b4a"]  # claim ids as new_claim makes them: "u" + 12 hex digits


def _checks(ws):
    with ws.connect() as cx:
        for i, cid in enumerate(CIDS):
            for j, suffix in enumerate(("", ":local", ":r2", ":r2:person", ":r3")):
                ps = [{"passage_id": f"d{i}:{j:04d}", "doc_id": f"d{i}", "title": f"Doc {i}", "page": 1, "text": "x"}]
                _task(cx, f"check:{cid}{suffix}", "check", status="done", queued=0,
                      payload={"subject_id": cid, "passages": ps}, created_at=f"2026-01-0{j + 1}T00:00:00")
            _task(cx, f"reread:{cid}:d{i}:0001:1", "reread", status="done", queued=0)
            _task(cx, f"second:check:{cid}:opus", "second", status="done", queued=0)
            _task(cx, f"expand:{cid}", "expand", status="done", queued=0)


def test_the_tasks_of_a_check_are_found_on_the_key_and_are_the_same_as_before(ws):
    _checks(ws)
    for cid in CIDS:
        old = ws.query("SELECT * FROM tasks WHERE kind='check' AND (task_id=? OR task_id LIKE ?) "
                       "ORDER BY created_at, rowid", (f"check:{cid}", f"check:{cid}:%"))
        assert [r["task_id"] for r in claimcheck._check_tasks(ws, cid)] == [r["task_id"] for r in old]
        assert len(old) == 5
        old_reread = {r[0] for r in ws.query("SELECT task_id FROM tasks WHERE kind='reread' AND task_id LIKE ?",
                                             (f"reread:{cid}:%",))}
        new_reread = {r[0] for r in ws.query("SELECT task_id FROM tasks WHERE +kind='reread' AND task_id >= ? AND "
                                             "task_id < ?", tasks.id_range(f"reread:{cid}:"))}
        assert new_reread == old_reread and len(new_reread) == 1
    cond, args = tasks.check_task_ids_sql(CIDS[0])
    plan = _plan(ws, f"SELECT * FROM tasks WHERE +kind='check' AND {cond} ORDER BY created_at, rowid", args)
    assert "sqlite_autoindex_tasks_1" in plan and "ix_tasks_kind_status" not in plan
    assert tasks.id_range("check:u1:") == ("check:u1:", "check:u1;")
    # the tasks a check's Excel sheet names (runs.hypothesis_task_ids), as the LIKE version found them
    with ws.connect() as cx:
        for cid in CIDS:
            cx.execute("INSERT INTO user_claims(claim_id, text, hyp_id, part) VALUES (?,?,?,0)", (cid, "c", "h1"))
    old_ids = ["decompose:h1"]
    for cid in CIDS:
        old_ids.append(f"expand:{cid}")
        old_ids += [r[0] for r in ws.query(
            "SELECT task_id FROM tasks WHERE kind IN ('check','reread','second') AND (task_id=? OR task_id LIKE ? OR "
            "task_id LIKE ? OR task_id LIKE ?)", (f"check:{cid}", f"check:{cid}:%", f"reread:{cid}:%",
                                                  f"second:check:{cid}%"))]
    assert sorted(runs.hypothesis_task_ids(ws, ["h1"])) == sorted(old_ids)


def test_removing_one_part_of_a_check_removes_its_own_tasks_only(ws):
    _checks(ws)
    keep = {r[0] for r in ws.query("SELECT task_id FROM tasks")}
    gone = {r[0] for pat in (f"check:{CIDS[0]}:%", f"reread:{CIDS[0]}:%", f"second:check:{CIDS[0]}:%")
            for r in ws.query("SELECT task_id FROM tasks WHERE task_id LIKE ?", (pat,))} | {f"check:{CIDS[0]}",
                                                                                           f"expand:{CIDS[0]}"}
    with ws.connect() as cx:
        cx.execute("INSERT INTO user_claims(claim_id, text, hyp_id, part) VALUES (?,?,?,0)", (CIDS[0], "c", "h1"))
        cx.execute("INSERT INTO user_claims(claim_id, text, hyp_id, part) VALUES (?,?,?,1)", (CIDS[1], "c", "h1"))
    claimcheck.delete_claim(ws, CIDS[0], _log=False)
    assert {r[0] for r in ws.query("SELECT task_id FROM tasks")} == keep - gone


# ---------------------------------------------------------------------------------------------
# what waits in the queue: one condition, two partial indexes, the same numbers
# ---------------------------------------------------------------------------------------------
def test_the_waiting_condition_is_the_index_condition_and_the_queue_uses_both_indexes(ws):
    flat = " ".join(store.INDEXES.split())
    assert f"ON tasks(kind, queued_at) WHERE {' '.join(taskqueue.WAITING.split())};" in flat
    assert "ON tasks(claimed_by) WHERE claimed_by IS NOT NULL;" in flat
    with ws.connect() as cx:
        for i in range(30):
            _task(cx, f"label:sdg:p{i}", status="pending" if i % 3 else "done")
    cut = taskqueue._cutoff()
    W = taskqueue.WAITING
    waiting = [
        (f"SELECT COUNT(*) FROM tasks WHERE {W}", ()),                                           # the sidebar
        (f"SELECT t.task_id FROM tasks t WHERE {W} AND {taskqueue._FREE} AND t.kind=? "
         "ORDER BY t.again DESC, t.queued_at, t.task_id", (cut, "label")),                       # _waiting_rows
        (f"SELECT kind, COUNT(*), MIN(queued_at) FROM tasks t WHERE {W} GROUP BY kind", ()),     # queue_info
        (f"SELECT COUNT(*) FROM tasks t WHERE {W} AND t.kind=?", ("label",)),                    # _waiting_count
    ]
    for sql, args in waiting:
        assert "ix_tasks_waiting" in _plan(ws, sql, args), sql
    held = [
        ("SELECT task_id FROM tasks WHERE claimed_by=?", ("q1",)),                                # submit, release
        (f"SELECT 1 FROM tasks t WHERE {taskqueue._HELD} AND {W} LIMIT 1", (cut,)),               # answering
        (f"SELECT t.kind FROM tasks t WHERE {taskqueue._HELD} AND {W}", (cut,)),                  # queue_info
    ]
    for sql, args in held:
        assert "ix_tasks_claimed" in _plan(ws, sql, args), sql


def _queue(ws):
    """A queue with every case: kinds, models, a forced model, a role, the stronger model, held, lapsed, answered,
    failed, out of the queue."""
    with ws.connect() as cx:
        n = 0
        for kind in ("label", "check", "theme"):
            for model in ("sonnet", "haiku"):
                for status, again, step in (("pending", 0, 0), ("retry", 0, 0), ("done", 1, 1), ("done", 0, 0),
                                            ("failed", 0, 0), ("pending", 0, 1)):
                    for claim in (None, ("q1", _iso(-1)), ("q2", _iso(-90))):
                        n += 1
                        _task(cx, f"{kind}:{model}:{n}", kind, status, again=again, step=step, model=model,
                              claimed_by=claim[0] if claim else None, claimed_at=claim[1] if claim else None,
                              queued_at=_iso(-10 - n % 7))
            _task(cx, f"{kind}:forced", kind, forced_model="opus", queued_at=_iso(-3))
            _task(cx, f"{kind}:audit", kind, role="audit", queued_at=_iso(-4))
            _task(cx, f"{kind}:out", kind, queued=0)
            _task(cx, f"{kind}:local", kind, access_="local")


def _old_counts(ws):
    """The queue's counts as status() worked them out before: every queued row read, the router asked per row."""
    r = taskqueue.router(ws)
    cutoff = taskqueue._cutoff()
    rows = ws.query("SELECT t.task_id, t.kind, t.role, t.status, t.again, t.step, t.forced_model, t.model, "
                    "t.claimed_by, t.claimed_at, t.queued_at FROM tasks t WHERE COALESCE(t.queued, 0)=1 AND "
                    "COALESCE(t.access, 'cloud')='cloud'")
    per: dict[str, dict] = {}
    groups: dict[tuple, dict] = {}
    for t in rows:
        k = t["kind"]
        d = per.setdefault(k, {"kind": k, "waiting": 0, "being_answered": 0, "done": 0, "failed": 0,
                               "stronger_model": 0})
        waiting = t["status"] in ("pending", "retry") or (t["status"] == "done" and t["again"])
        claimed = bool(t["claimed_by"]) and (t["claimed_at"] or "") >= cutoff
        if waiting and claimed:
            d["being_answered"] += 1
        elif waiting:
            d["waiting"] += 1
            m, hp = taskqueue.effective_model(t, r), taskqueue.effective_helper(t, r)
            g = groups.setdefault((k, m, hp), {"kind": k, "model": m, "helper": hp, "waiting": 0})
            g["waiting"] += 1
        elif t["status"] == "done":
            d["done"] += 1
        elif t["status"] == "failed":
            d["failed"] += 1
        if waiting and t["step"]:
            d["stronger_model"] += 1
    return per, groups


def test_the_queues_counts_per_kind_and_model_are_the_same_as_before(ws):
    _queue(ws)
    per, groups = _old_counts(ws)
    q = taskqueue.status(ws)
    keys = ("waiting", "being_answered", "done", "failed", "stronger_model")
    assert {k["kind"]: {x: k[x] for x in keys} for k in q["kinds"]} == {
        k: {x: d[x] for x in keys} for k, d in per.items()}
    o, _held = taskqueue.order(ws)
    rank = {k: i for i, k in enumerate(o)}
    want = sorted(groups.values(), key=lambda g: (rank.get(g["kind"], 99), g["model"], g["helper"]))
    assert [{x: g[x] for x in ("kind", "model", "helper", "waiting")} for g in q["groups"]] == want
    assert q["waiting"] == sum(d["waiting"] for d in per.values())
    assert q["being_answered"] == sum(d["being_answered"] for d in per.values())
    # the line a waiting page shows: what status says about that kind (and nothing about a kind with no tasks)
    for kind in ("label", "check", "theme", "link"):
        info = taskqueue.queue_info(ws, kind)
        k = next((x for x in q["kinds"] if x["kind"] == kind), None) or {}
        assert info["waiting"] == k.get("waiting", 0) + k.get("being_answered", 0)
        assert info["being_answered"] == k.get("being_answered", 0)
        assert info["estimate"] == k.get("estimate") and info["paused"] == q["paused"]
        assert info["command"] == q["command"]
    # the connector's projects with work count what queue_status calls waiting there
    with ws.connect() as cx:
        n = cx.execute(f"SELECT COUNT(*) FROM tasks t WHERE {taskqueue.WAITING} AND NOT {taskqueue.CLAIMED}",
                       (taskqueue._cutoff(),)).fetchone()[0]
    assert n == q["waiting"]
    # the "still waiting" of a batch and the run's total: as many as the rows the queue would hand out
    for kind in ("label", "check", "theme"):
        assert taskqueue._waiting_count(ws, kind) == len(taskqueue._waiting_rows(ws, kind))


def test_a_batch_takes_the_same_tasks_when_it_reads_the_queue_a_page_at_a_time(tmp_path, monkeypatch):
    from helpers_mixed_corpus import mixed_project

    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    picks = []
    for page in (10 ** 6, 3):
        w = core.create_project(f"Page {page}")
        ids = mixed_project(w, tmp_path / f"corpus{page}")
        pids = [r[0] for r in w.query("SELECT passage_id FROM passages WHERE doc_id=? ORDER BY seq", (ids["cloud"],))]
        local = w.scalar("SELECT passage_id FROM passages WHERE doc_id=? LIMIT 1", (ids["local"],))
        with w.connect() as cx:
            for i in range(12):  # the first four for another model; one whose document Claude may no longer read
                pid = local if i == 6 else pids[i % len(pids)]
                _task(cx, f"label:sdg:{i:02d}", forced_model="claude-opus-4-1" if i < 4 else None,
                      queued_at=f"2026-01-01T00:{i:02d}", payload={"framework": "sdg", "passage_id": pid, "title": "t",
                                                                   "page": 1, "text": "Green hydrogen.",
                                                                   "candidates": []})
        monkeypatch.setattr(taskqueue, "PAGE", page)
        model = taskqueue.effective_model(w.query("SELECT * FROM tasks WHERE task_id='label:sdg:05'")[0],
                                          taskqueue.router(w))
        got = taskqueue.next_tasks(w, "label", n=6, model=model)
        picks.append(([t["task_id"] for t in got["tasks"]], got["still_waiting"]))
    assert picks[0] == picks[1], picks
    assert picks[0][0] == ["label:sdg:04", "label:sdg:05", "label:sdg:07", "label:sdg:08", "label:sdg:09",
                           "label:sdg:10"]


def test_a_paused_queue_says_so_on_the_waiting_page_as_in_its_status(ws):
    with ws.connect() as cx:
        for i in range(4):
            _task(cx, f"label:sdg:p{i}", queued_at=_iso(-30 - i))
        _task(cx, "label:sdg:done", status="done", queued_at=_iso(-40))
        _task(cx, "link:x", "link", queued_at=_iso(-20))
    q = taskqueue.status(ws)
    assert q["paused"] and q["paused_text"]
    info = taskqueue.queue_info(ws, "link")
    assert info["paused"] and info["paused_text"] == q["paused_text"]
    assert info["text"].startswith("Waiting for Claude Code: 1 ")


# ---------------------------------------------------------------------------------------------
# the list of answers, the evidence map and a result read what they need once
# ---------------------------------------------------------------------------------------------
def _hypotheses(ws, n=6):
    """Hypotheses of one or two parts, checked in rounds (one failed, one waiting in the queue, one with a local part
    still waiting), with judgements."""
    with ws.connect() as cx:
        for d in range(4):
            cx.execute("INSERT INTO documents(doc_id, path, sha1, title, added_at) VALUES (?,?,?,?,?)",
                       (f"d{d}", f"/x/d{d}", f"s{d}", f"Doc {d}", "2026-01-01T00:00:00"))
            cx.executemany("INSERT INTO passages(passage_id, doc_id, seq, page, text) VALUES (?,?,?,?,?)",
                           [(f"d{d}:{i:04d}", f"d{d}", i, 1, "Green hydrogen and water.") for i in range(10)])
        cx.execute("INSERT INTO documents(doc_id, path, sha1, title, added_at) VALUES ('d9', '/x/d9', 's9', 'Later', "
                   "'2027-01-01T00:00:00')")
        for h in range(n):
            hid = f"h{h:012x}"
            cx.execute("INSERT INTO hypotheses(hyp_id, text, created_at, options_json) VALUES (?,?,?,?)",
                       (hid, f"Hypothesis {h}", f"2026-02-0{h + 1}T00:00:00", "{}"))
            for part in range(1 + h % 2):
                cid = f"u{h:06x}{part:06x}"
                cx.execute("INSERT INTO user_claims(claim_id, text, options_json, created_at, hyp_id, part, stage) "
                           "VALUES (?,?,?,?,?,?,?)", (cid, f"Part {part}", "{}", "2026-02-01", hid, part, "judge"))
                for r, suffix in enumerate(("", ":local", ":r2")):
                    ps = [{"passage_id": f"d{(h + j) % 4}:{r * 3 + j:04d}", "doc_id": f"d{(h + j) % 4}",
                           "title": f"Doc then {(h + j) % 4}", "page": 1, "text": "Green hydrogen and water."}
                          for j in range(3)]
                    status = ("failed" if (h == 2 and suffix == ":r2") else
                              "pending" if (h == 3 and suffix == ":local") or (h == 4 and suffix == ":r2") else "done")
                    _task(cx, f"check:{cid}{suffix}", "check", status, queued=1 if h == 4 else 0,
                          payload={"subject_id": cid, "passages": ps}, created_at=f"2026-02-0{h + 1}T0{r}:00:00")
                    for j, p in enumerate(ps):
                        cx.execute("INSERT INTO verifications(ver_id, subject_kind, subject_id, passage_id, doc_id, "
                                   "verdict, confidence, user_verdict) VALUES (?,?,?,?,?,?,?,?)",
                                   (f"v{cid}{r}{j}", "user_claim", cid, p["passage_id"], p["doc_id"],
                                    ("supports", "refutes", "partially_supports")[(h + j) % 3], 0.5 + 0.1 * j,
                                    "supports" if (h, j) == (1, 0) else None))
        cx.execute("DELETE FROM documents WHERE doc_id='d3'")  # a document removed since: its title from the check


def _heavy_checks(ws, claim_ids=None, titles=False):
    """The check tasks as history read them before: every payload parsed in Python."""
    out: dict = {}
    for n, r in enumerate(ws.query("SELECT task_id, status, payload_json, queued, model FROM tasks WHERE kind='check' "
                                   "ORDER BY created_at, rowid")):
        cid = r["task_id"].split(":")[1]
        if claim_ids is not None and cid not in claim_ids:
            continue
        ps = json.loads(r["payload_json"])["passages"]
        out.setdefault(cid, []).append({"task_id": r["task_id"], "status": r["status"], "queued": r["queued"],
                                        "model": r["model"], "n": n,
                                        "excerpts": [(p["passage_id"], p["doc_id"]) + ((p.get("title"),) if titles
                                                                                        else ()) for p in ps]})
    return out


def test_the_list_of_answers_reads_only_the_ids_of_each_checks_excerpts_with_the_same_answers(ws, monkeypatch):
    _hypotheses(ws)
    light = claimcheck.history(ws)
    assert [h["status"] for h in light].count("waiting") >= 1 and any(h["status_text"] for h in light)
    assert claimcheck.history(ws, limit=2) == light[:2]  # a short list reads its own checks only, with the same rows
    assert claimcheck.history(ws, query="Hypothesis 3") == [h for h in light if h["text"] == "Hypothesis 3"]
    m_light = claimcheck.evidence_map(ws)
    assert m_light == claimcheck.evidence_map(ws, cache=claimcheck.ResultCache(ws))
    assert any(d["title"] == "Doc then 3" for d in m_light["documents"])  # a removed document keeps the check's title
    monkeypatch.setattr(claimcheck, "_light_checks", _heavy_checks)
    assert claimcheck.history(ws) == light
    assert claimcheck.evidence_map(ws) == m_light
    # "waiting for the local model": as only_local_waits says, hypothesis by hypothesis
    for h in light:
        assert (h["status_text"] == claimcheck.WAITING_LOCAL) == (
            h["status"] == "waiting" and claimcheck.only_local_waits(ws, h["hyp_id"]))


def test_a_result_of_several_parts_reads_its_rounds_once_with_the_same_answer(ws):
    _hypotheses(ws)
    for h in range(6):
        hid = f"h{h:012x}"
        res = claimcheck.hypothesis_result(ws, hid)
        vs = []  # the balance as it was worked out before: the rounds and judgements of each part read again
        for (cid,) in ws.query("SELECT claim_id FROM user_claims WHERE hyp_id=? ORDER BY part, rowid", (hid,)):
            counts, _failed = claimcheck._counting(claimcheck._rounds(ws, cid))
            vs += [claimcheck.effective(v) for v in ws.query(
                "SELECT passage_id, verdict, confidence, doc_id, user_verdict FROM verifications WHERE "
                "subject_kind='user_claim' AND subject_id=?", (cid,)) if counts(v)]
        assert res["balance"] == claimcheck.balance(vs, res["threshold"])
        assert res["docs_added_since"] == claimcheck.new_documents(ws, hid)
        assert [d["doc_id"] for d in res["docs_added_since"]] == ["d9"]
        assert (res["status_text"] == claimcheck.WAITING_LOCAL) == (
            res["status"] == "waiting" and claimcheck.only_local_waits(ws, hid))
        assert [{k: v for k, v in p.items() if k != "status_before_stronger"} for p in res["parts"]] == [
            claimcheck.result(ws, p["claim_id"]) for p in res["parts"]]  # (a key hypothesis_result adds)


def test_the_local_parts_that_wait_are_the_same_as_before(ws):
    _hypotheses(ws)
    with ws.connect() as cx:
        cx.execute("UPDATE tasks SET status='failed' WHERE task_id='check:u000005000000:local'")

    def old(hyp_ids=None, retry_failed=False):
        rows = ws.query("SELECT task_id, payload_json, status FROM tasks WHERE kind='check' AND status IN "
                        f"('pending', 'retry'{', ' + repr('failed') if retry_failed else ''}) AND "
                        "substr(task_id, -6) = ':local'")
        out = []
        for r in rows:
            payload = json.loads(r["payload_json"])
            if hyp_ids is not None:
                hid = ws.scalar("SELECT hyp_id FROM user_claims WHERE claim_id=?", (payload.get("subject_id"),))
                if hid not in hyp_ids:
                    continue
            out.append({"task_id": r["task_id"], "status": r["status"], "passages": len(payload.get("passages") or [])})
        return out

    for hyp_ids in (None, ["h000000000003"], ["h000000000005", "h000000000001"], []):
        for retry in (False, True):
            assert claimcheck.local_waiting(ws, hyp_ids, retry) == old(hyp_ids, retry)
    assert claimcheck.local_waiting(ws, None, True)  # not an empty comparison


# ---------------------------------------------------------------------------------------------
# a changed setting: every open task worked out again, as each would be on its own
# ---------------------------------------------------------------------------------------------
def test_one_documents_new_setting_relabels_the_tasks_as_working_each_out_on_its_own_does(tmp_path, monkeypatch):
    from helpers_mixed_corpus import mixed_project

    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    w = core.create_project("Relabel")
    ids = mixed_project(w, tmp_path / "corpus")
    access.set_documents(w, [ids["local"], ids["none"]], "cloud")
    d1, d2 = ids["cloud"], ids["local"]
    p1, p2 = (w.scalar("SELECT passage_id FROM passages WHERE doc_id=? ORDER BY seq LIMIT 1", (d,)) for d in (d1, d2))

    # an add-on's floor about text of its own whose setting follows a document the task's text does not name: the
    # reason every open task is worked out again, not only those that name the changed document
    def follows(cx, payload, dflt):
        n = payload.get("note_id") if isinstance(payload, dict) else None
        row = cx.execute("SELECT doc_id FROM addon_notes WHERE note_id=?", (n,)).fetchone() if n else None
        return access.levels(cx, [row[0]], dflt=dflt)[row[0]] if row else None

    access.register_floor(follows)
    try:
        with w.connect() as cx:
            cx.execute("CREATE TABLE addon_notes(note_id TEXT, doc_id TEXT)")
            cx.execute("INSERT INTO addon_notes VALUES ('n1', ?)", (d2,))
            for tid, kind, payload in (
                    ("label:sdg:a", "label", {"passage_id": p1, "text": "x"}),
                    ("label:sdg:b", "label", {"passage_id": p2, "text": "x"}),
                    ("check:u1", "check", {"subject_id": "u1", "passages": [{"passage_id": p1, "doc_id": d1},
                                                                            {"passage_id": p2, "doc_id": d2}]}),
                    ("theme:t", "theme", {"members": [{"doc_id": d2}]}),
                    ("decompose:h", "decompose", {"text": "no document"}),
                    ("label:sdg:gone", "label", {"passage_id": "removed:0001"}),
                    ("note:n", "label", {"note_id": "n1", "text": "a note of the add-on"})):
                _task(cx, tid, kind, payload=payload)
            _task(cx, "label:sdg:answered", payload={"passage_id": p2}, status="done", queued=0)
            cx.execute("UPDATE tasks SET access=? WHERE task_id='label:sdg:gone'", ("cloud",))
        # what a narrowed relabel would have looked at: the tasks whose text names the document or its passages
        named = {r[0] for r in w.query("SELECT task_id FROM tasks WHERE instr(payload_json, ?)", (d2,))}
        assert "note:n" not in named
        before = {r[0]: r[1] for r in w.query("SELECT task_id, access FROM tasks")}
        out = access.set_documents(w, [d2], "local")
        after = {r[0]: r[1] for r in w.query("SELECT task_id, access FROM tasks")}
        with w.connect() as cx:  # the tasks as label_payload works each out alone (what relabel did per task)
            dflt = access._default_from_cx(cx)
            want = {r[0]: access.label_payload(cx, json.loads(r[1]), dflt=dflt) for r in cx.execute(
                f"SELECT task_id, payload_json FROM tasks WHERE {taskqueue.OPEN}")}
        assert {t: after[t] for t in want} == want
        assert after["label:sdg:answered"] == before["label:sdg:answered"] == "cloud"  # answered: left alone
        assert (after["label:sdg:b"], after["check:u1"], after["theme:t"], after["note:n"]) == ("local",) * 4
        assert after["label:sdg:a"] == after["decompose:h"] == "cloud" and after["label:sdg:gone"] == "none"
        assert out["tasks_changed"] == sum(before[t] != after[t] for t in want) == 5
        # found only by working every open task out: the add-on's note, and a label left stale (its passage gone)
        assert {t for t in want if before[t] != after[t]} - named == {"note:n", "label:sdg:gone"}
        assert w.scalar("SELECT queued FROM tasks WHERE task_id='label:sdg:b'") == 0  # out of the queue for Claude
    finally:
        access._FLOORS.remove(follows)


# ---------------------------------------------------------------------------------------------
# fewer statements, the same results
# ---------------------------------------------------------------------------------------------
def test_taking_tasks_out_of_the_queue_in_a_few_statements_leaves_what_it_left_before(ws):
    with ws.connect() as cx:
        _task(cx, "label:sdg:p1")
        _task(cx, "label:sdg:p2", status="retry")
        _task(cx, "label:sdg:p3", status="done", again=1, step=1, claimed_by="q0", claimed_at=_iso(-90))
        _task(cx, "label:sdg:p4", claimed_by="q1", claimed_at=_iso(-1))      # held: a helper answers it
        _task(cx, "label:sdg:p5", status="done")                            # answered: not in the queue's work
        _task(cx, "link:x", "link")                                         # another kind
        for tid in ("label:sdg:p1", "label:sdg:p2", "label:sdg:p3"):
            cx.execute("INSERT INTO results(task_id, attempt, kind, valid) VALUES (?, 1, 'label', 1)", (tid,))
    assert taskqueue.withdraw(ws, ["label"]) == 3
    left = {r["task_id"]: r for r in ws.query("SELECT * FROM tasks")}
    assert set(left) == {"label:sdg:p3", "label:sdg:p4", "label:sdg:p5", "link:x"}
    p3 = left["label:sdg:p3"]
    assert (p3["again"], p3["step"], p3["claimed_by"]) == (0, 0, None)  # keeps its first answer
    assert [r[0] for r in ws.query("SELECT task_id FROM results")] == ["label:sdg:p3"]
    assert taskqueue.withdraw(ws, task_ids=[]) == 0 and taskqueue.withdraw(ws, task_ids=["link:x"]) == 1


def test_the_first_tasks_of_a_kind_are_cut_in_sql(ws):
    with ws.connect() as cx:
        for i in (5, 3, 9, 1):
            _task(cx, f"label:sdg:p{i}", queued=0)
    every = tasks.pending(ws, "label")
    assert [r["task_id"] for r in every] == ["label:sdg:p1", "label:sdg:p3", "label:sdg:p5", "label:sdg:p9"]
    assert [r["task_id"] for r in tasks.pending(ws, "label", 2)] == [r["task_id"] for r in every[:2]]
    assert len(tasks.pending(ws, "label", None)) == len(tasks.pending(ws, "label", 0)) == 4


def test_the_seconds_of_a_batch_are_written_at_once_and_keep_the_last_fifty(ws):
    for _ in range(3):
        runs.timing(ws, "label", "sonnet", 2.0)
    runs.timing(ws, "label", "sonnet", 4.004, times=3)
    assert ws.meta("seconds:label:sonnet") == [2.0, 2.0, 2.0, 4.0, 4.0, 4.0]
    runs.timing(ws, "label", "sonnet", 1, times=60)
    assert ws.meta("seconds:label:sonnet") == [1.0] * 50
    runs.timing(ws, "label", "sonnet", 9, times=0)
    assert ws.meta("seconds:label:sonnet") == [1.0] * 50
    with ws.connect() as cx:
        cx.execute("INSERT OR REPLACE INTO meta VALUES ('seconds:x:y', 'not json')")
    runs.timing(ws, "x", "y", 1.5)
    assert ws.meta("seconds:x:y") == [1.5]


def test_the_step_up_rule_is_one_function_for_the_apps_runs_and_the_queue(ws):
    class Router:
        def step_up(self, kind):
            return "opus"

    with ws.connect() as cx:
        _task(cx, "label:sdg:p1")
        _task(cx, "label:sdg:p2", forced_model="haiku")
        _task(cx, "label:sdg:p3", status="retry")
        cx.execute("UPDATE tasks SET attempts=2 WHERE task_id='label:sdg:p3'")
    t1, t2, t3 = (ws.query("SELECT * FROM tasks WHERE task_id=?", (f"label:sdg:p{i}",))[0] for i in (1, 2, 3))
    unsure = {"labels": [{"code": "6.4", "confidence": 0.2, "quote": "q", "reason": "r"}]}
    assert tasks.step_up(ws, t1, Router(), True, unsure) == ("again", 0.2)
    assert ws.query("SELECT step, again, attempts FROM tasks WHERE task_id='label:sdg:p1'")[0][:] == (1, 1, 0)
    assert tasks.step_up(ws, t2, Router(), True, unsure) == (None, None)  # a model a person chose stays
    assert tasks.step_up(ws, t3, Router(), False, None) == ("retry", None)
    assert ws.scalar("SELECT step FROM tasks WHERE task_id='label:sdg:p3'") == 1
    assert tasks.step_up(ws, t1, None, True, unsure) == (None, None)

    class Backend:
        router = Router()

    assert tasks._step_up(ws, t3, Backend(), False, None) == "retry"


def test_a_model_tests_scratch_copy_is_noted_and_forgotten_under_the_data_folders_lock(ws, monkeypatch):
    calls = []
    monkeypatch.setattr(core, "mark_temporary", lambda name, **about: calls.append(("mark", name, about)))
    monkeypatch.setattr(core, "forget_temporary", lambda name: calls.append(("forget", name)) or True)
    monkeypatch.setattr(core, "_save_quicklooks", lambda data: pytest.fail("written outside the lock"))
    raws, _secs = taskqueue.answer_on_copy(ws, [], backend=None, purpose="model test")
    assert raws == {}
    (m, name, about), (f, name2) = calls
    assert (m, f, name2) == ("mark", "forget", name)
    assert about == {"file": "", "from": "Speed", "scratch": "model test"}


# ---------------------------------------------------------------------------------------------
# spreadsheets: text is never a formula
# ---------------------------------------------------------------------------------------------
VALUES = ["=1+1", "@SUM(A1)", "+1+1", "-2+3", "-5", "- a list item", "-", "3.5", "ordinary text", "\tx", "\r=x",
          "+1,200.50", "-3%", "-x", "+"]
CSV_WANT = {"=1+1": "'=1+1", "@SUM(A1)": "'@SUM(A1)", "+1+1": "'+1+1", "-2+3": "'-2+3", "-5": "-5",
            "- a list item": "- a list item", "-": "-", "3.5": "3.5", "ordinary text": "ordinary text",
            "\tx": "'\tx", "\r=x": "'\r=x", "+1,200.50": "+1,200.50", "-3%": "-3%", "-x": "'-x", "+": "+"}


def test_a_csv_cell_gets_an_apostrophe_only_where_a_spreadsheet_would_run_it():
    assert {v: review.csv_cell(v) for v in VALUES} == CSV_WANT
    for v in (3.5, -2, 0, None, True, ""):
        assert review.csv_cell(v) is v


def _csv_rows(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"), newline="")))


def _read(path, encoding="utf-8") -> str:
    with open(path, encoding=encoding, newline="") as f:  # as written: a "\r" in a cell stays one
        return f.read()


def _check_csv(rows: list[dict], col: str = "text"):
    got = [r[col] for r in rows]
    assert got[:len(VALUES)] == [CSV_WANT[v] for v in VALUES]


def _rows():
    return [{"text": v, "n": i - 3, "x": 0.5} for i, v in enumerate(VALUES)]


def test_every_csv_writer_writes_text_that_would_run_with_an_apostrophe(ws, tmp_path):
    from enlens_claims import cli, report
    from enlens_claims.gui.api_common import _csv

    rows = _csv_rows(_csv(_rows()).decode("utf-8-sig"))
    _check_csv(rows)
    assert [r["n"] for r in rows] == [str(i - 3) for i in range(len(VALUES))]  # numbers as they were
    assert _csv([]) == "".encode("utf-8-sig")

    cli._write_csv(str(tmp_path / "cli.csv"), _rows())
    _check_csv(_csv_rows(_read(tmp_path / "cli.csv", "utf-8-sig")))

    report._write_csv(tmp_path / "report.csv", [{**r, "list": ["=a"]} for r in _rows()])
    rows = _csv_rows(_read(tmp_path / "report.csv"))
    _check_csv(rows)
    assert rows[0]["list"] == '["=a"]'
    report._write_csv(tmp_path / "empty.csv", [])
    assert (tmp_path / "empty.csv").read_text() == ""

    with ws.connect() as cx:  # the reviewer queue: claims a model extracted, waiting for a person
        cx.execute("INSERT INTO documents(doc_id, path, sha1, title) VALUES ('d1', '/x', 's', '=Title')")
        cx.execute("INSERT INTO passages(passage_id, doc_id, seq, page, text) VALUES ('d1:0001', 'd1', 1, 1, 't')")
        for i, v in enumerate(VALUES):
            cx.execute("INSERT INTO claims(claim_id, task_id, doc_id, passage_id, claim, status, status_reason) "
                       "VALUES (?,?,?,?,?,?,?)", (f"c{i:02d}", "t", "d1", "d1:0001", v, "needs_review", "unsure"))
    review.export(ws, tmp_path / "review.csv", include_vca=False)
    rows = _csv_rows(_read(tmp_path / "review.csv"))
    _check_csv(rows)
    assert {r["source"] for r in rows} == {"'=Title"} and rows[0]["item_id"] == "c00"
    review.export(ws, tmp_path / "none.csv", include_vca=False)  # all reviewed or not: the header is always there
    assert (tmp_path / "none.csv").read_text(encoding="utf-8").startswith("item_kind,item_id,")


def _no_formula(data: bytes) -> list:
    wb = load_workbook(io.BytesIO(data))
    cells = [c for sh in wb.worksheets for row in sh.iter_rows() for c in row if c.value is not None]
    assert cells and not [c.coordinate for c in cells if c.data_type == "f"]
    return cells


def test_every_excel_writer_writes_text_as_text(ws):
    from enlens_claims.gui.api_common import _xlsx_with_provenance

    buf = io.BytesIO()
    claimcheck.write_xlsx(_rows(), buf, "Rows", summary=[{"=Name": "=1+1"}], extra=[("More", _rows())])
    cells = _no_formula(buf.getvalue())
    texts = [c.value for c in cells if c.data_type == "s"]
    plain = [v for v in VALUES if "\r" not in v]  # (an Excel file is XML: a bare carriage return is read as "\n")
    assert all(v in texts for v in plain) and "=Name" in texts
    assert -3 in [c.value for c in cells if c.data_type == "n"]  # numbers stay numbers
    _no_formula(_xlsx_with_provenance(ws, [("Rows", _rows()), ("More", _rows())]))
    # the helper itself: a sheet built by hand
    wb = Workbook()
    review.append_row(wb.active, ["=1+1", 2, None, "#N/A"])
    out = io.BytesIO()
    wb.save(out)
    sh = load_workbook(io.BytesIO(out.getvalue())).active
    assert [(c.value, c.data_type) for c in sh[1]] == [("=1+1", "s"), (2, "n"), (None, "n"), ("#N/A", "s")]


def test_a_table_read_from_a_pdf_and_the_works_to_find_download_as_text(api, monkeypatch):  # noqa: F811
    w = core.create_project("T")
    with w.connect() as cx:
        cx.execute("INSERT INTO documents(doc_id, path, sha1, title) VALUES ('d1', '/x', 's', '=HYPERLINK(\"x\")')")
        cx.execute("INSERT INTO doc_tables(doc_id, n, page, caption, rows_json) VALUES ('d1', 1, 2, ?, ?)",
                   ("=WEBSERVICE(\"https://x\")", json.dumps([VALUES])))
    st, body = api("GET", "/api/projects/T/documents/d1/tables/1.xlsx")
    assert st == 200
    _no_formula(body)
    sh = load_workbook(io.BytesIO(body)).active
    assert sh["A1"].value == "=WEBSERVICE(\"https://x\")" and sh["A2"].value.startswith("From: =HYPERLINK")
    row = [c.value for c in sh[4]]
    assert row[:9] == ["=1+1", "@SUM(A1)", "+1+1", "-2+3", -5, "- a list item", "-", 3.5, "ordinary text"]

    from enlens_claims import bibliography

    monkeypatch.setattr(bibliography, "to_find_rows", lambda ws: [{"Title": v, "Year": 2020} for v in VALUES])
    st, body = api("GET", "/api/projects/T/bibliography/to-find.xlsx")
    assert st == 200
    titles = [c.value for c in _no_formula(body) if c.column == 1][1:]
    assert [t for t, v in zip(titles, VALUES) if "\r" not in v] == [v for v in VALUES if "\r" not in v]
    st, body = api("GET", "/api/projects/T/bibliography/to-find.csv")
    _check_csv(_csv_rows(body.decode("utf-8-sig")), "Title")


def test_the_reviewer_queue_reads_back_the_decisions_written_beside_the_cells(ws, tmp_path):
    with ws.connect() as cx:
        cx.execute("INSERT INTO documents(doc_id, path, sha1, title) VALUES ('d1', '/x', 's', 'T')")
        cx.execute("INSERT INTO passages(passage_id, doc_id, seq, page, text) VALUES ('d1:0001', 'd1', 1, 1, 't')")
        cx.execute("INSERT INTO claims(claim_id, task_id, doc_id, passage_id, claim, status) VALUES "
                   "('c1', 't', 'd1', 'd1:0001', '=1+1 is a claim', 'needs_review')")
    review.export(ws, tmp_path / "r.csv", include_vca=False)
    text = (tmp_path / "r.csv").read_text(encoding="utf-8")
    assert re.search(r"^claim,c1,", text, re.M)
    rows = review.read_csv_rows(tmp_path / "r.csv")
    rows[0]["decision"] = "accept"
    with open(tmp_path / "r.csv", "w", newline="", encoding="utf-8") as f:
        review.write_csv(f, rows)
    assert review.import_decisions(ws, tmp_path / "r.csv")["applied"] == 1
    assert ws.scalar("SELECT status FROM claims WHERE claim_id='c1'") == "accepted"
