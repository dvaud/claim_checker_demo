from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from helpers import PAPER_A_PAGES, REPORT_B_TEXT, UNRELATED_HTML, make_pdf, make_vca_workbook  # noqa: E402

from enlens_claims.store import Workspace  # noqa: E402


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    d = tmp_path / "corpus"
    d.mkdir()
    make_pdf(d / "paper_a.pdf", PAPER_A_PAGES, title="Water footprint of electrolytic hydrogen in arid export regions")
    (d / "irena_jobs_report.txt").write_text(REPORT_B_TEXT)
    (d / "birds.html").write_text(UNRELATED_HTML)
    return d


@pytest.fixture
def vca_xlsx(tmp_path: Path) -> Path:
    return make_vca_workbook(tmp_path / "vca.xlsx")


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "ws")


@pytest.fixture
def loaded(ws: Workspace, corpus: Path, vca_xlsx: Path) -> Workspace:
    from enlens_claims import ingest, sources, vca

    vca.load_into(ws, vca_xlsx)
    ingest.ingest(ws, [corpus])
    sources.match(ws)
    return ws


@pytest.fixture(autouse=True)
def _no_real_claude_code(tmp_path, monkeypatch):
    """0.9: ENLENS finds and sets up Claude Code by itself. Tests never touch a real Claude Code: the `claude` program
    is "not found" unless a test points ENLENS_CLAUDE at the stand-in (tests/fake_claude_cli.py)."""
    monkeypatch.setenv("ENLENS_CLAUDE", str(tmp_path / "no-claude-here"))
    from enlens_claims import claude_setup

    claude_setup._STATUS.update(at=0.0, value=None)
