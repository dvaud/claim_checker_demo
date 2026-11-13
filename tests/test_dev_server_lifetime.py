"""The dev server stops on its own: after --max-minutes, and when the process it watches ends."""
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import dev_server  # noqa: E402

SCRIPT = ROOT / "tools" / "dev_server.py"


def test_claude_ancestor_is_chosen_not_the_parent():
    chain = [(500, "/bin/zsh -c sleep"), (400, "/usr/local/bin/claude --resume"), (300, "login")]
    assert dev_server.choose_watch_pid(None, chain) == 400


def test_node_running_claude_code_counts_and_a_claude_path_elsewhere_does_not():
    assert dev_server.is_claude_command("node /opt/lib/node_modules/@anthropic-ai/claude-code/cli.js -p x")
    assert dev_server.is_claude_command("/Users/a/.local/bin/claude")
    assert not dev_server.is_claude_command("/bin/zsh -c cd /Users/a/.claude/worktrees/x && python tools/dev_server.py")
    assert not dev_server.is_claude_command("")


def test_no_claude_ancestor_watches_nothing():
    assert dev_server.choose_watch_pid(None, [(500, "/bin/zsh"), (400, "Terminal")]) is None
    assert dev_server.choose_watch_pid(None, []) is None


def test_explicit_pid_wins():
    assert dev_server.choose_watch_pid(77, [(400, "claude")]) == 77


def test_ancestor_chain_walks_up_to_pid_1():
    table = {10: (20, "python dev_server.py"), 20: (30, "zsh"), 30: (40, "claude"), 40: (1, "launchd")}
    assert dev_server.ancestor_chain(10, lookup=table.get) == [(20, "zsh"), (30, "claude"), (40, "launchd")]
    assert dev_server.ancestor_chain(10, lookup=lambda pid: None) == []


def test_parse_ps_line():
    assert dev_server.parse_ps_line("  123 /usr/bin/claude --x") == (123, "/usr/bin/claude --x")
    assert dev_server.parse_ps_line("") is None


def _run(tmp_path, *args):
    return subprocess.Popen([sys.executable, str(SCRIPT), "--port", "0", "--home", str(tmp_path / "home"), "--empty",
                             *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def _finish(proc, timeout):
    t0 = time.time()
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        pytest.fail(f"the dev server did not stop within {timeout} s:\n{out}")
    return out, time.time() - t0


def test_stops_after_max_minutes(tmp_path):
    proc = _run(tmp_path, "--max-minutes", "0.05", "--watch-pid", "0")
    try:
        out, _ = _finish(proc, 40)
    finally:
        proc.kill()
    assert proc.returncode == 0
    assert "stopping after 0.05 minutes (--max-minutes)" in out


def test_stops_when_the_watched_process_ends(tmp_path):
    victim = subprocess.Popen(["sleep", "60"])
    proc = _run(tmp_path, "--max-minutes", "0", "--watch-pid", str(victim.pid))
    try:
        for line in proc.stdout:  # wait until the app is up
            if line.startswith("link:"):
                break
        victim.kill()
        victim.wait()
        out, took = _finish(proc, 15)
    finally:
        victim.kill()
        proc.kill()
    assert proc.returncode == 0
    assert "has ended" in out
    assert took < 15
