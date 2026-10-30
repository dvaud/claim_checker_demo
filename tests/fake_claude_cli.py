"""A stand-in for the `claude` program (0.9), for tests and `tools/dev_server.py --claude-cli`.

Point ENLENS_CLAUDE at this file. It answers what ENLENS asks of Claude Code: `--version`, `auth status`,
`plugin list --json`, `plugin marketplace add <folder>`, `plugin install enlens-run@enlens`, and
`-p "/enlens-run:enlens-run <project>" ...`, which plays /enlens-run with the fake Claude Code of the tests
(fake_claude_code.py) until nothing waits. What was "installed" is kept in <ENLENS_HOME>/fake-claude.json.

0.10: with FAKE_CLAUDE_LOGGED_OUT=1 it starts signed out; run with no arguments (as the sign-in window of "Set up
Claude" does) it "signs in".
"""
from __future__ import annotations

import json
import os
import shlex
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "src")]


def _state_file() -> Path:
    return Path(os.environ.get("ENLENS_HOME", ".")) / "fake-claude.json"


def _state() -> dict:
    try:
        return json.loads(_state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(st: dict) -> None:
    _state_file().write_text(json.dumps(st), encoding="utf-8")


def main(argv: list[str]) -> int:
    if argv[:1] == ["--version"]:
        print("2.1.312 (Claude Code, stand-in)")
        return 0
    if argv[:2] == ["auth", "status"]:
        st = _state()
        logged_in = st.get("logged_in", not os.environ.get("FAKE_CLAUDE_LOGGED_OUT"))
        print(json.dumps({"loggedIn": bool(logged_in), "authMethod": "claude.ai" if logged_in else "none"}))
        return 0
    if not argv:  # the interactive start: the person signs in
        st = _state()
        st["logged_in"] = True
        _save(st)
        print("Signed in with your Claude plan (stand-in).")
        return 0
    if argv[:2] == ["plugin", "list"]:
        st = _state()
        print(json.dumps([{"id": "enlens-run@enlens", "version": "x", "enabled": True}] if st.get("installed") else []))
        return 0
    if argv[:3] == ["plugin", "marketplace", "add"]:
        st = _state()
        st["marketplace"] = argv[3]
        _save(st)
        print("Successfully added marketplace: enlens")
        return 0
    if argv[:2] == ["plugin", "install"]:
        st = _state()
        if not st.get("marketplace"):
            print("Marketplace enlens not found", file=sys.stderr)
            return 1
        st["installed"] = True
        _save(st)
        print("Successfully installed plugin: enlens-run@enlens")
        return 0
    if argv[:1] == ["-p"]:
        words = shlex.split(argv[1])
        if not words or not words[0].startswith("/enlens-run") or len(words) < 2:
            print("Unknown command", file=sys.stderr)
            return 1
        project = words[1]
        import fake_claude_code

        delay = float(os.environ.get("FAKE_CLAUDE_DELAY", "0"))
        total = 0
        for _ in range(20):
            if delay:
                time.sleep(delay)
            r = fake_claude_code.run(project, tools=fake_claude_code.DirectTools(), wrong_first=False)
            b = r.get("batches") or 0
            n = b if isinstance(b, int) else len(b)
            total += n
            if not n:
                break
        print(f"Done: {total} batches answered for {project}. The results are in the ENLENS app.")
        return 0
    print(f"unsupported: {argv}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
