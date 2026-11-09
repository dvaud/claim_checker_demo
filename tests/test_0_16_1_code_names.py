"""0.16.1: a codebook made from the themes gets short code names, without AI (codenames.py).

Before, a theme's name was cut at 40 characters ("National green hydrogen strategies and d"). Now:
- a code name is words of the theme's name, as short as the documents allow: one or two words first, and a longer
  name only when the shorter ones are used too often outside the theme ("Remote work" is everywhere in the demo
  corpus, so "Remote work and young employees" becomes "Young employees");
- every theme gets a ladder of names from less to more specific, each within 40 characters, the chosen one marked;
- two themes never get the same code; a name a person gave the theme is kept when it fits; a name with no evidence
  in the documents (another language) is marked unsure;
- a theme named by its key terms keeps each term whole ("work from home", never "work");
- the last resort cuts before a word, never inside one.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from enlens_claims import codebooks, codenames, ingest, themes
from enlens_claims.store import Workspace

# A small corpus whose numbers are clear by design (the demo corpus is too small: its themes have five passages, and
# k-means groups them differently on Windows). Each document is one theme. "remote work" and "bus services" are in
# every paragraph of every document; "young employees" in one document (and once in another, so the glossary knows it);
# "night bus services" and "office days" in one each.
_FILLER = ["The report lists the figures for each district and year.",
           "Several respondents described the same pattern in their own words.",
           "The authors compare the findings with earlier surveys of the region.",
           "Most of the changes were small but consistent over time.",
           "A later section discusses the limits of the data and the sample.",
           "The numbers are rounded and the method is described in an annex.",
           "Readers can find the questionnaire in the appendix of the report."]
_CORES = {
    "interviews": "Young employees said that remote work left them lonely, and young employees in their first job "
                  "missed the office.",
    "transport": "Night bus services ran again, and remote work changed when people travelled; the night bus services "
                 "were full most evenings.",
    "offices": "Office days were set by employers, with remote work on the other days; office days had to be booked "
               "a week ahead.",
    "wellbeing": "Wellbeing and loneliness were measured each year, and remote work and wellbeing were linked in the "
                 "panel.",
}
LAYOUT = list(_CORES)


def _write_corpus(folder: Path) -> Path:
    folder.mkdir(parents=True)
    seasons = ["spring", "summer", "autumn", "winter"]
    for d, (stem, core) in enumerate(_CORES.items()):
        paras = []
        for i in range(8):
            extra = " Young employees were not asked." if stem == "wellbeing" and i == 0 else ""
            filler = " ".join(_FILLER[(i + d + k) % len(_FILLER)] for k in range(7))
            paras.append(f"Part {i + 1} of the {stem} file. {core} Bus services were mentioned too.{extra} {filler} "
                         f"Case {i * 7 + d * 3 + 3} is described here, with notes on {seasons[i % 4]} {2019 + i}.")
        (folder / f"{stem}.txt").write_text("\n\n".join(paras) + "\n", encoding="utf-8")
    return folder


@pytest.fixture
def run(tmp_path):
    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [_write_corpus(tmp_path / "corpus")])
    rid = themes.run(ws, k=4)
    tids = sorted(r[0] for r in ws.query("SELECT theme_id FROM themes WHERE run_id=?", (rid,)))
    assert len(tids) == len(LAYOUT)
    docs = {Path(r[1]).stem: r[0] for r in ws.query("SELECT doc_id, path FROM documents")}
    with ws.connect() as cx:   # each document is one theme, in LAYOUT's order
        for tid, stem in zip(tids, LAYOUT):
            cx.execute("UPDATE theme_members SET theme_id=? WHERE run_id=? AND passage_id IN "
                       "(SELECT passage_id FROM passages WHERE doc_id=?)", (tid, rid, docs[stem]))
    return ws, rid


def _name(ws, rid, names, source="model"):
    """Give the themes these names, in LAYOUT's order (interviews, transport, offices, wellbeing)."""
    tids = sorted(r[0] for r in ws.query("SELECT theme_id FROM themes WHERE run_id=?", (rid,)))
    with ws.connect() as cx:
        for tid, nm in zip(tids, names):
            cx.execute("UPDATE themes SET name=?, name_source=? WHERE run_id=? AND theme_id=?", (nm, source, rid, tid))
    v = themes.view(ws, rid)["themes"]
    order = {tid: i for i, tid in enumerate(tids)}
    v.sort(key=lambda t: order[t["theme_id"]])
    return v, codenames.for_run(ws, rid, v)


NAMES = ["Remote work and young employees", "Night bus services", "Office days and employer recommendations",
         "Remote work, loneliness and wellbeing"]


def _words(text):
    return {w.lower().strip(",") for w in text.replace("&", "and").split()}


def test_short_names_climb_past_a_generic_one(run):
    ws, rid = run
    v, got = _name(ws, rid, NAMES)
    picks = {t["name"]: got[t["theme_id"]]["names"][got[t["theme_id"]]["pick"]] for t in v}
    # "Remote work" is in every document, a quarter of its passages in each theme: too generic for any of them
    assert picks["Remote work and young employees"] == "Young employees"
    assert picks["Office days and employer recommendations"] == "Office days"
    assert picks["Remote work, loneliness and wellbeing"] != "Remote work"
    # "Bus services" is everywhere too, "services" is written inside it: only three words single out the theme
    bus = got[v[1]["theme_id"]]
    assert bus["names"] == ["Bus services", "Night bus services"] and bus["pick"] == 1 and bus["sure"]
    assert all(got[t["theme_id"]]["sure"] for t in v)
    for t in v:
        g = got[t["theme_id"]]
        assert len(g["names"][g["pick"]].split()) <= 3
        assert all(len(n) <= 40 for n in g["names"])
        # each name is words of the theme's name, from less to more specific, each holding the one before it
        assert all(_words(n) <= _words(t["name"]) for n in g["names"])
        counts = [len(n.split()) for n in g["names"]]
        assert counts == sorted(counts) and len(set(counts)) == len(counts)
        for a, b in zip(g["names"], g["names"][1:]):
            assert set(codenames.key(a).split()) <= set(codenames.key(b).split())


def test_two_themes_never_share_a_code_and_a_persons_name_is_kept(run):
    ws, rid = run
    v, got = _name(ws, rid, ["Office days and employer recommendations"] * 2 + NAMES[2:])
    codes = [codenames.key(got[t["theme_id"]]["names"][got[t["theme_id"]]["pick"]]) for t in v]
    assert len(set(codes)) == len(codes)
    v, got = _name(ws, rid, ["Commuting by night bus"], source="person")
    mine = next(t for t in v if t["name"] == "Commuting by night bus")
    g = got[mine["theme_id"]]
    assert g["names"][g["pick"]] == "Commuting by night bus" and g["sure"]


def test_no_evidence_is_marked_unsure_and_key_terms_stay_whole(run):
    ws, rid = run
    v, got = _name(ws, rid, ["Zorgmedewerkers en bewoners van verpleeghuizen"])
    t = next(t for t in v if t["name"].startswith("Zorg"))
    g = got[t["theme_id"]]
    assert g["sure"] is False and len(g["names"][g["pick"]]) <= 40
    assert _words(g["names"][g["pick"]]) <= _words(t["name"])
    v, got = _name(ws, rid, ["young employees · work from home · job"], source="terms")
    t = next(t for t in v if "·" in t["name"])
    assert all(n.lower() in {"young employees", "work from home", "job", "young employees, work from home, job"}
               for n in got[t["theme_id"]]["names"])


def test_the_codebook_draft_uses_the_chosen_name(run):
    ws, rid = run
    _name(ws, rid, NAMES)
    src = codebooks.theme_sources(ws)
    for t in src[0]["themes"]:
        assert t["code"]["code"] == t["names"][t["pick"]] and len(t["code"]["code"]) <= 40
        assert t["code"]["description"]   # the theme's full name stays in the description when there is no other
    drafts = [t["code"] for t in src[0]["themes"]]
    cb = codebooks.create(ws, "short_names", "Short names", "project", "themes", {"codes": drafts})
    assert "Young employees" in [c["code"] for c in cb["codes"]]


@pytest.mark.parametrize("text,cut", [
    ("National green hydrogen strategies and development", "National green hydrogen strategies"),
    ("Electricity and clean cooking access Africa", "Electricity and clean cooking access"),
    ("Short name", "Short name"),
    ("Decarbonisation-of-everything-everywhere-all-at-once-forever", "Decarbonisation-of-everything-everywhere"),
])
def test_a_last_resort_cut_is_before_a_word(text, cut):
    assert codenames.cut(text) == cut and len(codenames.cut(text)) <= 40


def test_parse_finds_the_phrases():
    assert codenames._parse("Hydrogen transport by pipeline and ship") == [
        (None, ["Hydrogen", "transport"]), ("by", ["pipeline"]), ("and", ["ship"])]
    assert codenames._parse("Social inclusion, polarization and social protection") == [
        (None, ["Social", "inclusion"]), (",", ["polarization"]), ("and", ["social", "protection"])]
    # two joining words in a row join no phrase; "the" is no word of a name; "compared" is no subject
    assert codenames._parse("Learning and using the Tovertafel")[1] == ("?", ["the", "Tovertafel"])
    assert codenames._parse("Electrolyser technologies compared") == [(None, ["Electrolyser", "technologies"])]


def _picks(ws, rid, names, source="model"):
    v, got = _name(ws, rid, names, source)
    return [(t["name"], got[t["theme_id"]]) for t in v]


def test_odd_names_give_clean_codes(run):
    """The review's cases: a dash after a bracket is no word, a name of marks gets "Theme N", the same name four
    times gives four codes, joining words of other languages start no code."""
    ws, rid = run
    out = _picks(ws, rid, ["Remote work (WFH) – young employees", "Office (days) - employer: recommendations",
                           "   ", "and of the"])
    for name, g in out:
        code = g["names"][g["pick"]]
        assert code[0].isalnum() and code.strip() == code and len(code) <= 40, (name, code)
        assert not any(n.startswith(("-", "–")) for n in g["names"])
    assert [g["names"][g["pick"]] for _n, g in out][2:] == [f"Theme {t['theme_id']}"
                                                           for t in themes.view(ws, rid)["themes"][2:4]]
    for same in (["Remote work"] * 4, ["Tovertafel"] * 4, ["Young employees"] * 4):
        codes = [codenames.key(g["names"][g["pick"]]) for _n, g in _picks(ws, rid, same)]
        assert len(set(codes)) == 4, codes
    for name, g in _picks(ws, rid, ["Zorgmedewerkers en bewoners van verpleeghuizen",
                                    "Travail à domicile et jeunes employés", "Работа из дома и сотрудники",
                                    "Lakhatás és a fiatal munkavállalók"]):
        for n in g["names"]:
            assert n.split()[0].lower() not in codenames._LINKS | codenames._FILLER, (name, n)


def test_a_persons_name_keeps_its_articles_and_longer_names_too(run):
    ws, rid = run
    for mine in ("Life in the city", "The role of the state", "The young employees"):
        (name, g), *_ = _picks(ws, rid, [mine], source="person")
        assert g["names"][g["pick"]] == mine and g["sure"]
    (name, g), *_ = _picks(ws, rid, ["Loneliness of the young employees"])
    assert "Loneliness of the young employees" in g["names"]


def test_a_moved_passage_counts_where_it_was_moved(run):
    ws, rid = run
    v = themes.view(ws, rid)["themes"]
    a, b = v[0]["theme_id"], v[1]["theme_id"]
    pid = ws.query("SELECT passage_id FROM theme_members WHERE run_id=? AND theme_id=? LIMIT 1", (rid, a))[0][0]
    themes.edit(ws, rid, "move", passage_id=pid, value=b)
    ev = codenames._Evidence(ws, rid, {})
    pos = ev.idx.pos[pid]
    assert pos in ev.theme[b] and pos not in ev.theme[a]
