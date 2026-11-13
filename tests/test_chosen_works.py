"""0.13.9: a bibliography of works chosen one by one. The Bibliography page lists the works of a Zotero library (or of
one collection), searched by Zotero's own quick search; the works ticked there are the bibliography, and *Update from
Zotero* reads those same works again. The tests never touch a real Zotero (tests/fake_zotero.py stands in)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from test_0130_bibliography import PANEL_TITLE, _documents, _library, zotero  # noqa: F401  (fixture)
from test_app import api, home  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "enlens_claims" / "gui" / "static"
FOUR = "A four-day week in the public sector: results of a one-year trial"
OFFICE = "The office as a social place: why employees return"


def test_the_works_to_choose_from(zotero, tmp_path):  # noqa: F811
    from enlens_claims import bibliography as b

    _library(zotero, tmp_path / "Zotero" / "storage", None)
    r = b.zotero_works("user")
    titles = [w["title"] for w in r["works"]]
    assert titles == sorted(titles, key=str.lower) and len(titles) == 7 and r["more"] is False  # by title, no note
    assert "A note" not in titles and not any(w["type"] == "File" for w in r["works"])  # no attachment of a work
    market = b.zotero_works("user", q="hydrogen")["works"]
    assert [(w["key"], w["cite"], w["type"]) for w in market] == [
        ("MARKET23", "Nordic Energy Agency (2023)", "Report"), ("MARKET24", "Nordic Energy Agency (2024)", "Report")]
    assert [w["key"] for w in b.zotero_works("user", q="okafor")["works"]] == ["PANELST1"]  # by an author too
    assert {w["key"] for w in b.zotero_works("user", q="2023")["works"]} == {"MARKET23", "OFFICEL1"}  # and the year
    assert b.zotero_works("user", q="no such words")["works"] == []
    # one collection: its own works, not those of its subcollections
    assert {w["key"] for w in b.zotero_works("user", "RWCOLL01")["works"]} == {"COMMUTE1", "SURVEY24", "FOURDAY1",
                                                                              "OFFICEL1"}
    few = b.zotero_works("user", limit=3)
    assert len(few["works"]) <= 3 and few["more"] is True
    with pytest.raises(ValueError):
        b.zotero_works("user", "../x")
    with pytest.raises(ValueError):
        b.zotero_works("users/1")


def test_pulling_the_chosen_works(zotero, tmp_path):  # noqa: F811
    from enlens_claims import bibliography as b

    _library(zotero, tmp_path / "Zotero" / "storage", None)
    works, src = b.pull_zotero("user", items=["OFFICEL1", "FOURDAY1", "GONE0001", "OFFICEL1"])
    # in the order chosen; Zotero's answer also holds FOURDAY1's two attachments, which are not works
    assert [w["key"] for w in works] == ["zotero:user:OFFICEL1", "zotero:user:FOURDAY1"]
    assert [f["name"] for f in works[1]["files"]] == ["four day week.pdf"]  # the PDF, not the publisher's page
    assert src == {"kind": "zotero", "library": "user", "collection": None, "subcollections": False,
                   "items": ["OFFICEL1", "FOURDAY1"]}  # a work Zotero no longer has is left out
    assert any("/api/users/0/items" == r for r in zotero.requests)
    assert not any(r.startswith("/api/users/0/collections/") for r in zotero.requests)  # no collection was read
    with pytest.raises(b.ZoteroError) as e:
        b.pull_zotero("user", items=["GONE0001"])
    assert e.value.kind == "failed" and "not in Zotero any more" in str(e.value)
    for bad in ([], ["no/key"], [f"K{i}" for i in range(b.MAX_CHOSEN + 1)]):
        with pytest.raises(ValueError):
            b.pull_zotero("user", items=bad)


def test_chosen_works_through_the_app(api, zotero, tmp_path):  # noqa: F811
    from enlens_claims import home as core
    from enlens_claims import ingest

    docs = _documents(tmp_path / "docs")
    _library(zotero, tmp_path / "Zotero" / "storage", docs / "download (3).pdf")
    ws = core.create_project("C")
    ingest.ingest(ws, [docs], ai_access="cloud")

    st, r = api("GET", "/api/zotero/works?library=user&q=hydrogen")
    assert st == 200 and [w["key"] for w in r["works"]] == ["MARKET23", "MARKET24"] and r["more"] is False
    st, r = api("GET", "/api/zotero/works?library=user&collection=ENERGY03")
    assert st == 200 and len(r["works"]) == 2
    assert api("GET", "/api/zotero/works?library=../etc")[0] == 400

    # two works: the same file and the same DOI link them to their documents by themselves
    st, r = api("POST", "/api/projects/C/bibliography", {"zotero": {"library": "user", "items": ["PANELST1", "COMMUTE1"]}})
    assert st == 200
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done" and job["result"]["works"] == 2 and job["result"]["linked"] == 2, job
    v = api("GET", "/api/projects/C/bibliography")[1]
    assert v["bibliography"]["items"] == ["PANELST1", "COMMUTE1"] and v["bibliography"]["collection"] is None
    assert v["counts"]["works"] == 2 and v["counts"]["to_find"] == 0
    assert {r_["work"]["title"] for r_ in v["linked"]} == {PANEL_TITLE, "Commuting less, emitting less? A survey of "
                                                         "4,000 workers in the Rivermouth region"}

    # Update from Zotero reads the same works again: a work added to Zotero does not come along, a deleted one goes
    zotero.user.item("NEWWORK1", "A work added to Zotero later", creators=[("Lee", "A.")], date="2026")
    zotero.user.items = [i for i in zotero.user.items if i["key"] != "COMMUTE1"]
    r = api("POST", "/api/projects/C/bibliography", {"update": True})[1]
    assert api.wait(r["job"]["id"])["state"] == "done"
    v = api("GET", "/api/projects/C/bibliography")[1]
    assert v["bibliography"]["items"] == ["PANELST1"] and v["counts"]["works"] == 1

    # one more work: the list chosen before, and the new one
    r = api("POST", "/api/projects/C/bibliography", {"zotero": {"library": "user", "items": ["PANELST1", "FOURDAY1"]}})[1]
    assert api.wait(r["job"]["id"])["state"] == "done"
    v = api("GET", "/api/projects/C/bibliography")[1]
    assert v["counts"]["works"] == 2 and [w["title"] for w in v["to_find"]] == [FOUR] and v["counts"]["files"] == 1

    # a collection again: the chosen works are forgotten
    r = api("POST", "/api/projects/C/bibliography", {"zotero": {"library": "user", "collection": "ENERGY03"}})[1]
    assert api.wait(r["job"]["id"])["state"] == "done"
    assert "items" not in api("GET", "/api/projects/C/bibliography")[1]["bibliography"]

    for bad in ([], "PANELST1", ["a/b"], [1], ["K"] * 501):
        assert api("POST", "/api/projects/C/bibliography", {"zotero": {"library": "user", "items": bad}})[0] == 400, bad

    zotero.mode = "api_off"
    st, err = api("GET", "/api/zotero/works?library=user")
    assert st == 409 and err["kind"] == "zotero_api_off"


def test_the_page_offers_the_works_one_by_one():
    page = (STATIC / "views" / "bibliography.js").read_text()
    assert "innerHTML" not in page
    for words in ("Choose the works one by one", "Search title, author or year", "/api/zotero/works",
                  "items: [...chosen.keys()]", "you chose", "Choose other works or a file",
                  "Only the first 100 are shown: search to find the others."):
        assert words in page, words
    assert re.search(r"Bring in \$\{plural\(chosen\.size, \"work\", \"works\"\)\}", page)
    from _static import rule  # 0.17.0: reads the cascade, so it holds when the rules move

    assert rule(".bib-chosen-chip") and rule(".bib-one")
