"""0.18.0rc2 (roadmap L6): the storage space through the app (gui/api_space.py), as the Team tab uses it."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from enlens_claims.sync import space
from test_app import api, home  # noqa: F401  (fixtures)

sys.path.insert(0, str(Path(__file__).parent))
import fake_b2  # noqa: E402


@pytest.fixture
def backblaze(monkeypatch):
    from enlens_claims.sync import _web

    monkeypatch.setattr(_web, "sleep", lambda s: None)
    srv, url = fake_b2.start()
    monkeypatch.setenv("ENLENS_B2_API", url)
    yield srv
    fake_b2.stop(srv)


def test_the_storage_space_through_the_app(api, backblaze):  # noqa: F811
    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    st, links = api("GET", "/api/space/links")
    assert st == 200 and links["b2_signup"].startswith("https://www.backblaze.com/") and links["r2_token"]
    st, r = api("GET", "/api/projects/Demo/shared-folder")
    assert st == 200 and r["space"] is None and r["folder"] is None
    assert api("POST", "/api/projects/Demo/space/b2", {"key_id": "x"})[0] == 400   # both halves of the key
    assert api("POST", "/api/projects/Demo/space/invites", {})[0] == 400            # no space yet
    assert api("POST", "/api/projects/Demo/space/dir", {"path": "/tmp"})[0] == 404   # only when trying the tab

    # a wrong key: the job ends with Backblaze's refusal in plain words, nothing set up
    st, r = api("POST", "/api/projects/Demo/space/b2", {"key_id": "nobody", "app_key": "nothing"})
    job = api.wait(r["job"]["id"])
    assert job["state"] == "error" and job["error"] and "Traceback" not in job["error"]
    assert api("GET", "/api/projects/Demo/shared-folder")[1]["space"] is None

    key_id, app_key = backblaze.master
    st, r = api("POST", "/api/projects/Demo/space/b2", {"key_id": key_id, "app_key": app_key})
    assert st == 200 and r["job"]["kind"] == "space-setup"
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done", job
    assert job["result"]["service"] == "b2" and job["result"]["keeper"] and job["result"]["warnings"] == []
    st, r = api("GET", "/api/projects/Demo/shared-folder")
    assert r["space"]["where"].startswith("Backblaze B2") and r["folder"]   # the rounds work on its copy here
    assert api("POST", "/api/projects/Demo/space/b2", {"key_id": key_id, "app_key": app_key})[0] == 409

    st, r = api("POST", "/api/projects/Demo/shared-folder/sync")
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done" and not job["result"]["problems"], job

    st, inv = api("POST", "/api/projects/Demo/space/invites", {"label": "Ben"})
    assert st == 200 and inv["link"].startswith(space.LINK) and inv["link"] in inv["message"]
    assert [i["label"] for i in inv["status"]["space"]["invites"]] == ["Ben"]
    st, r = api("DELETE", f"/api/projects/Demo/space/invites/{inv['part']}")
    assert st == 200 and r["space"]["invites"] == []
    assert api("DELETE", f"/api/projects/Demo/space/members/{inv['part']}")[0] == 400   # never joined

    for bad in ("", "https://example.org/x", space.LINK + "AAAA"):
        st, r = api("POST", "/api/join-team", {"link": bad})
        assert st == 400 and "invite link" in r["error"]
    assert api("POST", "/api/projects/Demo/space/join", {"link": inv["link"]})[0] == 409   # has a space already

    st, r = api("DELETE", "/api/projects/Demo/space")
    assert st == 200 and r["space"] is None and r["folder"] is None
