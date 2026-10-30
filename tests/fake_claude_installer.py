"""A stand-in for Anthropic's Claude Code installer (0.10), for tests and `tools/dev_server.py --claude-install`.

Point ENLENS_CLAUDE_INSTALLER at this file and ENLENS_CLAUDE at a path that does not exist yet (ending in .py): it
"installs" Claude Code by writing, at that path, a small program that runs the stand-in `claude`
(fake_claude_cli.py). FAKE_INSTALLER_FAIL=1 makes it fail as a real installer would without a network.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    target = os.environ.get("ENLENS_CLAUDE", "")
    if os.environ.get("FAKE_INSTALLER_FAIL"):
        print("curl: (6) Could not resolve host: claude.ai", file=sys.stderr)
        return 6
    if not target.endswith(".py"):
        print("ENLENS_CLAUDE must name a .py path for the stand-in installer", file=sys.stderr)
        return 2
    time.sleep(float(os.environ.get("FAKE_INSTALLER_DELAY", "0")))
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    cli = HERE / "fake_claude_cli.py"
    Path(target).write_text("import runpy, sys\n"
                            f"sys.argv[0] = {str(cli)!r}\n"
                            f"runpy.run_path({str(cli)!r}, run_name='__main__')\n", encoding="utf-8")
    print("Setting up Claude Code...\n✔ Claude Code successfully installed! (stand-in)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
