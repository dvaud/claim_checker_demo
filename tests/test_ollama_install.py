"""0.15.6: Ollama installed from the app with one button, as Claude Code is.

The card for a model on this computer promised "no terminal", but its first step linked to ollama.com, whose download
page now leads with a line to type in a terminal. Now one button installs Ollama: the dialog first says how big the
download is on this kind of computer (1.7 GB for Windows, 230 MB for macOS) and how much free space it needs; then the
app downloads Ollama's own installer, checks that it is Ollama's (Authenticode signer O=Ollama Inc. on Windows,
codesign against Ollama's Developer ID team on macOS), installs it for this user and starts it, with progress and
Stop. On Linux a terminal window runs Ollama's own line (it asks for the password). An Ollama that is installed but not
running is started with one button. These tests use a local web server in place of ollama.com and never install a
real Ollama.
"""
from __future__ import annotations

import os
import shutil
import threading
import time
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler

from enlens_claims.gui.server import QuickServer
from pathlib import Path

import pytest

from helpers import manual_text
from enlens_claims import ollama_setup
from test_app import Api, api, home  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "enlens_claims" / "gui" / "static"


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class _Server(QuickServer):   # (no 35-second wait for this computer's name on a Mac: tests/test_quick_server.py)
    def handle_error(self, request, client_address):
        pass   # a download stopped part way closes the connection mid-file


@pytest.fixture
def site(tmp_path, monkeypatch):
    """ollama.com/download, on this computer: a folder served over HTTP (HEAD gives Content-Length, as GitHub does)."""
    root = tmp_path / "site"
    root.mkdir()
    srv = _Server(("127.0.0.1", 0), partial(_Quiet, directory=str(root)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("ENLENS_OLLAMA_DOWNLOAD", f"http://127.0.0.1:{srv.server_address[1]}")
    ollama_setup._SIZE.clear()
    yield root
    srv.shutdown()
    ollama_setup._SIZE.clear()


@pytest.fixture
def nowhere(monkeypatch, tmp_path):
    """No Ollama on this computer (this Mac has one in /Applications)."""
    monkeypatch.setattr(ollama_setup, "mac_folders", lambda: [tmp_path / "Applications", tmp_path / "home" / "Applications"])
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.setattr(ollama_setup, "_on_path", lambda name: None)


# ---------------------------------------------------------------------------------------------- the size, first
def test_the_size_comes_from_ollama_com_and_the_room_from_it(site):
    (site / "OllamaSetup.exe").write_bytes(b"x" * 3_000_000)
    (site / "Ollama-darwin.zip").write_bytes(b"x" * 1_000_000)
    assert ollama_setup.download_size("windows") == {"bytes": 3_000_000, "exact": True}
    assert ollama_setup.download_size("mac") == {"bytes": 1_000_000, "exact": True}
    p = ollama_setup.plan("windows")
    assert p["size"] == {"bytes": 3_000_000, "exact": True} and p["needs"] == 12_000_000 and p["free"] > 0
    assert p["from"].endswith("/OllamaSetup.exe") and p["how"] == "app"


def test_without_ollama_com_the_known_size_is_said_as_about(monkeypatch):
    monkeypatch.setenv("ENLENS_OLLAMA_DOWNLOAD", "http://127.0.0.1:9")
    ollama_setup._SIZE.clear()
    assert ollama_setup.download_size("windows") == {"bytes": 1_700_000_000, "exact": False}
    assert ollama_setup.download_size("mac") == {"bytes": 230_000_000, "exact": False}


def test_status_per_system(nowhere, tmp_path):
    win = ollama_setup.status("windows")
    assert win == {"installed": False, "path": "", "system": "windows", "how": "app", "line": "",
                   "manual": "https://ollama.com/download/OllamaSetup.exe"}
    assert ollama_setup.status("mac")["manual"] == "https://ollama.com/download/Ollama.dmg"   # the file, not the page
    lin = ollama_setup.status("linux")
    assert lin["how"] == "terminal" and lin["line"] == "curl -fsSL https://ollama.com/install.sh | sh"
    exe = tmp_path / "LocalAppData" / "Programs" / "Ollama" / "ollama app.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert ollama_setup.status("windows")["installed"] is True and ollama_setup.app_path("windows") == exe
    (tmp_path / "home" / "Applications" / "Ollama.app").mkdir(parents=True)
    assert ollama_setup.status("mac")["installed"] is True


# ---------------------------------------------------------------------------------------------- the download
def test_download_reports_progress_and_can_stop(site, tmp_path):
    (site / "OllamaSetup.exe").write_bytes(os.urandom(3 << 20))
    seen = []
    dest = tmp_path / "got.exe"
    assert ollama_setup._download(ollama_setup.download_url("windows"), dest, seen.append, lambda: False) is True
    assert dest.read_bytes() == (site / "OllamaSetup.exe").read_bytes()
    assert seen[0] == {"step": "download", "done": 0, "total": 3 << 20} and seen[-1]["done"] == 3 << 20
    assert [p["done"] for p in seen] == sorted(p["done"] for p in seen)
    calls = []
    assert ollama_setup._download(ollama_setup.download_url("windows"), dest, lambda p: None,
                                  lambda: calls.append(1) or len(calls) > 1) is False


def test_not_enough_room_says_how_much(site, tmp_path, monkeypatch):
    (site / "OllamaSetup.exe").write_bytes(b"x" * 2_000_000)
    monkeypatch.setattr(ollama_setup, "free_space", lambda where=None: 5_000_000)
    with pytest.raises(ValueError, match=r"not enough free disk space for Ollama: it needs about 8 MB, and 5 MB is free"):
        ollama_setup._download(ollama_setup.download_url("windows"), tmp_path / "x.exe", lambda p: None, lambda: False)


def test_offline_says_so(monkeypatch, tmp_path):
    monkeypatch.setenv("ENLENS_OLLAMA_DOWNLOAD", "http://127.0.0.1:9")
    with pytest.raises(ValueError, match="Is this computer online"):
        ollama_setup._download(ollama_setup.download_url("mac"), tmp_path / "x.zip", lambda p: None, lambda: False)


# ---------------------------------------------------------------------------------------------- Windows
def test_windows_signature_must_be_valid_and_ollamas(monkeypatch):
    runs = []

    def fake(stdout):
        def run(args, **kw):
            runs.append((args, kw))
            return type("R", (), {"stdout": stdout, "stderr": "", "returncode": 0})()
        return run

    accented = Path("C:/Users/Dávid/AppData/Local/Temp/enlens-ollama-1/OllamaSetup.exe")
    monkeypatch.setattr(ollama_setup.subprocess, "run", fake("Valid|CN=Ollama Inc., O=Ollama Inc., L=Toronto, S=Ontario, C=CA\n"))
    assert ollama_setup.check_windows(accented) == ""
    args, kw = runs[-1]
    assert args[0] == "powershell" and "Get-AuthenticodeSignature -LiteralPath $env:ENLENS_OLLAMA_FILE" in args[-1]
    assert kw["env"]["ENLENS_OLLAMA_FILE"] == str(accented) and str(accented) not in " ".join(args)   # no quoting
    monkeypatch.setattr(ollama_setup.subprocess, "run", fake("Valid|CN=Not Ollama Inc., O=Not Ollama Inc., C=CA\n"))
    assert "signed by someone other than Ollama" in ollama_setup.check_windows(accented)
    monkeypatch.setattr(ollama_setup.subprocess, "run", fake("NotSigned|\n"))
    assert "does not call its signature valid (NotSigned)" in ollama_setup.check_windows(accented)
    monkeypatch.setattr(ollama_setup.subprocess, "run", fake("HashMismatch|CN=Ollama Inc., O=Ollama Inc.\n"))
    assert "HashMismatch" in ollama_setup.check_windows(accented)


@pytest.mark.skipif(os.name == "nt", reason="a shell script stands in for OllamaSetup.exe")
def test_windows_installer_runs_silently_for_this_user(nowhere, tmp_path):
    local = tmp_path / "LocalAppData"
    setup = tmp_path / "OllamaSetup.exe"
    args_file = tmp_path / "args.txt"
    setup.write_text("#!/bin/sh\n"
                     f'echo "$@" > "{args_file}"\n'
                     f'mkdir -p "{local}/Programs/Ollama" && : > "{local}/Programs/Ollama/ollama app.exe"\n')
    setup.chmod(0o755)
    assert ollama_setup._install_windows(setup) == local / "Programs" / "Ollama" / "ollama app.exe"
    assert args_file.read_text().split() == ["/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"]
    assert (local / "Ollama" / "upgraded").exists()   # as install.ps1 leaves it: Ollama starts hidden, in the tray
    # a failing installer: says so, and leaves no marker that would hide Ollama's next start
    (local / "Ollama" / "upgraded").unlink()
    setup.write_text("#!/bin/sh\nexit 5\n")
    with pytest.raises(ValueError, match=r"Ollama's installer stopped \(code 5\)"):
        ollama_setup._install_windows(setup)
    assert not (local / "Ollama" / "upgraded").exists()


def test_windows_install_installs_only_ollamas_file(site, nowhere, tmp_path, monkeypatch):
    (site / "OllamaSetup.exe").write_bytes(b"MZ" + os.urandom(100_000))
    installed, started = [], []
    monkeypatch.setattr(ollama_setup, "_install_windows", lambda f: installed.append(f.read_bytes()) or tmp_path / "ollama app.exe")
    monkeypatch.setattr(ollama_setup, "start", lambda name=None: started.append(name) or {"started": True})
    monkeypatch.setattr(ollama_setup, "check_windows", lambda f: "it is signed by someone other than Ollama (CN=Mallory)")
    with pytest.raises(ValueError, match="ENLENS did not install what it downloaded: it is signed by someone other than Ollama"):
        ollama_setup.install(sys_name="windows", is_running=lambda: False)
    assert installed == [] and started == []
    monkeypatch.setattr(ollama_setup, "check_windows", lambda f: "")
    steps = []
    r = ollama_setup.install(on_progress=lambda p: steps.append(p["step"]), sys_name="windows", is_running=lambda: True)
    assert installed == [(site / "OllamaSetup.exe").read_bytes()] and r == {"path": str(tmp_path / "ollama app.exe"), "running": True}
    assert started == []   # Windows' installer starts Ollama itself
    assert [s for i, s in enumerate(steps) if i == 0 or steps[i - 1] != s] == ["download", "check", "install", "start"]
    assert not ollama_setup.downloads().exists()   # the 1.7 GB file is not kept


def test_a_stop_after_installing_starts_nothing_and_waits_for_ollama(site, nowhere, tmp_path, monkeypatch):
    """Quitting the app stops every job: once Ollama is installed, that must not start a second copy beside the one
    the installer starts, nor call a running Ollama "not answering"."""
    (site / "OllamaSetup.exe").write_bytes(b"MZ" + os.urandom(1000))
    phase, started, looks = {"now": ""}, [], []
    monkeypatch.setattr(ollama_setup, "check_windows", lambda f: "")
    monkeypatch.setattr(ollama_setup, "_install_windows", lambda f: tmp_path / "ollama app.exe")
    monkeypatch.setattr(ollama_setup, "start", lambda name=None: started.append(name))
    monkeypatch.setattr(ollama_setup.time, "sleep", lambda s: None)
    r = ollama_setup.install(on_progress=lambda p: phase.update(now=p["step"]), should_stop=lambda: phase["now"] == "start",
                             is_running=lambda: looks.append(1) or len(looks) > 3, sys_name="windows")
    assert r == {"path": str(tmp_path / "ollama app.exe"), "running": True} and started == []


def test_left_over_downloads_are_cleared(home):  # noqa: F811
    d = ollama_setup.downloads()
    d.mkdir(parents=True)
    (d / "OllamaSetup.exe").write_bytes(b"part of 1.7 GB")
    ollama_setup.clear_downloads()
    assert not d.exists()
    src = (ROOT / "src" / "enlens_claims" / "gui" / "server.py").read_text(encoding="utf-8")
    assert "    ollama_setup.clear_downloads()" in src.split("def serve(", 1)[1]   # when the app starts


# ---------------------------------------------------------------------------------------------- macOS
def _fake_app_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Ollama.app/Contents/Info.plist", "<plist/>")
        z.writestr("Ollama.app/Contents/MacOS/Ollama", "#!/bin/sh\n")


@pytest.mark.skipif(not shutil.which("ditto"), reason="ditto is macOS's")
def test_mac_install_checks_the_signature_then_moves_and_opens_it(site, nowhere, tmp_path, monkeypatch):
    _fake_app_zip(site / "Ollama-darwin.zip")
    ro = tmp_path / "Applications"
    ro.mkdir()
    ro.chmod(0o555)   # /Applications that this user cannot write: ~/Applications instead
    started = []
    monkeypatch.setattr(ollama_setup, "start", lambda name=None: started.append(name) or {"started": True})
    try:
        monkeypatch.setattr(ollama_setup, "check_mac", lambda app: "its signature is not Ollama's (not signed at all)")
        with pytest.raises(ValueError, match="Nothing was installed"):
            ollama_setup.install(sys_name="mac", is_running=lambda: False)
        assert not (tmp_path / "home" / "Applications" / "Ollama.app").exists() and started == []
        monkeypatch.setattr(ollama_setup, "check_mac", lambda app: "" if (app / "Contents" / "MacOS" / "Ollama").exists() else "?")
        r = ollama_setup.install(sys_name="mac", is_running=lambda: True)
    finally:
        ro.chmod(0o755)
    dest = tmp_path / "home" / "Applications" / "Ollama.app"
    assert r == {"path": str(dest), "running": True} and (dest / "Contents" / "MacOS" / "Ollama").exists()
    assert started == ["mac"]   # opened hidden, as install.sh does


def test_the_mac_requirement_asks_for_ollamas_developer_id_and_notarisation():
    req = ollama_setup.MAC_REQUIREMENT
    assert req.startswith("anchor apple generic and ") and req.endswith(" and notarized")
    assert 'certificate leaf[subject.OU] = "3MU9H2V9Y9"' in req
    assert "certificate leaf[field.1.2.840.113635.100.6.1.13] exists" in req   # a Developer ID, not a development one


@pytest.mark.skipif(not shutil.which("codesign"), reason="codesign is macOS's")
def test_codesign_refuses_an_app_that_is_not_ollamas(tmp_path):
    app = tmp_path / "Ollama.app" / "Contents" / "MacOS"
    app.mkdir(parents=True)
    shutil.copy("/bin/echo", app / "Ollama")   # Apple's signature, not Ollama's team
    assert ollama_setup.check_mac(tmp_path / "Ollama.app").startswith("its signature is not Ollama's")
    real = Path("/Applications/Ollama.app")
    if real.exists():   # this Mac has the real one: Ollama's own signature passes
        assert ollama_setup.check_mac(real) == ""


def test_installed_but_not_running_is_started_not_downloaded(nowhere, tmp_path, monkeypatch):
    (tmp_path / "Applications" / "Ollama.app").mkdir(parents=True)
    monkeypatch.setattr(ollama_setup, "_download", lambda *a: pytest.fail("downloaded although Ollama is installed"))
    monkeypatch.setattr(ollama_setup, "start", lambda name=None: {"started": True, "path": "/Applications/Ollama.app"})
    r = ollama_setup.install(sys_name="mac", is_running=lambda: True)
    assert r == {"path": "/Applications/Ollama.app", "running": True, "already": True}


def test_linux_runs_ollamas_line_in_a_terminal_window(home, monkeypatch):  # noqa: F811
    from enlens_claims import claude_setup

    opened = []
    monkeypatch.setattr(claude_setup, "_open_window", lambda script: opened.append(script) or "xterm")
    r = ollama_setup.open_terminal()
    assert r == {"opened": True, "window": "xterm", "command": "curl -fsSL https://ollama.com/install.sh | sh"}
    text = opened[0].read_text()
    assert "curl -fsSL https://ollama.com/install.sh | sh\n" in text and "asks for your password" in text
    with pytest.raises(ValueError, match="terminal window"):
        ollama_setup.install(sys_name="linux")


# ---------------------------------------------------------------------------------------------- the app's API
def test_servers_say_whether_ollama_is_installed(api, nowhere, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ollama_setup, "system", lambda: "windows")
    st, info = api("GET", "/api/servers")
    assert st == 200 and info["ollama_app"]["installed"] is False and info["ollama_app"]["how"] == "app"


def test_plan_install_job_and_stop(api, site, nowhere, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ollama_setup, "system", lambda: "windows")
    (site / "OllamaSetup.exe").write_bytes(b"x" * 4_000_000)
    st, plan = api("GET", "/api/ollama")
    assert st == 200 and plan["size"] == {"bytes": 4_000_000, "exact": True} and plan["needs"] == 16_000_000

    def fake_install(on_progress, should_stop, is_running):
        on_progress({"step": "download", "done": 0, "total": 4_000_000})
        while not should_stop():
            if os.environ.get("FAKE_FINISH"):
                on_progress({"step": "start"})
                return {"path": "C:/x/ollama app.exe", "running": True}
            time.sleep(0.02)
        return {"stopped": True}

    monkeypatch.setattr(ollama_setup, "install", fake_install)
    st, r = api("POST", "/api/ollama/install", {})
    assert st == 200 and r["job"]["kind"] == "ollama-install"
    st, again = api("POST", "/api/ollama/install", {})
    assert again["job"]["id"] == r["job"]["id"]   # one install at a time
    api("POST", f"/api/jobs/{r['job']['id']}/cancel")
    assert api.wait(r["job"]["id"])["state"] == "cancelled"
    monkeypatch.setenv("FAKE_FINISH", "1")
    job = api.wait(api("POST", "/api/ollama/install", {})[1]["job"]["id"])
    assert job["state"] == "done" and job["result"] == {"path": "C:/x/ollama app.exe", "running": True}


def test_no_start_while_an_install_runs(api, nowhere, monkeypatch):  # noqa: F811
    """The installer writes "ollama app.exe" first: Ollama looks installed while the rest is still being written."""
    monkeypatch.setattr(ollama_setup, "system", lambda: "windows")
    monkeypatch.setattr(ollama_setup, "start", lambda name=None: pytest.fail("started during the install"))

    def slow_install(on_progress, should_stop, is_running):
        on_progress({"step": "install"})
        while not should_stop():
            time.sleep(0.02)
        return {"stopped": True}

    monkeypatch.setattr(ollama_setup, "install", slow_install)
    job = api("POST", "/api/ollama/install", {})[1]["job"]
    st, r = api("POST", "/api/ollama/start", {})
    assert st == 200 and r["job"]["id"] == job["id"]
    api("POST", f"/api/jobs/{job['id']}/cancel")
    api.wait(job["id"])


def test_start_and_linux_from_the_api(api, nowhere, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ollama_setup, "system", lambda: "mac")
    st, r = api("POST", "/api/ollama/start", {})
    assert st == 409 and "Ollama is not on this computer" in r["error"]
    monkeypatch.setattr(ollama_setup, "system", lambda: "linux")
    monkeypatch.setattr(ollama_setup, "open_terminal", lambda: {"opened": False, "window": "", "command": ollama_setup.LINUX_LINE})
    st, r = api("POST", "/api/ollama/install", {})
    assert st == 200 and r == {"terminal": {"opened": False, "window": "", "command": ollama_setup.LINUX_LINE}}


# ---------------------------------------------------------------------------------------------- the page and docs
def test_page_files():
    js = (STATIC / "views" / "local-model.js").read_text(encoding="utf-8")
    assert "Open ollama.com" not in js   # the page that leads with a terminal line
    assert '"Install Ollama"' in js and '"Start Ollama"' in js
    assert 'api("GET", "/api/ollama")' in js and 'api("POST", "/api/ollama/install", {})' in js and 'api("POST", "/api/ollama/start", {})' in js
    # the size on this kind of computer and the room it needs, before anything is downloaded
    assert "`Download: ${amount}`" in js and "Free disk space needed: about" in js and '"Not enough free disk space"' in js
    assert "Download ${amount} and install" in js and "None of your documents are sent." in js
    assert 'x.kind === "ollama-install"' in js and "/cancel" in js   # an install already running is shown again
    assert "if (j && app.how !== \"terminal\")" in js   # also when Ollama already looks installed (0.18.0rc2: the same look decides on the start by itself)
    assert "Ollama did not answer within a minute." in js   # Start Ollama does not wait for ever
    registry = (STATIC / "registry.js").read_text(encoding="utf-8")
    assert '"ollama-install": { icon: "download", text: "Installing Ollama", link: "#/settings/model" }' in registry


def test_the_docs_say_so():
    api_md = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")
    assert "GET /api/ollama" in api_md and "POST /api/ollama/install" in api_md and "POST /api/ollama/start" in api_md
    manual = manual_text()
    assert "*Install Ollama*" in manual and "1.7 GB" in manual and "*Start Ollama*" in manual
