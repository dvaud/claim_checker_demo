"""0.18.0: what copies exchange says which format it is written in, and the oldest format that merges it right.

A copy refuses, in words, a file a newer format would make it merge wrongly; it reads every older file (0.14 to 0.17
wrote no number: format 1), and the app's own version never decides it, so a release candidate and the stable release
sync with each other.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from enlens_claims import sync
from enlens_claims.sync import formats
from test_0_14_0_shared_projects import CLAIM, Person, anna_and_ben  # noqa: F401  (fixture)


def _rewrite(f: Path, out: Path, change) -> Path:
    """A copy of the project zip `f` whose bundle.json is changed by `change(meta)`."""
    with zipfile.ZipFile(f) as zin, zipfile.ZipFile(out, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "bundle.json":
                meta = json.loads(data)
                change(meta)
                data = json.dumps(meta).encode()
            zout.writestr(item, data)
    return out


def test_a_project_zip_says_its_format(anna_and_ben):
    anna, _ben = anna_and_ben
    info = sync.peek(anna.send())
    assert info["sync_format"] == formats.FORMAT == 4  # roles (DESIGN-roles §3.3): format 4
    # roles (DESIGN-roles §3.3): a zip of a project with an owner (Anna made and sent it) needs format 4, so a copy on
    # 0.17 refuses it in words; a project with no owner still says ZIP_NEEDS (formats.zip_needs)
    assert info["sync_needs"] == formats.OWNED_ZIP_NEEDS == 4 and formats.ZIP_NEEDS == 1
    assert info["scope"] == "all"


def test_a_file_of_a_newer_format_is_refused_in_words_and_changes_nothing(anna_and_ben, tmp_path):
    anna, ben = anna_and_ben
    with anna:
        from enlens_claims import claimcheck

        claimcheck.set_note(anna.ws, anna.hid, "Anna's note")
    f = _rewrite(anna.send(), tmp_path / "newer.zip",
                 lambda m: m.update(sync_format=7, sync_needs=formats.FORMAT + 1, version="0.21.0"))
    with ben:
        before = ben.ws.counts()
    for anyway in (False, True):  # "bring it in anyway" is about another project, never about a newer format
        with pytest.raises(ValueError) as e:
            ben.bring_in(f, anyway=anyway)
        assert "newer ENLENS (0.21.0)" in str(e.value) and "Update ENLENS" in str(e.value)
        assert "Nothing was changed" in str(e.value)
    with ben:
        assert ben.ws.counts() == before
        assert ben.ws.scalar("SELECT note FROM hypotheses WHERE hyp_id=?", (anna.hid,)) != "Anna's note"


def test_a_newer_format_that_older_copies_can_read_comes_in(anna_and_ben, tmp_path):
    anna, ben = anna_and_ben
    with anna:
        from enlens_claims import claimcheck

        claimcheck.set_note(anna.ws, anna.hid, "Anna's note")
    f = _rewrite(anna.send(), tmp_path / "later.zip", lambda m: m.update(sync_format=3, sync_needs=2))
    rep = ben.bring_in(f)
    assert rep["checks"]["updated"] == 1


def test_a_file_from_before_0_18_is_format_1_and_comes_in(anna_and_ben, tmp_path):
    anna, ben = anna_and_ben
    with anna:
        from enlens_claims import claimcheck

        claimcheck.set_note(anna.ws, anna.hid, "Anna's note")

    def as_017(m: dict) -> None:
        m.pop("sync_format", None)
        m.pop("sync_needs", None)
        m.pop("scope", None)
        m["version"] = "0.17.0rc4"

    f = _rewrite(anna.send(), tmp_path / "old.zip", as_017)
    assert sync.peek(f)["sync_format"] == 1 and sync.peek(f)["sync_needs"] == 1
    rep = ben.bring_in(f)
    assert rep["checks"]["updated"] == 1


@pytest.mark.parametrize("version", ["0.18.0rc1", "0.18.0", "0.18.3", "0.19.0rc2"])
def test_the_app_version_never_decides(version):
    """A release candidate and the stable release of one format read each other's files."""
    assert formats.problem({"version": version, **formats.stamp()}) is None
    assert formats.problem({"version": version, "sync_format": 9, "sync_needs": formats.FORMAT + 1}) is not None


def test_what_a_file_says_about_its_format_is_read_safely():
    assert formats.of(None) == (1, 1)
    assert formats.of({"sync_format": "x", "sync_needs": None}) == (1, 1)
    assert formats.of({"sync_format": 4}) == (4, 4)  # a file that does not say what it needs needs its own format
    assert formats.of({"sync_format": 4, "sync_needs": 0}) == (4, 1)
