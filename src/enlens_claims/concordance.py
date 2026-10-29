"""Search the corpus and read it as a concordance (F1): every place the words occur, one line per hit.

No model and no hypothesis are needed. Candidate passages come from the keyword index the checker already keeps
(`search.passage_index`): the union of the postings of the query's words, their intersection for all words or a
phrase. Each candidate's text is then read again for the exact positions (`textutil.token_spans`, the same word
rule and stemmer as the index), because the postings hold word counts, not positions.

Modes
- any:    every occurrence of any of the words
- all:    passages that contain every word; one line per occurrence of the rarest of them, the others marked
- phrase: the words in order, with at most MAX_GAP stop words between them ("imports of electrolysers")
- near:   all the words within `near` words of each other, in any order

`exact` switches stemming off: "prices" then finds "prices" only, as a case-insensitive regular expression would.
A quoted part of the query ("…") is searched as a phrase whatever the mode.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .search import passage_index
from .store import Workspace
from .textutil import is_stop, token_spans

MODES = ("any", "all", "phrase", "near")
SORTS = ("doc", "left", "right")
MAX_GAP = 3          # stop words allowed between the words of a phrase
WINDOW = 5           # words on each side counted for collocates
PAGE = 200           # lines per page


@dataclass
class Query:
    words: list[tuple[str, str]]          # (stem, word) of each word to find, in order
    phrases: list[list[tuple[str, str]]]  # quoted parts: each a phrase
    mode: str
    exact: bool
    near: int

    def key(self, w: tuple[str, str]) -> str:
        return w[1] if self.exact else w[0]


def parse(q: str, mode: str = "any", exact: bool = False, near: int = 5) -> Query:
    """The words of a query. Stop words are dropped except inside quotes, where they may be part of a phrase."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}.")
    q = " ".join((q or "").split())
    if len(q) > 500:
        raise ValueError("Keep the search under 500 characters.")
    phrases = []
    for m in re.finditer(r"[\"“”„]([^\"“”„]+)[\"“”„]", q):
        ws = [(st, w) for _a, _b, st, w in token_spans(m.group(1), keep_stop=True)]
        if any(not is_stop(w) for _s, w in ws):
            phrases.append(ws)
    rest = re.sub(r"[\"“”„][^\"“”„]+[\"“”„]", " ", q)
    words = [(st, w) for _a, _b, st, w in token_spans(rest)]
    if mode == "phrase" and words and not phrases:
        phrases = [[(st, w) for _a, _b, st, w in token_spans(rest, keep_stop=True)]]
        words = []
    if not words and not phrases:
        # only stop words: search them as they are (a full scan; rare)
        words = [(st, w) for _a, _b, st, w in token_spans(rest, keep_stop=True)]
    if not words and not phrases:
        raise ValueError("Type a word to search for.")
    return Query(words, phrases, mode, bool(exact), max(1, min(int(near or 5), 50)))


def _candidates(idx, query: Query) -> list[int]:
    """Passage indexes that may hold hits, from the postings (a superset; positions are checked afterwards)."""
    post = idx.bm25.postings

    def having(stem: str) -> set[int] | None:
        if is_stop(stem):
            return None  # not in the index: every passage is a candidate
        return {i for i, _f in post.get(stem, ())}

    groups: list[set[int] | None] = []
    for ph in query.phrases:
        sets = [having(st) for st, w in ph if not is_stop(w)]
        known = [x for x in sets if x is not None]
        groups.append(set.intersection(*known) if known else None)
    single = [having(st) for st, _w in query.words]
    everything = set(range(len(idx.rows)))
    if query.mode in ("all", "near"):
        sets = [g if g is not None else everything for g in groups + single]
        return sorted(set.intersection(*sets)) if sets else []
    out: set[int] = set()
    for g in groups + single:
        out |= g if g is not None else everything
    return sorted(out)


def _phrase_at(toks, i: int, ph, query: Query) -> int | None:
    """End index (inclusive) of the phrase starting at token i, or None. Stop words of the phrase must match
    exactly where they are written; other stop words (up to MAX_GAP) may stand between its words."""
    j = i
    first = True
    for st, w in ph:
        if is_stop(w):
            if j < len(toks) and toks[j][3] == w:
                j += 1
                first = False
            continue
        gap = 0
        while not first and j < len(toks) and is_stop(toks[j][3]) and toks[j][3] != w and gap < MAX_GAP:
            j += 1
            gap += 1
        if j >= len(toks):
            return None
        if (toks[j][3] if query.exact else toks[j][2]) != (w if query.exact else st):
            return None
        j += 1
        first = False
    return j - 1


def _hits_in(text: str, query: Query, rare: tuple[str, str] | None) -> list[tuple[int, int, list[tuple[int, int]]]]:
    """(start, end, marks) of every hit in one passage text; marks are other query words to highlight nearby."""
    toks = token_spans(text, keep_stop=True)
    if not toks:
        return []
    k = query.key
    want = {k(w) for w in query.words}
    keyof = (lambda t: t[3]) if query.exact else (lambda t: t[2])
    hits: list[tuple[int, int, list[tuple[int, int]]]] = []
    phrase_hits = []
    for ph in query.phrases:
        for i in range(len(toks)):
            end = _phrase_at(toks, i, ph, query)
            if end is not None:
                phrase_hits.append((i, end))
    if query.mode == "any":
        for i, t in enumerate(toks):
            if keyof(t) in want:
                hits.append((t[0], t[1], []))
        hits += [(toks[a][0], toks[b][1], []) for a, b in phrase_hits]
    elif query.mode == "phrase":
        hits += [(toks[a][0], toks[b][1], []) for a, b in phrase_hits]
    elif query.mode == "all":
        present = {keyof(t) for t in toks}
        if not want <= present or (query.phrases and not phrase_hits):
            return []
        marks = [(t[0], t[1]) for t in toks if keyof(t) in want] + [(toks[a][0], toks[b][1]) for a, b in phrase_hits]
        if rare is not None:
            anchor = k(rare)
            for t in toks:
                if keyof(t) == anchor:
                    hits.append((t[0], t[1], [m for m in marks if m != (t[0], t[1])]))
        else:  # a phrase alone is the anchor
            for a, b in phrase_hits:
                span = (toks[a][0], toks[b][1])
                hits.append((*span, [m for m in marks if m != span]))
    elif query.mode == "near":
        # each needed item: a word (token positions) or a phrase (start positions)
        items: list[list[tuple[int, int]]] = []
        for w in query.words:
            items.append([(i, i) for i, t in enumerate(toks) if keyof(t) == k(w)])
        for ph in query.phrases:
            items.append([(a, b) for a, b in phrase_hits if _phrase_at(toks, a, ph, query) == b])
        if not items or any(not x for x in items):
            return []
        seen = set()
        for a0, b0 in items[0]:
            lo, hi = a0, b0
            ok = True
            for other in items[1:]:
                best = min(other, key=lambda ab: max(abs(ab[0] - b0), abs(a0 - ab[1])))
                if max(abs(best[0] - b0), abs(a0 - best[1])) > query.near:
                    ok = False
                    break
                lo, hi = min(lo, best[0]), max(hi, best[1])
            if ok and (lo, hi) not in seen:
                seen.add((lo, hi))
                inner = [(toks[x][0], toks[x][1]) for x in range(lo, hi + 1) if keyof(toks[x]) in want]
                hits.append((toks[lo][0], toks[hi][1], inner))
    hits.sort()
    return hits


def _rarest(idx, query: Query) -> tuple[str, str] | None:
    if not query.words:
        return None
    post = idx.bm25.postings
    return min(query.words, key=lambda w: (len(post.get(w[0], ())) if not is_stop(w[1]) else 10 ** 9, w[0]))


def _context(text: str, a: int, b: int, width: int) -> tuple[str, str]:
    """Up to `width` characters left of a and right of b, cut at word boundaries, on one line."""
    left = text[max(0, a - width):a]
    if a - width > 0:
        m = re.search(r"\s", left)
        left = left[m.end():] if m else left
    right = text[b:b + width]
    if b + width < len(text):
        m = re.search(r"\s\S*$", right)
        right = right[:m.start()] if m else right
    # line breaks become spaces, one for one, so offsets into the line stay offsets into the text
    return re.sub(r"\s", " ", left), re.sub(r"\s", " ", right)


def _code_passages(ws: Workspace, code: str | None) -> set[str] | None:
    """Passages labelled with a code (F2), as `framework:code`; None for no filter."""
    if not code:
        return None
    from . import profile

    fw, _, c = code.partition(":")
    if not c:
        fw, c = "sdg", fw
    return profile.passages_with_code(ws, fw, c)


def search(ws: Workspace, q: str, mode: str = "any", docs: list[str] | None = None, sort: str = "doc",
           offset: int = 0, limit: int = PAGE, exact: bool = False, near: int = 5, width: int = 60,
           all_sections: bool = False, code: str | None = None) -> dict:
    """Every hit of the query in the project: counts per document first, then one page of lines.

    Returns {"query", "mode", "words", "total", "passages", "documents", "per_doc": [{doc_id, title, hits,
    passages}], "lines": [{n, doc_id, title, passage_id, page, location, left, node, right, marks, start, end}],
    "offset", "limit"}. `start`/`end` are document offsets of the node (the words found), for opening the document
    at them; `marks` are other query words in the line, as offsets into left + node + right.
    """
    if sort not in SORTS:
        raise ValueError(f"sort must be one of {', '.join(SORTS)}.")
    query = parse(q, mode, exact, near)
    idx = passage_index(ws, all_sections=all_sections)
    allowed_docs = set(docs) if docs else None
    allowed_passages = _code_passages(ws, code)
    rare = _rarest(idx, query) if mode == "all" else None
    found: list[tuple] = []   # (row index, start, end, marks)
    for i in _candidates(idx, query):
        r = idx.rows[i]
        if allowed_docs is not None and r["doc_id"] not in allowed_docs:
            continue
        if allowed_passages is not None and r["passage_id"] not in allowed_passages:
            continue
        for a, b, marks in _hits_in(r["text"], query, rare):
            found.append((i, a, b, marks))
    per: dict[str, dict] = {}
    for i, a, _b, _m in found:
        r = idx.rows[i]
        d = per.setdefault(r["doc_id"], {"doc_id": r["doc_id"], "title": r["title"] or "", "hits": 0, "_p": set()})
        d["hits"] += 1
        d["_p"].add(r["passage_id"])
    per_doc = sorted(({**{k: v for k, v in d.items() if k != "_p"}, "passages": len(d["_p"])} for d in per.values()),
                     key=lambda d: (-d["hits"], d["title"].lower()))

    def words_left(i, a):
        t = idx.rows[i]["text"][max(0, a - 80):a]
        return [w for _s, _e, _st, w in reversed(token_spans(t, keep_stop=True))][:3]

    def words_right(i, b):
        t = idx.rows[i]["text"][b:b + 80]
        return [w for _s, _e, _st, w in token_spans(t, keep_stop=True)][:3]

    if sort == "doc":
        found.sort(key=lambda h: ((idx.rows[h[0]]["title"] or "").lower(), idx.rows[h[0]]["doc_id"],
                                  idx.rows[h[0]]["seq"], h[1]))
    elif sort == "left":
        found.sort(key=lambda h: (words_left(h[0], h[1]), idx.rows[h[0]]["passage_id"], h[1]))
    else:
        found.sort(key=lambda h: (words_right(h[0], h[2]), idx.rows[h[0]]["passage_id"], h[1]))
    offset, limit = max(0, int(offset)), max(1, min(int(limit), 1000))
    page = found[offset:offset + limit]
    from .claimcheck import locate

    where = locate(ws, [(n, idx.rows[i]["passage_id"], (idx.rows[i]["start"] or 0) + a)
                        for n, (i, a, _b, _m) in enumerate(page)])
    lines = []
    for n, (i, a, b, marks) in enumerate(page):
        r = idx.rows[i]
        left, right = _context(r["text"], a, b, width)
        base = a - len(left)  # marks as offsets into left + node + right
        rel = [(ma - base, mb - base) for ma, mb in marks if a - len(left) <= ma and mb <= b + len(right)
               and r["text"][ma:mb] and (ma < a or ma >= b)]
        lines.append({"n": offset + n + 1, "doc_id": r["doc_id"], "title": r["title"] or "", "passage_id": r["passage_id"],
                      "page": r["page"], "location": (where.get(n) or {}).get("location") or "",
                      "section": r.get("section") or "body",
                      "left": left, "node": re.sub(r"\s", " ", r["text"][a:b]), "right": right, "marks": rel,
                      "start": (r["start"] or 0) + a, "end": (r["start"] or 0) + b})
    return {"query": q, "mode": mode, "exact": bool(exact), "near": query.near, "sort": sort,
            "words": [w for _s, w in query.words] + [" ".join(w for _s, w in ph) for ph in query.phrases],
            "other_forms": [] if exact else other_forms(idx, query), "rarest": rare[1] if rare else None,
            "total": len(found), "passages": len({idx.rows[h[0]]["passage_id"] for h in found}),
            "documents": len(per_doc), "per_doc": per_doc, "lines": lines, "offset": offset, "limit": limit}


def other_forms(idx, query: Query, n: int = 8) -> list[dict]:
    """Words of the documents that share the beginning of a searched word but are not found by it ("commuters" for
    "commuting": the stemmer keeps -er nouns apart), so a person can add them. [{word, count}], most frequent first."""
    post = idx.bm25.postings
    out: dict[str, int] = {}
    for st, _w in list(query.words) + [x for ph in query.phrases for x in ph]:
        if len(st) < 4 or is_stop(st):
            continue
        for other, plist in post.items():
            if other != st and other.startswith(st) and len(other) - len(st) <= 4 and not any(c.isdigit() for c in other):
                out[other] = out.get(other, 0) + sum(f for _i, f in plist)
    forms = []
    for st, c in sorted(out.items(), key=lambda x: (-x[1], x[0]))[:n]:
        word = st
        for i, _f in post.get(st, ())[:1]:
            for _a, _b, s2, w in token_spans(idx.rows[i]["text"]):
                if s2 == st:
                    word = w
                    break
        forms.append({"word": word, "count": c})
    return forms


def collocates(ws: Workspace, q: str, mode: str = "any", docs: list[str] | None = None, exact: bool = False,
               near: int = 5, all_sections: bool = False, window: int = WINDOW, min_count: int = 3, n: int = 40,
               code: str | None = None, order: str = "typical") -> dict:
    """The words that occur within `window` words of the hits, ranked against their frequency in the corpus by
    pointwise mutual information (log2 of observed over expected), counting only words seen at least `min_count`
    times near a hit. The counts come from the hits and the index's postings; nothing is stored.

    Returns {"words": [{word, stem, count, corpus, pmi}], "hits", "window_words", "min_count"}: the floor is
    `min_count`, or one in a thousand hits when that is more."""
    query = parse(q, mode, exact, near)
    idx = passage_index(ws, all_sections=all_sections)
    allowed_docs = set(docs) if docs else None
    allowed_passages = _code_passages(ws, code)
    rare = _rarest(idx, query) if mode == "all" else None
    qstems = {st for st, _w in query.words} | {st for ph in query.phrases for st, _w in ph}
    near_counts: Counter[str] = Counter()
    surface: dict[str, Counter] = {}
    hits = 0
    window_words = 0
    for i in _candidates(idx, query):
        r = idx.rows[i]
        if allowed_docs is not None and r["doc_id"] not in allowed_docs:
            continue
        if allowed_passages is not None and r["passage_id"] not in allowed_passages:
            continue
        found = _hits_in(r["text"], query, rare)
        if not found:
            continue
        toks = token_spans(r["text"])  # content words only, as the index counts them
        for a, b, _m in found:
            hits += 1
            left = [t for t in toks if t[1] <= a][-window:]
            right = [t for t in toks if t[0] >= b][:window]
            for t in left + right:
                window_words += 1
                if t[2] in qstems or any(ch.isdigit() for ch in t[3]):
                    continue
                near_counts[t[2]] += 1
                surface.setdefault(t[2], Counter())[t[3]] += 1
    total = sum(idx.bm25.lens) or 1
    # the floor grows with the number of hits, so a word seen 3 times near 16,000 hits does not top the list
    floor = max(min_count, hits // 1000)
    out = []
    for st, c in near_counts.items():
        if c < floor:
            continue
        corpus = sum(f for _i, f in idx.bm25.postings.get(st, ()))
        if not corpus:
            continue
        expected = corpus * window_words / total
        pmi = math.log2(c / expected) if expected > 0 else 0.0
        out.append({"word": surface[st].most_common(1)[0][0], "stem": st, "count": c, "corpus": corpus,
                    "pmi": round(pmi, 2)})
    if order == "often":
        out.sort(key=lambda x: (-x["count"], -x["pmi"], x["word"]))
    else:
        out.sort(key=lambda x: (-x["pmi"], -x["count"], x["word"]))
    return {"query": q, "hits": hits, "window": window, "order": order, "window_words": window_words, "min_count": floor,
            "words": out[:max(1, n)]}


def meaning(ws: Workspace, q: str, embedder, k: int = 20, docs: list[str] | None = None) -> dict:
    """Search by meaning: whole passages ranked by keyword and meaning together (`search.rank_passages`)."""
    from .claimcheck import locate
    from .search import rank_passages

    q = " ".join((q or "").split())
    if len(q) < 2:
        raise ValueError("Type a word to search for.")
    picked = rank_passages(ws, q, k=max(1, min(int(k), 100)), per_doc=max(1, min(int(k), 100)), doc_ids=docs,
                           embedder=embedder)
    where = locate(ws, [(p["passage_id"], p["passage_id"], None) for p in picked])
    return {"query": q, "mode": "meaning", "passages": [
        {"n": n, "passage_id": p["passage_id"], "doc_id": p["doc_id"], "title": p["title"] or "", "page": p["page"],
         "text": p["text"], "found_by": p["found_by"], "matched": p.get("matched") or [],
         "location": (where.get(p["passage_id"]) or {}).get("span") or "", "start": p.get("start")}
        for n, p in enumerate(picked, 1)]}


def table(result: dict) -> list[dict]:
    """The lines as rows for a spreadsheet or CSV."""
    return [{"Document": x["title"], "Where": x["location"], "Left": x["left"], "Words found": x["node"],
             "Right": x["right"], "Passage id (to find it again in ENLENS)": x["passage_id"]} for x in result["lines"]]
