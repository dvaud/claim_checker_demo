"""Proving it on the pilot (0.8, G6): which model is good enough for each kind of task, and how long it takes.

For every task kind and model a run goes through the queue, on a copy of the reference workspace (the pilot), so the
models' answers never mix with each other or with the pilot's own. A person fills the sample sheets once
(`enlens acceptance samples`); every run is scored against them.

    enlens --ws pilot acceptance queue --kind label --model haiku     # a copy "pilot eval label haiku", tasks queued
    /enlens-run "pilot eval label haiku"                              # in Claude Code (Claude models)
    enlens --ws "<copy folder>" queue run --backend ollama            # (the local model: answered here)
    enlens --ws pilot acceptance queue --kind label --model haiku --again   # the same tasks once more: repeatability
    enlens --ws pilot acceptance score                                # every run: the measure, seconds per task
    enlens --ws pilot acceptance score --apply                        # the cheapest model that passes becomes the default

| Kind | Sample (filled once by a person) | Measure |
| label | f2_labels.csv: 200 passages with their codes | kappa on "code present"; recall of the keyword pass |
| link | f3_pairs.csv: 50 term pairs, same or not | share of pairs judged as the person did |
| theme | g6_theme_names_<model>.csv, written after the run: each model's names, fitting or not | share fitting |
| resolve | f5_pronouns.csv: quotes opening with "it" or "they", the right referent | share where the chain names it |
| check | the pilot's checked VCA claims (its answers are the reference); g6_checks.csv: a person's status, if filled | agreement with the reference status and per excerpt; with the person |
| all kinds | the same tasks answered twice (--again) | share of agreeing answers (repeatability) |

The team sets the pass marks (`acceptance/pass_marks.json`, for example {"label": 0.6, "link": 0.8}) before any run is
scored. A kind where no affordable model passes keeps a person in the loop: its answers stay provisional.
"""
from __future__ import annotations

import json
import random
import re
import shutil
import sqlite3
import statistics
from pathlib import Path

from . import home
from .store import Workspace

KINDS = ("label", "link", "theme", "resolve", "check")
COST_ORDER = ("haiku", "sonnet", "opus", "fable")   # cheapest first; a local model ("local:<name>") costs no plan
DEFAULT_MODELS = {"label": ("haiku", "sonnet", "opus", "local"), "link": ("haiku", "sonnet"),
                  "theme": ("sonnet", "opus"), "resolve": ("sonnet", "opus"), "check": ("sonnet", "opus", "local")}
SEED = 11
CHECK_SAMPLE = 50
REPEAT_SAMPLE = 50


def _read_csv(path: Path) -> list[dict]:
    from .acceptance import _read

    return _read(path)


def eval_name(ref: Workspace, kind: str, model: str, again: bool = False) -> str:
    base = home.safe_name(ref.root.name) or "reference"
    m = re.sub(r"[^\w.-]", "-", model)
    return home.safe_name(f"{base} eval {kind} {m}{' again' if again else ''}")


def _copy(ref: Workspace, name: str) -> Workspace:
    """A copy of the reference workspace as a project of the data folder (the SQLite backup API: consistent while
    the reference is open). Earlier tasks and answers are dropped from the copy; its documents stay."""
    dest = home.home() / "projects" / name
    if dest.exists():
        raise ValueError(f"The evaluation project {name!r} exists already. Score it, or remove it under Manage "
                         "projects to run it again.")
    dest.mkdir(parents=True)
    src = sqlite3.connect(ref.db_path)
    dst = sqlite3.connect(dest / "enlens.sqlite")
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    if ref.config_path.exists():
        shutil.copy2(ref.config_path, dest / "config.json")
    for sub in ("frameworks",):
        if (ref.root / sub).is_dir():
            shutil.copytree(ref.root / sub, dest / sub)
    ws = Workspace.open(dest)
    with ws.connect() as cx:
        for tbl in ("results", "tasks", "task_claims", "runs"):
            cx.execute(f"DELETE FROM {tbl}")
    ws.set_meta("evaluation", {"reference": str(ref.root.resolve())})
    return ws


def _force(ws: Workspace, task_ids: list[str], model: str) -> int:
    """These tasks keep `model` (routing leaves them alone) and wait in the queue."""
    from .store import now

    forced = model.split(":", 1)[1] if model.startswith("local:") else model
    with ws.connect() as cx:
        for tid in task_ids:
            # 0.11: a task of a restricted document is never queued (the queue hands out `cloud` tasks only)
            cx.execute("UPDATE tasks SET forced_model=?, model=?, queued=CASE WHEN COALESCE(access, 'cloud')='cloud' "
                       "THEN 1 ELSE 0 END, queued_at=?, status='pending', attempts=0 WHERE task_id=?",
                       (forced, forced, now(), tid))
    return len(task_ids)


def prepare(ref: Workspace, folder: str | Path, kind: str, model: str, again: bool = False,
            framework: str = "sdg") -> dict:
    """Make the evaluation project for one kind and model, with its tasks waiting in the queue."""
    from . import profile, references, terms, themes

    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}.")
    folder = Path(folder)
    name = eval_name(ref, kind, model, again)
    ids: list[str] = []
    if kind == "label":
        rows = _read_csv(folder / "f2_labels.csv")
        if not rows:
            raise ValueError(f"No f2_labels.csv in {folder}: run `acceptance samples` first.")
        ws = _copy(ref, name)
        profile.ensure_pass1(ws, framework)
        pids = [r["passage_id"] for r in rows]
        if again:
            pids = random.Random(SEED).sample(pids, min(REPEAT_SAMPLE, len(pids)))
        profile.make_label_tasks(ws, framework, pids, model)
        ids = [f"label:{framework}:{p}" for p in pids if ws.scalar("SELECT 1 FROM tasks WHERE task_id=?",
                                                                     (f"label:{framework}:{p}",))]
    elif kind == "link":
        rows = _read_csv(folder / "f3_pairs.csv")
        if not rows:
            raise ValueError(f"No f3_pairs.csv in {folder}: run `acceptance samples` first.")
        ws = _copy(ref, name)
        terms.ensure(ws)
        for r in rows:
            try:
                ids.append(terms.make_link_task(ws, r["a"], r["b"], model))
            except KeyError:
                continue
    elif kind == "theme":
        rows = _read_csv(folder / "f4_themes.csv")
        run_id = next((r["run_id"] for r in rows if r.get("run_id")), None)
        if not run_id:
            raise ValueError(f"No set of themes in {folder}/f4_themes.csv: run themes on the reference, then "
                             "`acceptance samples`.")
        ws = _copy(ref, name)
        themes.make_name_tasks(ws, run_id, model)
        ids = [r[0] for r in ws.query("SELECT task_id FROM tasks WHERE kind='theme'")]
    elif kind == "resolve":
        rows = _read_csv(folder / "f5_pronouns.csv")
        if not rows:
            raise ValueError(f"No f5_pronouns.csv in {folder}: run `acceptance samples` first.")
        ws = _copy(ref, name)
        want = {r["passage_id"] for r in rows}
        docs = {r[0] for r in ws.query(f"SELECT DISTINCT doc_id FROM passages WHERE passage_id IN "
                                       f"({','.join('?' * len(want))})", list(want))} if want else set()
        for d in sorted(docs):
            for tid in references.make_tasks(ws, d, model):
                payload = json.loads(ws.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (tid,)))
                if any(p["passage_id"] in want for p in payload["passages"]):
                    ids.append(tid)
                else:
                    with ws.connect() as cx:
                        cx.execute("DELETE FROM tasks WHERE task_id=?", (tid,))
    else:
        refs = _reference_checks(ref)
        if not refs:
            raise ValueError("The reference workspace has no answered VCA checks (verify_set tasks).")
        sample = random.Random(SEED).sample(refs, min(CHECK_SAMPLE if not again else REPEAT_SAMPLE, len(refs)))
        ws = _copy(ref, name)
        from .tasks import _insert_task

        with ws.connect() as cx:
            for t in sample:
                p = dict(t["payload"])
                p["subject_kind"] = "eval_check"
                tid = f"check:eval:{p['subject_id']}"
                _insert_task(cx, tid, "check", model, p)
                ids.append(tid)
    n = _force(ws, ids, model)
    ws.set_meta("evaluation", {"reference": str(ref.root.resolve()), "kind": kind, "model": model, "again": again,
                               "tasks": ids})
    local = model.startswith("local:")
    return {"project": name, "kind": kind, "model": model, "tasks": n, "again": again,
            "next": (f'enlens --ws "{ws.root}" queue run --backend ollama' if local
                     else f'In Claude Code: /enlens-run "{name}"')}


def _reference_checks(ref: Workspace) -> list[dict]:
    """The reference's answered VCA checks: the payload, the reference status and grades per passage."""
    from .benchmark import _grades, _reference, _status_from

    thr = float(ref.config["thresholds"]["support_confidence"])
    out = []
    for t in ref.query("SELECT * FROM tasks WHERE kind='verify_set' AND status='done' AND task_id NOT LIKE '%:audit:%' "
                       "ORDER BY task_id"):
        payload = json.loads(t["payload_json"])
        r = _reference(ref, t["task_id"])
        if r is None:
            continue
        n = len(payload["passages"])
        out.append({"task_id": t["task_id"], "payload": payload, "status": _status_from(r, n, thr),
                    "grades": _grades(r, n)})
    return out


# ---------------------------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------------------------
def _eval_projects(ref: Workspace) -> list[tuple[str, Workspace, dict]]:
    out = []
    root = str(ref.root.resolve())
    for name in home.list_projects():
        try:
            ws = home.open_project(name)
        except Exception:  # noqa: BLE001
            continue
        m = ws.meta("evaluation") or {}
        if m.get("reference") == root and m.get("kind"):
            out.append((name, ws, m))
    return out


def _seconds(ws: Workspace, kind: str, model: str) -> float | None:
    xs = []
    for key in (f"seconds:{kind}:{model}", f"seconds:{kind}:{model.split(':', 1)[-1]}"):
        xs += ws.meta(key) or []
    return round(statistics.median(xs), 1) if xs else None


def _answered(ws: Workspace, ids: list[str]) -> tuple[int, int]:
    done = sum(1 for t in ids if ws.scalar("SELECT status FROM tasks WHERE task_id=?", (t,)) == "done")
    failed = sum(1 for t in ids if ws.scalar("SELECT status FROM tasks WHERE task_id=?", (t,)) == "failed")
    return done, failed


def _score_label(ref: Workspace, ws: Workspace, folder: Path, framework: str = "sdg") -> dict:
    from . import frameworks, profile
    from .acceptance import _kappa

    fw = frameworks.get(framework, ws)
    gold = {}
    for r in _read_csv(folder / "f2_labels.csv"):
        if (r.get("codes") or "").strip():
            gold[r["passage_id"]] = {fw.normalise(c) for c in re.split(r"[;,\s]+", r["codes"]) if fw.normalise(c)}
    if not gold:
        return {"note": "f2_labels.csv is not filled in yet"}
    pairs = []
    for pid, codes in gold.items():
        mine = {r[0] for r in ws.query("SELECT code FROM labels WHERE framework=? AND passage_id=? AND source='model'",
                                       (framework, pid))}
        cands = {c["code"] for c in profile.candidates_of(ws, framework, pid)}
        for c in codes | mine | cands:
            pairs.append((c in codes, c in mine))
    k = _kappa(pairs)
    return {"measure": "kappa on code present", "score": round(k, 3) if k is not None else None,
            "passages": len(gold), "keyword_pass_recall": profile.recall_at_candidates(ws, framework, gold)}


def _score_link(ws: Workspace, folder: Path) -> dict:
    from .acceptance import _yes

    rows = [r for r in _read_csv(folder / "f3_pairs.csv") if _yes(r.get("same")) is not None]
    if not rows:
        return {"note": "f3_pairs.csv is not filled in yet"}
    agree = n = 0
    for r in rows:
        a, b = sorted((r["a"], r["b"]))
        got = ws.query("SELECT relation FROM concept_links WHERE a=? AND b=? AND source='model'", (a, b))
        if not got:
            continue
        n += 1
        agree += (got[0][0] == "same") == _yes(r["same"])
    return {"measure": "pairs judged as the person did", "score": round(agree / n, 3) if n else None, "pairs": n}


def _score_theme(ws: Workspace, folder: Path, model: str) -> dict:
    from .acceptance import _write, _yes

    sheet = folder / f"g6_theme_names_{re.sub(r'[^\w.-]', '-', model)}.csv"
    rows = _read_csv(sheet)
    if not rows:
        names = [{"theme_id": r["theme_id"], "name": r["name"] or "", "description": r["description"] or "",
                  "fitting": "", "note": ""}
                 for r in ws.query("SELECT theme_id, name, description FROM themes WHERE name_source='model' "
                                   "ORDER BY theme_id")]
        if names:
            _write(sheet, names)
            return {"note": f"{sheet.name} written: a person says for each name whether it fits, then score again"}
        return {"note": "no theme was named yet"}
    filled = [r for r in rows if _yes(r.get("fitting")) is not None]
    if not filled:
        return {"note": f"{sheet.name} is not filled in yet"}
    return {"measure": "names fitting", "score": round(sum(_yes(r["fitting"]) for r in filled) / len(filled), 3),
            "themes": len(filled)}


def _norm(s: str | None) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (s or "").lower()))


def _score_resolve(ws: Workspace, folder: Path) -> dict:
    from .acceptance import _yes
    from .references import chain_at

    rows = _read_csv(folder / "f5_pronouns.csv")
    rows = [r for r in rows if _yes(r.get("right")) is not None]
    if not rows:
        return {"note": "f5_pronouns.csv is not filled in yet"}
    right = n = 0
    for r in rows:
        truth = r.get("refers_to") if _yes(r["right"]) else r.get("should_be")
        if not _norm(truth):
            continue
        p = ws.query("SELECT doc_id, start, text FROM passages WHERE passage_id=?", (r["passage_id"],))
        if not p:
            continue
        i = p[0]["text"].find(r["quote"] or "")
        if i < 0:
            continue
        n += 1
        ch = chain_at(ws, p[0]["doc_id"], p[0]["start"] + i, p[0]["start"] + i + 12)
        names = [_norm(m.get("text")) for m in (ch or {}).get("mentions", []) if m.get("is_named")] + \
            [_norm((ch or {}).get("name"))]
        t = _norm(truth)
        right += any(x and (x in t or t in x) for x in names)
    return {"measure": "referent right", "score": round(right / n, 3) if n else None, "quotes": n}


def _score_check(ref: Workspace, ws: Workspace, folder: Path, ids: list[str]) -> dict:
    from .acceptance import _read
    from .benchmark import _status_from

    refs = {r["payload"]["subject_id"]: r for r in _reference_checks(ref)}
    thr = float(ref.config["thresholds"]["support_confidence"])
    same_status = grade_same = grades = n = 0
    person = {r["vca_claim_id"]: (r.get("status") or "").strip() for r in _read(folder / "g6_checks.csv")
              if (r.get("status") or "").strip()}
    p_agree = p_n = 0
    for tid in ids:
        sid = tid.split(":", 2)[2]
        if sid not in refs:
            continue
        rr = ws.query("SELECT raw_json FROM results WHERE task_id=? AND valid=1 ORDER BY attempt DESC LIMIT 1", (tid,))
        if not rr:
            continue
        from .benchmark import _grades
        from .tasks import parse_json

        out = parse_json(rr[0][0])
        k = len(refs[sid]["payload"]["passages"])
        st = _status_from(out, k, thr)
        n += 1
        same_status += st == refs[sid]["status"]
        g = _grades(out, k)
        for a, b in zip(g, refs[sid]["grades"]):
            grades += 1
            grade_same += a == b
        if sid in person:
            p_n += 1
            p_agree += st == person[sid]
    return {"measure": "same status as the reference", "score": round(same_status / n, 3) if n else None,
            "claims": n, "same_grade_per_excerpt": round(grade_same / grades, 3) if grades else None,
            "agreement_with_person": round(p_agree / p_n, 3) if p_n else None, "judged_by_person": p_n}


def _decision(ws: Workspace, task_id: str, kind: str):
    """What an answer decides, to compare two runs: label codes, link relation, grades, theme name, chains."""
    from .tasks import parse_json

    rr = ws.query("SELECT raw_json FROM results WHERE task_id=? AND valid=1 ORDER BY attempt DESC LIMIT 1", (task_id,))
    if not rr:
        return None
    try:
        o = parse_json(rr[0][0])
    except ValueError:
        return None
    if kind == "label":
        return tuple(sorted(str(x.get("code")) for x in o.get("labels") or [] if isinstance(x, dict)))
    if kind == "link":
        return tuple(sorted(str(x.get("relation")) for x in o.get("relations") or [] if isinstance(x, dict)))
    if kind == "check":
        return tuple(sorted((int(x.get("passage") or 0), str(x.get("verdict"))) for x in o.get("evidence") or []
                            if isinstance(x, dict)))
    if kind == "theme":
        return _norm(o.get("name"))
    if kind == "resolve":
        return tuple(sorted(_norm(c.get("name")) for c in o.get("chains") or [] if isinstance(c, dict)))
    return json.dumps(o, sort_keys=True)


def _repeatability(a: Workspace, b: Workspace, kind: str, ids: list[str]) -> dict:
    same = n = 0
    for tid in ids:
        x, y = _decision(a, tid, kind), _decision(b, tid, kind)
        if x is None or y is None:
            continue
        n += 1
        same += x == y
    return {"measure": "same decision twice", "score": round(same / n, 3) if n else None, "tasks": n}


def score(ref: Workspace, folder: str | Path, apply: bool = False) -> dict:
    """Score every evaluation run of this reference; write model_choice.json and MODEL_CHOICE.md in `folder`."""
    folder = Path(folder)
    marks_path = folder / "pass_marks.json"
    marks = json.loads(marks_path.read_text(encoding="utf-8")) if marks_path.exists() else {}
    runs = _eval_projects(ref)
    by_key = {(m["kind"], m["model"], bool(m.get("again"))): (name, ws, m) for name, ws, m in runs}
    rows = []
    for (kind, model, again), (name, ws, m) in sorted(by_key.items()):
        if again:
            continue
        ids = m.get("tasks") or []
        done, failed = _answered(ws, ids)
        if kind == "label":
            s = _score_label(ref, ws, folder)
        elif kind == "link":
            s = _score_link(ws, folder)
        elif kind == "theme":
            s = _score_theme(ws, folder, model)
        elif kind == "resolve":
            s = _score_resolve(ws, folder)
        else:
            s = _score_check(ref, ws, folder, ids)
        rep = by_key.get((kind, model, True))
        if rep:
            s["repeatability"] = _repeatability(ws, rep[1], kind, rep[2].get("tasks") or [])["score"]
        mark = marks.get(kind)
        passes = None if mark is None or s.get("score") is None else s["score"] >= float(mark)
        rows.append({"kind": kind, "model": model, "project": name, "tasks": len(ids), "answered": done,
                     "failed": failed, "seconds_per_task": _seconds(ws, kind, model), "pass_mark": mark,
                     "passes": passes, **s})
    chosen = {}
    for kind in KINDS:
        cand = [r for r in rows if r["kind"] == kind and r["passes"]]
        claude = sorted((r for r in cand if r["model"] in COST_ORDER), key=lambda r: COST_ORDER.index(r["model"]))
        local = [r for r in cand if r["model"].startswith("local")]
        scored = [r for r in rows if r["kind"] == kind and r.get("score") is not None]
        chosen[kind] = {"claude": claude[0]["model"] if claude else None,
                        "local": local[0]["model"] if local else None,
                        "provisional": bool(scored) and not cand,
                        "measured": bool(scored)}
    out = {"reference": str(ref.root), "runs": rows, "chosen": chosen, "pass_marks": marks,
           "note": None if marks else "No pass marks set yet (acceptance/pass_marks.json): the team sets them before "
                                      "any run is scored."}
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "model_choice.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    (folder / "MODEL_CHOICE.md").write_text(report_markdown(out), encoding="utf-8")
    if apply:
        out["applied"] = apply_choice(chosen)
    return out


def apply_choice(chosen: dict) -> dict:
    """Make the chosen Claude models the defaults of this installation (Settings, AI model per task)."""
    s = home.load_settings()
    tm = dict(s.get("task_models") or {})
    claude = dict(tm.get("claude") or {})
    for kind, c in chosen.items():
        if c.get("claude"):
            claude[kind] = c["claude"]
    if claude:
        tm["claude"] = claude
    home.update_settings({"task_models": tm})
    return tm


def report_markdown(out: dict) -> str:
    from .routing import CLAUDE_DEFAULTS

    lines = ["# Which model each task needs (G6)", "",
             f"Reference: `{out['reference']}`. Written by `enlens acceptance score`.", ""]
    if out.get("note"):
        lines += [f"> {out['note']}", ""]
    for kind in KINDS:
        rows = [r for r in out["runs"] if r["kind"] == kind]
        lines += [f"## {kind}", "", "| Model | Tasks answered | Measure | Score | Repeatability | Seconds per task | "
                                   "Pass mark | Passes |", "|---|---|---|---|---|---|---|---|"]
        if not rows:
            lines.append("| not measured yet | | | | | | | |")
        for r in rows:
            lines.append(f"| {r['model']} | {r['answered']} of {r['tasks']} | {r.get('measure') or r.get('note') or ''} | "
                         f"{'' if r.get('score') is None else r['score']} | "
                         f"{'' if r.get('repeatability') is None else r['repeatability']} | "
                         f"{r.get('seconds_per_task') or ''} | {'' if r['pass_mark'] is None else r['pass_mark']} | "
                         f"{'' if r['passes'] is None else ('yes' if r['passes'] else 'no')} |")
        c = out["chosen"].get(kind, {})
        default = CLAUDE_DEFAULTS[kind][0]
        if c.get("claude"):
            verdict = f"Chosen Claude default: **{c['claude']}** (the cheapest model that passes; until now {default})."
        elif c.get("provisional"):
            verdict = ("No affordable model passes: a person stays in the loop, and its answers stay marked "
                       "provisional.")
        else:
            verdict = f"Not decided yet: the default stays **{default}** until this kind is measured."
        lines += ["", verdict, ""]
    return "\n".join(lines) + "\n"
