"""0.15.2: ENLENS installs and makes its icons for a Windows user whose folder has accents (C:\\Users\\Dávid).

- install.ps1 stopped at "ENLENS was installed, but C:\\Users\\D├ívid\\.local\\bin\\enlens.exe is missing": uv writes
  its folder in UTF-8 and PowerShell read it in the console's code page. It now reads uv's answer as UTF-8 bytes and
  also looks in the folders uv itself would choose;
- the Desktop folder came from PowerShell's output read in Python's code page ("á" became a no-break space), so the
  icon went to a folder that does not exist: it now comes from Windows' Known Folder API;
- what PowerShell, Claude Code, tasklist or git write back can no longer stop ENLENS with a decoding error, and the
  `enlens` command no longer stops when it prints a letter the computer's code page lacks ("ő") to a pipe;
- the release's Windows machine installs for a user folder "Ábel Gergő", with its Desktop moved there, every release.
PowerShell runs here only where it is installed (GitHub's Linux machine has pwsh; this Mac does not).
"""
from __future__ import annotations

import base64
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from test_app import home  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parent.parent
PS1 = ROOT / "install" / "install.ps1"
USER = "Ábel Gergő"  # "Á" is C3 81 in UTF-8 (0x81 is no letter in Windows-1252); "ő" is not in Windows-1252 at all


def _pwsh() -> str:
    found = shutil.which("pwsh") or shutil.which("powershell")
    if not found:
        pytest.skip("no PowerShell here (GitHub's Linux and Windows machines have it)")
    return found


def _ps(script: str, **env: str) -> str:
    """Run a PowerShell script; what it prints is base64 of UTF-8, which no code page can garble."""
    r = subprocess.run([_pwsh(), "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                       text=True, errors="replace", env={**os.environ, **env}, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    lines = r.stdout.strip().splitlines()
    return base64.b64decode(lines[-1]).decode("utf-8") if lines else ""


B64 = "[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string]({})))"


# ---------------------------------------------------------------------------------------------
# install.ps1: where uv put enlens.exe
# ---------------------------------------------------------------------------------------------
def test_install_ps1_reads_uvs_folder_as_utf8_and_knows_uvs_own_folders():
    ps1 = PS1.read_text()
    assert ps1.isascii()
    assert "(& $uv tool dir --bin)" not in ps1  # read in the console's code page: the 0.15.1 failure
    assert "StandardOutputEncoding = New-Object System.Text.UTF8Encoding $false" in ps1
    assert "Get-Utf8Output $Uv 'tool dir --bin'" in ps1
    for where in ("$env:UV_TOOL_BIN_DIR", "$env:XDG_BIN_HOME", "$env:XDG_DATA_HOME", "Join-Path $env:USERPROFILE '.local'"):
        assert where in ps1, where
    assert "$enlens = Find-EnlensExe $uv" in ps1 and "Test-Path -LiteralPath $exe" in ps1
    assert "enlens.exe is in none of these folders" in ps1


FIND = ("$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:T_PS1, [ref]$null, [ref]$null); "
        "$want = 'Get-Utf8Output', 'Get-EnlensBinFolders', 'Find-EnlensExe'; "
        "$fns = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] "
        "-and $want -contains $n.Name }, $true); "
        "if (@($fns).Count -ne 3) { throw 'the three functions are not in install.ps1' }; "
        "foreach ($f in $fns) { Invoke-Expression $f.Extent.Text }; "
        "$r = Find-EnlensExe $env:T_UV; " + B64.format("$r"))


@pytest.fixture
def fake_uv(tmp_path):
    """A stand-in for uv whose `tool dir --bin` writes T_ANSWER as UTF-8 bytes (or fails when it is empty)."""
    if os.name == "nt":
        pytest.skip("the stand-in is a script with a #! line (the release's Windows machine runs the real uv)")
    uv = tmp_path / "fake-uv"
    uv.write_text(f"#!{sys.executable}\nimport os, sys\n"
                  "answer = os.environ.get('T_ANSWER', '')\n"
                  "if not answer: sys.exit(2)\n"
                  "sys.stdout.buffer.write(answer.encode('utf-8') + b'\\n')\n", encoding="utf-8")
    uv.chmod(0o755)
    return uv


def _env(tmp_path, uv, answer: str, profile: Path) -> dict:
    env = {"T_PS1": str(PS1), "T_UV": str(uv), "T_ANSWER": answer, "USERPROFILE": str(profile)}
    for name in ("UV_TOOL_BIN_DIR", "XDG_BIN_HOME", "XDG_DATA_HOME"):
        env[name] = ""
    return env


def test_enlens_exe_is_found_where_uv_says_with_an_accented_folder(tmp_path, fake_uv):
    bin_ = tmp_path / USER / "tools-bin"
    bin_.mkdir(parents=True)
    (bin_ / "enlens.exe").write_bytes(b"MZ")
    got = _ps(FIND, **_env(tmp_path, fake_uv, str(bin_), tmp_path / "nobody"))
    assert got == str(bin_ / "enlens.exe")


def test_a_garbled_answer_falls_back_to_the_folder_uv_uses(tmp_path, fake_uv):
    profile = tmp_path / USER
    bin_ = profile / ".local" / "bin"
    bin_.mkdir(parents=True)
    (bin_ / "enlens.exe").write_bytes(b"MZ")
    garbled = str(bin_).replace("Á", "├ü").replace("ő", "┼æ")  # the answer as 0.15.1 read it
    assert _ps(FIND, **_env(tmp_path, fake_uv, garbled, profile)) == str(bin_ / "enlens.exe")
    # uv that cannot answer at all
    assert _ps(FIND, **_env(tmp_path, fake_uv, "", profile)) == str(bin_ / "enlens.exe")


def test_no_enlens_exe_anywhere_is_reported_not_guessed(tmp_path, fake_uv):
    profile = tmp_path / USER
    profile.mkdir()
    assert _ps(FIND, **_env(tmp_path, fake_uv, str(tmp_path / "empty"), profile)) == ""


# ---------------------------------------------------------------------------------------------
# the icons: the Desktop folder and the PowerShell that makes the shortcuts
# ---------------------------------------------------------------------------------------------
class AsWindows:  # a module's `os`, answering "nt"
    name = "nt"

    def __getattr__(self, attr):
        return getattr(os, attr)


def test_the_windows_desktop_comes_from_windows_not_from_powershells_output(monkeypatch, tmp_path):
    from enlens_claims.gui import launcher

    def no_programs(cmd, *a, **kw):
        raise AssertionError(f"ran {cmd[0]}")

    monkeypatch.setattr(launcher, "os", AsWindows())
    monkeypatch.setattr(launcher.subprocess, "run", no_programs)
    desk = tmp_path / USER / "OneDrive" / "Asztal"
    monkeypatch.setattr(launcher, "_windows_desktop", lambda: desk)
    assert launcher._desktop() == desk


@pytest.mark.skipif(os.name != "nt", reason="Windows' Known Folder API")
def test_the_known_folder_is_the_desktop_powershell_names():
    from enlens_claims.gui import launcher

    found = launcher._windows_desktop()
    assert found and found == launcher._desktop()
    assert str(found) == _ps(B64.format("[Environment]::GetFolderPath('Desktop')"))


def test_the_shell_interface_is_only_for_windows(tmp_path):
    from enlens_claims.gui import launcher

    if os.name == "nt":
        pytest.skip("on Windows it writes a real shortcut (the next test)")
    assert launcher._com_shortcut(tmp_path / "ENLENS.lnk", sys.executable, "", str(tmp_path), "x", "") is False


@pytest.mark.skipif(os.name != "nt", reason="Windows' shortcuts")
def test_a_shortcut_in_an_accented_folder_points_at_its_program(tmp_path, home):  # noqa: F811
    """WScript.Shell cannot store "ő" on an English Windows; the Shell's IShellLinkW can, and Shell.Application (which
    is Unicode too) reads the target back as it was given."""
    from enlens_claims.gui import launcher

    scripts = tmp_path / USER / "uv" / "tools" / "enlens-claims" / "Scripts"
    scripts.mkdir(parents=True)
    pyw = scripts / "pythonw.exe"
    shutil.copy(Path(sys.executable).with_name("pythonw.exe"), pyw)
    folder = tmp_path / USER / "Desktop"
    folder.mkdir()
    made = launcher._windows_shortcut(folder, str(scripts / "python.exe"), ["-m", "enlens_claims.gui.launch", "--launcher"])
    assert made == folder / "ENLENS.lnk" and made.is_file()
    read = ("$f = (New-Object -ComObject Shell.Application).Namespace($env:T_DIR); "
            "$l = $f.ParseName('ENLENS.lnk').GetLink; " + B64.format("$l.Path + '|' + $l.Arguments"))
    assert _ps(read, T_DIR=str(folder)) == f"{pyw}|-m enlens_claims.gui.launch --launcher"


def test_powershell_quotes_hold_any_path():
    from enlens_claims.gui.launcher import _ps_quote

    assert _ps_quote("C:\\Users\\Kovács") == "'C:\\Users\\Kovács'"
    assert _ps_quote("O'Brien") == "'O''Brien'"
    assert _ps_quote("O\u2019Brien") == "'O\u2019\u2019Brien'"  # PowerShell ends a string at a typographic quote too


def test_a_quoted_path_comes_back_from_powershell_unchanged():
    from enlens_claims.gui.launcher import _ps_quote

    path = f"C:\\Users\\{USER} O'Brien O\u2018Neil O\u2019Hara\\Desktop\\ENLENS.lnk"
    assert _ps(B64.format(_ps_quote(path))) == path


def test_powershell_writing_bytes_this_python_cannot_read_does_not_stop_the_icon(tmp_path, monkeypatch, home):  # noqa: F811
    """PowerShell writes its messages in the console's code page; a byte this Python's code page has no letter for
    raised UnicodeDecodeError out of make_launcher, which the installer does not catch."""
    from enlens_claims.gui import launcher

    if os.name == "nt":
        pytest.skip("the stand-in powershell is a script with a #! line")
    tools = tmp_path / "tools"
    tools.mkdir()
    ps = tools / "powershell"
    ps.write_text(f"#!{sys.executable}\nimport sys\nsys.stderr.buffer.write(b'Hiba: \\x81\\xff\\xfe\\n')\nsys.exit(1)\n")
    ps.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tools}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setattr(launcher, "_com_shortcut", lambda *a: False)
    folder = tmp_path / USER / "Desktop"
    folder.mkdir(parents=True)
    made = launcher._windows_shortcut(folder, str(tmp_path / USER / "Scripts" / "python.exe"), ["--launcher"])
    assert made == folder / "ENLENS.cmd" and made.is_file()  # PowerShell failed: the command file instead


def test_the_sign_in_window_gets_the_whole_path_of_its_script(monkeypatch, tmp_path):
    """Windows PowerShell's Start-Process joins -ArgumentList with spaces and quotes nothing: the script's path is
    quoted inside its argument, or C:\\Users\\Ábel Gergő\\... is cut at the space."""
    from enlens_claims import claude_setup

    class AsWindowsSys:
        platform = "win32"

        def __getattr__(self, attr):
            return getattr(sys, attr)

    started = []
    monkeypatch.setattr(claude_setup, "os", AsWindows())
    monkeypatch.setattr(claude_setup, "sys", AsWindowsSys())
    monkeypatch.setattr(claude_setup.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))
    script = f"C:\\Users\\{USER} O\u2019Brien\\enlens\\claude-runs\\sign-in.ps1"
    assert claude_setup._open_window(Path(script) if os.name == "nt" else script) == "PowerShell"
    command = started[0][-1]
    assert command.endswith(f"'-File','\"C:\\Users\\{USER} O\u2019\u2019Brien\\enlens\\claude-runs\\sign-in.ps1\"'")


def test_the_line_to_type_keeps_a_typographic_apostrophe():
    from enlens_claims import claude_setup

    line = claude_setup.sign_in_line(Path("C:/Users/O\u2019Brien/sign-in"), windows=True)
    assert line.startswith("cd 'C:") and "O\u2019\u2019Brien" in line and line.endswith("'; claude")


# ---------------------------------------------------------------------------------------------
# what other programs write back, and what `enlens` prints
# ---------------------------------------------------------------------------------------------
def test_claude_codes_answer_is_read_as_utf8(tmp_path, home):  # noqa: F811
    from enlens_claims import claude_setup

    said = f"C:\\Users\\{USER}\\.claude\\plugins"
    stand_in = tmp_path / "claude.py"
    stand_in.write_text("import sys\nsys.stdout.buffer.write(" + repr(said.encode("utf-8") + b"\xff") + ")\n",
                        encoding="utf-8")
    code, text = claude_setup._run([str(stand_in), "plugin", "list"])
    assert code == 0 and text.startswith(said)  # and the stray byte did not stop it


def test_enlens_prints_a_letter_its_code_page_lacks(monkeypatch):
    from enlens_claims import installation

    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", out)
    installation.printable_streams()
    print(f"Start it from its icon: C:\\Users\\{USER}\\Desktop\\ENLENS.lnk")
    out.flush()
    assert b"\\u0151" in raw.getvalue() and "Ábel".encode("cp1252") in raw.getvalue()


def test_enlens_leaves_a_utf8_stream_as_it_is(monkeypatch):
    from enlens_claims import installation

    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    monkeypatch.setattr(sys, "stdout", out)
    installation.printable_streams()
    assert out.errors == "strict"


# ---------------------------------------------------------------------------------------------
# the release's Windows machine
# ---------------------------------------------------------------------------------------------
def test_the_release_installs_for_an_accented_user_folder():
    wf = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    step = wf.split("- name: Install with Install-ENLENS-Windows.cmd for a user folder with accents and a space", 1)[1]
    step = step.split("\n  try-install-mac:", 1)[0]
    assert "if: runner.os == 'Windows'" in step
    assert '"$([char]0xC1)bel Gerg$([char]0x151)"' in step  # "Ábel Gergő", written in ASCII
    for name in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP"):
        assert f"$env:{name} = " in step, name
    assert "User Shell Folders" in step and "-Name Desktop" in step  # the Desktop moved into it as well
    assert 'Copy-Item "$uvHere\\uv*.exe" $userBin' in step  # uv in the user folder, as its installer puts it
    assert "Copy-Item dist\\Install-ENLENS-Windows.cmd $downloads" in step  # the file run from the user's Downloads
    assert 'cmd /d /c "chcp 852 >nul & `"$downloads\\Install-ENLENS-Windows.cmd`" < NUL"' in step  # Hungarian console
    assert "uv is here already" in step and "::warning::" in step
    assert "Shell.Application" in step and "GetLink.Path" in step  # read in UTF-16, as WScript.Shell cannot
    assert "could not be installed" in step and "ENLENS.lnk" in step and "Start Menu\\Programs" in step
    # this step's own reading of uv comes after the install, so it cannot hide the install's problem
    assert step.index("Install-ENLENS-Windows.cmd`\" < NUL") < step.index("[Console]::OutputEncoding")
