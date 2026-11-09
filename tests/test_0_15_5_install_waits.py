"""0.15.5: the Windows install waits while a program runs from ENLENS's folder, instead of half-removing it.

On the user's PC the install line ran while Claude Code had ENLENS connected: its connector runs ENLENS's own
python.exe from uv's folder for ENLENS (...\\uv\\tools\\enlens-claims). uv replaces that whole folder; Windows would not
let the running program's files go, so uv removed what it could, stopped with "Access is denied (os error 5)", and every
enlens command then said "uv trampoline failed to canonicalize script path". install.ps1 now lists the programs running
from that folder before uv touches it, names them (Claude Code's connector, the ENLENS app), says what to close, waits
for them, and installs nothing when they stay.

PowerShell runs here only where it is installed (GitHub's Linux machine has pwsh; this Mac does not). The release's
Windows machine runs the whole line with a stand-in for the connector (release.yml, "Install while a program runs from
ENLENS's folder").
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PS1 = ROOT / "install" / "install.ps1"
FUNCS = ("Get-ProgramsIn", "Get-ProgramLabel", "Wait-FolderFree")


def _pwsh() -> str:
    found = shutil.which("pwsh") or shutil.which("powershell")
    if not found:
        pytest.skip("no PowerShell here (GitHub's Linux and Windows machines have it)")
    return found


def _ps(body: str, **env: str) -> subprocess.CompletedProcess:
    """Run `body` in PowerShell after loading the three functions from install.ps1 (nothing else of it runs)."""
    load = ("$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:T_PS1, [ref]$null, [ref]$null); "
            f"$want = {', '.join(repr(f) for f in FUNCS)}; "
            "$fns = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] "
            "-and $want -contains $n.Name }, $true); "
            "if (@($fns).Count -ne 3) { throw 'the three functions are not in install.ps1' }; "
            "foreach ($f in $fns) { Invoke-Expression $f.Extent.Text }; ")
    return subprocess.run([_pwsh(), "-NoProfile", "-NonInteractive", "-Command", load + body], capture_output=True,
                          text=True, errors="replace", env={**os.environ, "T_PS1": str(PS1), **env}, timeout=120)


@pytest.fixture
def program_in_folder(tmp_path):
    """A copy of `sleep` in a folder named as uv names ENLENS's; started, it runs from that folder."""
    if os.name == "nt":
        pytest.skip("the release's Windows machine runs ENLENS's own Python for this (release.yml)")
    sleep = shutil.which("sleep")
    if not sleep:
        pytest.skip("no sleep program here")
    folder = tmp_path / "uv" / "tools" / "enlens-claims"
    (folder / "bin").mkdir(parents=True)
    exe = folder / "bin" / "sleep"
    shutil.copy(sleep, exe)  # not copy2: macOS's own programs carry flags a copy may not take
    exe.chmod(0o755)
    if subprocess.run([str(exe), "0"]).returncode != 0:
        pytest.skip("a copied sleep does not run here (macOS stops copies of its own programs)")
    started = []

    def start(seconds: int) -> subprocess.Popen:
        p = subprocess.Popen([str(exe), str(seconds)])
        started.append(p)
        return p

    yield folder, start
    for p in started:
        p.kill()
        p.wait()


# ---------------------------------------------------------------------------------------------
# what install.ps1 does, read from the file
# ---------------------------------------------------------------------------------------------
def test_the_install_waits_for_the_folder_before_uv_replaces_it():
    ps1 = PS1.read_text()
    assert ps1.isascii()
    step3 = ps1.split("# 3. install", 1)[1].split("# 4. the icon", 1)[0]
    assert step3.index("Wait-FolderFree (Get-EnlensEnvFolders $uv) $wait") < step3.index("tool install --force")
    assert "$env:ENLENS_FREE_WAIT" in step3 and "$wait = 300" in step3
    assert "ENLENS_FREE_WAIT=300" in ps1.split("function Get-ProgramsIn", 1)[0]  # listed with the options


def test_the_folder_is_where_uv_keeps_enlens_read_as_utf8():
    ps1 = PS1.read_text()
    env = ps1.split("function Get-EnlensEnvFolders", 1)[1].split("\n        }\n", 1)[0]
    assert "Get-Utf8Output $Uv 'tool dir'" in env  # uv's answer as UTF-8: C:\Users\Dávid (0.15.2)
    assert "$env:UV_TOOL_DIR" in env and "Join-Path $env:APPDATA 'uv'" in env and "'enlens-claims'" in env


def test_programs_are_found_by_their_path_on_windows_by_cim_elsewhere_by_get_process():
    ps1 = PS1.read_text()
    found = ps1.split("function Get-ProgramsIn", 1)[1].split("function Get-ProgramLabel", 1)[0]
    assert "Get-CimInstance Win32_Process -ErrorAction Stop" in found and "$_.CommandLine" in found
    assert "Get-Process" in found and "$p.Id -eq $PID" in found  # never the PowerShell that runs the install
    assert "StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)" in found  # no wildcards: a [ in a path


def test_a_failed_uv_install_says_to_close_claude_code():
    ps1 = PS1.read_text()
    fail = ps1.split("tool install --force", 1)[1].split("$enlens = Find-EnlensExe", 1)[0]
    assert "access is denied" in fail and "close Claude Code" in fail and "run the line again" in fail
    assert "repairs an ENLENS that no longer starts" in fail


def test_the_windows_update_message_says_to_close_claude_code():
    from test_0100_setup_and_moving import Runs, _releases

    from enlens_claims import update

    with pytest.raises(update.UpdateError) as e:
        update.update_release(fetch=_releases(), run=Runs(), windows=True)
    assert "quit ENLENS (Quit ENLENS in the app) and close Claude Code" in str(e.value)


def test_the_release_tries_the_line_while_a_connector_runs():
    wf = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    step = wf.split("- name: Install while a program runs from ENLENS's folder", 1)[1].split("\n      - name:", 1)[0]
    assert "if: runner.os == 'Windows'" in step
    assert "enlens-claims\\Scripts\\python.exe" in step and "enlens_claims.mcp_server" in step
    assert "powershell -NoProfile -ExecutionPolicy Bypass -File dist\\install.ps1" in step  # Windows PowerShell 5.1
    for needle in ("They have closed", "4/4", "$env:ENLENS_FREE_WAIT = '8'", "Nothing was changed", "-match '3/4'",
                   "ENLENS no longer starts", "Lib\\site-packages\\enlens_claims", "the line did not repair ENLENS"):
        assert needle in step, needle


# ---------------------------------------------------------------------------------------------
# the functions themselves, in PowerShell
# ---------------------------------------------------------------------------------------------
def test_labels_name_the_connector_and_the_app():
    r = _ps("$c = [pscustomobject]@{ Id = 7; Name = 'python.exe'; Line = 'C:\\x\\python.exe -m enlens_claims.mcp_server' }; "
            "$a = [pscustomobject]@{ Id = 8; Name = 'pythonw.exe'; Line = 'pythonw.exe -m enlens_claims.gui.launch --launcher' }; "
            "$o = [pscustomobject]@{ Id = 9; Name = 'enlens.exe'; Line = '' }; "
            "Get-ProgramLabel $c; Get-ProgramLabel $a; Get-ProgramLabel $o")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.splitlines()[-3:] == ["Claude Code's ENLENS connector (python.exe, process 7)",
                                          "the ENLENS app (pythonw.exe, process 8)", "enlens.exe, process 9"]


def test_a_program_running_from_the_folder_is_found(program_in_folder, tmp_path):
    folder, start = program_in_folder
    p = start(60)
    r = _ps("@(Get-ProgramsIn @($env:T_DIR, $env:T_OTHER)) | ForEach-Object { 'found ' + $_.Id }; "
            "@(Get-ProgramsIn @($env:T_OTHER)).Count",
            T_DIR=str(folder), T_OTHER=str(tmp_path / "elsewhere"))
    assert r.returncode == 0, r.stdout + r.stderr
    lines = r.stdout.splitlines()
    assert f"found {p.pid}" in lines and lines[-1] == "0"
    assert sum(line.startswith("found ") for line in lines) == 1  # not the PowerShell asking, nor anything else


def test_the_wait_ends_when_the_program_closes(program_in_folder):
    folder, start = program_in_folder
    p = start(4)
    r = _ps("Wait-FolderFree @($env:T_DIR) 60; 'went on'", T_DIR=str(folder))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ENLENS cannot be replaced while these programs run from its folder" in r.stdout
    assert f"sleep, process {p.pid}" in r.stdout and f"Stop-Process -Id {p.pid}" in r.stdout
    assert "close Claude Code" in r.stdout and "Nothing has" in r.stdout
    assert r.stdout.index("They have closed.") < r.stdout.index("went on")


def test_a_program_that_stays_stops_the_install_with_what_to_do(program_in_folder):
    folder, start = program_in_folder
    p = start(120)
    r = _ps("try { Wait-FolderFree @($env:T_DIR) 3; 'went on' } catch { 'stopped: ' + $_.Exception.Message }",
            T_DIR=str(folder))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "went on" not in r.stdout
    stop = r.stdout.split("stopped: ", 1)[1]
    assert stop.startswith(f"these programs still run from ENLENS's folder: sleep, process {p.pid}. Nothing was changed.")
    assert "close Claude Code" in stop and f"Stop-Process -Id {p.pid}" in stop and "run the line again" in stop
    assert p.poll() is None  # the install never ends a program itself


def test_a_free_folder_says_nothing(tmp_path):
    r = _ps("Wait-FolderFree @($env:T_DIR) 60; 'went on'", T_DIR=str(tmp_path / "uv" / "tools" / "enlens-claims"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == "went on"
