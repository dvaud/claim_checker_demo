from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(1, str(Path(__file__).parent.parent / "tools"))

# 2026-11-12: bytes written per test, a warning over ENLENS_WRITE_BUDGET_MB, ENLENS_WRITES=15 for the top 15 (writemeter.py)
import writemeter  # noqa: E402
from writemeter import pytest_runtest_logreport, pytest_runtest_makereport, pytest_runtest_setup  # noqa: E402,F401

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
    # 0.18.0rc2: secrets (a storage space's keys) go to files in that folder, never the computer's own keychain
    monkeypatch.setenv("ENLENS_KEYCHAIN", "file")


@pytest.fixture(autouse=True)
def _read_one_file_at_a_time(monkeypatch):
    """0.16: adding documents reads several files at once in reading processes (`ingest.read_workers`). Tests read
    them here, one at a time, so what a test changes in this process (a stand-in for OCR, say) is what reading sees;
    tests/test_0_16_0_speed.py reads at once on purpose and compares."""
    monkeypatch.setenv("ENLENS_READ_WORKERS", "1")


@pytest.fixture(autouse=True)
def _queue_looks_often(monkeypatch):
    """2026-11-12: the app looks at tasks waiting for Claude Code every 1.5 s (`taskqueue.QUEUE_POLL`) and at checks
    waiting for it every 2 s (`server.FOLLOW_POLL`). The stand-ins of Claude Code in tests answer at once, so each
    wait cost a test up to two seconds of nothing (13 s of test_08_queue's every-AI-button test); here they look
    every 0.1 s."""
    from enlens_claims import taskqueue
    from enlens_claims.gui import server

    monkeypatch.setattr(taskqueue, "QUEUE_POLL", 0.1)
    monkeypatch.setattr(server, "FOLLOW_POLL", 0.1)


RAM_DISK = "/Volumes/ENLENS-TESTS"


def pytest_configure(config):
    """2026-11-12: test files go to a RAM disk when there is one, so test runs stop wearing the SSD:
    `ENLENS_TEST_TMP=<folder>`, or a volume named ENLENS-TESTS (docs/DEVELOPING.md says how to make one). This sets
    TMPDIR, so pytest's tmp_path and every temporary file ENLENS makes in a test (scratch projects of a sync round,
    unpacked zips) land there; pytest-xdist's workers inherit it."""
    # 2026-11-12: programs a test starts (`python -m enlens_claims.gui.launch`, the dev server, reading processes) import
    # this copy's ENLENS too. pytest's `pythonpath` reaches only this process, so in a git worktree they imported the
    # copy the virtual environment was installed from (another version: three launcher tests failed in worktrees).
    src = str(Path(__file__).resolve().parent.parent / "src")
    paths = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p and p != src]
    os.environ["PYTHONPATH"] = os.pathsep.join([src, *paths])
    tmp = os.environ.get("ENLENS_TEST_TMP") or (RAM_DISK if os.path.isdir(RAM_DISK) else "")
    if tmp and os.path.isdir(tmp):
        for name in ("TMPDIR", "TEMP", "TMP"):
            os.environ[name] = tmp
        tempfile.tempdir = None


def _leaves_out_heavy(config) -> bool:
    """2026-11-12: a local run of the whole suite (no test file named, no -m) leaves out the tests marked `heavy`; CI
    (`CI` set) and `ENLENS_ALL_TESTS=1` run them, and naming their file runs them too."""
    if os.environ.get("CI") or os.environ.get("ENLENS_ALL_TESTS") == "1" or config.option.markexpr:
        return False
    here = config.invocation_params.dir
    return all((here / a.split("::")[0]).is_dir() for a in config.args)


@pytest.fixture(autouse=True)
def _fast_sqlite(request, monkeypatch):
    """2026-11-12: tests use SQLite without forced flushes or an on-disk rollback journal (store.py reads
    ENLENS_TEST_FAST_SQLITE), which halves what a test writes. A test marked `durable` gets the real settings."""
    if request.node.get_closest_marker("durable") is None:
        monkeypatch.setenv("ENLENS_TEST_FAST_SQLITE", "1")


def pytest_collection_modifyitems(config, items):
    """2026-11-12, CI (tests.yml): ENLENS_TEST_SHARD=k/n keeps every n-th test from the k-th on, so n machines share the
    suite evenly (Windows, the slowest system, is split in four). Neighbouring tests (the cases of one parametrised
    test, the tests of one file) go to different machines, and every machine and every pytest-xdist worker collects
    the same order, so they agree on the split. Unset (as on this computer): every test runs. Before the split, a
    local run of the whole suite leaves out the tests marked `heavy` (`_leaves_out_heavy`)."""
    if _leaves_out_heavy(config):
        heavy = [item for item in items if item.get_closest_marker("heavy") is not None]
        if heavy:
            config.hook.pytest_deselected(items=heavy)
            items[:] = [item for item in items if item.get_closest_marker("heavy") is None]
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



def pytest_terminal_summary(terminalreporter, config):
    writemeter.pytest_terminal_summary(terminalreporter)
    if not hasattr(config, "workerinput") and _leaves_out_heavy(config):
        terminalreporter.write_line("Tests marked heavy were left out (CI runs them; ENLENS_ALL_TESTS=1, or naming "
                                    "their file, runs them here).")
