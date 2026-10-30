"""0.11: the connector's tools with a mixed corpus: no restricted text, counts instead, "No AI" titles hidden, and
create_project / add_sources taking the AI setting of the documents they add."""
from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("mcp")

from helpers_0110 import mixed_project, use_local_model, write_corpus  # noqa: E402
from mcp import Client  # noqa: E402

from enlens_claims import access, home  # noqa: E402

HYP = "Green hydrogen production can increase water stress in arid regions."


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    use_local_model(monkeypatch, None)
    return tmp_path


def _run(fn):
    from enlens_claims.mcp_server import build_server

    async def go():
        async with Client(build_server()) as c:
            async def call(name, args):
                r = await c.call_tool(name, args)
                assert not r.is_error, r.content[0].text
                return json.loads(r.content[0].text)
            return await fn(call)

    return asyncio.run(go())


def test_create_project_and_add_sources_with_a_setting(env):
    write_corpus(env / "a")

    async def fn(call):
        p = await call("create_project", {"name": "Interviews", "sources_path": str(env / "a"), "ai_access": "none"})
        assert p["ai_access"] == "none" and p["documents_added"] == 3
        docs = (await call("list_documents", {"project": "Interviews"}))["documents"]
        assert [d["title"] for d in docs] == ["Restricted document 1", "Restricted document 2", "Restricted document 3"]
        s = await call("search_corpus", {"project": "Interviews", "query": "water"})
        assert s["lines"] == [] and s["restricted_hits"] == s["hits"] > 0

    _run(fn)
    ws = home.open_project("Interviews")
    assert access.default(ws) == "none" and access.default_chosen(ws)  # the first answer is the project's default


def test_every_tool_keeps_restricted_text_out(env):
    ws = home.create_project("Mixed")
    ids = mixed_project(ws, env / "corpus")

    async def fn(call):
        prof = await call("document_profile", {"project": "Mixed", "document_id": ids["local"]})
        assert prof["restricted_note"] and all("examples" not in c for c in prof["codes"])
        prof = await call("document_profile", {"project": "Mixed", "document_id": ids["cloud"]})
        assert "restricted_note" not in prof
        con = await call("find_concept", {"project": "Mixed", "name": "hydrogen"})
        assert all("zqx" not in w.lower() for w in con["wordings"])
        st = await call("start_check", {"project": "Mixed", "claim": HYP, "search_terms": ["water"], "passages": 12,
                                        "per_document": 4})
        assert st["restricted_passages"] > 0 and all("zqx" not in p["text"].lower() for p in st["passages"])
        quote = " ".join(st["passages"][0]["text"].split()[:6])
        done = await call("submit_grades", {"check_id": st["check_id"], "summary": "one",
                                            "grades": [{"passage": 1, "verdict": "supports", "confidence": 0.9,
                                                        "quote": quote}]})
        assert done["accepted"]
        assert done["restricted_evidence"]["waiting_for_the_user"] > 0  # no local model: they wait for the person
        assert all("zqx" not in json.dumps(e).lower() for e in done["evidence"])
        return done

    _run(fn)
