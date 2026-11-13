"""A codebook from a theory document (0.18.1, roadmap K2 part 2, Level 0: no model).

A third way to start in the codebook editor, beside *Start fresh* and *From the themes*: *From a theory document*. The
codes are the theory's own concepts (from Meadows: stock, flow, reinforcing loop, delay, leverage point…), each with a
**definition quoted from the theory, with its page**, so the codebook says where each code comes from. Its examples
come **only from the evidence documents** (never from a theory document), offered by keyword match and kept only when
the researcher ticks them: the labeller then learns what a reinforcing loop looks like in a care home, not in Meadows'
fishery.

The candidates, from the document's own structure and words, best first:

1. **defined in the text**: "a stock is …", "X is defined as …", "by X we mean …", "X refers to …", "we call this X",
   "X (also called Y) is …": the term and the sentence that defines it, quoted;
2. **headings**: short headings (at most five words, numbering taken off: "2.3 Stocks and flows" gives "Stocks and
   flows"), with the first sentence under them as the definition;
3. **frequent phrases**: words and two- or three-word phrases the document uses often (stop words left out at both
   ends), with the first sentence that uses each as the definition.

Every quote is a span of the document's own text (checked by finding it again, as quotes are everywhere). Words set in
italics are not offered: the readers do not keep fonts' slant (only boldness). The optional AI draft of the roadmap
(Level 2 or 3) is not built yet.
"""
from __future__ import annotations

import re
from collections import Counter

from .store import Workspace
from .textutil import split_sentences

MAX_TERM_WORDS = 4
MAX_CANDIDATES = 40
MAX_EXAMPLES = 3
_W = r"[A-Za-zÀ-ÖØ-öø-ÿ][\w'’-]*"
_TERM = rf"((?:{_W}\s+){{0,{MAX_TERM_WORDS - 1}}}{_W})"
# a term at the start of a sentence (an article before it allowed), then the defining words
_DEFINES = [
    re.compile(rf"^(?:(?:A|An|The)\s+)?{_TERM}\s+(?:is|are)\s+(?:defined\s+as|understood\s+as)\s+", re.I),
    re.compile(rf"^(?:(?:A|An|The)\s+)?{_TERM}\s+(?:refers?|refer)\s+to\s+", re.I),
    re.compile(rf"^(?:(?:A|An|The)\s+)?{_TERM}\s+(?:is|are)\s+(?:a|an|the)\s+", re.I),
    re.compile(rf"\bby\s+(?:(?:a|an|the)\s+)?{_TERM},?\s+(?:we|I)\s+mean\b", re.I),
    re.compile(rf"\b(?:we|I)\s+call\s+(?:this|these|it|them|such\s+\w+)\s+(?:(?:a|an|the)\s+)?{_TERM}\b", re.I),
    re.compile(rf"^(?:(?:A|An|The)\s+)?{_TERM}\s*\((?:also\s+(?:called|known\s+as)|or)\s+[^)]{{1,60}}\)\s+(?:is|are)\s+",
               re.I),
]
_NUMBERING = re.compile(r"^\s*(?:(?:chapter|part|section)\s+)?(?:\d+(?:\.\d+)*\.?|[IVXLC]+\.)\s+", re.I)


def _stop() -> frozenset[str]:
    from .stopwords import ENGLISH, STOPWORDS_V1

    return frozenset(STOPWORDS_V1 | ENGLISH | {"chapter", "section", "figure", "table", "example", "page", "part"})


def _norm(term: str) -> str:
    t = term.lower().strip(" .,:;'\"’()")
    return t[:-1] if len(t) > 4 and t.endswith("s") and not t.endswith("ss") else t


def _clean_term(term: str, stop: frozenset[str]) -> str | None:
    words = term.strip(" .,:;'\"’()").split()
    while words and words[0].lower() in stop:
        words = words[1:]
    while words and words[-1].lower() in stop:
        words = words[:-1]
    if not words or len(words) > MAX_TERM_WORDS or all(w.lower() in stop for w in words):
        return None
    t = " ".join(words)
    return t if 3 <= len(t) <= 60 and not t.isdigit() else None


def _page(ws: Workspace, doc_id: str, at: int) -> int | None:
    r = ws.query("SELECT page FROM pages WHERE doc_id=? AND start<=? AND ?<end", (doc_id, at, at))
    return r[0]["page"] if r else None


def _quote(ws: Workspace, doc_id: str, text: str, a: int, z: int) -> dict:
    q = " ".join(text[a:z].split())
    return {"quote": q, "start": a, "end": z, "page": _page(ws, doc_id, a)}


def _body_sentences(ws: Workspace, doc_id: str, text: str) -> list[tuple[int, int]]:
    """The sentences of the document's body passages (what the reader counts as its text), in order."""
    out: list[tuple[int, int]] = []
    for a, z in ws.query("SELECT start, end FROM passages WHERE doc_id=? AND section='body' ORDER BY start", (doc_id,)):
        # a heading and the paragraph under it share a passage: a sentence never runs over a line break, so "A stock
        # is …" starts its own sentence after the heading "1. Stocks and flows"
        at = a
        for line in re.split(r"(\n+)", text[a:z]):
            if line.strip() and not line.startswith("\n"):
                out += split_sentences(line, at)
            at += len(line)
    return out


def candidates(ws: Workspace, doc_id: str, limit: int = MAX_CANDIDATES) -> dict:
    """The candidate concepts of a theory document as draft codes: {"doc_id", "title", "role", "concepts": [{"term",
    "how" ("defined" | "heading" | "frequent"), "count", "definition": {"quote", "start", "end", "page"} | None,
    "code": {code, description, described, group, keywords, include, exclude, examples: []}, "suggested":
    [examples from the evidence documents, to tick]}]}."""
    row = ws.query("SELECT title, text, role FROM documents WHERE doc_id=?", (doc_id,))
    if not row:
        raise KeyError(doc_id)
    title, text, role = row[0]["title"] or "", row[0]["text"] or "", row[0]["role"]
    stop = _stop()
    sents = _body_sentences(ws, doc_id, text)
    found: dict[str, dict] = {}

    def add(term: str | None, how: str, span: tuple[int, int] | None) -> None:
        if not term:
            return
        k = _norm(term)
        if k in found:
            if found[k]["definition"] is None and span:
                found[k]["definition"] = _quote(ws, doc_id, text, *span)
            return
        found[k] = {"term": term[0].upper() + term[1:] if term[:1].islower() else term, "how": how,
                    "definition": _quote(ws, doc_id, text, *span) if span else None}

    # 1. defined in the text
    for a, z in sents:
        s = text[a:z].strip()
        lead = len(text[a:z]) - len(text[a:z].lstrip())
        for rx in _DEFINES:
            m = rx.search(s)
            if m:
                t = _clean_term(m.group(1), stop)
                if t and not (m.start() == 0 and t.split()[0] in ("It", "This", "That", "There", "Here")):
                    add(t, "defined", (a + lead, z))
                break
    # 2. headings, with the first sentence under each
    starts = [x[0] for x in sents]
    for r in ws.query("SELECT start, end, text FROM headings WHERE doc_id=? ORDER BY start", (doc_id,)):
        h = _NUMBERING.sub("", " ".join((r["text"] or text[r["start"]:r["end"]]).split()))
        if not h or len(h.split()) > 5 or h.isupper() and len(h) > 40:
            continue
        t = _clean_term(h, stop)
        nxt = next((i for i, st in enumerate(starts) if st >= r["end"]), None)
        add(t, "heading", sents[nxt] if nxt is not None else None)
    # 3. frequent words and phrases (in at least three sentences)
    grams: Counter = Counter()
    first: dict[str, tuple[str, tuple[int, int]]] = {}
    for a, z in sents:
        words = re.findall(_W, text[a:z])
        seen_here = set()
        for n in (1, 2, 3):
            for i in range(len(words) - n + 1):
                g = words[i:i + n]
                if g[0].lower() in stop or g[-1].lower() in stop or any(len(w) < 3 for w in g):
                    continue
                k = _norm(" ".join(g))
                if k in seen_here:
                    continue
                seen_here.add(k)
                grams[k] += 1
                first.setdefault(k, (" ".join(g), (a, z)))
    # a phrase counts over the words it is made of: "feedback loop" beats "feedback" when it is nearly as frequent
    for k, n in sorted(((k, n) for k, n in grams.items() if n >= 3),
                       key=lambda x: (-x[1] * (1 + 0.6 * x[0].count(" ")), x[0])):
        if len(found) >= limit * 2:
            break
        if any(k != o and k in o.split() and grams[o] >= 0.6 * n for o in grams if " " in o and o.count(" ") > k.count(" ")):
            continue
        term, span = first[k]
        add(_clean_term(term.lower() if not term.isupper() else term, stop), "frequent", span)
    for k, c in found.items():
        c["count"] = grams.get(k, 0)
    order = {"defined": 0, "heading": 1, "frequent": 2}
    picked = sorted(found.values(), key=lambda c: (order[c["how"]], -c["count"], c["term"].lower()))[:limit]
    out = []
    for c in picked:
        d = c["definition"]
        page = f", p. {d['page']}" if d and d.get("page") else ""
        desc = f"“{d['quote']}” ({title}{page})" if d else f"A concept of {title}."
        out.append({**c, "code": {"code": c["term"][:40], "description": desc[:2000], "described": bool(d), "group": "",
                                  "keywords": [c["term"].lower()], "include": "", "exclude": "", "examples": []},
                    "suggested": suggest_examples(ws, c["term"])})
    return {"doc_id": doc_id, "title": title, "role": role, "concepts": out}


def suggest_examples(ws: Workspace, term: str, k: int = MAX_EXAMPLES) -> list[dict]:
    """Up to `k` sentences of the evidence documents that use the term (its words, by keyword), to offer as examples:
    never from a theory document. Each {"quote", "doc_id", "title", "page", "start", "end", "project"}."""
    from .docrole import theory_docs
    from .search import rank_passages

    theory = theory_docs(ws._conn())
    words = [w.lower() for w in re.findall(_W, term)]
    if not words:
        return []
    try:
        found = rank_passages(ws, term, words, k=k * 3, per_doc=1, require_terms=True, evidence_only=True)
    except Exception:  # noqa: BLE001 - no index yet: nothing to offer
        return []
    out = []
    rx = re.compile(r"\b" + r"\W+".join(re.escape(w) for w in words), re.I)
    for p in found:
        if p["doc_id"] in theory:
            continue
        r = ws.query("SELECT p.page, p.start, p.text, d.title FROM passages p JOIN documents d ON d.doc_id=p.doc_id "
                     "WHERE p.passage_id=?", (p["passage_id"],))
        if not r:
            continue
        t = r[0]["text"]
        m = rx.search(t)
        if not m:
            continue
        a, z = next(((a, z) for a, z in split_sentences(t) if a <= m.start() < z), (0, len(t)))
        out.append({"quote": " ".join(t[a:z].split())[:400], "doc_id": p["doc_id"], "title": r[0]["title"],
                    "page": r[0]["page"], "start": r[0]["start"] + a, "end": r[0]["start"] + z,
                    "project": ws.project_uid()})
        if len(out) >= k:
            break
    return out


def keep_evidence_examples(ws: Workspace, codes: list[dict]) -> list[dict]:
    """The codes a person kept, with any example from a theory document taken out (the rule of K2: examples come only
    from the evidence)."""
    from .docrole import theory_docs

    theory = theory_docs(ws._conn())
    out = []
    for c in codes:
        if not isinstance(c, dict):
            continue
        ex = [e for e in (c.get("examples") or []) if isinstance(e, dict) and e.get("doc_id") not in theory]
        out.append({**c, "examples": ex})
    return out
