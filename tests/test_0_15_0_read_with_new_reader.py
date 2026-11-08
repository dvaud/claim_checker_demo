"""0.15 (roadmap A0): Read with the new reader. A document read by reader 1 is read again by reader 2 and every result
in it moves to the same words in the new text (reread.py):

- a check keeps the excerpt it showed, and its quote lands on the same words (the same occurrence) in the new text;
  the result page and the Excel export show the same words with the highlight inside them;
- a person's judgement and the sentence they pointed to move with it; a later answer (a stronger model reading the
  round again) is placed in the new text too;
- labels (the AI's and a person's) move with the reviews of them; keyword labels are made again;
- a theme run keeps the passages that map one to one, and is out of date otherwise (up to date when all do);
- tasks not answered yet are dropped; answered ones are kept under ids that never name another passage;
- no row anywhere names a passage id of the document that now means other text;
- what cannot be placed is reported, with where it was, and points nowhere;
- a preview writes nothing, a move is all or nothing;
- `check` refuses a changed original, a missing one, a document already on the new reader and one whose tasks wait
  for Claude Code;
- a person's corrections of the document's blocks are applied after moving;
- a move never changes which judgements count (a check by a model and one by queue answered by the fake Claude Code,
  on the dev server's Reading paper), also when a quote now sits in text the new reader leaves out, which the report
  lists; a table read as a stream by reader 1 is found in reader 2's table; a result with no place says where its
  words went when that can be told; the report's words; a 30-page paper previews and moves in a few seconds.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from enlens_claims import claimcheck, ingest, pdfmake, profile, reread, tasks, themes
from enlens_claims.store import Workspace
from enlens_claims.textutil import normalise

HEAD = "Journal of Arid Hydrogen Studies 12 (2026) 45-67"
_SYL = ["ar", "bel", "cor", "dun", "el", "fen", "gar", "hol", "ist", "jun", "kel", "lor"]
SITES = [(_SYL[i % 12] + _SYL[(5 * i + 3) % 12] + "a").capitalize() for i in range(36)]


def _para(i: int) -> str:
    s = SITES[i]
    return (f"The electrolysers planned at {s} would draw {120 + 7 * i} cubic metres of water a day for hydrogen. "
            f"Farmers near {s} fear that the long-term supply of water will fall as the plant grows. "
            f"The operator says desalination at {s} will cover {40 + i} per cent of the demand by {2030 + i}.")


def _paper(folder: Path) -> Path:
    """Two columns, a running head and page numbers on every page: reader 1 reads the head and the page number into
    the text, reader 2 sets them aside."""
    fl = pdfmake.Flow(columns=[(56, 230), (310, 230)], running_head=HEAD, page_numbers=True)
    for i in range(len(SITES)):
        fl.paragraph(_para(i))
    path = folder / "paper.pdf"
    fl.write(path)
    return path


def _add(ws: Workspace, monkeypatch, path: Path, reader: int = 1) -> str:
    """Add a file as it was added before 0.15 (reader 1), Claude allowed to read it."""
    with monkeypatch.context() as mp:
        mp.setattr(ingest, "READER", reader)
        st = ingest.ingest(ws, [path], ai_access="cloud")
    assert st["added"] == 1, st
    return ws.scalar("SELECT doc_id FROM documents WHERE path=?", (str(path),))


@pytest.fixture
def paper(tmp_path, monkeypatch):
    ws = Workspace.create(tmp_path / "ws")
    doc = _add(ws, monkeypatch, _paper(tmp_path))
    assert ws.scalar("SELECT reader FROM documents WHERE doc_id=?", (doc,)) == 1
    return ws, doc


def _check(ws: Workspace, grades: list[tuple[str, str]]) -> tuple[str, dict]:
    """A check by a Claude chat whose round shows every passage; `grades` are (quote, verdict): each passage holding a
    quote is graded with it. Returns the check id and {quote: passage id}."""
    r = claimcheck.open_check(ws, "Hydrogen plants need water in arid regions", terms=["hydrogen", "water"], k=60,
                              per_doc=60)
    cid = r["check_id"]
    pay = json.loads(ws.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (f"check:{cid}",)))["passages"]
    out, gs = {}, []
    for q, verdict in grades:
        n = next(i for i, p in enumerate(pay, 1) if q in p["text"])
        out[q] = pay[n - 1]["passage_id"]
        gs.append({"passage": n, "verdict": verdict, "confidence": 0.9, "quote": q})
    assert claimcheck.submit_grades(ws, cid, gs, "Read.")["accepted"]
    return cid, out


def _item(res: dict, quote: str) -> dict:
    return next(x for x in res["passages"] if x["quote"] == quote)


def _occurrence(text: str, words: str, at: int) -> int:
    """Which occurrence of `words` (the same words, typography, spacing and hyphens aside) starts at `at` (1-based),
    or 0."""
    hits = [a for a, _b in reread._Finder(text).all(words)]
    return hits.index(at) + 1 if at in hits else 0


def _same(a: str, b: str) -> bool:
    """The same words: case, typography, spacing, hyphens and table cell bars aside."""
    return reread._packed(a) == reread._packed(b)


Q_WATER = f"Farmers near {SITES[3]} fear that the long-term supply"
Q_DESAL = f"desalination at {SITES[20]} will cover"
Q_JUDGE = f"would draw {120 + 7 * 20} cubic metres of water a day"


# --- a check ------------------------------------------------------------------------------------------------------
def test_a_moved_check_keeps_its_excerpt_and_its_quote_lands_on_the_same_words(paper):
    ws, doc = paper
    cid, at = _check(ws, [(Q_WATER, "supports"), (Q_DESAL, "partially_supports")])
    old_text = ws.scalar("SELECT text FROM documents")
    before = claimcheck.result(ws, cid)
    old_v = {r["quote"]: dict(r) for r in ws.query("SELECT * FROM verifications WHERE quote IS NOT NULL")}
    rows_before = claimcheck.export_table(ws, hyp_ids=[cid])

    rep = reread.move(ws, doc)
    assert rep["moved"] and rep["reader"] == 1 and rep["new_reader"] == ingest.READER
    assert ws.scalar("SELECT reader FROM documents") == ingest.READER
    new_text = ws.scalar("SELECT text FROM documents")
    assert HEAD not in new_text.split("\n")[1:3]  # reader 2 set the running head apart (a block of its own)

    after = claimcheck.result(ws, cid)
    for q in (Q_WATER, Q_DESAL):
        b, a = _item(before, q), _item(after, q)
        assert b["counted"] and a["counted"] and a["verdict"] == b["verdict"]  # it still counts, as before
        assert a["text"] == b["text"]                       # the excerpt it showed is its record
        assert a["text"][a["quote_start"]:a["quote_end"]] == q  # the highlight is inside it, on the quote
        assert a["earlier_reading"] and a["earlier_reader"] == 1 and a["in_corpus"] and not a["not_placed"]
        v = ws.query("SELECT * FROM verifications WHERE quote=?", (q,))[0]
        assert _same(new_text[v["start"]:v["end"]], q)       # its pointer: the same words in the new text
        # ... the same occurrence of them
        o = old_v[q]
        now_words = new_text[v["start"]:v["end"]]
        assert _occurrence(old_text, q, o["start"]) == _occurrence(new_text, now_words, v["start"]) > 0
        # the page now: the new passage holding the quote, the page of the quote
        p = ws.query("SELECT * FROM passages WHERE passage_id=?", (v["passage_id"],))[0]
        assert p["start"] <= v["start"] < p["end"] and v["page"] == ingest.page_of(v["start"], [
            (r[0], r[1]) for r in ws.query("SELECT start, end FROM pages WHERE doc_id=? ORDER BY page", (doc,))])
        # the way into the document lands on the quote (doc_start + quote_start, as the page computes it)
        assert _same(new_text[a["doc_start"] + a["quote_start"]:a["doc_start"] + a["quote_end"]], q)
        assert a["location"] and a["location"].startswith("page ")
    assert after["status"] == before["status"]
    # the Excel export shows the same excerpts and quotes
    rows_after = claimcheck.export_table(ws, hyp_ids=[cid])
    key = ("Quote", "Excerpt (the text the AI read)", "Judgement")
    assert sorted(tuple(r[k] for k in key) for r in rows_after) == sorted(tuple(r[k] for k in key) for r in rows_before)
    assert rep["counts"]["check"]["moved"] >= 2


def test_a_judgement_and_its_sentence_move_and_a_later_answer_is_placed_in_the_new_text(paper):
    ws, doc = paper
    cid, at = _check(ws, [(Q_WATER, "supports")])
    pid = next(p for p in (r["passage_id"] for r in ws.query("SELECT passage_id FROM passages"))
               if Q_JUDGE in ws.scalar("SELECT text FROM passages WHERE passage_id=?", (p,)))
    shown = [p["passage_id"] for p in claimcheck.result(ws, cid)["passages"]]
    assert pid in shown
    claimcheck.set_judgement(ws, cid, pid, "refutes", "Not in this region.", quote=Q_JUDGE)
    reread.move(ws, doc)
    text = ws.scalar("SELECT text FROM documents")
    j = ws.query("SELECT * FROM judgements WHERE claim_id=?", (cid,))
    assert len(j) == 1 and j[0]["verdict"] == "refutes" and j[0]["note"] == "Not in this region."
    assert _same(text[j[0]["start"]:j[0]["end"]], Q_JUDGE)
    v = ws.query("SELECT * FROM verifications WHERE subject_id=? AND passage_id=?", (cid, j[0]["passage_id"]))[0]
    assert v["user_verdict"] == "refutes" and v["user_quote"] == Q_JUDGE and _same(text[v["user_start"]:v["user_end"]],
                                                                                   Q_JUDGE)
    it = next(x for x in claimcheck.result(ws, cid)["passages"] if x["passage_id"] == j[0]["passage_id"])
    assert it["quote_by"] == "you" and it["text"][it["quote_start"]:it["quote_end"]] == Q_JUDGE
    assert it["verdict"] == "refutes" and it["judged_by"] == "you"
    # the person changes the sentence, choosing it in the excerpt as it was shown
    from enlens_claims.textutil import split_sentences

    other = next(it["text"][a:b] for a, b in split_sentences(it["text"])
                 if Q_JUDGE not in it["text"][a:b] and "45-67" not in it["text"][a:b] and b - a > 40)
    claimcheck.set_judgement(ws, cid, j[0]["passage_id"], "refutes", "Not in this region.", quote=other)
    j2 = ws.query("SELECT * FROM judgements WHERE claim_id=?", (cid,))[0]
    assert j2["quote"] == other and _same(text[j2["start"]:j2["end"]], other)
    # a stronger model reads the round again (an answer stored after the move): its quote is placed in the new text
    tid = f"check:{cid}"
    pay = json.loads(ws.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (tid,)))["passages"]
    n = next(i for i, p in enumerate(pay, 1) if Q_WATER in p["text"])
    q2 = f"Farmers near {SITES[3]} fear"
    ok, errs = tasks.ingest_result(ws, tid, {"evidence": [{"passage": n, "verdict": "supports", "confidence": 0.95,
                                                            "quote": q2}], "rationale": "Again."}, model="stronger")
    assert ok, errs
    v = ws.query("SELECT * FROM verifications WHERE subject_id=? AND quote=?", (cid, q2))[0]
    assert _same(text[v["start"]:v["end"]], q2)
    assert v["ai_history_json"] and "long-term" in v["ai_history_json"]  # the first reading is kept, as always


def test_a_quote_said_several_times_in_an_excerpt_lands_on_the_same_occurrence(paper):
    """Every paragraph says "fear that the long-term supply of water will fall": an excerpt holds it several times,
    and the grade's quote must land on the occurrence it was on, not the first one in the new text near it."""
    ws, doc = paper
    old_text = ws.scalar("SELECT text FROM documents")
    r = claimcheck.open_check(ws, "Farmers fear for water", terms=["farmers", "water"], k=60, per_doc=60)
    cid = r["check_id"]
    pay = json.loads(ws.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (f"check:{cid}",)))["passages"]
    q = "fear that the long-term supply of water will fall"
    # an excerpt in the middle of the document holding the words several times; the quote is the first in it
    n, item = next((i, p) for i, p in enumerate(pay, 1)
                   if p["text"].count(q) >= 2 and old_text.index(p["text"]) > len(old_text) // 3)
    assert claimcheck.submit_grades(ws, cid, [{"passage": n, "verdict": "supports", "confidence": 0.9, "quote": q}],
                                    "x")["accepted"]
    v0 = ws.query("SELECT * FROM verifications WHERE quote IS NOT NULL")[0]
    k_old = _occurrence(old_text, q, v0["start"])
    assert k_old > 2
    reread.move(ws, doc)
    text = ws.scalar("SELECT text FROM documents")
    v = ws.query("SELECT * FROM verifications WHERE quote IS NOT NULL")[0]
    assert _occurrence(text, q, v["start"]) == k_old
    it = next(x for x in claimcheck.result(ws, cid)["passages"] if x["quote"] == q)
    assert it["text"][it["quote_start"]:it["quote_end"]] == q and it["doc_start"] + it["quote_start"] == v["start"]


def test_a_quote_whose_passage_is_lost_is_not_placed_where_the_same_words_stand_elsewhere():
    """An old passage none of whose text is in the new reading (garbled by reader 1): its quote is placed only where
    it is expected, never at the same words somewhere else in the document."""
    para = [f"Sentence number {w} of the report talks about hydrogen and water in a dry place." for w in
            ("one", "two", "three", "four", "five", "six", "seven", "eight")]
    old_text = " ".join(para[:4]) + " Qzx vbn the plant will double its output qwp zzx. " + " ".join(para[4:])
    a = len(" ".join(para[:4])) + 1
    old = [reread._P("d:0000", 0, 0, a - 1, old_text[:a - 1], "body", None),
           reread._P("d:0001", 1, a, a + 50, old_text[a:a + 50], "body", None),
           reread._P("d:0002", 2, a + 51, len(old_text), old_text[a + 51:], "body", None)]
    far = " ".join(para) + " " + "Filler sentence about something else entirely, said again. " * 40
    new_text = far + "In the summary, the plant will double its output by the end of the decade."
    new = [reread._P("d:0000", 0, 0, len(new_text), new_text, "body", None)]
    m = reread._Map(old_text, old, new_text, new, [(0, len(new_text))], True)
    assert "d:0001" not in m.regions  # nothing of the garbled passage was found
    assert m.place("the plant will double its output", a + 9, "d:0001") is None  # the same words, elsewhere
    near = " ".join(para[:4]) + " The plant will double its output soon. " + " ".join(para[4:])
    m2 = reread._Map(old_text, old, near, [reread._P("d:0000", 0, 0, len(near), near, "body", None)],
                     [(0, len(near))], True)
    got = m2.place("the plant will double its output", a + 9, "d:0001")
    assert got and near[got[0]:got[1]].lower() == "the plant will double its output"


# --- what counts does not change -----------------------------------------------------------------------------------
def _counting(ws: Workspace, hyp: str) -> tuple:
    r = claimcheck.hypothesis_result(ws, hyp)
    items = sorted((p["text"], p["quote"] or "", p["verdict"] or "", p["counted"]) for part in r["parts"]
                   for p in part["passages"])
    return r["status"], items


def test_a_move_never_changes_which_judgements_count(tmp_path, monkeypatch):
    """The Reading project of tools/dev_server.py: the known-text paper with front and back matter, added by reader 1,
    checked by a model (as the dev server seeds it) and by queue (answered by the fake Claude Code, as with
    --claude-code). After the move every excerpt has the same judgement and counts (or not) as before, wherever its
    quote now is (front matter included), and so does the answer."""
    import fake_claude_code as fcc
    import fake_servers

    from enlens_claims import home, measure, taskqueue
    from enlens_claims.llm import OllamaBackend

    case = next(c for c in measure.make_known_texts(tmp_path / "k") if c.name.startswith("d_"))
    ws = home.create_project("R")
    doc = _add(ws, monkeypatch, case.path)
    srv, url = fake_servers.start("ollama")
    try:
        srv.delay, srv.varied = 0.0, True
        hyp = "Coastal residents overestimate how fast their cliffs retreat."
        by_model = claimcheck.check_hypothesis(ws, hyp, OllamaBackend(base_url=url), fake_servers.FAKE_MODEL)
        by_queue = claimcheck.queue_check(ws, hyp, taskqueue.router(ws))
        for _ in range(4):
            fcc.FakeClaudeCode(fcc.DirectTools(), wrong_first=False).run("R")
        # a person's own judgement of an excerpt the AI found not about it, and a grade quoting the authors' names
        cid = ws.scalar("SELECT claim_id FROM user_claims WHERE hyp_id=?", (by_queue,))
        unjudged = [v for v in ws.query("SELECT * FROM verifications WHERE subject_id=?", (cid,)) if not v["quote"]]
        if unjudged:
            claimcheck.set_judgement(ws, cid, unjudged[0]["passage_id"], "supports", "Mine.")
        before = {h: _counting(ws, h) for h in (by_model, by_queue)}
        assert all(st != "waiting" for st, _ in before.values()), before
        assert any(c for _st, items in before.values() for *_x, c in items)  # something counts
        rep = reread.move(ws, doc)
        after = {h: _counting(ws, h) for h in (by_model, by_queue)}
        assert after == before
        # the case the UI review found: the model's quote is the authors' block, which reader 2 sets aside; it moves
        # there, still counts, and the report says where it is now (only excerpts with a judgement are listed)
        from enlens_claims.reader import KIND_TEXT

        front = [e for e in rep["left_out"] if e["left_out_kind"] == KIND_TEXT["front"]]
        assert front and front[0]["quote"].startswith("Katalin Marsh")
        quotes = {q for _st, items in after.values() for _t, q, _v, _c in items if q}
        assert all(any(q.startswith(e["quote"][:60]) for q in quotes) for e in rep["left_out"])
        it = next(p for part in claimcheck.hypothesis_result(ws, by_model)["parts"] for p in part["passages"]
                  if (p["quote"] or "").startswith("Katalin Marsh"))
        assert it["counted"] and it["in_corpus"]
    finally:
        srv.shutdown()


def test_a_result_now_in_text_the_new_reader_leaves_out_counts_as_before_and_is_reported(paper):
    """Reader 1 read the running head into the body text; reader 2 sets it apart as page furniture. A grade quoting
    it moves onto it, still counts, and the report says where it is now."""
    ws, doc = paper
    head = "Journal of Arid Hydrogen Studies"
    cid, at = _check(ws, [(head, "supports"), (Q_WATER, "supports")])
    before = _counting(ws, cid)
    pv = reread.preview(ws, doc)
    lo = [e for e in pv["left_out"] if e["kind"] == "check"]
    from enlens_claims.reader import KIND_TEXT

    furniture = KIND_TEXT["furniture"]
    assert len(lo) == 1 and lo[0]["left_out_kind"] == furniture and lo[0]["quote"] == head
    assert lo[0]["note"] == (f"This excerpt's words are in the {furniture}, which the new reader leaves out of "
                             "searches; the check keeps it, and its judgement counts as before.")
    assert pv["counts"]["check"]["left_out"] == 1 and lo[0]["page"] in (1, 2, 3)
    assert any("leaves out of searches" in w for w in pv["warnings"])
    rep = reread.move(ws, doc)
    assert rep["left_out"] == pv["left_out"]
    assert _counting(ws, cid) == before
    v = ws.query("SELECT * FROM verifications WHERE quote=?", (head,))[0]
    assert ws.scalar("SELECT section FROM passages WHERE passage_id=?", (v["passage_id"],)) == "left_out"
    text = ws.scalar("SELECT text FROM documents")
    assert text[v["start"]:v["end"]] == head
    it = _item(claimcheck.result(ws, cid), head)
    assert it["counted"] and it["in_corpus"] and not it["not_placed"]


def test_a_table_read_as_a_stream_by_reader_1_is_found_in_reader_2s_table(tmp_path, monkeypatch):
    """Reader 1 read a table's cells as a stream of words; reader 2 keeps the table with " | " between its cells."""
    from enlens_claims import measure

    case = next(c for c in measure.make_known_texts(tmp_path / "k") if c.name.startswith("e_"))
    ws = Workspace.create(tmp_path / "ws")
    doc = _add(ws, monkeypatch, case.path)
    q = "Riverside 2.4 41 per cent 52"
    pid = _pid_with(ws, q)
    profile.add_label(ws, "sdg", pid, "4.1", quote=q)
    rep = reread.move(ws, doc)
    lab = ws.query("SELECT * FROM labels WHERE source='person'")[0]
    text = ws.scalar("SELECT text FROM documents")
    assert _same(text[lab["start"]:lab["end"]], q) and "|" in text[lab["start"]:lab["end"]]
    from enlens_claims.reader import KIND_TEXT

    assert [e["left_out_kind"] for e in rep["left_out"]] == [KIND_TEXT["table"]]


def test_where_the_words_of_a_result_with_no_place_went_is_said_when_it_can_be_told():
    para = [f"Sentence number {w} of the report talks about hydrogen and water in a dry place." for w in
            ("one", "two", "three", "four", "five", "six")]
    old_text = " ".join(para[:3]) + " Water use grew by a third. " + " ".join(para[3:])
    old = [reread._P("d:0000", 0, 0, len(old_text), old_text, "body", 1)]
    block = "Table 2. Water / use / grew / by a third"
    new_text = " ".join(para[:3]) + "\n" + block + "\n" + " ".join(para[3:])
    a = new_text.index(block)
    new = [reread._P("d:0000", 0, 0, a - 1, new_text[:a - 1], "body", 1),
           reread._P("d:0001", 1, a, a + len(block), block, "left_out", 1),
           reread._P("d:0002", 2, a + len(block) + 1, len(new_text), new_text[a + len(block) + 1:], "body", 1)]
    m = reread._Map(old_text, old, new_text, new, [(0, len(new_text))], True)
    m.set_blocks([(0, a - 1, "body", True), (a, a + len(block), "table", False),
                  (a + len(block) + 1, len(new_text), "body", True)])
    q = "Water use grew by a third"
    assert m.place(q, old_text.index(q), "d:0000") is None  # the table writes it with slashes between the cells
    assert m.words_left_out(q, old_text.index(q), "d:0000") == "table"
    assert m.words_left_out("Sentence number nine of nothing", 0, "d:0000") is None
    from enlens_claims.reader import KIND_TEXT

    plan = reread._Plan()
    plan.miss("label", "Code 6.4", q, None, None, "gone", 1, "back")
    plan.miss("label", "Code 6.5", q, None, None, "gone", 1, None)
    words = KIND_TEXT["back"]
    assert plan.not_placed[0]["why"] == f"Its words are in the {words}, which the new reader sets aside."
    assert plan.not_placed[0]["left_out_kind"] == words
    assert plan.not_placed[1]["why"] == reread.WHY["gone"] and plan.not_placed[1]["left_out_kind"] is None


def test_the_report_says_in_plain_words_what_has_no_place():
    def warn(n):
        rep = {"not_placed": [{}] * n, "left_out": [], "addons": [], "reading": {}, "warnings": [],
               "themes": {"runs_out_of_date": 0}}
        reread._warnings(rep, {})
        return rep["warnings"]

    assert warn(0) == []
    assert warn(1) == ["1 result has no place in the new reading (listed below). It is kept as it was, but no longer "
                       "points at any words in the text."]
    assert warn(3) == ["3 results have no place in the new reading (listed below). They are kept as they were, but no "
                       "longer point at any words in the text."]


def test_preview_and_move_take_a_few_seconds_for_a_long_pdf(tmp_path, monkeypatch):
    """The page waits for them: a 30-page paper in two columns with 40 graded excerpts and its keyword labels."""
    import time

    fl = pdfmake.Flow(columns=[(56, 230), (310, 230)], running_head=HEAD, page_numbers=True)
    for k in range(14):
        for i in range(len(SITES)):
            fl.paragraph(_para(i).replace("electrolysers", f"electrolysers (phase {k})"))
    path = tmp_path / "long.pdf"
    fl.write(path)
    ws = Workspace.create(tmp_path / "ws")
    doc = _add(ws, monkeypatch, path)
    assert ws.scalar("SELECT n_pages FROM documents") >= 30
    r = claimcheck.open_check(ws, "Hydrogen plants need water", terms=["hydrogen", "water"], k=40, per_doc=40)
    grades = [{"passage": p["n"], "verdict": "supports", "confidence": 0.9, "quote": " ".join(p["text"].split()[20:28])}
              for p in r["passages"]]
    assert claimcheck.submit_grades(ws, r["check_id"], grades, "x")["accepted"]
    profile.keyword_pass(ws, "sdg")
    reread._READINGS.clear()
    t0 = time.time()
    pv = reread.preview(ws, doc)
    t1 = time.time()
    rep = reread.move(ws, doc)
    t2 = time.time()
    assert pv["counts"]["check"]["moved"] >= 35 and rep["moved"]
    assert t1 - t0 < 8 and t2 - t1 < 4, (t1 - t0, t2 - t1)  # the move reuses the preview's reading


# --- labels -------------------------------------------------------------------------------------------------------
def _pid_with(ws, words: str) -> str:
    return next(r[0] for r in ws.query("SELECT passage_id, text FROM passages ORDER BY seq") if words in r[1])


def test_labels_of_the_ai_and_of_a_person_move_with_their_reviews(paper):
    ws, doc = paper
    q_model = f"desalination at {SITES[10]} will cover"
    q_person = f"planned at {SITES[25]} would draw"
    pm, pp = _pid_with(ws, q_model), _pid_with(ws, q_person)
    profile.make_label_tasks(ws, "sdg", [pm], "test-model")
    ok, errs = tasks.ingest_result(ws, f"label:sdg:{pm}", {"labels": [
        {"code": "6.4", "relevance": "main", "direction": "helps", "confidence": 0.9, "quote": q_model,
         "reason": "water use"}]}, model="test-model")
    assert ok, errs
    lm = ws.scalar("SELECT label_id FROM labels WHERE source='model'")
    profile.set_label(ws, lm, "change", relevance="mentioned", note="Only in passing.")
    lp = profile.add_label(ws, "sdg", pp, "7.2", quote=q_person)
    profile.set_label(ws, lp, "accept")
    # a keyword label nobody reviewed (made again later) and one a person rejected (moved with its passage)
    profile.keyword_pass(ws, "sdg")
    kw = ws.query("SELECT label_id, passage_id FROM labels WHERE source IN ('keywords','meaning','both')")
    assert kw
    profile.set_label(ws, kw[0]["label_id"], "reject")
    # a label task not answered yet: dropped, asked again for the new passages
    other = next(r[0] for r in ws.query("SELECT passage_id FROM passages ORDER BY seq") if r[0] not in (pm, pp))
    profile.make_label_tasks(ws, "sdg", [other], "test-model")

    rep = reread.move(ws, doc)
    text = ws.scalar("SELECT text FROM documents")
    m = ws.query("SELECT * FROM labels WHERE source='model'")[0]
    p = ws.query("SELECT * FROM labels WHERE source='person'")[0]
    for lab, q, code in ((m, q_model, "6.4"), (p, q_person, "7.2")):
        assert _same(text[lab["start"]:lab["end"]], q)
        q_row = ws.query("SELECT * FROM passages WHERE passage_id=?", (lab["passage_id"],))[0]
        assert q_row["start"] <= lab["start"] < q_row["end"]
        assert lab["label_id"] == profile.label_id("sdg", lab["passage_id"], code, lab["source"])
    # the reviews follow the labels' new ids
    rv = {r["item_id"]: r for r in ws.query("SELECT * FROM reviews WHERE item_kind='label'")}
    assert rv[m["label_id"]]["decision"] == "change" and rv[p["label_id"]]["decision"] == "accept"
    assert lm not in rv or lm == m["label_id"]
    eff = {(r["code"], r["passage_id"]): r for r in profile.effective(ws, "sdg", doc_ids=[doc])}
    assert eff[("6.4", m["passage_id"])]["relevance"] == "mentioned"   # the person's change still applies
    assert ("7.2", p["passage_id"]) in eff
    # the reviewed keyword label moved with its passage; the others are gone, to be made again by the keyword pass
    kws = ws.query("SELECT * FROM labels WHERE source IN ('keywords','meaning','both')")
    assert len(kws) <= 1 and rep["remade"]["keyword_labels"] == len(kw) - 1
    if kws:
        assert ws.query("SELECT decision FROM reviews WHERE item_id=?", (kws[0]["label_id"],))[0][0] == "reject"
    # tasks: the one not answered is gone; the answered one is kept, never under another passage's id
    assert not ws.query("SELECT 1 FROM tasks WHERE task_id=?", (f"label:sdg:{other}",)) or \
        json.loads(ws.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (f"label:sdg:{other}",)))["text"] == \
        ws.scalar("SELECT text FROM passages WHERE passage_id=?", (other,))
    t = ws.query("SELECT * FROM tasks WHERE kind='label' AND status='done'")
    assert len(t) == 1 and m["task_id"] == t[0]["task_id"]
    pl = json.loads(t[0]["payload_json"])
    assert t[0]["task_id"] == f"label:sdg:{pl['passage_id']}"
    if reread.is_tombstone(pl["passage_id"]):
        assert not ws.query("SELECT 1 FROM passages WHERE passage_id=?", (pl["passage_id"],))
    else:  # one to one: the new passage holds what the model read
        now = ws.scalar("SELECT text FROM passages WHERE passage_id=?", (pl["passage_id"],))
        assert _same(now[:200], pl["text"][:200])
    assert rep["tasks"]["asked_again"] == 1 and rep["counts"]["label"]["moved"] >= 2
    # a keyword pass for the document makes its keyword labels again (as after adding documents)
    profile.keyword_pass(ws, "sdg", doc_ids=[doc])
    assert ws.scalar("SELECT COUNT(*) FROM labels WHERE source IN ('keywords','meaning','both')") > 0


# --- themes -------------------------------------------------------------------------------------------------------
def _notes(folder: Path, name: str, one_to_one: bool) -> Path:
    """A text file whose long paragraphs reader 1 and reader 2 cut the same way (one to one); with `one_to_one`
    false, short notes at the end that the two readers group differently."""
    def para(topic: str) -> str:
        # reader 1 fills a passage with whole sentences up to 1,100 characters: an opening sentence this long never
        # fits after a paragraph of about 800, so its passages end where the paragraphs do, as reader 2's
        first = (f"This opening sentence about {topic} is deliberately long, so that the first reader cannot add it to "
                 f"the passage before it without going over its limit of characters, which it would otherwise do "
                 f"for a short sentence, and so it starts a new passage exactly where a new paragraph about {topic} "
                 f"starts in the file, as the second reader does for every paragraph it finds in a text file.")
        rest = [f"The {topic} study {i} found that hydrogen made near the coast changes how {topic} is planned."
                for i in range(6)]
        return " ".join([first] + rest)
    parts = [para(t) for t in ("water", "energy", "transport")]
    if not one_to_one:
        parts += [f"A short note on {w}: the market for {w} made with hydrogen grew fast along the coast." for w in
                  ("steel", "ammonia", "shipping", "fertiliser", "cement", "aviation")]
    path = folder / name
    path.write_text("\n\n".join(parts) + "\n")
    return path


def _theme_run(ws: Workspace, run_id: str) -> None:
    """A theme run over every body passage (rows as themes.run writes them), up to date."""
    pids = [r[0] for r in ws.query("SELECT passage_id FROM passages WHERE section='body' ORDER BY passage_id")]
    with ws.connect() as cx:
        cx.execute("INSERT INTO theme_runs(run_id, mode, k, seed, created_at, passages, run_key, settings_json, "
                   "corpus_version) VALUES (?, 'words', 2, 0, 'x', ?, ?, '{}', ?)",
                   (run_id, len(pids), f"k{run_id}", ws.corpus_version()))
        cx.execute("INSERT INTO themes(run_id, theme_id, name, size, reps_json, name_source) VALUES "
                   "(?, 1, 'All', ?, ?, 'terms')", (run_id, len(pids), json.dumps(pids[:3])))
        cx.executemany("INSERT INTO theme_members(run_id, theme_id, passage_id, similarity) VALUES (?, 1, ?, 0.5)",
                       [(run_id, p) for p in pids])


def test_a_theme_run_keeps_passages_that_map_one_to_one_and_is_out_of_date_otherwise(tmp_path, monkeypatch):
    ws = Workspace.create(tmp_path / "ws")
    doc = _add(ws, monkeypatch, _notes(tmp_path, "studies.txt", one_to_one=False))
    old = {r[0]: r[1] for r in ws.query("SELECT passage_id, text FROM passages")}
    _theme_run(ws, "rA")
    assert not themes.runs(ws)[0]["stale"]
    pv = reread.preview(ws, doc)
    m = pv["themes"]["runs"][0]
    assert m["kept"] >= 1 and m["taken_out"] >= 1 and pv["themes"]["runs_out_of_date"] == 1
    reread.move(ws, doc)
    run = {r["run_id"]: r for r in themes.runs(ws)}["rA"]
    assert run["stale"]  # out of date: find the themes again
    mem = [r[0] for r in ws.query("SELECT passage_id FROM theme_members WHERE run_id='rA'")]
    assert len(mem) == m["kept"]
    for pid in mem:  # each kept passage is the same text as one that was in the run
        new = ws.scalar("SELECT text FROM passages WHERE passage_id=?", (pid,))
        assert any(_same(new, o[:len(new)]) or _same(new[:len(o)], o) or
                   normalise(new)[:120] == normalise(o)[:120] for o in old.values())
    view = themes.view(ws, "rA")  # shown as out of date, not broken
    assert view["run"]["stale"] and view["themes"][0]["size"] == len(mem)


def test_a_theme_run_stays_up_to_date_when_every_passage_maps_one_to_one(tmp_path, monkeypatch):
    ws = Workspace.create(tmp_path / "ws")
    doc = _add(ws, monkeypatch, _notes(tmp_path, "long.txt", one_to_one=True))
    n = ws.scalar("SELECT COUNT(*) FROM passages WHERE section='body'")
    _theme_run(ws, "rB")
    rep = reread.move(ws, doc)
    assert rep["passages"]["one_to_one"] == n == rep["passages"]["body_after"]
    assert not {r["run_id"]: r for r in themes.runs(ws)}["rB"]["stale"]
    assert ws.scalar("SELECT COUNT(*) FROM theme_members WHERE run_id='rB'") == n


# --- no old id left behind ---------------------------------------------------------------------------------------
def _references(ws: Workspace, doc: str) -> list[tuple[str, str, int, str]]:
    """Every (table, column, rowid, passage id of `doc`) in the database, whatever the column."""
    rx = re.compile(re.escape(doc) + r":\d{4,}(?![\w-])")
    out = []
    for (t,) in ws.query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        cols = [r[1] for r in ws.query(f"PRAGMA table_info({t})")]
        for r in ws.query(f"SELECT rowid AS _rid, * FROM {t}"):
            for c in cols:
                v = r[c]
                if isinstance(v, str) and doc in v:
                    out += [(t, c, r["_rid"], mm.group(0)) for mm in rx.finditer(v)]
    return out


def test_no_row_anywhere_names_an_old_passage_id_that_now_means_other_text(paper):
    """Every reference to a passage of the document after the move is checked against what it says: a quote at its
    offsets is its words, a grade's or a label's id is made from the passage it names, a task names the passage its
    payload shows, a theme member or a ledger row maps one to one. Passage ids are reused (`doc:0005`), so an old id
    left behind would pass a check that only looks for ids that exist."""
    ws, doc = paper
    cid, _at = _check(ws, [(Q_WATER, "supports"), (Q_DESAL, "refutes")])
    pj = _pid_with(ws, Q_JUDGE)
    claimcheck.set_judgement(ws, cid, pj, "supports", "Mine.", quote=Q_JUDGE)
    with ws.connect() as cx:  # a second opinion of the AI's excerpts
        for v in cx.execute("SELECT * FROM verifications WHERE quote IS NOT NULL").fetchall():
            cx.execute("INSERT INTO second_opinions(subject_id, passage_id, model, verdict, confidence, quote, start, "
                       "end, at) VALUES (?,?,?,?,?,?,?,?, 'x')",
                       (v["subject_id"], v["passage_id"], "second", "supports", 0.8, v["quote"], v["start"], v["end"]))
    q_model = f"desalination at {SITES[10]} will cover"
    pm = _pid_with(ws, q_model)
    profile.make_label_tasks(ws, "sdg", [pm], "test-model")
    assert tasks.ingest_result(ws, f"label:sdg:{pm}", {"labels": [{"code": "6.4", "confidence": 0.9,
                                                                   "quote": q_model}]}, model="test-model")[0]
    profile.keyword_pass(ws, "sdg")
    profile.make_label_tasks(ws, "sdg", [r[0] for r in ws.query("SELECT passage_id FROM passages")][:3], "test-model")
    _theme_run(ws, "rC")
    # the SDG pack: claims read from a passage (with evidence and an interaction it states), a person's review of one,
    # and a second check of the claim against its passage
    pe = _pid_with(ws, Q_WATER)
    tasks.make_extract(ws, "m", doc_ids=[doc], only_screened=False, limit=2)
    tasks.make_extract(ws, "m", doc_ids=[doc], only_screened=False)
    ok, errs = tasks.ingest_result(ws, f"extract:{pe}", {"claims": [
        {"claim": "Farmers fear for the supply of water", "activity": "electrolysis", "segment": "production",
         "targets": [{"target": "6.4", "direction": "negative"}], "confidence": 0.9,
         "evidence": [{"field": "claim", "quote": Q_WATER}]}],
        "interactions": [{"from_target": "6.4", "to_target": "2.4", "score": -1, "quote": Q_WATER}]}, model="m")
    assert ok, errs
    claim_id = ws.scalar("SELECT claim_id FROM claims")
    with ws.connect() as cx:
        cx.execute("INSERT INTO reviews(item_kind, item_id, field, decision, reviewer, decided_at) VALUES "
                   "('claim', ?, 'claim', 'accept', 'me', 'x')", (claim_id,))
    assert tasks.make_verify_claims(ws, "m2") == 1
    assert tasks.ingest_result(ws, f"verify:{claim_id}:m2", {"verdict": "supports", "confidence": 0.8,
                                                             "quote": Q_WATER}, model="m2")[0]
    with ws.connect() as cx:  # what the term index, the meaning index and reference chains hold, and the ledger
        p0 = ws.query("SELECT * FROM passages ORDER BY seq LIMIT 1")[0]
        cx.execute("INSERT INTO term_mentions VALUES ('t1', ?, ?, ?, ?)",
                   (p0["passage_id"], doc, p0["start"], p0["start"] + 5))
        cx.execute("INSERT INTO embeddings VALUES ('m', ?, x'00')", (p0["passage_id"],))
        cx.execute("INSERT INTO mentions(doc_id, chain_id, start, end, text, is_named, source, model, passage_id, "
                   "window) VALUES (?, 1, ?, ?, 'it', 0, 'model', 'm', ?, ?)",
                   (doc, p0["start"], p0["start"] + 2, p0["passage_id"], f"resolve:{doc}:00000#0"))
        cx.execute("INSERT INTO tasks(task_id, kind, model, prompt_version, payload_json, status, created_at) VALUES "
                   "(?, 'resolve', 'm', 'resolve-v1', ?, 'done', 'x')",
                   (f"resolve:{doc}:00000", json.dumps({"doc_id": doc, "passages": [
                       {"n": 1, "passage_id": p0["passage_id"], "text": p0["text"]}]})))
    old_text = {r[0]: r[1] for r in ws.query("SELECT passage_id, text FROM passages")}
    old_refs = _references(ws, doc)
    n_sent = ws.scalar("SELECT COUNT(*) FROM ai_sent")
    assert {t for t, *_ in old_refs} >= {"passages", "verifications", "judgements", "second_opinions", "labels",
                                         "tasks", "results", "theme_members", "ai_sent", "term_mentions",
                                         "embeddings", "mentions", "claims", "interactions"}

    rep = reread.move(ws, doc)
    assert ws.scalar("SELECT COUNT(*) FROM ai_sent") == n_sent  # the ledger keeps every row
    text = ws.scalar("SELECT text FROM documents")
    new = {r["passage_id"]: dict(r) for r in ws.query("SELECT * FROM passages WHERE doc_id=?", (doc,))}

    def words_at(row, q="quote", a="start", b="end"):
        return row[q] is None or row[a] is None or _same(text[row[a]:row[b]], row[q])

    def inside(pid, offset):
        return offset is None or new[pid]["start"] <= offset < new[pid]["end"]

    def same_text(pid_new, old_pid_text):
        return normalise(new[pid_new]["text"])[:80] == normalise(old_pid_text)[:80] or \
            normalise(old_pid_text)[:80] in normalise(new[pid_new]["text"])

    checked = set()
    for t, c, rid, pid in _references(ws, doc):
        assert pid in new, (t, c, pid)  # an id that names no passage now would be a dangling old id
        row = ws.query(f"SELECT rowid AS _rid, * FROM {t} WHERE rowid=?", (rid,))[0]
        checked.add(t)
        if t == "passages":
            assert row["doc_id"] == doc
        elif t == "verifications":
            assert words_at(row) and words_at(row, "user_quote", "user_start", "user_end") and inside(pid, row["start"])
            task_ids = [r[0] for r in ws.query("SELECT task_id FROM tasks WHERE payload_json LIKE ?", (f'%"{pid}"%',))]
            assert any(row["ver_id"] in (f"v{tasks._h(tid, pid)}", f"v{tasks._h(tid)}") for tid in task_ids)
        elif t in ("judgements", "second_opinions"):
            assert words_at(row)
            sid = row["claim_id"] if t == "judgements" else row["subject_id"]
            assert ws.query("SELECT 1 FROM verifications WHERE subject_id=? AND passage_id=?", (sid, pid))
        elif t == "labels":
            assert words_at(row) and inside(pid, row["start"])
            assert row["label_id"] == profile.label_id(row["framework"], pid, row["code"], row["source"])
        elif t == "tasks":
            pl = json.loads(row["payload_json"])
            if c == "task_id":
                assert pl.get("passage_id") == pid or any(p.get("passage_id") == pid for p in pl.get("passages", []))
            items = pl.get("passages") or [pl]
            for p in items:
                if p.get("passage_id") != pid:
                    continue
                if pl.get("subject_kind"):  # an excerpt (a check's, the SDG pack's): it points where its grade is
                    v = ws.query("SELECT * FROM verifications WHERE passage_id=? AND subject_id=?",
                                 (pid, pl["subject_id"]))
                    assert not v or v[0]["quote"] is None or v[0]["quote"] in p["text"]
                    assert v or row["status"] != "done" or row["kind"] in ("second", "reread")
                elif row["status"] == "done" and "text" in p:  # a task kept under the new id: one to one
                    assert same_text(pid, p["text"])
        elif t == "results":
            assert ws.query("SELECT 1 FROM tasks WHERE task_id=?", (row["task_id"],))
        elif t == "claims":  # under its extract task's new id; its passage holds its evidence, when placed
            assert ws.query("SELECT 1 FROM tasks WHERE task_id=?", (row["task_id"],))
            for ev in ws.query("SELECT * FROM evidence WHERE claim_id=?", (row["claim_id"],)):
                assert words_at(ev)
                if c == "passage_id" and ev["field"] == "claim" and ev["start"] is not None:
                    assert inside(pid, ev["start"]) or pid in row["task_id"]
            assert row["claim_id"] == f"c{tasks._h(row['task_id'], '0')}"  # its id made from its task's
        elif t == "interactions":
            assert words_at(row) and row["claim_id"].rpartition("#")[0] in {r[0] for r in ws.query("SELECT task_id "
                                                                                                   "FROM tasks")}
        elif t in ("theme_members", "ai_sent"):
            assert any(same_text(pid, o) for o in old_text.values())
        elif t == "reviews":
            assert row["item_kind"] in ("label", "theme_member")
        else:
            pytest.fail(f"{t}.{c} names {pid}, which nothing moved")
    assert {"verifications", "labels", "tasks"} <= checked
    # the SDG pack's claim keeps its review and its check under its new id
    cl = ws.query("SELECT * FROM claims")[0]
    assert ws.query("SELECT decision FROM reviews WHERE item_kind='claim' AND item_id=?", (cl["claim_id"],))
    v = ws.query("SELECT * FROM verifications WHERE subject_kind='claim'")[0]
    assert v["subject_id"] == cl["claim_id"] and words_at(v)
    assert ws.query("SELECT 1 FROM tasks WHERE task_id=?", (f"verify:{cl['claim_id']}:m2",))
    assert v["ver_id"] == f"v{tasks._h(f'verify:{claim_id}:m2'.replace(claim_id, cl['claim_id']))}"
    for t in ("term_mentions", "embeddings", "mentions"):  # made again, never kept
        assert not ws.query(f"SELECT 1 FROM {t} WHERE passage_id IN (SELECT passage_id FROM passages WHERE doc_id=?)",
                            (doc,))
    assert not ws.query("SELECT 1 FROM tasks WHERE kind='resolve'")  # its windows are read again on request
    # the share of the document Claude has read is not lowered by its passages having other ids now (a cap on it
    # must not loosen)
    from enlens_claims import access

    assert rep["ai_share"]["before"] > 0.5
    assert access.shares(ws, [doc])[doc]["share"] >= rep["ai_share"]["before"] == rep["ai_share"]["after"]
    with ws.connect() as cx:
        cx.execute("UPDATE documents SET ai_budget=50 WHERE doc_id=?", (doc,))
    assert access.levels(ws, [doc])[doc] == "local"  # the cap is reached, as it was before the move
    # what Claude reads after the move adds to what it had read before (it is not hidden behind it)
    before = access.shares(ws, [doc])[doc]
    unsent = [r[0] for r in ws.query("SELECT passage_id FROM passages WHERE doc_id=? AND passage_id NOT IN "
                                     "(SELECT passage_id FROM ai_sent) ORDER BY seq LIMIT 3", (doc,))]
    access.record_passages(ws, unsent, "Claude Code", "check")
    after = access.shares(ws, [doc])[doc]
    added = sum(len(new[p]["text"]) for p in unsent) / sum(len(x["text"]) for x in new.values())
    assert after["share"] == pytest.approx(min(1.0, before["share"] + added), abs=1e-3)
    # a later answer to the SDG pack's moved check of the claim is placed in the new text
    vt = f"verify:{cl['claim_id']}:m2"
    assert tasks.ingest_result(ws, vt, {"verdict": "supports", "confidence": 0.7, "quote": Q_WATER}, model="m3")[0]
    v2 = ws.query("SELECT * FROM verifications WHERE subject_kind='claim'")
    assert len(v2) == 1 and v2[0]["model"] == "m3" and words_at(v2[0]) and v2[0]["start"] is not None
    # every tombstone names no passage
    assert all(not ws.query("SELECT 1 FROM passages WHERE passage_id=?", (pid,))
               for (pid,) in ws.query("SELECT passage_id FROM ai_sent WHERE passage_id LIKE ?", (f"{doc}:r%",)))
    assert rep["tasks"]["asked_again"] >= 2


# --- what cannot be placed ----------------------------------------------------------------------------------------
def test_what_cannot_be_placed_is_reported_and_points_nowhere(paper):
    ws, doc = paper
    old_text = ws.scalar("SELECT text FROM documents")
    # a quote with reader 1's running head and page number in it: words reader 2 does not have in that order
    i = old_text.index(HEAD, 10)
    bad = old_text[i + len(HEAD) - 5:i + len(HEAD) + 22].strip()
    bad = bad[:bad.rfind(" ")]
    assert re.search(r"45-67 2 ", bad), bad
    cid, at = _check(ws, [(bad, "supports"), (Q_WATER, "supports")])
    pv = reread.preview(ws, doc)
    miss = [e for e in pv["not_placed"] if e["kind"] == "check"]
    assert len(miss) == 1 and bad.split()[-1] in miss[0]["quote"] and miss[0]["page"] == 2
    assert miss[0]["where"].startswith("page 2") and miss[0]["why"] and miss[0]["kind_text"]
    assert pv["counts"]["check"]["not_placed"] == 1 and pv["warnings"]
    rep = reread.move(ws, doc)
    assert [e["quote"] for e in rep["not_placed"]] == [e["quote"] for e in pv["not_placed"]]
    v = ws.query("SELECT * FROM verifications WHERE quote=?", (bad,))[0]
    assert reread.is_tombstone(v["passage_id"]) and v["start"] is None and v["end"] is None
    assert not ws.query("SELECT 1 FROM passages WHERE passage_id=?", (v["passage_id"],))
    res = claimcheck.result(ws, cid)
    it = _item(res, bad)
    assert it["not_placed"] and not it["in_corpus"] and it["text"][it["quote_start"]:it["quote_end"]] == bad
    assert it["verdict"] == "supports"  # the judgement is kept and still counts
    good = _item(res, Q_WATER)
    assert good["in_corpus"] and not good["not_placed"]
    rows = claimcheck.export_table(ws, hyp_ids=[cid])
    assert any(r["Quote"] == bad for r in rows)


# --- preview and the transaction ----------------------------------------------------------------------------------
def _files(ws: Workspace) -> dict[str, str]:
    out = {}
    for p in sorted(ws.root.glob("enlens.sqlite*")):
        out[p.name] = hashlib.sha1(p.read_bytes()).hexdigest()
    return out


def _dump(ws: Workspace) -> dict:
    out = {}
    tables = ws.query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    for (t,) in tables:
        out[t] = [tuple(r) for r in ws.query(f"SELECT rowid, * FROM {t} ORDER BY rowid")]
    return out


def test_preview_writes_nothing(paper):
    ws, doc = paper
    _check(ws, [(Q_WATER, "supports")])
    ws.close()
    files, dump = _files(ws), _dump(ws)
    ws.close()
    files = _files(ws)
    pv = reread.preview(ws, doc)
    assert pv["ok"] and not pv["moved"] and pv["counts"]["check"]["moved"] >= 1 and pv["reading"]["passages"]
    ws.close()
    assert _files(ws) == files and _dump(ws) == dump
    assert ws.scalar("SELECT reader FROM documents") == 1


def test_a_move_is_all_or_nothing(paper, monkeypatch):
    ws, doc = paper
    cid, _ = _check(ws, [(Q_WATER, "supports")])
    profile.keyword_pass(ws, "sdg")
    before = _dump(ws)

    def broken(*a, **k):
        raise RuntimeError("the disk is full")

    monkeypatch.setattr(ingest, "store_reading", broken)  # after every other row was changed
    with pytest.raises(RuntimeError, match="disk is full"):
        reread.move(ws, doc)
    assert _dump(ws) == before
    monkeypatch.undo()
    assert reread.move(ws, doc)["moved"] and ws.scalar("SELECT reader FROM documents") == ingest.READER


# --- check ------------------------------------------------------------------------------------------------------
def test_check_refuses_what_cannot_be_done_now(tmp_path, monkeypatch):
    ws = Workspace.create(tmp_path / "ws")
    folder = tmp_path / "files"
    folder.mkdir()
    doc = _add(ws, monkeypatch, _paper(folder))
    c = reread.check(ws, doc)
    assert c == {"ok": True, "reason": None, "reader": 1, "new_reader": ingest.READER}
    # tasks waiting for Claude Code, or handed out to it
    pid = ws.scalar("SELECT passage_id FROM passages LIMIT 1")
    profile.make_label_tasks(ws, "sdg", [pid], "test-model")
    with ws.connect() as cx:
        cx.execute("UPDATE tasks SET queued=1 WHERE kind='label'")
    c = reread.check(ws, doc)
    assert not c["ok"] and "waits for Claude Code" in c["reason"]
    with pytest.raises(ValueError, match="waits for Claude Code"):
        reread.move(ws, doc)
    assert not reread.preview(ws, doc)["ok"]
    with ws.connect() as cx:
        cx.execute("UPDATE tasks SET claimed_by='q1', claimed_at=? WHERE kind='label'",
                   (__import__("enlens_claims.store", fromlist=["now"]).now(),))
    assert "working on this document" in reread.check(ws, doc)["reason"]
    with ws.connect() as cx:
        cx.execute("UPDATE tasks SET queued=0, claimed_by=NULL, claimed_at=NULL")
    assert reread.check(ws, doc)["ok"]
    # the original changed
    path = Path(ws.scalar("SELECT path FROM documents"))
    data = path.read_bytes()
    path.write_bytes(data + b"\n% changed\n")
    c = reread.check(ws, doc)
    assert not c["ok"] and "changed since it was added" in c["reason"]
    path.write_bytes(data)
    assert reread.check(ws, doc)["ok"]
    # the original is not there
    path.rename(tmp_path / "elsewhere.pdf")
    c = reread.check(ws, doc)
    assert not c["ok"] and "no longer at" in c["reason"]
    (tmp_path / "elsewhere.pdf").rename(path)
    # a document read by the current reader already
    reread.move(ws, doc)
    c = reread.check(ws, doc)
    assert c == {"ok": False, "reason": c["reason"], "reader": ingest.READER, "new_reader": ingest.READER} and "already" in c["reason"]
    other = tmp_path / "files" / "new.txt"
    other.write_text("Hydrogen made by electrolysis needs water in arid regions, the new study said. " * 5)
    d2 = _add(ws, monkeypatch, other, reader=ingest.READER)
    assert not reread.check(ws, d2)["ok"]
    # a sync-clash copy's file sum carries a mark, and still counts as the same file
    with ws.connect() as cx:
        cx.execute("UPDATE documents SET reader=1, sha1=sha1 || '~0f1e2d' WHERE doc_id=?", (d2,))
    assert reread.check(ws, d2)["ok"]


# --- a person's corrections of blocks ------------------------------------------------------------------------------
def test_a_persons_block_corrections_are_applied_after_moving(paper):
    ws, doc = paper
    path = Path(ws.scalar("SELECT path FROM documents"))
    new = ingest.read_document(path, reader=2)
    body = next(b for b in new.blocks if b.kind == "body" and SITES[7] in b.text)
    head = next(b for b in new.blocks if b.kind == "furniture" and HEAD in b.text)
    from enlens_claims import reader

    with ws.connect() as cx:  # corrections kept by the blocks' words (as a colleague's reading of the file brings)
        cx.execute("INSERT INTO block_choices(doc_id, fp, included, kind, person_id, at) VALUES "
                   "(?,?,0,'body','me','x')",
                   (doc, reader.block_fp(body.text)))
        cx.execute("INSERT INTO block_choices(doc_id, fp, included, kind, person_id, at) VALUES "
                   "(?,?,1,'furniture','me','x')",
                   (doc, reader.block_fp(head.text)))
    reread.move(ws, doc)
    text = ws.scalar("SELECT text FROM documents")
    blocks = ws.query("SELECT * FROM blocks WHERE doc_id=?", (doc,))
    b = next(r for r in blocks if text[r["start"]:r["end"]] == body.text)
    h = next(r for r in blocks if text[r["start"]:r["end"]] == head.text)
    assert b["included"] == 0 and h["included"] == 1
    sec = {r["section"] for r in ws.query("SELECT section FROM passages WHERE doc_id=? AND start<? AND end>?",
                                         (doc, b["end"], b["start"]))}
    assert sec == {"left_out"}
    assert ws.scalar("SELECT reading_json FROM documents") and ws.scalar("SELECT old_fps FROM documents")
