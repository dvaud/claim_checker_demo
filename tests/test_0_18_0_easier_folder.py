"""0.18.0rc2 (roadmap L7): an easier shared folder. The system's folder window (gui/folder_picker.py), the cloud folders
offered by name and the team's folder found among them (sync/cloud_folders.py), their endpoints, and the Team tab's
set-up. Stand-in programs play the folder windows and fake home folders hold the cloud folders: no test opens a real
dialog or reads a real cloud folder."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from enlens_claims.gui import folder_picker
from enlens_claims.sync import cloud_folders
from test_app import api, home  # noqa: F401  (fixtures)

STATIC = Path(__file__).resolve().parents[1] / "src" / "enlens_claims" / "gui" / "static"
TEAM = (STATIC / "views" / "team.js").read_text(encoding="utf-8")
STATE = (STATIC / "views" / "team-state.js").read_text(encoding="utf-8")
VIEWS = (STATIC / "views.css").read_text(encoding="utf-8")

posix_only = pytest.mark.skipif(os.name == "nt", reason="the stand-in programs are shell-style scripts")


def _program(tmp_path: Path, name: str, body: str) -> Path:
    prog = tmp_path / name
    prog.write_text(f"#!{sys.executable}\nimport sys\n{body}\n")
    prog.chmod(0o755)
    return prog


# ------------------------------------------------------------------ the folder window
@posix_only
def test_the_macos_window_gets_the_prompt_and_gives_a_path(tmp_path, monkeypatch):
    log = tmp_path / "argv.json"
    prog = _program(tmp_path, "osascript", f"import json; json.dump(sys.argv[1:], open({str(log)!r}, 'w'))\n"
                    "sys.stdout.buffer.write('/Users/Dávid/Library/CloudStorage/OneDrive-Közös/\\n'.encode('utf-8'))")
    monkeypatch.setenv("ENLENS_OSASCRIPT", str(prog))
    monkeypatch.setattr(folder_picker.sys, "platform", "darwin")
    assert folder_picker.available()
    start = tmp_path / "start"
    start.mkdir()
    assert folder_picker.choose_folder('Choose "the" folder', str(start)) == "/Users/Dávid/Library/CloudStorage/OneDrive-Közös"
    argv = json.loads(log.read_text())
    assert argv[0] == "-e" and "choose folder" in argv[1] and argv[2:] == ['Choose "the" folder', str(start)]


@posix_only
def test_cancelled_failed_and_missing_windows_give_none(tmp_path, monkeypatch):
    monkeypatch.setattr(folder_picker.sys, "platform", "darwin")
    cancel = _program(tmp_path, "cancel", "sys.stderr.write('execution error: User canceled. (-128)\\n'); sys.exit(1)")
    monkeypatch.setenv("ENLENS_OSASCRIPT", str(cancel))
    assert folder_picker.choose_folder("Choose") is None
    monkeypatch.setenv("ENLENS_OSASCRIPT", str(tmp_path / "nowhere"))
    assert not folder_picker.available() and folder_picker.choose_folder("Choose") is None


@posix_only
def test_a_linux_window_and_one_window_at_a_time(tmp_path, monkeypatch):
    prog = _program(tmp_path, "zenity", "sys.stdout.write('/home/anna/Team folder\\n')")
    monkeypatch.setenv("ENLENS_ZENITY", str(prog))
    monkeypatch.setattr(folder_picker.sys, "platform", "linux")
    assert folder_picker.available() and folder_picker.choose_folder("Choose") == "/home/anna/Team folder"
    assert folder_picker._lock.acquire(blocking=False)
    try:
        with pytest.raises(folder_picker.Busy):
            folder_picker.choose_folder("Again")
    finally:
        folder_picker._lock.release()


def test_no_window_on_a_computer_without_one(monkeypatch, tmp_path):
    monkeypatch.setattr(folder_picker.sys, "platform", "linux")
    for k in ("ENLENS_ZENITY", "ENLENS_KDIALOG"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert not folder_picker.available() and folder_picker.choose_folder("Choose") is None


def test_the_windows_command_is_hidden_and_reads_its_words_from_the_environment(monkeypatch, tmp_path):
    cmd, extra = folder_picker._command("windows", "powershell.exe", "Choose the folder – Dávid", "C:\\Users\\Dávid")
    assert "-STA" in cmd and "-EncodedCommand" in cmd and "-NoProfile" in cmd and "Hidden" in cmd
    assert extra == {"ENLENS_PICK_PROMPT": "Choose the folder – Dávid", "ENLENS_PICK_START": "C:\\Users\\Dávid"}
    assert "UTF8Encoding" in folder_picker.WINDOWS_SCRIPT and "FolderBrowserDialog" in folder_picker.WINDOWS_SCRIPT
    assert "creationflags" not in str(extra)
    src = (Path(folder_picker.__file__)).read_text(encoding="utf-8")
    assert "**no_window()" in src   # no console window on Windows


# ------------------------------------------------------------------ the cloud folders
def _tree(root: Path, *folders: str) -> None:
    for f in folders:
        (root / f).mkdir(parents=True, exist_ok=True)


def test_a_mac_offers_the_cloud_storage_folders_by_name(tmp_path):
    _tree(tmp_path, "Library/CloudStorage/OneDrive-Personal", "Library/CloudStorage/OneDrive-UniversityofAmsterdam",
          "Library/CloudStorage/GoogleDrive-anna@example.org", "Library/CloudStorage/Box-Box", "Library/CloudStorage/.hidden",
          "Dropbox", "Documents")
    (tmp_path / "Library/CloudStorage/a file").write_text("x")
    got = cloud_folders.offered(tmp_path, "darwin")
    names = [(f["name"], f["service"]) for f in got]
    assert names == [("OneDrive – Personal", "onedrive"), ("OneDrive – UniversityofAmsterdam", "onedrive"),
                     ("Google Drive – anna@example.org", "googledrive"), ("Box", "box"), ("Dropbox", "dropbox")]
    assert got[-1]["path"] == str(tmp_path / "Dropbox")


def test_windows_cloud_folders_come_from_the_environment_and_dropbox_info(tmp_path, monkeypatch):
    one = tmp_path / "Dávid" / "OneDrive - University of Amsterdam"
    consumer = tmp_path / "Dávid" / "OneDrive"
    _tree(tmp_path, "Dávid/OneDrive - University of Amsterdam", "Dávid/OneDrive", "Dropbox (Business)", "Dropbox (Personal)")
    appdata = tmp_path / "Roaming"
    (appdata / "Dropbox").mkdir(parents=True)
    (appdata / "Dropbox" / "info.json").write_text(json.dumps({"personal": {"path": str(tmp_path / "Dropbox (Personal)")},
                                                               "business": {"path": str(tmp_path / "Dropbox (Business)")}}),
                                                   encoding="utf-8")
    monkeypatch.setenv("OneDrive", str(consumer))
    monkeypatch.setenv("OneDriveCommercial", str(one))
    monkeypatch.setenv("OneDriveConsumer", str(consumer))   # the same folder as %OneDrive%: listed once
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    got = cloud_folders.offered(tmp_path, "win32")
    assert [f["name"] for f in got] == ["OneDrive", "OneDrive – University of Amsterdam", "Dropbox", "Dropbox – business"]
    assert [f["service"] for f in got] == ["onedrive", "onedrive", "dropbox", "dropbox"]


def test_linux_offers_dropbox_from_its_home_and_its_info(tmp_path, monkeypatch):
    _tree(tmp_path, "Dropbox", "Elsewhere/Work box", ".dropbox")
    (tmp_path / ".dropbox" / "info.json").write_text(json.dumps({"business": {"path": str(tmp_path / "Elsewhere/Work box")}}))
    monkeypatch.setenv("ENLENS_CLOUD_HOME", str(tmp_path))   # the home folder can come from the environment
    assert [f["name"] for f in cloud_folders.offered(platform="linux")] == ["Dropbox", "Dropbox – business"]
    assert cloud_folders.offered(tmp_path / "nowhere", "linux") == []


def test_the_team_folder_is_found_a_few_levels_down(tmp_path):
    _tree(tmp_path, "Library/CloudStorage/OneDrive-Uni/Projects/Water/ENLENS-ab12cd34", "Library/CloudStorage/OneDrive-Uni/.git/ENLENS-ab12cd34",
          "Library/CloudStorage/OneDrive-Uni/a/b/c/d/ENLENS-ab12cd34", "Dropbox/Other", "Dropbox/Teams/ENLENS-ab12cd34")
    got = cloud_folders.find_team("ENLENS-ab12cd34", home=tmp_path, platform="darwin")
    root = tmp_path / "Library/CloudStorage/OneDrive-Uni"
    assert got == [str(root / "Projects" / "Water"), str(tmp_path / "Dropbox" / "Teams")]   # the folders that hold it
    assert cloud_folders.find_team("ENLENS-ab12cd34", depth=1, home=tmp_path, platform="darwin") == [str(tmp_path / "Dropbox" / "Teams")]
    assert cloud_folders.find_team("ENLENS-ffffffff", home=tmp_path, platform="darwin") == []
    assert cloud_folders.find_team("", home=tmp_path, platform="darwin") == []
    assert cloud_folders.find_team("ENLENS-ab12cd34", home=tmp_path, platform="darwin", budget=-1) == []   # out of time


# ------------------------------------------------------------------ the endpoints
def test_the_endpoints(api, tmp_path, monkeypatch):  # noqa: F811
    fake_home = tmp_path / "fake-home"
    _tree(fake_home, "Dropbox/Teams")
    monkeypatch.setenv("ENLENS_CLOUD_HOME", str(fake_home))
    monkeypatch.setattr(cloud_folders.sys, "platform", "linux")
    monkeypatch.setattr(folder_picker.sys, "platform", "linux")
    monkeypatch.delenv("ENLENS_ZENITY", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))   # no folder window on this "computer"
    monkeypatch.delenv("DISPLAY", raising=False)
    st, r = api("GET", "/api/cloud-folders")
    assert st == 200 and [f["name"] for f in r["folders"]] == ["Dropbox"] and r["picker"] is False
    assert api("POST", "/api/choose-folder", {"prompt": "x"}) == (200, {"path": None, "available": False})

    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    from enlens_claims import home as home_mod
    from enlens_claims.sync import folder

    team = folder.team_name(home_mod.open_project("Demo"))
    st, r = api("GET", "/api/projects/Demo/shared-folder/find")
    assert st == 200 and r == {"found": [], "team": team} and team.startswith("ENLENS-") and len(team) == 15
    (fake_home / "Dropbox" / "Teams" / team).mkdir()
    st, r = api("GET", "/api/projects/Demo/shared-folder/find")
    assert r["found"] == [str(fake_home / "Dropbox" / "Teams")]
    # the found folder is one the project can use
    st, r = api("PUT", "/api/projects/Demo/shared-folder", {"path": r["found"][0]})
    assert st == 200 and r["folder"] == str((fake_home / "Dropbox" / "Teams").resolve())
    assert api("GET", "/api/projects/Nobody/shared-folder/find")[0] == 404


@posix_only
def test_the_folder_window_through_the_endpoint(api, tmp_path, monkeypatch):  # noqa: F811
    prog = _program(tmp_path, "zenity", "sys.stdout.write('/home/anna/Team\\n')")
    monkeypatch.setenv("ENLENS_ZENITY", str(prog))
    monkeypatch.setattr(folder_picker.sys, "platform", "linux")
    st, r = api("GET", "/api/cloud-folders")
    assert r["picker"] is True
    assert api("POST", "/api/choose-folder", {"prompt": "Choose"}) == (200, {"path": "/home/anna/Team", "available": True})
    assert folder_picker._lock.acquire(blocking=False)
    try:
        st, r = api("POST", "/api/choose-folder", {})
        assert st == 409 and "already open" in r["error"]
    finally:
        folder_picker._lock.release()


# ------------------------------------------------------------------ the Team tab
NODE = r"""
import { folderAsSeen } from "./team-state.js";
const clouds = [{ name: "OneDrive – University of Amsterdam", path: "/Users/a/Library/CloudStorage/OneDrive-UniversityofAmsterdam" },
  { name: "Dropbox", path: "/Users/a/Dropbox" }, { name: "OneDrive", path: "C:\\Users\\Dávid\\OneDrive" }];
console.log(JSON.stringify([
  folderAsSeen("/Users/a/Library/CloudStorage/OneDrive-UniversityofAmsterdam/Water/Team", clouds).text,
  folderAsSeen("/Users/a/Dropbox", clouds).text,
  folderAsSeen("c:\\users\\dávid\\onedrive\\Our project\\", clouds).text,
  folderAsSeen("/Volumes/Share/Group/Team", clouds).text,
  folderAsSeen("/Users/a/DropboxOld/x", clouds).cloud,
]));
"""


def test_a_folder_is_named_as_a_colleague_sees_it(tmp_path):
    if shutil.which("node") is None:
        pytest.skip("Node is not installed")
    (tmp_path / "package.json").write_text('{"type": "module"}')
    (tmp_path / "team-state.js").write_text(STATE, encoding="utf-8")
    (tmp_path / "run.mjs").write_text(NODE, encoding="utf-8")
    r = subprocess.run([shutil.which("node"), str(tmp_path / "run.mjs")], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ["OneDrive – University of Amsterdam › Water › Team", "Dropbox", "OneDrive › Our project",
                                    "Group › Team", None]   # a folder in no cloud folder: its last two names


def test_the_set_up_offers_the_folders_the_window_and_what_to_do():
    assert '"/api/cloud-folders"' in TEAM and "/shared-folder/find" in TEAM and '"/api/choose-folder"' in TEAM
    assert "Choose folder…" in TEAM and "Your colleague’s shared folder is here:" in TEAM and '"Use it"' in TEAM
    assert "Cloud folders on this computer" in TEAM
    assert "Add shortcut to My files" in TEAM and "Always keep on this device" in TEAM and "keep the folder available offline" in TEAM
    assert "if (o.picker)" in TEAM          # no button on a computer without a folder window
    assert "e.status === 409" in TEAM
    assert "team-use-folder" in TEAM and 'placeholder: example' in TEAM   # the pasted path stays
    assert "this tab offers the shared folder" in TEAM and "folderAsSeen(st.folder" in TEAM
    assert ".team-cloud" in VIEWS
