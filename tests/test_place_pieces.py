"""0.17.0: pieces a place once drew for itself, now drawn by the components (docs/DESIGN.md 3.1, 4.5, 4.6, 4.14).

- Bibliography's four lists are a filter choice with counts, no longer tiles that spelled the tab roles by hand.
- Tab roles come only from tabs(): no page spells them.
- A download row's files wrap as one group; a theme card's "and N other documents" never breaks.
- A place's icon sits on a grey tile: soft teal means here, chosen or found (tested in test_0_17_0_design.py).
"""
from __future__ import annotations

import re

import pytest

from _fakedom import NODE, STATIC, run
from _static import rule

VIEWS_JS = {p.name: p.read_text(encoding="utf-8") for p in (STATIC / "views").glob("*.js")}


def test_no_page_spells_the_tab_roles():
    """docs/DESIGN.md 4.5: tabs without an address are the whole tab pattern, made by tabs(); a page never adds it."""
    pat = re.compile(r"""role\s*:\s*["'](tab|tablist|tabpanel)["']|role=["'](tab|tablist|tabpanel)["']""")
    found = [f"{name}: {m.group(0)}" for name, js in VIEWS_JS.items() for m in pat.finditer(js)]
    assert not found, "tab roles spelled by a page:\n" + "\n".join(found)


def test_the_bibliography_lists_are_a_filter_choice():
    js = VIEWS_JS["bibliography.js"]
    assert "bib-tile" not in js
    m = re.search(r"choice\(\{ filter: true, label: \"Show the list\"(.|\n){0,400}?options: TABS\.map", js)
    assert m, "the four lists are choice({ filter: true, … }) with a count for each"
    # picking a list draws the list again, not the card that holds the choice: the focus stays on it
    assert "clear(body); drawLists();" in m.group(0) or "clear(body); drawLists();" in js[m.start():m.end() + 200]
    css = (STATIC / "views.css").read_text(encoding="utf-8")
    assert ".bib-tile" not in css


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_a_download_rows_files_wrap_as_one_group(tmp_path):
    out = run(r"""
const { downloadLinks } = await import(LIB);
const row = downloadLinks([{ text: "Excel (.xlsx)", onClick() {} }, { text: "CSV", note: "(for programmers)", onClick() {} }], { label: "Download all:" });
console.log(JSON.stringify({ row: row.className, kids: row.children.map((c) => [c.className, c.children.length]) }));
""", tmp_path)
    assert out["row"] == "dl-links"
    assert out["kids"] == [["dl-label", 0], ["dl-files", 2]]
    files = rule(".dl-files")
    assert files.get("display") == "inline-flex" and files.get("flex-wrap") == "wrap"


def test_a_theme_cards_other_documents_never_break():
    js = VIEWS_JS["themes.js"]
    assert 'h("span", { class: "nowrap" }, `and ${plural(docs.length - 3, "other document")}`)' in js
    assert rule(".nowrap").get("white-space") == "nowrap"
