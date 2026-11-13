"""0.14.3: the exploration features and the SDG pack.

- the search: a phrase's own stop words are required where written and a match starts at its first word; words beside
  a quoted phrase are required; "words that often appear nearby" in one document are compared with that document;
- the highlighted PDF: each highlight lands at its own place on the page, short mentions ("it") included;
- the bibliography: a DOI a document only cites, and a reference list inside a short document, no longer link or
  match; a decision does not search again; BibTeX urls and @string macros;
- themes: edits follow their themes by the passages they share; two runs in one second do not collide;
- profile: a keyword label a person accepted stays once the AI has read the passage;
- SDG pack: references of different years stay apart;
- codebooks: semicolon-separated and Windows-code-page files, and a bad file in a folder is reported.
"""
from __future__ import annotations

import json
import random
import shutil
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from helpers import make_pdf  # noqa: E402

from enlens_claims import annotate, bibliography as bib, concordance, frameworks, ingest, profile, terms, themes, vca  # noqa: E402
from enlens_claims.store import Workspace  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "enlens_claims" / "gui" / "static"


def _ws(tmp_path: Path, files: dict[str, str], name: str = "ws") -> Workspace:
    d = tmp_path / f"corpus_{name}"
    d.mkdir(exist_ok=True)
    for fn, txt in files.items():
        (d / fn).write_text(txt, encoding="utf-8")
    ws = Workspace.create(tmp_path / name)
    ingest.ingest(ws, [d])
    return ws


# --- the search -----------------------------------------------------------------------------------------------------
ECONOMY = ("The economy grew fast. Imports from electrolysers rose. The economy shrank later. An economy of scale.\n\n"
           "Imports of electrolysers grew too.")


def test_a_phrases_own_stop_words_are_required_and_it_matches_once(tmp_path):
    ws = _ws(tmp_path, {"a.txt": ECONOMY})
    for q, mode in (('"the economy"', "any"), ("the economy", "phrase"), ('"the economy"', "phrase")):
        r = concordance.search(ws, q, mode=mode)
        assert r["total"] == 2, (q, mode, [x["node"] for x in r["lines"]])
        assert all(x["node"].lower() == "the economy" for x in r["lines"])
    r = concordance.search(ws, "imports of electrolysers", mode="phrase")
    assert [x["node"] for x in r["lines"]] == ["Imports of electrolysers"]   # not "Imports from electrolysers"
    # a stop word between two content words may still be skipped as before ("green and hydrogen" is not a phrase here)
    assert concordance.search(ws, "economy of scale", mode="phrase")["total"] == 1


def test_words_beside_a_quoted_phrase_are_required(tmp_path):
    pad = " The ministry keeps a long list of projects, partners, sites and permits that it reviews every year."
    ws = _ws(tmp_path, {"a.txt": "Green hydrogen helps Morocco export power to Europe over the next decade." + pad * 3,
                        "b.txt": "Green hydrogen is made with water and wind in northern Chile, far from any city." + pad * 3})
    assert concordance.search(ws, '"green hydrogen"', mode="phrase")["total"] == 2
    r = concordance.search(ws, '"green hydrogen" Morocco', mode="phrase")
    assert r["total"] == 1 and "Morocco" in r["lines"][0]["right"]
    assert concordance.search(ws, '"green hydrogen" Atlantis', mode="phrase")["total"] == 0


def test_nearby_words_are_compared_with_the_documents_searched(tmp_path):
    a = " ".join(["Hydrogen needs filler words and more filler words here."] * 60)
    b = " ".join(["Songbirds nest in wetlands and sing at dawn."] * 60)
    ws = _ws(tmp_path, {"a.txt": a, "b.txt": b})
    docs = [r["doc_id"] for r in ws.query("SELECT doc_id FROM documents WHERE path LIKE '%a.txt'")]
    whole = {w["word"]: w for w in concordance.collocates(ws, "hydrogen", min_count=3)["words"]}
    one = {w["word"]: w for w in concordance.collocates(ws, "hydrogen", docs=docs, min_count=3)["words"]}
    # a word as common in the document as anywhere in it is not "typical" of the hits; against the whole corpus it
    # seemed to be (the other document's words are missing from its baseline)
    assert "filler" in whole and "filler" in one
    assert whole["filler"]["pmi"] > 0.5
    assert abs(one["filler"]["pmi"]) < whole["filler"]["pmi"] / 2


# --- the highlighted PDF ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("pdfminer", [True, False])
def test_each_highlight_lands_at_its_own_place(tmp_path, pdfminer):
    if pdfminer:
        pytest.importorskip("pdfminer")
    d = tmp_path / "c"
    d.mkdir()
    page = ("Green hydrogen production needs water. In arid regions green hydrogen competes with farming for water. "
            "Exporters of green hydrogen must plan desalination. Wastewater reuse for green hydrogen is cheaper. ") * 3
    make_pdf(d / "a.pdf", [page, page], title="Green hydrogen water")
    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [d])
    terms.build(ws)
    tid = terms.find_term(ws, "green hydrogen")
    doc = ws.query("SELECT doc_id FROM documents")[0][0]
    marks = annotate.collect(ws, doc, layers=("concepts",), concept=tid)
    annotate.place(d / "a.pdf", marks, use_pdfminer=pdfminer)
    assert len(marks) >= 20 and all(m.placed for m in marks)
    spots = {(m.page, tuple(map(tuple, m.quads))) for m in marks}
    assert len(spots) == len(marks)          # one place each, not the first match of the words on the page


def test_a_short_mention_is_placed(tmp_path):
    d = tmp_path / "c"
    d.mkdir()
    page = "Green hydrogen is costly. The plant is new and it works. Many say it is early. We think it will pay."
    make_pdf(d / "a.pdf", [page])
    m = annotate.Mark(0, 2, "it", "concept", "n", "concepts", 1, where=0.5)
    m2 = annotate.Mark(0, 2, "we", "concept", "n", "concepts", 1)
    annotate.place(d / "a.pdf", [m, m2])
    assert m.placed and m2.placed
    # a whole word only: "it" is not found inside "with" or "writing"
    assert annotate._find_nearest("write with it", "it", None)[0] == 11
    assert annotate._find_nearest("writing with", "it", None) is None


# --- the bibliography ------------------------------------------------------------------------------------------------
BRIEF = ("Municipal policy brief on commuting\n\nThe city council asks whether remote work changes commuting. "
         "Earlier work found that hybrid work lowers emissions. " * 3 +
         "\n\nReferences\n\nLindqvist, A. (2025). Remote work and the commuting emissions of young employees. "
         "Journal of Transport 12, 1-20.\nOkafor, B. (2023). Hybrid work and productivity: a review. Work Studies 4, 2-30.\n")
BIB = """@string{ijhe = "International Journal of Hydrogen Energy"}
@article{lind, title={Remote work and the commuting emissions of young employees}, author={Lindqvist, Anna}, year={2025}}
@article{oka, title={Hybrid work and productivity: a review}, author={Okafor, Ben}, year={2023}, journal=ijhe,
  doi={10.5555/hybrid.2021.7}, url={https://example.org/~okafor/paper--1.pdf}}
"""


def _bib_state(ws):
    return {(r["item_key"], r["doc_id"]): r["status"] for r in ws.query("SELECT item_key, doc_id, status FROM bib_links")}


def test_the_reference_list_of_a_short_document_does_not_link_the_works_it_cites(tmp_path):
    ws = _ws(tmp_path, {"brief.txt": BRIEF, "other.txt": "Something else entirely about birds and their songs. " * 20})
    fmt, works = bib.parse_file("x.bib", BIB)
    r = bib.save(ws, works, {"kind": "file", "format": fmt})
    assert r["confirm"] == 0 and r["linked"] == 0 and r["to_find"] == 2, r
    assert not _bib_state(ws)


def test_bibtex_urls_and_string_macros(tmp_path):
    _fmt, works = bib.parse_file("x.bib", BIB)
    oka = next(w for w in works if w["key"] == "bib:oka")
    assert oka["url"] == "https://example.org/~okafor/paper--1.pdf"
    assert oka["doi"] == "10.5555/hybrid.2021.7"
    assert oka["container"] == "International Journal of Hydrogen Energy"


def test_a_doi_a_document_only_cites_is_proposed_not_linked(tmp_path):
    cited = "10.5555/cited.2020.9"
    body = ("A study of urban commuting and remote work. " * 80 + f"\n\nAs shown by Rossi (2020), doi:{cited}, remote "
            "work matters. " + "More text about the city. " * 400 + f"\n\nSee also doi:{cited} and doi:{cited}.")
    own = ("Remote work and wellbeing\ndoi:10.5555/own.2024.1\n\n" + "The text of the paper itself. " * 300)
    ws = _ws(tmp_path, {"citing.txt": "Commuting paper\n\n" + body + "\n\nReferences\n\nRossi, A. (2020). Work. doi:" + cited,
                        "own.txt": own})
    # the first document's DOI, as ingest guesses it, is the one it cites most
    assert ws.scalar("SELECT doi FROM documents WHERE path LIKE '%citing.txt'") == cited
    works = [bib._work("bib:rossi", "article", "Work at a distance", [{"last": "Rossi", "first": "A", "role": "author"}],
                       "2020", cited, None, None, None, None, []),
             bib._work("bib:own", "article", "Remote work and wellbeing", [{"last": "Nagy", "first": "B", "role": "author"}],
                       "2024", "10.5555/own.2024.1", None, None, None, None, [])]
    bib.save(ws, works, {"kind": "file", "format": "bibtex"})
    rows = {(r["item_key"], r["status"], r["method"]) for r in
            ws.query("SELECT item_key, status, method FROM bib_links")}
    assert ("bib:own", "auto", "doi") in rows            # printed on the title page
    assert ("bib:rossi", "probable", "doi") in rows      # only cited: a person confirms
    assert ws.scalar("SELECT title FROM documents WHERE path LIKE '%citing.txt'") == "Commuting paper"   # not renamed


def test_a_decision_does_not_search_the_documents_again(tmp_path, monkeypatch):
    rng = random.Random(5)
    vocab = "hydrogen energy storage policy market water grid demand export carbon trade industry cost".split()
    files = {}
    for i in range(12):
        title = " ".join(rng.sample(vocab, 5)).title()
        files[f"d{i}.txt"] = title + "\n\nLindqvist 2024\n\n" + " ".join(rng.choices(vocab, k=300))
    ws = _ws(tmp_path, files)
    works = [bib._work(f"bib:w{i}", "article", " ".join(rng.sample(vocab, 5)),
                       [{"last": "Lindqvist", "first": "A", "role": "author"}], "2024", None, None, None, None, None, [])
             for i in range(30)]
    bib.save(ws, works, {"kind": "file", "format": "bibtex"})
    probable = ws.query("SELECT item_key, doc_id FROM bib_links WHERE status='probable'")
    assert probable
    calls = []
    real = bib._title_found
    monkeypatch.setattr(bib, "_title_found", lambda *a, **k: calls.append(1) or real(*a, **k))
    k, d = probable[0][0], probable[0][1]
    bib.decide(ws, k, d, "same")
    bib.decide(ws, k, d, "clear")
    bib.decide(ws, k, d, "different")
    bib.confirm_all(ws)
    assert not calls
    # and the result is what a full search gives
    state = _bib_state(ws)
    bib._PAIRS.clear()
    bib.match(ws)
    assert _bib_state(ws) == state


def test_the_author_and_year_are_checked_before_the_title(tmp_path, monkeypatch):
    ws = _ws(tmp_path, {"a.txt": "Hydrogen storage policy market analysis\n\n" + "text " * 100})
    works = [bib._work("bib:w", "article", "Hydrogen storage policy market", [{"last": "Nobody", "first": "N", "role": "author"}],
                       "1999", None, None, None, None, None, [])]
    calls = []
    real = bib._title_found
    monkeypatch.setattr(bib, "_title_found", lambda *a, **k: calls.append(1) or real(*a, **k))
    bib.save(ws, works, {"kind": "file", "format": "bibtex"})
    assert not calls      # neither author nor year is on the document: no title search


# --- themes ----------------------------------------------------------------------------------------------------------
TOPICS = {"water": "water stress aquifer desalination groundwater irrigation drought scarcity river basin".split(),
          "jobs": "employment jobs wages workers training skills labour unions apprenticeships income".split(),
          "price": "electrolyser cost capital expenditure price tariff subsidy levelised investment finance".split(),
          "birds": "birds nesting migration songbirds wetlands habitat feathers predators eggs plumage".split()}


def _topic_doc(rng, topic, n=12):
    ws_ = TOPICS[topic]
    return "\n\n".join(" ".join(f"The {rng.choice(ws_)} {rng.choice(ws_)} and {rng.choice(ws_)} {rng.choice(ws_)} matter."
                                for _ in range(25)) for _ in range(n))


def _topic_of(view_theme) -> str:
    words = " ".join(view_theme["terms"][:6])
    return max(TOPICS, key=lambda t: sum(w in words for w in TOPICS[t]))


def test_edits_follow_their_themes_when_documents_are_added(tmp_path, monkeypatch):
    # about theme edits, not reading: these word-soup documents are read as 0.14 read them (0.15's reader makes a
    # passage per paragraph, and k-means then numbers this made-up corpus's themes another way)
    monkeypatch.setattr(ingest, "READER", 1)
    rng = random.Random(1)
    c = tmp_path / "c"
    c.mkdir()
    for t in TOPICS:
        for i in range(2):
            # 0.15.7: "\n" on every system, as in test_0_13_9's corpus: Windows' "\r\n" would give other document
            # ids (a file's sha1), so another passage order, and k-means would group this corpus another way
            (c / f"{t}{i}.txt").write_text(_topic_doc(rng, t), newline="\n")
    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [c])
    r1 = themes.run(ws, k=4, seed=2, mode="words")
    v1 = themes.view(ws, r1)["themes"]
    by_topic = {_topic_of(t): t for t in v1}
    assert set(by_topic) == set(TOPICS)
    themes.edit(ws, r1, "rename", by_topic["jobs"]["theme_id"], "Work and pay")
    themes.edit(ws, r1, "rename", by_topic["water"]["theme_id"], "Water")
    c2 = tmp_path / "c2"
    c2.mkdir()
    for i in range(8):        # birds become the biggest topic: the themes are numbered again
        (c2 / f"birds_more{i}.txt").write_text(_topic_doc(rng, "birds"), newline="\n")
    ingest.ingest(ws, [c2])
    r2 = themes.run(ws, k=4, seed=2, mode="words")
    v2 = themes.view(ws, r2)["themes"]
    assert by_topic["water"]["theme_id"] != next(t for t in v2 if _topic_of(t) == "water")["theme_id"]  # a new number
    assert [t for t in v2 if t["name"] == "Water" and _topic_of(t) != "water"] == []     # never on another theme
    assert [t for t in v2 if t["name"] == "Work and pay" and _topic_of(t) != "jobs"] == []
    assert any(t["name"] == "Work and pay" for t in v2) and any(t["name"] == "Water" for t in v2)   # it follows its theme
    settings = json.loads(ws.scalar("SELECT settings_json FROM theme_runs WHERE run_id=?", (r2,)))
    assert settings["carried_edits"] >= 1 and settings["edits_from"] == r1
    # the same grouping again keeps its edits as before (one key)
    r3 = themes.run(ws, k=4, seed=2, mode="words")
    assert ws.scalar("SELECT run_key FROM theme_runs WHERE run_id=?", (r3,)) == ws.scalar(
        "SELECT run_key FROM theme_runs WHERE run_id=?", (r2,))
    assert {t["name"] for t in themes.view(ws, r3)["themes"]} == {t["name"] for t in v2}


def test_two_runs_in_one_second_do_not_collide(tmp_path, monkeypatch):
    rng = random.Random(2)
    c = tmp_path / "c"
    c.mkdir()
    for t in ("water", "jobs"):
        for i in range(2):
            (c / f"{t}{i}.txt").write_text(_topic_doc(rng, t, 6))
    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [c])
    monkeypatch.setattr(themes, "now", lambda: "2026-11-07T10:00:00+00:00")
    a = themes.run(ws, k=2, seed=0, mode="words")
    b = themes.run(ws, k=2, seed=0, mode="words")
    assert a != b and len(themes.runs(ws)) == 2


# --- the profile -----------------------------------------------------------------------------------------------------
def test_an_accepted_keyword_label_stays_once_the_ai_has_read_the_passage(tmp_path):
    txt = ("Access to safe drinking water and sanitation is a basic need. Water scarcity and water stress affect the "
           "water use efficiency of all sectors and the sustainable withdrawals of freshwater. ") * 4
    ws = _ws(tmp_path, {"a.txt": txt, "b.txt": "Unrelated text about birds and their songs in spring. " * 10})
    profile.keyword_pass(ws, "sdg")
    labs = profile.effective(ws, "sdg")
    lab = labs[0]
    pid = lab["passage_id"]
    others = {x["code"] for x in labs if x["passage_id"] == pid} - {lab["code"]}
    profile.set_label(ws, lab["label_id"], "accept")
    with ws.connect() as cx:   # the AI read the passage and found no codes
        cx.execute("INSERT INTO tasks(task_id, kind, model, prompt_version, payload_json, status, attempts, created_at) "
                   "VALUES (?,?,?,?,?,?,?,?)", (f"label:sdg:{pid}", "label", "m", "label-v1", "{}", "done", 1, "x"))
    after = {x["code"]: x for x in profile.effective(ws, "sdg") if x["passage_id"] == pid}
    assert lab["code"] in after and after[lab["code"]]["decision"] == "accept"
    assert not (others & set(after))        # what nobody accepted is still dropped


# --- the SDG pack ----------------------------------------------------------------------------------------------------
def test_references_of_different_years_are_kept_apart():
    refs = {}
    for text in ("International Energy Agency. Global Hydrogen Review 2022. Paris: IEA, 2022.",
                 "International Energy Agency. Global Hydrogen Review 2023. Paris: IEA, 2023.",
                 "Hydrogen Council. Hydrogen Insights 2021: a perspective on hydrogen investment. Brussels, 2021.",
                 "Hydrogen Council. Hydrogen Insights 2022: a perspective on hydrogen investment. Brussels, 2022."):
        key, doi = vca.ref_key(text)
        refs.setdefault(key, {"reference": text, "doi": doi, "targets": ["7.2"]})
    assert len(refs) == 4
    alias = vca.merge_references(refs, fixes=[])
    assert alias == {}
    # the same text twice is one reference, and a short one keeps its readable key
    assert vca.ref_key("IEA. Hydrogen. 2022. Paris.")[0] == vca.ref_key("IEA. Hydrogen. 2022. Paris.")[0]
    assert vca.ref_key("IEA. Hydrogen. 2022. Paris.")[0] == "ref:ieahydrogen2022paris"


# --- codebooks -------------------------------------------------------------------------------------------------------
def test_semicolon_and_windows_code_page_codebooks(tmp_path):
    semi = frameworks.parse_csv("code;description;group;group_name\nH1;Remote work lowers commuting, a lot;C;Commuting\n")
    assert semi["H1"].group_name == "Commuting"
    ok = frameworks.parse_csv("code;description\nH1;Remote work lowers commuting, a lot\nH2;Second\n")
    assert list(ok) == ["H1", "H2"] and ok["H1"].description == "Remote work lowers commuting, a lot"
    assert list(frameworks.parse_csv("code,description\nH1,One\n")) == ["H1"]
    assert list(frameworks.parse_csv("code\tdescription\nH1\tOne\n")) == ["H1"]
    # Hungarian Excel: Windows-1250, semicolons
    hu = "kód;leírás\nH1;Az őszi felújítás hűtést igényel\n".encode("cp1250")
    assert "őszi" in frameworks.decode(hu) and "hűtést" in frameworks.decode(hu)
    assert frameworks.decode("code;description\nH1;Zürich café\n".encode("utf-8-sig")).startswith("code")
    assert "café" in frameworks.decode("code;description\nH1;café\n".encode("cp1252"))


def test_a_bad_codebook_in_a_folder_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    ws = Workspace.create(tmp_path / "ws")
    folder = Path(ws.root) / "frameworks"
    folder.mkdir()
    (folder / "good.csv").write_bytes("kód;description\n".encode("cp1250").replace(b"k\xf3d", b"code") + b"H1;Fine\n")
    (folder / "broken.csv").write_text("name,notes\nx,y\n", encoding="utf-8")
    (folder / "Bad Name.csv").write_text("code,description\nH1,One\n", encoding="utf-8")
    assert "good" in frameworks.available(ws)
    bad = {p["file"]: p for p in frameworks.problems(ws)}
    assert set(bad) == {"broken.csv", "Bad Name.csv"}
    assert "code and description" in bad["broken.csv"]["error"] and bad["broken.csv"]["source"] == "project"


def test_the_page_reads_a_codebook_in_its_own_code_page_and_shows_problems():
    # 0.16: codebooks are added on their own page (views/codebooks.js), with the same reading of the file
    js = (STATIC / "views" / "codebooks.js").read_text(encoding="utf-8")
    # one reading of an uploaded text file for every page (lib.js readTextFile), not a copy in each
    assert "readTextFile(f)" in js and "readCsv" not in js and "windows-1250" not in js
    lib = (STATIC / "lib.js").read_text(encoding="utf-8")
    assert "windows-1250" in lib and "fatal: true" in lib
    assert "data.problems" in js   # the codebook files that cannot be used, each with the reason
    assert "await f.text()" not in js
