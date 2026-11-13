"""The release pull request (0.18.1, roadmap J1.5, J2.5): `tools/release.py prepare` joins the fragments, writes the
README's *New in* and the app's *What's new* from the changelog entry, and makes the branch and the pull request.
Nothing here runs git or gh: the commands go to a recorder, and the files are a copy in a temporary folder."""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import release  # noqa: E402

CHANGELOG = ("# Changelog\n\n## 0.18.0 (November 2026): working together as a team\n\nThe stable 0.18.\n\n"
             "### New\n\n- **Old thing.** Cannot change results.\n")
README = (f"# ENLENS\n\n## Install\n\nText.\n\n{release.NEW_IN_START}\n## New in 0.18.0: old\n\n- **Old thing.**\n"
          f"{release.NEW_IN_END}\n\nHow it works: the manual.\n")
FRAGMENT_A = ("### New\n\n- **Theory books are a lens.** Mark a document as theory and ENLENS reads it as a lens, never as "
              "evidence. Cannot change results.\n- **Short.** Yes.\n\n### Not yet done\n\n- The AI draft.\n")
FRAGMENT_B = ("### Changes that can alter your results\n\n- **Reader 5 finds tables.** From their ruled lines, for documents "
              "you move to it (a long second sentence).\n  A second line of the same bullet. Can change results.\n\n"
              "### Fixed\n\n- **A fix.** It works now.\n")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "changes").mkdir(parents=True)
    (root / "src" / "enlens_claims" / "gui" / "static").mkdir(parents=True)
    (root / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    (root / "README.md").write_text(README, encoding="utf-8")
    (root / "changes" / "a-theory.md").write_text(FRAGMENT_A, encoding="utf-8")
    (root / "changes" / "b-reader.md").write_text(FRAGMENT_B, encoding="utf-8")
    (root / "changes" / "README.md").write_text("# not a fragment\n", encoding="utf-8")
    return root


class Recorder:
    def __init__(self, dirty: str = "", loose: str = "", heads: tuple = ("abc", "abc")):
        self.calls: list[list[str]] = []
        self.dirty, self.loose, self.heads = dirty, loose, dict(zip(("HEAD", "origin/main"), heads))

    def __call__(self, cmd, root):
        self.calls.append(list(cmd))
        if cmd[:2] == ["git", "status"]:
            return self.loose if "--untracked-files=all" in cmd else self.dirty
        if cmd[:2] == ["git", "rev-parse"]:
            return self.heads[cmd[2]]
        return ""


def test_a_dry_run_changes_nothing_and_runs_nothing(repo):
    run = Recorder()
    before = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    out = release.prepare("0.18.1", "Theory books", repo, dry_run=True, run=run)
    assert run.calls == [] and before == {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert out[0] == "git switch -c release/0.18.1" and any(s.startswith("gh pr create --base main") for s in out)
    assert "## 0.18.1 (" in "\n".join(out) and "Theory books" in "\n".join(out)


def test_the_command_line_is_a_dry_run_unless_told_otherwise(repo, monkeypatch, capsys):
    monkeypatch.setattr(release, "ROOT", repo)
    monkeypatch.setattr(release, "prepare",
                        lambda v, t, root=None, dry_run=True, run=None: [f"dry_run={dry_run}"])
    assert release.main(["prepare", "0.18.1", "A title"]) == 0
    assert "dry_run=True" in capsys.readouterr().out
    assert release.main(["prepare", "0.18.1", "A title", "--dry-run"]) == 0
    assert "dry_run=True" in capsys.readouterr().out
    assert release.main(["prepare", "0.18.1", "A title", "--go"]) == 0
    assert "dry_run=False" in capsys.readouterr().out


def test_prepare_makes_the_branch_the_files_the_commit_and_the_pull_request(repo):
    run = Recorder()
    release.prepare("0.18.1", "Theory books", repo, dry_run=False, run=run)
    cmds = [" ".join(c[:3]) for c in run.calls]
    assert cmds == ["git status --porcelain", "git fetch --quiet", "git rev-parse HEAD", "git rev-parse origin/main",
                    "git status --porcelain", "git switch -c", "git add CHANGELOG.md", "git commit -m",
                    "git push -u", "gh pr create"]
    assert run.calls[5][-1] == "release/0.18.1"
    assert run.calls[8][-2:] == ["origin", "release/0.18.1"]
    pr = run.calls[9]
    assert pr[pr.index("--base") + 1] == "main" and pr[pr.index("--head") + 1] == "release/0.18.1"
    assert pr[pr.index("--title") + 1] == "ENLENS 0.18.1"
    # the three files were written from the one entry, and the fragments are gone
    log = (repo / "CHANGELOG.md").read_text("utf-8")
    assert log.startswith("# Changelog\n\n## 0.18.1 (") and "Theory books\n" in log and release.fragment_files(repo) == []
    readme = (repo / "README.md").read_text("utf-8")
    assert "## New in 0.18.1: Theory books" in readme and "How it works: the manual." in readme
    assert "Old thing" not in readme and readme.count(release.NEW_IN_END) == 1
    note = (repo / release.WHATS_NEW).read_text("utf-8")
    assert note.startswith("# 0.18.1: Theory books\n*")


def test_prepare_refuses_a_dirty_tree_and_a_version_that_is_not_new(repo):
    with pytest.raises(release.ReleaseError, match="working tree has changes"):
        release.prepare("0.18.1", "t", repo, dry_run=False, run=Recorder(dirty=" M src/x.py"))
    with pytest.raises(release.ReleaseError, match="from main as it is on GitHub"):  # a feature branch, or main behind
        release.prepare("0.18.1", "t", repo, dry_run=False, run=Recorder(heads=("abc", "def")))
    with pytest.raises(release.ReleaseError, match="not committed"):  # another session's fragment, not committed yet
        release.prepare("0.18.1", "t", repo, dry_run=False, run=Recorder(loose="?? changes/a-other.md"))
    assert (repo / "changes" / "a-theory.md").exists()           # nothing was joined
    with pytest.raises(release.ReleaseError, match="already has an entry"):
        release.prepare("0.18.0", "t", repo, dry_run=True)
    with pytest.raises(release.ReleaseError, match="not of the form"):
        release.prepare("0.18", "t", repo, dry_run=True)
    shutil.rmtree(repo / "changes")
    with pytest.raises(release.ReleaseError, match="no fragments"):
        release.prepare("0.18.1", "t", repo, dry_run=True)


def test_new_in_is_the_entrys_bullets_with_whether_they_can_change_results(repo):
    release.join_fragments("0.18.1", "Theory books", repo, month="November 2026")
    block = release.readme_new_in("0.18.1", repo)
    lines = block.splitlines()
    assert lines[0] == release.NEW_IN_START and lines[1] == "## New in 0.18.1: Theory books" and lines[-1] == release.NEW_IN_END
    bullets = [ln for ln in lines if ln.startswith("- ")]
    # New first, then the changes that can alter results; the fix and "Not yet done" are not New
    assert [re.match(r"- \*\*(.+?)\*\*", b).group(1) for b in bullets] == [
        "Theory books are a lens.", "Short.", "Reader 5 finds tables."]
    assert bullets[0].endswith("Cannot change results.") or "Cannot change results" in bullets[0]
    assert bullets[2].endswith("Can change results.")           # said in the second line of the bullet: carried over
    assert all(len(b) < 260 for b in bullets)


def test_what_is_new_is_a_note_the_app_can_read(repo):
    from enlens_claims.gui.server import parse_whats_new

    release.join_fragments("0.18.1", "theory books", repo, month="November 2026")
    text = release.whats_new_text("0.18.1", repo)
    note = parse_whats_new(text)
    assert note and note["version"] == "0.18.1" and note["title"] == "Theory books"
    assert note["subtitle"] == release.NO_SUBTITLE             # no opening paragraph yet: written by hand later
    assert note["points"] == ["Theory books are a lens", "Short", "Reader 5 finds tables"]
    # an opening paragraph written by hand gives the subtitle
    log = (repo / "CHANGELOG.md").read_text("utf-8").replace("theory books\n", "theory books\n\nTheory books are a lens for reading the documents. And more.\n", 1)
    (repo / "CHANGELOG.md").write_text(log, encoding="utf-8")
    assert parse_whats_new(release.whats_new_text("0.18.1", repo))["subtitle"] == "Theory books are a lens for reading the documents."


def test_a_long_first_sentence_is_cut_at_a_clause_never_inside_a_bracket():
    text = ("The place where the team works (storage space or shared folder, with *Technical details*), the people with "
            "their roles and a long list of other things that goes on and on and on and on, again and again. Next.")
    cut = release._first_sentence(text, 120)
    assert cut.endswith(".") and cut.count("(") == cut.count(")") and cut.count("*") % 2 == 0 and len(cut) <= 125
    assert release._first_sentence("(roadmap N1). Under the box, as a list is typed.") == "(roadmap N1). Under the box, as a list is typed."


def test_sync_notes_rewrites_and_checks(repo):
    release.join_fragments("0.18.1", "Theory books", repo, month="November 2026")
    assert release.sync_notes(root=repo, check_only=True) == ["README.md", str(release.WHATS_NEW).replace("\\", "/")]
    assert release.sync_notes(root=repo) == ["README.md", str(release.WHATS_NEW).replace("\\", "/")]
    assert release.sync_notes(root=repo, check_only=True) == []
    assert release.sync_notes(root=repo) == []                   # nothing left to write
    (repo / "README.md").write_text((repo / "README.md").read_text("utf-8").replace("lens", "LENS", 1), encoding="utf-8")
    assert release.sync_notes(root=repo, check_only=True) == ["README.md"]
    (repo / "README.md").write_text("# ENLENS\n", encoding="utf-8")
    with pytest.raises(release.ReleaseError, match="no <!-- new-in:start"):
        release.sync_notes(root=repo)


def test_the_pull_request_text_says_what_merging_does():
    body = release.pull_request_body("0.18.1", "Theory books")
    assert "v0.18.1" in body and "sync-notes" in body and "Tests run" in body
