"""0.16.2: the sidebar is one window-high column. The brand and the project stay at the top, the foot (work running,
the AI line, Settings, Update, Quit) stays at the bottom, and only the list of features scrolls between them; a wheel
over the sidebar never scrolls the page behind it. Checked as the browser files they are, like the other page tests."""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"


def _read(name):
    return (STATIC / name).read_text(encoding="utf-8")


def _rule(css, selector):
    m = re.search(r"(?m)^" + re.escape(selector) + r" \{([^}]*)\}", css)
    assert m, f"no rule for {selector}"
    return " ".join(m.group(1).split())


def test_only_the_list_of_features_scrolls():
    css = _read("app.css")
    sidebar = _rule(css, ".sidebar")
    assert "height: 100dvh" in sidebar and "overflow: hidden" in sidebar and "overflow: auto" not in sidebar
    nav = _rule(css, "#nav")
    assert "flex: 1 1 auto" in nav and "min-height: 0" in nav and "overflow-y: auto" in nav
    assert "overscroll-behavior: contain" in nav
    # the shadows that say more features are beyond an edge use the colour tokens (they work in both themes)
    assert "var(--bg-2)" in nav and "var(--text)" in nav and "rgba(" not in nav
    assert ".sidebar-inner > .brand, .sidebar-inner > .project-switch { flex: none; }" in css


def test_the_foot_stays_and_an_open_panel_scrolls_inside_itself():
    css = _read("app.css")
    foot = _rule(css, ".sidebar-foot")
    assert "flex: none" in foot and "margin-top: auto" in foot
    # the foot is no scrolling box: the AI line's card opens upwards out of it and would be cut off
    assert "overflow" not in foot
    panel = _rule(css, ".sidebar-foot .jobs > .ps-menu")
    assert "max-height: max(120px, calc(100vh - 480px))" in panel and "overflow-y: auto" in panel
    # the phone menu is as high as the visible window, not the window behind the browser's bars
    assert "height: 100vh; height: 100dvh; z-index: 60;" in css


def test_a_wheel_over_the_sidebar_never_scrolls_the_page():
    app = _read("app.js")
    fn = app[app.index("function sidebarScrollInit("):app.index("\n}\n", app.index("function sidebarScrollInit("))]
    assert 'addEventListener("wheel"' in fn and "{ passive: false }" in fn and "e.preventDefault()" in fn
    assert "e.ctrlKey" in fn  # a pinch still zooms
    assert "scrollTop" in fn and "scrollHeight" in fn  # a part that can still scroll that way keeps the turn
    boot = app[app.index("async function boot()"):]
    assert boot.index("drawerInit();") < boot.index("sidebarScrollInit();") < boot.index("navIcons();")
