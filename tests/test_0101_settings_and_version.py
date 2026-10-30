"""0.10.1: Settings at the foot of the sidebar, with Theme and Quit; the version shown on the Settings page.

- the list of features (Overview … Results) no longer ends with Settings: Settings is one list with Theme and Quit
  at the foot of the sidebar, and still shows as the current page when a Settings tab is open;
- every Settings tab shows the version in its title row, linking to Technical → Where your data is (how ENLENS was
  installed and how to update it);
- the release's CSS uses only colour tokens defined in app.css (light and dark themes).
"""
import re
from pathlib import Path

from enlens_claims import __version__

from test_app import Api, api, home  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "enlens_claims" / "gui" / "static"


def _html():
    return (STATIC / "index.html").read_text(encoding="utf-8")


def test_settings_is_at_the_foot_with_theme_and_quit():
    html = _html()
    nav = html[html.index('<nav class="nav" aria-label="Main" id="nav">'):]
    nav = nav[:nav.index("</nav>")]
    assert 'data-route="settings"' not in nav and "nav-sep" not in nav
    assert 'data-route="history"' in nav  # the features are all still there
    foot = html[html.index('<div class="sidebar-foot">'):]
    foot = foot[:foot.index("</aside>")]
    app = foot[foot.index('<div class="sidebar-app">'):]
    # Settings, then Theme, then Quit, in one group, below the privacy line
    assert foot.index('id="privacy-indicator"') < foot.index('<div class="sidebar-app">')
    s, t, q = app.index('href="#/settings" data-route="settings"'), app.index('id="theme-btn"'), app.index('id="quit-btn"')
    assert s < t < q
    assert html.count('data-route="settings"') == 1


def test_settings_still_shows_as_the_current_page():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'document.querySelectorAll("#nav a, #nav-foot a")' in js
    assert 'nav.querySelector(".nav-sep")' not in js  # the legend no longer looks for the removed separator


def test_the_settings_page_shows_the_version():
    js = (STATIC / "views" / "settings.js").read_text(encoding="utf-8")
    assert 'pageHead("Settings", { actions: versionTag(),' in js
    tag = js[js.index("function versionTag()"):]
    tag = tag[:tag.index("\n}\n")]
    assert "st.version || VERSION" in tag and 'href: "#/settings/data"' in tag and 'class: `version-tag' in tag


def test_the_version_reaches_the_page(api):  # noqa: F811
    """The number the Settings page shows: /api/state's version, and the page's meta tag as the fallback."""
    code, st = api("GET", "/api/state")
    assert code == 200 and st["version"] == __version__
    code, body = api("GET", "/", token=False)
    assert code == 200 and f'<meta name="enlens-version" content="{__version__}">' in body.decode()


def test_page_files_of_the_release():
    html = _html()
    assert '<link rel="stylesheet" href="/static/v0101.css">' in html
    assert html.index("/static/v010.css") < html.index("/static/v0101.css")
    css = (STATIC / "v0101.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", (STATIC / "app.css").read_text(encoding="utf-8")))
    used = set(re.findall(r"var\((--[a-z0-9-]+)", css))
    assert used and used <= defined, used - defined
    # the hidden Quit button stays hidden although the foot's buttons are flex items
    assert ".sidebar-app .btn[hidden] { display: none; }" in css
    assert "a.version-tag:hover" in css  # a link styled as a pill keeps its own hover colours
