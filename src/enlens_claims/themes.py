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
the run's key (mode, k, seed, embedding model and the grouping itself), so they apply again to a re-run that gives
the same themes. When documents were added and the run groups the passages differently, the edits of the latest
earlier run with the same settings follow the themes by the passages they share (`_carry_edits`), never by theme
number. Older runs are kept until they are deleted, to compare the themes before and after documents are added.

A person can also remove a theme that is not relevant (running headers, reference lists, a topic outside the
question): its passages are left out of the themes until it is brought back. A new theme can then be found in its
place (`new_theme`): one more step of the same k-means, with every other centre fixed. Each theme is split in two, the
half that fits it least well is tried as the heart of a new theme, the one that draws most passages closer to it than
to their own theme wins, and it is refined; it takes only passages that are closer to it than to their own theme and
to every removed theme, so it does not grow back into what was removed. Removals and new themes belong to one run: they are
stored on its rows, not as reviews under its key.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import time
import uuid
from collections import Counter, defaultdict
from typing import Callable

from . import __version__
from .store import Workspace, now
from .textutil import fast_normalise

DEFAULT_K = 20
K_RANGE = (2, 60)
MIN_PASSAGES = 5
MAX_ITER = 60
MODES = ("auto", "meaning", "words")
CENTROID_TERMS = 400      # words mode: terms kept per centre (the rest are tiny weights)
MIN_NEW = 3               # a new theme needs at least this many passages
TRIES = 8                 # hearts of a new theme refined, the best first, until one keeps MIN_NEW passages


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


def _assign(vecs: list[dict], inv: dict, k: int) -> tuple[list[int], list[float]]:
    """Each vector's nearest centre and its similarity: `_sdot` for each vector, the same sums in the same order, and
    the first of the highest (as `max(range(k), key=lambda x: (acc[x], -x))` found it). 0.16: in one loop, with the
    centres' words looked up once per word; about twice as quick."""
    new: list[int] = []
    sim: list[float] = []
    zero = [0.0] * k
    get = inv.get
    for v in vecs:
        acc = zero[:]
        for t, w in v.items():
            lst = get(t)
            if lst:
                for j, cw in lst:
                    acc[j] += w * cw
        m = max(acc)
        new.append(acc.index(m))
        sim.append(m)
    return new, sim


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
        new, sim = _assign(vecs, _inverted(centres), k)
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
    assign, sim = _assign(vecs, _inverted(centres), k)
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
    asked_k = k
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
    vecs, keep = _vectors(ws, mode, embed_model, rows, counts)
    without_vector = len(rows) - len(keep) if mode == "meaning" else 0
    if mode == "meaning":
        assign, sim, _C = kmeans_dense(vecs, k, seed, should_stop)
    else:
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
    key_terms = _key_terms(ws, {renum[j]: [rows[i]["passage_id"] for i in groups[j]] for j in order}, counts)
    created = now()
    # a random part: two runs of the same settings in the same second (a double click) must not share an id
    rid = "r" + _h(mode, k, seed, embed_model, ws.corpus_version(), created, len(rows), uuid.uuid4().hex)
    # the key of a person's edits: the settings and the grouping itself (theme numbers mean nothing without it)
    rkey = run_key(mode, k, seed, embed_model if mode == "meaning" else None) + "-" + _h(
        *(f"{rows[i]['passage_id']}={renum[j]}" for i, j in sorted(enumerate(assign), key=lambda x: rows[x[0]]["passage_id"])))
    theme_rows, member_rows = [], []
    for j in order:
        tid = renum[j]
        members = sorted(groups[j], key=lambda i: (-sim[i], rows[i]["passage_id"]))
        reps = _pick_reps([(rows[i]["passage_id"], rows[i]["doc_id"]) for i in members])
        name = " · ".join(key_terms[tid][:3]) or f"Theme {tid}"
        theme_rows.append((rid, tid, name, None, json.dumps(key_terms[tid], ensure_ascii=False), len(groups[j]),
                           json.dumps(reps), "terms", None, None))
        for i in groups[j]:
            member_rows.append((rid, tid, rows[i]["passage_id"], round(float(sim[i]), 5)))
    settings = {"why": why, "dropped_repeats": dropped, "seconds": seconds, "passages_without_vector":
                without_vector, "asked_k": asked_k}  # recorded with the run (0.11.1: it was counted and then written as None)
    with ws.connect() as cx:
        previous = _previous_run(cx, mode, seed, embed_model if mode == "meaning" else None, asked_k, k, rkey)
        cx.execute("INSERT INTO theme_runs(run_id, mode, k, seed, embed_model, chat_model, created_at, passages, run_key, "
                   "settings_json, corpus_version, app_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (rid, mode, k, seed, embed_model if mode == "meaning" else None, None, created, len(rows), rkey,
                    json.dumps(settings), ws.corpus_version(), __version__))
        cx.executemany(f"INSERT INTO themes({_THEME_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?)", theme_rows)
        cx.executemany("INSERT INTO theme_members(run_id, theme_id, passage_id, similarity) VALUES (?,?,?,?)",
                       member_rows)
        if previous:
            carried = _carry_edits(cx, previous, rid, rkey, {p: t for _r, t, p, _s in member_rows})
            settings.update(carried)
            cx.execute("UPDATE theme_runs SET settings_json=? WHERE run_id=?", (json.dumps(settings), rid))
        from . import researchlog  # 0.16

        how = {"meaning": "by meaning", "words": "by words"}.get(mode, mode)
        researchlog.record(cx, "themes-found", f"Found {len(theme_rows)} themes {how} in {len(rows):,} passages.",
                           "themes", rid, f"themes found on {researchlog.day(created)}",
                           data={"k": k, "mode": mode, "passages": len(rows)})
    return rid


def _previous_run(cx, mode: str, seed: int, embed_model: str | None, asked_k: int, k: int, rkey: str):
    """The latest earlier run with the same settings (the k asked for; before 0.14.3 only the k used was recorded)
    whose edits may follow its themes into a new run; None when there is none or its grouping is the same."""
    for r in cx.execute("SELECT run_id, run_key, k, settings_json FROM theme_runs WHERE mode=? AND seed=? AND "
                        "COALESCE(embed_model, '')=? ORDER BY created_at DESC, rowid DESC",
                        (mode, seed, embed_model or "")).fetchall():
        asked = (json.loads(r[3] or "{}")).get("asked_k")
        if (asked == asked_k) if asked is not None else (r[2] == k):
            return None if r[1] == rkey else (r[0], r[1])
    return None


def _carry_edits(cx, previous: tuple[str, str], new_run: str, new_key: str, new_member: dict[str, int]) -> dict:
    """A person's edits of the earlier run (renames, merges, moved passages, removed themes) follow their themes into
    the new run: each old theme is matched with the new theme that has most of its passages (at least 40% of them,
    two at least, and each new theme at most once). Edits of a theme with no counterpart are left behind and counted."""
    old_run, old_key = previous
    old_member = {p: t for t, p in cx.execute("SELECT theme_id, passage_id FROM theme_members WHERE run_id=?", (old_run,))}
    size = Counter(old_member.values())
    overlap: Counter = Counter((t, new_member[p]) for p, t in old_member.items() if p in new_member)
    mapping: dict[int, int] = {}
    taken: set[int] = set()
    for (old, new), n in sorted(overlap.items(), key=lambda x: (-x[1], x[0])):
        if old in mapping or new in taken or n < 2 or n < 0.4 * size[old]:
            continue
        mapping[old] = new
        taken.add(new)
    cols = [r[1] for r in cx.execute("PRAGMA table_info(reviews)") if r[1] != "review_id"]
    carried = dropped = 0
    for row in cx.execute(f"SELECT {', '.join(cols)} FROM reviews WHERE item_kind IN ('theme', 'theme_member') AND "
                          "substr(item_id, 1, ?) = ? ORDER BY review_id", (len(old_key) + 1, old_key + ":")).fetchall():
        d = dict(zip(cols, row))
        tail = d["item_id"][len(old_key) + 1:]
        if d["item_kind"] == "theme":
            new_tail = mapping.get(int(tail))
            target = d["corrected"] if d["field"] == "name" else (
                str(mapping.get(int(d["corrected"]))) if d["corrected"] and mapping.get(int(d["corrected"])) else
                ("" if not d["corrected"] else None))
        else:
            new_tail = tail if tail in new_member else None
            target = (str(mapping.get(int(d["corrected"]))) if d["corrected"] and mapping.get(int(d["corrected"]))
                      else ("" if not d["corrected"] else None))
        if new_tail is None or target is None:
            dropped += 1
            continue
        d["item_id"] = f"{new_key}:{new_tail}"
        d["corrected"] = target
        cx.execute(f"INSERT INTO reviews({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [d[c] for c in cols])
        carried += 1
    for old, at in cx.execute("SELECT theme_id, removed_at FROM themes WHERE run_id=? AND removed_at IS NOT NULL",
                              (old_run,)).fetchall():
        if old in mapping:
            cx.execute("UPDATE themes SET removed_at=? WHERE run_id=? AND theme_id=?", (at, new_run, mapping[old]))
            carried += 1
        else:
            dropped += 1
    return {"carried_edits": carried, "left_behind_edits": dropped, "edits_from": old_run}


# the columns of a theme as a run finds it (a removed theme and a new one have two more: removed_at, replaces)
_THEME_COLS = "run_id, theme_id, name, description, terms_json, size, reps_json, name_source, quotes_json, model"


def _vectors(ws: Workspace, mode: str, embed_model: str | None, rows: list[dict], counts: dict) -> tuple:
    """The passages' vectors for a mode, and the rows that have one (in the same order): unit rows of a numpy matrix
    by meaning, unit sparse vectors (TF-IDF over the term index, its IDF over all `rows`) by words."""
    if mode == "meaning":
        import numpy as np

        from . import embed

        vs = embed.vectors(ws, embed_model) if embed_model else None
        if vs is None or vs.np is None:
            raise ValueError("The passages' embeddings of these themes are gone (search by meaning was set up again, "
                             "or numpy is missing). Find the themes again.")
        keep = [r for r in rows if r["passage_id"] in vs.pos]
        X = vs.matrix[[vs.pos[r["passage_id"]] for r in keep]]
        return X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-12), keep
    n_pass = len(rows)
    dfp: Counter = Counter()
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
    return vecs, keep


def _key_terms(ws: Workspace, groups: dict[int, list[str]], counts: dict) -> dict[int, list[str]]:
    """Each theme's key terms (at most 10): class-based TF-IDF of the term index over the themes' passages."""
    info = {r["term_id"]: r["label"] for r in ws.query("SELECT term_id, label FROM terms")}
    stems_of = {r["term_id"]: r["stems"].split(" ") for r in ws.query("SELECT term_id, stems FROM terms")}
    total_tf: Counter = Counter()
    per: dict[int, Counter] = {}
    for tid, pids in groups.items():
        c: Counter = Counter()
        for p in pids:
            c.update(counts.get(p, {}))
        per[tid] = c
        total_tf.update(c)
    avg = sum(sum(c.values()) for c in per.values()) / max(1, len(per))
    out = {}
    for tid, c in per.items():
        size_c = sum(c.values()) or 1
        scored = sorted(((cnt / size_c) * math.log(1 + avg / total_tf[t]), t) for t, cnt in c.items() if t in info)
        out[tid] = [info[t] for t in _distinct([t for _s, t in sorted(scored, key=lambda x: (-x[0], x[1]))[:30]],
                                               stems_of)[:10]]
    return out


def _pick_reps(members: list[tuple[str, str]], n: int = 3) -> list[str]:
    """The passages that represent a theme: of its (passage id, document id), nearest the centre first, the first n
    from different documents, topped up with the next nearest."""
    reps, used = [], set()
    for pid, doc in members:
        if doc not in used:
            reps.append(pid)
            used.add(doc)
        if len(reps) >= n:
            return reps
    for pid, _doc in members:
        if len(reps) >= n:
            break
        if pid not in reps:
            reps.append(pid)
    return reps


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
        ids = [x[0] for x in ws.query("SELECT theme_id FROM themes WHERE run_id=? AND removed_at IS NULL",
                                      (r["run_id"],))]
        d["themes_now"] = sum(1 for t in ids if _final(merges, t) == t)   # after the person's merges and removals
        out.append(d)
    return out


def delete_run(ws: Workspace, run_id: str, why: str | None = None) -> None:
    with ws.connect() as cx:
        r = cx.execute("SELECT created_at, k FROM theme_runs WHERE run_id=?", (run_id,)).fetchone()
        if not r:
            raise KeyError(run_id)
        ws.removed(cx, "themes", run_id, None)  # 0.14: not brought back by a colleague's work (sync.py)
        from . import researchlog  # 0.16: the research log says so, with the person's reason

        n = cx.execute("SELECT COUNT(*) FROM themes WHERE run_id=?", (run_id,)).fetchone()[0]
        researchlog.record(cx, "themes-removed", f"Removed the set of {n} themes found on {researchlog.day(r[0])}.",
                           "themes", run_id, f"themes found on {researchlog.day(r[0])}", why=why)
        cx.execute("DELETE FROM sync_copies WHERE kind='themes' AND key=?", (run_id,))
        for t in ("theme_members", "themes", "theme_runs"):
            cx.execute(f"DELETE FROM {t} WHERE run_id=?", (run_id,))
        for tbl in ("results", "tasks"):
            cx.execute(f"DELETE FROM {tbl} WHERE kind='theme' AND substr(task_id, 1, ?) = ?",
                       (len(f"theme:{run_id}:"), f"theme:{run_id}:"))


# ---------------------------------------------------------------------------------------------
# a person's edits (reviews under the run's key) and the view of a run with them applied
# ---------------------------------------------------------------------------------------------
def _edits(ws: Workspace, rkey: str) -> dict:
    from .people import review_order

    names, merges, moves = {}, {}, {}
    order, oargs = review_order()
    for r in ws.query("SELECT item_kind, item_id, field, corrected FROM reviews WHERE item_kind IN ('theme', "
                      f"'theme_member') AND substr(item_id, 1, ?) = ? {order}", (len(rkey) + 1, rkey + ":", *oargs)):
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
         passage_id: str | None = None, reviewer: str = "", reason: str | None = None) -> None:
    """rename (value: the new name, "" to undo), merge (theme_id into value; None to undo), move (passage_id to
    the theme `value`; None to undo), or remove (value true: leave the theme and its passages out of the themes;
    false: bring it back). A removed theme takes no merge and no passage; a passage can be moved out of it."""
    r = ws.query("SELECT run_key FROM theme_runs WHERE run_id=?", (run_id,))
    if not r:
        raise KeyError(run_id)
    rkey = r[0][0]
    ids = {x[0] for x in ws.query("SELECT theme_id FROM themes WHERE run_id=?", (run_id,))}
    removed = {x[0] for x in ws.query("SELECT theme_id FROM themes WHERE run_id=? AND removed_at IS NOT NULL",
                                      (run_id,))}
    merges = _edits(ws, rkey)["merges"] if what == "remove" else {}
    gone = "That theme was removed: bring it back first."
    from .people import me as _me

    me = _me()  # 0.14: a person's edits are theirs; yours count over a colleague's (see _edits)
    from . import history, researchlog

    names = {x[0]: x[1] for x in ws.query("SELECT theme_id, name FROM themes WHERE run_id=?", (run_id,))}
    shown = _edits(ws, rkey)["names"]

    def called(t) -> str:
        return researchlog.quoted(shown.get(t) or names.get(t) or f"Theme {t}", 80)

    with ws.connect() as cx:
        # 0.16: the set as it was (history.py), and what changed, in the research log
        label = {"rename": "renaming a theme", "merge": "merging themes", "move": "moving a passage",
                 "remove": "removing a theme" if value else "bringing a theme back"}.get(what, what)
        before = history.snapshot(ws, cx, "themes", run_id, label)
        title = f"themes found on {researchlog.day(ws.scalar('SELECT created_at FROM theme_runs WHERE run_id=?', (run_id,)))}"
        entry = None
        if what == "rename" and theme_id in ids:
            new_name = " ".join(str(value or "").split())[:80]
            entry = ("theme-renamed", f"Renamed the theme {called(theme_id)} "
                     + (f"to {researchlog.quoted(new_name, 80)}." if new_name else "back to its found name."))
        elif what == "merge" and theme_id in ids:
            entry = (("theme-merged", f"Merged the theme {called(theme_id)} into {called(int(value))}.")
                     if value is not None and int(value) in ids else
                     ("theme-separated", f"Separated the theme {called(theme_id)} again."))
        elif what == "remove" and theme_id in ids:
            entry = (("theme-removed", f"Removed the theme {called(theme_id)} from the themes shown.") if value else
                     ("theme-restored", f"Brought the theme {called(theme_id)} back."))
        if what == "rename":
            if theme_id not in ids:
                raise KeyError(theme_id)
            name = " ".join(str(value or "").split())[:80]
            cx.execute("INSERT INTO reviews(item_kind, item_id, field, decision, corrected, reviewer, decided_at, person_id) "
                       "VALUES ('theme', ?, 'name', 'change', ?, ?, ?, ?)", (f"{rkey}:{theme_id}", name, reviewer, now(), me))
        elif what == "merge":
            if theme_id not in ids or (value is not None and int(value) not in ids) or value == theme_id:
                raise ValueError("Choose two different themes of this run.")
            if value is not None and (theme_id in removed or int(value) in removed):
                raise ValueError(gone)
            cx.execute("INSERT INTO reviews(item_kind, item_id, field, decision, corrected, reviewer, decided_at, person_id) "
                       "VALUES ('theme', ?, 'merge', 'change', ?, ?, ?, ?)",
                       (f"{rkey}:{theme_id}", str(int(value)) if value is not None else "", reviewer, now(), me))
        elif what == "move":
            if not cx.execute("SELECT 1 FROM theme_members WHERE run_id=? AND passage_id=?", (run_id, passage_id)).fetchone():
                raise KeyError(passage_id)
            if value is not None and int(value) not in ids:
                raise KeyError(value)
            if value is not None and int(value) in removed:
                raise ValueError(gone)
            cx.execute("INSERT INTO reviews(item_kind, item_id, field, decision, corrected, reviewer, decided_at, person_id) "
                       "VALUES ('theme_member', ?, 'theme', 'change', ?, ?, ?, ?)",
                       (f"{rkey}:{passage_id}", str(int(value)) if value is not None else "", reviewer, now(), me))
        elif what == "remove":
            if theme_id not in ids:
                raise KeyError(theme_id)
            if _final(merges, theme_id) != theme_id:
                raise ValueError("That theme is merged into another one: remove that one, or separate them first.")
            if value:
                shown = [t for t in ids - removed if _final(merges, t) == t]
                if shown == [theme_id]:
                    raise ValueError("It is the last theme shown. Find the themes again instead.")
                cx.execute("UPDATE themes SET removed_at=COALESCE(removed_at, ?) WHERE run_id=? AND theme_id=?",
                           (now(), run_id, theme_id))
            else:
                cx.execute("UPDATE themes SET removed_at=NULL WHERE run_id=? AND theme_id=?", (run_id, theme_id))
        else:
            raise ValueError("what must be rename, merge, move or remove.")
        if entry:
            researchlog.record(cx, entry[0], entry[1], "themes", run_id, title, version_id=before,
                               why=reason or None, data={"theme_id": theme_id})


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
    members = [dict(m) for m in ws.query("SELECT m.passage_id, m.theme_id, m.similarity, m.found_in, p.doc_id FROM "
                                         "theme_members m JOIN passages p ON p.passage_id=m.passage_id WHERE m.run_id=?",
                                         (run_id,))]
    for m in members:
        moved = ed["moves"].get(m["passage_id"])
        m["moved"] = bool(moved and moved in themes)
        m["theme_id"] = _final(ed["merges"], moved if moved in themes else m["theme_id"])
    by_theme: dict[int, list[dict]] = defaultdict(list)
    for m in members:
        by_theme[m["theme_id"]].append(m)
    titles = {d["doc_id"]: d["title"] or "" for d in ws.query("SELECT doc_id, title FROM documents")}
    name_of = lambda x: ed["names"].get(x) or themes[x]["name"]  # noqa: E731
    out_themes, removed_themes = [], []
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
        # a theme found in place of a removed one: which themes its passages were in before it took them
        drawn = Counter(_final(ed["merges"], m["found_in"]) for m in ms if m["found_in"] in themes)
        (removed_themes if t.get("removed_at") else out_themes).append({
            "theme_id": tid, "name": name_of(tid), "name_source":
            "person" if tid in ed["names"] else t["name_source"], "description": t["description"],
            "quotes": json.loads(t["quotes_json"] or "null"), "model": t["model"], "terms": terms_[:10],
            "size": len(ms), "documents": [{"doc_id": d, "title": titles.get(d, ""), "passages": n}
                                           for d, n in docs.most_common()],
            "representatives": reps, "merged_from": merged_from,
            "moved_in": sum(1 for m in ms if m["moved"]),
            "removed": bool(t.get("removed_at")), "removed_at": t.get("removed_at"),
            "replaces": ({"theme_id": t["replaces"], "name": name_of(t["replaces"])}
                         if t.get("replaces") in themes else None),
            "replaced_by": [{"theme_id": x, "name": name_of(x)} for x, o in themes.items() if o.get("replaces") == tid],
            "drawn_from": [{"theme_id": x, "name": name_of(x), "passages": n} for x, n in drawn.most_common()]})
    out_themes.sort(key=lambda t: (-t["size"], t["theme_id"]))
    removed_themes.sort(key=lambda t: (-t["size"], t["theme_id"]))
    # 0.8: numbered 1 to n in the order shown (no gaps after a merge); theme_id stays the stable id for links. A
    # removed theme has no number: it is not one of the themes.
    for i, t in enumerate(out_themes + removed_themes, 1):
        t["number"] = i if not t["removed"] else None
        t["merged_from_names"] = [{"theme_id": x, "name": name_of(x)} for x in t["merged_from"]]
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
    for t in out_themes + removed_themes:
        t["representatives"] = [reps_text[p] for p in t["representatives"] if p in reps_text]
    shown = {t["theme_id"] for t in out_themes}   # the passages of a removed theme are left out of the grids
    doc_grid = {str(t["theme_id"]): {d["doc_id"]: d["passages"] for d in t["documents"]} for t in out_themes}
    code_grid = None
    if framework:
        from . import profile

        labs = profile.effective(ws, framework)
        theme_of = {m["passage_id"]: m["theme_id"] for m in members if m["theme_id"] in shown}
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
    run_row["terms_left_out"] = _left_out(ws, [w for t in out_themes for w in t.get("terms") or []])
    return {"run": run_row, "themes": out_themes, "removed": removed_themes, "doc_grid": doc_grid,
            "code_grid": code_grid,
            "documents": [{"doc_id": d, "title": titles.get(d, "")} for d in
                          sorted({m["doc_id"] for m in members if m["theme_id"] in shown},
                                 key=lambda d: titles.get(d, "").lower())],
            "edits": {"renamed": len(ed["names"]), "merged": len(ed["merges"]), "moved": len(ed["moves"]),
                      "removed": len(removed_themes),
                      "added": sum(1 for t in themes.values() if t.get("replaces") is not None)}}


def _left_out(ws: Workspace, labels: list[str]) -> list[str]:
    """0.17: the key terms (of a set of themes) that the glossary now leaves out: no longer a term, because they start
    or end with a common word (of English or of a language found in a share of the passages) or a word of the
    project's own, or are one of its own phrases. A term that left for another reason (documents changed, the
    glossary's limit) is not named. Finding the themes again gives key terms without them. Empty while the glossary is
    out of date (it cannot tell yet)."""
    from . import stopwords, terms
    from .textutil import token_spans

    st = terms.status(ws)
    if not labels or not st["built"] or st["stale"]:
        return []
    rules = stopwords.rules(ws)
    found = [f for f in stopwords.found(ws) if f["on"]]
    total = sum(f["passages"] for f in found) or 1
    common = set(rules.stops("en"))
    for f in found:
        if f["passages"] >= 0.01 * total:    # not a language read in a few tables or references
            common |= rules.stops(f["code"])
    keys = {lb: terms._key_of(lb, rules) for lb in dict.fromkeys(labels)}
    ids = {lb: terms.term_id(k) for lb, k in keys.items() if k}
    have: set[str] = set()
    todo = sorted(set(ids.values()))
    for i in range(0, len(todo), 500):
        chunk = todo[i:i + 500]
        have.update(r[0] for r in ws.query(f"SELECT term_id FROM terms WHERE term_id IN ({','.join('?' * len(chunk))})",
                                           chunk))
    out = []
    for lb, k in keys.items():
        if k and ids[lb] in have:
            continue
        words = [t[3] for t in token_spans(lb, keep_stop=True)]
        if not k or k in rules.phrases or (words and (words[0] in common or words[-1] in common)):
            out.append(lb)
    return out


def theme_passages(ws: Workspace, run_id: str, theme_id: int, offset: int = 0, limit: int = 50) -> dict:
    """The passages of one theme (edits applied), nearest the centre first."""
    from .claimcheck import locate

    v = view(ws, run_id)
    r = ws.query("SELECT run_key FROM theme_runs WHERE run_id=?", (run_id,))[0]
    ed = _edits(ws, r["run_key"])
    # only the rows that can belong to this theme (0.11.1: every member of the run was read, with its text, per
    # page of one theme): its own and the themes merged into it, plus the passages moved into it
    own = [t for (t,) in ws.query("SELECT theme_id FROM themes WHERE run_id=?", (run_id,))
           if _final(ed["merges"], t) == theme_id]
    moved_in = [pid for pid, t in ed["moves"].items() if _final(ed["merges"], t) == theme_id]
    marks = lambda xs: ",".join("?" * len(xs))  # noqa: E731
    rows = []
    for m in ws.query("SELECT m.passage_id, m.theme_id, m.similarity, p.doc_id, p.page, p.text, p.start, p.end, d.title "
                      "FROM theme_members m "
                      "JOIN passages p ON p.passage_id=m.passage_id JOIN documents d ON d.doc_id=p.doc_id "
                      f"WHERE m.run_id=? AND (m.theme_id IN ({marks(own)}) OR m.passage_id IN ({marks(moved_in)}))",
                      [run_id, *own, *moved_in]):
        moved = ed["moves"].get(m["passage_id"])
        t = _final(ed["merges"], moved or m["theme_id"])
        if t == theme_id:
            rows.append(dict(m) | {"moved": bool(moved)})
    rows.sort(key=lambda x: (-x["similarity"], x["passage_id"]))
    page = rows[max(0, offset):max(0, offset) + max(1, min(limit, 200))]
    where = locate(ws, [(p["passage_id"], p["passage_id"], None) for p in page])
    for p in page:
        p["location"] = (where.get(p["passage_id"]) or {}).get("span") or ""
    # a removed theme can be read too: its passages can be moved out of it into a theme that is shown
    t = next((x for x in v["themes"] + v["removed"] if x["theme_id"] == theme_id), None)
    if t is None:
        raise KeyError(theme_id)
    return {"theme": t, "total": len(rows), "offset": offset, "passages": page,
            "others": [{"theme_id": x["theme_id"], "number": x["number"], "name": x["name"]} for x in v["themes"]
                       if x["theme_id"] != theme_id]}


# ---------------------------------------------------------------------------------------------
# a new theme in place of a removed one
# ---------------------------------------------------------------------------------------------
def _new_id(run_id: str, taken: set[int]) -> int:
    """An id for a new theme: above a run's own (1 to k), and different from one run to the next, so a rename of a
    new theme (a review under the run's key, which runs with the same settings share) never lands on another run's."""
    n = 0
    while True:
        tid = 1000 + int(_h(run_id, "new", n), 16) % 9_000_000
        if tid not in taken:
            return tid
        n += 1


def _sims(vecs, centres: list, dense: bool) -> list[list[float]]:
    """The similarity of each vector to each centre (one row per vector)."""
    if not centres:
        return [[] for _ in range(len(vecs))]
    if dense:
        import numpy as np

        return (vecs @ np.stack(centres).T).tolist()
    inv = _inverted(centres)
    return [_sdot(v, inv, len(centres)) for v in vecs]


def _centre(vecs, idx: list[int], dense: bool):
    """The unit mean of the vectors at idx (a sparse one keeps its CENTROID_TERMS heaviest terms, as in a run)."""
    if dense:
        import numpy as np

        c = vecs[idx].sum(axis=0)
        return c / (np.linalg.norm(c) or 1.0)
    s: dict[str, float] = defaultdict(float)
    for i in idx:
        for t, w in vecs[i].items():
            s[t] += w
    return _unit_sparse(dict(sorted(s.items(), key=lambda x: (-x[1], x[0]))[:CENTROID_TERMS]))


def new_theme(ws: Workspace, run_id: str, replaces: int, progress: Callable[[str, int, int], None] | None = None,
              should_stop: Callable[[], bool] | None = None) -> int:
    """Find a new theme in place of the removed theme `replaces`; returns its id.

    One more step of the run's k-means with every other centre fixed. The passages the run put in a theme that is
    shown (not moved there by a person) can join it; each removed theme stays as a centre of its own that keeps the
    passages closer to it, so the new theme does not grow back into what was removed. Each theme shown is split in
    two inside itself (spherical 2-means, the run's seed), and the half that fits the theme's centre less well is a
    heart (a single passage is too narrow a heart for TF-IDF vectors: it draws almost nothing). Each heart is scored
    by how much closer it is than their own theme to the passages it would take, and the best are refined (members,
    centre, again) until one keeps MIN_NEW passages. Those passages move to the new theme, which is named by its key
    terms like the others; the themes they come from keep their names."""
    from . import terms

    say = progress or (lambda *a: None)
    rr = ws.query("SELECT * FROM theme_runs WHERE run_id=?", (run_id,))
    if not rr:
        raise KeyError(run_id)
    run_row = dict(rr[0])
    trows = {r["theme_id"]: dict(r) for r in ws.query("SELECT theme_id, name, reps_json, removed_at, replaces FROM themes "
                                                      "WHERE run_id=?", (run_id,))}
    if replaces not in trows:
        raise KeyError(replaces)
    ed = _edits(ws, run_row["run_key"])
    name_of = lambda x: ed["names"].get(x) or trows[x]["name"]  # noqa: E731
    if not trows[replaces]["removed_at"]:
        raise ValueError("A new theme is found in place of a removed one: remove this theme first.")
    earlier = [x for x, t in trows.items() if t["replaces"] == replaces]
    if earlier:
        raise ValueError(f"“{name_of(earlier[0])}” was found in place of it already. Remove that one to find "
                         "another in its place.")

    say("vectors", 0, 1)
    terms.ensure(ws, should_stop=should_stop)
    counts = terms.passage_term_counts(ws)
    rows, _dropped = _passages(ws)
    dense = run_row["mode"] == "meaning"
    vecs, keep = _vectors(ws, run_row["mode"], run_row["embed_model"], rows, counts)
    pos = {r["passage_id"]: i for i, r in enumerate(keep)}
    doc_of = {r["passage_id"]: r["doc_id"] for r in keep}
    removed = {x for x, t in trows.items() if t["removed_at"]}
    eligible: list[tuple[str, int, float]] = []          # (passage, the theme the run put it in, its similarity)
    shown_in: list[int] = []                              # the theme each of them is shown in (merges applied)
    left_out: dict[int, list[int]] = defaultdict(list)   # a removed theme: its passages (vector positions)
    groups: dict[int, list[str]] = defaultdict(list)     # a theme that is shown: its passages (for the key terms)
    for m in ws.query("SELECT passage_id, theme_id, similarity FROM theme_members WHERE run_id=? ORDER BY passage_id",
                      (run_id,)):
        moved = ed["moves"].get(m["passage_id"])
        moved = moved if moved in trows else None
        t = _final(ed["merges"], moved or m["theme_id"])
        if t in removed:
            if m["passage_id"] in pos:
                left_out[t].append(pos[m["passage_id"]])
            continue
        groups[t].append(m["passage_id"])
        if moved is None and m["passage_id"] in pos:
            eligible.append((m["passage_id"], m["theme_id"], float(m["similarity"])))
            shown_in.append(t)
    if len(eligible) < 2 * MIN_NEW:
        raise ValueError("Too few passages are left in the themes to find a new one.")
    idx = [pos[p] for p, _t, _s in eligible]
    sub = vecs[idx] if dense else [vecs[i] for i in idx]   # their vectors, in the same order

    say("search", 0, 1)
    # what a passage must be closer to the new theme than: its own theme, and every removed theme
    sinks = [_centre(vecs, ix, dense) for _t, ix in sorted(left_out.items()) if ix]
    bar = [max([own, *to_removed]) for (_p, _t, own), to_removed in zip(eligible, _sims(sub, sinks, dense))]
    # the hearts tried: each theme shown, split in two (spherical 2-means inside it, the run's seed); the half that
    # fits the theme's own centre less well is a heart
    in_theme: dict[int, list[int]] = defaultdict(list)
    for i, t in enumerate(shown_in):
        in_theme[t].append(i)
    hearts = []
    for t, ix in sorted(in_theme.items()):
        if len(ix) < 2 * MIN_NEW:
            continue
        part = sub[ix] if dense else [sub[i] for i in ix]
        assign, _s, _c = (kmeans_dense if dense else kmeans_sparse)(part, 2, run_row["seed"] or 0, should_stop)
        halves = [[i for i, a in zip(ix, assign) if a == h] for h in (0, 1)]
        if min(len(h) for h in halves) < MIN_NEW:
            continue
        far = min(halves, key=lambda h: (sum(eligible[i][2] for i in h) / len(h), h[0]))
        hearts.append(_centre(sub, far, dense))
    # each scored by how much closer than their bar it is to the passages it would take
    gain = [0.0] * len(hearts)
    for row, b in zip(_sims(sub, hearts, dense), bar):
        for j, s in enumerate(row):
            if s > b:
                gain[j] += s - b
    found = None
    for j in sorted(range(len(hearts)), key=lambda j: (-gain[j], j))[:TRIES]:
        c, mem = hearts[j], None
        for _it in range(MAX_ITER):
            if should_stop and should_stop():
                raise _stopped()
            sim = [row[0] for row in _sims(sub, [c], dense)]
            new = [i for i, (s, b) in enumerate(zip(sim, bar)) if s > b]
            if len(new) < MIN_NEW or new == mem:
                break
            mem = new
            c = _centre(sub, mem, dense)
        else:  # not settled: the members of the last centre
            sim = [row[0] for row in _sims(sub, [c], dense)]
            new = [i for i, (s, b) in enumerate(zip(sim, bar)) if s > b]
        if len(new) >= MIN_NEW:
            found = (new, sim)
            break
    if found is None:
        raise ValueError("No new theme could be found: the passages left fit their own themes better than any new "
                         "one. Find the themes again with more themes instead.")

    say("name", 0, 1)
    mem, sim = found
    taken = {eligible[i][0]: (eligible[i][1], round(float(sim[i]), 5)) for i in mem}
    new_id = _new_id(run_id, set(trows))
    for t in groups:
        groups[t] = [p for p in groups[t] if p not in taken]
    groups[new_id] = sorted(taken)
    key_terms = _key_terms(ws, {t: ps for t, ps in groups.items() if ps}, counts)[new_id]
    reps = _pick_reps([(p, doc_of[p]) for p in sorted(taken, key=lambda p: (-taken[p][1], p))])
    losers = {old for old, _s in taken.values()}
    with ws.connect() as cx:
        cx.executemany("UPDATE theme_members SET theme_id=?, similarity=?, found_in=? WHERE run_id=? AND passage_id=?",
                       [(new_id, s, old, run_id, p) for p, (old, s) in taken.items()])
        cx.execute(f"INSERT INTO themes({_THEME_COLS}, replaces) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (run_id, new_id, " · ".join(key_terms[:3]) or "New theme", None,
                    json.dumps(key_terms, ensure_ascii=False), len(taken), json.dumps(reps), "terms", None, None,
                    replaces))
        # the themes the passages came from: their size, and representatives that are still theirs
        for t in losers:
            left = cx.execute("SELECT m.passage_id, p.doc_id FROM theme_members m JOIN passages p ON "
                              "p.passage_id=m.passage_id WHERE m.run_id=? AND m.theme_id=? ORDER BY m.similarity DESC, "
                              "m.passage_id", (run_id, t)).fetchall()
            old_reps = json.loads(trows[t]["reps_json"] or "[]")
            reps_t = old_reps if not any(p in taken for p in old_reps) else _pick_reps([(a, b) for a, b in left])
            cx.execute("UPDATE themes SET size=?, reps_json=? WHERE run_id=? AND theme_id=?",
                       (len(left), json.dumps(reps_t), run_id, t))
    return new_id


# ---------------------------------------------------------------------------------------------
# the optional model pass: a name and a description, each with a checked quote
# ---------------------------------------------------------------------------------------------
def _allowed_reps(ws: Workspace, run_id: str, theme: dict, allowed: set[str], lv: dict[str, str]) -> list[dict]:
    """A theme's representatives from documents of these settings (0.11): the shown ones that qualify, topped up
    from the theme's other passages closest to its centre."""
    reps = [p for p in theme["representatives"] if lv.get(p["doc_id"]) in allowed]
    want = max(len(theme["representatives"]), 1)
    if len(reps) < want:
        have = {p["passage_id"] for p in reps} | {p["passage_id"] for p in theme["representatives"]}
        for r in ws.query("SELECT p.passage_id, p.doc_id, p.page, p.text, d.title FROM theme_members m JOIN passages p ON "
                          "p.passage_id=m.passage_id JOIN documents d ON d.doc_id=p.doc_id WHERE m.run_id=? AND "
                          "m.theme_id=? ORDER BY m.similarity DESC LIMIT 200", (run_id, theme["theme_id"])):
            if len(reps) >= want:
                break
            if r["passage_id"] not in have and lv.get(r["doc_id"]) in allowed:
                reps.append({"passage_id": r["passage_id"], "doc_id": r["doc_id"], "title": r["title"] or "",
                             "page": r["page"], "text": r["text"]})
    return reps


def make_name_tasks(ws: Workspace, run_id: str, model: str, allowed: set[str] | None = None,
                    theme_ids: set[int] | None = None) -> int:
    """A naming task per theme, with representatives from documents of the `allowed` settings only (0.11: the
    ones the reader may read; default: every document an AI may read). A theme without such passages gets none."""
    from . import access
    from .tasks import replace_task

    allowed = allowed or {"cloud", "local"}
    v = view(ws, run_id)
    lv = access.levels(ws)
    n = 0
    with ws.connect() as cx:
        for t in v["themes"]:
            if theme_ids is not None and t["theme_id"] not in theme_ids:
                continue
            reps = _allowed_reps(ws, run_id, t, allowed, lv)
            if not reps:
                continue
            # 0.11: key terms are words of the documents: only those found in the passages sent go with them
            texts = " ".join(p["text"] for p in reps).lower()
            payload = {"run_id": run_id, "theme_id": t["theme_id"],
                       "terms": [w for w in t["terms"][:10] if w.lower() in texts or
                                 all(x in texts for x in w.lower().split())],
                       "passages": [{"n": i, "passage_id": p["passage_id"], "title": p["title"], "page": p["page"],
                                     "text": p["text"]} for i, p in enumerate(reps, 1)]}
            n += replace_task(cx, f"theme:{run_id}:{t['theme_id']}", "theme", model, payload)
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
    from . import access
    from . import runs as runs_mod
    from . import tasks

    # 0.11: representatives from documents the main model may read; a theme with none of those is named by the
    # local model (from its restricted passages) or keeps its key terms
    readers = access.Readers(backend, model)
    make_name_tasks(ws, run_id, model, readers.main_levels)
    head = f"theme:{run_id}:"
    made = {r[0] for r in ws.query("SELECT task_id FROM tasks WHERE kind='theme' AND substr(task_id, 1, ?) = ?",
                                   (len(head), head))}
    rest = {t["theme_id"] for t in view(ws, run_id)["themes"] if f"{head}{t['theme_id']}" not in made}
    if rest and "local" not in readers.main_levels and readers.local_configured():
        make_name_tasks(ws, run_id, model, {"cloud", "local"}, rest)
    todo = [r["task_id"] for r in ws.query("SELECT task_id FROM tasks WHERE kind='theme' AND substr(task_id, 1, ?) = ? "
                                           "AND status != 'done' ORDER BY task_id", (len(head), head))]
    rid = runs_mod.start(ws, "theme", run_id, backend, model, len(todo))
    done = failed = kept = 0
    for i, tid in enumerate(todo, 1):
        if should_stop and should_stop():
            break
        if progress:
            progress(i, len(todo))
        got = readers.for_task(ws, tid)
        if got is None:
            kept += 1  # keeps its key terms as its name
            continue
        ok, _e = tasks.run_one(ws, tid, got[0], got[1])
        done += ok
        failed += not ok
    runs_mod.finish(ws, rid, done + failed)
    with ws.connect() as cx:
        cx.execute("UPDATE theme_runs SET chat_model=? WHERE run_id=?", (model, run_id))
    return {"named": done, "failed": failed, "themes": len(todo), "kept_terms": kept + len(rest - {
        int(t.split(":")[-1]) for t in todo})}


def tables(ws: Workspace, run_id: str, framework: str | None = None) -> list[tuple[str, list[dict]]]:
    """Excel sheets: the themes, themes by document, (with a profile) themes by code, and the themes removed."""
    v = view(ws, run_id, framework)
    themes_rows = [{"Theme": t["number"], "Name": t["name"], "Named by": {"terms": "key terms (no model)",
                                                                           "model": "the AI", "person": "you"}.get(
        t["name_source"], t["name_source"]), "Description": t["description"] or "", "Passages": t["size"],
        "Key terms": ", ".join(t["terms"]), "Documents": len(t["documents"]),
        "Found in place of": t["replaces"]["name"] if t["replaces"] else "",
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
    if v["removed"]:
        sheets.append(("Removed themes", [{"Name": t["name"], "Passages left out": t["size"],
                                           "Key terms": ", ".join(t["terms"]), "Removed": t["removed_at"] or "",
                                           "New theme in its place": ", ".join(x["name"] for x in t["replaced_by"])}
                                          for t in v["removed"]]))
    return sheets
