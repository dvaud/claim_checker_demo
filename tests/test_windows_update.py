"""0.15.4: *Update* installs the new version on Windows too, as on macOS (the hand-over, handover.py).

Windows does not let a running program's files be replaced, so the app said to quit it and run the install line by
hand. Now the app downloads and checks the new version, hands the install to handover.py (run with the Python uv
installed, outside ENLENS's own folder) and quits; the script installs it once the app has gone and starts the app
again, which the open page follows. Here the script runs for real with stand-ins for the app, uv and `post-install`
(the release's Windows machine runs it with the real ones): it waits for the app to quit, tries again while a file is
held, starts the app whether or not the install worked, and says what happened, which the app shows once.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from test_no_console_windows import AsWindows
from test_setup_and_moving import NEXT, _releases
from test_update_button import served  # noqa: F401  (fixture)
from test_app import home  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parent.parent
HANDOVER = ROOT / "src" / "enlens_claims" / "handover.py"

# a stand-in uv: records its call; fails as Windows does while a file is held, `FAIL` times (or always: -1)
FAKE_UV = r'''
import json, os, sys
from pathlib import Path
state = Path(sys.argv[1])
s = json.loads(state.read_text()) if state.exists() else {"calls": 0}
s["calls"] += 1
s.setdefault("app_gone", []).append(not os.path.exists(os.environ["APP_ALIVE"]))
state.write_text(json.dumps(s))
fail = int(os.environ.get("FAIL", "0"))
if fail < 0 or s["calls"] <= fail:
    print("error: failed to remove file `C:\\enlens\\Lib\\pydantic_core\\_pydantic_core.pyd`: " +
          os.environ.get("WHY", "The process cannot access the file because it is being used by another process. (os error 32)"))
    sys.exit(2)
'''
# a stand-in app: names its process in the address file, as the real one does, and runs for a while
FAKE_APP = r'''
import json, os, sys, time
open(sys.argv[1], "w").write(json.dumps({"pid": os.getpid(), "url": "http://127.0.0.1:1/"}))
time.sleep(float(sys.argv[2]) if len(sys.argv) > 2 else 20)
'''


@pytest.fixture()
def job(tmp_path):
    """A job for handover.run, with the app to quit (a real process), uv, post-install and the app's start."""
    (tmp_path / "uv.py").write_text(FAKE_UV)
    (tmp_path / "app.py").write_text(FAKE_APP)
    alive = tmp_path / "app-alive"
    alive.write_text("1")
    app = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    started = []

    def quit_app(after=0.4):
        def go():
            time.sleep(after)
            app.terminate()
            app.wait()
            alive.unlink()
        threading.Thread(target=go, daemon=True).start()

    j = {"from": "0.15.4", "version": "0.15.5", "folder": str(tmp_path), "pids": [app.pid],
         "install": [sys.executable, str(tmp_path / "uv.py"), str(tmp_path / "uv-state.json")],
         "env": {"APP_ALIVE": str(alive)},
         "post": [sys.executable, "-c", f"open({str(tmp_path / 'post-ran')!r}, 'w').write('1')"],
         "start": [sys.executable, str(tmp_path / "app.py"), str(tmp_path / "app.json")],
         "info": str(tmp_path / "app.json"), "result": str(tmp_path / "result.json"),
         "log": str(tmp_path / "logs" / "update.log"), "install_url": "", "wait": 10, "tries": 4,
         "retry_after": 0.05, "settle": 0.05, "come_back": 10}
    yield j, quit_app, started
    if app.poll() is None:
        app.kill()
        app.wait()
    try:  # the app the script started
        pid = json.loads((tmp_path / "app.json").read_text())["pid"]
        if pid != app.pid:
            os.kill(pid, 9)
    except (OSError, ValueError, KeyError):
        pass


def _uv(job) -> dict:
    p = Path(job["folder"]) / "uv-state.json"
    return json.loads(p.read_text()) if p.exists() else {"calls": 0}


def test_it_installs_once_the_app_has_quit_then_starts_it_again(job, monkeypatch):
    from enlens_claims import handover

    j, quit_app, _ = job
    quit_app()
    r = handover.run(j)
    assert r["ok"] and r["installed"] and r["restarted"], r
    assert _uv(j) == {"calls": 1, "app_gone": [True]}  # uv ran after the app had gone, never beside it
    assert (Path(j["folder"]) / "post-ran").exists()
    assert json.loads(Path(j["result"]).read_text())["ok"] is True
    log = Path(j["log"]).read_text()
    assert "waiting for the app to quit" in log and "install, try 1: exit 0" in log and "started ENLENS again" in log


def test_it_tries_again_while_windows_holds_a_file(job):
    from enlens_claims import handover

    j, quit_app, _ = job
    j["env"]["FAIL"] = "2"
    quit_app()
    r = handover.run(j)
    assert r["ok"] and _uv(j)["calls"] == 3 and r["restarted"]


def test_a_held_file_that_stays_held_is_said_and_the_app_still_comes_back(job):
    from enlens_claims import handover

    j, quit_app, _ = job
    j["env"].update(FAIL="-1", WHY="Access is denied. (os error 5)")
    j["tries"] = 2
    quit_app()
    r = handover.run(j)
    assert not r["ok"] and r["hint"] == "in_use" and "os error 5" in r["error"]
    assert _uv(j)["calls"] == 2 and not (Path(j["folder"]) / "post-ran").exists()
    assert r["restarted"]  # the version still installed runs again, and says what happened


def test_nothing_is_installed_while_another_program_uses_enlens(job, monkeypatch):
    """Claude Code's ENLENS connector runs from ENLENS's own folder: uv would remove part of it and stop, leaving an
    ENLENS that cannot start (as on GitHub's Windows machine). So the script waits, then starts ENLENS as it was."""
    from enlens_claims import handover

    j, quit_app, _ = job
    j.update(env_dir=j["folder"], free_wait=0.3)
    monkeypatch.setattr(handover, "_in_use", lambda folder: ["python.exe (process 7)"] if folder == j["folder"] else [])
    quit_app()
    r = handover.run(j)
    assert not r["ok"] and not r["installed"] and r["hint"] == "in_use" and _uv(j)["calls"] == 0
    assert r["restarted"] and "python.exe (process 7)" in Path(j["log"]).read_text()


def test_it_installs_once_the_other_program_lets_go(job, monkeypatch):
    from enlens_claims import handover

    j, quit_app, _ = job
    j.update(env_dir=j["folder"], free_wait=10)
    looks = []
    monkeypatch.setattr(handover, "_in_use", lambda folder: ["python.exe"] if looks.append(folder) or len(looks) < 2 else [])
    quit_app()
    r = handover.run(j)  # one look in use, two seconds, then free
    assert r["ok"] and len(looks) == 2 and _uv(j)["calls"] == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows' list of processes")
def test_the_programs_running_from_a_folder_are_found(tmp_path):
    """Claude Code's connector runs ENLENS's own Python: a program started from the folder is found, by its path."""
    from enlens_claims import handover

    here = os.path.dirname(sys.executable)
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        time.sleep(1)
        found = handover.programs_in(here)
        assert any(f"(process {p.pid})" in f for f in found), found
        assert handover.programs_in(str(tmp_path)) == []
    finally:
        p.kill()
        p.wait()


def test_elsewhere_no_program_is_looked_for(tmp_path):
    from enlens_claims import handover

    if os.name != "nt":
        assert handover.programs_in(str(tmp_path)) == [] and handover.programs_in(sys.prefix) == []


def test_an_app_that_does_not_quit_is_left_alone(job):
    from enlens_claims import handover

    j, _, _ = job
    j["wait"] = 0.5
    r = handover.run(j)
    assert not r["ok"] and r["hint"] == "not_quit" and _uv(j)["calls"] == 0
    assert not Path(j["info"]).exists()  # nothing started beside the app that still runs


def test_an_app_that_does_not_come_back_is_said(job):
    from enlens_claims import handover

    j, quit_app, _ = job
    j["start"] = [sys.executable, "-c", "pass"]  # starts and ends without answering
    j["come_back"] = 1
    quit_app()
    r = handover.run(j)
    assert r["installed"] and r["restarted"] is False  # on Windows a PowerShell window then runs the install line


def test_the_script_runs_on_its_own(job, tmp_path):
    """As on Windows: a copy of the script, run by a Python that does not know ENLENS (-I: no site, no PYTHONPATH)."""
    j, quit_app, _ = job
    folder = tmp_path / "elsewhere"
    folder.mkdir()
    shutil.copyfile(HANDOVER, folder / "handover.py")
    (folder / "job.json").write_text(json.dumps(j))
    quit_app()
    r = subprocess.run([sys.executable, "-I", str(folder / "handover.py"), str(folder / "job.json")], cwd=folder,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(Path(j["result"]).read_text())["ok"] is True


def test_the_script_imports_only_the_standard_library():
    import ast

    tree = ast.parse(HANDOVER.read_text(encoding="utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not any(isinstance(n, ast.ImportFrom) and n.level for n in ast.walk(tree))  # nothing relative
    assert names <= set(sys.stdlib_module_names) | {"__future__"}, names


# ---------------------------------------------------------------------------------------------
# the app's side: update_release on Windows
# ---------------------------------------------------------------------------------------------
def test_windows_checks_the_download_then_hands_the_install_over(monkeypatch, home):  # noqa: F811
    from enlens_claims import update

    monkeypatch.setattr(update, "find_uv", lambda: "C:/uv/uv.exe")
    jobs = []
    restart = ["pythonw.exe", "-m", "enlens_claims.gui.launch", "--port", "8765", "--headless", "--launcher"]
    r = update.update_release(fetch=_releases(), run=lambda *a: pytest.fail("installs nothing itself"), windows=True,
                              restart=restart, start=jobs.append)
    assert r["updated"] and r["handover"] and r["version"] == NEXT
    j = jobs[0]
    folder = Path(j["folder"])
    assert folder == update.updates_folder() / NEXT and folder.is_dir()  # kept for the script, not removed
    wheel = folder / f"enlens_claims-{NEXT}-py3-none-any.whl"
    assert wheel.read_bytes() == b"PK fake wheel"
    assert j["install"][:7] == ["C:/uv/uv.exe", "tool", "install", "--force", "--quiet", "--python", "3.12"]
    assert j["install"][7].endswith(wheel.resolve().as_uri())
    assert j["pids"] == [os.getpid()] and j["start"] == restart and j["env_dir"] == sys.prefix
    assert j["post"][1:] == ["-m", "enlens_claims.cli", "post-install", "--by", "script", "--no-icon"]
    assert j["result"] == str(update.result_path()) and j["env"] == {"UV_PYTHON_PREFERENCE": "only-managed"}
    assert j["install_url"].endswith(f"/releases/download/v{NEXT}/install.ps1")
    # a download that does not match is never handed over, and leaves nothing behind
    with pytest.raises(update.UpdateError, match="does not match"):
        update.update_release(fetch=_releases(good_sum=False), windows=True, restart=restart, start=jobs.append)
    assert len(jobs) == 1 and not any(update.updates_folder().iterdir())


def test_windows_without_the_app_says_to_press_update(monkeypatch):
    from enlens_claims import update

    monkeypatch.setattr(update, "find_uv", lambda: "C:/uv/uv.exe")
    with pytest.raises(update.UpdateError, match=f"press Update to {NEXT}") as e:
        update.update_release(fetch=_releases(), windows=True)
    assert "install.ps1" in str(e.value)  # and the line, for a terminal


def test_start_handover_runs_the_copied_script_with_the_python_outside(monkeypatch, tmp_path):
    from enlens_claims import handover, update

    started = []
    monkeypatch.setattr(handover, "_start", lambda args, folder: started.append((args, folder)) or 1)
    update.start_handover({"folder": str(tmp_path), "pids": [1]})
    (args, folder), = started
    assert args == [update.outside_python(), str(tmp_path / "handover.py"), str(tmp_path / "job.json")]
    assert (tmp_path / "handover.py").read_bytes() == HANDOVER.read_bytes()
    assert json.loads((tmp_path / "job.json").read_text()) == {"folder": str(tmp_path), "pids": [1]}
    assert update.outside_python().startswith(sys.base_prefix)


def test_the_release_api_can_be_a_stand_in(monkeypatch):
    from enlens_claims import update

    asked = []
    monkeypatch.setenv("ENLENS_RELEASE_API", "http://127.0.0.1:9/fake/")
    with pytest.raises(update.UpdateError):
        update.latest_release(fetch=lambda url: asked.append(url) or b"not json", channel="stable")
    assert asked == ["http://127.0.0.1:9/fake/releases/latest"]
    assert update.latest_version(lambda url: pytest.fail("the page is not asked"), channel="stable") == ""


# ---------------------------------------------------------------------------------------------
# the app's side: the route and the note
# ---------------------------------------------------------------------------------------------
def test_on_windows_update_quits_the_app_for_the_handover(served, monkeypatch):  # noqa: F811
    from enlens_claims import update
    from enlens_claims.gui import server

    a, app, restarts = served
    stops = []
    app.stop = lambda: stops.append(1)
    app.launcher = True
    monkeypatch.setattr(server, "os", AsWindows())  # the server's own view of the system: Windows
    seen = {}

    def fake(check_only=False, **kw):
        seen.update(kw)
        return {"updated": True, "from": "0.15.4", "version": "0.15.5", "handover": True}

    monkeypatch.setattr(update, "update", fake)
    monkeypatch.setattr(server, "_installed_version", lambda: server.__version__)
    st, r = a("POST", "/api/update", {})
    assert st == 200 and r["handover"] and r["restarting"] and r["version"] == "0.15.5"
    assert seen["restart"][1:4] == ["-m", "enlens_claims.gui.launch", "--host"] and "--launcher" in seen["restart"]
    assert str(app.port) in seen["restart"]
    t0 = time.time()
    while not stops and time.time() - t0 < 5:
        time.sleep(0.05)
    assert stops and not restarts  # it quits; handover.py starts it again


def test_elsewhere_update_asks_for_no_handover(served, monkeypatch):  # noqa: F811
    from enlens_claims import update
    from enlens_claims.gui import server

    a, app, restarts = served
    seen = []
    monkeypatch.setattr(update, "update", lambda check_only=False, **kw: seen.append(kw) or
                        {"updated": True, "from": "1", "version": "2"})
    monkeypatch.setattr(server, "_installed_version", lambda: server.__version__)
    if os.name == "nt":
        pytest.skip("this is Windows")
    st, r = a("POST", "/api/update", {})
    assert st == 200 and r["handover"] is False and seen == [{}]


def test_an_update_that_did_not_finish_is_said_once(served):  # noqa: F811
    from enlens_claims import update

    a, _, _ = served
    update.updates_folder().mkdir(parents=True, exist_ok=True)
    update.result_path().write_text(json.dumps({"ok": False, "hint": "in_use", "version": "0.15.5"}))
    note = a("GET", "/api/whats-new")[1]["note"]
    assert note["kind"] == "problem" and note["title"] == "The update to 0.15.5 did not finish"
    assert "Claude Code" in " ".join(note["points"])
    assert not update.result_path().exists()
    assert (a("GET", "/api/whats-new")[1]["note"] or {}).get("kind") != "problem"  # once
    update.result_path().write_text(json.dumps({"ok": True, "version": "0.15.5"}))
    assert (a("GET", "/api/whats-new")[1]["note"] or {}).get("kind") != "problem"
    assert not update.result_path().exists()  # a good result is only cleared away


def test_the_page_waits_longer_for_the_handover_and_shows_the_problem():
    app = (ROOT / "src" / "enlens_claims" / "gui" / "static" / "app.js").read_text(encoding="utf-8")
    assert "waitForRestart(r.version, r.handover)" in app and "handover ? 300000 : 90000" in app
    assert 'note.kind === "problem"' in app
    from _static import all_css  # 0.17.0: the cascade, so it holds when the rule moves

    assert ".release-note-problem" in all_css()
