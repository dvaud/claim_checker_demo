"""Paths between two concepts, and a concept over time and across groups (0.18.1, roadmap D3 and D4, Level 0).

**D3. Paths between two concepts.** How the documents get from one concept to another: the shortest chains through a
graph whose nodes are the glossary's concepts (a concept's wordings count as one node) and whose edges are

- the links a person accepted or added (and those the glossary confirmed: abbreviations), at a low cost, and
- co-occurrence in passages, weighted by how much more often than by chance two concepts are mentioned together
  (pointwise mutual information, as `concordance.collocates` weighs words), only when they share at least
  `MIN_TOGETHER` passages and PMI is above zero; the cost of a step falls as PMI rises.

Each step comes with its bridge passages: passages that mention both ends (a link a person accepted with no passage
in common shows the link's own sentences or quotes). A list, not a drawn map (D1, the concept map, is not built).

**D4. A concept over time and across groups.** A concept's wordings and its neighbours (the concepts most often
mentioned with it, by PMI) by publication year (from the bibliography: a document's year is its linked work's; those
without one are counted apart), or between two sets of documents a person picks on the page (not stored).

Theory documents (docrole.py) are left out of both: the glossary leaves them out, and every query here keeps to
evidence documents too, in case the glossary was made before a document was marked.
"""
from __future__ import annotations

import heapq
import math
from collections import Counter, defaultdict
from typing import Iterable

from .store import Workspace

MIN_TOGETHER = 2       # passages two concepts share before co-occurrence joins them
NEIGHBOURS = 25        # the strongest co-occurrence neighbours a node is joined to (the graph stays small)
LINK_COST = 0.5        # a step along an accepted link
MAX_STEPS = 5
BRIDGES = 3            # bridge passages shown per step


class _Graph:
    def __init__(self, ws: Workspace):
        from . import terms
        from .docrole import evidence_sql

        self.ws = ws
        self.ev = evidence_sql("p.doc_id")
        self.group = {r[0]: r[1] for r in ws.query("SELECT term_id, concept_id FROM concept_terms")}
        self.members: dict[str, list[str]] = defaultdict(list)
        for t, c in self.group.items():
            self.members[c].append(t)
        self.labels = {r[0]: r[1] for r in ws.query("SELECT term_id, label FROM terms")}
        for c in list(self.members):
            row = ws.query("SELECT label FROM concepts WHERE concept_id=?", (c,))
            self.labels[c] = row[0][0] if row else self.labels.get(min(self.members[c]), c)
        self.total = int(ws.scalar(f"SELECT COUNT(DISTINCT m.passage_id) FROM term_mentions m JOIN passages p ON "
                                   f"p.passage_id=m.passage_id WHERE {self.ev}") or 1)
        self.links: dict[str, dict[str, dict]] = defaultdict(dict)
        for lk in terms.links(ws):
            rel = lk["relation_effective"]
            if not lk["confirmed"] or rel in (None, "different") or lk["a"] not in self.labels or lk["b"] not in self.labels:
                continue
            a, b = self.node(lk["a"]), self.node(lk["b"])
            if a != b:
                self.links[a][b] = lk
                self.links[b][a] = lk
        self._n: dict[str, int] = {}
        self._nb: dict[str, dict[str, float]] = {}

    def node(self, term: str) -> str:
        return self.group.get(term, term)

    def terms_of(self, node: str) -> list[str]:
        return self.members.get(node) or [node]

    def passages(self, node: str) -> int:
        if node not in self._n:
            ts = self.terms_of(node)
            q = ",".join("?" * len(ts))
            self._n[node] = int(self.ws.scalar(f"SELECT COUNT(DISTINCT m.passage_id) FROM term_mentions m JOIN passages "
                                               f"p ON p.passage_id=m.passage_id WHERE m.term_id IN ({q}) AND {self.ev}",
                                               ts) or 0)
        return self._n[node]

    def neighbours(self, node: str) -> dict[str, float]:
        """{other node: PMI} for the strongest co-occurrence neighbours of a node."""
        if node in self._nb:
            return self._nb[node]
        ts = self.terms_of(node)
        q = ",".join("?" * len(ts))
        together: dict[str, set] = defaultdict(set)
        for tid, pid in self.ws.query(f"SELECT m.term_id, m.passage_id FROM term_mentions m JOIN passages p ON "
                                      f"p.passage_id=m.passage_id WHERE m.passage_id IN (SELECT passage_id FROM "
                                      f"term_mentions WHERE term_id IN ({q})) AND {self.ev}", ts):
            other = self.node(tid)
            if other != node:
                together[other].add(pid)
        n_a = self.passages(node) or 1
        out = {}
        for other, ps in together.items():
            if len(ps) < MIN_TOGETHER:
                continue
            pmi = math.log2(len(ps) * self.total / (n_a * max(1, self.passages(other))))
            if pmi > 0:
                out[other] = pmi
        self._nb[node] = dict(sorted(out.items(), key=lambda x: (-x[1], x[0]))[:NEIGHBOURS])
        return self._nb[node]

    def edges(self, node: str) -> Iterable[tuple[str, float, str]]:
        """(other, cost, kind "link" | "together") from a node."""
        seen = set()
        for other in self.links.get(node, {}):
            seen.add(other)
            yield other, LINK_COST, "link"
        for other, pmi in self.neighbours(node).items():
            if other not in seen:
                yield other, 1.0 / (1.0 + pmi), "together"


def _shortest(g: _Graph, a: str, b: str, banned_edges: set, banned_nodes: set) -> tuple[float, list[str]] | None:
    dist = {a: 0.0}
    prev: dict[str, str] = {}
    heap = [(0.0, a)]
    while heap:
        d, u = heapq.heappop(heap)
        if u == b:
            path = [b]
            while path[-1] != a:
                path.append(prev[path[-1]])
            return d, path[::-1]
        if d > dist.get(u, math.inf) or len(_path_to(prev, a, u)) > MAX_STEPS:
            continue
        for v, c, _k in g.edges(u):
            if v in banned_nodes or (u, v) in banned_edges:
                continue
            nd = d + c
            if nd < dist.get(v, math.inf):
                dist[v], prev[v] = nd, u
                heapq.heappush(heap, (nd, v))
    return None


def _path_to(prev: dict, a: str, u: str) -> list[str]:
    out = [u]
    while out[-1] != a and out[-1] in prev:
        out.append(prev[out[-1]])
    return out


def _bridges(g: _Graph, u: str, v: str, k: int = BRIDGES) -> list[dict]:
    from .claimcheck import locate

    tu, tv = g.terms_of(u), g.terms_of(v)
    qu, qv = ",".join("?" * len(tu)), ",".join("?" * len(tv))
    rows = g.ws.query(f"SELECT p.passage_id, p.doc_id, p.page, p.start, p.text, d.title FROM passages p JOIN documents d "
                      f"ON d.doc_id=p.doc_id WHERE p.passage_id IN (SELECT passage_id FROM term_mentions WHERE term_id IN "
                      f"({qu})) AND p.passage_id IN (SELECT passage_id FROM term_mentions WHERE term_id IN ({qv})) AND "
                      f"{g.ev} ORDER BY d.title, p.seq LIMIT ?", (*tu, *tv, k))
    where = locate(g.ws, [(r["passage_id"], r["passage_id"], None) for r in rows])
    return [{"passage_id": r["passage_id"], "doc_id": r["doc_id"], "title": r["title"] or "", "page": r["page"],
             "location": (where.get(r["passage_id"]) or {}).get("location") or "",
             "text": " ".join(r["text"].split())[:600], "start": r["start"]} for r in rows]


def paths(ws: Workspace, a_term: str, b_term: str, k: int = 3) -> dict:
    """The `k` shortest chains from one concept to another: {"from", "to", "paths": [{"cost", "steps": [{"from",
    "to", "kind" ("link" | "together"), "relation", "pmi", "together" (passages), "bridges": [passages],
    "sentences": [for a link]}]}]}. Raises KeyError for a term the glossary does not know."""
    for t in (a_term, b_term):
        if not ws.scalar("SELECT 1 FROM terms WHERE term_id=?", (t,)):
            raise KeyError(t)
    g = _Graph(ws)
    a, b = g.node(a_term), g.node(b_term)
    out = {"from": {"node": a, "label": g.labels.get(a, a)}, "to": {"node": b, "label": g.labels.get(b, b)},
           "paths": []}
    if a == b:
        return out
    # Yen's k shortest simple paths
    found: list[tuple[float, list[str]]] = []
    first = _shortest(g, a, b, set(), set())
    if first is None:
        return out
    found.append(first)
    candidates: list[tuple[float, list[str]]] = []
    while len(found) < k:
        last = found[-1][1]
        for i in range(len(last) - 1):
            root = last[:i + 1]
            banned_e = {(p[1][i], p[1][i + 1]) for p in found if p[1][:i + 1] == root and len(p[1]) > i + 1}
            spur = _shortest(g, root[-1], b, banned_e, set(root[:-1]))
            if spur is None:
                continue
            path = root[:-1] + spur[1]
            cost = sum(_cost(g, x, y) for x, y in zip(path, path[1:]))
            if all(p[1] != path for p in found) and all(c[1] != path for c in candidates):
                heapq.heappush(candidates, (cost, path))
        if not candidates:
            break
        found.append(heapq.heappop(candidates))
    for cost, path in found:
        steps = []
        for u, v in zip(path, path[1:]):
            lk = g.links.get(u, {}).get(v)
            st = {"from": {"node": u, "label": g.labels.get(u, u)}, "to": {"node": v, "label": g.labels.get(v, v)},
                  "kind": "link" if lk else "together", "relation": None, "pmi": None,
                  "bridges": _bridges(g, u, v)}
            if lk:
                rel = lk["relation_effective"]
                if g.node(lk["a"]) != u:   # stored from a to b: seen from this step's first concept
                    from .terms import _INVERSE

                    rel = _INVERSE.get(rel, rel)
                st["relation"] = rel
                if lk["source"] == "pattern":
                    from .textrelations import sentences

                    st["sentences"] = sentences(ws._conn(), lk["a"], lk["b"])
                else:
                    st["sentences"] = [{"quote": q} for q in (lk.get("quote_a"), lk.get("quote_b")) if q]
            if v in g.neighbours(u):
                st["pmi"] = round(g.neighbours(u)[v], 2)
            steps.append(st)
        out["paths"].append({"cost": round(cost, 3), "steps": steps})
    return out


def _cost(g: _Graph, u: str, v: str) -> float:
    return min((c for o, c, _k in g.edges(u) if o == v), default=math.inf)


# ---- D4 -------------------------------------------------------------------------------------------------------------
def _years(ws: Workspace) -> dict[str, str | None]:
    """{doc id: publication year} from the bibliography (the work each document is): `bibliography.doc_citations`."""
    from . import bibliography

    try:
        cites = bibliography.doc_citations(ws)
    except Exception:  # noqa: BLE001 - no bibliography: no years
        return {}
    out = {}
    for d, c in cites.items():
        y = c.get("year")
        if y is None and c.get("cite"):   # (the year is the last number of "Meadows 2008" until doc_citations gives it)
            nums = [w for w in str(c["cite"]).replace(",", " ").split() if w[:4].isdigit() and len(w) >= 4]
            y = nums[-1][:4] if nums else None
        out[d] = str(y)[:4] if y else None
    return out


def _profile(g: _Graph, node: str, docs: set[str] | None, top: int = 10) -> dict:
    """A concept within a set of documents (None: all): its mentions, documents, wordings and neighbours."""
    ws = g.ws
    ts = g.terms_of(node)
    q = ",".join("?" * len(ts))
    dq = ""
    args: list = list(ts)
    if docs is not None:
        if not docs:
            return {"documents": 0, "passages": 0, "mentions": 0, "wordings": [], "neighbours": []}
        dq = f" AND p.doc_id IN ({','.join('?' * len(docs))})"
        args += sorted(docs)
    rows = ws.query(f"SELECT m.term_id, m.passage_id, p.doc_id FROM term_mentions m JOIN passages p ON "
                    f"p.passage_id=m.passage_id WHERE m.term_id IN ({q}) AND {g.ev}{dq}", args)
    words = Counter(g.labels.get(r[0], r[0]) for r in rows)
    mine = {r[1] for r in rows}
    # neighbours within these documents: PMI against the passages of these documents
    total = int(ws.scalar(f"SELECT COUNT(DISTINCT m.passage_id) FROM term_mentions m JOIN passages p ON "
                          f"p.passage_id=m.passage_id WHERE {g.ev}{dq}", sorted(docs) if docs else []) or 1)
    together: dict[str, set] = defaultdict(set)
    per: dict[str, set] = defaultdict(set)
    if mine:
        for tid, pid in ws.query(f"SELECT m.term_id, m.passage_id FROM term_mentions m JOIN passages p ON "
                                 f"p.passage_id=m.passage_id WHERE m.passage_id IN (SELECT m2.passage_id FROM "
                                 f"term_mentions m2 WHERE m2.term_id IN ({q})) AND {g.ev}{dq}", args):
            o = g.node(tid)
            if o != node:
                together[o].add(pid)
        others = list(together)
        for o in others:
            ots = g.terms_of(o)
            oq = ",".join("?" * len(ots))
            per[o] = {r[0] for r in ws.query(f"SELECT m.passage_id FROM term_mentions m JOIN passages p ON "
                                             f"p.passage_id=m.passage_id WHERE m.term_id IN ({oq}) AND {g.ev}{dq}",
                                             [*ots, *(sorted(docs) if docs else [])])}
    nb = []
    for o, ps in together.items():
        if len(ps) < MIN_TOGETHER:
            continue
        pmi = math.log2(len(ps) * total / (max(1, len(mine)) * max(1, len(per[o]))))
        if pmi > 0:
            nb.append({"node": o, "label": g.labels.get(o, o), "together": len(ps), "pmi": round(pmi, 2)})
    nb.sort(key=lambda x: (-x["pmi"], -x["together"], x["label"]))
    return {"documents": len({r[2] for r in rows}), "passages": len(mine), "mentions": len(rows),
            "wordings": [{"label": w, "mentions": n} for w, n in words.most_common()], "neighbours": nb[:top]}


def over_time(ws: Workspace, term: str) -> dict:
    """A concept by publication year: {"label", "years": [{"year", "documents_in_year", **profile}], "no_year":
    {**profile, "documents_in_group"}, "with_year": n documents}."""
    from .docrole import theory_docs

    if not ws.scalar("SELECT 1 FROM terms WHERE term_id=?", (term,)):
        raise KeyError(term)
    g = _Graph(ws)
    node = g.node(term)
    theory = theory_docs(ws._conn())
    docs = [r[0] for r in ws.query("SELECT doc_id FROM documents") if r[0] not in theory]
    years = _years(ws)
    by: dict[str | None, set] = defaultdict(set)
    for d in docs:
        by[years.get(d)].add(d)
    out = {"node": node, "label": g.labels.get(node, node), "with_year": sum(len(v) for y, v in by.items() if y),
           "years": [], "no_year": None}
    for y in sorted(k for k in by if k):
        out["years"].append({"year": y, "documents_in_group": len(by[y]), **_profile(g, node, by[y])})
    if by.get(None):
        out["no_year"] = {"documents_in_group": len(by[None]), **_profile(g, node, by[None])}
    return out


def compare_groups(ws: Workspace, term: str, groups: dict[str, list[str]]) -> dict:
    """A concept in two (or more) sets of documents a person picked (not stored): {"label", "groups": [{"name",
    "documents_in_group", **profile}]}. Theory documents in a set are left out (and counted as such)."""
    from .docrole import theory_docs

    if not ws.scalar("SELECT 1 FROM terms WHERE term_id=?", (term,)):
        raise KeyError(term)
    if not groups or len(groups) > 6:
        raise ValueError("Pick two sets of documents to compare (at most six).")
    g = _Graph(ws)
    node = g.node(term)
    theory = theory_docs(ws._conn())
    known = {r[0] for r in ws.query("SELECT doc_id FROM documents")}
    out = {"node": node, "label": g.labels.get(node, node), "groups": []}
    for name, ids in groups.items():
        picked = {d for d in ids if d in known}
        kept = picked - theory
        out["groups"].append({"name": str(name)[:80], "documents_in_group": len(kept),
                              "theory_left_out": len(picked & theory), **_profile(g, node, kept)})
    return out
