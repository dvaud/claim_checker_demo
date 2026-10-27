"""Write the evidence report (one self-contained HTML file) and CSV/JSON exports."""
from __future__ import annotations

import csv
import html
import json
from collections import Counter, defaultdict
from pathlib import Path

from . import analysis
from .store import Workspace, now
from .taxonomy import HORIZON_LABELS, SEGMENT_LABELS, SEGMENTS, goal_names, target_sort_key, targets

E = html.escape

CSS = """
:root{--bg:#F4F6F5;--surface:#FFFFFF;--ink:#17201D;--muted:#5B6A65;--line:#D5DDDA;--accent:#1F5F8B;
--pos:#1E7A46;--pos-soft:rgba(30,122,70,.13);--neg:#B23A1E;--neg-soft:rgba(178,58,30,.12);--mix:#8A6400;--mix-soft:rgba(138,100,0,.14);
--f-body:"IBM Plex Sans","Helvetica Neue",Arial,sans-serif;--f-mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;--f-serif:"Source Serif 4",Georgia,serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0F1513;--surface:#16201D;--ink:#E2EAE7;--muted:#97A8A2;--line:#2A3833;
--accent:#6FB3E0;--pos:#5BC98B;--pos-soft:rgba(91,201,139,.15);--neg:#F08D6E;--neg-soft:rgba(240,141,110,.15);--mix:#E1B850;--mix-soft:rgba(225,184,80,.15);color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0F1513;--surface:#16201D;--ink:#E2EAE7;--muted:#97A8A2;--line:#2A3833;--accent:#6FB3E0;--pos:#5BC98B;
--pos-soft:rgba(91,201,139,.15);--neg:#F08D6E;--neg-soft:rgba(240,141,110,.15);--mix:#E1B850;--mix-soft:rgba(225,184,80,.15);color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 var(--f-body);
padding:0 max(16px,env(safe-area-inset-left,0px)) 64px max(16px,env(safe-area-inset-right,0px))}
.wrap{max-width:1080px;margin:0 auto}h1,h2,h3{line-height:1.2;text-wrap:balance}h1{font-size:2rem;margin:36px 0 6px}
h2{font-size:1.35rem;margin:40px 0 6px;padding-top:12px;border-top:1px solid var(--line)}h3{font-size:1rem;margin:20px 0 6px}
p{max-width:78ch;margin:6px 0}.muted{color:var(--muted)}.small{font-size:13px}.q{font-style:italic;color:var(--muted)}
.meta{font:12px/1.5 var(--f-mono);color:var(--muted)}a{color:var(--accent)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:10px 12px}.kpi b{display:block;font-size:1.5rem;font-variant-numeric:tabular-nums}
.tbl{overflow-x:auto;background:var(--surface);border:1px solid var(--line);border-radius:8px;margin:10px 0}
table{border-collapse:collapse;width:100%;font-size:13.5px}th{font:500 11px/1.3 var(--f-mono);text-transform:uppercase;letter-spacing:.04em;
color:var(--muted);text-align:left;padding:8px;border-bottom:1px solid var(--line);vertical-align:bottom;white-space:nowrap}
td{padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}tr:last-child td{border-bottom:0}td.n{text-align:right;font-variant-numeric:tabular-nums}
.pill{display:inline-block;font:500 11.5px/1 var(--f-mono);padding:4px 6px;border-radius:4px;white-space:nowrap}
.positive{color:var(--pos);background:var(--pos-soft)}.negative{color:var(--neg);background:var(--neg-soft)}.mixed{color:var(--mix);background:var(--mix-soft)}
.none{color:var(--muted)}.neutral{color:var(--muted);background:var(--bg);border:1px solid var(--line)}.quote{font-family:var(--f-serif);font-size:14px}details{margin:4px 0}summary{cursor:pointer;color:var(--accent)}
.goal{font-weight:600;background:var(--bg)}.note{border-left:3px solid var(--line);padding-left:10px;color:var(--muted);font-size:13.5px;max-width:80ch}
"""


def _pill(sign: str, text: str | None = None) -> str:
    if not sign and not text:
        return '<span class="none">–</span>'
    cls = sign if sign in ("positive", "negative", "mixed") else "neutral"
    return f'<span class="pill {cls}">{E(text or sign)}</span>'


def _gold_pill(cell: str) -> str:
    if not cell:
        return '<span class="none">–</span>'
    out = []
    for part in cell.split("+"):
        kind, sign = part.split("_")
        out.append(_pill(sign, f"{kind} {'+' if sign == 'positive' else '−'}"))
    return " ".join(out)


def _gold_sign_cell(cell: str) -> str:
    signs = {p.split("_")[1] for p in cell.split("+") if p}
    return signs.pop() if len(signs) == 1 else "mixed"


def _table(headers: list[str], rows: list[list[str]], numeric: set[int] = frozenset()) -> str:
    th = "".join(f"<th>{E(h)}</th>" for h in headers)
    body = []
    for r in rows:
        tds = "".join(f'<td class="n">{c}</td>' if i in numeric else f"<td>{c}</td>" for i, c in enumerate(r))
        body.append(f"<tr>{tds}</tr>")
    return f'<div class="tbl"><table><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    keys = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in r.items()})


def build(ws: Workspace, out_dir: str | Path | None = None, strict: bool = False) -> Path:
    out = Path(out_dir) if out_dir else ws.root / "report"
    out.mkdir(parents=True, exist_ok=True)
    analysis.infer_interactions(ws, strict)
    counts = ws.counts()
    status = Counter(r[0] for r in ws.query("SELECT status FROM claims"))
    models = Counter(f"{r[0]} ({r[1]})" for r in ws.query("SELECT model, prompt_version FROM results WHERE valid=1"))
    eff = analysis.effects(ws, strict)
    inter = analysis.interaction_table(ws)
    sup = analysis.vca_support(ws)
    rec = analysis.label_recovery(ws, strict)
    rec_all = analysis.label_recovery(ws, strict, only_covered=False)
    gold = {r["target"]: dict(r) for r in ws.query("SELECT * FROM vca_targets")}
    from .sources import coverage
    cov = coverage(ws)
    gn = goal_names()
    tg = targets()
    claims = analysis.claim_rows(ws, strict)
    claim_by_id = {}
    for c in claims:
        claim_by_id.setdefault(c["claim_id"], c)

    # ---- exports ------------------------------------------------------------------------
    _write_csv(out / "effects.csv", [{k: v for k, v in e.items() if k != "claim_ids"} for e in eff])
    _write_csv(out / "interactions.csv", inter)
    _write_csv(out / "vca_claims.csv", sup)
    _write_csv(out / "label_recovery_targets.csv", rec["targets"])
    _write_csv(out / "label_recovery_cells.csv", rec["cells"])
    ev_rows = []
    for c in claims:
        q = ws.query("SELECT quote, page FROM evidence WHERE claim_id=? AND field='claim' LIMIT 1", (c["claim_id"],))
        ev_rows.append({"claim_id": c["claim_id"], "status": c["status"], "target": c["target"], "direction": c["direction"],
                        "influence": c["influence"], "segment": c["segment"], "horizon": c["horizon"], "side": c["side"],
                        "countries": c["countries"], "condition": c["condition"], "policy_lever": c["policy_lever"],
                        "confidence": c["confidence"], "claim": c["claim"], "quote": q[0][0] if q else "",
                        "page": q[0][1] if q else "", "source": c["title"], "doi": c["doi"], "model": c["model"]})
    _write_csv(out / "claims.csv", ev_rows)
    metrics = {k: v for k, v in rec.items() if k not in ("targets", "cells", "new_candidates", "target_presence")}
    metrics["target_presence_all_targets"] = rec_all["target_presence"]
    metrics["vca_claim_status"] = dict(Counter(s["status"] for s in sup))
    metrics["claim_status"] = dict(status)
    sens = analysis.status_sensitivity(ws)
    audit = analysis.audit_summary(ws)
    metrics["vca_status_by_threshold"] = sens
    metrics["audit"] = audit
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))

    # ---- report -------------------------------------------------------------------------
    h: list[str] = []
    a = h.append
    a(f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
      f"<title>Green Hydrogen SDG Evidence</title><style>{CSS}</style></head><body><div class='wrap'>")
    a("<h1>Green hydrogen and the SDGs: evidence report</h1>")
    a(f"<p class='meta'>Generated {E(now())} · {counts['documents']} documents · {counts['passages']} passages · "
      f"{counts['claims']} claims · analysis set: {'reviewed and auto-accepted claims only' if strict else 'all claims except rejected'}</p>")
    a(f"<p class='meta'>Models and prompts: {E(', '.join(f'{k} × {v}' for k, v in models.most_common()) or 'none yet')}</p>")

    vstat = Counter(s["status"] for s in sup)
    status_pill = {"supported": "positive", "partially_supported": "mixed", "contradicted": "negative",
                   "unsupported": "neutral"}
    covered = sum(1 for c in cov if c["available"])
    a("<div class='kpis'>")
    for label, val in [("Justified VCA targets", len(cov)), ("with a cited source available", covered),
                       ("claims in the VCA justifications", len(sup)), ("supported by a source", vstat.get("supported", 0)),
                       ("partly supported", vstat.get("partially_supported", 0)),
                       ("impact claims extracted", len({c['claim_id'] for c in claims})),
                       ("candidate interactions", len(inter))]:
        a(f"<div class='kpi'><b>{val}</b><span class='small muted'>{E(label)}</span></div>")
    a("</div>")
    a("<p class='note'>Every number below traces to quoted evidence in claims.csv. Model outputs are unreviewed unless "
      "their status says accepted or changed; confidences are model self-reports and are not calibrated yet.</p>")

    # Q1 -------------------------------------------------------------------------------------
    a("<h2>1. Does the cited literature support the VCA's judgements?</h2>")
    a("<p class='q'>Each VCA justification is split into single claims, and each claim is checked against passages from the "
      "sources the VCA cites for that target.</p>")
    rows = [[_pill(status_pill.get(k, ""), k), str(v)]
            for k, v in sorted(vstat.items(), key=lambda x: -x[1])]
    a(_table(["VCA claim status", "Claims"], rows, {1}))
    a("<p class='small muted'>supported: at least one passage states the effect · partially supported: a passage states part "
      "of it (the mechanism, the converse case, or the effect for another segment or for renewables in general), so one "
      "inference step remains · unsupported: sources available but no passage bears on it · contradicted: a passage states "
      "the opposite · source missing: none of the cited sources was available and readable · not checked: verification "
      "tasks not run yet.</p>")
    if any(sum(r[k] for k in ("supported", "partially_supported", "contradicted", "unsupported")) for r in sens):
        a("<p class='q'>The same statuses at other confidence thresholds (grades below the threshold are ignored; "
          f"the report uses {float(ws.config['thresholds']['support_confidence']):g}):</p>")
        a(_table(["Threshold", "supported", "partially supported", "contradicted", "unsupported"],
                 [[f"{r['threshold']:g}", str(r["supported"]), str(r["partially_supported"]), str(r["contradicted"]),
                   str(r["unsupported"])] for r in sens], {1, 2, 3, 4}))
    trows = []
    for t in sorted({s["target"] for s in sup}, key=target_sort_key):
        ss = [s for s in sup if s["target"] == t]
        g = gold.get(t, {})
        st = Counter(s["status"] for s in ss)
        details = "".join(
            f"<li>{_pill(status_pill.get(s['status'], ''), s['status'])} "
            f"{E(s['text'])}" + "".join(f"<div class='quote'>“{E(x['quote'] or '')}” <span class='small muted'>{E(x['title'] or '')}{', p. ' + str(x['page']) if x['page'] else ''}</span></div>"
                                        for x in (s["support"][:1] or s.get("partial", [])[:1]) + s["refute"][:1]) + "</li>" for s in ss)
        trows.append([f"<b>{t}</b><div class='small muted'>{E(tg[t].description[:110])}</div>",
                      " ".join(_gold_pill(g.get(seg, "")) for seg in SEGMENTS),
                      E(HORIZON_LABELS.get(g.get("horizon") or "not_stated", "")),
                      ", ".join(f"{k} {v}" for k, v in st.items()),
                      f"<details><summary>{len(ss)} claims</summary><ul>{details}</ul></details>"])
    a(_table(["Target", "VCA cells (production · transport · end-use)", "VCA horizon", "Claim status", "Details"], trows))

    cons = analysis.vca_consistency(ws)
    if cons["compared"]:
        cc = cons["counts"]
        a("<h3>Do the VCA's texts and colours agree?</h3>")
        a(f"<p class='q'>Each claim from a justification compared with the colour of the VCA's own cell for that segment "
          f"({cons['compared']} claims with a clear direction): {cc.get('consistent', 0)} agree, {cc.get('differs', 0)} point the "
          f"other way, {cc.get('no_cell', 0)} name a segment whose cell is empty. Differences are flags for the authors, not "
          f"errors: many are mitigations written into the justification of a negative cell.</p>")
        rows = [[f"<b>{x['target']}</b>", E(SEGMENT_LABELS.get(x["segment"], x["segment"])), _pill(x["text_direction"]),
                 " ".join(_gold_pill(c) for c in x["cells"].values()), E(x["text"])]
                for x in cons["rows"] if x["verdict"] != "consistent"]
        a(f"<details><summary>{len(rows)} claims to review</summary>"
          + _table(["Target", "Segment", "Text says", "Cell colour", "Claim"], rows) + "</details>")
        _write_csv(out / "vca_consistency.csv", [{k: v for k, v in x.items()} for x in cons["rows"]])

    # Q1b label recovery
    a("<h3>Can the method rebuild the VCA labels from the sources?</h3>")
    a(f"<p class='q'>Claims extracted independently from the sources, aggregated per target, compared with the VCA. Whether a "
      f"target is affected is scored over all {rec_all['targets_scored']} targets (the VCA's empty targets are the negatives); "
      f"cells, signs and horizons over the {rec['targets_scored']} justified targets with a cited source available.</p>")
    tp, cp = rec_all["target_presence"], rec["cell_presence"]

    def accs(x):
        return f"{x['agree']}/{x['n']} ({x['accuracy']:.0%})" if x["n"] else "–"
    a(_table(["Measure", "Precision", "Recall", "F1", "Cohen's κ", "Agreement"], [
        ["Target has an effect (all targets)", f"{tp['precision']:.2f}", f"{tp['recall']:.2f}", f"{tp['f1']:.2f}", f"{tp['kappa']:.2f}", ""],
        ["Target × segment cell has an effect", f"{cp['precision']:.2f}", f"{cp['recall']:.2f}", f"{cp['f1']:.2f}", f"{cp['kappa']:.2f}", ""],
        ["Sign of the effect (targets both mark)", "", "", "", "", accs(rec["target_sign"])],
        ["Sign per cell (cells both mark)", "", "", "", "", accs(rec["cell_sign"])],
        ["Direct or indirect (cells both mark)", "", "", "", "", accs(rec["cell_influence"])],
        ["Time horizon (targets both date)", "", "", "", "", accs(rec["horizon"])],
    ]))

    # Q2 effects -----------------------------------------------------------------------------
    a("<h2>2. Which SDG targets does green hydrogen affect, in which direction and in which segment?</h2>")
    a("<p class='q'>Sign by number of documents: positive or negative when one side has at least twice the documents of the other, "
      "otherwise mixed. Segment columns follow the VCA; whole chain and unclear are claims not tied to one segment.</p>")
    by_t: dict[str, dict[str, dict]] = defaultdict(dict)
    for e in eff:
        by_t[e["target"]][e["segment"]] = e
    rows = []
    last_goal = None
    for t in sorted(by_t, key=target_sort_key):
        gnum = tg[t].goal
        if gnum != last_goal:
            rows.append([f"<span class='goal'>SDG {gnum} · {E(gn[gnum])}</span>", "", "", "", "", "", ""])
            last_goal = gnum
        cells = []
        for seg in list(SEGMENTS) + ["whole_chain", "unclear"]:
            e = by_t[t].get(seg)
            cells.append(_pill(e["sign"], f"{e['sign'] or 'other'} · {e['n_docs']}") if e else "<span class='none'>–</span>")
        vca = " ".join(_gold_pill(gold.get(t, {}).get(s, "")) for s in SEGMENTS) if t in gold else ""
        rows.append([f"<b>{t}</b> <span class='small muted'>{E(tg[t].description[:80])}</span>", *cells, vca])
    a(_table(["Target", SEGMENT_LABELS["production"], SEGMENT_LABELS["transportation"], SEGMENT_LABELS["end_use"],
              "Whole chain", "Unclear", "VCA cells"], rows))
    a("<p class='small muted'>Cell text: sign · number of documents. Full rows with horizons, countries and conditions are in effects.csv.</p>")
    dirs = Counter(c["direction"] for c in {c["claim_id"]: c for c in claims}.values())
    gsig = Counter(_gold_sign_cell(g[s_]) for g in gold.values() for s_ in SEGMENTS if g[s_])
    a(f"<p class='small'>Direction of the extracted claims: {dirs.get('positive', 0)} positive, {dirs.get('negative', 0)} negative, "
      f"{dirs.get('mixed', 0) + dirs.get('no_effect', 0)} mixed or no effect. The VCA's coloured cells: {gsig.get('positive', 0)} positive, "
      f"{gsig.get('negative', 0)} negative.</p>")

    # Q3 interactions --------------------------------------------------------------------------
    a("<h2>3. Where do synergies and trade-offs between SDG targets appear?</h2>")
    a("<p class='q'>Stated: a passage says progress on one target affects another (scored on the Nilsson scale). Inferred: one document "
      "links the same activity, segment and place to both targets; synergy = both helped, trade-off = one helped and one hindered, "
      "shared pressure = both hindered. Inferred pairs are candidates for expert scoring, not findings.</p>")
    rel_counts = Counter(i["relation"] for i in inter)
    a(_table(["Relation", "Target pairs"], [[E(k), str(v)] for k, v in rel_counts.most_common()], {1}))
    def _pair_rows(items):
        out_rows = []
        for i in items:
            rel = {"synergy": "positive", "trade_off": "negative", "shared_pressure": "mixed", "stated": ""}.get(i["relation"], "")
            q = "".join(f"<div class='quote'>“{E(x['quote'])}”</div>" for x in i["quotes"][:1])
            out_rows.append([f"{i['from']} <span class='small muted'>{E(tg[i['from']].description[:50])}</span>",
                             f"{i['to']} <span class='small muted'>{E(tg[i['to']].description[:50])}</span>",
                             _pill(rel, i["relation"]) if rel else E(i["relation"]), str(i["n_docs"]),
                             "" if i["score"] is None else f"{i['score']:+g}", q])
        return out_rows
    heads = ["Target", "Target", "Relation", "Documents", "Score", "Evidence"]
    stated = [x for x in inter if x["relation"] == "stated"]
    if stated:
        a("<h3>Stated in the text</h3>")
        a(_table(heads, _pair_rows(stated), {3}))
    for rel_name, title in (("trade_off", "Candidate trade-offs"), ("shared_pressure", "Candidate shared pressures"),
                            ("synergy", "Candidate synergies")):
        items = [x for x in inter if x["relation"] == rel_name and x["cross_goal"] and x["n_docs"] >= 2]
        if items:
            a(f"<h3>{title} (two or more documents, across goals)</h3>")
            a(_table(heads, _pair_rows(items[:25]), {3}))
    a("<p class='small muted'>Pairs resting on one document are left out here; one long document can link dozens of targets. "
      "All pairs: interactions.csv.</p>")

    # Q4 timing ---------------------------------------------------------------------------------
    a("<h2>4. When do the effects occur?</h2>")
    a("<p class='q'>Claims by stated time horizon and direction. The VCA reports that synergies dominate up to 2030 and trade-offs after.</p>")
    hz = Counter((c["horizon"], c["direction"]) for c in claims)
    rows = []
    for h_ in ("short_term", "medium_long_term", "not_stated"):
        rows.append([E(HORIZON_LABELS[h_]), str(hz[(h_, "positive")]), str(hz[(h_, "negative")]),
                     str(hz[(h_, "mixed")] + hz[(h_, "no_effect")])])
    a(_table(["Horizon", "Positive", "Negative", "Mixed or none"], rows, {1, 2, 3}))
    vh = Counter(g["horizon"] for g in gold.values() if g["horizon"])
    a(f"<p class='small muted'>VCA horizons: {vh.get('short_term', 0)} targets short term, {vh.get('medium_long_term', 0)} medium to long term.</p>")

    # Q5 geography -----------------------------------------------------------------------------
    a("<h2>5. Where do the effects land?</h2>")
    a("<p class='q'>Countries named in claims, and whether the effect lands with the producing or the importing side.</p>")
    geo = defaultdict(Counter)
    for c in {c["claim_id"]: c for c in claims}.values():
        for k in c["countries"] or ["(none named)"]:
            geo[k][c["direction"]] += 1
    rows = [[E(k), str(v["positive"]), str(v["negative"]), str(v["mixed"] + v["no_effect"])]
            for k, v in sorted(geo.items(), key=lambda kv: -sum(kv[1].values()))[:30]]
    a(_table(["Country or region", "Positive", "Negative", "Mixed or none"], rows, {1, 2, 3}))
    side = Counter(c["side"] for c in {c["claim_id"]: c for c in claims}.values())
    a(f"<p class='small muted'>Side where the effect lands: {E(', '.join(f'{k} {v}' for k, v in side.most_common()))}. "
      f"Claims naming the Netherlands: {sum(v.total() for k, v in geo.items() if 'netherlands' in k.lower() or 'dutch' in k.lower())}.</p>")

    # Q6 conditions -------------------------------------------------------------------------------
    a("<h2>6. Under which conditions do effects change, and which policy levers are named?</h2>")
    rows = []
    seen = set()
    for c in claims:
        if not (c["condition"] or c["policy_lever"]) or (c["claim_id"], c["target"]) in seen:
            continue
        seen.add((c["claim_id"], c["target"]))
        rows.append([c["target"], _pill(c["direction"]), E(c["condition"] or ""), E(c["policy_lever"] or ""),
                     f"<span class='small'>{E(c['title'] or '')}</span>"])
    rows.sort(key=lambda r: target_sort_key(r[0]))
    a(_table(["Target", "Effect", "Condition", "Policy lever", "Source"], rows[:80]))

    # Q7 gaps -------------------------------------------------------------------------------------
    a("<h2>7. Gaps and new candidates</h2>")
    a("<p class='q'>Target and segment cells the VCA leaves empty but at least two documents mark, and VCA targets whose sources were not provided.</p>")
    rows = [[n["target"], E(SEGMENT_LABELS.get(n["segment"], n["segment"])), _pill(n["sign"]), str(n["n_docs"]),
             E(tg[n["target"]].description[:100])] for n in rec["new_candidates"][:40]]
    a(_table(["Target", "Segment", "Sign", "Documents", "Description"], rows, {3}))
    missing = [c["target"] for c in cov if not c["available"]]
    a(f"<p class='small'>Justified targets with none of their cited sources provided ({len(missing)}): {E(', '.join(missing) or 'none')}.</p>")

    a("<h2>Sources</h2>")
    from .sources import unreadable_docs
    bad = unreadable_docs(ws)
    n_claims = Counter(c["doc_id"] for c in {c["claim_id"]: c for c in claims}.values())
    linked = defaultdict(set)
    for r in ws.query("SELECT dr.doc_id, r.targets_json FROM doc_refs dr JOIN vca_refs r ON r.ref_key=dr.ref_key"):
        linked[r["doc_id"]] |= set(json.loads(r["targets_json"] or "[]"))
    rows = []
    for d in ws.query("SELECT d.doc_id, d.title, d.kind, d.n_pages, d.n_chars, (SELECT COUNT(*) FROM passages p WHERE "
                      "p.doc_id=d.doc_id AND p.section='body') AS body FROM documents d ORDER BY d.title"):
        flags = []
        if d["doc_id"] in bad:
            flags.append("unreadable text layer")
        if d["body"] < 8 or d["n_chars"] < 5000:
            flags.append("very short: check it is the cited work")
        rows.append([E((d["title"] or "")[:110]), E(d["kind"]), str(d["n_pages"] or "–"), str(d["body"]), str(n_claims.get(d["doc_id"], 0)),
                     E(", ".join(sorted(linked.get(d["doc_id"], ()), key=target_sort_key))), E("; ".join(flags))])
    a(_table(["Document", "Kind", "Pages", "Passages", "Claims", "VCA targets citing it", "Check"], rows, {2, 3, 4}))

    a("<h2>Method notes</h2>")
    a("<p class='small'>Sources were split into passages with page and character positions. Passages were screened for hydrogen "
      "and impact terms; claims were extracted with quoted evidence, and every quote was checked against the source text. VCA labels "
      "come from the cell colours of the supplementary table (T3) of Peyerl &amp; van der Zwaan (2024). See the usage manual for limits: "
      "unreviewed model output, uncalibrated confidences, and a corpus limited to the sources provided.</p>")
    if audit.get("vca_checks"):
        v = audit["vca_checks"]
        a(f"<p class='small'><b>Second-model audit of VCA checks.</b> {v['claims']} claims were checked again by "
          f"{E(', '.join(v['models']))} on the same passages. Same status: {v['status_agreement']:.0%}. Grounded "
          f"(supported or partially supported) or not: agreement {v['grounded_agreement']['tp'] + v['grounded_agreement']['tn']}"
          f"/{v['claims']}, Cohen's κ {v['grounded_agreement']['kappa']:.2f}. Same grade per passage: "
          f"{(v['passage_grade_agreement'] or 0):.0%}.</p>")
    if audit.get("claim_checks"):
        v = audit["claim_checks"]
        a(f"<p class='small'><b>Second-model audit of extracted claims.</b> {v['claims']} claims were checked against their own "
          f"passage by {E(', '.join(v['models']))}: {E(', '.join(f'{k} {n}' for k, n in v['verdicts'].items()))}. "
          f"Share confirmed at the support threshold: {v['supported_share']:.0%}.</p>")
    a("</div></body></html>")
    path = out / "report.html"
    path.write_text("".join(h), encoding="utf-8")
    return path
