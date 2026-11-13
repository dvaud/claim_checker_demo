"""The validation report's AI half (roadmap J4.3, 0.18.4): ENLENS's AI answers scored against known right answers.

`enlens measure` (measure.py) is the half that needs no AI. This half needs a set of right answers (the gold set) and
a recorded, dated run of the AI on it. The gold set is invented on purpose (`tools/validation/`, read its README):
documents on remote work in which every name and figure is fictional, so the right answer to each question is known
by construction. It holds hypotheses with their verdicts (the kind `check`) and passages with the codes of a small
codebook made for it (the kind `label`).

    enlens validate prepare --project "Validation 2026-11-13"     # a new project from the gold documents, tasks queued
    /enlens-run "Validation 2026-11-13"                           # in Claude Code: the queue answers them
    enlens validate prepare --project "Validation 2026-11-13 again"   # the same again, for repeatability
    /enlens-run "Validation 2026-11-13 again"
    enlens validate score --project "Validation 2026-11-13" --again "Validation 2026-11-13 again"
                                                                  # tools/validation/runs/<date>-<route>.json
    enlens validate report --latest tools/validation/runs --out validation-report-ai.md   # no AI

A local model answers the same queue with `enlens --ws <project folder> queue run --backend ollama` instead of
/enlens-run. The run file keeps every answer with its model, prompt version, ENLENS version and date, and the gold
answer beside it, so the report is made from the run file alone, with no AI (the release workflow does that).
"""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from .store import Workspace

FORMAT = 1
FRAMEWORK = "validation"
META = "validation"
STATUSES = ("supported", "partially_supported", "contested", "contradicted", "unsupported")
GROUNDED = {"supported", "partially_supported"}
STATUS_WORDS = {"supported": "Supported", "partially_supported": "Partly supported", "contested": "Mixed evidence",
                "contradicted": "Contradicted", "unsupported": "No evidence found"}
DECOMPOSE = ("compound", "all", "none")


def default_folder() -> Path:
    """`tools/validation/` of a git copy of ENLENS (the gold set is not part of the installed package)."""
    return Path(__file__).resolve().parents[2] / "tools" / "validation"


# ---------------------------------------------------------------------------------------------------------------
# The gold set
# ---------------------------------------------------------------------------------------------------------------
def _norm(s: str) -> str:
    s = (s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return " ".join(s.split()).lower()


def _codes(v: str | None) -> list[str]:
    return sorted({c.strip() for c in re.split(r"[;,]", v or "") if c.strip()})


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def load_gold(folder: str | Path | None = None) -> dict:
    """The gold set: its documents (its own and the demo corpus beside it), codebook, hypotheses and labelled
    passages, and a fingerprint of all of them (so a run says which version of the gold set it was scored on)."""
    folder = Path(folder) if folder else default_folder()
    if not (folder / "hypotheses.csv").exists():
        raise FileNotFoundError(f"No gold set in {folder} (hypotheses.csv is missing). The gold set is in a git copy of "
                                "ENLENS, in tools/validation/.")
    demo = folder.parent / "demo_corpus"
    docs = sorted((folder / "documents").glob("*.*"))
    if demo.is_dir():
        docs += sorted(p for p in demo.iterdir() if p.suffix.lower() in (".txt", ".html", ".htm", ".md")
                       and p.name.lower() != "readme.md")
    codebook = (folder / "codebook.csv").read_text(encoding="utf-8-sig")
    hyps = []
    for r in _rows(folder / "hypotheses.csv"):
        v = r.get("verdict", "").lower()
        if v not in STATUSES:
            raise ValueError(f"hypotheses.csv, {r.get('id')}: the verdict {v!r} is not one of {', '.join(STATUSES)}.")
        hyps.append({"id": r["id"], "hypothesis": r["hypothesis"], "gold": v,
                     "compound": r.get("compound", "").lower() in ("yes", "y", "1", "true")})
    labels = [{"file": r["file"], "anchor": r["anchor"], "gold": _codes(r.get("codes")),
               "mentioned": _codes(r.get("mentioned"))} for r in _rows(folder / "labels.csv")]
    from .frameworks import parse_csv

    known = set(parse_csv(codebook))
    for lb in labels:
        bad = [c for c in lb["gold"] + lb["mentioned"] if c not in known]
        if bad:
            raise ValueError(f"labels.csv, {lb['file']} {lb['anchor'][:30]!r}: codes not in the codebook: {bad}")
    h = hashlib.sha256()
    for p in [folder / "codebook.csv", folder / "hypotheses.csv", folder / "labels.csv", *docs]:
        h.update(p.name.encode() + b"\0" + p.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return {"folder": str(folder), "documents": docs, "codebook": codebook, "codes": sorted(known),
            "hypotheses": hyps, "labels": labels, "fingerprint": h.hexdigest()[:16]}


def match_passages(ws: Workspace, labels: list[dict]) -> dict[str, str]:
    """{gold key ("file#anchor"): passage_id}: the passage of that file whose text holds the anchor. Raises ValueError
    listing every anchor found in no passage, or in more than one (the gold set and the reader disagree)."""
    by_file: dict[str, list] = {}
    for r in ws.query("SELECT p.passage_id, p.text, d.path FROM passages p JOIN documents d ON d.doc_id=p.doc_id "
                      "ORDER BY p.passage_id"):
        by_file.setdefault(Path(r["path"] or "").name, []).append((r["passage_id"], _norm(r["text"])))
    out, problems = {}, []
    for lb in labels:
        a = _norm(lb["anchor"])
        hits = [pid for pid, t in by_file.get(lb["file"], []) if a in t]
        if len(hits) != 1:
            problems.append(f"{lb['file']}: {lb['anchor'][:50]!r} is in {len(hits)} passages")
        else:
            out[key(lb)] = hits[0]
    if problems:
        raise ValueError("The gold set's passages do not match how ENLENS reads the documents: " + "; ".join(problems))
    return out


def key(lb: dict) -> str:
    return f"{lb['file']}#{lb['anchor']}"


# ---------------------------------------------------------------------------------------------------------------
# Prepare: a new project from the gold documents, its tasks waiting in the queue
# ---------------------------------------------------------------------------------------------------------------
def prepare(ws: Workspace, folder: str | Path | None = None, decompose: str = "compound", k: int = 8,
            per_doc: int = 2) -> dict:
    """Read the gold documents into an empty project, add the gold codebook, and queue a check for every hypothesis
    and a label task for every gold passage, as the app would (`decompose`: split into parts the compound
    hypotheses, all of them, or none, as a researcher ticks *Split into parts*). Nothing is answered here."""
    from . import access, claimcheck, frameworks, home, ingest, profile, routing
    from . import tasks as tk
    from . import __version__

    if decompose not in DECOMPOSE:
        raise ValueError(f"decompose: one of {', '.join(DECOMPOSE)}")
    g = load_gold(folder)
    if ws.scalar("SELECT COUNT(*) FROM documents"):
        raise ValueError("Prepare a validation run in a new, empty project: this one already has documents.")
    access.set_default(ws, "cloud")
    read = ingest.ingest(ws, [str(p) for p in g["documents"]], ai_access="cloud")
    frameworks.save(ws, FRAMEWORK, g["codebook"], title="Validation codebook (invented, remote work)", label="code")
    pids = match_passages(ws, g["labels"])
    r = routing.from_settings(home.load_settings(), route="claude_code")
    hyps: dict[str, str] = {}
    with tk.queueing():
        batch = claimcheck._new_id("b")
        for h in g["hypotheses"]:
            split = decompose == "all" or (decompose == "compound" and h["compound"])
            hyps[h["id"]] = claimcheck.queue_check(ws, h["hypothesis"], r, k=k, per_doc=per_doc, expand=True,
                                                   decompose=split, batch_id=batch, origin="validation",
                                                   origin_id=h["id"])
        profile.ensure_pass1(ws, FRAMEWORK)
        made = profile.make_label_tasks(ws, FRAMEWORK, list(pids.values()), r.model("label"), all_passages=True)
        with ws.connect() as cx:
            tk.mark_queued(cx, [f"label:{FRAMEWORK}:{p}" for p in pids.values()])
    ws.set_meta(META, {"fingerprint": g["fingerprint"], "hypotheses": hyps, "passages": pids,
                       "prepared_at": _now(), "prepared_by": __version__,
                       "settings": {"k": k, "per_doc": per_doc, "decompose": decompose, "expand": True}})
    return {"documents": ws.scalar("SELECT COUNT(*) FROM documents"), "failed": read.get("failed") or [],
            "hypotheses": len(hyps), "label_tasks": made,
            "gold_fingerprint": g["fingerprint"]}


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------------------------------------------
# Score: one answered project (two with --again) into a run file
# ---------------------------------------------------------------------------------------------------------------
def _quote_problem(errors: list) -> bool:
    return any("quote" in str(e) and ("not found" in str(e) or "too long" in str(e)) for e in errors or [])


def _answers(ws: Workspace, task_ids: list[str]) -> list[dict]:
    """Each task with the answer that counts (its last accepted one), how it was made, and whether its first answer
    was rejected for a quote not found in the text."""
    from .tasks import parse_json

    out = []
    for tid in task_ids:
        t = ws.query("SELECT task_id, kind, status FROM tasks WHERE task_id=?", (tid,))
        if not t:
            continue
        rs = ws.query("SELECT attempt, model, prompt_version, app_version, received_at, route, helper, valid, "
                      "errors_json, raw_json FROM results WHERE task_id=? ORDER BY attempt", (tid,))
        valid = [r for r in rs if r["valid"]]
        last = valid[-1] if valid else None
        first_errors = json.loads(rs[0]["errors_json"] or "[]") if rs else []
        try:
            answer = parse_json(last["raw_json"]) if last else None
        except ValueError:
            answer = None
        out.append({"task_id": tid, "kind": t[0]["kind"], "status": t[0]["status"], "attempts": len(rs),
                    "accepted_first": bool(rs and rs[0]["valid"]), "quote_problem_first": bool(rs) and
                    not rs[0]["valid"] and _quote_problem(first_errors),
                    "first_errors": [str(e)[:200] for e in first_errors[:3]] if rs and not rs[0]["valid"] else [],
                    "models": [r["model"] for r in valid],
                    **({"model": last["model"], "prompt_version": last["prompt_version"],
                        "app_version": last["app_version"], "answered_at": last["received_at"],
                        "route": last["route"], "helper": last["helper"]} if last else {}),
                    "answer": answer})
    return out


def _hyp_tasks(ws: Workspace, hyp_id: str) -> list[str]:
    cids = [r[0] for r in ws.query("SELECT claim_id FROM user_claims WHERE hyp_id=? ORDER BY part", (hyp_id,))]
    ids = [r[0] for r in ws.query("SELECT task_id FROM tasks WHERE task_id=?", (f"decompose:{hyp_id}",))]
    for c in cids:
        ids += [r[0] for r in ws.query(
            "SELECT task_id FROM tasks WHERE task_id=? OR task_id=? OR substr(task_id, 1, ?)=? OR substr(task_id, 1, ?)=? "
            "ORDER BY task_id", (f"expand:{c}", f"check:{c}", len(f"check:{c}:"), f"check:{c}:",
                                 len(f"second:check:{c}"), f"second:check:{c}"))]
    return list(dict.fromkeys(ids))


def collect(ws: Workspace, folder: str | Path | None = None) -> dict:
    """One answered pass of a prepared project: per gold item, ENLENS's result and every answer it rests on."""
    from . import claimcheck, frameworks

    meta = ws.meta(META)
    if not meta:
        raise ValueError(f"{ws.root.name} is not a validation project (made with `enlens validate prepare`).")
    g = load_gold(folder)
    hist = {h["hyp_id"]: h for h in claimcheck.history(ws)}
    checks = []
    for h in g["hypotheses"]:
        hid = meta["hypotheses"].get(h["id"])
        row = hist.get(hid) if hid else None
        checks.append({"id": h["id"], "hypothesis": h["hypothesis"], "compound": h["compound"], "gold": h["gold"],
                       "got": row["status"] if row else None, "parts": row["parts"] if row else None,
                       "answers": _answers(ws, _hyp_tasks(ws, hid)) if hid else []})
    fw = frameworks.get(FRAMEWORK, ws)
    labels = []
    for lb in g["labels"]:
        pid = meta["passages"].get(key(lb))
        ans = _answers(ws, [f"label:{FRAMEWORK}:{pid}"]) if pid else []
        got = None
        if ans and ans[0]["answer"] is not None:
            got = sorted({fw.normalise(x["code"]) or str(x["code"]) for x in ans[0]["answer"].get("labels") or []
                          if isinstance(x, dict) and x.get("code")})
        labels.append({"key": key(lb), "passage_id": pid, "gold": lb["gold"], "mentioned": lb["mentioned"],
                       "got": got, "answers": ans})
    return {"project": ws.root.name, "prepared_at": meta.get("prepared_at"), "prepared_by": meta.get("prepared_by"),
            "settings": meta.get("settings"), "gold_fingerprint_prepared": meta.get("fingerprint"),
            "checks": checks, "labels": labels}


def _route_of(passes: list[dict]) -> str:
    routes = Counter(a.get("route") or "" for p in passes for it in p["checks"] + p["labels"] for a in it["answers"]
                     if a.get("route"))
    r = routes.most_common(1)[0][0] if routes else "unanswered"
    return re.sub(r"[^a-z0-9]+", "-", r.lower()).strip("-") or "unknown"


def make_run(passes: list[dict], gold: dict, route: str | None = None, date: str | None = None) -> dict:
    from . import __version__

    route = route or _route_of(passes)
    models: dict[str, Counter] = {}
    prompts: dict[str, Counter] = {}
    versions: Counter = Counter()
    for p in passes:
        for it in p["checks"] + p["labels"]:
            for a in it["answers"]:
                if a.get("model"):
                    models.setdefault(a["kind"], Counter())[a["model"]] += 1
                    prompts.setdefault(a["kind"], Counter())[a.get("prompt_version") or "?"] += 1
                    versions[a.get("app_version") or "?"] += 1
    return {"format": FORMAT, "date": date or _dt.date.today().isoformat(), "route": route,
            "scored_by": __version__, "gold": {"fingerprint": gold["fingerprint"], "hypotheses": len(gold["hypotheses"]),
                                               "passages": len(gold["labels"]), "codes": gold["codes"]},
            "models": {k: dict(v) for k, v in sorted(models.items())},
            "prompt_versions": {k: dict(v) for k, v in sorted(prompts.items())},
            "enlens_versions": dict(versions), "passes": passes}


def write_run(run: dict, out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"{run['date']}-{run['route']}"
    path, n = out_dir / f"{base}.json", 2
    while path.exists():
        path, n = out_dir / f"{base}-{n}.json", n + 1
    path.write_text(json.dumps(run, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def read_run(path: str | Path) -> dict:
    run = json.loads(Path(path).read_text(encoding="utf-8"))
    if run.get("format") != FORMAT:
        raise ValueError(f"{path}: not a validation run file of format {FORMAT}.")
    return run


def latest_run(folder: str | Path) -> Path | None:
    """The newest run file in `folder` (by the date its name starts with, then its name), or None."""
    folder = Path(folder)

    def order(p: Path) -> tuple:
        m = re.search(r"-(\d{1,3})$", p.stem)  # write_run's -2, -3 for a second run of the same day and route
        return p.name[:10], p.stem[: m.start()] if m else p.stem, int(m.group(1)) if m else 1

    files = sorted(folder.glob("*.json"), key=order) if folder.is_dir() else []
    return files[-1] if files else None


# ---------------------------------------------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------------------------------------------
def kappa(pairs: list[tuple]) -> float | None:
    """Cohen's kappa of two raters over any number of categories; None with nothing to compare or when chance
    agreement is already complete (both raters always give the same one category)."""
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[c] * cb[c] for c in ca) / (n * n)
    if pe >= 1:
        return None
    return round((po - pe) / (1 - pe), 3)


def _share(xs: list[bool]) -> float | None:
    return round(sum(xs) / len(xs), 3) if xs else None


def _code_pairs(a: list[str] | None, b: list[str] | None, codes: list[str], skip: list[str]) -> list[tuple]:
    a, b = set(a or []), set(b or [])
    return [(c in a, c in b) for c in codes if c not in skip]


def score_checks(items: list[dict]) -> dict:
    pairs = [(it["gold"], it["got"] or "no answer") for it in items]
    conf: dict[str, Counter] = {}
    for g, x in pairs:
        conf.setdefault(g, Counter())[x] += 1
    out = {"n": len(items), "answered": sum(1 for it in items if it["got"] in STATUSES),
           "accuracy": _share([g == x for g, x in pairs]), "kappa": kappa(pairs),
           "grounded_accuracy": _share([(g in GROUNDED) == (x in GROUNDED) for g, x in pairs]),
           "grounded_kappa": kappa([(g in GROUNDED, x in GROUNDED) for g, x in pairs]),
           "confusion": {g: dict(c) for g, c in conf.items()},
           "per_verdict": {s: _share([x == s for g, x in pairs if g == s]) for s in STATUSES
                           if any(g == s for g, _ in pairs)}}
    for name, sel in (("simple", False), ("compound", True)):
        sub = [(g, x) for (g, x), it in zip(pairs, items) if it.get("compound") == sel]
        if sub:
            out[f"{name}_accuracy"], out[f"{name}_n"] = _share([g == x for g, x in sub]), len(sub)
    return out


def score_labels(items: list[dict], codes: list[str]) -> dict:
    pairs = [p for it in items for p in _code_pairs(it["gold"], it["got"], codes, it.get("mentioned") or [])]
    per_code = {}
    for c in codes:
        tp = sum(1 for it in items if c in it["gold"] and c in (it["got"] or []))
        fp = sum(1 for it in items if c not in it["gold"] and c not in it.get("mentioned", []) and c in (it["got"] or []))
        fn = sum(1 for it in items if c in it["gold"] and c not in (it["got"] or []))
        per_code[c] = {"gold": tp + fn, "precision": round(tp / (tp + fp), 3) if tp + fp else None,
                       "recall": round(tp / (tp + fn), 3) if tp + fn else None}
    same = [set(it["gold"]) == set(it["got"] or []) - set(it.get("mentioned") or []) for it in items]
    return {"n": len(items), "answered": sum(1 for it in items if it["got"] is not None),
            "code_decisions": len(pairs), "code_accuracy": _share([a == b for a, b in pairs]),
            "kappa": kappa(pairs), "same_codes": _share(same), "per_code": per_code}


def quote_failures(items: list[dict], kinds: tuple[str, ...]) -> dict:
    ans = [a for it in items for a in it["answers"] if a["kind"] in kinds and a["attempts"]]
    return {"answers": len(ans), "first_rejected_for_quotes": _share([a["quote_problem_first"] for a in ans]),
            "never_accepted": _share([not a["models"] for a in ans])}


def repeatability(p1: dict, p2: dict, codes: list[str]) -> dict:
    a = {it["id"]: it["got"] or "no answer" for it in p1["checks"]}
    b = {it["id"]: it["got"] or "no answer" for it in p2["checks"]}
    cp = [(a[i], b[i]) for i in a if i in b]
    la = {it["key"]: it for it in p1["labels"]}
    lp = [(la[it["key"]], it) for it in p2["labels"] if it["key"] in la]
    pairs = [p for x, y in lp for p in _code_pairs(x["got"], y["got"], codes, [])]
    return {"checks": {"n": len(cp), "same_status": _share([x == y for x, y in cp]), "kappa": kappa(cp)},
            "labels": {"n": len(lp), "same_codes": _share([set(x["got"] or []) == set(y["got"] or []) for x, y in lp]),
                       "code_agreement": _share([x == y for x, y in pairs]), "kappa": kappa(pairs)}}


def score(run: dict) -> dict:
    codes = run["gold"]["codes"]
    passes = run["passes"]
    out = {"passes": []}
    for p in passes:
        out["passes"].append({"checks": score_checks(p["checks"]), "labels": score_labels(p["labels"], codes),
                              "quotes": {"check": quote_failures(p["checks"], ("check",)),
                                         "label": quote_failures(p["labels"], ("label",))}})
    if len(passes) > 1:
        out["repeatability"] = repeatability(passes[0], passes[1], codes)
    return out


# ---------------------------------------------------------------------------------------------------------------
# The report (no AI: from the run file alone)
# ---------------------------------------------------------------------------------------------------------------
def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{round(x * 100)}%"


def _k(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def _listing(d: dict) -> str:
    return ", ".join(f"{k} ({n})" for k, n in sorted(d.items(), key=lambda kv: -kv[1])) or "none"


def to_markdown(run: dict, gold_fingerprint: str | None = None) -> str:
    s = score(run)
    first = s["passes"][0]
    c, lb = first["checks"], first["labels"]
    L = ["# Validation report: the AI's answers against known right answers", "",
         f"Recorded on {run['date']} through the route **{run['route']}**, scored by ENLENS {run['scored_by']}. This "
         "report was made from the recorded run file with no AI; the figures change only when a new run is recorded. "
         "It is the half of the validation report that needs AI; `validation-report.md` is the half that does not.", "",
         "## What was asked", "",
         f"The gold set (fingerprint `{run['gold']['fingerprint']}`) holds {run['gold']['hypotheses']} hypotheses with "
         f"a known verdict and {run['gold']['passages']} passages with the codes of a small codebook of "
         f"{len(run['gold']['codes'])} codes. ENLENS checked each hypothesis and labelled each passage as it does in "
         "the app, through its task queue, and its results were compared with the gold answers.", ""]
    if gold_fingerprint and gold_fingerprint != run["gold"]["fingerprint"]:
        L += [f"**Note:** the gold set has changed since this run (now `{gold_fingerprint}`). The figures below are "
              "scored against the gold answers as they were when the run was recorded.", ""]
    L += ["| Kind | Models (answers) | Prompt version |", "|---|---|---|"]
    for kind in sorted(run["models"]):
        L.append(f"| {kind} | {_listing(run['models'][kind])} | {_listing(run['prompt_versions'].get(kind, {}))} |")
    L += ["", f"ENLENS versions that answered: {_listing(run['enlens_versions'])}.", "",
          "## Checks (hypotheses against the documents)", "",
          f"- **Right verdict:** {_pct(c['accuracy'])} of {c['n']} hypotheses (Cohen's kappa {_k(c['kappa'])} over "
          f"the five verdicts); {c['answered']} of {c['n']} were finished.",
          f"- **Found evidence or not** (supported or partly, against the rest): right for {_pct(c['grounded_accuracy'])} "
          f"(kappa {_k(c['grounded_kappa'])}).",
          *([f"- Single hypotheses: {_pct(c['simple_accuracy'])} of {c['simple_n']}; compound ones (two claims that "
             f"must both hold): {_pct(c['compound_accuracy'])} of {c['compound_n']}."]
            if "simple_n" in c and "compound_n" in c else []),
          "", "Which verdict ENLENS gave (columns) for each right verdict (rows):", "",
          "| Right verdict | " + " | ".join(STATUS_WORDS[x] for x in STATUSES) + " | Other | Share right |",
          "|---|" + "---|" * (len(STATUSES) + 2)]
    for g in STATUSES:
        row = c["confusion"].get(g)
        if not row:
            continue
        other = sum(n for x, n in row.items() if x not in STATUSES)
        L.append(f"| {STATUS_WORDS[g]} | " + " | ".join(str(row.get(x, 0)) for x in STATUSES) +
                 f" | {other} | {_pct(c['per_verdict'].get(g))} |")
    L += ["", "## Labels (passages against the codebook)", "",
          f"- **Each code, present or not:** {_pct(lb['code_accuracy'])} of {lb['code_decisions']} decisions right "
          f"(Cohen's kappa {_k(lb['kappa'])}). Codes the gold set marks as only mentioned in passing are not scored.",
          f"- **Exactly the right codes:** {_pct(lb['same_codes'])} of {lb['n']} passages ({lb['answered']} answered).",
          "", "| Code | Passages with it | Precision | Recall |", "|---|---|---|---|"]
    for code, v in lb["per_code"].items():
        L.append(f"| {code} | {v['gold']} | {_pct(v['precision'])} | {_pct(v['recall'])} |")
    q = first["quotes"]
    L += ["", "## Quotes", "",
          "Every answer must quote the text it rests on, word for word; ENLENS rejects an answer whose quote is not in "
          "the passage and asks again.", "",
          f"- Checks: {_pct(q['check']['first_rejected_for_quotes'])} of {q['check']['answers']} answers were first "
          f"rejected for a quote; {_pct(q['check']['never_accepted'])} were never accepted.",
          f"- Labels: {_pct(q['label']['first_rejected_for_quotes'])} of {q['label']['answers']} answers were first "
          f"rejected for a quote; {_pct(q['label']['never_accepted'])} were never accepted.", "",
          "## Repeatability", ""]
    rp = s.get("repeatability")
    if rp:
        L += ["The whole run was made a second time, in a new project, and the two passes compared with each other "
              "(not with the gold set).", "",
              f"- Checks: the same verdict for {_pct(rp['checks']['same_status'])} of {rp['checks']['n']} hypotheses "
              f"(kappa {_k(rp['checks']['kappa'])}).",
              f"- Labels: the same codes for {_pct(rp['labels']['same_codes'])} of {rp['labels']['n']} passages; "
              f"{_pct(rp['labels']['code_agreement'])} of code decisions the same (kappa {_k(rp['labels']['kappa'])}).",
              ""]
        sec = s["passes"][1]
        L += [f"Against the gold set, the second pass had the right verdict for {_pct(sec['checks']['accuracy'])} of "
              f"hypotheses (kappa {_k(sec['checks']['kappa'])}) and {_pct(sec['labels']['code_accuracy'])} of code "
              f"decisions right (kappa {_k(sec['labels']['kappa'])}).", ""]
    else:
        L += ["This run has one pass only, so repeatability was not measured.", ""]
    L += ["## Limits", "",
          "- **The documents are invented**, written to make the right answers clear. Real documents are longer, less "
          "tidy and more ambiguous, so these figures are an upper bound more than a forecast.",
          "- **The gold set is small** (about 30 hypotheses and 100 passages): one hypothesis is about three points of "
          "accuracy, so a change of a few points between runs is not a real change.",
          "- **English only**, on one subject (remote work), with one codebook made for it.",
          "- **The right answers were written by an AI and checked by a second one**, against the documents only and "
          "without seeing any model's answers; the disagreements were settled by hand. They may still hold mistakes.",
          "- **A check's verdict also depends on the search**: when the eight passages read miss the evidence, the "
          "verdict is wrong although each grade was right. This report measures the whole check, as a researcher "
          "gets it.",
          "- **Claude's answers are not repeatable** the way a seeded local model's are; the repeatability above is "
          "of one run, on one day.", ""]
    return "\n".join(L)


def report(run_path: str | Path | None = None, latest: str | Path | None = None, out: str | Path | None = None,
           folder: str | Path | None = None) -> tuple[str | None, Path | None]:
    """(markdown, the run file used); (None, None) when `latest` names a folder without any run file."""
    path = Path(run_path) if run_path else latest_run(latest) if latest else None
    if path is None:
        return None, None
    run = read_run(path)
    fp = None
    try:
        fp = load_gold(folder)["fingerprint"]
    except (FileNotFoundError, ValueError):
        pass
    md = to_markdown(run, fp)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(md, encoding="utf-8")
    return md, path

