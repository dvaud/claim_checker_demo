"""0.14.5: the install as files to double-click, in every GitHub Release beside the install line.

- Install-ENLENS-Windows.cmd: a short cmd part has PowerShell read the whole file, in which that part is one comment
  (`<# … #>`) and install.ps1 of the same release follows. So it is one file that downloads no other script, and the
  release's Windows machine tries it before the release exists. Plain ASCII with Windows line endings (cmd reads it
  in the console's code page);
- Install-ENLENS-macOS.zip: install.sh as "Install ENLENS.command", which Terminal runs on a double-click, in a zip
  that keeps its "may run" mark (a browser drops it from a bare download). Unzipped as Archive Utility does, it runs
  and installs (stand-ins for uv and curl, as in test_setup_and_moving.py; no network). Gatekeeper still asks
  once, since the file is not signed by an Apple developer: the release notes say how to allow it;
- SHA256SUMS lists both, the release notes link both files of that release, and the release workflow tries both;
- on Windows, where ENLENS cannot update itself, the update message names the file to double-click.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

# (0.18.1: the files of the release being made are named by the changelog's top entry, not by the running version)
from test_setup_and_moving import ROOT, RELEASE as VERSION, Runs, _releases, sandbox  # noqa: F401  (fixture)

import release  # tools/, put on the path by test_setup_and_moving

WIN, MAC, COMMAND = "Install-ENLENS-Windows.cmd", "Install-ENLENS-macOS.zip", "Install ENLENS.command"


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    d.mkdir()
    (d / f"enlens_claims-{VERSION}-py3-none-any.whl").write_bytes(b"PK")
    release.assets(d)
    return d


def test_the_release_has_both_files_with_their_checksums(dist):
    assert {p.name for p in dist.iterdir()} == {f"enlens_claims-{VERSION}-py3-none-any.whl", "install.sh",
                                                "install.ps1", WIN, MAC, "SHA256SUMS"}
    sums = dict(reversed(line.split("  ")) for line in (dist / "SHA256SUMS").read_text().splitlines())
    assert set(sums) == {p.name for p in dist.iterdir()} - {"SHA256SUMS"}
    for name, digest in sums.items():
        assert hashlib.sha256((dist / name).read_bytes()).hexdigest() == digest


def test_install_ps1_is_plain_ascii():
    data = (ROOT / "install" / "install.ps1").read_bytes()
    assert data.isascii(), [n for n, line in enumerate(data.splitlines(), 1) if not line.isascii()]


def test_the_windows_file_is_cmd_then_install_ps1(dist):
    data = (dist / WIN).read_bytes()
    assert data.isascii()
    assert b"\n" not in data.replace(b"\r\n", b"")  # Windows line endings throughout
    text = data.decode("ascii").replace("\r\n", "\n")
    # what PowerShell reads: one comment, then install.ps1 of this release, unchanged
    assert text.startswith("<# :") and text.count("#>") == 1
    head, ps1 = text.split("#>\n", 1)
    assert ps1 == (dist / "install.ps1").read_text()
    assert f"'{VERSION}'" in ps1 and "@ENLENS_VERSION@" not in text
    # what cmd runs: up to `exit /b`, which it never passes
    cmd = head.split("\n")
    end = cmd.index("exit /b %ENLENS_RC%")
    assert cmd[-1].startswith(":") and end == len(cmd) - 2  # the last line, a label, is never reached
    assert 'set "ENLENS_SELF=%~f0"' in cmd
    run = next(x for x in cmd if x.startswith("powershell "))
    assert "-NoProfile -ExecutionPolicy Bypass" in run
    assert run.endswith('-Command "Invoke-Expression ([IO.File]::ReadAllText($env:ENLENS_SELF))"')
    assert cmd.index(run) < cmd.index("pause >nul") < end  # the window stays open to read what happened
    assert not [x for x in cmd if x.lower().startswith("rem") and "%" in x]  # cmd expands % even in a rem line
    assert f"ENLENS {VERSION}:" in head


def test_the_windows_file_parses_in_powershell(dist):
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if not pwsh:
        pytest.skip("no PowerShell here (the release's Windows machine runs the file)")
    # the file's name goes in by the environment: words after -Command become part of the command, not $args
    script = ("$t = $null; $e = $null; "
              "$null = [System.Management.Automation.Language.Parser]::ParseFile($env:ENLENS_TEST_FILE, [ref]$t, [ref]$e); "
              "if ($e) { $e | ForEach-Object { $_.Message }; exit 1 }; "
              "Write-Output \"$($t[0].Kind) $($t[0].Text.EndsWith('#>'))\"")
    r = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True,
                       env={**os.environ, "ENLENS_TEST_FILE": str(dist / WIN)}, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.split() == ["Comment", "True"]  # the whole cmd part is one comment to PowerShell


@pytest.mark.parametrize("bad", ["#> early", "no start"])
def test_a_broken_windows_head_stops_the_release(tmp_path, bad):
    root = tmp_path / "root"
    shutil.copytree(ROOT / "install", root / "install")
    head = root / "install" / WIN
    text = head.read_text()
    head.write_text(text.replace("@echo off", "@echo off\nrem #> early") if bad == "#> early" else text[2:])
    d = tmp_path / "dist"
    d.mkdir()
    for name in ("install.sh", "install.ps1"):
        (d / name).write_text((ROOT / "install" / name).read_text())
    with pytest.raises(release.ReleaseError, match="#>"):
        release.double_click_files(d, VERSION, root)


def _unzip(zip_path: Path, into: Path) -> Path:
    """Unzip as a Mac does (Archive Utility and ditto keep the "may run" mark); elsewhere with unzip."""
    if sys.platform == "darwin" and shutil.which("ditto"):
        subprocess.run(["ditto", "-x", "-k", str(zip_path), str(into)], check=True)
    elif shutil.which("unzip"):
        subprocess.run(["unzip", "-q", str(zip_path), "-d", str(into)], check=True)
    else:
        pytest.skip("no ditto or unzip here")
    return into / COMMAND


def test_the_mac_zip_holds_install_sh_that_may_run(dist):
    with zipfile.ZipFile(dist / MAC) as z:
        [entry] = z.infolist()
        assert entry.filename == COMMAND and entry.create_system == 3
        assert entry.external_attr >> 16 == 0o100755
        assert z.read(entry) == (dist / "install.sh").read_bytes()
    assert f'VERSION="${{ENLENS_VERSION:-{VERSION}}}"' in (dist / "install.sh").read_text()


def test_the_unzipped_mac_file_runs_and_installs(dist, sandbox):  # noqa: F811
    tmp, env = sandbox
    command = _unzip(dist / MAC, tmp / "unzipped")
    assert command.stat().st_mode & 0o111
    wheel = Path(env["FAKE_DL"]) / f"enlens_claims-{VERSION}-py3-none-any.whl"
    wheel.write_bytes(b"PK the package")
    (Path(env["FAKE_DL"]) / "SHA256SUMS").write_text(f"{hashlib.sha256(wheel.read_bytes()).hexdigest()}  {wheel.name}\n")
    env.update(LANG="en_US.UTF-8", LC_ALL="en_US.UTF-8")  # what Terminal sets
    r = subprocess.run([str(command)], env=env, capture_output=True, text=True, timeout=60)  # as Terminal runs it
    assert r.returncode == 0, r.stderr + r.stdout
    assert "Done. Next time, open ENLENS from its icon." in r.stdout
    log = (tmp / "log").read_text().splitlines()
    assert any(x.endswith(f"releases/download/v{VERSION}/{wheel.name}") for x in log)
    assert log[-1] == "enlens post-install --by script"


def test_the_release_notes_link_both_files_of_that_release():
    notes = release.notes(VERSION)
    files = f"https://github.com/dvaud/claim_checker_demo/releases/download/v{VERSION}"
    assert f"[{WIN}]({files}/{WIN})" in notes and f"[{MAC}]({files}/{MAC})" in notes
    assert "*More info*, then *Run anyway*" in notes and "*Open Anyway*" in notes
    assert notes.index(WIN) < notes.index("\n\n---\n\n")  # with the install lines, above the changes


def test_the_release_workflow_tries_both():
    wf = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    win = wf.split("Install with Install-ENLENS-Windows.cmd", 1)[1].split("\n  try-install-mac:", 1)[0]
    assert "if: runner.os == 'Windows'" in win and "uv tool uninstall enlens-claims" in win
    assert 'cmd /d /c "dist\\Install-ENLENS-Windows.cmd < NUL"' in win and "Done\\. Next time" in win
    mac = wf.split("try-install-mac:", 1)[1].split("\n  release:", 1)[0]
    step = mac.split("Install with Install-ENLENS-macOS.zip", 1)[1]
    for needle in ("uv tool uninstall enlens-claims", "ditto -x -k dist/Install-ENLENS-macOS.zip",
                   'test -x "$CMD"', 'grep -q "Done. Next time"'):
        assert needle in step, needle
    assert "dist/*" in wf.split("\n  release:", 1)[1]  # every file goes into the release


def test_on_windows_the_update_message_names_the_file():
    from enlens_claims import installation, update

    with pytest.raises(update.UpdateError) as e:
        update.update_release(fetch=_releases(), run=Runs(), windows=True)
    msg = str(e.value)
    assert "quit ENLENS" in msg and "releases/latest/download/Install-ENLENS-Windows.cmd" in msg
    assert installation.install_line("windows") in msg
    assert installation.double_click_file("mac").endswith("/releases/latest/download/Install-ENLENS-macOS.zip")
    assert installation.double_click_file("linux") == ""
