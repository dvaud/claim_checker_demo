"""0.15.1: an update of a git copy brings the layout reader (pdfminer), as the one-line install always has; and the
version numbers: 0.15.1 is a release, so no number is withdrawn any more."""
from __future__ import annotations


def _copy(tmp_path, extras_after: str):
    root = tmp_path / "copy"
    (root / "src" / "enlens_claims").mkdir(parents=True)
    (root / "src" / "enlens_claims" / "__init__.py").write_text('__version__ = "0.15.0"\n')
    py = root / "pyproject.toml"
    py.write_text('[project]\nname = "enlens-claims"\n[project.optional-dependencies]\nconnector = ["pydantic>=2"]\n')
    calls = []

    class R:
        def __init__(self, out="", rc=0):
            self.stdout, self.stderr, self.returncode = out, "", rc

    def run(cmd, cwd):
        calls.append(cmd)
        if cmd[:2] == ["git", "status"]:
            return R("")
        if cmd[:2] == ["git", "rev-parse"]:
            return R("origin/main")
        if cmd[:2] == ["git", "rev-list"]:
            return R("1" if "HEAD..origin/main" in cmd else "0")
        if cmd[:2] == ["git", "merge"]:
            py.write_text('[project]\nname = "enlens-claims"\nversion = "0.15.1"\n[project.optional-dependencies]\n'
                          f'connector = ["pydantic>=2"]\n{extras_after}')
            (root / "src" / "enlens_claims" / "__init__.py").write_text('__version__ = "0.15.1"\n')
            return R("")
        return R("")

    return root, run, calls


def test_a_git_copy_gets_the_layout_reader_at_its_next_update(tmp_path):
    from enlens_claims import update

    root, run, calls = _copy(tmp_path, 'pdfminer = ["pdfminer.six>=20231228"]\n')
    out = update.update_git(root=root, run=run, python="py")
    assert out["reinstalled"] and out["extras"] == ["connector", "pdfminer"]
    assert any(c[-1].endswith("[connector,pdfminer]") for c in calls if c[:1] == ["py"])


def test_no_layout_extra_is_asked_for_when_the_version_has_none(tmp_path):
    from enlens_claims import update

    root, run, _calls = _copy(tmp_path, "")
    assert update.update_git(root=root, run=run, python="py")["extras"] == ["connector"]


def test_no_version_is_withdrawn_any_more():
    from enlens_claims import __version__, update
    from enlens_claims.gui import launcher

    assert update.WITHDRAWN == frozenset() and __version__ == "0.15.1"
    assert launcher.is_older({"version": "0.15.0"}) and not launcher.is_older({"version": "0.15.1"})
