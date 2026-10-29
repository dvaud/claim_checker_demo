"""Score a model on tasks that a reference model already answered, before trusting it with new work.

Typical use: run a local model on a sample of the pilot's VCA checks and extraction passages, and compare its answers
with the pilot's Claude Opus answers. Nothing is stored: answers are validated in a transaction that is rolled back.

What is measured, per task kind:
- usable: the answer passed every check (format, quotes, passage numbers) on the first try
- quote problems: share of answers with at least one quote not found in the text it was given
- seconds per task, on this computer
- agreement with the reference answer:
  - verify_set: same claim status (supported / partly / contradicted / nothing), grounded or not (Cohen's kappa),
    and the same grade per passage
  - extract: passage has a claim or not (kappa), overlap of the SDG targets named, same direction on shared targets
  - label (0.7): code present or not, over the candidate codes and the codes either answer names (kappa), and the
    share of passages labelled with exactly the same codes

Agreement with the reference is not correctness: the reference is itself unreviewed model output.

With Claude Code (0.8.1) the sample waits in the queue of a scratch copy of the reference, removed afterwards; each
kind is answered by `model` when it is one of haiku, sonnet, opus or fable, else by the model the router names for
that kind. Only the first answer to each task is scored ("usable on the first try"), and the seconds per task are
those Claude Code took.
"""
from __future__ import annotations

import json
import random
import sqlite3
import statistics
import time
from typing import Callable

from . import prompts
from .analysis import _prf
from .tasks import HANDLERS, _errs, parse_json
from .store import Workspace

GROUNDED = {"supported", "partially_supported"}


def _status_from(out: dict, n_passages: int, thr: float) -> str:
    grades = [e for e in (out.get("evidence") or []) if isinstance(e, dict)
              and float(e.get("confidence") or 0) >= thr]
    kinds = {str(e.get("verdict")) for e in grades}
    if "supports" in kinds:
        return "supported"
    if "partially_supports" in kinds or "partial" in kinds:
        return "partially_supported"
    if "refutes" in kinds:
        return "contradicted"
    return "unsupported"


def _grades(out: dict, n: int) -> list[str]:
    g = ["none"] * n
    for e in out.get("evidence") or []:
        try:
            i = int(str(e.get("passage")).upper().lstrip("P")) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= i < n:
            g[i] = str(e.get("verdict"))
    return g


def _targets(out: dict) -> dict[str, str]:
    from .taxonomy import normalise_target

    found: dict[str, str] = {}
    for c in out.get("claims") or []:
        for t in (c.get("targets") or []) if isinstance(c, dict) else []:
            code = normalise_target(t.get("target")) if isinstance(t, dict) else None
            if code:
                found.setdefault(code, str(t.get("direction")))
    return found


def _codes(out: dict, payload: dict) -> set[str]:
    from . import frameworks

    try:
        fw = frameworks.get(payload.get("framework") or "sdg")
    except ValueError:
        fw = None
    got = set()
    for lb in out.get("labels") or []:
        if isinstance(lb, dict) and lb.get("code"):
            c = fw.normalise(lb["code"]) if fw else str(lb["code"])
            if c:
                got.add(c)
    return got


def _sample(ws: Workspace, kind: str, n: int, seed: int) -> list:
    rows = ws.query("SELECT t.* FROM tasks t WHERE t.kind=? AND t.status='done' AND t.task_id NOT LIKE '%:audit:%' "
                    "ORDER BY t.task_id", (kind,))
    rng = random.Random(seed)
    return rng.sample(list(rows), min(n, len(rows)))


def _reference(ws: Workspace, task_id: str) -> dict | None:
    r = ws.query("SELECT raw_json FROM results WHERE task_id=? AND valid=1 ORDER BY attempt LIMIT 1", (task_id,))
    if not r:
        return None
    try:
        return parse_json(r[0][0])
    except ValueError:
        return None


def _queue_models(backend, model: str | None, kinds) -> dict:
    """Claude Code: the model of each kind, `model` when it is an alias, else the routed one."""
    from . import routing

    r = getattr(backend, "router", None)
    if r is None:
        from .home import load_settings

        r = routing.from_settings(load_settings(), route="claude_code")
    return {k: (model if model in routing.ALIASES else r.first(k) or "opus") for k in kinds}


def run(ws: Workspace, backend, model: str | None, kinds=("verify_set", "extract"), sample: int = 30, seed: int = 0,
        progress: Callable[[int, int, str], None] | None = None) -> dict:
    thr = float(ws.config["thresholds"]["support_confidence"])
    jobs = [(k, t) for k in kinds for t in _sample(ws, k, sample, seed)]
    if not jobs:
        raise ValueError("The reference workspace has no answered tasks of these kinds.")
    per: dict[str, list[dict]] = {k: [] for k in kinds}
    queued = secs = models = None
    if getattr(backend, "name", "") == "claude_code":
        from .taskqueue import answer_on_copy

        models = _queue_models(backend, model, kinds)
        queued, secs = answer_on_copy(ws, [(t["task_id"], k, json.loads(t["payload_json"]), models[k])
                                           for k, t in jobs], backend, "model test",
                                      should_stop=getattr(backend, "should_stop", None))
    cx = sqlite3.connect(ws.db_path, timeout=60)
    cx.row_factory = sqlite3.Row
    try:
        for i, (kind, t) in enumerate(jobs, 1):
            if progress:
                progress(i, len(jobs), t["task_id"])
            payload = json.loads(t["payload_json"])
            system, user = prompts.system_prompt(kind), prompts.user_prompt(kind, payload)
            rec: dict = {"task_id": t["task_id"]}
            t0 = time.time()
            try:
                if queued is not None:
                    raw = queued.get(t["task_id"])
                    if raw is None:
                        raise ValueError("Claude Code gave no answer to this task")
                else:
                    raw = backend.complete(kind, system, user, model, payload)
            except Exception as e:  # keep going: one failure should not stop the benchmark
                rec.update(error=str(e)[:300], seconds=round(time.time() - t0, 2))
                per[kind].append(rec)
                continue
            rec["seconds"] = (secs.get((kind, models[kind])) or 0.0) if secs is not None else round(time.time() - t0, 2)
            try:
                out = parse_json(raw)
                rec["json_ok"] = True
                ok, errors = HANDLERS[kind](cx, t, payload, out, models[kind] if models else model)
            except Exception as e:
                out, ok, errors = None, False, (_errs(e) if hasattr(e, "errors") else [str(e)])
                rec["json_ok"] = out is not None
            finally:
                cx.rollback()
            rec["usable"] = bool(ok and not errors)
            rec["quote_problem"] = any("quote" in e and "not found" in e for e in errors)
            rec["errors"] = errors[:5]
            ref = _reference(ws, t["task_id"])
            if out is not None and ref is not None:
                if kind in ("verify_set", "check"):
                    n = len(payload["passages"])
                    rec["status"], rec["ref_status"] = _status_from(out, n, thr), _status_from(ref, n, thr)
                    a, b = _grades(out, n), _grades(ref, n)
                    rec["same_grades"], rec["passages"] = sum(x == y for x, y in zip(a, b)), n
                elif kind == "label":
                    a, b = _codes(out, payload), _codes(ref, payload)
                    universe = {c["code"] for c in payload.get("candidates") or []} | a | b
                    rec["code_pairs"] = [(c in b, c in a) for c in sorted(universe)]
                    rec["same_codes"] = a == b
                elif kind == "extract":
                    ta, tb = _targets(out), _targets(ref)
                    rec["has_claims"], rec["ref_has_claims"] = bool(ta), bool(tb)
                    if ta and tb:
                        shared = set(ta) & set(tb)
                        rec["target_jaccard"] = round(len(shared) / len(set(ta) | set(tb)), 3)
                        rec["same_direction"] = [ta[c] == tb[c] for c in shared]
            per[kind].append(rec)
    finally:
        cx.close()
    out = {"model": model or ("the routed models" if models else model), "backend": getattr(backend, "name", ""),
           "sample_per_kind": sample, "seed": seed,
           "reference": _ref_models(ws, kinds), "threshold": thr,
           "kinds": {k: _summarise(k, v) for k, v in per.items()}, "tasks": per}
    if models:
        out["models"] = models
    return out


def _ref_models(ws: Workspace, kinds) -> dict:
    out = {}
    for k in kinds:
        r = ws.query("SELECT model, COUNT(*) AS n FROM results WHERE kind=? AND valid=1 GROUP BY model ORDER BY n DESC", (k,))
        out[k] = r[0]["model"] if r else None
    return out


def _summarise(kind: str, recs: list[dict]) -> dict:
    n = len(recs)
    answered = [r for r in recs if "error" not in r]
    secs = [r["seconds"] for r in answered]
    s = {"tasks": n, "errors": n - len(answered),
         "usable": round(sum(r.get("usable", False) for r in recs) / n, 3) if n else None,
         "valid_json": round(sum(r.get("json_ok", False) for r in recs) / n, 3) if n else None,
         "quote_problems": round(sum(r.get("quote_problem", False) for r in recs) / n, 3) if n else None,
         "seconds_median": round(statistics.median(secs), 1) if secs else None,
         "seconds_total": round(sum(secs), 1)}
    if kind in ("verify_set", "check"):
        pairs = [(r["ref_status"], r["status"]) for r in recs if "status" in r]
        if pairs:
            tp = sum(a in GROUNDED and b in GROUNDED for a, b in pairs)
            fp = sum(a not in GROUNDED and b in GROUNDED for a, b in pairs)
            fn = sum(a in GROUNDED and b not in GROUNDED for a, b in pairs)
            s["same_status"] = round(sum(a == b for a, b in pairs) / len(pairs), 3)
            s["grounded_kappa"] = _prf(tp, fp, fn, len(pairs) - tp - fp - fn)["kappa"]
            s["same_passage_grade"] = round(sum(r["same_grades"] for r in recs if "same_grades" in r)
                                            / sum(r["passages"] for r in recs if "passages" in r), 3)
            s["compared"] = len(pairs)
    if kind == "label":
        pairs = [p for r in recs for p in r.get("code_pairs", [])]
        if pairs:
            tp = sum(a and b for a, b in pairs)
            fp = sum((not a) and b for a, b in pairs)
            fn = sum(a and not b for a, b in pairs)
            s["codes_kappa"] = _prf(tp, fp, fn, len(pairs) - tp - fp - fn)["kappa"]
            same = [r["same_codes"] for r in recs if "same_codes" in r]
            s["same_codes"] = round(sum(same) / len(same), 3) if same else None
            s["compared"] = len(same)
    if kind == "extract":
        pairs = [(r["ref_has_claims"], r["has_claims"]) for r in recs if "has_claims" in r]
        if pairs:
            tp = sum(a and b for a, b in pairs)
            fp = sum((not a) and b for a, b in pairs)
            fn = sum(a and not b for a, b in pairs)
            s["claims_kappa"] = _prf(tp, fp, fn, len(pairs) - tp - fp - fn)["kappa"]
            s["same_has_claims"] = round(sum(a == b for a, b in pairs) / len(pairs), 3)
            jac = [r["target_jaccard"] for r in recs if "target_jaccard" in r]
            s["target_overlap"] = round(statistics.mean(jac), 3) if jac else None
            dirs = [x for r in recs for x in r.get("same_direction", [])]
            s["same_direction"] = round(sum(dirs) / len(dirs), 3) if dirs else None
            s["compared"] = len(pairs)
    return s


def verdict(summary: dict) -> list[str]:
    """Plain-language reading of a benchmark, with the thresholds used, for the GUI and the CLI."""
    lines = []
    for kind, s in summary["kinds"].items():
        name = {"verify_set": "Checking claims", "check": "Checking claims", "extract": "Extracting claims",
                "label": "Labelling passages with codes"}.get(kind, kind)
        if not s["tasks"]:
            continue
        if s["errors"] == s["tasks"]:
            lines.append(f"{name}: every task failed; see the errors.")
            continue
        usable = s["usable"] or 0
        agree = {"extract": s.get("claims_kappa"), "label": s.get("codes_kappa")}.get(kind, s.get("grounded_kappa"))
        if usable >= 0.9 and (agree or 0) >= 0.6:
            word = "good enough to use, with review"
        elif usable >= 0.75 and (agree or 0) >= 0.4:
            word = "usable for a first pass; review its results"
        else:
            word = "not reliable enough"
        a = "–" if agree is None else f"{agree:.2f}"
        lines.append(f"{name}: {word} (usable answers {usable:.0%}, agreement with the reference κ {a}, "
                     f"median {s['seconds_median']} s per task).")
    return lines
