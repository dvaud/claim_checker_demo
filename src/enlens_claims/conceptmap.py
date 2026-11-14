"""The concept map (roadmap D1, Level 0: no AI, no new dependency).

A graph of the glossary's concepts (a concept's wordings count as one node, as in D3: `conceptpaths._Graph`):

- **Nodes**: the `n` concepts mentioned in the most passages (at least `MIN_TOGETHER`), within the filters.
- **Co-occurrence edges**: two concepts mentioned together in at least `MIN_TOGETHER` passages, weighted by how much
  more often than by chance (pointwise mutual information over the passages in scope, as `concordance.collocates` and
  D3 weigh words), never by the raw count. Only the strongest are kept: each concept's `PER_NODE` strongest, and at
  most `EDGES_PER_NODE` × n in all (but always each concept's strongest one), so the map stays readable.
- **Links**: the links a person accepted or added, the AI's confident ones and the abbreviations (`terms.links`,
  "confirmed"), drawn in their type (broader, narrower, related, leads to, replaces; a link "the same" joins two
  wordings into one node, so it is never an edge).
- **Groups**: the concepts clustered by their co-occurrence edges (each concept's `GROUP_EDGES` strongest, more than
  are drawn) with the Louvain method (greedy modularity, then joined groups, again until nothing moves), in a fixed
  order, so the same project and filters give the same groups. A concept with no such edge is in no group.
- **Layout**: each group in a disc of its own, laid out force-directed (Fruchterman and Reingold) from fixed starting
  places, the discs placed by the edges between them without overlapping, the concepts in no group in a row under
  them; a fixed number of rounds, rounded: the same map every time. Places are in a unit square for a map `ASPECT`
  times as wide as high; the page scales them (and turns them a quarter round on a narrow screen).

**Filters** narrow the passages counted, and PMI is computed within them: documents, a theme (its passages, with a
person's merges and moves), a code of a codebook (its passages, as `profile.passages_with_code`), and years of
publication (from the bibliography, as D4). Theory and (N3) working documents are always left out (`docrole`).
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .conceptpaths import MIN_TOGETHER, _Graph, _years
from .store import Workspace

DEFAULT_N = 60          # concepts on the map
MAX_N = 150
MIN_N = 10
PER_NODE = 4            # each concept keeps its strongest co-occurrence edges on the map
EDGES_PER_NODE = 2      # at most 2 × n co-occurrence edges drawn in all
GROUP_EDGES = 8         # the groups are found from each concept's 8 strongest edges (more than are drawn)
CANDIDATES = 3          # nodes ranked from 3 × n candidates (a concept of several wordings is counted exactly after)
ROUNDS = 150            # layout rounds within a group
PASSAGES_SHOWN = 5      # passages an edge shows
_CHUNK = 500            # ids per IN (…) of a query


@dataclass
class Filters:
    docs: list[str] | None = None             # document ids
    theme: tuple[str, int] | None = None      # (run id, theme id)
    code: tuple[str, str] | None = None       # (codebook, code)
    year_from: int | None = None
    year_to: int | None = None
    applied: dict = field(default_factory=dict)

    def any(self) -> bool:
        return bool(self.docs or self.theme or self.code or self.year_from or self.year_to)


class _Scope:
    """The passages in scope: evidence documents, the documents and years asked for, the passages of a theme or a code.
    `pairs(terms)` yields the (term, passage) pairs within it."""

    def __init__(self, ws: Workspace, g: _Graph, f: Filters):
        self.ws, self.g = ws, g
        docs: set[str] | None = set(f.docs) if f.docs else None
        if f.year_from or f.year_to:
            lo, hi = f.year_from or 0, f.year_to or 9999
            by_year = {d for d, y in _years(ws).items() if y and lo <= int(y) <= hi}
            docs = by_year if docs is None else docs & by_year
        self.docs = docs
        ps: set[str] | None = None
        if f.theme:
            ps = theme_passages(ws, *f.theme)
        if f.code:
            from .profile import passages_with_code

            cp = passages_with_code(ws, f.code[0], f.code[1])
            ps = cp if ps is None else ps & cp
        self.passages = ps

    def empty(self) -> bool:
        return (self.docs is not None and not self.docs) or (self.passages is not None and not self.passages)

    def _where(self) -> tuple[list[str], list]:
        """The SQL conditions on `p` (passages) for the documents in scope, and their arguments (one chunk of passages
        is added by the caller)."""
        cond, args = [self.g.ev], []
        if self.docs is not None:
            cond.append(f"p.doc_id IN ({','.join('?' * len(self.docs))})")
            args += sorted(self.docs)
        return cond, args

    def _chunks(self):
        if self.passages is None:
            yield None
            return
        ids = sorted(self.passages)
        for i in range(0, len(ids), _CHUNK):
            yield ids[i:i + _CHUNK]

    def query(self, select: str, extra: str = "", extra_args: tuple = (), group: str = ""):
        """Rows of `select` FROM term_mentions m JOIN passages p, within the scope (chunked over a set of passages)."""
        if self.empty():
            return
        cond, args = self._where()
        for chunk in self._chunks():
            c, a = list(cond), list(args)
            if chunk is not None:
                c.append(f"p.passage_id IN ({','.join('?' * len(chunk))})")
                a += chunk
            if extra:
                c.append(extra)
                a += list(extra_args)
            yield from self.ws.query(f"SELECT {select} FROM term_mentions m JOIN passages p ON p.passage_id=m.passage_id "
                                     f"WHERE {' AND '.join(c)} {group}", a)

    def total(self) -> int:
        """Passages in scope that mention any term (the base of PMI); chunks are disjoint, so their counts add up."""
        return sum(int(r[0] or 0) for r in self.query("COUNT(DISTINCT m.passage_id)"))

    def term_counts(self) -> Counter:
        out: Counter = Counter()
        for t, n in self.query("m.term_id, COUNT(DISTINCT m.passage_id)", group="GROUP BY m.term_id"):
            out[t] += int(n)
        return out

    def passages_of(self, terms: list[str]) -> dict[str, set[str]]:
        """{term: its passages in scope} for these terms."""
        out: dict[str, set[str]] = defaultdict(set)
        for i in range(0, len(terms), _CHUNK):
            chunk = terms[i:i + _CHUNK]
            for t, p in self.query("DISTINCT m.term_id, m.passage_id", f"m.term_id IN ({','.join('?' * len(chunk))})",
                                   tuple(chunk)):
                out[t].add(p)
        return out


def theme_passages(ws: Workspace, run_id: str, theme_id: int) -> set[str]:
    """The passages of a theme with a person's merges and moves applied (as `themes.theme_passages` finds them)."""
    from .themes import _edits, _final

    r = ws.query("SELECT run_key FROM theme_runs WHERE run_id=?", (run_id,))
    if not r:
        raise KeyError(run_id)
    ed = _edits(ws, r[0]["run_key"], run_id)
    out = set()
    for pid, t in ws.query("SELECT passage_id, theme_id FROM theme_members WHERE run_id=?", (run_id,)):
        if _final(ed["merges"], ed["moves"].get(pid) or t) == theme_id:
            out.add(pid)
    return out


# ---- clustering: Louvain, in a fixed order ---------------------------------------------------------------------
def _louvain(n: int, edges: dict[tuple[int, int], float]) -> list[int]:
    """Groups of nodes 0..n-1 by greedy modularity (the Louvain method). Deterministic: nodes are visited in their
    order, a move needs a strictly larger gain, ties go to the smaller group number."""
    # W[i][j]: weights, symmetric; W[i][i]: weight inside a joined node, counted both ways
    W: list[dict[int, float]] = [defaultdict(float) for _ in range(n)]
    for (i, j), w in edges.items():
        if i != j and w > 0:
            W[i][j] += w
            W[j][i] += w
    member = list(range(n))            # original node -> current node
    while True:
        size = len(W)
        k = [sum(W[i].values()) for i in range(size)]
        m2 = sum(k)
        if m2 <= 0:
            break
        comm = list(range(size))
        tot = list(k)
        for _round in range(50):
            moved = False
            for i in range(size):
                if k[i] == 0:
                    continue
                own = comm[i]
                tot[own] -= k[i]
                w_to: dict[int, float] = defaultdict(float)
                for j, w in W[i].items():
                    if j != i:
                        w_to[comm[j]] += w
                best, gain = own, w_to.get(own, 0.0) - tot[own] * k[i] / m2
                for c in sorted(w_to):
                    g = w_to[c] - tot[c] * k[i] / m2
                    if g > gain + 1e-12:
                        best, gain = c, g
                comm[i] = best
                tot[best] += k[i]
                if best != own:
                    moved = True
            if not moved:
                break
        # renumber in the order of first appearance, and join the nodes of each group into one
        renum: dict[int, int] = {}
        for c in comm:
            renum.setdefault(c, len(renum))
        if len(renum) == size:
            break
        W2: list[dict[int, float]] = [defaultdict(float) for _ in range(len(renum))]
        for i in range(size):
            a = renum[comm[i]]
            for j, w in W[i].items():
                W2[a][renum[comm[j]]] += w
        member = [renum[comm[x]] for x in member]
        W = W2
    return member


# ---- layout: each group in a disc of its own, the discs placed by how much joins them ------------------------------
ASPECT = 1.6            # the map is laid out 1.6 times as wide as it is high (a narrow page turns it a quarter round)


def _disc(nodes: list[int], edges: dict[tuple[int, int], float], rounds: int) -> dict[int, tuple[float, float]]:
    """A group's nodes in the unit disc: a force-directed layout (Fruchterman and Reingold) of the edges inside it, from
    a sunflower of places in the nodes' order, a fixed number of rounds."""
    m = len(nodes)
    if m == 1:
        return {nodes[0]: (0.0, 0.0)}
    golden = math.pi * (3 - math.sqrt(5))
    pos = [[math.sqrt((k + 0.5) / m) * math.cos(k * golden), math.sqrt((k + 0.5) / m) * math.sin(k * golden)]
           for k in range(m)]
    at = {v: k for k, v in enumerate(nodes)}
    inside = [(at[i], at[j], w) for (i, j), w in sorted(edges.items()) if i in at and j in at]
    kk = 1.5 / math.sqrt(m)
    temp = 0.15
    for step in range(rounds):
        disp = [[0.0, 0.0] for _ in range(m)]
        for i in range(m):
            for j in range(i + 1, m):
                dx, dy = pos[i][0] - pos[j][0], pos[i][1] - pos[j][1]
                d2 = dx * dx + dy * dy
                if d2 < 1e-12:
                    dx, dy, d2 = 1e-4 * (1 + i % 7), 1e-4 * (1 + j % 5), 1e-8
                f = kk * kk / d2
                disp[i][0] += dx * f
                disp[i][1] += dy * f
                disp[j][0] -= dx * f
                disp[j][1] -= dy * f
        for i, j, w in inside:
            dx, dy = pos[i][0] - pos[j][0], pos[i][1] - pos[j][1]
            f = math.sqrt(dx * dx + dy * dy) * w / kk
            disp[i][0] -= dx * f
            disp[i][1] -= dy * f
            disp[j][0] += dx * f
            disp[j][1] += dy * f
        for i in range(m):
            dx, dy = disp[i]
            d = math.sqrt(dx * dx + dy * dy)
            if d > 0:
                sc = min(d, temp) / d
                pos[i][0] += dx * sc
                pos[i][1] += dy * sc
            r = math.sqrt(pos[i][0] ** 2 + pos[i][1] ** 2)
            if r > 1:              # kept in the disc
                pos[i][0] /= r
                pos[i][1] /= r
        temp = 0.15 * (1 - (step + 1) / rounds) + 0.003
    return {v: (pos[k][0], pos[k][1]) for k, v in enumerate(nodes)}


def _discs(gids: list[int], radius: dict[int, float], weight: dict[tuple[int, int], float],
           rounds: int = 400) -> dict[int, tuple[float, float]]:
    """Places for the groups' discs: joined groups pulled together by their edges between them, no two discs
    overlapping, spread wider than high. The largest starts in the middle, the others on a sunflower round it."""
    if len(gids) == 1:
        return {gids[0]: (0.0, 0.0)}
    golden = math.pi * (3 - math.sqrt(5))
    spread = sum(radius.values())
    pos = {g: [0.0, 0.0] if k == 0 else [math.sqrt(k) * spread / math.sqrt(len(gids)) * math.cos(k * golden) * ASPECT,
                                          math.sqrt(k) * spread / math.sqrt(len(gids)) * math.sin(k * golden)]
           for k, g in enumerate(gids)}
    for step in range(rounds):
        disp = {g: [0.0, 0.0] for g in gids}
        for a_i, a in enumerate(gids):
            for b in gids[a_i + 1:]:
                dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
                d = math.sqrt(dx * dx + dy * dy) or 1e-6
                want = radius[a] + radius[b] + 0.8
                f = (want - d) * 0.5 if d < want else -min(d - want, 2.0) * 0.02 * weight.get((a, b), 0.0)
                disp[a][0] += dx / d * f
                disp[a][1] += dy / d * f
                disp[b][0] -= dx / d * f
                disp[b][1] -= dy / d * f
        for g in gids:   # towards the middle, more strongly up and down: a map wider than high
            disp[g][0] -= pos[g][0] * 0.01
            disp[g][1] -= pos[g][1] * 0.01 * ASPECT * ASPECT
            pos[g][0] += disp[g][0]
            pos[g][1] += disp[g][1]
    return {g: (pos[g][0], pos[g][1]) for g in gids}


def _layout(n: int, group: list[int | None], edges: dict[tuple[int, int], float], rounds: int = ROUNDS) -> list[tuple[float, float]]:
    """Places in the unit square for a map `ASPECT` times as wide as high: each group in a disc of its own (a disc's
    area grows with its concepts), the discs placed by the edges between them, and the concepts in no group in a row
    under them. Deterministic: fixed starting places, a fixed number of rounds, rounded."""
    if n == 0:
        return []
    members: dict[int | None, list[int]] = defaultdict(list)
    for i, g in enumerate(group):
        members[g].append(i)
    gids = sorted(k for k in members if k is not None)
    radius = {g: math.sqrt(len(members[g])) * 0.55 for g in gids}
    local: dict[int, tuple[float, float]] = {}
    for g in gids:
        local.update(_disc(members[g], edges, rounds))
    weight: dict[tuple[int, int], float] = defaultdict(float)
    for (i, j), w in edges.items():
        a, b = group[i], group[j]
        if a is not None and b is not None and a != b:
            weight[(min(a, b), max(a, b))] += w
    centres = _discs(gids, radius, dict(weight)) if gids else {}
    pos: dict[int, tuple[float, float]] = {}
    for g in gids:
        cx, cy = centres[g]
        for i in members[g]:
            pos[i] = (cx + radius[g] * local[i][0], cy + radius[g] * local[i][1])
    alone = members.get(None, [])
    if alone:
        if pos:
            x0, x1 = min(p[0] for p in pos.values()), max(p[0] for p in pos.values())
            y1 = max(p[1] for p in pos.values()) + 0.7
        else:
            x0, x1, y1 = 0.0, max(1.0, len(alone) * 0.25), 0.0
        per_row = max(1, int((x1 - x0) / 1.1) + 1)
        for k, i in enumerate(alone):
            pos[i] = (x0 + (k % per_row) * 1.1, y1 + (k // per_row) * 0.6)
    xs, ys = [p[0] for p in pos.values()], [p[1] for p in pos.values()]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    scale = max((x1 - x0) / ASPECT, y1 - y0) or 1.0      # one scale for both: discs stay round
    ox = (ASPECT - (x1 - x0) / scale) / 2                 # centred in the box
    oy = (1 - (y1 - y0) / scale) / 2
    return [(round(((pos[i][0] - x0) / scale + ox) / ASPECT, 4), round((pos[i][1] - y0) / scale + oy, 4))
            for i in range(n)]


# ---- the map -----------------------------------------------------------------------------------------------------
def options(ws: Workspace) -> dict:
    """What the filters can choose from: documents (evidence only), the themes of the latest set, the codebooks with
    labels and their codes, and the years known."""
    from .docrole import not_evidence_docs

    left = not_evidence_docs(ws._conn())
    docs = [{"doc_id": r["doc_id"], "title": r["title"] or ""} for r in
            ws.query("SELECT doc_id, title FROM documents ORDER BY title, doc_id") if r["doc_id"] not in left]
    themes_out: dict = {"run_id": None, "themes": []}
    run = ws.query("SELECT run_id, run_key FROM theme_runs ORDER BY created_at DESC, rowid DESC LIMIT 1")
    if run:   # the latest set of themes, as the Themes page opens on it: those shown (not removed, not merged away)
        from .themes import _edits, _final

        ed = _edits(ws, run[0]["run_key"], run[0]["run_id"])
        rows = ws.query("SELECT theme_id, name FROM themes WHERE run_id=? AND removed_at IS NULL ORDER BY theme_id",
                        (run[0]["run_id"],))
        themes_out = {"run_id": run[0]["run_id"], "themes": [
            {"theme_id": r["theme_id"], "name": ed["names"].get(r["theme_id"]) or r["name"] or f"Theme {r['theme_id']}"}
            for r in rows if _final(ed["merges"], r["theme_id"]) == r["theme_id"]]}
    codebooks = []
    for (fw_name,) in ws.query("SELECT DISTINCT framework FROM labels WHERE framework IS NOT NULL ORDER BY framework"):
        codes = [r[0] for r in ws.query("SELECT DISTINCT code FROM labels WHERE framework=? ORDER BY code", (fw_name,))]
        title, names = fw_name, {}
        try:
            from . import frameworks

            fw = frameworks.get(fw_name, ws)
            if fw:
                title = fw.title or fw_name
                order = {c.code: i for i, c in enumerate(fw.sorted_codes())}
                codes.sort(key=lambda c: (order.get(c, 10 ** 6), c))
                names = {c: (fw.codes[c].description if c in fw.codes else "") for c in codes}
        except (ValueError, KeyError):
            pass
        codebooks.append({"name": fw_name, "title": title,
                          "codes": [{"code": c, "description": (names.get(c) or "")[:120]} for c in codes]})
    years = sorted({int(y) for d, y in _years(ws).items() if y and d not in left})
    return {"documents": docs, "themes": themes_out, "codebooks": codebooks, "years": years}


def _built(ws: Workspace) -> bool:
    return bool(ws.scalar("SELECT 1 FROM terms LIMIT 1"))


def concept_map(ws: Workspace, f: Filters | None = None, n: int = DEFAULT_N) -> dict:
    """{"built", "filters", "passages" (in scope), "concepts_in_scope", "nodes": [{"id", "label", "passages",
    "group", "x", "y"}], "edges": [{"a", "b", "together", "pmi"}], "links": [{"a", "b", "relation", "source"}],
    "groups": [{"group", "size", "names"}], "links_off_map"}. `id` is a term id of the glossary (the page of the
    concept). Raises KeyError for a theme set that does not exist."""
    f = f or Filters()
    n = max(MIN_N, min(MAX_N, int(n or DEFAULT_N)))
    out = {"built": _built(ws), "filters": f.applied, "n": n, "passages": 0, "concepts_in_scope": 0, "nodes": [],
           "edges": [], "links": [], "groups": [], "links_off_map": 0}
    if not out["built"]:
        return out
    g = _Graph(ws)
    sc = _Scope(ws, g, f)
    total = sc.total()
    out["passages"] = total
    if not total:
        return out
    # rank the nodes: first by the sum of their terms' counts (an upper bound), then exactly among the candidates
    per_term = sc.term_counts()
    rough: Counter = Counter()
    for t, c in per_term.items():
        rough[g.node(t)] += c
    out["concepts_in_scope"] = sum(1 for c in rough.values() if c >= MIN_TOGETHER)
    cands = [x for x, c in sorted(rough.items(), key=lambda x: (-x[1], x[0])) if c >= MIN_TOGETHER][:CANDIDATES * n]
    terms_needed = sorted({t for x in cands for t in g.terms_of(x)})
    tp = sc.passages_of(terms_needed)
    node_ps: dict[str, set[str]] = {}
    for x in cands:
        s: set[str] = set()
        for t in g.terms_of(x):
            s |= tp.get(t, set())
        if len(s) >= MIN_TOGETHER:
            node_ps[x] = s
    label = lambda x: g.labels.get(x, x)  # noqa: E731
    chosen = sorted(node_ps, key=lambda x: (-len(node_ps[x]), label(x).lower(), x))[:n]
    idx = {x: i for i, x in enumerate(chosen)}
    # how often each pair is mentioned together
    in_passage: dict[str, list[int]] = defaultdict(list)
    for x in chosen:
        for p in node_ps[x]:
            in_passage[p].append(idx[x])
    together: Counter = Counter()
    for p in sorted(in_passage):
        ids = sorted(in_passage[p])
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                together[(ids[a], ids[b])] += 1
    pmi: dict[tuple[int, int], float] = {}
    for (a, b), c in together.items():
        if c < MIN_TOGETHER:
            continue
        v = math.log2(c * total / (len(node_ps[chosen[a]]) * len(node_ps[chosen[b]])))
        if v > 0:
            pmi[(a, b)] = v
    # keep each node's strongest, then the strongest of all
    order = lambda e: (-pmi[e], -together[e], e)  # noqa: E731
    by_node: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for e in pmi:
        by_node[e[0]].append(e)
        by_node[e[1]].append(e)
    kept, for_groups, must = set(), set(), set()
    for i in range(len(chosen)):
        ranked = sorted(by_node[i], key=order)
        kept |= set(ranked[:PER_NODE])
        for_groups |= set(ranked[:GROUP_EDGES])
        must |= set(ranked[:1])          # the cap below never leaves a joined concept without a line
    rest = sorted(kept - must, key=order)
    kept = must | set(rest[:max(0, EDGES_PER_NODE * len(chosen) - len(must))])
    edges = {e: pmi[e] for e in sorted(kept)}
    # the person's links among the concepts shown (one per pair, as stored: from a to b)
    links, off = [], set()
    seen = set()
    for lk in _confirmed_links(g):
        a, b = g.node(lk["a"]), g.node(lk["b"])
        if a == b:
            continue
        key = tuple(sorted((a, b)))
        if a in idx and b in idx:
            if key in seen:
                continue
            seen.add(key)
            links.append({"a": a, "b": b, "relation": lk["relation_effective"], "source": lk["source"]})
        else:
            off.add(key)
    links.sort(key=lambda x: (idx[x["a"]], idx[x["b"]]))
    # groups, from the co-occurrence edges only (what the documents group); a lone concept is in none
    mx = max(pmi.values(), default=1.0)
    raw = _louvain(len(chosen), {e: pmi[e] / mx for e in sorted(for_groups)})
    members: dict[int, list[int]] = defaultdict(list)
    for i, c in enumerate(raw):
        members[c].append(i)
    real = [ms for ms in members.values() if len(ms) > 1]
    real.sort(key=lambda ms: (-len(ms), -sum(len(node_ps[chosen[i]]) for i in ms), min(ms)))
    group: list[int | None] = [None] * len(chosen)
    for gi, ms in enumerate(real, 1):
        for i in ms:
            group[i] = gi
    # the layout: the edges the groups were found from, and the links a little weaker
    lay = {e: 0.3 + 0.7 * pmi[e] / mx for e in sorted(for_groups)}
    for lk in links:
        e = tuple(sorted((idx[lk["a"]], idx[lk["b"]])))
        lay[e] = max(lay.get(e, 0.0), 0.5)
    pos = _layout(len(chosen), group, lay)
    out["nodes"] = [{"id": x, "label": label(x), "passages": len(node_ps[x]), "group": group[i],
                     "x": pos[i][0], "y": pos[i][1]} for i, x in enumerate(chosen)]
    out["edges"] = [{"a": chosen[a], "b": chosen[b], "together": together[(a, b)], "pmi": round(w, 2)}
                    for (a, b), w in sorted(edges.items(), key=lambda kv: order(kv[0]))]
    out["links"] = links
    out["groups"] = [{"group": gi, "size": len(ms),
                      "names": [label(chosen[i]) for i in sorted(ms, key=lambda i: (-len(node_ps[chosen[i]]), i))[:3]]}
                     for gi, ms in enumerate(real, 1)]
    out["links_off_map"] = len(off)
    return out


def _confirmed_links(g: _Graph) -> list[dict]:
    """The links `_Graph` keeps (confirmed, not rejected, not "different"), each once, in a fixed order."""
    out, seen = [], set()
    for a in sorted(g.links):
        for b in sorted(g.links[a]):
            lk = g.links[a][b]
            key = (lk["a"], lk["b"], lk["source"])
            if key not in seen:
                seen.add(key)
                out.append(lk)
    return out


def edge(ws: Workspace, a_term: str, b_term: str, f: Filters | None = None) -> dict:
    """One edge of the map: {"a", "b" ({"node", "label"}), "together" (passages in scope), "pmi", "link"
    ({"relation", "source", "sentences"} or null), "passages": up to `PASSAGES_SHOWN`}. Raises KeyError for a term
    the glossary does not know."""
    from .claimcheck import locate

    for t in (a_term, b_term):
        if not ws.scalar("SELECT 1 FROM terms WHERE term_id=?", (t,)):
            raise KeyError(t)
    f = f or Filters()
    g = _Graph(ws)
    a, b = g.node(a_term), g.node(b_term)
    sc = _Scope(ws, g, f)
    tp = sc.passages_of(sorted(set(g.terms_of(a)) | set(g.terms_of(b))))
    pa = set().union(*(tp.get(t, set()) for t in g.terms_of(a)))
    pb = set().union(*(tp.get(t, set()) for t in g.terms_of(b)))
    both = pa & pb
    total = sc.total()
    v = math.log2(len(both) * total / (len(pa) * len(pb))) if both and total else None
    out = {"a": {"node": a, "label": g.labels.get(a, a)}, "b": {"node": b, "label": g.labels.get(b, b)},
           "together": len(both), "pmi": round(v, 2) if v is not None else None, "link": None, "passages": []}
    lk = g.links.get(a, {}).get(b)
    if lk:
        rel = lk["relation_effective"]
        if g.node(lk["a"]) != a:     # stored from b to a: seen from a
            from .terms import _INVERSE

            rel = _INVERSE.get(rel, rel)
        if lk["source"] == "pattern":
            from .textrelations import sentences

            sents = sentences(ws._conn(), lk["a"], lk["b"])
        else:
            sents = [{"quote": q} for q in (lk.get("quote_a"), lk.get("quote_b")) if q]
        out["link"] = {"relation": rel, "source": lk["source"], "sentences": sents}
    if both:
        ids = sorted(both)
        rows = []
        for i in range(0, len(ids), _CHUNK):
            chunk = ids[i:i + _CHUNK]
            rows += ws.query(f"SELECT p.passage_id, p.doc_id, p.page, p.start, p.seq, p.text, d.title FROM passages p "
                             f"JOIN documents d ON d.doc_id=p.doc_id WHERE p.passage_id IN ({','.join('?' * len(chunk))})",
                             chunk)
        rows.sort(key=lambda r: ((r["title"] or "").lower(), r["doc_id"], r["seq"] or 0))
        rows = rows[:PASSAGES_SHOWN]
        where = locate(ws, [(r["passage_id"], r["passage_id"], None) for r in rows])
        out["passages"] = [{"passage_id": r["passage_id"], "doc_id": r["doc_id"], "title": r["title"] or "",
                            "page": r["page"], "location": (where.get(r["passage_id"]) or {}).get("location") or "",
                            "text": " ".join(r["text"].split())[:600], "start": r["start"]} for r in rows]
    return out


def as_text(m: dict) -> str:
    """The map in words, for the command line: its groups, the strongest pairs and the links."""
    if not m["built"]:
        return "No glossary yet: make it first (enlens terms build)."
    if not m["nodes"]:
        return "No concept is mentioned in two passages within these filters."
    lab = {x["id"]: x["label"] for x in m["nodes"]}
    lines = [f"{len(m['nodes'])} of {m['concepts_in_scope']} concepts, from {m['passages']} passages."]
    for gr in m["groups"]:
        ms = [x["label"] for x in m["nodes"] if x["group"] == gr["group"]]
        lines.append(f"Group {gr['group']} ({gr['size']}): {', '.join(ms)}")
    alone = [x["label"] for x in m["nodes"] if x["group"] is None]
    if alone:
        lines.append(f"In no group: {', '.join(alone)}")
    if m["edges"]:
        lines.append("Mentioned together more often than by chance:")
        for e in m["edges"][:20]:
            lines.append(f"  {lab[e['a']]} – {lab[e['b']]}: {e['together']} passages, PMI {e['pmi']}")
    if m["links"]:
        lines.append("Links:")
        for lk in m["links"]:
            lines.append(f"  {lab[lk['a']]} {lk['relation']} {lab[lk['b']]} ({lk['source']})")
    return "\n".join(lines)
