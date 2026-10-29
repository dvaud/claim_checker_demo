"""Find the passages that bear on a hypothesis: keyword ranking (BM25), optionally fused with semantic search.

The keyword index of a project is built once per corpus state and kept in memory (a few projects at a time),
shared by all threads. With embeddings (see embed.py) the keyword and the semantic rankings are fused by
reciprocal rank fusion, which needs no tuning of score scales: a passage ranked high by either method rises.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass

from .retrieve import BM25
from .store import Workspace
from .textutil import tokens

RRF_K = 60          # reciprocal rank fusion constant (the usual value)
DEPTH = 200         # how far down each ranking is read before fusing


@dataclass
class PassageIndex:
    rows: list[dict]
    bm25: BM25
    pos: dict[str, int]


_INDEXES: "OrderedDict[tuple, PassageIndex]" = OrderedDict()
_LOCK = threading.Lock()
_BUILDING: dict[tuple, threading.Lock] = {}
MAX_CACHED = 4


def _key(ws: Workspace, all_sections: bool = False) -> tuple:
    row = ws.query("SELECT COUNT(*), MAX(rowid) FROM passages")[0]
    return (str(ws.db_path.resolve()), ws.corpus_version(), row[0], row[1], bool(all_sections))


def passage_index(ws: Workspace, all_sections: bool = False) -> PassageIndex:
    """Readable passages of the project and their keyword index (built on first use, then cached).

    With `all_sections` (0.7, for the concordance's "include reference lists and front matter"), every passage,
    whatever its section; the default is the body text, which is all the checker and the SDG pack ever read."""
    key = _key(ws, all_sections)
    with _LOCK:
        hit = _INDEXES.get(key)
        if hit is not None:
            _INDEXES.move_to_end(key)
            return hit
        build_lock = _BUILDING.setdefault(key, threading.Lock())
    with build_lock:  # two requests for the same new index build it once
        with _LOCK:
            hit = _INDEXES.get(key)
        if hit is not None:
            return hit
        rows = [dict(r) for r in ws.query(
            "SELECT p.passage_id, p.doc_id, p.seq, p.page, p.text, d.title, p.start, p.section FROM passages p "
            "JOIN documents d ON d.doc_id=p.doc_id" + ("" if all_sections else " WHERE p.section='body'") +
            " ORDER BY p.passage_id")]
        idx = PassageIndex(rows, BM25([tokens(r["text"]) for r in rows]), {r["passage_id"]: i for i, r in enumerate(rows)})
        with _LOCK:
            for k in [k for k in _INDEXES if k[0] == key[0] and k[-1] == key[-1]]:  # older states of the project
                del _INDEXES[k]
            _INDEXES[key] = idx
            while len(_INDEXES) > MAX_CACHED:
                _INDEXES.popitem(last=False)
            _BUILDING.pop(key, None)
        return idx


RERANK_POOL = 3   # the second pass re-sorts the best 3 × k candidates


def lexical_score(claim_tokens: list[str], idf: dict[str, float], text: str) -> float:
    """How closely a passage words the claim, from 0 to 1, without a model: the best sentence's coverage of the
    claim's distinct words weighted by how rare they are (idf), and how many adjacent word pairs of the claim the
    passage has side by side (phrases)."""
    from .textutil import split_sentences

    distinct = list(dict.fromkeys(claim_tokens))
    if not distinct:
        return 0.0
    weight = {t: idf.get(t, 1.0) for t in distinct}
    total = sum(weight.values()) or 1.0
    best = 0.0
    for a, b in split_sentences(text) or [(0, len(text))]:
        have = set(tokens(text[a:b]))
        best = max(best, sum(w for t, w in weight.items() if t in have) / total)
    pairs = {(x, y) for x, y in zip(claim_tokens, claim_tokens[1:]) if x != y}
    if pairs:
        toks = tokens(text)
        phrase = len(pairs & set(zip(toks, toks[1:]))) / len(pairs)
    else:
        phrase = 0.0
    return 0.75 * best + 0.25 * phrase


def rerank(idx: "PassageIndex", query_text: str, ranked: list[tuple[int, float]], k: int) -> list[tuple[int, float]]:
    """The second sorting pass (no model): the best RERANK_POOL × k candidates sorted again by `lexical_score`,
    in steps of 0.1 so passages that word the claim about equally well keep the order of the first ranking."""
    pool = ranked[:RERANK_POOL * k]
    q = tokens(query_text)
    keyed = [(-round(lexical_score(q, idx.bm25.idf, idx.rows[i]["text"]), 1), pos, (i, s))
             for pos, (i, s) in enumerate(pool)]
    return [x for _l, _p, x in sorted(keyed)] + ranked[RERANK_POOL * k:]


def rank_passages(ws: Workspace, query_text: str, terms: list[str] | None = None, k: int = 8, per_doc: int = 2,
                  doc_ids: list[str] | None = None, exclude: set[str] | None = None, embedder=None,
                  require_terms: bool = False, second_pass: bool = False) -> list[dict]:
    """The k passages that best match the claim and its search terms, at most `per_doc` from one document first.

    With `require_terms`, only passages containing at least one of the terms qualify (a search with other words a
    person typed should find those words, not more of the claim's own). With `second_pass`, the best candidates
    are sorted again by how closely they word the claim (`rerank`); the hypothesis checker uses it, the SDG pack
    never does.
    Each row carries `score` (BM25, or the fused score) and `found_by`: "keywords", "meaning" or "both", and (0.7)
    `matched`: the words of the passage that it shares with the claim and its search terms, as the passage writes
    them (empty for a passage found by meaning alone).
    """
    idx = passage_index(ws)
    rows = idx.rows
    if not rows:
        return []
    allowed = set(doc_ids) if doc_ids else None
    skip = exclude or set()
    having = None
    if require_terms:
        having = set(idx.bm25.sparse(tokens(" ".join(terms or []))))  # every passage containing one of them

    def ok(i: int) -> bool:
        r = rows[i]
        return ((allowed is None or r["doc_id"] in allowed) and r["passage_id"] not in skip
                and (having is None or i in having))

    q = tokens(query_text) * 2 + tokens(" ".join(terms or []))  # the claim's own words count double
    lexical = [(i, s) for i, s in sorted(idx.bm25.sparse(q, weighted=True).items(), key=lambda x: (-x[1], x[0]))
               if s > 0 and ok(i)][:DEPTH]
    semantic: list[tuple[int, float]] = []
    if embedder is not None:
        from . import embed

        vs = embed.vectors(ws, embedder.model)
        if vs is not None:
            sims = vs.similarities(embed.query_vector(embedder, query_text))
            cand = [(idx.pos[pid], s) for pid, s in zip(vs.ids, sims) if pid in idx.pos]
            semantic = sorted((c for c in cand if ok(c[0])), key=lambda x: (-x[1], x[0]))[:DEPTH]
    if semantic:
        fused: dict[int, float] = {}
        for ranking in (lexical, semantic):
            for rank, (i, _s) in enumerate(ranking):
                fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + rank + 1)
        ranked = [(i, s) for i, s in sorted(fused.items(), key=lambda x: (-x[1], x[0]))]
        lex_set, sem_set = {i for i, _ in lexical}, {i for i, _ in semantic}
    else:
        ranked = lexical
        lex_set, sem_set = {i for i, _ in lexical}, set()
    ranked = ranked[: max(k * 8, 60)]
    if second_pass:
        ranked = rerank(idx, query_text, ranked, k)
    picked: list[int] = []
    count: dict[str, int] = {}
    for i, _s in ranked:
        if len(picked) >= k:
            break
        d = rows[i]["doc_id"]
        if count.get(d, 0) < per_doc:
            picked.append(i)
            count[d] = count.get(d, 0) + 1
    chosen = set(picked)
    for i, _s in ranked:
        if len(picked) >= k:
            break
        if i not in chosen:
            picked.append(i)
            chosen.add(i)
    score = dict(ranked)
    qstems = set(q)
    out = []
    for i in picked:
        found = "both" if (i in lex_set and i in sem_set) else ("meaning" if i in sem_set else "keywords")
        out.append({**rows[i], "score": round(score[i], 4 if semantic else 2), "found_by": found,
                    "matched": shared_words(rows[i]["text"], qstems)})
    return out


def shared_words(text: str, stems: set[str]) -> list[str]:
    """The words of `text` whose stems are among `stems`, as the text writes them (first spelling, in order)."""
    from .textutil import token_spans

    seen: dict[str, str] = {}
    for _a, _b, st, w in token_spans(text):
        if st in stems and st not in seen:
            seen[st] = w
    return list(seen.values())


def docs_matching(ws: Workspace, query_text: str, terms: list[str] | None, doc_ids: set[str]) -> set[str]:
    """Which of these documents have a readable passage that shares a word with the claim or its search words
    (one keyword query, nothing is read by a model)."""
    if not doc_ids:
        return set()
    idx = passage_index(ws)
    q = tokens(query_text) + tokens(" ".join(terms or []))
    return {idx.rows[i]["doc_id"] for i, sc in idx.bm25.sparse(q).items() if sc > 0 and idx.rows[i]["doc_id"] in doc_ids}


def neighbours(ws: Workspace, passage_id: str, before: int = 1, after: int = 1) -> dict:
    """A passage with the passages around it, to read a quote in context."""
    row = ws.query("SELECT p.*, d.title FROM passages p JOIN documents d ON d.doc_id=p.doc_id WHERE p.passage_id=?",
                   (passage_id,))
    if not row:
        raise KeyError(passage_id)
    p = dict(row[0])
    around = ws.query("SELECT passage_id, seq, page, start, end, text, section FROM passages WHERE doc_id=? AND seq "
                      "BETWEEN ? AND ? ORDER BY seq", (p["doc_id"], p["seq"] - before, p["seq"] + after))
    from .claimcheck import _breaks

    br = _breaks(ws, [(r["passage_id"], p["doc_id"], r["start"], r["end"]) for r in around])
    return {"passage_id": passage_id, "doc_id": p["doc_id"], "title": p["title"], "page": p["page"],
            "passages": [{"passage_id": r["passage_id"], "page": r["page"], "text": r["text"], "section": r["section"],
                          "current": r["passage_id"] == passage_id, "start": r["start"],
                          "breaks": br.get(r["passage_id"], [])} for r in around]}
