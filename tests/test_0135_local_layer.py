"""0.13.5: stylesheet layers and the local layer.

- index.html links ENLENS's sheets, then the marker `<!-- release stylesheets end -->`, then site.css last.
- site.css ships empty; the colour and type tokens live in tokens.css (loaded first), not in app.css.
- brand.json holds the app's name and words; the page reads it from /api/state.
- The local layer's files exist and say releases never edit them.
- The stand-in add-on (a package, through its entry point) and a fork (gui/extensions.py) change the look and the name
  without touching index.html, app.css or the page code.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from _static import MARKER, SITE, STATIC, assert_sheet_after, defined_tokens, index_html, release_sheets
from test_app import api, home  # noqa: F401  (fixtures)

from enlens_claims import addons

ROOT = Path(__file__).resolve().parent.parent
LOCAL_LAYER = ["src/enlens_claims/gui/static/site.css", "src/enlens_claims/gui/static/brand.json",
               "src/enlens_claims/gui/extensions.py", "docs/ADDON_API.md", "docs/ADDON_MANUAL.md"]


def test_the_marker_and_site_css_last():
    index = index_html()
    sheets = re.findall(r'<link rel="stylesheet" href="([^"]+)">', index)
    assert sheets[-1] == SITE and index.count(MARKER) == 1
    assert index.index(MARKER) < index.index(SITE)
    ours = release_sheets(index)
    assert ours[:2] == ["/static/tokens.css", "/static/app.css"]
    assert SITE not in ours
    assert_sheet_after("/static/v0134.css", "/static/v0133.css", index)
    for f in ours:  # every sheet named is shipped
        assert (STATIC / f.removeprefix("/static/")).is_file(), f


def test_the_helper_catches_a_sheet_after_site_css():
    import pytest

    bad = index_html().replace(f'<link rel="stylesheet" href="{SITE}">',
                               f'<link rel="stylesheet" href="{SITE}">\n<link rel="stylesheet" href="/static/v9.css">')
    with pytest.raises(AssertionError, match="only site.css may follow"):
        assert_sheet_after("/static/v0134.css", "/static/v0133.css", bad)
    with pytest.raises(AssertionError, match="must come after"):
        assert_sheet_after("/static/v0133.css", "/static/v0134.css")


def test_site_css_ships_empty():
    css = (STATIC / "site.css").read_text(encoding="utf-8")
    assert re.sub(r"/\*.*?\*/", "", css, flags=re.S).strip() == ""
    assert "never edit" in css


def test_the_tokens_are_in_tokens_css():
    tokens = (STATIC / "tokens.css").read_text(encoding="utf-8")
    app = (STATIC / "app.css").read_text(encoding="utf-8")
    assert not re.findall(r"^\s*--[a-z0-9-]+\s*:", app, flags=re.M)  # app.css defines none any more
    for block in (":root {", '@media (prefers-color-scheme: dark) {\n  :root:not([data-theme="light"]) {',
                  ':root[data-theme="dark"] {'):
        assert block in tokens, block
    defined = defined_tokens()
    for t in ("--accent", "--font-ui", "--font-serif", "--bg", "--surface", "--ok", "--bad", "--heat-4", "--radius"):
        assert t in defined, t
    used, scoped = set(), set()
    for f in STATIC.glob("*.css"):
        css = f.read_text(encoding="utf-8")
        used |= set(re.findall(r"var\((--[a-z0-9-]+)", css))
        if f.name not in ("tokens.css", "app.css"):
            scoped |= set(re.findall(r"(--[a-z0-9-]+)\s*:", css))  # set on one part of the page (.result's sizes)
    assert used <= defined | scoped, used - defined - scoped


def test_brand_json_and_the_state(api):  # noqa: F811
    b = json.loads((STATIC / "brand.json").read_text(encoding="utf-8"))
    assert set(b) == set(addons.BRAND_KEYS) and b["name"] == "ENLENS" and b["logo"] == "/static/logo.svg"
    st, state = api("GET", "/api/state")
    assert st == 200 and state["brand"] == b


def test_the_page_names_the_app_from_the_brand():
    lib = (STATIC / "lib.js").read_text(encoding="utf-8")
    assert "export function brand()" in lib and "export function appName()" in lib
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    code = "\n".join(l for l in app.splitlines() if not l.lstrip().startswith("//"))
    assert "ENLENS" not in code  # every name in app.js comes from brand.json
    assert "applyBrand();" in app and 'querySelector(".sidebar .brand-text")' in app
    setup = (STATIC / "views" / "setup.js").read_text(encoding="utf-8")
    assert "brand().welcome_title" in setup and "brand().welcome_text" in setup and "ENLENS" not in setup


def test_the_local_layer_files_exist_and_are_empty_in_enlens():
    for f in LOCAL_LAYER:
        assert (ROOT / f).is_file(), f
    from enlens_claims.gui import extensions

    assert not addons.defines(extensions)  # a docstring only
    assert addons.names() == []
    for f in ("docs/ADDON_API.md", "docs/ADDON_MANUAL.md"):
        assert "never edit" in (ROOT / f).read_text(encoding="utf-8"), f
    ext = (ROOT / "docs" / "EXTENDING.md").read_text(encoding="utf-8")
    for f in LOCAL_LAYER:
        assert Path(f).name in ext, f


def test_the_stand_in_addon_changes_the_name_and_the_look(api, addon):  # noqa: F811
    """Done when: without touching index.html, app.css or the page code."""
    before = {f: (STATIC / f).read_bytes() for f in ("index.html", "app.css", "app.js", "lib.js")}
    st, state = api("GET", "/api/state")
    assert state["brand"]["name"] == "Fieldnotes" and state["brand"]["welcome_title"] == "Welcome to Fieldnotes"
    assert state["brand"]["logo"] == "/static/logo.svg"  # not set by the add-on: brand.json's
    assert "not_a_brand_key" not in state["brand"]
    st, css = api("GET", "/static/site.css", token=False)
    assert st == 200 and b"/* add-on: fake */" in css and b"--accent: #8a3b12" in css
    assert css.startswith((STATIC / "site.css").read_bytes())  # the installation's own comes first
    st, own = api("GET", "/static/addons/fake/site.css", token=False)
    assert st == 200 and b".fake-addon-card" in own
    for bad in ("/static/addons/fake/../__init__.py", "/static/addons/fake/%2e%2e/__init__.py",
                "/static/addons/nobody/site.css", "/static/addons/fake/nothing.css"):
        assert api("GET", bad, token=False)[0] == 404, bad
    assert before == {f: (STATIC / f).read_bytes() for f in before}


def test_a_fork_changes_the_name_in_gui_extensions(api, local_addon):  # noqa: F811
    local_addon.set(BRAND={"name": "Margin", "tagline": "a writing companion", "logo": ""})
    assert addons.names() == ["local"]
    b = api("GET", "/api/state")[1]["brand"]
    assert b["name"] == "Margin" and b["tagline"] == "a writing companion" and b["logo"] == "/static/logo.svg"


def test_an_addon_that_fails_to_load_leaves_enlens_running(api, monkeypatch):  # noqa: F811
    class Broken:
        name = "broken"

        def load(self):
            raise ImportError("no module named broken_addon")

    monkeypatch.setattr(addons, "_entry_points", lambda: [Broken()])
    try:
        addons.load(refresh=True)
        assert addons.errors() == [{"addon": "broken", "error": "ImportError: no module named broken_addon"}]
        st, state = api("GET", "/api/state")
        assert st == 200 and state["brand"]["name"] == "ENLENS"
    finally:
        monkeypatch.undo()
        addons.load(refresh=True)
    assert addons.errors() == []
