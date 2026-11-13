"""0.18.0 (roadmap L5): the shared folder through the app (gui/api_folder.py), as the Team tab will use it."""
from __future__ import annotations

from pathlib import Path

from enlens_claims import bundle, claimcheck, people, sharing
from enlens_claims.llm import BaselineBackend
from enlens_claims.sync import folder
from test_app import api, home  # noqa: F401  (fixtures)


def test_the_shared_folder_through_the_app(api, tmp_path, monkeypatch):  # noqa: F811
    import os

    from enlens_claims import home as home_mod, ingest

    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    ws = home_mod.open_project("Demo")
    ingest.ingest(ws, [Path(__file__).resolve().parents[1] / "tools" / "demo_corpus"])
    hid = claimcheck.check_hypothesis(ws, "Remote work reduces commuting emissions.", BaselineBackend(), "baseline", k=2)
    sharing.share(ws, [{"kind": "check", "key": hid}])
    shared = tmp_path / "OneDrive - Közös" / "Team"
    shared.mkdir(parents=True)

    st, r = api("GET", "/api/projects/Demo/shared-folder")
    assert st == 200 and r["folder"] is None and r["people"] == [] and r["job"] is None and r["last_round"] is None
    assert api("POST", "/api/projects/Demo/shared-folder/sync")[0] == 400  # no folder chosen yet
    for bad, words in ((str(tmp_path / "nowhere"), "no folder"), (str(ws.root / "exports"), "inside this project"),
                       ("", "Choose")):
        st, r = api("PUT", "/api/projects/Demo/shared-folder", {"path": bad})
        assert st == 400 and words in r["error"]
    st, r = api("PUT", "/api/projects/Demo/shared-folder", {"path": str(shared), "keep_out": True})
    assert st == 200 and r["folder"] == str(shared.resolve()) and r["reachable"] is True
    assert r["keep_out"] == {"mine": True, "colleagues": [], "in_force": True}
    assert api("PUT", "/api/projects/Demo/shared-folder/keep-out", {"keep_out": "yes"})[0] == 400
    st, r = api("PUT", "/api/projects/Demo/shared-folder/keep-out", {"keep_out": False})
    assert st == 200 and r["keep_out"]["mine"] is False

    st, r = api("POST", "/api/projects/Demo/shared-folder/sync")
    assert st == 200 and r["job"]["kind"] == "folder-sync"
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done" and job["result"]["wrote"]["seq"] == 1 and not job["result"]["problems"]
    st, r = api("GET", "/api/projects/Demo/shared-folder")
    assert r["me"]["last_written"] == 1 and r["last_round"]["result"]["wrote"]["snapshot"]

    # a colleague, Ben, with his own ENLENS folder and copy, writes into the same folder
    zip_path = tmp_path / "demo.zip"
    bundle.export_project(ws, zip_path)
    me_home = os.environ["ENLENS_HOME"]
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home-ben"))
    try:
        home_mod.update_settings({"your_name": "Ben"})
        ben_id = people.me()
        ben = bundle.import_project(zip_path, tmp_path / "ben-project")
        hb = claimcheck.check_hypothesis(ben, "Cycling lanes cut car trips.", BaselineBackend(), "baseline", k=2)
        sharing.share(ben, [{"kind": "check", "key": hb}])
        folder.set_folder(ben, str(shared))
        assert folder.sync_now(ben)["wrote"]["seq"] == 1
    finally:
        monkeypatch.setenv("ENLENS_HOME", me_home)

    st, r = api("GET", "/api/projects/Demo/shared-folder")
    assert [(p["id"], p["name"], p["last_bundle"], p["read_up_to"], p["waiting"]) for p in r["people"]] == \
        [(ben_id, "Ben", 1, None, 1)]
    job = api.wait(api("POST", "/api/projects/Demo/shared-folder/sync")[1]["job"]["id"])
    got = [e for e in job["result"]["read"] if e["report"]]
    assert [(e["name"], e["bundles"]) for e in got] == [("Ben", [1, 1])] and got[0]["report"]["checks"]["new"] == 1
    assert ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (hb,))
    st, r = api("GET", "/api/projects/Demo/shared-folder")
    assert r["people"][0]["read_up_to"] == 1 and r["people"][0]["waiting"] == 0 and r["people"][0]["last_read_at"]

    st, r = api("DELETE", "/api/projects/Demo/shared-folder")
    assert st == 200 and r["folder"] is None and list(shared.glob("ENLENS-*"))  # nothing in the folder is removed
    assert api("GET", "/api/projects/Nope/shared-folder")[0] == 404
