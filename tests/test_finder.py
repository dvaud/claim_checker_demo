"""0.17.0: the feature finder (static/finder-index.js, static/finder.js).

The index and its scoring are plain JavaScript with no imports, so Node runs them here on the real FEATURES and
PLACES (features.js imports the DOM helpers of lib.js, so the page's globals are stood in for, as test_update_check does).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "enlens_claims" / "gui" / "static"
NODE = shutil.which("node")

STUB = """
globalThis.document = { querySelector: () => null, addEventListener() {}, documentElement: { dataset: {} } };
globalThis.window = globalThis; globalThis.location = { hash: "" };
globalThis.sessionStorage = { getItem: () => null, setItem() {} }; globalThis.localStorage = globalThis.sessionStorage;
"""

QUERIES = ["", "zotero", "codbook", "bibliografy", "hypothesys", "results", "check several", "themes", "glosary",
           "nvivo", "profile", "check a hypothesis", "diary", "highlight", "share", "excel", "xyzzyq", "changelog",
           "what's new"]


@pytest.fixture(scope="module")
def found(tmp_path_factory):
    f = tmp_path_factory.mktemp("finder") / "t.mjs"
    f.write_text(STUB + f"""
const {{ FEATURES, PLACES, SECTIONS }} = await import({json.dumps((STATIC / "features.js").as_uri())});
const {{ buildIndex, findFeatures }} = await import({json.dumps((STATIC / "finder-index.js").as_uri())});
const index = buildIndex({{ FEATURES, PLACES, SECTIONS }});
const addon = buildIndex({{ FEATURES: {{ ...FEATURES, tides: {{ section: "explore", title: "Tide tables", href: "#/tides", what: "Read the tide of every harbour.", icon: "clock" }} }}, PLACES, SECTIONS }});
const out = {{ n: index.length, queries: {{}}, kinds: [...new Set(index.map((e) => e.kind))], addon: findFeatures("tide", addon).map((e) => e.title) }};
for (const q of {json.dumps(QUERIES)}) out.queries[q] = findFeatures(q, index).map((e) => [e.title, e.href, e.kind, e.where]);
out.limit = findFeatures("a", index, {{ limit: 3 }}).length;
console.log(JSON.stringify(out));
""")
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def top(found, q, n=1):
    return [(t, h) for t, h, _k, _w in found["queries"][q][:n]]


pytestmark = pytest.mark.skipif(not NODE, reason="node is not installed")


def test_index_covers_places_views_features_and_actions(found):
    assert found["n"] >= 30
    assert set(found["kinds"]) == {"place", "view", "action"}
    assert found["addon"][0] == "Tide tables"            # an add-on's feature is found too


def test_empty_query_lists_the_seven_places(found):
    rows = found["queries"][""]
    assert [k for _t, _h, k, _w in rows] == ["place"] * 7
    assert [t for t, *_ in rows] == ["Overview", "Documents", "Search", "Codes", "Concepts", "Themes", "Hypotheses"]


def test_limit_option(found):
    assert found["limit"] <= 3


@pytest.mark.parametrize("q, title, href", [
    ("zotero", "Bibliography", "#/bibliography"),
    ("codbook", "Codebooks", "#/codebooks"),             # misspelt
    ("bibliografy", "Bibliography", "#/bibliography"),
    ("hypothesys", "Hypotheses", "#/hypotheses"),
    ("themes", "Themes", "#/themes"),
    ("glosary", None, "#/concepts"),
    ("nvivo", "Codes", "#/profile"),
    ("diary", "Research log", "#/log"),
    ("highlight", None, "#/notes"),
    ("share", None, "#/projects"),
])
def test_top_result(found, q, title, href):
    (t, h), = top(found, q)
    assert h == href
    if title:
        assert t == title


def test_glossary_misspelt_reaches_concepts_place(found):
    assert "Concepts" in [t for t, *_ in found["queries"]["glosary"]]


@pytest.mark.parametrize("q", ["results", "check several", "check a hypothesis"])
def test_old_names_lead_to_hypotheses(found, q):
    (t, h), = top(found, q)
    assert h == "#/hypotheses"


def test_results_says_where_it_went(found):
    t, h, k, where = found["queries"]["results"][0]
    # the old name leads to the answers on the Hypotheses page (the feature is called Answers since 0.17.0)
    assert h == "#/hypotheses" and (t == "Answers" or "Answers" in where)


def test_profile_old_name_leads_to_by_document(found):
    t, h, k, where = found["queries"]["profile"][0]
    assert h == "#/profile" and "By document" in where


def test_nonsense_finds_nothing(found):
    assert found["queries"]["xyzzyq"] == []


def test_finder_js_exports_and_search_row():
    src = (STATIC / "finder.js").read_text()
    assert "export function openFinder(" in src and "export function finderBox(" in src
    assert "Search the documents for" in src and "href: searchHref(q)," in src   # the link is lib.js's own
    for aria in ('role: "combobox"', 'role: "listbox"', 'role: "option"', "aria-activedescendant", 'aria-modal'):
        assert aria in src


def test_finder_index_has_no_imports():
    src = (STATIC / "finder-index.js").read_text()
    assert not [l for l in src.splitlines() if l.startswith("import ")]
    assert "export function buildIndex(" in src and "export function findFeatures(" in src


def test_the_changelog_is_found(found):
    # after 0.17.2 what is new is read only when asked: Find goes to Settings › Technical, where it opens
    for q in ("changelog", "what's new"):
        assert top(found, q) == [("Read what's new in this version", "#/settings/updates")]
