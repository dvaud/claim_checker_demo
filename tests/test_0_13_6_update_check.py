"""0.13.6: the Update button shows only when there is an update; Settings has Check for updates.

- the page looks when it opens and every two minutes; the server keeps its answer (or why it has none) a little less
  than that, so the open tabs share one look, and `?fresh=1` (Settings → Check for updates) looks again now;
- a one-line install learns the newest version from GitHub's release page (its redirect), which GitHub's limit of 60
  API requests an hour does not count, and falls back to the API when the page does not say;
- the shared state in lib.js (checkUpdate) runs in Node with a stand-in fetch;
- the page files: the button stays hidden until a look finds something, a pop-up, Settings' section, the stylesheet.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from enlens_claims import __version__

from test_app import Api, home  # noqa: F401  (fixtures)
from test_0131_update_button import served  # noqa: F401  (fixture)
from test_0100_setup_and_moving import NEXT, Runs, _releases
from _static import release_sheets
from helpers import manual_text

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "enlens_claims" / "gui" / "static"
NODE = shutil.which("node")
TAG = "https://github.com/dvaud/claim_checker_demo/releases/tag/v"


# ---------------------------------------------------------------------------------------------
# update.py: the release page instead of the API
# ---------------------------------------------------------------------------------------------
def test_the_newest_version_from_the_release_page():
    from enlens_claims import update

    asked = []

    def peek(url):
        asked.append(url)
        return TAG + "9.9.0"

    assert update.latest_version(peek) == "9.9.0"
    assert asked == ["https://github.com/dvaud/claim_checker_demo/releases/latest"]
    assert update.latest_version(lambda url: "https://github.com/dvaud/claim_checker_demo/releases") == ""  # no release

    def offline(url):
        raise OSError("no network")

    with pytest.raises(update.UpdateError, match="Are you online"):
        update.latest_version(offline)


def test_a_check_reads_the_page_and_never_the_api():
    from enlens_claims import update

    def no_api(url):
        raise AssertionError(f"the API was asked: {url}")

    r = update.update_release(check_only=True, fetch=no_api, peek=lambda url: TAG + NEXT, run=Runs())
    assert r["waiting"] == NEXT and "ready to install" in r["message"]
    r = update.update_release(check_only=True, fetch=no_api, peek=lambda url: TAG + __version__, run=Runs())
    assert r["updated"] is False and "waiting" not in r
    # the page does not say: the API does
    r = update.update_release(check_only=True, fetch=_releases(), peek=lambda url: "", run=Runs())
    assert r["waiting"] == NEXT


def test_only_the_apps_quick_check_uses_the_page(monkeypatch):
    from enlens_claims import installation, update

    monkeypatch.setattr(update, "source_root", lambda: None)
    monkeypatch.setattr(installation, "kind", lambda: "script")
    seen = []
    monkeypatch.setattr(update, "update_release", lambda check_only=False, run=None, peek=None: seen.append((check_only, peek)) or {})
    update.update(check_only=True, quick=True)
    update.update(check_only=True)  # enlens update --check: as before
    update.update(quick=True)  # an install never takes the page's word
    assert seen == [(True, update._peek), (True, None), (False, None)]


# ---------------------------------------------------------------------------------------------
# GET /api/update: one look shared by the tabs, fresh on request
# ---------------------------------------------------------------------------------------------
def _looks(monkeypatch, answers):
    """update.update stands in: each look takes the next answer (a dict, or an error message)."""
    from enlens_claims import update

    calls = []

    def fake(check_only=False, quick=False, **kw):
        calls.append((check_only, quick))
        a = answers[min(len(calls), len(answers)) - 1]
        if isinstance(a, str):
            raise update.UpdateError(a)
        return a

    monkeypatch.setattr(update, "update", fake)
    return calls


NEWER = {"updated": False, "version": __version__, "waiting": "9.9.0", "message": "…"}
SAME = {"updated": False, "version": __version__, "message": "up to date"}


def test_the_answer_is_kept_and_shared(served, monkeypatch):  # noqa: F811
    a, app, restarts = served
    calls = _looks(monkeypatch, [SAME, NEWER])
    assert a("GET", "/api/update")[1]["available"] is False
    assert a("GET", "/api/update")[1]["available"] is False  # kept: no second look
    assert calls == [(True, True)]  # a check, the quick way
    st, r = a("GET", "/api/update?fresh=1")  # Check for updates: looks now
    assert st == 200 and r["available"] is True and r["latest"] == "9.9.0" and len(calls) == 2
    assert restarts == []


def test_a_kept_answer_expires(served, monkeypatch):  # noqa: F811
    from enlens_claims.gui import server

    a, app, _ = served
    calls = _looks(monkeypatch, [SAME, NEWER])
    assert a("GET", "/api/update")[1]["available"] is False
    app.update_seen["at"] -= server.UPDATE_LOOK_EVERY  # the page's next look, two minutes on
    assert a("GET", "/api/update")[1]["available"] is True and len(calls) == 2
    assert server.UPDATE_LOOK_EVERY < 120  # less than the page's two minutes: each of its looks is a real one


def test_a_failed_look_is_kept_too(served, monkeypatch):  # noqa: F811
    a, _, _ = served
    calls = _looks(monkeypatch, ["Could not ask GitHub for the newest ENLENS (OSError). Are you online?", SAME])
    for _ in range(2):  # an offline computer is not asked again at once
        st, r = a("GET", "/api/update")
        assert st == 409 and "Are you online" in r["error"]
    assert len(calls) == 1
    assert a("GET", "/api/update?fresh=1")[1]["available"] is False and len(calls) == 2


def test_an_update_forgets_the_kept_answer(served, monkeypatch):  # noqa: F811
    from enlens_claims import update

    a, app, _ = served
    calls = _looks(monkeypatch, [NEWER])
    assert a("GET", "/api/update")[1]["available"] is True
    monkeypatch.setattr(update, "update", lambda check_only=False, **kw: calls.append("x") or SAME)
    assert a("POST", "/api/update", {})[1]["restarting"] is False  # up to date after all
    assert app.update_seen is None  # the next look is a real one
    assert a("GET", "/api/update")[1]["available"] is False


def test_a_version_on_disk_is_seen_at_once(served, monkeypatch):  # noqa: F811
    from enlens_claims.gui import server

    a, _, _ = served
    calls = _looks(monkeypatch, [SAME])
    assert a("GET", "/api/update")[1]["available"] is False
    monkeypatch.setattr(server, "_installed_version", lambda: "9.9.0")
    r = a("GET", "/api/update")[1]  # updated in a terminal meanwhile: not hidden by the kept answer
    assert r["available"] is True and r["on_disk"] is True and len(calls) == 1


# ---------------------------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------------------------
STUB = """
globalThis.document = { querySelector: () => null, addEventListener() {}, documentElement: { dataset: {} } };
globalThis.window = globalThis; globalThis.location = { hash: "", pathname: "/" };
globalThis.history = { replaceState() {} };
globalThis.sessionStorage = { getItem: () => null, setItem() {} }; globalThis.localStorage = globalThis.sessionStorage;
const answers = [];
const asked = [];
globalThis.fetch = async (path) => {
  asked.push(path);
  const [status, body] = answers.shift();
  return { ok: status < 400, status, statusText: "", headers: { get: () => "application/json" },
           json: async () => body, text: async () => JSON.stringify(body) };
};
"""


@pytest.mark.skipif(NODE is None, reason="needs Node")
def test_the_shared_update_state_in_node(tmp_path):
    f = tmp_path / "t.mjs"
    f.write_text(STUB + f"""
const lib = await import({json.dumps((STATIC / "lib.js").as_uri())});
const out = {{ every: lib.UPDATE_EVERY }};
const seen = [];
lib.onUpdateSeen((info, err) => seen.push(err ? "error" : info.available));
answers.push([200, {{ available: true, latest: "9.9.0", version: "0.13.6", on_disk: false }}]);
const p1 = lib.checkUpdate(), p2 = lib.checkUpdate();
out.shared = p1 === p2;  // two asks at once: one request
await p1;
answers.push([409, {{ error: "Are you online?" }}]);
try {{ await lib.checkUpdate(true); }} catch (e) {{ out.error = e.message; }}
out.kept = lib.Updates.info.latest;  // a failed look keeps what the last one found
answers.push([200, {{ available: false, version: "0.13.6" }}]);
await lib.checkUpdate(true);
out.asked = asked; out.seen = seen; out.at = lib.Updates.at > 0;
console.log(JSON.stringify(out));
""")
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["every"] == 120000 and out["shared"] is True
    assert out["asked"] == ["/api/update", "/api/update?fresh=1", "/api/update?fresh=1"]
    assert out["error"] == "Are you online?" and out["kept"] == "9.9.0"
    assert out["seen"] == [True, "error", False] and out["at"] is True


def test_page_files():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '<button class="btn btn-ghost btn-sm" id="update-btn" type="button" hidden></button>' in html
    assert "/static/v0136.css" not in release_sheets()  # its rules are in app.css (shared stylesheets)
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    init = app[app.index("function updateInit()"):app.index("function updatePopup(")]
    assert "btn.hidden = false" not in init.split("function showUpdate(")[0]  # never shown before a look
    assert "if (!info || !info.available) { btn.hidden = true; return; }" in init
    assert "setInterval(look, UPDATE_EVERY)" in init and "visibilitychange" in init
    assert 'store("update-later", key)' in app and "Updates.install()" in app
    assert "checkUpdate()" in app[app.index("async function updateApp("):]  # the kept answer: no second look
    settings = (STATIC / "views" / "settings.js").read_text(encoding="utf-8")
    assert '"Check for updates"' in settings and "checkUpdate(true)" in settings and "updatesSection()" in settings
    assert 'href: "#/settings/updates"' in settings and 'updates: "advanced"' in settings
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert ".update-ready" in css and ".update-popup" in css


def test_the_docs_say_so():
    api_md = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")
    assert "?fresh=1" in api_md
    manual = manual_text()  # the hub and its pages
    assert "Check for updates" in manual
