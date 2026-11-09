"""0.16 (roadmap F4): the research log.

- the app writes an entry by itself when something is decided: documents added (one entry a batch) and removed (with
  the reason), who may read documents with AI, a check made and removed (with the reason), themes found, a theme
  removed, renamed or merged, a set of themes removed; a check the app takes back before it was made leaves nothing;
- a person adds, edits and removes entries of their own and says why beside any entry of theirs; the app's entries
  keep their words and cannot be removed; a colleague's entries cannot be changed here;
- the log filters by group and words, and goes out as Markdown (oldest first, a heading a day) and Excel;
- entries travel with the project: a colleague's come in under their name, yours are never changed, an entry you
  removed does not come back, and one its author removed goes here too.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from enlens_claims import access, claimcheck, ingest, researchlog, store, themes
from enlens_claims.store import Workspace

from test_0_14_0_shared_projects import CLAIM, Person, anna_and_ben  # noqa: F401  (fixtures)
from test_app import Api, api, home  # noqa: F401  (fixtures)

DEMO = Path(__file__).resolve().parents[1] / "tools" / "demo_corpus"


def _kinds(ws: Workspace) -> list[str]:
    return [e["kind"] for e in researchlog.entries(ws, oldest_first=True)["entries"]]


@pytest.fixture
def demo(tmp_path) -> Workspace:
    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [DEMO])
    return ws


def test_documents_added_and_removed_are_written_down(demo):
    e = researchlog.entries(demo)["entries"]
    assert [x["kind"] for x in e] == ["documents-added"]
    assert e[0]["text"].startswith("Added 6 documents: “") and "and 1 more" in e[0]["text"]
    assert len(e[0]["data"]["documents"]) == 6 and e[0]["mine"] and e[0]["who"] == "you"
    doc, title = demo.query("SELECT doc_id, title FROM documents ORDER BY doc_id LIMIT 1")[0]
    demo.remove_document(doc, why="a duplicate of the panel study")
    last = researchlog.entries(demo)["entries"][0]
    assert last["kind"] == "document-removed" and title[:40] in last["text"] and last["why"] == "a duplicate of the panel study"
    assert last["subject_kind"] == "document" and last["subject_id"] == doc


def test_a_check_made_and_dropped_with_its_reason_and_one_taken_back_leaves_nothing(demo):
    hid = claimcheck.create_hypothesis(demo, "Remote work lowers commuting emissions.")
    claimcheck.new_claim(demo, "Remote work lowers commuting emissions.", hyp_id=hid)
    claimcheck.delete_hypothesis(demo, hid, why="reworded as two hypotheses")
    e = researchlog.entries(demo, group="checks", oldest_first=True)["entries"]
    assert [x["kind"] for x in e] == ["check-added", "check-removed"]
    assert e[1]["why"] == "reworded as two hypotheses" and "commuting emissions" in e[1]["text"]
    # a check the app takes back (stopped, withdrawn, a look before checking) never was: no line about it
    hid2 = claimcheck.create_hypothesis(demo, "Hybrid work raises productivity for most workers.")
    claimcheck.delete_hypothesis(demo, hid2, unmade=True)
    assert not researchlog.entries(demo, subject_id=hid2)["entries"]
    # removing the last part of a check removes the check: written down once
    hid3 = claimcheck.create_hypothesis(demo, "Rush hour traffic came back after the pandemic.")
    cid = claimcheck.new_claim(demo, "Rush hour traffic came back after the pandemic.", hyp_id=hid3)
    claimcheck.delete_claim(demo, cid)
    assert [x["kind"] for x in researchlog.entries(demo, subject_id=hid3)["entries"]] == ["check-removed", "check-added"]


def test_who_may_read_documents_with_ai_is_written_down(demo):
    docs = [r[0] for r in demo.query("SELECT doc_id FROM documents ORDER BY doc_id")]
    access.set_documents(demo, docs[:1], "none")
    access.set_documents(demo, docs[:3], "local")
    access.set_documents(demo, docs[:3], "local")  # no change: no line
    e = researchlog.entries(demo, group="documents")["entries"]
    assert [x["kind"] for x in e[:2]] == ["ai-access", "ai-access"]
    assert e[1]["text"].startswith("Who may read “") and e[1]["text"].endswith("no AI may read it.")
    assert e[0]["text"] == "Who may read 3 documents with AI: only a local AI may read them."
    access.set_default(demo, "cloud")
    access.set_default(demo, "local")
    assert researchlog.entries(demo, group="documents")["entries"][0]["text"] == \
        "New documents of this project: only a local AI may read them (before: Claude may read them)."


def test_themes_found_removed_renamed_and_merged_are_written_down_with_the_state_before(demo):
    rid = themes.run(demo, k=4)
    v = themes.view(demo, rid)
    a, b, c = (t["theme_id"] for t in v["themes"][:3])
    themes.edit(demo, rid, "rename", a, "Commuting")
    themes.edit(demo, rid, "merge", b, a)
    themes.edit(demo, rid, "merge", b, None)
    themes.edit(demo, rid, "remove", c, True, reason="boilerplate of the policy brief")
    themes.edit(demo, rid, "remove", c, False)
    e = researchlog.entries(demo, group="themes", oldest_first=True)["entries"]
    assert [x["kind"] for x in e] == ["themes-found", "theme-renamed", "theme-merged", "theme-separated",
                                      "theme-removed", "theme-restored"]
    assert e[0]["text"].startswith("Found 4 themes by words in ")
    assert e[1]["text"].endswith("to “Commuting”.") and e[2]["text"].endswith("into “Commuting”.")
    assert e[4]["why"] == "boilerplate of the policy brief"
    assert all(x["has_version"] for x in e[1:])  # each change names the state before it (history.py)
    themes.delete_run(demo, rid, why="found again with more themes")
    last = researchlog.entries(demo)["entries"][0]
    assert last["kind"] == "themes-removed" and last["why"] == "found again with more themes"


def test_your_own_entries_and_reasons_and_what_cannot_be_changed(demo):
    e = researchlog.add(demo, "Decided to code the interviews before the reports.\nSecond line.")
    assert e["kind"] == "entry" and e["can_edit"] and e["group"] == "entries"
    with pytest.raises(ValueError, match="Write the entry"):
        researchlog.add(demo, "   ")
    e2 = researchlog.update(demo, e["entry_id"], text="Decided to code the interviews first.", why="they are shorter")
    assert e2["text"] == "Decided to code the interviews first." and e2["why"] == "they are shorter" and e2["edited_at"]
    auto = researchlog.entries(demo, group="documents")["entries"][0]
    with pytest.raises(ValueError, match="keep their words"):
        researchlog.update(demo, auto["entry_id"], text="something else")
    with pytest.raises(ValueError, match="cannot be removed"):
        researchlog.remove(demo, auto["entry_id"])
    assert researchlog.update(demo, auto["entry_id"], why="the first batch")["why"] == "the first batch"
    assert researchlog.update(demo, auto["entry_id"], why="")["why"] is None
    researchlog.remove(demo, e["entry_id"])
    assert demo.scalar("SELECT 1 FROM sync_removed WHERE kind='log' AND key=?", (e["entry_id"],))
    # a colleague's entry is theirs
    with demo.connect() as cx:
        other = researchlog.record(cx, "entry", "Ben's note", person_id="p0123456789ab")
    with pytest.raises(PermissionError):
        researchlog.update(demo, other, why="mine now")
    with pytest.raises(PermissionError):
        researchlog.remove(demo, other)


def test_the_log_filters_searches_and_goes_out_as_markdown_and_excel(demo):
    researchlog.add(demo, "Field note: the panel study uses self-reported hours.")
    hid = claimcheck.create_hypothesis(demo, "Remote work lowers commuting emissions.")
    claimcheck.delete_hypothesis(demo, hid, why="too broad")
    r = researchlog.entries(demo)
    assert r["total"] == 4 and r["groups"] == {"documents": 1, "entries": 1, "checks": 2}
    assert [x["kind"] for x in researchlog.entries(demo, q="SELF-REPORTED")["entries"]] == ["entry"]
    assert [x["kind"] for x in researchlog.entries(demo, q="too broad")["entries"]] == ["check-removed"]  # the reason
    assert researchlog.entries(demo, q="100%_")["total"] == 0  # LIKE wildcards are words here
    with pytest.raises(ValueError):
        researchlog.entries(demo, group="nonsense")
    md = researchlog.markdown(demo, "Demo")
    assert md.startswith("# Research log: Demo\n") and md.count("\n## ") == 1
    assert md.index("Added 6 documents") < md.index("Field note") < md.index("Removed the check")
    assert "  *Why:* too broad" in md
    rows = researchlog.table(demo)
    assert [r["What"] for r in rows] == ["Documents", "Your own entries", "Checks", "Checks"] and rows[3]["Why"] == "too broad"


def test_entries_travel_with_the_project(anna_and_ben):
    anna, ben = anna_and_ben
    with anna:
        mine = researchlog.add(anna.ws, "Anna: the water figures are per kilogram.")
        gone = researchlog.add(anna.ws, "Anna: a note she will remove.")
    with ben:
        ben_own = researchlog.add(ben.ws, "Ben: I read the reports first.")
    f = anna.send()
    rep = ben.bring_in(f)
    assert rep["log"] >= 2 and any("research log entr" in line for line in rep["lines"])
    with ben:
        got = {e["entry_id"]: e for e in researchlog.entries(ben.ws)["entries"]}
        assert got[mine["entry_id"]]["who"] == "Anna" and not got[mine["entry_id"]]["mine"]
        assert got[ben_own["entry_id"]]["mine"]
        assert any(e["kind"] == "sync" and e["text"].startswith("Brought in Anna's work.") for e in got.values())
    # Anna removes one entry and changes another: both reach Ben; Ben's own entry is never changed by her file
    with anna:
        researchlog.remove(anna.ws, gone["entry_id"])
        researchlog.update(anna.ws, mine["entry_id"], text="Anna: the water figures are per kilogram of hydrogen.")
        with anna.ws.connect() as cx:  # even if her copy had a row of his, changed
            cx.execute("INSERT INTO research_log(entry_id, at, person_id, kind, text, edited_at) VALUES (?,?,?,?,?,?)",
                       (ben_own["entry_id"], store.now(), ben.id, "entry", "changed by Anna", "2999-01-01"))
    ben.bring_in(anna.send())
    with ben:
        got = {e["entry_id"]: e for e in researchlog.entries(ben.ws)["entries"]}
        assert gone["entry_id"] not in got
        assert got[mine["entry_id"]]["text"].endswith("of hydrogen.")
        assert got[ben_own["entry_id"]]["text"] == "Ben: I read the reports first."
        # Ben removes his own entry: Anna's file does not bring it back
        researchlog.remove(ben.ws, ben_own["entry_id"])
    ben.bring_in(anna.send())
    with ben:
        assert ben_own["entry_id"] not in {e["entry_id"] for e in researchlog.entries(ben.ws)["entries"]}


def test_the_log_through_the_app(api, tmp_path):  # noqa: F811
    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    st, r = api("POST", "/api/projects/Demo/log", {"text": "First entry of the project."})
    assert st == 200 and r["entry"]["kind"] == "entry"
    eid = r["entry"]["entry_id"]
    assert api("POST", "/api/projects/Demo/log", {"text": " "})[0] == 400
    st, r = api("PUT", f"/api/projects/Demo/log/{eid}", {"why": "to start the log"})
    assert st == 200 and r["entry"]["why"] == "to start the log"
    st, r = api("GET", "/api/projects/Demo/log?group=entries")
    assert st == 200 and r["total"] == 1 and r["group_names"]["entries"] == "Your own entries"
    st, body = api("GET", "/api/projects/Demo/log.md")
    assert st == 200 and b"First entry of the project." in body
    st, body = api("GET", "/api/projects/Demo/log.xlsx")
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(body))
    assert wb.sheetnames[0] == "Research log" and wb.active["D2"].value == "First entry of the project."
    assert api("DELETE", f"/api/projects/Demo/log/{eid}")[0] == 200
    assert api("DELETE", f"/api/projects/Demo/log/{eid}")[0] == 404
    from enlens_claims import home as home_mod

    ws = home_mod.open_project("Demo")
    with ws.connect() as cx:
        other = researchlog.record(cx, "entry", "A colleague's", person_id="p0123456789ab")
    st, r = api("PUT", f"/api/projects/Demo/log/{other}", {"text": "mine"})
    assert st == 403 and "colleague" in r["error"]
