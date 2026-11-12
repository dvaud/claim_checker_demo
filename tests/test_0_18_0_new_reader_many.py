"""0.18 (M7): moving many documents to the new reader.

- `POST …/new-reader/preview` is a dry run as a job: per document how many results would find no place (and which),
  how many documents move cleanly, which cannot be read again; nothing is stored or changed;
- `POST …/new-reader` with `keep_unplaced` (the person's *Move anyway*) moves a document with results that have no place:
  they are kept as records that point nowhere, as in a move from the document's own page;
- the move's result has a summary and the counts the one-line note and the compact table need;
- the Documents page asks first, says how many move cleanly, and offers the combined review and *Review next*.
"""
from __future__ import annotations

from pathlib import Path

from enlens_claims import ingest, reread

from test_0_15_0_read_with_new_reader import _dump  # noqa: F401
from test_0_15_7_documents_reading import _project
from test_app import Api, api, home  # noqa: F401  (fixtures)

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"


def test_the_dry_run_counts_what_would_move_cleanly_and_what_would_lose_its_place(api, home, tmp_path, monkeypatch):  # noqa: F811
    name, one, two = _project(home, tmp_path, monkeypatch, lost=True)
    ws = home.open_project(name)
    before = _dump(ws)
    st, r = api("POST", f"/api/projects/{name}/new-reader/preview", {})
    assert st == 200 and r["job"]["kind"] == "new_reader_preview" and "2 documents" in r["job"]["title"]
    job = api.wait(r["job"]["id"], timeout=120)
    assert job["state"] == "done", job
    res = job["result"]
    assert res["summary"] == {"documents": 2, "clean": 1, "would_lose": 1, "cannot": 0, "results_without_place": 1}
    by = {d["doc_id"]: d for d in res["documents"]}
    assert by[one]["no_place"] == 0 and by[one]["not_placed"] == [] and by[one]["ok"]
    lost = by[two]
    assert lost["no_place"] == 1 and len(lost["not_placed"]) == 1 and lost["results"] >= 1
    item = lost["not_placed"][0]
    assert item["quote"] and item["kind_text"] and "why" in item          # what the combined review shows
    # nothing was stored or moved
    assert _dump(home.open_project(name)) == before
    assert dict(ws.query("SELECT doc_id, reader FROM documents")) == {one: 1, two: 1}


def test_the_dry_run_takes_the_same_documents_as_the_move(api, home, tmp_path, monkeypatch):  # noqa: F811
    name, one, two = _project(home, tmp_path, monkeypatch, lost=False)
    st, r = api("POST", f"/api/projects/{name}/new-reader/preview", {"doc_ids": [two, "not-a-document"]})
    assert st == 200
    res = api.wait(r["job"]["id"], timeout=120)["result"]
    assert [d["doc_id"] for d in res["documents"]] == [two] and res["summary"]["clean"] == 1
    assert api("POST", f"/api/projects/{name}/new-reader/preview", {"doc_ids": "all"})[0] == 400
    assert api("POST", f"/api/projects/{name}/new-reader", {"doc_ids": [two]})[0] == 200
    api.wait(next(j["id"] for j in api("GET", "/api/jobs")[1]["jobs"] if j["kind"] == "new_reader"), timeout=120)
    assert api("POST", f"/api/projects/{name}/new-reader/preview", {"doc_ids": [two]})[0] == 409


def test_move_anyway_keeps_the_results_without_a_place_as_records_that_point_nowhere(api, home, tmp_path, monkeypatch):  # noqa: F811
    name, one, two = _project(home, tmp_path, monkeypatch, lost=True)
    pre = api.wait(api("POST", f"/api/projects/{name}/new-reader/preview", {"doc_ids": [two]})[1]["job"]["id"], timeout=120)
    first_preview_quote = pre["result"]["documents"][0]["not_placed"][0]["quote"]
    # without Move anyway the document stays as it was
    st, r = api("POST", f"/api/projects/{name}/new-reader", {"doc_ids": [two]})
    first = api.wait(r["job"]["id"], timeout=120)["result"]
    assert [k["doc_id"] for k in first["kept"]] == [two] and first["kept"][0]["not_placed"] == 1
    assert first["summary"]["left_as_they_were"] == 1 and first["summary"]["moved_anyway"] is False
    ws = home.open_project(name)
    assert ws.scalar("SELECT reader FROM documents WHERE doc_id=?", (two,)) == 1
    # Move anyway
    st, r = api("POST", f"/api/projects/{name}/new-reader", {"doc_ids": [two], "keep_unplaced": True})
    assert st == 200
    res = api.wait(r["job"]["id"], timeout=120)["result"]
    assert not res["kept"] and [m["doc_id"] for m in res["moved"]] == [two]
    assert res["moved"][0]["no_place"] == 1
    assert res["summary"] == {"moved": 1, "left_as_they_were": 0, "results_moved": res["moved"][0]["results"],
                              "results_without_place": 1, "moved_anyway": True}
    ws = home.open_project(name)
    assert ws.scalar("SELECT reader FROM documents WHERE doc_id=?", (two,)) == ingest.READER
    # the result keeps its quote and points at no passage: a tombstone, which names no passage and never will
    lost_item = first_preview_quote
    v = ws.query("SELECT * FROM verifications WHERE quote=?", (lost_item,))[0]
    assert reread.is_tombstone(v["passage_id"]) and v["start"] is None and v["end"] is None
    assert not ws.query("SELECT 1 FROM passages WHERE passage_id=?", (v["passage_id"],))
    # how it was made is recorded: the document's own log of readings, and the research log
    assert ws.meta(f"read_again:{two}")
    assert ws.query("SELECT 1 FROM research_log WHERE text LIKE '%again with the new reader%'")


def test_a_clean_move_after_the_dry_run_reports_in_one_summary(api, home, tmp_path, monkeypatch):  # noqa: F811
    name, one, two = _project(home, tmp_path, monkeypatch, lost=True)
    r = api("POST", f"/api/projects/{name}/new-reader", {"doc_ids": [one]})[1]
    res = api.wait(r["job"]["id"], timeout=120)["result"]
    assert res["summary"]["moved"] == 1 and res["summary"]["results_without_place"] == 0 and not res["kept"]
    assert set(res["moved"][0]) >= {"doc_id", "title", "results", "left_out", "no_place"}


def test_a_document_that_cannot_be_read_again_is_listed_with_its_reason(api, home, tmp_path, monkeypatch):  # noqa: F811
    name, one, two = _project(home, tmp_path, monkeypatch, lost=False)
    ws = home.open_project(name)
    path = Path(ws.scalar("SELECT path FROM documents WHERE doc_id=?", (two,)))
    path.unlink()
    res = api.wait(api("POST", f"/api/projects/{name}/new-reader/preview", {})[1]["job"]["id"], timeout=120)["result"]
    gone = next(d for d in res["documents"] if d["doc_id"] == two)
    assert gone["ok"] is False and gone["reason"] and res["summary"]["cannot"] == 1 and res["summary"]["clean"] == 1
    res = api.wait(api("POST", f"/api/projects/{name}/new-reader", {"keep_unplaced": True})[1]["job"]["id"], timeout=120)["result"]
    assert [k["doc_id"] for k in res["kept"]] == [two] and res["kept"][0]["cannot"] is True


def test_the_page_checks_first_then_offers_the_three_ways_on():
    js = (STATIC / "views" / "sources.js").read_text(encoding="utf-8")
    assert "`/api/projects/${P(project)}/new-reader/preview`" in js and 'j.kind === "new_reader_preview"' in js
    plan = js[js.index("function nrPlan(plan)"):js.index("async function moveNr")]
    assert "that ${clean.length === 1 ? \"moves\" : \"move\"} cleanly" in plan and "without a place" in plan and "Review next" in plan and "Not now" in plan
    # one summary line and a compact table: document, results without a place, Review
    assert "Results without a place" in js and 'class: "nr-table small"' in js and '"Review")' in js
    # Move anyway sends keep_unplaced, from the dialog of the combined review, only after the person's click
    assert "keep_unplaced: true" in js and "Move anyway (" in js and "Results that would lose their place" in js
    review = js[js.index("async function reviewAll"):js.index("async function moveNr")]
    assert "x.quote" in review and "x.kind_text" in review and "x.what" in review
    # Review next walks the documents' own Reading preview, one at a time
    assert "tab=reading&preview=1" in js and "function reviewNext" in js
    css = (STATIC / "views.css").read_text(encoding="utf-8")
    assert ".nr-table" in css and ".nr-review-list" in css
