"""0.18.0 (roadmap L1, design note §1.4): the codebook clash review in the codebook editor (views/codebooks.js).

Where you and a colleague both changed one code since you last exchanged the codebook, the editor shows the two
versions side by side (what differs marked in words, not by colour alone) with *Keep mine* / *Keep theirs*, on the
existing endpoint `POST …/codebooks/<name>/clashes/<uid>`. Static checks of the page, and the endpoint as the page uses
it (the clash written as the merge writes it).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from test_app import api, home  # noqa: F401  (fixtures)

STATIC = Path(__file__).resolve().parents[1] / "src" / "enlens_claims" / "gui" / "static"
JS = (STATIC / "views" / "codebooks.js").read_text(encoding="utf-8")
# 0.17.0 (design guide): team.css is folded in; the clash review's own pieces are in views.css's Codebooks block, and
# the two versions side by side are the comparison component (lib.js compare(), components.css 4.27)
VIEWS = (STATIC / "views.css").read_text(encoding="utf-8")
CSS = VIEWS[VIEWS.index("/* ==== Codebooks */"):VIEWS.index("/* ==== Concepts */")]
COMPONENTS = (STATIC / "components.css").read_text(encoding="utf-8")


def test_the_editor_shows_both_versions_and_keeps_one():
    assert "function drawClashes()" in JS and "drawClashes();" in JS
    assert '"Keep mine"' in JS and '"Keep theirs"' in JS
    assert 'api("POST", `${base}/clashes/${P(x.uid)}`, { keep: which })' in JS
    assert 'clashSide("Yours", null, mine, x.theirs, !!x.removed_here)' in JS and "You removed this code." in JS
    assert "`Keep mine: “${name}” stays removed`" in JS                       # the button says what it does
    assert "Save or discard your changes first" in JS.split("async function settle", 1)[1][:300]   # never over a draft
    assert "actions: ro ? null : [mineBtn, theirsBtn]" in JS  # read-only: no buttons
    # what differs is said in words too (a screen reader, or no colour), and the two columns become one on a phone
    assert '" · differs"' in JS and ".cb-field.cb-differs" in CSS
    assert "compare({" in JS and "left: clashSide(" in JS and "right: clashSide(" in JS
    assert re.search(r"@media \(max-width: 860px\) \{\s*\.compare-sides \{ grid-template-columns: minmax\(0, 1fr\); \}", COMPONENTS)
    for field in ("Name", "Definition", "Group", "When to use it", "When not to use it", "Words it is matched by", "Examples"):
        assert f'"{field}"]' in JS, field


def test_keep_theirs_and_keep_mine_through_the_app(api):  # noqa: F811
    from enlens_claims import codebooks, home as home_mod

    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    ws = home_mod.open_project("Demo")
    codebooks.create(ws, "jobs", title="Jobs")
    st = codebooks.state_of(ws, "jobs")
    st["codes"] = [{"uid": "", "code": "Local jobs", "description": "Jobs near the plant.", "group": "", "include": "",
                    "exclude": "", "keywords": ["hiring"], "examples": []},
                   {"uid": "", "code": "Water", "description": "Fresh water.", "group": "", "include": "", "exclude": "",
                    "keywords": [], "examples": []}]
    codebooks.save(ws, "jobs", st)
    uids = {c["code"]: c["uid"] for c in codebooks.state_of(ws, "jobs")["codes"]}
    # the clashes as the merge writes them (sync/codebook_merge.py): theirs, in the side file
    _, f = codebooks.locate(ws, "jobs")
    meta = json.loads((f / "jobs.json").read_text(encoding="utf-8"))
    meta["clashes"] = {
        uids["Local jobs"]: {"code": "Local employment", "description": "Jobs held by residents.", "group": "", "group_name": "",
                             "include": "", "exclude": "", "keywords": ["hiring", "local"], "examples": ["few local people"],
                             "person_id": "p0123456789ab", "name": "Ben", "at": "2026-11-11T08:40:00+00:00"},
        uids["Water"]: {"code": "Water stress", "description": "Pressure on water.", "group": "", "group_name": "",
                        "include": "", "exclude": "", "keywords": [], "examples": [], "person_id": "p0123456789ab",
                        "name": "Ben", "at": "2026-11-11T08:41:00+00:00"},
    }
    (f / "jobs.json").write_text(json.dumps(meta), encoding="utf-8")

    st, r = api("GET", "/api/projects/Demo/codebooks/jobs")
    clashes = {c["uid"]: c for c in r["codebook"]["clashes"]}
    assert st == 200 and set(clashes) == {uids["Local jobs"], uids["Water"]}
    c = clashes[uids["Local jobs"]]  # every field the page reads
    assert c["code"] == "Local jobs" and c["removed_here"] is False and c["name"] == "Ben" and c["at"]
    assert c["theirs"]["code"] == "Local employment" and c["theirs"]["examples"] == ["few local people"]

    st, r = api("POST", f"/api/projects/Demo/codebooks/jobs/clashes/{uids['Local jobs']}", {"keep": "theirs"})
    assert st == 200 and [x["uid"] for x in r["codebook"]["clashes"]] == [uids["Water"]]
    assert {x["code"] for x in r["codebook"]["codes"]} == {"Local employment", "Water"}
    st, r = api("POST", f"/api/projects/Demo/codebooks/jobs/clashes/{uids['Water']}", {"keep": "mine"})
    assert st == 200 and r["codebook"]["clashes"] == [] and {x["code"] for x in r["codebook"]["codes"]} == {"Local employment", "Water"}
    assert api("POST", f"/api/projects/Demo/codebooks/jobs/clashes/{uids['Water']}", {"keep": "mine"})[0] == 404  # settled
    st, r = api("GET", "/api/projects/Demo/log?group=codebooks")
    assert any("Ben" in e["text"] for e in r["entries"])                     # the research log says whose was kept
