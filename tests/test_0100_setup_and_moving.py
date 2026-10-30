"""0.10: from GitHub to the ENLENS icon in one line, Claude set up with one button, and moving to another computer.

- installation.py says how ENLENS was installed (git copy, the one-line install, a package, pip); `enlens
  post-install` records it, makes the icon and repairs the Claude Code plugin; `enlens update` follows it (a git
  copy pulls, the one-line install takes the newest GitHub Release, checked against its SHA256SUMS);
- install/install.sh runs with stand-ins for uv and curl (no network), and refuses a package whose checksum is wrong;
- tools/release.py checks the version everywhere, writes the install scripts and the checksums;
- "Set up Claude": the app installs Claude Code (a stand-in installer), opens the sign-in and waits for it, adds the
  plugin; the plugin is written again when the Python it names has moved;
- Move ENLENS to another computer: every project and the settings in one zip, never a saved cloud key; importing it
  on a new computer takes the settings, on one in use keeps its own;
- Tesseract is found where its installers put it, and the app says how to get it on this system.
A test never touches a real Claude Code (conftest.py), a real uv or the network.
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from test_app import Api, api, home  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parent.parent
FAKE = str(Path(__file__).with_name("fake_claude_cli.py"))
INSTALLER = str(Path(__file__).with_name("fake_claude_installer.py"))
sys.path.insert(0, str(ROOT / "tools"))


@pytest.fixture
def prefix(tmp_path, monkeypatch):
    """A Python prefix of its own, so the install marker is never written into the test's venv."""
    p = tmp_path / "prefix"
    p.mkdir()
    monkeypatch.setattr(sys, "prefix", str(p))
    return p


@pytest.fixture
def fake_claude(monkeypatch):
    monkeypatch.setenv("ENLENS_CLAUDE", FAKE)
    from enlens_claims import claude_setup

    claude_setup._STATUS.update(at=0.0, value=None)
    return claude_setup


# ---------------------------------------------------------------------------------------------
# how ENLENS was installed
# ---------------------------------------------------------------------------------------------
def test_installation_kind_and_marker(prefix, monkeypatch):
    from enlens_claims import installation, update

    assert installation.kind() == "git"  # the tests run from the git copy
    monkeypatch.setattr(update, "source_root", lambda: None)
    assert installation.kind() == "pip"
    p = installation.write_marker("script")
    assert p == prefix / "enlens-install.json"
    m = json.loads(p.read_text())
    assert m["kind"] == "script" and m["repo"] == installation.REPO and m["python"] == sys.executable
    assert installation.kind() == "script"
    with pytest.raises(ValueError):
        installation.write_marker("zip")
    assert installation.install_line("mac") == ("curl -fsSL https://github.com/dvaud/claim_checker_demo/releases/latest/"
                                                 "download/install.sh | sh")
    assert "install.ps1 | iex" in installation.install_line("windows")
    assert set(installation.EXTRAS) == {"connector", "fast", "pdfminer", "ocr"}


def test_post_install_records_makes_the_icon_and_repairs_the_plugin(home, prefix, tmp_path, monkeypatch, fake_claude):  # noqa: F811
    from enlens_claims import installation

    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    monkeypatch.setattr("enlens_claims.gui.launcher._desktop", lambda: tmp_path / "user" / "Desktop")
    fake_claude.write_plugin()
    mcp = fake_claude.plugin_folder() / ".mcp.json"
    cfg = json.loads(mcp.read_text())
    cfg["mcpServers"]["enlens"]["command"] = "/old/place/python"
    mcp.write_text(json.dumps(cfg))
    out = installation.post_install(by="script", icon=True, open_app=False)
    assert installation.read_marker()["kind"] == "script"
    assert out["icons"] and all(Path(p).exists() for p in out["icons"])
    assert out["plugin"]["repaired"] and "/old/place/python" in out["plugin"]["reason"]
    assert [s["ok"] for s in out["plugin"]["steps"]] == [True, True]  # the two set-up commands, again
    assert json.loads(mcp.read_text())["mcpServers"]["enlens"]["command"] == sys.executable
    assert "ENLENS 0.10.0 is installed." in out["message"]
    # the CLI runs the same (without an icon here)
    from enlens_claims import cli

    assert cli.main(["post-install", "--by", "none", "--no-icon"]) == 0


def test_plugin_repair_only_when_needed(home, fake_claude, monkeypatch):  # noqa: F811
    assert fake_claude.stale() == "" and fake_claude.repair() == {"repaired": False}  # no plugin set up: nothing
    fake_claude.install()
    assert fake_claude.stale() == "" and fake_claude.repair()["repaired"] is False
    mcp = fake_claude.plugin_folder() / ".mcp.json"
    cfg = json.loads(mcp.read_text())
    cfg["mcpServers"]["enlens"]["env"]["ENLENS_HOME"] = "/elsewhere"
    mcp.write_text(json.dumps(cfg))
    assert "another data folder" in fake_claude.stale()
    monkeypatch.setenv("ENLENS_LOCAL_ONLY", "1")
    assert fake_claude.repair()["repaired"] is False  # local only: never
    monkeypatch.delenv("ENLENS_LOCAL_ONLY")
    assert fake_claude.repair()["repaired"] is True and fake_claude.stale() == ""


def test_desktop_config_follows_a_moved_python(home, tmp_path):  # noqa: F811
    from enlens_claims import mcp_server

    cfg = tmp_path / "claude_desktop_config.json"
    entry = {"command": str(tmp_path / "gone" / "python"), "args": ["-m", "enlens_claims.mcp_server"],
             "env": {"ENLENS_HOME": str(home.home())}}
    cfg.write_text(json.dumps({"mcpServers": {"enlens": entry, "other": {"command": "x"}}}))
    assert mcp_server.repair_desktop(cfg) is True
    data = json.loads(cfg.read_text())
    assert data["mcpServers"]["enlens"]["command"] == sys.executable and data["mcpServers"]["other"] == {"command": "x"}
    assert mcp_server.repair_desktop(cfg) is False  # now it fits
    entry["env"]["ENLENS_HOME"] = "/another/home"  # another data folder's entry is left alone
    cfg.write_text(json.dumps({"mcpServers": {"enlens": entry}}))
    assert mcp_server.repair_desktop(cfg) is False
    assert mcp_server.repair_desktop(tmp_path / "missing.json") is False


# ---------------------------------------------------------------------------------------------
# enlens update from GitHub Releases
# ---------------------------------------------------------------------------------------------
class Runs:
    def __init__(self, code=0):
        self.calls, self.code = [], code

    def __call__(self, cmd, cwd):
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, self.code, stdout="ok", stderr="boom" if self.code else "")


def _releases(version="0.10.1", wheel=b"PK fake wheel", good_sum=True):
    name = f"enlens_claims-{version}-py3-none-any.whl"
    digest = hashlib.sha256(wheel if good_sum else b"other").hexdigest()
    pages = {
        "https://api.github.com/repos/dvaud/claim_checker_demo/releases/latest": json.dumps({
            "tag_name": f"v{version}", "html_url": "https://github.com/x/releases/tag/v" + version, "body": "notes",
            "assets": [{"name": name, "browser_download_url": "https://dl/" + name},
                       {"name": "SHA256SUMS", "browser_download_url": "https://dl/SHA256SUMS"},
                       {"name": "install.sh", "browser_download_url": "https://dl/install.sh"}]}).encode(),
        "https://dl/" + name: wheel,
        "https://dl/SHA256SUMS": f"{digest}  {name}\n{'0' * 64}  install.sh\n".encode(),
    }
    return lambda url: pages[url]


def test_update_from_the_latest_release(monkeypatch, tmp_path):
    from enlens_claims import update

    monkeypatch.setattr(update, "find_uv", lambda: "/bin/uv")
    assert update.version_tuple("v0.10.1") == (0, 10, 1) and update.version_tuple("0.9.1") < update.version_tuple("0.10.0")
    r = update.update_release(fetch=_releases("0.10.0"), run=Runs())
    assert r["updated"] is False and "up to date" in r["message"]
    r = update.update_release(check_only=True, fetch=_releases(), run=Runs())
    assert r["waiting"] == "0.10.1" and "ready to install" in r["message"]
    runs = Runs()
    r = update.update_release(fetch=_releases(), run=runs, workdir=tmp_path, windows=False)
    assert r["updated"] and r["version"] == "0.10.1" and r["route"] == "release"
    uv = runs.calls[0]
    assert uv[:6] == ["/bin/uv", "tool", "install", "--force", "--quiet", "--python"]
    assert uv[-1].startswith("enlens-claims[connector,fast,pdfminer,ocr] @ file://") and uv[-1].endswith(".whl")
    assert runs.calls[1][1:] == ["-m", "enlens_claims.cli", "post-install", "--by", "script", "--no-icon"]
    # a download that does not match the release's checksum is never installed
    runs = Runs()
    with pytest.raises(update.UpdateError, match="does not match"):
        update.update_release(fetch=_releases(good_sum=False), run=runs, workdir=tmp_path, windows=False)
    assert runs.calls == []
    # Windows: the running program cannot replace itself: the install line, again
    with pytest.raises(update.UpdateError, match="install.ps1"):
        update.update_release(fetch=_releases(), run=Runs(), windows=True)
    # offline
    def offline(url):
        raise OSError("no network")
    with pytest.raises(update.UpdateError, match="Are you online"):
        update.update_release(fetch=offline)


def test_update_follows_the_way_it_was_installed(prefix, monkeypatch):
    from enlens_claims import installation, update

    monkeypatch.setattr(update, "source_root", lambda: None)
    installation.write_marker("script")
    called = {}
    monkeypatch.setattr(update, "update_release", lambda check_only=False, run=None: called.setdefault("release", check_only) or {"message": "x"})
    update.update(check_only=True)
    assert called == {"release": True}
    installation.write_marker("package")
    with pytest.raises(update.UpdateError, match="download"):
        update.update()


# ---------------------------------------------------------------------------------------------
# the one-line install, with stand-ins for uv and curl
# ---------------------------------------------------------------------------------------------
FAKE_UV = r"""#!/bin/sh
# a stand-in for uv: records its arguments, "installs" an enlens program that records its own
echo "UV_PYTHON_PREFERENCE=$UV_PYTHON_PREFERENCE $*" >> "$LOG"
if [ "$1 $2" = "tool dir" ]; then echo "$FAKE_BIN"; exit 0; fi
if [ "$1 $2" = "tool install" ]; then
  mkdir -p "$FAKE_BIN"
  printf '#!/bin/sh\necho "enlens $*" >> "%s"\necho "ENLENS is installed."\n' "$LOG" > "$FAKE_BIN/enlens"
  chmod +x "$FAKE_BIN/enlens"
fi
"""
FAKE_CURL = r"""#!/bin/sh
# a stand-in for curl: `curl -fsSL -o FILE URL` copies FILE's name from $FAKE_DL
out=""; url=""
while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift 2;; -*) shift;; *) url="$1"; shift;; esac; done
echo "curl $url" >> "$LOG"
cp "$FAKE_DL/$(basename "$url")" "$out"
"""


@pytest.fixture
def sandbox(tmp_path):
    if not shutil.which("sh"):
        pytest.skip("no POSIX shell")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, text in (("uv", FAKE_UV), ("curl", FAKE_CURL)):
        (bin_dir / name).write_text(text)
        (bin_dir / name).chmod(0o755)
    dl = tmp_path / "dl"
    dl.mkdir()
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path / "user"), "LOG": str(tmp_path / "log"),
           "FAKE_BIN": str(tmp_path / "user" / "tools-bin"), "FAKE_DL": str(dl), "ENLENS_NO_OPEN": "1"}
    return tmp_path, env


def test_install_sh_downloads_checks_installs_and_finishes(sandbox):
    tmp, env = sandbox
    script = tmp / "install.sh"
    script.write_text((ROOT / "install" / "install.sh").read_text().replace("@ENLENS_VERSION@", "0.10.0"))
    wheel = Path(env["FAKE_DL"]) / "enlens_claims-0.10.0-py3-none-any.whl"
    wheel.write_bytes(b"PK the package")
    (Path(env["FAKE_DL"]) / "SHA256SUMS").write_text(f"{hashlib.sha256(wheel.read_bytes()).hexdigest()}  {wheel.name}\n")
    r = subprocess.run(["sh", str(script)], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr + r.stdout
    log = (tmp / "log").read_text().splitlines()
    assert any("releases/download/v0.10.0/enlens_claims-0.10.0-py3-none-any.whl" in x for x in log)
    install = next(x for x in log if " tool install " in x)
    assert install.startswith("UV_PYTHON_PREFERENCE=only-managed tool install --force --quiet --python 3.12 "
                              "enlens-claims[connector,fast,pdfminer,ocr] @ file://")
    assert log[-1] == "enlens post-install --by script"  # ENLENS_NO_OPEN: not opened
    assert "Done." in r.stdout and "4/4" in r.stdout
    # a package that does not match the checksum is refused before anything is installed
    (Path(env["FAKE_DL"]) / "SHA256SUMS").write_text(f"{'0' * 64}  {wheel.name}\n")
    (tmp / "log").unlink()
    r = subprocess.run(["sh", str(script)], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "does not match the release's checksum" in r.stderr
    assert not any(" tool install " in x for x in (tmp / "log").read_text().splitlines())


def test_install_sh_with_a_local_package_and_options(sandbox):
    tmp, env = sandbox
    pkg = tmp / "enlens_claims-0.10.0-py3-none-any.whl"
    pkg.write_bytes(b"PK")
    env.update(ENLENS_WHEEL=str(pkg), ENLENS_HOME=str(tmp / "data"))
    env.pop("ENLENS_NO_OPEN")
    r = subprocess.run(["sh", str(ROOT / "install" / "install.sh")], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert (tmp / "log").read_text().splitlines()[-1] == f"enlens post-install --by script --home {tmp / 'data'} --open"
    # the raw script (no version filled in) needs a package or a version
    env.pop("ENLENS_WHEEL")
    r = subprocess.run(["sh", str(ROOT / "install" / "install.sh")], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "does not name a version" in r.stderr


def test_install_scripts_parse():
    if shutil.which("sh"):
        assert subprocess.run(["sh", "-n", str(ROOT / "install" / "install.sh")]).returncode == 0
    ps1 = (ROOT / "install" / "install.ps1").read_text()
    assert "@ENLENS_VERSION@" in ps1 and "connector,fast,pdfminer,ocr" in ps1
    assert "exit" not in [w.strip().lower() for w in ps1.split()]  # `irm | iex` runs in the person's own window
    assert ps1.count("{") == ps1.count("}") and ps1.count("(") == ps1.count(")")


# ---------------------------------------------------------------------------------------------
# the release helper
# ---------------------------------------------------------------------------------------------
def test_release_check_notes_and_assets(tmp_path):
    import release

    v = release.check()
    assert v == "0.10.0" and release.check("v0.10.0") == v
    with pytest.raises(release.ReleaseError, match="the tag is v0.9.9"):
        release.check("v0.9.9")
    notes = release.notes(v)
    assert "install.sh \\| sh" in notes and "## 0.10.0" not in notes and "## 0.9.1" not in notes
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / f"enlens_claims-{v}-py3-none-any.whl").write_bytes(b"PK")
    files = release.assets(dist)
    assert {p.name for p in files} == {f"enlens_claims-{v}-py3-none-any.whl", "install.sh", "install.ps1", "SHA256SUMS"}
    assert 'VERSION="${ENLENS_VERSION:-0.10.0}"' in (dist / "install.sh").read_text()
    assert "'0.10.0'" in (dist / "install.ps1").read_text()
    for line in (dist / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ")
        assert hashlib.sha256((dist / name).read_bytes()).hexdigest() == digest
    (dist / "enlens_claims-0.9.0-py3-none-any.whl").write_bytes(b"PK")
    with pytest.raises(release.ReleaseError, match="exactly"):
        release.assets(dist)


def test_release_workflow_builds_tries_and_drafts():
    wf = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    for needle in ('tags: ["v*"]', "python tools/release.py check", "python -m pytest -q", "tools/release.py assets dist",
                   "ubuntu-latest, macos-latest, windows-latest", "dist/install.sh", "install.ps1", "--draft",
                   "needs: [build, try-install]", "check_connector()"):
        assert needle in wf, needle


# ---------------------------------------------------------------------------------------------
# Set up Claude, from the app
# ---------------------------------------------------------------------------------------------
@pytest.fixture
def not_installed(tmp_path, monkeypatch):
    """Claude Code not on this computer yet; the stand-in installer puts it at ENLENS_CLAUDE; signed out."""
    monkeypatch.setenv("ENLENS_CLAUDE", str(tmp_path / "claude-code" / "claude.py"))
    monkeypatch.setenv("ENLENS_CLAUDE_INSTALLER", INSTALLER)
    monkeypatch.setenv("FAKE_CLAUDE_LOGGED_OUT", "1")
    from enlens_claims import claude_setup

    claude_setup._STATUS.update(at=0.0, value=None)
    opened = []

    def window(script):  # the "terminal window": the person signs in
        opened.append(script)
        subprocess.run([sys.executable, os.environ["ENLENS_CLAUDE"]], capture_output=True, timeout=30)
        return "Terminal"

    monkeypatch.setattr(claude_setup, "_open_window", window)
    return opened


def test_set_up_claude_installs_signs_in_and_adds_the_plugin(api, not_installed):  # noqa: F811
    st, info = api("GET", "/api/claude-setup?refresh=1")
    assert info["status"]["found"] is False and "claude.ai/install" in info["installer"] and info["docs"]
    assert api("POST", "/api/claude-setup/sign-in", {})[0] == 400  # nothing to sign in to yet
    st, r = api("POST", "/api/claude-setup/claude-code", {})
    assert st == 200 and r["job"]["kind"] == "claude-install"
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done" and job["result"]["ok"] and job["result"]["status"]["found"]
    assert job["result"]["status"]["signed_in"] is False
    assert api("POST", "/api/claude-setup/claude-code", {})[0] == 409  # already there
    st, r = api("POST", "/api/claude-setup/sign-in", {})
    assert st == 200 and r["opened"] and r["window"] == "Terminal" and len(not_installed) == 1
    script = not_installed[0].read_text()
    assert "sign in to Claude Code" in script
    st, info = api("GET", "/api/claude-setup?refresh=1")
    assert info["status"]["signed_in"] is True and info["status"]["installed"] is False
    # refresh=1 reads Claude Code again instead of the status of half a minute ago (0.9 ignored it)
    state = Path(os.environ["ENLENS_HOME"]) / "fake-claude.json"
    state.write_text(json.dumps({"logged_in": False}))
    assert api("GET", "/api/claude-setup")[1]["status"]["signed_in"] is True  # cached
    assert api("GET", "/api/claude-setup?refresh=1")[1]["status"]["signed_in"] is False
    state.write_text(json.dumps({"logged_in": True}))
    assert api("GET", "/api/claude-setup?refresh=1")[1]["status"]["signed_in"] is True
    st, r = api("POST", "/api/claude-setup", {})
    assert st == 200 and r["status"]["ready"] is True


def test_a_failed_install_says_so(api, not_installed, monkeypatch):  # noqa: F811
    monkeypatch.setenv("FAKE_INSTALLER_FAIL", "1")
    st, r = api("POST", "/api/claude-setup/claude-code", {})
    job = api.wait(r["job"]["id"])
    assert job["state"] == "error" and "could not be installed" in job["error"] and "Could not resolve host" in job["error"]


def test_set_up_claude_is_refused_when_local_only(api, not_installed, monkeypatch):  # noqa: F811
    monkeypatch.setenv("ENLENS_LOCAL_ONLY", "1")
    assert api("POST", "/api/claude-setup/claude-code", {})[0] == 403
    assert api("POST", "/api/claude-setup/sign-in", {})[0] == 400
    assert not_installed == []


def test_installer_command_per_system(monkeypatch):
    from enlens_claims import claude_setup

    monkeypatch.delenv("ENLENS_CLAUDE_INSTALLER", raising=False)
    mac = claude_setup.installer_command("mac")
    assert mac["line"] == "curl -fsSL https://claude.ai/install.sh | bash" and mac["args"][-1] == mac["line"]
    win = claude_setup.installer_command("windows")
    assert win["line"] == "irm https://claude.ai/install.ps1 | iex" and win["args"][0] == "powershell"


# ---------------------------------------------------------------------------------------------
# Move ENLENS to another computer
# ---------------------------------------------------------------------------------------------
def _project_with_a_document(api, name, corpus):  # noqa: F811
    st, r = api("POST", "/api/projects", {"name": name})
    assert st == 200, r
    st, r = api("POST", f"/api/projects/{name}/ingest", {"path": str(corpus)})
    assert api.wait(r["job"]["id"])["state"] == "done"


def test_move_everything_to_another_computer(api, home, corpus, tmp_path, monkeypatch):  # noqa: F811
    _project_with_a_document(api, "Alpha", corpus)
    _project_with_a_document(api, "Beta", corpus)
    home.remember_key("sk-ant-secret")
    api("PUT", "/api/settings", {"threshold": 0.7, "project": "Beta"})
    st, data = api("GET", "/api/move.zip")
    assert st == 200
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        meta = json.loads(zf.read("enlens-move.json"))
        assert all(b"sk-ant-secret" not in zf.read(n) for n in names if not n.endswith(".zip"))
    assert [p["name"] for p in meta["projects"]] == ["Alpha", "Beta"] and meta["current"] == "Beta"
    assert meta["settings"]["threshold"] == 0.7 and "project" not in meta["settings"]
    assert not any("credentials" in n for n in names)

    # a new computer: everything comes in, with the settings
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "new-computer"))
    st, r = api("POST", "/api/projects/import", raw=data, headers={"Content-Type": "application/zip"})
    assert st == 200, r
    assert [(p["from"], p["name"]) for p in r["moved"]["projects"]] == [("Alpha", "Alpha"), ("Beta", "Beta")]
    assert r["moved"]["settings"] is True and r["moved"]["current"] == "Beta" and r["project"]["documents"] == 3
    s = home.load_settings()
    assert s["threshold"] == 0.7 and s["project"] == "Beta" and home.stored_key() == ""
    st, state = api("GET", "/api/state")
    assert {p["name"] for p in state["projects"]} == {"Alpha", "Beta"}

    # a computer in use: the projects come in beside its own, its settings stay
    api("PUT", "/api/settings", {"threshold": 0.5})
    st, r = api("POST", "/api/projects/import", raw=data, headers={"Content-Type": "application/zip"})
    assert [p["name"] for p in r["moved"]["projects"]] == ["Alpha (2)", "Beta (2)"] and r["moved"]["settings"] is False
    assert home.load_settings()["threshold"] == 0.5 and home.load_settings()["project"] == "Beta"  # stays put


def test_a_single_project_zip_still_imports(api, corpus):  # noqa: F811
    _project_with_a_document(api, "Solo", corpus)
    st, data = api("GET", "/api/projects/Solo/export.zip")
    st, r = api("POST", "/api/projects/import?name=Copy", raw=data, headers={"Content-Type": "application/zip"})
    assert st == 200 and "moved" not in r and r["project"]["name"] == "Copy"


def test_moved_settings_respect_local_only(home, tmp_path, monkeypatch):  # noqa: F811
    from enlens_claims import bundle

    home.create_project("P")
    home.update_settings({"backend": "claude_code", "allow_claude_code": True, "themes_k": 12})
    out = tmp_path / "all.zip"
    bundle.export_all(out)
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "locked"))
    monkeypatch.setenv("ENLENS_LOCAL_ONLY", "1")
    r = bundle.import_all(out)
    s = home.load_settings()
    assert r["settings"] is True and s["themes_k"] == 12 and s["backend"] == "auto"  # nothing may leave this one
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("enlens-move.json", json.dumps({"format": "other"}))
    with pytest.raises(ValueError, match="not made with"):
        bundle.import_all(bad)


# ---------------------------------------------------------------------------------------------
# Tesseract
# ---------------------------------------------------------------------------------------------
def test_tesseract_is_found_where_installers_put_it(tmp_path, monkeypatch):
    from enlens_claims import ingest

    monkeypatch.setattr(ingest.shutil, "which", lambda name: None)
    monkeypatch.setattr(ingest, "TESSERACT_PLACES", [str(tmp_path / "opt" / "homebrew" / "bin" / "tesseract")])
    assert ingest.find_tesseract() == ""
    exe = tmp_path / "Programs" / "Tesseract-OCR" / "tesseract.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "Programs"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "nothing"))
    assert ingest.find_tesseract() == str(exe)


def test_the_app_says_how_to_get_tesseract(monkeypatch):
    from enlens_claims import ingest, installation

    monkeypatch.setattr(ingest, "find_tesseract", lambda: "")
    ingest._OCR_STATUS[:] = [0.0, None]
    st = ingest.ocr_status()
    ingest._OCR_STATUS[:] = [0.0, None]
    assert st["available"] is False and "tesseract" in st["missing"]
    assert st["install"] == ingest.TESSERACT_HELP[installation.system()]
    assert ingest.TESSERACT_HELP["mac"]["command"] == "brew install tesseract"
    assert "UB-Mannheim" in ingest.TESSERACT_HELP["windows"]["link"]


# ---------------------------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------------------------
def test_page_files_of_the_release():
    static = ROOT / "src" / "enlens_claims" / "gui" / "static"
    assert '<link rel="stylesheet" href="/static/v010.css">' in (static / "index.html").read_text()
    css = (static / "v010.css").read_text()
    import re

    defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", (static / "app.css").read_text()))
    used = set(re.findall(r"var\((--[a-z0-9-]+)", css))
    assert used and used <= defined, used - defined
    js = (static / "views" / "settings.js").read_text()
    for needle in ('"/api/claude-setup/claude-code"', '"/api/claude-setup/sign-in"', "Set up Claude", "Install Claude Code?"):
        assert needle in js
    assert "/api/move.zip" in (static / "views" / "projects.js").read_text()
    assert "Import from another computer" in (static / "views" / "setup.js").read_text()
    assert "ask IT to install Tesseract" not in (static / "views" / "sources.js").read_text()
    api_md = (ROOT / "docs" / "API.md").read_text()
    for route in ("/api/claude-setup/claude-code", "/api/claude-setup/sign-in", "/api/move.zip"):
        assert route in api_md, route
