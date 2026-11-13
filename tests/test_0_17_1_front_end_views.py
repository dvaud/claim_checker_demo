"""The deep dive after 0.17.0, the other pages: a big grid that can be drawn, an older answer that never replaces a newer
one, a quick look that stops when it is stopped, a sidebar that keeps looking after one failed request, and the helpers
of lib.js used in place of the copies the pages had written.

Node runs the pieces that are logic (a grid's largest count, the quick look with a stand-in for lib.js); the rest is
read as text, as the other tests of the page do.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from _fakedom import NODE, run
from enlens_claims import bibliography

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"
needs_node = pytest.mark.skipif(not NODE, reason="node is not installed")


def _js(rel: str) -> str:
    return (STATIC / rel).read_text(encoding="utf-8")


def _fn(js: str, start: str, end: str = "\n  }\n") -> str:
    body = js[js.index(start):]
    return body[:body.index(end) + len(end)]


# ---- F3: a project of thousands of documents draws its grids ---------------------------------------------------
@needs_node
@pytest.mark.parametrize("rel", ["views/profile.js", "views/themes.js"])
def test_a_grid_of_three_hundred_thousand_cells_finds_its_largest_count(rel, tmp_path):
    src = _fn(_js(rel), "function gridMax", "\n}\n")
    probe = tmp_path / "grid.mjs"
    probe.write_text(src + r"""
const grid = {};
for (let d = 0; d < 2000; d++) { const row = {}; for (let c = 0; c < 150; c++) row[`c${c}`] = (d * c) % 97; grid[`d${d}`] = row; }
grid.d1999.c149 = 412;
let spread = "fine";
try { Math.max(1, ...Object.values(grid).flatMap((row) => Object.values(row))); } catch (e) { spread = e.name; }
console.log(JSON.stringify({ max: gridMax(grid), empty: gridMax({}), small: gridMax({ a: { x: 0 } }), spread }));
""", encoding="utf-8")
    out = json.loads(subprocess.run([NODE, str(probe)], capture_output=True, text=True, check=True).stdout)
    assert out["max"] == 412 and out["empty"] == 1 and out["small"] == 1
    assert out["spread"] in ("RangeError", "fine")   # (the old way throws on this machine's node, or the limit is higher)


def test_no_page_spreads_a_list_that_grows_with_the_project_into_math_max():
    for rel in ("views/profile.js", "views/themes.js"):
        assert not re.search(r"Math\.(max|min)\([^)]*\.\.\.Object\.values", _js(rel)), rel


# ---- F7, F16: the newest look is the one drawn --------------------------------------------------------------
def test_an_older_look_at_the_answers_does_not_draw_over_a_newer_one():
    hist = _js("views/history.js")
    refresh = _fn(hist, "  async function refresh() {")
    assert "const mine = fresh();" in refresh and "if (stopped || !mine()) return;" in refresh
    assert "if (!mine()) return; failedLoad(tableBox, e)" in refresh   # an old failure does not either
    assert "const fresh = latest();" in hist


def test_an_older_page_of_the_log_and_of_the_notes_is_not_drawn_over_a_newer_one():
    for rel, kind in (("views/log.js", "log"), ("views/notes.js", "note")):
        js = _js(rel)
        load = _fn(js, "  async function load() {")
        assert "const mine = fresh();" in load and "if (!mine()) return;" in load, rel
        assert "if (mine()) failedLoad(listBox, e)" in load, rel


def test_the_suggested_codes_of_an_older_text_are_not_drawn_over_those_of_a_newer_one():
    js = _js("views/hypotheses.js")
    suggest = _fn(js, "  const fetchSuggestions = debounce(")
    assert "const mine = freshSuggestions();" in suggest and "if (!mine()) return;" in suggest


def test_the_sharing_map_is_read_once_for_the_page_and_again_after_a_change_to_an_item():
    log = _js("views/log.js")
    load = _fn(log, "  async function load() {")
    assert 'sharesStale ? sharingOf("log") : null' in load and "sharesStale = false" in load
    assert load.count("sharingOf(") == 1
    assert "sharesStale = true; await load();" in log        # a new entry, an edit, a removal
    assert "sharesStale = true; return load();" in log       # Share / Unshare on an entry
    notes = _js("views/notes.js")
    assert 'sharesStale ? sharingOf("note") : null' in _fn(notes, "  async function load() {")
    assert "noteCard(n, changed," in notes and "const changed = () => { sharesStale = true; return load(); };" in notes
    # typing in the search box and the filters only look again at the list
    assert "q = search.value.trim(); load(); }, 250)" in notes and "q = search.value.trim(); shown = PAGE; load(); }, 250)" in log


# ---- F8: the quick look stops when it is stopped ----------------------------------------------------------
STUB_LIB = r"""
export const S = { calls: [], errors: [], navs: [], dialogs: [], toasts: [], post: null, watch: null };
export const App = { refresh: async () => {}, state: {}, project: "p" };
export const P = encodeURIComponent;
export const h = () => ({}); export const icon = () => null; export const replace = () => {}; export const button = () => null; export const notice = () => null;
export const fmt = { bytes: (n) => `${n} B`, dateShort: () => "" };
export const toast = (m) => S.toasts.push(m);
export const showError = (e) => S.errors.push(e.message || String(e));
export const navigate = (hash) => S.navs.push(hash);
export const confirmDialog = () => null;
export function api(method, path, body, opts = {}) {
  S.calls.push([method, path]);
  return path.startsWith("/api/quicklook") ? S.post(opts) : Promise.resolve({});
}
// the real dialog(): closes (and removes itself) on its own "cancel" event, and never resolves otherwise
export function dialog({ onOpen }) {
  return new Promise((resolve) => {
    const dlg = { isConnected: true,
      close() { if (this.isConnected) { this.isConnected = false; resolve(null); } },
      dispatchEvent(e) { if (e.type === "cancel") this.close(); return true; } };
    S.dialogs.push(dlg);
    if (onOpen) onOpen(dlg);
  });
}
export function watchJob(id) {
  const w = { id, stopped: false };
  w.promise = new Promise((res) => { w.res = res; });
  S.watch = w;
  return { promise: w.promise, stop() { w.stopped = true; } };
}
"""

QUICKLOOK_PROBE = r"""
import { startQuickLook } from "./views/quicklook.js";
import { S } from "./lib.js";
const tick = () => new Promise((r) => setTimeout(r, 0));
const file = { name: "report.pdf", size: 2048 };
const cancels = () => S.calls.filter(([m, p]) => m === "POST" && p.endsWith("/cancel")).map(([, p]) => p);
const reset = () => { Object.assign(S, { calls: [], errors: [], navs: [], dialogs: [], toasts: [], post: null, watch: null }); };
const out = {};

// A: Stop while the file is still being copied: the copy is cut off, nothing is reported, no job is stopped
reset();
let aborted = false;
S.post = (opts) => new Promise((_, rej) => opts.signal.addEventListener("abort", () => { aborted = true; rej(Object.assign(new Error("The operation was aborted."), { name: "AbortError" })); }));
let p = startQuickLook(file); await tick();
S.dialogs[0].close(); await p;
out.A = { aborted, errors: S.errors, navs: S.navs, cancels: cancels(), watched: !!S.watch };

// B: the job ends while a Find (another dialog) is open: only the quick look's own dialog closes, and the document opens
reset();
S.post = async () => ({ job: { id: "j1" } });
p = startQuickLook(file); await tick(); await tick();
const other = { isConnected: true, close() { this.isConnected = false; }, dispatchEvent() { return true; } };
S.dialogs.push(other);
S.watch.res({ state: "done", result: { documents_added: [{ doc_id: "d 1" }] } });
await p;
out.B = { own: S.dialogs[0].isConnected, other: other.isConnected, navs: S.navs, errors: S.errors, cancels: cancels() };

// C: Stop while the job runs: the job is stopped, and nothing opens when it ends
reset();
S.post = async () => ({ job: { id: "j2" } });
p = startQuickLook(file); await tick(); await tick();
S.dialogs[0].close(); await tick();
const stopped = cancels();
S.watch.res({ state: "cancelled" });
await p;
out.C = { stopped, navs: S.navs, errors: S.errors };

// D: Stop as the copy ends: the job is stopped as soon as it is known, and is not followed
reset();
let finish;
S.post = () => new Promise((res) => { finish = () => res({ job: { id: "j3" } }); });
p = startQuickLook(file); await tick();
S.dialogs[0].close(); await tick();
finish(); await p;
out.D = { cancels: cancels(), watched: !!S.watch, navs: S.navs };

// E: an error of the app is shown, and the dialog is gone
reset();
S.post = async () => { throw new Error("The app is not answering."); };
p = startQuickLook(file); await tick(); await p;
out.E = { errors: S.errors, own: S.dialogs[0].isConnected };
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def quicklook(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("quicklook")
    (tmp / "views").mkdir()
    (tmp / "package.json").write_text('{"type": "module"}')
    (tmp / "views" / "quicklook.js").write_text(_js("views/quicklook.js"), encoding="utf-8")
    (tmp / "views" / "progress.js").write_text("export const simpleProgress = () => null;")
    (tmp / "lib.js").write_text(STUB_LIB)
    # the page's views import "../lib.js": the stand-in sits beside views/, as lib.js does
    (tmp / "run.mjs").write_text(QUICKLOOK_PROBE)
    r = subprocess.run([NODE, str(tmp / "run.mjs")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@needs_node
def test_stopping_a_quick_look_while_the_file_is_copied_cuts_the_copy_off(quicklook):
    assert quicklook["A"] == {"aborted": True, "errors": [], "navs": [], "cancels": [], "watched": False}


@needs_node
def test_a_quick_look_that_ends_closes_only_its_own_dialog(quicklook):
    b = quicklook["B"]
    assert b["own"] is False and b["other"] is True      # the Find that was open stays open
    assert b["navs"] == ["#/doc/d%201?tab=terms"] and b["errors"] == [] and b["cancels"] == []


@needs_node
def test_stopping_a_quick_look_stops_its_job_and_opens_nothing(quicklook):
    assert quicklook["C"] == {"stopped": ["/api/jobs/j2/cancel"], "navs": [], "errors": []}
    d = quicklook["D"]
    assert d["cancels"] == ["/api/jobs/j3/cancel"] and d["watched"] is False and d["navs"] == []


@needs_node
def test_a_quick_look_that_fails_shows_the_error_and_leaves_no_dialog(quicklook):
    assert quicklook["E"] == {"errors": ["The app is not answering."], "own": False}


def test_the_quick_look_no_longer_closes_whichever_dialog_is_open():
    js = _js("views/quicklook.js")
    assert 'document.querySelector("#dialogs dialog")' not in js
    assert "signal: upload.signal" in js and "new AbortController()" in js


# ---- F10: the sidebar's status keeps looking ----------------------------------------------------------------
def test_one_failed_look_at_the_jobs_does_not_end_the_sidebars_status():
    app = _js("app.js")
    status = _fn(app, "async function drawStatus() {", "\n}\n")
    assert "statusTimer = setTimeout(renderStatus, Math.min(60000, 5000 * 2 ** Math.min(statusFailures++, 4)));" in status
    assert "statusFailures = 0;" in status                  # a look that works starts the waiting over
    assert "if (again && document.hidden) again = Math.max(again, HIDDEN_LOOK);" in status
    assert 'document.addEventListener("visibilitychange", () => { if (!document.hidden) renderStatus(); });' in app


# ---- F12: Escape in a dialog does not also close the drawer ----------------------------------------------
def test_escape_in_a_dialog_leaves_the_log_drawer_open():
    js = _js("views/logdrawer.js")
    assert '"#dialogs dialog[open]"' in js and "[role=dialog]" not in js


# ---- F13: Try it works once at a time and stops with its page ------------------------------------------
def test_try_it_waits_while_its_job_runs_and_its_watcher_stops_with_the_page():
    js = _js("views/codebooks.js")
    assert "disabled: trying, onClick: (e) => tryIt(e.currentTarget)" in js
    try_it = _fn(js, "  async function tryIt(btn) {")
    assert "if (trying) return;" in try_it and "setBusy(btn, true)" in try_it and "setBusy(btn, false)" in try_it
    assert "tryWatch = watchJob(r.job.id);" in try_it
    assert 'return () => { window.removeEventListener("beforeunload", onUnload); if (tryWatch) tryWatch.stop(); };' in js


# ---- F20-F23: one copy of each helper ---------------------------------------------------------------------
def test_the_research_log_drawer_uses_the_one_when_text_of_lib():
    js = _js("views/logdrawer.js")
    assert "export function whenText" not in js and "fmt.whenText(e.at)" in js


def test_the_search_links_of_the_pages_come_from_lib_and_finder_keeps_its_own_mode():
    for rel in ("views/concepts.js", "views/themes.js"):
        js = _js(rel)
        assert "const searchHref" not in js and 'searchHref(' in js and '{ mode: "phrase" }' in js, rel
    finder = _js("finder.js")
    assert "const searchHref" not in finder and "href: searchHref(q)," in finder   # what a person typed: the page's own Find mode


def test_the_benchmark_result_is_saved_with_the_one_download_of_lib():
    js = _js("views/settings.js")
    assert "saveBlob(blob, `benchmark_" in js and "URL.createObjectURL" not in js


def test_the_unused_severity_words_are_gone():
    assert "SEVERITY_WORDS" not in _js("views/owner-state.js")


@needs_node
def test_a_text_is_normalised_once_by_lib_for_the_answers_and_the_hypotheses(tmp_path):
    out = run(r"""
const { norm } = await import(LIB);
console.log(JSON.stringify([norm("  Remote  work\n raises\twellbeing "), norm(null), norm("")]));
""", tmp_path)
    assert out == ["Remote work raises wellbeing", "", ""]
    for rel in ("views/history.js", "views/hypotheses.js"):
        js = _js(rel)
        assert "const norm =" not in js and re.search(r"import \{[^}]*\bnorm\b[^}]*\} from \"../lib.js\"", js), rel


# ---- E4: a file from an older program is read in its own code page -------------------------------------------
def test_the_files_a_person_loads_are_read_by_the_one_reader_of_lib():
    for rel in ("views/bibliography.js", "views/codebooks.js", "views/hypotheses.js"):
        js = _js(rel)
        assert "readTextFile(f)" in js and "f.text()" not in js, rel
    assert "function readCsv" not in _js("views/codebooks.js")


# ---- F2: the bibliography's links and excerpts ----------------------------------------------------------------
def test_a_works_link_to_zotero_is_a_link_only_by_a_web_or_zotero_scheme():
    js = _js("views/bibliography.js")
    assert 'safeHref(w.link, ["http", "https", "zotero"])' in js and "href: w.link" not in js


@needs_node
def test_the_found_words_of_a_pair_are_marked_by_the_apps_offsets_after_a_mathematical_letter(tmp_path):
    head = "𝑥 and 😀 note. A study of Hybrid work and wellbeing in teams"
    where = bibliography._where({"head": head}, "Hybrid work")
    assert where["excerpt"][where["start"]:where["end"]] == "Hybrid work"   # Python counts code points
    out = run(r"""
const { cpToIndex } = await import(LIB);
const ev = %s;
console.log(JSON.stringify({ plain: ev.excerpt.slice(ev.start, ev.end),   // what the page did: one place too far left for each 😀
  converted: ev.excerpt.slice(cpToIndex(ev.excerpt, ev.start), cpToIndex(ev.excerpt, ev.end)) }));
""" % json.dumps(where), tmp_path)
    assert out["converted"] == "Hybrid work" and out["plain"] != "Hybrid work"
    js = _js("views/bibliography.js")
    assert "cpToIndex(ev.excerpt, ev.start)" in js and "cpToIndex(ev.excerpt, ev.end)" in js


# ---- F18: the drawer asks for one title, not the list of documents ---------------------------------------
def test_the_log_drawer_asks_for_the_one_document_it_names():
    js = _js("views/logdrawer.js")
    title = _fn(js, "  async function titleOf(ctx) {")
    assert "/documents/${P(ctx.subject_id)}?limit=1" in title and 'documents`)' not in title


# ---- F17: the answers are drawn in steps ------------------------------------------------------------------------
def test_the_answers_table_draws_its_first_rows_and_the_rest_as_it_scrolls():
    js = _js("views/history.js")
    draw = _fn(js, "  function drawTable() {")
    assert "lazyList({ items: rows, render: answerRow, list: tbody," in draw and "Math.max(60, keep)" in draw   # 0.18.1: lazyList
    assert "rows.map((x) => {" not in draw


# ---- F24: CSS nothing uses -----------------------------------------------------------------------------------
def test_the_two_rules_nothing_could_produce_are_gone():
    assert ".note-head " not in _js("views.css") and ".log-who" not in _js("components.css")
