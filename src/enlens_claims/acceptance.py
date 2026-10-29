"""The 0.7 acceptance measures on a reference workspace (the pilot): one person fills a fixed sample once, and every
release is scored against it.

    enlens --ws pilot acceptance samples          # writes acceptance/*.csv for a person to fill in once
    enlens --ws pilot acceptance measure          # scores the filled sheets
    enlens --ws pilot acceptance search           # F1, automatic: hits equal a regular expression; response time

| Feature | Sheet a person fills | Measure |
| F1 Search | (none) | hits equal a case-insensitive regular expression; median response time |
| F2 Profile | f2_labels.csv: 200 passages, their codes | kappa on "code present", per model; recall of pass 1's top 8 |
| F3 Concepts | f3_pairs.csv: 50 term pairs, same or not | agreement on same / different |
| F4 Themes | f4_themes.csv: the themes of one run, fitting or not | share of names judged fitting |
| F5 References | f5_pronouns.csv: grades whose quote opens with a pronoun | share where refers_to is right |
| F7 Highlights | f7_quotes.csv: 100 quotes, highlighted on the right words? | share right, with and without pdfminer |
| G6 Checks (0.8) | g6_checks.csv: 50 checked VCA claims, a person's status (supported, partially_supported, contradicted, unsupported) | agreement per model (evaluation.py) |

The team sets the pass marks before measuring, not after. Sheets that are not filled in are skipped.
"""
from __future__ import annotations

import csv
import random
import re
import statistics
import time
from pathlib import Path

from .store import Workspace

SEED = 7


def _write(path: Path, rows: list[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    return len(rows)


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _yes(v: str | None) -> bool | None:
    v = (v or "").strip().lower()
    if v in ("y", "yes", "1", "true", "ja", "x"):
        return True
    if v in ("n", "no", "0", "false", "nee"):
        return False
    return None


def make_samples(ws: Workspace, folder: str | Path, framework: str = "sdg") -> dict:
    """Write the sheets a person fills in once (existing sheets are never overwritten)."""
    from . import terms, themes

    folder = Path(folder)
    rng = random.Random(SEED)
    out = {}

    def write(name: str, rows: list[dict]) -> None:
        p = folder / name
        if p.exists():
            out[name] = "kept (already there)"
        else:
            out[name] = f"{_write(p, rows)} rows"

    body = ws.query("SELECT p.passage_id, p.page, p.text, d.title FROM passages p JOIN documents d ON d.doc_id=p.doc_id "
                    "WHERE p.section='body' ORDER BY p.passage_id")
    pick = rng.sample(list(body), min(200, len(body)))
    write("f2_labels.csv", [{"passage_id": r["passage_id"], "document": r["title"] or "", "page": r["page"] or "",
                             "text": r["text"], "codes": "", "note": ""} for r in pick])
    terms.ensure(ws)
    pairs = [(r["a"], r["b"]) for r in ws.query("SELECT a, b FROM concept_links ORDER BY a, b")]
    info = {r["term_id"]: r["label"] for r in ws.query("SELECT term_id, label FROM terms")}
    ids = sorted(info)
    possible = len(ids) * (len(ids) - 1) // 2
    tries = 0
    while len(pairs) < min(50, possible) and tries < 5000:
        tries += 1
        a, b = sorted(rng.sample(ids, 2))
        if (a, b) not in pairs:
            pairs.append((a, b))
    pairs = [p for p in pairs if p[0] in info and p[1] in info][:50]
    write("f3_pairs.csv", [{"a": a, "b": b, "term_a": info[a], "term_b": info[b], "same": "", "note": ""}
                           for a, b in pairs])
    runs = themes.runs(ws)
    rows = []
    if runs:
        v = themes.view(ws, runs[0]["run_id"])
        for t in v["themes"][:20]:
            rows.append({"run_id": runs[0]["run_id"], "theme_id": t["theme_id"], "name": t["name"],
                         "key_terms": ", ".join(t["terms"][:8]),
                         "passages": "\n\n".join(p["text"][:500] for p in t["representatives"]), "fitting": "",
                         "note": ""})
    write("f4_themes.csv", rows)
    from .references import pronoun_grades

    pg = pronoun_grades(ws)
    pg = rng.sample(pg, min(100, len(pg)))
    write("f5_pronouns.csv", [{"subject_id": r["subject_id"], "passage_id": r["passage_id"], "quote": r["quote"],
                               "refers_to": r["refers_to"] or "", "right": "", "should_be": ""} for r in pg])
    # 0.8 (G6): a person's own status for a sample of the reference's checked VCA claims (optional; the reference
    # answers are scored without it)
    vc = ws.query("SELECT vca_claim_id, target, text FROM vca_claims ORDER BY vca_claim_id")
    done = {r[0].split(":")[1] for r in ws.query("SELECT task_id FROM tasks WHERE kind='verify_set' AND status='done' "
                                                 "AND task_id NOT LIKE '%:audit:%'")}
    vc = [r for r in vc if r["vca_claim_id"] in done]
    vc = rng.sample(list(vc), min(50, len(vc)))
    write("g6_checks.csv", [{"vca_claim_id": r["vca_claim_id"], "target": r["target"], "claim": r["text"],
                             "status": "", "note": ""} for r in vc])
    q = ws.query("SELECT v.ver_id, v.doc_id, v.page, v.quote, d.title FROM verifications v JOIN documents d ON "
                 "d.doc_id=v.doc_id WHERE v.quote IS NOT NULL AND d.kind='pdf' ORDER BY v.ver_id")
    q = rng.sample(list(q), min(100, len(q)))
    write("f7_quotes.csv", [{"ver_id": r["ver_id"], "doc_id": r["doc_id"], "document": r["title"] or "",
                             "page": r["page"] or "", "quote": r["quote"], "right_with_pdfminer": "",
                             "right_without_pdfminer": ""} for r in q])
    return {"folder": str(folder), "sheets": out}


def _kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    from .analysis import _prf

    if not pairs:
        return None
    tp = sum(a and b for a, b in pairs)
    fp = sum((not a) and b for a, b in pairs)
    fn = sum(a and not b for a, b in pairs)
    return _prf(tp, fp, fn, len(pairs) - tp - fp - fn)["kappa"]


def measure(ws: Workspace, folder: str | Path, framework: str = "sdg") -> dict:
    """Score the filled sheets."""
    from . import frameworks, profile, terms

    folder = Path(folder)
    out: dict = {}
    rows = [r for r in _read(folder / "f2_labels.csv") if (r.get("codes") or "").strip()]
    if rows:
        fw = frameworks.get(framework, ws)
        gold = {r["passage_id"]: {fw.normalise(c) for c in re.split(r"[;,\s]+", r["codes"]) if fw.normalise(c)}
                for r in rows}
        gold = {k: v for k, v in gold.items() if v is not None}
        per_model: dict[str, list] = {}
        labs = profile.effective(ws, framework, passage_ids=list(gold), provisional=False)
        by_pid: dict[str, dict[str, set]] = {}
        for lb in labs:
            if lb["source"] == "model":
                by_pid.setdefault(lb["model"] or "?", {}).setdefault(lb["passage_id"], set()).add(lb["code"])
        for model, got in by_pid.items():
            pairs = []
            for pid, codes in gold.items():
                mine = got.get(pid, set())
                cands = {c["code"] for c in profile.candidates_of(ws, framework, pid)}
                for c in codes | mine | cands:
                    pairs.append((c in codes, c in mine))
            per_model[model] = {"kappa": _kappa(pairs), "passages": len(gold)}
        out["F2"] = {"passages": len(gold), "kappa_by_model": per_model,
                     "keyword_pass_recall": profile.recall_at_candidates(ws, framework, gold)}
    rows = [r for r in _read(folder / "f3_pairs.csv") if _yes(r.get("same")) is not None]
    if rows:
        eff = {(lk["a"], lk["b"]): lk for lk in terms.links(ws)}
        agree = n = 0
        for r in rows:
            lk = eff.get((r["a"], r["b"]))
            if not lk or lk["source"] not in ("model", "abbreviation"):
                continue
            n += 1
            agree += (lk["relation_effective"] == "same") == _yes(r["same"])
        out["F3"] = {"pairs_judged_by_person": len(rows), "pairs_judged_by_model_or_rule": n,
                     "agreement": round(agree / n, 3) if n else None}
    rows = [r for r in _read(folder / "f4_themes.csv") if _yes(r.get("fitting")) is not None]
    if rows:
        out["F4"] = {"themes": len(rows), "fitting": round(sum(_yes(r["fitting"]) for r in rows) / len(rows), 3)}
    rows = [r for r in _read(folder / "f5_pronouns.csv") if _yes(r.get("right")) is not None]
    if rows:
        out["F5"] = {"grades": len(rows), "refers_to_right": round(sum(_yes(r["right"]) for r in rows) / len(rows), 3)}
    rows = _read(folder / "f7_quotes.csv")
    a = [r for r in rows if _yes(r.get("right_with_pdfminer")) is not None]
    b = [r for r in rows if _yes(r.get("right_without_pdfminer")) is not None]
    if a or b:
        out["F7"] = {"with_pdfminer": round(sum(_yes(r["right_with_pdfminer"]) for r in a) / len(a), 3) if a else None,
                     "without_pdfminer": round(sum(_yes(r["right_without_pdfminer"]) for r in b) / len(b), 3) if b else None,
                     "quotes": max(len(a), len(b))}
    if not out:
        out["note"] = f"No filled sheet in {folder}. Run `acceptance samples` and fill them in first."
    return out


def search_measure(ws: Workspace, queries: list[str] | None = None) -> dict:
    """F1: for each query, the hits of an exact search equal the matches of a case-insensitive regular expression
    over the same passages; and the median response time."""
    from . import concordance, terms

    if not queries:
        terms.ensure(ws)
        queries = [r[0] for r in ws.query("SELECT label FROM terms WHERE n_words=1 AND label GLOB '[a-z]*' "
                                          "ORDER BY df DESC, tf DESC LIMIT 20")]
    texts = [r[0] for r in ws.query("SELECT text FROM passages WHERE section='body'")]
    rows, times = [], []
    for q in queries:
        t0 = time.time()
        res = concordance.search(ws, q, exact=True, limit=1)
        times.append(time.time() - t0)
        rx = re.compile(r"(?<![^\W_])" + re.escape(q) + r"(?![^\W_])", re.I)
        n = sum(len(rx.findall(t)) for t in texts)
        rows.append({"query": q, "hits": res["total"], "regex": n, "equal": res["total"] == n})
    return {"queries": len(rows), "all_equal": all(r["equal"] for r in rows),
            "median_seconds": round(statistics.median(times), 3) if times else None, "rows": rows}
