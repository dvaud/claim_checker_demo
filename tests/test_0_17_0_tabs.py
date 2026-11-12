"""0.17.0: tabs without an address are the whole tab pattern, made by tabs() (docs/DESIGN.md 4.5).

lib.js builds the DOM, so Node runs it here with the stand-in document of tests/_fakedom.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from _fakedom import NODE, STATIC, run

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(not NODE, reason="node is not installed")

PROBE = r"""
const { tabs, drawer } = await import(LIB);
const out = {};
const panel = document.createElement("div");
const seen = [];
const row = tabs({ label: "Views", current: "b", panel, onTab: (k) => seen.push(k),
  items: [{ key: "a", label: "A" }, { key: "b", label: "B" }, { key: "c", label: "C" }] });
const bs = row.children;
const state = () => bs.map((b) => `${b.dataset.key}:${b.getAttribute("aria-selected")}:${b.tabIndex}`).join(" ");
const at = () => document.activeElement && document.activeElement.dataset.key;
const t = out.tabs = {
  role: row.getAttribute("role"), roles: bs.map((b) => b.getAttribute("role")), ids: bs.map((b) => b.id),
  controls: bs.map((b) => b.getAttribute("aria-controls")), current: bs.map((b) => b.getAttribute("aria-current")),
  panel: { role: panel.getAttribute("role"), id: panel.id, labelledby: panel.getAttribute("aria-labelledby") }, start: state(),
};
key(bs[1], "ArrowRight"); t.right = [state(), at(), panel.getAttribute("aria-labelledby")];
key(bs[2], "ArrowRight"); t.wrapRight = [state(), at()];
key(bs[0], "ArrowLeft"); t.wrapLeft = [state(), at()];
key(bs[2], "Home"); t.home = [state(), at()];
key(bs[0], "End"); t.end = [state(), at()];
key(bs[2], "Enter"); t.otherKey = state();
bs[0].click(); t.click = state();
row.choose("b"); t.choose = state();
t.seen = seen;
const links = tabs({ label: "Links", current: "x", items: [["x", "X", "#/x"], ["y", "Y", "#/y"]] });
out.links = links.children.map((a) => ({ tag: a.tagName, current: a.getAttribute("aria-current"), role: a.getAttribute("role"), tabindex: a.getAttribute("tabindex") }));
const d = drawer({ id: "dr", title: "Drawer", tabs: [{ key: "log", label: "Log" }, { key: "team", label: "Team" }], current: "team", onTab: () => {} });
const body = d.children.find((c) => c.className === "drawer-body");
out.drawer = { hasTabs: !!d.tabs, role: body.getAttribute("role"), labelledby: body.getAttribute("aria-labelledby"),
  chosenId: d.tabs.children[1].id, controls: d.tabs.children.map((b) => b.getAttribute("aria-controls")), bodyId: body.id };
const plain = drawer({ id: "dr2", title: "Plain", sections: [] });
out.plainDrawer = { tabs: plain.tabs, role: plain.children.find((c) => c.className === "drawer-body").getAttribute("role") };
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    return run(PROBE, tmp_path_factory.mktemp("probe"))


def test_tabs_without_an_address_are_the_whole_tab_pattern(probe):
    t = probe["tabs"]
    assert t["role"] == "tablist"
    assert t["roles"] == ["tab", "tab", "tab"]
    # each tab its own id, each controlling the panel; the panel is named by the chosen tab
    assert len(set(t["ids"])) == 3 and all(t["ids"])
    assert t["panel"]["role"] == "tabpanel"
    assert t["controls"] == [t["panel"]["id"]] * 3
    assert t["panel"]["labelledby"] == t["ids"][1]
    # chosen: aria-selected, and the only tab in the Tab order (no aria-current: they have no address)
    assert t["start"] == "a:false:-1 b:true:0 c:false:-1"
    assert t["current"] == [None, None, None]


def test_the_arrow_keys_home_and_end_move_between_tabs_and_choose(probe):
    t = probe["tabs"]
    assert t["right"] == ["a:false:-1 b:false:-1 c:true:0", "c", probe["tabs"]["ids"][2]]
    assert t["wrapRight"] == ["a:true:0 b:false:-1 c:false:-1", "a"]   # past the last: the first
    assert t["wrapLeft"] == ["a:false:-1 b:false:-1 c:true:0", "c"]    # before the first: the last
    assert t["home"] == ["a:true:0 b:false:-1 c:false:-1", "a"]
    assert t["end"] == ["a:false:-1 b:false:-1 c:true:0", "c"]
    assert t["otherKey"] == t["end"][0]                                # other keys change nothing
    assert t["click"] == "a:true:0 b:false:-1 c:false:-1"
    assert t["choose"] == "a:false:-1 b:true:0 c:false:-1"             # row.choose(key), from code
    assert t["seen"] == ["c", "a", "c", "a", "c", "a", "b"]


def test_tabs_with_an_address_stay_links(probe):
    assert probe["links"] == [{"tag": "A", "current": "page", "role": None, "tabindex": None},
                              {"tag": "A", "current": None, "role": None, "tabindex": None}]


def test_a_drawer_with_tabs_makes_its_body_their_panel(probe):
    d = probe["drawer"]
    assert d["hasTabs"]
    assert d["role"] == "tabpanel"
    assert d["labelledby"] == d["chosenId"]
    assert d["controls"] == [d["bodyId"], d["bodyId"]]
    # one tab or none: a title, no tab pattern
    assert probe["plainDrawer"] == {"tabs": None, "role": None}


def test_the_guide_and_the_reference_page_say_so():
    guide = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
    assert "Home and End" in guide and "`tabpanel`" in guide
    ref = (STATIC / "views" / "design.js").read_text(encoding="utf-8")
    assert "panel: tabPanel" in ref
