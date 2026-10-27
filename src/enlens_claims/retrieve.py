"""BM25 ranking over passages, plus the heuristic passage screen."""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Sequence

from .store import Workspace
from .taxonomy import targets
from .textutil import tokens


class BM25:
    def __init__(self, docs: Sequence[Sequence[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = [Counter(d) for d in docs]
        self.lens = [len(d) for d in docs]
        self.avg = (sum(self.lens) / len(self.lens)) if self.lens else 0.0
        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def score(self, query: Sequence[str]) -> list[float]:
        q = Counter(query)
        out = []
        for d, ln in zip(self.docs, self.lens):
            s = 0.0
            for t in q:
                f = d.get(t)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * ln / (self.avg or 1))
                s += self.idf.get(t, 0.0) * f * (self.k1 + 1) / denom
            out.append(s)
        return out

    def top(self, query: Sequence[str], k: int) -> list[tuple[int, float]]:
        sc = self.score(query)
        ranked = sorted(range(len(sc)), key=lambda i: -sc[i])
        return [(i, sc[i]) for i in ranked[:k] if sc[i] > 0]


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
    thr = ws.config["thresholds"]["screen_min_score"] if min_score is None else min_score
    tq = [tokens(t.description) for t in targets().values()]
    with ws.connect() as cx:
        rows = list(cx.execute("SELECT passage_id, doc_id, text, section FROM passages"))
        doc_h2: Counter[str] = Counter()
        for r in rows:
            if H2_RE.search(r["text"]):
                doc_h2[r["doc_id"]] += 1
        bm = BM25([tokens(r["text"]) for r in rows]) if rows else None
        # best match of each passage against any SDG target description, scaled to 0..2
        best = [0.0] * len(rows)
        if bm:
            for q in tq:
                for i, s in enumerate(bm.score(q)):
                    if s > best[i]:
                        best[i] = s
        n_in = 0
        for i, r in enumerate(rows):
            if r["section"] != "body":
                cx.execute("UPDATE passages SET screen_score=0, screened=0 WHERE passage_id=?", (r["passage_id"],))
                continue
            text = r["text"]
            h2 = 1.5 if H2_RE.search(text) else (0.5 if doc_h2[r["doc_id"]] >= 3 else 0.0)
            impact = min(3, len(set(m.group(1).lower()[:6] for m in IMPACT_RE.finditer(text)))) * 0.5
            sdg = 2 * best[i] / (best[i] + 8) if best[i] > 0 else 0.0
            score = round(h2 + impact + sdg, 3)
            ok = int(score >= thr and h2 > 0)
            n_in += ok
            cx.execute("UPDATE passages SET screen_score=?, screened=? WHERE passage_id=?", (score, ok, r["passage_id"]))
    return {"passages": len(rows), "screened_in": n_in}
