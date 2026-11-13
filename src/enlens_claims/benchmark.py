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
    from . import access

    # 0.11: only answered tasks whose documents this model may read are sent again
    jobs = [(k, t) for k in kinds for t in _sample(ws, k, sample, seed)
            if access.may_read(ws, json.loads(t["payload_json"]), backend)]
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
                    access.sending(ws, payload, backend, f"{kind} (model test)", t["task_id"])
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


# ---------------------------------------------------------------------------------------------
# 0.18.1 (I5): agreement between routes
# ---------------------------------------------------------------------------------------------
# A sample of answered tasks of one kind is answered by both the local model and Claude, and their decisions are
# compared with Cohen's kappa. Nothing is stored (a measurement, like the model test above). The kinds without a
# categorical decision (theme names, search words, hypothesis splits, resolved terms) are left out: there is no
# decision to compare, only wording.
AGREEMENT_KINDS = ("check", "reread", "second", "label", "link")
KAPPA_GOOD, KAPPA_FAIR = 0.8, 0.6    # kappa from this: good; from this: fair; below: poor
_CLAUDE_ROUTES = frozenset({"Claude Code", "Claude API", "Claude app (connector)"})
_LOCAL_ROUTE = "local model server"
_WHAT = {"check": "checking claims", "reread": "reading excerpts again", "second": "second opinions",
         "label": "labels", "link": "links between terms"}


def kappa(pairs: list[tuple]) -> float | None:
    """Cohen's kappa for two raters over any categories ((a, b) pairs of decisions). None when it is undefined: no
    pairs, or both raters used one and the same single category throughout (nothing to agree about)."""
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    cats = {x for p in pairs for x in p}
    pe = sum((sum(a == c for a, _ in pairs) / n) * (sum(b == c for _, b in pairs) / n) for c in cats)
    if pe >= 1:
        return None
    return round((po - pe) / (1 - pe), 3)


def _decisions(kind: str, payload: dict, out: dict, other: dict | None = None) -> dict:
    """The decisions in an answer, by key: the grade of each excerpt (check, reread, second), whether each candidate
    code applies (label; the codes of `other` count as candidates too, as in the model test) or the relation of each
    pair of terms (link). What an answer leaves out counts as "none" ("no"), as it does in the stored results."""
    if kind in ("check", "reread", "second"):
        g = _grades(out, len(payload.get("passages") or []))
        return {f"P{i}": ("partially_supports" if v == "partial" else v) for i, v in enumerate(g, 1)}
    if kind == "label":
        mine = _codes(out, payload)
        universe = {c["code"] for c in payload.get("candidates") or []} | mine | (_codes(other, payload) if other else set())
        return {c: ("yes" if c in mine else "no") for c in sorted(universe)}
    if kind == "link":
        n = len(payload.get("terms") or [])
        got = {}
        for r in out.get("relations") or []:
            if isinstance(r, dict):
                try:
                    got[(int(r["a"]), int(r["b"]))] = str(r.get("relation"))
                except (KeyError, TypeError, ValueError):
                    continue
        return {f"{a}-{b}": got.get((a, b), "none") for a in range(1, n + 1) for b in range(a + 1, n + 1)}
    raise ValueError(f"There is no decision to compare for {kind} tasks.")


def _stored(ws: Workspace, task_id: str) -> dict:
    """The answers a task already has, by route: {"local": raw, "claude": raw}. The newest accepted answer of each
    (a task the local model was unsure of has both)."""
    out: dict = {"local": None, "claude": None}
    for r in ws.query("SELECT raw_json, route FROM results WHERE task_id=? AND valid=1 ORDER BY attempt", (task_id,)):
        side = "claude" if r["route"] in _CLAUDE_ROUTES else "local" if r["route"] == _LOCAL_ROUTE else None
        if side:
            out[side] = r["raw_json"]
    return out


def agreement_kinds(ws: Workspace) -> list[dict]:
    """The kinds with a decision to compare that have answered tasks here: [{"kind", "answered", "name"}]."""
    from .taskqueue import NOUN

    out = []
    for k in AGREEMENT_KINDS:
        n = ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind=? AND status='done' AND task_id NOT LIKE '%:audit:%'", (k,))
        if n:
            out.append({"kind": k, "answered": n, "name": _WHAT[k], "noun": (NOUN.get(k) or ("task", "tasks"))[1]})
    return out


def _agreement_sample(ws: Workspace, kind: str, n: int, seed: int) -> tuple[list, int]:
    """(the tasks to compare, how many answered tasks are left out because Claude may not read their documents)."""
    from . import access

    if kind not in AGREEMENT_KINDS:
        raise ValueError(f"There is no decision to compare for {kind} tasks.")
    rows = _sample(ws, kind, 10 ** 9, seed)
    with ws.connect() as cx:
        ok = [t for t in rows if access.label_payload(cx, json.loads(t["payload_json"])) == "cloud"]
    rng = random.Random(seed)
    return rng.sample(ok, min(n, len(ok))), len(rows) - len(ok)


def agreement_plan(ws: Workspace, kind: str, n: int = 30, seed: int = 0) -> dict:
    """What an agreement run would do, before it starts: {"kind", "n" (tasks compared), "ask_local", "ask_claude"
    (tasks each route is asked: answers it already has are reused), "left_out" (answered tasks Claude may not read)}."""
    sample, left_out = _agreement_sample(ws, kind, n, seed)
    have = [_stored(ws, t["task_id"]) for t in sample]
    return {"kind": kind, "n": len(sample), "ask_local": sum(h["local"] is None for h in have),
            "ask_claude": sum(h["claude"] is None for h in have), "left_out": left_out}


def verdict_sentence(kind: str, kap: float | None, agree: float | None, compared: int) -> str:
    """A plain sentence on what the agreement means: kappa from 0.8 is good, from 0.6 fair, below that poor."""
    what = _WHAT.get(kind, kind)
    if not compared or agree is None:
        return f"Nothing could be compared for {what}: no task was answered by both."
    pct = f"{agree:.0%}"
    if kap is None:
        return (f"Too little variety in the decisions to measure kappa for {what}: the local model and Claude agree "
                f"on {pct} of them.")
    s = f"the local model agrees with Claude on {pct} of decisions (kappa {kap:.2f})"
    if kap >= KAPPA_GOOD:
        return f"Good enough for {what}: {s}."
    if kap >= KAPPA_FAIR:
        return f"Fair for {what}: {s}. Review what it answers."
    return f"Not good enough for {what}: {s}. Let Claude read these."


def agreement(ws: Workspace, kind: str, n: int, local, claude_backend, seed: int = 0, progress=None,
              should_stop=None, claude_model: str | None = None) -> dict:
    """Have the local model and Claude answer the same tasks and compare their decisions. `local`: (backend, model)
    of the local model; `claude_backend`: Claude Code (answered on a scratch copy, see taskqueue.answer_on_copy) or the
    Claude API backend (asked directly, each excerpt set noted in the ledger of what left this computer). Only
    tasks whose documents Claude may read are used. An answer a task already has from a route is reused, so only what
    is missing is asked. Nothing is stored in the project. Returns the shape described in docs/API.md."""
    from . import access, tasks

    be_l, model_l = local
    sample, left_out = _agreement_sample(ws, kind, n, seed)
    if not sample:
        raise ValueError("No answered task of this kind may be read by Claude, so there is nothing to compare.")
    have = {t["task_id"]: _stored(ws, t["task_id"]) for t in sample}
    code = getattr(claude_backend, "name", "") == "claude_code"

    def claude_alias(t) -> str:
        if code:
            return claude_model if claude_model in ("haiku", "sonnet", "opus", "fable") else _queue_models(
                claude_backend, None, [kind])[kind]
        return tasks.model_for({"forced_model": None, "step": 0, "kind": kind, "role": None, "model": claude_model},
                               claude_backend, claude_model)

    asked = {"local": 0, "claude": 0}
    queued: dict = {}
    todo = [t for t in sample if have[t["task_id"]]["claude"] is None]
    if code and todo:
        from .taskqueue import answer_on_copy

        queued, _secs = answer_on_copy(ws, [(t["task_id"], kind, json.loads(t["payload_json"]), claude_alias(t))
                                            for t in todo], claude_backend, "agreement between routes",
                                       should_stop=should_stop)
    items, pairs, failed = [], [], 0
    for i, t in enumerate(sample, 1):
        if should_stop and should_stop():
            break
        if progress:
            progress(i, len(sample))
        tid, payload = t["task_id"], json.loads(t["payload_json"])
        raws, how = dict(have[tid]), {"local": "stored", "claude": "stored"}
        try:
            system, user = prompts.system_prompt(kind), prompts.user_prompt(kind, payload)
            if raws["local"] is None:
                how["local"] = "asked"
                access.sending(ws, payload, be_l, f"{kind} (agreement)", tid)
                raws["local"] = be_l.complete(kind, system, user, model_l, payload)
                asked["local"] += 1
            if raws["claude"] is None:
                how["claude"] = "asked"
                if code:
                    raws["claude"] = queued.get(tid)
                    if raws["claude"] is None:
                        raise ValueError("Claude Code gave no answer to this task")
                else:
                    access.sending(ws, payload, claude_backend, f"{kind} (agreement)", tid)
                    raws["claude"] = claude_backend.complete(kind, system, user, claude_alias(t), payload)
                asked["claude"] += 1
            out_l, out_c = parse_json(raws["local"]), parse_json(raws["claude"])
            dl, dc = _decisions(kind, payload, out_l, out_c), _decisions(kind, payload, out_c, out_l)
        except Exception as e:  # noqa: BLE001 - one task failing must not stop the measurement; Stop does
            if str(e).startswith("Stopped"):
                raise
            failed += 1
            items.append({"task_id": tid, "error": str(e)[:200]})
            continue
        keys = sorted(set(dl) | set(dc))
        ps = [(dl.get(k, "none"), dc.get(k, "none")) for k in keys]
        pairs += ps
        items.append({"task_id": tid, "decisions": len(ps), "same": sum(a == b for a, b in ps), "local": how["local"],
                      "claude": how["claude"]})
    kap = kappa(pairs)
    agree = round(sum(a == b for a, b in pairs) / len(pairs), 3) if pairs else None
    return {"kind": kind, "n": len(sample), "compared": len(items) - failed, "failed": failed, "kappa": kap,
            "agree": agree, "decisions": len(pairs), "items": items, "left_out": left_out, "asked": asked,
            "verdict": verdict_sentence(kind, kap, agree, len(pairs)),
            "thresholds": {"good": KAPPA_GOOD, "fair": KAPPA_FAIR}}
