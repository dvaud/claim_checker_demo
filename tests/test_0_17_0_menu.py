"""0.17.0: a menu floats over the page only where a frame would cut its list (docs/DESIGN.md 4.17).

lib.js builds the DOM, so Node runs it here with the stand-in document of tests/_fakedom.py; the probe adds the few
layout answers menu() asks for (computed overflow, rectangles, the window's listeners).
"""
from __future__ import annotations

import pytest

from _fakedom import NODE, run

pytestmark = pytest.mark.skipif(not NODE, reason="node is not installed")

PROBE = r"""
const { menu } = await import(LIB);
Object.defineProperty(Node.prototype, "parentElement", { get() { return this.parentNode instanceof Element ? this.parentNode : null; } });
const L = [];
globalThis.addEventListener = (t, f) => L.push([t, f]);
globalThis.removeEventListener = (t, f) => { const i = L.findIndex(([a, b]) => a === t && b === f); if (i >= 0) L.splice(i, 1); };
globalThis.innerWidth = 1280; globalThis.innerHeight = 860;
const styles = new Map();
globalThis.getComputedStyle = (el) => styles.get(el) || { overflowX: "visible", overflowY: "visible" };
const rect = (el, r) => { el.getBoundingClientRect = () => ({ ...r, right: r.left + r.width, bottom: r.top + r.height }); };
function build(overflow, frameRect, listRect, trigRect) {
  const frame = document.createElement("div");
  styles.set(frame, { overflowX: overflow, overflowY: overflow });
  rect(frame, frameRect);
  document.body.appendChild(frame);
  const m = menu({ items: [{ text: "Remove…", danger: true, onClick() {} }] });
  frame.appendChild(m);
  const [trig, list] = m.children;
  rect(list, listRect); list.offsetWidth = listRect.width; list.offsetHeight = listRect.height;
  rect(trig, trigRect);
  return { m, list, frame };
}
const open = (m) => { m.open = true; m.dispatchEvent(new Event("toggle")); };
const shut = (m) => { m.open = false; m.dispatchEvent(new Event("toggle")); };
const scrolls = () => L.filter(([t]) => t === "scroll").map(([, f]) => f);
const out = {};

// the sidebar (overflow hidden): the project list fits inside it, so it hangs from its button
const side = build("hidden", { left: 0, top: 0, width: 264, height: 860 }, { left: 15, top: 130, width: 234, height: 150 }, { left: 15, top: 70, width: 234, height: 56 });
open(side.m);
out.sidebar = { float: side.list.dataset.float || null, left: side.list.style.left || "", listeners: scrolls().length };
shut(side.m);

// a table that scrolls, its last row: the list would run out of the frame, so it floats
const table = build("auto", { left: 318, top: 100, width: 908, height: 600 }, { left: 369, top: 682, width: 220, height: 45 }, { left: 369, top: 650, width: 76, height: 28 });
open(table.m);
out.table = { float: table.list.dataset.float || null, left: table.list.style.left || "", top: table.list.style.top || "" };
// the list's own scroll leaves it open; the page's scroll closes it
for (const f of scrolls()) f({ type: "scroll", target: table.list });
out.ownScroll = table.m.open;
for (const f of scrolls()) f({ type: "scroll", target: table.frame });
out.pageScroll = table.m.open;
shut(table.m);
out.afterClose = { float: table.list.dataset.float || null, left: table.list.style.left || "", top: table.list.style.top || "", listeners: scrolls().length };
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    return run(PROBE, tmp_path_factory.mktemp("probe"))


def test_a_menu_whose_list_fits_hangs_from_its_button(probe):
    """The project switch sits in the sidebar, whose overflow is hidden; its list fits there, so it never floats."""
    assert probe["sidebar"] == {"float": None, "left": "", "listeners": 0}


def test_a_menu_cut_by_its_frame_floats_under_its_button(probe):
    t = probe["table"]
    assert t["float"] == "true"
    assert t["left"] == "369px" and t["top"] == "682px"


def test_the_lists_own_scroll_keeps_it_open_and_the_pages_closes_it(probe):
    assert probe["ownScroll"] is True
    assert probe["pageScroll"] is False


def test_a_closed_menu_forgets_where_it_floated(probe):
    assert probe["afterClose"] == {"float": None, "left": "", "top": "", "listeners": 0}
