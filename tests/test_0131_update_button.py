"""0.13.1: "Update ENLENS" in the app installs the newest version and restarts into it (as Margin 0.2.1 does).

- GET /api/update says whether a newer ENLENS waits (the latest GitHub release, new commits on a git copy's branch,
  or a newer version already on disk);
- POST /api/update installs it the way ENLENS was installed (update.py) and restarts the app on the same port;
  nothing restarts when ENLENS is up to date or the update fails;
- POST /api/restart restarts into the version on disk (the banner's *Restart now*);
- a real launched copy restarts in place: same port, a new token, and it still quits cleanly;
- the page has the button, and docs/API.md the new routes.
"""
import http.client
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from enlens_claims import __version__

from test_app import Api, home  # noqa: F401  (fixtures)
from helpers import api_docs

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "enlens_claims" / "gui" / "static"


@pytest.fixture()
def served(home):  # noqa: F811
    """A server whose app can restart: the restart is recorded instead of done."""
    from enlens_claims.gui.server import make_server

    srv, app = make_server("127.0.0.1", 0)
    restarts = []
    app.stop = lambda: None
    app.restart = lambda: restarts.append(time.time())
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token), app, restarts
    srv.shutdown()
    srv.server_close()


def _wait(cond, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _fake_update(monkeypatch, check=None, result=None, error=None):
    from enlens_claims import update

    calls = []

    def fake(check_only=False, **kw):
        calls.append(check_only)
        if error:
            raise update.UpdateError(error)
        return check if check_only else result

    monkeypatch.setattr(update, "update", fake)
    return calls


def test_the_state_says_whether_the_app_can_restart(served):
    a, app, _ = served
    assert a("GET", "/api/state")[1]["can_restart"] is True
    app.restart = None
    assert a("GET", "/api/state")[1]["can_restart"] is False


def test_check_reports_a_newer_release(served, monkeypatch):
    a, _, restarts = served
    _fake_update(monkeypatch, check={"updated": False, "version": __version__, "waiting": "9.9.0", "message": "…"})
    st, r = a("GET", "/api/update")
    assert st == 200 and r == {"available": True, "on_disk": False, "version": __version__, "latest": "9.9.0",
                               "changes": None}
    assert restarts == []  # a check never restarts


def test_check_reports_new_commits_on_a_git_copy(served, monkeypatch):
    a, _, _ = served
    _fake_update(monkeypatch, check={"updated": False, "version": __version__, "waiting": 3, "message": "…"})
    r = a("GET", "/api/update")[1]
    assert r["available"] is True and r["latest"] is None and r["changes"] == 3


def test_check_when_up_to_date(served, monkeypatch):
    a, _, _ = served
    _fake_update(monkeypatch, check={"updated": False, "version": __version__, "message": "up to date"})
    assert a("GET", "/api/update")[1]["available"] is False


def test_check_says_why_an_update_cannot_happen(served, monkeypatch):
    a, _, _ = served
    _fake_update(monkeypatch, error="These files of ENLENS were changed on this computer")
    st, r = a("GET", "/api/update")
    assert st == 409 and "changed on this computer" in r["error"]


def test_update_installs_then_restarts_once(served, monkeypatch):
    a, _, restarts = served
    calls = _fake_update(monkeypatch, result={"updated": True, "from": __version__, "version": "9.9.0", "message": "…"})
    st, r = a("POST", "/api/update", {})
    assert st == 200 and r["updated"] is True and r["restarting"] is True and r["version"] == "9.9.0"
    assert calls == [False]
    assert _wait(lambda: len(restarts) == 1)
    st, r = a("POST", "/api/update", {})  # a second click while restarting does not update again
    assert st == 409 and "already being updated" in r["error"] and calls == [False]


def test_nothing_restarts_when_up_to_date(served, monkeypatch):
    a, _, restarts = served
    _fake_update(monkeypatch, result={"updated": False, "version": __version__, "message": "up to date"})
    st, r = a("POST", "/api/update", {})
    assert st == 200 and r == {"updated": False, "restarting": False, "version": __version__}
    time.sleep(0.6)
    assert restarts == []
    assert a("POST", "/api/update", {})[0] == 200  # the lock was let go


def test_a_failed_update_does_not_restart(served, monkeypatch):
    a, _, restarts = served
    _fake_update(monkeypatch, error="Installing ENLENS 9.9.0 failed")
    st, r = a("POST", "/api/update", {})
    assert st == 409 and "9.9.0 failed" in r["error"]
    time.sleep(0.6)
    assert restarts == []
    st, r = a("POST", "/api/update", {})  # it can be tried again: the lock was let go
    assert st == 409 and "already" not in r["error"]


def test_a_version_already_on_disk_only_needs_a_restart(served, monkeypatch):
    from enlens_claims.gui import server

    a, _, restarts = served
    calls = _fake_update(monkeypatch, error="must not be called")
    monkeypatch.setattr(server, "_installed_version", lambda: "9.9.0")
    r = a("GET", "/api/update")[1]
    assert r["available"] is True and r["on_disk"] is True and r["latest"] == "9.9.0"
    r = a("POST", "/api/update", {})[1]
    assert r["restarting"] is True and r["version"] == "9.9.0" and calls == []
    assert _wait(lambda: len(restarts) == 1)


def test_update_and_restart_need_an_app_that_can_restart(served, monkeypatch):
    a, app, _ = served
    app.restart = None
    _fake_update(monkeypatch, error="must not be called")
    assert a("POST", "/api/update", {})[0] == 409
    assert a("POST", "/api/restart", {})[0] == 409


def test_restart_route(served):
    a, _, restarts = served
    st, r = a("POST", "/api/restart", {})
    assert st == 200 and r["restarting"] is True
    assert _wait(lambda: len(restarts) == 1)


def test_the_restart_command():
    from enlens_claims.gui.server import restart_command

    cmd = restart_command("127.0.0.1", 8766, launcher=True)
    assert cmd[:3] == [sys.executable, "-m", "enlens_claims.gui.launch"]
    assert cmd[cmd.index("--port") + 1] == "8766" and "--headless" in cmd and "--launcher" in cmd
    assert "--launcher" not in restart_command("127.0.0.1", 8766, launcher=False)


def test_a_launched_copy_restarts_in_place(home, tmp_path):  # noqa: F811
    """A real launch from the icon: Restart answers, the same port comes back with a new token, and Quit still works."""
    from enlens_claims.gui import launcher

    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    env = {**os.environ, "ENLENS_HOME": str(home.home())}
    cmd = [sys.executable, "-m", "enlens_claims.gui.launch", "--launcher", "--headless", "--no-start-ollama",
           "--port", str(port)]
    proc = subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def token_now():
        live = launcher.running(timeout=0.5)
        if not live:
            return None
        try:
            page = urllib.request.urlopen(live["url"], timeout=5).read().decode()
            return live["url"].rstrip("/"), page.split('name="enlens-token" content="')[1].split('"')[0]
        except (OSError, IndexError, http.client.HTTPException):
            return None  # 0.13.5: a restart began between the two: "not answering yet", not an error

    try:
        assert _wait(lambda: token_now() is not None, timeout=15), "ENLENS did not start"
        url, token = token_now()
        assert url == f"http://127.0.0.1:{port}"
        assert Api(url, token)("POST", "/api/restart", {})[1]["restarting"] is True
        assert _wait(lambda: (t := token_now()) is not None and t[1] != token, timeout=30), "ENLENS did not come back"
        url2, token2 = token_now()
        assert url2 == url  # the open page finds it where it was
        assert proc.poll() is None  # macOS and Linux: the same process became the new copy
        a = Api(url2, token2)
        assert a("GET", "/api/state")[1]["version"] == __version__
        assert a("POST", "/api/quit", {})[1]["stopping"] is True
        assert proc.wait(timeout=15) == 0
        log = (home.home() / "logs" / "enlens.log").read_text()
        assert "Restarting ENLENS with the version now installed" in log
    finally:
        if proc.poll() is None:
            proc.kill()


def test_page_files():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index('id="update-btn"') < html.index('id="quit-btn"')
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "function updateInit()" in app and "updateInit();\n  quitInit();" in app
    assert 'api("POST", "/api/update", {})' in app
    lib = (STATIC / "lib.js").read_text(encoding="utf-8")  # 0.13.6: the look is shared (checkUpdate)
    assert 'api("GET", fresh ? "/api/update?fresh=1" : "/api/update")' in lib
    assert 'api("POST", "/api/restart", {})' in app and "location.reload()" in app


def test_the_routes_are_documented():
    from enlens_claims.gui.server import ROUTES

    api_md = api_docs()  # 0.13.5: every docs/*API*.md
    for method, rx, _name in ROUTES:
        path = rx.pattern.strip("^$")
        if path in ("/api/restart", "/api/update"):
            assert f"`{method} {path}`" in api_md, (method, path)
    assert "can_restart" in api_md
