"""0.14.2: the theme is a small icon at the end of the Settings row, not a row of its own.

- index.html: Settings and the theme icon share one row at the foot of the sidebar; the icon is an icon button, not
  a full-width button with a label;
- app.js: the icon shows the theme in use (monitor, sun, moon), its name stays readable to a screen reader (hidden
  text) and the tooltip says what a click does; the choice is kept as before (store "theme");
- the CSS of the row (in app.css, with the rest of the sidebar foot) uses only the colour tokens.
"""
import re
from pathlib import Path

from _static import all_css, css_blocks, defined_tokens_all, rule

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "enlens_claims" / "gui" / "static"


def _foot():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app = html[html.index('<div class="sidebar-app">'):]
    return app[:app.index("</aside>")]


def test_the_theme_is_an_icon_on_the_settings_row():
    app = _foot()
    row = app[app.index('<div class="sidebar-app-row">'):]
    row = row[:row.index("</div>")]
    assert 'data-route="settings"' in row and 'id="theme-btn"' in row
    assert row.index('data-route="settings"') < row.index('id="theme-btn"')  # the icon at the end of the row
    btn = re.search(r'<button [^>]*id="theme-btn"[^>]*>', row).group(0)
    assert 'class="icon-btn theme-btn"' in btn and "btn-sm" not in btn and 'aria-live="polite"' in btn
    # 0.17.0: Quit sits in the row before the icon, and an update takes Quit's place (the owner's call)
    assert row.index('data-route="settings"') < row.index('id="update-btn"') < row.index('id="quit-btn"') < row.index('id="theme-btn"')


def test_the_icon_says_what_it_does():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    fn = js[js.index("function themeInit()"):]
    fn = fn[:fn.index("\n}\n")]
    for ic in ('"monitor"', '"sun"', '"moon"'):
        assert ic in fn
    assert 'h("span", { class: "visually-hidden" }, label)' in fn  # no visible label, still a name for screen readers
    assert "btn.title = " in fn  # the tooltip: the theme in use and what a click does
    assert 'store("theme")' in fn and 'store("theme", mode === "system" ? null : mode)' in fn  # kept as before


def test_css_of_the_row():
    # 0.17.0: reads the cascade (tests/_static.py rule()), so it holds when the design guide moves the rules; the
    # old "moved, not copied" check of which sheet holds them is gone with the sheets
    assert rule(".sidebar-app .btn[hidden]")["display"] == "none"  # the hidden Quit stays hidden
    row = rule(".sidebar-app-row")
    assert row["display"] == "flex"
    nav = rule(".sidebar-app-row .nav-foot")
    assert nav["flex"] == "1" and nav["min-width"] == "0"
    assert rule(".sidebar-app .theme-btn")
    foot = [d for _m, sels, d in css_blocks(all_css()) if any(s.startswith(".sidebar-app") for s in sels)]
    used = set(re.findall(r"var\((--[a-z0-9-]+)", " ".join(v for d in foot for v in d.values())))
    assert used and used <= defined_tokens_all(), used - defined_tokens_all()
