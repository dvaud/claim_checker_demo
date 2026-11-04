"""0.13.2: the result page, finished: a short heading of the document above its paragraph instead of a sentence of
context, "Not counted" and the certainty as two facts, a document on two sides counted once, a source line that never
starts with "·", a selection across the window's "…", the cards drawn again when the width crosses 600 px, and the
"Ask another AI model" card saying what has happened first."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"
JS = (STATIC / "views" / "result.js").read_text()
NODE = shutil.which("node")


def _node(script: str, tmp_path: Path):
    f = tmp_path / "t.js"
    f.write_text(script)
    return json.loads(subprocess.run([NODE, str(f)], capture_output=True, text=True, check=True).stdout)


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_a_short_heading_that_opens_a_paragraph_is_shown_as_a_heading(tmp_path):
    # the pattern windowNode uses, run on paragraph starts
    pattern = re.search(r"const m = (/\^.*?/u)\.exec\(t\.textContent\);", JS).group(1)
    starts = {
        "heading": "Recommendations. Employers can make the most of remote work.",
        "two_words": "Services to citizens. Citizens did not report longer waiting times.",
        "sentence": "The municipality closed one of its three office buildings.",
        "long": "Remote work lowers commuting emissions for most workers. More text.",
        "lower": "e.g. this is not a heading.",
    }
    out = _node(f"""
const re = {pattern};
const starts = {json.dumps(starts)};
const out = {{}};
for (const [k, t] of Object.entries(starts)) {{ const m = re.exec(t); out[k] = m ? m[1] : null; }}
console.log(JSON.stringify(out));""", tmp_path)
    assert out["heading"] == "Recommendations."
    assert out["two_words"] == "Services to citizens."
    assert out["sentence"] is None and out["long"] is None and out["lower"] is None
    # only where a paragraph starts, never when the line opens with the quote itself, and drawn above its paragraph
    assert "const paraStart = (i) => i > 0 || a === 0" in JS and "t.nodeType !== 3" in JS
    assert 'h("span", { class: "runin" }, m[1])' in JS
    css = (STATIC / "v012.css").read_text()
    assert re.search(r"\.result \.ev \.passage \.runin \{ display: block;", css)


def test_an_uncounted_card_says_not_counted_then_its_certainty():
    head = JS[JS.index("    const top = h(\"div\", { class: \"ev-top\" });"):JS.index("    card.appendChild(top);")]
    # "Not counted" first, then the same "Certainty: …" label every card has (no "Not counted · certainty: low")
    assert '"Not counted")]);\n      if (p.verdict && word) append(top, [fact(`Certainty: ${word}`' in head
    assert "not counted ·" not in head.lower() and "· not counted" not in head.lower()


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_a_document_on_two_sides_counts_once(tmp_path):
    src = re.search(r"  function sidesText\(b\) \{.*?\n  \}\n", JS, re.S).group(0)
    cases = [
        {"docs_counted": 3, "docs_supporting": 3, "docs_refuting": 1},
        {"docs_counted": 2, "docs_supporting": 1, "docs_partly": 1},
        {"docs_counted": 1, "docs_supporting": 1, "docs_partly": 1},
        {"docs_counted": 3, "docs_supporting": 2, "docs_refuting": 2},
        {"docs_counted": 2, "docs_supporting": 2},
    ]
    out = _node(src + f"\nconsole.log(JSON.stringify({json.dumps(cases)}.map(sidesText)));", tmp_path)
    assert out == ["3 documents for, one of them also against", "1 document for, 1 partly for",
                   "1 document for and partly for", "2 documents for, 2 against (3 documents in all)", "2 documents for"]


def test_the_source_line_and_the_selection():
    where = JS[JS.index("  function whereText(p) {"):JS.index("  // the quote's place in the whole document")]
    # the separator is joined to the place on both sides: a line never starts with "·"
    assert where.count("`\\u00a0·\\u00a0${nb(") == 3
    assert "`\\u00a0·\\u00a0also in ${" in JS and 'class: "page also-in"' in JS
    # your judgement in the other part is in the tooltip, not in the line
    assert "In part ${x.part} you judged it" in JS
    # a selection that crosses the "…" the window adds is still text of the excerpt
    assert 'const q = (text || "").replace(/…/g, " ").replace(/\\s+/g, " ").trim();' in JS
    assert '"Use it"' in JS and "Quote another sentence: select it in the excerpt, then" in JS


def test_the_cards_follow_the_width_and_the_models_card_says_what_happened_first():
    assert 'const narrowMq = matchMedia("(max-width: 600px)");' in JS
    assert 'narrowMq.addEventListener("change", onNarrow);' in JS and "if (!box.isConnected) { narrowMq.removeEventListener" in JS
    models = JS[JS.index("  function modelsCard(r, allPassages) {"):JS.index("  // The model's size in plain words")]
    assert "noStronger = h(" in models and models.index("if (noStronger) facts.push(noStronger);") < models.index('h("div", { class: "ask-facts" }, facts)')
    # the split answer: the fact, the rule in its tooltip
    assert '"decides"} the answer.`' in JS and "The hypothesis holds only if every part does" in JS
    assert '"Every matching excerpt has been read."' in JS
