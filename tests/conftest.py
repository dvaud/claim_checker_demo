from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from addon_fixtures import addon, local_addon  # noqa: E402,F401  (0.13.5: add-on fixtures)
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


@pytest.fixture(autouse=True)
def _no_real_enlens_home(tmp_path, monkeypatch):
    """0.13.11: tests never read the researcher's own ENLENS folder (~/enlens). Without this, a test that did not set
    ENLENS_HOME read the real settings, so the models recommended for the plan Claude Code found there (Max: Opus)
    replaced the ones the test expects (Pro). A test that sets ENLENS_HOME itself still gets its own."""
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "enlens-home"))


@pytest.fixture(autouse=True)
def _read_one_file_at_a_time(monkeypatch):
    """0.16: adding documents reads several files at once in reading processes (`ingest.read_workers`). Tests read
    them here, one at a time, so what a test changes in this process (a stand-in for OCR, say) is what reading sees;
    tests/test_0_16_0_speed.py reads at once on purpose and compares."""
    monkeypatch.setenv("ENLENS_READ_WORKERS", "1")


def pytest_collection_modifyitems(config, items):
    """2026-11-12, CI (tests.yml): ENLENS_TEST_SHARD=k/n keeps every n-th test from the k-th on, so n machines share the
    suite evenly (Windows, the slowest system, is split in four). Neighbouring tests (the cases of one parametrised
    test, the tests of one file) go to different machines, and every machine and every pytest-xdist worker collects
    the same order, so they agree on the split. Unset (as on this computer): every test runs."""
    import os

    shard = os.environ.get("ENLENS_TEST_SHARD", "").strip()
    if not shard:
        return
    try:
        k, n = (int(x) for x in shard.split("/"))
        assert 1 <= k <= n
    except (ValueError, AssertionError):
        raise pytest.UsageError(f"ENLENS_TEST_SHARD={shard!r}: expected k/n with 1 <= k <= n, such as 2/3") from None
    keep = [item for i, item in enumerate(items) if i % n == k - 1]
    drop = [item for i, item in enumerate(items) if i % n != k - 1]
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep
