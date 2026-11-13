"""0.18.1 (roadmap D2, Part A, A5): relations found from the text, without AI, only between terms the glossary knows.

"X such as Y" and "Y and other X" (broader and narrower), "X, also called Y" / "X (also known as Y)" (the same), "X
leads to / causes / reduces Y" (an effect), "X instead of Y" (replaces). Each proposal carries its sentences and is
accepted or rejected as other links are."""
from __future__ import annotations

import re

import pytest

from enlens_claims import ingest, terms, textrelations
from enlens_claims.store import Workspace

TERMS = ("renewable energy", "solar power", "wind power", "hydropower", "heat pumps", "heating systems",
         "carbon tax", "emissions", "remote work", "telework", "commuting", "gas boilers", "energy poverty")


def pairs(sentence: str) -> set[tuple[str, str, str]]:
    """The relations `_pairs` finds in a sentence whose known terms are TERMS (each mention found by its words)."""
    ms = []
    for t in TERMS:
        for m in re.finditer(r"\b" + re.escape(t) + r"\b", sentence, re.I):
            ms.append((m.start(), m.end(), t))
    return set(textrelations._pairs(sentence, ms))


def test_such_as_and_a_list_after_it():
    assert pairs("Renewable energy such as solar power is cheaper every year.") == \
        {("renewable energy", "solar power", "broader")}
    assert pairs("We compared renewable energy, such as solar power, wind power and hydropower, with coal.") == \
        {("renewable energy", t, "broader") for t in ("solar power", "wind power", "hydropower")}


def test_and_other_with_the_items_before_it():
    assert pairs("Solar power and other renewable energy sources grew.") == \
        {("solar power", "renewable energy", "narrower")}
    assert pairs("Solar power, wind power and other renewable energy grew.") == \
        {("wind power", "renewable energy", "narrower"), ("solar power", "renewable energy", "narrower")}


def test_also_called_and_also_known_as_are_the_same():
    assert pairs("Remote work, also called telework, spread after 2020.") == {("remote work", "telework", "same")}
    assert pairs("Remote work (also known as telework) spread after 2020.") == {("remote work", "telework", "same")}


def test_effects_and_replacements():
    assert pairs("A carbon tax reduces emissions in every sector studied.") == {("carbon tax", "emissions", "effect")}
    assert pairs("Remote work can lead to less commuting.") == set()       # "less" stands between: not stated plainly
    assert pairs("Remote work can lead to commuting at odd hours.") == {("remote work", "commuting", "effect")}
    assert pairs("Households chose heat pumps instead of gas boilers.") == {("heat pumps", "gas boilers", "replaces")}


def test_negatives():
    # inside quotation marks: someone's words, a title
    assert pairs("The report is called “Renewable energy such as solar power”.") == set()
    assert pairs('She wrote "a carbon tax reduces emissions" in 2019.') == set()
    # other words between the two terms
    assert pairs("Renewable energy, a sector such as no other, needs solar power.") == set()
    assert pairs("A carbon tax, unlike subsidies, reduces emissions.") == set()
    # a list without a pattern says nothing
    assert pairs("Solar power, wind power and hydropower were compared.") == set()
    # a sentence break between them
    assert pairs("We studied renewable energy. Such as solar power, it varies.") == set()
    # one term only
    assert pairs("Renewable energy such as the sun is free.") == set()


def test_stored_from_the_smaller_id_with_the_relation_turned_round():
    assert textrelations._INV["effect"] == "effect_of" and textrelations._INV["replaces"] == "replaced_by"
    for rel in ("effect", "effect_of", "replaces", "replaced_by"):
        assert rel in terms.LINK_RELATIONS and terms._INVERSE[terms._INVERSE[rel]] == rel


# ---- with the glossary -------------------------------------------------------------------------------------------
TEXT = ("Heating in cold regions\n\n"
        "Households replace heating systems slowly. Heating systems such as heat pumps are subsidised in the region. "
        "Most households chose heat pumps instead of gas boilers once the subsidy came.\n\n"
        "Gas boilers and other heating systems are still sold. Heat pumps are quiet. Heat pumps lower energy poverty "
        "where the subsidy is large, and energy poverty is a risk for older households with gas boilers.\n\n"
        "Heating systems differ by region. Heat pumps need electricity; gas boilers need gas. Energy poverty "
        "remains where gas boilers are kept. Heat pumps instead of gas boilers was the advice of the agency.\n")


@pytest.fixture
def built(tmp_path):
    ws = Workspace.create(tmp_path / "p")
    d = tmp_path / "docs"
    d.mkdir()
    (d / "heating.txt").write_text(TEXT, encoding="utf-8")
    (d / "heating2.txt").write_text(TEXT.replace("Heating in cold regions", "Heating in warm regions"), encoding="utf-8")
    ingest.ingest(ws, [d])
    terms.build(ws)
    yield ws
    ws.close_all()


def _term(ws, label: str) -> str:
    t = terms.find_term(ws, label)
    assert t, (label, [r[0] for r in ws.query("SELECT label FROM terms ORDER BY tf DESC LIMIT 40")])
    return t


def test_the_glossary_proposes_them_with_their_sentences_and_a_person_decides(built):
    ws = built
    hp, gb, hs = _term(ws, "heat pumps"), _term(ws, "gas boilers"), _term(ws, "heating systems")
    got = {(r["a"], r["b"]): r for r in ws.query("SELECT * FROM concept_links WHERE source='pattern'")}
    a, b = sorted((hp, gb))
    assert (a, b) in got and got[(a, b)]["relation"] == ("replaces" if a == hp else "replaced_by")
    a2, b2 = sorted((hs, hp))
    assert (a2, b2) in got and got[(a2, b2)]["relation"] == ("broader" if a2 == hs else "narrower")
    s = textrelations.sentences(ws._conn(), hp, gb)
    assert s and all("instead of" in x["quote"] for x in s) and {x["title"] for x in s}
    text = ws.scalar("SELECT text FROM documents WHERE doc_id=?", (s[0]["doc_id"],))
    assert " ".join(text[s[0]["start"]:s[0]["end"]].split()) == s[0]["quote"]
    # proposed, never confirmed by itself
    lk = next(x for x in terms.links(ws) if (x["a"], x["b"]) == (a, b) and x["source"] == "pattern")
    assert not lk["confirmed"]
    # the concept page shows it with its sentences, seen from the concept
    rel = terms._related(ws, [hp], terms.links(ws))
    mine = next(x for x in rel["links"] if x["term_id"] == gb)
    assert mine["relation"] == "replaces" and mine["sentences"] and mine["state"] == "proposed"
    # accepted as any link
    terms.set_link(ws, a, b, "accept")
    lk = next(x for x in terms.links(ws) if (x["a"], x["b"]) == (a, b) and x["source"] == "pattern")
    assert lk["confirmed"]
    # the decision holds when the glossary is made again
    terms.build(ws)
    lk = next(x for x in terms.links(ws) if (x["a"], x["b"]) == (a, b) and x["source"] == "pattern")
    assert lk["confirmed"]
