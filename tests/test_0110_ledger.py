"""0.11: the ledger of what was sent to Claude, the share per document, and the cap.

Rows are written when text leaves the computer and only then: the Claude API (before the call), Claude Code (when it
takes a batch), a Claude chat through the connector (the excerpts it is shown); a local model writes none.
"""
from __future__ import annotations

import pytest
from helpers_0110 import Cloud, Local, mixed_project, use_local_model

from enlens_claims import access, claimcheck, home, taskqueue, tasks

HYP = "Green hydrogen production can increase water stress in arid regions."


@pytest.fixture
def mixed(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    ws = home.create_project("Mixed")
    ids = mixed_project(ws, tmp_path / "corpus")
    use_local_model(monkeypatch, Local())
    return ws, ids


def test_rows_on_send_and_only_then(mixed):
    ws, ids = mixed
    assert access.ledger(ws) == []
    claimcheck.check_hypothesis(ws, HYP, Local(), "qwen", k=12, per_doc=4)
    assert access.ledger(ws) == []  # a local model: nothing left the computer
    cloud = Cloud()
    hid = claimcheck.check_hypothesis(ws, HYP, cloud, "claude-opus", k=12, per_doc=4)
    rows = access.ledger(ws)
    assert rows and {r["doc_id"] for r in rows} == {ids["cloud"]}
    assert {r["route"] for r in rows} == {"Claude API"} and {r["feature"] for r in rows} == {"Check"}
    sent = {r["passage_id"] for r in rows}
    shown = {x["passage_id"] for p in claimcheck.hypothesis_result(ws, hid)["parts"] for x in p["passages"]
             if x["doc_id"] == ids["cloud"]}
    assert shown <= sent  # every excerpt sent (and the passage before it, shown as context, when there is one)
    share = access.shares(ws)[ids["cloud"]]
    assert 0 < share["share"] <= 1 and share["passages"] == len(sent)
    assert access.shares(ws)[ids["local"]]["share"] == 0
    d = access.document_ledger(ws, ids["cloud"])
    assert d["passages"] and d["passages"][0]["features"] == ["Check"] and d["share"] == share["share"]


def test_claude_code_rows_when_a_batch_is_taken(mixed):
    ws, ids = mixed
    with tasks.queueing():
        claimcheck.queue_check(ws, HYP, None, k=12, per_doc=4, expand=False)
    assert access.ledger(ws) == []  # waiting in the queue is not sent
    got = taskqueue.next_tasks(ws, "check")
    assert got["tasks"]
    rows = access.ledger(ws)
    assert rows and {r["route"] for r in rows} == {"Claude Code"} and {r["doc_id"] for r in rows} == {ids["cloud"]}


def test_a_claude_chat_rows_for_what_it_is_shown(mixed):
    ws, ids = mixed
    r = claimcheck.open_check(ws, HYP, terms=["water"], k=12, per_doc=4)
    rows = access.ledger(ws)
    assert {x["route"] for x in rows} == {"Claude app (connector)"} and {x["doc_id"] for x in rows} == {ids["cloud"]}
    assert len({x["passage_id"] for x in rows}) >= len(r["passages"])


def test_the_cap_stops_further_reading(mixed):
    ws, ids = mixed
    access.set_documents(ws, [ids["cloud"]], budget=5)
    cloud = Cloud()
    claimcheck.check_hypothesis(ws, HYP, cloud, "claude-opus", k=12, per_doc=4)
    first = len(cloud.sent)
    assert first  # the first round may overshoot the cap (it is checked when tasks are made)
    assert access.levels(ws, [ids["cloud"]])[ids["cloud"]] == "local"
    before = len({r["passage_id"] for r in access.ledger(ws)})
    claimcheck.check_hypothesis(ws, "Electrolysis needs fresh water.", cloud, "claude-opus", k=12, per_doc=4)
    assert len({r["passage_id"] for r in access.ledger(ws)}) == before  # nothing more of it reached Claude


def test_the_csv_and_the_documents_page(mixed, tmp_path):
    ws, ids = mixed
    import threading

    from test_app import Api

    from enlens_claims.gui.server import make_server

    claimcheck.check_hypothesis(ws, HYP, Cloud(), "claude-opus", k=12, per_doc=4)
    srv, app = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        api = Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token)
        st, body = api("GET", "/api/projects/Mixed/documents")
        assert st == 200
        by = {d["doc_id"]: d for d in body["documents"]}
        assert by[ids["cloud"]]["sent"] > 0 and by[ids["local"]]["ai_access"] == "local"
        assert by[ids["none"]]["ai_access"] == "none" and body["ai_access"]["counts"] == {"cloud": 1, "local": 1, "none": 1}
        st, raw = api("GET", "/api/projects/Mixed/ai-sent.csv")
        text = raw if isinstance(raw, str) else raw.decode() if isinstance(raw, bytes) else str(raw)
        assert st == 200 and "Claude API" in text and "Passage id" in text
        st, led = api("GET", f"/api/projects/Mixed/documents/{ids['cloud']}/ai-sent")
        assert st == 200 and led["passages"]
        # changing several documents at once, with a note
        st, body = api("PUT", "/api/projects/Mixed/documents/ai-access",
                       {"doc_ids": [ids["cloud"], ids["local"]], "ai_access": "none", "note": "contains interview data"})
        assert st == 200 and body["tasks_changed"] >= 0
        by = {d["doc_id"]: d for d in body["documents"]}
        assert by[ids["cloud"]]["ai_access"] == "none" and by[ids["local"]]["note"] == "contains interview data"
        st, body = api("PUT", "/api/projects/Mixed/documents/ai-access", {"doc_ids": [ids["cloud"]], "ai_access": "x"})
        assert st == 400
        st, body = api("PUT", "/api/projects/Mixed/ai-access", {"default": "local"})
        assert st == 200 and body["ai_access"]["default"] == "local"
    finally:
        srv.shutdown()
        srv.server_close()
