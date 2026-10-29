"""Reproducibility of model-made labels: what exactly produced each answer, and a warning when that changes.

Every model request already uses temperature 0, every task stores its model and prompt version, and every raw
answer is kept in `results`. 0.7 adds:

- the exact model: Ollama's digest of the model (from /api/tags); for OpenAI-compatible servers, which report none,
  the model file name the server lists; stored with each result, with the seed and the settings that matter
  (context length, reasoning and its budget) (`llm.provenance`);
- a fixed seed with every request (an Ollama option; a request field that llama.cpp, vLLM and LM Studio accept);
- runs: a label, theme or reference run records its model, digest, prompt version, seed and settings
  (`runs` table). Before the next run of the same kind and scope, `plan` says what differs from the last one, so
  the app can warn and offer to label a sample again first (`profile.compare_sample`);
- a sheet "How these results were made" in every Excel download (`provenance_table`).

The keyword-and-meaning pass, the term index and the clustering are deterministic (fixed seed) and need none of this.
"""
from __future__ import annotations

import json
import statistics
import uuid

from . import prompts
from .store import Workspace, now

FIELDS = ("model", "digest", "prompt_version", "seed", "num_ctx", "think", "think_budget", "backend")


def _settings_of(prov: dict) -> dict:
    s = dict(prov.get("settings") or {})
    return {k: s.get(k) for k in ("backend", "num_ctx", "think", "think_budget")}


def _routed(backend, kind: str, model: str) -> str:
    """The model the backend's router (0.8) gives this kind of task, else `model`."""
    r = getattr(backend, "router", None)
    return (r.call_model(kind) if r is not None else None) or model


def start(ws: Workspace, kind: str, scope: str, backend, model: str, n_tasks: int) -> str:
    from .llm import provenance

    model = _routed(backend, kind, model)
    prov = provenance(backend, model)
    rid = "u" + uuid.uuid4().hex[:12]
    with ws.connect() as cx:
        cx.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (rid, kind, scope, model, prov.get("digest"), prompts.VERSIONS.get(kind), prov.get("seed"),
                    json.dumps(_settings_of(prov)), now(), None, n_tasks))
    return rid


def finish(ws: Workspace, run_id: str, n_tasks: int) -> None:
    with ws.connect() as cx:
        cx.execute("UPDATE runs SET finished_at=?, tasks=? WHERE run_id=?", (now(), n_tasks, run_id))


def last(ws: Workspace, kind: str, scope: str | None = None) -> dict | None:
    sql = "SELECT * FROM runs WHERE kind=?" + (" AND scope=?" if scope else "") + " AND tasks > 0 ORDER BY started_at DESC, rowid DESC LIMIT 1"
    r = ws.query(sql, (kind, scope) if scope else (kind,))
    if not r:
        return None
    d = dict(r[0])
    d["settings"] = json.loads(d.pop("settings_json") or "{}")
    return d


def plan(ws: Workspace, kind: str, scope: str, backend, model: str) -> dict:
    """What would produce the next run, and how it differs from the last finished run of this kind and scope:
    {"now": {...}, "last": {...} | None, "changed": [{"field", "was", "now"}], "estimate_seconds"}."""
    from .llm import provenance

    model = _routed(backend, kind, model)
    prov = provenance(backend, model)
    cur = {"model": model, "digest": prov.get("digest"), "prompt_version": prompts.VERSIONS.get(kind),
           "seed": prov.get("seed"), **_settings_of(prov)}
    before = last(ws, kind, scope)
    changed = []
    if before:
        was = {"model": before["model"], "digest": before["digest"], "prompt_version": before["prompt_version"],
               "seed": before["seed"], **(before.get("settings") or {})}
        for f in FIELDS:
            if was.get(f) != cur.get(f) and not (was.get(f) is None and cur.get(f) is None):
                changed.append({"field": f, "was": was.get(f), "now": cur.get(f)})
    return {"now": cur, "last": before, "changed": changed, "seconds_per_task": seconds_per_task(ws, kind, model)}


def timing(ws: Workspace, kind: str, model: str, seconds: float) -> None:
    """Remember how long a task of this kind took with this model (the last 50), for estimates."""
    key = f"seconds:{kind}:{model}"
    xs = (ws.meta(key) or [])[-49:] + [round(float(seconds), 2)]
    ws.set_meta(key, xs)


def seconds_per_task(ws: Workspace, kind: str, model: str) -> float | None:
    """The median seconds per task: from this project's recent tasks of this kind, else from the model test
    (benchmark) of this model on this computer, else None."""
    xs = ws.meta(f"seconds:{kind}:{model}") or []
    if len(xs) >= 3:
        return round(statistics.median(xs), 1)
    from .home import benchmark_medians

    med = benchmark_medians().get(model) or {}
    for k in (kind, "check", "verify_set", "extract"):
        if med.get(k):
            return float(med[k])
    return None


def provenance_table(ws: Workspace, task_ids: list[str] | None = None, kinds: tuple[str, ...] | None = None) -> list[dict]:
    """"How these results were made": one row per model, digest, prompt version, seed and settings behind the
    answers of these tasks (or of these kinds), with how many answers and the dates."""
    sql = ("SELECT r.kind, r.model, r.digest, r.prompt_version, r.seed, r.settings_json, COUNT(*) AS n, "
           "MIN(r.received_at) AS first, MAX(r.received_at) AS last, COALESCE(r.route, '') AS route, "
           "COALESCE(r.helper, '') AS helper, SUM(COALESCE(r.step, 0)) AS stepped, MIN(r.claimed_at) AS claimed "
           "FROM results r WHERE r.valid=1")
    args: list = []
    if task_ids is not None:
        if not task_ids:
            return [{"Step": "No AI model was used for these rows: they come from the documents' text alone, and "
                             "the same documents always give the same rows."}]
        sql += " AND r.task_id IN (" + ",".join("?" * len(task_ids)) + ")"
        args += task_ids
    if kinds:
        sql += " AND r.kind IN (" + ",".join("?" * len(kinds)) + ")"
        args += list(kinds)
    sql += (" GROUP BY r.kind, r.model, r.digest, r.prompt_version, r.seed, r.settings_json, COALESCE(r.route, ''), "
            "COALESCE(r.helper, '') ORDER BY r.kind, first")
    names = {"check": "Checking hypotheses", "reread": "Reading an excerpt again", "second": "Second model",
             "expand": "Search words", "decompose": "Splitting a hypothesis", "label": "Codebook labels",
             "link": "How concepts relate", "theme": "Theme names", "resolve": "References in a document",
             "extract": "Extracting claims (SDG pack)", "verify_set": "Checking VCA claims (SDG pack)",
             "verify": "Checking claims (SDG pack)", "split": "Splitting justifications (SDG pack)"}
    out = []
    claude_code = False
    for r in ws.query(sql, args):
        s = json.loads(r["settings_json"] or "{}")
        route = r["route"] or s.get("route") or {"file queue": "file queue"}.get(s.get("backend"), "")
        cc = route == "Claude Code"
        claude_code = claude_code or cc
        out.append({"Step": names.get(r["kind"], r["kind"]), "Route": route,
                    "Helper": r["helper"] or "",
                    "AI model": (f"{r['model']} (as set for the helper)" if cc else r["model"]) or "",
                    "Exact model (digest or file)": r["digest"] or ("Claude Code reports none" if cc else
                                                                    "not reported by the model server"),
                    "Prompt version": r["prompt_version"] or "",
                    "Seed": "" if r["seed"] is None else r["seed"],
                    "Server": s.get("backend") or "", "Context length": s.get("num_ctx") or "",
                    "Reasoning": s.get("think") if s.get("think") is not None else "",
                    "Reasoning budget": s.get("think_budget") or "",
                    "Temperature": "" if cc else s.get("temperature", 0),
                    "Answers": r["n"], "Of them from the stronger model (stepped up)": int(r["stepped"] or 0),
                    "First claimed": r["claimed"] or "", "First": r["first"] or "", "Last": r["last"] or ""})
    if not out:
        out.append({"Step": "No AI model answer is behind these rows (keyword and meaning passes are deterministic)."})
    elif claude_code:
        out.append({"Step": "Note: answers by Claude Code carry no seed and no model digest, so they are not "
                            "repeatable by seed the way a seeded local model's are; the model is the one set for its "
                            "helper. How much two readings differ is measured by the acceptance runs (see the manual)."})
    return out


def hypothesis_task_ids(ws: Workspace, hyp_ids: list[str]) -> list[str]:
    ids: list[str] = []
    for hid in hyp_ids:
        ids.append(f"decompose:{hid}")
        for (cid,) in ws.query("SELECT claim_id FROM user_claims WHERE hyp_id=?", (hid,)):
            ids.append(f"expand:{cid}")
            ids += [r[0] for r in ws.query("SELECT task_id FROM tasks WHERE kind IN ('check','reread','second') AND "
                                           "(task_id=? OR task_id LIKE ? OR task_id LIKE ? OR task_id LIKE ?)",
                                           (f"check:{cid}", f"check:{cid}:r%", f"reread:{cid}:%", f"second:check:{cid}%"))]
    return ids
