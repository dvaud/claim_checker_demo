"""0.14.3: the local server's lifecycle, Claude Code set-up, updating, and the dev server.

- the Claude Code plugin follows the version: a plugin written by an older ENLENS is written again and Claude Code is
  told to take it (marketplace update, plugin update);
- Start Claude Code: one run per project even when pressed at once, each run in its own work folder;
- a run is recorded under the data folder: Quit and "Update and restart" stop it, and a restarted app still sees,
  can stop, and does not duplicate a run that kept working;
- an app started from disk serves the page code it started with (not the new files of an update);
- a git copy whose install step failed finishes it on the next update; git never waits for a password or for ever;
- the sign-in script and the Windows command file are read right with an accent in the path;
- the dev server never finds the real Claude Code.
Tests never touch a real Claude Code (the stand-in tests/fake_claude_cli.py), uv, git remotes or the network.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from enlens_claims import __version__, update

from test_app import Api, api, home  # noqa: F401  (fixtures)
from test_082_update_and_grid import Pip, _g, _release, copies, needs_git  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parent.parent
FAKE = str(Path(__file__).with_name("fake_claude_cli.py"))


@pytest.fixture
def fake_claude(monkeypatch):
    monkeypatch.setenv("ENLENS_CLAUDE", FAKE)
    from enlens_claims import claude_setup

    claude_setup._STATUS.update(at=0.0, value=None)
    claude_setup._RUNS.clear()
    yield claude_setup
    claude_setup.stop_all_runs()
    claude_setup._RUNS.clear()


def _wait(cond, timeout=10.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _fake_state(home):  # noqa: F811
    return json.loads((home.home() / "fake-claude.json").read_text())


# ---------------------------------------------------------------------------------------------
# 1. the plugin follows the version
# ---------------------------------------------------------------------------------------------
def test_an_older_plugin_is_written_again_and_claude_code_takes_it(home, fake_claude):  # noqa: F811
    fake_claude.install()
    assert fake_claude.stale() == "" and fake_claude.repair() == {"repaired": False}
    plug = fake_claude.plugin_folder()
    pj = plug / ".claude-plugin" / "plugin.json"
    data = json.loads(pj.read_text())
    data["version"] = "0.13.0"
    pj.write_text(json.dumps(data))
    (plug / "SKILL.md").write_text("an old skill text")
    assert "0.13.0" in fake_claude.stale() and __version__ in fake_claude.stale()
    r = fake_claude.repair()
    assert r["repaired"] is True and [s["ok"] for s in r["steps"]] == [True, True]
    assert (plug / "SKILL.md").read_text() != "an old skill text"
    assert json.loads(pj.read_text())["version"] == __version__
    assert [s["ok"] for s in r["refreshed"]] == [True, True]
    assert _fake_state(home)["updates"] == ["plugin marketplace update enlens", "plugin update enlens-run@enlens"]
    assert fake_claude.stale() == "" and fake_claude.repair()["repaired"] is False  # once is enough: idempotent


def test_the_install_line_run_again_brings_the_plugin_along(home, fake_claude, tmp_path, monkeypatch):  # noqa: F811
    from enlens_claims import installation

    monkeypatch.setattr(sys, "prefix", str(tmp_path / "prefix"))
    (tmp_path / "prefix").mkdir()
    fake_claude.install()
    pj = fake_claude.plugin_folder() / ".claude-plugin" / "plugin.json"
    pj.write_text(json.dumps({**json.loads(pj.read_text()), "version": "0.13.0"}))
    out = installation.post_install(by=None, icon=False)
    assert out["plugin"]["repaired"] is True and json.loads(pj.read_text())["version"] == __version__
    assert _fake_state(home)["updates"]


def test_a_plugin_whose_version_cannot_be_read_is_written_again(home, fake_claude):  # noqa: F811
    fake_claude.install()
    (fake_claude.plugin_folder() / ".claude-plugin" / "plugin.json").write_text("not json")
    assert "version" in fake_claude.stale()
    assert fake_claude.repair()["repaired"] is True and fake_claude.stale() == ""


# ---------------------------------------------------------------------------------------------
# 2. one run per project, each in its own folder
# ---------------------------------------------------------------------------------------------
def test_pressing_start_at_once_starts_one_run(home, fake_claude, monkeypatch):  # noqa: F811
    monkeypatch.setenv("FAKE_CLAUDE_DELAY", "30")
    home.create_project("Demo")
    started = []
    real = subprocess.Popen

    def counting(*a, **kw):
        p = real(*a, **kw)
        if a and "-p" in a[0] and "--allowedTools" in a[0]:  # a run (not `claude --version`, `ps`, …)
            started.append(p.pid)
        return p

    monkeypatch.setattr(subprocess, "Popen", counting)
    results = []
    threads = [threading.Thread(target=lambda: results.append(fake_claude.start_run("Demo"))) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert len(started) == 1 and len(results) == 3
    assert all(r["running"] for r in results) and len({r["started_at"] for r in results}) == 1
    assert fake_claude.stop_run("Demo")["running"] is False  # Stop reaches the one run there is
    assert _wait(lambda: not fake_claude._pid_runs_enlens(started[0]))


def test_three_posts_to_the_start_route_give_one_run(api, home, fake_claude, monkeypatch):  # noqa: F811
    monkeypatch.setenv("FAKE_CLAUDE_DELAY", "30")
    home.create_project("Demo")
    out = []
    threads = [threading.Thread(target=lambda: out.append(api("POST", "/api/projects/Demo/queue/claude-code", {})))
               for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert [s for s, _ in out] == [200, 200, 200]
    assert len({r["started_at"] for _, r in out}) == 1
    assert len(list((home.home() / "claude-runs").glob("*.run.json"))) == 1


def test_each_project_has_its_own_work_folder(home):  # noqa: F811
    from enlens_claims import claude_setup

    a = claude_setup.work_folder("Project A")
    (a / "note.txt").write_text("the first run's file")
    b = claude_setup.work_folder("Project B")
    assert a != b and (a / "note.txt").exists()  # starting a second run did not empty the first one's folder
    assert claude_setup.work_folder("a b") != claude_setup.work_folder("a_b")  # names that look alike stay apart
    assert not (claude_setup.work_folder("Project A") / "note.txt").exists()  # the same project: emptied, as before


# ---------------------------------------------------------------------------------------------
# 4. a run is recorded: quit stops it; a restarted app sees it
# ---------------------------------------------------------------------------------------------
def test_stop_all_runs_stops_every_run(home, fake_claude, monkeypatch):  # noqa: F811
    monkeypatch.setenv("FAKE_CLAUDE_DELAY", "30")
    home.create_project("One")
    home.create_project("Two")
    pids = []
    for name in ("One", "Two"):
        fake_claude.start_run(name)
        pids.append(fake_claude._read_record(name)["pid"])
    stopped = fake_claude.stop_all_runs()
    assert sorted(r["project"] for r in stopped) == ["One", "Two"] and all(r["started_at"] for r in stopped)
    assert _wait(lambda: not any(fake_claude._pid_runs_enlens(p) for p in pids))
    assert fake_claude.run_state("One")["running"] is False and fake_claude.stop_all_runs() == []


def test_quit_and_restart_stop_the_runs_first(home, fake_claude, monkeypatch):  # noqa: F811
    from enlens_claims.gui.server import make_server

    monkeypatch.setenv("FAKE_CLAUDE_DELAY", "30")
    home.create_project("Demo")
    srv, app = make_server("127.0.0.1", 0)
    quits, restarts = [], []
    app.stop, app.restart = (lambda: quits.append(1)), (lambda: restarts.append(1))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    a = Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token)
    try:
        for route, done in (("/api/quit", quits), ("/api/restart", restarts)):
            assert a("POST", "/api/projects/Demo/queue/claude-code", {})[1]["running"] is True
            pid = fake_claude._read_record("Demo")["pid"]
            assert a("POST", route, {})[0] == 200
            assert _wait(lambda: done)
            assert fake_claude.run_state("Demo")["running"] is False
            assert _wait(lambda: not fake_claude._pid_runs_enlens(pid))
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_restarted_app_sees_stops_and_does_not_duplicate_a_run(home, fake_claude, monkeypatch):  # noqa: F811
    monkeypatch.setenv("FAKE_CLAUDE_DELAY", "30")
    home.create_project("Demo")
    first = fake_claude.start_run("Demo")
    pid = fake_claude._read_record("Demo")["pid"]
    fake_claude._RUNS.clear()  # the app quit without stopping it (or crashed): the new app knows nothing in memory
    st = fake_claude.run_state("Demo")
    assert st["running"] is True and st["started_at"] == first["started_at"]
    again = fake_claude.start_run("Demo")  # Start does not launch a second one beside it
    assert again["running"] is True and fake_claude._read_record("Demo")["pid"] == pid
    assert fake_claude.stop_run("Demo")["running"] is False  # and Stop reaches it
    assert _wait(lambda: not fake_claude._pid_runs_enlens(pid))
    assert not fake_claude._record_path("Demo").exists()


def test_a_record_of_a_run_that_ended_or_a_reused_number_is_not_a_run(home, fake_claude):  # noqa: F811
    home.create_project("Demo")
    fake_claude._write_record("Demo", 2 ** 22 + 12345, "2026-01-01 00:00:00", time.time(), {})  # no such process
    assert fake_claude.run_state("Demo") == {"running": False} and not fake_claude._record_path("Demo").exists()
    fake_claude._write_record("Demo", os.getpid(), "2026-01-01 00:00:00", time.time(), {})  # this test: not a run
    assert fake_claude.run_state("Demo") == {"running": False}
    assert fake_claude.stop_run("Demo")["running"] is False  # and Stop never signals it


# ---------------------------------------------------------------------------------------------
# 5. the page code of a running app
# ---------------------------------------------------------------------------------------------
def _serve(app_srv):
    srv, app = app_srv
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}", srv, app


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.read().decode("utf-8")


def test_a_started_app_serves_the_page_code_it_started_with(home, tmp_path, monkeypatch):  # noqa: F811
    from enlens_claims.gui import server

    static = tmp_path / "static"
    (static / "js").mkdir(parents=True)
    (static / "index.html").write_text("<html>old page {{ENLENS_VERSION}}</html>")
    (static / "js" / "app.js").write_text("old script")
    monkeypatch.setattr(server, "STATIC", static)
    base, srv, app = _serve(server.make_server("127.0.0.1", 0))
    try:
        assert "old page" in _get(base + "/") and _get(base + "/static/js/app.js") == "old script"
        app.freeze_static()
        (static / "index.html").write_text("<html>NEW page</html>")  # the update lands on disk
        (static / "js" / "app.js").write_text("new script")
        (static / "js" / "extra.js").write_text("a file the old copy never had")
        assert "old page" in _get(base + "/") and _get(base + "/static/js/app.js") == "old script"
        with pytest.raises(urllib.error.HTTPError) as e:
            _get(base + "/static/js/extra.js")
        assert e.value.code == 404
        with pytest.raises(urllib.error.HTTPError) as e:
            _get(base + "/static/../../secret.txt")
        assert e.value.code in (400, 404)
        # an app that was not frozen (the tests, the dev server) reads the files from disk, so page code can be edited
        app.frozen_static = None
        assert "NEW page" in _get(base + "/") and _get(base + "/static/js/app.js") == "new script"
    finally:
        srv.shutdown()
        srv.server_close()


def test_serve_freezes_the_page_code_and_the_dev_server_does_not(home, monkeypatch):  # noqa: F811
    from enlens_claims.gui import server

    box = {}
    real = server.make_server

    def capture(*a, **kw):
        srv, app = real(*a, **kw)
        box["srv"], box["app"] = srv, app
        return srv, app

    monkeypatch.setattr(server, "make_server", capture)
    monkeypatch.setattr(server, "_repair_plugin", lambda: None)
    monkeypatch.setattr(server, "_repair_icons", lambda: None)
    t = threading.Thread(target=lambda: server.serve("127.0.0.1", 0, open_browser=False), daemon=True)
    t.start()
    assert _wait(lambda: "app" in box and box["app"].frozen_static is not None)
    assert "index.html" in box["app"].frozen_static
    box["app"].stop()
    t.join(10)
    assert "make_server(" in (ROOT / "tools" / "dev_server.py").read_text()
    assert "freeze_static" not in (ROOT / "tools" / "dev_server.py").read_text()
    assert real("127.0.0.1", 0)[1].frozen_static is None


# ---------------------------------------------------------------------------------------------
# 3. a failed install step is finished by the next update
# ---------------------------------------------------------------------------------------------
class FailingPip(Pip):
    def __init__(self, fail_times):
        super().__init__()
        self.fail_times = fail_times

    def __call__(self, cmd, cwd):
        if cmd[1:3] == ["-m", "pip"]:
            self.calls.append(cmd)
            if len(self.calls) <= self.fail_times:
                return subprocess.CompletedProcess(cmd, 1, "", "no network")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return update._run(cmd, cwd)


@needs_git
def test_a_failed_reinstall_is_run_again_by_the_next_update(copies):  # noqa: F811
    dev, user = copies
    _release(dev, "0.8.2", deps='"pydantic>=2.5", "numpy>=1.24"')
    _g(dev, "push", "-q")
    pip = FailingPip(fail_times=1)
    with pytest.raises(update.UpdateError, match="requirements failed"):
        update.update(root=user, run=pip, python="/py")
    assert (user / ".git" / "enlens-reinstall-pending").exists()
    assert update.version_in(user) == "0.8.2"  # merged already: nothing is waiting any more
    # a check says there is still something to do
    chk = update.update(check_only=True, root=user, run=pip, python="/py")
    assert chk["waiting"] and "not installed yet" in chk["message"]
    out = update.update(root=user, run=pip, python="/py")  # not "up to date": it reaches pip
    assert out["updated"] is True and out["reinstalled"] is True and len(pip.calls) == 2
    assert not (user / ".git" / "enlens-reinstall-pending").exists()
    assert "requirements" in out["message"]
    assert update.update(root=user, run=pip, python="/py")["updated"] is False and len(pip.calls) == 2


@needs_git
def test_a_code_only_update_leaves_no_marker(copies):
    dev, user = copies
    (dev / "src" / "enlens_claims" / "__init__.py").write_text('__version__ = "0.8.2"\n', encoding="utf-8")
    _g(dev, "commit", "-qam", "code only")
    _g(dev, "push", "-q")
    pip = Pip()
    out = update.update(root=user, run=pip)
    assert out["updated"] is True and out["reinstalled"] is False and pip.calls == []
    assert not (user / ".git" / "enlens-reinstall-pending").exists()


# ---------------------------------------------------------------------------------------------
# 8. git never waits for a password or for ever
# ---------------------------------------------------------------------------------------------
def test_git_runs_without_prompts_and_with_a_timeout(monkeypatch, tmp_path):
    seen = []

    def fake_run(cmd, **kw):
        seen.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    update._run(["git", "fetch"], tmp_path)
    cmd, kw = seen[-1]
    assert kw["stdin"] == subprocess.DEVNULL and kw["timeout"] == update.GIT_TIMEOUT
    assert kw["env"]["GIT_TERMINAL_PROMPT"] == "0" and "BatchMode=yes" in kw["env"]["GIT_SSH_COMMAND"]
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i mykey")
    update._run(["git", "fetch"], tmp_path)
    assert seen[-1][1]["env"]["GIT_SSH_COMMAND"] == "ssh -i mykey"  # the person's own choice is kept
    update._run(["python", "-m", "pip"], tmp_path)  # pip may take as long as it takes
    assert seen[-1][1]["timeout"] is None and seen[-1][1]["stdin"] == subprocess.DEVNULL

    def hang(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr(subprocess, "run", hang)
    r = update._run(["git", "fetch", "--quiet"], tmp_path)
    assert r.returncode == 124 and "took longer" in r.stderr
    with pytest.raises(update.UpdateError, match="took longer"):
        update._git(update._run, tmp_path, "fetch", "--quiet")


def test_no_look_for_updates_while_one_runs(api, home, monkeypatch):  # noqa: F811
    from enlens_claims.gui import server  # noqa: F401

    calls = []
    monkeypatch.setattr(update, "update", lambda **kw: calls.append(kw) or {"updated": False, "version": __version__})
    # the api fixture's app: take the update lock as POST /api/update does while it works
    from enlens_claims.gui.server import make_server

    srv, app = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    a = Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token)
    try:
        app.updating.acquire()
        st, r = a("GET", "/api/update?fresh=1")
        assert st == 200 and r["updating"] is True and calls == []  # no git fetch beside the update's git commands
        app.updating.release()
        st, r = a("GET", "/api/update?fresh=1")
        assert st == 200 and "updating" not in r and len(calls) == 1
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------------------------------------
# 6, 7. an accent in a Windows path
# ---------------------------------------------------------------------------------------------
def test_the_sign_in_script_has_a_byte_order_mark_for_windows_powershell(home, monkeypatch):  # noqa: F811
    from enlens_claims import claude_setup

    class AsWindows:  # this module's `os`, answering "nt"
        name = "nt"

        def __getattr__(self, attr):
            return getattr(os, attr)

    monkeypatch.setattr(claude_setup, "os", AsWindows())
    exe = r"C:\Users\Kovács\.local\bin\claude.exe"
    p = claude_setup._sign_in_script(exe)
    raw = p.read_bytes()
    assert p.name == "sign-in.ps1" and raw.startswith(b"\xef\xbb\xbf")
    assert exe in raw.decode("utf-8-sig") and "Kovács".encode("utf-8") in raw


def test_the_windows_command_file_switches_to_utf8(tmp_path, monkeypatch, home):  # noqa: F811
    from enlens_claims.gui import launcher

    def no_powershell(*a, **kw):
        raise OSError("no PowerShell")

    monkeypatch.setattr(subprocess, "run", no_powershell)
    monkeypatch.setattr(launcher, "_com_shortcut", lambda *a: False)  # 0.15.2: nor the Shell's own interface
    python = str(tmp_path / "Kovács" / "Scripts" / "python.exe")
    cmd = launcher._windows_shortcut(tmp_path, python, ["-m", "enlens_claims.gui.launch", "--launcher"])
    raw = cmd.read_bytes()
    lines = raw.split(b"\r\n")
    assert cmd.suffix == ".cmd" and lines[0] == b"@echo off" and lines[1] == b"chcp 65001 >nul"
    assert "Kovács".encode("utf-8") in raw  # the path is UTF-8, which cmd.exe now reads as such


# ---------------------------------------------------------------------------------------------
# 9. the dev server never finds the real Claude Code
# ---------------------------------------------------------------------------------------------
def _dev_server(tmp_path, *flags):
    """Start tools/dev_server.py with a program named `claude` on the PATH that records being run (the stand-in of
    "the developer's real one"); returns (process, base url, token, marker file)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    marker = tmp_path / "real-claude-was-run"
    claude = bin_dir / "claude"
    claude.write_text(f"#!/bin/sh\necho run >> '{marker}'\necho 'real claude'\n")
    claude.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "HOME": str(tmp_path / "home-dir"),
           "PYTHONPATH": str(ROOT / "src"), "PYTHONUNBUFFERED": "1"}
    env.pop("ENLENS_CLAUDE", None)
    (tmp_path / "home-dir").mkdir(exist_ok=True)
    proc = subprocess.Popen([sys.executable, str(ROOT / "tools" / "dev_server.py"), "--port", "0", "--empty",
                             "--home", str(tmp_path / "dev-home"), *flags], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env, cwd=str(tmp_path))
    base = token = ""
    t0 = time.time()
    while time.time() - t0 < 60 and not (base and token):
        line = proc.stdout.readline()
        if not line:
            break
        if line.startswith("app: "):
            base = line.split("app: ", 1)[1].strip().rstrip("/")
        if line.startswith("token: "):
            token = line.split("token: ", 1)[1].strip()
    assert base and token, "the dev server did not start"
    return proc, base, token, marker


@pytest.mark.skipif(os.name == "nt", reason="the stand-in `claude` is a /bin/sh script")
@pytest.mark.parametrize("flags", [(), ("--claude-code",), ("--claude-code-paused",)])
def test_no_dev_server_mode_finds_the_real_claude(tmp_path, flags):
    proc, base, token, marker = _dev_server(tmp_path, *flags)
    try:
        a = Api(base, token)
        st, r = a("GET", "/api/claude-setup?refresh=1")
        assert st == 200
        found = r["status"]
        if flags:
            assert found["found"] and found["path"].endswith("fake_claude_cli.py")  # the stand-in, not `claude`
        else:
            assert found["found"] is False
        assert not marker.exists()  # the program named claude on the PATH was never run
    finally:
        proc.terminate()
        proc.wait(15)
