"""0.17.0: the Search page marks every searched word and shows the title first.

The server already knows which words it found; it sends them as offsets (`marks`) and the page only draws them.
"""
from __future__ import annotations

from pathlib import Path

from enlens_claims import concordance, ingest
from enlens_claims.store import Workspace

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"
TEXT = ("Communities fight against dementia with music and walks. Dementia care also needs fighting spirit "
        "and patient families, and the ministry keeps a long list of projects, partners and sites.")


def _ws(tmp_path: Path) -> Workspace:
    d = tmp_path / "corpus"
    d.mkdir()
    (d / "a.txt").write_text(TEXT, encoding="utf-8")
    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [d])
    return ws


def _marked(x: dict) -> list[str]:
    line = x["left"] + x["node"] + x["right"]
    return [line[a:b].lower() for a, b in x["marks"]]


def test_all_words_mark_the_other_word_with_its_forms(tmp_path):
    ws = _ws(tmp_path)
    r = concordance.search(ws, "fight dementia", mode="all")
    assert r["lines"]
    for x in r["lines"]:
        centre = x["node"].lower()
        other = "dementia" if centre.startswith("fight") else "fight"
        assert other in " ".join(_marked(x)) or any(m.startswith(other) for m in _marked(x)), (centre, _marked(x))
    # stemming: "fighting" is found by "fight", so it is marked like the rest
    assert {"fight", "fighting"} <= {w for x in r["lines"] for w in _marked(x)}
    exact = concordance.search(ws, "fight dementia", mode="all", exact=True)
    assert all("fighting" not in _marked(x) for x in exact["lines"])


def test_near_marks_stay_inside_the_line(tmp_path):
    ws = _ws(tmp_path)
    r = concordance.search(ws, "fight dementia", mode="near", near=4)
    for x in r["lines"]:
        n = len(x["left"] + x["node"] + x["right"])
        assert all(0 <= a < b <= n for a, b in x["marks"])


def test_meaning_results_carry_every_matched_word(tmp_path):
    ws = _ws(tmp_path)
    r = concordance.meaning(ws, "fight dementia", None, k=5)
    p = r["passages"][0]
    assert p["text"] == TEXT or p["text"] in TEXT
    words = [p["text"][a:b].lower() for a, b in p["marks"]]
    assert {"fight", "fighting", "dementia"} <= set(words)    # every form, every occurrence
    assert words.count("dementia") == 2
    # nothing matched (found by meaning alone): nothing to mark
    assert all(not x["marks"] for x in concordance.meaning(ws, "zzzz qqqq", None, k=5)["passages"])


def test_the_page_draws_the_marks_and_puts_the_title_first():
    js = (STATIC / "views" / "search.js").read_text(encoding="utf-8")
    assert "wordSpans(x.left, addWord, x.marks)" in js
    assert "wordSpans(x.right, addWord, x.marks, x.left.length + x.node.length)" in js
    assert "markedText(p.text, p.marks)" in js
    assert ".slice(0, 28)" not in js
    assert 'class: "kw-title"' in js and "aria-label" in js
    css = (STATIC / "v07.css").read_text(encoding="utf-8")
    assert "mark.kw-also" in css and "-webkit-line-clamp: 2" in css


def test_one_visible_way_to_open_a_document_from_search():
    js = (STATIC / "views" / "search.js").read_text(encoding="utf-8")
    # the book icon is gone: the title opens the document; the flask action has a visible label
    assert 'icon("book-open"' not in js
    assert js.count("Open the document at these words") == 2  # the title's tooltip and accessible name
    assert 'icon("flask", { size: 13 }), "Check"' in js
    assert "Open the document at this passage" in js  # search by meaning opens the same way
    css = (STATIC / "v07.css").read_text(encoding="utf-8")
    assert ".kw-title:focus-visible" in css and "var(--accent-text)" in css
