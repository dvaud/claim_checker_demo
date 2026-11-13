"""0.18 (roadmap N1): near-duplicate hypotheses, by key words, without AI.

Lines of a list that say nearly the same are pointed out before checking ("Lines 1 and 2 are very close: check them as
one?"), and so is a hypothesis checked before in the project that says nearly the same, a colleague's too once it came
in through sync. An offer, never a merge: lines that differ in strength (*observable*, *indicates*, *predicts*), in
direction or by a negation are said to be close but different, and are not offered as one.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from _fakedom import NODE, STATIC, run
from enlens_claims import claimcheck, nearduplicates as nd, sharing
from enlens_claims.llm import BaselineBackend
from test_app import api, home  # noqa: F401  (fixtures)
from test_storage_space import _round, _share, owner, store_dir, team  # noqa: F401  (fixtures)
from test_shared_projects import anna_and_ben  # noqa: F401  (fixture)

needs_node = pytest.mark.skipif(not NODE, reason="node is not installed")

# ------------------------------------------------------------------ the scoring
NEAR = [  # the same claim, written twice
    ("Remote work increases productivity.", "Remote work increases employee productivity."),
    ("Green hydrogen production can increase water stress in arid regions.",
     "In arid regions, green hydrogen production increases water stress."),
    ("Social media use is associated with depression in teenagers.",
     "Social media use is associated with depression among adolescents and teenagers."),
    ("Electrolysers create local jobs.", "Electrolyser projects create jobs locally."),
    ("Carbon taxes reduce emissions in the power sector.", "A carbon tax reduces emissions from the power sector."),
    ("Mindfulness training reduces stress among nurses.", "Mindfulness training reduces nurses' stress levels."),
    ("Hydrogen storage is cheap.", "Storage of hydrogen is cheap."),
    ("Dementia indicators are observable during gameplay.", "Dementia indicators can be observed during gameplay."),
]
SAME_TOPIC = [  # the same subject, another claim
    ("Screen time reduces sleep quality in adolescents.", "Screen time increases anxiety in adolescents."),
    ("Green hydrogen production can increase water stress in arid regions.",
     "Green hydrogen production creates local jobs in arid regions."),
    ("Remote work increases productivity.", "Remote work reduces team cohesion."),
    ("Carbon taxes reduce emissions in the power sector.", "Carbon taxes raise electricity prices for households."),
    ("Social media use is associated with depression in teenagers.",
     "Social media use is associated with loneliness in older adults."),
    ("Hydrogen storage is cheap.", "Hydrogen transport is expensive."),
    ("Electrolysers create local jobs.", "Hydrogen export hubs create local jobs."),
    ("Mindfulness training reduces stress among nurses.", "Mindfulness training improves sleep among nurses."),
    ("Teachers' feedback improves student motivation in secondary schools.",
     "Teachers' feedback improves student achievement in secondary schools."),
    ("Dementia indicators are observable during gameplay.", "Gameplay improves memory in older adults."),
]
DEMENTIA = ["Dementia indicators are observable during gameplay.", "Gameplay patterns can indicate dementia.",
            "Dementia can be predicted based on gameplay patterns."]


@pytest.mark.parametrize("a,b", NEAR)
def test_the_same_claim_written_twice_is_close(a, b):
    c = nd.close(a, b)
    assert c is not None and c["differ"] == [], (a, b)
    assert nd.close(b, a) is not None   # either way round


@pytest.mark.parametrize("a,b", SAME_TOPIC)
def test_hypotheses_on_the_same_topic_that_claim_other_things_are_not(a, b):
    assert nd.close(a, b) is None, (a, b, nd.similarity(nd.Sentence(a), nd.Sentence(b)))


def test_the_roots_join_a_words_forms():
    assert {nd.root(w) for w in ("indicators", "indicates", "indicate", "indication")} == {"indic"}
    assert {nd.root(w) for w in ("observable", "observed", "observation")} == {"observ"}
    assert {nd.root(w) for w in ("predicted", "prediction", "predictive", "predictor")} == {"predict"}
    assert nd.root("water") == "water" and nd.root("low") == "low"   # a short root is not cut


def test_lines_that_differ_in_strength_are_close_but_kept_apart():
    pairs = nd.in_list(DEMENTIA)
    assert {(p["a"], p["b"]) for p in pairs} == {(0, 1), (0, 2), (1, 2)}   # close: each is pointed out
    words = {(p["a"], p["b"]): p["differ"] for p in pairs}
    assert words[(0, 1)] == ["observable", "indicate"]
    assert words[(1, 2)] == ["indicate", "predicted"]
    assert words[(0, 2)] == ["observable", "predicted"]   # the verb, not the noun "indicators"
    # the same strength, worded twice, is one claim
    assert nd.close("Gameplay patterns indicate dementia.", "Gameplay patterns can indicate dementia.")["differ"] == []


def test_a_direction_or_a_negation_keeps_lines_apart():
    assert nd.close("Remote work increases productivity.", "Remote work reduces productivity.")["differ"] == \
        ["increases", "reduces"]
    assert nd.close("Remote work increases productivity.", "Remote work does not increase productivity.")["differ"] == ["not"]
    assert nd.close("Remote work increases productivity.", "Remote work doesn't increase productivity.")["differ"]
    assert nd.close("Social media use is associated with depression in teenagers.",
                    "Social media use causes depression in teenagers.")["differ"] == ["associated", "causes"]
    # a strength or a direction only one names is not a difference: "increases" and "causes more" say the same
    assert nd.close("Remote work increases productivity.", "Remote work causes higher productivity.")["differ"] == []


def test_two_short_lines_need_two_words_in_common():
    assert nd.close("Hydrogen is cheap.", "Hydrogen is dangerous.") is None
    assert nd.close("Electrolysers create local jobs.", "Electrolysers create local jobs.")["score"] == 1.0


def test_a_list_of_unrelated_lines_has_no_pairs():
    assert nd.in_list([a for a, _ in SAME_TOPIC[:5]]) == []


# ------------------------------------------------------------------ checked before, here and by a colleague
def _hyp(ws, hid, text, at="2026-11-03T10:00:00+00:00"):
    with ws.connect() as cx:
        cx.execute("INSERT INTO hypotheses(hyp_id, text, created_at) VALUES (?,?,?)", (hid, text, at))


def test_a_hypothesis_checked_before_is_found(loaded):
    _hyp(loaded, "h-one", "Remote work increases productivity.")
    _hyp(loaded, "h-two", "Remote work reduces productivity.")          # another claim: not offered
    _hyp(loaded, "h-far", "Hydrogen export hubs create local jobs.")
    got = nd.checked_before(loaded, ["Remote work increases employee productivity.", "Electrolysers are expensive."])
    assert [b["hyp_id"] for b in got[0]] == ["h-one"] and got[1] == []
    b = got[0][0]
    assert b["text"] == "Remote work increases productivity." and b["created_at"].startswith("2026-11-03")
    assert b["who"]["mine"] and b["who"]["name"] == "you"   # made in this copy: yours


def test_the_endpoint(api):  # noqa: F811
    from enlens_claims import home as h

    st, r = api("POST", "/api/projects", {"name": "Near"})
    ws = h.open_project("Near")
    _hyp(ws, "h-one", DEMENTIA[1])
    st, r = api("POST", "/api/projects/Near/hypotheses/similar",
                {"lines": DEMENTIA + ["Remote work increases productivity.", "Remote work increases employee productivity."]})
    assert st == 200
    pairs = {(p["a"], p["b"]): p for p in r["pairs"]}
    assert pairs[(3, 4)]["differ"] == [] and pairs[(1, 2)]["differ"] == ["indicate", "predicted"]
    assert [b["hyp_id"] for b in r["before"][1]] == ["h-one"] and r["before"][1][0]["score"] == 1.0
    assert r["before"][2] == []   # predicted, not indicated: the earlier answer is not this one's
    st, r = api("POST", "/api/projects/Near/hypotheses/similar", {"lines": [DEMENTIA[1]]})
    assert st == 200 and r["pairs"] == [] and r["before"][0][0]["hyp_id"] == "h-one"
    assert api("POST", "/api/projects/Near/hypotheses/similar", {"lines": "one line"})[0] == 400
    assert api("POST", "/api/projects/Near/hypotheses/similar", {"lines": ["x"] * 501})[0] == 400


def test_a_colleagues_shared_check_is_offered_with_their_name(team):
    anna, carol = team
    with anna:
        hid = claimcheck.check_hypothesis(anna.ws, "Electrolysers create local jobs in arid regions.",
                                          BaselineBackend(), "baseline", k=2)
    _share(anna, "check", hid)
    _round(anna)
    _round(carol)
    with carol:
        assert carol.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (hid,))
        got = nd.checked_before(carol.ws, ["Electrolysers create jobs locally in arid regions."])[0]
        mine = nd.checked_before(carol.ws, ["Hydrogen storage is cheap."])[0]
    assert [b["hyp_id"] for b in got] == [hid]
    assert got[0]["who"] == {"id": anna.id, "name": "Anna", "mine": False}
    assert mine == []
    with anna:  # in Anna's own copy it is hers
        b = nd.checked_before(anna.ws, ["Electrolysers create jobs locally in arid regions."])[0][0]
    assert b["who"]["mine"] and b["who"]["name"] == "you"
    # Anna takes it back: Carol's copy keeps it, but it is no longer offered
    with anna:
        sharing.unshare(anna.ws, [{"kind": "check", "key": hid}])
    _round(anna)
    _round(carol)
    with carol:
        assert sharing.state(carol.ws._conn(), "check", hid)["state"] == "withdrawn"
        assert nd.checked_before(carol.ws, ["Electrolysers create jobs locally in arid regions."])[0] == []


# ------------------------------------------------------------------ the page
def _js(rel: str) -> str:
    return (STATIC / rel).read_text(encoding="utf-8")


def test_the_page_asks_the_server_and_draws_offers_under_the_box():
    hyp = _js("views/hypotheses.js")
    assert 'import { nearNotices, dropLines, saysSomething } from "./near.js";' in hyp
    assert "/hypotheses/similar" in hyp and "const lookNearSoon = debounce(lookNear, 500);" in hyp
    assert 'h("div", { class: "field" }, label, ta, hint, listFold, nearBox, splitHint)' in hyp
    # a list is compared once the server has read it, line for line as it numbers them
    assert "list.items.map((it) => it.text)" in hyp and "await lookNear();" in hyp
    # never blocks: what is on screen when Check is pressed is checked anyway; what was not is shown first, once
    assert "const seen = near.text === ta.value;" in hyp and "checkList(seen); else checkOne(seen);" in hyp
    assert '"Check anyway"' in hyp
    # "Check as one" keeps one line, and a toast puts the others back
    assert "dropLines(was, list.items, group.filter((i) => i !== keep))" in hyp and 'text: "Undo"' in hyp
    css = _js("views.css")
    assert ".hyp-near {" in css and ".hyp-near:empty { display: none; }" in css


@needs_node
def test_the_offers_read_as_the_owner_asked(tmp_path):
    lines = DEMENTIA + ["Remote work increases productivity.", "Remote work increases employee productivity."]
    res = {"pairs": [{"a": 0, "b": 1, "score": 0.67, "differ": ["observable", "indicate"]},
                     {"a": 0, "b": 2, "score": 0.67, "differ": ["observable", "predicted"]},
                     {"a": 1, "b": 2, "score": 1.0, "differ": ["indicate", "predicted"]},
                     {"a": 3, "b": 4, "score": 0.75, "differ": []}],
           "before": [[], [{"hyp_id": "h1", "text": DEMENTIA[1], "created_at": "2026-11-03T10:00:00+00:00", "score": 1.0,
                            "differ": [], "who": {"id": "p1", "name": "Anna", "mine": False}}], [], [], []]}
    single = {"pairs": [], "before": [[{"hyp_id": "h2", "text": "Remote work increases productivity.",
                                        "created_at": "2026-11-03T10:00:00+00:00", "score": 0.75, "differ": [],
                                        "who": {"id": "me", "name": "you", "mine": True}}]]}
    probe = f"""
const N = await import(LIB.replace("lib.js", "views/near.js"));
const res = {json.dumps(res)}, single = {json.dumps(single)}, lines = {json.dumps(lines)};
const text = (els) => els.map((e) => e.textContent);
let kept = null;
const list = N.nearNotices(res, {{ lines, list: true, onKeep: (k, g) => {{ kept = [k, g]; }} }});
const one = N.nearNotices(single, {{ lines: ["Remote work increases employee productivity."] }});
const negation = text(N.nearNotices({{ pairs: [{{ a: 0, b: 1, score: 1, differ: ["not"] }}], before: [[], []] }}, {{ lines: ["a", "b"], list: true }})).map((t) => t.trim());
const unknown = N.nearNotices({{ pairs: [], before: [[{{ ...single.before[0][0], who: null }}]] }}, {{ lines: ["x"] }});
console.log(JSON.stringify({{
  list: text(list), one: text(one), unknown: text(unknown), negation,
  clusters: N.clusters([{{ a: 0, b: 1, differ: [] }}, {{ a: 1, b: 3, differ: [] }}, {{ a: 2, b: 4, differ: ["not"] }}]),
  apart: N.clusters([{{ a: 0, b: 1, differ: [] }}, {{ a: 2, b: 4, differ: ["not"] }}], true),
  says: [N.saysSomething(res), N.saysSomething({{ pairs: res.pairs.slice(0, 2), before: [[], []] }})],
  words: [N.linesWords([1]), N.linesWords([0, 1]), N.linesWords([0, 1, 3])],
  drop: N.dropLines("A first line here.\\n\\n# a comment\\nA second line here.\\nA third line here.",
                    [{{ text: "A first line here." }}, {{ text: "A second line here." }}, {{ text: "A third line here." }}], [1]),
  csv: N.dropLines('hypothesis,code\\n"A first line here.",6.4\\n"A second line here.",\\n',
                   [{{ text: "A first line here." }}, {{ text: "A second line here." }}], [0]),
  lost: N.dropLines("Something else entirely.", [{{ text: "A first line here." }}, {{ text: "B" }}], [0]),
}}));
"""
    out = run(probe, tmp_path)
    out["list"] = [t.strip() for t in out["list"]]
    assert out["list"][0].startswith("Lines 4 and 5 are very close: check them as one?")
    assert "Check as one" in out["list"][0]
    # the owner's list: one quiet line for the three, no merge offered
    assert "Lines 1, 2 and 3 are close but say “observable”, “indicate” and “predicted”: each is checked." in out["list"]
    assert out["negation"] == ["Lines 1 and 2 are close but one says “not”: both are checked."]
    assert not any("Lines 1 and 2 are very close" in t or "Lines 2 and 3 are very close" in t for t in out["list"])
    assert any(t.startswith("Line 2 — Anna checked this one on 3 Nov: “Gameplay patterns can indicate dementia.”")
               and t.endswith("Open its answer") for t in out["list"])
    assert out["one"] == ["You checked a very similar one on 3 Nov: “Remote work increases productivity.”Open its answer"]
    assert out["unknown"][0].startswith("A very similar one was checked on 3 Nov")
    assert out["clusters"] == [[0, 1, 3]] and out["apart"] == [[2, 4]]
    assert out["says"] == [True, False]
    assert out["words"] == ["Line 2", "Lines 1 and 2", "Lines 1, 2 and 4"]
    assert out["drop"] == "A first line here.\n\n# a comment\nA third line here."
    assert out["csv"] == 'hypothesis,code\n"A second line here.",\n'
    assert out["lost"] is None


def test_docs_name_the_endpoint_and_the_roadmap_item_is_built():
    root = Path(__file__).resolve().parent.parent
    assert "/hypotheses/similar" in (root / "docs" / "API.md").read_text(encoding="utf-8")
    road = (root / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    assert "**N1. Near-duplicate hypotheses** · Level 0 · built in 0.18.0" in road
