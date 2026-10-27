"""Check one claim, typed by a person, against the documents in a workspace.

The steps are the pilot's, applied to any claim:

1. (optional) A model writes search terms for the claim: synonyms, related technical words and the words a source
   would use to state the opposite. Keyword ranking misses evidence worded differently; this narrows that gap.
2. The best passages across the documents are picked by BM25 on the claim and its terms, at most `per_doc` from one
   document first so one long report cannot crowd out the others.
3. A model grades each passage that bears on the claim: supports, partially supports or refutes, with a quote.
   Quotes are checked against the passage like every other answer.

Everything is stored like any other task (tasks, results, verifications), so a check can be audited later.
"""
from __future__ import annotations

import hashlib
import json
from typing import Callable

from . import tasks
from .analysis import _status
from .retrieve import BM25
from .store import Workspace, now
from .taxonomy import target_sort_key, targets
from .textutil import tokens

Progress = Callable[[str, str], None]  # (step, message)

STATUS_TEXT = {
    "supported": "Stated by a source",
    "partially_supported": "Partly stated by a source",
    "contradicted": "Contradicted by a source",
    "unsupported": "Nothing found in the passages read",
    "not_checked": "Not checked yet",
    "no_passages": "No passage matched the claim",
    "failed": "The model's answer could not be used",
}

_INDEX: dict = {}
_TARGET_INDEX: list = []


# ---------------------------------------------------------------------------------------------
# retrieval
# ---------------------------------------------------------------------------------------------
def _index(ws: Workspace):
    """Body passages and their BM25 index, built once per workspace state (it takes a second or two)."""
    key = (str(ws.db_path.resolve()), ws.scalar("SELECT COUNT(*) FROM passages"), ws.scalar("SELECT MAX(rowid) FROM passages"))
    if key not in _INDEX:
        rows = [dict(r) for r in ws.query(
            "SELECT p.passage_id, p.doc_id, p.page, p.text, d.title FROM passages p JOIN documents d ON d.doc_id=p.doc_id "
            "WHERE p.section='body' ORDER BY p.passage_id")]
        _INDEX.clear()
        _INDEX[key] = (rows, BM25([tokens(r["text"]) for r in rows]))
    return _INDEX[key]


def rank_passages(ws: Workspace, query_text: str, terms: list[str] | None = None, k: int = 8, per_doc: int = 2,
                  doc_ids: list[str] | None = None) -> list[dict]:
    rows, bm = _index(ws)
    if not rows:
        return []
    q = tokens(query_text) * 2 + tokens(" ".join(terms or []))  # the claim's own words count double
    scores = bm.score(q)
    allowed = set(doc_ids) if doc_ids else None
    ranked = [i for i in sorted(range(len(rows)), key=lambda i: -scores[i])
              if scores[i] > 0 and (allowed is None or rows[i]["doc_id"] in allowed)][: max(k * 8, 60)]
    picked: list[int] = []
    count: dict[str, int] = {}
    for i in ranked:
        if len(picked) >= k:
            break
        d = rows[i]["doc_id"]
        if count.get(d, 0) < per_doc:
            picked.append(i)
            count[d] = count.get(d, 0) + 1
    for i in ranked:
        if len(picked) >= k:
            break
        if i not in picked:
            picked.append(i)
    return [{**rows[i], "score": round(scores[i], 2)} for i in picked]


def suggest_targets(text: str, n: int = 5) -> list[dict]:
    """SDG targets whose wording is closest to the claim (keyword match, no model): a starting point only."""
    import re

    from .llm import LEXICON

    if not _TARGET_INDEX:
        ts = sorted(targets().values(), key=lambda t: target_sort_key(t.code))
        _TARGET_INDEX.extend([ts, BM25([tokens(f"{t.description} {t.goal_name}") for t in ts])])
    ts, bm = _TARGET_INDEX
    scores = dict(zip((t.code for t in ts), bm.score(tokens(text))))
    for pattern, code in LEXICON:  # common phrasings the target texts do not use ("water stress", "jobs")
        if re.search(pattern, text, re.I):
            scores[code] = scores.get(code, 0) + 10
    best = sorted((c for c in scores if scores[c] > 0), key=lambda c: -scores[c])[:n]
    tg = targets()
    return [{"code": c, "goal": tg[c].goal, "description": tg[c].description, "score": round(scores[c], 2)} for c in best]


# ---------------------------------------------------------------------------------------------
# running a check
# ---------------------------------------------------------------------------------------------
def new_claim(ws: Workspace, text: str, target: str | None = None, options: dict | None = None) -> str:
    text = " ".join(text.split())
    if len(text) < 10:
        raise ValueError("Write the claim as a sentence (at least 10 characters).")
    if target and target not in targets():
        raise ValueError(f"Unknown SDG target {target!r}.")
    cid = "u" + hashlib.sha1(f"{text}|{now()}".encode()).hexdigest()[:10]
    with ws.connect() as cx:
        cx.execute("INSERT INTO user_claims(claim_id, text, target, options_json, created_at) VALUES (?,?,?,?,?)",
                   (cid, text, target or None, json.dumps(options or {}), now()))
    return cid


def _add_task(ws: Workspace, task_id: str, kind: str, model: str, payload: dict) -> None:
    with ws.connect() as cx:
        tasks._insert_task(cx, task_id, kind, model, payload)


def check_claim(ws: Workspace, text: str, backend, model: str, target: str | None = None, k: int = 8, per_doc: int = 2,
                expand: bool = True, doc_ids: list[str] | None = None, progress: Progress | None = None) -> str:
    """Run a full check and return the claim id; read the outcome with `result`. Backend errors propagate."""
    say = progress or (lambda step, msg: None)
    if not ws.scalar("SELECT COUNT(*) FROM passages WHERE section='body'"):
        raise ValueError("This project has no readable documents yet. Add sources first.")
    used = "baseline" if getattr(backend, "name", "") == "baseline" else model
    options = {"k": k, "per_doc": per_doc, "expand": expand, "doc_ids": doc_ids or [], "backend": getattr(backend, "name", ""),
               "model": used}
    cid = new_claim(ws, text, target, options)
    try:
        _run_check(ws, cid, backend, model, used, target, k, per_doc, expand, doc_ids, say)
    except Exception:
        delete_claim(ws, cid)  # a check stopped by a connection or key problem should not linger in the history
        raise
    return cid


def _run_check(ws, cid, backend, model, used, target, k, per_doc, expand, doc_ids, say) -> None:
    claim = ws.scalar("SELECT text FROM user_claims WHERE claim_id=?", (cid,))
    terms: list[str] = []
    if expand:
        say("terms", "Finding search terms")
        _add_task(ws, f"expand:{cid}", "expand", used, {"claim_id": cid, "claim": claim})
        ok, _errs = tasks.run_one(ws, f"expand:{cid}", backend, model)
        if ok:
            terms = json.loads(ws.scalar("SELECT terms_json FROM user_claims WHERE claim_id=?", (cid,)) or "[]")
    say("rank", "Picking passages")
    picked = rank_passages(ws, claim, terms, k=k, per_doc=per_doc, doc_ids=doc_ids)
    if not picked:
        return
    t = targets().get(target or "")
    payload = {"subject_kind": "user_claim", "subject_id": cid, "claim": claim, "target": target or None,
               "target_description": t.description if t else None,
               "passages": [{"passage_id": p["passage_id"], "doc_id": p["doc_id"], "title": p["title"], "page": p["page"],
                             "text": p["text"]} for p in picked]}
    _add_task(ws, f"check:{cid}", "check", used, payload)
    say("grade", f"Reading {len(picked)} passages with {used}")
    tasks.run_one(ws, f"check:{cid}", backend, model)


# ---------------------------------------------------------------------------------------------
# reading results
# ---------------------------------------------------------------------------------------------
def result(ws: Workspace, claim_id: str, threshold: float | None = None) -> dict:
    thr = float(ws.config["thresholds"]["support_confidence"]) if threshold is None else float(threshold)
    rows = ws.query("SELECT * FROM user_claims WHERE claim_id=?", (claim_id,))
    if not rows:
        raise KeyError(claim_id)
    uc = dict(rows[0])
    task = ws.query("SELECT * FROM tasks WHERE task_id=?", (f"check:{claim_id}",))
    out = {"claim_id": claim_id, "claim": uc["text"], "target": uc["target"], "created_at": uc["created_at"],
           "terms": json.loads(uc["terms_json"] or "[]"), "rationale": uc["rationale"], "model": uc["model"],
           "options": json.loads(uc["options_json"] or "{}"), "threshold": thr, "passages": [], "errors": []}
    if uc["target"] and uc["target"] in targets():
        out["target_description"] = targets()[uc["target"]].description
    if not task:
        out["status"] = out["status_any"] = "no_passages"
        return out
    task = task[0]
    payload = json.loads(task["payload_json"])
    vs = [dict(v) for v in ws.query("SELECT * FROM verifications WHERE subject_kind='user_claim' AND subject_id=?", (claim_id,))]
    by_passage = {v["passage_id"]: v for v in vs}
    starts = {r["passage_id"]: r["start"] for r in ws.query(
        f"SELECT passage_id, start FROM passages WHERE passage_id IN ({','.join('?' * len(payload['passages']))})",
        tuple(p["passage_id"] for p in payload["passages"]))}
    for n, p in enumerate(payload["passages"], 1):
        v = by_passage.get(p["passage_id"])
        item = {"n": n, "passage_id": p["passage_id"], "doc_id": p["doc_id"], "title": p["title"], "page": p["page"],
                "text": p["text"], "verdict": None, "confidence": None, "quote": None, "quote_start": None, "quote_end": None}
        if v and v["verdict"] != "not_enough_info":
            item.update(verdict=v["verdict"], confidence=v["confidence"], quote=v["quote"])
            base = starts.get(p["passage_id"])
            if base is not None and v["start"] is not None:
                item.update(quote_start=v["start"] - base, quote_end=v["end"] - base)
        out["passages"].append(item)
    if task["status"] == "done":
        out["status"] = _status(vs, thr)
        out["status_any"] = _status(vs, 0.0)
    else:
        out["status"] = out["status_any"] = "failed" if task["status"] in ("failed", "retry") else "not_checked"
        last = ws.query("SELECT errors_json FROM results WHERE task_id=? ORDER BY attempt DESC LIMIT 1", (task["task_id"],))
        out["errors"] = json.loads(last[0][0]) if last else []
    order = {"supports": 0, "partially_supports": 1, "refutes": 2, None: 3}
    out["passages"].sort(key=lambda x: (order[x["verdict"]], -(x["confidence"] or 0), x["n"]))
    return out


def history(ws: Workspace, threshold: float | None = None) -> list[dict]:
    out = []
    for r in ws.query("SELECT claim_id FROM user_claims ORDER BY created_at DESC, rowid DESC"):
        res = result(ws, r[0], threshold)
        graded = [p for p in res["passages"] if p["verdict"]]
        out.append({"claim_id": res["claim_id"], "created_at": res["created_at"], "claim": res["claim"],
                    "target": res["target"] or "", "status": res["status"], "status_any": res["status_any"],
                    "supports": sum(p["verdict"] == "supports" for p in graded),
                    "partly": sum(p["verdict"] == "partially_supports" for p in graded),
                    "refutes": sum(p["verdict"] == "refutes" for p in graded),
                    "passages_read": len(res["passages"]), "model": res["model"] or res["options"].get("model", "")})
    return out


def export_rows(ws: Workspace, threshold: float | None = None) -> list[dict]:
    """One row per graded passage of every check, for a spreadsheet."""
    rows = []
    for h in history(ws, threshold):
        res = result(ws, h["claim_id"], threshold)
        graded = [p for p in res["passages"] if p["verdict"]] or [None]
        for p in graded:
            rows.append({"claim_id": res["claim_id"], "checked_at": res["created_at"], "claim": res["claim"],
                         "target": res["target"] or "", "status": res["status"], "model": h["model"],
                         "verdict": p["verdict"] if p else "", "confidence": p["confidence"] if p else "",
                         "quote": p["quote"] if p else "", "source": p["title"] if p else "", "page": p["page"] if p else ""})
    return rows


def delete_claim(ws: Workspace, claim_id: str) -> None:
    with ws.connect() as cx:
        cx.execute("DELETE FROM verifications WHERE subject_kind='user_claim' AND subject_id=?", (claim_id,))
        for tid in (f"expand:{claim_id}", f"check:{claim_id}"):
            cx.execute("DELETE FROM results WHERE task_id=?", (tid,))
            cx.execute("DELETE FROM tasks WHERE task_id=?", (tid,))
        cx.execute("DELETE FROM user_claims WHERE claim_id=?", (claim_id,))
