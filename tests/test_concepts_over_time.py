"""0.18.1 (roadmap D4, Part A, A6): a concept's wordings and neighbours by publication year (from the bibliography;
documents without a year counted apart) and between two sets of documents picked on the page; theory left out."""
from __future__ import annotations

import pytest

from enlens_claims import bibliography, conceptpaths, docrole, ingest, terms
from enlens_claims.store import Workspace
from concept_corpus import write


@pytest.fixture
def ws(tmp_path):
    w = Workspace.create(tmp_path / "p")
    ingest.ingest(w, [write(tmp_path / "docs")["solar"].parent])
    terms.build(w)
    yield w
    w.close_all()


def _doc(ws, title: str) -> str:
    return ws.scalar("SELECT doc_id FROM documents WHERE title=?", (title,))


def test_by_year_with_the_documents_without_a_year_apart(ws, monkeypatch):
    solar, solar2 = _doc(ws, "Solar report"), _doc(ws, "Solar survey")
    storage, storage2 = _doc(ws, "Storage review"), _doc(ws, "Storage outlook")
    cite = bibliography.cite   # the citations as the bibliography makes them: "Lund (2019)" (review 4)
    monkeypatch.setattr(bibliography, "doc_citations", lambda w: {
        solar: {"cite": cite([{"last": "Lund"}], "2019")}, solar2: {"cite": cite([{"last": "Lund"}, {"last": "Berg"}], "2019")},
        storage: {"cite": cite([{"last": "Okafor"}, {"last": "Ito"}, {"last": "Abe"}], "2023"), "year": "2023"},
        storage2: {"cite": cite([{"last": "Ito"}], "2023")}})
    gs = terms.find_term(ws, "grid storage")
    out = conceptpaths.over_time(ws, gs)
    assert out["label"].lower() == "grid storage" and out["with_year"] == 4
    years = {y["year"]: y for y in out["years"]}
    assert set(years) == {"2019", "2023"}
    assert years["2019"]["documents"] == 2 and years["2023"]["documents"] == 2
    assert years["2019"]["wordings"][0]["label"].lower() == "grid storage"
    near19 = " | ".join(n["label"].lower() for n in years["2019"]["neighbours"])
    near23 = " | ".join(n["label"].lower() for n in years["2023"]["neighbours"])
    assert "solar" in near19 and "battery" not in near19, near19
    assert "battery" in near23 and "solar" not in near23, near23
    assert out["no_year"] and out["no_year"]["documents_in_group"] == 1 and out["no_year"]["mentions"] == 0


def test_two_sets_of_documents_picked_on_the_page(ws):
    solar, storage, filler = _doc(ws, "Solar report"), _doc(ws, "Storage review"), _doc(ws, "Council minutes")
    gs = terms.find_term(ws, "grid storage")
    out = conceptpaths.compare_groups(ws, gs, {"Policy": [solar, filler], "Industry": [storage, "nope"]})
    g = {x["name"]: x for x in out["groups"]}
    assert g["Policy"]["documents_in_group"] == 2 and g["Industry"]["documents_in_group"] == 1
    assert g["Policy"]["mentions"] > 0 and g["Industry"]["mentions"] > 0
    with pytest.raises(ValueError):
        conceptpaths.compare_groups(ws, gs, {})
    with pytest.raises(ValueError):          # two sets at least, as the API says
        conceptpaths.compare_groups(ws, gs, {"Only": [solar]})


def test_theory_documents_are_left_out(ws, monkeypatch):
    solar, storage = _doc(ws, "Solar report"), _doc(ws, "Storage review")
    docrole.set_role(ws, storage, "theory")
    monkeypatch.setattr(bibliography, "doc_citations", lambda w: {solar: {"year": "2019"}, storage: {"year": "2023"}})
    gs = terms.find_term(ws, "grid storage")
    out = conceptpaths.over_time(ws, gs)
    assert [y["year"] for y in out["years"]] == ["2019"]
    cmp = conceptpaths.compare_groups(ws, gs, {"A": [solar], "B": [storage]})
    b = next(x for x in cmp["groups"] if x["name"] == "B")
    assert b["documents_in_group"] == 0 and b["theory_left_out"] == 1 and b["mentions"] == 0


def test_the_routes(api, tmp_path):  # noqa: F811
    from enlens_claims import home

    assert api("POST", "/api/projects", {"name": "Time"})[0] == 200
    w = Workspace.open(home.project_path("Time"))
    try:
        ingest.ingest(w, [write(tmp_path / "docs")["solar"].parent])
        terms.build(w)
        gs = terms.find_term(w, "grid storage")
        docs = [r[0] for r in w.query("SELECT doc_id FROM documents ORDER BY title")]
    finally:
        w.close_all()
    st, body = api("GET", f"/api/projects/Time/concept-time/{gs}")
    assert st == 200 and body["no_year"]["documents_in_group"] == 5     # no bibliography: no years
    st, body = api("POST", f"/api/projects/Time/concept-groups/{gs}", {"groups": {"A": docs[:1], "B": docs[1:]}})
    assert st == 200 and len(body["groups"]) == 2
    assert api("POST", f"/api/projects/Time/concept-groups/{gs}", {"groups": "x"})[0] == 400
    assert api("GET", "/api/projects/Time/concept-time/tnope")[0] == 404


from test_app import api, home  # noqa: E402,F401  (fixtures)
