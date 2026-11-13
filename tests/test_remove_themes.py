"""Remove a theme that is not relevant, and find a new theme in its place (themes.new_theme).

A removed theme's passages are left out of the themes, the grids and the downloads until it is brought back. A new
theme is one more k-means step with the other centres fixed: it takes only passages that the run put in a theme that
is shown, each closer to it than to its own theme and to every removed theme."""
import random
import re
import shutil
from array import array
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"
from test_app import Api, api, home  # noqa: F401  (fixtures)


# six topics, each with words of its own; a document is about one topic (a passage never spans two documents)
TOPICS = {
    "water": "desalination aquifer groundwater irrigation drought salinity brine reservoir".split(),
    "jobs": "employment wages apprenticeships unions skills vacancies payroll recruitment".split(),
    "birds": "warblers wetlands nesting plumage flyway songbirds ringing estuary".split(),
    "transport": "railway freight harbours shipping tankers pipelines terminals logistics".split(),
    "finance": "investment subsidies tariffs loans bonds auctions contracts pricing".split(),
    "health": "hospitals patients vaccination clinics nurses diagnosis epidemics therapy".split(),
}
SENTENCES = ["The {0} and the {1} were studied together with {2}.", "Studies of {0} often mention {1} and {2}.",
             "In the region, {0} depends on {1}, and {2} follows.", "Experts linked {0} to {1} and to {2} last year.",
             "Without {0}, the {1} of the area and its {2} would change."]


def topics_corpus(folder: Path, per_topic: int = 10) -> Path:
    """Two documents per topic, of five paragraphs (about 800 characters each): about 40 passages in all."""
    rng = random.Random(7)
    folder.mkdir()
    for t, words in TOPICS.items():
        paras = [" ".join(rng.choice(SENTENCES).format(*rng.sample(words, 3)) for _ in range(12))
                 for _ in range(per_topic)]
        for i in (0, 1):
            # 0.15.7: "\n" on every system. Windows writes "\r\n" otherwise: other bytes, so other document ids (a
            # file's sha1), another passage order and other themes than these tests expect (the same text, though)
            (folder / f"{t}_{i}.txt").write_text(f"Notes {i + 1}\n\n" + "\n\n".join(paras[i::2]) + "\n", newline="\n")
    return folder


def topic_of(ws) -> dict[str, str]:
    out = {}
    for r in ws.query("SELECT passage_id, text FROM passages WHERE section='body'"):
        hits = [t for t, words in TOPICS.items() if any(re.search(rf"\b{w}\b", r["text"]) for w in words)]
        out[r["passage_id"]] = hits[0] if len(hits) == 1 else "+".join(hits)
    return out


@pytest.fixture
def project(home, tmp_path):
    from enlens_claims import ingest

    ws = home.create_project("T")
    ingest.ingest(ws, [topics_corpus(tmp_path / "topics")])
    return ws


def _members(ws, run, *themes_):
    q = ",".join("?" * len(themes_))
    return {r[0] for r in ws.query(f"SELECT passage_id FROM theme_members WHERE run_id=? AND theme_id IN ({q})",
                                   (run, *themes_))}


def _shown(ws, run, tid):
    from enlens_claims import themes

    return {p["passage_id"] for p in themes.theme_passages(ws, run, tid, limit=200)["passages"]}


def test_remove_a_theme_and_bring_it_back(project):
    from enlens_claims import themes

    ws = project
    run = themes.run(ws, k=5, seed=0, mode="words")
    v = themes.view(ws, run)
    k = len(v["themes"])
    gone = v["themes"][1]
    themes.edit(ws, run, "remove", gone["theme_id"], True)
    v2 = themes.view(ws, run)
    assert gone["theme_id"] not in {t["theme_id"] for t in v2["themes"]}
    assert [t["number"] for t in v2["themes"]] == list(range(1, k))          # no gap where it was
    rm = v2["removed"][0]
    assert rm["theme_id"] == gone["theme_id"] and rm["removed"] and rm["removed_at"] and rm["number"] is None
    assert rm["size"] == gone["size"] and rm["replaced_by"] == []
    assert str(gone["theme_id"]) not in v2["doc_grid"] and v2["edits"]["removed"] == 1
    assert themes.runs(ws)[0]["themes_now"] == k - 1
    # its page still opens, and a passage of it can be moved into a theme that is shown
    page = themes.theme_passages(ws, run, gone["theme_id"], limit=200)
    assert page["theme"]["removed"] and page["total"] == gone["size"]
    assert gone["theme_id"] not in {x["theme_id"] for x in page["others"]}
    rescued, into = page["passages"][0]["passage_id"], v2["themes"][0]["theme_id"]
    themes.edit(ws, run, "move", None, into, passage_id=rescued)
    assert rescued in _shown(ws, run, into)
    # a removed theme takes no merge and no passage
    with pytest.raises(ValueError, match="removed"):
        themes.edit(ws, run, "merge", into, gone["theme_id"])
    with pytest.raises(ValueError, match="removed"):
        themes.edit(ws, run, "merge", gone["theme_id"], into)
    other = next(iter(_members(ws, run, into) - {rescued}))
    with pytest.raises(ValueError, match="removed"):
        themes.edit(ws, run, "move", None, gone["theme_id"], passage_id=other)
    # its passages are left out of the Excel file's themes and listed apart
    sheets = dict(themes.tables(ws, run))
    assert gone["name"] not in {r["Name"] for r in sheets["Themes"]}
    assert sheets["Removed themes"][0]["Name"] == gone["name"]
    # brought back: it is one of the themes again
    themes.edit(ws, run, "remove", gone["theme_id"], False)
    v3 = themes.view(ws, run)
    assert len(v3["themes"]) == k and not v3["removed"] and themes.runs(ws)[0]["themes_now"] == k
    assert "Removed themes" not in dict(themes.tables(ws, run))


def test_the_last_theme_and_a_merged_one_cannot_be_removed(project):
    from enlens_claims import themes

    ws = project
    run = themes.run(ws, k=3, seed=0, mode="words")
    ids = [t["theme_id"] for t in themes.view(ws, run)["themes"]]
    themes.edit(ws, run, "merge", ids[2], ids[0])
    with pytest.raises(ValueError, match="merged"):
        themes.edit(ws, run, "remove", ids[2], True)
    themes.edit(ws, run, "remove", ids[1], True)
    with pytest.raises(ValueError, match="last theme"):
        themes.edit(ws, run, "remove", ids[0], True)
    with pytest.raises(KeyError):
        themes.edit(ws, run, "remove", 999, True)


def test_a_new_theme_in_place_of_a_removed_one(project, tmp_path):
    from enlens_claims import themes
    from enlens_claims.store import Workspace

    ws = project
    run = themes.run(ws, k=4, seed=0, mode="words")   # fewer themes than topics: some themes mix topics
    v = themes.view(ws, run)
    k = len(v["themes"])
    gone = v["themes"][-1]["theme_id"]
    left_out = _members(ws, run, gone)
    with pytest.raises(ValueError, match="remove this theme first"):
        themes.new_theme(ws, run, gone)
    themes.edit(ws, run, "remove", gone, True)
    before = {m["passage_id"]: m["theme_id"] for m in ws.query("SELECT passage_id, theme_id FROM theme_members "
                                                                "WHERE run_id=?", (run,))}
    copy = Workspace(shutil.copytree(ws.root, tmp_path / "copy"))
    new = themes.new_theme(ws, run, gone)
    assert new > 1000 and new not in before.values()
    v2 = themes.view(ws, run)
    assert len(v2["themes"]) == k                                   # one in place of the one removed
    t = next(x for x in v2["themes"] if x["theme_id"] == new)
    assert t["replaces"] == {"theme_id": gone, "name": v["themes"][-1]["name"]} and t["name_source"] == "terms"
    assert t["size"] >= themes.MIN_NEW and t["terms"] and t["name"] == " · ".join(t["terms"][:3])
    assert v2["removed"][0]["replaced_by"] == [{"theme_id": new, "name": t["name"]}] and v2["edits"]["added"] == 1
    taken = _members(ws, run, new)
    assert not taken & left_out                                     # nothing of the removed theme comes back
    topic, got = topic_of(ws), [topic_of(ws)[p] for p in taken]
    main = max(set(got), key=got.count)
    assert got.count(main) / len(got) >= 0.8 and main in TOPICS, got   # a topic of its own …
    gone_topics = [topic[p] for p in left_out]
    assert main != max(set(gone_topics), key=gone_topics.count)       # … and not the one removed
    assert sum(x["passages"] for x in t["drawn_from"]) == t["size"] == len(taken)
    assert {x["theme_id"] for x in t["drawn_from"]} == {before[p] for p in taken}
    assert {r[0] for r in ws.query("SELECT found_in FROM theme_members WHERE run_id=? AND theme_id=?", (run, new))} \
        == {before[p] for p in taken}
    # the themes it took passages from keep representatives of their own
    for x in v2["themes"]:
        assert {p["passage_id"] for p in x["representatives"]} <= _members(ws, run, x["theme_id"])
    # the same set and the same removal give the same new theme
    assert _members(copy, run, themes.new_theme(copy, run, gone)) == taken
    # once per removed theme; remove the new one to find another, which takes nothing of either
    with pytest.raises(ValueError, match="already"):
        themes.new_theme(ws, run, gone)
    themes.edit(ws, run, "remove", new, True)
    newer = themes.new_theme(ws, run, new)
    assert not _members(ws, run, newer) & (left_out | taken)
    v3 = themes.view(ws, run)
    assert len(v3["themes"]) == k and {x["theme_id"] for x in v3["removed"]} == {gone, new}
    # a rename of a new theme stays with it
    themes.edit(ws, run, "rename", newer, "Something else")
    assert next(x for x in themes.view(ws, run)["themes"] if x["theme_id"] == newer)["name"] == "Something else"
    # the AI is asked to name the new theme too, and never a removed one
    n = themes.make_name_tasks(ws, run, "m")
    ids = {r[0] for r in ws.query("SELECT task_id FROM tasks WHERE kind='theme'")}
    assert n == k and f"theme:{run}:{newer}" in ids and f"theme:{run}:{gone}" not in ids


def _planted(ws, groups: int, dim: int = 24, seed: int = 1) -> dict[str, int]:
    """Embeddings in `groups` well-apart directions (a fake model), one group per passage in turn."""
    rng = random.Random(seed)
    ids = [r[0] for r in ws.query("SELECT passage_id FROM passages WHERE section='body' ORDER BY passage_id")]
    group = {}
    with ws.connect() as cx:
        for i, pid in enumerate(ids):
            g = i % groups
            v = [rng.gauss(0, 0.08) for _ in range(dim)]
            v[g] += 1.0
            group[pid] = g
            cx.execute("INSERT INTO embeddings VALUES (?,?,?)", ("planted", pid, array("f", v).tobytes()))
    return group


def test_by_meaning_a_new_theme_splits_a_mixed_one(project):
    """Five planted groups in four themes: one theme mixes two groups. With another theme removed, the new theme is
    one planted group (taken out of the mixed theme), never the removed one's."""
    pytest.importorskip("numpy")
    from enlens_claims import themes

    ws = project
    group = _planted(ws, 5)
    run = themes.run(ws, k=4, seed=0, mode="meaning", embed_model="planted")
    v = themes.view(ws, run)
    assert v["run"]["mode"] == "meaning"
    pure = [t["theme_id"] for t in v["themes"] if len({group[p] for p in _members(ws, run, t["theme_id"])}) == 1]
    gone = pure[0]
    gone_group = {group[p] for p in _members(ws, run, gone)}
    themes.edit(ws, run, "remove", gone, True)
    new = themes.new_theme(ws, run, gone)
    got = [group[p] for p in _members(ws, run, new)]
    top = max(set(got), key=got.count)
    assert got.count(top) / len(got) >= 0.9 and top not in gone_group, got


def test_through_the_app(api, tmp_path):
    st, _ = api("PUT", "/api/settings", {"embed_backend": "off"})
    assert st == 200
    assert api("POST", "/api/projects", {"name": "P"})[0] == 200
    for f in sorted(topics_corpus(tmp_path / "topics").iterdir()):
        assert api("POST", f"/api/projects/P/uploads?batch=b1&name={f.name}", raw=f.read_bytes())[0] == 200
    assert api.wait(api("POST", "/api/projects/P/ingest", {"batch": "b1"})[1]["job"]["id"])["state"] == "done"
    job = api.wait(api("POST", "/api/projects/P/themes", {"k": 4})[1]["job"]["id"])
    rid = job["result"]["run_id"]
    base = f"/api/projects/P/themes/{rid}"
    v = api("GET", base)[1]
    gone = v["themes"][-1]["theme_id"]
    st, r = api("POST", f"{base}/new", {"replaces": gone})
    assert st == 400 and "remove this theme first" in r["error"]
    assert api("PUT", f"{base}/edit", {"what": "remove", "theme_id": gone, "value": True})[0] == 200
    assert api("GET", "/api/projects/P/overview")[1]["themes"]["themes"] == len(v["themes"]) - 1
    assert api("POST", f"{base}/new", {})[0] == 400
    assert api("POST", f"{base}/new", {"replaces": 999})[0] == 404
    st, r = api("POST", f"{base}/new", {"replaces": gone})
    assert st == 200 and r["job"]["kind"] == "theme-new" and r["job"]["scope"] == rid
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done", job["error"]
    new = job["result"]["theme_id"]
    v2 = api("GET", base)[1]
    assert [t["theme_id"] for t in v2["removed"]] == [gone]
    assert next(t for t in v2["themes"] if t["theme_id"] == new)["replaces"]["theme_id"] == gone
    assert api("GET", f"{base}/{gone}")[1]["theme"]["removed"] is True
    st, r = api("POST", f"{base}/new", {"replaces": gone})
    assert st == 400 and "already" in r["error"]
    st, body = api("GET", f"{base}/export.xlsx")
    assert st == 200 and body[:2] == b"PK"
    assert api("PUT", f"{base}/edit", {"what": "remove", "theme_id": gone, "value": False})[0] == 200
    assert len(api("GET", base)[1]["themes"]) == len(v["themes"]) + 1
    assert api("GET", "/api/projects/P/themes")[1]["runs"][0]["themes_now"] == len(v["themes"]) + 1


def test_a_workspace_from_before_gains_the_columns(tmp_path):
    import sqlite3

    from enlens_claims.store import Workspace

    ws = Workspace.create(tmp_path / "old")
    with sqlite3.connect(ws.db_path) as cx:   # a theme table as it was before
        cx.execute("DROP TABLE themes")
        cx.execute("CREATE TABLE themes(run_id TEXT, theme_id INT, name TEXT, description TEXT, terms_json TEXT, "
                   "size INT, reps_json TEXT, name_source TEXT, quotes_json TEXT, model TEXT, "
                   "PRIMARY KEY(run_id, theme_id))")
    again = Workspace.open(ws.root)
    cols = {r[1] for r in again.query("PRAGMA table_info(themes)")}
    assert {"removed_at", "replaces"} <= cols
    assert "found_in" in {r[1] for r in again.query("PRAGMA table_info(theme_members)")}


def test_the_page_offers_it():
    js = (STATIC / "views" / "themes.js").read_text(encoding="utf-8")
    for s in ("Remove and find a new theme", "Just remove it", "Removed themes", "Bring it back",
              "Find a new theme in its place", '"theme-new"', "/new`", "found in place of"):
        assert s in js, s
    reg = (STATIC / "registry.js").read_text(encoding="utf-8")
    assert '"theme-new": { icon: "shapes", text: "Finding a new theme"' in reg
    # 0.17.0: reads the cascade (tests/_static.py), not the Themes page's own sheet: the rules of the classes this
    # release added (.th-removed*, .th-new*) are in it, and they use colour tokens only (light and dark both work)
    from _static import all_css, css_blocks

    mine = [d for _m, sels, d in css_blocks(all_css()) if any(re.match(r"\.th-(removed|new)", s) for s in sels)]
    assert mine
    assert not any(re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", v) for d in mine for v in d.values())
