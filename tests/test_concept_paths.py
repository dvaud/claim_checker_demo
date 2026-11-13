"""0.18.1 (roadmap D3, Part A, A6): paths between two concepts, through accepted links and co-occurrence weighted by
PMI, each step with its bridge passages; theory documents left out."""
from __future__ import annotations

import pytest

from enlens_claims import conceptpaths, docrole, ingest, terms
from enlens_claims.store import Workspace
from concept_corpus import write


@pytest.fixture
def ws(tmp_path):
    w = Workspace.create(tmp_path / "p")
    ingest.ingest(w, [write(tmp_path / "docs")["solar"].parent])
    terms.build(w)
    yield w
    w.close_all()


def _t(ws, label: str) -> str:
    t = terms.find_term(ws, label)
    assert t, (label, [r[0] for r in ws.query("SELECT label FROM terms ORDER BY tf DESC LIMIT 30")])
    return t


def _labels(path: dict) -> list[str]:
    return [path["steps"][0]["from"]["label"].lower()] + [s["to"]["label"].lower() for s in path["steps"]]


def test_the_path_runs_through_the_concept_both_share(ws):
    sp, bp = _t(ws, "solar panels"), _t(ws, "battery prices")
    out = conceptpaths.paths(ws, sp, bp)
    assert out["paths"], out
    best = out["paths"][0]
    labels = _labels(best)
    assert labels[0] == "solar panels" and labels[-1] == "battery prices" and len(labels) == 3
    assert "storage" in labels[1]                       # (the glossary keeps "storage" and "grid storage" apart)
    for st in best["steps"]:
        assert st["kind"] == "together" and st["pmi"] > 0
        assert st["bridges"], st                         # the passages that join the two
        for b in st["bridges"]:
            assert st["from"]["label"].lower() in b["text"].lower() and st["to"]["label"].lower() in b["text"].lower()
    costs = [p["cost"] for p in out["paths"]]
    assert costs == sorted(costs)


def test_an_accepted_link_is_a_short_step(ws):
    sp, bp = _t(ws, "solar panels"), _t(ws, "battery prices")
    terms.set_link(ws, sp, bp, "add", "related")
    best = conceptpaths.paths(ws, sp, bp)["paths"][0]
    assert len(best["steps"]) == 1 and best["steps"][0]["kind"] == "link"
    assert best["steps"][0]["relation"] == "related" and best["steps"][0]["bridges"] == []


def test_a_rejected_or_different_link_is_no_step(ws):
    sp, bp = _t(ws, "solar panels"), _t(ws, "battery prices")
    terms.set_link(ws, sp, bp, "add", "different")
    best = conceptpaths.paths(ws, sp, bp)["paths"][0]
    assert len(best["steps"]) == 2


def test_theory_documents_are_left_out(ws):
    sp, bp = _t(ws, "solar panels"), _t(ws, "battery prices")
    for (storage,) in ws.query("SELECT doc_id FROM documents WHERE title LIKE 'Storage%'"):
        docrole.set_role(ws, storage, "theory")         # the only bridges to battery prices are in them
    assert conceptpaths.paths(ws, sp, bp)["paths"] == []


def test_unknown_terms_and_the_same_concept(ws):
    sp = _t(ws, "solar panels")
    with pytest.raises(KeyError):
        conceptpaths.paths(ws, sp, "t-nope")
    assert conceptpaths.paths(ws, sp, sp)["paths"] == []


def test_the_route(api, tmp_path):  # noqa: F811
    from enlens_claims import home

    assert api("POST", "/api/projects", {"name": "Paths"})[0] == 200
    w = Workspace.open(home.project_path("Paths"))
    try:
        ingest.ingest(w, [write(tmp_path / "docs")["solar"].parent])
        terms.build(w)
        sp, bp = terms.find_term(w, "solar panels"), terms.find_term(w, "battery prices")
    finally:
        w.close_all()
    st, body = api("GET", f"/api/projects/Paths/concept-paths?from={sp}&to={bp}")
    assert st == 200 and body["paths"] and len(body["paths"][0]["steps"]) == 2
    assert api("GET", "/api/projects/Paths/concept-paths?from=" + sp)[0] == 400
    assert api("GET", f"/api/projects/Paths/concept-paths?from={sp}&to=tnope")[0] == 404


from test_app import api, home  # noqa: E402,F401  (fixtures)
