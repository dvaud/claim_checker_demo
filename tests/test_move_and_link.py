"""Roles (DESIGN-roles §4.11, §5.5, §5.7): the move zip always asks who this computer is, and decides it before any
project comes in; a folder linked as a project is cleaned as a project from a zip is."""
from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from enlens_claims import bundle, home, people
from enlens_claims.store import Workspace
from enlens_claims.sync import folder
from owner_helpers import choices, leave_out, sync
from test_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)
from test_owner import shared_dir, team  # noqa: F401  (fixtures)


def _move_zip(p: Person, tmp: Path, name: str = "Shared", settings: dict | None = None) -> Path:
    """`p`'s computer, moved: their project in their data folder, and `export_all`."""
    with p:
        if name not in home.list_projects():
            home.link_existing(str(p.ws.root), name)
        if settings:
            home.update_settings(settings)
        out = tmp / f"move-{p.name}.zip"
        bundle.export_all(out)
    return out


def _at(tmp: Path, monkeypatch, name: str) -> Path:
    h = tmp / f"computer-{name}"
    monkeypatch.setenv("ENLENS_HOME", str(h))
    return h


# ---- the move zip -------------------------------------------------------------------------------------------
def test_the_mode_must_be_said(team, tmp_path, monkeypatch):
    _anna, ben, _carol = team
    out = _move_zip(ben, tmp_path)
    _at(tmp_path, monkeypatch, "new")
    with pytest.raises(TypeError):
        bundle.import_all(out)  # no default
    with pytest.raises(ValueError, match="moving to this computer or will use both"):
        bundle.import_all(out, "")
    assert home.list_projects() == []


def test_peek_says_what_comes_before_anything_comes(team, tmp_path, monkeypatch):
    _anna, ben, _carol = team
    out = _move_zip(ben, tmp_path, settings={"themes_k": 17, "ollama_url": "http://10.0.0.5:11434",
                                             "openai_url": "http://localhost:1234/v1"})
    _at(tmp_path, monkeypatch, "new")
    m = bundle.peek_move(out)
    assert m["fresh"] is True and m["person"] == {"id": ben.id, "name": "Ben"}
    assert [p["name"] for p in m["projects"]] == ["Shared"] and m["projects"][0]["documents"] >= 1
    assert m["settings"]["themes_k"] == 17
    assert not {"person_id", "your_name", "installation_id", "installation_place", "project", "ollama_url"} & set(m["settings"])
    servers = {s["key"]: s for s in m["servers"]}
    assert servers["ollama_url"]["here"] is False and servers["openai_url"]["here"] is True
    assert home.list_projects() == [] and home.load_settings()["themes_k"] != 17
    with zipfile.ZipFile(out) as zf:
        sent = json.loads(zf.read(bundle.MOVE_MANIFEST))["settings"]
    assert "installation_id" not in sent and "installation_place" not in sent  # never in a move zip


def test_moving_takes_the_person_before_the_projects_so_they_stay_theirs(team, tmp_path, monkeypatch):
    """DESIGN-roles §1.2 (2): the projects came in before the person's id, so the mover's own projects were taken
    for a colleague's: the folder record went, and a Leave out not proposed yet was reset to the project's."""
    anna, ben, _carol = team
    doc = next(iter(r[0] for r in anna.ws.query("SELECT doc_id FROM documents")))
    fp = leave_out(ben, doc)  # Ben's own change, not sent yet (no round since)
    with ben:
        written = ben.ws.scalar("SELECT COUNT(*) FROM sync_written")
    assert written
    out = _move_zip(ben, tmp_path, settings={"themes_k": 17})
    _at(tmp_path, monkeypatch, "new")
    r = bundle.import_all(out, "moving")
    assert r["mode"] == "moving" and r["person"] == {"id": ben.id, "name": "Ben"}
    assert people.me() == ben.id and people.my_name() == "Ben"
    ws = home.open_project("Shared")
    assert ws.scalar("SELECT COUNT(*) FROM sync_written") == written  # the folder record stays
    assert {r[0]: r[1] for r in ws.query("SELECT fp, included FROM block_choices WHERE doc_id=?", (doc,))}.get(fp) == 0
    assert r["settings"] is False and home.load_settings()["themes_k"] != 17  # the settings only when asked


def test_moving_is_only_for_a_computer_with_no_project(team, tmp_path, monkeypatch):
    _anna, ben, _carol = team
    out = _move_zip(ben, tmp_path)
    _at(tmp_path, monkeypatch, "used")
    home.create_project("Mine")
    me = people.me()
    assert bundle.peek_move(out)["fresh"] is False
    with pytest.raises(ValueError, match="already has projects"):
        bundle.import_all(out, "moving")
    assert people.me() == me and home.list_projects() == ["Mine"]
    r = bundle.import_all(out, "both", name="Ben (2)")
    assert people.me() == me and r["person"]["id"] == me  # a computer in use keeps its own id
    assert sorted(home.list_projects()) == ["Mine", "Shared"]


def test_both_computers_makes_a_second_person_whose_copy_is_a_colleagues(team, tmp_path, monkeypatch):
    _anna, ben, _carol = team
    with ben:
        assert ben.ws.scalar("SELECT COUNT(*) FROM sync_written")
    out = _move_zip(ben, tmp_path, settings={"themes_k": 17})
    _at(tmp_path, monkeypatch, "laptop")
    r = bundle.import_all(out, "both", settings=True, name="Ben (laptop)")
    assert r["mode"] == "both" and people.me() != ben.id and people.my_name() == "Ben (laptop)"
    assert r["settings"] is True and home.load_settings()["themes_k"] == 17
    ws = home.open_project("Shared")
    assert not ws.scalar("SELECT COUNT(*) FROM sync_written")  # no folder record: Ben's, not this person's
    assert folder.chosen(ws) is None


def test_addresses_not_on_this_computer_come_only_when_ticked(team, tmp_path, monkeypatch):
    _anna, ben, _carol = team
    out = _move_zip(ben, tmp_path, settings={"ollama_url": "http://10.0.0.5:11434", "backend": "ollama",
                                             "ollama_model": "llama3", "openai_url": "http://127.0.0.1:9999/v1",
                                             "themes_k": 9})
    _at(tmp_path, monkeypatch, "a")
    bundle.import_all(out, "moving", settings=True)
    s = home.load_settings()
    assert s["themes_k"] == 9 and s["openai_url"] == "http://127.0.0.1:9999/v1"  # on this computer: taken
    assert s["ollama_url"] == home.DEFAULTS["ollama_url"]  # another computer's: not without a tick
    assert s["backend"] == home.DEFAULTS["backend"] and s["ollama_model"] == ""  # left without its address
    _at(tmp_path, monkeypatch, "b")
    bundle.import_all(out, "moving", settings=True, servers=["ollama_url"])
    s = home.load_settings()
    assert s["ollama_url"] == "http://10.0.0.5:11434" and s["backend"] == "ollama"


def test_the_app_asks_before_a_move_zip_comes_in(team, tmp_path, monkeypatch):
    import threading

    from enlens_claims.gui.server import make_server
    from test_app import Api

    _anna, ben, _carol = team
    out = _move_zip(ben, tmp_path)
    _at(tmp_path, monkeypatch, "new")
    srv, app = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    call = Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token)
    try:
        st, r = call("POST", "/api/projects/import", raw=out.read_bytes(), headers={"Content-Type": "application/zip"})
        assert st == 200 and r["move"]["person"]["id"] == ben.id and r["token"] and "moved" not in r
        assert home.list_projects() == []  # nothing yet
        st, _bad = call("POST", "/api/move", {"token": r["token"], "mode": "sideways"})
        assert st == 400 and home.list_projects() == []
        st, done = call("POST", "/api/move", {"token": r["token"], "mode": "both", "name": "Ben (2)"})
        assert st == 200 and done["moved"]["projects"][0]["name"] == "Shared" and people.my_name() == "Ben (2)"
        st, _again = call("POST", "/api/move", {"token": r["token"], "mode": "both"})
        assert st == 410  # the upload went once it was brought in
        st, two = call("POST", "/api/second-computer", {"name": "Ben (desk)"})
        assert st == 200 and two["person"]["name"] == "Ben (desk)" and people.me() == two["person"]["id"]
    finally:
        srv.shutdown()
        srv.server_close()


# ---- linking a folder -----------------------------------------------------------------------------------------
def _trigger(root: Path) -> None:
    cx = sqlite3.connect(root / "enlens.sqlite")
    cx.execute("CREATE TRIGGER evil AFTER UPDATE ON documents BEGIN UPDATE documents SET ai_access='cloud'; END")
    cx.execute("CREATE VIEW sneaky AS SELECT * FROM documents")
    cx.commit()
    cx.close()


def test_linking_ones_own_folder_drops_triggers_and_cleans_its_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    ws = Workspace.create(tmp_path / "pilot")
    ws.close_all()
    _trigger(ws.root)
    cfg = json.loads(ws.config_path.read_text(encoding="utf-8"))
    cfg.update({"thresholds": "nonsense", "shared_folder": str(tmp_path / "team")})
    ws.config_path.write_text(json.dumps(cfg), encoding="utf-8")
    rep = bundle.check_linked(ws.root)
    assert rep["other"] is None and rep["triggers"] == 1 and rep["views"] == 1 and rep["config"] == ["thresholds"]
    assert home.link_existing(str(ws.root), "pilot") == "pilot"
    cx = sqlite3.connect(ws.root / "enlens.sqlite")
    assert not cx.execute("SELECT name FROM sqlite_master WHERE type IN ('trigger', 'view') AND name IN "
                          "('evil', 'sneaky')").fetchall()
    cx.close()
    new = json.loads(ws.config_path.read_text(encoding="utf-8"))
    assert isinstance(new["thresholds"], dict) and new["shared_folder"] == str(tmp_path / "team")  # this computer's
    assert (ws.root / "config.json.before-linking").is_file()


def test_a_virtual_table_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    ws = Workspace.create(tmp_path / "odd")
    ws.close_all()
    cx = sqlite3.connect(ws.root / "enlens.sqlite")
    cx.execute("CREATE TABLE gen(a INT, b INT GENERATED ALWAYS AS (a + 1))")
    cx.commit()
    cx.close()
    with pytest.raises(ValueError, match="more than a project's rows"):
        home.link_existing(str(ws.root), "odd")
    assert "odd" not in home.list_projects()


def test_a_folder_of_another_person_asks_first_then_is_cleaned_like_an_import(team, tmp_path, monkeypatch):
    anna, _ben, _carol = team
    with anna:
        anna.ws.close_all()
    root = anna.ws.root
    _trigger(root)
    (root / "cache").mkdir(exist_ok=True)
    (root / "cache" / "x.bin").write_bytes(b"x")
    (root / "backups").mkdir(exist_ok=True)
    (root / "backups" / "old.sqlite").write_bytes(b"x")
    cx = sqlite3.connect(root / "enlens.sqlite")
    cx.execute("INSERT INTO bib_items(item_key, files_json) VALUES ('k1', ?)",
               (json.dumps([{"name": "a.pdf", "path": "/Users/anna/a.pdf"}]),))
    cx.commit()
    written = cx.execute("SELECT COUNT(*) FROM sync_written").fetchone()[0]
    cx.close()
    assert written
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "someone-else"))
    with pytest.raises(home.NeedsCleaning) as e:
        home.link_existing(str(root), "Annas")
    rep = e.value.report
    assert rep["other"]["id"] == anna.id and rep["other"]["name"] == "Anna"
    assert rep["triggers"] == 1 and rep["views"] == 1 and rep["bib_paths"] == 1 and rep["cache"] is True
    assert "Anna’s project" in str(e.value)
    assert "Annas" not in home.list_projects() and (root / "cache").is_dir()  # nothing changed yet
    assert home.link_existing(str(root), "Annas", clean=True) == "Annas"
    ws = home.open_project("Annas")
    assert not ws.scalar("SELECT COUNT(*) FROM sync_written") and folder.chosen(ws) is None
    assert not ws.scalar("SELECT COUNT(*) FROM sqlite_master WHERE name IN ('evil', 'sneaky')")
    assert "/Users/anna" not in (ws.scalar("SELECT files_json FROM bib_items WHERE item_key='k1'") or "")
    assert not (root / "cache").exists() and (root / "backups.before-linking" / "old.sqlite").is_file()


def test_the_link_route_answers_409_until_the_person_says_clean(team, tmp_path, monkeypatch):
    from enlens_claims.gui.api_common import ApiError
    from enlens_claims.gui.api_documents import DocumentsApi

    anna, _ben, _carol = team
    with anna:
        anna.ws.close_all()
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "someone-else"))

    class Fake(DocumentsApi):
        def __init__(self, body):
            self.body = body
            self.app = type("A", (), {"project_summary": lambda _s, n: {"name": n}})()

        def _body(self):
            return self.body

    with pytest.raises(ApiError) as e:
        Fake({"path": str(anna.ws.root), "name": "Annas"}).post_link({})
    assert e.value.status == 409 and e.value.extra["needs_cleaning"]["other"]["id"] == anna.id
    assert Fake({"path": str(anna.ws.root), "name": "Annas", "clean": True}).post_link({})["project"]["name"] == "Annas"


def test_after_linking_a_shared_project_its_rounds_go_on(team, tmp_path, monkeypatch):
    """ENLENS's own change counters go with the other triggers; the next round makes them again."""
    anna, ben, carol = team
    with anna:
        home.link_existing(str(anna.ws.root), "Mine")
    sync(anna, ben, carol, rounds=1)
    with anna:
        cx = sqlite3.connect(anna.ws.root / "enlens.sqlite")
        assert cx.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'enlens_changes_%'"
                          ).fetchone()[0]
        cx.close()
    assert choices(anna, next(iter(r[0] for r in anna.ws.query("SELECT doc_id FROM documents")))) is not None


def test_the_copy_a_zip_made_for_this_person_is_theirs_to_link(anna_and_ben, tmp_path, monkeypatch):  # noqa: F811
    """Ben's copy from Anna's zip knows only Anna until Ben sends something: it is still Ben's own copy."""
    _anna, ben = anna_and_ben
    with ben:
        ben.ws.close_all()
        assert bundle.check_linked(ben.ws.root)["other"] is None
        assert home.link_existing(str(ben.ws.root), "Mine") == "Mine"
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "carol"))
    assert bundle.check_linked(ben.ws.root)["other"]["name"] == "Anna"  # to anyone else, it is the maker's


def test_a_zip_of_a_project_with_an_owner_needs_format_4(anna_and_ben, tmp_path):  # noqa: F811
    """DESIGN-roles §3.3: an older copy refuses a zip of a project with an owner."""
    anna, _ben = anna_and_ben

    def needs(p: Person) -> int:
        with zipfile.ZipFile(p.send()) as zf:
            return json.loads(zf.read("bundle.json"))["sync_needs"]

    with anna:
        assert anna.ws.scalar("SELECT COUNT(*) FROM ownership")  # (Anna made it and sent it: she is its owner)
    assert needs(anna) == 4  # (a project with no owner: formats.zip_needs says 1, test_roles_schema)
