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
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError

from . import prompts
from .retrieve import BM25, H2_RE
from .schema import (CheckOut, DecomposeOut, ExpandOut, ExtractOut, ImpactClaimOut, InteractionOut, SplitOut,
                     VerifyOut, VerifySetOut)
from .sources import docs_for_target
from .store import Workspace, now
from .taxonomy import targets
from .textutil import find_quote, normalise
from .textutil import tokens_v1 as tokens  # the SDG pack keeps the 0.4 tokenizer, so its selections do not change

KINDS = ("split", "extract", "verify", "verify_set", "expand", "check", "decompose", "reread", "second",
         "label", "link", "theme", "resolve")
# 0.7: the kinds whose passages are the user's own corpus at large (not a check they started): handing them to an
# outside worker through the file queue sends those passages off this computer, so the command line says so
CORPUS_KINDS = ("label", "link", "theme", "resolve")
MAX_ATTEMPTS = 3


def _h(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


# 0.8: while a thread works "by queue" (Claude Code answers the tasks, see taskqueue), every task it creates or
# puts back to pending is handed to the queue: queued=1 and the time. Set with `queueing()`.
_QUEUE = threading.local()


@contextmanager
def queueing(on: bool = True):
    """Within this block, tasks this thread creates (or sends back to pending) wait in the queue for an outside AI."""
    before = getattr(_QUEUE, "on", False)
    _QUEUE.on = bool(on)
    try:
        yield
    finally:
        _QUEUE.on = before


def queue_mode() -> bool:
    return bool(getattr(_QUEUE, "on", False))


def mark_queued(cx, task_ids: Iterable[str]) -> int:
    """Hand these tasks to the queue (no change for tasks already in it)."""
    n = 0
    for tid in task_ids:
        n += cx.execute("UPDATE tasks SET queued=1, queued_at=COALESCE(queued_at, ?) WHERE task_id=? AND "
                        "COALESCE(queued, 0)=0", (now(), tid)).rowcount
    return n


def _insert_task(cx, task_id: str, kind: str, model: str, payload: dict) -> bool:
    if cx.execute("SELECT 1 FROM tasks WHERE task_id=?", (task_id,)).fetchone():
        if queue_mode():  # an existing task asked for again (a stopped run started anew): into the queue
            cx.execute("UPDATE tasks SET queued=1, queued_at=COALESCE(queued_at, ?) WHERE task_id=? AND status IN "
                       "('pending', 'retry')", (now(), task_id))
        return False
    q = queue_mode()
    cx.execute("INSERT INTO tasks(task_id, kind, model, prompt_version, payload_json, status, attempts, created_at, "
               "queued, queued_at) VALUES (?,?,?,?,?,?,0,?,?,?)",
               (task_id, kind, model, prompts.VERSIONS[kind], json.dumps(payload, ensure_ascii=False), "pending", now(),
                int(q), now() if q else None))
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
    sql = ("SELECT p.*, d.title, d.doi, q.text AS prev FROM passages p JOIN documents d ON d.doc_id=p.doc_id "
           "LEFT JOIN passages q ON q.doc_id=p.doc_id AND q.seq=p.seq - 1 WHERE p.section='body'")
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
            payload = {"passage_id": r["passage_id"], "doc_id": r["doc_id"], "title": r["title"], "doi": r["doi"],
                       "page": r["page"], "text": r["text"], "context": (r["prev"] or "")[-500:]}
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
    # the passages of a set of sources and their index, built once per set (every target, with --beyond-cited)
    indexes: dict[tuple, tuple[list, BM25 | None]] = {}
    for docs in {tuple(sorted(d)) for d in docs_by_target.values() if d}:
        rows = ws.query(f"SELECT p.*, d.title FROM passages p JOIN documents d ON d.doc_id=p.doc_id "
                        f"WHERE p.section='body' AND p.doc_id IN ({','.join('?' * len(docs))}) ORDER BY p.passage_id",
                        docs)
        indexes[docs] = (rows, BM25([tokens(p["text"]) for p in rows]) if rows else None)
    with ws.connect() as cx:
        for vc in vcs:
            doc_ids = docs_by_target[vc["target"]]
            if not doc_ids:
                missing += 1
                continue
            ps, bm = indexes[tuple(sorted(doc_ids))]
            if not ps:
                missing += 1
                continue
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
# 0.8.1: the SDG pack through the queue (Claude Code, or `enlens queue run` with the routed models)
# ---------------------------------------------------------------------------------------------
SDG_PREPARE = ("split", "extract", "verify-vca", "verify-claims", "audit-vca")


def _alias(model: str | None) -> str | None:
    """A Claude model as the alias Claude Code takes (haiku, sonnet, opus, fable); a full API id is mapped back."""
    from .routing import ALIASES, API_IDS

    if not model:
        return None
    m = str(model).strip()
    if m in ALIASES:
        return m
    for a, full in API_IDS.items():
        if m == full:
            return a
    raise ValueError(f"For Claude Code choose haiku, sonnet, opus or fable (not {m!r}).")


def prepare_sdg(ws: Workspace, what: str, router, model: str | None = None, **opts) -> dict:
    """Make the SDG pack's tasks of `what` (as `make-tasks` does) and put them, with any of that kind still waiting,
    in the queue. The router names the model of each kind (extract on Sonnet, split and the checks on Opus); a task
    records the Claude API id of that model, so `enlens run --backend anthropic` can answer it as well.

    The audits (audit-vca: a second model on answered VCA checks; verify-claims: a second check of extracted
    claims) get the role "audit": the auditor answers them (Opus, or Fable when switched on), or `model` when given;
    that model is kept (no stepping up), so the audit stays a second model's reading.
    Returns {"tasks": new tasks, "queued": tasks of that kind now waiting in the queue, "model": ...}."""
    if what not in SDG_PREPARE:
        raise ValueError(f"Choose one of {', '.join(SDG_PREPARE)}.")
    _sync_thresholds(ws)
    kind = {"verify-vca": "verify_set" if not opts.get("pairwise") else "verify", "verify-claims": "verify",
            "audit-vca": "verify_set"}.get(what, what)
    out: dict = {"what": what, "kind": kind}
    with queueing():
        if what in ("audit-vca", "verify-claims"):
            alias = _alias(model) or router.first("audit")
            if what == "audit-vca":
                out["tasks"] = make_audit_vca(ws, alias, float(opts.get("sample") or 0.1), int(opts.get("seed") or 0))
                ids = [r[0] for r in ws.query("SELECT task_id FROM tasks WHERE kind='verify_set' AND task_id LIKE ? "
                                              "AND status != 'done'", (f"%:audit:{alias}",))]
            else:
                out["tasks"] = make_verify_claims(ws, alias, float(opts.get("sample") or 1.0), int(opts.get("seed") or 0))
                ids = [r[0] for r in ws.query("SELECT task_id FROM tasks WHERE kind='verify' AND task_id LIKE ? AND "
                                              "json_extract(payload_json, '$.subject_kind')='claim' AND status != 'done'",
                                              (f"verify:%:{alias}",))]
            with ws.connect() as cx:
                for tid in ids:
                    cx.execute("UPDATE tasks SET role='audit', forced_model=? WHERE task_id=?", (alias, tid))
                mark_queued(cx, ids)
            out["model"] = alias
        else:
            alias = _alias(model) or router.first(kind)
            mid = router.api_id(alias)
            if what == "split":
                out["tasks"] = make_split(ws, mid)
            elif what == "extract":
                out["tasks"] = make_extract(ws, mid, opts.get("docs"), only_screened=not opts.get("all_passages"),
                                            limit=opts.get("limit"), per_target=opts.get("per_target"),
                                            hydrogen_only=not opts.get("any_passage"))
            else:
                r = make_verify_vca(ws, mid, opts.get("k"), bool(opts.get("beyond_cited")), bool(opts.get("pairwise")),
                                    int(opts.get("per_doc") or 2))
                out["tasks"], out["vca_claims_without_sources"] = r["tasks"], r["vca_claims_without_sources"]
            # tasks of this kind made earlier (make-tasks) and not answered yet wait in the queue too; audits keep
            # their own role
            ids = [r[0] for r in ws.query("SELECT task_id FROM tasks WHERE kind=? AND status IN ('pending', 'retry') "
                                          "AND role IS NULL AND (? = 0 OR json_extract(payload_json, '$.subject_kind')"
                                          " = 'vca_claim')", (kind, int(what == "verify-vca")))]
            with ws.connect() as cx:
                if model:  # a model chosen for this run: kept, as an acceptance run keeps its model
                    for tid in ids:
                        cx.execute("UPDATE tasks SET forced_model=? WHERE task_id=?", (alias, tid))
                mark_queued(cx, ids)
            out["model"] = alias
    out["queued"] = int(ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind=? AND COALESCE(queued, 0)=1 AND status IN "
                                  "('pending', 'retry')", (kind,)) or 0)
    return out


# ---------------------------------------------------------------------------------------------
# parsing and validation
# ---------------------------------------------------------------------------------------------
_THINK_RE = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.S | re.I)


def parse_json(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    s = str(raw).strip()
    s = _THINK_RE.sub("", s).strip()  # local reasoning models may put their reasoning before the answer
    if "</think>" in s:                 # an opening tag cut off by the server
        s = s.split("</think>", 1)[1].strip()
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


def ingest_result(ws: Workspace, task_id: str, raw: Any, model: str | None = None,
                  provenance: dict | None = None, route: str | None = None, helper: str | None = None,
                  claimed_at: str | None = None) -> tuple[bool, list[str]]:
    """Validate and store one answer. `provenance` (0.7): the model's digest, the seed and the settings that
    produced it (`llm.provenance`), kept with the raw answer. 0.8: `route` (Claude Code, Claude API, local model
    server, file queue), the plugin's `helper` agent and when its batch was claimed, kept with it too.

    A task that was already answered and is read again by the stronger model (`again`, see routing) keeps its first
    answer when the new one is not accepted: it stays done, and the step-up is given up after the last attempt."""
    with ws.connect() as cx:
        t = cx.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not t:
            return False, [f"unknown task {task_id}"]
        payload = json.loads(t["payload_json"])
        model = model or t["model"]
        again = t["status"] == "done" and bool(t["again"])
        attempt = int(t["attempts"]) + 1
        errors: list[str] = []
        ok = False
        cx.execute("SAVEPOINT handler")  # an answer that is not accepted changes nothing that was stored before
        try:
            obj = parse_json(raw)
            handler = HANDLERS[t["kind"]]
            ok, errors = handler(cx, t, payload, obj, model)
        except (ValueError, ValidationError) as e:
            errors = _errs(e) if isinstance(e, ValidationError) else [str(e)]
            ok = False
        except sqlite3.Error:
            raise  # a database problem (locked, disk full) is not a problem of the answer
        except Exception as e:  # an answer shaped in a way nothing expected must not stop a whole run
            errors, ok = [f"the answer could not be processed ({type(e).__name__}: {e})"], False
        if not ok:
            cx.execute("ROLLBACK TO handler")
        cx.execute("RELEASE handler")
        if again:  # a second reading by the stronger model: the first answer stays unless this one is accepted
            status = "done"
            keep_again = 0 if ok or attempt >= MAX_ATTEMPTS else 1
            cx.execute("UPDATE tasks SET status=?, attempts=?, again=? WHERE task_id=?",
                       (status, attempt, keep_again, task_id))
        else:
            status = "done" if ok else ("failed" if attempt >= MAX_ATTEMPTS else "retry")
            cx.execute("UPDATE tasks SET status=?, attempts=? WHERE task_id=?", (status, attempt, task_id))
        seq = cx.execute("SELECT COALESCE(MAX(attempt), 0) + 1 FROM results WHERE task_id=?", (task_id,)).fetchone()[0]
        prov = provenance or {}
        cx.execute("INSERT INTO results(task_id, attempt, kind, model, prompt_version, raw_json, valid, errors_json, "
                   "received_at, digest, seed, settings_json, route, helper, step, claimed_at) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (task_id, seq, t["kind"], model, t["prompt_version"],
                    raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False), int(ok), json.dumps(errors), now(),
                    prov.get("digest"), prov.get("seed"),
                    json.dumps(prov["settings"]) if prov.get("settings") else None,
                    route or (prov.get("settings") or {}).get("route"), helper, int(t["step"] or 0), claimed_at))
    return ok, errors


def _store_extract(cx, t, payload, obj, model) -> tuple[bool, list[str]]:
    out = ExtractOut.model_validate(obj)
    text = payload["text"]
    base = cx.execute("SELECT start, page FROM passages WHERE passage_id=?", (payload["passage_id"],)).fetchone()
    p_start, p_page = (base["start"], base["page"]) if base else (0, payload.get("page"))
    thr = _meta_float(cx, "accept_confidence", 0.8)
    # claims a reviewer decided on: a new answer must not silently undo the decision (see _keep_reviews)
    reviewed = {r["claim_id"]: dict(r) for r in cx.execute(
        "SELECT claim_id, claim, status, status_reason, segment, horizon FROM claims WHERE task_id=? "
        "AND status IN ('accepted', 'changed', 'rejected')", (t["task_id"],))}
    for cid in reviewed:
        reviewed[cid]["targets"] = [tuple(r) for r in cx.execute(
            "SELECT target, direction, influence FROM claim_targets WHERE claim_id=?", (cid,))]
    # replace anything stored from an earlier attempt of this task
    old = [r[0] for r in cx.execute("SELECT claim_id FROM claims WHERE task_id=?", (t["task_id"],))]
    for cid in old:
        for tbl in ("claim_targets", "evidence"):
            cx.execute(f"DELETE FROM {tbl} WHERE claim_id=?", (cid,))
    cx.execute("DELETE FROM claims WHERE task_id=?", (t["task_id"],))
    # interactions of this task are stored as '<task_id>#<n>'; compare the prefix exactly (LIKE would also match
    # 'extract:d…:1000' for 'extract:d…:100', and treats '_' in ids as a wildcard)
    prefix = t["task_id"] + "#"
    cx.execute("DELETE FROM interactions WHERE kind='stated' AND substr(claim_id, 1, ?) = ?", (len(prefix), prefix))
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
    if ok and reviewed:
        _keep_reviews(cx, reviewed)
    return ok, errors


def _keep_reviews(cx, reviewed: dict[str, dict]) -> None:
    """After a task is answered again: a claim with the same id and the same text keeps the reviewer's decision
    (and correction); a reviewed claim that changed or disappeared has its review marked superseded, so it comes
    back to the review queue and is not exported as gold."""
    for cid, r in reviewed.items():
        now_row = cx.execute("SELECT claim FROM claims WHERE claim_id=?", (cid,)).fetchone()
        if now_row and " ".join(now_row[0].split()) == " ".join((r["claim"] or "").split()):
            cx.execute("UPDATE claims SET status=?, status_reason=?, segment=?, horizon=? WHERE claim_id=?",
                       (r["status"], r["status_reason"], r["segment"], r["horizon"], cid))
            if r["status"] == "changed":
                cx.execute("DELETE FROM claim_targets WHERE claim_id=?", (cid,))
                cx.executemany("INSERT INTO claim_targets VALUES (?,?,?,?)", [(cid, *x) for x in r["targets"]])
        else:
            cx.execute("UPDATE reviews SET field='superseded' WHERE item_kind='claim' AND item_id=?", (cid,))


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
    # VCA claim ids are positions ('6.4#1'): when a new split puts another claim at a position, the grades of the
    # old claim must not be read as grades of the new one
    new_text = {r[0]: r[3] for r in rows}
    for cid, text in cx.execute("SELECT vca_claim_id, text FROM vca_claims WHERE target=?", (payload["target"],)).fetchall():
        if new_text.get(cid) != text:
            _forget_vca_claim(cx, cid)
    cx.execute("DELETE FROM vca_claims WHERE target=?", (payload["target"],))
    cx.executemany("INSERT INTO vca_claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return True, []


def _forget_vca_claim(cx, cid: str) -> None:
    cx.execute("DELETE FROM verifications WHERE subject_kind IN ('vca_claim', 'vca_claim_audit') AND subject_id=?", (cid,))
    cx.execute("UPDATE reviews SET field='superseded' WHERE item_kind='vca_claim' AND item_id=?", (cid,))
    for prefix in (f"verify_set:{cid}:", f"verify:{cid}:"):
        for tbl in ("results", "tasks"):
            cx.execute(f"DELETE FROM {tbl} WHERE substr(task_id, 1, ?) = ?", (len(prefix), prefix))
    for tbl in ("results", "tasks"):
        cx.execute(f"DELETE FROM {tbl} WHERE task_id = ?", (f"verify_set:{cid}",))


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
    cx.execute("INSERT OR REPLACE INTO verifications(ver_id, subject_kind, subject_id, passage_id, doc_id, verdict, confidence, quote, start, end, page, model, prompt_version, scope_note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (vid, payload["subject_kind"], payload["subject_id"], payload["passage_id"], payload["doc_id"], v.verdict,
                v.confidence, quote, s, e, payload.get("page"), model, t["prompt_version"], None))
    if payload["subject_kind"] == "claim":
        thr = _meta_float(cx, "support_confidence", 0.6)
        if not (v.verdict == "supports" and v.confidence >= thr):
            cx.execute("UPDATE claims SET status='needs_review', status_reason=? WHERE claim_id=? AND status IN ('auto','needs_review')",
                       (f"second check ({model}): {v.verdict} {v.confidence:.2f}", payload["subject_id"]))
    return True, []


def _graded_passages(v, passages: list[dict]) -> tuple[dict[int, tuple], list[str]]:
    """The grades of a set answer by passage number, each with its quote found in that passage; or the problems."""
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
        ref = getattr(ev, "refers_to", None)
        if ref:
            from .references import locate_reference

            if not locate_reference(p, ref):
                errors.append(f"evidence[{j}]: refers_to not found in passage P{ev.passage} or the text before it: "
                              f"{ref[:80]!r}")
                continue
        graded[ev.passage] = (ev, hit)
    return graded, errors


def _refers(p: dict, ev, off: int | None) -> tuple:
    """(refers_to, start, end, where) in document offsets, for a grade that names what its quote refers to."""
    ref = getattr(ev, "refers_to", None)
    if not ref:
        return (None, None, None, None)
    from .references import locate_reference

    got = locate_reference(p, ref)
    if not got:
        return (None, None, None, None)
    text, a, b, where = got
    base = off if where == "excerpt" else p.get("context_start")
    return (text, base + a if base is not None else None, base + b if base is not None else None, where)


def capped(verdict: str, scope_note: str | None) -> str:
    """check-v3's rule: an excerpt about another group or setting than the claim's supports it at most partly."""
    return "partially_supports" if scope_note and verdict == "supports" else verdict


def _store_verify_set(cx, t, payload, obj, model, schema=VerifySetOut) -> tuple[bool, list[str]]:
    v = schema.model_validate(obj)
    passages = payload["passages"]
    graded, errors = _graded_passages(v, passages)
    if errors:
        return False, errors
    again = t["status"] == "done"  # answered before: a second reading (0.8, the stronger model)
    for n, p in enumerate(passages, 1):
        base = cx.execute("SELECT start FROM passages WHERE passage_id=?", (p["passage_id"],)).fetchone()
        off = base[0] if base else 0
        vid = f"v{_h(t['task_id'], p['passage_id'])}"
        before = cx.execute("SELECT * FROM verifications WHERE ver_id=?", (vid,)).fetchone() if again else None
        note = None
        ref = (None, None, None, None)
        if n in graded:
            ev, hit = graded[n]
            note = getattr(ev, "scope_note", None)
            row = (capped(ev.verdict, note), ev.confidence, p["text"][hit[0]:hit[1]], off + hit[0], off + hit[1])
            ref = _refers(p, ev, off if base else None)
        else:
            row = ("not_enough_info", None, None, None, None)
        cx.execute("INSERT OR REPLACE INTO verifications(ver_id, subject_kind, subject_id, passage_id, doc_id, verdict, "
                   "confidence, quote, start, end, page, model, prompt_version, scope_note, refers_to, refers_start, "
                   "refers_end, refers_where) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (vid, payload["subject_kind"], payload["subject_id"],
                    p["passage_id"], p["doc_id"], *row[:3], row[3], row[4], p.get("page"), model, t["prompt_version"],
                    note, *ref))
        if before is not None:
            _keep_person_and_history(cx, vid, before, "stepped up")
    return True, []


def _keep_person_and_history(cx, vid: str, before, why: str) -> None:
    """After an excerpt's judgement is stored again (a stronger model read it): a person's own judgement stays, and
    the AI's earlier judgement joins its history (shown on the result, as for an excerpt read again)."""
    b = dict(before)
    hist = json.loads(b.get("ai_history_json") or "[]")
    hist.append({"verdict": b.get("verdict"), "confidence": b.get("confidence"), "quote": b.get("quote"),
                 "scope_note": b.get("scope_note"), "model": b.get("model"), "prompt_version": b.get("prompt_version"),
                 "at": None, "replaced_at": now(), "why": why})
    cx.execute("UPDATE verifications SET user_verdict=?, user_note=?, user_at=?, user_quote=?, user_start=?, user_end=?, "
               "ai_history_json=?, reread_json=? WHERE ver_id=?",
               (b.get("user_verdict"), b.get("user_note"), b.get("user_at"), b.get("user_quote"), b.get("user_start"),
                b.get("user_end"), json.dumps(hist, ensure_ascii=False), b.get("reread_json"), vid))


def _store_reread(cx, t, payload, obj, model) -> tuple[bool, list[str]]:
    """One excerpt read again: its new grade replaces the AI's, the earlier ones are kept in ai_history_json.
    A person's own judgement (user_*) is not touched, so it still counts."""
    v = CheckOut.model_validate(obj)
    p = payload["passages"][0]
    graded, errors = _graded_passages(v, payload["passages"])
    if errors:
        return False, errors
    base = cx.execute("SELECT start FROM passages WHERE passage_id=?", (p["passage_id"],)).fetchone()
    off = base[0] if base else None
    ref = (None, None, None, None)
    if 1 in graded:
        ev, hit = graded[1]
        row = (capped(ev.verdict, ev.scope_note), ev.confidence, p["text"][hit[0]:hit[1]],
               off + hit[0] if off is not None else None, off + hit[1] if off is not None else None, ev.scope_note)
        ref = _refers(p, ev, off)
    else:
        row = ("not_enough_info", None, None, None, None, None)
    old = cx.execute("SELECT * FROM verifications WHERE subject_kind=? AND subject_id=? AND passage_id=?",
                     (payload["subject_kind"], payload["subject_id"], p["passage_id"])).fetchone()
    info = json.dumps({"hint": payload.get("reader_note"), "rationale": (v.rationale or "").strip() or None,
                       "model": model, "at": now()}, ensure_ascii=False)
    history = []
    if old is not None:
        history = json.loads(old["ai_history_json"] or "[]")
        history.append({"verdict": old["verdict"], "confidence": old["confidence"], "quote": old["quote"],
                        "scope_note": old["scope_note"], "model": old["model"], "prompt_version": old["prompt_version"],
                        "at": payload.get("previous_at"), "replaced_at": now()})
        cx.execute("UPDATE verifications SET verdict=?, confidence=?, quote=?, start=?, end=?, scope_note=?, model=?, "
                   "prompt_version=?, ai_history_json=?, reread_json=?, refers_to=?, refers_start=?, refers_end=?, "
                   "refers_where=? WHERE ver_id=?",
                   (*row[:5], row[5], model, t["prompt_version"], json.dumps(history, ensure_ascii=False), info,
                    *ref, old["ver_id"]))
    else:
        cx.execute("INSERT INTO verifications(ver_id, subject_kind, subject_id, passage_id, doc_id, verdict, confidence, "
                   "quote, start, end, page, model, prompt_version, scope_note, ai_history_json, reread_json) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (f"v{_h(t['task_id'], p['passage_id'])}", payload["subject_kind"], payload["subject_id"],
                    p["passage_id"], p["doc_id"], *row[:5], p.get("page"), model, t["prompt_version"], row[5], "[]",
                    info))
    return True, []


def _store_expand(cx, t, payload, obj, model) -> tuple[bool, list[str]]:
    out = ExpandOut.model_validate(obj)
    if not out.terms:
        return False, ["give at least one search term"]
    if payload.get("concept"):  # 0.7: other wordings of a concept (F3), kept for the concept card
        cx.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (f"concept_wordings:{payload['concept']}",
                                                               json.dumps(out.terms, ensure_ascii=False)))
        return True, []
    cx.execute("UPDATE user_claims SET terms_json=? WHERE claim_id=?", (json.dumps(out.terms, ensure_ascii=False), payload["claim_id"]))
    return True, []


def _store_decompose(cx, t, payload, obj, model) -> tuple[bool, list[str]]:
    out = DecomposeOut.model_validate(obj)
    parts, seen = [], set()
    for p in out.parts:
        key = normalise(p.text).strip(" .")
        if key and key not in seen:
            seen.add(key)
            parts.append({"text": " ".join(p.text.split()), "role": p.role})
    if not parts:
        return False, ["give at least one part"]
    cx.execute("UPDATE hypotheses SET parts_json=?, decomposed=? WHERE hyp_id=?",
               (json.dumps(parts, ensure_ascii=False), int(len(parts) > 1), payload["hyp_id"]))
    return True, []


def _store_second(cx, t, payload, obj, model) -> tuple[bool, list[str]]:
    """A second model's grades of the excerpts a check already read: kept apart (table second_opinions), so they
    never change an answer; the app shows where the two models disagree."""
    v = CheckOut.model_validate(obj)
    passages = payload["passages"]
    graded, errors = _graded_passages(v, passages)
    if errors:
        return False, errors
    second = payload.get("second_model") or model
    for n, p in enumerate(passages, 1):
        base = cx.execute("SELECT start FROM passages WHERE passage_id=?", (p["passage_id"],)).fetchone()
        off = base[0] if base else None
        if n in graded:
            ev, hit = graded[n]
            row = (capped(ev.verdict, ev.scope_note), ev.confidence, p["text"][hit[0]:hit[1]],
                   off + hit[0] if off is not None else None, off + hit[1] if off is not None else None, ev.scope_note)
        else:
            row = ("not_enough_info", None, None, None, None, None)
        cx.execute("INSERT OR REPLACE INTO second_opinions(subject_id, passage_id, model, verdict, confidence, quote, "
                   "start, end, scope_note, at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (payload["subject_id"], p["passage_id"], second, *row, now()))
    return True, []


def _store_check(cx, t, payload, obj, model) -> tuple[bool, list[str]]:
    ok, errors = _store_verify_set(cx, t, payload, obj, model, schema=CheckOut)
    if ok:
        cx.execute("UPDATE user_claims SET rationale=?, model=? WHERE claim_id=?",
                   ((obj.get("rationale") if isinstance(obj, dict) else None), model, payload["subject_id"]))
    return ok, errors


def _store_label(cx, t, payload, obj, model):
    from .profile import store_labels

    return store_labels(cx, t, payload, obj, model)


def _store_link(cx, t, payload, obj, model) -> tuple[bool, list[str]]:
    """How two (or more) terms relate (link-v1): each quote must come from the passages shown for its term."""
    from .schema import LinkOut

    out = LinkOut.model_validate(obj)
    terms = {x["n"]: x for x in payload["terms"]}
    errors, rows = [], []
    inverse = {"broader": "narrower", "narrower": "broader"}
    for i, r in enumerate(out.relations):
        if r.a not in terms or r.b not in terms or r.a == r.b:
            errors.append(f"relations[{i}]: a and b must be two different term numbers shown (1 to {len(terms)})")
            continue
        qa = next((find_quote(sn["text"], r.quote_a) for sn in terms[r.a]["snippets"] if find_quote(sn["text"], r.quote_a)), None)
        qb = next((find_quote(sn["text"], r.quote_b) for sn in terms[r.b]["snippets"] if find_quote(sn["text"], r.quote_b)), None)
        if not qa:
            errors.append(f"relations[{i}]: quote_a not found in the passages of term {r.a}: {r.quote_a[:80]!r}")
        if not qb:
            errors.append(f"relations[{i}]: quote_b not found in the passages of term {r.b}: {r.quote_b[:80]!r}")
        if not (qa and qb):
            continue
        a, b = terms[r.a]["term_id"], terms[r.b]["term_id"]
        rel, qa_t, qb_t = r.relation, r.quote_a, r.quote_b
        if a > b:
            a, b, rel, qa_t, qb_t = b, a, inverse.get(rel, rel), qb_t, qa_t
        rows.append((a, b, rel, "model", r.confidence, qa_t, qb_t, model, now()))
    if errors:
        return False, errors
    cx.executemany("INSERT OR REPLACE INTO concept_links VALUES (?,?,?,?,?,?,?,?,?)", rows)
    return True, []


def _store_theme(cx, t, payload, obj, model):
    from .themes import store_theme

    return store_theme(cx, t, payload, obj, model)


def _store_resolve(cx, t, payload, obj, model):
    from .references import store_resolve

    return store_resolve(cx, t, payload, obj, model)


HANDLERS = {"extract": _store_extract, "split": _store_split, "verify": _store_verify, "verify_set": _store_verify_set,
            "expand": _store_expand, "check": _store_check, "decompose": _store_decompose, "reread": _store_reread,
            "second": _store_second, "label": _store_label, "link": _store_link, "theme": _store_theme,
            "resolve": _store_resolve}


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


def model_for(t, backend, model: str | None = None) -> str:
    """The model that answers this task: the one it must keep (an acceptance run), else the backend's router (0.8,
    by kind and step), else the model given, else the one the task was made for."""
    if t["forced_model"]:
        return t["forced_model"]
    router = getattr(backend, "router", None)
    if router is not None:
        from .routing import task_kind

        m = router.call_model(task_kind(t), int(t["step"] or 0))
        if m:
            return m
    return model or t["model"]


def _step_up(ws: Workspace, t, backend, ok: bool, raw: Any) -> str | None:
    """After an answer: does the task go up to the stronger model (routing, once at most)? Returns "again" (an
    accepted answer read again: it counts meanwhile), "retry" (the last attempt goes to the stronger model) or None."""
    from .routing import STEP_UP_BELOW, certainty

    router = getattr(backend, "router", None)
    from .routing import task_kind

    if router is None or t["forced_model"] or int(t["step"] or 0) or not router.step_up(task_kind(t)):
        return None
    cur = ws.query("SELECT status, attempts FROM tasks WHERE task_id=?", (t["task_id"],))[0]
    if ok:
        try:
            c = certainty(t["kind"], parse_json(raw))
        except ValueError:
            c = None
        if c is not None and c < STEP_UP_BELOW:
            with ws.connect() as cx:
                cx.execute("UPDATE tasks SET step=1, again=1, attempts=0 WHERE task_id=?", (t["task_id"],))
            return "again"
        return None
    if cur["status"] == "retry" and int(cur["attempts"]) >= MAX_ATTEMPTS - 1:
        with ws.connect() as cx:
            cx.execute("UPDATE tasks SET step=1 WHERE task_id=?", (t["task_id"],))
        return "retry"
    return None


def run_one(ws: Workspace, task_id: str, backend, model: str | None = None) -> tuple[bool, list[str]]:
    """Answer one task now, retrying with the problems listed, up to three attempts. Backend errors propagate.

    0.8: with a router on the backend, the task's kind picks its model, and a hard task steps up once (see
    routing): on the Claude API at once; with local models the second readings wait for `run_stepups`, so each
    model is loaded once per run. With the Claude Code backend nothing is asked here: the task waits in the queue
    until Claude Code has answered it (`taskqueue.wait_for`)."""
    if getattr(backend, "name", "") == "claude_code":
        from .taskqueue import wait_for

        return wait_for(ws, task_id, backend)
    errors: list[str] = []
    for _ in range(MAX_ATTEMPTS + 1):
        found = ws.query("SELECT * FROM tasks WHERE task_id=?", (task_id,))
        if not found:
            raise KeyError(f"unknown task {task_id}")
        t = found[0]
        if t["status"] == "done" and not (t["again"] and _answers_again_now(backend)):
            return True, []
        if t["status"] == "failed":
            break
        system, user = render(ws, t)
        call = model_for(t, backend, model)
        raw = backend.complete(t["kind"], system, user, call, json.loads(t["payload_json"]))
        used = "baseline" if getattr(backend, "name", "") == "baseline" else call
        was_again = t["status"] == "done"
        ok, errors = ingest_result(ws, task_id, raw, model=used, provenance=_provenance(backend, used),
                                   route=_route_name(backend))
        if was_again:
            if ok or ws.scalar("SELECT again FROM tasks WHERE task_id=?", (task_id,)) == 0:
                return True, errors  # the first answer is kept when the stronger model's does not pass
            continue
        step = _step_up(ws, t, backend, ok, raw)
        if ok and step != "again":
            return True, errors
        if ok and step == "again" and not _answers_again_now(backend):
            return True, errors  # read again later, with the other second readings of this run (run_stepups)
    return False, errors


def _answers_again_now(backend) -> bool:
    """Whether a second reading by the stronger model is asked at once (the Claude API) or after the run (a local
    server: the other model is loaded once, see run_stepups)."""
    router = getattr(backend, "router", None)
    return router is not None and router.route != "local"


def _route_name(backend) -> str:
    from .routing import ROUTE_NAMES

    return ROUTE_NAMES.get(getattr(backend, "name", ""), getattr(backend, "name", ""))


def run_stepups(ws: Workspace, backend, kinds: Iterable[str] | None = None,
                should_stop=None, progress=None, queued: bool = False) -> dict:
    """Answer the second readings a run left for the stronger model (local servers: after the run, so each model
    is loaded once). Tasks waiting in the queue for Claude Code are left to it, unless `queued` (the queue is being
    answered here, see taskqueue.run_here)."""
    q = "SELECT task_id FROM tasks WHERE status='done' AND again=1" + ("" if queued else " AND COALESCE(queued, 0)=0")
    args: list = []
    if kinds:
        ks = list(kinds)
        q += f" AND kind IN ({','.join('?' * len(ks))})"
        args += ks
    ids = [r[0] for r in ws.query(q + " ORDER BY kind, task_id", args)]
    out = {"stepped_up": 0, "kept_first": 0}
    for i, tid in enumerate(ids, 1):
        if should_stop and should_stop():
            break
        if progress:
            progress(i, len(ids))
        ok = answer_again(ws, tid, backend)
        out["stepped_up" if ok else "kept_first"] += 1
    return out


def answer_again(ws: Workspace, task_id: str, backend) -> bool:
    """The stronger model's reading of an answered task (`again`): up to three attempts; the first answer stays when
    none is accepted. With the Claude Code backend: wait for it in the queue. Returns whether the new answer counts."""
    if getattr(backend, "name", "") == "claude_code":
        from .taskqueue import wait_for

        wait_for(ws, task_id, backend)
        return int(ws.scalar("SELECT step FROM tasks WHERE task_id=?", (task_id,)) or 0) == 1 and \
            bool(ws.scalar("SELECT valid FROM results WHERE task_id=? ORDER BY attempt DESC LIMIT 1", (task_id,)))
    t = ws.query("SELECT * FROM tasks WHERE task_id=?", (task_id,))[0]
    for _ in range(MAX_ATTEMPTS):
        if not (t["status"] == "done" and t["again"]):
            return False
        system, user = render(ws, t)
        call = model_for(t, backend)
        raw = backend.complete(t["kind"], system, user, call, json.loads(t["payload_json"]))
        ok, _e = ingest_result(ws, task_id, raw, model=call, provenance=_provenance(backend, call),
                               route=_route_name(backend))
        if ok:
            return True
        t = ws.query("SELECT * FROM tasks WHERE task_id=?", (task_id,))[0]
    return False


def ask_stronger(ws: Workspace, task_id: str) -> dict:
    """A person asks for a stronger model on an answered task ("Ask a stronger model"): it is read again once by
    the model the task steps up to. Raises ValueError when it already was, or has no answer yet."""
    t = ws.query("SELECT * FROM tasks WHERE task_id=?", (task_id,))
    if not t:
        raise KeyError(task_id)
    t = t[0]
    if t["status"] != "done":
        raise ValueError("This has no answer yet to read again.")
    if int(t["step"] or 0):
        raise ValueError("A stronger model has already read this; a task steps up once at most.")
    with ws.connect() as cx:
        cx.execute("UPDATE tasks SET step=1, again=1, attempts=0, claimed_by=NULL WHERE task_id=?", (task_id,))
        if queue_mode():
            mark_queued(cx, [task_id])
    return {"task_id": task_id, "kind": t["kind"]}


def _provenance(backend, model: str) -> dict:
    from .llm import provenance

    try:
        return provenance(backend, model)
    except Exception:  # never lose an answer over a missing detail
        return {}


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
            ingest_result(ws, t["task_id"], raw, model=used, provenance=_provenance(backend, used))
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
    numbers = [int(m.group(1)) for f in out_dir.glob("batch_*.jsonl") if (m := re.fullmatch(r"batch_(\d+)\.jsonl", f.name))]
    start = max(numbers, default=0)  # after the highest number, so a gap left by a deleted batch is never overwritten
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
            if not isinstance(rec, dict):
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
            used = rec.get("model") or model
            ok, _errs = ingest_result(ws, tid, raw, model=used, provenance={
                "digest": rec.get("digest") or (f"name:{used}" if used else None), "seed": rec.get("seed"),
                "settings": {"backend": "file queue"}})
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
                if not isinstance(rec, dict):
                    out["problems"].append({"line": where, "errors": ["each line must be a JSON object"]})
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
            # second opinions (audits of VCA checks, second checks of extracted claims) are about their own model:
            # they are queued again under the new prompt but keep the model they were made for
            own = ("COALESCE(json_extract(payload_json, '$.subject_kind'), '') IN ('vca_claim_audit', 'claim')")
            cur = cx.execute("UPDATE tasks SET status='pending', attempts=0, prompt_version=?, model=? "
                             f"WHERE kind=? AND NOT {own} AND (prompt_version != ? OR model != ?)",
                             (version, model, kind, version, model))
            n = cur.rowcount
            cur = cx.execute("UPDATE tasks SET status='pending', attempts=0, prompt_version=? "
                             f"WHERE kind=? AND {own} AND prompt_version != ?", (version, kind, version))
            return n + cur.rowcount
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
