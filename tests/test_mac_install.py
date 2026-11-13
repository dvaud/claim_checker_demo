"""0.14.1: the one-line install on a Mac.

`curl -fsSL …/install.sh | sh` stopped after its first step on most Macs since 0.10.0: macOS's sh is bash 3.2, and in
a UTF-8 language setting (what a Mac's Terminal sets, such as en_US.UTF-8) it took the ellipsis printed right after
$VERSION for part of the variable's name, so `set -u` ended the script ("VERSION…: unbound variable"). Only
`… | LC_ALL=C sh` got through. Linux's sh never did this, which is why the release CI (tests on Linux; the macOS job
installs a local package and skips the download step) did not see it.

- install.sh is plain ASCII, so no character can run into a name again, whatever shell reads it;
- piped into sh as the install line does, in UTF-8 language settings, it downloads, checks and installs (stand-ins
  for uv and curl, as in test_setup_and_moving.py; no network);
- a script error ends as a failure: macOS's sh ran the clean-up trap after an unbound variable with $? already 0, so
  the broken install line even ended "successfully". The temporary folder goes either way.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from test_setup_and_moving import ROOT, sandbox  # noqa: F401  (fixture)


def test_install_sh_is_plain_ascii():
    data = (ROOT / "install" / "install.sh").read_bytes()
    assert data.isascii(), [n for n, line in enumerate(data.splitlines(), 1) if not line.isascii()]


def _ready(tmp: Path, env: dict, lang: str | None = None) -> str:
    """The install line's script (version 0.14.1), a package and its checksum to download, its own TMPDIR."""
    if lang:
        env.update(LANG=lang, LC_ALL=lang)
    (tmp / "tmpdir").mkdir()
    env["TMPDIR"] = str(tmp / "tmpdir")
    wheel = Path(env["FAKE_DL"]) / "enlens_claims-0.14.1-py3-none-any.whl"
    wheel.write_bytes(b"PK the package")
    (Path(env["FAKE_DL"]) / "SHA256SUMS").write_text(f"{hashlib.sha256(wheel.read_bytes()).hexdigest()}  {wheel.name}\n")
    return (ROOT / "install" / "install.sh").read_text("ascii").replace("@ENLENS_VERSION@", "0.14.1")


@pytest.mark.parametrize("lang", ["en_US.UTF-8", "hu_HU.UTF-8"])
def test_the_install_line_in_a_utf8_language_setting(sandbox, lang):  # noqa: F811
    tmp, env = sandbox
    text = _ready(tmp, env, lang)
    r = subprocess.run(["sh"], input=text, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr + r.stdout
    assert not list((tmp / "tmpdir").iterdir())  # the temporary folder is gone
    assert "unbound variable" not in r.stderr
    assert "2/4  Downloading ENLENS 0.14.1...\n" in r.stdout and "Done." in r.stdout
    log = (tmp / "log").read_text().splitlines()
    assert any(x.endswith("releases/download/v0.14.1/enlens_claims-0.14.1-py3-none-any.whl") for x in log)
    assert any(" tool install " in x for x in log)
    assert log[-1] == "enlens post-install --by script"  # ENLENS_NO_OPEN: not opened


@pytest.mark.parametrize("error", ['say "$NOT_SET"', "false", 'fail "a test"'])
def test_a_script_error_ends_as_a_failure(sandbox, error):  # noqa: F811
    tmp, env = sandbox
    text = _ready(tmp, env, "en_US.UTF-8")
    step3 = 'say "3/4  Installing ENLENS'
    assert text.count(step3) == 1
    r = subprocess.run(["sh"], input=text.replace(step3, error + "\n" + step3), env=env, capture_output=True,
                       text=True, timeout=60)
    assert r.returncode != 0, r.stdout + r.stderr
    assert "3/4" not in r.stdout and "Done." not in r.stdout
    assert not list((tmp / "tmpdir").iterdir())
    assert not any(" tool install " in x for x in (tmp / "log").read_text().splitlines())
