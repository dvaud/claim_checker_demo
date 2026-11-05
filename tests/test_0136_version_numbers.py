"""0.13.6: 0.14.0, 0.15.0 and 0.15.1 were withdrawn (their changes are part of 0.13.6).

- a copy of a withdrawn version that is still running counts as older, so the icon stops it and starts this one;
- the changelog lists no withdrawn version as a release, and its versions go down from the top.
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

    assert update.WITHDRAWN == {"0.14.0", "0.15.0", "0.15.1"}
    for v in update.WITHDRAWN:
        assert launcher.is_older({"version": v}), v
    assert __version__ not in update.WITHDRAWN
    assert not launcher.is_older({"version": __version__})
    assert launcher.is_older({"version": "0.13.5"})
    assert not launcher.is_older({"version": "0.16.0"})  # a later number is a later version again


def test_the_changelog_lists_no_withdrawn_version():
    from enlens_claims import update
    from enlens_claims.update import version_tuple

    versions = release.changelog_versions()
    assert versions[0] == __version__
    assert not set(versions) & update.WITHDRAWN
    assert [version_tuple(v) for v in versions] == sorted((version_tuple(v) for v in versions), reverse=True)
    assert len(set(versions)) == len(versions)
