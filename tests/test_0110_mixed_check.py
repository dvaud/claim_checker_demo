"""0.11: one round of a check with excerpts of all three settings.

Claude reads the excerpts it may, the local model those marked "Only a local AI", and those marked "No AI" wait for a
person's judgement. The round is shown as one; each excerpt says who read it; without a local model (or when it cannot
be reached) the local excerpts wait for a person too.
"""
from __future__ import annotations

import pytest
from helpers_0110 import Cloud, Local, mixed_project, use_local_model

from enlens_claims import claimcheck, home
from enlens_claims.llm import BackendError

HYP = "Green hydrogen production can increase water stress in arid regions."


@pytest.fixture
def mixed(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    ws = home.create_project("Mixed")
    return ws, mixed_project(ws, tmp_path / "corpus")


def test_one_round_three_readers(mixed, monkeypatch):
    ws, ids = mixed
    cloud, local = Cloud(), Local()
    use_local_model(monkeypatch, local)
    steps = []
    hid = claimcheck.check_hypothesis(ws, HYP, cloud, "claude-opus", k=12, per_doc=4,
                                      progress=lambda s, m, i=None: steps.append((s, m)))
    res = claimcheck.hypothesis_result(ws, hid)
    part = res["parts"][0]
    assert part["rounds"] == 1 and len(part["rounds_info"]) == 1  # shown as one round
    info = part["rounds_info"][0]
    assert {p["read_by"] for p in info["parts"]} == {"claude", "local", "you"}
    assert info["passages"] == len(part["passages"])
    who = {}
    for x in part["passages"]:
        who.setdefault(x["doc_id"], set()).add(x["read_by"])
    assert who == {ids["cloud"]: {"claude"}, ids["local"]: {"local"}, ids["none"]: {"you"}}
    assert all(x["waiting_for_you"] for x in part["passages"] if x["doc_id"] == ids["none"])
    assert res["waiting_for_you"] == sum(1 for x in part["passages"] if x["doc_id"] == ids["none"])
    # each model was told how many excerpts of the round it is not shown
    assert "from documents you are not shown" in cloud.sent[-1] and "from documents you are not shown" in local.sent[-1]
    # the progress said who reads what
    grade = [m for s, m in steps if s == "grade"][0]
    assert "Claude is reading" in grade and "local model" in grade and "your judgement" in grade
    # the overall answer counts the local model's grades too
    assert res["status"] in ("supported", "partially_supported", "contested", "uncertain")
    # a further round is split the same way
    r = claimcheck.continue_check(ws, part["claim_id"], cloud, "claude-opus", k=12)
    if r["passages"]:
        again = claimcheck.result(ws, part["claim_id"])
        assert again["rounds"] == 2
    # deleting the check removes every part
    claimcheck.delete_hypothesis(ws, hid)
    assert ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind='check'") == 0
    assert ws.scalar("SELECT COUNT(*) FROM verifications WHERE subject_kind='user_claim'") == 0


def test_without_a_local_model_they_wait_for_a_person(mixed, monkeypatch):
    ws, ids = mixed
    use_local_model(monkeypatch, None)
    hid = claimcheck.check_hypothesis(ws, HYP, Cloud(), "claude-opus", k=12, per_doc=4)
    part = claimcheck.hypothesis_result(ws, hid)["parts"][0]
    assert {x["read_by"] for x in part["passages"] if x["doc_id"] != ids["cloud"]} == {"you"}
    assert {p["read_by"] for p in part["rounds_info"][0]["parts"]} == {"claude", "you"}


def test_a_local_model_that_cannot_be_reached(mixed, monkeypatch):
    ws, ids = mixed

    class Down(Local):
        def complete(self, *a, **k):
            raise BackendError("No local model server is running.")

    use_local_model(monkeypatch, Down())
    steps = []
    hid = claimcheck.check_hypothesis(ws, HYP, Cloud(), "claude-opus", k=12, per_doc=4,
                                      progress=lambda s, m, i=None: steps.append((s, m)))
    part = claimcheck.hypothesis_result(ws, hid)["parts"][0]
    assert {x["read_by"] for x in part["passages"] if x["doc_id"] == ids["local"]} == {"you"}
    assert any("could not be reached" in m for s, m in steps if s == "note")
    assert part["status"] != "failed"


def test_with_a_local_main_model_one_task_reads_both(mixed, monkeypatch):
    """A model on this computer may read documents marked Only a local AI: no split is needed for them."""
    ws, ids = mixed
    use_local_model(monkeypatch, None)
    local = Local()
    hid = claimcheck.check_hypothesis(ws, HYP, local, "qwen", k=12, per_doc=4)
    part = claimcheck.hypothesis_result(ws, hid)["parts"][0]
    assert [p["read_by"] for p in part["rounds_info"][0]["parts"]] == ["local", "you"]
    assert {x["read_by"] for x in part["passages"] if x["doc_id"] in (ids["cloud"], ids["local"])} == {"local"}


def test_a_check_in_a_claude_chat(mixed, monkeypatch):
    """The connector's open_check shows Claude the excerpts it may read; the local ones wait for the app."""
    ws, ids = mixed
    local = Local()
    use_local_model(monkeypatch, local)
    r = claimcheck.open_check(ws, HYP, terms=["water"], k=12, per_doc=4)
    assert r["passages"] and r["restricted_passages"] > 0 and "not shown to you" in r["restricted_note"]
    hid = r["check_id"]
    res = claimcheck.hypothesis_result(ws, hid)
    assert res["status"] == "waiting" and res["waiting_local"] > 0
    first = r["passages"][0]
    quote = " ".join(first["text"].split()[:6])
    assert claimcheck.submit_grades(ws, hid, [{"passage": 1, "verdict": "supports", "confidence": 0.9, "quote": quote}],
                                    "One.")["accepted"]
    # the app reads the local part with the local model ("Read them now")
    from enlens_claims import access

    assert claimcheck.run_local_parts(ws, [hid], access.Readers(None, "")) == 1
    res = claimcheck.hypothesis_result(ws, hid)
    assert res["waiting_local"] == 0 and res["status"] != "waiting" and local.sent
    # a round whose excerpts all come from restricted documents has nothing for the chat to grade
    more = claimcheck.more_passages(ws, hid, k=4, doc_ids=[ids["none"]])
    if more.get("restricted_passages") and not more["passages"]:
        with pytest.raises(ValueError, match="nothing for you to grade"):
            claimcheck.submit_grades(ws, hid, [], "none")
