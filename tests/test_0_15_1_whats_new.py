"""0.15.1: the small "what's new" note after an update. After 0.17.2 it is read only when asked.

- `static/whats-new.md` is parsed (heading, subtitle, points); anything malformed is no note;
- `GET /api/whats-new` serves it (`changes`) when its version is the running one, and says whether it is unread (an
  update brought it and it has not been opened); serving it marks nothing;
- `POST /api/whats-new/read` marks it read (the sidebar's What's new, once opened, goes);
- a new installation is marked read silently; a different version is never offered.
"""
import json
from pathlib import Path

import pytest

from enlens_claims import __version__
from enlens_claims import home as homemod
from enlens_claims.gui import server

from test_app import Api, api, home  # noqa: F401  (fixtures)

STATIC = Path(server.__file__).resolve().parent / "static"

GOOD = """# 0.15.1: Cleaner text
*Documents read with less clutter around the text.*
- Running heads set aside
-No space after the dash

- Zotero adds a work's PDF
"""


def _note(version):
    return GOOD.replace("0.15.1", version)


@pytest.fixture
def note_file(tmp_path, monkeypatch):
    f = tmp_path / "whats-new.md"
    f.write_text(_note(__version__), encoding="utf-8")
    monkeypatch.setattr(server, "WHATS_NEW_FILE", f)
    return f


def _update_from_0_15_0():
    """A settings file without the new key, and a project: what 0.15.0 leaves behind."""
    homemod.create_project("Demo")
    s = json.loads(json.dumps(homemod.DEFAULTS))
    s.pop("whats_new_seen")
    (homemod.home() / "settings.json").write_text(json.dumps({"_version": 2, **s}), encoding="utf-8")


def test_parse_the_format():
    n = server.parse_whats_new(GOOD)
    assert n == {"version": "0.15.1", "title": "Cleaner text", "subtitle": "Documents read with less clutter around the text.",
                 "points": ["Running heads set aside", "No space after the dash", "Zotero adds a work's PDF"]}


@pytest.mark.parametrize("text", ["", "nothing", "# 0.15.1 no colon\n*s*\n- a", "# 0.15.1: T\nno subtitle\n- a",
                                  "# 0.15.1: T\n*s*", "# 0.15.1: T\n*s*\n- a\nnot a point", "# x: T\n*s*\n- a"])
def test_malformed_is_no_note(text):
    assert server.parse_whats_new(text) is None


def test_offered_after_an_update_until_it_is_read(api, note_file):
    _update_from_0_15_0()
    st, body = api("GET", "/api/whats-new")
    assert st == 200 and body["note"] is None and body["unread"] is True
    assert body["changes"]["version"] == __version__ and len(body["changes"]["points"]) == 3
    assert body["changes"]["url"] == f"https://github.com/dvaud/claim_checker_demo/releases/tag/v{__version__}"
    # looking marks nothing: a reload, or a second tab, still offers it
    assert homemod.load_settings()["whats_new_seen"] == ""
    assert api("GET", "/api/whats-new")[1]["unread"] is True
    assert api("POST", "/api/whats-new/read", {}) == (200, {"unread": False})
    assert homemod.load_settings()["whats_new_seen"] == __version__
    after = api("GET", "/api/whats-new")[1]
    assert after["unread"] is False and after["changes"]["version"] == __version__   # still there, when asked
    assert api("POST", "/api/whats-new/read", {}) == (200, {"unread": False})          # twice is no error


def test_not_offered_on_a_new_installation(api, note_file):
    body = api("GET", "/api/whats-new")[1]   # nothing there yet
    assert body["unread"] is False and body["changes"]["version"] == __version__
    assert homemod.load_settings()["whats_new_seen"] == __version__
    homemod.create_project("Demo")                                  # the first project, made afterwards
    assert api("GET", "/api/whats-new")[1]["unread"] is False


def test_not_offered_with_projects_but_no_settings_file(api, note_file):
    homemod.create_project("Demo")
    assert api("GET", "/api/whats-new")[1]["unread"] is False


def test_not_offered_when_the_version_differs(api, note_file):
    note_file.write_text(_note("0.0.1"), encoding="utf-8")
    _update_from_0_15_0()
    assert api("GET", "/api/whats-new")[1] == {"note": None, "changes": None, "unread": False}
    assert homemod.load_settings()["whats_new_seen"] == ""   # not marked: the note was not for this version


def test_a_missing_or_broken_file_is_no_error(api, note_file):
    _update_from_0_15_0()
    note_file.write_text("garbage", encoding="utf-8")
    nothing = (200, {"note": None, "changes": None, "unread": False})
    assert api("GET", "/api/whats-new") == nothing
    note_file.unlink()
    assert api("GET", "/api/whats-new") == nothing


def test_the_note_of_this_release():
    n = server.parse_whats_new((STATIC / "whats-new.md").read_text(encoding="utf-8"))
    assert n and 1 <= len(n["points"]) <= 6 and n["title"] and n["subtitle"]
    assert all(len(p) < 110 for p in n["points"])


def test_the_route_and_the_page():
    assert any(m == "GET" and rx.pattern == "^/api/whats-new$" for m, rx, _ in server.ROUTES)
    assert any(m == "POST" and rx.pattern == "^/api/whats-new/read$" for m, rx, _ in server.ROUTES)
    lib = (STATIC / "lib.js").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert '"/api/whats-new"' in lib and '"/api/whats-new/read"' in lib
    # after 0.17.2 what is new is read only when asked, in a dialog: never a note in the corner by itself
    show = lib[lib.index("export function showWhatsNew"):lib.index("export function whatsNewLink")]
    assert "dialog({" in show and "/api/whats-new/read" in show
    init = js[js.index("async function whatsNewInit"):js.index("function syncNewsInit")]
    assert "showWhatsNew()" in init and "WhatsNew.unread" in init and "WhatsNew.changes.title" not in init
    assert 'note.kind !== "problem"' in init   # the corner keeps only an update that did not finish
    # the problem note still closes with its icon button or Escape
    assert 'label: "Close"' in js and '"Escape"' in js


def test_what_is_new_is_offered_in_the_sidebar_settings_and_find():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    btn = html[html.index('id="news-btn"') - 80:html.index('id="news-btn"') + 80]
    assert "hidden" in btn and 'aria-haspopup="dialog"' in btn   # shown only while unread
    assert html.index('id="news-btn"') < html.index('class="sidebar-app-row"')   # above the last row, not in it
    settings = (STATIC / "views" / "settings.js").read_text(encoding="utf-8")
    assert "whatsNewLink()" in settings and "showWhatsNew()" in settings
    finder = (STATIC / "finder-index.js").read_text(encoding="utf-8")
    row = next(ln for ln in finder.splitlines() if "Read what's new" in ln)
    assert '"#/settings/updates"' in row and "changelog" in row


def test_the_md_file_is_packaged():
    toml = (STATIC.parents[3] / "pyproject.toml").read_text(encoding="utf-8")
    assert '"gui/static/*"' in toml   # the pattern covers whats-new.md
