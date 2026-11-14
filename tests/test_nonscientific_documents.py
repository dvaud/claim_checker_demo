"""0.18.6: a document marked Non-scientific (a news article, a press release, a brochure) is read and judged as any
other, but no judgement of its excerpts counts in an answer, on either side. The answer counting it is kept beside
(`status_all_sources`); when only such documents speak to a hypothesis, the status text says so. The mark sits beside
the role (a theory document can carry it too), changes answers at once, and travels as *Leave out* does."""
from __future__ import annotations

import pytest

from enlens_claims import assessment, claimcheck, docrole, ingest, judgements
from enlens_claims.check_exports import evidence_map
from enlens_claims.check_results import hypothesis_result
from enlens_claims.llm import BaselineBackend
from enlens_claims.store import Workspace
from enlens_claims.verdicts import UNSUPPORTED_NONSCI
from owner_helpers import TEXTS

NEWS = ("Hydrogen boom brings jobs to the coast\n\n"
        "Electrolyser plants create local jobs, the company said in a press release on Monday. Hundreds of workers "
        "will be hired to build the plant, and the mayor expects more jobs to follow.\n\n"
        "Critics say the electrolyser plant will employ few local workers once it is built.\n")
CLAIM = "Electrolyser plants create local jobs"


@pytest.fixture
def project(tmp_path):
    """One scientific study and one news article, and a check that read both: (ws, news id, study id, hyp id)."""
    ws = Workspace.create(tmp_path / "proj")
    d = tmp_path / "docs"
    d.mkdir()
    (d / "jobs.txt").write_text(TEXTS["jobs"], encoding="utf-8")
    (d / "news.txt").write_text(NEWS, encoding="utf-8")
    ingest.ingest(ws, [d])
    news = ws.scalar("SELECT doc_id FROM documents WHERE title LIKE 'Hydrogen boom%'")
    study = ws.scalar("SELECT doc_id FROM documents WHERE doc_id<>?", (news,))
    hid = claimcheck.check_hypothesis(ws, CLAIM, BaselineBackend(), "baseline", k=8, per_doc=4)
    yield ws, news, study, hid
    ws.close_all()


def _judge(ws, hid, by_doc: dict[str, str]) -> None:
    """Judge every excerpt the check read yourself: the verdict given for its document (else Not about this)."""
    for part in hypothesis_result(ws, hid)["parts"]:
        for x in part["passages"]:
            judgements._set_judgement(ws, part["claim_id"], x["passage_id"], by_doc.get(x["doc_id"], "not_relevant"))


def _first(ws, hid, doc, verdict) -> None:
    """Judge one excerpt of `doc` as `verdict`, every other excerpt Not about this."""
    done = False
    for part in hypothesis_result(ws, hid)["parts"]:
        for x in part["passages"]:
            v = verdict if x["doc_id"] == doc and not done else "not_relevant"
            done = done or v == verdict
            judgements._set_judgement(ws, part["claim_id"], x["passage_id"], v)
    assert done, "the check read no excerpt of the document"


def test_marking_sets_the_mark_beside_the_role(project):
    ws, news, _study, _hid = project
    assert not docrole.is_nonscientific(ws, news) and not docrole.nonscientific_docs(ws)
    out = docrole.set_nonscientific(ws, news, True, why="a press release")
    assert out["changed"] and out["checks"] == 1 and docrole.nonscientific_docs(ws) == {news}
    assert docrole.set_nonscientific(ws, news, True)["changed"] is False
    docrole.set_role(ws, news, "theory")                # a role and the mark side by side
    docrole.set_role(ws, news, None)                    # clearing the role keeps the mark
    assert docrole.is_nonscientific(ws, news) and docrole.role_of(ws, news) is None
    log = ws.query("SELECT kind, why FROM research_log WHERE subject_id=? AND kind='document-mark'", (news,))
    assert [(r[0], r[1]) for r in log] == [("document-mark", "a press release")]
    docrole.set_nonscientific(ws, news, False)
    assert not docrole.nonscientific_docs(ws)
    assert not ws.scalar("SELECT COUNT(*) FROM block_choices WHERE doc_id=?", (news,))
    with pytest.raises(KeyError):
        docrole.set_nonscientific(ws, "no-such-doc", True)


def test_only_non_scientific_support_is_no_evidence(project):
    ws, news, _study, hid = project
    _first(ws, hid, news, "supports")
    assert hypothesis_result(ws, hid)["status"] == "supported"
    out = docrole.set_nonscientific(ws, news, True)
    assert [(a["hyp_id"], a["was"], a["now"]) for a in out["answers"]] == [(hid, "supported", "unsupported")]
    r = hypothesis_result(ws, hid)
    assert (r["status"], r["status_all_sources"], r["status_text"]) == ("unsupported", "supported", UNSUPPORTED_NONSCI)
    assert r["balance"]["docs_counted"] == 0 and not r["who"]
    xs = [x for p in r["parts"] for x in p["passages"] if x["doc_id"] == news]
    assert xs and all(x["nonscientific"] and not x["counted"] for x in xs)
    assert any(x["verdict"] == "supports" for x in xs)                   # the judgement is still shown
    # the written assessment says so, and what counting it would give; no "below your strictness" for it
    a = assessment.assess(ws, hid, r)
    rules = {s["rule"]: s["text"] for s in a["sentences"]}
    assert rules["verdict"].startswith(UNSUPPORTED_NONSCI)
    assert "non-scientific document supports it" in rules["non-scientific"]
    assert "the answer would be Supported" in rules["non-scientific"]
    assert "below-strictness" not in rules
    # the list of checks and the evidence map say the same
    row = next(h for h in claimcheck.history(ws) if h["hyp_id"] == hid)
    assert (row["status"], row["status_text"], row["supports"]) == ("unsupported", UNSUPPORTED_NONSCI, 0)
    m = evidence_map(ws)
    assert next(h for h in m["hypotheses"] if h["hyp_id"] == hid)["status"] == "unsupported"
    # 0.19.0 (K3): shown with a mark of its own, behind no answer
    assert {d["doc_id"]: d["answers"] for d in m["documents"]}[news] == 0
    assert m["cells"][hid][news]["counted"] is False
    # counted again: the answer comes back
    back = docrole.set_nonscientific(ws, news, False)
    assert [(a["was"], a["now"]) for a in back["answers"]] == [("unsupported", "supported")]
    assert hypothesis_result(ws, hid)["status"] == "supported"


def test_a_non_scientific_contradiction_makes_nothing_contested(project):
    ws, news, study, hid = project
    _judge(ws, hid, {study: "supports", news: "refutes"})
    assert hypothesis_result(ws, hid)["status"] == "contested"
    docrole.set_nonscientific(ws, news, True)
    r = hypothesis_result(ws, hid)
    assert (r["status"], r["status_all_sources"]) == ("supported", "contested")
    assert r["status_text"] != UNSUPPORTED_NONSCI and r["balance"]["docs_refuting"] == 0
    text = {s["rule"]: s["text"] for s in assessment.assess(ws, hid, r)["sentences"]}["non-scientific"]
    assert "contradicts it" in text and "the answer would be Mixed evidence" in text


def test_non_scientific_support_does_not_raise_a_partial_answer(project):
    ws, news, study, hid = project
    _judge(ws, hid, {study: "partially_supports", news: "supports"})
    assert hypothesis_result(ws, hid)["status"] == "supported"
    docrole.set_nonscientific(ws, news, True)
    assert hypothesis_result(ws, hid)["status"] == "partially_supported"


def test_the_routes(api, tmp_path):  # noqa: F811
    d = tmp_path / "in"
    d.mkdir()
    (d / "news.txt").write_text(NEWS, encoding="utf-8")
    assert api("POST", "/api/projects", {"name": "News"})[0] == 200
    from enlens_claims import home

    ws = Workspace.open(home.project_path("News"))
    try:
        ingest.ingest(ws, [d])
        news = ws.scalar("SELECT doc_id FROM documents")
    finally:
        ws.close_all()
    st, body = api("GET", f"/api/projects/News/documents/{news}/role")
    assert st == 200 and body["nonscientific"] is False and body["answers"] == []
    st, body = api("PUT", f"/api/projects/News/documents/{news}/nonscientific", {"nonscientific": True})
    assert st == 200 and body["nonscientific"] and body["changed"] and body["answers"] == []
    assert api("GET", "/api/projects/News/document-roles")[1] == {"roles": {}, "nonscientific": [news]}
    assert api("GET", f"/api/projects/News/documents/{news}/role")[1]["nonscientific"] is True
    assert api("PUT", f"/api/projects/News/documents/{news}/nonscientific", {"nonscientific": "yes"})[0] == 400
    assert api("PUT", "/api/projects/News/documents/nope/nonscientific", {"nonscientific": True})[0] == 404
    api("PUT", f"/api/projects/News/documents/{news}/nonscientific", {"nonscientific": False})
    assert api("GET", "/api/projects/News/document-roles")[1] == {"roles": {}, "nonscientific": []}


# ---- between copies: a decision about the document, like Leave out -------------------------------------------------
def test_an_owners_mark_holds_at_once_and_a_members_is_a_proposal(anna_and_ben, tmp_path):  # noqa: F811
    from enlens_claims.sync import folder
    from owner_helpers import accept, add_doc, proposals, sync, view

    shared = tmp_path / "shared"
    shared.mkdir()
    anna, ben = anna_and_ben
    for p in (anna, ben):
        with p:
            folder.set_folder(p.ws, str(shared))
    sync(anna, ben)
    paper = add_doc(anna, tmp_path, "news", text=NEWS)
    other = add_doc(anna, tmp_path, "interview")
    sync(anna, ben)
    with anna:                                       # the owner marks the article: the project's at once
        docrole.set_nonscientific(anna.ws, paper, True)
    view(anna)
    sync(anna, ben, rounds=2)
    with ben:
        assert docrole.is_nonscientific(ben.ws, paper)
    with ben:                                        # Ben, a Member, marks the interview: a proposal
        docrole.set_nonscientific(ben.ws, other, True)
    props = proposals(ben, state="waiting", kind="blocks")
    assert [(p["doc"], p["severity"]) for p in props] == [(other, "medium")]
    assert "non-scientific" in props[0]["what"] and props[0]["detail"]["nonscientific"] is True
    sync(ben, anna, rounds=2)
    with anna:
        assert not docrole.is_nonscientific(anna.ws, other)   # not the project's until she accepts
    accept(anna, proposals(anna, state="waiting", kind="blocks")[0]["id"])
    with anna:
        assert docrole.is_nonscientific(anna.ws, other)
    sync(anna, ben, rounds=2)
    with ben:
        assert docrole.is_nonscientific(ben.ws, other)
    with anna:                                       # the owner counts the article again: in every copy
        docrole.set_nonscientific(anna.ws, paper, False)
    view(anna)
    sync(anna, ben, rounds=2)
    with ben:
        assert not docrole.is_nonscientific(ben.ws, paper)


from test_shared_projects import anna_and_ben  # noqa: E402,F401  (fixture)
from test_app import api, home  # noqa: E402,F401  (fixtures)


# ---- review 1 (0.18.6) ---------------------------------------------------------------------------------------------
def test_the_rule_in_small(project):
    from enlens_claims.verdicts import PERSON, nonsci_text, set_aside

    # only "No evidence found" becomes "No scientific evidence found": "Only uncertain evidence" stays itself
    assert nonsci_text("unsupported", "supported") == UNSUPPORTED_NONSCI
    assert nonsci_text("uncertain", "supported") is None and nonsci_text("unsupported", "uncertain") is None
    # an excerpt no AI may read, that nobody has judged yet, still waits for the person (it is not "not about it")
    waits = {"doc_id": "d", "verdict": "not_enough_info", "confidence": None, "model": PERSON, "user_verdict": None}
    judged = {"doc_id": "d", "verdict": "supports", "confidence": 1.0, "model": "ai", "user_verdict": "supports"}
    assert set_aside([waits, judged], {"d"})[0] == waits
    assert set_aside([waits, judged], {"d"})[1]["verdict"] == "not_enough_info"


def test_the_connector_says_which_quotes_count(project):
    from enlens_claims import mcp_server

    ws, news, _study, hid = project
    _first(ws, hid, news, "supports")
    docrole.set_nonscientific(ws, news, True)
    cid = hypothesis_result(ws, hid)["parts"][0]["claim_id"]
    out = mcp_server._summary(ws, cid)
    assert out["status"] == "unsupported" and out["status_counting_non_scientific"] == "supported"
    mine = [e for e in out["evidence"] if e.get("non_scientific")]
    assert mine and all(e["counted"] is False for e in mine) and "non-scientific" in out["non_scientific_note"]
    # the checks list and the document's page give the answer counting them too, without a full result each
    row = next(h for h in claimcheck.history(ws) if h["hyp_id"] == hid)
    assert row["status_all_sources"] == "supported"
    assert docrole.counted_without(ws, news) == [{"hyp_id": hid, "text": CLAIM, "status": "unsupported",
                                                  "status_text": UNSUPPORTED_NONSCI, "all": "supported",
                                                  "all_text": "Supported by your documents",
                                                  "count_nonscientific": False}]
    log = ws.query("SELECT text, data_json FROM research_log WHERE kind='document-mark' AND subject_id=?", (news,))
    assert len(log) == 1 and "Answers changed" in log[0][0] and hid in log[0][1]
