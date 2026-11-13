"""0.16: Restore, Leave out and where the text starts or ends change the reading view in place.

Before, the reading view drew the whole document again after each of them: the page flashed and it was hard to see
what had happened. Now the app sends back what the view needs to show the change where it happened: every block that
changed as it is now (wherever it is in the document: the first 1000 blocks only before), the block that carries or
carried a start or end mark, and the reading's figures (what is left out, by kind, and the passages read).
"""
from __future__ import annotations

from test_0_15_1_reader3 import _project, make_book
from test_app import api, home  # noqa: F401  (fixtures)


def _figures(api, base):
    d = api("GET", f"{base}?view=blocks&limit=1")[1]
    return {k: d[k] for k in ("left_out", "passages_read", "passages_all")}


def _all_blocks(api, base):
    d = api("GET", f"{base}?view=blocks&limit=1000")[1]
    assert len(d["blocks"]) == d["total_blocks"]
    return {b["n"]: b for b in d["blocks"]}


def test_leave_out_and_restore_send_back_the_blocks_and_the_figures(api, tmp_path):
    path, _truth, _paras, _boiler = make_book(tmp_path)
    (d,) = _project(api, [path])
    base = f"/api/projects/R/documents/{d['doc_id']}"
    blocks = _all_blocks(api, base)
    para = next(b for b in blocks.values() if b["kind"] == "body" and b["included"] and b["label"])
    figures = _figures(api, base)
    # Leave out: each block of the group as the reading view now lists it, and the figures as the page now has them
    st, r = api("PUT", f"{base}/blocks/{para['n']}", {"included": False})
    assert st == 200 and para["n"] in {b["n"] for b in r["blocks"]}
    now = _all_blocks(api, base)
    assert r["blocks"] == [now[b["n"]] for b in r["blocks"]]
    assert all(b["included"] is False and b["changed"] for b in r["blocks"])
    assert r["doc"] == _figures(api, base)
    assert r["doc"]["passages_read"] < figures["passages_read"] and r["doc"]["left_out"]["body"] > figures["left_out"].get("body", 0)
    # Restore: back as the reader had it, the figures too
    st, r = api("PUT", f"{base}/blocks/{para['n']}", {"included": True})
    assert st == 200 and all(b["included"] and not b["changed"] for b in r["blocks"])
    assert r["doc"] == figures == _figures(api, base)
    # All like this: every block like it is sent back, as now listed
    slug = next(b for b in blocks.values() if b["text"].startswith("TIS final pgs 12 "))
    st, r = api("PUT", f"{base}/blocks/{slug['n']}", {"included": True, "alike": True})
    assert st == 200 and len(r["blocks"]) == r["together"] >= r["alike"] == slug["alike"] + 1
    now = _all_blocks(api, base)
    assert r["blocks"] == [now[b["n"]] for b in r["blocks"]] and r["doc"] == _figures(api, base)
    api("PUT", f"{base}/blocks/{slug['n']}", {"included": False, "alike": True})


def test_the_text_starts_or_ends_here_sends_back_the_blocks_it_changed(api, tmp_path):
    path, _truth, _paras, _boiler = make_book(tmp_path)
    (d,) = _project(api, [path])
    base = f"/api/projects/R/documents/{d['doc_id']}"
    blocks = _all_blocks(api, base)
    two = next(b for b in blocks.values() if b["text"] == "A Visit to the Systems Zoo" and b["kind"] == "heading")
    last_one = max(n for n, b in blocks.items() if n < two["n"] and b["kind"] == "body")
    st, r = api("PUT", f"{base}/bounds", {"side": "end", "block": last_one})
    assert st == 200 and r["left_out"] >= 20
    now = _all_blocks(api, base)
    sent = {b["n"]: b for b in r["blocks"]}
    changed = {n for n in now if now[n]["included"] != blocks[n]["included"]}
    assert set(sent) == changed | {last_one}                    # what changed, and the block that carries the mark
    assert all(sent[n] == now[n] for n in sent) and sent[last_one]["bound"] == "end"
    assert r["doc"] == _figures(api, base)
    # the mark moves up a block: the block that carried it is sent back too, without it
    earlier = max(n for n, b in blocks.items() if n < last_one and b["kind"] == "body")
    st, r = api("PUT", f"{base}/bounds", {"side": "end", "block": earlier})
    sent = {b["n"]: b for b in r["blocks"]}
    assert sent[earlier]["bound"] == "end" and sent[last_one]["bound"] is None and sent[last_one]["included"] is False
    # undone: what it had left out comes back, and the block that carried it says so no longer
    st, r = api("PUT", f"{base}/bounds", {"side": "end", "block": None})
    sent = {b["n"]: b for b in r["blocks"]}
    assert st == 200 and sent[earlier]["bound"] is None and r["restored"] >= 20
    assert all(sent[n] == b for n, b in _all_blocks(api, base).items() if n in sent)
    assert r["doc"] == _figures(api, base)


def test_blocks_by_number_are_the_blocks_of_the_listing(api, tmp_path):
    from enlens_claims.gui.server import App

    path, _truth, _paras, _boiler = make_book(tmp_path)
    (d,) = _project(api, [path])
    blocks = _all_blocks(api, f"/api/projects/R/documents/{d['doc_id']}")
    from enlens_claims import home
    from enlens_claims.store import Workspace

    ws = Workspace(home.project_path("R"))
    text = ws.scalar("SELECT text FROM documents WHERE doc_id=?", (d["doc_id"],))
    pick = sorted(set(sorted(blocks)[::7]) | {max(blocks)})
    got, total = App.reading_blocks(ws, d["doc_id"], text, 0, 0, only=set(pick))
    assert total == len(blocks) and [b["n"] for b in got] == pick and got == [blocks[n] for n in pick]
    assert App.reading_blocks(ws, d["doc_id"], text, 0, 0, only=set())[0] == []


def test_blocks_elsewhere_with_the_same_words_are_sent_back_too(api, tmp_path):
    """A choice is kept by the block's words, so it holds for every block with those words (a title or a source note
    on every page): the view must hear of each of them, or it would show them as they were."""
    note = "Source: the authors' own calculations based on the household survey data of the national statistics office."
    parts = []
    for i in range(6):
        parts += [f"# Section {i}", f"This is paragraph number {i} of the report, about water policy and river basin "
                  "management in some detail, with words enough to be a paragraph of its own.",
                  f"Further discussion {i}: the river keepers argued that budgets must be steady over many years.", note]
    path = tmp_path / "report.md"
    path.write_text("\n\n".join(parts), encoding="utf-8")
    (d,) = _project(api, [path])
    base = f"/api/projects/R/documents/{d['doc_id']}"
    blocks = _all_blocks(api, base)
    notes = [n for n, b in blocks.items() if b["text"] == note]
    assert len(notes) == 6 and all(blocks[n]["included"] for n in notes)
    st, r = api("PUT", f"{base}/blocks/{notes[2]}", {"included": False})
    now = _all_blocks(api, base)
    sent = {b["n"]: b for b in r["blocks"]}
    moved = {n for n in now if now[n]["included"] != blocks[n]["included"] or now[n]["changed"] != blocks[n]["changed"]}
    assert st == 200 and moved >= set(notes) and moved <= set(sent)     # every block that changed is sent back
    assert all(sent[n] == now[n] for n in sent) and r["doc"] == _figures(api, base)
    assert notes[2] in r["group"] and not set(notes) - {notes[2]} & set(r["group"])  # the others are not its passage
    st, r = api("PUT", f"{base}/blocks/{notes[0]}", {"included": True})
    assert {b["n"] for b in r["blocks"]} >= set(notes) and all(b["included"] for b in r["blocks"] if b["n"] in notes)
