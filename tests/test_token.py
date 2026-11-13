"""0.17.2: the access token leaves the page (BRIEF §4.1, P3).

Before, `GET /` put the token into the page for any client on this computer that named 127.0.0.1 in its Host header,
so another account on a shared computer got the whole API. Now the page never carries it; the app opens its link with
the token after `#`, keeps it in a file only this account can read (for the icon's "open again", `enlens post-install
--open` and quitting an older copy), and a restart after an update carries it over so the open tabs reach the new copy.
The page keeps it per tab (sessionStorage), asks the app's other tabs for it, and otherwise says how to open ENLENS.
"""
from __future__ import annotations

import json
import os
import re
import stat
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from _fakedom import NODE, run
from test_app import Api, home  # noqa: F401  (fixtures)

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"
needs_node = pytest.mark.skipif(not NODE, reason="node is not installed")


def _wait(pred, timeout=60.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return True
        time.sleep(0.05)
    return False


def _get(url, host=None):
    req = urllib.request.Request(url, headers={"Host": host} if host else {})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read()


# ---------------------------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("listen", ["127.0.0.1", "0.0.0.0"])
def test_the_page_never_carries_the_token_whatever_the_host(home, listen):  # noqa: F811
    from enlens_claims.gui.server import make_server

    srv, app = make_server(listen, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        for host in (f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"):
            for path in ("/", "/index.html", "/overview"):
                page = _get(f"http://127.0.0.1:{port}{path}", host)
                assert b'name="enlens-version"' in page
                assert app.token.encode() not in page and b"{{ENLENS_" not in page, (listen, host, path)
                assert f'name="enlens-run" content="{app.run_id}"'.encode() in page
        # the Host check stays: another name is refused before anything is served
        with pytest.raises(urllib.error.HTTPError) as e:
            _get(f"http://127.0.0.1:{port}/", "evil.example")
        assert e.value.code == 403
        # and the API still takes the token, in the header (and as ?token= for the downloads that are plain links)
        assert Api(f"http://127.0.0.1:{port}", app.token)("GET", "/api/jobs")[0] == 200
        assert Api(f"http://127.0.0.1:{port}", "wrong-token-wrong-token")("GET", "/api/jobs")[0] == 401
    finally:
        srv.shutdown()
        srv.server_close()


def test_each_run_has_its_own_token_and_run_id(home):  # noqa: F811
    from enlens_claims.gui.server import App

    a, b = App(), App()
    assert a.token != b.token and a.run_id != b.run_id
    assert len(a.token) >= 32 and re.fullmatch(r"[A-Za-z0-9_-]+", a.token)


def test_the_page_files_hold_no_token():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "enlens-token" not in html and "{{ENLENS_TOKEN}}" not in html
    assert '<meta name="enlens-run" content="{{ENLENS_RUN}}">' in html
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'meta("enlens-token")' not in app and "enlens-token" not in app
    # the key first; without it, the page that says how to open ENLENS
    assert "if (!(await ensureToken())) { renderNoKey(keyWasStale()); return; }" in app
    assert "if (e.status === 401) { renderNoKey(true); return; }" in app
    assert 'const oldRun = meta("enlens-run");' in app  # the restart's new copy is known by its run


# ---------------------------------------------------------------------------------------------
# starting: the link, the token file
# ---------------------------------------------------------------------------------------------
def _target(url: str) -> str:
    """What the browser was sent to: on Linux `launcher.browse` hands it a private file that sends it on to the link
    (test_on_linux_the_browser_gets_a_private_file_not_the_token); that link is read from the file."""
    if url.startswith("file://"):
        from urllib.parse import unquote, urlparse

        page = Path(unquote(urlparse(url).path)).read_text(encoding="utf-8")
        return json.loads(re.search(r"location\.replace\((\"[^\"]*\")\)", page).group(1))
    return url


def _serve_once(monkeypatch, launcher_mode=False, env_token=None, port=0):
    """Run server.serve() in a thread on a free port, as the icon or the terminal would. Returns what it opened in the
    browser, the token file's text and mode while it ran, the app, and whether the file was gone after it stopped."""
    import webbrowser

    from enlens_claims.gui import launcher, server

    opened, made = [], []
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: opened.append(_target(url)) or True)
    monkeypatch.setattr(server, "_repair_plugin", lambda: None)
    monkeypatch.setattr(server, "_repair_icons", lambda: None)
    real = server.make_server

    def capture(*a, **k):
        srv, app = real(*a, **k)
        made.append(app)
        return srv, app

    monkeypatch.setattr(server, "make_server", capture)
    if env_token is not None:
        monkeypatch.setenv(server.RESTART_TOKEN, env_token)
    if port:  # a port that cannot be had: the app takes the next one (the real one is port 0, any free port)
        monkeypatch.setattr(server, "make_server", lambda h, p, app=None: capture(h, 0 if p >= port else p, app))
    t = threading.Thread(target=server.serve, kwargs={"host": "127.0.0.1", "port": port, "open_browser": True,
                                                      "launcher": launcher_mode}, daemon=True)
    t.start()
    assert _wait(lambda: opened and made), "the app did not open its link"
    app = made[-1]
    path = launcher.token_path(app.port)
    text, mode = path.read_text(encoding="utf-8"), stat.S_IMODE(path.stat().st_mode)
    app.stop()
    t.join(30)
    assert not t.is_alive()
    return opened, json.loads(text), mode, app, not path.exists()


def test_the_app_opens_its_link_with_the_token_and_keeps_it_in_a_private_file(home, monkeypatch, capsys):  # noqa: F811
    opened, saved, mode, app, gone = _serve_once(monkeypatch)
    assert opened == [f"http://127.0.0.1:{app.port}/#token={app.token}"]
    assert saved["token"] == app.token and saved["port"] == app.port and saved["pid"] == os.getpid()
    if os.name != "nt":  # Windows has no mode bits: the data folder is in the person's own profile there
        assert mode == 0o600
    assert gone  # the file goes when the app stops
    # the terminal shows the link (the person who started it is the account that may use it)
    assert f"#token={app.token}" in capsys.readouterr().out


def test_the_icon_does_not_write_the_token_into_its_log(home, monkeypatch, capsys):  # noqa: F811
    opened, saved, _mode, app, _gone = _serve_once(monkeypatch, launcher_mode=True)
    assert opened == [f"http://127.0.0.1:{app.port}/#token={app.token}"]
    out = capsys.readouterr().out  # started from the icon, this goes to logs/enlens.log
    assert app.token not in out and f"http://127.0.0.1:{app.port}/" in out


def test_every_start_has_a_fresh_token(home, monkeypatch):  # noqa: F811
    first = _serve_once(monkeypatch)
    second = _serve_once(monkeypatch)
    assert first[1]["token"] != second[1]["token"]


def test_a_restart_carries_the_token_over_once(home, monkeypatch):  # noqa: F811
    from enlens_claims.gui import server

    carried = "C" * 40
    opened, saved, _mode, app, _gone = _serve_once(monkeypatch, env_token=carried)
    assert app.token == carried and saved["token"] == carried and opened[0].endswith(f"#token={carried}")
    assert server.RESTART_TOKEN not in os.environ  # the programs it starts do not inherit it
    # on another port than the one it restarts on, it takes a new one: the tabs that hold it are on the old address
    opened, saved, _mode, app, _gone = _serve_once(monkeypatch, env_token=carried, port=1)
    assert app.port != 1 and app.token != carried and saved["token"] == app.token
    monkeypatch.setenv(server.RESTART_TOKEN, "short")  # anything that is not a token is ignored
    assert server.carried_token() is None and server.RESTART_TOKEN not in os.environ


def test_restart_hands_the_token_to_the_new_copy(home, monkeypatch):  # noqa: F811
    from enlens_claims import ingest
    from enlens_claims.gui import server

    seen = {}
    monkeypatch.setattr(ingest, "end_reading_processes", lambda: None)
    monkeypatch.delenv(server.RESTART_TOKEN, raising=False)
    if os.name == "nt":
        import subprocess

        monkeypatch.setattr(subprocess, "Popen", lambda cmd, **k: seen.update(cmd=cmd, token=os.environ.get(server.RESTART_TOKEN)))
    else:
        monkeypatch.setattr(os, "execv", lambda exe, cmd: seen.update(cmd=cmd, token=os.environ.get(server.RESTART_TOKEN)))
    try:
        server._restart(["python", "-m", "enlens_claims.gui.launch"], "T" * 40)
    finally:
        os.environ.pop(server.RESTART_TOKEN, None)  # (the real one becomes the new copy, which takes it out)
    assert seen["token"] == "T" * 40


def test_update_on_windows_hands_the_token_to_the_hand_over_and_nothing_else(monkeypatch, home):  # noqa: F811
    """The Update button passes the token to update(), which passes it to handover.py in that program's environment
    only: never in the job file, and never in the app's own environment (a job's programs would inherit it)."""
    from enlens_claims import handover, update
    from enlens_claims.gui import server
    from test_setup_and_moving import _releases

    # (each step stubs only what it needs and puts the real function back; never monkeypatch.undo(), which would also
    # undo the temporary data folder conftest.py sets)
    real_update, real_release = update.update, update.update_release
    # the button: the app's token goes with the restart command
    seen = {}
    monkeypatch.setattr(server, "handover_command", lambda app: ["pythonw.exe", "-m", "enlens_claims.gui.launch"])
    monkeypatch.setattr(update, "update", lambda **k: seen.update(k) or {"updated": False})
    srv, app = server.make_server("127.0.0.1", 0)
    app.restart = lambda: None  # started as serve() starts it: it can restart itself
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token)("POST", "/api/update", {})[1]
    finally:
        srv.shutdown()
        srv.server_close()
    assert r["updated"] is False and seen["token"] == app.token and seen["restart"]
    monkeypatch.setattr(update, "update", real_update)
    # update() hands it on to update_release()
    from enlens_claims import installation

    got = {}
    monkeypatch.setattr(update, "source_root", lambda: None)
    monkeypatch.setattr(installation, "kind", lambda: "script")
    monkeypatch.setattr(update, "update_release", lambda **k: got.update(k) or {"updated": False})
    update.update(restart=["x"], token="H" * 40)
    assert got["token"] == "H" * 40
    monkeypatch.setattr(update, "update_release", real_release)
    # update_release() starts handover.py with it in that program's environment
    assert str(home.home()) != str(Path.home() / "enlens")  # still the test's own data folder
    started = []
    monkeypatch.setattr(update, "find_uv", lambda: "C:/uv/uv.exe")
    monkeypatch.setattr(handover, "_start", lambda args, folder, env=None: started.append((args, env)) or 1)
    r = update.update_release(fetch=_releases(), run=lambda *a: pytest.fail("installs nothing itself"), windows=True,
                              restart=["pythonw.exe", "-m", "enlens_claims.gui.launch"], token="H" * 40)
    assert r["handover"] and started[0][1][handover.RESTART_TOKEN] == "H" * 40
    job = Path(started[0][0][-1]).read_text(encoding="utf-8")
    assert "H" * 40 not in job and handover.RESTART_TOKEN not in os.environ


def test_the_windows_hand_over_gives_the_token_to_the_new_copy_only(monkeypatch, tmp_path):
    """handover.py gives the token it inherited to the copy it starts, not to the installer."""
    from enlens_claims import handover
    from enlens_claims.gui import server

    runs, starts = [], []
    monkeypatch.setattr(handover, "_wait_gone", lambda pids, s: True)
    monkeypatch.setattr(handover, "_wait_free", lambda job: True)
    monkeypatch.setattr(handover, "_run", lambda job, args, env=None: runs.append(dict(env or os.environ)) or (0, "ok"))
    monkeypatch.setattr(handover, "_start", lambda args, folder, env=None: starts.append(env) or 4242)
    monkeypatch.setattr(handover, "_came_back", lambda job, before, s: True)
    monkeypatch.setenv(handover.RESTART_TOKEN, "H" * 40)
    job = {"from": "0.17.1", "version": "0.17.2", "folder": str(tmp_path), "pids": [1], "install": ["uv"],
           "post": ["post"], "start": ["python", "-m", "enlens_claims.gui.launch"], "info": str(tmp_path / "app.json"),
           "result": str(tmp_path / "result.json"), "log": str(tmp_path / "update.log"), "settle": 0}
    assert handover.run(job)["restarted"] is True
    assert all(handover.RESTART_TOKEN not in env for env in runs) and len(runs) == 2
    assert starts[0][handover.RESTART_TOKEN] == "H" * 40
    assert handover.RESTART_TOKEN not in os.environ
    assert handover.RESTART_TOKEN == server.RESTART_TOKEN


# ---------------------------------------------------------------------------------------------
# open again, quit an older copy, the installer's --open
# ---------------------------------------------------------------------------------------------
def test_open_again_opens_the_link_with_the_token(home, monkeypatch):  # noqa: F811
    import webbrowser

    from enlens_claims import installation
    from enlens_claims.gui import launch, launcher

    url = "http://127.0.0.1:8799/"
    launcher.write_token(url, 8799, "K" * 40)
    live = {"url": url, "port": 8799, "pid": 1, "version": installation.__version__}
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda u, *a, **k: opened.append(_target(u)) or True)
    monkeypatch.setattr(launcher, "running", lambda timeout=1.5: live)
    assert launch.main(["--launcher", "--no-start-ollama"]) == 0  # a second double-click on the icon
    assert installation._open(live, None, False) is True           # enlens post-install --open
    assert opened == [f"{url}#token={'K' * 40}"] * 2
    # no file (or another app's port): the bare address, which says how to open ENLENS
    assert launcher.open_link({"url": "http://127.0.0.1:8798/", "port": 8798}) == "http://127.0.0.1:8798/"


def test_quitting_an_older_copy_reads_the_token_file(home, monkeypatch):  # noqa: F811
    from enlens_claims.gui import launcher

    launcher.write_token("http://127.0.0.1:9/", 9, "F" * 40)
    seen = []

    def fetch(method, path, token=None):
        seen.append((method, path, token))
        return json.dumps({"jobs": []}).encode() if path == "/api/jobs" else b'{"stopping": true}'

    monkeypatch.setattr(launcher, "running", lambda timeout=1.5: None)
    assert launcher.stop_older({"url": "http://127.0.0.1:9/", "port": 9, "version": "0.17.0"}, fetch=fetch) == "stopped"
    assert ("GET", "/", None) not in seen  # the page is not asked: it has no token
    assert ("POST", "/api/quit", "F" * 40) in seen


def test_quitting_an_older_copy_falls_back_to_its_page_when_the_file_is_refused(home, monkeypatch):  # noqa: F811
    import io
    from urllib.error import HTTPError

    from enlens_claims.gui import launcher

    launcher.write_token("http://127.0.0.1:9/", 9, "S" * 40)  # left behind: not the running copy's token
    seen = []

    def fetch(method, path, token=None):
        seen.append((method, path, token))
        if path == "/":
            return b'<meta name="enlens-token" content="page-token-page-token">'
        if token != "page-token-page-token":
            raise HTTPError("http://127.0.0.1:9" + path, 401, "Unauthorized", {}, io.BytesIO(b"{}"))
        return json.dumps({"jobs": []}).encode() if path == "/api/jobs" else b'{"stopping": true}'

    monkeypatch.setattr(launcher, "running", lambda timeout=1.5: None)
    assert launcher.stop_older({"url": "http://127.0.0.1:9/", "port": 9, "version": "0.17.0"}, fetch=fetch) == "stopped"
    assert ("POST", "/api/quit", "page-token-page-token") in seen


def test_on_windows_the_token_file_stays_in_the_persons_profile(tmp_path):
    from enlens_claims.gui import launcher

    local = r"C:\Users\Dávid\AppData\Local"
    inside = tmp_path / "Dávid" / "enlens"
    assert launcher.token_dir(tmp_path, windows=False) == tmp_path
    assert launcher.token_dir(tmp_path, windows=True, profile=str(tmp_path.parent), local_appdata=local) == tmp_path
    assert launcher.token_dir(tmp_path, windows=True, profile=str(tmp_path / "elsewhere"),
                              local_appdata=str(tmp_path / "local")) == tmp_path / "local" / "ENLENS"
    assert launcher.token_dir(inside, windows=True, profile=str(tmp_path / "x"), local_appdata="") == inside


def test_on_linux_the_browser_gets_a_private_file_not_the_token(home, monkeypatch):  # noqa: F811
    import sys
    import webbrowser

    from enlens_claims.gui import launcher

    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda u, *a, **k: opened.append(u) or True)
    link = "http://127.0.0.1:8797/#token=" + "L" * 40
    launcher.browse(link)
    if os.name == "posix" and sys.platform != "darwin":
        assert opened[0].startswith("file://") and "L" * 40 not in opened[0]  # nothing on a command line
        page = launcher.token_path(8797).with_name("open-8797.html")
        assert "L" * 40 in page.read_text(encoding="utf-8") and stat.S_IMODE(page.stat().st_mode) == 0o600
    else:
        assert opened == [link]
    launcher.browse("http://127.0.0.1:8797/")  # no token: the address itself
    assert opened[-1] == "http://127.0.0.1:8797/"


def test_the_token_file_is_written_whole_and_cleared_only_by_its_app(home):  # noqa: F811
    from enlens_claims.gui import launcher

    p = launcher.write_token("http://127.0.0.1:8790/", 8790, "A" * 40)
    assert launcher.read_token(8790) == "A" * 40 and launcher.read_token("8790") == "A" * 40
    assert not [f for f in p.parent.iterdir() if f.name.endswith(".part")]
    p.write_text(json.dumps({"token": "B" * 40, "pid": os.getpid() + 1}), encoding="utf-8")  # another app's now
    launcher.clear_token(8790)
    assert p.exists() and launcher.read_token(8790) == "B" * 40
    p.write_text('{"token": "<script>"}', encoding="utf-8")
    assert launcher.read_token(8790) is None
    assert launcher.read_token(8791) is None


# ---------------------------------------------------------------------------------------------
# the page's side (Node runs lib.js with the stand-in document of tests/_fakedom.py)
# ---------------------------------------------------------------------------------------------
@needs_node
def test_the_tab_keeps_the_token_from_its_link_and_takes_it_out_of_the_address(tmp_path):
    out = run("""
const kept = {}; const replaced = [];
globalThis.location = { hash: "#token=" + "a".repeat(32), pathname: "/", origin: "http://127.0.0.1:8765" };
globalThis.sessionStorage = { getItem: (k) => kept[k] || null, setItem: (k, v) => { kept[k] = v; }, removeItem() {} };
globalThis.history = { replaceState: (_s, _t, url) => replaced.push(url) };
const lib = await import(LIB);
console.log(JSON.stringify({ token: lib.TOKEN, kept, replaced, link: lib.myLink() }));
""", tmp_path)
    assert out["token"] == "a" * 32 and out["kept"] == {"enlens-token": "a" * 32}
    assert out["replaced"] == ["/#/"]  # the address bar no longer shows it
    assert out["link"] == "http://127.0.0.1:8765/#token=" + "a" * 32


@needs_node
def test_a_tab_without_the_token_asks_the_apps_other_tabs(tmp_path):
    """A new tab (or a bookmark) has no token: it asks this browser's other ENLENS tabs and takes the first answer
    the app accepts (a tab left open from before a restart answers with an old one)."""
    out = run("""
const kept = {};
globalThis.location = { hash: "", pathname: "/", origin: "http://127.0.0.1:8765" };
globalThis.sessionStorage = { getItem: (k) => kept[k] || null, setItem: (k, v) => { kept[k] = v; }, removeItem() {} };
const OLD = "o".repeat(32), GOOD = "g".repeat(32);
const asked = [];
globalThis.BroadcastChannel = class {
  constructor(name) { this.name = name; }
  postMessage(m) { if (m.ask) { asked.push(this.name); setTimeout(() => { this.onmessage({ data: { token: OLD } }); this.onmessage({ data: { token: GOOD } }); this.onmessage({ data: { token: "<bad>" } }); }, 5); } }
  close() {}
};
const tried = [];
globalThis.fetch = async (url, opts) => { tried.push(opts.headers["X-Enlens-Token"]); return { ok: opts.headers["X-Enlens-Token"] === GOOD }; };
const lib = await import(LIB);
const before = lib.TOKEN;
const got = await lib.ensureToken();
console.log(JSON.stringify({ before, got, now: lib.TOKEN, asked, tried, kept }));
""", tmp_path)
    assert out["before"] == "" and out["got"] == "g" * 32 and out["now"] == "g" * 32
    assert out["asked"] == ["enlens-token"] and out["tried"] == ["o" * 32, "g" * 32]
    assert out["kept"] == {"enlens-token": "g" * 32}


@needs_node
def test_a_tab_with_an_old_key_drops_it_and_asks_the_other_tabs(tmp_path):
    out = run("""
const kept = { "enlens-token": "o".repeat(32) };
globalThis.location = { hash: "", pathname: "/", origin: "http://127.0.0.1:8765" };
globalThis.sessionStorage = { getItem: (k) => kept[k] || null, setItem: (k, v) => { kept[k] = v; }, removeItem: (k) => { delete kept[k]; } };
const GOOD = "g".repeat(32);
let answer = true;
globalThis.BroadcastChannel = class { postMessage(m) { if (m.ask && answer) setTimeout(() => this.onmessage({ data: { token: GOOD } }), 5); } close() {} };
globalThis.fetch = async (url, opts) => ({ ok: opts.headers["X-Enlens-Token"] === GOOD, status: opts.headers["X-Enlens-Token"] === GOOD ? 200 : 401 });
const lib = await import(LIB);
const got = await lib.ensureToken();
console.log(JSON.stringify({ got, stale: lib.keyWasStale(), kept }));
""", tmp_path)
    assert out == {"got": "g" * 32, "stale": False, "kept": {"enlens-token": "g" * 32}}


@needs_node
def test_an_old_key_with_no_other_tab_says_enlens_started_again(tmp_path):
    out = run("""
const kept = { "enlens-token": "o".repeat(32) };
globalThis.location = { hash: "", pathname: "/", origin: "http://127.0.0.1:8765" };
globalThis.sessionStorage = { getItem: (k) => kept[k] || null, setItem: (k, v) => { kept[k] = v; }, removeItem: (k) => { delete kept[k]; } };
globalThis.BroadcastChannel = class { postMessage() {} close() {} };
globalThis.fetch = async () => ({ ok: false, status: 401 });
const lib = await import(LIB);
console.log(JSON.stringify({ got: await lib.ensureToken(), stale: lib.keyWasStale(), kept }));
""", tmp_path)
    assert out == {"got": "", "stale": True, "kept": {}}


@needs_node
def test_a_kept_key_is_not_dropped_when_the_app_does_not_answer(tmp_path):
    out = run("""
globalThis.location = { hash: "", pathname: "/", origin: "http://127.0.0.1:8765" };
globalThis.sessionStorage = { getItem: () => "k".repeat(32), setItem() {}, removeItem() {} };
globalThis.BroadcastChannel = class { postMessage() {} close() {} };
globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
const lib = await import(LIB);
console.log(JSON.stringify({ got: await lib.ensureToken(), stale: lib.keyWasStale() }));
""", tmp_path)
    assert out == {"got": "k" * 32, "stale": False}  # the page then says the app is not answering


@needs_node
def test_a_tab_with_the_key_answers_the_others(tmp_path):
    out = run("""
globalThis.location = { hash: "#token=" + "a".repeat(32), pathname: "/", origin: "http://127.0.0.1:8765" };
const posted = []; const chans = [];
globalThis.BroadcastChannel = class { constructor(n) { this.name = n; chans.push(this); } postMessage(m) { posted.push(m); } close() {} };
const lib = await import(LIB);
await lib.ensureToken();
chans[0].onmessage({ data: { ask: true } });
chans[0].onmessage({ data: { token: "x".repeat(32) } });   // another tab's answer: not a question
console.log(JSON.stringify({ name: chans[0].name, posted }));
""", tmp_path)
    assert out == {"name": "enlens-token", "posted": [{"token": "a" * 32}]}


@needs_node
def test_with_no_other_tab_the_page_has_no_token_and_a_401_says_open_from_the_icon(tmp_path):
    out = run("""
globalThis.location = { hash: "", pathname: "/", origin: "http://127.0.0.1:8765" };
globalThis.BroadcastChannel = class { postMessage() {} close() {} };
globalThis.fetch = async () => ({ ok: false, status: 401, text: async () => JSON.stringify({ error: "Missing or wrong token." }) });
const lib = await import(LIB);
const got = await lib.ensureToken();
let msg = "";
try { await lib.api("GET", "/api/state"); } catch (e) { msg = e.message; }
console.log(JSON.stringify({ got, msg }));
""", tmp_path)
    assert out["got"] == ""
    assert "Open ENLENS from its icon (or run enlens-gui)." in out["msg"]
