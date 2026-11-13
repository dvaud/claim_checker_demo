"""Changelog fragments (0.18.1, roadmap J1.4): changes/*.md joined into a new CHANGELOG entry by tools/release.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import release  # noqa: E402

CHANGELOG = "# Changelog\n\n## 0.18.0 (November 2026): working together as a team\n\nThe stable 0.18.\n"


def _root(tmp_path: Path, fragments: dict[str, str]) -> Path:
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    (tmp_path / "changes").mkdir()
    (tmp_path / "changes" / "README.md").write_text("# not a fragment\n", encoding="utf-8")
    for name, text in fragments.items():
        (tmp_path / "changes" / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_fragments_join_by_section_in_a_fixed_order_and_are_deleted(tmp_path):
    root = _root(tmp_path, {
        "a-theory.md": "### Not yet done\n\n- The AI draft.\n\n### New\n\n- **Theory documents.** Marked by you.\n",
        "b-assessment.md": "### Checks\n\nA paragraph.\n\n### new\n\n- **The assessment in words.**\n",
        "c-fix.md": "### Fixed\n\n- **A fix.**\n\n### For developers\n\n- `changes/`.\n",
    })
    entry = release.join_fragments("0.18.1", "a title", root, month="November 2026")
    assert entry.splitlines()[0] == "## 0.18.1 (November 2026): a title"
    heads = [line for line in entry.splitlines() if line.startswith("### ")]
    assert heads == ["### New", "### Checks", "### Fixed", "### For developers", "### Not yet done"]
    # two lists run on as one list, in the fragments' order
    assert "- **Theory documents.** Marked by you.\n- **The assessment in words.**" in entry
    text = (root / "CHANGELOG.md").read_text("utf-8")
    assert text.startswith("# Changelog\n\n## 0.18.1 (November 2026): a title\n")
    assert text.index("## 0.18.1") < text.index("## 0.18.0") and "The stable 0.18." in text
    assert release.changelog_versions(root)[:2] == ["0.18.1", "0.18.0"]
    assert [p.name for p in (root / "changes").iterdir()] == ["README.md"]
    release.no_fragments_left(root)


def test_dry_run_changes_nothing_and_check_fails_while_fragments_are_left(tmp_path):
    root = _root(tmp_path, {"x.md": "### Fixed\n\n- **A fix.**\n"})
    assert "### Fixed\n\n- **A fix.**" in release.fragments_entry("0.18.1", "t", root, month="November 2026")
    assert (root / "CHANGELOG.md").read_text("utf-8") == CHANGELOG
    with pytest.raises(release.ReleaseError, match="x.md"):
        release.no_fragments_left(root)


@pytest.mark.parametrize("text, problem", [
    ("- text before any heading\n", "before its first"),
    ("## A version heading\n", "only '### Section'"),
    ("### Fixed\n\n\n", "empty"),
])
def test_a_wrong_fragment_is_refused_in_words(tmp_path, text, problem):
    root = _root(tmp_path, {"bad.md": text})
    with pytest.raises(release.ReleaseError, match=problem):
        release.join_fragments("0.18.1", "t", root)
    assert (root / "changes" / "bad.md").exists()


def test_no_fragments_a_known_version_or_a_bad_one_is_refused(tmp_path):
    root = _root(tmp_path, {})
    with pytest.raises(release.ReleaseError, match="no fragments"):
        release.join_fragments("0.18.1", "t", root)
    (root / "changes" / "f.md").write_text("### Fixed\n\n- x\n", encoding="utf-8")
    with pytest.raises(release.ReleaseError, match="already has"):
        release.join_fragments("0.18.0", "t", root)
    with pytest.raises(release.ReleaseError, match="not of the form"):
        release.join_fragments("v0.18.1", "t", root)


def test_the_repositorys_own_fragments_join_cleanly():
    """Every fragment in this repository is well formed, so the release's join cannot stop on one."""
    if not release.fragment_files(ROOT):
        pytest.skip("no fragments waiting")
    entry = release.fragments_entry("99.0.0", "check", ROOT)
    assert entry.count("\n### ") >= 1


def test_the_release_workflow_refuses_a_tag_with_fragments_left():
    wf = (ROOT / ".github" / "workflows" / "release.yml").read_text("utf-8")
    assert "python tools/release.py fragments --check" in wf
