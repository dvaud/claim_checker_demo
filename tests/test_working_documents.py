"""0.18.8 (roadmap N3): a working document is the researcher's own draft or notes, kept in the project, never a source.

It is the third value of a document's role (docrole.py), beside evidence and theory. It is read, searched, opened,
noted and labelled with codebooks (its codes are its own: a row of the profile's grid, never in the corpus's code
counts), and a sentence of it can be checked against the corpus; it is left out of themes, the excerpts a check reads,
key terms and the glossary's counts, as a theory document is."""
from __future__ import annotations

import pytest

from enlens_claims import docrole, ingest, profile, search, terms, themes, theorycodes
from enlens_claims.store import Workspace
from owner_helpers import TEXTS

DRAFT = ("My chapter draft on hydrogen jobs\n\n"
         "I argue that electrolyser plants create local jobs for workers in the region, and that the jobs last "
         "beyond the construction phase. Desalination for the electrolysers needs water and workers too.\n\n"
         "The grid connection of the plants shapes where the jobs go, and local workers gain most.\n")


@pytest.fixture
def project(tmp_path) -> tuple[Workspace, str, list[str]]:
    """Three evidence documents and the researcher's draft (not marked yet): (ws, the draft's id, the evidence's ids)."""
    ws = Workspace.create(tmp_path / "proj")
    d = tmp_path / "docs"
    d.mkdir()
    for key in ("desalination", "jobs", "grid"):
        (d / f"{key}.txt").write_text(TEXTS[key], encoding="utf-8")
    (d / "draft.txt").write_text(DRAFT, encoding="utf-8")
    ingest.ingest(ws, [d])
    ids = {r[1]: r[0] for r in ws.query("SELECT doc_id, title FROM documents")}
    draft = next(i for t, i in ids.items() if t.startswith("My chapter"))
    yield ws, draft, sorted(i for i in ids.values() if i != draft)
    ws.close_all()


def test_marking_a_working_document_is_one_role_of_three(project):
    ws, draft, ev = project
    out = docrole.set_role(ws, draft, "working", why="my own chapter")
    assert out["changed"] and docrole.role_of(ws, draft) == "working"
    assert docrole.working_docs(ws._conn()) == {draft} and not docrole.theory_docs(ws._conn())
    assert docrole.not_evidence_docs(ws._conn()) == {draft}
    log = ws.query("SELECT text, why FROM research_log WHERE subject_id=? AND kind='document-role'", (draft,))
    assert [r[1] for r in log] == ["my own chapter"] and "working document" in log[0][0]
    # one role at a time: theory replaces it, and both are never a source
    docrole.set_role(ws, draft, "theory")
    assert docrole.role_of(ws, draft) == "theory" and not docrole.working_docs(ws._conn())
    assert ws.scalar("SELECT COUNT(*) FROM block_choices WHERE doc_id=? AND fp LIKE 'role:%'", (draft,)) == 1
    docrole.set_role(ws, ev[0], "working")
    assert docrole.not_evidence_docs(ws._conn()) == {draft, ev[0]}
    docrole.set_role(ws, draft, None)
    assert docrole.not_evidence_docs(ws._conn()) == {ev[0]}


def test_a_working_document_is_left_out_of_themes_and_key_terms(project):
    ws, draft, ev = project
    docrole.set_role(ws, draft, "working")
    got, _ = themes._passages(ws)
    assert {p["doc_id"] for p in got} == set(ev)
    assert set(terms._body_docs(ws)) == set(ev)


def test_a_check_never_reads_a_working_document_but_search_finds_it(project):
    ws, draft, ev = project
    claim = "Electrolyser plants create local jobs"
    words = ["jobs", "workers", "electrolyser"]
    assert draft in {p["doc_id"] for p in search.rank_passages(ws, claim, words, k=12, per_doc=4)}   # (unmarked)
    docrole.set_role(ws, draft, "working")
    found = search.rank_passages(ws, claim, words, k=12, per_doc=4)
    assert found and draft not in {p["doc_id"] for p in found}
    assert draft not in search.docs_matching(ws, claim, words, {draft, *ev})
    # named by hand, it is read (as a theory document is)
    only = search.rank_passages(ws, claim, words, k=4, per_doc=4, doc_ids=[draft])
    assert {p["doc_id"] for p in only} == {draft}
    # the Search page still finds it
    assert draft in {p["doc_id"] for p in search.rank_passages(ws, claim, words, k=12, per_doc=4,
                                                                 evidence_only=False)}


def test_a_working_document_is_labelled_but_its_codes_are_never_the_corpus(project):
    ws, draft, ev = project
    profile.keyword_pass(ws, "sdg")
    whole = profile.grid(ws, "sdg")
    stats_whole = profile.stats(ws, "sdg")
    assert draft in {d["doc_id"] for d in whole["documents"]}, "the draft needs a keyword code for this test"
    docrole.set_role(ws, draft, "working")
    profile.keyword_pass(ws, "sdg")                    # labelled again, with the role
    assert ws.scalar("SELECT COUNT(*) FROM labels WHERE doc_id=?", (draft,)) > 0
    plan = profile.label_plan(ws, "sdg", all_passages=True)
    assert plan["passages"] == ws.scalar("SELECT COUNT(*) FROM passages WHERE section='body'")   # all, the draft too
    g = profile.grid(ws, "sdg")
    rows = g["documents"]
    assert rows[-1]["doc_id"] == draft and rows[-1]["working"] is True              # its own row, last
    assert not any(r.get("working") for r in rows[:-1])
    corpus = [r["doc_id"] for r in rows[:-1]]
    for c in g["codes"]:                                # the totals are the corpus's alone
        assert c["passages"] == sum(g["cells"].get(d, {}).get(c["code"], 0) for d in corpus)
        assert c["documents"] == sum(1 for d in corpus if g["cells"].get(d, {}).get(c["code"]))
    st = profile.stats(ws, "sdg")
    assert st["documents"] == stats_whole["documents"] - 1 and st["labels"] < stats_whole["labels"]
    # its own page shows its codes
    assert profile.doc_profile(ws, "sdg", draft)["codes"]


def test_a_codes_examples_never_come_from_a_working_document(project):
    ws, draft, ev = project
    docrole.set_role(ws, draft, "working")
    kept = theorycodes.keep_evidence_examples(ws, [{"code": "jobs", "examples": [
        {"quote": "mine", "doc_id": draft}, {"quote": "theirs", "doc_id": ev[0]}]}])
    assert [e["doc_id"] for e in kept[0]["examples"]] == [ev[0]]
    assert all(e["doc_id"] != draft for e in theorycodes.suggest_examples(ws, "jobs"))


def test_the_proposal_and_the_log_say_working_document():
    from enlens_claims import ownership

    assert ownership.what({"kind": "blocks", "title": "Draft", "detail": {"role": "working"}}) == \
        "marking “Draft” as a working document (never a source)"


# ---- the routes ---------------------------------------------------------------------------------------------------
def test_the_routes(api, tmp_path):  # noqa: F811
    d = tmp_path / "in"
    d.mkdir()
    (d / "draft.txt").write_text(DRAFT, encoding="utf-8")
    assert api("POST", "/api/projects", {"name": "Mine"})[0] == 200
    from enlens_claims import home

    ws = Workspace.open(home.project_path("Mine"))
    try:
        ingest.ingest(ws, [d])
        draft = ws.scalar("SELECT doc_id FROM documents")
    finally:
        ws.close_all()
    st, body = api("PUT", f"/api/projects/Mine/documents/{draft}/role", {"role": "working"})
    assert st == 200 and body["role"] == "working" and body["changed"]
    assert api("GET", "/api/projects/Mine/document-roles")[1] == {"roles": {draft: "working"}, "nonscientific": []}
    assert api("GET", f"/api/projects/Mine/documents/{draft}/role")[1]["role"] == "working"
    assert api("PUT", f"/api/projects/Mine/documents/{draft}/role", {"role": "draft"})[0] == 400


from test_app import api, home  # noqa: E402,F401  (fixtures)
