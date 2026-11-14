"""Roadmap D1: the concept map. Concepts mentioned together more often than by chance (PMI over the passages in scope,
not raw counts), grouped and laid out the same way every time, with the links a person accepted in their type;
theory and working documents left out; documents, a theme, a code and years narrow the passages counted."""
from __future__ import annotations

import json
import math

import pytest

from enlens_claims import bibliography, conceptmap, docrole, ingest, profile, terms
from enlens_claims.conceptmap import Filters
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
    assert t, label
    return t


def _doc(ws, title: str) -> str:
    return ws.scalar("SELECT doc_id FROM documents WHERE title=?", (title,))


def _labels(m: dict) -> set[str]:
    return {n["label"].lower() for n in m["nodes"]}


def _edge(m: dict, a: str, b: str) -> dict | None:
    return next((e for e in m["edges"] if {e["a"], e["b"]} == {a, b}), None)


def test_no_glossary_says_so(tmp_path):
    w = Workspace.create(tmp_path / "empty")
    try:
        m = conceptmap.concept_map(w)
        assert m["built"] is False and m["nodes"] == [] and m["edges"] == []
        assert "No glossary yet" in conceptmap.as_text(m)
    finally:
        w.close_all()


def test_concepts_mentioned_together_are_joined_by_pmi_not_by_count(ws):
    m = conceptmap.concept_map(ws, n=150)
    assert m["built"] and m["passages"] > 0 and m["nodes"]
    sp, gs, bp = _t(ws, "solar panels"), _t(ws, "grid storage"), _t(ws, "battery prices")
    ids = {n["id"] for n in m["nodes"]}
    assert {sp, gs, bp} <= ids
    assert _edge(m, sp, bp) is None                         # never in one passage
    # (solar panels and grid storage are joined, but the map keeps only each concept's strongest lines)
    assert conceptmap.edge(ws, sp, gs)["pmi"] > 0 and conceptmap.edge(ws, sp, bp)["together"] == 0
    assert any(sp in (e["a"], e["b"]) for e in m["edges"]) and any(bp in (e["a"], e["b"]) for e in m["edges"])
    by_id = {n["id"]: n for n in m["nodes"]}
    for e in m["edges"]:                                    # each weight is PMI over the passages in scope
        expect = math.log2(e["together"] * m["passages"] / (by_id[e["a"]]["passages"] * by_id[e["b"]]["passages"]))
        assert e["pmi"] == round(expect, 2) and e["pmi"] > 0 and e["together"] >= conceptmap.MIN_TOGETHER
    pmis = [e["pmi"] for e in m["edges"]]
    assert pmis == sorted(pmis, reverse=True)               # strongest first, by PMI
    # a pair mentioned together more often can still weigh less: the weight is not the count
    assert any(x["together"] > y["together"] and x["pmi"] < y["pmi"] for x in m["edges"] for y in m["edges"])
    # nodes: most passages first, at least two each
    ps = [n["passages"] for n in m["nodes"]]
    assert ps == sorted(ps, reverse=True) and min(ps) >= 2
    assert all(0 <= n["x"] <= 1 and 0 <= n["y"] <= 1 for n in m["nodes"])
    # the cap on lines never leaves a joined concept without one (the most frequent have the weakest PMI): a concept
    # in a group has a join, so its strongest line is drawn
    drawn = {i for e in m["edges"] for i in (e["a"], e["b"])}
    assert {n["id"] for n in m["nodes"] if n["group"]} <= drawn
    small = conceptmap.concept_map(ws, n=60)
    assert {n["id"] for n in small["nodes"] if n["group"]} <= {i for e in small["edges"] for i in (e["a"], e["b"])}


def test_the_number_of_concepts_is_kept_and_bounded(ws):
    m = conceptmap.concept_map(ws, n=10)
    assert len(m["nodes"]) == 10 and m["concepts_in_scope"] > 10
    assert len(m["edges"]) <= max(conceptmap.EDGES_PER_NODE * 10, 10)
    assert conceptmap.concept_map(ws, n=5)["n"] == conceptmap.MIN_N
    assert conceptmap.concept_map(ws, n=10_000)["n"] == conceptmap.MAX_N


def test_the_same_project_gives_the_same_map(ws):
    a = conceptmap.concept_map(ws, n=60)
    b = conceptmap.concept_map(ws, n=60)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    # groups: the solar concepts and the battery concepts fall apart, and the council's words in a group of their own
    sp, gs, bp = _t(ws, "solar panels"), _t(ws, "battery prices"), _t(ws, "council")
    g = {n["id"]: n["group"] for n in a["nodes"]}
    assert g[sp] and g[gs] and g[bp]
    assert g[sp] != g[bp] and g[bp] != g[gs] and g[sp] != g[gs]
    assert [x["group"] for x in a["groups"]] == list(range(1, len(a["groups"]) + 1))
    sizes = [x["size"] for x in a["groups"]]
    assert sizes == sorted(sizes, reverse=True) and all(s > 1 for s in sizes)


def test_the_grouping_and_the_layout_alone_are_deterministic():
    edges = {(0, 1): 1.0, (1, 2): 1.0, (0, 2): 1.0, (3, 4): 1.0, (4, 5): 1.0, (3, 5): 1.0, (2, 3): 0.1}
    g1 = conceptmap._louvain(7, edges)
    assert g1 == conceptmap._louvain(7, dict(reversed(list(edges.items()))))
    assert g1[0] == g1[1] == g1[2] and g1[3] == g1[4] == g1[5] and g1[0] != g1[3] and g1[6] not in (g1[0], g1[3])
    groups = [1, 1, 1, 2, 2, 2, None]
    assert conceptmap._layout(7, groups, edges) == conceptmap._layout(7, groups, edges)


def test_accepted_links_carry_their_relation(ws):
    sp, bp, gs = _t(ws, "solar panels"), _t(ws, "battery prices"), _t(ws, "grid storage")
    terms.set_link(ws, sp, gs, "add", "narrower")
    terms.set_link(ws, sp, bp, "add", "different")         # "different" is no link to draw
    m = conceptmap.concept_map(ws, n=150)
    rels = {(lk["a"], lk["b"]): lk for lk in m["links"]}
    lk = rels.get((sp, gs)) or rels.get((gs, sp))
    assert lk and lk["source"] == "person"
    assert (lk["a"], lk["relation"]) in ((sp, "narrower"), (gs, "broader"))
    assert not any({x["a"], x["b"]} == {sp, bp} for x in m["links"])
    e = conceptmap.edge(ws, sp, gs)
    assert e["link"]["relation"] == "narrower" and e["together"] >= 2 and e["pmi"] > 0
    for p in e["passages"]:
        assert "solar panels" in p["text"].lower() and "grid storage" in p["text"].lower()
    # seen from the other end, the relation turns round
    assert conceptmap.edge(ws, gs, sp)["link"]["relation"] == "broader"


def test_a_link_to_a_concept_off_the_map_is_counted(ws):
    sp, bp = _t(ws, "solar panels"), _t(ws, "battery prices")
    terms.set_link(ws, sp, bp, "add", "related")
    m = conceptmap.concept_map(ws, Filters(docs=[_doc(ws, "Solar report"), _doc(ws, "Solar survey")]), n=150)
    assert sp in {n["id"] for n in m["nodes"]} and bp not in {n["id"] for n in m["nodes"]}
    assert m["links_off_map"] == 1 and m["links"] == []


@pytest.mark.parametrize("role", ["theory", "working"])
def test_theory_and_working_documents_are_left_out(ws, role):
    before = conceptmap.concept_map(ws, n=150)
    for t in ("Solar report", "Solar survey"):
        docrole.set_role(ws, _doc(ws, t), role)
    after = conceptmap.concept_map(ws, n=150)
    assert "solar panels" in _labels(before) and "solar panels" not in _labels(after)
    assert after["passages"] < before["passages"]
    assert _doc(ws, "Solar report") not in {d["doc_id"] for d in conceptmap.options(ws)["documents"]}


def test_a_document_filter_narrows_and_pmi_is_counted_within_it(ws):
    whole = conceptmap.concept_map(ws, n=150)
    f = Filters(docs=[_doc(ws, "Storage review"), _doc(ws, "Storage outlook")])
    m = conceptmap.concept_map(ws, f, n=150)
    assert m["passages"] < whole["passages"]
    assert "battery prices" in _labels(m) and "solar panels" not in _labels(m)
    by_id = {n["id"]: n for n in m["nodes"]}
    for e in m["edges"]:
        assert e["pmi"] == round(math.log2(e["together"] * m["passages"] / (by_id[e["a"]]["passages"] * by_id[e["b"]]["passages"])), 2)
    assert conceptmap.concept_map(ws, Filters(docs=["nope"]))["nodes"] == []


def test_a_year_filter_uses_the_bibliography(ws, monkeypatch):
    solar, solar2 = _doc(ws, "Solar report"), _doc(ws, "Solar survey")
    storage, storage2 = _doc(ws, "Storage review"), _doc(ws, "Storage outlook")
    monkeypatch.setattr(bibliography, "doc_citations", lambda w: {
        solar: {"year": "2019"}, solar2: {"year": "2019"}, storage: {"year": "2023"}, storage2: {"year": "2023"}})
    early = conceptmap.concept_map(ws, Filters(year_to=2020), n=150)
    late = conceptmap.concept_map(ws, Filters(year_from=2021, year_to=2024), n=150)
    assert "solar panels" in _labels(early) and "battery prices" not in _labels(early)
    assert "battery prices" in _labels(late) and "solar panels" not in _labels(late)
    whole = conceptmap.concept_map(ws, n=150)
    assert early["passages"] + late["passages"] < whole["passages"]   # the minutes have no year
    assert conceptmap.options(ws)["years"] == [2019, 2023]


def test_a_theme_filter_takes_its_passages_with_a_persons_merges(ws):
    solar = [r[0] for r in ws.query("SELECT passage_id FROM passages WHERE text LIKE '%solar panels%'")]
    storage = [r[0] for r in ws.query("SELECT passage_id FROM passages WHERE text LIKE '%battery prices%'")]
    with ws.connect() as cx:
        cx.execute("INSERT INTO theme_runs(run_id, mode, k, seed, created_at, passages, run_key, settings_json) "
                   "VALUES ('r1', 'words', 2, 0, '2026-11-14', 10, 'rk', '{}')")
        for tid, name, ps in ((1, "Solar", solar), (2, "Storage", storage)):
            cx.execute("INSERT INTO themes(run_id, theme_id, name, size) VALUES ('r1', ?, ?, ?)", (tid, name, len(ps)))
            cx.executemany("INSERT INTO theme_members(run_id, theme_id, passage_id, similarity) VALUES ('r1', ?, ?, 1.0)",
                           [(tid, p) for p in ps])
    m = conceptmap.concept_map(ws, Filters(theme=("r1", 1)), n=150)
    assert m["passages"] == len(solar)
    assert "solar panels" in _labels(m) and "battery prices" not in _labels(m)
    opts = conceptmap.options(ws)["themes"]
    assert opts["run_id"] == "r1" and [t["name"] for t in opts["themes"]] == ["Solar", "Storage"]
    from enlens_claims import themes

    themes.edit(ws, "r1", "merge", 2, 1)                     # Storage merged into Solar
    m2 = conceptmap.concept_map(ws, Filters(theme=("r1", 1)), n=150)
    assert m2["passages"] == len(solar) + len(storage) and "battery prices" in _labels(m2)
    assert [t["name"] for t in conceptmap.options(ws)["themes"]["themes"]] == ["Solar"]
    with pytest.raises(KeyError):
        conceptmap.concept_map(ws, Filters(theme=("gone", 1)))


def test_a_code_filter_takes_the_passages_labelled_with_it(ws):
    storage = [r[0] for r in ws.query("SELECT passage_id FROM passages WHERE text LIKE '%battery prices%'")]
    for p in storage:
        profile.add_label(ws, "sdg", p, "7.2")
    m = conceptmap.concept_map(ws, Filters(code=("sdg", "7.2")), n=150)
    assert m["passages"] == len(storage)
    assert "battery prices" in _labels(m) and "solar panels" not in _labels(m)
    cb = {c["name"]: c for c in conceptmap.options(ws)["codebooks"]}
    assert [c["code"] for c in cb["sdg"]["codes"]] == ["7.2"]
    # filters combine: the code's passages within documents that have none of them
    assert conceptmap.concept_map(ws, Filters(code=("sdg", "7.2"), docs=[_doc(ws, "Solar report")]))["nodes"] == []


def test_a_concept_of_several_wordings_hands_out_term_ids(ws):
    """A "same" link joins two wordings into one node: the map's ids (nodes, edges, links) and the edge route's are term
    ids, so the concept's page (terms.card) and a click on its line both work (review: a concept id broke both)."""
    sp, gs, bp = _t(ws, "solar panels"), _t(ws, "grid storage"), _t(ws, "battery prices")
    terms.set_link(ws, gs, bp, "add", "same")
    cid = ws.scalar("SELECT concept_id FROM concept_terms WHERE term_id=?", (gs,))
    assert cid and cid == ws.scalar("SELECT concept_id FROM concept_terms WHERE term_id=?", (bp,))
    terms.set_link(ws, sp, gs, "add", "related")
    m = conceptmap.concept_map(ws, n=150)
    ids = [n["id"] for n in m["nodes"]]
    known = {r[0] for r in ws.query("SELECT term_id FROM terms")}
    assert set(ids) <= known and cid not in ids
    label = ws.scalar("SELECT label FROM concepts WHERE concept_id=?", (cid,))
    joined = next(n for n in m["nodes"] if n["id"] in (gs, bp))
    assert joined["label"] == label and sum(n["id"] in (gs, bp) for n in m["nodes"]) == 1
    assert terms.card(ws, joined["id"])["label"] == label
    for e in m["edges"] + m["links"]:
        assert e["a"] in ids and e["b"] in ids
    assert any(joined["id"] in (lk["a"], lk["b"]) for lk in m["links"])
    mine = [e for e in m["edges"] + m["links"] if joined["id"] in (e["a"], e["b"])]
    assert mine
    for e in mine:
        r = conceptmap.edge(ws, e["a"], e["b"])
        assert {r["a"]["node"], r["b"]["node"]} == {e["a"], e["b"]} and {r["a"]["node"], r["b"]["node"]} <= known
    # the joined node counts the passages of either wording once, and an older link with the concept's id still works
    both = {r[0] for r in ws.query("SELECT DISTINCT passage_id FROM term_mentions WHERE term_id IN (?,?)", (gs, bp))}
    assert joined["passages"] == len(both)
    assert conceptmap.edge(ws, cid, sp)["a"]["node"] == joined["id"]
    with pytest.raises(KeyError):
        conceptmap.edge(ws, "c-nope", sp)


def test_a_links_own_sentences_keep_to_evidence_documents_in_scope(ws):
    sp, gs = _t(ws, "solar panels"), _t(ws, "grid storage")
    a, b = sorted((sp, gs))
    solar, survey, storage = _doc(ws, "Solar report"), _doc(ws, "Solar survey"), _doc(ws, "Storage review")
    with ws.connect() as cx:
        cx.execute("INSERT INTO concept_links VALUES (?,?,?,?,?,?,?,?,?)",
                   (a, b, "related", "pattern", 0.5, None, None, None, "2026-11-14"))
        cx.executemany("INSERT INTO concept_link_sentences(a, b, passage_id, doc_id, page, start, end, quote) "
                       "VALUES (?,?,NULL,?,1,?,?,?)", [(a, b, d, k, k + 5, f"sentence {k}")
                                                       for k, d in enumerate((solar, survey, storage))])
    terms.set_link(ws, a, b, "accept")
    docs = lambda r: [x["doc_id"] for x in r["link"]["sentences"]]  # noqa: E731
    assert sorted(docs(conceptmap.edge(ws, sp, gs))) == sorted([solar, survey, storage])
    assert docs(conceptmap.edge(ws, sp, gs, Filters(docs=[solar]))) == [solar]
    docrole.set_role(ws, storage, "theory")
    assert storage not in docs(conceptmap.edge(ws, sp, gs))


def test_the_filters_are_said_back_and_counted_exactly(ws):
    from enlens_claims import cli

    f = Filters(docs=[_doc(ws, "Solar report")], year_from=2000)
    assert f.describe() == {"doc": [_doc(ws, "Solar report")], "year_from": 2000}
    assert Filters(theme=("r1", 2), code=("sdg", "7.2")).describe() == {"theme": "r1:2", "framework": "sdg", "code": "7.2"}
    assert Filters(year_to=0).any()
    m = conceptmap.concept_map(ws, n=150)
    # every concept mentioned in two passages or more, counted exactly
    n = ws.scalar("SELECT COUNT(*) FROM (SELECT term_id FROM term_mentions GROUP BY term_id "
                  "HAVING COUNT(DISTINCT passage_id) >= 2)")
    assert m["concepts_in_scope"] == n == len(m["nodes"])
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cli.main(["--ws", str(ws.root), "concept-map", "--json", "--doc", _doc(ws, "Solar report")]) == 0
    assert json.loads(buf.getvalue())["filters"] == {"doc": [_doc(ws, "Solar report")]}
    assert cli.main(["--ws", str(ws.root), "concept-map", "--year-from", "0"]) == 1


def test_no_query_binds_more_variables_than_sqlite_allows(ws, monkeypatch):
    """A filter of many documents or passages goes through temporary tables, never an IN (…) of its ids."""
    many = [_doc(ws, "Storage review"), _doc(ws, "Storage outlook")] + [f"nope{i:05}" for i in range(40_000)]
    m = conceptmap.concept_map(ws, Filters(docs=many), n=150)
    assert m["passages"] and "battery prices" in _labels(m)
    from enlens_claims import profile as prof

    every = {r[0] for r in ws.query("SELECT passage_id FROM passages")} | {f"p{i:05}" for i in range(40_000)}
    monkeypatch.setattr(prof, "passages_with_code", lambda w, fw, code: every)
    assert conceptmap.concept_map(ws, Filters(code=("sdg", "7.2")), n=150)["passages"] == \
        conceptmap.concept_map(ws, n=150)["passages"]
    bp, gs = _t(ws, "battery prices"), _t(ws, "grid storage")
    assert conceptmap.edge(ws, bp, gs, Filters(docs=many))["together"] >= 2
    # the temporary tables are gone afterwards
    assert not ws.query("SELECT name FROM sqlite_temp_master WHERE name LIKE 'd1_%'")


def test_the_command_line_says_it_in_words(ws):
    text = conceptmap.as_text(conceptmap.concept_map(ws, n=30))
    assert "concepts, from" in text and "Group 1" in text


def test_the_routes(api, tmp_path):  # noqa: F811
    from enlens_claims import home

    assert api("POST", "/api/projects", {"name": "Map"})[0] == 200
    ws = Workspace.open(home.project_path("Map"))
    try:
        st, m = api("GET", "/api/projects/Map/concept-map")
        assert st == 200 and m["built"] is False
        ingest.ingest(ws, [write(tmp_path / "docs")["solar"].parent])
        terms.build(ws)
        sp, gs = _t(ws, "solar panels"), _t(ws, "grid storage")
        doc = _doc(ws, "Solar report")
    finally:
        ws.close_all()
    st, m = api("GET", "/api/projects/Map/concept-map?n=30")
    assert st == 200 and m["built"] and len(m["nodes"]) == 30 and m["edges"]
    st, m2 = api("GET", f"/api/projects/Map/concept-map?doc={doc}&n=150")
    assert st == 200 and m2["passages"] < m["passages"] and m2["filters"] == {"doc": [doc]}
    st, e = api("GET", f"/api/projects/Map/concept-map/edge?a={sp}&b={gs}&doc={doc}")
    assert st == 200 and e["together"] >= 2 and e["passages"] and all(p["doc_id"] == doc for p in e["passages"])
    st, o = api("GET", "/api/projects/Map/concept-map/options")
    assert st == 200 and len(o["documents"]) == 5 and o["themes"]["themes"] == []
    assert api("GET", "/api/projects/Map/concept-map?theme=bad")[0] == 400
    assert api("GET", "/api/projects/Map/concept-map?theme=gone:1")[0] == 404
    assert api("GET", "/api/projects/Map/concept-map?code=7.2")[0] == 400
    assert api("GET", "/api/projects/Map/concept-map?year_from=19")[0] == 400
    assert api("GET", "/api/projects/Map/concept-map?year_from=0000")[0] == 400
    assert api("GET", "/api/projects/Map/concept-map/edge?a=x")[0] == 400
    assert api("GET", f"/api/projects/Map/concept-map/edge?a={sp}&b=nope")[0] == 404


from test_app import api, home  # noqa: E402,F401  (fixtures)
