"""0.15.1: reader 3 (`reader3.py`): text-only files and books.

A book copied out of a PDF into a text file (as the converters that make `.md` files do: pages apart by a blank line,
every running head, page number and printer's slug still in the text, no headings marked) is made here with known text,
and read with reader 2 and reader 3. Reader 3 sets aside the running heads, the slugs printed twice letter by letter,
the page numbers, the publishing details, the contents, the notes, the bibliography and the index, finds the chapter
headings from the contents and the paragraphs from the line lengths, and keeps every word of the book's own text.
Reader 2 still reads such a file exactly as ENLENS 0.15.0 did.

Also: interview answers that come back are not running heads; a Markdown file without marked headings gets headings;
ligatures broken by a space are joined; words run together are split only in a document that lost its spaces; the
reading report says when a text file looks copied out of a PDF; a reader-2 document moves to reader 3.
"""
from __future__ import annotations

import random
import textwrap
from collections import Counter
from pathlib import Path

from test_app import api, home  # noqa: F401  (fixtures)

from enlens_claims import ingest, measure, reader, reader3, reread
from enlens_claims.store import Workspace

_NOUNS = ("system", "stock", "flow", "feedback loop", "delay", "goal", "river", "forest", "market", "population",
          "company", "budget", "harvest", "climate", "city", "school", "farm", "reservoir", "factory", "household")
_VERBS = ("changes", "shapes", "limits", "drains", "feeds", "balances", "reinforces", "slows", "follows", "explains")
_ADJ = ("slow", "steady", "hidden", "simple", "complex", "resilient", "fragile", "local", "large", "old")


def _sentence(rng: random.Random) -> str:
    a, b, c = rng.choice(_NOUNS), rng.choice(_NOUNS), rng.choice(_NOUNS)
    s = (f"The {rng.choice(_ADJ)} {a} {rng.choice(_VERBS)} the {b} of the {c}, and the {rng.choice(_NOUNS)} "
         f"{rng.choice(_VERBS)} with it when the {rng.choice(_NOUNS)} is {rng.choice(_ADJ)}.")
    return s


def _paragraphs(rng: random.Random, n: int) -> list[str]:
    return [" ".join(_sentence(rng) for _ in range(rng.randint(3, 6))) for _ in range(n)]


def _slug(page: str) -> str:
    """The printer's slug at the foot of a proof page, drawn twice letter by letter, as the PDF had it."""
    return " ".join("".join(ch * 2 for ch in w) for w in f"TIS final pgs {page} 5/2/09 10:37:34".split())


ROMAN = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii"]


def make_book(folder: Path) -> tuple[Path, str, list[str], list[str]]:
    """The book as a .md copied out of its PDF; returns (path, its own text, its paragraphs, what is not its text)."""
    rng = random.Random(15)
    pages: list[list[str]] = []
    boiler: list[str] = []

    def page(lines: list[str], no: str, head: str | None = None) -> None:
        body = ([head] if head else []) + lines + [_slug(no)]
        pages.append(body)
        boiler.append(f"TIS final pgs {no} 5/2/09")
        if head:
            boiler.append(head)

    # front matter: half title, other books, title page, copyright page, dedication, contents
    page(["Systems at Work"], "i")
    page(["Other Books by Ada Example:", "Rivers and Their Keepers: A Field Guide (1989).",
          "The Global Household (1991).", "with Ben Example:", "Toward Steady Budgets (1973)."], "ii")
    page(["Systems at Work", "—— A Primer ——", "Ada Example", "Edited by Cleo Example,", "Example Institute",
          "LONDON • STERLING, VA"], "iii")
    page(["First published by Example Press in the UK in 2009", "Copyright © 2008 by Example Institute.",
          "All rights reserved", "ISBN: 978-1-84407-726-7 (pb)", "Typeset by Dee Setter, Hill Productions",
          "Cover design by Eve Artist", "Tel: +44 (0)20 7841 1930", "Printed in the UK by Example Print Ltd."], "iv")
    page(["FOR DANA", "(1941–2001)", "and for all those who would learn from her"], "v")
    page(["CONTENTS", "A Note from the Author | ix", "Introduction: The Systems Lens | 1",
          "Part One: Structures and Behaviour", "ONE. The Basics | 11", "TWO. A Visit to the Systems Zoo | 35",
          "Notes | 204", "Bibliography of Systems Resources | 208", "About the Author | 213", "Index | 215"], "vi")
    boiler += ["ISBN: 978-1-84407-726-7", "All rights reserved", "Typeset by Dee Setter", "Other Books by Ada Example",
               "FOR DANA", "Toward Steady Budgets", "A Visit to the Systems Zoo 35"]
    own: list[str] = []          # the book's own paragraphs, in order

    def chapter(opening: list[str], paras: list[str], first_no: int, heads: tuple[str, str], roman: bool = False):
        """The chapter's text wrapped at 70 characters, 32 lines a page, a running head on each page after the first
        (left and right pages differ) and the slug at the foot."""
        lines: list[str] = list(opening)
        for p in paras:
            lines += textwrap.wrap(p, 70)
        no = first_no
        first = True
        while lines:
            chunk, lines = lines[:32], lines[32:]
            label = ROMAN[no - 1] if roman else str(no)
            head = None if first else (f"{label} {heads[0]}" if no % 2 == 0 else f"{heads[1]} {label}")
            page(chunk, label, head)
            first = False
            no += 1

    note = _paragraphs(rng, 12)
    chapter(["A NOTE FROM THE AUTHOR"], note, 9, ("A NOTE FROM THE AUTHOR", "A NOTE FROM THE AUTHOR"), roman=True)
    intro = _paragraphs(rng, 16)
    chapter(["Introduction: The Systems Lens"], intro, 1, ("INTRODUCTION", "THE SYSTEMS LENS"))
    pages.append(["PART ONE", "Structures and Behaviour", _slug("9")])
    one = _paragraphs(rng, 22)
    chapter(["— ONE —", "The Basics"], one, 11, ("SYSTEMS AT WORK", "CHAPTER ONE: THE BASICS"))
    two = _paragraphs(rng, 22)
    chapter(["— TWO —", "A Visit to the Systems Zoo"], two, 35, ("SYSTEMS AT WORK", "CHAPTER TWO: THE SYSTEMS ZOO"))
    own += note + intro + one + two
    # end matter
    notes = ["Notes", "Introduction", "1. Russell Ackoff, “The Future Is Past,” Journal of Research 30, no. 2 (1979): 93–104.",
             "2. Idries Shah, Tales of the Dervishes (New York: E. P. Dutton, 1970), 25.", "Chapter One",
             "1. Poul Anderson, quoted in Arthur Koestler, The Ghost in the Machine (New York: Macmillan, 1968), 59."]
    page(notes, "204")
    page(["Bibliography of", "Systems Resources",
          "Bossel, Hartmut. System Zoo Simulation Models. (Norderstedt: Books on Demand, 2007).",
          "Laszlo, Ervin. A Systems View of the World. (Cresskill, NJ: Hampton Press, 1996)."], "208")
    page(["About the Author", "Ada Example was a pioneering environmental scientist, teacher and writer, who "
          "wrote about systems for thirty years."], "213")
    index = ["Index"] + [f"{rng.choice(_NOUNS)} {rng.choice(_ADJ)}, {rng.randint(1, 90)}–{rng.randint(91, 190)}, "
                         f"{rng.randint(191, 200)} {rng.choice(_NOUNS)}, {rng.randint(1, 200)}" for _ in range(30)]
    page(index[:24], "215")
    page(index[24:], "216")
    boiler += ["Tales of the Dervishes", "System Zoo Simulation Models", "pioneering environmental scientist",
               "Russell Ackoff"]
    text = "\n\n".join("\n".join(p) for p in pages) + "\n"
    path = folder / "book.md"
    path.write_text(text, encoding="utf-8")
    return path, "\n".join(own), own, boiler


def _read(path: Path, version: int):
    return reader.build_document(ingest.read_file(path), version=version)


def _kind_of(doc, needle: str) -> str:
    b = next((b for b in doc.blocks if needle in b.text), None)
    assert b is not None, needle
    return b.kind


def test_reader_3_reads_a_book_copied_out_of_its_pdf(tmp_path):
    path, truth, paras, boiler = make_book(tmp_path)
    doc = _read(path, 3)
    f = measure.figures(measure.body_text(doc), truth, boiler)
    assert f["recall"] >= 0.995 and f["precision"] >= 0.99 and f["order"] >= 0.99, f
    assert f["boilerplate_left"] == 0, f
    read = measure.body_text(doc)
    assert "TIS final" not in read and "ffiinnaall" not in read and "CHAPTER ONE" not in read
    # what each part is
    assert _kind_of(doc, "TIS final pgs 12 ") == "furniture"                  # the slug, read once, set aside
    assert _kind_of(doc, "ISBN") == "front" and _kind_of(doc, "FOR DANA") == "front"
    assert _kind_of(doc, "Other Books by") == "front"
    assert _kind_of(doc, "ONE. The Basics") == "contents"
    for h in ("A NOTE FROM THE AUTHOR", "Introduction: The Systems Lens", "The Basics", "A Visit to the Systems Zoo"):
        assert next(b for b in doc.blocks if b.text == h).kind == "heading", h
    assert _kind_of(doc, "Tales of the Dervishes") == "back"                   # the notes
    assert _kind_of(doc, "System Zoo Simulation Models") == "references"       # the bibliography
    assert _kind_of(doc, "pioneering environmental scientist") == "back"       # about the author
    assert sum(1 for b in doc.blocks if b.kind == "index") >= 2
    # paragraphs found from the line lengths: about one block per paragraph, not one per page
    body = [b for b in doc.blocks if b.kind == "body"]
    assert len(body) >= 0.9 * len(paras), (len(body), len(paras))
    rep = doc.reading
    assert rep["reader"] == 3 and rep["repairs"]["doubled"] >= 25
    assert rep["book"]["contents"] == 1 and rep["book"]["chapters"] >= 4
    assert any("copied out of a PDF" in w for w in rep["warnings"]) and rep["quality"] == "fair"
    # the same file reads the same twice
    assert measure.fingerprint(doc) == measure.fingerprint(_read(path, 3))


def test_reader_2_still_reads_it_as_0_15_0_did(tmp_path):
    path, truth, _paras, boiler = make_book(tmp_path)
    doc = _read(path, 2)
    assert doc.reading["reader"] == 2 and "text_layout" not in doc.reading
    assert set(Counter(b.kind for b in doc.blocks)) <= {"body", "caption", "heading", "title"}
    assert measure.figures(measure.body_text(doc), truth, boiler)["boilerplate_left"] > 10
    # the reading of ENLENS 0.15.0, to the byte (its fingerprint, taken with 0.15.0's code)
    assert measure.fingerprint(doc) == READER_2_FINGERPRINT


READER_2_FINGERPRINT = "4747a00de8a42dfb6fd6cdda2a43e1fd18733bb4"  # ENLENS 0.15.0 (reader.py at v0.15.0)


def test_answers_that_come_back_in_an_interview_are_not_running_heads(tmp_path):
    rng = random.Random(3)
    lines = []
    for i in range(160):
        lines.append(f"[I] {_sentence(rng)[:-1]}?")
        lines.append(rng.choice(["[P] Ja.", "[P] Ja, ja.", "[P] Nee.", _sentence(rng)]))
        if rng.random() < 0.3:
            lines.append("[P] Ja.")
    p = tmp_path / "interview.txt"
    p.write_text("\n".join(lines), encoding="utf-8")
    doc = _read(p, 3)
    assert not any(b.kind == "furniture" for b in doc.blocks)
    assert "[P] Ja." in measure.body_text(doc)


def test_running_heads_of_a_journal_copy_and_its_page_numbers(tmp_path):
    rng = random.Random(4)
    out = []
    for pg in range(1, 9):
        out.append(f"Frontiers in Neurology {pg:02d} frontiersin.org")
        out += textwrap.wrap(" ".join(_sentence(rng) for _ in range(14)), 80)
        out.append(str(pg))
        out.append("")
    p = tmp_path / "journal.txt"
    p.write_text("\n".join(out), encoding="utf-8")
    doc = _read(p, 3)
    read = measure.body_text(doc)
    assert "frontiersin.org" not in read
    assert sum(1 for b in doc.blocks if b.kind == "furniture" and reader.furniture_label(b.text) == "Page number") >= 6


def test_a_markdown_file_without_marked_headings_gets_headings(tmp_path):
    rng = random.Random(5)
    body = "\n\n".join(" ".join(_sentence(rng) for _ in range(4)) for _ in range(3))
    p = tmp_path / "plain.md"
    p.write_text(f"Methods\n\n{body}\n\nResults\n\n{body}\n", encoding="utf-8")
    assert {b.text for b in _read(p, 3).blocks if b.kind == "heading"} >= {"Methods", "Results"}
    assert not any(b.kind == "heading" for b in _read(p, 2).blocks)       # reader 2 found none
    marked = tmp_path / "marked.md"
    marked.write_text(f"# One\n\n{body}\n\n# Two\n\n{body}\n\n# Three\n\nResults\n\n{body}\n", encoding="utf-8")
    heads = {b.text for b in _read(marked, 3).blocks if b.kind == "heading"}
    assert heads == {"One", "Two", "Three"}                                 # a file that marks them is believed


def test_ligatures_a_converter_broke_with_a_space_are_joined():
    lines = [reader.Line(0, t) for t in ["We fi nd that the fi rst fi eld was infl uenced by fl ows, said the Sufi s.",
                                         "The staff members fi nd it; turn it off the wall, five fi xes, fi ve fi les."]]
    words = reader3.ligature_words(lines)
    assert words is not None
    c = Counter()
    out = [reader3.join_ligature_gaps(ln.text, words, c) for ln in lines]
    assert out[0] == "We find that the first field was influenced by flows, said the Sufis."
    assert out[1] == "The staff members find it; turn it off the wall, five fixes, five files."
    assert reader3.ligature_words([reader.Line(0, "The staff of the firm took off.")]) is None   # no broken ligatures


def test_words_run_together_are_split_only_where_spaces_were_lost():
    rng = random.Random(6)
    clean = [_sentence(rng) for _ in range(80)] + ["Its background matters, as the healthcare budget does."]
    damaged = [s.replace(" ", "") if i % 3 == 0 else s for i, s in enumerate(clean)]
    text = " ".join(damaged)
    assert reader3.damaged_spacing(text) and not reader3.damaged_spacing(" ".join(clean))
    lines = [reader.Line(0, t) for t in damaged]
    vocab, bigrams = reader._vocabulary(lines), reader._bigrams(lines)
    c = Counter()
    fixed = reader3.split_runs(text, vocab, bigrams, reader._COMMON | reader._CLOSED, c)
    assert measure.figures(fixed, " ".join(clean))["recall"] >= 0.97
    assert "background" in fixed and "healthcare" in fixed and c["words_split"] >= 20
    # an ending is never a word of its own
    v = Counter({"require": 5, "ment": 5, "addition": 5, "al": 9})
    assert reader3.split_runs("requirement additional", v, Counter(), set(), Counter()) == "requirement additional"


def test_the_reading_report_says_when_a_pdf_was_read_without_its_layout():
    warns = reader3.report_warnings({"engine": "pypdf", "text_layout": {}}, "pdf", "plain words " * 200)
    assert any("without its layout" in w for w in warns)
    assert reader3.report_warnings({"engine": "pdfminer"}, "pdf", "plain words " * 200) == []


def test_text_starts_and_ends_where_the_person_says():
    items = [("Title page", "front"), ("Introduction", "heading"), ("First words.", "body"), ("Repeat", "body"),
             ("Repeat", "body"), ("Last words.", "body"), ("Notes", "body"), ("A note.", "body")]
    fps = [reader.block_fp(t) for t, _k in items]
    assert reader.choose_inclusion(items, {}) == [0, 1, 1, 1, 1, 1, 1, 1]
    start = reader.bound_key("start", fps, 1)
    end = reader.bound_key("end", fps, 5)
    assert reader.choose_inclusion(items, {start: 0, end: 0}) == [0, 1, 1, 1, 1, 1, 0, 0]
    # the second of two blocks with the same words is the one meant
    end2 = reader.bound_key("end", fps, 4)
    assert end2.endswith(":1") and reader.choose_inclusion(items, {end2: 0}) == [0, 1, 1, 1, 1, 0, 0, 0]
    # a block the person restored after the end still counts
    assert reader.choose_inclusion(items, {end: 0, fps[7]: 1}) == [0, 1, 1, 1, 1, 1, 0, 1]
    # a mark whose block is no longer there changes nothing
    assert reader.choose_inclusion(items, {"start:0123456789abcdef:0": 0}) == [0, 1, 1, 1, 1, 1, 1, 1]


def _project(api, files):
    api("PUT", "/api/settings", {"backend": "baseline"})
    api("POST", "/api/projects", {"name": "R"})
    for f in files:
        api("POST", f"/api/projects/R/uploads?batch=b1&name={f.name}", raw=f.read_bytes())
    api.wait(api("POST", "/api/projects/R/ingest", {"batch": "b1"})[1]["job"]["id"])
    return api("GET", "/api/projects/R/documents")[1]["documents"]


def test_all_like_this_and_where_the_text_starts_and_ends_in_the_reading_view(api, tmp_path):
    path, _truth, _paras, _boiler = make_book(tmp_path)
    (d,) = _project(api, [path])
    base = f"/api/projects/R/documents/{d['doc_id']}"
    blocks = api("GET", f"{base}?view=blocks&limit=1000")[1]["blocks"]
    slug = next(b for b in blocks if b["text"].startswith("TIS final pgs 12 "))
    assert slug["included"] is False and slug["alike"] >= 30
    passages = api("GET", "/api/projects/R/documents")[1]["documents"][0]["passages"]
    # Restore all like this, then leave them all out again
    st, r = api("PUT", f"{base}/blocks/{slug['n']}", {"included": True, "alike": True})
    assert st == 200 and r["alike"] == slug["alike"] + 1
    blocks = api("GET", f"{base}?view=blocks&limit=1000")[1]["blocks"]
    assert all(b["included"] and b["changed"] for b in blocks if b["text"].startswith("TIS final pgs"))
    st, r = api("PUT", f"{base}/blocks/{slug['n']}", {"included": False, "alike": True})
    blocks = api("GET", f"{base}?view=blocks&limit=1000")[1]["blocks"]
    assert not any(b["included"] or b["changed"] for b in blocks if b["text"].startswith("TIS final pgs"))
    assert api("GET", "/api/projects/R/documents")[1]["documents"][0]["passages"] == passages
    # the text ends where chapter two begins: chapter two is left out; a paragraph restored there still counts
    two = next(b for b in blocks if b["text"] == "A Visit to the Systems Zoo" and b["kind"] == "heading")
    one = next(b for b in blocks if b["text"] == "The Basics" and b["kind"] == "heading")
    last_one = max(b["n"] for b in blocks if b["n"] < two["n"] and b["kind"] == "body")
    st, r = api("PUT", f"{base}/bounds", {"side": "end", "block": last_one})
    assert st == 200 and r["left_out"] >= 20
    blocks = api("GET", f"{base}?view=blocks&limit=1000")[1]["blocks"]
    assert next(b for b in blocks if b["n"] == last_one)["bound"] == "end"
    after = [b for b in blocks if b["n"] > last_one and b["kind"] == "body"]
    assert after and not any(b["included"] for b in after) and all(b["changed"] for b in after)
    keep = after[3]
    api("PUT", f"{base}/blocks/{keep['n']}", {"included": True})
    blocks = api("GET", f"{base}?view=blocks&limit=1000")[1]["blocks"]
    assert next(b for b in blocks if b["n"] == keep["n"])["included"] is True
    assert next(b for b in blocks if b["n"] == keep["n"])["changed"] is True        # "restored by you"
    # the text cannot start after it ends
    assert api("PUT", f"{base}/bounds", {"side": "start", "block": two["n"]})[0] == 400
    assert api("PUT", f"{base}/bounds", {"side": "start", "block": one["n"]})[0] == 200
    blocks = api("GET", f"{base}?view=blocks&limit=1000")[1]["blocks"]
    assert not any(b["included"] for b in blocks if b["n"] < one["n"])
    # undo both: as the reader had it, but for the paragraph restored by hand
    assert api("PUT", f"{base}/bounds", {"side": "end", "block": None})[0] == 200
    assert api("PUT", f"{base}/bounds", {"side": "start", "block": None})[0] == 200
    blocks = api("GET", f"{base}?view=blocks&limit=1000")[1]["blocks"]
    assert all(b["included"] for b in blocks if b["kind"] == "body")
    assert [b["n"] for b in blocks if b["changed"]] == [keep["n"]]          # restored by the person, still says so
    assert api("PUT", f"{base}/bounds", {"side": "middle", "block": 3})[0] == 400
    assert api("PUT", f"{base}/bounds", {"side": "end", "block": 99999})[0] == 404
    assert api("PUT", f"{base}/blocks/{slug['n']}", {"included": True, "alike": "yes"})[0] == 400


def test_a_document_of_reader_2_moves_to_reader_3_with_the_persons_marks(tmp_path, monkeypatch):
    path, _truth, _paras, _boiler = make_book(tmp_path)
    ws = Workspace.create(tmp_path / "ws")
    with monkeypatch.context() as mp:
        mp.setattr(ingest, "READER", 2)
        assert ingest.ingest(ws, [path], ai_access="cloud")["added"] == 1
    doc_id = ws.scalar("SELECT doc_id FROM documents")
    assert ws.scalar("SELECT reader FROM documents") == 2
    assert not ws.scalar("SELECT COUNT(*) FROM blocks WHERE doc_id=? AND kind='furniture'", (doc_id,))
    # the person marked where the text ends (the heading of the notes, by its words), under reader 2
    text = ws.scalar("SELECT text FROM documents")
    rows = ws.query("SELECT n, start, end FROM blocks WHERE doc_id=? ORDER BY n", (doc_id,))
    fps = [reader.block_fp(text[r["start"]:r["end"]]) for r in rows]
    about = next(i for i, r in enumerate(rows) if text[r["start"]:r["end"]].startswith("About the Author"))
    with ws.connect() as cx:
        cx.execute("INSERT INTO block_choices(doc_id, fp, included, kind) VALUES (?,?,0,'bound')",
                   (doc_id, reader.bound_key("end", fps, about - 1)))
    assert reread.check(ws, doc_id)["ok"]
    assert reread.move(ws, doc_id)["moved"] is not None
    assert ws.scalar("SELECT reader FROM documents") == ingest.READER   # 3, and 4 since 0.17.2 (the same for a book)
    kinds = Counter(r[0] for r in ws.query("SELECT kind FROM blocks WHERE doc_id=?", (doc_id,)))
    assert kinds["furniture"] >= 40 and kinds["contents"] and kinds["index"]
    # nothing after the person's mark is read
    text = ws.scalar("SELECT text FROM documents")
    for r in ws.query("SELECT start, end, included FROM blocks WHERE doc_id=? ORDER BY n", (doc_id,)):
        if text[r["start"]:r["end"]].startswith("About the Author"):
            assert r["included"] == 0
