"""0.15: what testing needs.

- the update channel (Settings → Technical, "Try new versions early"): "stable" (default) or "early"; early looks at
  all published releases, a release candidate too, skipping drafts; stable keeps GitHub's *latest*;
- `update_release` and `latest_version` honour the channel; the update answer says when a version is a candidate;
- "Copy technical details" (a short block, none of the private things);
- the issue forms and SECURITY.md exist, and the test workflow runs on three systems.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from test_0100_setup_and_moving import ROOT, Runs

from enlens_claims import home, installation, update  # noqa: E402,F401


def _release(version, draft=False, prerelease=None):
    return {"tag_name": f"v{version}", "draft": draft,
            "prerelease": update.is_candidate(version) if prerelease is None else prerelease,
            "html_url": f"https://x/{version}", "body": "", "assets": []}


class Github:
    """A fake of the GitHub API: records the addresses asked, answers the list or the latest one."""

    def __init__(self, releases, latest):
        self.releases, self.latest, self.asked = releases, latest, []

    def __call__(self, url):
        self.asked.append(url)
        if url.endswith("/releases/latest"):
            return json.dumps(_release(self.latest)).encode()
        if url.endswith("/releases?per_page=30"):
            return json.dumps(self.releases).encode()
        raise AssertionError(url)


def _early():
    home.update_settings({"update_channel": "early"})


# --- the setting ----------------------------------------------------------------------------------------------------
def test_the_channel_is_stable_unless_chosen():
    assert home.DEFAULTS["update_channel"] == "stable"
    assert home.load_settings()["update_channel"] == "stable" and update.update_channel() == "stable"
    _early()
    assert home.load_settings()["update_channel"] == "early" and update.update_channel() == "early"
    home.update_settings({"update_channel": "stable"})
    assert update.update_channel() == "stable"


def test_the_channel_is_validated():
    assert home.clean_settings({"update_channel": " early "}) == {"update_channel": "early"}
    for bad in ("beta", "", "Early", "nightly"):
        with pytest.raises(ValueError, match="stable or early"):
            home.clean_settings({"update_channel": bad})
    with pytest.raises(ValueError):
        home.update_settings({"update_channel": "sometimes"})
    assert update.update_channel() == "stable"


def test_a_candidate_is_told_from_a_release():
    for v in ("0.15.0rc1", "v0.15.0rc2", "0.15.0b1", "0.15.0.dev1"):
        assert update.is_candidate(v), v
    for v in ("0.15.0", "v0.14.6", "0.15.0.1", "", "unknown"):
        assert not update.is_candidate(v), v


# --- which release the check takes ----------------------------------------------------------------------------------
LIST = [_release("0.15.1", draft=True), _release("0.15.0rc2"), _release("0.15.0rc1"), _release("0.14.6"),
        _release("0.14.5")]


def test_early_takes_the_highest_published_version_a_candidate_too():
    gh = Github(LIST, latest="0.14.6")
    rel = update.latest_release(gh, channel="early")
    assert rel["version"] == "0.15.0rc2" and rel["tag"] == "v0.15.0rc2"  # the draft 0.15.1 is not published
    assert gh.asked == ["https://api.github.com/repos/dvaud/claim_checker_demo/releases?per_page=30"]
    # the order of GitHub's list does not matter, and a release beats its own candidates
    shuffled = [_release("0.14.6"), _release("0.15.0rc1"), _release("0.15.0"), _release("0.15.0rc2")]
    assert update.latest_release(Github(shuffled, "0.15.0"), channel="early")["version"] == "0.15.0"
    assert update.highest_release([]) == {} and update.highest_release([_release("0.15.0", draft=True)]) == {}
    assert update.highest_release([{"tag_name": "nightly"}, "junk"]) == {}


def test_stable_ignores_a_pre_release():
    gh = Github(LIST, latest="0.14.6")
    rel = update.latest_release(gh, channel="stable")
    assert rel["version"] == "0.14.6"
    assert gh.asked == ["https://api.github.com/repos/dvaud/claim_checker_demo/releases/latest"]
    assert update.latest_release(Github(LIST, "0.14.6"))["version"] == "0.14.6"  # the default is the settings': stable
    _early()
    assert update.latest_release(Github(LIST, "0.14.6"))["version"] == "0.15.0rc2"


def test_a_release_marked_as_a_pre_release_is_skipped_on_stable(monkeypatch):
    """Rolling back: GitHub's latest is then the release before, which is all stable looks at."""
    import enlens_claims

    monkeypatch.setattr(enlens_claims, "__version__", "0.14.5")
    gh = Github([_release("0.15.0", prerelease=True), _release("0.14.6")], latest="0.14.6")
    r = update.update_release(check_only=True, fetch=gh, run=Runs())
    assert r["waiting"] == "0.14.6"


def test_update_release_honours_the_channel(monkeypatch):
    import enlens_claims

    monkeypatch.setattr(enlens_claims, "__version__", "0.14.6")
    gh = Github(LIST, latest="0.14.6")
    assert "up to date" in update.update_release(check_only=True, fetch=gh, run=Runs())["message"]
    r = update.update_release(check_only=True, fetch=gh, run=Runs(), channel="early")
    assert r["waiting"] == "0.15.0rc2" and "0.15.0rc2 is ready" in r["message"]
    _early()  # the same from the settings
    assert update.update_release(check_only=True, fetch=gh, run=Runs())["waiting"] == "0.15.0rc2"
    # a copy of the candidate is not offered an older candidate, and is offered the release when it comes
    monkeypatch.setattr(enlens_claims, "__version__", "0.15.0rc2")
    assert "up to date" in update.update_release(check_only=True, fetch=gh, run=Runs())["message"]
    gh = Github(LIST + [_release("0.15.0")], latest="0.15.0")
    assert update.update_release(check_only=True, fetch=gh, run=Runs())["waiting"] == "0.15.0"


def test_the_quick_look_leaves_the_release_page_on_the_early_channel(monkeypatch):
    """github.com/…/releases/latest never shows a pre-release, so early asks the API's list instead."""
    import enlens_claims

    monkeypatch.setattr(enlens_claims, "__version__", "0.14.5")
    seen = []

    def peek(url):
        seen.append(url)
        return "https://github.com/dvaud/claim_checker_demo/releases/tag/v0.14.6"

    assert update.latest_version(peek, channel="stable") == "0.14.6" and len(seen) == 1
    assert update.latest_version(peek, channel="early") == "" and len(seen) == 1
    gh = Github(LIST, latest="0.14.6")
    r = update.update_release(check_only=True, fetch=gh, run=Runs(), peek=peek, channel="early")
    assert r["waiting"] == "0.15.0rc2" and len(seen) == 1
    r = update.update_release(check_only=True, fetch=gh, run=Runs(), peek=peek, channel="stable")
    assert r["waiting"] == "0.14.6" and len(seen) == 2


def test_a_failed_look_says_so_on_either_channel():
    def offline(url):
        raise OSError("no network")

    for channel in ("stable", "early"):
        with pytest.raises(update.UpdateError, match="Are you online"):
            update.latest_release(offline, channel=channel)


# --- technical details ----------------------------------------------------------------------------------------------
def test_the_technical_details_have_what_a_report_needs_and_nothing_private(monkeypatch, tmp_path):
    from enlens_claims import __version__

    secret = "Zebra-Oncology-Interviews"
    ws = home.create_project(secret)
    (ws.root / "Confidential-Minutes-Smith.pdf").write_bytes(b"x")
    home.remember_key("sk-ant-api03-SECRETKEY123")
    home.update_settings({"update_channel": "early"})
    monkeypatch.setattr(installation, "kind", lambda: "script")
    text = installation.technical_details()
    lines = dict(line.split(": ", 1) for line in text.splitlines())
    assert list(lines) == ["ENLENS version", "Installed", "System", "Python", "AI route", "Local only", "Secrets kept in", "Update channel"]
    assert lines["ENLENS version"] == __version__ and lines["Installed"] == "script"
    assert re.fullmatch(r"3\.\d+\.\d+", lines["Python"])
    assert lines["System"].split()[0] in ("Windows", "macOS", "Linux")
    assert lines["AI route"] == home.BACKEND_LABELS[home.load_settings()["backend"]]
    assert lines["Local only"] == "no" and lines["Update channel"].startswith("early")
    assert "yes" in installation.technical_details(local_only=True)
    for private in (secret, "Confidential", "Smith", "sk-ant", "SECRETKEY", str(tmp_path), str(home.home()), str(Path.home()),
                    "/Users", "\\Users", ".pdf", ".sqlite"):
        assert private not in text, private
    import getpass

    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - no user name known here
        user = ""
    assert len(user) < 4 or user not in text
    monkeypatch.setattr(installation, "kind", lambda: "git")
    assert "git copy" in installation.technical_details().splitlines()[-1]


def test_the_endpoint_and_the_page_carry_it():
    server = (ROOT / "src/enlens_claims/gui/server.py").read_text("utf-8")
    assert '"/api/technical-details", "get_technical_details"' in server
    assert "/api/technical-details" in (ROOT / "docs/API.md").read_text("utf-8")
    js = (ROOT / "src/enlens_claims/gui/static/views/settings.js").read_text("utf-8")
    assert "Copy technical details" in js and "Stable (recommended)" in js and "Try new versions early" in js
    assert 'target: "_blank", rel: "noopener"' in js and "issues/new?template=problem.yml" in js


# --- the issue forms, the security policy, the workflow --------------------------------------------------------------
FORMS = ROOT / ".github" / "ISSUE_TEMPLATE"


def test_the_issue_forms_and_security_policy_exist():
    for name in ("problem.yml", "idea.yml", "config.yml"):
        assert (FORMS / name).is_file(), name
    problem = (FORMS / "problem.yml").read_text("utf-8")
    assert "Copy technical details" in problem and "Settings" in problem and "private" in problem
    assert "blank_issues_enabled: false" in (FORMS / "config.yml").read_text("utf-8")
    assert "security/policy" in (FORMS / "config.yml").read_text("utf-8")
    sec = (ROOT / "SECURITY.md").read_text("utf-8")
    for needle in ("Report a vulnerability", "release candidate", "latest release", "cloud models are switched off"):
        assert needle in sec, needle


def test_the_forms_parse_as_yaml():
    yaml = pytest.importorskip("yaml")
    problem = yaml.safe_load((FORMS / "problem.yml").read_text("utf-8"))
    assert problem["name"] == "Something does not work"
    kinds = [b["type"] for b in problem["body"]]
    assert "textarea" in kinds and kinds[-1] == "checkboxes"
    ids = [b["id"] for b in problem["body"] if "id" in b]
    assert {"did", "expected", "happened", "details", "privacy"} <= set(ids) and len(ids) == len(set(ids))
    idea = yaml.safe_load((FORMS / "idea.yml").read_text("utf-8"))
    assert idea["name"] == "An idea or a wish" and idea["body"]
    cfg = yaml.safe_load((FORMS / "config.yml").read_text("utf-8"))
    assert cfg["blank_issues_enabled"] is False
    assert cfg["contact_links"][0]["url"].endswith("/security/policy")
    wf = yaml.safe_load((ROOT / ".github/workflows/tests.yml").read_text("utf-8"))
    assert wf["jobs"]["test"]["strategy"]["fail-fast"] is False
    rows = wf["jobs"]["test"]["strategy"]["matrix"]["include"]
    assert {r["os"] for r in rows} == {"ubuntu-latest", "macos-latest", "windows-latest"}
    # 2026-11-12: Windows runs in parts (ENLENS_TEST_SHARD, tests/conftest.py); together they are every test once
    parts = sorted(r["shard"] for r in rows if r["os"] == "windows-latest")
    assert parts == [f"{k}/{len(parts)}" for k in range(1, len(parts) + 1)]
    assert all(not r["shard"] for r in rows if r["os"] != "windows-latest")
    # 2026-11-12: one Linux job installs every optional extra, so no test is skipped everywhere for a missing one
    full = [r for r in rows if r["all"]]
    assert len(full) == 1 and full[0]["os"] == "ubuntu-latest"
    assert set(full[0]["extras"].split(",")) >= {"dev", "connector", "fast", "pdfminer", "anthropic", "ocr"}
    assert all(set(r["extras"].split(",")) >= {"dev", "connector", "fast"} for r in rows)


def test_the_tests_run_on_three_systems_and_a_linux_job_lints():
    text = (ROOT / ".github/workflows/tests.yml").read_text("utf-8")
    for needle in ("fail-fast: false", "ubuntu-latest", "macos-latest", "windows-latest", '"3.10"', '"3.13"',
                   # 0.18.1 (J1.7): packages come from uv.lock, and the checkout has the tags the version is made from
                   "uv sync --frozen", "uv lock --check", "fetch-depth: 0", "tesseract-ocr",
                   "ruff check --select E9,F63,F7,F82 src tests tools", "workflow_dispatch", "pull_request",
                   "cancel-in-progress", "contents: read"):
        assert needle in text, needle
    assert text.count("lint: true") == 1
    assert "Windows, Python 3.12" in text


def test_the_rollback_runbook_is_written_down():
    doc = (ROOT / "docs/DEVELOPING.md").read_text("utf-8")
    assert "## Rolling back a release" in doc and "gh release edit vX.Y.Z --prerelease" in doc
    assert doc.index("Release candidates (0.15)") < doc.index("## Rolling back a release")
    assert "releases/download/vX.Y.Z/install.sh" in doc
