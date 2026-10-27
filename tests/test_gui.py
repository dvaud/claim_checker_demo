import os
import stat
from pathlib import Path

import pytest

from enlens_claims.llm import BackendError, BaselineBackend, OllamaBackend


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from enlens_claims.gui import core
    return core


def test_settings_projects_and_key(home, tmp_path):
    core = home
    s = core.load_settings()
    assert s["backend"] == "anthropic" and s["num_ctx"] == 16384
    s.update(backend="ollama", ollama_model="qwen3:8b", unknown="dropped")
    core.save_settings(s)
    assert core.load_settings()["ollama_model"] == "qwen3:8b" and "unknown" not in core.load_settings()

    core.remember_key("sk-test")
    p = core.home() / "credentials.json"
    assert core.stored_key() == "sk-test" and stat.S_IMODE(os.stat(p).st_mode) == 0o600
    core.forget_key()
    assert core.stored_key() == ""

    ws = core.create_project("Green / hydrogen: Morocco!")
    assert ws.root.name == "Green hydrogen Morocco" and core.list_projects() == ["Green hydrogen Morocco"]
    with pytest.raises(ValueError, match="already exists"):
        core.create_project("Green hydrogen Morocco")
    with pytest.raises(ValueError, match="Give the project a name"):
        core.create_project("///")
    folder = core.save_uploads(ws, [("../../evil.txt", b"x" * 10), ("a.pdf", b"%PDF")])
    assert sorted(p.name for p in folder.iterdir()) == ["a.pdf", "evil.txt"] and folder.parent.parent == ws.root

    other = tmp_path / "pilot"
    from enlens_claims.store import Workspace
    Workspace.create(other)
    assert core.link_existing(str(other)) == "pilot" and "pilot" in core.list_projects()
    with pytest.raises(ValueError, match="No workspace"):
        core.link_existing(str(tmp_path))


def test_make_backend(home):
    core = home
    s = dict(core.DEFAULTS)
    with pytest.raises(BackendError, match="No Claude API key"):
        pytest.importorskip("anthropic")
        core.make_backend(s)
    s.update(backend="ollama")
    with pytest.raises(BackendError, match="Choose an Ollama model"):
        core.make_backend(s)
    s.update(ollama_model="qwen3:8b", num_ctx=32768, think="off")
    be, model = core.make_backend(s)
    assert isinstance(be, OllamaBackend) and be.num_ctx == 32768 and be.think is False and model == "qwen3:8b"
    s.update(backend="baseline")
    assert isinstance(core.make_backend(s)[0], BaselineBackend)
    assert core.backend_label(s).startswith("Offline demo")


def test_app_runs_a_check_with_the_demo_backend(home):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    from enlens_claims import ingest
    from helpers import PAPER_A_PAGES, REPORT_B_TEXT, make_pdf

    core = home
    ws = core.create_project("Demo")
    d = ws.root / "src"
    d.mkdir()
    make_pdf(d / "paper_a.pdf", PAPER_A_PAGES)
    (d / "b.txt").write_text(REPORT_B_TEXT)
    ingest.ingest(ws, [d])
    s = core.load_settings()
    s.update(project="Demo", backend="baseline")
    core.save_settings(s)
    app = Path(core.__file__).with_name("app.py")
    at = AppTest.from_file(str(app), default_timeout=60).run()
    assert not at.exception and at.title[0].value == "Check a claim"
    at.text_area(key="claim_text").input("Green hydrogen production can increase water stress in arid regions.").run()
    assert at.selectbox(key="claim_target").options[1].startswith("★ 6.4")
    at.button[0].click().run()
    assert not at.exception
    html = " ".join(m.value for m in at.markdown)
    assert "Stated by a source" in html and "<mark>" in html
    from enlens_claims import claimcheck
    assert len(claimcheck.history(ws)) == 1
