"""0.18 (M3): search by meaning is set up from the Search page.

Three states, told by the project's `search` block: no model chosen (a line that leads to Settings → Documents), a model
chosen but the project not (fully) set up (a prompt with the same button and job as the Documents page), and set up
(nothing to say). The page draws them from that block, so these tests read the API and the page source."""
from pathlib import Path

import fake_servers
from test_app import Api, api, home  # noqa: F401  (fixtures)

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"


def test_the_three_states_through_the_api(api, corpus):
    srv, url = fake_servers.start("ollama")
    try:
        api("PUT", "/api/settings", {"embed_backend": "off", "embed_model": ""})
        api("POST", "/api/projects", {"name": "P"})
        api.wait(api("POST", "/api/projects/P/ingest", {"path": str(corpus)})[1]["job"]["id"])
        # 1: no model chosen
        s = api("GET", "/api/projects/P")[1]["search"]
        assert not s["model"] and not s["embedded"]
        # 2: a model chosen, this project not set up: passages are there, none covered
        api("PUT", "/api/settings", {"embed_backend": "ollama", "embed_url": url, "embed_model": fake_servers.FAKE_EMBED})
        s = api("GET", "/api/projects/P")[1]["search"]
        assert s["model"] == fake_servers.FAKE_EMBED and s["passages"] > 0 and s["embedded"] == 0 and not s["complete"]
        # the page's button starts the Documents page's job; a second press attaches to it
        st, first = api("POST", "/api/projects/P/index")
        assert st == 200 and first["job"]["kind"] == "index"
        st, second = api("POST", "/api/projects/P/index")
        assert second["job"]["id"] == first["job"]["id"] or second["job"]["state"] in ("done", "queued", "running")
        assert api.wait(first["job"]["id"])["state"] == "done"
        # 3: set up
        s = api("GET", "/api/projects/P")[1]["search"]
        assert s["complete"] and s["embedded"] == s["passages"]
    finally:
        srv.shutdown()


def test_starting_without_a_model_is_refused_in_words(api):
    api("PUT", "/api/settings", {"embed_backend": "off", "embed_model": ""})
    api("POST", "/api/projects", {"name": "P"})
    st, r = api("POST", "/api/projects/P/index")
    assert st == 400 and "Settings" in r["error"]


def test_the_search_page_draws_each_state():
    js = (STATIC / "views" / "search.js").read_text(encoding="utf-8")
    box = js[js.index("async function setUpMeaning"):js.index("const fresh = latest()")]
    # no model: a link a keyboard reaches, not a tooltip on a disabled box only
    assert 'link({ href: "#/settings/documents" }' in box and "if (!search.model)" in box
    # a model, not set up (or partly): the prompt, the covered counts and the Documents page's button and job
    assert "Set up search by meaning for this project" in box and "excerpts are covered so far" in box
    assert '"POST", `/api/projects/${P(project)}/index`' in box
    # a running job (started anywhere) shows as progress and no button
    running = box[box.index("if (job) {"):box.index("if (search.complete")]
    assert "simpleProgress" in running and "button(" not in running
    assert 'j.kind === "index"' in box and "!TERMINAL.has(j.state)" in box
    # when it ends the figures are read again and the tick box is usable without a reload
    assert "info.search = (await api(" in box
    assert "meaning.disabled = !semantic" in js
    # the old hint that only pointed elsewhere is gone
    assert "Turn on search by meaning under Settings" not in js


def test_the_settings_note_names_the_documents_page():
    js = (STATIC / "views" / "settings.js").read_text(encoding="utf-8")
    assert "set up search by meaning on the project’s Documents page" in js
    assert "Set up search by meaning under Documents if needed" not in js
