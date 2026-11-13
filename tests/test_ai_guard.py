"""The AI-access guard and the task queue, after a review of 0.17.0.

- a task brought back after it was answered ("Ask a stronger model", `refresh`, `requeue`) gets the setting of its
  documents now, and the guard works the setting out again from the task's text whenever it is about to leave;
- "Read them now" on the local parts of a check: a part whose document is now marked No AI waits for the person,
  and one part the guard stops does not stop the others;
- the cap on how much of a document Claude may read holds within one batch the queue hands out, and in a run of
  several tasks (`run_here`, `tasks.run`);
- an answer is stored for the claim that holds its task, and only then; a Claude chat does not grade a round a
  helper holds;
- taking one kind of task out of the queue removes only the checks that wait for that kind, and none a helper holds;
- a line of Ollama's stream that does not parse is skipped, as the local server's are.
"""
from __future__ import annotations

import json
import time

import pytest
from helpers_mixed_corpus import Cloud, Local, mixed_project, use_local_model

from enlens_claims import access, claimcheck, taskqueue, tasks
from enlens_claims import home as core
from test_app import CLAIM, api, home  # noqa: F401  (fixtures)


@pytest.fixture
def mixed(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    ws = core.create_project("Mixed")
    ids = mixed_project(ws, tmp_path / "corpus")
    pid = {k: ws.scalar("SELECT passage_id FROM passages WHERE doc_id=? ORDER BY seq LIMIT 1", (v,))
           for k, v in ids.items()}
    return ws, ids, pid


def _label(pid):
    return {"framework": "sdg", "passage_id": pid, "title": "t", "page": None, "text": "Green hydrogen and water.",
            "candidates": []}


def _insert(ws, tid, payload, kind="label", queued=False):
    with tasks.queueing(queued):
        with ws.connect() as cx:
            tasks._insert_task(cx, tid, kind, "m", payload)
    return ws.query("SELECT * FROM tasks WHERE task_id=?", (tid,))[0]


def _row(ws, tid):
    return ws.query("SELECT * FROM tasks WHERE task_id=?", (tid,))[0]


# ---------------------------------------------------------------------------------------------
# C1: a task brought back after it was answered
# ---------------------------------------------------------------------------------------------
def test_asking_a_stronger_model_after_a_document_was_restricted_keeps_its_text_from_claude(mixed):
    ws, ids, pid = mixed
    tid = "label:sdg:" + pid["cloud"]
    _insert(ws, tid, _label(pid["cloud"]))
    with ws.connect() as cx:  # answered while Claude could read the document
        cx.execute("UPDATE tasks SET status='done' WHERE task_id=?", (tid,))
    access.set_documents(ws, [ids["cloud"]], "local")
    assert _row(ws, tid)["access"] == "cloud"  # an answered task keeps the setting it was read under
    with tasks.queueing():
        tasks.ask_stronger(ws, tid)
    t = _row(ws, tid)
    assert (t["again"], t["access"], t["queued"]) == (1, "local", 0)
    assert taskqueue.next_tasks(ws, "label", n=5)["claim"] is None
    cloud = Cloud()
    assert tasks.answer_again(ws, tid, cloud) is False  # the first answer stays; nothing reaches Claude
    assert not cloud.sent
    assert not _row(ws, tid)["again"]  # and it does not wait for a stronger reading no route here may give
    # a model on this computer may still read it again
    with ws.connect() as cx:
        cx.execute("UPDATE tasks SET step=0 WHERE task_id=?", (tid,))
    tasks.ask_stronger(ws, tid)
    local = Local()
    tasks.answer_again(ws, tid, local)
    assert local.sent


def test_refresh_and_requeue_give_a_task_the_setting_of_its_documents_now(mixed):
    ws, ids, pid = mixed
    a, b = "label:sdg:" + pid["cloud"], "label:sdg:other"
    _insert(ws, a, _label(pid["cloud"]))
    _insert(ws, b, {**_label(pid["cloud"]), "title": "b"})
    with ws.connect() as cx:
        cx.execute("UPDATE tasks SET status='done', prompt_version='old' WHERE task_id=?", (a,))
        cx.execute("UPDATE tasks SET status='exported' WHERE task_id=?", (b,))
    access.set_documents(ws, [ids["cloud"]], "local")
    assert tasks.refresh(ws, "label") == 1
    assert (_row(ws, a)["status"], _row(ws, a)["access"]) == ("pending", "local")
    assert tasks.requeue(ws, "label") == 1
    assert (_row(ws, b)["status"], _row(ws, b)["access"]) == ("pending", "local")
    cloud = Cloud()
    tasks.run(ws, "label", cloud)
    assert not cloud.sent


def test_the_guard_works_the_setting_out_again_when_text_is_about_to_leave(mixed):
    ws, ids, pid = mixed
    tid = "label:sdg:" + pid["local"]
    _insert(ws, tid, _label(pid["local"]))
    with ws.connect() as cx:  # a column that went stale (a path that forgot to relabel)
        cx.execute("UPDATE tasks SET access='cloud', queued=1, queued_at='2026-01-01T00:00:00+00:00' WHERE task_id=?",
                   (tid,))
    assert taskqueue.next_tasks(ws, "label", n=5)["claim"] is None
    t = _row(ws, tid)
    assert (t["access"], t["queued"]) == ("local", 0)  # corrected, and out of the queue
    with ws.connect() as cx:
        cx.execute("UPDATE tasks SET access='cloud' WHERE task_id=?", (tid,))
    cloud = Cloud()
    with pytest.raises(access.AccessError, match="Only a local AI"):
        tasks.run_one(ws, tid, cloud, "m")
    assert not cloud.sent and _row(ws, tid)["access"] == "local"
    from enlens_claims.llm import ClaudeCodeBackend

    with ws.connect() as cx:
        cx.execute("UPDATE tasks SET access='cloud' WHERE task_id=?", (tid,))
    with pytest.raises(access.AccessError):
        tasks.run_one(ws, tid, ClaudeCodeBackend(), "haiku")
    # the guard never loosens a task: one labelled for the local model stays so, whatever the column of its peers
    ok = "label:sdg:" + pid["cloud"]
    _insert(ws, ok, _label(pid["cloud"]))
    with ws.connect() as cx:
        cx.execute("UPDATE tasks SET access='local' WHERE task_id=?", (ok,))
    with pytest.raises(access.AccessError):
        tasks.run_one(ws, ok, Cloud(), "m")


# ---------------------------------------------------------------------------------------------
# C2: "Read them now" on the local parts of a check
# ---------------------------------------------------------------------------------------------
def _local_part(ws, ids, pid, which, tid, status="pending"):
    p = ws.query("SELECT passage_id, doc_id, page, text FROM passages WHERE passage_id=?", (pid[which],))[0]
    payload = {"subject_kind": "user_claim", "subject_id": tid.split(":")[1], "claim": CLAIM, "target": None,
               "target_description": None, "passages": [{"passage_id": p["passage_id"], "doc_id": p["doc_id"],
                                                         "title": "t", "page": p["page"], "text": p["text"]}]}
    _insert(ws, tid, payload, "check")
    with ws.connect() as cx:
        cx.execute("UPDATE tasks SET status=?, attempts=? WHERE task_id=?",
                   (status, 3 if status == "failed" else 0, tid))


def test_reading_local_parts_again_never_gives_a_no_ai_document_to_the_local_model(mixed, monkeypatch):
    ws, ids, pid = mixed
    local = Local()
    use_local_model(monkeypatch, local)
    _local_part(ws, ids, pid, "local", "check:c1:local", status="failed")
    access.set_documents(ws, [ids["local"]], "none")  # marked No AI after its answers could not be used
    n = claimcheck.run_local_parts(ws, readers=access.Readers(None, ""), retry_failed=True)
    assert n == 1 and not local.sent
    t = _row(ws, "check:c1:local")
    assert (t["status"], t["model"], t["access"]) == ("done", claimcheck.PERSON, "none")  # it waits for the person
    assert ws.scalar("SELECT COUNT(*) FROM verifications WHERE subject_id='c1' AND model=?", (claimcheck.PERSON,)) == 1


def test_one_local_part_the_guard_stops_does_not_stop_the_others(mixed, monkeypatch):
    ws, ids, pid = mixed
    local = Local()
    use_local_model(monkeypatch, local)
    _local_part(ws, ids, pid, "local", "check:c1:local")
    _local_part(ws, ids, pid, "local", "check:c2:local")
    with ws.connect() as cx:  # the first one's document became No AI; the second is still for the local model
        cx.execute("UPDATE tasks SET access='none' WHERE task_id='check:c1:local'")
        cx.execute("UPDATE tasks SET payload_json=replace(payload_json, ?, ?) WHERE task_id='check:c1:local'",
                   (ids["local"], ids["none"]))
    n = claimcheck.run_local_parts(ws, readers=access.Readers(None, ""))
    assert n == 2
    assert _row(ws, "check:c1:local")["model"] == claimcheck.PERSON
    assert local.sent and all("check:c1" not in s for s in local.sent)
    assert _row(ws, "check:c2:local")["model"] != claimcheck.PERSON


# ---------------------------------------------------------------------------------------------
# C3: the cap holds within a batch and a run
# ---------------------------------------------------------------------------------------------
@pytest.fixture
def capped(tmp_path, monkeypatch):
    """One document of five passages that Claude may read up to 20 % of, and five check tasks of one passage each."""
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    c = tmp_path / "c"
    c.mkdir()
    paras = [f"Section {i:02d}. Green hydrogen plants in arid regions need fresh water, land and steady sun, and "
             f"section {i:02d} of this report weighs each of those needs against the others in some detail."
             for i in range(10)]
    (c / "capped.txt").write_text("Capped report\n\n" + "\n\n".join(paras) + "\n")
    ws = core.create_project("Cap")
    from enlens_claims import ingest

    ingest.ingest(ws, [c], ai_access="cloud")
    doc = ws.scalar("SELECT doc_id FROM documents")
    access.set_documents(ws, [doc], budget=20)
    rows = ws.query("SELECT passage_id, page, text, LENGTH(text) AS n FROM passages WHERE doc_id=? ORDER BY seq",
                    (doc,))
    assert len(rows) >= 5
    ids = []
    for i, p in enumerate(rows[:5]):
        tid = f"check:cap{i}"
        _insert(ws, tid, {"subject_kind": "user_claim", "subject_id": f"cap{i}", "claim": CLAIM, "target": None,
                          "target_description": None,
                          "passages": [{"passage_id": p["passage_id"], "doc_id": doc, "title": "Capped report",
                                        "page": p["page"], "text": p["text"]}]}, "check", queued=True)
        ids.append(tid)
    assert {r[0] for r in ws.query("SELECT access FROM tasks")} == {"cloud"}  # nothing read yet: all for Claude
    total = sum(r["n"] for r in rows)
    allowed, sent = 0, 0  # the rule: a task goes while what Claude has read is below the cap
    for p in rows[:5]:
        if sent * 100 / total >= 20:
            break
        allowed += 1
        sent += p["n"]
    assert allowed < 5
    return ws, doc, ids, allowed


def _read_passages(ws, doc):
    return ws.scalar("SELECT COUNT(DISTINCT passage_id) FROM ai_sent WHERE doc_id=?", (doc,))


def test_one_batch_from_the_queue_keeps_within_the_cap(capped):
    ws, doc, ids, allowed = capped
    got = taskqueue.next_tasks(ws, "check", n=5)
    assert len(got["tasks"]) == allowed and _read_passages(ws, doc) == allowed
    left = ws.query("SELECT access, queued FROM tasks WHERE claimed_by IS NULL")
    assert left and {(r["access"], r["queued"]) for r in left} == {("local", 0)}  # they wait for the local model
    assert taskqueue.next_tasks(ws, "check", n=5)["claim"] is None


def test_answering_the_queue_here_keeps_within_the_cap(capped):
    ws, doc, ids, allowed = capped
    cloud = Cloud()
    taskqueue.run_here(ws, cloud, kinds=["check"])
    assert _read_passages(ws, doc) == allowed
    assert {json.loads(_row(ws, t)["payload_json"])["subject_id"] for t in ids
            if _row(ws, t)["access"] == "cloud"} == {f"cap{i}" for i in range(allowed)}


def test_a_run_of_several_tasks_keeps_within_the_cap(capped):
    ws, doc, ids, allowed = capped
    cloud = Cloud()
    tasks.run(ws, "check", cloud)
    assert _read_passages(ws, doc) == allowed
    assert ws.scalar("SELECT COUNT(*) FROM tasks WHERE access='local' AND status='pending'") == 5 - allowed


def test_writing_tasks_for_the_file_queue_keeps_within_the_cap(capped):
    ws, doc, ids, allowed = capped
    files = tasks.export(ws, "check")
    written = [json.loads(line)["task_id"] for f in files for line in f.read_text().splitlines()]
    assert len(written) == allowed and _read_passages(ws, doc) == allowed
    assert ws.scalar("SELECT COUNT(*) FROM tasks WHERE status='pending' AND access='local'") == 5 - allowed


# ---------------------------------------------------------------------------------------------
# C8: one answer per claim
# ---------------------------------------------------------------------------------------------
def test_an_answer_from_a_lapsed_claim_is_not_stored_beside_the_new_one(mixed, monkeypatch):
    ws, ids, pid = mixed
    tid = "label:sdg:" + pid["cloud"]
    _insert(ws, tid, _label(pid["cloud"]), queued=True)
    a = taskqueue.next_tasks(ws, "label", n=1, taken_by="A")
    assert [t["task_id"] for t in a["tasks"]] == [tid]
    real = tasks.ingest_result
    seen = {"b": None}

    def meanwhile(*args, **kw):
        if seen["b"] is None:  # A's answer is on its way: its claim lapses, and B takes the task and answers it
            with ws.connect() as cx:
                cx.execute("UPDATE tasks SET claimed_at='2000-01-01T00:00:00+00:00' WHERE task_id=?", (tid,))
            b = taskqueue.next_tasks(ws, "label", n=1, taken_by="B")
            seen["b"] = b
            assert [t["task_id"] for t in b["tasks"]] == [tid]
            seen["b_out"] = taskqueue.submit(ws, b["claim"], [{"task_id": tid, "answer": {"labels": []}}])
        return real(*args, **kw)

    monkeypatch.setattr(tasks, "ingest_result", meanwhile)
    out = taskqueue.submit(ws, a["claim"], [{"task_id": tid, "answer": {"labels": []}}])
    assert ws.scalar("SELECT COUNT(*) FROM results WHERE task_id=?", (tid,)) == 1
    assert seen["b_out"]["results"][0]["task_id"] == tid  # B's answer is the one kept
    item = out["results"][0]  # A is told, in the words of a task another session took (or has answered)
    assert item["stored"] is False and item["attempts_left"] == 0
    assert item["problems"][0] in ("already answered",
                                   "this claim lapsed and the task was handed to another session; leave it")


def test_a_claude_chat_does_not_grade_a_round_a_helper_holds(mixed, monkeypatch):
    ws, ids, pid = mixed
    r = claimcheck.open_check(ws, CLAIM, terms=["water"], k=3, per_doc=3)
    cid = r["check_id"]
    tid = f"check:{cid}"
    with ws.connect() as cx:  # the round waits in the queue, and a helper takes it
        tasks.mark_queued(cx, [tid])
    a = taskqueue.next_tasks(ws, "check", n=1, taken_by="A")
    assert [t["task_id"] for t in a["tasks"]] == [tid]
    with pytest.raises(ValueError, match="helper"):
        claimcheck.submit_grades(ws, cid, [], "Nothing bears on it.")
    assert ws.scalar("SELECT COUNT(*) FROM results WHERE task_id=?", (tid,)) == 0
    taskqueue.submit(ws, a["claim"], [{"task_id": tid, "answer": {"evidence": [], "rationale": "Nothing."}}])
    assert ws.scalar("SELECT COUNT(*) FROM results WHERE task_id=?", (tid,)) == 1
    # a helper that takes it between the chat's look and its answer: still one answer, and the chat is told
    r2 = claimcheck.open_check(ws, "Electrolysis needs fresh water.", terms=["water"], k=3, per_doc=3)
    tid2 = f"check:{r2['check_id']}"
    real = tasks.ingest_result

    def meanwhile(*args, **kw):
        with ws.connect() as cx:
            cx.execute("UPDATE tasks SET queued=1, claimed_by='qhelper', claimed_at=? WHERE task_id=?",
                       (taskqueue.now(), tid2))
        return real(*args, **kw)

    monkeypatch.setattr(tasks, "ingest_result", meanwhile)
    with pytest.raises(ValueError, match="helper"):
        claimcheck.submit_grades(ws, r2["check_id"], [], "Nothing bears on it.")
    assert ws.scalar("SELECT COUNT(*) FROM results WHERE task_id=?", (tid2,)) == 0


# ---------------------------------------------------------------------------------------------
# C9: taking one kind out of the queue
# ---------------------------------------------------------------------------------------------
def test_taking_one_kind_out_of_the_queue_removes_only_the_checks_that_wait_for_it(api, home, corpus):  # noqa: F811
    from enlens_claims import ingest, routing

    ws = home.create_project("W")
    ingest.ingest(ws, [corpus])
    home.update_settings({"allow_claude_code": True, "backend": "claude_code"})
    r = routing.from_settings(home.load_settings())
    h1 = claimcheck.queue_check(ws, CLAIM, r, k=3)
    h2 = claimcheck.queue_check(ws, "Electrolysis needs fresh water.", r, k=3)
    waiting = {h["hyp_id"] for h in ws.query("SELECT hyp_id FROM hypotheses WHERE queue='waiting'")}
    assert waiting == {h1, h2}
    assert ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind='expand' AND queued=1") == 2
    # nothing of kind "check" waits yet: taking that kind out leaves both checks alone
    st, out = api("POST", "/api/projects/W/queue/withdraw", {"kind": "check"})
    assert st == 200 and out["checks_removed"] == 0
    assert {h["hyp_id"] for h in ws.query("SELECT hyp_id FROM hypotheses")} == {h1, h2}
    # a helper holds the search words of one of them: taking "expand" out removes only the other
    got = taskqueue.next_tasks(ws, "expand", n=1, taken_by="A")
    held = got["tasks"][0]["task_id"]
    held_hyp = ws.scalar("SELECT hyp_id FROM user_claims WHERE claim_id=?", (held.split(":", 1)[1],))
    st, out = api("POST", "/api/projects/W/queue/withdraw", {"kind": "expand"})
    assert st == 200 and out["checks_removed"] == 1
    assert {h["hyp_id"] for h in ws.query("SELECT hyp_id FROM hypotheses")} == {held_hyp}
    assert ws.query("SELECT claimed_by FROM tasks WHERE task_id=?", (held,))[0][0] == got["claim"]


# ---------------------------------------------------------------------------------------------
# C15: a line of Ollama's stream that does not parse
# ---------------------------------------------------------------------------------------------
class _Stream:
    def __init__(self, lines):
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self.lines)

    def close(self):
        pass


def test_a_broken_line_in_ollamas_stream_is_skipped():
    from enlens_claims.llm import OllamaBackend

    lines = [json.dumps({"message": {"content": '{"a": '}}).encode() + b"\n",
             b"{not json at all\n",
             b"\xff\xfe\n",
             json.dumps({"message": {"content": "1}"}}).encode() + b"\n",
             json.dumps({"done": True, "eval_count": 2}).encode() + b"\n"]
    be = OllamaBackend("http://127.0.0.1:9", opener=lambda req, timeout=None: _Stream(lines))
    info = {"task": "check", "model": "m", "phase": "waiting", "prompt_tokens": 1, "thinking_tokens": 0,
            "answer_tokens": 0, "seconds": 0.0, "first_token_after": None, "rate": None, "tail": ""}
    content, final = be._stream({"model": "m"}, "m", info, time.time(), 0)
    assert "".join(content) == '{"a": 1}' and final.get("done") is True
