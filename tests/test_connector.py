import asyncio
import json
import os
import sys

import pytest

pytest.importorskip("mcp")

from mcp import Client, StdioServerParameters  # noqa: E402

from enlens_claims import claimcheck  # noqa: E402

CLAIM = "Green hydrogen production can increase water stress in arid regions."


@pytest.fixture
def home(tmp_path, monkeypatch, corpus):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def _call(client, name, args):
    return client.call_tool(name, args)


def _json(result):
    assert not result.is_error, result.content[0].text
    return json.loads(result.content[0].text)


def test_full_check_through_the_connector(home, corpus):
    from enlens_claims.mcp_server import build_server

    async def run():
        async with Client(build_server()) as c:
            assert "How to check a claim" in (c.instructions or "")
            names = {t.name for t in (await c.list_tools()).tools}
            assert {"create_project", "start_check", "submit_grades", "more_passages", "get_check"} <= names

            p = _json(await _call(c, "create_project", {"name": "Demo", "sources_path": str(corpus)}))
            assert p["project"] == "Demo" and p["documents_added"] == 3 and p["readable_passages_added"] > 0
            docs = _json(await _call(c, "list_documents", {}))["documents"]
            assert len(docs) == 3

            start = _json(await _call(c, "start_check", {"claim": CLAIM, "search_terms": ["freshwater", "water scarcity"],
                                                         "passages": 2}))
            assert start["passages"] and "supports" in start["rules"] and start["round"] == 1
            first = start["passages"][0]
            quote = " ".join(first["text"].split()[:6])

            bad = _json(await _call(c, "submit_grades", {"check_id": start["check_id"], "summary": "x", "grades": [
                {"passage": 1, "verdict": "supports", "confidence": 0.9, "quote": "words that are not there"}]}))
            assert bad["accepted"] is False and bad["attempts_left"] == 2 and "not found" in bad["problems"][0]

            good = _json(await _call(c, "submit_grades", {"check_id": start["check_id"], "summary": "Stated in P1.",
                                                          "grades": [{"passage": 1, "verdict": "supports",
                                                                      "confidence": 0.9, "quote": quote}]}))
            assert good["accepted"] and good["status"] == "supported" and good["evidence"][0]["quote"] == quote

            more = _json(await _call(c, "more_passages", {"check_id": start["check_id"], "passages": 2}))
            shown = {p["text"] for p in start["passages"]}
            assert more["round"] == 2 and more["passages"] and not ({p["text"] for p in more["passages"]} & shown)
            again = await _call(c, "more_passages", {"check_id": start["check_id"]})
            assert again.is_error and "Grade the passages already shown first" in again.content[0].text
            done = _json(await _call(c, "submit_grades", {"check_id": start["check_id"], "grades": [], "summary": "none"}))
            third = _json(await _call(c, "more_passages", {"check_id": start["check_id"], "passages": 2,
                                                           "search_terms": ["jobs", "employment"]}))
            assert third["round"] == 3 and ("rules" in third or not third["passages"])
            if third["passages"]:
                assert not ({p["text"] for p in third["passages"]} & (shown | {p["text"] for p in more["passages"]}))
                _json(await _call(c, "submit_grades", {"check_id": start["check_id"], "grades": [], "summary": "none"}))
            assert done["passages_read"] == len(start["passages"]) + len(more["passages"]) and done["status"] == "supported"


            listed = _json(await _call(c, "list_checks", {}))["checks"]
            assert listed[0]["graded_by"] == claimcheck.CHAT_MODEL

            err = await _call(c, "start_check", {"claim": "short", "search_terms": []})
            assert err.is_error and "at least 10 characters" in err.content[0].text
            err = await _call(c, "add_sources", {"project": "Nope", "sources_path": str(corpus)})
            assert err.is_error and "No single project matches" in err.content[0].text

            prompt = await c.get_prompt("check_claim", {"claim": CLAIM, "project": "Demo"})
            assert CLAIM in prompt.messages[0].content.text

    asyncio.run(run())
    # the browser app sees the same check
    from enlens_claims.gui import core
    h = claimcheck.history(core.open_project("Demo"))
    assert h[0]["model"] == claimcheck.CHAT_MODEL and h[0]["passages_read"] >= 3


def test_connector_over_stdio(home, corpus):
    from enlens_claims.gui import core
    from enlens_claims import ingest

    ws = core.create_project("Demo")
    ingest.ingest(ws, [corpus])
    env = {**os.environ, "ENLENS_HOME": str(home), "PYTHONPATH": os.pathsep.join(sys.path)}
    params = StdioServerParameters(command=sys.executable, args=["-m", "enlens_claims.mcp_server"], env=env)

    async def run():
        async with Client(params, read_timeout_seconds=60) as c:
            projects = _json(await c.call_tool("list_projects", {}))["projects"]
            assert projects == [{"project": "Demo", "documents": 3, "checks": 0}]
            start = _json(await c.call_tool("start_check", {"claim": CLAIM, "search_terms": ["water"]}))
            assert start["passages"]

    asyncio.run(run())


def test_desktop_config_is_merged_with_a_backup(home, tmp_path):
    from enlens_claims import mcp_server

    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))
    mcp_server.install_desktop(cfg)
    data = json.loads(cfg.read_text())
    assert data["theme"] == "dark" and set(data["mcpServers"]) == {"other", "enlens"}
    assert data["mcpServers"]["enlens"]["env"]["ENLENS_HOME"] == str(home)
    assert data["mcpServers"]["enlens"]["command"] == sys.executable
    assert data["mcpServers"]["enlens"]["args"] == ["-m", "enlens_claims.mcp_server"]
    assert json.loads((tmp_path / "claude_desktop_config.json.bak").read_text())["mcpServers"] == {"other": {"command": "x"}}
