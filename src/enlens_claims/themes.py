"""The themes of a corpus (F4): passages grouped by what they discuss, before any hypothesis is formed.

The one new component is clustering: spherical k-means (cosine similarity) with a k-means++ start drawn from a fixed
seed, so two runs with the same seed and the same passages give the same themes. It runs in one of two modes:

- by meaning: the passages' embeddings (`embed.vectors`), when the project has them for most passages and numpy (the
  `fast` extra) is installed; takes seconds;
- by words: sparse TF-IDF vectors over the term index (F3), in pure Python; takes up to a few minutes on a large
  project.

Steps of a run: the body passages, without exact repeats (the same normalised text: running headers and footers);
k themes (default 20, from 5 to 60); every passage assigned to its nearest centre with its similarity. Each theme is
named without a model by its key terms (class-based TF-IDF on the term index) and shown with the three passages
nearest its centre, from different documents where possible. An optional model pass (`theme` tasks, prompt
theme-v1) gives each theme a name of at most six words and a one-sentence description, each with a quote from the
representative passages that is checked like every other quote.

A person can rename a theme, merge two, or move a passage to another theme. The edits are stored as reviews under
the run's key (mode, k, seed and embedding model), so they apply again to a re-run with the same seed. Older runs are
kept until they are deleted, to compare the themes before and after documents are added.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import time
from collections import Counter, defaultdict
from typing import Callable

from .store import Workspace, now
from .textutil import fast_normalise

DEFAULT_K = 20
K_RANGE = (2, 60)
MIN_PASSAGES = 5
MAX_ITER = 60
MODES = ("auto", "meaning", "words")
CENTROID_TERMS = 400      # words mode: terms kept per centre (the rest are tiny weights)


def _h(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:10]


def run_key(mode: str, k: int, seed: int, embed_model: str | None) -> str:
    return "k" + _h(mode, k, seed, embed_model or "")


def _stopped():
    from .llm import BackendError

    return BackendError("Stopped.")


def _passages(ws: Workspace) -> tuple[list[dict], int]:
    """Body passages without exact repeats (the first of each repeated text is kept), and how many were dropped."""
    rows = [dict(r) for r in ws.query("SELECT passage_id, doc_id, seq, text FROM passages WHERE section='body' "
                                      "ORDER BY passage_id")]
    seen: set[str] = set()
    out = []
    for r in rows:
        key = fast_normalise(r["text"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out, len(rows) - len(out)


# ---------------------------------------------------------------------------------------------
# spherical k-means, dense (numpy) and sparse (pure Python)
# ---------------------------------------------------------------------------------------------
def _kmeanspp_dense(np, X, k: int, rng: random.Random):
    n = X.shape[0]
    centres = [rng.randrange(n)]
    best = X @ X[centres[0]]
    for _ in range(1, k):
        d = np.clip(1.0 - best, 0.0, None) ** 2
        total = float(d.sum())
        if total <= 0:
            pick = next(i for i in range(n) if i not in centres)
        else:
            target = rng.random() * total
            pick = int(np.searchsorted(np.cumsum(d), target, side="right"))
            pick = min(pick, n - 1)
        centres.append(pick)
        best = np.maximum(best, X @ X[pick])
    return X[centres].copy()


def kmeans_dense(X, k: int, seed: int = 0, should_stop: Callable | None = None):
    """Spherical k-means on unit rows of X (numpy). Returns (assignment, similarity, centres)."""
    import numpy as np

    rng = random.Random(seed)
    k = min(k, X.shape[0])
    C = _kmeanspp_dense(np, X, k, rng)
    assign = None
    for _it in range(MAX_ITER):
        if should_stop and should_stop():
            raise _stopped()
        S = X @ C.T
        new = S.argmax(axis=1)
        if assign is not None and np.array_equal(new, assign):
            break
        assign = new
        for j in range(k):
            members = X[assign == j]
            if len(members) == 0:  # an empty theme takes the passage farthest from its own centre
                far = int(np.argmin(S[np.arange(len(assign)), assign]))
                C[j] = X[far]
                assign[far] = j
                continue
            c = members.sum(axis=0)
            C[j] = c / (np.linalg.norm(c) or 1.0)
    S = X @ C.T
    assign = S.argmax(axis=1)
    sim = S[np.arange(len(assign)), assign]
    return [int(a) for a in assign], [float(s) for s in sim], C


def _sdot(a: dict, inv: dict, k: int) -> list[float]:
    acc = [0.0] * k
    for t, w in a.items():
        for j, cw in inv.get(t, ()):
            acc[j] += w * cw
    return acc


def _inverted(centres: list[dict]) -> dict:
    inv: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for j, c in enumerate(centres):
        for t, w in c.items():
            inv[t].append((j, w))
    return inv


def _unit_sparse(v: dict) -> dict:
    n = math.sqrt(sum(w * w for w in v.values())) or 1.0
    return {t: w / n for t, w in v.items()}


def kmeans_sparse(vecs: list[dict], k: int, seed: int = 0, should_stop: Callable | None = None):
    """Spherical k-means on unit sparse vectors (dicts), pure Python. Returns (assignment, similarity, centres)."""
    rng = random.Random(seed)
    n = len(vecs)
    k = min(k, n)
    first = rng.randrange(n)
    centres = [dict(vecs[first])]
    best = _sdot_one(vecs, centres[0])
    for _ in range(1, k):
        d = [max(0.0, 1.0 - b) ** 2 for b in best]
        total = sum(d)
        if total <= 0:
            pick = next(i for i in range(n) if vecs[i] is not centres[0])
        else:
            target, acc, pick = rng.random() * total, 0.0, n - 1
            for i, x in enumerate(d):
                acc += x
                if acc > target:
                    pick = i
                    break
        centres.append(dict(vecs[pick]))
        sims = _sdot_one(vecs, centres[-1])
        best = [max(a, b) for a, b in zip(best, sims)]
    assign: list[int] | None = None
    for _it in range(MAX_ITER):
        if should_stop and should_stop():
            raise _stopped()
        inv = _inverted(centres)
        new, sim = [], []
        for v in vecs:
            acc = _sdot(v, inv, k)
            j = max(range(k), key=lambda x: (acc[x], -x))
            new.append(j)
            sim.append(acc[j])
        if new == assign:
            break
        assign = new
        sums: list[dict] = [defaultdict(float) for _ in range(k)]
        for v, j in zip(vecs, assign):
            s = sums[j]
            for t, w in v.items():
                s[t] += w
        for j in range(k):
            if not sums[j]:  # an empty theme takes the passage farthest from its own centre
                far = min(range(n), key=lambda i: (sim[i], i))
                sums[j] = defaultdict(float, vecs[far])
                assign[far] = j
            top = sorted(sums[j].items(), key=lambda x: (-x[1], x[0]))[:CENTROID_TERMS]
            centres[j] = _unit_sparse(dict(top))
    inv = _inverted(centres)
    assign, sim = [], []
    for v in vecs:
        acc = _sdot(v, inv, k)
        j = max(range(k), key=lambda x: (acc[x], -x))
        assign.append(j)
        sim.append(acc[j])
    return assign, sim, centres


def _sdot_one(vecs: list[dict], c: dict) -> list[float]:
    return [sum(w * c.get(t, 0.0) for t, w in v.items()) for v in vecs]


# ---------------------------------------------------------------------------------------------
# a run
# ---------------------------------------------------------------------------------------------
def choose_mode(ws: Workspace, mode: str, embed_model: str | None) -> tuple[str, str]:
    """The mode a run will use, and why."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}.")
    try:
        import numpy  # noqa: F401
        have_np = True
    except ImportError:
        have_np = False
    body = int(ws.scalar("SELECT COUNT(*) FROM passages WHERE section='body'") or 0)
    vec = int(ws.scalar("SELECT COUNT(*) FROM embeddings e JOIN passages p ON p.passage_id=e.passage_id WHERE "
                        "e.model=? AND p.section='body'", (embed_model or "",)) or 0) if embed_model else 0
    meaning_ok = have_np and embed_model and body and vec >= 0.9 * body
    if mode == "meaning" and not meaning_ok:
        why = ("numpy is not installed (pip install 'enlens-claims[fast]')" if not have_np else
               "search by meaning is not set up for most passages yet")
        raise ValueError(f"Themes by meaning need passage embeddings and numpy: {why}. Use themes by words instead.")
    if mode == "auto":
        if meaning_ok:
            return "meaning", "the passages' embeddings"
        return "words", ("no embeddings" if not embed_model or vec < 0.9 * body else "numpy is not installed")
    return mode, "chosen"


def run(ws: Workspace, k: int = DEFAULT_K, seed: int = 0, mode: str = "auto", embed_model: str | None = None,
        progress: Callable[[str, int, int], None] | None = None, should_stop: Callable[[], bool] | None = None) -> str:
    """Group the project's passages into k themes; returns the run id."""
    from . import terms

    k = max(K_RANGE[0], min(int(k), K_RANGE[1]))
    mode, why = choose_mode(ws, mode, embed_model)
    say = progress or (lambda *a: None)
    say("terms", 0, 1)
    terms.ensure(ws, should_stop=should_stop)     # names (and the words mode) come from the term index
    rows, dropped = _passages(ws)
    if len(rows) < MIN_PASSAGES:
        raise ValueError(f"There are only {len(rows)} passages of text in this project: themes need at least "
                         f"{MIN_PASSAGES}. Add documents first.")
    # a small project gets fewer themes than asked: about three passages a theme at least
    k = max(K_RANGE[0], min(k, len(rows) // 3))
    counts = terms.passage_term_counts(ws)
    say("cluster", 0, 1)
    t0 = time.time()
    if mode == "meaning":
        import numpy as np

        from . import embed

        vs = embed.vectors(ws, embed_model)
        keep = [r for r in rows if r["passage_id"] in vs.pos]
        X = vs.matrix[[vs.pos[r["passage_id"]] for r in keep]]
        X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-12)
        assign, sim, _C = kmeans_dense(X, k, seed, should_stop)
        rows = keep
    else:
        n_pass = len(rows)
        dfp = Counter()
        for r in rows:
            for t in counts.get(r["passage_id"], ()):
                dfp[t] += 1
        vecs, keep = [], []
        for r in rows:
            c = counts.get(r["passage_id"])
            if not c:
                continue
            v = {t: (1 + math.log(f)) * math.log(n_pass / dfp[t]) for t, f in c.items() if dfp[t] < n_pass}
            if v:
                vecs.append(_unit_sparse(v))
                keep.append(r)
        if len(keep) < k:
            raise ValueError("Too few passages have terms of the glossary to group them by words.")
        assign, sim, _C = kmeans_sparse(vecs, k, seed, should_stop)
        rows = keep
    seconds = round(time.time() - t0, 1)
    # theme ids: by size, largest first (ties: the smallest passage id), so the same run gives the same ids
    groups: dict[int, list[int]] = defaultdict(list)
    for i, j in enumerate(assign):
        groups[j].append(i)
    order = sorted(groups, key=lambda j: (-len(groups[j]), min(rows[i]["passage_id"] for i in groups[j])))
    renum = {j: n for n, j in enumerate(order, 1)}
    say("name", 0, 1)
    info = {r["term_id"]: r["label"] for r in ws.query("SELECT term_id, label FROM terms")}
    stems_of = {r["term_id"]: r["stems"].split(" ") for r in ws.query("SELECT term_id, stems FROM terms")}
    total_tf: Counter = Counter()
    per: dict[int, Counter] = defaultdict(Counter)
    for i, j in enumerate(assign):
        c = counts.get(rows[i]["passage_id"], {})
        per[renum[j]].update(c)
        total_tf.update(c)
    avg = sum(sum(c.values()) for c in per.values()) / max(1, len(per))
    created = now()
    rid = "r" + _h(mode, k, seed, embed_model, ws.corpus_version(), created, len(rows))
    rkey = run_key(mode, k, seed, embed_model if mode == "meaning" else None)
    theme_rows, member_rows = [], []
    for j in order:
        tid = renum[j]
        c = per[tid]
        size_c = sum(c.values()) or 1
        scored = sorted(((cnt / size_c) * math.log(1 + avg / total_tf[t]), t) for t, cnt in c.items() if t in info)
        key_terms = [info[t] for t in _distinct([t for _s, t in sorted(scored, key=lambda x: (-x[0], x[1]))[:30]],
                                                stems_of)[:10]]
        members = sorted(groups[j], key=lambda i: (-sim[i], rows[i]["passage_id"]))
        reps, used = [], set()
        for i in members:
            if rows[i]["doc_id"] not in used:
                reps.append(rows[i]["passage_id"])
                used.add(rows[i]["doc_id"])
            if len(reps) >= 3:
                break
        for i in members:
            if len(reps) >= 3:
                break
            if rows[i]["passage_id"] not in reps:
                reps.append(rows[i]["passage_id"])
        name = " · ".join(key_terms[:3]) or f"Theme {tid}"
        theme_rows.append((rid, tid, name, None, json.dumps(key_terms, ensure_ascii=False), len(groups[j]),
                           json.dumps(reps), "terms", None, None))
        for i in groups[j]:
            member_rows.append((rid, tid, rows[i]["passage_id"], round(float(sim[i]), 5)))
    settings = {"why": why, "dropped_repeats": dropped, "seconds": seconds, "passages_without_vector":
                None}
    with ws.connect() as cx:
        cx.execute("INSERT INTO theme_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (rid, mode, k, seed, embed_model if mode == "meaning" else None, None, created, len(rows), rkey,
                    json.dumps(settings), ws.corpus_version()))
        cx.executemany("INSERT INTO themes VALUES (?,?,?,?,?,?,?,?,?,?)", theme_rows)
        cx.executemany("INSERT INTO theme_members VALUES (?,?,?,?)", member_rows)
    return rid


def _distinct(ids: list[str], stems_of: dict[str, list[str]]) -> list[str]:
    """Terms in order, without one that is part of another ("green" beside "green hydrogen": the longer stays, in
    the place of the first of them)."""
    from .terms import _nested

    out: list[str] = []
    for t in ids:
        st = stems_of.get(t, [])
        inside = [o for o in out if _nested(st, stems_of.get(o, [])) and len(stems_of.get(o, [])) >= len(st)]
        if inside:
            continue
        holder = [o for o in out if _nested(stems_of.get(o, []), st)]
        if holder:
            out[out.index(holder[0])] = t
            for o in holder[1:]:
                out.remove(o)
            continue
        out.append(t)
    return out


def runs(ws: Workspace) -> list[dict]:
    out = []
    for r in ws.query("SELECT * FROM theme_runs ORDER BY created_at DESC, rowid DESC"):
        d = dict(r)
        d["settings"] = json.loads(d.pop("settings_json") or "{}")
        d["stale"] = d["corpus_version"] != ws.corpus_version()
        d["named_by_model"] = int(ws.scalar("SELECT COUNT(*) FROM themes WHERE run_id=? AND name_source='model'",
                                            (r["run_id"],)) or 0)
        merges = _edits(ws, d["run_key"])["merges"]
        ids = [x[0] for x in ws.query("SELECT theme_id FROM themes WHERE run_id=?", (r["run_id"],))]
        d["themes_now"] = sum(1 for t in ids if _final(merges, t) == t)   # after the person's merges
        out.append(d)
    return out


def delete_run(ws: Workspace, run_id: str) -> None:
    with ws.connect() as cx:
        if not cx.execute("SELECT 1 FROM theme_runs WHERE run_id=?", (run_id,)).fetchone():
            raise KeyError(run_id)
        for t in ("theme_members", "themes", "theme_runs"):
            cx.execute(f"DELETE FROM {t} WHERE run_id=?", (run_id,))
        for tbl in ("results", "tasks"):
            cx.execute(f"DELETE FROM {tbl} WHERE kind='theme' AND substr(task_id, 1, ?) = ?",
                       (len(f"theme:{run_id}:"), f"theme:{run_id}:"))


# ---------------------------------------------------------------------------------------------
# a person's edits (reviews under the run's key) and the view of a run with them applied
# ---------------------------------------------------------------------------------------------
def _edits(ws: Workspace, rkey: str) -> dict:
    names, merges, moves = {}, {}, {}
    for r in ws.query("SELECT item_kind, item_id, field, corrected FROM reviews WHERE item_kind IN ('theme', "
                      "'theme_member') AND substr(item_id, 1, ?) = ? ORDER BY review_id", (len(rkey) + 1, rkey + ":")):
        tail = r["item_id"][len(rkey) + 1:]
        if r["item_kind"] == "theme" and r["field"] == "name":
            names[int(tail)] = r["corrected"] or None
        elif r["item_kind"] == "theme" and r["field"] == "merge":
            merges[int(tail)] = int(r["corrected"]) if r["corrected"] else None
        elif r["item_kind"] == "theme_member":
            moves[tail] = int(r["corrected"]) if r["corrected"] else None
    return {"names": {k: v for k, v in names.items() if v}, "merges": {k: v for k, v in merges.items() if v},
            "moves": {k: v for k, v in moves.items() if v}}


def edit(ws: Workspace, run_id: str, what: str, theme_id: int | None = None, value=None,
         passage_id: str | None = None, reviewer: str = "") -> None:
    """rename (value: the new name, "" to undo), merge (theme_id into value; None to undo), or move (passage_id to
    the theme `value`; None to undo)."""
    r = ws.query("SELECT run_key FROM theme_runs WHERE run_id=?", (run_id,))
    if not r:
        raise KeyError(run_id)
    rkey = r[0][0]
    ids = {x[0] for x in ws.query("SELECT theme_id FROM themes WHERE run_id=?", (run_id,))}
    with ws.connect() as cx:
        if what == "rename":
            if theme_id not in ids:
                raise KeyError(theme_id)
            name = " ".join(str(value or "").split())[:80]
            cx.execute("INSERT INTO reviews(item_kind, item_id, field, decision, corrected, reviewer, decided_at) "
                       "VALUES ('theme', ?, 'name', 'change', ?, ?, ?)", (f"{rkey}:{theme_id}", name, reviewer, now()))
        elif what == "merge":
            if theme_id not in ids or (value is not None and int(value) not in ids) or value == theme_id:
                raise ValueError("Choose two different themes of this run.")
            cx.execute("INSERT INTO reviews(item_kind, item_id, field, decision, corrected, reviewer, decided_at) "
                       "VALUES ('theme', ?, 'merge', 'change', ?, ?, ?)",
                       (f"{rkey}:{theme_id}", str(int(value)) if value is not None else "", reviewer, now()))
        elif what == "move":
            if not cx.execute("SELECT 1 FROM theme_members WHERE run_id=? AND passage_id=?", (run_id, passage_id)).fetchone():
                raise KeyError(passage_id)
            if value is not None and int(value) not in ids:
                raise KeyError(value)
            cx.execute("INSERT INTO reviews(item_kind, item_id, field, decision, corrected, reviewer, decided_at) "
                       "VALUES ('theme_member', ?, 'theme', 'change', ?, ?, ?)",
                       (f"{rkey}:{passage_id}", str(int(value)) if value is not None else "", reviewer, now()))
        else:
            raise ValueError("what must be rename, merge or move.")


def _final(merges: dict[int, int], t: int) -> int:
    seen = set()
    while t in merges and t not in seen:
        seen.add(t)
        t = merges[t]
    return t


def view(ws: Workspace, run_id: str, framework: str | None = None) -> dict:
    """A run with a person's edits applied: themes (name, description, key terms, size, documents, representative
    passages), the theme × document grid, and with a codebook profile the theme × code grid."""
    from .claimcheck import locate

    r = ws.query("SELECT * FROM theme_runs WHERE run_id=?", (run_id,))
    if not r:
        raise KeyError(run_id)
    run_row = dict(r[0])
    ed = _edits(ws, run_row["run_key"])
    themes = {t["theme_id"]: dict(t) for t in ws.query("SELECT * FROM themes WHERE run_id=? ORDER BY theme_id", (run_id,))}
    members = [dict(m) for m in ws.query("SELECT m.passage_id, m.theme_id, m.similarity, p.doc_id FROM theme_members m "
                                         "JOIN passages p ON p.passage_id=m.passage_id WHERE m.run_id=?", (run_id,))]
    for m in members:
        moved = ed["moves"].get(m["passage_id"])
        m["moved"] = bool(moved and moved in themes)
        m["theme_id"] = _final(ed["merges"], moved if moved in themes else m["theme_id"])
    by_theme: dict[int, list[dict]] = defaultdict(list)
    for m in members:
        by_theme[m["theme_id"]].append(m)
    titles = {d["doc_id"]: d["title"] or "" for d in ws.query("SELECT doc_id, title FROM documents")}
    out_themes = []
    rep_ids = []
    for tid, t in themes.items():
        if tid in ed["merges"] and _final(ed["merges"], tid) != tid:
            continue
        ms = by_theme.get(tid, [])
        merged_from = [x for x in themes if x != tid and _final(ed["merges"], x) == tid]
        docs = Counter(m["doc_id"] for m in ms)
        reps = json.loads(t["reps_json"] or "[]")
        terms_ = json.loads(t["terms_json"] or "[]")
        for x in merged_from:
            terms_ += [w for w in json.loads(themes[x]["terms_json"] or "[]") if w not in terms_]
        rep_ids += reps
        out_themes.append({"theme_id": tid, "name": ed["names"].get(tid) or t["name"], "name_source":
                           "person" if tid in ed["names"] else t["name_source"], "description": t["description"],
                           "quotes": json.loads(t["quotes_json"] or "null"), "model": t["model"], "terms": terms_[:10],
                           "size": len(ms), "documents": [{"doc_id": d, "title": titles.get(d, ""), "passages": n}
                                                          for d, n in docs.most_common()],
                           "representatives": reps, "merged_from": merged_from,
                           "moved_in": sum(1 for m in ms if m["moved"])})
    out_themes.sort(key=lambda t: (-t["size"], t["theme_id"]))
    # 0.8: numbered 1 to n in the order shown (no gaps after a merge); theme_id stays the stable id for links
    for i, t in enumerate(out_themes, 1):
        t["number"] = i
        t["merged_from_names"] = [{"theme_id": x, "name": ed["names"].get(x) or themes[x]["name"]}
                                  for x in t["merged_from"]]
    reps_text = {}
    if rep_ids:
        q = ",".join("?" * len(rep_ids))
        where = locate(ws, [(p, p, None) for p in rep_ids])
        for p in ws.query(f"SELECT p.passage_id, p.doc_id, p.page, p.text, p.start, p.end, d.title FROM passages p "
                          f"JOIN documents d ON "
                          f"d.doc_id=p.doc_id WHERE p.passage_id IN ({q})", rep_ids):
            reps_text[p["passage_id"]] = {"passage_id": p["passage_id"], "doc_id": p["doc_id"], "title": p["title"] or "",
                                          "start": p["start"], "end": p["end"],
                                          "page": p["page"], "text": p["text"],
                                          "location": (where.get(p["passage_id"]) or {}).get("span") or ""}
    for t in out_themes:
        t["representatives"] = [reps_text[p] for p in t["representatives"] if p in reps_text]
    doc_grid = {str(t["theme_id"]): {d["doc_id"]: d["passages"] for d in t["documents"]} for t in out_themes}
    code_grid = None
    if framework:
        from . import profile

        labs = profile.effective(ws, framework)
        theme_of = {m["passage_id"]: m["theme_id"] for m in members}
        cg: dict[str, Counter] = defaultdict(Counter)
        for lb in labs:
            t = theme_of.get(lb["passage_id"])
            if t is not None:
                cg[str(t)][lb["code"]] += 1
        from . import frameworks

        order = {c.code: i for i, c in enumerate(frameworks.get(framework, ws).sorted_codes())}
        code_grid = {"framework": framework, "cells": {t: dict(c) for t, c in cg.items()},
                     "codes": sorted({c for v in cg.values() for c in v}, key=lambda c: (order.get(c, 10 ** 6), c))}
    run_row["settings"] = json.loads(run_row.pop("settings_json") or "{}")
    run_row["stale"] = run_row["corpus_version"] != ws.corpus_version()
    return {"run": run_row, "themes": out_themes, "doc_grid": doc_grid, "code_grid": code_grid,
            "documents": [{"doc_id": d, "title": titles.get(d, "")} for d in
                          sorted({m["doc_id"] for m in members}, key=lambda d: titles.get(d, "").lower())],
            "edits": {"renamed": len(ed["names"]), "merged": len(ed["merges"]), "moved": len(ed["moves"])}}


def theme_passages(ws: Workspace, run_id: str, theme_id: int, offset: int = 0, limit: int = 50) -> dict:
    """The passages of one theme (edits applied), nearest the centre first."""
    from .claimcheck import locate

    v = view(ws, run_id)
    r = ws.query("SELECT run_key FROM theme_runs WHERE run_id=?", (run_id,))[0]
    ed = _edits(ws, r["run_key"])
    rows = []
    for m in ws.query("SELECT m.passage_id, m.theme_id, m.similarity, p.doc_id, p.page, p.text, p.start, p.end, d.title "
                      "FROM theme_members m "
                      "JOIN passages p ON p.passage_id=m.passage_id JOIN documents d ON d.doc_id=p.doc_id "
                      "WHERE m.run_id=?", (run_id,)):
        moved = ed["moves"].get(m["passage_id"])
        t = _final(ed["merges"], moved or m["theme_id"])
        if t == theme_id:
            rows.append(dict(m) | {"moved": bool(moved)})
    rows.sort(key=lambda x: (-x["similarity"], x["passage_id"]))
    page = rows[max(0, offset):max(0, offset) + max(1, min(limit, 200))]
    where = locate(ws, [(p["passage_id"], p["passage_id"], None) for p in page])
    for p in page:
        p["location"] = (where.get(p["passage_id"]) or {}).get("span") or ""
    t = next((x for x in v["themes"] if x["theme_id"] == theme_id), None)
    if t is None:
        raise KeyError(theme_id)
    return {"theme": t, "total": len(rows), "offset": offset, "passages": page,
            "others": [{"theme_id": x["theme_id"], "number": x["number"], "name": x["name"]} for x in v["themes"]
                       if x["theme_id"] != theme_id]}


# ---------------------------------------------------------------------------------------------
# the optional model pass: a name and a description, each with a checked quote
# ---------------------------------------------------------------------------------------------
def make_name_tasks(ws: Workspace, run_id: str, model: str) -> int:
    from .tasks import _insert_task

    v = view(ws, run_id)
    n = 0
    with ws.connect() as cx:
        for t in v["themes"]:
            reps = t["representatives"]
            if not reps:
                continue
            payload = {"run_id": run_id, "theme_id": t["theme_id"], "terms": t["terms"][:10],
                       "passages": [{"n": i, "passage_id": p["passage_id"], "title": p["title"], "page": p["page"],
                                     "text": p["text"]} for i, p in enumerate(reps, 1)]}
            n += _insert_task(cx, f"theme:{run_id}:{t['theme_id']}", "theme", model, payload)
    return n


def store_theme(cx, t, payload: dict, obj: dict, model: str) -> tuple[bool, list[str]]:
    from .schema import ThemeOut
    from .textutil import find_quote

    out = ThemeOut.model_validate(obj)
    errors = []
    quotes = {}
    for field, ev in (("name", out.name_quote), ("description", out.description_quote)):
        if ev.passage > len(payload["passages"]):
            errors.append(f"{field}_quote: there is no passage P{ev.passage}")
            continue
        p = payload["passages"][ev.passage - 1]
        hit = find_quote(p["text"], ev.quote)
        if not hit:
            errors.append(f"{field}_quote: quote not found in passage P{ev.passage}: {ev.quote[:80]!r}")
            continue
        quotes[field] = {"passage_id": p["passage_id"], "quote": p["text"][hit[0]:hit[1]]}
    if errors:
        return False, errors
    cx.execute("UPDATE themes SET name=?, description=?, name_source='model', quotes_json=?, model=? WHERE run_id=? "
               "AND theme_id=?", (out.name, out.description, json.dumps(quotes, ensure_ascii=False), model,
                                  payload["run_id"], payload["theme_id"]))
    return True, []


def name_with_model(ws: Workspace, run_id: str, backend, model: str, progress: Callable | None = None,
                    should_stop: Callable[[], bool] | None = None) -> dict:
    from . import runs as runs_mod
    from . import tasks

    make_name_tasks(ws, run_id, model)
    todo = [r["task_id"] for r in ws.query("SELECT task_id FROM tasks WHERE kind='theme' AND substr(task_id, 1, ?) = ? "
                                           "AND status != 'done' ORDER BY task_id", (len(f"theme:{run_id}:"),
                                                                                    f"theme:{run_id}:"))]
    rid = runs_mod.start(ws, "theme", run_id, backend, model, len(todo))
    done = failed = 0
    for i, tid in enumerate(todo, 1):
        if should_stop and should_stop():
            break
        if progress:
            progress(i, len(todo))
        ok, _e = tasks.run_one(ws, tid, backend, model)
        done += ok
        failed += not ok
    runs_mod.finish(ws, rid, done + failed)
    with ws.connect() as cx:
        cx.execute("UPDATE theme_runs SET chat_model=? WHERE run_id=?", (model, run_id))
    return {"named": done, "failed": failed, "themes": len(todo)}


def tables(ws: Workspace, run_id: str, framework: str | None = None) -> list[tuple[str, list[dict]]]:
    """Excel sheets: the themes, themes by document, and (with a profile) themes by code."""
    v = view(ws, run_id, framework)
    themes_rows = [{"Theme": t["number"], "Name": t["name"], "Named by": {"terms": "key terms (no model)",
                                                                           "model": "the AI", "person": "you"}.get(
        t["name_source"], t["name_source"]), "Description": t["description"] or "", "Passages": t["size"],
        "Key terms": ", ".join(t["terms"]), "Documents": len(t["documents"]),
        "Representative passages": "\n\n".join(f"{p['title']} ({p['location']}): {p['text'][:400]}"
                                               for p in t["representatives"])} for t in v["themes"]]
    docs = v["documents"]
    by_doc = []
    for t in v["themes"]:
        row = {"Theme": f"{t['number']}. {t['name']}"}
        for d in docs:
            row[(d["title"] or d["doc_id"])[:60]] = v["doc_grid"].get(str(t["theme_id"]), {}).get(d["doc_id"], "") or ""
        by_doc.append(row)
    sheets = [("Themes", themes_rows), ("Themes by document", by_doc)]
    if v["code_grid"]:
        cg = v["code_grid"]
        by_code = []
        for t in v["themes"]:
            row = {"Theme": f"{t['number']}. {t['name']}"}
            for c in cg["codes"]:
                row[c] = cg["cells"].get(str(t["theme_id"]), {}).get(c, "") or ""
            by_code.append(row)
        sheets.append(("Themes by code", by_code))
    return sheets
