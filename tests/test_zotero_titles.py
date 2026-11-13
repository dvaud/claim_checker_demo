"""0.13.3: a document linked to a work of the bibliography (the same file, the same DOI, or a person's word) is called
by the work's title from Zotero everywhere: the Documents list, the document page, Search, a check's excerpts and its
exports. The title read from the file is kept, shown on the document page and the Bibliography page, and comes back
when the link goes. The matching keeps reading the document's own title. The tests never touch a real Zotero."""
from __future__ import annotations

from pathlib import Path

from test_0130_bibliography import PANEL_TITLE, _documents, _library, zotero  # noqa: F401  (fixture)
from test_app import api, home  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "enlens_claims" / "gui" / "static"
OFFICE = "The office as a social place: why employees return"
DRAFT = "Draft v3 - do not circulate"


def _with_draft(folder: Path) -> Path:
    """The four documents of the 0.13.0 tests, and a paper whose first line is no title: the DOI links it."""
    _documents(folder)
    (folder / "paper_final.txt").write_text(
        f"{DRAFT}\nJ. Moreau\ndoi:10.5555/os.2023.212\n\nEmployees return to the office for its colleagues more than "
        "for its desks. Teams that agreed on shared office days reported stronger ties and more informal learning.")
    return folder


def _titles(ws) -> dict[str, tuple]:
    return {Path(r["path"]).name: (r["title"], r["file_title"])
            for r in ws.query("SELECT path, title, file_title FROM documents")}


def test_a_linked_document_takes_its_works_title(zotero, ws, tmp_path):  # noqa: F811
    from enlens_claims import bibliography as b
    from enlens_claims import ingest, search

    docs = _with_draft(tmp_path / "docs")
    _library(zotero, tmp_path / "Zotero" / "storage", docs / "download (3).pdf")
    ingest.ingest(ws, [docs], ai_access="cloud")
    ids = {Path(r["path"]).name: r["doc_id"] for r in ws.query("SELECT doc_id, path FROM documents")}
    own = {k: v[0] for k, v in _titles(ws).items()}
    assert own["paper_final.txt"] == DRAFT and own["download (3).pdf"].endswith("2019-2024 M.")
    before = search.passage_index(ws)
    assert {r["title"] for r in before.rows if r["doc_id"] == ids["paper_final.txt"]} == {DRAFT}

    works, src = b.pull_zotero("user")
    b.save(ws, works, src)
    t = _titles(ws)
    # linked by DOI and by the same file: the work's title; the file's own is kept
    assert t["paper_final.txt"] == (OFFICE, DRAFT)
    assert t["download (3).pdf"] == (PANEL_TITLE, own["download (3).pdf"])
    # the same title already: nothing to keep; proposed or not in the bibliography: their own title
    assert t["s41599-024.txt"] == (own["s41599-024.txt"], None)
    assert t["market_2024.txt"] == (own["market_2024.txt"], None) and t["brief.txt"] == (own["brief.txt"], None)

    # the Bibliography page: the document under its work's title, with the file's own title under it
    v = b.view(ws)
    office = next(r["doc"] for r in v["linked"] if r["doc"]["file"] == "paper_final.txt")
    assert office["title"] == OFFICE and office["file_title"] == DRAFT
    assert next(r["doc"] for r in v["linked"] if r["doc"]["file"] == "s41599-024.txt")["file_title"] is None
    assert v["not_in"][0]["file_title"] is None
    # only quote marks, case or dashes differ: nothing worth showing
    assert b.file_title({"title": "“You never really meet anyone”: young employees",
                         "file_title": '"You never really meet anyone": Young employees'}) is None
    assert b.file_title({"title": OFFICE, "file_title": DRAFT}) == DRAFT

    # Search: the keyword index is built again with the new titles (not the one cached before the link)
    after = search.passage_index(ws)
    assert after is not before
    assert {r["title"] for r in after.rows if r["doc_id"] == ids["paper_final.txt"]} == {OFFICE}
    from enlens_claims import concordance

    hits = concordance.search(ws, "informal learning")
    assert [d["title"] for d in hits["per_doc"]] == [OFFICE] and hits["lines"][0]["title"] == OFFICE
    assert search.passage_index(ws) is after  # nothing changed: the same index

    # another bibliography, whose work has the same title and author but no DOI or year: nothing links the paper any
    # more, so its own title is back, and the matching reads that one (the borrowed title would propose the work)
    lone = [b._work("csl:office", "report", OFFICE, [{"last": "Moreau", "first": "J."}], None, None, None, None, None,
                    None, [])]
    b.save(ws, lone, {"kind": "file", "name": "office.json", "format": "csl"})
    assert _titles(ws)["paper_final.txt"] == (DRAFT, None)
    assert not ws.query("SELECT 1 FROM bib_links WHERE doc_id=?", (ids["paper_final.txt"],))
    assert search.passage_index(ws) is not after
    b.save(ws, works, src)
    assert _titles(ws)["paper_final.txt"] == (OFFICE, DRAFT)

    # a proposal confirmed: the work's title; the 2024 edition is "Hydrogen market report" in Zotero
    b.decide(ws, "zotero:user:MARKET24", ids["market_2024.txt"], "same")
    assert _titles(ws)["market_2024.txt"] == ("Hydrogen market report", own["market_2024.txt"])

    # unlinked by a person: the file's own title comes back; linked again: the work's
    b.decide(ws, "zotero:user:OFFICEL1", ids["paper_final.txt"], "different")
    assert _titles(ws)["paper_final.txt"] == (DRAFT, None)
    b.decide(ws, "zotero:user:OFFICEL1", ids["paper_final.txt"], "same")
    assert _titles(ws)["paper_final.txt"] == (OFFICE, DRAFT)

    # a title edited in Zotero: the document follows it; the file's own title stays the file's
    for w in works:
        if w["key"] == "zotero:user:PANELST1":
            w["title"] = "Working from home and wellbeing"
    b.save(ws, works, src)
    assert _titles(ws)["download (3).pdf"] == ("Working from home and wellbeing", own["download (3).pdf"])

    # a document without a title of its own, linked by hand: back to no title when the link is cleared
    with ws.connect() as cx:
        cx.execute("UPDATE documents SET title=NULL WHERE doc_id=?", (ids["brief.txt"],))
    b.decide(ws, "zotero:user:SURVEY24", ids["brief.txt"], "same")
    assert _titles(ws)["brief.txt"] == ("Northbridge staff survey 2024", "")
    assert b.view(ws)["linked"] and all(r["doc"]["file_title"] is None for r in b.view(ws)["linked"]
                                        if r["doc"]["file"] == "brief.txt")
    b.decide(ws, "zotero:user:SURVEY24", ids["brief.txt"], "clear")
    assert _titles(ws)["brief.txt"] == (None, None)

    # the bibliography removed: every document has its own title again
    b.remove(ws)
    assert {k: v for k, v in _titles(ws).items() if k != "brief.txt"} == {
        k: (own[k], None) for k in own if k != "brief.txt"}


def test_a_check_shows_the_title_the_document_has_now(zotero, ws, tmp_path):  # noqa: F811
    import json

    from enlens_claims import bibliography as b
    from enlens_claims import claimcheck, ingest
    from enlens_claims.llm import BaselineBackend

    docs = _with_draft(tmp_path / "docs")
    _library(zotero, tmp_path / "Zotero" / "storage", docs / "download (3).pdf")
    ingest.ingest(ws, [docs], ai_access="cloud")
    hid = claimcheck.check_hypothesis(ws, "Shared office days strengthen ties between colleagues and informal learning.",
                                      BaselineBackend(), "baseline", k=5)
    titles = {p["title"] for part in claimcheck.hypothesis_result(ws, hid)["parts"] for p in part["passages"]}
    assert DRAFT in titles

    works, src = b.pull_zotero("user")
    b.save(ws, works, src)
    res = claimcheck.hypothesis_result(ws, hid)
    titles = {p["title"] for part in res["parts"] for p in part["passages"]}
    assert OFFICE in titles and DRAFT not in titles
    assert OFFICE in {r["source"] for r in claimcheck.export_rows(ws)}
    # what the AI was shown stays on record as it was
    payloads = [json.loads(r["payload_json"]) for r in ws.query("SELECT payload_json FROM tasks WHERE kind='check'")]
    assert DRAFT in {p["title"] for pl in payloads for p in pl["passages"]}


def test_the_app_shows_the_works_title_and_the_files(api, zotero, tmp_path):  # noqa: F811
    from enlens_claims import home as core
    from enlens_claims import ingest

    docs = _with_draft(tmp_path / "docs")
    _library(zotero, tmp_path / "Zotero" / "storage", docs / "download (3).pdf")
    ws = core.create_project("T")
    ingest.ingest(ws, [docs], ai_access="cloud")
    r = api("POST", "/api/projects/T/bibliography", {"zotero": {"library": "user", "collection": None}})[1]
    assert api.wait(r["job"]["id"])["state"] == "done"
    listed = {d["file"]: d for d in api("GET", "/api/projects/T/documents")[1]["documents"]}
    assert listed["paper_final.txt"]["title"] == OFFICE and listed["brief.txt"]["bib"] is None
    one = api("GET", f"/api/projects/T/documents/{listed['paper_final.txt']['doc_id']}?view=blocks&offset=0&limit=5")[1]
    assert one["title"] == OFFICE and one["file_title"] == DRAFT and one["bib"]["title"] == OFFICE
    other = api("GET", f"/api/projects/T/documents/{listed['brief.txt']['doc_id']}?view=blocks&offset=0&limit=5")[1]
    assert other["file_title"] is None
    v = api("GET", "/api/projects/T/bibliography")[1]
    assert {r["doc"]["file_title"] for r in v["linked"] if r["doc"]["file"] == "paper_final.txt"} == {DRAFT}
    st, found = api("GET", "/api/projects/T/search?q=informal+learning")
    assert st == 200 and [d["title"] for d in found["per_doc"]] == [OFFICE]
    st, v = api("DELETE", "/api/projects/T/bibliography", {})
    assert st == 200
    assert {d["file"]: d["title"] for d in api("GET", "/api/projects/T/documents")[1]["documents"]}[
        "paper_final.txt"] == DRAFT


def test_the_pages_show_the_files_own_title():
    sources = (STATIC / "views" / "sources.js").read_text()
    # 0.17.0 (design guide, changed on purpose): the spacing is a class of the page's block in views.css
    assert 'd.file_title ? h("p", { class: "muted small dv-file-title" }, "Title in the file: "' \
        in sources
    # the work's title is not repeated next to the heading that already shows it
    assert "d.bib.title && d.bib.title !== d.title" in sources
    page = (STATIC / "views" / "bibliography.js").read_text()
    assert 'd.file_title ? h("div", { class: "muted small bib-own-title" }, "Title in the file: ", d.file_title) : null' in page
    assert "${r.doc.file_title || \"\"}" in page  # the filter finds a document by the title in its file too
    assert "file_title" in (ROOT / "docs" / "API.md").read_text()
