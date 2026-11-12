"""0.17.0: the person mark's initials and its name where it stands alone (docs/DESIGN.md 4.10, 5.5).

lib.js builds the DOM, so Node runs it here with the stand-in document of tests/_fakedom.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from _fakedom import NODE, STATIC, run

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(not NODE, reason="node is not installed")

PROBE = r"""
const { personMark, initials } = await import(LIB);
const out = {};
out.initials = Object.fromEntries(["Anna de Vries", "Ludwig van Beethoven", "Rui da Costa", "Ben Okafor", "Cleo",
  "  Ábel  Gergő ", "you", "a colleague", ""].map((n) => [n, initials(n)]));
const m = (p, o) => { const e = personMark(p, o); return { shown: e.textContent, label: e.getAttribute("aria-label"), title: e.getAttribute("title") }; };
out.marks = {
  initials: m(["Anna de Vries"]), several: m(["you", "Anna de Vries", "Ben Okafor"]), role: m(["Anna de Vries"], { role: "Owner" }),
  short: m(["Anna de Vries"], { name: "short" }), full: m(["Anna de Vries"], { name: "full" }),
  by: m(["Anna de Vries"], { name: "short", prefix: "By" }), changedByYou: m(["you"], { name: "short", prefix: "Changed by" }),
  youAndAnna: m(["you", "Anna de Vries"], { name: "short" }), unknown: m(["a colleague"]),
  unknownAlone: m(["a colleague"], { name: "short" }), unknownBy: m(["a colleague"], { name: "short", prefix: "Changed by" }),
};
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    return run(PROBE, tmp_path_factory.mktemp("probe"))


def test_initials_take_the_first_and_the_last_word(probe):
    i = probe["initials"]
    # a particle (de, van, da) never counts
    assert i["Anna de Vries"] == "AV"
    assert i["Ludwig van Beethoven"] == "LB"
    assert i["Rui da Costa"] == "RC"
    assert i["Ben Okafor"] == "BO"
    # one word: one letter; accents kept; a person not known: none
    assert i["Cleo"] == "C"
    assert i["  Ábel  Gergő "] == "ÁG"
    assert i["you"] == i["a colleague"] == i[""] == ""


def test_a_person_mark_shows_initials_and_its_tooltip_names_in_full(probe):
    m = probe["marks"]
    assert m["initials"]["shown"] == "AV"
    assert m["initials"]["label"] == m["initials"]["title"] == "Anna de Vries"
    assert m["several"]["shown"] == "You · AV · BO"
    assert m["several"]["label"] == "You, Anna de Vries and Ben Okafor"
    assert m["role"]["shown"] == "AVOwner"            # the role after a dot (drawn by CSS)
    assert m["role"]["label"] == "Anna de Vries (Owner)"
    # a colleague not known: the icon alone, the words still its name
    assert m["unknown"]["shown"] == ""
    assert m["unknown"]["label"] == "A colleague"


def test_a_person_mark_that_stands_alone_shows_the_name(probe):
    m = probe["marks"]
    assert m["short"]["shown"] == "Anna"
    assert m["full"]["shown"] == "Anna de Vries"
    # what they did is said on the mark too; the tooltip keeps the full name
    assert m["by"]["shown"] == "By Anna"
    assert m["by"]["label"] == "By Anna de Vries"
    assert m["changedByYou"]["shown"] == "Changed by you"
    assert m["youAndAnna"]["shown"] == "You and Anna"
    # a colleague whose name is not known stays whole: never "A" or "Changed by a"
    assert m["unknownAlone"]["shown"] == "A colleague"
    assert m["unknownBy"]["shown"] == "Changed by a colleague"
    for k in ("short", "full"):
        assert m[k]["label"] == "Anna de Vries"


def test_the_guide_and_the_reference_page_say_so():
    guide = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
    assert "*Anna de Vries* is *AV*" in guide
    assert 'name: "short"' in guide and 'name: "full"' in guide
    ref = (STATIC / "views" / "design.js").read_text(encoding="utf-8")
    assert 'name: "short"' in ref and 'name: "full"' in ref
