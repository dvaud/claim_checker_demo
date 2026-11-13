"""0.18.1 (roadmap J4.2, the rest): each result's own page says which earlier ENLENS made it.

0.15 recorded the version with every check, theme run, label and AI answer and summed it up on the Overview. Now the
check's page, a theme run's page and the Codes page say it too, as one of the head's facts, and say nothing when
this version made it.
"""
from __future__ import annotations

import re
from pathlib import Path

from test_app import api, home  # noqa: F401  (fixtures)

from enlens_claims import __version__, claimcheck, ingest, runs, themes

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"
DEMO = Path(__file__).resolve().parent.parent / "tools" / "demo_corpus"


def test_made_with_one_says_whether_an_earlier_version_made_it():
    assert runs.made_with_one(__version__) == {"app_version": __version__, "label": __version__,
                                               "version": __version__, "older": False}
    assert runs.made_with_one("0.0.1")["older"] is True
    old = runs.made_with_one(None)  # made before versions were recorded
    assert old["older"] is True and old["label"] == f"before {runs.RECORDED_SINCE}"


def test_each_results_page_names_an_earlier_version(api, home):  # noqa: F811
    assert api("POST", "/api/projects", {"name": "v"})[0] in (200, 201)
    ws = home.open_project("v")
    ingest.ingest(ws, [DEMO])
    hid = claimcheck.create_hypothesis(ws, "Electrolysis needs water")
    run = themes.run(ws, k=3, seed=0, mode="words")
    run_id = run["run_id"] if isinstance(run, dict) else run

    # made with this version: each page says so plainly (older False), and the page shows nothing
    st, r = api("GET", f"/api/projects/v/hypotheses/{hid}")
    assert st == 200 and r["made_with"]["older"] is False and r["made_with"]["version"] == __version__
    st, t = api("GET", f"/api/projects/v/themes/{run_id}")
    assert st == 200 and t["made_with"]["older"] is False
    st, p = api("GET", "/api/projects/v/profile?framework=sdg")
    assert st == 200 and not any(m["older"] for m in p["made_with"])

    with ws.connect() as cx:
        cx.execute("UPDATE hypotheses SET app_version='0.0.1' WHERE hyp_id=?", (hid,))
        cx.execute("UPDATE theme_runs SET app_version=NULL WHERE run_id=?", (run_id,))
        pid = cx.execute("SELECT passage_id, doc_id FROM passages LIMIT 1").fetchone()
        for i, (source, version) in enumerate((("model", "0.0.1"), ("model", "0.0.1"), ("model", __version__),
                                               ("person", "0.0.1"))):
            cx.execute("INSERT INTO labels(label_id, passage_id, doc_id, framework, code, source, app_version) "
                       "VALUES (?,?,?,?,?,?,?)", (f"l{i}", pid[0], pid[1], "sdg", "6.4", source, version))
    st, r = api("GET", f"/api/projects/v/hypotheses/{hid}")
    assert r["made_with"]["older"] is True and r["made_with"]["label"] == "0.0.1"
    st, t = api("GET", f"/api/projects/v/themes/{run_id}")
    assert t["made_with"]["older"] is True and t["made_with"]["label"].startswith("before ")
    st, p = api("GET", "/api/projects/v/profile?framework=sdg")
    older = [(m["label"], m["n"]) for m in p["made_with"] if m["older"]]
    assert older == [("0.0.1", 2)]  # a person's own label does not depend on a version


def test_the_three_pages_show_it_in_their_head():
    lib = (STATIC / "lib.js").read_text("utf-8")
    assert "export function madeWithFact(m)" in lib
    for view, call in (("result.js", "madeWithFact(r.made_with)"), ("themes.js", "madeWithFact(v.made_with)"),
                       ("profile.js", "madeWithFact(prof.made_with)")):
        js = (STATIC / "views" / view).read_text("utf-8")
        assert call in js and re.search(r"import \{[^}]*\bmadeWithFact\b[^}]*\} from \"\.\./lib\.js\"", js)
