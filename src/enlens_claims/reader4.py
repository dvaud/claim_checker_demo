"""Reader 4 (ENLENS 0.17.2): what it reads otherwise than reader 3.

`reader.read_blocks(raw, version=4)` calls the rule here; `version=3` still reads exactly as ENLENS 0.15.1 to 0.17.1
did. Reader 4 also reads Word files otherwise (`ingest._read_docx`): text in content controls and custom XML, and a
table inside a table's cell once. No model is used.

**A text file with one paragraph per line** (what Word saves as "plain text", and many other programs): no blank line
between paragraphs, each paragraph one long line. Reader 3 started a new paragraph only after a blank line or a short
line that ends a sentence, so such a file became one block: every quote was cited as paragraph 1, and the reading of
one huge block took ever longer. Reader 4 takes each line of such a file as a paragraph of its own.
"""
from __future__ import annotations

from .reader3 import _ENDS_SENTENCE, wrap_width

# longer than any line of text broken into lines of one width (`reader3.wrap_width` gives up above 130 characters)
LONG_LINE = 160


def paragraph_lines(pages) -> bool:
    """In a text file whose paragraphs are one line each, every line starts a paragraph (`Line.blank_before`).

    Such a file: its lines are not hard-wrapped to one width; lines longer than any wrap hold most of its text; and
    where such a long line runs straight on into the next one (no blank line between), it mostly ends a sentence,
    which a hard-wrapped line seldom does. Returns whether the file is one."""
    lines = [ln for p in pages for ln in p if ln.top is None and not ln.furniture and ln.text.strip()]
    if not lines or wrap_width(lines) is not None:
        return False
    total = sum(len(ln.text.strip()) for ln in lines)
    long_chars = sum(len(ln.text.strip()) for ln in lines if len(ln.text.strip()) > LONG_LINE)
    if long_chars < 0.5 * total:
        return False
    run_on = []  # long lines a line follows without a blank line between
    for p in pages:
        for a, b in zip(p, p[1:]):
            if (a.top is None and b.top is None and not a.furniture and not b.furniture and not b.blank_before
                    and len(a.text.strip()) > LONG_LINE):
                run_on.append(a.text.strip())
    if len(run_on) < 2 or sum(1 for t in run_on if _ENDS_SENTENCE.search(t)) < 0.6 * len(run_on):
        return False
    for ln in lines:
        ln.blank_before = True
    return True
