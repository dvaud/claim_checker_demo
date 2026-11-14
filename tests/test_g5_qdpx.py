"""0.18.7 (roadmap G5): the project for NVivo, ATLAS.ti and MAXQDA as a REFI-QDA project (`.qdpx`), and a codebook as
a REFI-QDA codebook (`.qdc`). No AI. The file is checked as a strict reader would: well-formed XML in the right
namespace, the elements in the schema's order, every reference pointing at something that exists, every selection's
offsets inside its text and on the exact words of its quote, and the same GUIDs every time."""
from __future__ import annotations

import re
import uuid
import zipfile
import xml.etree.ElementTree as ET

import pytest

from enlens_claims import claimcheck, home, judgements, notes, profile, qdpx
from enlens_claims.check_results import hypothesis_result
from enlens_claims.llm import BaselineBackend
from enlens_claims.reader import apply_choices, block_fp
from enlens_claims.store import now

NS = {"q": qdpx.NS}
Q = "{%s}" % qdpx.NS
CB = "{%s}" % qdpx.NS_CODEBOOK
# the order of the children the schema allows, per element: REFI-QDA Project Exchange 1.0, Project.xsd (ProjectType,
# CodeType, TextSourceType, NoteType, PlainTextSelectionType, CodingType), checked against the schema on 2026-11-14
ORDER = {
    "Project": ["Users", "CodeBook", "Variables", "Cases", "Sources", "Notes", "Links", "Sets", "Graphs", "Description",
                "NoteRef"],
    "Code": ["Description", "NoteRef", "Code"],
    "TextSource": ["Description", "PlainTextContent", "PlainTextSelection", "Coding", "NoteRef", "VariableValue"],
    "Note": ["Description", "PlainTextContent", "PlainTextSelection", "Coding", "NoteRef", "VariableValue"],
    "PlainTextSelection": ["Description", "Coding", "NoteRef"],
    "Coding": ["CodeRef", "NoteRef"],
}
PAPER = "Water footprint of electrolytic hydrogen in arid export regions"


@pytest.fixture
def project(loaded):
    """The shared corpus with: a check (graded by the offline baseline, not by reading), a person's judgement, a
    person's label and an AI's label, two notes (one on words then left out), and a document no AI may read."""
    ws = loaded
    home.update_settings({"your_name": "Dóra Ábel"})
    paper = ws.scalar("SELECT doc_id FROM documents WHERE title=?", (PAPER,))
    irena = ws.scalar("SELECT doc_id FROM documents WHERE title LIKE 'IRENA%'")
    hid = claimcheck.check_hypothesis(ws, "Hydrogen export hubs raise water stress", BaselineBackend(), "baseline",
                                      k=8, per_doc=4)
    part = hypothesis_result(ws, hid)["parts"][0]
    x = next(x for x in part["passages"] if x["doc_id"] == irena)
    judgements._set_judgement(ws, part["claim_id"], x["passage_id"], "refutes", note="Jobs, not water.")
    p0, p1 = (dict(r) for r in ws.query("SELECT * FROM passages WHERE doc_id=? ORDER BY seq LIMIT 2", (paper,)))
    profile.add_label(ws, "sdg", p0["passage_id"], "6.4", quote="increase water stress in arid regions")
    q = "compete with farming for groundwater"
    i = p0["text"].index(q)
    with ws.connect() as cx:   # a label the AI made (as a label task would write it)
        cx.execute("INSERT INTO labels(label_id, passage_id, doc_id, framework, code, relevance, direction, confidence, "
                   "quote, start, end, page, source, model, reason, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("lab-ai", p0["passage_id"], paper, "sdg", "2.4", "mentioned", "hinders", 0.8, q,
                    p0["start"] + i, p0["start"] + i + len(q), p0["page"], "model", "claude-test-model",
                    "farming and groundwater", now()))
        cx.execute("UPDATE documents SET ai_access='none' WHERE doc_id=?", (irena,))
    text = ws.scalar("SELECT text FROM documents WHERE doc_id=?", (paper,))
    a = text.index("fresh water")
    kept = notes.add(ws, paper, a, a + len("fresh water"), text="Freshwater <demand> & farming")
    b = text.index("desalinated seawater")
    gone = notes.add(ws, paper, b, b + len("desalinated seawater"), text="Check the costs")
    # leave out the block that holds the second passage, as a person's Leave out does
    with ws.connect() as cx:
        blk = cx.execute("SELECT start, end, kind FROM blocks WHERE doc_id=? AND start<? AND end>? AND included=1",
                         (paper, p1["end"], p1["start"])).fetchone()
        cx.execute("INSERT OR REPLACE INTO block_choices(doc_id, fp, included, kind, person_id, at) VALUES (?,?,?,?,?,?)",
                   (paper, block_fp(text[blk[0]:blk[1]]), 0, blk[2], "p000000000001", now()))
        apply_choices(cx, paper)
    assert ws.scalar("SELECT section FROM passages WHERE passage_id=?", (p1["passage_id"],)) == "left_out"
    return {"ws": ws, "hid": hid, "paper": paper, "irena": irena, "p1": p1, "kept": kept, "gone": gone}


def _read(path):
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("project.qde"))
        texts = {n[len("sources/"):]: zf.read(n).decode("utf-8") for n in zf.namelist() if n.startswith("sources/")}
    return root, texts


def _local(tag: str) -> str:
    return tag.split("}", 1)[1]


def _check_order(el):
    allowed = ORDER.get(_local(el.tag))
    if allowed is not None:
        places = [allowed.index(_local(c.tag)) for c in el]   # ValueError: an element the schema does not allow here
        assert places == sorted(places), f"{_local(el.tag)}: {[_local(c.tag) for c in el]}"
    for c in el:
        _check_order(c)


def test_the_project_file_is_one_a_strict_reader_takes(project, tmp_path):
    ws = project["ws"]
    out = tmp_path / "p.qdpx"
    summary = qdpx.export_project(ws, out)
    root, texts = _read(out)
    assert root.tag == Q + "Project" and root.get("name") and root.get("origin", "").startswith("ENLENS")
    _check_order(root)
    every = [e for e in root.iter() if e.get("guid")]
    guids = [e.get("guid") for e in every]
    assert len(guids) == len(set(guids)), "a GUID used twice"
    assert all(uuid.UUID(g) for g in guids)
    users = {u.get("guid"): u.get("name") for u in root.iterfind("q:Users/q:User", NS)}
    codes = {c.get("guid"): c for c in root.iter(Q + "Code")}
    note_ids = {n.get("guid") for n in root.iterfind("q:Notes/q:Note", NS)}
    assert root.get("creatingUserGUID") in users
    for ref in root.iter(Q + "CodeRef"):
        assert ref.get("targetGUID") in codes and codes[ref.get("targetGUID")].get("isCodable") == "true"
    for ref in root.iter(Q + "NoteRef"):
        assert ref.get("targetGUID") in note_ids
    for e in root.iter():
        if e.get("creatingUser"):
            assert e.get("creatingUser") in users
    for c in root.iter(Q + "Code"):
        assert c.get("isCodable") in ("true", "false") and c.get("name")
        assert c.get("color") is None or re.fullmatch(r"#[0-9A-F]{6}", c.get("color"))
    # every document, the one no AI may read too, each with its text file
    sources = root.findall("q:Sources/q:TextSource", NS)
    assert len(sources) == ws.scalar("SELECT COUNT(*) FROM documents") == summary["documents"] == len(texts)
    by_title = {s.get("name"): s for s in sources}
    assert "No AI reads this document." in by_title[next(t for t in by_title if t.startswith("IRENA"))].find(
        "q:Description", NS).text
    for s in sources:
        path = s.get("plainTextPath")
        assert path == f"internal://{s.get('guid')}.txt" and f"{s.get('guid')}.txt" in texts
        text = texts[f"{s.get('guid')}.txt"]
        for sel in s.iterfind("q:PlainTextSelection", NS):
            a, z = int(sel.get("startPosition")), int(sel.get("endPosition"))
            assert 0 <= a < z <= len(text)
            assert sel.get("name") == qdpx._short(text[a:z], 60)   # the offsets are on the words the name shows
    assert summary["codings"] == len(root.findall(".//q:Coding", NS)) and summary["not_placed"] == 0


def _selections(root, texts):
    """[(selection text, its codes' names, user names, NoteRef targets)] of every document."""
    users = {u.get("guid"): u.get("name") for u in root.iterfind("q:Users/q:User", NS)}
    codes = {c.get("guid"): c.get("name") for c in root.iter(Q + "Code")}
    out = []
    for s in root.iterfind("q:Sources/q:TextSource", NS):
        text = texts[f"{s.get('guid')}.txt"]
        for sel in s.iterfind("q:PlainTextSelection", NS):
            a, z = int(sel.get("startPosition")), int(sel.get("endPosition"))
            out.append((text[a:z], [codes[r.get("targetGUID")] for r in sel.iter(Q + "CodeRef")],
                        users[sel.get("creatingUser")], [r.get("targetGUID") for r in sel.iterfind("q:NoteRef", NS)]))
    return out


def test_labels_judgements_and_notes_sit_on_their_exact_words_with_whose_decision(project, tmp_path):
    ws = project["ws"]
    out = tmp_path / "p.qdpx"
    qdpx.export_project(ws, out)
    root, texts = _read(out)
    sels = _selections(root, texts)
    users = {u.get("name") for u in root.iterfind("q:Users/q:User", NS)}
    assert {"Dóra Ábel", "ENLENS AI (baseline)", "ENLENS AI (claude-test-model)"} <= users
    # the person's label and the AI's, on their quotes, each coded by whoever decided it
    mine = next(s for s in sels if s[0] == "increase water stress in arid regions")
    assert mine[1] and mine[1][0].startswith("6.4 ") and mine[2] == "Dóra Ábel"
    ai = next(s for s in sels if s[0] == "compete with farming for groundwater")
    assert ai[1][0].startswith("2.4 ") and ai[2] == "ENLENS AI (claude-test-model)"
    # the judgements that count: the AI's Supports on its quote, the person's Contradicts on the whole excerpt
    res = hypothesis_result(ws, project["hid"])
    counted = [x for p in res["parts"] for x in p["passages"] if x["counted"]]
    assert len(counted) == 2
    sup = next(s for s in sels if s[1] == ["Supports"])
    ref = next(s for s in sels if s[1] == ["Contradicts"])
    ai_x = next(x for x in counted if not x["user_verdict"])
    assert sup[0] == ai_x["quote"] and sup[2] == "ENLENS AI (baseline)"
    you_x = next(x for x in counted if x["user_verdict"])
    assert ref[0] == you_x["text"] and ref[2] == "Dóra Ábel"
    # the judgement not counted (below the strictness) and the excerpt not about it do not go
    assert not any(s[1] == ["Partly supports"] for s in sels)
    hyp = next(c for c in root.iter(Q + "Code") if c.get("name") == "Hydrogen export hubs raise water stress")
    assert [c.get("name") for c in hyp.iterfind("q:Code", NS)] == ["Supports", "Partly supports", "Contradicts"]
    # memos: the note on its words, the note whose words were left out on the document itself, the research log
    note_by_guid = {n.get("guid"): n for n in root.iterfind("q:Notes/q:Note", NS)}
    kept = next(s for s in sels if s[0] == "fresh water")
    assert kept[3] and "Freshwater <demand> & farming" in note_by_guid[kept[3][0]].find("q:PlainTextContent", NS).text
    paper_src = next(s for s in root.iterfind("q:Sources/q:TextSource", NS) if s.get("name") == PAPER)
    on_doc = [r.get("targetGUID") for r in paper_src.iterfind("q:NoteRef", NS)]
    assert len(on_doc) == 1 and note_by_guid[on_doc[0]].get("name") == "Check the costs"
    assert any(n.get("name") == "Research log (ENLENS)" for n in note_by_guid.values())


def test_left_out_text_stays_out_and_the_guids_are_the_same_every_time(project, tmp_path):
    ws = project["ws"]
    a, b = tmp_path / "a.qdpx", tmp_path / "b.qdpx"
    qdpx.export_project(ws, a)
    qdpx.export_project(ws, b)
    (ra, ta), (rb, tb) = _read(a), _read(b)
    assert sorted(e.get("guid") for e in ra.iter() if e.get("guid")) == \
        sorted(e.get("guid") for e in rb.iter() if e.get("guid"))
    assert ta == tb
    left_out = project["p1"]["text"]
    assert all(left_out not in t for t in ta.values())
    assert any("increase water stress in arid regions" in t for t in ta.values())


def test_a_codebook_alone_and_its_codes_share_the_projects_guids(project, tmp_path):
    ws = project["ws"]
    body = qdpx.codebook_xml(ws, "sdg")
    root = ET.fromstring(body)
    assert root.tag == CB + "CodeBook" and root.get("origin", "").startswith("ENLENS")
    assert [_local(c.tag) for c in root] == ["Codes"]
    codable = [c for c in root.iter(CB + "Code") if c.get("isCodable") == "true"]
    assert len(codable) == 169 and len({c.get("guid") for c in root.iter(CB + "Code")}) == len(list(root.iter(CB + "Code")))
    out = tmp_path / "p.qdpx"
    qdpx.export_project(ws, out, framework="sdg")
    proj, _texts = _read(out)
    in_project = {c.get("guid") for c in proj.iter(Q + "Code")}
    assert {c.get("guid") for c in codable} <= in_project
    assert qdpx.export_codebook(ws, "sdg", tmp_path / "sdg.qdc")["codes"] == 169
    with pytest.raises(ValueError):
        qdpx.codebook_xml(ws, "no_such_codebook")


def test_the_source_text_maps_document_offsets_across_left_out_gaps():
    doc = "AAAA\n\nBBBB--CCCC"
    st = qdpx.SourceText(doc, [(0, 4), (12, 16)])     # BBBB-- left out
    assert st.text == "AAAA\n\nCCCC"
    assert st.span(1, 3) == (1, 3) and st.span(12, 16) == (6, 10) and st.span(6, 10) is None
    assert st.span(2, 14) == (2, 8)                    # cut to the passages it falls in
    assert qdpx.SourceText("whole text", [], whole=True).text == "whole text"
    assert qdpx.SourceText("all left out", [], whole=False).text == ""


def test_the_downloads_through_the_app(home_api):  # noqa: F811
    api = home_api
    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    st, body = api("GET", "/api/projects/Demo/export.qdpx")
    assert st == 200
    import io

    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        assert ET.fromstring(zf.read("project.qde")).tag == Q + "Project"
    st, body = api("GET", "/api/projects/Demo/codebooks/sdg.qdc")
    assert st == 200 and ET.fromstring(body).tag == CB + "CodeBook"
    assert api("GET", "/api/projects/Demo/codebooks/nothing.qdc")[0] == 404
    assert api("GET", "/api/projects/Demo/export.qdpx?framework=nothing")[0] == 400


@pytest.fixture
def home_api(tmp_path, monkeypatch):
    import threading

    from test_app import Api

    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from enlens_claims.gui.server import make_server

    srv, app = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token)
    srv.shutdown()
    srv.server_close()


def test_the_command_line(project, tmp_path):
    from enlens_claims import cli

    ws = project["ws"]
    assert cli.main(["--ws", str(ws.root), "export-qdpx", str(tmp_path / "c.qdpx")]) == 0
    assert cli.main(["--ws", str(ws.root), "export-qdc", "sdg", str(tmp_path / "c.qdc")]) == 0
    assert zipfile.is_zipfile(tmp_path / "c.qdpx") and (tmp_path / "c.qdc").read_bytes().startswith(b"<?xml")


def test_control_characters_and_a_hypothesis_note_make_a_valid_file(project, tmp_path):
    """Review of G5: PDF text holds control characters XML 1.0 forbids, in attributes too (titles, selection names);
    a code's NoteRef comes before its child codes."""
    ws = project["ws"]
    with ws.connect() as cx:
        cx.execute("UPDATE documents SET title=? WHERE doc_id=?", ("Water\x02 footprint\x1b report", project["paper"]))
        cx.execute("UPDATE hypotheses SET note=? WHERE hyp_id=?", ("Ask \x01 Jones", project["hid"]))
    out = tmp_path / "c.qdpx"
    qdpx.export_project(ws, out)
    root, _texts = _read(out)                       # parses: no forbidden character got through
    _check_order(root)
    want = qdpx.guid(ws.project_uid(), "hypothesis", project["hid"])
    hyp = next(c for c in root.iter(Q + "Code") if c.get("guid") == want)
    kids = [_local(c.tag) for c in hyp]
    assert "NoteRef" in kids and kids.index("NoteRef") < kids.index("Code")


def test_an_excerpt_with_no_place_today_is_not_coded(project, tmp_path, monkeypatch):
    """Review of G5: an excerpt read before its document was read again has no place in today's text; it is counted
    as not placed, never coded on other words."""
    from enlens_claims import check_results

    ws = project["ws"]
    real = check_results.hypothesis_result

    def moved(ws_, hid, *a, **kw):
        res = real(ws_, hid, *a, **kw)
        for part in res["parts"]:
            for x in part["passages"]:
                x["in_corpus"], x["doc_start"] = False, None
        return res

    monkeypatch.setattr(check_results, "hypothesis_result", moved)
    summary = qdpx.export_project(ws, tmp_path / "m.qdpx")
    assert summary["judgements"] == 0 and summary["not_placed"] >= 1


def test_passages_cut_mid_word_join_again():
    """Review of G5: two passages that touch (a forced cut in a long word) keep the text as it was."""
    st = qdpx.SourceText("abcdef ghi", [(0, 3), (3, 6), (7, 10)])
    assert st.text == "abcdef ghi"
