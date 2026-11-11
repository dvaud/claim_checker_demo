"""0.10.1: Settings at the foot of the sidebar, with Theme and Quit; the version shown on the Settings page.

- the list of features (Overview … Results) no longer ends with Settings: Settings is one list with Theme and Quit
  at the foot of the sidebar, and still shows as the current page when a Settings tab is open;
- every Settings tab shows the version in its title row, linking to Technical → Where your data is (how ENLENS was
  installed and how to update it);
- the release's CSS uses only colour tokens defined in tokens.css (light and dark themes).
"""
import re
from pathlib import Path

from enlens_claims import __version__

from test_app import Api, api, home  # noqa: F401  (fixtures)
from _static import all_css, defined_tokens_all, rule

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "enlens_claims" / "gui" / "static"


def _html():
    return (STATIC / "index.html").read_text(encoding="utf-8")


def test_settings_is_at_the_foot_with_theme_and_quit():
    html = _html()
    nav = html[html.index('<nav class="nav" aria-label="Main" id="nav">'):]
    nav = nav[:nav.index("</nav>")]
    assert 'data-route="settings"' not in nav and "nav-sep" not in nav
    assert 'data-route="hypotheses"' in nav  # 0.17.0: the places are all still there (checking and answers are Hypotheses)
    foot = html[html.index('<div class="sidebar-foot">'):]
    foot = foot[:foot.index("</aside>")]
    app = foot[foot.index('<div class="sidebar-app">'):]
    # Settings, then Quit (or, 0.17.0, Update in its place), then the theme icon, in one row, below the status area
    assert foot.index('id="privacy-indicator"') < foot.index('<div class="sidebar-app">')
    s, q, t = app.index('href="#/settings" data-route="settings"'), app.index('id="quit-btn"'), app.index('id="theme-btn"')
    assert s < q < t
    assert html.count('data-route="settings"') == 1


def test_settings_still_shows_as_the_current_page():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'document.querySelectorAll("#nav a, #nav-foot a")' in js
    assert 'nav.querySelector(".nav-sep")' not in js  # the legend no longer looks for the removed separator


def test_the_settings_page_shows_the_version():
    js = (STATIC / "views" / "settings.js").read_text(encoding="utf-8")
    # 0.17.0 (design guide, changed on purpose): the version is a link, so it sits in the line under the title, not at
    # the head's right (which holds only actions)
    assert 'pageHead("Settings", { sub: [' in js and '[tab], " ", versionTag()] }' in js
    tag = js[js.index("function versionTag()"):]
    tag = tag[:tag.index("\n}\n")]
    # 0.13.6: it opens Technical → Updates (Check for updates), just above Where your data is
    assert "st.version || VERSION" in tag and 'href: "#/settings/updates"' in tag and 'class: "version-tag"' in tag  # 0.17.0 (design guide): words with a link, not a pill


def test_the_version_reaches_the_page(api):  # noqa: F811
    """The number the Settings page shows: /api/state's version, and the page's meta tag as the fallback."""
    code, st = api("GET", "/api/state")
    assert code == 200 and st["version"] == __version__
    code, body = api("GET", "/", token=False)
    assert code == 200 and f'<meta name="enlens-version" content="{__version__}">' in body.decode()


def test_page_files_of_the_release():
    html = _html()
    # 0.17.0: the release's rules are in the cascade (tests/_static.py rule()), not in a sheet of its own
    # 0.17.0 (design guide): the version is words with a link (and an attention tag when a newer one waits), drawn by
    # the Links and Tags components, not a pill of its own
    settings = (STATIC / "views" / "settings.js").read_text(encoding="utf-8")
    assert 'h("span", { class: "version-tag" }' in settings and 'link({ href: "#/settings/updates"' in settings
    css = all_css()
    defined = defined_tokens_all()
    used = set(re.findall(r"var\((--[a-z0-9-]+)", css))
    assert used and used <= defined, used - defined
    # the hidden Quit button stays hidden although the foot's buttons are flex items
    assert rule(".sidebar-app .btn[hidden]")["display"] == "none"
    assert "a.version-tag:hover" not in css  # 0.17.0 (design guide): the version is a plain link now, not a pill with hover colours of its own
