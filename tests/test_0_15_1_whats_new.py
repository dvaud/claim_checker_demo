"""0.15.1: the small "what's new" note, shown once after an update.

- `static/whats-new.md` is parsed (heading, subtitle, points); anything malformed is no note;
- `GET /api/whats-new` serves it when its version is the running one and it has not been seen, and marks it seen;
- a new installation is marked silently; a different version is never shown.
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


def test_shown_once_after_an_update(api, note_file):
    _update_from_0_15_0()
    st, body = api("GET", "/api/whats-new")
    assert st == 200 and body["note"]["version"] == __version__ and len(body["note"]["points"]) == 3
    assert homemod.load_settings()["whats_new_seen"] == __version__
    assert api("GET", "/api/whats-new")[1] == {"note": None}


def test_not_shown_on_a_new_installation(api, note_file):
    assert api("GET", "/api/whats-new")[1] == {"note": None}   # nothing there yet
    assert homemod.load_settings()["whats_new_seen"] == __version__
    homemod.create_project("Demo")                                  # the first project, made afterwards
    assert api("GET", "/api/whats-new")[1] == {"note": None}


def test_not_shown_with_projects_but_no_settings_file(api, note_file):
    homemod.create_project("Demo")
    assert api("GET", "/api/whats-new")[1] == {"note": None}


def test_not_shown_when_the_version_differs(api, note_file):
    note_file.write_text(_note("0.0.1"), encoding="utf-8")
    _update_from_0_15_0()
    assert api("GET", "/api/whats-new")[1] == {"note": None}
    assert homemod.load_settings()["whats_new_seen"] == ""   # not marked: the note was not for this version


def test_a_missing_or_broken_file_is_no_error(api, note_file):
    _update_from_0_15_0()
    note_file.write_text("garbage", encoding="utf-8")
    assert api("GET", "/api/whats-new") == (200, {"note": None})
    note_file.unlink()
    assert api("GET", "/api/whats-new") == (200, {"note": None})


def test_the_note_of_this_release():
    n = server.parse_whats_new((STATIC / "whats-new.md").read_text(encoding="utf-8"))
    assert n and 1 <= len(n["points"]) <= 6 and n["title"] and n["subtitle"]
    assert all(len(p) < 110 for p in n["points"])


def test_the_route_and_the_page():
    assert any(m == "GET" and rx.pattern == "^/api/whats-new$" for m, rx, _ in server.ROUTES)
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert '"/api/whats-new"' in js and 'aria-label": "Close"' in js and '"Escape"' in js


def test_the_md_file_is_packaged():
    toml = (STATIC.parents[3] / "pyproject.toml").read_text(encoding="utf-8")
    assert '"gui/static/*"' in toml   # the pattern covers whats-new.md
