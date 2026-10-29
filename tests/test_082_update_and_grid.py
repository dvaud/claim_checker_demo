"""0.8.2: the heat grids stay readable on hover, and `enlens update` moves a git copy forward without a new venv."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from enlens_claims import update

STATIC = Path(__file__).resolve().parents[1] / "src" / "enlens_claims" / "gui" / "static"


# ---------------------------------------------------------------------------------------------
# the grids
# ---------------------------------------------------------------------------------------------
def _specificity(selector: str) -> tuple[int, int, int]:
    s = re.sub(r"::?[a-z-]+\([^)]*\)", lambda m: m.group(0) if m.group(0).startswith(":not") else ":p", selector)
    ids = len(re.findall(r"#[\w-]+", s))
    classes = len(re.findall(r"\.[\w-]+|\[[^\]]+\]|(?<!:):(?!not)[\w-]+", s))
    elements = len(re.findall(r"(?:^|[\s>+~])([a-z][\w-]*)", s))
    return ids, classes, elements


def _rules(css: str) -> list[tuple[str, str]]:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]


def test_heat_levels_outrank_the_row_hover():
    css = "\n".join((STATIC / f).read_text("utf-8") for f in ("app.css", "concepts-themes.css", "profile-viewer.css"))
    rules = _rules(css)
    hovers = [sel for s, body in rules if "background" in body for sel in s.split(",")
              if ".row-link:hover" in sel and not re.search(r"\.(pf|th)-l0|\.map-hyp", sel)]
    assert hovers, "the row hover rules were not found"
    strongest_hover = max(_specificity(h.strip()) for h in hovers)
    for p in ("pf", "th"):
        for lv in range(1, 5):
            sels = [sel.strip() for s, body in rules if "background" in body for sel in s.split(",")
                    if f".{p}-l{lv}" in sel and ":hover" not in sel]
            assert sels, f"no background for .{p}-l{lv}"
            assert max(_specificity(x) for x in sels) > strongest_hover, f".{p}-l{lv} loses to the row hover"


def test_darkest_cell_has_its_own_token_in_every_theme():
    app = (STATIC / "app.css").read_text("utf-8")
    assert app.count("--heat-4:") == 3  # light, dark by system setting, dark by choice
    for f in ("concepts-themes.css", "profile-viewer.css"):
        assert "var(--heat-4)" in (STATIC / f).read_text("utf-8")


# ---------------------------------------------------------------------------------------------
# enlens update
# ---------------------------------------------------------------------------------------------
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _g(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main", *args],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout


def _release(repo: Path, version: str, deps: str = '"pydantic>=2.5"') -> None:
    (repo / "src" / "enlens_claims").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "enlens_claims" / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    (repo / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{version}"\ndependencies = [{deps}]\n',
                                         encoding="utf-8")
    _g(repo, "add", "-A")
    _g(repo, "commit", "-qm", version)


@pytest.fixture
def copies(tmp_path, monkeypatch):
    """A GitHub stand-in (bare), the developer's copy and the user's installed copy."""
    monkeypatch.setattr(update, "_refresh_plugin", lambda: False)
    monkeypatch.setattr(update, "_app_running", lambda: False)
    remote, dev, user = tmp_path / "remote.git", tmp_path / "dev", tmp_path / "user"
    _g(tmp_path, "init", "-q", "--bare", str(remote))
    _g(tmp_path, "init", "-q", str(dev))
    _release(dev, "0.8.1")
    _g(dev, "remote", "add", "origin", str(remote))
    _g(dev, "push", "-q", "-u", "origin", "HEAD:main")
    _g(tmp_path, "clone", "-q", "-b", "main", str(remote), str(user))
    return dev, user


class Pip:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd, cwd):
        if cmd[1:3] == ["-m", "pip"]:
            self.calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return update._run(cmd, cwd)


@needs_git
def test_up_to_date(copies):
    _, user = copies
    out = update.update(root=user, run=Pip())
    assert out["updated"] is False and out["version"] == "0.8.1" and "up to date" in out["message"]


@needs_git
def test_code_only_update_needs_no_reinstall(copies):
    dev, user = copies
    (dev / "src" / "enlens_claims" / "__init__.py").write_text('__version__ = "0.8.2"\n', encoding="utf-8")
    _g(dev, "commit", "-qam", "0.8.2")
    _g(dev, "push", "-q")
    assert update.update(check_only=True, root=user, run=Pip())["waiting"] == 1
    assert update.version_in(user) == "0.8.1"  # --check changes nothing
    pip = Pip()
    out = update.update(root=user, run=pip)
    assert out["updated"] and out["from"] == "0.8.1" and out["version"] == "0.8.2"
    assert out["reinstalled"] is False and pip.calls == []


@needs_git
def test_new_requirements_are_installed_into_the_same_python(copies):
    dev, user = copies
    _release(dev, "0.8.2", deps='"pydantic>=2.5", "numpy>=1.24"')
    _g(dev, "push", "-q")
    pip = Pip()
    out = update.update(root=user, run=pip, python="/the/venv/python")
    assert out["reinstalled"] is True
    assert pip.calls == [["/the/venv/python", "-m", "pip", "install", "--quiet", "-e", str(user)]]


@needs_git
def test_local_changes_stop_the_update(copies):
    dev, user = copies
    _release(dev, "0.8.2")
    _g(dev, "push", "-q")
    (user / "src" / "enlens_claims" / "__init__.py").write_text('__version__ = "mine"\n', encoding="utf-8")
    with pytest.raises(update.UpdateError, match="changed on this computer.*__init__.py"):
        update.update(root=user, run=Pip())
    assert update.version_in(user) == "mine"


def test_not_a_git_copy(monkeypatch):
    monkeypatch.setattr(update, "source_root", lambda: None)
    with pytest.raises(update.UpdateError, match="not installed from a git copy"):
        update.update(run=Pip())
