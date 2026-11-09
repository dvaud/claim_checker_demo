"""0.17: the glossary and the key terms of themes leave out the common words of each passage's language (stopwords.py).

In a project with Dutch interviews, "dan", "wel", "maar", "ja" and "ik" were the most frequent glossary terms and the
key terms of a theme (and, found by words, what held it together). Now:
- each passage is read by the common words of its own language (58 languages come with ENLENS; English and Dutch are
  edited by hand), and a word that is also English ("net", "door") is left out only in passages of its language;
- a short passage ("Ja.") takes the language of the passage before it;
- a project can switch a language off and list its own words (a speaker label) or phrases;
- a change of either makes the glossary out of date, and the Themes page says which key terms are now left out;
- search is unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from enlens_claims import ingest, researchlog, stopwords, terms, themes
from enlens_claims.store import Workspace
from enlens_claims.textutil import STOPWORDS, token_spans
from test_app import Api, api, home  # noqa: F401  (fixtures)

_DUTCH = [
    "Onderzoeker: Hoe gaat het met de Tovertafel in de huiskamer? Respondent: Ja, dan zie je wel dat de bewoners "
    "het leuk vinden, maar ik denk dat het na een tijdje minder wordt. Dus ja, de huiskamer is wel een goede plek, "
    "maar er moet dan wel iemand bij zijn. Eigen regie van de bewoners vind ik belangrijk.",
    "Onderzoeker: En wat doen jullie dan met de Tovertafel? Respondent: Nou, ik ben net terug van vakantie, maar ik "
    "weet wel dat de bewoners in de huiskamer er dan mee spelen. Ja, dat is echt fijn. Eigen regie, dat vinden we "
    "hier belangrijk, en de bewoners kiezen dan zelf een spel.",
    "Ja.",
    "Onderzoeker: Is de Tovertafel dan makkelijk te gebruiken? Respondent: Ja, je zet hem aan en dan gaat het wel. "
    "Maar ik denk dat de bewoners soms niet weten wat ze moeten doen, dus dan help ik ze. Eigen regie blijft lastig "
    "in de huiskamer.",
]
_ENGLISH = [
    "The care home set a target of net zero emissions by 2040. Staff met the target for heating early, and the door "
    "to the garden was replaced. Net zero is the aim of the whole care home group, and plants die in winter.",
    "Residents of the care home play games on the projected table. Because staff are busy, the table is used less "
    "over time. The care home reached net zero for electricity, and everyone agreed that net zero was worth it.",
    "Interviews with staff of each care home showed that the games work best in the afternoon. They themselves "
    "chose the games. A net zero plan was discussed with the care home managers, and the door stays open.",
]


def _write_corpus(folder: Path) -> Path:
    folder.mkdir(parents=True)
    for i, (place, season) in enumerate((("Amsterdam", "voorjaar"), ("Utrecht", "najaar")), 1):
        head = f"Interview {i}, opgenomen in {place} in het {season} van 202{i}, met een verzorgende van locatie {i}."
        (folder / f"interview{i}.txt").write_text("\n\n".join([head, *_DUTCH]) + "\n", encoding="utf-8")
        head = f"Report {i} on the projected table, written for the board of care group {i} in 202{i}."
        (folder / f"report{i}.txt").write_text("\n\n".join([head, *_ENGLISH]) + "\n", encoding="utf-8")
    return folder


@pytest.fixture
def ws(tmp_path):
    w = Workspace.create(tmp_path / "ws")
    ingest.ingest(w, [_write_corpus(tmp_path / "corpus")])
    terms.build(w)
    return w


def _labels(ws) -> set[str]:
    return {r[0].lower() for r in ws.query("SELECT label FROM terms")}


def test_dutch_common_words_are_no_terms_and_english_terms_stay(ws):
    labels = _labels(ws)
    assert not labels & {"dan", "wel", "maar", "ja", "ik", "je", "dus", "denk", "er", "nou"}, labels
    # content words of both languages stay, and so do English terms with a word Dutch lists ("net", "door")
    assert {"huiskamer", "bewoners", "tovertafel", "eigen regie", "care home", "net zero"} <= labels, labels
    assert "net terug" not in labels and "because" not in labels
    # the languages found, for the Concepts page
    found = {f["code"]: f["passages"] for f in stopwords.found(ws)}
    assert set(found) == {"en", "nl"} and found["nl"] >= 4 and found["en"] >= 4
    st = terms.status(ws)
    assert st["built"] and not st["stale"] and not st["words_changed"] and not st["documents_changed"]


def test_a_passages_language_is_told_by_its_common_words():
    def lang(text):
        return stopwords.detect(t[3] for t in token_spans(text, keep_stop=True))

    assert lang("Ja, in het begin is iedereen heel enthousiast.") == "nl"
    assert lang("Ja.") is None and lang("Tovertafel") is None           # too short to tell
    assert lang("People living in a care home or attending a day service.") == "en"
    assert lang("Nursing Care Technology Long-term care Residential Care") != "ro"   # "care" is Romanian too
    assert lang("Le résumé présente les résultats et les limites de cette étude pour les pays.") == "fr"
    assert lang("Die Ergebnisse zeigen, dass die Pflege mit dem Spiel nicht schlechter wird.") == "de"
    assert lang("Net zero by 2040 is the target.") == "en"                # "net" and "door" are Dutch as well
    assert lang("0 1 2 3 4 5 6 a e o y") is None                          # numbers and letters tell nothing
    # a passage that does not tell takes the one before it (the first ones: the first that tells)
    assert stopwords.fill([None, "nl", None, "en", None]) == ["nl", "nl", "nl", "en", "en"]
    assert stopwords.fill([None, None]) == ["en", "en"]


def test_the_lists_come_with_enlens():
    ls = stopwords.lists()
    assert len(ls) == 58 and set(ls) == set(stopwords.NAMES)
    assert {"dan", "wel", "maar", "nou", "oké", "allee", "denk"} <= ls["nl"]
    assert not {"eigen", "samen", "vrij"} & ls["nl"]                       # they start Dutch terms
    assert "zero" not in ls["en"] and "research" not in ls["en"] and "because" in ls["en"]
    # no letters or numbers from the lists (English is search's list, which has "a" and "i")
    assert all(len(w) > 1 and not w.isdigit() for c, words in ls.items() if c != "en" for w in words)
    data = Path(stopwords.__file__).parent / "data"
    assert (data / "stopwords-iso-LICENSE.txt").read_text().startswith("The MIT License")
    assert json.loads((data / "stopwords.json").read_text(encoding="utf-8"))["source"].startswith("stopwords-iso")
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text()
    assert '"data/*.json"' in pyproject and '"data/*.txt"' in pyproject
    # search keeps its own rule: "dan" and "wel" are still found
    assert "dan" not in STOPWORDS and "wel" not in STOPWORDS


def test_own_words_and_a_language_switched_off(ws):
    digest = ws.meta("terms_words")
    stopwords.save(ws, own=["Onderzoeker", "  net   zero ", "onderzoeker", ""])
    assert stopwords.settings(ws)["own"] == ["Onderzoeker", "net zero"]   # trimmed, no repeats (ignoring case)
    st = terms.status(ws)
    assert st["stale"] and st["words_changed"] and not st["documents_changed"]
    assert terms.ensure(ws)["terms"] > 0
    labels = _labels(ws)
    assert "onderzoeker" not in labels and "net zero" not in labels and "care home" in labels
    assert ws.meta("terms_words") != digest and not terms.status(ws)["stale"]
    # Dutch switched off: its passages are read by the English rule
    stopwords.save(ws, off=["nl"])
    terms.build(ws)
    assert {"dan", "wel"} <= _labels(ws)
    assert [f for f in stopwords.found(ws) if f["code"] == "nl"][0]["on"] is False
    # the research log says what changed
    logged = [r["text"] for r in ws.query("SELECT text FROM research_log WHERE kind='glossary-words'")]
    assert len(logged) == 2 and "Dutch" in logged[1] and "Onderzoeker" in logged[0]
    assert researchlog.GROUPS["glossary-words"]
    # saving the same again changes nothing and logs nothing
    stopwords.save(ws, off=["nl"])
    assert ws.scalar("SELECT COUNT(*) FROM research_log WHERE kind='glossary-words'") == 2
    with pytest.raises(ValueError):
        stopwords.save(ws, off=["en"])
    with pytest.raises(ValueError):
        stopwords.save(ws, off=["xx"])
    with pytest.raises(ValueError):
        stopwords.save(ws, own=["x" * (stopwords.MAX_OWN_CHARS + 1)])


def test_a_reading_made_under_other_rules_is_not_used(ws):
    plain = terms._reading_stamp(stopwords.rules(ws))
    stopwords.save(ws, own=["huiskamer"])
    assert terms._reading_stamp(stopwords.rules(ws)) != plain
    assert stopwords.Rules(own=["a b"]).digest == stopwords.Rules(own=["a  b"]).digest
    terms.build(ws)
    assert "huiskamer" not in _labels(ws)
    stopwords.save(ws, own=[])
    terms.build(ws)                                       # back to the first rules: the word is a term again
    assert "huiskamer" in _labels(ws)


def test_the_themes_page_names_key_terms_now_left_out(ws):
    rid = themes.run(ws, k=2, mode="words")
    all_terms = [w for t in themes.view(ws, rid)["themes"] for w in t["terms"]]
    assert all_terms and themes.view(ws, rid)["run"]["terms_left_out"] == []
    gone = next(w for w in all_terms if " " not in w)
    stopwords.save(ws, own=[gone])
    assert themes.view(ws, rid)["run"]["terms_left_out"] == []     # out of date: it cannot tell yet
    terms.build(ws)
    assert gone in themes.view(ws, rid)["run"]["terms_left_out"]


def test_the_api_for_what_the_glossary_leaves_out(api, tmp_path):  # noqa: F811
    corpus = _write_corpus(tmp_path / "corpus")
    assert api("POST", "/api/projects", {"name": "P"})[0] == 200
    for f in sorted(corpus.iterdir()):
        assert api("POST", f"/api/projects/P/uploads?batch=b1&name={f.name}", raw=f.read_bytes())[0] == 200
    job = api.wait(api("POST", "/api/projects/P/ingest", {"batch": "b1"})[1]["job"]["id"])
    assert job["state"] == "done", job["error"]
    st, r = api("GET", "/api/projects/P/terms/words")
    assert st == 200 and r["off"] == [] and r["own"] == [] and r["max_own"] == stopwords.MAX_OWN
    assert [lang["code"] for lang in r["languages"]] == ["nl", "en"] and all(lang["on"] for lang in r["languages"])
    assert r["status"]["built"] and not r["status"]["stale"]
    st, r = api("PUT", "/api/projects/P/terms/words", {"off": ["nl"], "own": "Onderzoeker\n\nR1\n"})
    assert st == 200 and r["off"] == ["nl"] and r["own"] == ["Onderzoeker", "R1"]
    assert r["status"]["words_changed"] and r["languages"][0] == {"code": "nl", "name": "Dutch",
                                                                   "passages": r["languages"][0]["passages"], "on": False}
    assert api("PUT", "/api/projects/P/terms/words", {"off": ["en"]})[0] == 400
    assert api("PUT", "/api/projects/P/terms/words", {"off": "nl"})[0] == 400
    assert api("PUT", "/api/projects/P/terms/words", {"own": 5})[0] == 400
    assert api("PUT", "/api/projects/P/terms/words", {"own": ["a", ["b"]]})[0] == 400
    st, g = api("GET", "/api/projects/P/terms")
    assert st == 200 and g["stale"] and g["words_changed"] and not g["documents_changed"]


# ---- the 0.17 review -------------------------------------------------------------------------------------------------

def test_english_headings_and_tables_are_not_read_as_another_language():
    def lang(text):
        return stopwords.detect(t[3] for t in token_spans(text, keep_stop=True))

    # words of other languages' lists that are English words too tell nothing ("care" is Romanian, "global" Malay)
    for text in ("Net zero care homes", "Global design program for media", "Ana Maria de la Cruz",
                 "Van der Waals forces", "Table 4. Net zero care home retrofits in 2023 Private care homes 12 14"):
        assert lang(text) in (None, "en"), text
    assert {"care", "global", "door", "net"} <= set(stopwords._data()["english_too"])
    # words English shares with Dutch ("in", "is") speak for neither
    assert lang("Ja, in het begin is iedereen heel enthousiast.") == "nl"
    # and in a table the English terms stay
    rules = stopwords.DEFAULT
    toks = token_spans("Net zero care homes and net zero care homes", keep_stop=True)
    lang_ = stopwords.fill([stopwords.detect(t[3] for t in toks)])[0]
    keys = {k for _a, _b, k in terms._grams("Net zero care homes and net zero care homes", None, rules.stops(lang_))}
    assert {"net zero", "care home"} <= keys


def test_a_typed_name_finds_its_term_whatever_its_language(ws):
    rules = stopwords.rules(ws)
    assert terms._key_of("global bank", rules) == "global bank"     # not read as Malay
    assert terms._key_of("de huiskamer", rules) == "huiskamer"
    assert terms.find_term(ws, "Care homes") == terms.find_term(ws, "care home") is not None
    assert terms._key_of("dan", rules) == "dan"                      # no term: the Themes page can name it
    # an own phrase is read as a term is written: "the care home" leaves out "care home"
    assert stopwords.Rules(own=["the care home"]).phrases == {terms._key_of("care home")}
    assert stopwords.Rules(own=["the Interviewer"]).words == {"interviewer"}


def test_a_build_by_an_older_enlens_makes_the_glossary_out_of_date(ws):
    assert not terms.status(ws)["stale"]
    ws.set_meta("terms_build_id", "made-by-0.16")     # what a build of before 0.17 changes; it notes no rules
    st = terms.status(ws)
    assert st["stale"] and st["words_changed"]


def test_a_phrase_of_ones_own_does_not_read_the_documents_again(ws):
    before = terms._reading_stamp(stopwords.rules(ws))
    stopwords.save(ws, own=["care home"])
    assert terms._reading_stamp(stopwords.rules(ws)) == before     # the readings stand; only the term goes
    assert terms.status(ws)["words_changed"]
    terms.build(ws)
    assert "care home" not in _labels(ws) and "net zero" in _labels(ws)


def test_saving_keeps_what_another_window_saved(ws):
    stopwords.save(ws, off=["nl"])
    stopwords.save(ws, own=["Onderzoeker"])
    assert stopwords.settings(ws) == {"off": ["nl"], "own": ["Onderzoeker"]}
    with pytest.raises(ValueError):
        stopwords.save(ws, own=["a", ["b"]])
    assert stopwords.settings(ws)["own"] == ["Onderzoeker"]


def test_a_term_that_left_for_another_reason_is_not_named_left_out(ws):
    rid = themes.run(ws, k=2, mode="words")
    shown = [w for t in themes.view(ws, rid)["themes"] for w in t["terms"]]
    content = next(w for w in shown if terms._key_of(w))
    with ws.connect() as cx:     # as if the glossary's limit or a removed document had taken it
        cx.execute("DELETE FROM terms WHERE term_id=?", (terms.term_id(terms._key_of(content)),))
    assert content not in themes.view(ws, rid)["run"]["terms_left_out"]
