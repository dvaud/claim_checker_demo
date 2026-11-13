"""0.17.2: an export from the command line, and the connector's search, run one search each.

- `enlens search ... --out file.csv` used to run the whole search again for every 1,000 lines when the search was not
  kept (with --code, or over 300,000 hits); with the cache it was one search, and still is;
- the connector's search_corpus ran its search twice (once for the counts of all documents, once for the lines of
  those Claude may read); when Claude may read every document it is one search, with the same answer.
"""
from __future__ import annotations

import csv
import json

import pytest

from enlens_claims import cli, concordance, home, ingest


def _count_searches(monkeypatch) -> list:
    calls: list = []
    real = concordance._search_hits

    def counting(*a, **k):
        calls.append(a[3:5])
        return real(*a, **k)

    monkeypatch.setattr(concordance, "_search_hits", counting)
    return calls


@pytest.fixture
def zebras(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    ws = home.create_project("Zebras")
    folder = tmp_path / "docs"
    folder.mkdir()
    for i in range(3):
        paras = [" ".join(f"The zebra number {i}-{n}-{m} crossed the river." for m in range(8)) for n in range(120)]
        (folder / f"zoo{i}.txt").write_text("\n\n".join(paras), encoding="utf-8", newline="\n")
    ingest.ingest(ws, [folder])
    return ws


def _export(ws, tmp_path, *extra):
    out = tmp_path / "out.csv"
    rc = cli.main(["--ws", str(ws.root), "search", "zebra", "--out", str(out), "--limit", "5", *extra])
    assert rc == 0
    with open(out, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_the_export_of_more_than_a_thousand_lines_is_one_search(zebras, tmp_path, monkeypatch, capsys):
    calls = _count_searches(monkeypatch)
    rows = _export(zebras, tmp_path)
    assert len(rows) == 3 * 120 * 8 > 1000
    assert len(calls) == 1          # the page printed and every page of the CSV: the kept search answers them all


def test_a_search_that_is_not_kept_is_still_not_run_once_per_thousand_lines(zebras, tmp_path, monkeypatch, capsys):
    want = _export(zebras, tmp_path)
    monkeypatch.setattr(concordance, "HITS_KEPT", 10)        # as a search over 300,000 hits: not kept
    concordance._KEPT.clear()
    calls = _count_searches(monkeypatch)
    rows = _export(zebras, tmp_path)
    assert rows == want
    assert len(calls) <= 2          # the page printed, and the export in one go (it was 1 + 3 for these 2,880 lines)


def test_the_export_has_every_line_past_the_largest_page(zebras, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(concordance, "EXPORT_MAX", 700)      # pages of 700 lines, four of them
    rows = _export(zebras, tmp_path)
    assert len(rows) == 2880
    assert len({r["Passage id (to find it again in ENLENS)"] + r["Left"] + r["Right"] for r in rows}) == 2880


# ---------------------------------------------------------------------------------------------
# the connector's search
# ---------------------------------------------------------------------------------------------
def _call_search(**args):
    pytest.importorskip("mcp")
    import asyncio

    from mcp import Client

    from enlens_claims.mcp_server import build_server

    async def run():
        async with Client(build_server()) as c:
            r = await c.call_tool("search_corpus", {"project": "Zebras", "query": "zebra", **args})
            assert not r.is_error, r.content[0].text
            return json.loads(r.content[0].text)

    return asyncio.run(run())


def test_the_connectors_search_is_one_search_when_claude_may_read_every_document(zebras, monkeypatch):
    calls = _count_searches(monkeypatch)
    got = _call_search(lines=20)
    assert len(calls) == 1
    # the same answer as the two searches gave
    everything = concordance.search(zebras, "zebra", "any", None, "doc", 0, 1)
    assert got["hits"] == everything["total"] == 2880 and got["passages"] == everything["passages"]
    assert [d["hits"] for d in got["documents"]] == [d["hits"] for d in everything["per_doc"][:30]]
    assert len(got["lines"]) == 20 and got["more"] == 2880 - 20 and "restricted_hits" not in got
    # a search of some documents only
    some = [r[0] for r in zebras.query("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 2")]
    calls.clear()
    got = _call_search(document_ids=some, lines=5)
    assert len(calls) == 1 and got["hits"] == 2 * 960


def test_the_connectors_search_still_counts_the_documents_claude_may_not_read(zebras, monkeypatch):
    from enlens_claims import access

    one = zebras.query("SELECT doc_id FROM documents ORDER BY doc_id")[0][0]
    access.set_documents(zebras, [one], "none")
    calls = _count_searches(monkeypatch)
    got = _call_search(lines=5)
    assert len(calls) == 2                                   # the counts of all, the lines of those it may read
    assert got["hits"] == 2880 and got["restricted_hits"] == 960
