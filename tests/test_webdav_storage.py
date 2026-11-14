"""14 November 2026 (roadmap L6): the institution's drive over WebDAV (SURFdrive, SURF Research Drive, a Nextcloud) as
the team's storage space. `WebDAVStorage` (storage.py), `webdav.py` and the space's set-up, invites, joining, removing
and moving, against a stand-in drive (tests/fake_webdav.py): never the network, never a real account.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from enlens_claims import claimcheck, keychain, sharing
from enlens_claims import home as enlens_home
from enlens_claims.llm import BaselineBackend
from enlens_claims.sync import folder, space, webdav
from enlens_claims.sync.storage import (DENIED, FULL, MAINTENANCE, NOT_FOUND, TOO_LARGE, StorageProblem,
                                        WebDAVStorage)
from test_app import api, home  # noqa: F401  (fixtures)
from test_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)

sys.path.insert(0, str(Path(__file__).parent))
import fake_webdav  # noqa: E402

USERS = {"anna@uva.nl": "app-pw-anna", "carol": "app-pw-carol", "ben": "app-pw-ben"}


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    from enlens_claims.sync import _web

    monkeypatch.setattr(_web, "sleep", lambda s: None)


@pytest.fixture
def drive():
    srv, url = fake_webdav.start(USERS)
    srv.url = url
    srv.address = lambda user: f"{url}/remote.php/dav/files/{user}/"
    yield srv
    fake_webdav.stop(srv)


def _store(drive, user="anna@uva.nl", folder="Team folder", prefix="enlens/abc/") -> WebDAVStorage:
    drive.state.dirs.add(f"{user}/{folder}")
    return webdav.storage(drive.address(user), user, USERS[user], folder=folder, prefix=prefix)


# ---------------------------------------------------------------------------------------------
# the storage
# ---------------------------------------------------------------------------------------------
def test_write_read_list_and_remove(drive):
    s = _store(drive)
    assert s.list() == {}
    s.put("space/roster.json", b"roster")
    s.put("parts/m0123456789ab/b/000001", b"one")
    s.put("parts/m0123456789ab/b/000002", b"two" * 100)
    assert s.get("space/roster.json") == b"roster"
    listed = s.list()
    assert set(listed) == {"space/roster.json", "parts/m0123456789ab/b/000001", "parts/m0123456789ab/b/000002"}
    assert listed["parts/m0123456789ab/b/000002"].size == 300
    assert set(s.list("parts/m0123456789ab/b/")) == {"parts/m0123456789ab/b/000001", "parts/m0123456789ab/b/000002"}
    assert s.list("parts/nobody/") == {}
    before = listed["space/roster.json"].etag
    s.put("space/roster.json", b"roster 2")   # written again: a new etag
    assert s.list("space/")["space/roster.json"].etag != before and s.get("space/roster.json") == b"roster 2"
    s.delete("space/roster.json")
    s.delete("space/roster.json")   # (not there: no problem)
    with pytest.raises(StorageProblem) as e:
        s.get("space/roster.json")
    assert e.value.kind == NOT_FOUND
    with pytest.raises(StorageProblem) as e:
        s.get("parts/m0123456789ab/b/000002", max_size=10)
    assert e.value.kind == TOO_LARGE
    # the user name with @ and the folder's space travel encoded, and come back as they read
    assert any("/anna@uva.nl/Team folder/enlens/abc/" in c for c in drive.state.calls)


def test_a_file_is_written_whole_or_not_at_all(drive):
    s = _store(drive)
    s.put("space/keys.json", b"old")
    drive.state.fail["MOVE"] = 500
    with pytest.raises(StorageProblem):
        s.put("space/keys.json", b"new, half")
    drive.state.fail.clear()
    assert s.get("space/keys.json") == b"old"
    assert set(s.list()) == {"space/keys.json"}   # the temporary file is never listed (and was removed)
    assert not [f for f in drive.state.files if ".enlens-" in f]


@pytest.mark.parametrize("method,status,kind", [("GET", 401, DENIED), ("PUT", 403, DENIED), ("PUT", 507, FULL),
                                                 ("PROPFIND", 401, DENIED)])
def test_refusals_in_plain_words(drive, method, status, kind):
    s = _store(drive)
    drive.state.fail[method] = status
    with pytest.raises(StorageProblem) as e:
        {"GET": lambda: s.get("space/x"), "PUT": lambda: s.put("space/x", b"x"), "PROPFIND": lambda: s.list()}[method]()
    assert e.value.kind == kind and "HTTP" not in str(e.value)


def test_maintenance_and_a_wrong_password(drive):
    s = _store(drive)
    drive.state.maintenance = True
    with pytest.raises(StorageProblem) as e:
        s.list()
    assert e.value.kind == MAINTENANCE
    drive.state.maintenance = False
    bad = webdav.storage(drive.address("anna@uva.nl"), "anna@uva.nl", "wrong", folder="Team folder")
    with pytest.raises(StorageProblem) as e:
        bad.get("x")
    assert e.value.kind == DENIED and "app password" in str(e.value)


def test_a_password_travels_only_over_https():
    with pytest.raises(StorageProblem):
        WebDAVStorage("http://drive.example.org/remote.php/webdav/", "u", "p")
    with pytest.raises(webdav.WebDAVProblem):
        webdav.normalise("http://drive.example.org/remote.php/webdav/")
    assert webdav.normalise("surfdrive.surf.nl/files/remote.php/nonshib-webdav") == webdav.SURFDRIVE
    assert webdav.normalise("https://cloud.uni.nl/remote.php/dav/files/<user>", "a@b.nl") == \
        "https://cloud.uni.nl/remote.php/dav/files/a@b.nl/"
    assert webdav.member_address("https://cloud.uni.nl/remote.php/dav/files/anna/", "carol") == \
        "https://cloud.uni.nl/remote.php/dav/files/carol/"
    assert webdav.member_address(webdav.SURFDRIVE, "carol") == webdav.SURFDRIVE
    assert webdav.in_eu(webdav.SURFDRIVE) is True and webdav.in_eu("https://cloud.example.com/") is None


def test_sharing_through_the_drives_interface(drive):
    a = drive.address("anna@uva.nl")
    name = webdav.make_folder(a, "anna@uva.nl", USERS["anna@uva.nl"], "Hydrogen")
    assert name == "ENLENS - Hydrogen"
    assert webdav.make_folder(a, "anna@uva.nl", USERS["anna@uva.nl"], "Hydrogen") == "ENLENS - Hydrogen 2"
    sid = webdav.share(a, "anna@uva.nl", USERS["anna@uva.nl"], name, "carol")
    assert drive.state.shares[sid]["permissions"] == webdav.SHARE_PERMISSIONS
    with pytest.raises(webdav.WebDAVProblem):
        webdav.share(a, "anna@uva.nl", USERS["anna@uva.nl"], name, "nobody")
    webdav.unshare(a, "anna@uva.nl", USERS["anna@uva.nl"], sid)
    webdav.unshare(a, "anna@uva.nl", USERS["anna@uva.nl"], sid)   # (gone already: no problem)
    assert drive.state.shares == {}
    drive.state.ocs = False
    with pytest.raises(webdav.WebDAVProblem) as e:
        webdav.share(a, "anna@uva.nl", USERS["anna@uva.nl"], name, "carol")
    assert e.value.kind == "no_share_api"


# ---------------------------------------------------------------------------------------------
# the team's storage space in a drive
# ---------------------------------------------------------------------------------------------
def _round(p: Person, ok=("documents",)) -> dict:
    with p:
        out = folder.sync_now(p.ws)
    bad = [x for x in out["problems"] if x["kind"] not in ok]
    assert not bad, bad
    return out


def _carol_drive(drive, **kw) -> dict:
    return {"user": "carol", "password": USERS["carol"], **kw}


def _set_up(anna: Person, drive) -> dict:
    with anna:
        out = space.setup_webdav(anna.ws, drive.address("anna@uva.nl"), "anna@uva.nl", USERS["anna@uva.nl"])
        desc = space.configured(anna.ws)
    assert out["service"] == "webdav" and out["keeper"] and out["drive"]["folder"] == desc["folder"]
    assert desc["folder"].startswith("ENLENS - ") and f"anna@uva.nl/{desc['folder']}" in drive.state.dirs
    assert USERS["anna@uva.nl"] not in Path(anna.ws.config_path).read_text(encoding="utf-8")   # keychain only
    return desc


def test_set_up_invite_join_work_together_and_remove(anna_and_ben, drive, tmp_path, monkeypatch):
    anna, _ben = anna_and_ben
    carol = Person(tmp_path, "Carol", monkeypatch)
    desc = _set_up(anna, drive)
    _round(anna)
    drive.state.dirs.add(f"carol/{desc['folder']}")   # Carol has a folder of that name: the share lands renamed
    with anna:
        inv = space.invite(anna.ws, "Carol", drive_user="carol")
    assert inv["shared"] and inv["share_note"] is None and "app password" in inv["message"]
    assert space.peek(inv["link"])["service"] == "webdav"
    assert not any(pw in str(space.parse_link(inv["link"])) for pw in USERS.values())   # no app password travels
    with carol, pytest.raises(space.SpaceProblem) as e:
        space.join_new_project(inv["link"])
    assert e.value.kind == "drive_needed"
    with carol:
        carol.ws = enlens_home.open_project(space.join_new_project(inv["link"], drive=_carol_drive(drive)))
        cdesc = space.configured(carol.ws)
    assert cdesc["folder"] == f"{desc['folder']} (2)" and cdesc["endpoint"] == drive.address("carol")
    _round(anna)   # binds Carol
    _round(carol)  # Carol gets the project
    with carol:
        assert carol.ws.scalar("SELECT COUNT(*) FROM documents") == anna.ws.scalar("SELECT COUNT(*) FROM documents")
        h = claimcheck.check_hypothesis(carol.ws, "Hydrogen storage is cheap.", BaselineBackend(), "baseline", k=2)
        sharing.share(carol.ws, [{"kind": "check", "key": h}])
    _round(carol)
    _round(anna)
    with anna:
        assert anna.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (h,))
    # what is in the drive is sealed: no project words, no names
    assert not any(b"Hydrogen" in v or b"Carol" in v for v in drive.state.files.values())
    # removed: the folder is no longer shared with her, and the project's key is replaced
    with anna:
        out = space.remove_member(anna.ws, cdesc["part"])
    assert out["warnings"] == [] and drive.state.shares == {}
    with carol:
        out = folder.sync_now(carol.ws)
    assert [x["kind"] for x in out["problems"]] == [NOT_FOUND]


def test_without_the_sharing_interface_the_owner_shares_by_hand(anna_and_ben, drive, tmp_path, monkeypatch):
    anna, _ben = anna_and_ben
    carol = Person(tmp_path, "Carol", monkeypatch)
    desc = _set_up(anna, drive)
    _round(anna)
    drive.state.ocs = False
    drive.state.shares_in = "Shared"
    with anna:
        inv = space.invite(anna.ws, "Carol", drive_user="carol")
    assert not inv["shared"] and "drive's website" in inv["share_note"]
    with carol, pytest.raises(space.SpaceProblem) as e:   # not shared yet: nothing to find, nothing made
        space.join_new_project(inv["link"], drive=_carol_drive(drive))
    assert e.value.kind == "folder_not_found" and isinstance(e.value.extra["folders"], list)
    with carol:
        assert not list((carol.home / "projects").glob("*")) if (carol.home / "projects").is_dir() else True
    # the owner shares it in the drive's website, under another name in Carol's files
    drive.state.ocs = True
    webdav.share(desc["endpoint"], "anna@uva.nl", USERS["anna@uva.nl"], desc["folder"], "carol")
    drive.state.ocs = False
    sh = next(iter(drive.state.shares.values()))
    assert sh["mount"] == f"Shared/{desc['folder']}"
    with carol:
        carol.ws = enlens_home.open_project(space.join_new_project(inv["link"], drive=_carol_drive(drive)))
        assert space.configured(carol.ws)["folder"] == f"Shared/{desc['folder']}"
    _round(anna)
    _round(carol)
    # removing her: ENLENS cannot stop sharing; it says what to do in the drive's website
    with anna:
        out = space.remove_member(anna.ws, next(m["part"] for m in space.status(anna.ws)["members"] if not m["me"]))
    assert len(out["warnings"]) == 1 and "Stop sharing" in out["warnings"][0]


def test_a_chosen_folder_must_hold_the_team(anna_and_ben, drive, tmp_path, monkeypatch):
    anna, _ben = anna_and_ben
    carol = Person(tmp_path, "Carol", monkeypatch)
    _set_up(anna, drive)
    drive.state.dirs.add("carol/Holiday photos")
    with anna:
        inv = space.invite(anna.ws, "Carol")   # no user name given: shared by hand
    assert not inv["shared"]
    with carol, pytest.raises(space.SpaceProblem) as e:
        space.join_new_project(inv["link"], drive=_carol_drive(drive, folder="Holiday photos"))
    assert e.value.kind == "folder_not_found" and "Holiday photos" in e.value.extra["folders"]


def test_a_new_app_password(anna_and_ben, drive):
    anna, _ben = anna_and_ben
    desc = _set_up(anna, drive)
    drive.state.users["anna@uva.nl"] = "app-pw-new"   # the old app password was revoked
    with anna:
        out = folder.sync_now(anna.ws)
        assert DENIED in [x["kind"] for x in out["problems"]]
        with pytest.raises(space.SpaceProblem):
            space.set_drive_password(anna.ws, "anna@uva.nl", "wrong")
        space.set_drive_password(anna.ws, "anna@uva.nl", "app-pw-new")
        assert space._get_secret(desc["id"], "access")["password"] == "app-pw-new"
    drive.state.users["anna@uva.nl"] = USERS["anna@uva.nl"]


def test_the_hand_over_never_passes_the_app_password_on(anna_and_ben, drive, tmp_path, monkeypatch):
    from enlens_claims import ownership

    anna, _ben = anna_and_ben
    carol = Person(tmp_path, "Carol", monkeypatch)
    desc = _set_up(anna, drive)
    with anna:
        assert keychain.get(space._secret_name(desc["id"], "keeper")) is None   # no keys that make keys in a drive
        inv = space.invite(anna.ws, "Carol", drive_user="carol")
    with carol:
        carol.ws = enlens_home.open_project(space.join_new_project(inv["link"], drive=_carol_drive(drive)))
    for p in (anna, carol, anna, carol):
        _round(p)
    with anna:
        ownership.hand_over(anna.ws, carol.id)
    _round(anna)
    _round(carol)
    with carol:
        cdesc = space.configured(carol.ws)
        assert folder.status(carol.ws)["space"]["keeper"]
        assert space._get_secret(cdesc["id"], "access") == {"user": "carol", "password": USERS["carol"]}
        inv = space.invite(carol.ws, "Ben", drive_user="ben")   # a share Carol may not reshare: said in words
    assert not inv["shared"] and "drive's website" in inv["share_note"]


def test_move_from_a_drive_to_another_folder_and_from_elsewhere(anna_and_ben, drive, tmp_path, monkeypatch):
    anna, _ben = anna_and_ben
    carol = Person(tmp_path, "Carol", monkeypatch)
    desc = _set_up(anna, drive)
    _round(anna)
    with anna:
        inv = space.invite(anna.ws, "Carol", drive_user="carol")
    with carol:
        carol.ws = enlens_home.open_project(space.join_new_project(inv["link"], drive=_carol_drive(drive)))
    _round(anna)
    _round(carol)
    # 1. to a new folder in the same drive: Carol's copy follows with her own account
    with anna:
        out = space.move(anna.ws, lambda w, i: space.setup_webdav(w, drive.address("anna@uva.nl"), "anna@uva.nl",
                                                                    USERS["anna@uva.nl"], ident=i))
        new = space.configured(anna.ws)
    assert out["moved"]["told"] == 1 and out["moved"]["invite_again"] == [] and out["moved"]["share_by_hand"] == []
    assert new["folder"] != desc["folder"] and new["drive_users"]
    with carol:
        out = folder.sync_now(carol.ws)
        assert out.get("moved") and space.configured(carol.ws)["id"] == new["id"]
        assert space.configured(carol.ws)["folder"] == new["folder"]
    _round(carol)
    _round(anna)
    _round(carol)
    # 2. to a folder on this computer and back to the drive: from elsewhere, Carol is asked for a new invite
    with anna:
        space.move(anna.ws, lambda w, i: space.setup_dir(w, tmp_path / "plain", ident=i))
    _round(carol, ok=("documents",))
    with carol:
        assert space.configured(carol.ws)["service"] == "dir"
    _round(carol)
    _round(anna)
    with anna:
        out = space.move(anna.ws, lambda w, i: space.setup_webdav(w, drive.address("anna@uva.nl"), "anna@uva.nl",
                                                                    USERS["anna@uva.nl"], ident=i))
    assert out["moved"]["told"] == 1 and len(out["moved"]["invite_again"]) == 1
    with carol:
        out = folder.sync_now(carol.ws)
        assert "moved_away" in [x["kind"] for x in out["problems"]] and space.configured(carol.ws) is None


def test_the_drive_through_the_app(api, drive):  # noqa: F811
    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    links = api("GET", "/api/space/links")[1]
    assert links["webdav_surfdrive"] == webdav.SURFDRIVE
    assert api("POST", "/api/projects/Demo/space/webdav", {"address": drive.address("anna@uva.nl")})[0] == 400
    st, r = api("POST", "/api/projects/Demo/space/webdav", {"address": drive.address("anna@uva.nl"),
                                                           "user": "anna@uva.nl", "password": "wrong"})
    job = api.wait(r["job"]["id"])
    assert job["state"] == "error" and "app password" in job["error"]
    st, r = api("POST", "/api/projects/Demo/space/webdav", {"address": drive.address("anna@uva.nl"),
                                                           "user": "anna@uva.nl", "password": USERS["anna@uva.nl"]})
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done", job
    st, r = api("GET", "/api/projects/Demo/shared-folder")
    assert r["space"]["drive"]["folder"] == "ENLENS - Demo" and r["space"]["drive"]["user"] == "anna@uva.nl"
    st, inv = api("POST", "/api/projects/Demo/space/invites", {"label": "Carol", "drive_user": "carol"})
    assert st == 200 and inv["shared"] is True
    st, p = api("POST", "/api/space/peek", {"link": inv["link"]})
    assert st == 200 and p["service"] == "webdav" and p["folder"] == "ENLENS - Demo" and "password" not in p
    st, r = api("POST", "/api/join-team", {"link": inv["link"]})
    assert st == 400 and r["kind"] == "drive_needed"
    st, r = api("POST", "/api/join-team", {"link": inv["link"], "drive": {"user": "ben", "password": USERS["ben"]}})
    assert st == 400 and r["kind"] == "folder_not_found" and isinstance(r["folders"], list)
    assert api("PUT", "/api/projects/Demo/space/drive-password", {"user": "anna@uva.nl", "password": "no"})[0] == 400
    st, r = api("DELETE", f"/api/projects/Demo/space/invites/{inv['part']}")
    assert st == 200 and r["warnings"] == [] and drive.state.shares == {}
