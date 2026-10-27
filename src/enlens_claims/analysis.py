"""Aggregate claims into effects, candidate interactions and comparisons with the VCA."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from itertools import combinations

from .store import Workspace
from .taxonomy import SEGMENTS, goal_of, target_sort_key, targets

USABLE_DEFAULT = ("auto", "needs_review", "accepted", "changed")
USABLE_STRICT = ("auto", "accepted", "changed")


def _statuses(strict: bool) -> tuple[str, ...]:
    return USABLE_STRICT if strict else USABLE_DEFAULT


def claim_rows(ws: Workspace, strict: bool = False) -> list[dict]:
    st = _statuses(strict)
    rows = ws.query(
        f"SELECT c.*, ct.target, ct.direction, ct.influence, d.title, d.doi FROM claims c "
        f"JOIN claim_targets ct ON ct.claim_id=c.claim_id JOIN documents d ON d.doc_id=c.doc_id "
        f"WHERE c.status IN ({','.join('?' * len(st))})", st)
    out = []
    for r in rows:
        d = dict(r)
        d["countries"] = json.loads(d.pop("countries_json") or "[]")
        out.append(d)
    return out


def evidence_for(ws: Workspace, claim_id: str) -> list[dict]:
    return [dict(r) for r in ws.query("SELECT * FROM evidence WHERE claim_id=? ORDER BY field='claim' DESC", (claim_id,))]


# ---------------------------------------------------------------------------------------------
# effects
# ---------------------------------------------------------------------------------------------
def net_sign(pos: int, neg: int) -> str:
    if pos and neg:
        if pos >= 2 * neg:
            return "positive"
        if neg >= 2 * pos:
            return "negative"
        return "mixed"
    if pos:
        return "positive"
    if neg:
        return "negative"
    return ""


def effects(ws: Workspace, strict: bool = False) -> list[dict]:
    """One row per (target, segment): documents and claims behind each direction."""
    groups: dict[tuple[str, str], dict] = {}
    for r in claim_rows(ws, strict):
        key = (r["target"], r["segment"])
        g = groups.setdefault(key, {"target": r["target"], "segment": r["segment"], "claims": [], "docs_pos": set(),
                                    "docs_neg": set(), "docs_other": set(), "influence": Counter(), "horizon": Counter(),
                                    "countries": Counter(), "side": Counter(), "conditions": []})
        g["claims"].append(r["claim_id"])
        bucket = {"positive": "docs_pos", "negative": "docs_neg"}.get(r["direction"], "docs_other")
        if r["direction"] == "mixed":
            g["docs_pos"].add(r["doc_id"])
            g["docs_neg"].add(r["doc_id"])
        else:
            g[bucket].add(r["doc_id"])
        g["influence"][r["influence"]] += 1
        g["horizon"][r["horizon"]] += 1
        for c in r["countries"]:
            g["countries"][c] += 1
        g["side"][r["side"]] += 1
        if r["condition"] or r["policy_lever"]:
            g["conditions"].append({"claim_id": r["claim_id"], "condition": r["condition"], "policy_lever": r["policy_lever"],
                                    "direction": r["direction"]})
    out = []
    for (t, seg), g in groups.items():
        docs = g["docs_pos"] | g["docs_neg"] | g["docs_other"]
        stated = {k: v for k, v in g["horizon"].items() if k != "not_stated"}
        out.append({
            "target": t, "goal": goal_of(t), "segment": seg, "n_claims": len(g["claims"]), "n_docs": len(docs),
            "docs_positive": len(g["docs_pos"]), "docs_negative": len(g["docs_neg"]),
            "sign": net_sign(len(g["docs_pos"]), len(g["docs_neg"])),
            "influence": g["influence"].most_common(1)[0][0] if g["influence"] else "",
            "horizon": max(stated, key=stated.get) if stated else "not_stated",
            "horizons": dict(g["horizon"]), "countries": dict(g["countries"].most_common(8)),
            "sides": dict(g["side"]), "conditions": g["conditions"], "claim_ids": g["claims"],
        })
    out.sort(key=lambda x: (target_sort_key(x["target"]), x["segment"]))
    return out


# ---------------------------------------------------------------------------------------------
# candidate interactions between targets
# ---------------------------------------------------------------------------------------------
def _compatible(a: dict, b: dict) -> bool:
    loose = ("whole_chain", "unclear")
    if a["segment"] != b["segment"] and a["segment"] not in loose and b["segment"] not in loose:
        return False
    ca, cb = set(a["countries"]), set(b["countries"])
    return not (ca and cb and not (ca & cb))


def _relation(d1: str, d2: str) -> str | None:
    if d1 == "positive" and d2 == "positive":
        return "synergy"
    if {d1, d2} == {"positive", "negative"}:
        return "trade_off"
    if d1 == "negative" and d2 == "negative":
        return "shared_pressure"
    return None


def infer_interactions(ws: Workspace, strict: bool = False) -> int:
    """Pairs of targets that the same document links to the same activity, segment and place.

    These are candidates only: the text does not state that one target affects the other. 'synergy' = both
    helped, 'trade_off' = one helped and one hindered, 'shared_pressure' = both hindered.
    """
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for r in claim_rows(ws, strict):
        by_doc[r["doc_id"]].append(r)
    rows = {}
    for doc, rs in by_doc.items():
        for a, b in combinations(rs, 2):
            if a["target"] == b["target"] or not _compatible(a, b):
                continue
            rel = _relation(a["direction"], b["direction"])
            if not rel:
                continue
            t1, t2 = sorted((a["target"], b["target"]), key=target_sort_key)
            iid = "x" + hashlib.sha1(f"{doc}|{t1}|{t2}|{rel}".encode()).hexdigest()[:12]
            rows[iid] = (iid, f"{a['claim_id']}|{b['claim_id']}", doc, t1, t2, None, rel, None, None, None, f"inferred_{rel}")
    with ws.connect() as cx:
        cx.execute("DELETE FROM interactions WHERE kind LIKE 'inferred%'")
        cx.executemany("INSERT INTO interactions VALUES (?,?,?,?,?,?,?,?,?,?,?)", list(rows.values()))
    return len(rows)


def interaction_table(ws: Workspace) -> list[dict]:
    agg: dict[tuple[str, str, str], dict] = {}
    for r in ws.query("SELECT * FROM interactions"):
        kind = r["kind"]
        if kind == "stated":
            rel = "stated"
            t1, t2 = r["from_target"], r["to_target"]
        else:
            rel = kind.replace("inferred_", "")
            t1, t2 = r["from_target"], r["to_target"]
        key = (t1, t2, rel)
        g = agg.setdefault(key, {"from": t1, "to": t2, "relation": rel, "docs": set(), "scores": [], "quotes": []})
        g["docs"].add(r["doc_id"])
        if r["score"] is not None:
            g["scores"].append(r["score"])
        if r["quote"] and kind == "stated":
            g["quotes"].append({"quote": r["quote"], "doc_id": r["doc_id"], "page": r["page"]})
    out = []
    for g in agg.values():
        out.append({"from": g["from"], "to": g["to"], "relation": g["relation"], "n_docs": len(g["docs"]),
                    "score": round(sum(g["scores"]) / len(g["scores"]), 1) if g["scores"] else None,
                    "cross_goal": goal_of(g["from"]) != goal_of(g["to"]), "quotes": g["quotes"][:3]})
    out.sort(key=lambda x: (-x["n_docs"], x["relation"], target_sort_key(x["from"]), target_sort_key(x["to"])))
    return out


# ---------------------------------------------------------------------------------------------
# comparison with the VCA
# ---------------------------------------------------------------------------------------------
def _graded(vs, thr: float) -> tuple[list, list, list]:
    strong = [v for v in vs if v["confidence"] is not None and v["confidence"] >= thr]
    return ([v for v in strong if v["verdict"] == "supports"], [v for v in strong if v["verdict"] == "partially_supports"],
            [v for v in strong if v["verdict"] == "refutes"])


def _status(vs, thr: float) -> str:
    """A VCA claim's status from its verification rows: the strongest grade at or above the threshold wins."""
    if not vs:
        return "not_checked"
    sup, part, ref = _graded(vs, thr)
    return "supported" if sup else "partially_supported" if part else "contradicted" if ref else "unsupported"


def vca_support(ws: Workspace) -> list[dict]:
    thr = float(ws.config["thresholds"]["support_confidence"])
    from .sources import docs_for_target

    out = []
    doc_cache: dict[str, list[str]] = {}
    for vc in ws.query("SELECT * FROM vca_claims ORDER BY target, seq"):
        t = vc["target"]
        if t not in doc_cache:
            doc_cache[t] = docs_for_target(ws, t)
        vs = ws.query("SELECT v.*, d.title FROM verifications v JOIN documents d ON d.doc_id=v.doc_id "
                      "WHERE subject_kind='vca_claim' AND subject_id=? ORDER BY confidence IS NULL, confidence DESC", (vc["vca_claim_id"],))
        sup, part, ref = _graded(vs, thr)
        status = "source_missing" if not doc_cache[t] else _status(vs, thr)
        out.append({
            "vca_claim_id": vc["vca_claim_id"], "target": t, "text": vc["text"], "segment": vc["segment"],
            "direction": vc["direction"], "horizon": vc["horizon"], "status": status, "n_checked": len(vs),
            "n_sources": len(doc_cache[t]), "n_supporting_docs": len({v["doc_id"] for v in sup}),
            "support": [{"quote": v["quote"], "title": v["title"], "page": v["page"], "confidence": v["confidence"]} for v in sup[:3]],
            "partial": [{"quote": v["quote"], "title": v["title"], "page": v["page"], "confidence": v["confidence"]} for v in part[:3]],
            "refute": [{"quote": v["quote"], "title": v["title"], "page": v["page"], "confidence": v["confidence"]} for v in ref[:2]],
            "n_refuting": len(ref),
        })
    return out


def _gold_sign(cell: str) -> str:
    signs = {p.split("_")[1] for p in cell.split("+") if p}
    if not signs:
        return ""
    return signs.pop() if len(signs) == 1 else "mixed"


def _gold_kind(cell: str) -> str:
    kinds = {p.split("_")[0] for p in cell.split("+") if p}
    return kinds.pop() if len(kinds) == 1 else ("both" if kinds else "")


def _prf(tp: int, fp: int, fn: int, tn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    n = tp + fp + fn + tn
    po = (tp + tn) / n if n else 0.0
    pe = (((tp + fp) * (tp + fn)) + ((fn + tn) * (fp + tn))) / (n * n) if n else 0.0
    kappa = (po - pe) / (1 - pe) if pe < 1 else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": round(p, 3), "recall": round(r, 3), "f1": round(f, 3),
            "kappa": round(kappa, 3)}


def label_recovery(ws: Workspace, strict: bool = False, min_docs: int = 1, only_covered: bool = True) -> dict:
    """Does evidence extracted from the sources reproduce the VCA's cells?

    only_covered: score only justified targets for which at least one cited source was available, so missing
    PDFs are not counted as model errors. Effects found for targets the VCA left empty are listed separately
    as new candidates.
    """
    from .sources import coverage

    cov = {c["target"]: c for c in coverage(ws)}
    gold = {r["target"]: dict(r) for r in ws.query("SELECT * FROM vca_targets")}
    eff = {(e["target"], e["segment"]): e for e in effects(ws, strict) if e["n_docs"] >= min_docs}
    by_target: dict[str, list[dict]] = defaultdict(list)
    for e in eff.values():
        by_target[e["target"]].append(e)

    def in_scope(t: str) -> bool:
        if not only_covered:
            return True
        c = cov.get(t)
        return bool(c and c["available"] > 0)

    # target level
    tp = fp = fn = tn = 0
    sign_pairs = []
    horizon_pairs = []
    rows = []
    for t in sorted(gold, key=target_sort_key):
        if not in_scope(t):
            continue
        g = gold[t]
        g_cells = [g[s] for s in SEGMENTS]
        g_present = any(g_cells)
        p_list = by_target.get(t, [])
        p_present = bool(p_list)
        tp += g_present and p_present
        fp += (not g_present) and p_present
        fn += g_present and not p_present
        tn += (not g_present) and not p_present
        g_signs = {_gold_sign(c) for c in g_cells if c}
        g_sign = g_signs.pop() if len(g_signs) == 1 else ("mixed" if g_signs else "")
        pos = sum(e["docs_positive"] for e in p_list)
        neg = sum(e["docs_negative"] for e in p_list)
        p_sign = net_sign(pos, neg)
        if g_present and p_present:
            sign_pairs.append((g_sign, p_sign))
        p_h = Counter()
        for e in p_list:
            for h, n in e["horizons"].items():
                if h != "not_stated":
                    p_h[h] += n
        p_hz = p_h.most_common(1)[0][0] if p_h else ""
        if g["horizon"] and p_hz:
            horizon_pairs.append((g["horizon"], p_hz))
        rows.append({"target": t, "gold_present": g_present, "gold_sign": g_sign, "gold_horizon": g["horizon"],
                     "pred_present": p_present, "pred_sign": p_sign, "pred_claims": len({c for e in p_list for c in e["claim_ids"]}),
                     "pred_horizon": p_hz, "sources_available": (cov.get(t) or {}).get("available", 0)})
    # cell level
    ctp = cfp = cfn = ctn = 0
    cell_sign = []
    cell_kind = []
    cell_rows = []
    for t in sorted(gold, key=target_sort_key):
        if not in_scope(t):
            continue
        for s in SEGMENTS:
            gc = gold[t][s]
            e = eff.get((t, s))
            gp, pp = bool(gc), bool(e)
            ctp += gp and pp
            cfp += (not gp) and pp
            cfn += gp and not pp
            ctn += (not gp) and not pp
            if gp and pp:
                cell_sign.append((_gold_sign(gc), e["sign"]))
                if e["influence"] in ("direct", "indirect"):
                    cell_kind.append((_gold_kind(gc), e["influence"]))
            if gp or pp:
                cell_rows.append({"target": t, "segment": s, "gold": gc, "pred_sign": e["sign"] if e else "",
                                  "pred_influence": e["influence"] if e else "", "pred_docs": e["n_docs"] if e else 0})

    def acc(pairs):
        return {"n": len(pairs), "agree": sum(a == b for a, b in pairs),
                "accuracy": round(sum(a == b for a, b in pairs) / len(pairs), 3) if pairs else None}

    new = [e for e in eff.values() if e["segment"] in SEGMENTS and not gold.get(e["target"], {}).get(e["segment"]) and e["n_docs"] >= 2]
    return {
        "scope": "targets with at least one cited source available" if only_covered else "all 169 targets",
        "targets_scored": len(rows), "target_presence": _prf(tp, fp, fn, tn), "target_sign": acc(sign_pairs),
        "horizon": acc(horizon_pairs), "cell_presence": _prf(ctp, cfp, cfn, ctn), "cell_sign": acc(cell_sign),
        "cell_influence": acc(cell_kind), "targets": rows, "cells": cell_rows,
        "new_candidates": sorted(({"target": e["target"], "segment": e["segment"], "sign": e["sign"], "n_docs": e["n_docs"]} for e in new),
                                 key=lambda x: (-x["n_docs"], target_sort_key(x["target"]))),
    }


def target_label(code: str) -> str:
    t = targets().get(code)
    return f"{code} {t.description[:90]}" if t else code


def status_sensitivity(ws: Workspace, thresholds=(0.0, 0.5, 0.6, 0.7, 0.8)) -> list[dict]:
    """How the VCA claim statuses shift with the confidence threshold (claims with sources only)."""
    rows = ws.query("SELECT subject_id, verdict, confidence FROM verifications WHERE subject_kind='vca_claim'")
    by: dict[str, list] = defaultdict(list)
    for r in rows:
        by[r["subject_id"]].append(r)
    out = []
    for thr in thresholds:
        c = Counter(_status(vs, thr) for vs in by.values())
        out.append({"threshold": thr, **{k: c.get(k, 0) for k in
                    ("supported", "partially_supported", "contradicted", "unsupported")}})
    return out


def audit_summary(ws: Workspace) -> dict:
    """Agreement between the first answers and a second model on the audited samples."""
    thr = float(ws.config["thresholds"]["support_confidence"])
    out: dict = {}
    aud = ws.query("SELECT subject_id, verdict, confidence, passage_id, model FROM verifications WHERE subject_kind='vca_claim_audit'")
    if aud:
        prim = ws.query("SELECT subject_id, verdict, confidence, passage_id, model FROM verifications WHERE subject_kind='vca_claim' "
                        f"AND subject_id IN ({','.join('?' * len({a['subject_id'] for a in aud}))})",
                        tuple({a["subject_id"] for a in aud}))
        a_by, p_by = defaultdict(list), defaultdict(list)
        for r in aud:
            a_by[r["subject_id"]].append(r)
        for r in prim:
            p_by[r["subject_id"]].append(r)
        pairs = [(_status(p_by[k], thr), _status(a_by[k], thr)) for k in a_by]
        grounded = {"supported", "partially_supported"}
        tp = sum(1 for a, b in pairs if a in grounded and b in grounded)
        fp = sum(1 for a, b in pairs if a not in grounded and b in grounded)
        fn = sum(1 for a, b in pairs if a in grounded and b not in grounded)
        tn = len(pairs) - tp - fp - fn
        pa = {(r["subject_id"], r["passage_id"]): r["verdict"] for r in prim}
        pb = {(r["subject_id"], r["passage_id"]): r["verdict"] for r in aud}
        same = [pa[k] == pb[k] for k in pb if k in pa]
        out["vca_checks"] = {
            "claims": len(pairs), "models": sorted({r["model"] for r in aud}),
            "status_agreement": round(sum(a == b for a, b in pairs) / len(pairs), 3),
            "grounded_agreement": _prf(tp, fp, fn, tn),
            "passage_grade_agreement": round(sum(same) / len(same), 3) if same else None,
            "confusion": dict(Counter(f"{a} -> {b}" for a, b in pairs)),
        }
    cl = ws.query("SELECT verdict, confidence, model FROM verifications WHERE subject_kind='claim'")
    if cl:
        out["claim_checks"] = {"claims": len(cl), "models": sorted({r["model"] for r in cl}),
                               "verdicts": dict(Counter(r["verdict"] for r in cl)),
                               "supported_share": round(sum(r["verdict"] == "supports" and (r["confidence"] or 0) >= thr
                                                            for r in cl) / len(cl), 3)}
    return out


def vca_consistency(ws: Workspace) -> dict:
    """Does each claim in a VCA justification agree with the colour of the VCA's own cell?

    A claim tied to one segment is compared with that segment's cell; a whole-chain or unclear claim with all
    coloured cells of the target. 'differs': the text gives one direction and every compared cell the other (often a
    mitigation inside the justification of a negative cell, sometimes a real mismatch, so it is a flag for review).
    'no_cell': the text names a segment whose cell is empty. Mixed and no-effect claims are not compared.
    """
    gold = {r["target"]: dict(r) for r in ws.query("SELECT * FROM vca_targets")}
    rows = []
    for vc in ws.query("SELECT * FROM vca_claims ORDER BY target, seq"):
        g = gold.get(vc["target"], {})
        if vc["direction"] not in ("positive", "negative"):
            continue
        segs = [vc["segment"]] if vc["segment"] in SEGMENTS else [x for x in SEGMENTS if g.get(x)]
        cells = [g.get(x) or "" for x in segs]
        signs = {_gold_sign(c) for c in cells if c}
        if not signs:
            verdict = "no_cell"
        elif vc["direction"] in signs or "mixed" in signs:
            verdict = "consistent"
        else:
            verdict = "differs"
        rows.append({"vca_claim_id": vc["vca_claim_id"], "target": vc["target"], "segment": vc["segment"],
                     "text_direction": vc["direction"], "cells": {x: g.get(x) or "" for x in segs}, "verdict": verdict,
                     "text": vc["text"]})
    return {"compared": len(rows), "counts": dict(Counter(r["verdict"] for r in rows)), "rows": rows}
