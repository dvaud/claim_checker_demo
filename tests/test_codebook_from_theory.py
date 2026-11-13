"""0.18.1 (roadmap K2 part 2, Part A, A4): a codebook from a theory document, Level 0 (no model).

The candidate concepts come from the theory's own structure and words (terms it defines, its headings, its frequent
phrases), each with a definition quoted from it with its page; examples come only from the evidence documents and are
kept only when ticked; the result is an ordinary codebook."""
from __future__ import annotations

import pytest

from enlens_claims import codebooks, docrole, ingest, pdfmake, theorycodes
from enlens_claims.store import Workspace

THEORY_PAGES = [
    ["1. Stocks and flows",
     "A stock is the memory of the history of changing flows within the system. Stocks change only through flows.",
     "A flow is the rate at which a stock is filled or drained. Flows can be seen as actions or decisions."],
    ["2. Feedback",
     "By a reinforcing loop we mean a loop that amplifies whatever happens in it. A reinforcing loop can make "
     "a stock grow faster the larger it already is.",
     "A balancing loop is defined as a loop that keeps a stock near a goal. A delay in a balancing loop makes a "
     "system overshoot. The delay matters, and every delay in a balancing loop is worth looking for."],
    ["3. Leverage points",
     "Leverage points refer to places in a system where a small shift produces large changes in everything. "
     "Leverage points are seldom where people look for them. A delay hides the effect of a shift for a while."],
]
EVIDENCE = ("Staff interviews in the care home\n\n"
            "The staff said that when a resident failed at the game once, they switched it on less, and so the "
            "resident grew less sure of it: a reinforcing loop nobody had planned.\n\n"
            "A delay between ordering the table and its delivery meant that the team lost interest before it "
            "arrived. Managers kept a balancing loop going by asking each week how often it was used.\n")


def _theory_pdf(path) -> None:
    """The theory as a PDF of three pages: a bold heading on each, then its paragraphs (pdfmake)."""
    pages = []
    for n, (head, *paras) in enumerate(THEORY_PAGES):
        pg = pdfmake.Page()
        y = 770
        if n == 0:
            pg.text("Thinking in systems", 72, y, "Helvetica-Bold", 18)
            y -= 36
        pg.text(head, 72, y, "Helvetica-Bold", 13)
        y -= 26
        for para in paras:
            for line in pdfmake.wrap(para, 451, "Times-Roman", 11):
                pg.text(line, 72, y, "Times-Roman", 11)
                y -= 14
            y -= 10
        pages.append(pg)
    pdfmake.write(pages, path, title="Thinking in systems")


@pytest.fixture
def project(tmp_path):
    ws = Workspace.create(tmp_path / "proj")
    d = tmp_path / "docs"
    d.mkdir()
    _theory_pdf(d / "meadows.pdf")
    (d / "carehome.txt").write_text(EVIDENCE, encoding="utf-8")
    ingest.ingest(ws, [d])
    theory = ws.scalar("SELECT doc_id FROM documents WHERE text LIKE '%memory of the history%'")
    evidence = ws.scalar("SELECT doc_id FROM documents WHERE doc_id != ?", (theory,))
    docrole.set_role(ws, theory, "theory")
    yield ws, theory, evidence
    ws.close_all()


def _by_term(cands: dict) -> dict[str, dict]:
    return {c["term"].lower(): c for c in cands["concepts"]}


def test_defined_terms_come_first_with_their_definition_quoted_from_the_theory(project):
    ws, theory, _ev = project
    cands = theorycodes.candidates(ws, theory)
    got = _by_term(cands)
    for term in ("stock", "flow", "reinforcing loop", "balancing loop", "leverage points"):
        assert term in got, (term, sorted(got))
        assert got[term]["how"] == "defined", (term, got[term]["how"])
    text = ws.scalar("SELECT text FROM documents WHERE doc_id=?", (theory,))
    for term in ("stock", "balancing loop", "reinforcing loop"):
        d = got[term]["definition"]
        assert d and " ".join(text[d["start"]:d["end"]].split()) == d["quote"]    # quote-checked: the document's words
        assert d["quote"] in got[term]["code"]["description"]
        assert "Thinking in systems" in got[term]["code"]["description"]
    defined = [c["how"] for c in cands["concepts"]]
    assert defined[:5] == ["defined"] * 5                                         # best first


def test_a_definition_carries_its_page(project):
    ws, theory, _ev = project
    if ws.scalar("SELECT kind FROM documents WHERE doc_id=?", (theory,)) != "pdf":
        pytest.skip("the theory was written as text: it has no pages")
    got = _by_term(theorycodes.candidates(ws, theory))
    assert got["stock"]["definition"]["page"] == 1
    assert got["balancing loop"]["definition"]["page"] == 2
    assert ", p. 2)" in got["balancing loop"]["code"]["description"]


def test_headings_and_frequent_phrases_are_offered_too(project):
    ws, theory, _ev = project
    got = _by_term(theorycodes.candidates(ws, theory))
    hows = {c["how"] for c in got.values()}
    assert "delay" in got                       # frequent (in three sentences), never defined
    assert hows <= {"defined", "heading", "frequent"}
    assert not any(t in got for t in ("the", "is", "a stock is"))


def test_examples_are_offered_only_from_the_evidence_and_start_unticked(project):
    ws, theory, ev = project
    got = _by_term(theorycodes.candidates(ws, theory))
    sug = got["reinforcing loop"]["suggested"]
    assert sug and {e["doc_id"] for e in sug} == {ev}
    assert all("reinforcing loop" in e["quote"].lower() for e in sug)
    assert all(not c["code"]["examples"] for c in got.values())                 # none kept until ticked


def test_the_ticked_concepts_become_an_ordinary_codebook_without_theory_examples(project):
    ws, theory, ev = project
    got = _by_term(theorycodes.candidates(ws, theory))
    keep = []
    for term in ("reinforcing loop", "balancing loop", "delay"):
        c = dict(got[term]["code"])
        c["examples"] = list(got[term]["suggested"][:1])
        keep.append(c)
    # an example from the theory, smuggled in, is dropped
    keep[2]["examples"].append({"quote": "The delay matters", "doc_id": theory, "title": "Thinking in systems",
                                "page": 2, "start": 0, "end": 17})
    cb = codebooks.create(ws, "systems", "Systems codes", start="theory", source={"codes": keep, "doc_id": theory})
    codes = {c["code"]: c for c in cb["codes"]}
    assert set(codes) == {"Reinforcing loop", "Balancing loop", "Delay"}
    assert all(e["doc_id"] == ev for c in codes.values() for e in c["examples"])
    assert "Thinking in systems" in codes["Balancing loop"]["description"]
    log = ws.query("SELECT text FROM research_log WHERE kind='codebook-added'")
    assert log and "3 concepts of the theory document" in log[0][0]
    with pytest.raises(ValueError):
        codebooks.create(ws, "empty", "Nothing", start="theory", source={"codes": [], "doc_id": theory})


def test_the_routes(api, tmp_path):  # noqa: F811
    from enlens_claims import home

    assert api("POST", "/api/projects", {"name": "Lens"})[0] == 200
    d = tmp_path / "in"
    d.mkdir()
    (d / "meadows.txt").write_text("Thinking in systems\n\n" + "\n\n".join("\n\n".join(p) for p in THEORY_PAGES),
                                   encoding="utf-8")
    (d / "carehome.txt").write_text(EVIDENCE, encoding="utf-8")
    ws = Workspace.open(home.project_path("Lens"))
    try:
        ingest.ingest(ws, [d])
        theory = ws.scalar("SELECT doc_id FROM documents WHERE text LIKE '%memory of the history%'")
        docrole.set_role(ws, theory, "theory")
    finally:
        ws.close_all()
    st, body = api("GET", "/api/projects/Lens/codebook-theory")
    assert st == 200 and body["documents"][0] == {"doc_id": theory, "title": body["documents"][0]["title"], "theory": True}
    st, body = api("GET", f"/api/projects/Lens/codebook-theory/{theory}")
    assert st == 200 and body["concepts"] and body["role"] == "theory"
    assert api("GET", "/api/projects/Lens/codebook-theory/nope")[0] == 404


from test_app import api, home  # noqa: E402,F401  (fixtures)
