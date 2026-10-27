"""Command line: `enlens <command> --ws WORKSPACE ...`. Run `enlens -h` for the list."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import analysis, ingest, report, retrieve, review, sources, tasks, vca
from .llm import BackendError, get_backend
from .store import Workspace


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def _backend(a):
    kw: dict = {}
    if a.backend == "ollama":
        kw = {"base_url": a.url, "num_ctx": a.num_ctx, "think": None if a.think is None else a.think == "on"}
    elif a.backend == "local" and a.url:
        kw = {"base_url": a.url}
    return get_backend(a.backend, **kw)


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except BackendError as e:
        print(f"Problem: {e}", file=sys.stderr)
        return 1


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="enlens", description="Evidence-grounded SDG impact claims for value chain assessment.")
    ap.add_argument("--ws", default="workspace", help="workspace folder (default: ./workspace)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create the workspace folder and database")
    p = sub.add_parser("load-vca", help="load the VCA supplementary workbook as gold labels")
    p.add_argument("xlsx")
    p = sub.add_parser("ingest", help="add PDFs, HTML or text files (folders and zips are searched)")
    p.add_argument("inputs", nargs="+")
    p.add_argument("--exclude", action="append", default=[], metavar="PATTERN",
                   help="leave out files whose name matches this pattern, e.g. 'A_18_*' (repeatable)")
    sub.add_parser("match-sources", help="link documents to the references cited in the VCA")
    p = sub.add_parser("reset-corpus", help="remove all documents and what was derived from them (keeps the VCA and splits)")
    p.add_argument("--yes", action="store_true", help="confirm")
    sub.add_parser("coverage", help="which justified targets have their cited sources available")
    p = sub.add_parser("screen", help="mark passages worth sending to extraction")
    p.add_argument("--min-score", type=float)

    p = sub.add_parser("make-tasks", help="create model tasks")
    p.add_argument("kind", choices=["split", "extract", "verify-vca", "verify-claims", "audit-vca"])
    p.add_argument("--model", help="model id recorded with the task (defaults from config.json)")
    p.add_argument("--limit", type=int)
    p.add_argument("--all-passages", action="store_true", help="extract: include passages the screen left out")
    p.add_argument("--per-target", type=int, help="extract: only the top N passages for each of the 169 SDG targets")
    p.add_argument("--docs", nargs="*", help="extract: only these document ids")
    p.add_argument("--k", type=int, help="verify-vca: passages per VCA claim (default: thresholds.verify_top_k)")
    p.add_argument("--per-doc", type=int, default=2, help="verify-vca: at most this many passages from one source first")
    p.add_argument("--pairwise", action="store_true", help="verify-vca: one task per claim and passage (older design)")
    p.add_argument("--any-passage", action="store_true",
                   help="extract --per-target: also rank passages that do not name hydrogen or a derivative")
    p.add_argument("--beyond-cited", action="store_true", help="verify-vca: search all documents, not only cited ones")
    p.add_argument("--sample", type=float, default=1.0,
                   help="verify-claims / audit-vca: fraction of claims to re-check (audit-vca needs --model)")

    def backend_args(p, default="anthropic"):
        p.add_argument("--backend", default=default, choices=["anthropic", "ollama", "local", "baseline"],
                       help="anthropic = Claude API; ollama = a model in Ollama; local = another OpenAI-compatible server; "
                            "baseline = offline keyword demo")
        p.add_argument("--url", help="ollama: server address (default http://localhost:11434); local: OpenAI-compatible "
                                     "base URL")
        p.add_argument("--num-ctx", type=int, default=16384, help="ollama: context length in tokens (default 16384)")
        p.add_argument("--think", choices=["on", "off"], help="ollama: switch a reasoning model's thinking on or off")

    p = sub.add_parser("run", help="answer pending tasks with a backend")
    p.add_argument("kind", choices=list(tasks.KINDS))
    backend_args(p)
    p.add_argument("--model", help="override the model id stored on the tasks")
    p.add_argument("--limit", type=int)

    p = sub.add_parser("check", help="check one claim against the documents in the workspace")
    p.add_argument("claim")
    p.add_argument("--target", help="SDG target the claim is about, e.g. 6.4 (optional)")
    p.add_argument("--k", type=int, default=8, help="passages to read (default 8)")
    p.add_argument("--per-doc", type=int, default=2, help="at most this many passages from one document first")
    p.add_argument("--no-expand", action="store_true", help="skip the model call that writes search terms")
    p.add_argument("--model", help="model id (default: models.verify in config.json)")
    backend_args(p)

    p = sub.add_parser("benchmark", help="score a model on tasks the workspace already answered (nothing is stored)")
    p.add_argument("--model", required=True)
    p.add_argument("--sample", type=int, default=30, help="tasks per kind (default 30)")
    p.add_argument("--kinds", nargs="+", default=["verify_set", "extract"], choices=["verify_set", "extract", "split"])
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", help="write the full result as JSON here")
    backend_args(p, default="ollama")

    p = sub.add_parser("backend-check", help="test the connection to a backend and whether a model is available")
    p.add_argument("--model")
    backend_args(p, default="ollama")

    p = sub.add_parser("export-tasks", help="write pending tasks to JSONL batches for an outside worker")
    p.add_argument("kind", choices=list(tasks.KINDS))
    p.add_argument("--batch-size", type=int, default=25)
    p.add_argument("--limit", type=int)
    p = sub.add_parser("import-results", help="validate and store worker answers (files or folders of JSONL)")
    p.add_argument("paths", nargs="+")
    p.add_argument("--model", help="model id to record when a result line has none")
    p = sub.add_parser("check-results", help="validate worker answers without storing them (for workers)")
    p.add_argument("paths", nargs="+")
    p = sub.add_parser("refresh", help="queue tasks again after a prompt change (old results are kept)")
    p.add_argument("kind", choices=list(tasks.KINDS))
    p.add_argument("--model", help="also switch the tasks to this model")
    p = sub.add_parser("requeue", help="put exported tasks without an answer back in the queue")
    p.add_argument("kind", nargs="?", choices=list(tasks.KINDS))

    p = sub.add_parser("review-export", help="write the reviewer queue as CSV")
    p.add_argument("csv")
    p.add_argument("--audit", type=float, default=0.05, help="fraction of auto-accepted claims to audit")
    p = sub.add_parser("review-import", help="read reviewer decisions from CSV")
    p.add_argument("csv")
    p.add_argument("--reviewer", default="")
    p = sub.add_parser("gold-export", help="write reviewed claims as JSONL")
    p.add_argument("path")

    p = sub.add_parser("evaluate", help="compare extracted evidence with the VCA and print metrics")
    p.add_argument("--strict", action="store_true", help="only auto-accepted and reviewed claims")
    p = sub.add_parser("report", help="write report.html and CSV exports")
    p.add_argument("--out")
    p.add_argument("--strict", action="store_true")
    sub.add_parser("status", help="counts per table and task status")

    a = ap.parse_args(argv)
    if a.cmd == "backend-check":
        try:
            _print(_backend(a).check(a.model))
        except BackendError as e:
            print(f"Problem: {e}")
            return 1
        return 0
    if a.cmd == "init":
        ws = Workspace.create(a.ws)
        print(f"Workspace ready at {ws.root.resolve()}")
        return 0
    ws = Workspace.open(a.ws)

    if a.cmd == "load-vca":
        _print(vca.load_into(ws, a.xlsx))
    elif a.cmd == "ingest":
        _print(ingest.ingest(ws, a.inputs, a.exclude))
    elif a.cmd == "reset-corpus":
        if not a.yes:
            print("This deletes documents, passages, claims, verifications and their tasks. Run again with --yes.")
            return 1
        _print(ws.reset_corpus())
    elif a.cmd == "match-sources":
        _print(sources.match(ws))
    elif a.cmd == "coverage":
        cov = sources.coverage(ws)
        _print({"justified_targets": len(cov), "with_any_source": sum(1 for c in cov if c["available"]),
                "unreadable_documents": sorted(sources.unreadable_docs(ws)), "targets": cov})
    elif a.cmd == "screen":
        _print(retrieve.screen(ws, a.min_score))
    elif a.cmd == "make-tasks":
        if a.kind == "split":
            _print({"created": tasks.make_split(ws, a.model)})
        elif a.kind == "extract":
            _print({"created": tasks.make_extract(ws, a.model, a.docs, only_screened=not a.all_passages, limit=a.limit,
                                                  per_target=a.per_target, hydrogen_only=not a.any_passage)})
        elif a.kind == "verify-vca":
            _print(tasks.make_verify_vca(ws, a.model, a.k, a.beyond_cited, a.pairwise, a.per_doc))
        elif a.kind == "audit-vca":
            if not a.model:
                print("audit-vca needs --model: the second model whose answers are compared with the first.")
                return 1
            _print({"created": tasks.make_audit_vca(ws, a.model, a.sample)})
        else:
            _print({"created": tasks.make_verify_claims(ws, a.model, a.sample)})
    elif a.cmd == "run":
        _print(tasks.run(ws, a.kind, _backend(a), a.limit, a.model))
    elif a.cmd == "check":
        from . import claimcheck

        model = a.model or ws.config["models"]["verify"]
        cid = claimcheck.check_claim(ws, a.claim, _backend(a), model, target=a.target, k=a.k, per_doc=a.per_doc,
                                     expand=not a.no_expand, progress=lambda step, msg: print(msg, "...", file=sys.stderr))
        r = claimcheck.result(ws, cid)
        _print({"claim_id": cid, "status": r["status"], "explanation": claimcheck.STATUS_TEXT.get(r["status"]),
                "status_any_confidence": r["status_any"], "rationale": r["rationale"], "search_terms": r["terms"],
                "errors": r["errors"],
                "graded": [{k: p[k] for k in ("verdict", "confidence", "quote", "title", "page")} for p in r["passages"] if p["verdict"]],
                "also_read": [{k: p[k] for k in ("title", "page")} for p in r["passages"] if not p["verdict"]]})
    elif a.cmd == "benchmark":
        from . import benchmark

        res = benchmark.run(ws, _backend(a), a.model, kinds=a.kinds, sample=a.sample, seed=a.seed,
                            progress=lambda i, n, tid: print(f"[{i}/{n}] {tid}", file=sys.stderr))
        if a.out:
            Path(a.out).write_text(json.dumps(res, indent=2, ensure_ascii=False))
        _print({"model": res["model"], "reference": res["reference"], "kinds": res["kinds"],
                "verdict": benchmark.verdict(res)})
    elif a.cmd == "export-tasks":
        files = tasks.export(ws, a.kind, a.batch_size, a.limit)
        _print({"files": [str(f) for f in files], "instructions": str(ws.root / "tasks" / a.kind / "WORKER_GUIDE.md")})
    elif a.cmd == "import-results":
        _print(tasks.import_results(ws, a.paths, a.model))
    elif a.cmd == "check-results":
        res = tasks.check_results(ws, a.paths)
        _print(res)
        return 0 if not res["problems"] else 1
    elif a.cmd == "refresh":
        _print({"queued": tasks.refresh(ws, a.kind, a.model)})
    elif a.cmd == "requeue":
        _print({"requeued": tasks.requeue(ws, a.kind)})
    elif a.cmd == "review-export":
        _print(review.export(ws, a.csv, a.audit))
    elif a.cmd == "review-import":
        _print(review.import_decisions(ws, a.csv, a.reviewer))
    elif a.cmd == "gold-export":
        _print({"written": review.export_gold(ws, a.path)})
    elif a.cmd == "evaluate":
        analysis.infer_interactions(ws, a.strict)
        rec = analysis.label_recovery(ws, a.strict)
        rec["target_presence_all_targets"] = analysis.label_recovery(ws, a.strict, only_covered=False)["target_presence"]
        rec.pop("target_presence")  # within justified targets every target is positive, so only all-target scoring is informative
        from collections import Counter
        _print({"vca_claims": dict(Counter(s["status"] for s in analysis.vca_support(ws))),
                "status_by_threshold": analysis.status_sensitivity(ws), "audit": analysis.audit_summary(ws),
                **{k: v for k, v in rec.items() if k not in ("targets", "cells")}})
    elif a.cmd == "report":
        path = report.build(ws, a.out, a.strict)
        print(f"Report written to {path}")
    elif a.cmd == "status":
        st = {r[0] + ":" + r[1]: r[2] for r in ws.query("SELECT kind, status, COUNT(*) FROM tasks GROUP BY kind, status")}
        cl = {r[0]: r[1] for r in ws.query("SELECT status, COUNT(*) FROM claims GROUP BY status")}
        _print({"tables": ws.counts(), "tasks": st, "claims": cl})
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
