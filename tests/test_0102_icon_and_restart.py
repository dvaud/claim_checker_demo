"""0.10.2: the ENLENS icon has its picture without Pillow, and opens the version that is installed.

- the icon files ship with ENLENS (gui/icons/ENLENS.icns, ENLENS.ico): the macOS app and the Windows shortcut use
  them, so an installation without Pillow no longer gets a blank icon;
- an icon made without a picture before is given one when ENLENS starts (`launcher.repair_icons`), and only ENLENS's
  own icons are touched;
- double-clicking the icon while an older version still runs (ENLENS updated meanwhile) quits that copy and starts
  this one; when a check or another job runs in it, it is left alone and opened;
- /api/state says which version is installed now, and the page shows a notice with *Quit ENLENS* when it is newer
  than the one running.
"""
import json
import os
import plistlib
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from enlens_claims import __version__

from test_app import Api, api, home  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "enlens_claims" / "gui" / "static"


def _no_pillow(monkeypatch):
    from enlens_claims.gui import launcher

    monkeypatch.setattr(launcher, "draw_icon", lambda size=512: None)
    return launcher


# ---------------------------------------------------------------------------------------------
# the icon files
# ---------------------------------------------------------------------------------------------
def test_the_icon_files_ship_with_enlens():
    from enlens_claims.gui import launcher

    icns = (launcher.ICONS / "ENLENS.icns").read_bytes()
    assert icns[:4] == b"icns" and int.from_bytes(icns[4:8], "big") == len(icns)
    assert b"ic10" in icns  # 512 points at 2x (1024 pixels), for the Desktop and Finder at full size
    ico = (launcher.ICONS / "ENLENS.ico").read_bytes()
    assert ico[:4] == b"\x00\x00\x01\x00" and int.from_bytes(ico[4:6], "little") == 5
    assert '"gui/icons/*"' in (ROOT / "pyproject.toml").read_text()  # in the wheel the one-line install takes


def test_the_mac_app_gets_its_picture_without_pillow(monkeypatch, tmp_path):
    launcher = _no_pillow(monkeypatch)
    app = launcher.make_launcher(None, False, [tmp_path], python=sys.executable, platform="darwin")[0]
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleIconFile"] == "ENLENS" and info["CFBundleIdentifier"] == "org.enlens.launcher"
    assert (app / "Contents" / "Resources" / "ENLENS.icns").read_bytes() == (launcher.ICONS / "ENLENS.icns").read_bytes()


def test_the_windows_shortcut_gets_its_picture_without_pillow(monkeypatch, tmp_path, home):  # noqa: F811
    launcher = _no_pillow(monkeypatch)
    launcher.make_launcher(None, False, [tmp_path], python=sys.executable, platform="win32")
    assert (home.home() / "ENLENS.ico").read_bytes() == (launcher.ICONS / "ENLENS.ico").read_bytes()


# ---------------------------------------------------------------------------------------------
# icons made without a picture before 0.10.2
# ---------------------------------------------------------------------------------------------
def test_a_blank_mac_icon_is_repaired_and_nothing_else(monkeypatch, tmp_path):
    launcher = _no_pillow(monkeypatch)
    real = launcher.ICONS
    monkeypatch.setattr(launcher, "ICONS", tmp_path / "none")  # as before 0.10.2 without Pillow: no picture
    app = launcher.make_launcher(str(tmp_path / "data"), True, [tmp_path / "desk"], python=sys.executable, platform="darwin")[0]
    before = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert "CFBundleIconFile" not in before and not (app / "Contents" / "Resources" / "ENLENS.icns").exists()
    other = tmp_path / "desk" / "Other.app" / "Contents"  # somebody else's app is never touched
    other.mkdir(parents=True)
    (other / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.example.other"}))
    script = (app / "Contents" / "MacOS" / "ENLENS").read_text()

    monkeypatch.setattr(launcher, "ICONS", real)
    assert launcher.repair_icons([tmp_path / "desk", tmp_path / "missing"], platform="darwin") == [app]
    after = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert after == {**before, "CFBundleIconFile": "ENLENS"}
    assert (app / "Contents" / "Resources" / "ENLENS.icns").read_bytes() == (real / "ENLENS.icns").read_bytes()
    assert (app / "Contents" / "MacOS" / "ENLENS").read_text() == script  # what it starts is unchanged
    assert plistlib.loads((other / "Info.plist").read_bytes()) == {"CFBundleIdentifier": "com.example.other"}
    assert launcher.repair_icons([tmp_path / "desk"], platform="darwin") == []  # once is enough


def test_blank_windows_shortcuts_are_pointed_at_the_picture(monkeypatch, tmp_path, home):  # noqa: F811
    from enlens_claims.gui import launcher

    for d in ("desk", "start"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "ENLENS.lnk").write_bytes(b"lnk")
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    fixed = launcher.repair_icons([tmp_path / "desk", tmp_path / "start"], platform="win32", run=run)
    ico = home.home() / "ENLENS.ico"
    assert fixed == [tmp_path / "desk" / "ENLENS.lnk", tmp_path / "start" / "ENLENS.lnk"] and ico.is_file()
    script = calls[0][-1]
    assert calls[0][0] == "powershell" and script.count("IconLocation") == 2 and str(ico) in script
    assert launcher.repair_icons([tmp_path / "desk"], platform="win32", run=run) == [] and len(calls) == 1
    assert launcher.repair_icons(platform="linux") == []


# ---------------------------------------------------------------------------------------------
# an older copy still running
# ---------------------------------------------------------------------------------------------
def test_which_running_copy_is_older():
    from enlens_claims.gui import launcher

    assert launcher.is_older({"version": "0.9.1"}) and launcher.is_older({}) and launcher.is_older({"version": ""})
    assert not launcher.is_older({"version": __version__}) and not launcher.is_older({"version": "99.0.0"})


def test_stop_older_quits_only_when_nothing_runs(monkeypatch):
    from enlens_claims.gui import launcher

    page = b'<meta name="enlens-token" content="tok-1"><meta name="enlens-version" content="0.10.1">'
    seen = []

    def fetch_with(jobs):
        def fetch(method, path, token=None):
            seen.append((method, path, token))
            if path == "/":
                return page
            if path == "/api/jobs":
                return json.dumps({"jobs": jobs}).encode()
            return b'{"stopping": true}'
        return fetch

    monkeypatch.setattr(launcher, "running", lambda timeout=1.5: None)
    live = {"url": "http://127.0.0.1:9/", "version": "0.10.1"}
    assert launcher.stop_older(live, fetch=fetch_with([{"state": "done"}])) == "stopped"
    assert ("POST", "/api/quit", "tok-1") in seen
    seen.clear()
    assert launcher.stop_older(live, fetch=fetch_with([{"state": "running"}])) == "busy"
    assert not any(p == "/api/quit" for _, p, _ in seen)  # a running check is never stopped by the icon
    assert launcher.stop_older(live, fetch=lambda *a, **k: b"<html>no token</html>") == "failed"

    def offline(*a, **k):
        raise OSError("refused")

    assert launcher.stop_older(live, fetch=offline) == "failed"


def test_the_icon_replaces_an_older_running_copy(home, tmp_path):  # noqa: F811
    """Two real launches: the first copy is made to look older (as after `git pull`), the second double-click quits
    it and starts this version in its place."""
    from enlens_claims.gui import launcher

    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    env = {**os.environ, "ENLENS_HOME": str(home.home())}
    cmd = [sys.executable, "-m", "enlens_claims.gui.launch", "--launcher", "--headless", "--no-start-ollama",
           "--port", str(port)]
    procs = [subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]

    def wait_for(pid):
        for _ in range(150):
            live = launcher.running()
            if live and live["pid"] == pid:
                return live
            time.sleep(0.1)
        raise AssertionError("ENLENS did not start")

    try:
        live = wait_for(procs[0].pid)
        info = launcher.info_path()
        info.write_text(json.dumps({**json.loads(info.read_text()), "version": "0.10.1"}))  # it "is" the old one
        procs.append(subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True))
        assert procs[0].wait(timeout=30) == 0  # the old copy quit
        new = wait_for(procs[1].pid)
        assert new["version"] == __version__
        page = urllib.request.urlopen(new["url"], timeout=5).read().decode()
        token = page.split('name="enlens-token" content="')[1].split('"')[0]
        a = Api(new["url"].rstrip("/"), token)
        assert a("GET", "/api/state")[1]["version"] == __version__
        assert a("POST", "/api/quit", {})[1]["stopping"] is True
        assert procs[1].wait(timeout=15) == 0
        log = (home.home() / "logs" / "enlens.log").read_text()
        assert f"ENLENS 0.10.1 was still running: stopped it to start {__version__}." in log
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()


# ---------------------------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------------------------
def test_the_state_says_which_version_is_installed(api, monkeypatch):  # noqa: F811
    from enlens_claims.gui import server

    assert server._installed_version() == __version__
    assert api("GET", "/api/state")[1]["installed_version"] == __version__
    monkeypatch.setattr(server, "__version__", "0.10.1")  # this copy started before the update
    st = api("GET", "/api/state")[1]
    assert st["version"] == "0.10.1" and st["installed_version"] == __version__


def test_page_files_of_the_release():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="/static/v0102.css">' in html
    assert html.index('id="update-banner"') < html.index('id="quicklook-banner"') < html.index('id="view"')
    css = (STATIC / "v0102.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", (STATIC / "app.css").read_text(encoding="utf-8")))
    used = set(re.findall(r"var\((--[a-z0-9-]+)", css))
    assert used and used <= defined, used - defined
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "function renderUpdateBanner()" in app and "renderUpdateBanner(); });" in app
    assert "st.installed_version" in app and 'onclick: () => quitApp(' in app
    assert 'btn.addEventListener("click", () => quitApp());' in app
    settings = (STATIC / "views" / "settings.js").read_text(encoding="utf-8")
    assert "version-tag-stale" in settings and "installed_version" in settings
    server_py = (ROOT / "src" / "enlens_claims" / "gui" / "server.py").read_text(encoding="utf-8")
    serve = server_py[server_py.index("def serve("):]
    assert 'target=_repair_icons' in serve  # an icon without a picture is repaired when ENLENS starts
