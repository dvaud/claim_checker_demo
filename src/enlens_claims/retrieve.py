"""BM25 ranking over passages, plus the heuristic passage screen of the SDG / value chain pack."""
from __future__ import annotations

import heapq
import math
import re
from collections import Counter
from typing import Sequence

from .store import Workspace
from .textutil import tokens_v1


class BM25:
    """Okapi BM25 over an inverted index: a query only touches the passages that contain its terms.

    `weighted=False` (the default, as in 0.4) counts each query term once however often it occurs in the query;
    `weighted=True` multiplies a term's contribution by its count in the query, so repeating words gives them weight.
    """

    def __init__(self, docs: Sequence[Sequence[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.lens: list[int] = []
        postings: dict[str, list[tuple[int, int]]] = {}
        for i, d in enumerate(docs):
            self.lens.append(len(d))
            for t, f in Counter(d).items():
                postings.setdefault(t, []).append((i, f))
        n = len(self.lens)
        self.n = n
        self.avg = (sum(self.lens) / n) if n else 0.0
        self.postings = postings
        self.idf = {t: math.log(1 + (n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in postings.items()}
        avg = self.avg or 1
        self._norm = [k1 * (1 - b + b * ln / avg) for ln in self.lens]

    def sparse(self, query: Sequence[str], weighted: bool = False) -> dict[int, float]:
        """Scores of the passages that share at least one term with the query (others score 0)."""
        out: dict[int, float] = {}
        k1p1, norm = self.k1 + 1, self._norm
        for t, qf in Counter(query).items():
            plist = self.postings.get(t)
            if not plist:
                continue
            idf, m = self.idf[t], (qf if weighted else 1)
            for i, f in plist:  # same operation order as 0.4, so unweighted scores are bit-identical
                out[i] = out.get(i, 0.0) + idf * f * k1p1 / (f + norm[i]) * m
        return out

    def score(self, query: Sequence[str], weighted: bool = False) -> list[float]:
        dense = [0.0] * self.n
        for i, s in self.sparse(query, weighted).items():
            dense[i] = s
        return dense

    def top(self, query: Sequence[str], k: int, weighted: bool = False) -> list[tuple[int, float]]:
        """The k best (index, score) pairs with a score above 0; ties go to the earlier passage."""
        sp = self.sparse(query, weighted)
        best = heapq.nlargest(k, sp.items(), key=lambda x: (x[1], -x[0]))
        return [(i, s) for i, s in best if s > 0]


# ---------------------------------------------------------------------------------------------
# heuristic screen: stands in for a fast decision model (see the manual) until one is benchmarked
# ---------------------------------------------------------------------------------------------
H2_RE = re.compile(r"hydrogen|\bh2\b|electroly[sz]|electrolyser|electrolyzer|ammonia|fuel[- ]cell|e-?fuel|power[- ]to[- ]x|\bptx\b|methanol", re.I)
IMPACT_RE = re.compile(
    r"\b(increas|decreas|reduc|risk|benefit|impact|effect|improv|threat|opportunit|job|employ|income|poverty|wage|"
    r"salar|water|land|emission|pollut|health|safety|conflict|inequal|gender|women|communit|local|export|import|"
    r"price|cost|access|infrastructur|biodivers|food|agricultur|fertili|displac|resettl|human rights|labou?r|"
    r"skill|education|training|corruption|governance|depend|sovereign|electrification|energy security|"
    r"desalinat|scarc|stress|ecosystem|marine|ocean|waste|recycl|mineral|mining|tax|revenue|gdp|growth|"
    r"partnership|technology transfer|capacity|investment|financ|subsid|policy|regulat)\w*", re.I)


def screen(ws: Workspace, min_score: float | None = None) -> dict[str, int]:
    from .taxonomy import targets

    thr = ws.config["thresholds"]["screen_min_score"] if min_score is None else min_score
    rows = ws.query("SELECT passage_id, doc_id, text, section FROM passages")
    doc_h2: Counter[str] = Counter()
    has_h2 = [bool(H2_RE.search(r["text"])) for r in rows]
    for r, h in zip(rows, has_h2):
        if h:
            doc_h2[r["doc_id"]] += 1
    # best match of each passage against any SDG target description, scaled to 0..2
    best = [0.0] * len(rows)
    if rows:
        bm = BM25([tokens_v1(r["text"]) for r in rows])
        for t in targets().values():
            for i, s in bm.sparse(tokens_v1(t.description)).items():
                if s > best[i]:
                    best[i] = s
    updates = []
    n_in = 0
    for i, r in enumerate(rows):
        if r["section"] != "body":
            updates.append((0, 0, r["passage_id"]))
            continue
        text = r["text"]
        h2 = 1.5 if has_h2[i] else (0.5 if doc_h2[r["doc_id"]] >= 3 else 0.0)
        impact = min(3, len(set(m.group(1).lower()[:6] for m in IMPACT_RE.finditer(text)))) * 0.5
        sdg = 2 * best[i] / (best[i] + 8) if best[i] > 0 else 0.0
        score = round(h2 + impact + sdg, 3)
        ok = int(score >= thr and h2 > 0)
        n_in += ok
        updates.append((score, ok, r["passage_id"]))
    with ws.connect() as cx:
        cx.executemany("UPDATE passages SET screen_score=?, screened=? WHERE passage_id=?", updates)
    return {"passages": len(rows), "screened_in": n_in}
