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
import threading
from bisect import bisect_left, bisect_right
from collections import Counter, OrderedDict
from dataclasses import dataclass

from .search import passage_index
from .store import Workspace
from .textutil import is_stop, token_spans, tokens

MODES = ("any", "all", "phrase", "near")
SORTS = ("doc", "left", "right")
MAX_GAP = 3          # stop words allowed between the words of a phrase
WINDOW = 5           # words on each side counted for collocates
PAGE = 200           # lines per page
CHUNK = 2000         # candidate passages read at a time (0.16)


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
            # the phrase's own stop word is required where it is written (0.14.3: it used to be optional, and a
            # phrase starting with one matched twice)
            if j < len(toks) and toks[j][3] == w:
                j += 1
                first = False
                continue
            return None
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


def _hits_in(text: str, query: Query, rare: tuple[str, str] | None,
             toks: list | None = None) -> list[tuple[int, int, list[tuple[int, int]]]]:
    """(start, end, marks) of every hit in one passage text; marks are other query words to highlight nearby.
    `toks`: the text's words with stop words (`token_spans(text, keep_stop=True)`), when already split."""
    if toks is None:
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
        # words typed beside a quoted phrase are required in the passage (0.14.3: they were ignored)
        if want and not want <= {keyof(t) for t in toks}:
            return []
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


EXPORT_MAX = 50000  # lines of one export

# The hits of the last few searches, so another page or another sort of a search is a slice of them instead of every
# candidate passage read and split into words again. Keyed by the index's state (`search._key`: a change of the
# documents or their titles is another key) and everything the hits depend on; a search with a code filter is not
# kept (a code's passages change without the documents changing). A hit takes about 300 bytes (its place, its marks,
# and its place in each sort asked for), so HITS_KEPT bounds this at about 90 MB (a search with more is not kept).
SEARCHES_KEPT = 4
HITS_KEPT = 300_000
_KEPT: "OrderedDict[tuple, dict]" = OrderedDict()
_KEPT_LOCK = threading.Lock()


def _words_left(text: str, a: int) -> list[str]:
    t = text[max(0, a - 80):a]
    return [w for _s, _e, _st, w in reversed(token_spans(t, keep_stop=True))][:3]


def _words_right(text: str, b: int) -> list[str]:
    t = text[b:b + 80]
    return [w for _s, _e, _st, w in token_spans(t, keep_stop=True)][:3]


def _sort_words(idx, found: list[tuple], sort: str) -> list[list[str]]:
    """The words beside each hit that a sort by the left or right context sorts by, from its passage read again."""
    out: list[list[str]] = []
    for k in range(0, len(found), CHUNK):
        part = found[k:k + CHUNK]
        rows = idx.read([h[0] for h in part])
        out.extend(_words_left(r["text"], h[1]) if sort == "left" else _words_right(r["text"], h[2])
                   for h, r in zip(part, rows))
    return out


def search(ws: Workspace, q: str, mode: str = "any", docs: list[str] | None = None, sort: str = "doc",
           offset: int = 0, limit: int | None = PAGE, exact: bool = False, near: int = 5, width: int = 60,
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
    ck = None if code or idx.key is None else (idx.key, q, mode, bool(exact), query.near,
                                               tuple(sorted(allowed_docs)) if allowed_docs is not None else None)
    with _KEPT_LOCK:
        kept = _KEPT.get(ck) if ck is not None else None
        if kept is not None:
            _KEPT.move_to_end(ck)
    if kept is None:
        kept = _search_hits(ws, idx, query, mode, allowed_docs, code, sort)
        if ck is not None and len(kept["found"]) <= HITS_KEPT:
            with _KEPT_LOCK:
                _KEPT[ck] = kept
                while len(_KEPT) > SEARCHES_KEPT or sum(len(v["found"]) for v in _KEPT.values()) > HITS_KEPT:
                    _KEPT.popitem(last=False)
    rare, per_doc = kept["rare"], kept["per_doc"]
    found = kept["sorted"].get(sort)
    if found is None:   # another sort of a search kept: its hits sorted again (stable, from the order found in)
        base = kept["found"]
        if sort == "doc":
            found = sorted(base, key=lambda h: (h[5].lower(), h[4], h[6], h[1]))
        else:
            words = kept["words"].pop(sort, None) or _sort_words(idx, base, sort)   # not kept once sorted by
            found = [base[n] for n in sorted(range(len(base)), key=lambda n: (words[n], base[n][7], base[n][1]))]
        kept["sorted"][sort] = found
    # a page of lines; `limit` None gives every hit at once, for the export (0.11.1: it ran the whole search once per
    # thousand lines), at most EXPORT_MAX
    offset = max(0, int(offset))
    limit = EXPORT_MAX if limit is None else max(1, min(int(limit), 1000))
    page = found[offset:offset + limit]
    from .claimcheck import locate

    page_rows = idx.read([h[0] for h in page])
    where = locate(ws, [(n, r["passage_id"], (r["start"] or 0) + h[1]) for n, (h, r) in enumerate(zip(page, page_rows))])
    lines = []
    for n, ((i, a, b, marks, *_rest), r) in enumerate(zip(page, page_rows)):
        left, right = _context(r["text"], a, b, width)
        base = a - len(left)  # marks as offsets into left + node + right
        rel = [(ma - base, mb - base) for ma, mb in marks if a - len(left) <= ma and mb <= b + len(right)
               and r["text"][ma:mb] and (ma < a or ma >= b)]
        lines.append({"n": offset + n + 1, "doc_id": r["doc_id"], "title": r["title"] or "", "passage_id": r["passage_id"],
                      "page": r["page"], "location": (where.get(n) or {}).get("location") or "",
                      "section": r.get("section") or "body",
                      "left": left, "node": re.sub(r"\s", " ", r["text"][a:b]), "right": right, "marks": rel,
                      "start": (r["start"] or 0) + a, "end": (r["start"] or 0) + b})
    if "other_forms" not in kept:
        kept["other_forms"] = [] if exact else other_forms(idx, query)
    return {"query": q, "mode": mode, "exact": bool(exact), "near": query.near, "sort": sort,
            "words": [w for _s, w in query.words] + [" ".join(w for _s, w in ph) for ph in query.phrases],
            "other_forms": [dict(x) for x in kept["other_forms"]], "rarest": rare[1] if rare else None,
            "total": len(found), "passages": kept["passages"],
            "documents": len(per_doc), "per_doc": [dict(d) for d in per_doc], "lines": lines, "offset": offset,
            "limit": limit}


def _search_hits(ws: Workspace, idx, query: Query, mode: str, allowed_docs: set | None, code: str | None,
                 sort: str) -> dict:
    """Every hit of a search, in the order found, with the counts per document: what `search` keeps of a search.
    0.16 (H2): each candidate passage is read once, in chunks, and what the counts and the sorting need is kept with
    its hits: (row index, start, end, marks, doc_id, title, seq, passage_id); the words a sort by the left or right
    context sorts by are taken then for the sort asked for, the other's when it is asked for."""
    allowed_passages = _code_passages(ws, code)
    rare = _rarest(idx, query) if mode == "all" else None
    found: list[tuple] = []
    words: list[list[str]] = []
    cands = [i for i in _candidates(idx, query)
             if (allowed_docs is None or idx.doc_of[i] in allowed_docs)
             and (allowed_passages is None or idx.ids[i] in allowed_passages)]
    for k in range(0, len(cands), CHUNK):
        chunk = cands[k:k + CHUNK]
        for i, r in zip(chunk, idx.read(chunk)):
            for a, b, marks in _hits_in(r["text"], query, rare):
                if sort == "left":
                    words.append(_words_left(r["text"], a))
                elif sort == "right":
                    words.append(_words_right(r["text"], b))
                found.append((i, a, b, marks, r["doc_id"], r["title"] or "", r["seq"], r["passage_id"]))
    per: dict[str, dict] = {}
    for h in found:
        d = per.setdefault(h[4], {"doc_id": h[4], "title": h[5], "hits": 0, "_p": set()})
        d["hits"] += 1
        d["_p"].add(h[7])
    per_doc = sorted(({**{k: v for k, v in d.items() if k != "_p"}, "passages": len(d["_p"])} for d in per.values()),
                     key=lambda d: (-d["hits"], d["title"].lower()))
    return {"found": found, "rare": rare, "per_doc": per_doc, "passages": len({h[7] for h in found}),
            "sorted": {}, "words": {sort: words} if sort != "doc" else {}}


def other_forms(idx, query: Query, n: int = 8) -> list[dict]:
    """Words of the documents that share the beginning of a searched word but are not found by it ("commuters" for
    "commuting": the stemmer keeps -er nouns apart), so a person can add them. [{word, count}], most frequent first."""
    post = idx.bm25.postings
    out: dict[str, int] = {}
    for st, _w in list(query.words) + [x for ph in query.phrases for x in ph]:
        if len(st) < 4 or is_stop(st):
            continue
        for other, total in idx.terms_starting(st):   # 0.16: the words of the index that start so, not all of them
            if other != st and len(other) - len(st) <= 4 and not any(c.isdigit() for c in other):
                out[other] = out.get(other, 0) + total
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
    # the baseline is the passages searched: with a document or code filter the nearby words are compared with that
    # part of the corpus, not the whole of it (0.14.3), or the list would just be the filtered document's vocabulary
    scope: set[int] | None = None
    if allowed_docs is not None or allowed_passages is not None:
        scope = {i for i, (pid, doc) in enumerate(zip(idx.ids, idx.doc_of))
                 if (allowed_docs is None or doc in allowed_docs)
                 and (allowed_passages is None or pid in allowed_passages)}
    cands = [i for i in _candidates(idx, query) if scope is None or i in scope]
    for r in (r for k in range(0, len(cands), CHUNK) for r in idx.read(cands[k:k + CHUNK])):
        every = token_spans(r["text"], keep_stop=True)
        found = _hits_in(r["text"], query, rare, every)
        if not found:
            continue
        # content words only, as the index counts them: the same words `token_spans(text)` gives (0.16: taken from
        # the words already split, and the words beside each hit found by bisection, not by reading them all)
        toks = [t for t in every if not is_stop(t[3])]
        ends = [t[1] for t in toks]
        starts = [t[0] for t in toks]
        for a, b, _m in found:
            hits += 1
            i = bisect_right(ends, a)
            j = bisect_left(starts, b)
            # the words end and start in order (a word's place never comes before the one before it), so those
            # ending by `a` are the first i and those starting from `b` the rest from j, as the filters found them
            for t in toks[:i][-window:] + toks[j:][:window]:
                window_words += 1
                if t[2] in qstems or any(ch.isdigit() for ch in t[3]):
                    continue
                near_counts[t[2]] += 1
                surface.setdefault(t[2], Counter())[t[3]] += 1
    total = (sum(idx.bm25.lens) if scope is None else sum(idx.bm25.lens[i] for i in scope)) or 1
    # the floor grows with the number of hits, so a word seen 3 times near 16,000 hits does not top the list
    floor = max(min_count, hits // 1000)
    out = []
    for st, c in near_counts.items():
        if c < floor:
            continue
        corpus = idx.total(st) if scope is None else sum(f for i, f in idx.bm25.postings.get(st, ()) if i in scope)
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
                           embedder=embedder, evidence_only=False)  # (0.18.1: the Search page still finds theory)
    where = locate(ws, [(p["passage_id"], p["passage_id"], None) for p in picked])
    stems = set(tokens(q))  # the same words and stemmer as `rank_passages` and its `matched`

    def marks(text: str) -> list[list[int]]:
        """Every word of the passage that the keywords found it by (all its forms), as [start, end] offsets."""
        return [[a, b] for a, b, st, _w in token_spans(text) if st in stems]

    return {"query": q, "mode": "meaning", "passages": [
        {"n": n, "passage_id": p["passage_id"], "doc_id": p["doc_id"], "title": p["title"] or "", "page": p["page"],
         "text": p["text"], "found_by": p["found_by"], "matched": p.get("matched") or [],
         "marks": marks(p["text"]) if p.get("matched") else [],
         "location": (where.get(p["passage_id"]) or {}).get("span") or "", "start": p.get("start")}
        for n, p in enumerate(picked, 1)]}


def table(result: dict) -> list[dict]:
    """The lines as rows for a spreadsheet or CSV."""
    return [{"Document": x["title"], "Where": x["location"], "Left": x["left"], "Words found": x["node"],
             "Right": x["right"], "Passage id (to find it again in ENLENS)": x["passage_id"]} for x in result["lines"]]
