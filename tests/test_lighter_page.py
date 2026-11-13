"""0.18.1 (roadmap H5): a lighter page. Long lists are drawn a page at a time as the page scrolls (lazyList in lib.js:
the Search page's lines, the answers, a check's excerpt cards), the hypotheses list can be asked for a page at a time,
and a judgement changes only what it changes on the result page instead of drawing the whole page again.

lib.js's helper runs in Node with the stand-in document of tests/_fakedom.py; the pages are checked as the browser
files they are, like the other page tests; the paging is checked through the API."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from _fakedom import NODE, run
from test_app import api, home  # noqa: F401  (fixtures)

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"


def _js(name):
    return (STATIC / name).read_text(encoding="utf-8")


def _fn(src, start, end="\n  }\n"):
    i = src.index(start)
    return src[i:src.index(end, i)]


# ---------------------------------------------------------------------------------------------- the API's pages
class _FakeApp:
    """What ChecksApi.get_hypotheses asks of the app: the whole list, as App.hypotheses answers it."""

    def __init__(self, n):
        self.rows = [{"hyp_id": f"h{i:03}", "text": f"hypothesis {i}", "status": "supported" if i % 2 else "unsupported"} for i in range(n)]
        self.asked = []

    def hypotheses(self, name, q):
        self.asked.append(dict(q))
        rows = list(self.rows)
        status = (q.get("status") or [None])[0] if isinstance(q.get("status"), list) else q.get("status")
        if status:
            rows = [r for r in rows if r["status"] == status]
        limit = int(float((q.get("limit") or ["0"])[0])) if "limit" in q else 0   # as App.hypotheses: limit alone cuts
        rows = rows[:limit] if limit else rows
        return {"hypotheses": rows, "counts": {"supported": 5, "unsupported": 5}, "threshold": 0.6}


def _handler(n=10):
    from enlens_claims.gui.api_checks import ChecksApi

    h = ChecksApi()
    h.app = _FakeApp(n)
    return h


def test_hypotheses_without_offset_answer_as_they_always_did():
    h = _handler(10)
    whole = h.get_hypotheses("P", {})
    assert len(whole["hypotheses"]) == 10 and set(whole) == {"hypotheses", "counts", "threshold"}
    cut = h.get_hypotheses("P", {"limit": ["3"]})   # limit alone still cuts the list, with no paging keys
    assert [r["hyp_id"] for r in cut["hypotheses"]] == ["h000", "h001", "h002"] and "total" not in cut


def test_hypotheses_come_a_page_at_a_time_in_the_order_of_the_whole_list():
    h = _handler(10)
    pages = [h.get_hypotheses("P", {"offset": [str(o)], "limit": ["4"]}) for o in (0, 4, 8)]
    assert [len(p["hypotheses"]) for p in pages] == [4, 4, 2]
    assert all(p["total"] == 10 and p["limit"] == 4 and p["counts"] == {"supported": 5, "unsupported": 5} for p in pages)
    assert [p["offset"] for p in pages] == [0, 4, 8]
    ids = [r["hyp_id"] for p in pages for r in p["hypotheses"]]
    assert ids == [r["hyp_id"] for r in h.app.rows]   # nothing twice, nothing missing, same order
    # the app was asked for the whole list (the counts and the filters need it), never for a cut one
    assert all("limit" not in q and "offset" not in q for q in h.app.asked)


def test_a_page_past_the_end_is_empty_and_a_filter_changes_the_total():
    h = _handler(10)
    past = h.get_hypotheses("P", {"offset": ["50"], "limit": ["4"]})
    assert past["hypotheses"] == [] and past["total"] == 10
    some = h.get_hypotheses("P", {"offset": ["0"], "limit": ["3"], "status": ["supported"]})
    assert some["total"] == 5 and len(some["hypotheses"]) == 3 and all(r["status"] == "supported" for r in some["hypotheses"])
    assert h.get_hypotheses("P", {"offset": ["-5"]})["offset"] == 0
    assert h.get_hypotheses("P", {"offset": ["0"]})["limit"] == 100   # a page is 100 rows when not said


def test_the_real_list_pages_and_keeps_its_order(api, corpus):
    assert api("PUT", "/api/settings", {"backend": "baseline"})[0] == 200
    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    for f in sorted(corpus.iterdir()):
        assert api("POST", f"/api/projects/Demo/uploads?batch=b1&name={f.name}", raw=f.read_bytes())[0] == 200
    st, r = api("POST", "/api/projects/Demo/ingest", {"batch": "b1"})
    assert api.wait(r["job"]["id"])["state"] == "done"
    text = "\n".join(f"Green hydrogen production can increase water stress in arid regions, case {i}." for i in range(5))
    st, r = api("POST", "/api/projects/Demo/batches", {"text": text, "k": 2})
    assert api.wait(r["job"]["id"], timeout=120)["state"] == "done"
    whole = api("GET", "/api/projects/Demo/hypotheses")[1]
    assert len(whole["hypotheses"]) == 5 and "total" not in whole
    got = []
    for o in (0, 2, 4):
        st, page = api("GET", f"/api/projects/Demo/hypotheses?offset={o}&limit=2")
        assert st == 200 and page["total"] == 5 and page["counts"] == whole["counts"]
        got += [x["hyp_id"] for x in page["hypotheses"]]
    assert got == [x["hyp_id"] for x in whole["hypotheses"]]
    assert api("GET", "/api/projects/Demo/hypotheses?offset=0&limit=3&q=nomatch")[1]["total"] == 0


# ---------------------------------------------------------------------------------------------- the helper
PROBE = r"""
const { lazyList, h } = await import(LIB);
Element.prototype.append = function (...n) { for (const x of n.flat(Infinity)) this.appendChild(typeof x === "string" ? document.createTextNode(x) : x); };
Object.defineProperty(Element.prototype, "isConnected", { get() { let n = this; while (n.parentNode) n = n.parentNode; return n === document.body; } });
globalThis.addEventListener = () => {}; globalThis.removeEventListener = () => {};
const IO = { cb: null, made: 0, observed: 0 };
globalThis.IntersectionObserver = class { constructor(cb) { IO.cb = cb; IO.made++; } observe() { IO.observed++; } unobserve() {} disconnect() {} };
const li = (x) => h("li", {}, `item ${x}`);
const text = (l) => l.footer.children[0].textContent;   // the status line (the button is the next child)
const button = (l) => l.footer.children.find((c) => c.tagName === "BUTTON");
const nums = (n, from = 0) => Array.from({ length: n }, (_, i) => from + i);
const out = {};

// 1. a local list: the first page, the count, "Show more", reveal() up to an item, everything fits
{
  const l = lazyList({ items: nums(250), render: li, pageSize: 100, noun: ["line", "lines"] });
  document.body.appendChild(l.el); document.body.appendChild(l.footer);
  out.local = { first: l.el.children.length, text: text(l), hidden: l.footer.hidden };
  button(l).click();
  out.local.afterMore = [l.el.children.length, text(l)];
  out.local.focus = document.activeElement === l.el.children[100];
  out.local.revealed = l.reveal((x) => x === 240);
  out.local.afterReveal = [l.shown(), l.el.children.length, text(l), button(l).hidden];
  out.local.missing = l.reveal((x) => x === 999);
  const small = lazyList({ items: nums(30), render: li, pageSize: 100 });
  out.small = { drawn: small.el.children.length, hidden: small.footer.hidden };
  const none = lazyList({ items: [], render: li, empty: h("p", {}, "Nothing here") });
  out.none = { hidden: none.footer.hidden, text: text(none) };
  const all = lazyList({ items: nums(60), render: li, pageSize: 20 });
  all.revealAll();
  out.all = [all.el.children.length, text(all)];
}

// 2. from the API: the first page is given, the others asked for once each, never twice
{
  const calls = [];
  const fetchPage = async (offset, limit) => { calls.push([offset, limit]); return { items: nums(Math.min(limit, 7 - offset), offset), total: 7 }; };
  const l = lazyList({ first: { items: nums(3), total: 7 }, fetchPage, render: li, pageSize: 3, noun: "line" });
  document.body.appendChild(l.el); document.body.appendChild(l.footer);
  out.api = { first: l.el.children.length, text: text(l), calls: calls.length };
  await Promise.all([l.more(), l.more(), l.more()]);   // three asks at once are one request
  out.api.afterThree = [l.shown(), calls.slice()];
  await l.more(); await l.more();                        // the last page, then nothing more to ask
  out.api.end = [l.shown(), calls.slice(), text(l), button(l).hidden];
  out.api.rows = l.el.children.map((c) => c.textContent).join("|");
}

// 3. a failure: said, no automatic loading, "Try again" asks the same page again
{
  let fail = true; const calls = [];
  const fetchPage = async (offset, limit) => { calls.push(offset); if (fail) { fail = false; throw new Error("down"); } return { items: nums(2, offset), total: 5 }; };
  const l = lazyList({ first: { items: nums(3), total: 5 }, fetchPage, render: li, pageSize: 3, noun: "line" });
  document.body.appendChild(l.el); document.body.appendChild(l.footer);
  await l.more();
  out.fail = { text: text(l), label: button(l).textContent, shown: l.shown() };
  IO.cb([{ isIntersecting: true }]);   // the page scrolling does not retry by itself
  await new Promise((r) => setTimeout(r, 0));
  out.fail.callsAfterScroll = calls.slice();
  button(l).click(); await new Promise((r) => setTimeout(r, 0));
  out.fail.retry = { calls: calls.slice(), shown: l.shown(), text: text(l) };
}

// 4. the page scrolling asks for the next page; reset() drops an answer that arrives late
{
  const calls = []; let release;
  const fetchPage = (offset, limit) => { calls.push(offset); return new Promise((r) => { release = () => r({ items: nums(3, offset), total: 9 }); }); };
  const l = lazyList({ first: { items: nums(3), total: 9 }, fetchPage, render: li, pageSize: 3, noun: "line" });
  document.body.appendChild(l.el); document.body.appendChild(l.footer);
  IO.cb([{ isIntersecting: true }]);
  await new Promise((r) => setTimeout(r, 0));
  out.scroll = { calls: calls.slice(), loading: l.footer.attributes["aria-busy"] || null };
  l.reset({ items: nums(2, 100), total: 2 });   // a new query while the page is on its way
  release(); await new Promise((r) => setTimeout(r, 0));
  out.reset = { rows: l.el.children.map((c) => c.textContent).join("|"), shown: l.shown(), hidden: l.footer.hidden };
}

// 5. without IntersectionObserver the button is the way
{
  delete globalThis.IntersectionObserver;
  const l = lazyList({ items: nums(150), render: li, pageSize: 100 });
  button(l).click();
  out.noObserver = l.el.children.length;
}
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    if not NODE:
        pytest.skip("node is not installed")
    return run(PROBE, tmp_path_factory.mktemp("probe"))


def test_a_local_list_draws_a_page_says_how_many_and_reveals_up_to_an_item(probe):
    t = probe["local"]
    assert t["first"] == 100 and t["text"] == "100 of 250 lines" and t["hidden"] is False
    assert t["afterMore"] == [200, "200 of 250 lines"] and t["focus"] is True   # the focus goes on to the first new item
    assert t["revealed"] is True and t["afterReveal"] == [250, 250, "All 250 lines shown", True]
    assert t["missing"] is False
    assert probe["small"] == {"drawn": 30, "hidden": True}            # everything on the first page: nothing to say
    assert probe["none"] == {"hidden": False, "text": "Nothing here"}
    assert probe["all"] == [60, "All 60 items shown"]                   # what print draws


def test_pages_from_the_api_are_asked_for_once_each(probe):
    a = probe["api"]
    assert a["first"] == 3 and a["text"] == "3 of 7 lines" and a["calls"] == 0     # the first page is not asked for again
    assert a["afterThree"] == [6, [[3, 3]]]                                          # three asks at once are one request
    assert a["end"] == [7, [[3, 3], [6, 3]], "All 7 lines shown", True]
    assert a["rows"] == "|".join(f"item {i}" for i in range(7))


def test_a_failed_page_is_said_and_can_be_asked_again(probe):
    f = probe["fail"]
    assert f["text"] == "Could not load more lines." and f["label"] == "Try again" and f["shown"] == 3
    assert f["callsAfterScroll"] == [3]                                              # scrolling does not retry by itself
    assert f["retry"] == {"calls": [3, 3], "shown": 5, "text": "All 5 lines shown"}


def test_scrolling_asks_for_the_next_page_and_a_reset_drops_a_late_answer(probe):
    assert probe["scroll"] == {"calls": [3], "loading": "true"}
    r = probe["reset"]
    assert r["rows"] == "item 100|item 101" and r["shown"] == 2 and r["hidden"] is True


def test_without_an_intersection_observer_the_button_still_loads_more(probe):
    assert probe["noObserver"] == 150


# ---------------------------------------------------------------------------------------------- the pages
def test_the_helper_is_exported_and_documented():
    lib = _js("lib.js")
    assert "export function lazyList({" in lib and "IntersectionObserver" in _fn(lib, "export function lazyList({", "\n}\n")
    assert 'rootMargin: "900px 0px"' in lib and "beforeprint" in lib


def test_the_search_page_loads_its_lines_as_it_scrolls():
    js = _js("views/search.js")
    assert "lazyList({ first: { items: r.lines, total: r.total }" in js and 'noun: "line"' in js
    assert "lines.footer" in js and "offset" in js and "limit" in js
    assert '"Previous"' not in js and "Lines ${fmt.num(st.offset" not in js     # no pages to turn
    assert "const base = apiQs();" in js                                         # later pages ask what the first one asked


def test_the_answers_list_uses_the_helper():
    js = _js("views/history.js")
    draw = _fn(js, "  function drawTable() {")
    assert "lazyList({ items: rows, render: answerRow" in draw and "drawInSteps" not in js
    assert "steps.shown()" in draw and "steps.footer" in draw


def test_the_result_page_draws_long_card_lists_in_pages_and_still_finds_every_card():
    js = _js("views/result.js")
    assert "const LIST_PAGE = 40;" in js and "lazyList({ items, render: make, pageSize: LIST_PAGE" in js
    # every jump to an excerpt goes through findCard(), which draws the card first when it is not drawn yet
    find = _fn(js, "  function findCard(claimId, passageId) {")
    assert "l.lazy.reveal(" in find
    for where in ("function assessmentBlock(a)", "function nextToReview"):
        assert "findCard(" in js[js.index(where):js.index(where) + 2500], where
    assert "const showIt = () => { const el = findCard(part.claim_id, p.passage_id);" in js
    assert "returnTo" in js and "findCard(id.claim_id, id.passage_id)" in js and "findCard(f.claim_id, f.passage_id)" in js
    # no lookup of a card by the DOM alone is left in a jump (placeOf, which measures a card that is drawn, and the
    # in-place update, which replaces the cards that are, keep theirs)
    assert len(re.findall(r"box\.querySelector\(`\[data-claim=", js)) <= 6
    # "Next to review" is worked out from the data, in the page's order, not from the cards drawn so far
    order = _fn(js, "  function reviewOrder() {")
    assert "partLists(part)" in order and 'querySelectorAll(".ev")' not in order
    nxt = _fn(js, "  function nextToReview(opts = {}) {")
    assert "findCard(entry.part.claim_id, entry.p.passage_id)" in nxt
    # the cards of a part and "Next to review" share one list of what is shown
    assert "const { judged, forYou, rest, shown: byCount } = partLists(part);" in js


def test_a_judgement_changes_only_what_it_changes():
    js = _js("views/result.js")
    put = _fn(js, "    const put = async (verdict, note, msg, opts = {}) => {", "\n    };\n")
    assert "await applyJudgement(saved)" in put and "await load()" not in put
    assert "await applyJudgement(undone)" in js
    apply_ = _fn(js, "  async function applyJudgement(saved) {")
    assert "inPlacePlan(current, r)" in apply_ and "patchInPlace(plan, r)" in apply_
    assert "draw(r)" in apply_ and "await load()" not in apply_                      # the whole page only as the fallback
    assert "movedNote = saved.moved" in apply_ and "finally { movedNote = null; }" in apply_
    patch = _fn(js, "  function patchInPlace(plan, r) {")
    for part in ('":scope > .answer"', '":scope > .ev-section-head"', "techCard(r, parts)", "partHead(parts[i], r)", "evidenceCard(p, part)", "makeExRow("):
        assert part in patch, part
    assert "answerCard(r, parts, single, allPassages)" in patch and "draw(" not in patch.replace("// ", "")
    # the moved sentence is the answer card's "Just now:" note, once
    card = _fn(js, "  function answerCard(r, parts, single, allPassages) {", "\n  }\n")
    assert "const justMoved = movedNote; movedNote = null;" in card and "followNote, justMoved" in card
    # what makes the page be drawn whole
    plan = _fn(js, "  function inPlacePlan(was, now) {")
    assert 'was.status === "waiting"' in plan and "place(p) !== place(pb[k])" in plan and "changed.length > 8" in plan


def test_the_table_view_rows_can_be_made_one_at_a_time():
    js = _js("views/result.js")
    assert 'const exRow = (part, p, i) => h("tr", { "data-ex-key"' in js and "h(\"tbody\", {}, rows.map(([part, p], i) => exRow(part, p, i)))" in js
