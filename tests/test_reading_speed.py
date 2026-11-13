"""Speed and memory fixes in the reader and the text helpers. The readers are frozen: each fix computes the same
result sooner, and each test here holds a copy of the way it was done before and compares to the byte."""
from __future__ import annotations

import html
import random
import sqlite3
import sys
import threading
import time
import unicodedata
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from enlens_claims import annotate, reader, reader3, textutil  # noqa: E402
from helpers import make_pdf  # noqa: E402

ALPHABET = ["a", "b", "e", "x", "T", "Z", "é", "ß", "ﬁ", "­", "-", "-", "‐", "–", "/", " ", " ", "\t", ".", ".",
            "e.g.", " et al.", " Fig.", " approx.", "A.", "1", "23", "́", "ǅ", "İ", "’", " ", "\n", "?", "!", '"',
            ")", "ᴀ", "ſ", "K"]


def _rstr(rnd: random.Random, n: int) -> str:
    return "".join(rnd.choice(ALPHABET) for _ in range(n))


# ---- reading: the lines of a block ---------------------------------------------------------------------------
def _old_join_lines(texts, vocab, counts):
    out = ""
    for t in texts:
        t = t.strip()
        if not t:
            continue
        if not out:
            out = t
            continue
        if out.endswith("­"):
            out = out[:-1] + t
            counts["hyphens_joined"] += 1
            continue
        m = reader._TAIL.search(out)
        nxt = reader._HEAD.match(t)
        if m and out[-1] in "-‐" and nxt and t[0].islower():
            left, right = m.group(1), nxt.group(1)
            whole = (left + right).lower()
            hyph = vocab.get(f"{left}-{right}".lower(), 0)
            if whole in reader._CLOSED or (vocab.get(whole, 0) >= 1 and vocab.get(whole, 0) >= hyph):
                join = True
            elif hyph:
                join = False
            elif left.lower() in reader._HYPHEN_PREFIX:
                join = False
            elif reader._SUFFIX_PIECE.fullmatch(right.lower()):
                join = True
            elif reader._is_word(left, vocab) and len(left) >= 3 and len(right) >= 3:
                join = False
            else:
                join = True
            if join:
                out = out[:-1] + t
                counts["hyphens_joined"] += 1
            else:
                out = out + t
                counts["hyphens_kept"] += 1
            continue
        if out[-1] in "-‐–/" and not out.endswith(" -") and not out.endswith(" –"):
            out = out + t
            continue
        out = out + " " + t
    return out.replace("­", "")


def test_lines_are_joined_as_before_on_hyphens_and_odd_text():
    rnd = random.Random(11)
    vocab = Counter({"longterm": 2, "long-term": 1, "example": 3, "co-op": 2, "coop": 1, "re-search": 1,
                     "research": 4, "information": 3})
    pieces = "long- term exam- ple COVID- 19 and/ or self- reported infor- mation non- fiction re- search ab cd- x".split()
    cases = [[_rstr(rnd, rnd.randint(0, 12)) for _ in range(rnd.randint(1, 8))] for _ in range(1500)]
    cases += [[" ".join(rnd.choice(pieces) for _ in range(rnd.randint(1, 5))) for _ in range(rnd.randint(2, 9))]
              for _ in range(700)]
    cases += [["a" * rnd.randint(1, 300) + "-", "b" * rnd.randint(1, 300), "é" * 200 + "‐", "ü", "x-", " y", "z­", "w"]
              for _ in range(20)]  # a long word before the hyphen: the look at the end must reach back to its start
    joined = 0
    for lines in cases:
        old_c, new_c = Counter(), Counter()
        assert reader.join_lines(lines, vocab, new_c) == _old_join_lines(lines, vocab, old_c), lines
        assert new_c == old_c, lines
        joined += new_c["hyphens_joined"] + new_c["hyphens_kept"]
    assert joined > 300  # the cases do reach the rule about hyphens


def test_a_block_of_two_thousand_lines_is_joined_at_once():
    rnd = random.Random(1)
    words = "the climate policy energy transition renewable investment growth market reduce emissions carbon".split()
    lines = [" ".join(rnd.choice(words) for _ in range(14)) for _ in range(2000)]
    t0 = time.perf_counter()
    got = reader.join_lines(lines, Counter(), Counter())
    assert time.perf_counter() - t0 < 0.5  # 18.9 s: the whole text was searched for every line
    assert got == " ".join(lines)


def test_a_word_hyphenated_across_a_block_turn_is_still_put_together():
    # the same look at the end of the text is used where a paragraph goes on in the next block
    assert reader._tail_match("a long text with exam-").group(1) == "exam"
    assert reader._tail_match("x" * 5000 + "-").group(1) == "x" * 5000
    assert reader._tail_match("no hyphen at the end") is None
    assert reader._tail_match("ends with a digit 2-") is None


# ---- text: sentences, and normalising one character for one ---------------------------------------------------
_OLD_ABBREV = textutil._ABBREV


def _old_split_sentences(text, offset=0):
    import re

    spans = []
    start = 0
    for m in textutil._SENT_END.finditer(text):
        end = m.start(1)
        head = text[start:end]
        if _OLD_ABBREV.search(head):
            continue
        if re.fullmatch(r"\s*\d+\.", head):
            continue
        if head.strip():
            s = start + (len(head) - len(head.lstrip()))
            spans.append((offset + s, offset + end))
        start = m.end()
    tail = text[start:]
    if tail.strip():
        s = start + (len(tail) - len(tail.lstrip()))
        spans.append((offset + s, offset + start + len(tail.rstrip())))
    return spans


def test_sentences_are_split_as_before_around_abbreviations():
    rnd = random.Random(5)
    stops = ["e.g.", "i.e.", "et al.", "etc.", "Fig.", "figs.", "approx.", "vs.", "A.", "Dr.", "Prof.", "St.", "Ref.",
             "refs.", "pp.", "incl.", "resp.", "esp.", "no.", "Vol.", "cf.", "Eq.", "ca.", "al.", "ſt.", "K."]
    texts = []
    for _ in range(1500):
        texts.append(_rstr(rnd, rnd.randint(0, 60)) + " X. " + _rstr(rnd, rnd.randint(0, 30)))
    for _ in range(1500):  # a stop before the end of every sentence end, with the letters before it close or far
        texts.append(" ".join(rnd.choice(stops + ["see", "Table 3.", "x" * rnd.randint(1, 12) + ".", "(a.)", "3."]) +
                              rnd.choice(["", "", "\"", ")", "”"]) + rnd.choice([" ", " ", "  ", "\n"]) +
                              rnd.choice(["Next", "3", "(Then", "next"]) for _ in range(rnd.randint(1, 12))))
    for t in texts:
        assert textutil.split_sentences(t, 7) == _old_split_sentences(t, 7), t


def test_a_long_run_of_abbreviation_stops_is_one_sentence_found_at_once():
    text = " ".join(f"see Fig. {i} and e.g. Table {i}" for i in range(2000))  # 66,000 characters, no real sentence end
    t0 = time.perf_counter()
    got = textutil.split_sentences(text)
    assert time.perf_counter() - t0 < 0.5  # 9.1 s: every stop read the whole stretch before it again
    assert got == [(0, len(text))]
    assert textutil.split_sentences(text[:3000]) == _old_split_sentences(text[:3000])


_ONE_OLD: dict = {}


def _old_one_to_one(text):
    out = []
    for ch in text:
        if ch < "\x80":
            out.append(ch.lower() if not ch.isspace() else " ")
            continue
        rep = _ONE_OLD.get(ch, "")
        if rep == "":
            if unicodedata.combining(ch):
                rep = None
            else:
                r = textutil._norm_cluster(ch)
                rep = r if len(r) == 1 else None
            _ONE_OLD[ch] = rep
        if rep is None:
            return None
        out.append(rep)
    return "".join(out)


def test_text_is_normalised_one_character_for_one_as_before():
    rnd = random.Random(8)
    texts = [_rstr(rnd, rnd.randint(0, 40)) for _ in range(2500)]
    texts += [chr(i) + "a B\t" + chr(j) for i, j in zip(range(0, 0x2600, 3), range(0x2600, 0, -3))]  # a wide range
    texts += ["Ünïcödé “quotes” – dashes’ 12 ñ", "ASCII only. With\u000bwhite\u001cspace\x1d.", "", "ﬁ", "é", "­"]
    for t in texts:
        assert textutil._one_to_one(t) == _old_one_to_one(t), repr(t)
    assert textutil._one_to_one("Ünï  “a”\t") == "ünï  \"a\" "  # one character for one
    assert textutil._one_to_one("ﬁne") is None and textutil._one_to_one("e\u0301") is None


def test_ascii_white_space_and_capitals_have_the_entries_the_loop_gave_them():
    for i in range(128):
        ch = chr(i)
        assert textutil._ONE_TABLE[i] == (" " if ch.isspace() else ch.lower())


def test_text_normalised_one_for_one_by_several_threads_is_never_wrong():
    rnd = random.Random(2)
    chars = [chr(i) for i in range(0xC0, 0x500)]
    texts = ["".join(rnd.choice(chars) for _ in range(30)) + " Z" for _ in range(300)]
    wrong: list[str] = []
    textutil._ONE_TABLE.clear()  # as at the start of a run: a thread meets characters that another is adding
    textutil._ONE_TABLE.update({i: " " if chr(i).isspace() else chr(i).lower() for i in range(128)})
    textutil._NOT_ONE.clear()

    def work(offset: int):
        for t in texts[offset::4]:
            if textutil._one_to_one(t) != _old_one_to_one(t):
                wrong.append(t)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert not wrong


def test_a_page_of_text_with_accents_is_normalised_in_a_moment():
    text = ("Économie et développement durable: l’énergie “verte” – çà et là. " * 3000)[:200_000]
    textutil._one_to_one(text)
    t0 = time.perf_counter()
    for _ in range(20):
        assert textutil._one_to_one(text) is not None
    assert time.perf_counter() - t0 < 0.5  # 20 passes of the per-character loop took about 1 s


# ---- reading: which blocks a passage touches --------------------------------------------------------------------
def _db(blocks, passages, text_len, choices=()):
    cx = sqlite3.connect(":memory:")
    cx.executescript("""CREATE TABLE blocks(doc_id, n, page, start, end, kind, included, x0,y0,x1,y1);
    CREATE TABLE passages(passage_id, doc_id, seq, page, start, end, text, section, block);
    CREATE TABLE documents(doc_id, text); CREATE TABLE block_choices(doc_id, fp, included);""")
    cx.execute("INSERT INTO documents VALUES ('d1', ?)", ("x" * text_len,))
    cx.executemany("INSERT INTO blocks VALUES ('d1',?,1,?,?,?,?,0,0,0,0)", blocks)
    cx.executemany("INSERT INTO passages VALUES (?, 'd1', ?, 1, ?, ?, '', ?, 'body')", passages)
    cx.executemany("INSERT INTO block_choices VALUES ('d1', ?, ?)", choices)
    return cx


def _old_apply_choices(cx, doc_id):
    rows = cx.execute("SELECT n, start, end, kind, included FROM blocks WHERE doc_id=? ORDER BY n", (doc_id,)).fetchall()
    if not rows:
        return []
    (text,) = cx.execute("SELECT text FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    choices = {fp: inc for fp, inc in cx.execute("SELECT fp, included FROM block_choices WHERE doc_id=?", (doc_id,))}
    changed = []
    want = {}
    chosen = reader.choose_inclusion([(text[a:z], kind) for _n, a, z, kind, _inc in rows], choices)
    for (n, _a, _z, _kind, inc), w in zip(rows, chosen):
        want[n] = w
        if w != inc:
            changed.append(n)
    if changed:
        cx.executemany("UPDATE blocks SET included=? WHERE doc_id=? AND n=?", [(want[n], doc_id, n) for n in changed])
    spans = [(a, z, want[n], kind) for n, a, z, kind, _inc in rows]
    ups = []
    for pid, a, z, section in cx.execute("SELECT passage_id, start, end, section FROM passages WHERE doc_id=?",
                                         (doc_id,)).fetchall():
        mine = [(inc, kind) for b0, b1, inc, kind in spans if b0 < z and b1 > a]
        if not mine:
            continue
        inc = any(i for i, _k in mine)
        if inc:
            if section in ("left_out", "references"):
                from enlens_claims.ingest import reference_like, unreadable

                body = text[a:z]
                new = "unreadable" if unreadable(body) else "reference_like" if reference_like(body) else "body"
            else:
                new = section
        else:
            new = "references" if all(k == "references" for _i, k in mine) else "left_out"
        if new != section:
            ups.append((new, pid))
    if ups:
        cx.executemany("UPDATE passages SET section=? WHERE passage_id=?", ups)
    return changed


def _dump(cx):
    return (cx.execute("SELECT * FROM blocks ORDER BY n").fetchall(),
            cx.execute("SELECT passage_id, section FROM passages ORDER BY passage_id").fetchall())


def test_the_passages_of_a_document_get_the_sections_they_got_before():
    rnd = random.Random(4)
    kinds = ["body", "body", "heading", "references", "furniture", "caption"]
    for case in range(60):
        n_blocks = rnd.randint(1, 40)
        pos = 0
        blocks = []
        for i in range(n_blocks):
            gap = rnd.choice([0, 0, 1, 3])
            a = pos + gap
            z = a + rnd.randint(0, 30)  # a block may be empty
            blocks.append((i + 1, a, z, rnd.choice(kinds), rnd.choice([0, 1])))
            pos = z
        if case % 6 == 0:  # blocks out of order, and overlapping: the plain scan is used
            rnd.shuffle(blocks)
            blocks = [(i + 1, a, z, k, inc) for i, (_n, a, z, k, inc) in enumerate(blocks)]
        length = pos + 10
        passages = []
        for i in range(rnd.randint(0, 30)):
            a = rnd.randint(0, length)
            z = min(length, a + rnd.randint(0, 60))
            passages.append((f"d1:{i:04d}", i, a, z, rnd.choice(["body", "left_out", "references", "unreadable"])))
        choices = [(f"fp{i}", rnd.choice([0, 1])) for i in range(3)]
        old, new = _db(blocks, passages, length, choices), _db(blocks, passages, length, choices)
        assert reader.apply_choices(new, "d1") == _old_apply_choices(old, "d1")
        assert _dump(new) == _dump(old), case


def test_four_thousand_passages_over_fifteen_thousand_blocks_are_settled_at_once():
    n_blocks, n_pass = 15000, 4000
    length = 200 * n_blocks
    blocks = [(i + 1, i * 200, i * 200 + 199, "body", 1) for i in range(n_blocks)]
    passages = [(f"d1:{i:04d}", i, i * length // n_pass, (i + 1) * length // n_pass - 1, "body") for i in range(n_pass)]
    cx = _db(blocks, passages, length)
    t0 = time.perf_counter()
    reader.apply_choices(cx, "d1")
    assert time.perf_counter() - t0 < 0.3  # 0.77 s: each passage was compared with each block


# ---- reading: a book's parts from its table of contents ----------------------------------------------------------
def _old_find_entries(blocks, fracs, c1, titles):
    n = len(blocks)
    entries = [(t, reader3._norm(t)) for t in titles]
    matches = []
    e = 0
    k = c1
    while k < n and e < len(entries):
        b = blocks[k]
        if b.kind in ("furniture", "table", "figure", "contents") or len(reader3._text(b)) > 200:
            k += 1
            continue
        mine = reader3._norm(reader3._text(b))
        nxt = next((blocks[x] for x in range(k + 1, min(n, k + 3)) if blocks[x].kind != "furniture"), None)
        both = (reader3._norm(reader3._text(b) + " " + reader3._text(nxt))
                if nxt is not None and len(reader3._text(nxt)) <= 80 else None)
        hit = None
        for x in range(e, len(entries)):
            t, ne = entries[x]
            if not ne:
                continue
            late = bool(reader3._ENTRY_REFS.match(ne) or reader3._ENTRY_INDEX.match(ne) or reader3._ENTRY_BACK.match(ne))
            if late and fracs[k] < 0.5:
                continue
            parts = [ne] + ([p for p in (reader3._norm(s) for s in t.split(":")) if len(p) >= 6] if ":" in t else [])
            if any(reader3._same_title(mine, p) for p in parts) or (both and reader3._same_title(both, ne)):
                hit = x
                break
        if hit is not None:
            matches.append((k, entries[hit][0]))
            e = hit + 1
        k += 1
    return matches


def _old_same_title(block, entry):
    if not block or not entry:
        return False
    if block == entry:
        return True
    if len(entry) >= 8 and len(block) >= 8 and (block.startswith(entry) and len(block) <= len(entry) + 40
                                                  or entry.startswith(block) and len(block) >= 0.45 * len(entry)):
        return True
    a, b = reader3._stems(block), reader3._stems(entry)
    return len(a) >= 2 and len(b) >= 2 and len(a & b) / len(a | b) >= 0.75


_TITLE_WORDS = ("climate policy energy transition renewable investment growth market reduce emissions carbon price "
                "households income region notes references index").split()


def _book(rnd: random.Random, n_titles: int, n_blocks: int):
    titles = []
    for _ in range(n_titles):
        k = rnd.random()
        if k < 0.06:
            titles.append(rnd.choice(["Notes", "References", "Index", "Bibliography", "Acknowledgements"]))
        elif k < 0.2:
            titles.append(f"{' '.join(rnd.choice(_TITLE_WORDS) for _ in range(2))}: "
                          f"{' '.join(rnd.choice(_TITLE_WORDS) for _ in range(3))}")
        else:
            titles.append(" ".join(rnd.choice(_TITLE_WORDS) for _ in range(rnd.randint(1, 7))))
    blocks = [reader.Block(0, [reader.Line(0, "Contents")], kind="heading")]
    for _ in range(n_blocks):
        c = rnd.random()
        if c < 0.25:
            w = rnd.choice(titles).split()
            if rnd.random() < 0.3:
                rnd.shuffle(w)
            if rnd.random() < 0.3 and len(w) > 2:
                w = w[:-1]
            if rnd.random() < 0.3:
                w = w + ["x"]
            text = " ".join(w)
            if rnd.random() < 0.2:
                text = text.split(":")[0]
            if rnd.random() < 0.2:
                text += " " + " ".join(rnd.choice(_TITLE_WORDS) for _ in range(rnd.randint(1, 8)))
        elif c < 0.35:
            text = " ".join(rnd.choice(_TITLE_WORDS) for _ in range(300))
        else:
            text = " ".join(rnd.choice(_TITLE_WORDS) for _ in range(rnd.randint(1, 14)))
        kind = rnd.choice(["body", "body", "heading", "furniture", "table", "figure", "caption"])
        blocks.append(reader.Block(0, [reader.Line(0, text)], kind=kind))
    sizes = [len(reader3._text(b)) for b in blocks]
    total, done, fracs = sum(sizes), 0, []
    for s in sizes:
        fracs.append(done / total)
        done += s
    return blocks, fracs, titles


def test_the_headings_a_book_finds_for_its_contents_are_those_it_found_before():
    found = 0
    for case in range(150):
        rnd = random.Random(case)
        blocks, fracs, titles = _book(rnd, rnd.randint(3, 25), rnd.randint(20, 120))
        new = reader3._find_entries(blocks, fracs, 1, titles)
        assert new == _old_find_entries(blocks, fracs, 1, titles), case
        found += len(new)
    assert found > 150


def test_two_titles_are_the_same_title_as_before():
    rnd = random.Random(6)
    vocab = _TITLE_WORDS + ["the", "of", "x", "a", "years", "year"]
    titles = [" ".join(rnd.choice(vocab) for _ in range(rnd.randint(0, 9))) for _ in range(300)]
    titles += [t + " " + t.split(" ")[0] for t in titles[:100]] + [t[: len(t) // 2] for t in titles[:100]]
    for _ in range(6000):
        a, b = rnd.choice(titles), rnd.choice(titles)
        assert reader3._same_title(a, b) == _old_same_title(a, b), (a, b)


def test_a_contents_of_three_hundred_entries_is_looked_up_for_fifteen_thousand_blocks_at_once():
    rnd = random.Random(5)
    words = "the climate policy energy transition renewable investment growth market reduce emissions carbon price".split()
    titles = [f"Chapter title number {i} on {rnd.choice(words)} {rnd.choice(words)}" for i in range(300)]
    blocks = [reader.Block(0, [reader.Line(0, " ".join(rnd.choice(words) for _ in range(12)))], kind="body")
              for _ in range(15000)]
    fracs = [i / len(blocks) for i in range(len(blocks))]
    t0 = time.perf_counter()
    assert reader3._find_entries(blocks, fracs, 0, titles) == []
    # 12.6 s when every entry was worked out again for every block; about 1 s here, up to 5 s on a busy CI runner
    assert time.perf_counter() - t0 < 8.0


# ---- the marked copy of a document -------------------------------------------------------------------------------
def _old_write_html_parts(text, marks):
    bounds = sorted({0, len(text), *(m.start for m in marks), *(m.end for m in marks)})
    order = {"refutes": 0, "partially_supports": 1, "supports": 2, "label": 3, "concept": 4, "reference": 5}
    parts = []
    for a, b in zip(bounds, bounds[1:]):
        if a >= b:
            continue
        on = [m for m in marks if m.start <= a and b <= m.end]
        seg = html.escape(text[a:b])
        if on:
            top = min(on, key=lambda m: order.get(m.kind, 9))
            notes = "\n\n".join(dict.fromkeys(m.note for m in on))
            seg = (f'<mark style="background:{annotate.CSS_COLOURS.get(top.kind, "#ffe08a")}" title="{html.escape(notes)}">'
                   f"{seg}</mark>")
        parts.append(seg)
    return "".join(parts)


def test_a_text_with_marks_is_written_as_before():
    kinds = ["refutes", "partially_supports", "supports", "label", "concept", "reference", "other"]
    for case in range(200):
        rnd = random.Random(1000 + case)
        text = "".join(rnd.choice("ab <>&\"'é\n") for _ in range(rnd.randint(0, 200)))
        marks = []
        for _ in range(rnd.randint(0, 30)):
            a = rnd.randint(-5, len(text) + 5)
            b = rnd.choice([a, a + rnd.randint(-3, 40)])  # empty, backwards, inside, past the end
            marks.append(annotate.Mark(a, b, "q", rnd.choice(kinds), rnd.choice(["n1", "n2", "n3<"]), "x"))
        if case % 4 == 0:
            marks.sort(key=lambda m: (m.start, m.end))
        want = _old_write_html_parts(text, marks)
        body = annotate.write_html(text, marks, "N").decode()
        assert f"<pre>{want}</pre>" in body, case
        assert all(m.placed and m.method == "text" for m in marks)


def test_eight_thousand_marks_on_a_long_text_are_written_at_once():
    text = "word " * 400000
    marks = [annotate.Mark(i * 200, i * 200 + 20, "x", "concept", "Concept: x", "concepts") for i in range(8000)]
    t0 = time.perf_counter()
    annotate.write_html(text, marks, "t")
    assert time.perf_counter() - t0 < 0.5  # 1.2 s: every mark was tried against every stretch


# ---- the highlighted PDF ------------------------------------------------------------------------------------------
def test_a_page_is_normalised_once_however_many_quotes_are_looked_for_on_it(monkeypatch):
    seen = []
    real = annotate._normalise_spans

    def spy(text, drop_spaces=False):
        if len(text) > 100:
            seen.append(drop_spaces)
        return real(text, drop_spaces=drop_spaces)

    monkeypatch.setattr(annotate, "_normalise_spans", spy)
    page = "Green hydrogen needs water in arid regions. Exporters must plan desalination for the plant. " * 4
    pt = annotate.PageText(page, [None] * len(page), "exact")
    cache = pt.norm
    first = annotate._find_nearest(page, "must plan desalination", 0.5, cache)
    for _ in range(10):
        assert annotate._find_nearest(page, "must plan desalination", 0.5, cache) == first
    assert seen == [False]  # the page was normalised once for eleven quotes
    assert annotate._find_nearest(page, "mustplan desalination", None, cache)  # found only without spaces
    assert annotate._find_nearest(page, "mustplan desalination", None, cache)
    assert seen == [False, True]  # and once more, the other way
    assert annotate._find_nearest(page, "must plan desalination", 0.5) == first  # no cache: as it was
    assert seen == [False, True, False]


def _old_place(path, marks, use_pdfminer=True):
    from pypdf import PdfReader

    rd = PdfReader(str(path))
    exact = annotate._pdfminer_pages(path) if use_pdfminer else None
    lines = None
    for m in marks:
        candidates = [m.page] if m.page else list(range(1, len(rd.pages) + 1))
        if m.page:
            candidates += [p for p in (m.page - 1, m.page + 1) if 1 <= p <= len(rd.pages)]
        for pno in candidates:
            got = None
            for source in ("exact", "lines"):
                if source == "exact" and not exact:
                    continue
                if source == "lines":
                    if lines is None:
                        lines = annotate._pypdf_pages(rd)
                    pt = lines.get(pno)
                else:
                    pt = exact.get(pno)
                if not pt or not pt.text.strip():
                    continue
                hit = annotate._find_nearest(pt.text, m.quote, m.where)
                if hit:
                    q = annotate._quads(pt, hit[0], hit[1])
                    if q:
                        got = (q, pt.method)
                        break
            if got:
                m.quads, m.method, m.placed, m.page = got[0], got[1], True, pno
                break
    return {"pages": len(rd.pages), "exact": bool(exact)}


def _pdf_with_marks(tmp_path, seed):
    rnd = random.Random(seed)
    words = "green hydrogen water arid regions farming exporters desalination wastewater reuse cheaper plant".split()
    pages = [" ".join(" ".join(rnd.choice(words) for _ in range(rnd.randint(4, 14))).capitalize() + "."
                      for _ in range(rnd.randint(3, 12))) for _ in range(7)]
    path = make_pdf(tmp_path / f"d{seed}.pdf", pages)

    def marks():
        r = random.Random(seed + 1)
        out = []
        for _ in range(20):
            p = r.randint(0, len(pages))  # page 0: unknown, so the mark may be on any page
            w = pages[max(p, 1) - 1].split()
            a = r.randint(0, len(w) - 5)
            q = "no such words here" if r.random() < 0.15 else " ".join(w[a:a + r.randint(1, 4)])
            out.append(annotate.Mark(0, len(q), q, "concept", "n", "concepts", p or None, r.choice([None, 0.2, 0.9])))
        return out
    return path, marks


@pytest.mark.parametrize("use_pdfminer", [True, False])
def test_marks_are_placed_on_a_pdf_where_they_were_before(tmp_path, use_pdfminer):
    if use_pdfminer:
        pytest.importorskip("pdfminer")
    for seed in (1, 2, 3):
        path, make_marks = _pdf_with_marks(tmp_path, seed)
        old_marks, new_marks = make_marks(), make_marks()
        old = _old_place(path, old_marks, use_pdfminer)
        new = annotate.place(path, new_marks, use_pdfminer=use_pdfminer)
        assert new == old
        assert [(m.placed, m.method, m.page, m.quads) for m in new_marks] == \
               [(m.placed, m.method, m.page, m.quads) for m in old_marks]
        assert sum(m.placed for m in new_marks) >= 10


def test_pdfminer_keeps_the_boxes_of_the_pages_asked_for_only(tmp_path):
    pytest.importorskip("pdfminer")
    path, _ = _pdf_with_marks(tmp_path, 1)
    full = annotate._pdfminer_pages(path)
    some = annotate._pdfminer_pages(path, {2, 3})
    assert len(full) == 7
    assert sorted(some) == [2, 3] and all(some.values())   # 0.17.2: the other pages are not read at all
    for p in (2, 3):
        assert some[p].text == full[p].text
        assert [b and b[:4] for b in some[p].boxes] == [b and b[:4] for b in full[p].boxes]
        assert (some[p].x0, some[p].y0, some[p].width, some[p].height) == (full[p].x0, full[p].y0, full[p].width,
                                                                           full[p].height)


def test_pypdf_reads_only_the_pages_the_marks_are_looked_for_on(tmp_path, monkeypatch):
    path, _ = _pdf_with_marks(tmp_path, 2)
    read = []
    real = annotate._pypdf_page
    monkeypatch.setattr(annotate, "_pypdf_page", lambda rd, pno: read.append(pno) or real(rd, pno))
    marks = [annotate.Mark(0, 3, "water", "concept", "n", "concepts", 4, 0.1)]
    annotate.place(path, marks, use_pdfminer=False)
    assert read and set(read) <= {3, 4, 5}, read  # it was 7 pages, all of them, at the first look
