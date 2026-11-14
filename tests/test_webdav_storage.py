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
from enlens_claims.sync.storage import (BAD_ANSWER, DENIED, FULL, MAINTENANCE, NOT_FOUND, TEST_PLAIN_HTTP,
                                        TOO_LARGE, StorageProblem, WebDAVStorage, check_name)
from test_app import api, home  # noqa: F401  (fixtures)
from test_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)

sys.path.insert(0, str(Path(__file__).parent))
import fake_webdav  # noqa: E402

USERS = {"anna@uva.nl": "app-pw-anna", "carol": "app-pw-carol", "ben": "app-pw-ben"}


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    from enlens_claims.sync import _web

    monkeypatch.setattr(_web, "sleep", lambda s: None)
    monkeypatch.setenv(TEST_PLAIN_HTTP, "1")   # (the stand-in drive is on this computer, over plain http)


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
    return {"user": "carol", "password": USERS["carol"], "confirmed": True, **kw}


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


# ---------------------------------------------------------------------------------------------
# the review of 14 November 2026
# ---------------------------------------------------------------------------------------------
def _with_carol(anna_and_ben, drive, tmp_path, monkeypatch):
    """Anna's space in her drive, and Carol in it (her own account), each with a round done."""
    anna, _ben = anna_and_ben
    carol = Person(tmp_path, "Carol", monkeypatch)
    desc = _set_up(anna, drive)
    _round(anna)
    with anna:
        inv = space.invite(anna.ws, "Carol", drive_user="carol")
    with carol:
        carol.ws = enlens_home.open_project(space.join_new_project(inv["link"], drive=_carol_drive(drive)))
    for p in (anna, carol, anna, carol):
        _round(p)
    with carol:
        cdesc = space.configured(carol.ws)
    return anna, carol, desc, cdesc


def test_plain_http_only_when_the_tests_allow_it(monkeypatch):
    monkeypatch.delenv(TEST_PLAIN_HTTP)
    with pytest.raises(StorageProblem):
        WebDAVStorage("http://127.0.0.1:9/remote.php/webdav/", "u", "p")
    with pytest.raises(webdav.WebDAVProblem):
        webdav.normalise("http://localhost:9/remote.php/webdav/")
    monkeypatch.setenv(TEST_PLAIN_HTTP, "1")
    WebDAVStorage("http://127.0.0.1:9/remote.php/webdav/", "u", "p")
    with pytest.raises(StorageProblem):   # (never to another computer, even in the tests)
        WebDAVStorage("http://drive.example.org/remote.php/webdav/", "u", "p")


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_an_answer_from_another_address_is_never_followed(drive, status):
    s = _store(drive)
    s.put("space/x", b"x")
    drive.state.redirect = (status, f"{drive.url}/elsewhere/remote.php/webdav/")
    for call in (lambda: s.list(), lambda: s.get("space/x"), lambda: s.put("space/y", b"y")):
        with pytest.raises(StorageProblem) as e:
            call()
        assert e.value.kind == BAD_ANSWER and "another address" in str(e.value)
    assert not [c for c in drive.state.calls if "/elsewhere" in c]   # the password never went along
    assert not [p for p in drive.state.auth_to if "/elsewhere" in p]


def test_an_answer_about_another_folder_is_not_an_empty_one(drive):
    s = _store(drive)
    s.put("space/roster.json", b"r")
    drive.state.href_base = "/remote.php/dav/files/carol/"
    with pytest.raises(StorageProblem) as e:
        s.list()
    assert e.value.kind == BAD_ANSWER and "HTTP" not in str(e.value)
    drive.state.href_base = None
    assert set(s.list()) == {"space/roster.json"}


def test_names_no_storage_takes_are_left_out_of_a_listing(drive):
    s = _store(drive)
    s.put("space/roster.json", b"r")
    base = "/remote.php/dav/files/anna@uva.nl/Team folder/enlens/abc/"
    drive.state.extra_hrefs = [base + "space/../../../evil", base + "space/./x", base + "space/caf%C3%A9"]
    listed = s.list()
    assert set(listed) == {"space/roster.json"} and all(check_name(n) for n in listed)


def test_a_new_folder_takes_the_next_name_when_one_is_there_unlisted(drive):
    a = drive.address("anna@uva.nl")
    drive.state.dirs.add("anna@uva.nl/ENLENS - Hydrogen")
    drive.state.unlisted.add("anna@uva.nl/ENLENS - Hydrogen")   # (not shown in the listing; MKCOL answers 405)
    assert webdav.make_folder(a, "anna@uva.nl", USERS["anna@uva.nl"], "Hydrogen") == "ENLENS - Hydrogen 2"


def test_a_move_that_was_done_but_answered_with_an_error_counts(drive):
    s = _store(drive)
    s.put("space/keys.json", b"old")
    drive.state.move_then = [502]   # done, then 502: the MOVE tried again answers 404
    s.put("space/keys.json", b"new")
    assert s.get("space/keys.json") == b"new"
    assert not [f for f in drive.state.files if ".enlens-" in f]


def test_the_keepers_round_removes_old_temporary_files(anna_and_ben, drive):
    import time

    anna, _ben = anna_and_ben
    desc = _set_up(anna, drive)
    where = f"anna@uva.nl/{desc['folder']}/enlens/{desc['id']}/space/"
    old = [f"{where}.enlens-{i:08x}-roster.json" for i in range(7)]
    fresh = f"{where}.enlens-ffffffff-keys.json"
    for f in old + [fresh]:
        drive.state.files[f], drive.state.etags[f] = b"half", 1
        drive.state.mtimes[f] = time.time() - (2 * 86400 if f in old else 60)

    def propfinds() -> int:
        n = len(drive.state.calls)
        _round(anna)
        return sum(c.startswith("PROPFIND ") for c in drive.state.calls[n:])

    propfinds()
    assert sum(f in drive.state.files for f in old) == 2   # a handful per round
    walked = propfinds()
    assert not any(f in drive.state.files for f in old) and fresh in drive.state.files
    assert propfinds() < walked   # (then looked through once a day only)


def test_the_share_path_follows_an_address_deeper_than_the_users_root(drive):
    a = drive.address("anna@uva.nl") + "Projects/"
    drive.state.dirs |= {"anna@uva.nl/Projects", "anna@uva.nl/ENLENS - Hydrogen"}   # (a folder of that name at the root)
    name = webdav.make_folder(a, "anna@uva.nl", USERS["anna@uva.nl"], "Hydrogen")
    assert name == "ENLENS - Hydrogen" and "anna@uva.nl/Projects/ENLENS - Hydrogen" in drive.state.dirs
    sid = webdav.share(a, "anna@uva.nl", USERS["anna@uva.nl"], name, "carol")
    assert drive.state.shares[sid]["path"] == "Projects/ENLENS - Hydrogen"
    assert webdav._user_root_path(webdav.SURFDRIVE + "Work/", "F") == "/Work/F"
    assert webdav._user_root_path("https://x.nl/remote.php/webdav/", "F") == "/F"
    with pytest.raises(webdav.WebDAVProblem) as e:   # an address ENLENS cannot place: nothing is shared
        webdav._user_root_path("https://x.nl/dav/", "F")
    assert e.value.kind == "no_share_path"
    desc = {"folder": name, "endpoint": "https://x.nl/dav/", "user": "anna@uva.nl"}
    sid, note = space._drive_share(desc, {"user": "anna@uva.nl", "password": "pw"}, "carol")
    assert sid is None and "drive's website" in note


def test_one_share_per_drive_user(anna_and_ben, drive, tmp_path, monkeypatch):
    anna, _ben = anna_and_ben
    carol = Person(tmp_path, "Carol", monkeypatch)
    _set_up(anna, drive)
    _round(anna)
    with anna:
        first = space.invite(anna.ws, "Carol", drive_user="carol")
        second = space.invite(anna.ws, "Carol, again", drive_user="carol")   # the same account: the share is used again
    assert first["shared"] and second["shared"] and len(drive.state.shares) == 1
    with anna:
        out = space.cancel_invite(anna.ws, first["part"])
    assert len(drive.state.shares) == 1 and "stays shared with carol" in out["warnings"][0]
    with carol:
        carol.ws = enlens_home.open_project(space.join_new_project(second["link"], drive=_carol_drive(drive)))
        cdesc = space.configured(carol.ws)
    _round(anna)
    _round(carol)
    with anna:
        out = space.remove_member(anna.ws, cdesc["part"])
    assert out["warnings"] == [] and drive.state.shares == {}


def test_removing_one_of_two_members_with_one_account_keeps_the_share(anna_and_ben, drive, tmp_path, monkeypatch):
    anna, carol, desc, cdesc = _with_carol(anna_and_ben, drive, tmp_path, monkeypatch)
    with anna:
        inv = space.invite(anna.ws, "Carol's laptop", drive_user="carol")
    assert inv["shared"] and len(drive.state.shares) == 1
    with anna:
        out = space.remove_member(anna.ws, cdesc["part"])
    assert len(drive.state.shares) == 1 and "stays shared with carol" in out["warnings"][0]


def _forged(link: str, **change) -> str:
    payload = space.parse_link(link)
    payload["space"].update(change)
    return space._link(payload)


def test_an_invite_whose_drive_name_and_address_differ_is_refused(anna_and_ben, drive):
    anna, _ben = anna_and_ben
    _set_up(anna, drive)
    with anna:
        inv = space.invite(anna.ws, "Carol", drive_user="carol")
    p = space.peek(inv["link"])
    assert p["host"] == "127.0.0.1" and p["address"] == drive.address("anna@uva.nl")
    for forged in (_forged(inv["link"], host="surfdrive.surf.nl"),
                   _forged(inv["link"], endpoint="http://drive.example.org/remote.php/webdav/",
                           host="drive.example.org")):
        for call in (space.peek, space.parse_link, lambda x: space.join_new_project(x, drive=_carol_drive(None))):
            with pytest.raises(space.SpaceProblem) as e:
                call(forged)
            assert e.value.kind == "link"
    # without a name, the name shown is the address's own
    assert space.peek(_forged(inv["link"], host=None))["host"] == "127.0.0.1"


def test_an_unknown_drive_is_confirmed_before_the_password_goes_there(anna_and_ben, drive, tmp_path, monkeypatch):
    anna, _ben = anna_and_ben
    carol = Person(tmp_path, "Carol", monkeypatch)
    _set_up(anna, drive)
    with anna:
        inv = space.invite(anna.ws, "Carol", drive_user="carol")
        assert space.peek(inv["link"])["known"] is True   # (Anna uses it on her computer)
    with carol:
        assert space.peek(inv["link"])["known"] is False
        n = len(drive.state.calls)
        with pytest.raises(space.SpaceProblem) as e:
            space.join_new_project(inv["link"], drive=_carol_drive(drive, confirmed=False))
        assert e.value.kind == "drive_confirm" and e.value.extra["address"] == drive.address("carol")
        assert len(drive.state.calls) == n   # nothing was sent to it
        carol.ws = enlens_home.open_project(space.join_new_project(inv["link"], drive=_carol_drive(drive)))
        assert space.peek(inv["link"])["known"] is True   # from now on, on this computer
    assert webdav.known("https://surfdrive.surf.nl/files/remote.php/nonshib-webdav/")
    assert webdav.known("https://uva.data.surf.nl/remote.php/webdav/")
    assert not webdav.known("https://data.surf.nl.example.com/remote.php/webdav/")


def test_after_a_hand_over_the_folders_holder_is_named(anna_and_ben, drive, tmp_path, monkeypatch):
    from enlens_claims import ownership

    anna, carol, desc, cdesc = _with_carol(anna_and_ben, drive, tmp_path, monkeypatch)
    with anna:
        assert space.status(anna.ws)["drive"]["mine"] is True
        ownership.hand_over(anna.ws, carol.id)
    _round(anna)
    _round(carol)
    with carol:
        st = space.status(carol.ws)
        assert st["keeper"] and st["drive"]["mine"] is False and "anna@uva.nl" in st["drive"]["holder"]
        assert space.configured(carol.ws)["drive_users"].get(desc["part"]) == "anna@uva.nl"   # passed on
        inv = space.invite(carol.ws, "Ben", drive_user="ben")
    assert not inv["shared"] and "anna@uva.nl" in inv["share_note"] and "only they" in inv["share_note"]
    assert "Move to another storage space" in inv["share_note"] and len(drive.state.shares) == 1
    with carol:
        out = space.cancel_invite(carol.ws, inv["part"])
    assert "anna@uva.nl" in out["warnings"][0] and "ben" in out["warnings"][0]
    # Carol takes full control: a folder in her own drive, shared with Anna by itself (the user names came along)
    with carol:
        out = space.move(carol.ws, lambda w, i: space.setup_webdav(w, drive.address("carol"), "carol",
                                                                    USERS["carol"], ident=i))
        new = space.configured(carol.ws)
        assert space.status(carol.ws)["drive"]["mine"] is True
    assert out["moved"]["told"] == 1 and out["moved"]["share_by_hand"] == []
    assert any(sh["owner"] == "carol" and sh["with"] == "anna@uva.nl" for sh in drive.state.shares.values())
    with anna:
        out = folder.sync_now(anna.ws)
        assert out.get("moved") and space.configured(anna.ws)["id"] == new["id"]


def test_waiting_to_follow_a_move_asks_the_drive_little(anna_and_ben, drive, tmp_path, monkeypatch):
    anna, carol, desc, cdesc = _with_carol(anna_and_ben, drive, tmp_path, monkeypatch)
    drive.state.dirs |= {f"carol/Folder {i}" for i in range(12)}
    drive.state.ocs = False   # the new folder is not shared with Carol yet
    with anna:
        out = space.move(anna.ws, lambda w, i: space.setup_webdav(w, drive.address("anna@uva.nl"), "anna@uva.nl",
                                                                    USERS["anna@uva.nl"], ident=i))
        new = space.configured(anna.ws)
    assert out["moved"]["share_by_hand"]

    def looks() -> int:
        n = len(drive.state.calls)
        with carol:
            out = folder.sync_now(carol.ws)
        assert "moved" in [x["kind"] for x in out["problems"]] and space.configured(carol.ws)["id"] == cdesc["id"]
        return sum(new["id"] in c for c in drive.state.calls[n:])

    assert looks() >= 12   # the first time: the whole drive
    assert looks() == 1    # then only the folder's own name
    import json

    with carol:
        mirror = space.mirror_of(carol.ws) / ".space-state.json"
        st = json.loads(mirror.read_text(encoding="utf-8"))
        st["follow_search_at"] -= space.FOLLOW_SEARCH_EVERY + 1
        mirror.write_text(json.dumps(st), encoding="utf-8")
    assert looks() >= 12   # half an hour on: the whole drive again
    # shared now: Carol's copy follows
    drive.state.ocs = True
    webdav.share(new["endpoint"], "anna@uva.nl", USERS["anna@uva.nl"], new["folder"], "carol")
    with carol:
        assert folder.sync_now(carol.ws).get("moved")


def test_a_move_puts_project_json_in_the_new_space_before_the_old_one_is_told(anna_and_ben, drive, tmp_path,
                                                                             monkeypatch):
    anna, carol, desc, _cdesc = _with_carol(anna_and_ben, drive, tmp_path, monkeypatch)
    puts = []
    real_put = WebDAVStorage.put

    def put(self, name, data):
        puts.append((self.root, name))
        return real_put(self, name, data)

    monkeypatch.setattr(WebDAVStorage, "put", put)
    with anna:
        space.move(anna.ws, lambda w, i: space.setup_webdav(w, drive.address("anna@uva.nl"), "anna@uva.nl",
                                                              USERS["anna@uva.nl"], ident=i))
        new = space.configured(anna.ws)
    told = next(i for i, (root, n) in enumerate(puts) if n == "space/moved.json" and desc["folder"] in root)
    sent = next(i for i, (root, n) in enumerate(puts) if n == "space/project.json" and new["folder"] in root)
    assert sent < told
    _round(carol)   # Carol follows before Anna's next round, and writes there
    _round(carol)
    _round(anna)   # Anna's copy does not wait for project.json (no "arriving": `_round` allows none)
    with anna:
        assert (space.mirror_of(anna.ws) / folder.team_name(anna.ws) / "project.json").is_file()


# ---------------------------------------------------------------------------------------------
# the audit of 14 November 2026 (DAV-1 to DAV-11)
# ---------------------------------------------------------------------------------------------
def _log(p: Person) -> list[str]:
    with p:
        return [r[0] for r in p.ws._conn().execute("SELECT text FROM research_log WHERE kind='sync' ORDER BY at")]


def _age(p: Person, key: str, seconds: float) -> None:
    """Make a time kept in the copy's state of the space `seconds` older (a day or an hour passes)."""
    import json

    with p:
        f = space.mirror_of(p.ws) / ".space-state.json"
        st = json.loads(f.read_text(encoding="utf-8"))
        st[key] -= seconds
        f.write_text(json.dumps(st), encoding="utf-8")


def _tree(root: Path) -> dict:
    return {str(f): (f.stat().st_size, f.stat().st_mtime_ns) for f in root.rglob("*") if f.is_file()}


def _rename(drive, old: str, new: str) -> None:
    """A folder renamed or moved in its owner's drive (`old`, `new`: owner paths); its shares follow it."""
    st = drive.state
    with st.lock:
        st.dirs = {new + d[len(old):] if d == old or d.startswith(old + "/") else d for d in st.dirs}
        for k in [k for k in st.files if k.startswith(old + "/")]:
            nk = new + k[len(old):]
            st.files[nk], st.etags[nk] = st.files.pop(k), st.etags.pop(k)
            st.mtimes[nk] = st.mtimes.pop(k, 0)
        for sh in st.shares.values():
            if f"{sh['owner']}/{sh['path']}" == old:
                sh["path"] = new.split("/", 1)[1]


def _invited_by_hand(anna_and_ben, drive, tmp_path, monkeypatch, drive_user=None):
    """Carol in Anna's space; the folder was shared with her in the drive's website, not by ENLENS."""
    anna, _ben = anna_and_ben
    carol = Person(tmp_path, "Carol", monkeypatch)
    desc = _set_up(anna, drive)
    _round(anna)
    drive.state.ocs = False   # (ENLENS cannot share it: the owner does, in the drive's website)
    with anna:
        inv = space.invite(anna.ws, "Carol", drive_user=drive_user)
    assert not inv["shared"]
    drive.state.ocs = True
    webdav.share(desc["endpoint"], "anna@uva.nl", USERS["anna@uva.nl"], desc["folder"], "carol")
    with carol:
        carol.ws = enlens_home.open_project(space.join_new_project(inv["link"], drive=_carol_drive(drive)))
        cdesc = space.configured(carol.ws)
    for p in (anna, carol, anna, carol):
        _round(p)
    return anna, carol, desc, cdesc


def test_a_removal_that_cannot_stop_the_sharing_stays_on_the_team_tab(anna_and_ben, drive, tmp_path, monkeypatch):
    """DAV-1: shared by hand with an account ENLENS does not know: the removal says what is left, and the Team tab
    keeps saying it until the owner says it is done."""
    anna, carol, desc, cdesc = _invited_by_hand(anna_and_ben, drive, tmp_path, monkeypatch)
    with anna:
        assert space.status(anna.ws)["drive"]["unshare"][cdesc["part"]] == "by_hand"
        out = space.remove_member(anna.ws, cdesc["part"])
    assert len(drive.state.shares) == 1 and out["warnings"][0].startswith("Stop sharing the folder")
    assert "with Carol" in out["warnings"][0]
    _round(anna)
    with anna:
        left = space.status(anna.ws)["left_to_do"]
    assert [t["text"] for t in left] == out["warnings"] and left[0]["check"] is False
    assert left[0]["id"] == f"unshare-{cdesc['part']}" and left[0]["who"] == "Carol"
    assert any("Left to do: Stop sharing" in t for t in _log(anna))   # the research log's entry of the removal
    n = len(drive.state.calls)
    _round(anna)
    assert not any("/ocs/" in c for c in drive.state.calls[n:])   # (nothing ENLENS can look at: nothing asked)
    with anna:
        space.dismiss(anna.ws, left[0]["id"])
        assert space.status(anna.ws)["left_to_do"] == []
        with pytest.raises(space.SpaceProblem):
            space.dismiss(anna.ws, left[0]["id"])
    assert any(t.startswith("Marked as done") for t in _log(anna))


def test_a_share_made_in_the_website_is_stopped_when_the_account_is_known(anna_and_ben, drive, tmp_path,
                                                                         monkeypatch):
    """DAV-1: ENLENS did not make the share, but knows the account: the drive's list of shares says which it is."""
    anna, carol, desc, cdesc = _invited_by_hand(anna_and_ben, drive, tmp_path, monkeypatch, drive_user="carol")
    with anna:
        assert space.status(anna.ws)["drive"]["unshare"][cdesc["part"]] == "enlens"
        out = space.remove_member(anna.ws, cdesc["part"])
        assert space.status(anna.ws)["left_to_do"] == []
    assert out["warnings"] == [] and drive.state.shares == {}


def test_a_share_left_after_a_failed_removal_is_stopped_by_a_later_round(anna_and_ben, drive, tmp_path, monkeypatch):
    """DAV-1: the drive did not answer the removal's request: the keeper's round tries again, then the note goes."""
    anna, carol, desc, cdesc = _with_carol(anna_and_ben, drive, tmp_path, monkeypatch)
    drive.state.fail["DELETE"] = 502
    with anna:
        out = space.remove_member(anna.ws, cdesc["part"])
        left = space.status(anna.ws)["left_to_do"]
    assert len(drive.state.shares) == 1 and "could not stop sharing" in out["warnings"][0]
    assert left[0]["check"] is True
    drive.state.fail.clear()
    _round(anna)
    assert drive.state.shares == {}
    with anna:
        assert space.status(anna.ws)["left_to_do"] == []
    assert any("is no longer shared with Carol" in t for t in _log(anna))


def test_inviting_the_same_account_again_ends_what_was_left_to_do(anna_and_ben, drive, tmp_path, monkeypatch):
    anna, carol, desc, cdesc = _with_carol(anna_and_ben, drive, tmp_path, monkeypatch)
    drive.state.fail["DELETE"] = 502
    with anna:
        space.remove_member(anna.ws, cdesc["part"])
    drive.state.fail.clear()
    with anna:
        inv = space.invite(anna.ws, "Carol again", drive_user="carol")
        assert inv["shared"] and space.status(anna.ws)["left_to_do"] == []
    _round(anna)
    assert len(drive.state.shares) == 1   # (shared with her again on purpose: kept)


def test_removing_the_member_whose_drive_holds_the_folder(anna_and_ben, drive, tmp_path, monkeypatch):
    """DAV-5: the folder is in the removed person's own drive: they keep it, and the words say so."""
    from enlens_claims import ownership

    anna, carol, desc, cdesc = _with_carol(anna_and_ben, drive, tmp_path, monkeypatch)
    with anna:
        ownership.hand_over(anna.ws, carol.id)
    for p in (anna, carol, anna, carol):
        _round(p)
    with carol:
        assert space.status(carol.ws)["drive"]["unshare"][desc["part"]] == "holds"
        out = space.remove_member(carol.ws, desc["part"])
        left = space.status(carol.ws)["left_to_do"]
    w = out["warnings"][0]
    assert "stays theirs" in w and "Move to another storage space" in w and "Ask them" not in w
    assert left[0]["text"] == w and left[0]["check"] is False


def test_files_deleted_in_the_drives_website_are_written_again(anna_and_ben, drive, tmp_path, monkeypatch):
    """DAV-2: a member deletes the space's own files and the owner's part in the drive's website."""
    anna, carol, desc, cdesc = _with_carol(anna_and_ben, drive, tmp_path, monkeypatch)
    theirs = webdav.storage(cdesc["endpoint"], "carol", USERS["carol"], folder=cdesc["folder"], prefix=cdesc["prefix"])
    gone = [n for n in theirs.list("") if n.startswith("space/") or n.startswith(f"parts/{desc['part']}/")]
    assert {"space/roster.json", "space/keys.json", "space/project.json"} <= set(gone) and len(gone) > 5
    for n in gone:
        theirs.delete(n)
    _round(anna)   # the space's own files: at once (the round reads them anyway)
    assert {"space/roster.json", "space/keys.json", "space/project.json"} <= set(theirs.list(""))
    with anna:
        st = space.status(anna.ws)["restored"]
    assert st["files"] == 3 and "drive's website" in st["text"]
    _age(anna, "walked_at", space.WALK_EVERY + 1)   # her own files: on the daily walk
    _round(anna)
    assert set(gone) <= set(theirs.list(""))
    with anna:
        assert space.status(anna.ws)["restored"]["files"] == len(gone)
    assert any("written again" in t for t in _log(anna))
    _round(carol)   # the team goes on (the list of members has a new number)
    with anna:
        space.dismiss(anna.ws, "restored")
        assert space.status(anna.ws)["restored"] is None


def test_a_file_deleted_from_any_kind_of_space_is_written_again(anna_and_ben, tmp_path):
    """DAV-2 is older than the drive: the walk is the same for every kind (here a folder on this computer)."""
    anna, _ben = anna_and_ben
    with anna:
        space.setup_dir(anna.ws, tmp_path / "plain")
        desc = space.configured(anna.ws)
    _round(anna)
    root = Path(desc["dir"]) / desc["prefix"]
    mine = sorted(f for f in (root / "parts" / desc["part"]).rglob("*") if f.is_file())
    assert mine
    for f in mine:
        f.unlink()
    _age(anna, "walked_at", space.WALK_EVERY + 1)
    _round(anna)
    assert all(f.is_file() for f in mine)
    with anna:
        assert "at the storage service" in space.status(anna.ws)["restored"]["text"]


def test_a_refused_password_stops_the_rounds_until_a_new_one(anna_and_ben, drive, tmp_path, monkeypatch):
    """DAV-3: one try, then no request and nothing written, until a new app password (or Try again)."""
    anna, carol, desc, cdesc = _with_carol(anna_and_ben, drive, tmp_path, monkeypatch)
    drive.state.users["carol"] = "revoked"
    seen = []
    for _ in range(3):
        n, before = len(drive.state.calls), _tree(carol.home)
        with carol:
            out = folder.sync_now(carol.ws)
        seen.append((len(drive.state.calls) - n, [x["kind"] for x in out["problems"]], _tree(carol.home) == before))
    assert seen[0][0] >= 1 and seen[0][1] == [DENIED] and seen[1:] == [(0, [DENIED], True)] * 2
    assert USERS["carol"] not in str(seen)
    with carol:
        st = space.status(carol.ws)["refused"]
        assert "new app password" in st["text"]
        space.retry_drive(carol.ws)   # Try the same one again: one more try, then stopped again
        n = len(drive.state.calls)
        folder.sync_now(carol.ws)
        assert len(drive.state.calls) > n and space.status(carol.ws)["refused"]
        drive.state.users["carol"] = "app-pw-new"
        space.set_drive_password(carol.ws, "carol", "app-pw-new")
        assert space.status(carol.ws)["refused"] is None
    _round(carol)


def test_a_drive_that_asks_to_slow_down_is_not_asked_again_at_once(drive, monkeypatch):
    """DAV-3: a 429 is not tried again within the round; a Retry-After is waited for, or ends the round."""
    from enlens_claims.sync import _web

    waits = []
    monkeypatch.setattr(_web, "sleep", waits.append)
    s = _store(drive)
    drive.state.fail["PROPFIND"] = 429
    for header, calls, waited in ((None, 1, []), ("3", 4, [3.0, 3.0, 3.0]), ("120", 1, [])):
        drive.state.fail_headers = {"Retry-After": header} if header else {}
        waits.clear()
        n = len(drive.state.calls)
        with pytest.raises(StorageProblem) as e:
            s.list()
        assert e.value.kind == "unreachable" and len(drive.state.calls) - n == calls and waits == waited


def test_the_invite_says_whose_account_the_folder_was_shared_with(anna_and_ben, drive):
    """DAV-4: the display name the drive gives; none when it gives only the user name; withdrawn at once."""
    anna, _ben = anna_and_ben
    _set_up(anna, drive)
    drive.state.names["carol"] = "Carol de Vries"
    with anna:
        inv = space.invite(anna.ws, "Carol", drive_user="carol")
        again = space.invite(anna.ws, "Carol's laptop", drive_user="carol")   # the share there already
        ben = space.invite(anna.ws, "Ben", drive_user="ben")
    assert inv["shared_with"] == {"user": "carol", "name": "Carol de Vries"}
    assert again["shared_with"]["name"] == "Carol de Vries"
    assert ben["shared_with"] == {"user": "ben", "name": None}
    with anna:   # not them: the invite is withdrawn and the folder no longer shared with that account
        out = space.cancel_invite(anna.ws, ben["part"])
    assert out["warnings"] == [] and not any(sh["with"] == "ben" for sh in drive.state.shares.values())


def test_a_doctype_in_an_answer_is_refused(drive, monkeypatch):
    """DAV-6: a drive's listing, an S3 listing and an S3 error alike."""
    from enlens_claims.sync import _web, storage
    from enlens_claims.sync.storage import S3Storage

    s = _store(drive)
    s.put("space/roster.json", b"r")
    drive.state.doctype = '<!DOCTYPE d [<!ENTITY a "' + "x" * 100 + '"><!ENTITY b "&a;&a;&a;&a;&a;">]>'
    with pytest.raises(StorageProblem) as e:
        s.list()
    assert e.value.kind == BAD_ANSWER
    drive.state.doctype = None
    assert set(s.list()) == {"space/roster.json"}
    body = (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><ListBucketResult><Contents><Key>p/space/x</Key>'
            b'<Size>1</Size><ETag>&a;</ETag></Contents></ListBucketResult>')
    monkeypatch.setattr(_web, "send_retrying", lambda *a, **k: _web.Reply(200, {}, body))
    with pytest.raises(StorageProblem) as e:
        S3Storage("https://s3.example.org", "auto", "b", "k", "s", prefix="p/").list()
    assert e.value.kind == BAD_ANSWER
    assert storage._xml_fields(b'<!DOCTYPE x [<!ENTITY a "AccessDenied">]><Error><Code>&a;</Code></Error>') == {}
    assert storage._xml_fields(b"<Error><Code>AccessDenied</Code></Error>") == {"Code": "AccessDenied"}


def test_every_answer_is_read_up_to_a_cap(drive, monkeypatch):
    """DAV-6: writes, moves, removals and new folders too."""
    from enlens_claims.sync import _web

    caps = []
    real = _web.send

    def send(method, url, headers=None, body=None, timeout=60.0, read_cap=None):
        caps.append((method, read_cap))
        return real(method, url, headers, body, timeout, read_cap)

    monkeypatch.setattr(_web, "send", send)
    s = _store(drive)
    s.put("space/x", b"x")
    s.get("space/x")
    s.list()
    s.delete("space/x")
    webdav.share(drive.address("anna@uva.nl"), "anna@uva.nl", USERS["anna@uva.nl"], "Team folder", "carol")
    assert {m for m, _c in caps} >= {"PUT", "MOVE", "GET", "PROPFIND", "DELETE", "MKCOL", "POST"}
    assert all(c is not None and c <= 1024 ** 3 + 64 * 1024 for _m, c in caps)
    assert all(c <= 64 * 1024 for m, c in caps if m in ("PUT", "MOVE", "DELETE", "MKCOL"))


def test_a_folder_renamed_in_the_drive_is_found_again(anna_and_ben, drive, tmp_path, monkeypatch):
    """DAV-7: by the owner in her drive, by a member in theirs; and the owner's own words when it is not found."""
    anna, carol, desc, cdesc = _with_carol(anna_and_ben, drive, tmp_path, monkeypatch)
    _rename(drive, f"anna@uva.nl/{desc['folder']}", "anna@uva.nl/Our team")
    with anna:
        out = folder.sync_now(anna.ws)
        assert [x["kind"] for x in out["problems"]] == [NOT_FOUND] and "found it again" in out["problems"][0]["message"]
        assert space.configured(anna.ws)["folder"] == "Our team"
    _round(anna)
    _round(carol)   # (her share follows the folder, not its name)
    for sh in drive.state.shares.values():
        sh["mount"] = "Team work"   # Carol renames it in her own files
    with carol:
        out = folder.sync_now(carol.ws)
        assert "found it again" in out["problems"][0]["message"] and space.configured(carol.ws)["folder"] == "Team work"
    _round(carol)
    drive.state.dirs.add("anna@uva.nl/Archive")
    _rename(drive, "anna@uva.nl/Our team", "anna@uva.nl/Archive/Our team")   # deeper than ENLENS looks
    _age(anna, "folder_search_at", space.FOLLOW_SEARCH_EVERY + 1)
    with anna:
        n = len(drive.state.calls)
        out = folder.sync_now(anna.ws)
        first = len(drive.state.calls) - n
        assert "not in your drive under that name" in out["problems"][0]["message"]
        n = len(drive.state.calls)
        folder.sync_now(anna.ws)   # (looked for again in half an hour, not each round)
        assert len(drive.state.calls) - n < first


def test_an_address_with_a_password_in_it_is_refused_without_showing_it(anna_and_ben, drive):
    """DAV-8."""
    with pytest.raises(webdav.WebDAVProblem) as e:
        webdav.normalise("https://anna:secret@drive.example.org/remote.php/webdav/")
    assert e.value.kind == "input" and "secret" not in str(e.value) and "anna" not in str(e.value)
    with pytest.raises(StorageProblem) as e:
        WebDAVStorage("https://anna:secret@drive.example.org/remote.php/webdav/", "u", "p")
    assert "secret" not in str(e.value)
    assert webdav.normalise("https://cloud.uni.nl/remote.php/dav/files/anna@uva.nl/") == \
        "https://cloud.uni.nl/remote.php/dav/files/anna@uva.nl/"   # (an @ in the path is a user name, and fine)
    anna, _ben = anna_and_ben
    _set_up(anna, drive)
    with anna:
        inv = space.invite(anna.ws, "Carol", drive_user="carol")
    forged = _forged(inv["link"], endpoint="https://x:secret@surfdrive.surf.nl/files/remote.php/nonshib-webdav/",
                     host="surfdrive.surf.nl")
    with pytest.raises(space.SpaceProblem) as e:
        space.peek(forged)
    assert e.value.kind == "link" and "secret" not in str(e.value)


def test_without_etags_a_file_written_again_is_still_seen_as_new(drive):
    """DAV-9: the size and the time written stand in for a missing ETag."""
    s = _store(drive)
    drive.state.no_etag = True
    s.put("space/x", b"one")
    first = s.list()["space/x"].etag
    s.put("space/x", b"two")   # the same size
    drive.state.mtimes["anna@uva.nl/Team folder/enlens/abc/space/x"] += 5
    assert s.list()["space/x"].etag != first


def test_hrefs_as_full_addresses_and_in_another_unicode_form(drive):
    """DAV-11: an href may be a whole address, and a folder's é may come back as e and an accent."""
    import unicodedata
    from urllib.parse import quote

    nfc = unicodedata.normalize("NFC", "Kódkönyv")
    s = _store(drive, folder=nfc)
    s.put("space/roster.json", b"r")
    base = f"/remote.php/dav/files/anna@uva.nl/{nfc}/enlens/abc/"
    drive.state.extra_hrefs = [quote(f"{drive.url}{base}space/keys.json", safe=":/@"),
                               quote(unicodedata.normalize("NFD", f"{base}space/read.json"), safe="/@")]
    assert set(s.list()) == {"space/roster.json", "space/keys.json", "space/read.json"}


def test_a_folder_shared_for_reading_only(anna_and_ben, drive, tmp_path, monkeypatch):
    """DAV-11: a share without the right to write: the round says so in words, and goes on asking (not a refused
    password)."""
    anna, carol, desc, cdesc = _with_carol(anna_and_ben, drive, tmp_path, monkeypatch)
    for sh in drive.state.shares.values():
        sh["permissions"] = 1
    with carol:
        h = claimcheck.check_hypothesis(carol.ws, "Hydrogen storage is cheap.", BaselineBackend(), "baseline", k=2)
        sharing.share(carol.ws, [{"kind": "check", "key": h}])
        out = folder.sync_now(carol.ws)
        probs = [x for x in out["problems"] if x["kind"] != "documents"]
        assert [x["kind"] for x in probs] == [DENIED] and "only for reading" in probs[0]["message"]
        assert space.status(carol.ws)["refused"] is None


def test_an_idle_round_asks_little_and_writes_nothing(anna_and_ben, drive, tmp_path, monkeypatch):
    anna, carol, desc, cdesc = _with_carol(anna_and_ben, drive, tmp_path, monkeypatch)
    _round(anna)
    _round(carol)
    for p, most in ((anna, 10), (carol, 6)):
        n, before = len(drive.state.calls), _tree(p.home)
        _round(p)
        assert len(drive.state.calls) - n <= most and _tree(p.home) == before


def test_the_team_tabs_notices_through_the_app(api, drive):  # noqa: F811
    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    assert api("GET", "/api/space/links")[1]["keychain"]
    st, r = api("POST", "/api/projects/Demo/space/webdav", {"address": drive.address("anna@uva.nl"),
                                                           "user": "anna@uva.nl", "password": USERS["anna@uva.nl"]})
    assert api.wait(r["job"]["id"])["state"] == "done"
    drive.state.names["carol"] = "Carol de Vries"
    st, inv = api("POST", "/api/projects/Demo/space/invites", {"label": "Carol", "drive_user": "carol"})
    assert st == 200 and inv["shared_with"] == {"user": "carol", "name": "Carol de Vries"}
    drive.state.users["anna@uva.nl"] = "revoked"
    st, r = api("POST", "/api/projects/Demo/shared-folder/sync", {})
    api.wait(r["job"]["id"])
    sp = api("GET", "/api/projects/Demo/shared-folder")[1]["space"]
    assert sp["refused"] and USERS["anna@uva.nl"] not in str(sp)
    st, r = api("POST", "/api/projects/Demo/space/drive-retry", {})
    assert st == 200 and r["space"]["refused"] is None
    assert api("DELETE", "/api/projects/Demo/space/notices/restored")[0] == 200
    assert api("DELETE", "/api/projects/Demo/space/notices/unshare-m0123456789ab")[0] == 400
    drive.state.users["anna@uva.nl"] = USERS["anna@uva.nl"]
