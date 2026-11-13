"""Relations found from the text (0.18.1, roadmap D2, Level 0: no model).

Links between concepts are proposed from the sentences themselves, only between terms the glossary already knows (two
mentions in `term_mentions` in one sentence), by the words between them:

    X such as Y (, Z and W)          X broader than Y (and Z, W)
    Y (, Z) and other X / or other X X broader than Y (and Z)
    X, also called Y / X (also known as Y) / X, i.e. Y          the same
    X leads to / causes / reduces / increases / results in Y      X has an effect on Y
    X instead of Y                   X replaces Y

**English only**, in this release (the manual says so). A pattern inside quotation marks (someone's words being
quoted, a title) is passed by, and so is a sentence where the two terms are not joined by the connecting words alone
(anything else between them, beyond an article). Each proposal is a row of `concept_links` with source `pattern`,
never confirmed until a person accepts it, as links from search by meaning are; its sentences (each with its document
and page) are kept in `concept_link_sentences`, so the Concepts page shows why it was proposed. Theory documents
(docrole.py) are not read: the glossary leaves them out, so their terms have no mentions here.

Rebuilt with the glossary (terms.build calls `find`), like the abbreviation links: a person's decisions on the pairs
(`reviews`, item kind `concept_link`) are kept, by the pair.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict

from .store import now
from .textutil import split_sentences

SOURCE = "pattern"
MAX_SENTENCES = 5   # kept per proposal
_ART = r"(?:(?:the|a|an)\s+)?"
_MODAL = r"(?:(?:can|could|may|might|will|would|often|usually|also|in\s+turn)\s+)?"
# the words between X and Y (both terms), and the relation from X to Y
_BETWEEN = [
    (re.compile(rf"^\s*,?\s*such\s+as\s+{_ART}$", re.I), "broader"),
    (re.compile(rf"^\s*,?\s+(?:and|or)\s+other\s+$", re.I), "narrower"),   # "Y and other X": Y narrower than X
    (re.compile(rf"^\s*,\s*(?:also\s+(?:called|known\s+as)|i\.\s?e\.,?|that\s+is,?|or\s+simply)\s+{_ART}$", re.I), "same"),
    (re.compile(rf"^\s*\(\s*(?:also\s+(?:called|known\s+as)|a\.k\.a\.?|i\.\s?e\.,?)\s+{_ART}$", re.I), "same"),
    (re.compile(rf"^\s+{_MODAL}(?:leads?|led|leading)\s+to\s+{_ART}$", re.I), "effect"),
    (re.compile(rf"^\s+{_MODAL}(?:causes?|caused|causing|reduces?|reduced|reducing|increases?|increased|increasing|"
                rf"raises?|raised|lowers?|lowered|improves?|improved|worsens?|worsened|results?\s+in|resulted\s+in)\s+"
                rf"{_ART}$", re.I), "effect"),
    (re.compile(rf"^\s+instead\s+of\s+{_ART}$", re.I), "replaces"),
]
_LIST = re.compile(r"^\s*(?:,|,?\s+(?:and|or))\s+(?:(?:the|a|an)\s+)?$", re.I)   # between the items of a list
_QUOTES = "\"“”«»„"
LANGUAGES = ("en",)


def _inside_quotes(sentence: str, at: int) -> bool:
    """Whether position `at` of a sentence is inside quotation marks (an odd number of quote marks before it)."""
    return sum(sentence[:at].count(q) for q in _QUOTES) % 2 == 1


def _pairs(text: str, ms: list[tuple[int, int, str]]) -> list[tuple[str, str, str]]:
    """The relations one sentence states between its terms' mentions (`ms`: (start, end, term) in sentence offsets):
    [(a, b, relation from a to b)]. The glossary's terms overlap ("heat pumps", "heat pumps instead"), so the first term
    of a pair is the longest one ending at a place, and the second the longest one starting at a place."""
    ends: dict[int, tuple[int, int, str]] = {}
    starts: dict[int, tuple[int, int, str]] = {}
    for m in ms:
        if m[1] not in ends or m[0] < ends[m[1]][0]:
            ends[m[1]] = m
        if m[0] not in starts or m[1] > starts[m[0]][1]:
            starts[m[0]] = m
    firsts = sorted(ends.values(), key=lambda m: m[1])
    seconds = sorted(starts.values())

    def after(pos: int) -> list[tuple[int, int, str]]:
        return [m for m in seconds if m[0] >= pos and m[0] - pos <= 40]

    def before(pos: int) -> list[tuple[int, int, str]]:
        return [m for m in firsts if m[1] <= pos and pos - m[1] <= 40]

    out = []
    for s1, e1, t1 in firsts:
        for s2, e2, t2 in after(e1):
            gap = text[e1:s2]
            if "." in gap.replace("i.e.", "").replace("i. e.", "").replace("a.k.a.", ""):
                continue
            for rx, rel in _BETWEEN:
                if not rx.match(gap) or _inside_quotes(text, e1) or _inside_quotes(text, s2):
                    continue
                if rel == "same" and "(" in gap and ")" not in text[e2:e2 + 3]:
                    continue
                out.append((t1, t2, rel))
                if rel == "broader":      # X such as Y, Z and W: each item of the list
                    last = e2
                    while True:
                        nxt = next((m for m in after(last) if _LIST.match(text[last:m[0]])), None)
                        if nxt is None:
                            break
                        out.append((t1, nxt[2], "broader"))
                        last = nxt[1]
                if rel == "narrower":     # A, B and other X: each item before
                    first = s1
                    while True:
                        prv = next((m for m in reversed(before(first)) if re.match(r"^\s*,\s*$", text[m[1]:first])), None)
                        if prv is None:
                            break
                        out.append((prv[2], t2, "narrower"))
                        first = prv[0]
                break
    return list(dict.fromkeys((a, b, r) for a, b, r in out if a != b))


_INV = {"broader": "narrower", "narrower": "broader", "effect": "effect_of", "effect_of": "effect",
        "replaces": "replaced_by", "replaced_by": "replaces"}


def find(cx: sqlite3.Connection) -> int:
    """Propose the links the sentences state, anew (source `pattern`): returns how many pairs. Run in the glossary's
    build transaction, after its mentions are written."""
    cx.execute("DELETE FROM concept_links WHERE source=?", (SOURCE,))
    try:
        cx.execute("DELETE FROM concept_link_sentences")
    except sqlite3.OperationalError:   # a database without the table (opened by an older schema)
        return 0
    by_passage: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    for tid, pid, a, z in cx.execute("SELECT term_id, passage_id, start, end FROM term_mentions"):
        by_passage[pid].append((a, z, tid))
    found: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for pid, ms in by_passage.items():
        if len(ms) < 2:
            continue
        row = cx.execute("SELECT doc_id, page, start, text FROM passages WHERE passage_id=?", (pid,)).fetchone()
        if row is None:
            continue
        doc, page, p0, text = row
        for sa, sz in split_sentences(text):
            inside = [(a - p0 - sa, z - p0 - sa, t) for a, z, t in ms if sa <= a - p0 and z - p0 <= sz]
            if len(inside) < 2:
                continue
            sent = text[sa:sz]
            for a, b, rel in _pairs(sent, inside):
                if a > b:   # stored from the smaller id, the relation turned round with it (terms.set_link)
                    a, b, rel = b, a, _INV.get(rel, rel)
                found[(a, b, rel)].append({"passage_id": pid, "doc_id": doc, "page": page, "start": p0 + sa,
                                           "end": p0 + sz, "quote": " ".join(sent.split())})
    # a pair stated with two relations: the one stated most often (ties: the first by name)
    best: dict[tuple[str, str], tuple[str, list[dict]]] = {}
    for (a, b, rel), ss in sorted(found.items()):
        if (a, b) not in best or len(ss) > len(best[(a, b)][1]):
            best[(a, b)] = (rel, ss)
    at = now()
    for (a, b), (rel, ss) in best.items():
        if cx.execute("SELECT 1 FROM concept_links WHERE a=? AND b=? AND source != ?", (a, b, SOURCE)).fetchone():
            # the pair has a link already (a person's, an abbreviation, the AI's, search by meaning's): a person's
            # decision is kept by the pair, so a second link of it would take that decision too (review 8)
            continue
        ss = ss[:MAX_SENTENCES]
        cx.execute("INSERT OR REPLACE INTO concept_links VALUES (?,?,?,?,?,?,?,?,?)",
                   (a, b, rel, SOURCE, round(min(0.5, 0.2 + 0.1 * len(ss)), 2), ss[0]["quote"],
                    ss[1]["quote"] if len(ss) > 1 else None, None, at))
        cx.executemany("INSERT OR REPLACE INTO concept_link_sentences(a, b, passage_id, doc_id, page, start, end, quote) "
                       "VALUES (?,?,?,?,?,?,?,?)", [(a, b, s["passage_id"], s["doc_id"], s["page"], s["start"],
                                                     s["end"], s["quote"]) for s in ss])
    return len(best)


def sentences(cx: sqlite3.Connection, a: str, b: str) -> list[dict]:
    """The sentences a proposed link was found in: [{"doc_id", "title", "page", "start", "end", "quote"}]."""
    a, b = sorted((a, b))
    try:
        rows = cx.execute("SELECT s.doc_id, d.title, s.page, s.start, s.end, s.quote FROM concept_link_sentences s "
                          "LEFT JOIN documents d ON d.doc_id=s.doc_id WHERE s.a=? AND s.b=? ORDER BY s.doc_id, s.start",
                          (a, b)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [{"doc_id": r[0], "title": r[1] or "", "page": r[2], "start": r[3], "end": r[4], "quote": r[5]} for r in rows]


def as_json(cx: sqlite3.Connection, a: str, b: str) -> str:
    return json.dumps(sentences(cx, a, b))
