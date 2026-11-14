"""A codebook profile of any document (F2): which codes it addresses, how much, and where, each label with its reason.

Two passes, the second optional:

1. Keywords and meaning (no model, seconds). For every body passage, candidate codes come from
   - the keyword match of `Framework.scores` (BM25 on the code texts plus the lexicon of common phrasings), with
     the words the passage shares with the code text ("matched words"), and
   - when the project has embeddings, the cosine between the passage's vector and each code's vector. Code texts
     are embedded once per framework and model (`code_vectors`). A code is a meaning candidate for a passage when
     the passage is unusually close to it (MEANING_Z standard deviations above the code's mean over the corpus)
     and among the passage's closest codes.
   A code found both ways is marked "keywords and meaning agree". The strongest candidates form the provisional
   profile at once; up to MAX_CANDIDATES go to the model pass.
2. The model pass (`label` tasks, prompt label-v1): one passage (with the passage before it as context) and its
   candidates. The model says which codes apply, as the main topic or a mention, in which direction where the
   codebook has one, with a quote checked against the passage and a reason of at most 200 characters.
   Task ids are `label:<framework>:<passage_id>`, so a stopped job resumes and a re-run reads nothing twice.

What counts for a passage (`effective`): the model's labels once the passage was read by the model, otherwise the
provisional ones of pass 1; a person's decisions (reviews, item_kind 'label') and labels of their own always win.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import statistics
from collections import Counter, defaultdict
from operator import itemgetter
from typing import Callable

from . import __version__, frameworks
from .people import me, mine_sql
from .store import Workspace, now
from .textutil import STOPWORDS, _TOKEN_RE, fast_normalise, stem

MAX_CANDIDATES = 8
KEYWORD_FLOOR = 0.2       # share of a code text's (idf-weighted) words a passage must have to be a candidate
PROVISIONAL = 0.6         # ... to count in the provisional profile on keywords alone
MEANING_Z = 2.0           # how unusual the closeness of a passage to a code must be (z-score over the corpus)
MEANING_TOP = 5           # ... and the code among the passage's closest codes
SOURCES = ("keywords", "meaning", "both", "model", "person")
RELEVANCE = ("main", "mentioned")
DIRECTIONS = ("helps", "hinders", "mixed", "not_stated")


# 0.15: a label row as this module writes it, with the ENLENS version that made it (the table may have more columns:
# an add-on's); named, so a column added later does not break the writes
_LABEL_COLS = ("label_id, passage_id, doc_id, framework, code, relevance, direction, confidence, quote, start, end, page, "
               "source, model, prompt_version, reason, matched_json, score, similarity, task_id, created_at")
_INSERT_LABEL = f"INSERT OR REPLACE INTO labels({_LABEL_COLS}, app_version) VALUES ({','.join('?' * 22)})"


def _h(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def label_id(framework: str, passage_id: str, code: str, source: str) -> str:
    kind = "p1" if source in ("keywords", "meaning", "both") else source
    return "l" + _h(framework, passage_id, code, kind)


# ---------------------------------------------------------------------------------------------
# pass 1: keywords and meaning
# ---------------------------------------------------------------------------------------------
def _coverage(fw: frameworks.Framework, code: str, have: set[str], idf: dict[str, float],
              totals: dict | None = None, words: bool = True) -> tuple[float, list[str] | set[str]]:
    """The share of a code text's words (weighted by how rare they are in the corpus) that a passage has, and the
    words shared (sorted; with `words` False, the set as found, for a caller that sorts only the ones it keeps).
    `totals` caches each code's denominator and word weights for one pass (0.11.1: a module-wide cache keyed by the
    idf dict's address kept the denominators of an earlier corpus once the index was rebuilt)."""
    want = fw.code_stems(code)
    if not want:
        return 0.0, []
    got = totals.get(code) if totals is not None else None
    if got is None:
        weight = {t: idf.get(t, 1.0) for t in want}
        got = (sum(idf.get(t, 1.0) for t in want) or 1.0, weight)
        if totals is not None:
            totals[code] = got
    total, weight = got
    shared = want & have
    cov = sum(weight[t] for t in shared) / total   # the same weights added in the same order as before
    return cov, (sorted(shared) if words else shared)


def code_vectors(ws: Workspace, fw: frameworks.Framework, embedder) -> dict[str, list[float]] | None:
    """The vector of every code's text for this embedding model (made once, kept in `code_vectors`)."""
    from .embed import _unit, prefixes

    _q, dprefix = prefixes(embedder.model)
    have = {r["code"]: (r["text_hash"], bytes(r["vec"])) for r in ws.query(
        "SELECT code, text_hash, vec FROM code_vectors WHERE model=? AND framework=?", (embedder.model, fw.name))}
    todo = []
    for c in fw.sorted_codes():
        th = _h(fw.code_text(c.code))
        if have.get(c.code, ("", b""))[0] != th:
            todo.append((c.code, th, f"{fw.label} {c.code}: {fw.code_text(c.code)}"))
    for i in range(0, len(todo), 32):
        chunk = todo[i:i + 32]
        vecs = embedder.embed([dprefix + t for _c, _h2, t in chunk])
        with ws.connect() as cx:
            cx.executemany("INSERT OR REPLACE INTO code_vectors VALUES (?,?,?,?,?)",
                           [(embedder.model, fw.name, c, th, _unit(v).tobytes()) for (c, th, _t), v in zip(chunk, vecs)])
        for (c, th, _t), v in zip(chunk, vecs):
            have[c] = (th, _unit(v).tobytes())
    from array import array

    return {c: list(array("f", b)) for c, (_t, b) in have.items() if c in fw.codes}


def _words(text: str) -> tuple[list[str], dict[str, str]]:
    """`tokens(text)` and `surface_words(text)` from one reading of the text: the same words, stop words and stems.
    0.16: the keyword pass normalised and split each passage twice for them."""
    toks: list[str] = []
    surface: dict[str, str] = {}
    for w in _TOKEN_RE.findall(fast_normalise(text)):
        if len(w) > 1 and w not in STOPWORDS:
            s = stem(w)
            toks.append(s)
            surface.setdefault(s, w)
    return toks, surface


def _meaning_candidates(ws: Workspace, fw, embedder, pids: list[str]) -> dict[str, list[tuple[str, float]]]:
    """{passage_id: [(code, cosine)]} for the passages unusually close to a code (see MEANING_Z, MEANING_TOP)."""
    from . import embed

    vs = embed.vectors(ws, embedder.model)
    if vs is None:
        return {}
    cv = code_vectors(ws, fw, embedder)
    if not cv:
        return {}
    codes = sorted(cv)
    try:
        import numpy as np
    except ImportError:
        if len(vs.ids) * len(codes) > 2_000_000:
            return {}  # too slow without numpy: keywords only (pip install 'enlens-claims[fast]')
        np = None
    want = set(pids)
    out: dict[str, list[tuple[str, float]]] = defaultdict(list)
    if np is not None:
        cm = np.asarray([cv[c] for c in codes], dtype=np.float32)
        if cm.shape[1] != vs.matrix.shape[1]:
            return {}
        sims = vs.matrix @ cm.T                      # passages × codes
        mean, sd = sims.mean(axis=0), sims.std(axis=0) + 1e-6
        z = (sims - mean) / sd
        order = np.argsort(-sims, axis=1)[:, :MEANING_TOP]
        for i, pid in enumerate(vs.ids):
            if pid not in want:
                continue
            for j in order[i]:
                if z[i, j] >= MEANING_Z:
                    out[pid].append((codes[int(j)], round(float(sims[i, j]), 4)))
        return out
    cols = {c: vs.similarities(cv[c]) for c in codes}
    stats = {c: (statistics.fmean(v), statistics.pstdev(v) + 1e-6) for c, v in cols.items()}
    for i, pid in enumerate(vs.ids):
        if pid not in want:
            continue
        row = sorted(((cols[c][i], c) for c in codes), reverse=True)[:MEANING_TOP]
        for s, c in row:
            if (s - stats[c][0]) / stats[c][1] >= MEANING_Z:
                out[pid].append((c, round(s, 4)))
    return out


def keyword_candidates(fw: frameworks.Framework, text: str, idf: dict[str, float], totals: dict,
                       toks: list[str] | None = None) -> dict[str, dict]:
    """The codes the keyword pass finds in one passage's text, before meaning is added: {code: {score, coverage,
    matched, lexicon}}. 0.16: one function for the keyword pass and the codebook editor's *Try it* (codebooks.py)."""
    if toks is None:
        toks, _words_of = _words(text)
    have = set(toks)
    lex_hits = fw.lexicon_hits(text) if fw.lexicon else set()
    scores = fw.scores(text, toks, lex_hits)  # the phrasings matched once, not twice (0.11.1)
    cands: dict[str, dict] = {}
    # the best scores only, in the order a full sort gave them (`nlargest` is that sort's first n, ties included)
    for code, sc in heapq.nlargest(MAX_CANDIDATES * 3, scores.items(), key=itemgetter(1)):
        cov, shared = _coverage(fw, code, have, idf, totals, words=False)
        lexicon = code in lex_hits
        if cov < KEYWORD_FLOOR and not lexicon:
            continue
        cands[code] = {"score": round(sc, 3), "coverage": round(cov, 3), "matched": sorted(shared), "lexicon": lexicon}
    return cands


def rank_candidates(cands: dict[str, dict]) -> list[tuple[str, dict]]:
    """A passage's candidates, best first, as the keyword pass keeps them (the first MAX_CANDIDATES)."""
    return sorted(cands.items(), key=lambda x: (-(("similarity" in x[1]) and (x[1]["coverage"] > 0 or x[1]["lexicon"])),
                                                -max(x[1]["coverage"], 0.6 if x[1]["lexicon"] else 0),
                                                -x[1].get("similarity", 0), x[0]))


def keyword_pass(ws: Workspace, framework: str = "sdg", embedder=None, doc_ids: list[str] | None = None,
                 progress: Callable[[int, int], None] | None = None) -> dict:
    """Pass 1 for every body passage (or those of `doc_ids`): store the candidates as labels with source keywords,
    meaning or both. Deterministic and quick; earlier pass-1 labels of these passages are replaced (a person's
    decisions on them are kept: label ids do not change)."""
    from .search import passage_index

    from .docrole import theory_docs

    fw = frameworks.get(framework, ws)
    idx = passage_index(ws)
    only = set(doc_ids) if doc_ids else None
    theory = theory_docs(ws._conn())  # 0.18.1 (K2): theory documents are never labelled with a codebook
    rows = idx.read([i for i, d in enumerate(idx.doc_of) if (only is None or d in only) and d not in theory])
    idf = idx.bm25.idf
    meaning = _meaning_candidates(ws, fw, embedder, [r["passage_id"] for r in rows]) if embedder is not None else {}
    out_rows = []
    stamp = now()
    totals: dict[str, float] = {}
    for n, r in enumerate(rows, 1):
        toks, words = _words(r["text"])
        cands = keyword_candidates(fw, r["text"], idf, totals, toks)
        for code, sim in meaning.get(r["passage_id"], []):
            cands.setdefault(code, {"score": 0.0, "coverage": 0.0, "matched": [], "lexicon": False})["similarity"] = sim
        ranked = rank_candidates(cands)[:MAX_CANDIDATES]
        surface = words if ranked else {}
        for code, c in ranked:
            kw = c["coverage"] > 0 or c["lexicon"]
            source = "both" if kw and "similarity" in c else "keywords" if kw else "meaning"
            conf = max(c["coverage"], 0.6 if c["lexicon"] else 0.0)
            if source == "both":
                conf = max(conf, 0.7)
            elif source == "meaning":
                conf = 0.5
            matched = [surface.get(s, s) for s in c["matched"]]
            reason = (("matched words: " + ", ".join(matched)) if matched else
                      ("a common phrasing of this code" if c["lexicon"] else ""))
            if "similarity" in c:
                reason = (reason + "; " if reason else "") + f"close in meaning (similarity {c['similarity']:.2f})"
            out_rows.append((label_id(fw.name, r["passage_id"], code, source), r["passage_id"], r["doc_id"], fw.name,
                             code, None, None, round(conf, 3), None, None, None, r["page"], source, None, None,
                             reason[:200], json.dumps(matched, ensure_ascii=False), c["score"], c.get("similarity"),
                             None, stamp))
        if progress and n % 500 == 0:
            progress(n, len(rows))
    pids = [r["passage_id"] for r in rows]
    with ws.connect() as cx:
        for i in range(0, len(pids), 500):
            chunk = pids[i:i + 500]
            cx.execute(f"DELETE FROM labels WHERE framework=? AND source IN ('keywords','meaning','both') AND passage_id "
                       f"IN ({','.join('?' * len(chunk))})", (fw.name, *chunk))
        cx.executemany(_INSERT_LABEL, [(*r, __version__) for r in out_rows])
        meta = ws.meta("profile_pass1") or {}
        meta[fw.name] = {"at": stamp, "corpus_version": ws.corpus_version(), "passages": len(rows),
                         "meaning_model": getattr(embedder, "model", None) if meaning else None,
                         "codes_fp": codes_fp(fw)}
        ws.set_meta("profile_pass1", meta, cx)
    return {"framework": fw.name, "passages": len(rows), "candidates": len(out_rows),
            "with_candidates": len({x[1] for x in out_rows}), "meaning": bool(meaning)}


def pass1_status(ws: Workspace, framework: str) -> dict:
    m = (ws.meta("profile_pass1") or {}).get(framework)
    changed = False
    if m and m.get("codes_fp"):  # 0.16: the codebook's codes or their words changed since (a pass before 0.16 has none)
        try:
            changed = codes_fp(frameworks.get(framework, ws)) != m["codes_fp"]
        except ValueError:
            changed = False
    return {"done": m is not None, "stale": bool(m) and m.get("corpus_version") != ws.corpus_version(), **(m or {}),
            "codebook_changed": changed}


def ensure_pass1(ws: Workspace, framework: str, embedder=None) -> dict:
    st = pass1_status(ws, framework)
    if st["done"] and not st["stale"] and (embedder is None or st.get("meaning_model") == getattr(embedder, "model", None)
                                           or st.get("meaning_model") is not None):
        return st
    keyword_pass(ws, framework, embedder)
    return pass1_status(ws, framework)


# ---------------------------------------------------------------------------------------------
# the model pass
# ---------------------------------------------------------------------------------------------
def candidates_of(ws: Workspace, framework: str, passage_id: str) -> list[dict]:
    rows = ws.query("SELECT code, confidence, source, similarity FROM labels WHERE framework=? AND passage_id=? AND "
                    "source IN ('keywords','meaning','both') ORDER BY confidence DESC, code", (framework, passage_id))
    return [dict(r) for r in rows]


def label_plan(ws: Workspace, framework: str = "sdg", doc_ids: list[str] | None = None, all_passages: bool = False,
               limit: int | None = None, passage_ids: list[str] | None = None) -> dict:
    """What a model pass would read: the passages (with at least one candidate unless `all_passages`) not read yet,
    and how long it is likely to take (from this project's recent label tasks, or the model test)."""
    st = pass1_status(ws, framework)
    from .docrole import labelled_sql   # 0.19.0 (N3): a working document is labelled too; theory never

    sql = (f"SELECT p.passage_id FROM passages p WHERE p.section='body' AND {labelled_sql('p.doc_id')}" +
           (f" AND p.doc_id IN ({','.join('?' * len(doc_ids))})" if doc_ids else "") + " ORDER BY p.doc_id, p.seq")
    pids = [r[0] for r in ws.query(sql, doc_ids or [])]
    if passage_ids is not None:  # 0.16: only these (a code's passages labelled with its earlier wording)
        only = set(passage_ids)
        pids = [p for p in pids if p in only]
    with_cands = {r[0] for r in ws.query("SELECT DISTINCT passage_id FROM labels WHERE framework=? AND source IN "
                                         "('keywords','meaning','both')", (framework,))}
    chosen = pids if all_passages else [p for p in pids if p in with_cands]
    head = f"label:{framework}:"
    done = {r[0][len(head):] for r in ws.query(
        "SELECT task_id FROM tasks WHERE kind='label' AND status='done' AND substr(task_id, 1, ?) = ?",
        (len(f"label:{framework}:"), f"label:{framework}:"))}
    todo = [p for p in chosen if p not in done]
    # 0.11: passages of documents marked No AI are never read by a model; those marked Only a local AI are read by
    # the local model (or skipped without one: see run_labels)
    from . import access

    lv = access.levels(ws)
    doc_of = access.doc_of_passages(ws._conn(), todo) if todo else {}
    no_ai = [p for p in todo if lv.get(doc_of.get(p), "none") == "none"]
    local = [p for p in todo if lv.get(doc_of.get(p)) == "local"]
    todo = [p for p in todo if p not in set(no_ai)]
    if limit:
        todo = todo[:int(limit)]
    return {"framework": framework, "passages": len(pids), "with_candidates": len([p for p in pids if p in with_cands]),
            "already_read": len([p for p in chosen if p in done]), "to_read": len(todo), "passage_ids": todo,
            "pass1": st, "no_ai": len(no_ai), "local": len(set(local) & set(todo))}


def make_label_tasks(ws: Workspace, framework: str, passage_ids: list[str], model: str,
                     all_passages: bool = False) -> int:
    """`label` tasks for these passages (each with its candidates, up to MAX_CANDIDATES)."""
    from .tasks import _insert_task

    fw = frameworks.get(framework, ws)
    n = 0
    with ws.connect() as cx:
        for pid in passage_ids:
            r = cx.execute("SELECT p.*, d.title, q.text AS prev FROM passages p JOIN documents d ON d.doc_id=p.doc_id "
                           "LEFT JOIN passages q ON q.doc_id=p.doc_id AND q.seq=p.seq - 1 WHERE p.passage_id=?",
                           (pid,)).fetchone()
            if r is None:
                continue
            cands = [c["code"] for c in candidates_of(ws, fw.name, pid)][:MAX_CANDIDATES]
            if not cands and all_passages:
                cands = [c["code"] for c in fw.suggest(r["text"], MAX_CANDIDATES)]
            payload = {"framework": fw.name, "framework_title": fw.title, "code_label": fw.label,
                       "directional": fw.directional, "passage_id": pid, "doc_id": r["doc_id"], "title": r["title"],
                       "page": r["page"], "text": r["text"], "context": (r["prev"] or "")[-500:],
                       "candidates": [{"code": c, "description": fw.codes[c].description,
                                       # 0.16: when to use the code and when not, only when the codebook says
                                       **({"include": fw.codes[c].include} if fw.codes[c].include else {}),
                                       **({"exclude": fw.codes[c].exclude} if fw.codes[c].exclude else {})}
                                      for c in cands if c in fw.codes]}
            n += _insert_task(cx, f"label:{fw.name}:{pid}", "label", model, payload)
    return n


def store_labels(cx, t, payload: dict, obj: dict, model: str) -> tuple[bool, list[str]]:
    """The handler of a `label` answer: every code must exist in the framework, every quote must be found in the
    passage; otherwise the answer is retried with the problems listed."""
    from .schema import LabelOut
    from .textutil import find_quote

    out = LabelOut.model_validate(obj)
    fw = frameworks.get(payload["framework"], _WsShim(cx))
    text = payload["text"]
    errors: list[str] = []
    rows = []
    seen = set()
    from .tasks import doc_span

    base = cx.execute("SELECT start, page FROM passages WHERE passage_id=?", (payload["passage_id"],)).fetchone()
    p_page = base["page"] if base else payload.get("page")
    for i, lb in enumerate(out.labels):
        code = fw.normalise(lb.code)
        if not code:
            errors.append(f"labels[{i}]: unknown code {lb.code!r} in {fw.title}; use a code exactly as listed")
            continue
        if code in seen:
            errors.append(f"labels[{i}]: the code {code} is listed twice; give one label per code")
            continue
        seen.add(code)
        hit = find_quote(text, lb.quote)
        if not hit:
            errors.append(f"labels[{i}]: quote not found in the passage: {lb.quote[:80]!r}")
            continue
        direction = lb.direction if payload.get("directional") else "not_stated"
        # 0.15: a passage of an earlier reading (a task kept by Read with the new reader) is placed in the new text
        start, end = doc_span(cx, payload["passage_id"], text, hit[0], hit[1])
        rows.append((label_id(fw.name, payload["passage_id"], code, "model"), payload["passage_id"], payload["doc_id"],
                     fw.name, code, lb.relevance, direction, lb.confidence, text[hit[0]:hit[1]], start, end, p_page,
                     "model", model, t["prompt_version"], lb.reason, None, None, None, t["task_id"], now()))
    if errors:
        return False, errors
    # 0.16: a label of a code the codebook no longer has (removed, or kept under its name by a merge) waits for its
    # code (codebooks.py): the new answer replaces the task's labels of the codebook's codes only
    for lid, code in cx.execute("SELECT label_id, code FROM labels WHERE task_id=? AND source='model'",
                                (t["task_id"],)).fetchall():
        if code in fw.codes:
            cx.execute("DELETE FROM labels WHERE label_id=?", (lid,))
    keep = {r[0] for r in cx.execute("SELECT label_id FROM labels WHERE task_id=?", (t["task_id"],))}
    rows = [r for r in rows if r[0] not in keep]
    cx.executemany(_INSERT_LABEL, [(*r, __version__) for r in rows])
    return True, []


class _WsShim:
    """frameworks.get needs a project folder for project codebooks; inside a handler only the connection is at hand."""

    def __init__(self, cx):
        path = cx.execute("PRAGMA database_list").fetchone()[2]
        from pathlib import Path

        self.root = Path(path).parent


def run_labels(ws: Workspace, framework: str, backend, model: str, doc_ids: list[str] | None = None,
               all_passages: bool = False, limit: int | None = None, progress: Callable | None = None,
               should_stop: Callable[[], bool] | None = None, passage_ids: list[str] | None = None) -> dict:
    """The model pass as a job: make the tasks, answer them one by one (resumable), record the run. `passage_ids`:
    only these passages (0.16)."""
    from . import runs, tasks

    from . import access

    plan = label_plan(ws, framework, doc_ids, all_passages, limit, passage_ids)
    readers = access.Readers(backend, model)
    dflt = access.default(ws)
    lv = access.levels(ws)
    doc_of = access.doc_of_passages(ws._conn(), plan["passage_ids"]) if plan["passage_ids"] else {}
    reader_of = {}
    skipped = 0
    for pid in plan["passage_ids"]:  # 0.11: each passage is read by a model its document's setting allows
        got = readers.for_level(lv.get(doc_of.get(pid), "none"))
        if got is None:
            skipped += 1
        else:
            reader_of[pid] = got
    plan["passage_ids"] = [p for p in plan["passage_ids"] if p in reader_of]
    make_label_tasks(ws, framework, plan["passage_ids"], model, all_passages)
    run_id = runs.start(ws, "label", framework, backend, model, len(plan["passage_ids"]))
    done = failed = 0
    change = {"confirmed": 0, "not_confirmed": 0, "added": 0}   # the keyword codes against the AI's, passage by passage
    import time

    for i, pid in enumerate(plan["passage_ids"], 1):
        if should_stop and should_stop():
            break
        tid = f"label:{framework}:{pid}"
        if progress:
            progress(i, len(plan["passage_ids"]))
        t0 = time.time()
        # its setting worked out again as its text is about to leave, as `tasks.run` does: a document's cap counts
        # what the passages before this one sent (and a passage Claude has read already adds nothing to it)
        with ws.connect() as cx:
            if access.recheck(cx, tid, dflt) is None:
                skipped += 1
                continue
        got = readers.for_task(ws, tid)
        if got is None:
            skipped += 1
            continue
        ok, _errs = tasks.run_one(ws, tid, got[0], got[1])
        if getattr(backend, "name", "") != "claude_code":  # by queue the connector measures (waiting is not reading)
            runs.timing(ws, "label", runs._routed(backend, "label", model), time.time() - t0)
        done += ok
        failed += not ok
        if ok:
            cand = {c["code"] for c in candidates_of(ws, framework, pid)}
            got = {r[0] for r in ws.query("SELECT code FROM labels WHERE framework=? AND passage_id=? AND source='model'",
                                          (framework, pid))}
            change["confirmed"] += len(cand & got)
            change["not_confirmed"] += len(cand - got)
            change["added"] += len(got - cand)
    if getattr(getattr(backend, "router", None), "route", "") == "local" and not (should_stop and should_stop()):
        tasks.run_stepups(ws, backend, ["label"], should_stop)  # the stronger model once, after the small one
    runs.finish(ws, run_id, done + failed)
    return {"framework": framework, "read": done, "failed": failed, "planned": len(plan["passage_ids"]),
            "stopped": bool(should_stop and should_stop()), "changes": change,
            "skipped_restricted": skipped + plan.get("no_ai", 0)}


# ---------------------------------------------------------------------------------------------
# what counts, and the views built on it
# ---------------------------------------------------------------------------------------------
def _decisions(ws: Workspace, ids: list[str] | None = None) -> dict[str, dict]:
    from .people import review_order

    sql = "SELECT item_id, decision, corrected, note, reviewer, decided_at FROM reviews WHERE item_kind='label'"
    out = {}
    order, oargs = review_order()  # 0.14: the last counts, and yours come after a colleague's
    for r in ws.query(f"{sql} {order}", oargs):
        out[r["item_id"]] = {"decision": r["decision"], "corrected": json.loads(r["corrected"]) if r["corrected"] else None,
                             "note": r["note"], "at": r["decided_at"]}
    return out


# 0.16: what `effective(light=True)` reads of each label: what the rule needs and what the grid and the counts show
_LIGHT = "l.label_id, l.passage_id, l.doc_id, l.code, l.source, l.confidence, l.relevance, l.direction"


def effective(ws: Workspace, framework: str, doc_ids: list[str] | None = None, passage_ids: list[str] | None = None,
              provisional: bool = True, code: str | None = None, light: bool = False) -> list[dict]:
    """The labels that count: per passage, the model's once the model read it, else the strong pass-1 candidates
    (when `provisional`); a person's rejection removes a label, a change replaces its fields, their own labels add,
    and a keyword label a person accepted or changed stays whether or not the model read the passage.
    `code` keeps the query to one code (the rule per passage and code is the same, so nothing else changes).
    0.16: `light` reads only the fields of `_LIGHT` (the same labels, for the grid and the counts: a quicker page)."""
    where, args = ["l.framework=?"], [framework]
    if doc_ids:
        where.append(f"l.doc_id IN ({','.join('?' * len(doc_ids))})")
        args += list(doc_ids)
    if passage_ids:
        where.append(f"l.passage_id IN ({','.join('?' * len(passage_ids))})")
        args += list(passage_ids)
    if code:
        where.append("l.code=?")
        args.append(code)
    cols = _LIGHT if light else "l.*, p.seq, p.start AS pstart"
    rows = [dict(r) for r in ws.query(f"SELECT {cols} FROM labels l JOIN passages p ON "
                                      f"p.passage_id=l.passage_id WHERE {' AND '.join(where)}", args)]
    head = f"label:{framework}:"
    read = {r[0][len(head):] for r in ws.query(
        "SELECT task_id FROM tasks WHERE kind='label' AND status='done' AND substr(task_id, 1, ?) = ?",
        (len(f"label:{framework}:"), f"label:{framework}:"))}
    dec = _decisions(ws)
    out = []
    for r in rows:
        d = dec.get(r["label_id"])
        r["decision"] = d["decision"] if d else None
        r["person_note"] = d["note"] if d else None
        if d and d["decision"] == "reject":
            continue
        if d and d["decision"] == "change" and d["corrected"]:
            for k in ("relevance", "direction"):
                if d["corrected"].get(k):
                    r[k] = d["corrected"][k]
        if r["source"] == "person":
            out.append(r)
        elif r["source"] == "model":
            out.append(r)
        elif d and d["decision"] in ("accept", "change"):
            # 0.14.3: a keyword label a person accepted or changed counts whether or not the AI has read the passage
            # ("your labels always count"); it was dropped once the AI had read it
            r["provisional"] = r["passage_id"] not in read
            out.append(r)
        elif r["passage_id"] not in read and provisional and (
                r["source"] == "both" or (r["confidence"] or 0) >= PROVISIONAL):
            r["provisional"] = True
            out.append(r)
    # one label per passage and code: a person's, then the model's, then pass 1
    rank = {"person": 0, "model": 1, "both": 2, "keywords": 3, "meaning": 4}
    best: dict[tuple, dict] = {}
    for r in out:
        k = (r["passage_id"], r["code"])
        if k not in best or rank[r["source"]] < rank[best[k]["source"]]:
            best[k] = r
    # 0.16 (K1): the labels of a code taken out of the codebook wait (codebooks.removed_codes): they do not count
    try:
        known = frameworks.get(framework, ws).codes
    except ValueError:
        known = None
    return [r for r in best.values() if known is None or r["code"] in known]


def codes_fp(fw: frameworks.Framework) -> str:
    """0.16: a fingerprint of the words each code is matched by, so the Profile page can say when the codebook changed
    since its keyword pass."""
    return _h(*(f"{c.code}\x00{fw.code_text(c.code)}" for c in fw.sorted_codes()))


def passages_with_code(ws: Workspace, framework: str, code: str) -> set[str]:
    fw = frameworks.get(framework, ws)
    c = (fw.normalise(code) if fw else code) or code
    return {r["passage_id"] for r in effective(ws, framework, code=c)}  # one code's labels only (0.11.1)


def doc_profile(ws: Workspace, framework: str, doc_id: str) -> dict:
    """One document's codes, ranked by the number of passages and their share of the document, each with where it
    occurs (pages, or the position for documents without pages) and its labelled passages."""
    from .claimcheck import locate

    fw = frameworks.get(framework, ws)
    d = ws.query("SELECT doc_id, title, n_pages, n_chars FROM documents WHERE doc_id=?", (doc_id,))
    if not d:
        raise KeyError(doc_id)
    d = dict(d[0])
    n_body = int(ws.scalar("SELECT COUNT(*) FROM passages WHERE doc_id=? AND section='body'", (doc_id,)) or 0)
    labs = effective(ws, framework, doc_ids=[doc_id])
    where = locate(ws, [(r["label_id"], r["passage_id"], r["start"]) for r in labs])
    by_code: dict[str, list] = defaultdict(list)
    for r in labs:
        by_code[r["code"]].append(r)
    codes = []
    for code, rs in by_code.items():
        passages = {r["passage_id"] for r in rs}
        items = []
        for r in sorted(rs, key=lambda r: (r["seq"], r["start"] or 0)):
            loc = where.get(r["label_id"]) or {}
            items.append({"label_id": r["label_id"], "passage_id": r["passage_id"], "page": r["page"],
                          "location": loc.get("location") or "", "position_pct": loc.get("position_pct"),
                          "source": r["source"], "provisional": bool(r.get("provisional")), "relevance": r["relevance"],
                          "direction": r["direction"], "confidence": r["confidence"], "quote": r["quote"],
                          "start": r["start"], "end": r["end"], "reason": r["reason"],
                          "matched": json.loads(r["matched_json"] or "[]"), "similarity": r["similarity"],
                          "model": r["model"], "decision": r.get("decision"), "note": r.get("person_note")})
        codes.append({"code": code, "description": fw.codes[code].description if code in fw.codes else "",
                      "group": fw.codes[code].group if code in fw.codes else "",
                      "group_name": fw.codes[code].group_name if code in fw.codes else "",
                      "passages": len(passages), "share": round(len(passages) / n_body, 4) if n_body else 0,
                      "main": sum(1 for r in rs if r["relevance"] == "main"),
                      "pages": sorted({r["page"] for r in rs if r["page"]}),
                      "positions": sorted({(where.get(r["label_id"]) or {}).get("position_pct") or 0 for r in rs}),
                      "items": items})
    codes.sort(key=lambda c: (-c["passages"], c["code"]))
    # a label task's id is its passage's ("label:<framework>:<doc_id>:<seq>", a tombstone "<doc_id>:r1-<seq>" after
    # a new reading): the document's tasks are a range of the ids' index, and only theirs are parsed (every label
    # task of the project was)
    head = f"label:{framework}:{doc_id}:"
    # (`+kind`, `+status`: not the index of kinds, which a project without statistics would choose)
    read = int(ws.scalar("SELECT COUNT(*) FROM tasks WHERE task_id >= ? AND task_id < ? AND +kind='label' AND "
                         "+status='done' AND json_extract(payload_json, '$.doc_id') = ?",
                         (head, head[:-1] + ";", doc_id)) or 0)
    return {"doc_id": doc_id, "title": d["title"], "framework": fw.name, "framework_title": fw.title,
            "code_label": fw.label, "directional": fw.directional, "n_pages": d["n_pages"], "passages": n_body,
            "read_by_model": read, "codes": codes, "pass1": pass1_status(ws, framework)}


def grid(ws: Workspace, framework: str, doc_ids: list[str] | None = None, level: str = "code",
         labs: list[dict] | None = None) -> dict:
    """Documents × codes: in each cell the number of passages of the document with that code (`level` "group":
    codes added up by their group, the 17 goals for the SDG targets). 0.16: `labs`, the labels that count for these
    documents when already known (`effective(..., light=True)`), so the profile page works them out once. 0.19.0
    (N3): a working document has its own row, marked `"working": true`, after the corpus's, and is never added into a
    code's `passages` or `documents`."""
    fw = frameworks.get(framework, ws)
    if labs is None:
        labs = effective(ws, framework, doc_ids=doc_ids, light=True)
    titles = {r["doc_id"]: r["title"] or "" for r in ws.query("SELECT doc_id, title FROM documents")}
    from .docrole import working_docs

    working = working_docs(ws._conn())   # 0.19.0 (N3): their own rows, never in the codes' totals
    cells: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for r in labs:
        key = r["code"]
        if level == "group" and key in fw.codes:
            key = fw.codes[key].group or key
        cells[r["doc_id"]][key].add(r["passage_id"])
    place: dict[str, int] = {}   # each code's place in the codebook's order (the first, as list.index found it)
    if level != "group":
        for i, c in enumerate(fw.sorted_codes()):
            place.setdefault(c.code, i)
    cols = sorted({k for row in cells.values() for k in row},
                  key=lambda k: frameworks._natural(k) if level == "group" else
                  (place[k] if k in fw.codes else 10 ** 6))
    # the corpus's documents first, most coded first; a working document's row after them (N3)
    docs = sorted(cells, key=lambda d: (d in working, -sum(len(v) for v in cells[d].values()), titles.get(d, "").lower()))
    corpus = [d for d in docs if d not in working]
    names = {}
    for c in cols:
        if level == "group":
            g = next((x for x in fw.codes.values() if x.group == c), None)
            names[c] = g.group_name if g else c
        else:
            names[c] = fw.codes[c].description if c in fw.codes else c
    totals = {c: sum(len(cells[d].get(c, ())) for d in corpus) for c in cols}
    return {"framework": fw.name, "framework_title": fw.title, "code_label": fw.label, "level": level,
            "codes": [{"code": c, "description": names[c], "passages": totals[c],
                       "documents": sum(1 for d in corpus if cells[d].get(c))} for c in cols],
            "documents": [{"doc_id": d, "title": titles.get(d, ""), "passages": len({p for v in cells[d].values() for p in v}),
                           **({"working": True} if d in working else {})} for d in docs],
            "cells": {d: {c: len(v) for c, v in row.items()} for d, row in cells.items()},
            "provisional": any(r.get("provisional") for r in labs), "labels": len(labs)}


def grid_table(g: dict) -> list[dict]:
    rows = []
    for d in g["documents"]:
        # 0.19.0 (N3): a working document's row says so, so a column's sum in a spreadsheet is not taken for the corpus's
        row = {"Document": (d["title"] or d["doc_id"]) + (" (your working document, not in the totals)"
                                                          if d.get("working") else "")}
        for c in g["codes"]:
            desc = " ".join((c.get("description") or "").split())
            head = f'{c["code"]} {desc[:40].rstrip()}{"…" if len(desc) > 40 else ""}'.strip()
            row[head] = g["cells"].get(d["doc_id"], {}).get(c["code"], "") or ""
        rows.append(row)
    return rows


def labels_table(ws: Workspace, framework: str, doc_ids: list[str] | None = None) -> list[dict]:
    """Every label that counts, with its quote and its reason or matched words (F6), for the Excel download."""
    from .claimcheck import locate

    fw = frameworks.get(framework, ws)
    labs = effective(ws, framework, doc_ids=doc_ids)
    titles = {r["doc_id"]: r["title"] or "" for r in ws.query("SELECT doc_id, title FROM documents")}
    where = locate(ws, [(r["label_id"], r["passage_id"], r["start"]) for r in labs])
    src = {"keywords": "keywords (no model)", "meaning": "meaning (no model)",
           "both": "keywords and meaning agree (no model)", "model": "the AI", "person": "you"}
    out = []
    for r in sorted(labs, key=lambda r: (titles.get(r["doc_id"], ""), r["seq"], r["code"])):
        matched = json.loads(r["matched_json"] or "[]")
        out.append({"Document": titles.get(r["doc_id"], ""), "Where": (where.get(r["label_id"]) or {}).get("location", ""),
                    "Code": r["code"], "Code text": fw.codes[r["code"]].description if r["code"] in fw.codes else "",
                    "Relevance": {"main": "main topic", "mentioned": "mentioned"}.get(r["relevance"] or "", ""),
                    "Direction": {"helps": "helps", "hinders": "hinders", "mixed": "mixed",
                                  "not_stated": "not stated"}.get(r["direction"] or "", ""),
                    "Labelled by": src.get(r["source"], r["source"]) + (" (provisional)" if r.get("provisional") else ""),
                    "Certainty": r["confidence"] if r["confidence"] is not None else "",
                    "Quote": r["quote"] or "", "Reason": r["reason"] or "",
                    "Matched words": ", ".join(matched), "Similarity": r["similarity"] or "",
                    "Your decision": r.get("decision") or "", "Your note": r.get("person_note") or "",
                    "AI model": r["model"] or "", "Prompt": r["prompt_version"] or ""})
    return out


def set_label(ws: Workspace, label_id_: str, decision: str, relevance: str | None = None,
              direction: str | None = None, note: str | None = None, reviewer: str = "") -> None:
    """A person's verdict on a label: agree (accept), change its relevance or direction, or reject it."""
    if decision not in ("accept", "reject", "change", "clear"):
        raise ValueError("decision must be accept, change, reject or clear.")
    if relevance is not None and relevance not in RELEVANCE:
        raise ValueError(f"relevance must be one of {', '.join(RELEVANCE)}.")
    if direction is not None and direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {', '.join(DIRECTIONS)}.")
    with ws.connect() as cx:
        row = cx.execute("SELECT * FROM labels WHERE label_id=?", (label_id_,)).fetchone()
        if row is None:
            raise KeyError(label_id_)
        if decision == "clear":  # 0.14: your own verdicts; a colleague's stay theirs (and yours stay taken back)
            from .people import forget_reviews

            mine, margs = mine_sql()
            forget_reviews(cx, review_ids=[r[0] for r in cx.execute(
                f"SELECT review_id FROM reviews WHERE item_kind='label' AND item_id=? AND {mine}", (label_id_, *margs))])
            return
        corrected = json.dumps({k: v for k, v in (("relevance", relevance), ("direction", direction)) if v}) \
            if decision == "change" else None
        proposed = json.dumps({"code": row["code"], "relevance": row["relevance"], "direction": row["direction"],
                               "confidence": row["confidence"], "source": row["source"]})
        cx.execute("INSERT INTO reviews(item_kind, item_id, field, proposed, decision, corrected, reviewer, note, "
                   "decided_at, person_id) VALUES ('label', ?, 'label', ?, ?, ?, ?, ?, ?, ?)",
                   (label_id_, proposed, decision, corrected, reviewer, (note or "").strip()[:2000] or None, now(), me()))


def add_label(ws: Workspace, framework: str, passage_id: str, code: str, quote: str | None = None,
              relevance: str = "main", direction: str = "not_stated", note: str | None = None) -> str:
    """A label of a person's own (it always counts)."""
    from .textutil import find_selection

    fw = frameworks.get(framework, ws)
    c = fw.normalise(code)
    if not c:
        raise ValueError(f"Unknown {fw.label} {code!r} in {fw.title}.")
    p = ws.query("SELECT * FROM passages WHERE passage_id=?", (passage_id,))
    if not p:
        raise KeyError(passage_id)
    p = p[0]
    q = s = e = None
    if quote:
        hit = find_selection(p["text"], quote)  # 0.14.3: a selection cutting a word is widened to whole words
        if not hit:
            raise ValueError("The quote must be text from this passage.")
        q, s, e = p["text"][hit[0]:hit[1]], p["start"] + hit[0], p["start"] + hit[1]
    lid = label_id(fw.name, passage_id, c, "person")
    with ws.connect() as cx:
        cx.execute(_INSERT_LABEL,
                   (lid, passage_id, p["doc_id"], fw.name, c, relevance, direction if fw.directional else "not_stated",
                    1.0, q, s, e, p["page"], "person", None, None, (note or "").strip()[:200] or "added by you", None,
                    None, None, None, now(), __version__))
    return lid


def calibration(ws: Workspace, framework: str | None = None) -> dict:
    """How often a person agreed with the model's labels, by the model's certainty (as for hypothesis grades)."""
    from .claimcheck import CALIBRATION_BINS

    dec = _decisions(ws)
    rows = []
    sql = "SELECT label_id, confidence FROM labels WHERE source='model'" + (" AND framework=?" if framework else "")
    for r in ws.query(sql, (framework,) if framework else ()):
        d = dec.get(r["label_id"])
        if d and d["decision"] in ("accept", "reject", "change") and r["confidence"] is not None:
            rows.append((float(r["confidence"]), d["decision"] != "reject"))
    edges = list(CALIBRATION_BINS) + [1.0000001]
    bins = [{"from": a, "to": min(1.0, b), "judged": 0, "agreed": 0, "rate": None} for a, b in zip(edges, edges[1:])]
    for c, ok in rows:
        for b, hi in zip(bins, edges[1:]):
            if b["from"] <= c < hi:
                b["judged"] += 1
                b["agreed"] += ok
                break
    for b in bins:
        b["rate"] = round(b["agreed"] / b["judged"], 3) if b["judged"] else None
    return {"bins": bins, "total": len(rows), "agreed": sum(ok for _c, ok in rows)}


# ---------------------------------------------------------------------------------------------
# reproducibility: label a sample again and compare (nothing is stored)
# ---------------------------------------------------------------------------------------------
def compare_sample(ws: Workspace, framework: str, backend, model: str, n: int = 50, seed: int = 0,
                   progress: Callable | None = None, should_stop: Callable[[], bool] | None = None) -> dict:
    """Label a sample of passages the model already labelled again with this model and these settings, without
    storing anything, and report the agreement with the earlier labels: kappa on "code present" over the candidate
    codes of each passage, and the share of passages with exactly the same codes.

    With Claude Code (0.8.1) the sample waits in the queue of a scratch copy of the project, on `model`, and the
    copy is removed afterwards (taskqueue.answer_on_copy): the project itself is not touched either way."""
    import random

    from . import prompts
    from .tasks import parse_json

    rows = ws.query("SELECT * FROM tasks WHERE kind='label' AND status='done' AND substr(task_id, 1, ?) = ? "
                    "ORDER BY task_id", (len(f"label:{framework}:"), f"label:{framework}:"))
    from . import access

    if getattr(backend, "name", "") != "claude_code":  # by queue, answer_on_copy leaves restricted ones out
        rows = [r for r in rows if access.may_read(ws, json.loads(r["payload_json"]), backend)]
    rng = random.Random(seed)
    sample = rng.sample(list(rows), min(n, len(rows)))
    if not sample:
        raise ValueError("No passage has model labels yet: there is nothing to compare with.")
    fw = frameworks.get(framework, ws)
    pairs = []
    same = 0
    compared = 0
    errors = 0
    queued = None
    if getattr(backend, "name", "") == "claude_code":
        from .taskqueue import answer_on_copy

        queued, _secs = answer_on_copy(ws, [(t["task_id"], "label", json.loads(t["payload_json"]), model)
                                            for t in sample], backend, f"compare labels {model}",
                                       should_stop=should_stop)
    for i, t in enumerate(sample, 1):
        if should_stop and should_stop():
            break
        if progress:
            progress(i, len(sample))
        payload = json.loads(t["payload_json"])
        before = {r["code"] for r in ws.query("SELECT code FROM labels WHERE task_id=? AND source='model'",
                                              (t["task_id"],))}
        try:
            if queued is not None:
                raw = queued.get(t["task_id"])
                if raw is None:
                    raise ValueError("not answered")
            else:
                access.sending(ws, payload, backend, "label (compare labels)", t["task_id"])
                raw = backend.complete("label", prompts.system_prompt("label"),
                                       prompts.user_prompt("label", payload), model, payload)
            obj = parse_json(raw)
        except Exception:
            errors += 1
            continue
        now_codes = set()
        for lb in obj.get("labels") or []:
            c = fw.normalise(lb.get("code")) if isinstance(lb, dict) else None
            if c:
                now_codes.add(c)
        universe = {c["code"] for c in payload.get("candidates", [])} | before | now_codes
        for c in universe:
            pairs.append((c in before, c in now_codes))
        same += before == now_codes
        compared += 1
    from .analysis import _prf

    tp = sum(a and b for a, b in pairs)
    fp = sum((not a) and b for a, b in pairs)
    fn = sum(a and not b for a, b in pairs)
    tn = len(pairs) - tp - fp - fn
    return {"framework": framework, "model": model, "compared": compared, "errors": errors,
            "kappa": _prf(tp, fp, fn, tn)["kappa"] if pairs else None,
            "same_codes": round(same / compared, 3) if compared else None}


def recall_at_candidates(ws: Workspace, framework: str, gold: dict[str, set[str]]) -> dict:
    """How often pass 1 has a person's codes among its candidates (this recall bounds the model pass)."""
    hit = total = 0
    per_passage = 0
    for pid, codes in gold.items():
        cands = {c["code"] for c in candidates_of(ws, framework, pid)}
        total += len(codes)
        hit += len(codes & cands)
        per_passage += bool(codes) and codes <= cands
    return {"codes": total, "found": hit, "recall": round(hit / total, 3) if total else None,
            "passages_all_found": round(per_passage / len(gold), 3) if gold else None}


def stats(ws: Workspace, framework: str, labs: list[dict] | None = None) -> dict:
    """How many labels count, in how many documents and passages, by where they come from. 0.16: `labs`, the labels
    that count in the whole project when already known (see `grid`)."""
    if labs is None:
        labs = effective(ws, framework, light=True)
    from .docrole import working_docs

    working = working_docs(ws._conn())   # 0.19.0 (N3): a working document's codes are never the corpus's
    if working:
        labs = [r for r in labs if r["doc_id"] not in working]
    return {"labels": len(labs), "documents": len({r["doc_id"] for r in labs}),
            "passages": len({r["passage_id"] for r in labs}),
            "by_source": dict(Counter(r["source"] for r in labs)), "pass1": pass1_status(ws, framework)}
