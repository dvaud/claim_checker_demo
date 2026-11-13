"""The deep dive after 0.17.0, the page: text positions counted alike on both sides, the reading view's loads and
paints, the result page's look while a check waits, Search's pages and words, and the shared helpers of lib.js.

The app counts a text's characters as Python does (code points); a JavaScript string counts UTF-16 units, so every
character outside the Basic Multilingual Plane (𝑥, an emoji) before a place moved each highlight after it by one.
Node runs lib.js (and search.js) here with the stand-in document of tests/_fakedom.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from _fakedom import NODE, run
from enlens_claims import concordance, ingest
from enlens_claims.store import Workspace

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"
needs_node = pytest.mark.skipif(not NODE, reason="node is not installed")


def _js(rel: str) -> str:
    return (STATIC / rel).read_text(encoding="utf-8")


def _fn(js: str, start: str, end: str = "\n  }\n") -> str:
    body = js[js.index(start):]
    return body[:body.index(end) + len(end)]


# ---- text positions: the app's offsets and the string's indices -----------------------------------------------
# (text, the app's offset) cases: none of the characters, one before the place, one after, several, combining marks
# and accented letters of the plane (one unit each on both sides)
CASES = ["Yield rose", "Yield 𝑥 rose", "rose 𝑥", "𝑥𝑦 and 😀 then 𝔸 rose", "été and café", "", "𝑥"]


@pytest.fixture(scope="module")
def positions(tmp_path_factory):
    table = []
    for text in CASES:
        for cp in range(len(text) + 1):
            table.append([text, cp])
    probe = f"""
const {{ textPositions, cpToIndex, indexToCp, cpLength, breaksToIndex, passageNode }} = await import(LIB);
const table = {json.dumps(table, ensure_ascii=False)};
const out = {{ index: [], back: [], lengths: {{}}, inside: [] }};
for (const [text, cp] of table) {{
  const i = cpToIndex(text, cp);
  out.index.push(text.slice(i));
  out.back.push(indexToCp(text, i));
  out.lengths[text] = cpLength(text);
}}
// a string index inside a pair of surrogates counts as the pair's start
out.inside.push(indexToCp("Yield 𝑥 rose", 7), indexToCp("𝑥𝑦", 1), indexToCp("𝑥𝑦", 3));
out.plain = textPositions("plain text").plain === true && cpToIndex("plain text", 4) === 4;
out.breaks = breaksToIndex("𝑥 a. Heading b", [{{ at: 5, end: 12, kind: "heading" }}]);
// the app's offsets of "rose" after 𝑥, turned into indices, mark "rose", not " ros"
const el = passageNode("Yield 𝑥 rose", cpToIndex("Yield 𝑥 rose", 8), cpToIndex("Yield 𝑥 rose", 12));
out.mark = el.childNodes[1].textContent;
// many places in a long text with many such characters: one table, bisected (not a scan per place)
const long = "𝑥 word ".repeat(20000);
const t0 = Date.now();
let sum = 0;
for (let k = 0; k < 20000; k++) sum += cpToIndex(long, k * 7);
out.longMs = Date.now() - t0;
out.longOk = long.slice(cpToIndex(long, 7 * 1000), cpToIndex(long, 7 * 1000) + 7) === "𝑥 word";
console.log(JSON.stringify(out));
"""
    return run(probe, tmp_path_factory.mktemp("positions")), table


@needs_node
def test_an_offset_of_the_app_finds_the_same_text_on_the_page(positions):
    out, table = positions
    for (text, cp), rest in zip(table, out["index"]):
        assert rest == text[cp:], (text, cp)   # what Python's text[cp:] is, the page's slice is too


@needs_node
def test_a_place_on_the_page_goes_back_to_the_app_as_the_same_offset(positions):
    out, table = positions
    assert out["back"] == [cp for _text, cp in table]
    assert out["lengths"] == {t: len(t) for t in CASES}


@needs_node
def test_a_place_inside_a_pair_of_surrogates_counts_as_its_character(positions):
    out, _ = positions
    assert out["inside"] == [6, 0, 1]


@needs_node
def test_a_text_without_such_characters_keeps_its_offsets_and_breaks_move_with_them(positions):
    out, _ = positions
    assert out["plain"] is True
    text = "𝑥 a. Heading b"
    assert out["breaks"][0]["at"] == 6 and out["breaks"][0]["end"] == 13
    assert text[5:12] == "Heading"


@needs_node
def test_a_quote_after_a_mathematical_letter_is_highlighted_on_its_own_words(positions):
    out, _ = positions
    assert "Yield 𝑥 rose"[8:12] == "rose"
    assert out["mark"] == "rose"


@needs_node
def test_many_places_in_a_long_text_are_found_without_scanning_it_each_time(positions):
    out, _ = positions
    assert out["longOk"] is True
    assert out["longMs"] < 1000


# ---- Search: the marks the server sends land on the words it found --------------------------------------------
@needs_node
def test_the_words_search_found_are_marked_after_a_mathematical_letter(tmp_path):
    d = tmp_path / "corpus"
    d.mkdir()
    (d / "a.txt").write_text("Yield 𝑥 rose with water stress, and 😀 water stress fell when water was cheap. " * 3, encoding="utf-8")
    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [d])
    r = concordance.search(ws, "water stress", mode="all")
    lines = [x for x in r["lines"] if x["marks"]]
    assert lines
    want = [[(x["left"] + x["node"] + x["right"])[a:b] for a, b in x["marks"]] for x in lines]
    probe = f"""
const {{ markedText }} = await import({json.dumps((STATIC / 'views' / 'search.js').as_uri())});
const lines = {json.dumps(lines, ensure_ascii=False)};
console.log(JSON.stringify(lines.map((x) => markedText(x.left + x.node + x.right, x.marks)
  .filter((n) => typeof n !== "string").map((n) => n.textContent))));
"""
    assert run(probe, tmp_path) == want


def test_search_words_answer_one_listener_and_count_as_the_app_does():
    js = _js("views/search.js")
    spans = _fn(js, "function wordSpans", "\n}\n")
    assert "onClick" not in spans and "title:" not in spans   # thousands of listeners and tooltips per page before
    assert "onClick: (e) => wordClick(e, addWord)" in js
    assert "cpLength(x.left) + cpLength(x.node)" in js and "x.left.length + x.node.length" not in js
    assert "cpLength(p.text)" in js and "p.text.length" not in js


def test_an_older_page_of_search_results_is_not_drawn_over_a_newer_one():
    js = _js("views/search.js")
    go = _fn(js, "async function go_()")
    assert "const mine = fresh();" in go and "if (mine()) drawLines(r);" in go
    assert "if (!mine()) return;" in _fn(js, "async function meaningResults")


# ---- the reading view ---------------------------------------------------------------------------------------------
def test_two_loads_at_once_add_the_next_blocks_once():
    js = _js("views/doc-page.js")   # 0.18.4: the document page left sources.js
    more = _fn(js, "function loadMore()")
    assert "if (!loading) loading = loadNext().finally(() => { loading = null; });" in more
    assert "if (rows.has(b.n)) continue;" in _fn(js, "function addBlocks(bs)")


def test_the_page_beside_the_text_follows_the_rows_added_later():
    js = _js("views/doc-page.js")
    assert "for (const w of rowWatchers) w.observe(row);" in _fn(js, "function addBlocks(bs)")
    page = _js("views/doc-reading.js")   # the Page panel
    assert "rowWatchers.add(seen);" in page and "rowWatchers.delete(seen)" in page


def test_painting_sweeps_the_decorations_once_and_next_hit_moves_the_current_row():
    js = _js("views/doc-page.js")
    paint = _fn(js, "  function paint() {")
    assert "all.filter(" not in paint and "while (next < all.length && all[next].start < b.end)" in paint
    go = _fn(_js("views/doc-lookup.js"), "  function go(i) {", "\n  }\n")   # in the Search panel
    assert "draw()" not in go and 'classList.add("dv-cur")' in go


def test_the_reading_view_turns_the_apps_offsets_into_indices_of_each_block():
    js = _js("views/doc-page.js")
    block = _fn(js, "  function blockText(b, decos)")
    assert "pos.index(x.start - b.start)" in block and "b.start + pos.point(a)" in block
    assert "breaksToIndex(text," in block
    assert "o + textPositions(node.data).point(offset)" in js and "cpLength(t.data)" in js
    assert "b.start + pos.point(s), end: b.start + pos.point(e)" in _fn(js, "  function wordAt(off)")
    assert "pos.index(s - b.start), pos.index(e - b.start)" in _fn(js, "  function docSlice(s, e)")


def test_cancelling_let_claude_read_this_puts_the_rows_choice_back_in_place():
    js = _js("views/sources.js")
    fn = _fn(js, "async function setAccess", "\n    }\n")
    head = fn[:fn.index("const body")]
    assert "patchDocs({ documents: docs.filter((d) => ids.includes(d.doc_id)) }, ids)" in head and "reloadDocs" not in head


def test_a_zotero_link_with_another_scheme_is_not_a_link():
    js = _js("views/doc-page.js")
    assert 'safeHref(d.bib.link, ["http", "https", "zotero"])' in js and "href: d.bib.link" not in js


# ---- the result page ------------------------------------------------------------------------------------------
def test_a_look_answered_after_a_save_does_not_put_the_judgement_back():
    js = _js("views/result.js")
    fetch = _fn(js, "  async function fetchResult(")
    assert "return mine() ? r : null;" in fetch
    load = _fn(js, "  async function load(opts = {})")
    assert "if (!r) return;" in load and "fetchResult(!!opts.ifChanged)" in load
    assert "look ? newest.quiet() : newest()" in fetch
    # every other fetch of the result goes through the same count
    assert js.count('api("GET", `/api/projects/${P(project)}/hypotheses/${P(hypId)}?threshold=${threshold}`)') == 2


def test_while_a_check_waits_the_page_is_drawn_again_only_when_its_answer_changed():
    js = _js("views/result.js")
    assert "load({ ifChanged: true })" in _fn(js, "  function armWait()")
    load = _fn(js, "  async function load(opts = {})")
    assert "JSON.stringify(r) === JSON.stringify(current)" in load and "if (waitsForClaude(r)) armWait();" in load


def test_the_result_page_marks_quotes_by_the_apps_offsets():
    js = _js("views/result.js")
    assert "cpToIndex(p.text" in js and "breaksToIndex(p.text" in js
    assert "passageNode(p.text, hsI, heI," in js and "excerptWindow(p.text, hsI, heI, brI," in js
    assert "indexToCp(t, i)" in _fn(js, "  function secondQuote(p)")
    assert "cpLength(p.text" in _fn(js, "  function quoteSpan(p)")
    block = _fn(js, "export function blockNode", "\n}\n")
    assert "const n = cpLength(text);" in block and "cpToIndex(text, s), cpToIndex(text, e)" in block and "breaksToIndex(text," in block


def test_unused_helpers_are_gone():
    lib, result = _js("lib.js"), _js("views/result.js")
    assert "partsSentence" not in lib and "PART_PHRASE" not in lib
    assert "projectZipLink" not in result


# ---- the shared helpers ---------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def helpers(tmp_path_factory):
    probe = r"""
const lib = await import(LIB);
const out = {};
out.names = [
  lib.dispositionName(`attachment; filename="_bel Gerg_ check.xlsx"; filename*=UTF-8''%C3%81bel%20Gerg%C5%91%20check.xlsx`),
  lib.dispositionName('attachment; filename="plain.csv"'),
  lib.dispositionName("attachment; filename=bare.txt"),
  lib.dispositionName(""),
];
out.hrefs = [lib.safeHref("https://example.org/a"), lib.safeHref("javascript:alert(1)"), lib.safeHref(" JaVaScRiPt:x"),
  lib.safeHref("zotero://select/items/ABC"), lib.safeHref("zotero://select/items/ABC", ["http", "https", "zotero"]),
  lib.safeHref("data:text/html,x"), lib.safeHref(null), lib.safeHref("/relative")];
out.search = [lib.searchHref("green hydrogen"), lib.searchHref("green hydrogen", { mode: "phrase" }), lib.searchHref("a+b & c", { mode: null, docs: "d1" })];
const fresh = lib.latest();
const a = fresh(), b = fresh();
const look = fresh.quiet();          // a look every few seconds: it makes b no older
const c = fresh();                   // a request after the look: the look is old now
out.latest = [a(), b(), look(), c()];
const fresh2 = lib.latest();
const save = fresh2(), look2 = fresh2.quiet();
out.quiet = [save(), look2()];
const now = new Date(2026, 10, 12, 18, 0);
out.when = [lib.fmt.whenText(new Date(2026, 10, 12, 17, 26).toISOString(), now), lib.fmt.whenText(new Date(2026, 10, 11, 9, 5).getTime(), now),
  lib.fmt.whenText(new Date(2026, 10, 4, 17, 26).getTime() / 1000, now), lib.fmt.whenText(new Date(2025, 10, 4, 17, 26).toISOString(), now),
  lib.fmt.whenText(null, now)];
// menus: one listener on the document for any number of menus; the window's only while a floating list is open
let docClicks = 0;
document.addEventListener = (t) => { if (t === "click") docClicks++; };
for (let i = 0; i < 50; i++) lib.menu({ items: [{ text: "Remove" }] });
out.docClicks = docClicks;
const bytes = (arr) => ({ arrayBuffer: async () => new Uint8Array(arr).buffer });
out.decoded = [await lib.readTextFile(bytes([0xEF, 0xBB, 0xBF, 0x41, 0xC3, 0xA1])), await lib.readTextFile(bytes([0x47, 0x65, 0x72, 0x67, 0xF5])),
  await lib.readTextFile(bytes([0x63, 0x61, 0x66, 0xE9]))];
console.log(JSON.stringify(out));
"""
    return run(probe, tmp_path_factory.mktemp("helpers"))


@needs_node
def test_a_download_keeps_its_name_with_accents(helpers):
    assert helpers["names"] == ["Ábel Gergő check.xlsx", "plain.csv", "bare.txt", ""]


@needs_node
def test_a_link_from_a_library_opens_only_by_the_schemes_named(helpers):
    assert helpers["hrefs"] == ["https://example.org/a", None, None, None, "zotero://select/items/ABC", None, None, None]


@needs_node
def test_the_search_link_is_written_once_with_its_mode_as_an_option(helpers):
    assert helpers["search"] == ["#/search?q=green%20hydrogen", "#/search?q=green%20hydrogen&mode=phrase", "#/search?q=a%2Bb%20%26%20c&docs=d1"]


@needs_node
def test_only_the_newest_request_is_still_the_newest(helpers):
    assert helpers["latest"] == [False, False, False, True]
    assert helpers["quiet"] == [True, True]   # a look never makes a save's answer old


@needs_node
def test_when_reads_today_yesterday_or_the_day(helpers):
    assert helpers["when"] == ["Today 17:26", "Yesterday 09:05", "4 Nov 17:26", "4 Nov 2025 17:26", ""]


@needs_node
def test_fifty_menus_share_one_click_listener_on_the_document(helpers):
    assert helpers["docClicks"] <= 1


@needs_node
def test_an_uploaded_file_is_read_as_utf8_or_as_a_windows_code_page(helpers):
    assert helpers["decoded"] == ["Aá", "Gergő", "café"]


def test_the_shared_helpers_are_used_where_this_batch_needs_them():
    lib = _js("lib.js")
    assert "saveBlob(blob, filename || dispositionName(" in _fn(lib, "export async function download", "\n}\n")
    assert 'document.addEventListener("click", outside)' not in lib
    sources = "\n".join(_js(f"views/{f}") for f in ("sources.js", "doc-page.js", "doc-reading.js", "doc-codes.js", "doc-lookup.js"))   # 0.18.4: split
    assert "searchHref(" in sources and "#/search?q=${encodeURIComponent" not in sources
