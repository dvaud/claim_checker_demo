"""0.14.4: a Claude Code run left going is recognised from its whole command line, also on Linux.

ENLENS records each run's process number and, after a restart, checks with `ps` that the process is still a Claude
Code run of ENLENS (its command line holds the slash command). On Linux, `ps` cuts its output at 80 characters when it
writes to a pipe, and Claude Code's command line starts with a long path, so the slash command was cut off and a run
left going was not recognised: the reopened app could not stop it and would start a second one. 0.14.3's own test
caught it on the release's Linux machine; this test does the same with a command line longer than 80 characters.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from enlens_claims import claude_setup

pytestmark = pytest.mark.skipif(os.name == "nt", reason="Windows reads the process list with tasklist")


def test_a_run_with_a_long_command_line_is_recognised(tmp_path):
    folder = tmp_path / ("a-long-folder-name-" * 8)  # like ~/.local/share/claude/versions/2.1.319/…
    folder.mkdir()
    args = [sys.executable, "-c", "import time; time.sleep(30)", str(folder / "claude"),
            "-p", f'{claude_setup.SLASH} "Demo"']
    assert len(" ".join(args)) > 200
    proc = subprocess.Popen(args)
    try:
        assert claude_setup._pid_runs_enlens(proc.pid)
    finally:
        proc.kill()
        proc.wait()
    assert not claude_setup._pid_runs_enlens(proc.pid)


def test_another_program_with_the_number_is_not_a_run(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "x" * 200])
    try:
        assert not claude_setup._pid_runs_enlens(proc.pid)
    finally:
        proc.kill()
        proc.wait()
