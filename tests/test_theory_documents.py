"""0.18.1 (roadmap K2 part 1, Part A, A3): a document marked as theory is the lens, not the evidence.

It is still read, searched, opened and noted; it is left out of themes, labelling with codebooks, the excerpts a check
reads, key terms and the glossary's counts. Marking changes no result by itself: the document's page lists what was
made with it in. The mark travels as a decision about the document, like *Leave out*: an Owner's holds at once, a
Member's is a proposal of medium severity."""
from __future__ import annotations

from pathlib import Path

import pytest

from enlens_claims import docrole, ingest, profile, search, terms, themes
from enlens_claims.store import Workspace
from owner_helpers import TEXTS

THEORY = ("Thinking in systems\n\n"
          "A stock is the memory of the history of changing flows within the system. A flow changes a stock over "
          "time, and a reinforcing feedback loop makes a stock grow faster the larger it already is.\n\n"
          "Electrolyser plants and local jobs are examples a systems thinker might use: a balancing loop keeps the "
          "number of workers near a goal, and a delay in hiring makes it overshoot.\n\n"
          "A leverage point is a place in a system where a small shift produces large changes in everything.\n")


@pytest.fixture
def project(tmp_path) -> tuple[Workspace, str, list[str]]:
    """Three evidence documents and one theory book (not marked yet): (ws, the theory's id, the evidence's ids)."""
    ws = Workspace.create(tmp_path / "proj")
    d = tmp_path / "docs"
    d.mkdir()
    for key in ("desalination", "jobs", "grid"):
        (d / f"{key}.txt").write_text(TEXTS[key], encoding="utf-8")
    (d / "meadows.txt").write_text(THEORY, encoding="utf-8")
    ingest.ingest(ws, [d])
    ids = {r[1]: r[0] for r in ws.query("SELECT doc_id, title FROM documents")}
    theory = next(i for t, i in ids.items() if t.startswith("Thinking"))
    yield ws, theory, sorted(i for i in ids.values() if i != theory)
    ws.close_all()


def _docs_of_passages(ws: Workspace, pids) -> set[str]:
    pids = list(pids)
    q = ",".join("?" * len(pids))
    return {r[0] for r in ws.query(f"SELECT DISTINCT doc_id FROM passages WHERE passage_id IN ({q})", pids)}


def test_marking_sets_the_role_and_unmarking_clears_it(project):
    ws, theory, _ev = project
    assert docrole.role_of(ws, theory) is None
    out = docrole.set_role(ws, theory, "theory", why="Meadows is our framework")
    assert out["changed"] and docrole.role_of(ws, theory) == "theory" and docrole.theory_docs(ws._conn()) == {theory}
    assert docrole.set_role(ws, theory, "theory")["changed"] is False            # (marked already: nothing new)
    log = ws.query("SELECT kind, why FROM research_log WHERE subject_id=? ORDER BY at, rowid", (theory,))
    assert [(r[0], r[1]) for r in log] == [("document-role", "Meadows is our framework")]
    docrole.set_role(ws, theory, None)
    assert docrole.role_of(ws, theory) is None and not docrole.theory_docs(ws._conn())
    assert not ws.scalar("SELECT COUNT(*) FROM block_choices WHERE doc_id=?", (theory,))
    with pytest.raises(ValueError):
        docrole.set_role(ws, theory, "framework")   # "framework" means a codebook: never a role
    with pytest.raises(KeyError):
        docrole.set_role(ws, "no-such-doc", "theory")


def test_a_theory_document_is_left_out_of_themes(project):
    ws, theory, ev = project
    before, _ = themes._passages(ws)
    assert theory in {p["doc_id"] for p in before}
    docrole.set_role(ws, theory, "theory")
    after, _ = themes._passages(ws)
    assert {p["doc_id"] for p in after} == set(ev)


def test_a_theory_document_is_never_labelled_with_a_codebook(project):
    ws, theory, ev = project
    docrole.set_role(ws, theory, "theory")
    profile.keyword_pass(ws, "sdg")
    assert not ws.scalar("SELECT COUNT(*) FROM labels WHERE doc_id=?", (theory,))
    assert ws.scalar("SELECT COUNT(*) FROM labels") > 0                          # the evidence was labelled
    plan = profile.label_plan(ws, "sdg", all_passages=True)
    assert plan["passage_ids"] and theory not in _docs_of_passages(ws, plan["passage_ids"])
    assert plan["passages"] == ws.scalar("SELECT COUNT(*) FROM passages WHERE section='body' AND doc_id != ?",
                                         (theory,))


def test_a_check_reads_no_excerpt_of_a_theory_document_but_search_still_finds_it(project):
    from enlens_claims import concordance

    ws, theory, ev = project
    claim = "Electrolyser plants create local jobs"
    found = search.rank_passages(ws, claim, ["jobs", "workers", "electrolyser"], k=10, per_doc=4)
    assert theory in {p["doc_id"] for p in found}                                 # (it would be read, unmarked)
    docrole.set_role(ws, theory, "theory")
    found = search.rank_passages(ws, claim, ["jobs", "workers", "electrolyser"], k=10, per_doc=4)
    assert found and theory not in {p["doc_id"] for p in found}
    # a person who limits a check to the theory by hand means it
    only = search.rank_passages(ws, claim, ["jobs", "workers"], k=4, per_doc=4, doc_ids=[theory])
    assert only and {p["doc_id"] for p in only} == {theory}
    # "Read the new documents" asks which new documents match the claim: never a theory document (review 2)
    assert search.docs_matching(ws, claim, ["jobs", "workers"], {theory, *ev}) == \
        search.docs_matching(ws, claim, ["jobs", "workers"], set(ev))
    assert theory not in search.docs_matching(ws, claim, ["jobs", "workers", "stock"], {theory})
    # the Search page's search by meaning still finds it
    got = concordance.meaning(ws, "reinforcing feedback loop stock", None, k=10)
    assert theory in {p["doc_id"] for p in got["passages"]}


def test_key_terms_and_the_glossary_count_no_theory(project):
    ws, theory, ev = project
    docrole.set_role(ws, theory, "theory")
    assert set(terms._body_docs(ws)) == set(ev)
    terms.build(ws)
    assert not ws.scalar("SELECT COUNT(*) FROM term_mentions m JOIN passages p ON p.passage_id=m.passage_id "
                         "WHERE p.doc_id=?", (theory,))
    words = " ".join(t["label"].lower() for t in terms.glossary(ws, limit=500)["items"])
    assert "leverage point" not in words and "stock" not in words.split()


def test_the_page_lists_what_was_made_with_it_in(project):
    from enlens_claims import claimcheck
    from enlens_claims.llm import BaselineBackend

    ws, theory, ev = project
    themes.run(ws, k=2, seed=0)
    profile.keyword_pass(ws, "sdg")
    hid = claimcheck.check_hypothesis(ws, "A reinforcing feedback loop makes a stock grow.", BaselineBackend(),
                                      "baseline", k=4)
    imp = docrole.set_role(ws, theory, "theory")["impact"]
    assert imp["themes"] and imp["themes"][0]["passages"] > 0
    assert any(c["hyp_id"] == hid for c in imp["checks"])
    assert all(set(x) >= {"framework", "name", "passages"} for x in imp["labels"])
    # marking changed none of them
    assert ws.scalar("SELECT COUNT(*) FROM theme_members m JOIN passages p ON p.passage_id=m.passage_id "
                     "WHERE p.doc_id=?", (theory,)) == imp["themes"][0]["passages"]


def test_the_mark_holds_when_the_document_is_read_with_the_new_reader(project):
    from enlens_claims import reread

    ws, theory, _ev = project
    was = ingest.READER
    with ws.connect() as cx:
        cx.execute("UPDATE documents SET reader=1 WHERE doc_id=?", (theory,))
    docrole.set_role(ws, theory, "theory")
    c = reread.check(ws, theory)
    assert c["ok"], c                              # (the move must happen, or the test proves nothing: review 18)
    reread.move(ws, theory)
    assert ws.scalar("SELECT reader FROM documents WHERE doc_id=?", (theory,)) == was
    assert docrole.role_of(ws, theory) == "theory"


# ---- the routes ---------------------------------------------------------------------------------------------------
def test_the_routes(api, tmp_path):  # noqa: F811
    d = tmp_path / "in"
    d.mkdir()
    (d / "meadows.txt").write_text(THEORY, encoding="utf-8")
    (d / "jobs.txt").write_text(TEXTS["jobs"], encoding="utf-8")
    assert api("POST", "/api/projects", {"name": "Lens"})[0] == 200
    from enlens_claims import home

    ws = Workspace.open(home.project_path("Lens"))
    try:
        ingest.ingest(ws, [d])
        theory = ws.scalar("SELECT doc_id FROM documents WHERE title LIKE 'Thinking%'")
    finally:
        ws.close_all()
    st, body = api("GET", f"/api/projects/Lens/documents/{theory}/role")
    assert st == 200 and body["role"] is None and set(body["impact"]) == {"themes", "labels", "checks"}
    st, body = api("PUT", f"/api/projects/Lens/documents/{theory}/role", {"role": "theory", "why": "our lens"})
    assert st == 200 and body["role"] == "theory" and body["changed"]
    assert api("GET", "/api/projects/Lens/document-roles")[1] == {"roles": {theory: "theory"}, "nonscientific": []}
    assert api("PUT", f"/api/projects/Lens/documents/{theory}/role", {"role": "framework"})[0] == 400
    assert api("PUT", "/api/projects/Lens/documents/nope/role", {"role": "theory"})[0] == 404
    st, body = api("PUT", f"/api/projects/Lens/documents/{theory}/role", {"role": None})
    assert st == 200 and body["role"] is None
    assert api("GET", "/api/projects/Lens/document-roles")[1] == {"roles": {}, "nonscientific": []}


# ---- between copies: a decision about the document, like Leave out -------------------------------------------------
def test_an_owners_mark_holds_at_once_and_a_members_is_a_proposal(anna_and_ben, tmp_path):  # noqa: F811
    from enlens_claims import ownership
    from enlens_claims.sync import folder
    from owner_helpers import accept, add_doc, proposals, sync, view

    shared = tmp_path / "shared"
    shared.mkdir()
    anna, ben = anna_and_ben
    for p in (anna, ben):
        with p:
            folder.set_folder(p.ws, str(shared))
    sync(anna, ben)
    book = add_doc(anna, tmp_path, "meadows", text=THEORY)
    other = add_doc(anna, tmp_path, "interview")
    sync(anna, ben)
    with anna:                                       # the owner marks the book: the project's at once
        docrole.set_role(anna.ws, book, "theory")
    view(anna)
    sync(anna, ben, rounds=2)
    with ben:
        assert docrole.role_of(ben.ws, book) == "theory"
    with ben:                                        # Ben, a Member, marks the interview: a proposal
        docrole.set_role(ben.ws, other, "theory")
    props = proposals(ben, state="waiting", kind="blocks")
    assert [(p["doc"], p["severity"]) for p in props] == [(other, "medium")]
    assert "as theory" in props[0]["what"] and props[0]["detail"]["role"] == "theory"
    sync(ben, anna, rounds=2)
    with anna:
        assert docrole.role_of(anna.ws, other) is None   # not the project's until she accepts
        assert ownership.owner(anna.ws._conn()) == anna.id
    accept(anna, proposals(anna, state="waiting", kind="blocks")[0]["id"])
    with anna:
        assert docrole.role_of(anna.ws, other) == "theory"
    sync(anna, ben, rounds=2)
    with ben:
        assert docrole.role_of(ben.ws, other) == "theory"
    with anna:                                       # the owner unmarks it: evidence again in every copy
        docrole.set_role(anna.ws, book, None)
    view(anna)
    sync(anna, ben, rounds=2)
    with ben:
        assert docrole.role_of(ben.ws, book) is None


from test_shared_projects import anna_and_ben  # noqa: E402,F401  (fixture)
from test_app import api, home  # noqa: E402,F401  (fixtures)
