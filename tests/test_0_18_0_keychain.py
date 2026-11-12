"""0.18.0rc2: the system keychains (keychain.py). Stand-in programs for `security` and `secret-tool` keep their items in
a file and record what they were given, so no test touches a real keychain; the Windows Credential Manager is tried for
real, on Windows only (a throw-away runner)."""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import pytest

from enlens_claims import keychain

posix_only = pytest.mark.skipif(os.name == "nt", reason="the stand-in programs are shell-style scripts")

SECURITY = '''#!{py}
import json, os, shlex, sys
store, log = {store!r}, {log!r}
items = json.load(open(store)) if os.path.exists(store) else {{}}
def note(kind, text):
    with open(log, "a") as f:
        f.write(json.dumps({{"kind": kind, "text": text}}) + "\\n")
note("argv", " ".join(sys.argv[1:]))
if os.environ.get("FAKE_FAIL"):
    sys.stderr.write("security: SecKeychainAddGenericPassword: User interaction is not allowed.\\n")
    sys.exit(36)
if sys.argv[1:2] == ["-i"]:
    for line in sys.stdin.read().splitlines():
        note("stdin", line)
        w = shlex.split(line)
        if w[0] == "add-generic-password":
            items[w[w.index("-a") + 1]] = w[w.index("-w") + 1]
elif sys.argv[1] == "find-generic-password":
    a = sys.argv[sys.argv.index("-a") + 1]
    if a not in items:
        sys.stderr.write("could not be found\\n"); sys.exit(44)
    print(items[a])
elif sys.argv[1] == "delete-generic-password":
    items.pop(sys.argv[sys.argv.index("-a") + 1], None)
json.dump(items, open(store, "w"))
'''

SECRET_TOOL = '''#!{py}
import json, os, sys
store, log = {store!r}, {log!r}
items = json.load(open(store)) if os.path.exists(store) else {{}}
with open(log, "a") as f:
    f.write(json.dumps({{"kind": "argv", "text": " ".join(sys.argv[1:])}}) + "\\n")
if os.environ.get("FAKE_FAIL") and sys.argv[1] == "store":
    sys.stderr.write("Cannot autolaunch D-Bus\\n"); sys.exit(1)
a = sys.argv[-1]
if sys.argv[1] == "store":
    items[a] = sys.stdin.read()
elif sys.argv[1] == "lookup":
    if a not in items:
        sys.exit(1)
    sys.stdout.write(items[a])
elif sys.argv[1] == "clear":
    items.pop(a, None)
json.dump(items, open(store, "w"))
'''


def _stand_in(tmp_path: Path, template: str, name: str) -> tuple[Path, Path]:
    prog = tmp_path / name
    log = tmp_path / f"{name}.log"
    prog.write_text(template.format(py=sys.executable, store=str(tmp_path / f"{name}.json"), log=str(log)))
    prog.chmod(0o755)
    return prog, log


@pytest.fixture
def system(monkeypatch):
    monkeypatch.delenv("ENLENS_KEYCHAIN", raising=False)
    monkeypatch.delenv("FAKE_FAIL", raising=False)
    keychain._tool_answers.clear()


def _records(log: Path, kind: str) -> list[str]:
    return [json.loads(x)["text"] for x in log.read_text().splitlines() if json.loads(x)["kind"] == kind]


def test_forced_file_backend():
    assert os.environ["ENLENS_KEYCHAIN"] == "file"
    assert keychain.backend() == "file"
    keychain.put("a", "s1")
    assert keychain.get("a") == "s1"
    keychain.delete("a")
    assert keychain.get("a") is None


@posix_only
def test_macos_secret_never_on_a_command_line(tmp_path, monkeypatch, system):
    prog, log = _stand_in(tmp_path, SECURITY, "security")
    monkeypatch.setenv("ENLENS_SECURITY", str(prog))
    monkeypatch.setattr(keychain.sys, "platform", "darwin")
    assert keychain.backend() == "macos"
    secret = 'pa ss"w\\ord é\nsecond line 0123456789abcdef'
    keychain.put("space-key", secret)
    assert keychain.get("space-key") == secret
    argv = " ".join(_records(log, "argv"))
    assert "pa ss" not in argv and "second line" not in argv and secret not in argv
    stdin = _records(log, "stdin")
    assert len(stdin) == 1 and stdin[0].startswith("add-generic-password -U -s ENLENS -a \"space-key\" -w ")
    assert "pa ss" not in stdin[0]   # base64, so no character can upset the parser
    assert not (keychain._file("space-key")).exists()   # nothing was written to the file
    keychain.put("space-key", "second")
    assert keychain.get("space-key") == "second"
    keychain.delete("space-key")
    assert keychain.get("space-key") is None


@posix_only
def test_macos_refusal_falls_back_to_the_file(tmp_path, monkeypatch, system):
    prog, log = _stand_in(tmp_path, SECURITY, "security")
    monkeypatch.setenv("ENLENS_SECURITY", str(prog))
    monkeypatch.setattr(keychain.sys, "platform", "darwin")
    keychain.put("k", "in the keychain")
    monkeypatch.setenv("FAKE_FAIL", "1")
    keychain.put("k", "newer, in the file")
    monkeypatch.delenv("FAKE_FAIL")
    assert keychain.get("k") == "newer, in the file"   # the file's newer secret is not hidden by the old one
    keychain.delete("k")
    assert keychain.get("k") is None and not keychain._file("k").exists()


@posix_only
def test_missing_security_program_falls_back(tmp_path, monkeypatch, system):
    monkeypatch.setenv("ENLENS_SECURITY", str(tmp_path / "nowhere"))
    monkeypatch.setattr(keychain.sys, "platform", "darwin")
    keychain.put("k", "v")
    assert keychain.get("k") == "v"


@posix_only
def test_secret_tool_on_linux(tmp_path, monkeypatch, system):
    prog, log = _stand_in(tmp_path, SECRET_TOOL, "secret-tool")
    monkeypatch.setenv("ENLENS_SECRET_TOOL", str(prog))
    monkeypatch.setattr(keychain.sys, "platform", "linux")
    assert keychain.backend() == "secret-tool"
    keychain.put("k", "tooth secret é")
    assert keychain.get("k") == "tooth secret é"
    assert "tooth" not in " ".join(_records(log, "argv"))
    keychain.delete("k")
    assert keychain.get("k") is None
    monkeypatch.setenv("FAKE_FAIL", "1")
    keychain.put("k2", "kept in a file")
    monkeypatch.delenv("FAKE_FAIL")
    assert keychain.get("k2") == "kept in a file"


def test_linux_without_secret_tool_uses_files(tmp_path, monkeypatch, system):
    monkeypatch.setenv("ENLENS_SECRET_TOOL", str(tmp_path / "nowhere"))
    monkeypatch.setattr(keychain.sys, "platform", "linux")
    assert keychain.backend() == "file"
    keychain.put("k", "v")
    assert keychain.get("k") == "v"


def test_windows_credential_manager_for_real():
    if sys.platform != "win32":
        pytest.skip("Windows only: the Credential Manager")
    name = "test-" + uuid.uuid4().hex
    secret = "Dávid ő secret " + uuid.uuid4().hex
    try:
        os.environ.pop("ENLENS_KEYCHAIN", None)
        assert keychain.backend() == "windows"
        keychain.put(name, secret)
        assert keychain.get(name) == secret
        assert not keychain._file(name).exists()
        keychain.put(name, "second")
        assert keychain.get(name) == "second"
        keychain.put(name, "x" * 2561)   # longer than the Credential Manager takes: kept in the file, never lost
        assert keychain.get(name) == "x" * 2561 and keychain._file(name).exists()
        keychain.put(name, "y" * 2560)
        assert keychain.get(name) == "y" * 2560
    finally:
        keychain.delete(name)
        os.environ["ENLENS_KEYCHAIN"] = "file"
