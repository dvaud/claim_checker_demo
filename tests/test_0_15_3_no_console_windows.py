"""0.15.3: on Windows, the programs ENLENS starts open no console window.

The app runs without a console on Windows (its icon starts pythonw.exe), and a console program started from such a
process gets a console window of its own, which takes the focus and closes again. The app's check of Claude Code ran
`claude` three times every half minute while a task queue was open; Tesseract did so for every scanned page, git and
uv for every update, and `ollama serve` kept one open. Every program the package starts now goes through
procs.no_window() (CREATE_NO_WINDOW), or says on its line why it needs none (`# console: ...`).
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from test_app import home  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "enlens_claims"
STARTERS = {"run", "Popen", "call", "check_call", "check_output"}


class AsWindows:
    """The os module, with Windows' name."""
    name = "nt"

    def __getattr__(self, attr):
        return getattr(os, attr)


def _starts(tree: ast.AST):
    """Every call that starts a program: subprocess.run/Popen/call/check_*, os.system/popen, asyncio's subprocesses."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            mod, attr = node.func.value.id, node.func.attr
            if (mod == "subprocess" and attr in STARTERS) or (mod == "os" and attr in ("system", "popen")) or (
                    mod == "asyncio" and attr.startswith("create_subprocess")):
                yield node


def _hides_window(node: ast.Call, lines: list[str]) -> bool:
    for kw in node.keywords:
        if kw.arg == "creationflags":
            return True
        if kw.arg is None and ast.unparse(kw.value) in ("no_window()", "_PS_TEXT"):
            return True
    # a reason on the call's lines, or on the line above it, why no window is to be hidden
    return any("# console:" in lines[i - 1] for i in range(node.lineno - 1, (node.end_lineno or node.lineno) + 1))


def test_every_program_the_package_starts_hides_its_window():
    missing = []
    for path in sorted(PACKAGE.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        for node in _starts(ast.parse(source)):
            if not _hides_window(node, lines):
                missing.append(f"{path.relative_to(ROOT)}:{node.lineno}: {lines[node.lineno - 1].strip()}")
    assert not missing, ("These start a program that may get a console window of its own on Windows: add "
                         "**no_window() (enlens_claims.procs), or say why it needs none with '# console: ...':\n"
                         + "\n".join(missing))


def test_powershell_for_the_icons_runs_without_a_window():
    tree = ast.parse((PACKAGE / "gui" / "launcher.py").read_text(encoding="utf-8"))
    value = next(n.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "_PS_TEXT" for t in n.targets))
    assert "no_window()" in ast.unparse(value)


def test_no_window_is_create_no_window_on_windows_only(monkeypatch):
    from enlens_claims import procs

    if os.name == "nt":
        assert procs.no_window() == {"creationflags": subprocess.CREATE_NO_WINDOW}
        assert procs.CREATE_NO_WINDOW == subprocess.CREATE_NO_WINDOW
        return
    assert procs.no_window() == {}  # anywhere else Python refuses creationflags
    monkeypatch.setattr(procs, "os", AsWindows())
    assert procs.no_window() == {"creationflags": 0x08000000}


def test_the_claude_code_status_runs_claude_without_a_window(monkeypatch, home):  # noqa: F811
    """The flashing windows the person saw: `claude --version`, `auth status` and `plugin list`, every half minute."""
    from enlens_claims import claude_setup, procs

    monkeypatch.setattr(procs, "os", AsWindows())
    monkeypatch.setattr(claude_setup, "find_claude", lambda: "/no/claude")
    monkeypatch.setattr(claude_setup, "_STATUS", {"at": 0.0, "value": None})
    seen = []

    def claude(cmd, **kw):
        seen.append((cmd[1:], kw))
        return subprocess.CompletedProcess(cmd, 0, "{}", "")

    monkeypatch.setattr(subprocess, "run", claude)
    claude_setup.status(refresh=True)
    assert [c for c, _ in seen] == [["--version"], ["auth", "status"], ["plugin", "list", "--json"]]
    assert all(kw.get("creationflags") == procs.CREATE_NO_WINDOW for _, kw in seen)


def test_updates_run_git_and_uv_without_a_window(monkeypatch, tmp_path):
    from enlens_claims import procs, update

    monkeypatch.setattr(procs, "os", AsWindows())
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen.append(kw) or subprocess.CompletedProcess(cmd, 0))
    update._run(["git", "fetch"], tmp_path)
    update._run(["uv", "tool", "install"], tmp_path)
    assert [kw.get("creationflags") for kw in seen] == [procs.CREATE_NO_WINDOW] * 2


PROBE = "import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())"
PARENT = ("import subprocess, sys\n"
          "from enlens_claims.procs import no_window\n"
          f"probe = [sys.executable, '-c', {PROBE!r}]\n"
          "plain = subprocess.run(probe, capture_output=True, text=True).stdout.strip()\n"
          "hidden = subprocess.run(probe, capture_output=True, text=True, **no_window()).stdout.strip()\n"
          "print(plain, hidden)\n")


@pytest.mark.skipif(os.name != "nt", reason="Windows' console windows")
def test_a_program_started_without_a_console_gets_no_window_of_its_own():
    """As in the app: a parent without a console (DETACHED_PROCESS, like pythonw) starts a console program and reads
    what it writes. Without no_window() Windows gives that program a window (this test flashes one); with it, none."""
    r = subprocess.run([sys.executable, "-c", PARENT], capture_output=True, text=True, timeout=120,
                       creationflags=0x00000008, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr
    plain, hidden = r.stdout.split()
    if plain == "0":
        pytest.skip("this Windows gives the program no console window even without the flag")
    assert hidden == "0"
