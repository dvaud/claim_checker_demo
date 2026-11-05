"""0.13: a project's bibliography. A Zotero library or collection, read from the Zotero app on this computer (its local
API, here a stand-in: tests/fake_zotero.py), or a file exported from a reference manager (BibTeX, RIS, CSL JSON,
Zotero's CSV), matched with the project's documents: linked by itself when it is the same file or the same DOI,
proposed when the title stands on a document's first pages with an author or the year, never against a person's
word. The tests never touch a real Zotero or the network."""
from __future__ import annotations

import json
import re
import shutil
import socket
from pathlib import Path

import pytest

from fake_zotero import FakeZotero
from helpers import make_pdf
from test_app import api, home  # noqa: F401  (fixtures)
from _static import defined_tokens
from helpers import api_docs

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "enlens_claims" / "gui" / "static"


@pytest.fixture
def zotero(monkeypatch):
    z = FakeZotero()
    monkeypatch.setenv("ENLENS_ZOTERO_URL", z.start())
    yield z
    z.stop()


def _closed_port() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{s.getsockname()[1]}"


PANEL_TITLE = "Working from home and wellbeing: evidence from the Lowland Household Panel, 2019-2024"


def _documents(folder: Path) -> Path:
    """Four documents as a researcher would have downloaded them: no metadata, odd file names."""
    folder.mkdir(parents=True, exist_ok=True)
    make_pdf(folder / "download (3).pdf", [
        f"{PANEL_TITLE}\nM. Verhoeven and A. Okafor, Journal of Work and Society, 2025\n\nAbstract. We follow 6,200 "
        "employees of the Lowland Household Panel before, during and after the pandemic. Employees who worked from home "
        "at least two days a week reported higher life satisfaction than comparable employees at the office.",
        "Results. Hybrid workers commuted on average 3.1 fewer hours a week and reported slightly better sleep."])
    (folder / "s41599-024.txt").write_text(
        "Commuting less, emitting less? A survey of 4,000 workers in the Rivermouth region\n"
        "Rivermouth Mobility Institute, Research report 12, 2024\ndoi:10.5555/rmi.2024.12\n\n"
        "Summary. Remote work reduces commuting emissions, but by less than often assumed. Workers who stay home two "
        "days a week cut their commuting distance by 35 percent, and part of the saving is lost to errands by car.")
    (folder / "brief.txt").write_text(
        "Policy brief: hybrid working at the Municipality of Northbridge, 2025\n\nBackground. Since 2022 municipal "
        "staff may work from home up to three days a week. In the 2024 staff survey, 78 percent of staff said hybrid "
        "working improved their work-life balance. The Municipality of Northbridge publishes the survey each year.")
    (folder / "market_2024.txt").write_text(
        "Hydrogen market report 2024\nNordic Energy Agency\n\nThe market grew faster than in the 2023 edition of "
        "this report. Electrolyser orders doubled, and prices for green hydrogen fell for the first time.")
    return folder


def _library(z: FakeZotero, storage: Path, panel_file: Path | None) -> None:
    lib = z.user
    rw = lib.collection("RWCOLL01", "Remote work")
    wb = lib.collection("WELLBE02", "Wellbeing", parent=rw)
    lib.collection("ENERGY03", "Energy")
    lib.item("PANELST1", PANEL_TITLE, creators=[("Verhoeven", "M."), ("Okafor", "A.")], date="2025", collections=[wb])
    if panel_file is not None:
        p = storage / "ATTPANEL" / "Verhoeven - 2025 - Working from home.pdf"
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(panel_file, p)
        lib.attachment("ATTPANEL", "PANELST1", p)
    lib.item("COMMUTE1", "Commuting less, emitting less? A survey of 4,000 workers in the Rivermouth region",
             creators=["Rivermouth Mobility Institute"], date="2024", type_="report", collections=[rw],
             extra="DOI: 10.5555/RMI.2024.12")
    lib.item("SURVEY24", "Northbridge staff survey 2024", creators=["Municipality of Northbridge"], date="2024",
             type_="report", collections=[rw])
    lib.item("NOTE0001", "A note", type_="note", collections=[rw])
    lib.item("MARKET23", "Hydrogen market report", creators=["Nordic Energy Agency"], date="2023", type_="report",
             collections=["ENERGY03"])
    lib.item("MARKET24", "Hydrogen market report", creators=["Nordic Energy Agency"], date="2024", type_="report",
             collections=["ENERGY03"])
    four = storage / "ATTFOURD" / "four day week.pdf"
    four.parent.mkdir(parents=True, exist_ok=True)
    make_pdf(four, ["A four-day week in the public sector: results of a one-year trial\nS. Haugen, 2024\n\nSixty teams "
                    "of a regional administration worked four days a week for a year at the same pay. Sick leave fell "
                    "by 18 percent and staff reported less stress."])
    lib.item("FOURDAY1", "A four-day week in the public sector: results of a one-year trial", creators=[("Haugen", "S.")],
             date="2024", collections=[rw], DOI="10.5555/par.2024.077")
    lib.attachment("ATTFOURD", "FOURDAY1", four)
    lib.attachment("ATTLINK1", "FOURDAY1", None, title="Publisher page", content_type="", link_mode="linked_url")
    lib.item("OFFICEL1", "The office as a social place: why employees return", creators=[("Moreau", "J.")],
             date="2023", collections=[rw], url="https://doi.org/10.5555/os.2023.212")
    g = z.group(4711, "Lab group")
    g.collection("LABCOLL1", "Shared")
    g.item("GROUPIT1", "A shared paper on teleworking", creators=[("Kim", "H.")], date="2021", collections=["LABCOLL1"])


# ---------------------------------------------------------------------------------------------
# exported files
# ---------------------------------------------------------------------------------------------
BIB = r"""
@comment{jabref-meta: databaseType:bibtex;}
@string{jws = "Journal of Work and Society"}
@article{verhoeven2025,
  title = {Working from home and wellbeing: evidence from the {Lowland} {Household} {Panel}, 2019--2024},
  author = {Verhoeven, M. and Okafor, A. and M{\"u}ller, J{\"o}rg and Garc\'{\i}a, Ana},
  journal = jws,
  year = 2025,
  doi = {https://doi.org/10.5555/JWS.2025.014},
  file = {Full Text PDF:/Users/me/Zotero/storage/ABCD1234/Verhoeven 2025.pdf:application/pdf;Snapshot:C\:\\Users\\me\\snap.html:text/html}
}
@techreport{rmi2024,
  title = "Commuting less, emitting less? {A} survey of 4,000 workers in the {Rivermouth} region",
  author = {{Rivermouth Mobility Institute}},
  institution = {Rivermouth Mobility Institute},
  date = {2024-03},
  url = {https://example.org/rmi}
}
@misc{nokey, title = {On {\&} off: notes}, author = {Smith, J.}, year = {2020}, note = {DOI: 10.5555/x.1} }
"""

RIS = """TY  - JOUR
TI  - Working from home and wellbeing
AU  - Verhoeven, M.
AU  - Okafor, A.
PY  - 2025///
T2  - Journal of Work and Society
DO  - 10.5555/jws.2025.014
L1  - file:///Users/me/Zotero/storage/ABCD1234/paper.pdf
ID  - 7
ER  -
TY  - RPRT
T1  - Commuting less, emitting less? A survey
  of 4,000 workers
A1  - Rivermouth Mobility Institute
Y1  - 2024
UR  - https://doi.org/10.5555/rmi.2024.12
ER  -
"""

CSL = json.dumps([
    {"id": "http://zotero.org/users/local/AbCdEf/items/PANELST1", "type": "article-journal", "title": PANEL_TITLE,
     "author": [{"family": "Verhoeven", "given": "M."}, {"family": "Okafor", "given": "A."}],
     "issued": {"date-parts": [[2025, 3]]}, "container-title": "Journal of Work and Society", "DOI": "10.5555/jws.2025.014"},
    {"id": "http://zotero.org/groups/4711/items/GROUPIT1", "type": "report", "title": "A shared paper",
     "author": [{"literal": "Lab group"}], "issued": {"raw": "2021"}},
    {"id": "other-1", "type": "book", "title": "No key here", "editor": [{"family": "Kim", "given": "H."}]},
])

CSV = ('\ufeff"Key","Item Type","Publication Year","Author","Title","Publication Title","ISBN","DOI","Url","Extra",'
       '"File Attachments"\n'
       '"PANELST1","journalArticle","2025","Verhoeven, M.; Okafor, A.","' + PANEL_TITLE + '","Journal of Work and '
       'Society","","10.5555/jws.2025.014","","","/Users/me/Zotero/storage/ABCD1234/a.pdf; /Users/me/b.html"\n'
       '"OFFICEL1","report","2023","Moreau, J.","The office as a social place","","","","","DOI: 10.5555/os.2023.212",""\n')


def test_exported_files_of_each_format():
    from enlens_claims import bibliography as b

    fmt, works = b.parse_file("My Library.bib", BIB)
    assert fmt == "bibtex" and len(works) == 3
    v, r, n = works
    assert v["key"] == "bib:verhoeven2025" and v["year"] == "2025" and v["doi"] == "10.5555/jws.2025.014"
    assert v["title"] == "Working from home and wellbeing: evidence from the Lowland Household Panel, 2019–2024"
    assert [c.get("last") for c in v["creators"]] == ["Verhoeven", "Okafor", "Müller", "García"]
    assert v["creators"][2]["first"] == "Jörg" and v["type"] == "article"
    assert [f["path"] for f in v["files"]] == ["/Users/me/Zotero/storage/ABCD1234/Verhoeven 2025.pdf",
                                               "C:\\Users\\me\\snap.html"]
    assert r["creators"] == [{"name": "Rivermouth Mobility Institute", "role": "author"}] and r["year"] == "2024"
    assert r["title"].startswith("Commuting less, emitting less? A survey") and r["url"] == "https://example.org/rmi"
    assert n["title"] == "On & off: notes" and n["doi"] == "10.5555/x.1"

    fmt, works = b.parse_file("export.txt", RIS)
    assert fmt == "ris" and [w["year"] for w in works] == ["2025", "2024"]
    assert works[0]["files"][0]["path"] == "/Users/me/Zotero/storage/ABCD1234/paper.pdf" and works[0]["key"] == "ris:7"
    assert works[0]["container"] == "Journal of Work and Society"
    assert works[1]["title"] == "Commuting less, emitting less? A survey of 4,000 workers"  # a line continued
    assert works[1]["doi"] == "10.5555/rmi.2024.12" and works[1]["creators"][0]["name"] == "Rivermouth Mobility Institute"

    fmt, works = b.parse_file("items.json", CSL)
    assert fmt == "csl"
    assert works[0]["key"] == "zotero:user:PANELST1" and works[0]["link"] == "zotero://select/library/items/PANELST1"
    assert works[1]["key"] == "zotero:group-4711:GROUPIT1" and works[1]["link"].endswith("/groups/4711/items/GROUPIT1")
    assert works[1]["creators"][0]["name"] == "Lab group" and works[1]["year"] == "2021"
    assert works[2]["key"] == "csl:other-1" and works[2]["creators"][0]["role"] == "editor"

    fmt, works = b.parse_file("Exported Items.csv", CSV)
    assert fmt == "csv" and works[0]["key"] == "zotero:user:PANELST1" and len(works[0]["files"]) == 2
    assert works[1]["doi"] == "10.5555/os.2023.212" and works[1]["link"] == "zotero://select/library/items/OFFICEL1"

    # one unbalanced brace costs one entry, not the ones after it
    broken = b.parse_bibtex("@article{k, title = {Broken {brace}, year = 2000}\n@article{k2, title={Next}, year=2001}")
    assert [w["key"] for w in broken][-1] == "bib:k2" and broken[-1]["title"] == "Next"
    with pytest.raises(ValueError, match="not a bibliography"):
        b.parse_file("notes.txt", "Just some notes about a meeting.")
    with pytest.raises(ValueError, match="could not be read"):
        b.parse_file("broken.json", "[{")
    assert b.cite([{"last": "A"}, {"last": "B"}, {"last": "C"}], "2020") == "A et al. (2020)"
    assert b.cite([{"name": "IEA", "role": "author"}, {"last": "Ed", "role": "editor"}], None) == "IEA"


# ---------------------------------------------------------------------------------------------
# reading Zotero
# ---------------------------------------------------------------------------------------------
def test_zotero_states(zotero, monkeypatch):
    from enlens_claims import bibliography as b

    zotero.group(4711, "Lab group")
    st = b.zotero_status()
    assert st["state"] == "ready" and st["libraries"] == [{"id": "user", "name": "My Library"},
                                                          {"id": "group-4711", "name": "Lab group"}]
    zotero.mode = "api_off"
    assert b.zotero_status()["state"] == "api_off"
    zotero.mode = "old"
    assert b.zotero_status()["state"] == "too_old"
    monkeypatch.setenv("ENLENS_ZOTERO_URL", _closed_port())
    assert b.zotero_status()["state"] == "not_running"
    with pytest.raises(b.ZoteroError) as e:
        b.zotero_collections("user")
    assert e.value.kind == "not_running"
    with pytest.raises(ValueError):
        b.pull_zotero("users/1/../x")
    # by default only this computer is asked: never a server on the internet
    assert b.ZOTERO.startswith("http://127.0.0.1:")


def test_pulling_a_collection_and_the_whole_library(zotero, tmp_path):
    from enlens_claims import bibliography as b

    panel = _documents(tmp_path / "docs") / "download (3).pdf"
    _library(zotero, tmp_path / "Zotero" / "storage", panel)
    cols = b.zotero_collections("user")
    assert [(c["name"], c["depth"], c["items"]) for c in cols] == [("Energy", 0, 2), ("Remote work", 0, 5),
                                                                   ("Wellbeing", 1, 1)]
    works, src = b.pull_zotero("user", "RWCOLL01", subcollections=True)
    keys = {w["key"] for w in works}
    assert keys == {"zotero:user:PANELST1", "zotero:user:COMMUTE1", "zotero:user:SURVEY24", "zotero:user:FOURDAY1",
                    "zotero:user:OFFICEL1"}  # the note is left out; the subcollection's work comes along
    assert src["collection_name"] == "Remote work" and src["subcollections"] is True
    w = {x["key"]: x for x in works}
    assert w["zotero:user:COMMUTE1"]["doi"] == "10.5555/rmi.2024.12"     # from Zotero's "Extra"
    assert w["zotero:user:OFFICEL1"]["doi"] == "10.5555/os.2023.212"     # from a doi.org address
    assert [f["name"] for f in w["zotero:user:FOURDAY1"]["files"]] == ["four day week.pdf"]  # not the web link
    assert w["zotero:user:PANELST1"]["link"] == "zotero://select/library/items/PANELST1"
    assert {x["key"] for x in b.pull_zotero("user", "RWCOLL01", subcollections=False)[0]} == keys - {"zotero:user:PANELST1"}
    everything, src = b.pull_zotero("user")
    assert len(everything) == 7 and src["collection"] is None
    assert [f["name"] for f in {x["key"]: x for x in everything}["zotero:user:PANELST1"]["files"]] == [
        "Verhoeven - 2025 - Working from home.pdf"]
    group, _ = b.pull_zotero("group-4711", "LABCOLL1")
    assert group[0]["key"] == "zotero:group-4711:GROUPIT1" and group[0]["link"] == "zotero://select/groups/4711/items/GROUPIT1"
    assert any(r.startswith("/api/groups/4711/") for r in zotero.requests)


# ---------------------------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------------------------
def test_matching_links_proposes_and_keeps_a_persons_word(zotero, ws, tmp_path):
    from enlens_claims import bibliography as b
    from enlens_claims import ingest

    docs = _documents(tmp_path / "docs")
    _library(zotero, tmp_path / "Zotero" / "storage", docs / "download (3).pdf")
    ingest.ingest(ws, [docs], ai_access="cloud")
    ids = {Path(r["path"]).name: r["doc_id"] for r in ws.query("SELECT doc_id, path FROM documents")}
    works, src = b.pull_zotero("user")
    c = b.save(ws, works, src)
    v = b.view(ws)
    linked = {(r["work"]["key"], r["doc"]["file"], r["method"]) for r in v["linked"]}
    # the very same file, and the same DOI (the report prints its DOI; Zotero has it in "Extra")
    assert linked == {("zotero:user:PANELST1", "download (3).pdf", "file"),
                      ("zotero:user:COMMUTE1", "s41599-024.txt", "doi")}
    prop = {(r["work"]["key"], r["doc"]["file"]) for r in v["confirm"]}
    # the 2024 edition: its year stands next to the title; the 2023 edition is only mentioned
    assert prop == {("zotero:user:MARKET24", "market_2024.txt")}
    ev = v["confirm"][0]["evidence"]
    assert ev["author"] == "nordic energy agency" and ev["year"] == "2024" and ev["title"] == "whole"
    assert ev["excerpt"][ev["start"]:ev["end"]] == "Hydrogen market report"
    # a document that cites a work is not that work: "the 2024 staff survey" in the brief
    assert "zotero:user:SURVEY24" in {w["key"] for w in v["to_find"]}
    assert [d["file"] for d in v["not_in"]] == ["brief.txt"]
    assert c["linked"] == 2 and c["confirm"] == 1 and v["counts"]["files"] == 1
    assert v["counts"] == {"works": 7, "linked": 2, "confirm": 1, "to_find": 4, "not_in": 1, "files": 1}

    # a person's word: a link undone stays undone, a proposal confirmed stays confirmed
    b.decide(ws, "zotero:user:COMMUTE1", ids["s41599-024.txt"], "different")
    b.decide(ws, "zotero:user:MARKET24", ids["market_2024.txt"], "same")
    b.match(ws)
    v = b.view(ws)
    assert ("zotero:user:COMMUTE1", "s41599-024.txt") not in {(r["work"]["key"], r["doc"]["file"]) for r in v["linked"]}
    assert ("zotero:user:MARKET24", "market_2024.txt", "title") in {(r["work"]["key"], r["doc"]["file"], r["method"])
                                                                    for r in v["linked"]}
    # linked by hand: the brief is the staff survey after all
    b.decide(ws, "zotero:user:SURVEY24", ids["brief.txt"], "same")
    assert ("zotero:user:SURVEY24", "person") in {(r["work"]["key"], r["method"]) for r in b.view(ws)["linked"]}
    with pytest.raises(ValueError):
        b.decide(ws, "zotero:user:SURVEY24", ids["brief.txt"], "maybe")
    with pytest.raises(KeyError):
        b.decide(ws, "zotero:user:NOPE", ids["brief.txt"], "same")

    # the same library from an exported file (other keys): the person's word follows each work
    csl = [{"id": f"w{i}", "title": w["title"], "issued": {"raw": w["year"]}, "DOI": w["doi"],
            "author": [{"family": (w["creators"][0].get("last") or w["creators"][0].get("name"))}] if w["creators"] else []}
           for i, w in enumerate(works)]
    fmt, again = b.parse_file("lib.json", json.dumps(csl))
    b.save(ws, again, {"kind": "file", "name": "lib.json", "format": fmt})
    v = b.view(ws)
    by = {r["doc"]["file"]: (r["status"], r["method"]) for r in v["linked"]}
    assert by["market_2024.txt"] == ("confirmed", "title") and by["brief.txt"] == ("confirmed", "person")
    assert "s41599-024.txt" not in by  # still undone
    assert v["bibliography"]["kind"] == "file" and v["bibliography"]["format_text"] == "CSL JSON"

    # a removed document: its work is to find again
    ws.remove_document(ids["brief.txt"])
    assert not ws.query("SELECT 1 FROM bib_links WHERE doc_id=?", (ids["brief.txt"],))
    b.remove(ws)
    assert b.view(ws) == {"bibliography": None} and not b.has(ws)


def test_short_titles_need_an_author_and_the_year(ws, tmp_path):
    from enlens_claims import bibliography as b
    from enlens_claims import ingest

    d = tmp_path / "d"
    d.mkdir()
    (d / "a.txt").write_text("Hydrogen\nA. Rossi, 2021\n\n" + "Hydrogen is a gas that is used in industry. " * 6)
    (d / "b.txt").write_text("Hydrogen\nan overview for students\n\n" + "Hydrogen is a gas that is used in industry. " * 6)
    ingest.ingest(ws, [d])
    works = [b._work("w1", "book", "Hydrogen", [{"last": "Rossi", "first": "A."}], "2021", None, None, None, None, None,
                     [])]
    b.save(ws, works, {"kind": "file", "name": "x.bib", "format": "bibtex"})
    assert [r["doc"]["file"] for r in b.view(ws)["confirm"]] == ["a.txt"]


# ---------------------------------------------------------------------------------------------
# the app
# ---------------------------------------------------------------------------------------------
def test_the_bibliography_through_the_app(api, zotero, tmp_path):  # noqa: F811
    from enlens_claims import home as core
    from enlens_claims import ingest

    docs = _documents(tmp_path / "docs")
    _library(zotero, tmp_path / "Zotero" / "storage", docs / "download (3).pdf")
    later = tmp_path / "later"
    later.mkdir()
    shutil.move(str(docs / "market_2024.txt"), later / "market_2024.txt")
    ws = core.create_project("B")
    ingest.ingest(ws, [docs], ai_access="cloud")
    assert api("GET", "/api/projects/B/bibliography")[1]["bibliography"] is None
    st, z = api("GET", "/api/zotero")
    assert st == 200 and z["state"] == "ready"
    st, cols = api("GET", "/api/zotero/collections?library=user")
    assert st == 200 and [c["name"] for c in cols["collections"]][:2] == ["Energy", "Remote work"]

    st, r = api("POST", "/api/projects/B/bibliography", {"zotero": {"library": "user", "collection": None}})
    assert st == 200 and r["job"]["kind"] == "bibliography"
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done" and job["result"]["linked"] == 2, job
    st, v = api("GET", "/api/projects/B/bibliography")
    assert v["bibliography"]["library_name"] == "My Library" and v["counts"]["files"] == 1
    assert v["ai_access"]["default"] == "cloud"
    docs_view = api("GET", "/api/projects/B/documents")[1]["documents"]
    cites = {d["file"]: (d["bib"] or {}).get("cite") for d in docs_view}
    assert cites["download (3).pdf"] == "Verhoeven and Okafor (2025)" and cites["brief.txt"] is None
    panel = next(d["doc_id"] for d in docs_view if d["file"] == "download (3).pdf")
    one = api("GET", f"/api/projects/B/documents/{panel}?view=blocks&offset=0&limit=5")[1]
    assert one["bib"]["link"] == "zotero://select/library/items/PANELST1"

    # Zotero's file for a work without a document: added where it is, and linked by itself
    st, r = api("POST", "/api/projects/B/bibliography/files", {"ai_access": "local"})
    assert st == 200 and r["job"]["kind"] == "ingest" and r["job"]["title"] == "Adding Zotero's files"
    job = api.wait(r["job"]["id"])
    assert job["result"]["added"] == 1 and job["result"]["bibliography"] == {"linked": 1, "confirm": 0}
    four = ws.query("SELECT path, ai_access FROM documents WHERE path LIKE '%four day week.pdf'")
    assert four and four[0]["ai_access"] == "local" and "Zotero" in four[0]["path"]
    assert api("POST", "/api/projects/B/bibliography/files", {"ai_access": "cloud"})[0] == 400  # nothing left

    # a document added later is matched as it comes in
    st, r = api("POST", "/api/projects/B/ingest", {"path": str(later), "ai_access": "cloud"})
    job = api.wait(r["job"]["id"])
    assert job["result"]["bibliography"] == {"linked": 0, "confirm": 1}
    v = api("GET", "/api/projects/B/bibliography")[1]
    pair = v["confirm"][0]
    st, v = api("PUT", "/api/projects/B/bibliography/links", {"item_key": pair["work"]["key"],
                                                               "doc_id": pair["doc"]["doc_id"], "decision": "same"})
    assert st == 200 and v["counts"]["confirm"] == 0 and v["counts"]["linked"] == 4
    assert api("PUT", "/api/projects/B/bibliography/links", {"item_key": "x", "doc_id": "y", "decision": "same"})[0] == 404
    assert api("POST", "/api/projects/B/bibliography/confirm-all", {})[1]["confirmed"] == 0

    # the works to find, as a spreadsheet and as CSV
    st, xlsx = api("GET", "/api/projects/B/bibliography/to-find.xlsx")
    assert st == 200 and xlsx[:2] == b"PK"
    from io import BytesIO

    from openpyxl import load_workbook

    sheet = load_workbook(BytesIO(xlsx)).active
    head = [c.value for c in sheet[1]]
    assert head[:3] == ["Title", "Authors", "Year"] and "DOI link" in head and "Open in Zotero" in head
    titles = [r[0].value for r in sheet.iter_rows(min_row=2)]
    assert "Northbridge staff survey 2024" in titles and "Hydrogen market report" in titles
    st, csv_body = api("GET", "/api/projects/B/bibliography/to-find.csv")
    assert st == 200 and b"https://doi.org/10.5555/os.2023.212" in csv_body

    # updating from Zotero keeps the person's word; a file replaces it; bad requests
    r = api("POST", "/api/projects/B/bibliography", {"update": True})[1]
    assert api.wait(r["job"]["id"])["state"] == "done"
    assert api("GET", "/api/projects/B/bibliography")[1]["counts"]["linked"] == 4
    st, r = api("POST", "/api/projects/B/bibliography", {"file": {"name": "refs.bib", "text": BIB}})
    assert st == 200 and api.wait(r["job"]["id"])["state"] == "done"
    v = api("GET", "/api/projects/B/bibliography")[1]
    assert v["bibliography"]["kind"] == "file" and v["counts"]["works"] == 3
    assert api("POST", "/api/projects/B/bibliography", {"update": True})[0] == 400
    assert api("POST", "/api/projects/B/bibliography", {"file": {"name": "x.txt", "text": "hello"}})[0] == 400
    assert api("POST", "/api/projects/B/bibliography", {"zotero": {"library": "../etc"}})[0] == 400
    assert api("POST", "/api/projects/B/bibliography", {})[0] == 400
    st, v = api("DELETE", "/api/projects/B/bibliography", {})
    assert st == 200 and v["bibliography"] is None and v["removed"] == 3

    # Zotero closed: the collections say so plainly; the job says so too
    zotero.mode = "api_off"
    st, err = api("GET", "/api/zotero/collections?library=user")
    assert st == 409 and err["kind"] == "zotero_api_off"
    r = api("POST", "/api/projects/B/bibliography", {"zotero": {"library": "user"}})[1]
    job = api.wait(r["job"]["id"])
    assert job["state"] == "error" and "does not let other programs read it" in job["error"]


def test_the_page_shell_and_documents():
    features = (STATIC / "features.js").read_text()
    assert re.search(r'bibliography: \{\s*section: "project", title: "Bibliography", icon: "library", '
                     r'href: "#/bibliography", ai: "none"', features)
    index = (STATIC / "index.html").read_text()
    assert 'data-route="bibliography"' in index and "/static/v013.css" in index
    assert index.index('data-route="sources"') < index.index('data-route="bibliography"') < index.index('data-route="search"')
    app = (STATIC / "app.js").read_text()
    assert 'renderBibliography } from "./views/bibliography.js"' in app and '"bibliography", renderBibliography]' in app
    reg = (STATIC / "registry.js").read_text()  # 0.13.6: the sidebar's job kinds moved to registry.js
    assert 'bibliography: { icon: "library", text: "Bringing in the bibliography", link: "#/bibliography" }' in reg
    assert "library:" in (STATIC / "icons.js").read_text()
    page = (STATIC / "views" / "bibliography.js").read_text()
    assert "innerHTML" not in page and ".append(null" not in page
    for words in ("Bring in the bibliography", "Allow other applications on this computer to communicate with Zotero",
                  "Same work", "Not the same", "Link a document", "Download the list", "Update from Zotero",
                  "nothing goes over the internet", "Use an exported file instead"):
        assert words in page, words
    sources = (STATIC / "views" / "sources.js").read_text()
    assert 'class: "doc-cite it"' in sources and 'class: "dv-bib"' in sources and "see Bibliography" in sources
    css = (STATIC / "v013.css").read_text()
    defined = defined_tokens()  # 0.13.5: the tokens are in tokens.css
    used = set(re.findall(r"var\((--[a-z0-9-]+)", css))
    assert used and used <= defined, used - defined
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", css)  # colours only through the tokens (light and dark)
    api_md = api_docs()  # 0.13.5: every docs/*API*.md
    from enlens_claims.gui.server import ROUTES

    for _m, rx, name in ROUTES:
        if "bibliography" in name or "zotero" in name:
            path = rx.pattern.strip("^$").replace("([^/]+)", "<p>").replace("\\.(csv|xlsx)", ".xlsx").replace("\\", "")
            assert path.replace("/api/projects/<p>", "") in api_md, path
