"""0.13.6: 0.14.0, 0.15.0 and 0.15.1 were withdrawn (their changes are part of 0.13.6).

- a copy of a withdrawn version that is still running counts as older, so the icon stops it and starts this one;
- the changelog lists no withdrawn version as a release, and its versions go down from the top.

0.15: a withdrawn number counts as older only while this version is below it, so 0.15.0 and 0.15.1 can be released
for real without changing the list first; such a release stands in the changelog above the withdrawal (0.14.x).
"""
from __future__ import annotations

import sys
from pathlib import Path

from enlens_claims import __version__

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import release  # noqa: E402


def test_a_withdrawn_version_still_running_counts_as_older():
    from enlens_claims import update
    from enlens_claims.gui import launcher

    assert update.WITHDRAWN == set()  # 0.14.0 (shared projects), 0.15.0 (the new reader), 0.15.1 (reader 3): releases
    for v in update.WITHDRAWN:
        above = update.version_tuple(v) > update.version_tuple(__version__)
        assert launcher.is_older({"version": v}) == above, v  # 0.15: released for real, a number is a number again
    assert not launcher.is_older({"version": "0.15.1"}) or update.version_tuple(__version__) > (0, 15, 1)
    assert not launcher.is_older({"version": __version__})
    assert launcher.is_older({"version": "0.13.5"})
    assert not launcher.is_older({"version": "9.0.0"})  # a later number is a later version again
    assert launcher.is_older({"version": "0.16.0"}) == (update.version_tuple(__version__) > (0, 16, 0))


def test_the_changelog_lists_no_withdrawn_version():
    from enlens_claims import update
    from enlens_claims.update import version_tuple

    versions = release.changelog_versions()
    # 0.18.1 (J1.3): the version is made from the git tag, so a commit after a tag is "0.18.0.post3", and the changelog
    # may already hold the entry of the release being prepared (the release pull request, before its tag)
    assert update.version_tuple(versions[0]) >= update.version_tuple(__version__)
    for v in set(versions) & update.WITHDRAWN:  # 0.15: only a release of that number made after the withdrawal
        assert versions.index(v) < versions.index("0.14.6"), v
    assert [version_tuple(v) for v in versions] == sorted((version_tuple(v) for v in versions), reverse=True)
    assert len(set(versions)) == len(versions)
