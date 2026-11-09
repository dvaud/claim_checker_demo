"""0.16 (roadmap F2): notes and highlights on exact words of a document.

- a note's words are checked against the document as every quote is: words not in the text are refused, a selection
  cut inside a word is widened to whole words, and the page is recorded;
- notes are searchable (every word, in the note or the words it marks), by document, colour and person;
- a note can be evidence in a check: the passage holding its words becomes an excerpt judged by the person (a part no
  model reads), with the note's words as their sentence, and the answer counts it; a passage the check shows already
  only gets the judgement; words across two passages, or in text left out of the reading, are refused in words;
- notes follow their words when the document's text changes (read again) and say so when the words are gone; removing a
  document keeps its notes;
- notes travel with the project: a colleague's come in under their name and cannot be changed here.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from enlens_claims import claimcheck, ingest, notes, researchlog
from enlens_claims.store import Workspace

from test_0_14_0_shared_projects import Person, anna_and_ben  # noqa: F401  (fixtures)
from test_app import Api, api, home  # noqa: F401  (fixtures)

DEMO = Path(__file__).resolve().parents[1] / "tools" / "demo_corpus"
WORDS = "commuting emissions"


@pytest.fixture
def demo(tmp_path) -> Workspace:
    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [DEMO])
    return ws


def _doc_with(ws: Workspace, words: str) -> tuple[str, str, int]:
    for doc, text in ws.query("SELECT doc_id, text FROM documents ORDER BY doc_id"):
        i = text.find(words)
        if i >= 0:
            return doc, text, i
    raise AssertionError(words)


def test_a_notes_words_are_the_documents_own(demo):
    doc, text, i = _doc_with(demo, WORDS)
    n = notes.add(demo, doc, i + 2, i + len(WORDS) - 2, None, "Look at the sample size.", "green")  # cut inside words
    assert n["quote"] == WORDS and (n["start"], n["end"]) == (i, i + len(WORDS)) and n["colour"] == "green"
    assert n["text"] == "Look at the sample size." and n["mine"] and not n["lost"] and n["present"]
    h = notes.add(demo, doc, i, i + len(WORDS), WORDS)  # a highlight: no note
    assert h["text"] is None and h["colour"] == "yellow"
    with pytest.raises(ValueError, match="not in the document's text"):
        notes.add(demo, doc, i, i + 20, "words that are nowhere in it at all")
    with pytest.raises(ValueError, match="Select the words"):
        notes.add(demo, doc, 10, 5)
    with pytest.raises(KeyError):
        notes.add(demo, "nodoc", 0, 5)
    assert notes.update(demo, n["note_id"], text="", colour="pink")["text"] is None
    with pytest.raises(ValueError, match="colour"):
        notes.update(demo, n["note_id"], colour="purple")


def test_notes_are_searchable(demo):
    doc, text, i = _doc_with(demo, WORDS)
    notes.add(demo, doc, i, i + len(WORDS), None, "Sample size too small", "blue")
    doc2, text2, j = _doc_with(demo, "productivity")
    notes.add(demo, doc2, j, j + len("productivity"), None, "", "yellow")
    assert notes.search(demo, "size SAMPLE")["total"] == 1          # every word, any order, in the note
    assert notes.search(demo, "productivity")["total"] == 1         # or in the words it marks
    assert notes.search(demo, colour="blue")["total"] == 1
    assert notes.search(demo, doc_id=doc2)["notes"][0]["doc_id"] == doc2
    assert notes.search(demo, "50%_")["total"] == 0
    r = notes.search(demo)
    assert r["total"] == 2 and {d["doc_id"] for d in r["documents"]} == {doc, doc2}
    md = notes.markdown(demo, "Demo")
    assert md.startswith("# Notes: Demo") and "> commuting emissions" in md and "Sample size too small" in md
    assert {row["Words"] for row in notes.table(demo)} == {WORDS, "productivity"}


def test_a_note_as_evidence_in_a_check(demo):
    doc, text, i = _doc_with(demo, WORDS)
    n = notes.add(demo, doc, i, i + len(WORDS), None, "It says less than often claimed.")
    hid = claimcheck.create_hypothesis(demo, "Remote work lowers commuting emissions.")
    cid = claimcheck.new_claim(demo, "Remote work lowers commuting emissions.", hyp_id=hid)
    r = notes.use_as_evidence(demo, n["note_id"], cid, "partially_supports", "less than claimed")
    assert r["new"] and r["hyp_id"] == hid
    res = claimcheck.hypothesis_result(demo, hid)
    ex = [p for part in res["parts"] for p in part["passages"]]
    assert len(ex) == 1 and ex[0]["passage_id"] == r["passage_id"]
    assert ex[0]["user_verdict"] == "partially_supports" and ex[0]["quote"] == WORDS and ex[0]["quote_by"] == "you"
    assert ex[0]["found_by"] == "note" and ex[0]["user_note"] == "less than claimed"
    assert res["status"] == "partially_supported"
    t = demo.query("SELECT task_id, model, status, payload_json FROM tasks WHERE kind='check'")
    assert len(t) == 1 and t[0]["task_id"].endswith(":person") and t[0]["model"] == "person" and t[0]["status"] == "done"
    pl = json.loads(t[0]["payload_json"])
    assert pl["from_note"] == n["note_id"] and pl["passages"][0]["found_by"] == "note"
    # the same passage again: the judgement changes, no second excerpt
    r2 = notes.use_as_evidence(demo, n["note_id"], cid, "supports")
    assert not r2["new"] and demo.scalar("SELECT COUNT(*) FROM tasks WHERE kind='check'") == 1
    assert claimcheck.hypothesis_result(demo, hid)["status"] == "supported"
    e = researchlog.entries(demo, group="checks")["entries"][0]
    assert e["kind"] == "evidence-added" and "as evidence: it supports" in e["text"]
    with pytest.raises(ValueError, match="must be one of"):
        notes.use_as_evidence(demo, n["note_id"], cid, "maybe")


def test_words_across_passages_or_left_out_cannot_be_evidence(demo):
    doc = demo.scalar("SELECT doc_id FROM passages GROUP BY doc_id HAVING COUNT(*) > 1 LIMIT 1")
    p1, p2 = demo.query("SELECT start, end FROM passages WHERE doc_id=? ORDER BY seq LIMIT 2", (doc,))
    text = demo.scalar("SELECT text FROM documents WHERE doc_id=?", (doc,))
    n = notes.add(demo, doc, p1["end"] - 12, p2["start"] + 12)
    hid = claimcheck.create_hypothesis(demo, "Remote work lowers commuting emissions.")
    cid = claimcheck.new_claim(demo, "Remote work lowers commuting emissions.", hyp_id=hid)
    with pytest.raises(ValueError, match="run across two passages"):
        notes.use_as_evidence(demo, n["note_id"], cid, "supports")
    # a note in text no passage holds (left out of the reading)
    with demo.connect() as cx:
        cx.execute("DELETE FROM passages WHERE doc_id=? AND start=?", (doc, p1["start"]))
    m = notes.add(demo, doc, p1["start"], p1["start"] + 30)
    with pytest.raises(ValueError, match="left out of the document's reading"):
        notes.use_as_evidence(demo, m["note_id"], cid, "supports")
    assert text  # the document is still there


def test_notes_follow_their_words_and_stay_when_a_document_goes(demo):
    doc, text, i = _doc_with(demo, WORDS)
    n = notes.add(demo, doc, i, i + len(WORDS), None, "keep me")
    with demo.connect() as cx:  # the text changes before the words (as a new reading may)
        cx.execute("UPDATE documents SET text=? WHERE doc_id=?", ("A new first line.\n\n" + text, doc))
    got = notes.get(demo, n["note_id"])
    assert not got["lost"] and got["start"] == i + 19 and got["quote"] == WORDS
    assert demo.scalar("SELECT start FROM notes WHERE note_id=?", (n["note_id"],)) == i + 19  # written down
    with demo.connect() as cx:
        moved = notes.move(cx, doc, text.replace(WORDS, "c. e."))
    assert moved == {"moved": 0, "lost": 1}
    with demo.connect() as cx:
        cx.execute("UPDATE documents SET text=? WHERE doc_id=?", (text.replace(WORDS, "c. e."), doc))
    assert notes.get(demo, n["note_id"])["lost"]
    title = demo.scalar("SELECT title FROM documents WHERE doc_id=?", (doc,))
    demo.remove_document(doc)
    kept = notes.get(demo, n["note_id"])
    assert not kept["present"] and kept["title"] == title and kept["text"] == "keep me"


def test_notes_travel_with_the_project(anna_and_ben):
    anna, ben = anna_and_ben
    doc, text = anna.ws.query("SELECT doc_id, text FROM documents WHERE text LIKE '%water%' LIMIT 1")[0]
    i = text.index("water")
    with anna:
        a1 = notes.add(anna.ws, doc, i, i + 5, None, "Anna's note")
        a2 = notes.add(anna.ws, doc, i, i + 5, None, "to remove")
    with ben:
        b1 = notes.add(ben.ws, doc, i, i + 5, None, "Ben's note")
    rep = ben.bring_in(anna.send())
    assert rep["notes"] == 2
    with ben:
        got = {n["note_id"]: n for n in notes.search(ben.ws)["notes"]}
        assert got[a1["note_id"]]["who"] == "Anna" and not got[a1["note_id"]]["mine"]
        assert got[b1["note_id"]]["mine"]
        with pytest.raises(PermissionError):
            notes.update(ben.ws, a1["note_id"], text="Ben's now")
    with anna:
        notes.remove(anna.ws, a2["note_id"])
        notes.update(anna.ws, a1["note_id"], text="Anna's note, changed")
    ben.bring_in(anna.send())
    with ben:
        got = {n["note_id"]: n for n in notes.search(ben.ws)["notes"]}
        assert a2["note_id"] not in got and got[a1["note_id"]]["text"] == "Anna's note, changed"
        notes.remove(ben.ws, b1["note_id"])
    ben.bring_in(anna.send())
    with ben:
        assert b1["note_id"] not in {n["note_id"] for n in notes.search(ben.ws)["notes"]}


def test_notes_through_the_app(api, tmp_path):  # noqa: F811
    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    for f in sorted(DEMO.iterdir()):
        if f.suffix in (".txt", ".html"):
            assert api("POST", f"/api/projects/Demo/uploads?batch=b1&name={f.name}", raw=f.read_bytes())[0] == 200
    assert api.wait(api("POST", "/api/projects/Demo/ingest", {"batch": "b1"})[1]["job"]["id"])["state"] == "done"
    from enlens_claims import home as home_mod

    ws = home_mod.open_project("Demo")
    doc, text, i = _doc_with(ws, WORDS)
    st, r = api("POST", "/api/projects/Demo/notes", {"doc_id": doc, "start": i, "end": i + len(WORDS), "quote": WORDS,
                                                    "text": "a note", "colour": "blue"})
    assert st == 200 and r["note"]["colour"] == "blue"
    nid = r["note"]["note_id"]
    assert api("POST", "/api/projects/Demo/notes", {"doc_id": doc, "start": "x", "end": 3})[0] == 400
    st, r = api("GET", f"/api/projects/Demo/documents/{doc}/notes")
    assert st == 200 and [n["note_id"] for n in r["notes"]] == [nid] and r["colours"] == list(notes.COLOURS)
    assert api("GET", "/api/projects/Demo/documents/nodoc/notes")[0] == 404
    st, r = api("PUT", f"/api/projects/Demo/notes/{nid}", {"text": "changed"})
    assert st == 200 and r["note"]["text"] == "changed"
    assert api("GET", "/api/projects/Demo/notes?q=changed")[1]["total"] == 1
    st, body = api("GET", "/api/projects/Demo/notes.md")
    assert st == 200 and b"changed" in body
    import openpyxl

    st, body = api("GET", "/api/projects/Demo/notes.xlsx")
    assert openpyxl.load_workbook(io.BytesIO(body)).sheetnames[0] == "Notes"
    hid = claimcheck.create_hypothesis(ws, "Remote work lowers commuting emissions.")
    cid = claimcheck.new_claim(ws, "Remote work lowers commuting emissions.", hyp_id=hid)
    st, r = api("POST", f"/api/projects/Demo/notes/{nid}/evidence", {"claim_id": cid, "verdict": "supports"})
    assert st == 200 and r["new"] and r["hyp_id"] == hid
    assert api("POST", f"/api/projects/Demo/notes/{nid}/evidence", {"claim_id": "nope", "verdict": "supports"})[0] == 404
    with ws.connect() as cx:
        cx.execute("UPDATE notes SET person_id='p0123456789ab' WHERE note_id=?", (nid,))
    assert api("DELETE", f"/api/projects/Demo/notes/{nid}")[0] == 403
