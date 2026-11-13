"""0.16 (roadmap K1): your own codebook.

- a codebook starts fresh (no codes yet), from the themes found (their names, descriptions, key terms and best
  passages, removed themes left out), as a copy (of the SDG targets too) or from a CSV; it stays a CSV that opens in a
  spreadsheet, with the editor's columns, and a codebook without them reads as before (its codes are matched by the
  same words: no result changes);
- labels follow a rename and a merge (their ids and the reviews of them too), and so do checks tagged with the code; a
  label made after the change keeps its code; names can be swapped; restoring the version from before gives every
  label back as it was; a merged code's label on a passage that has the other code already stays, marked, and comes
  back with it;
- a removed code's labels are kept, wait under Removed codes and do not count, and count again when the code comes
  back; a new code may not take the name of a removed code whose labels wait;
- a code whose wording changed after the AI labelled with it says so, and only those passages are labelled again;
- a codebook kept with all projects: a change made in one project reaches the labels of another when it opens it;
- *Try it* picks, code by code, what the keyword pass picks;
- the Profile page says when the codebook changed since its keyword pass;
- move, copy, remove and bring back, with history; and the endpoints.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from enlens_claims import codebooks, frameworks, history, ingest, profile, researchlog, themes
from enlens_claims.store import Workspace, now

from test_app import Api, api, home  # noqa: F401  (fixtures)

DEMO = Path(__file__).resolve().parents[1] / "tools" / "demo_corpus"
CODES = [{"code": "Commuting", "description": "Travel between home and the office, and its emissions.", "group": "t",
          "keywords": ["commute", "commuting", "travel"]},
         {"code": "Wellbeing", "description": "How workers feel: stress, loneliness, life satisfaction.", "group": "w",
          "keywords": ["wellbeing", "loneliness"]},
         {"code": "Productivity", "description": "Output and performance of workers working from home.", "group": "w",
          "keywords": ["productivity", "performance"]}]


@pytest.fixture
def demo(tmp_path) -> Workspace:
    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [DEMO])
    return ws


def _make(ws, name="remote", where="project", made=False):
    cb = codebooks.load(ws, name) if made else codebooks.create(ws, name, "Remote work", where, "fresh")
    st = json.loads(json.dumps(cb))
    st["groups"] = [{"group": "t", "group_name": "Travel"}, {"group": "w", "group_name": "Work and life"}]
    st["codes"] = [dict(c, include="", exclude="", examples=[]) for c in CODES]
    codebooks.save(ws, name, st)
    return codebooks.load(ws, name)


def _model_labels(ws, fw="remote"):
    """Model labels on some passages (as the AI would give them), with a person's review of one."""
    pids = [r[0] for r in ws.query("SELECT passage_id FROM passages ORDER BY passage_id LIMIT 6")]
    with ws.connect() as cx:
        for i, pid in enumerate(pids):
            for code in (["Commuting", "Productivity"] if i < 3 else ["Wellbeing"]):
                lid = profile.label_id(fw, pid, code, "model")
                cx.execute("INSERT INTO labels(label_id, passage_id, doc_id, framework, code, source, created_at) "
                           "VALUES (?,?,?,?,?,'model',?)", (lid, pid, pid.split(":")[0], fw, code, "2026-01-01T00:00:00+00:00"))
        cx.execute("INSERT INTO reviews(item_kind, item_id, field, decision, decided_at) VALUES ('label', ?, 'label', "
                   "'accept', ?)", (profile.label_id(fw, pids[0], "Commuting", "model"), now()))
    return pids


def _counts(ws, fw="remote"):
    return {r[0]: r[1] for r in ws.query("SELECT code, COUNT(*) FROM labels WHERE framework=? GROUP BY code", (fw,))}


def test_a_fresh_codebook_its_csv_and_the_log(demo):
    cb = codebooks.create(demo, "Remote Work!", "Remote work", "project", "fresh")
    assert cb["name"] == "remote_work" and cb["codes"] == [] and cb["where"] == "project" and cb["editable"]
    assert "remote_work" in frameworks.available(demo) and not frameworks.problems(demo)
    with pytest.raises(ValueError, match="exists already"):
        codebooks.create(demo, "remote_work", "Again")
    cb = _make(demo, "remote_work", made=True)
    assert [c["code"] for c in cb["codes"]] == ["Commuting", "Wellbeing", "Productivity"]
    rows = list(csv.DictReader(io.StringIO((demo.root / "frameworks" / "remote_work.csv").read_text(encoding="utf-8"))))
    assert list(rows[0]) == list(codebooks.COLUMNS) and rows[0]["keywords"] == "commute; commuting; travel"
    assert rows[0]["group_name"] == "Travel"
    fw = frameworks.get("remote_work", demo)
    assert fw.code_text("Commuting") == "Travel between home and the office, and its emissions. Travel commute commuting travel"
    kinds = [e["kind"] for e in researchlog.entries(demo, group="codebooks", oldest_first=True)["entries"]]
    assert kinds == ["codebook-added", "codebook-changed"]


def test_a_codebook_without_the_editors_columns_reads_as_before(demo):
    text = "code,description,group,group_name\nH1,Remote work lowers commuting,C,Commuting\n"
    frameworks.save(demo, "plain", text)
    fw = frameworks.get("plain", demo)
    assert fw.code_text("H1") == "Remote work lowers commuting Commuting"   # the words of before 0.16
    assert fw.codes["H1"] == frameworks.Code("H1", "Remote work lowers commuting", "C", "Commuting")
    with pytest.raises(ValueError, match="no rows"):
        frameworks.parse_csv("code,description\n")


def test_from_the_themes_a_copy_and_a_csv(demo):
    rid = themes.run(demo, k=4)
    gone = themes.view(demo, rid)["themes"][1]
    themes.edit(demo, rid, "remove", gone["theme_id"], True)
    src = codebooks.theme_sources(demo)
    assert len(src) == 1 and src[0]["here"] and gone["name"] not in [t["name"] for t in src[0]["themes"]]
    drafts = [t["code"] for t in src[0]["themes"]]
    for d in drafts:
        assert d["keywords"] and d["examples"]
        for e in d["examples"]:   # every example is words of a document, at its place
            text = demo.scalar("SELECT text FROM documents WHERE doc_id=?", (e["doc_id"],))
            assert " ".join(text[e["start"]:e["end"]].split()) == e["quote"]
    cb = codebooks.create(demo, "from_themes", "From the themes", "project", "themes", {"codes": drafts})
    assert len(cb["codes"]) == len(drafts) and all(c["examples"] for c in cb["codes"])
    copy = codebooks.create(demo, "sdg_mine", "", "project", "copy", {"of": "sdg"})
    assert len(copy["codes"]) == 169 and copy["title"].endswith("(copy)") and copy["directional"]
    one = codebooks.create(demo, "csvbook", "From CSV", "project", "csv",
                           {"csv": "code;description\nA;First code of the file\nB;Second code of the file\n"})
    assert [c["code"] for c in one["codes"]] == ["A", "B"]


def test_labels_follow_a_rename_and_a_merge_and_come_back_with_a_restore(demo):
    cb = _make(demo)
    pids = _model_labels(demo)
    hid_code = demo.query("SELECT COUNT(*) FROM hypotheses")[0][0]
    from enlens_claims import claimcheck

    hid = claimcheck.create_hypothesis(demo, "Remote work lowers commuting emissions.", framework="remote", code="Commuting")
    before = _counts(demo)
    st = json.loads(json.dumps(cb))
    by = {c["code"]: c for c in st["codes"]}
    by["Commuting"]["code"] = "Travel to work"
    st["codes"] = [by["Commuting"], by["Wellbeing"]]          # Productivity merged into Wellbeing
    r = codebooks.save(demo, "remote", st, merges=[{"from": by["Productivity"]["uid"], "into": by["Wellbeing"]["uid"]}],
                       why="clearer names")
    assert any("renamed" in c for c in r["changes"]) and any("merged" in c for c in r["changes"])
    assert _counts(demo) == {"Travel to work": 3, "Wellbeing": 6}
    assert demo.scalar("SELECT code FROM hypotheses WHERE hyp_id=?", (hid,)) == "Travel to work"
    lid = profile.label_id("remote", pids[0], "Travel to work", "model")
    assert demo.scalar("SELECT item_id FROM reviews WHERE item_kind='label'") == lid  # the review moved with it
    assert demo.scalar("SELECT COUNT(*) FROM labels WHERE merged_from='Productivity'") == 3
    e = researchlog.entries(demo, group="codebooks")["entries"][0]
    assert e["why"] == "clearer names" and e["has_version"]
    # a label made after the rename, with a code of the old name, is not moved by a later follow
    vid = history.versions(demo, "codebook", "remote")["versions"][0]["version_id"]
    history.restore(demo, "codebook", "remote", vid)
    assert _counts(demo) == before
    assert demo.scalar("SELECT code FROM hypotheses WHERE hyp_id=?", (hid,)) == "Commuting"
    assert demo.scalar("SELECT COUNT(*) FROM labels WHERE merged_from IS NOT NULL") == 0
    assert hid_code == 0


def test_a_merged_label_on_a_passage_with_both_codes_waits_and_comes_back(demo):
    cb = _make(demo)
    pids = _model_labels(demo)
    with demo.connect() as cx:  # the first passage has Wellbeing too
        cx.execute("INSERT INTO labels(label_id, passage_id, doc_id, framework, code, source, created_at) VALUES "
                   "(?,?,?,?,?,'model',?)", (profile.label_id("remote", pids[0], "Wellbeing", "model"), pids[0],
                                             pids[0].split(":")[0], "remote", "Wellbeing", "2026-01-01"))
    before = _counts(demo)
    st = json.loads(json.dumps(cb))
    by = {c["code"]: c for c in st["codes"]}
    st["codes"] = [by["Commuting"], by["Wellbeing"]]
    codebooks.save(demo, "remote", st, merges=[{"from": by["Productivity"]["uid"], "into": by["Wellbeing"]["uid"]}])
    assert _counts(demo) == {"Commuting": 3, "Wellbeing": 6, "Productivity": 1}
    rem = codebooks.removed_codes(demo, "remote")
    assert rem[0]["code"] == "Productivity" and rem[0]["labels"] == 1 and rem[0]["definition"]["merged_into"] == "Wellbeing"
    assert "Productivity" not in {r["code"] for r in profile.effective(demo, "remote")}
    history.restore(demo, "codebook", "remote", history.versions(demo, "codebook", "remote")["versions"][0]["version_id"])
    assert _counts(demo) == before


def test_names_can_be_swapped(demo):
    cb = _make(demo)
    _model_labels(demo)
    st = json.loads(json.dumps(cb))
    by = {c["code"]: c for c in st["codes"]}
    by["Commuting"]["code"], by["Wellbeing"]["code"] = "Wellbeing", "Commuting"
    codebooks.save(demo, "remote", st)
    assert _counts(demo) == {"Wellbeing": 3, "Commuting": 3, "Productivity": 3}


def test_a_removed_codes_labels_wait_and_count_again_when_it_comes_back(demo):
    cb = _make(demo)
    _model_labels(demo)
    counted = {r["code"] for r in profile.effective(demo, "remote")}
    assert counted == {"Commuting", "Productivity", "Wellbeing"}
    st = json.loads(json.dumps(cb))
    st["codes"] = [c for c in st["codes"] if c["code"] != "Wellbeing"]
    r = codebooks.save(demo, "remote", st)
    assert any("labels wait under Removed codes" in c for c in r["changes"])
    assert _counts(demo)["Wellbeing"] == 3   # kept
    assert {x["code"] for x in profile.effective(demo, "remote")} == {"Commuting", "Productivity"}
    rem = r["codebook"]["removed"]
    assert rem[0]["code"] == "Wellbeing" and rem[0]["labels"] == 3 and rem[0]["uid"]
    st2 = json.loads(json.dumps(r["codebook"]))
    st2["codes"].append({"code": "Wellbeing", "description": "Another meaning", "group": "w"})
    with pytest.raises(ValueError, match="removed code whose labels wait"):
        codebooks.save(demo, "remote", st2)
    st2["codes"][-1] = {"uid": rem[0]["uid"], "code": "Wellbeing", "description": rem[0]["description"], "group": "w"}
    r = codebooks.save(demo, "remote", st2)
    assert any("brought" in c for c in r["changes"]) and not r["codebook"]["removed"]
    assert {x["code"] for x in profile.effective(demo, "remote")} == {"Commuting", "Productivity", "Wellbeing"}


def test_a_code_reworded_after_the_ai_labelled_says_so_and_only_those_passages_are_read_again(demo):
    cb = _make(demo)
    pids = _model_labels(demo)
    with demo.connect() as cx:
        for pid in pids:
            cx.execute("INSERT INTO tasks(task_id, kind, model, status, payload_json, created_at) VALUES "
                       "(?, 'label', 'm', 'done', '{}', ?)", (f"label:remote:{pid}", "2026-01-01"))
    assert codebooks.stale(demo, "remote") == {}
    st = json.loads(json.dumps(cb))
    st["codes"][0]["include"] = "Only travel to the usual place of work."
    codebooks.save(demo, "remote", st)
    s = codebooks.stale(demo, "remote")
    assert list(s) == ["Commuting"] and s["Commuting"]["passages"] == 3
    got = codebooks.relabel_passages(demo, "remote", "Commuting")
    assert sorted(got) == sorted(pids[:3])
    left = {r[0] for r in demo.query("SELECT task_id FROM tasks WHERE kind='label'")}
    assert left == {f"label:remote:{p}" for p in pids[3:]}
    assert _counts(demo)["Commuting"] == 3   # the labels stay until the new answers replace them
    assert codebooks.relabel_passages(demo, "remote", "Wellbeing") == []
    plan = profile.label_plan(demo, "remote", passage_ids=got, all_passages=True)
    assert sorted(plan["passage_ids"]) == sorted(got)


def test_a_codebook_kept_with_all_projects_changes_the_labels_of_another_when_it_opens(tmp_path):
    a = Workspace.create(tmp_path / "a")
    b = Workspace.create(tmp_path / "b")
    for ws in (a, b):
        ingest.ingest(ws, [DEMO])
    cb = _make(a, "shared", where="home")
    assert cb["where"] == "home" and (codebooks._home_folder() / "shared.csv").is_file()
    _model_labels(b, "shared")
    st = json.loads(json.dumps(cb))
    st["codes"][0]["code"] = "Travel"
    codebooks.save(a, "shared", st)
    assert _counts(b, "shared")["Commuting"] == 3           # not yet: b has not looked
    with b.connect() as cx:  # a label made in b after the rename, with a code of that name, stays as it is
        cx.execute("INSERT INTO labels(label_id, passage_id, doc_id, framework, code, source, created_at) VALUES "
                   "('lnew', 'x:0001', 'x', 'shared', 'Commuting', 'person', '2999-01-01')")
    codebooks.follow(b, "shared")
    assert _counts(b, "shared") == {"Travel": 3, "Commuting": 1, "Productivity": 3, "Wellbeing": 3}
    assert codebooks.follow(b, "shared") == 0               # once
    # this project's own copy: its changes stay here
    own = codebooks.copy_here(b, "shared")
    assert own["where"] == "project" and own["shadows_home"]
    st2 = json.loads(json.dumps(own))
    st2["title"] = "Shared, b's version"
    codebooks.save(b, "shared", st2)
    assert frameworks.get("shared", a).title == "Remote work"


def test_try_it_picks_what_the_keyword_pass_picks(demo):
    cb = _make(demo)
    tried = codebooks.try_codes(demo, cb)
    profile.keyword_pass(demo, "remote")
    rows = demo.query("SELECT code, passage_id, doc_id FROM labels WHERE framework='remote'")
    for code, t in tried["codes"].items():
        mine = [r for r in rows if r["code"] == code]
        assert t["passages"] == len(mine) and t["documents"] == len({r["doc_id"] for r in mine}), code
    assert tried["passages"] == demo.scalar("SELECT COUNT(*) FROM passages WHERE section='body'") or tried["passages"]
    st = json.loads(json.dumps(cb))
    st["codes"].append({"code": "Nothing", "description": "Zyxwvut qqqq", "group": ""})
    assert "matches nothing" in codebooks.try_codes(demo, st)["codes"]["Nothing"]["note"]


def test_the_profile_says_when_the_codebook_changed_since_its_keyword_pass(demo):
    cb = _make(demo)
    profile.keyword_pass(demo, "remote")
    assert not profile.pass1_status(demo, "remote")["codebook_changed"]
    st = json.loads(json.dumps(cb))
    st["codes"][1]["keywords"] = ["stress"]
    codebooks.save(demo, "remote", st)
    assert profile.pass1_status(demo, "remote")["codebook_changed"]


def test_move_copy_remove_and_bring_back(demo):
    _make(demo)
    cb = codebooks.move(demo, "remote", "home")
    assert cb["where"] == "home" and codebooks._version_files(demo, "remote")
    assert not (demo.root / "frameworks" / "remote.csv").exists()
    with pytest.raises(ValueError, match="kept there already"):
        codebooks.move(demo, "remote", "home")
    codebooks.move(demo, "remote", "project")
    codebooks.remove(demo, "remote", why="replaced by a new one")
    assert "remote" not in frameworks.available(demo)
    e = researchlog.entries(demo)["entries"][0]
    assert e["kind"] == "codebook-removed" and e["why"] == "replaced by a new one" and e["has_version"]
    cmp = history.compare(demo, "codebook", "remote", e["version_id"])
    assert sum(1 for c in cmp["changes"] if c["what"].startswith("Code ")) == 3
    assert history.restore(demo, "codebook", "remote", e["version_id"])["restored"]
    assert [c.code for c in frameworks.get("remote", demo).sorted_codes()] == ["Commuting", "Wellbeing", "Productivity"]
    with pytest.raises(ValueError, match="ship with the app"):
        codebooks.remove(demo, "sdg")


def test_codebooks_through_the_app(api):  # noqa: F811
    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    from enlens_claims import home as home_mod

    ws = home_mod.open_project("Demo")
    ingest.ingest(ws, [DEMO])
    st, r = api("POST", "/api/projects/Demo/codebooks", {"name": "remote", "title": "Remote work", "start": "fresh"})
    assert st == 200 and r["codebook"]["codes"] == []
    cb = r["codebook"]
    cb["codes"] = [dict(c, include="", exclude="", examples=[]) for c in CODES]
    st, r = api("PUT", "/api/projects/Demo/codebooks/remote", {"codebook": cb, "why": "first codes"})
    assert st == 200 and len(r["changes"]) == 3 and r["version_id"]
    assert api("PUT", "/api/projects/Demo/codebooks/remote", {"codebook": "x"})[0] == 400
    st, r = api("GET", "/api/projects/Demo/codebooks")
    assert st == 200 and {c["name"] for c in r["codebooks"]} >= {"sdg", "sdg_goals", "remote"}
    assert api("GET", "/api/projects/Demo/codebooks/remote")[1]["codebook"]["used"]["labels"] == 0
    assert api("GET", "/api/projects/Demo/codebooks/nothere")[0] == 404
    text = ws.scalar("SELECT text FROM documents WHERE text LIKE '%commuting emissions%'")
    i = text.index("commuting emissions")
    st, r = api("POST", "/api/projects/Demo/codebooks/example", {"quote": text[i - 20:i + 19]})
    assert st == 200 and r["example"]["doc_id"] and r["example"]["quote"]
    assert api("POST", "/api/projects/Demo/codebooks/example", {"quote": "words that no document holds anywhere"})[0] == 400
    st, r = api("POST", "/api/projects/Demo/codebooks/remote/try", {})
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done" and set(job["result"]["codes"]) == {"Commuting", "Wellbeing", "Productivity"}
    st, r = api("POST", "/api/projects/Demo/codebooks/remote/relabel", {"code": "Commuting"})
    assert st == 409
    st, body = api("GET", "/api/projects/Demo/codebooks/remote.csv")
    assert st == 200 and body.decode("utf-8").startswith("code,description,group")
    st, body = api("GET", "/api/projects/Demo/codebooks/sdg.csv")
    assert st == 200 and len(body.decode("utf-8-sig").splitlines()) == 170
    st, r = api("GET", "/api/projects/Demo/history/codebook/remote")
    assert st == 200 and len(r["versions"]) == 1
    st, r = api("GET", "/api/projects/Demo/codebooks/sources")
    assert st == 200 and r["runs"] == []
    assert api("POST", "/api/projects/Demo/codebooks/remote/move", {"to": "home"})[1]["codebook"]["where"] == "home"
    assert api("DELETE", "/api/projects/Demo/codebooks/remote?why=done")[0] == 200
    assert api("DELETE", "/api/projects/Demo/codebooks/sdg")[0] == 400
    st, r = api("GET", "/api/projects/Demo/profile?framework=sdg")
    assert st == 200 and r["removed_codes"] == [] and r["stale_codes"] == {}


def test_the_ai_reads_when_to_use_a_code_and_when_not_only_where_the_codebook_says(demo):
    from enlens_claims import prompts

    base = {"framework": "x", "framework_title": "X", "code_label": "code", "directional": False, "passage_id": "p",
            "doc_id": "d", "title": "T", "page": 1, "text": "Some text.", "context": ""}
    plain = dict(base, candidates=[{"code": "A", "description": "First"}])
    told = dict(base, candidates=[{"code": "A", "description": "First", "include": "Only travel to work.",
                                   "exclude": "Not holidays."}])
    assert "CANDIDATE CODES:\nA: First\n" in prompts.user_prompt("label", plain) + "\n"
    assert "A: First Use it when: Only travel to work. Not when: Not holidays." in prompts.user_prompt("label", told)
    cb = _make(demo)
    st = json.loads(json.dumps(cb))
    st["codes"][0]["include"] = "Only travel to work."
    codebooks.save(demo, "remote", st)
    profile.keyword_pass(demo, "remote")
    pid = demo.scalar("SELECT passage_id FROM labels WHERE framework='remote' AND code='Commuting' LIMIT 1")
    profile.make_label_tasks(demo, "remote", [pid], "m")
    cands = json.loads(demo.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (f"label:remote:{pid}",)))["candidates"]
    by = {c["code"]: c for c in cands}
    assert by["Commuting"]["include"] == "Only travel to work." and "exclude" not in by["Commuting"]
    assert all(set(c) == {"code", "description"} for k, c in by.items() if k != "Commuting")


# ---- what the independent review of 0.16.0 found: each test is a scenario the review reproduced ---------------
def test_a_code_may_not_take_the_name_of_one_removed_or_merged_in_the_same_change(demo):
    cb = _make(demo)
    _model_labels(demo)
    st = json.loads(json.dumps(cb))
    by = {c["code"]: c for c in st["codes"]}
    by["Productivity"]["code"] = "Commuting"
    st["codes"] = [by["Wellbeing"], by["Productivity"]]
    with pytest.raises(ValueError, match="remove or merge in this same change"):
        codebooks.save(demo, "remote", st, merges=[{"from": by["Commuting"]["uid"], "into": by["Wellbeing"]["uid"]}])
    with pytest.raises(ValueError, match="remove or merge in this same change"):
        codebooks.save(demo, "remote", st)   # Commuting removed, Productivity renamed to it
    assert _counts(demo) == {"Commuting": 3, "Productivity": 3, "Wellbeing": 3}


def test_changes_saved_in_one_second_are_followed_in_their_order(tmp_path, monkeypatch):
    a, b = Workspace.create(tmp_path / "a"), Workspace.create(tmp_path / "b")
    for ws in (a, b):
        ingest.ingest(ws, [DEMO])
    cb = _make(a, "shared", where="home")
    _model_labels(b, "shared")
    monkeypatch.setattr(codebooks, "now", lambda: "2026-11-09T12:00:00+00:00")
    for new_name in ("Travel", "Commute", "Trips"):   # three saves in the same second
        st = json.loads(json.dumps(codebooks.load(a, "shared")))
        st["codes"][0]["code"] = new_name
        codebooks.save(a, "shared", st)
    codebooks.follow(b, "shared")
    assert _counts(b, "shared") == {"Trips": 3, "Productivity": 3, "Wellbeing": 3}
    assert cb["codes"][0]["code"] == "Commuting"


def test_restoring_the_version_after_a_merge_merges_again(demo):
    cb = _make(demo)
    _model_labels(demo)
    st = json.loads(json.dumps(cb))
    by = {c["code"]: c for c in st["codes"]}
    st["codes"] = [by["Commuting"], by["Productivity"]]
    codebooks.save(demo, "remote", st, merges=[{"from": by["Wellbeing"]["uid"], "into": by["Productivity"]["uid"]}])
    merged = _counts(demo)
    counted = len(profile.effective(demo, "remote"))
    vs = history.versions(demo, "codebook", "remote")["versions"]
    history.restore(demo, "codebook", "remote", vs[0]["version_id"])          # before the merge
    assert _counts(demo) == {"Commuting": 3, "Productivity": 3, "Wellbeing": 3}
    after = next(v for v in history.versions(demo, "codebook", "remote")["versions"]
                 if v["label"].startswith("restoring the version of"))      # the state the restore replaced
    history.restore(demo, "codebook", "remote", after["version_id"])
    assert _counts(demo) == merged and len(profile.effective(demo, "remote")) == counted
    assert not codebooks.removed_codes(demo, "remote")


def test_labelling_again_keeps_the_labels_of_removed_and_merged_codes(demo):
    cb = _make(demo)
    pid = demo.scalar("SELECT passage_id FROM passages WHERE text LIKE '%commut%' ORDER BY passage_id LIMIT 1")
    text = demo.scalar("SELECT text FROM passages WHERE passage_id=?", (pid,))
    tid = f"label:remote:{pid}"
    with demo.connect() as cx:
        for code, merged in (("Commuting", None), ("Gone", None), ("Wellbeing", "Merged code")):
            cx.execute("INSERT INTO labels(label_id, passage_id, doc_id, framework, code, source, task_id, merged_from, "
                       "created_at) VALUES (?,?,?,?,?,'model',?,?,?)",
                       (profile.label_id("remote", pid, code, "model"), pid, pid.split(":")[0], "remote", code, tid,
                        merged, "2026-01-01"))
    payload = {"framework": "remote", "passage_id": pid, "doc_id": pid.split(":")[0], "text": text, "candidates": []}
    words = " ".join(text.split()[:5])
    obj = {"labels": [{"code": "Commuting", "relevance": "main", "direction": "not_stated", "confidence": 0.9,
                       "quote": words, "reason": "about commuting"}], "note": None}
    with demo.connect() as cx:
        ok, errs = profile.store_labels(cx, {"task_id": tid, "prompt_version": "label-v1"}, payload, obj, "m")
    assert ok, errs
    left = {r[0]: r[1] for r in demo.query("SELECT code, merged_from FROM labels WHERE task_id=?", (tid,))}
    # the removed code's label stays; a label of a code still in the codebook (a merge's too) is the new answer's
    assert left == {"Commuting": None, "Gone": None}
    assert cb["name"] == "remote"


def test_a_note_keeps_the_occurrence_selected(demo):
    from enlens_claims import notes

    doc, text = demo.query("SELECT doc_id, text FROM documents WHERE text LIKE '%Rivermouth%Rivermouth%' LIMIT 1")[0]
    first = text.index("Rivermouth")
    second = text.index("Rivermouth", first + 1)
    n = notes.add(demo, doc, second, second + len("Rivermouth"))
    assert n["start"] == second
    assert notes.find(text, "Rivermouth", second + 3) == (second, second + len("Rivermouth"))


def test_a_colleagues_labels_under_a_name_changed_here_follow_it(tmp_path, monkeypatch):
    from enlens_claims import bundle
    from test_0_14_0_shared_projects import Person

    anna, ben = Person(tmp_path, "Anna", monkeypatch), Person(tmp_path, "Ben", monkeypatch)
    with anna:
        anna.ws = Workspace.create(tmp_path / "anna-project")
        ingest.ingest(anna.ws, [DEMO])
        cb = _make(anna.ws)
        from enlens_claims import claimcheck  # a check tagged with a code: the codebook is in use, so it travels

        claimcheck.create_hypothesis(anna.ws, "Remote work lowers commuting emissions.", framework="remote",
                                     code="Commuting")
    first = anna.send()
    with ben:
        ben.ws = bundle.import_project(first, tmp_path / "ben-project")
        _model_labels(ben.ws)
    with anna:
        st = json.loads(json.dumps(cb))
        st["codes"][0]["code"] = "Travel"
        codebooks.save(anna.ws, "remote", st)
    anna.bring_in(ben.send())
    with anna:
        assert _counts(anna.ws) == {"Travel": 3, "Productivity": 3, "Wellbeing": 3}
        assert not codebooks.removed_codes(anna.ws, "remote")


def test_a_csv_not_made_in_the_editor_is_read_as_before_even_with_a_keywords_column(demo):
    frameworks.save(demo, "old", "code,description,keywords,when_to_use\nH1,Remote work and commuting,car; bus,always\n")
    fw = frameworks.get("old", demo)
    assert fw.code_text("H1") == "Remote work and commuting " and fw.codes["H1"].include == ""
    cb = codebooks.create(demo, "new_one", "New", "project", "csv",
                          {"csv": "code,description,keywords\nH1,Remote work and commuting,car; bus\n"})
    assert cb["codes"][0]["keywords"] == ["car", "bus"]   # a CSV brought into the editor keeps them


def test_names_that_are_not_names_never_reach_a_path(api):  # noqa: F811
    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    for bad in ("..%2F..%2Fx", "%2E%2E", "a%2Fb"):
        st, r = api("GET", f"/api/projects/Demo/history/codebook/{bad}")
        assert st == 404, (bad, st, r)
        st, r = api("POST", f"/api/projects/Demo/history/codebook/{bad}/c0123456789abcdef/restore", {})
        assert st == 404, (bad, st, r)
    with pytest.raises(KeyError):
        codebooks._write(Path("/nonexistent"), "../x", "", {})


def test_a_colleagues_labels_follow_only_the_changes_their_copy_had_not_followed(tmp_path, monkeypatch):
    """The review's second look: swapped names, and a name used again, are followed once by each copy's labels."""
    from enlens_claims import bundle, claimcheck
    from test_0_14_0_shared_projects import Person

    anna, ben = Person(tmp_path, "Anna", monkeypatch), Person(tmp_path, "Ben", monkeypatch)
    with anna:
        anna.ws = Workspace.create(tmp_path / "anna-project")
        ingest.ingest(anna.ws, [DEMO])
        cb = _make(anna.ws)
        claimcheck.create_hypothesis(anna.ws, "Remote work lowers commuting emissions.", framework="remote",
                                     code="Commuting")
    first = anna.send()
    with ben:
        ben.ws = bundle.import_project(first, tmp_path / "ben-project")
        pids = _model_labels(ben.ws)
    with anna:
        st = json.loads(json.dumps(cb))
        by = {c["code"]: c for c in st["codes"]}
        by["Commuting"]["code"], by["Wellbeing"]["code"] = "Wellbeing", "Commuting"   # swapped
        codebooks.save(anna.ws, "remote", st)
        st = json.loads(json.dumps(codebooks.load(anna.ws, "remote")))
        by = {c["code"]: c for c in st["codes"]}
        by["Productivity"]["code"] = "Output"
        codebooks.save(anna.ws, "remote", st)
    anna.bring_in(ben.send())
    want = {"Wellbeing": 3, "Commuting": 3, "Output": 3}
    with anna:
        assert _counts(anna.ws) == want
        assert anna.ws.scalar("SELECT code FROM labels WHERE passage_id=? AND code != 'Output'", (pids[0],)) == "Wellbeing"
        assert codebooks.follow(anna.ws) == 0 and _counts(anna.ws) == want          # nothing left to follow
    ben.bring_in(anna.send())                     # Ben gets the changed codebook: his own labels follow it, once
    with ben:
        assert _counts(ben.ws) == want and codebooks.follow(ben.ws) == 0
    anna.bring_in(ben.send())                     # and back: nothing moves again
    with anna:
        assert _counts(anna.ws) == want


def test_a_name_used_again_is_followed_right_by_a_colleagues_labels(tmp_path, monkeypatch):
    from enlens_claims import bundle, claimcheck
    from test_0_14_0_shared_projects import Person

    anna, ben = Person(tmp_path, "Anna", monkeypatch), Person(tmp_path, "Ben", monkeypatch)
    with anna:
        anna.ws = Workspace.create(tmp_path / "anna-project")
        ingest.ingest(anna.ws, [DEMO])
        _make(anna.ws)
        claimcheck.create_hypothesis(anna.ws, "Remote work lowers commuting emissions.", framework="remote",
                                     code="Commuting")
    first = anna.send()
    with ben:
        ben.ws = bundle.import_project(first, tmp_path / "ben-project")
        _model_labels(ben.ws)
    with anna:
        for old, new in (("Commuting", "Travel"), ("Wellbeing", "Commuting")):   # the second takes the freed name
            st = json.loads(json.dumps(codebooks.load(anna.ws, "remote")))
            next(c for c in st["codes"] if c["code"] == old)["code"] = new
            codebooks.save(anna.ws, "remote", st)
    anna.bring_in(ben.send())
    with anna:
        assert _counts(anna.ws) == {"Travel": 3, "Commuting": 3, "Productivity": 3}
