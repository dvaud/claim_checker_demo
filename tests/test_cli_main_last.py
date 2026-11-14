"""`python -m enlens_claims.cli` runs `main()` only after every command is defined: the `if __name__ == "__main__":`
block is the module's last statement (14acc2b; a part appended below it brought back a NameError, and the block is
`# pragma: no cover`, so nothing else notices)."""
from __future__ import annotations

import ast
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "src" / "enlens_claims" / "cli.py"


def test_the_main_block_is_the_last_statement_of_cli():
    last = ast.parse(CLI.read_text(encoding="utf-8")).body[-1]
    assert isinstance(last, ast.If) and ast.unparse(last.test) in ("__name__ == '__main__'", '__name__ == "__main__"')
