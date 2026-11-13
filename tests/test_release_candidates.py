"""0.15: release candidates (the roadmap's rule: every minor release first as a candidate, in use for a week).

- versions order a release candidate (0.15.0rc1) after every earlier release and before its own release (before, it
  counted as 0.15.0, so a copy of it never heard of 0.15.0 itself);
- a copy of a candidate is offered its release by Update, and is never offered an older full release;
- a withdrawn number (0.15.0, 0.15.1) counts as older only while this version is below it, so it can be released;
- the release helper takes a candidate's tag and changelog entry, and its notes install that candidate (GitHub's
  "latest" is the latest full release) and say what it is;
- the release workflow drafts a candidate as a GitHub pre-release.
"""
from __future__ import annotations

import json
import re
import shutil

import pytest

from test_0100_setup_and_moving import ROOT, Runs

import release  # tools/, put on the path by test_0100_setup_and_moving

# loaded before any test changes enlens_claims.__version__: a module that copies it on import keeps the real one
from enlens_claims import installation, update  # noqa: E402,F401
from enlens_claims.gui import launcher  # noqa: E402,F401


def test_a_release_candidate_comes_between_the_releases():
    from enlens_claims.update import version_tuple

    order = ["0.14.6", "0.14.7", "0.15.0.dev1", "0.15.0a1", "0.15.0b2", "0.15.0rc1", "0.15.0rc2", "0.15.0", "0.15.0.1",
             "0.15.1rc1", "0.15.1", "0.16.0"]
    assert sorted(order, key=version_tuple) == order
    for junk in ("0.15.0candidate", "0.15.0abc", "0.15.0 (local)"):  # other words after the number are ignored
        assert version_tuple(junk) == version_tuple("0.15.0"), junk
    assert version_tuple("v0.15.0rc1") == version_tuple("0.15.0rc1") == version_tuple("0.15.0-rc.1")
    assert version_tuple("0.15") == version_tuple("0.15.0") and version_tuple("v0.15.0") == version_tuple("0.15.0")
    assert version_tuple("") == () == version_tuple("unknown")


def test_the_claude_code_plugin_gets_a_candidate_s_number_as_semantic_versioning(monkeypatch, tmp_path):
    from enlens_claims import claude_setup
    from enlens_claims.update import semver

    assert semver("0.15.0rc1") == "0.15.0-rc.1" and semver("0.15.0") == "0.15.0" and semver("0.15.0b2") == "0.15.0-b.2"
    monkeypatch.setattr(claude_setup, "__version__", "0.15.0rc1")
    assert '"version": "0.15.0-rc.1"' in claude_setup._fill('"version": "{{VERSION}}"')
    claude_setup.write_plugin()
    written = (claude_setup.plugin_folder() / ".claude-plugin" / "plugin.json").read_text("utf-8")
    assert '"version": "0.15.0-rc.1"' in written
    assert claude_setup.stale() == ""  # the candidate's own plugin is not out of date
    monkeypatch.setattr(claude_setup, "__version__", "0.15.0rc2")
    assert "written by ENLENS 0.15.0-rc.1" in claude_setup.stale()  # the next candidate writes it again


def _latest(version):
    page = json.dumps({"tag_name": f"v{version}", "html_url": "https://x", "body": "", "assets": []}).encode()
    return lambda url: page


def test_update_offers_a_candidate_its_release_and_nothing_older(monkeypatch):
    import enlens_claims
    from enlens_claims import update

    monkeypatch.setattr(enlens_claims, "__version__", "0.15.0rc1")
    r = update.update_release(check_only=True, fetch=_latest("0.15.0"), run=Runs())
    assert r["waiting"] == "0.15.0" and "ready to install" in r["message"]
    for older in ("0.14.7", "0.15.0rc1"):
        r = update.update_release(check_only=True, fetch=_latest(older), run=Runs())
        assert r["updated"] is False and "up to date" in r["message"], older
    # a full release never sees a candidate of its own number as newer
    monkeypatch.setattr(enlens_claims, "__version__", "0.15.0")
    assert "up to date" in update.update_release(check_only=True, fetch=_latest("0.15.0rc2"), run=Runs())["message"]


def test_a_withdrawn_number_released_for_real_is_not_older(monkeypatch):
    import enlens_claims
    from enlens_claims.gui import launcher

    monkeypatch.setattr(enlens_claims, "__version__", "0.14.7")
    # 0.15.0 and 0.15.1 were released for real (they left update.WITHDRAWN): a running one of them is newer
    assert not launcher.is_older({"version": "0.15.0"}) and not launcher.is_older({"version": "0.15.1"})
    assert not launcher.is_older({"version": "0.15.0rc1"})  # a newer candidate is running: leave it
    monkeypatch.setattr(enlens_claims, "__version__", "0.15.0")
    assert not launcher.is_older({"version": "0.15.0"})      # the same release in another window
    assert not launcher.is_older({"version": "0.15.1"})      # a newer release (0.15.1 left the list too)
    assert launcher.is_older({"version": "0.15.0rc2"}) and launcher.is_older({"version": "0.14.7"})
    monkeypatch.setattr(enlens_claims, "__version__", "0.15.2")
    assert launcher.is_older({"version": "0.15.1"}) and not launcher.is_older({"version": "0.16.0"})


@pytest.fixture
def candidate(tmp_path):
    """A copy of the release's version files at 0.15.0rc1, its changelog entry above the current one."""
    root = tmp_path / "repo"
    (root / "src" / "enlens_claims").mkdir(parents=True)
    shutil.copy(ROOT / "pyproject.toml", root / "pyproject.toml")
    shutil.copy(ROOT / "src" / "enlens_claims" / "__init__.py", root / "src" / "enlens_claims" / "__init__.py")
    for p in (root / "pyproject.toml", root / "src" / "enlens_claims" / "__init__.py"):
        text = p.read_text("utf-8")
        p.write_text(re.sub(r'((?:^version|__version__)\s*=\s*")[^"]+"', r'\g<1>0.15.0rc1"', text, count=1, flags=re.M),
                     "utf-8")
    log = (ROOT / "CHANGELOG.md").read_text("utf-8").replace(
        "# Changelog\n", "# Changelog\n\n## 0.15.0rc1 (November 2026): a release candidate\n\nTry it.\n", 1)
    (root / "CHANGELOG.md").write_text(log, "utf-8")
    return root


def test_the_release_helper_takes_a_candidate(candidate):
    assert release.changelog_versions(candidate)[0] == "0.15.0rc1"
    assert release.check("v0.15.0rc1", candidate) == "0.15.0rc1"
    for bad in ("v0.15.0-rc1", "v0.15.0rc", "v0.15.0b1"):
        with pytest.raises(release.ReleaseError, match="of the form"):
            release.check(bad, candidate)
    with pytest.raises(release.ReleaseError, match="the tag is v0.15.0"):
        release.check("v0.15.0", candidate)
    assert release.is_prerelease("v0.15.0rc1") and not release.is_prerelease("v0.15.0")
    notes = release.notes("0.15.0rc1", candidate)
    files = "https://github.com/dvaud/claim_checker_demo/releases/download/v0.15.0rc1"
    assert notes.startswith("**This is a release candidate** of ENLENS 0.15.0") and "Try it." in notes
    assert f"curl -fsSL {files}/install.sh" in notes and f"irm {files}/install.ps1" in notes
    assert "releases/latest" not in notes
    assert "## 0.14" not in notes  # only the candidate's own entry


def test_a_full_release_still_installs_the_latest(tmp_path):
    # 0.16: a full release's own changelog, not the repository's top entry (which is a candidate while one is out)
    root = tmp_path / "repo"
    root.mkdir()
    (root / "CHANGELOG.md").write_text("# Changelog\n\n## 0.15.7 (November 2026): a release\n\nIt works.\n", "utf-8")
    notes = release.notes("0.15.7", root)
    assert "This is a release candidate" not in notes and "releases/latest/download/install.sh" in notes


def test_the_workflow_drafts_a_candidate_as_a_pre_release():
    wf = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    build = wf.split("\n  build:", 1)[1].split("\n  try-install:", 1)[0]
    assert "prerelease: ${{ steps.version.outputs.prerelease }}" in build
    assert 'echo "prerelease=$(python tools/release.py prerelease)" >> "$GITHUB_OUTPUT"' in build
    draft = wf.split("\n  release:", 1)[1]
    assert "needs.build.outputs.prerelease == 'true' && '--prerelease'" in draft and "--draft" in draft
