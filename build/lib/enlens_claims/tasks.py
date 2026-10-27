"""Model tasks: create, export to files, run against a backend, and validate + store results.

Every result is validated before it is stored. Quotes must be found in the text the model was given
(exact match after typography and whitespace normalisation); claims whose main quote is not found are
rejected, and a task whose output cannot be used is marked failed so it can be retried with the errors.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError

from . import prompts
from .retrieve import BM25, H2_RE
from .schema import ExpandOut, ExtractOut, ImpactClaimOut, InteractionOut, SplitOut, VerifyOut, VerifySetOut
from .sources import docs_for_target
from .store import Workspace, now
from .taxonomy import targets
from .textutil import find_quote, tokens

KINDS = ("split", "extract", "verify", "verify_set", "expand", "check")
MAX_ATTEMPTS = 3


def _h(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def _insert_task(cx, task_id: str, kind: str, model: str, payload: dict) -> bool:
    if cx.execute("SELECT 1 FROM tasks WHERE task_id=?", (task_id,)).fetchone():
        return False
    cx.execute("INSERT INTO tasks(task_id, kind, model, prompt_version, payload_json, status, attempts, created_at) "
               "VALUES (?,?,?,?,?,?,0,?)",
               (task_id, kind, model, prompts.VERSIONS[kind], json.dumps(payload, ensure_ascii=False), "pending", now()))
    return True


# ---------------------------------------------------------------------------------------------
# creating tasks
# ---------------------------------------------------------------------------------------------
def make_split(ws: Workspace, model: str | None = None) -> int:
    model = model or ws.config["models"]["split"]
    n = 0
    with ws.connect() as cx:
        for r in cx.execute("SELECT * FROM vca_targets WHERE justification != ''"):
            payload = {"target": r["target"], "description": r["description"], "justification": r["justification"],
                       "horizon": r["horizon"], "cells": {"production": r["production"], "transportation": r["transportation"],
                                                         "end_use": r["end_use"]}}
            n += _insert_task(cx, f"split:{r['target']}", "split", model, payload)
    return n


def select_per_target(ws: Workspace, n: int, only_screened: bool = True, hydrogen_only: bool = True) -> list[str]:
    """Passage ids: the top-n passages for each of the 169 SDG targets (BM25 on the target text).

    Bounds extraction cost on a large corpus while giving every target, not only the VCA's, the same chance.
    hydrogen_only keeps passages that name hydrogen or a derivative themselves or at the end of the passage
    before (which the task shows as CONTEXT); without it, general energy passages crowd out the value chain.
    """
    sql = ("SELECT p.passage_id, p.text, q.text AS prev FROM passages p LEFT JOIN passages q "
           "ON q.doc_id = p.doc_id AND q.seq = p.seq - 1 WHERE p.section='body'" + (" AND p.screened=1" if only_screened else ""))
    rows = ws.query(sql)
    if hydrogen_only:
        rows = [r for r in rows if H2_RE.search(r["text"]) or H2_RE.search((r["prev"] or "")[-500:])]
    if not rows:
        return []
    bm = BM25([tokens(r["text"]) for r in rows])
    chosen: dict[str, None] = {}
    for t in targets().values():
        for i, _s in bm.top(tokens(f"{t.description} {t.goal_name}"), n):
            chosen.setdefault(rows[i]["passage_id"], None)
    return list(chosen)


def make_extract(ws: Workspace, model: str | None = None, doc_ids: Iterable[str] | None = None,
                 only_screened: bool = True, limit: int | None = None, per_target: int | None = None,
                 hydrogen_only: bool = True) -> int:
    """Extraction tasks for screened passages; with per_target, only the top passages for each SDG target."""
    model = model or ws.config["models"]["extract"]
    keep = set(select_per_target(ws, per_target, only_screened, hydrogen_only)) if per_target else None
    sql = "SELECT p.*, d.title, d.doi FROM passages p JOIN documents d ON d.doc_id=p.doc_id WHERE p.section='body'"
    args: list[Any] = []
    if only_screened:
        sql += " AND p.screened=1"
    if doc_ids:
        ids = list(doc_ids)
        sql += f" AND p.doc_id IN ({','.join('?' * len(ids))})"
        args += ids
    sql += " ORDER BY p.doc_id, p.seq"
    n = 0
    with ws.connect() as cx:
        rows = list(cx.execute(sql, args))
        for r in rows:
            if limit is not None and n >= limit:
                break
            if keep is not None and r["passage_id"] not in keep:
                continue
            prev = cx.execute("SELECT text FROM passages WHERE doc_id=? AND seq=?", (r["doc_id"], r["seq"] - 1)).fetchone()
            payload = {"passage_id": r["passage_id"], "doc_id": r["doc_id"], "title": r["title"], "doi": r["doi"],
                       "page": r["page"], "text": r["text"], "context": (prev[0][-500:] if prev else "")}
            n += _insert_task(cx, f"extract:{r['passage_id']}", "extract", model, payload)
    return n


def _diverse_top(bm: BM25, q: list[str], doc_of: list[str], k: int, per_doc: int) -> list[int]:
    """Top-k passage indexes, at most per_doc from one document before the rest are filled by score."""
    ranked = bm.top(q, max(k * 6, 40))
    picked: list[int] = []
    count: dict[str, int] = {}
    for i, _s in ranked:
        if len(picked) >= k:
            break
        if count.get(doc_of[i], 0) < per_doc:
            picked.append(i)
            count[doc_of[i]] = count.get(doc_of[i], 0) + 1
    for i, _s in ranked:
        if len(picked) >= k:
            break
        if i not in picked:
            picked.append(i)
    return picked


def make_verify_vca(ws: Workspace, model: str | None = None, k: int | None = None, beyond_cited: bool = False,
                    pairwise: bool = False, per_doc: int = 2) -> dict[str, int]:
    """Check each VCA claim against the top-k passages from the sources cited for its target.

    Default: one 'verify_set' task per claim showing all k passages (at most per_doc from one document first),
    graded supports / partially_supports / refutes. pairwise=True makes one 'verify' task per claim and passage.
    """
    model = model or ws.config["models"]["verify"]
    k = k or int(ws.config["thresholds"]["verify_top_k"])
    made, missing = 0, 0
    tdesc = targets()
    vcs = ws.query("SELECT * FROM vca_claims ORDER BY target, seq")
    all_docs = [r["doc_id"] for r in ws.query("SELECT doc_id FROM documents")]
    docs_by_target = {t: (all_docs if beyond_cited else docs_for_target(ws, t)) for t in {vc["target"] for vc in vcs}}
    with ws.connect() as cx:
        for vc in vcs:
            doc_ids = docs_by_target[vc["target"]]
            if not doc_ids:
                missing += 1
                continue
            ps = list(cx.execute(
                f"SELECT p.*, d.title FROM passages p JOIN documents d ON d.doc_id=p.doc_id "
                f"WHERE p.section='body' AND p.doc_id IN ({','.join('?' * len(doc_ids))}) ORDER BY p.passage_id", doc_ids))
            if not ps:
                missing += 1
                continue
            bm = BM25([tokens(p["text"]) for p in ps])
            base = {"subject_kind": "vca_claim", "subject_id": vc["vca_claim_id"], "target": vc["target"],
                    "target_description": tdesc[vc["target"]].description, "claim": vc["text"]}
            if pairwise:
                q = tokens(f"{vc['text']} {vc['quote']} {tdesc[vc['target']].description}")
                for i, _s in bm.top(q, k):
                    p = ps[i]
                    payload = {**base, "passage_id": p["passage_id"], "doc_id": p["doc_id"], "title": p["title"],
                               "page": p["page"], "text": p["text"]}
                    made += _insert_task(cx, f"verify:{vc['vca_claim_id']}:{p['passage_id']}", "verify", model, payload)
                continue
            picked = _diverse_top(bm, tokens(f"{vc['text']} {vc['quote']}"), [p["doc_id"] for p in ps], k, per_doc)
            payload = {**base, "passages": [{"passage_id": ps[i]["passage_id"], "doc_id": ps[i]["doc_id"],
                                             "title": ps[i]["title"], "page": ps[i]["page"], "text": ps[i]["text"]}
                                            for i in picked]}
            # After new documents are added the best passages can change: then the claim gets a further task
            # for the new set (earlier answers are kept); an unchanged set is not asked again.
            tid = f"verify_set:{vc['vca_claim_id']}"
            ids = sorted(p["passage_id"] for p in payload["passages"])
            earlier = cx.execute("SELECT task_id, payload_json FROM tasks WHERE kind='verify_set' AND (task_id=? OR task_id LIKE ?) "
                                 "AND task_id NOT LIKE '%:audit:%'", (tid, tid + ":set:%")).fetchall()
            if any(sorted(x["passage_id"] for x in json.loads(r["payload_json"])["passages"]) == ids for r in earlier):
                continue
            if earlier:
                tid = f"{tid}:set:{_h(*ids)}"
            made += _insert_task(cx, tid, "verify_set", model, payload)
    return {"tasks": made, "vca_claims_without_sources": missing}


def make_verify_claims(ws: Workspace, model: str | None = None, sample: float = 1.0, seed: int = 0) -> int:
    """Second check of extracted claims against their own passage (for example with a different model)."""
    model = model or ws.config["models"]["verify"]
    rng = random.Random(seed)
    tdesc = targets()
    n = 0
    with ws.connect() as cx:
        rows = list(cx.execute(
            "SELECT c.*, p.text AS ptext, p.page, d.title FROM claims c JOIN passages p ON p.passage_id=c.passage_id "
            "JOIN documents d ON d.doc_id=c.doc_id WHERE c.status IN ('auto','needs_review') ORDER BY c.claim_id"))
        for c in rows:
            if rng.random() > sample:
                continue
            t = cx.execute("SELECT target FROM claim_targets WHERE claim_id=? ORDER BY target LIMIT 1", (c["claim_id"],)).fetchone()
            if not t:
                continue
            payload = {"subject_kind": "claim", "subject_id": c["claim_id"], "target": t[0],
                       "target_description": tdesc[t[0]].description, "claim": c["claim"], "passage_id": c["passage_id"],
                       "doc_id": c["doc_id"], "title": c["title"], "page": c["page"], "text": c["ptext"]}
            n += _insert_task(cx, f"verify:{c['claim_id']}:{model}", "verify", model, payload)
    return n


def make_audit_vca(ws: Workspace, model: str, sample: float = 0.1, seed: int = 0) -> int:
    """Second opinion on a sample of answered VCA checks: the same claim and passages, another model.

    Audit answers are stored under subject_kind 'vca_claim_audit', so they never change a claim's status;
    analysis.audit_summary compares them with the first answers.
    """
    rng = random.Random(seed)
    n = 0
    with ws.connect() as cx:
        rows = list(cx.execute("SELECT task_id, payload_json FROM tasks WHERE kind='verify_set' AND status='done' "
                               "AND task_id NOT LIKE '%:audit:%' ORDER BY task_id"))
        for r in rows:
            if rng.random() > sample:
                continue
            payload = json.loads(r["payload_json"])
            payload["subject_kind"] = "vca_claim_audit"
            n += _insert_task(cx, f"{r['task_id']}:audit:{model}", "verify_set", model, payload)
    return n


# ---------------------------------------------------------------------------------------------
# parsing and validation
# ---------------------------------------------------------------------------------------------
def parse_json(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    s = str(raw).strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        a, b = s.find("{"), s.rfind("}")
        if a < 0 or b <= a:
            raise ValueError("no JSON object in the response")
        obj = json.loads(s[a:b + 1])
    if not isinstance(obj, dict):
        raise ValueError("the response must be a JSON object")
    return obj


def _errs(e: ValidationError) -> list[str]:
    return [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()]


def ingest_result(ws: Workspace, task_id: str, raw: Any, model: str | None = None) -> tuple[bool, list[str]]:
    with ws.connect() as cx:
        t = cx.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not t:
            return False, [f"unknown task {task_id}"]
        payload = json.loads(t["payload_json"])
        model = model or t["model"]
        attempt = int(t["attempts"]) + 1
        errors: list[str] = []
        ok = False
        try:
            obj = parse_json(raw)
            handler = HANDLERS[t["kind"]]
            ok, errors = handler(cx, t, payload, obj, model)
        except (ValueError, ValidationError) as e:
            errors = _errs(e) if isinstance(e, ValidationError) else [str(e)]
            ok = False
        status = "done" if ok else ("failed" if attempt >= MAX_ATTEMPTS else "retry")
        cx.execute("UPDATE tasks SET status=?, attempts=? WHERE task_id=?", (status, attempt, task_id))
        seq = cx.execute("SELECT COALESCE(MAX(attempt), 0) + 1 FROM results WHERE task_id=?", (task_id,)).fetchone()[0]
        cx.execute("INSERT INTO results VALUES (?,?,?,?,?,?,?,?,?)",
                   (task_id, seq, t["kind"], model, t["prompt_version"],
                    raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False), int(ok), json.dumps(errors), now()))
    return ok, errors


def _store_extract(cx, t, payload, obj, model) -> tuple[bool, list[str]]:
    out = ExtractOut.model_validate(obj)
    text = payload["text"]
    base = cx.execute("SELECT start, page FROM passages WHERE passage_id=?", (payload["passage_id"],)).fetchone()
    p_start, p_page = (base["start"], base["page"]) if base else (0, payload.get("page"))
    thr = _meta_float(cx, "accept_confidence", 0.8)
    # replace anything stored from an earlier attempt of this task
    old = [r[0] for r in cx.execute("SELECT claim_id FROM claims WHERE task_id=?", (t["task_id"],))]
    for cid in old:
        for tbl in ("claim_targets", "evidence"):
            cx.execute(f"DELETE FROM {tbl} WHERE claim_id=?", (cid,))
    cx.execute("DELETE FROM claims WHERE task_id=?", (t["task_id"],))
    cx.execute("DELETE FROM interactions WHERE claim_id LIKE ? AND kind='stated'", (t["task_id"] + "%",))
    errors: list[str] = []
    stored = 0
    for i, raw_claim in enumerate(out.claims):
        try:
            c = ImpactClaimOut.model_validate(raw_claim)
        except ValidationError as e:
            errors += [f"claims[{i}].{m}" for m in _errs(e)]
            continue
        found = []
        for ev in c.evidence:
            hit = find_quote(text, ev.quote)
            if hit:
                found.append((ev, hit))
            else:
                errors.append(f"claims[{i}]: quote not found in the passage: {ev.quote[:80]!r}")
        if not any(ev.field == "claim" for ev, _ in found):
            errors.append(f"claims[{i}]: no 'claim' quote was found in the passage; claim dropped")
            continue
        cid = f"c{_h(t['task_id'], str(i))}"
        status = "auto" if c.confidence >= thr else "needs_review"
        reason = "" if status == "auto" else f"confidence {c.confidence:.2f} below {thr:.2f}"
        cx.execute("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (cid, t["task_id"], payload["doc_id"], payload["passage_id"], c.claim, c.activity, c.segment, c.place,
                    json.dumps(c.countries, ensure_ascii=False), c.scale, c.side, c.horizon, c.condition, c.policy_lever,
                    c.confidence, model, t["prompt_version"], status, reason))
        for te in c.targets:
            cx.execute("INSERT OR REPLACE INTO claim_targets VALUES (?,?,?,?)", (cid, te.target, te.direction, te.influence))
        for ev, (s, e, kind) in found:
            cx.execute("INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?)",
                       (cid, ev.field, text[s:e], payload["doc_id"], p_start + s, p_start + e, p_page, kind))
        stored += 1
    for j, raw_i in enumerate(out.interactions):
        try:
            it = InteractionOut.model_validate(raw_i)
        except ValidationError as e:
            errors += [f"interactions[{j}].{m}" for m in _errs(e)]
            continue
        hit = find_quote(text, it.quote)
        if not hit:
            errors.append(f"interactions[{j}]: quote not found in the passage")
            continue
        s, e, _k = hit
        cx.execute("INSERT OR REPLACE INTO interactions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (f"i{_h(t['task_id'], str(j))}", f"{t['task_id']}#{j}", payload["doc_id"], it.from_target, it.to_target,
                    it.score, text[s:e], p_start + s, p_start + e, p_page, "stated"))
    ok = stored > 0 or not out.claims  # an empty answer is valid; all claims failing is not
    return ok, errors


def _store_split(cx, t, payload, obj, model) -> tuple[bool, list[str]]:
    out = SplitOut.model_validate(obj)
    just = payload["justification"]
    errors = []
    rows = []
    for i, c in enumerate(out.claims):
        if not find_quote(just, c.quote):
            errors.append(f"claims[{i}]: quote not found in the justification: {c.quote[:80]!r}")
            continue
        rows.append((f"{payload['target']}#{i + 1}", payload["target"], i + 1, c.text, c.quote, c.segment, c.direction,
                     c.place, c.horizon, c.condition, model, t["prompt_version"]))
    if not rows:
        return False, errors or ["no usable claims"]
    if errors:
        return False, errors  # partial splits distort the evaluation; ask again
    cx.execute("DELETE FROM vca_claims WHERE target=?", (payload["target"],))
    cx.executemany("INSERT INTO vca_claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return True, []


def _store_verify(cx, t, payload, obj, model) -> tuple[bool, list[str]]:
    v = VerifyOut.model_validate(obj)
    text = payload["text"]
    s = e = None
    quote = None
    if v.verdict != "not_enough_info":
        if not v.quote:
            return False, [f"verdict {v.verdict} needs a quote from the passage"]
        hit = find_quote(text, v.quote)
        if not hit:
            return False, [f"quote not found in the passage: {v.quote[:80]!r}"]
        base = cx.execute("SELECT start FROM passages WHERE passage_id=?", (payload["passage_id"],)).fetchone()
        off = base[0] if base else 0
        s, e = off + hit[0], off + hit[1]
        quote = text[hit[0]:hit[1]]
    vid = f"v{_h(t['task_id'])}"
    cx.execute("INSERT OR REPLACE INTO verifications VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (vid, payload["subject_kind"], payload["subject_id"], payload["passage_id"], payload["doc_id"], v.verdict,
                v.confidence, quote, s, e, payload.get("page"), model, t["prompt_version"]))
    if payload["subject_kind"] == "claim":
        thr = _meta_float(cx, "support_confidence", 0.6)
        if not (v.verdict == "supports" and v.confidence >= thr):
            cx.execute("UPDATE claims SET status='needs_review', status_reason=? WHERE claim_id=? AND status IN ('auto','needs_review')",
                       (f"second check ({model}): {v.verdict} {v.confidence:.2f}", payload["subject_id"]))
    return True, []


def _store_verify_set(cx, t, payload, obj, model) -> tuple[bool, list[str]]:
    v = VerifySetOut.model_validate(obj)
    passages = payload["passages"]
    errors: list[str] = []
    graded: dict[int, tuple] = {}
    for j, ev in enumerate(v.evidence):
        if ev.passage > len(passages):
            errors.append(f"evidence[{j}]: there is no passage P{ev.passage} (P1 to P{len(passages)} were shown)")
            continue
        p = passages[ev.passage - 1]
        hit = find_quote(p["text"], ev.quote)
        if not hit:
            errors.append(f"evidence[{j}]: quote not found in passage P{ev.passage}: {ev.quote[:80]!r}")
            continue
        if ev.passage in graded:
            errors.append(f"evidence[{j}]: passage P{ev.passage} is listed twice; give one grade per passage")
            continue
        graded[ev.passage] = (ev, hit)
    if errors:
        return False, errors
    for n, p in enumerate(passages, 1):
        base = cx.execute("SELECT start FROM passages WHERE passage_id=?", (p["passage_id"],)).fetchone()
        off = base[0] if base else 0
        if n in graded:
            ev, hit = graded[n]
            row = (ev.verdict, ev.confidence, p["text"][hit[0]:hit[1]], off + hit[0], off + hit[1])
        else:
            row = ("not_enough_info", None, None, None, None)
        cx.execute("INSERT OR REPLACE INTO verifications VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (f"v{_h(t['task_id'], p['passage_id'])}", payload["subject_kind"], payload["subject_id"],
                    p["passage_id"], p["doc_id"], *row[:3], row[3], row[4], p.get("page"), model, t["prompt_version"]))
    return True, []


def _store_expand(cx, t, payload, obj, model) -> tuple[bool, list[str]]:
    out = ExpandOut.model_validate(obj)
    if not out.terms:
        return False, ["give at least one search term"]
    cx.execute("UPDATE user_claims SET terms_json=? WHERE claim_id=?", (json.dumps(out.terms, ensure_ascii=False), payload["claim_id"]))
    return True, []


def _store_check(cx, t, payload, obj, model) -> tuple[bool, list[str]]:
    ok, errors = _store_verify_set(cx, t, payload, obj, model)
    if ok:
        cx.execute("UPDATE user_claims SET rationale=?, model=? WHERE claim_id=?",
                   ((obj.get("rationale") if isinstance(obj, dict) else None), model, payload["subject_id"]))
    return ok, errors


HANDLERS = {"extract": _store_extract, "split": _store_split, "verify": _store_verify, "verify_set": _store_verify_set,
            "expand": _store_expand, "check": _store_check}


# ---------------------------------------------------------------------------------------------
# running: a backend directly, or files for an outside worker
# ---------------------------------------------------------------------------------------------
def _meta_float(cx, key: str, default: float) -> float:
    row = cx.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    try:
        return float(json.loads(row[0])) if row else default
    except (TypeError, ValueError):
        return default


def _sync_thresholds(ws: Workspace) -> None:
    th = ws.config["thresholds"]
    with ws.connect() as cx:
        for key in ("accept_confidence", "support_confidence"):
            cx.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, json.dumps(float(th[key]))))


def pending(ws: Workspace, kind: str, limit: int | None = None, statuses=("pending", "retry")) -> list:
    q = f"SELECT * FROM tasks WHERE kind=? AND status IN ({','.join('?' * len(statuses))}) ORDER BY task_id"
    rows = ws.query(q, (kind, *statuses))
    return rows[:limit] if limit else rows


def _last_errors(ws: Workspace, task_id: str) -> list[str]:
    r = ws.query("SELECT errors_json, valid FROM results WHERE task_id=? ORDER BY attempt DESC LIMIT 1", (task_id,))
    return json.loads(r[0][0]) if r and not r[0][1] else []


def render(ws: Workspace, task) -> tuple[str, str]:
    payload = json.loads(task["payload_json"])
    user = prompts.user_prompt(task["kind"], payload)
    errs = _last_errors(ws, task["task_id"]) if task["attempts"] else []
    if errs:
        user += "\n\nYOUR PREVIOUS ANSWER HAD THESE PROBLEMS. Fix them:\n- " + "\n- ".join(errs[:10])
    return prompts.system_prompt(task["kind"]), user


def run_one(ws: Workspace, task_id: str, backend, model: str | None = None) -> tuple[bool, list[str]]:
    """Answer one task now, retrying with the problems listed, up to three attempts. Backend errors propagate."""
    errors: list[str] = []
    for _ in range(MAX_ATTEMPTS):
        t = ws.query("SELECT * FROM tasks WHERE task_id=?", (task_id,))[0]
        if t["status"] == "done":
            return True, []
        if t["status"] == "failed":
            break
        system, user = render(ws, t)
        raw = backend.complete(t["kind"], system, user, model or t["model"], json.loads(t["payload_json"]))
        used = "baseline" if getattr(backend, "name", "") == "baseline" else (model or t["model"])
        ok, errors = ingest_result(ws, task_id, raw, model=used)
        if ok:
            return True, errors
    return False, errors


def run(ws: Workspace, kind: str, backend, limit: int | None = None, model: str | None = None) -> dict[str, int]:
    _sync_thresholds(ws)
    stats = {"done": 0, "retry": 0, "failed": 0}
    for _round in range(MAX_ATTEMPTS):
        todo = pending(ws, kind, limit)
        if not todo:
            break
        for t in todo:
            system, user = render(ws, t)
            payload = json.loads(t["payload_json"])
            raw = backend.complete(kind, system, user, model or t["model"], payload)
            used = "baseline" if backend.name == "baseline" else (model or t["model"])
            ingest_result(ws, t["task_id"], raw, model=used)
    for r in ws.query("SELECT status, COUNT(*) FROM tasks WHERE kind=? GROUP BY status", (kind,)):
        stats[r[0]] = r[1]
    return stats


WORKER_GUIDE = """# Worker guide (file queue)

You are answering model tasks for the ENLENS claims pipeline.

1. Read SYSTEM.md in this folder once. It is the instruction for every task in this folder.
2. Each line of a batch_*.jsonl file is one task: {"task_id": ..., "user": "..."}. Treat `user` as the user message.
3. For each task write one line to the matching results file (same name, under results/<kind>/):
   {"task_id": "<same id>", "model": "<the model you are>", "output": { ...the JSON object SYSTEM.md asks for... }}
4. Quotes must be copied exactly from the text in the task. Answers with quotes that are not in the text are rejected.
5. If a task shows "YOUR PREVIOUS ANSWER HAD THESE PROBLEMS", fix exactly those problems.
6. Judge every task yourself, one by one. Use code only to write and check the JSON, never to produce answers
   (no keyword rules or batch heuristics standing in for reading the text).
7. Before handing the file back, run `enlens --ws <workspace> check-results <your results file>`. It applies the
   same checks as the import without storing anything. Fix every line it reports and run it again until it is clean.
"""


def export(ws: Workspace, kind: str, batch_size: int = 25, limit: int | None = None) -> list[Path]:
    _sync_thresholds(ws)
    todo = pending(ws, kind, limit)
    out_dir = ws.root / "tasks" / kind
    out_dir.mkdir(parents=True, exist_ok=True)
    (ws.root / "results" / kind).mkdir(parents=True, exist_ok=True)
    (out_dir / "SYSTEM.md").write_text(prompts.system_prompt(kind), encoding="utf-8")
    (out_dir / "WORKER_GUIDE.md").write_text(WORKER_GUIDE, encoding="utf-8")
    existing = sorted(out_dir.glob("batch_*.jsonl"))
    start = len(existing)
    files = []
    for b in range(0, len(todo), batch_size):
        path = out_dir / f"batch_{start + b // batch_size + 1:04d}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for t in todo[b:b + batch_size]:
                _sys, user = render(ws, t)
                f.write(json.dumps({"task_id": t["task_id"], "user": user}, ensure_ascii=False) + "\n")
        files.append(path)
    with ws.connect() as cx:
        for t in todo:
            cx.execute("UPDATE tasks SET status='exported' WHERE task_id=?", (t["task_id"],))
    return files


def import_results(ws: Workspace, paths: Iterable[str | Path], model: str | None = None) -> dict[str, int]:
    _sync_thresholds(ws)
    stats = {"lines": 0, "ok": 0, "invalid": 0, "unknown": 0, "skipped_done": 0}
    files: list[Path] = []
    for p in paths:
        p = Path(p)
        files += sorted(p.rglob("*.jsonl")) if p.is_dir() else [p]
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            stats["lines"] += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                stats["invalid"] += 1
                continue
            tid = rec.get("task_id")
            st = ws.scalar("SELECT status FROM tasks WHERE task_id=?", (tid,))
            if st is None:
                stats["unknown"] += 1
                continue
            if st == "done":
                stats["skipped_done"] += 1
                continue
            raw = rec.get("output", rec.get("text", ""))
            ok, _errs = ingest_result(ws, tid, raw, model=rec.get("model") or model)
            stats["ok" if ok else "invalid"] += 1
    return stats


def check_results(ws: Workspace, paths: Iterable[str | Path]) -> dict[str, Any]:
    """Validate worker answers exactly as import-results would, without storing anything.

    Workers run this on their own results file and fix the reported lines before handing it back.
    """
    import sqlite3

    files: list[Path] = []
    for p in paths:
        p = Path(p)
        files += sorted(p.rglob("*.jsonl")) if p.is_dir() else [p]
    out: dict[str, Any] = {"lines": 0, "ok": 0, "problems": []}
    cx = sqlite3.connect(ws.db_path, timeout=60)
    cx.row_factory = sqlite3.Row
    try:
        for f in files:
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                out["lines"] += 1
                where = f"{f.name}:{n}"
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as e:
                    out["problems"].append({"line": where, "errors": [f"not valid JSON: {e}"]})
                    continue
                t = cx.execute("SELECT * FROM tasks WHERE task_id=?", (rec.get("task_id"),)).fetchone()
                if not t:
                    out["problems"].append({"line": where, "errors": [f"unknown task_id {rec.get('task_id')!r}"]})
                    continue
                errors: list[str] = []
                try:
                    obj = parse_json(rec.get("output", rec.get("text", "")))
                    handler = HANDLERS[t["kind"]]
                    ok, errors = handler(cx, t, json.loads(t["payload_json"]), obj, rec.get("model") or t["model"])
                except (ValueError, ValidationError) as e:
                    ok, errors = False, (_errs(e) if isinstance(e, ValidationError) else [str(e)])
                finally:
                    cx.rollback()  # never keep what the handler wrote
                if ok and not errors:
                    out["ok"] += 1
                else:
                    out["problems"].append({"line": where, "task_id": t["task_id"], "accepted": ok, "errors": errors})
    finally:
        cx.close()
    return out


def refresh(ws: Workspace, kind: str, model: str | None = None) -> int:
    """Queue tasks again under the current prompt version (and optionally another model). Old results are kept."""
    version = prompts.VERSIONS[kind]
    with ws.connect() as cx:
        if model:
            cur = cx.execute("UPDATE tasks SET status='pending', attempts=0, prompt_version=?, model=? "
                             "WHERE kind=? AND (prompt_version != ? OR model != ?)", (version, model, kind, version, model))
        else:
            cur = cx.execute("UPDATE tasks SET status='pending', attempts=0, prompt_version=? WHERE kind=? AND prompt_version != ?",
                             (version, kind, version))
        return cur.rowcount


def requeue(ws: Workspace, kind: str | None = None) -> int:
    """Put exported tasks that never got an answer back in the queue."""
    with ws.connect() as cx:
        if kind:
            cur = cx.execute("UPDATE tasks SET status='pending' WHERE status='exported' AND kind=?", (kind,))
        else:
            cur = cx.execute("UPDATE tasks SET status='pending' WHERE status='exported'")
        return cur.rowcount
