"""Claude Code started by ENLENS works in a box of its own.

It needs nothing from the computer but the passages in its tasks, which reach it through the ENLENS connector.
- With a Claude Code that knows the options (read from `claude --help`), a run gets `--tools Agent` (no built-in tool
  that reads, writes or searches files, runs commands or browses exists in it), `--restricted` (the person's own
  Claude Code settings, hooks and CLAUDE.md files are not read) and `--plugin-dir` (ENLENS's plugin alone), and
  ENABLE_CLAUDEAI_MCP_SERVERS=false (the person's claude.ai connectors stay out). An older Claude Code runs as before:
  denied the tools in DENIED_TOOLS.
- The sign-in window ("Set up Claude") starts Claude Code in an empty folder of ENLENS's own
  (`<data folder>/claude-runs/sign-in`), without those tools, instead of in the home folder, where Claude Code could
  read every file of the person without asking; the line shown when no window opens goes there first.
Tests never touch a real Claude Code (the stand-in tests/fake_claude_cli.py).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

from test_app import Api, api, home  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parent.parent
FAKE = str(Path(__file__).with_name("fake_claude_cli.py"))
ALL = {"--allowedTools", "--disallowedTools", "--tools", "--restricted", "--plugin-dir"}


class _AsWindows:  # claude_setup's `os`, answering "nt"
    name = "nt"

    def __getattr__(self, attr):
        return getattr(os, attr)


@pytest.fixture
def cs(home, monkeypatch):  # noqa: F811
    from enlens_claims import claude_setup

    monkeypatch.setattr(claude_setup, "_OPTIONS", {})
    return claude_setup


# -- the box --------------------------------------------------------------------------------------------------
def test_the_options_are_read_from_claude_codes_help_once(cs, monkeypatch):
    calls = []
    real = cs._run
    monkeypatch.setattr(cs, "_run", lambda args, timeout=60: calls.append(args) or real(args, timeout))
    assert cs.known_options(FAKE) == ALL
    assert cs.known_options(FAKE) == ALL and len(calls) == 1   # read once for this program file
    assert cs.known_options("/no/such/claude") == set()
    monkeypatch.setattr(cs, "_OPTIONS", {})
    monkeypatch.setenv("FAKE_CLAUDE_OPTIONS", "none")  # 0.15.7: not "": Windows drops a variable set to nothing
    assert cs.known_options(FAKE) == set()                      # an older Claude Code


def test_a_run_has_no_file_tools_and_none_of_the_persons_own_claude_code(cs):
    cs.write_plugin()
    args = cs.run_args("P", "/usr/bin/claude", options=ALL)
    assert args[args.index("--tools") + 1] == "Agent"            # the only built-in tool: starting the helpers
    assert "--restricted" in args and args[args.index("--plugin-dir") + 1] == str(cs.plugin_folder())
    assert "--disallowedTools" not in args
    tools = args[args.index("--allowedTools") + 1:]
    assert tools[0] == "Agent" and {t.rsplit("__", 1)[1] for t in tools[1:]} == set(cs.QUEUE_TOOLS)
    assert args[2] == '/enlens-run:enlens-run "P"'               # the slash command and the plan are where they were


def test_an_older_claude_code_runs_as_before(cs):
    cs.write_plugin()
    args = cs.run_args("P", "/usr/bin/claude", options=set())
    assert set(args[args.index("--disallowedTools") + 1].split(",")) == set(cs.DENIED_TOOLS)
    assert "--tools" not in args and "--restricted" not in args and "--plugin-dir" not in args
    # one that knows --tools but not --restricted: no file tools, its own plugins as before
    args = cs.run_args("P", "/usr/bin/claude", options={"--tools", "--allowedTools"})
    assert args[args.index("--tools") + 1] == "Agent" and "--restricted" not in args


def test_restricted_only_with_the_plugin_written(cs):
    # --restricted ignores the person's settings, where the installed plugin is switched on: without ENLENS's own
    # plugin folder to load instead, the run would have no queue tools
    assert not (cs.plugin_folder() / ".mcp.json").exists()
    assert "--restricted" not in cs.box_args("/usr/bin/claude", options=ALL)


def test_start_run_closes_claude_code_in(cs, monkeypatch):
    seen = {}

    class P:
        pid = None

        def __init__(self, args, cwd=None, env=None, **kw):
            seen.update(args=args, cwd=cwd, env=env)

        def poll(self):
            return 0

    monkeypatch.setenv("ENLENS_CLAUDE", FAKE)
    cs.write_plugin()
    assert cs.known_options(FAKE) == ALL   # read now: the Popen below stands in for the run only
    monkeypatch.setattr(cs.subprocess, "Popen", P)
    monkeypatch.setattr(cs, "setup_info", lambda: {"ready": True})
    monkeypatch.setattr(cs, "status", lambda refresh=False: {"installed": True})
    cs.start_run("P")
    a = seen["args"]
    assert a[a.index("--tools") + 1] == "Agent" and "--restricted" in a and "--plugin-dir" in a
    assert seen["env"]["ENABLE_CLAUDEAI_MCP_SERVERS"] == "false"
    assert seen["env"].get("PATH") == os.environ.get("PATH")   # the rest of the environment is kept
    assert Path(seen["cwd"]).parent == cs.core.home() / "claude-runs" / "work" and not any(Path(seen["cwd"]).iterdir())


# -- the sign-in window -----------------------------------------------------------------------------------------
def test_the_sign_in_folder_is_emptied_but_kept(cs):
    d = cs.sign_in_folder()
    assert d == cs.core.home() / "claude-runs" / "sign-in" and d.is_dir() and not any(d.iterdir())
    assert d.resolve() != Path.home().resolve()
    (d / "notes.txt").write_text("left behind")
    (d / "sub").mkdir()
    (d / "sub" / "deep.txt").write_text("x")
    before = d.stat().st_ino
    assert cs.sign_in_folder() == d and not any(d.iterdir())
    assert d.stat().st_ino == before  # the same folder: a sign-in window still open keeps working in it


@pytest.mark.skipif(os.name == "nt", reason="runs the macOS/Linux script with /bin/sh")
@pytest.mark.parametrize("options", [ALL, set()], ids=["box", "older-claude-code"])
def test_the_sign_in_script_starts_claude_code_in_the_empty_folder_without_file_tools(cs, tmp_path, options):
    seen = tmp_path / "seen.json"
    fake = tmp_path / "fake claude.py"   # a .py stand-in runs with this Python (claude_setup._cmd)
    fake.write_text("import json, os, sys\n"
                    f"open({str(seen)!r}, 'w').write(json.dumps({{'cwd': os.getcwd(), 'argv': sys.argv[1:]}}))\n")
    script = cs._sign_in_script(str(fake), options=options)
    assert f"cd {Path.home()}\n" not in script.read_text()
    subprocess.run(["/bin/sh", str(script)], check=True, capture_output=True, timeout=30, cwd=str(tmp_path))
    got = json.loads(seen.read_text())
    assert Path(got["cwd"]).resolve() == cs.sign_in_folder().resolve()
    argv = got["argv"]
    assert "--restricted" not in argv and "--plugin-dir" not in argv   # the sign-in needs no plugin
    if options:
        assert argv == ["--tools", "Agent"]
    else:
        denied = set(argv[argv.index("--disallowedTools") + 1].split(","))
        assert {"Read", "Grep", "Glob", "Bash", "Write", "Edit", "WebFetch"} <= denied


def test_the_windows_sign_in_script_goes_to_the_empty_folder_first(cs, monkeypatch):
    monkeypatch.setattr(cs, "os", _AsWindows())
    monkeypatch.setenv("ENLENS_HOME", str(Path(os.environ["ENLENS_HOME"]).parent / "O'Brien home"))
    exe = r"C:\Users\Kovács\.local\bin\claude.exe"
    text = cs._sign_in_script(exe, options=ALL).read_text(encoding="utf-8-sig")
    folder = str(cs.sign_in_folder()).replace("'", "''")
    lines = text.splitlines()
    go = next(i for i, x in enumerate(lines) if x.startswith("Set-Location"))
    start = next(i for i, x in enumerate(lines) if x.startswith("& "))
    assert go < start and lines[go] == f"Set-Location -LiteralPath '{folder}'"
    assert lines[start] == f"& '{exe}' '--tools' 'Agent'"
    old = cs._sign_in_script(exe, options=set()).read_text(encoding="utf-8-sig")
    assert f"& '{exe}' '--disallowedTools' '{','.join(cs.DENIED_TOOLS)}'" in old


def test_the_line_to_type_goes_to_the_empty_folder_first(cs):
    assert cs.sign_in_line(PurePosixPath("/Users/a b/enlens/claude-runs/sign-in"), windows=False) == \
        "cd '/Users/a b/enlens/claude-runs/sign-in' && claude"
    assert cs.sign_in_line(Path(r"C:\Users\O'Brien\enlens\claude-runs\sign-in"), windows=True) == \
        r"cd 'C:\Users\O''Brien\enlens\claude-runs\sign-in'; claude"


def test_the_sign_in_route_gives_the_line_for_the_empty_folder(api, cs, monkeypatch):  # noqa: F811
    monkeypatch.setenv("ENLENS_CLAUDE", FAKE)
    opened = []
    monkeypatch.setattr(cs, "_open_window", lambda script: opened.append(script) or "")  # no window
    st, r = api("POST", "/api/claude-setup/sign-in", {})
    folder = cs.sign_in_folder()
    assert st == 200 and r["opened"] is False and r["folder"] == str(folder)
    assert r["command"] == cs.sign_in_line(folder) and r["command"].endswith("claude")
    assert len(opened) == 1 and str(folder) in opened[0].read_text(encoding="utf-8-sig")


def test_the_stand_in_signs_in_from_the_boxed_window(cs, monkeypatch):
    monkeypatch.setenv("ENLENS_CLAUDE", FAKE)
    monkeypatch.setenv("FAKE_CLAUDE_LOGGED_OUT", "1")
    r = subprocess.run([sys.executable, FAKE, *cs.box_args(FAKE, run=False)], capture_output=True, text=True,
                       timeout=30, cwd=str(cs.sign_in_folder()))
    assert r.returncode == 0 and "Signed in" in r.stdout


def test_the_page_says_where_claude_code_works_and_shows_that_line():
    js = (ROOT / "src" / "enlens_claims" / "gui" / "static" / "views" / "settings.js").read_text(encoding="utf-8")
    assert "Where the program is kept does not decide what it can read" in js
    assert 'copyLine(opened.command || "claude"' in js
