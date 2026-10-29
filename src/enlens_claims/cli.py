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


def _context(a, kinds: tuple[str, ...], ws=None) -> int:
    """--num-ctx, or with "auto" the smallest length that fits: for `run`, the largest pending task itself; otherwise
    the largest task of these kinds at --k excerpts (see home.context_plan)."""
    from . import home
    from .llm import OUTPUT_CAP, THINK_ALLOWANCE, estimate_tokens, fit_context

    if str(a.num_ctx).lower() != "auto":
        return int(a.num_ctx)
    thinks = a.think != "off"
    budget = a.think_budget if thinks else 0
    if ws is not None and getattr(a, "cmd", "") == "run":
        todo = tasks.pending(ws, a.kind, a.limit)
        if todo:
            from .llm import JUDGING

            need = max(estimate_tokens(s) + estimate_tokens(u) for s, u in (tasks.render(ws, t) for t in todo))
            on = thinks and (a.think != "judging" or a.kind in JUDGING)
            return fit_context(need + OUTPUT_CAP.get(a.kind, 2000) +
                               ((2 * budget + 64 if budget else THINK_ALLOWANCE) if on else 0))
    k = int(getattr(a, "k", None) or 8)
    return home.context_plan({"num_ctx": "auto", "k": k, "think": a.think or "default", "think_budget": budget},
                             kinds)["num_ctx"]


def _backend(a, kinds: tuple[str, ...] = ("check", "expand", "decompose"), ws=None):
    kw: dict = {}
    seed = getattr(a, "model_seed", 42)
    seed = None if seed is None or seed < 0 else seed
    if a.backend in ("ollama", "auto"):
        from .llm import JUDGING

        kw = {"base_url": a.url, "num_ctx": _context(a, kinds, ws),
              "think": None if a.think is None else a.think in ("on", "judging"),
              "think_kinds": JUDGING if a.think == "judging" else None,
              "think_budget": a.think_budget if a.think != "off" else 0, "seed": seed}
    elif a.backend == "local":
        kw = {"base_url": a.url, "seed": seed} if a.url else {"seed": seed}
    be = get_backend(a.backend, **kw)
    if a.backend == "auto":
        print(f"Using {getattr(be, 'base_url', '')} ({be.name}).", file=sys.stderr)
    if getattr(be, "name", "") in ("ollama", "local") and sys.stderr.isatty():
        from .gui.progress import model_line

        def show(info):  # one line, redrawn in place, while the model works
            line = f"[{info['task']}] {model_line(info)}"
            sys.stderr.write("\r" + line[:150].ljust(150) + ("\n" if info["phase"] == "done" else ""))
            sys.stderr.flush()
        be.progress = show
    return be


def _model(a, be, ws=None, fallback_key: str = "verify") -> str | None:
    """The model to use: --model, else for the Claude API the workspace's configured model, else (local servers) the
    first chat model the server offers. Model ids stored on tasks name Claude models, which a local server lacks."""
    if getattr(a, "model", None):
        return a.model
    name = getattr(be, "name", "")
    if name == "anthropic":
        return ws.config["models"][fallback_key] if ws is not None else "claude-opus-5-5"
    if name == "baseline":
        return "baseline"
    from .home import best_model

    model = best_model(be) if hasattr(be, "models") else ""  # one already in memory first, then the newest
    if not model:
        raise BackendError("The local server offers no chat model. Pull or load one, or name it with --model.")
    print(f"Model: {model} (choose another with --model)", file=sys.stderr)
    return model


def _embedder(a):
    if not getattr(a, "embed_model", None):
        return None
    from .embed import make_embedder

    kind = "ollama" if a.backend in ("ollama", "auto") and not (a.embed_url or "").rstrip("/").endswith("/v1") else "openai"
    return make_embedder(kind, a.embed_model, a.embed_url or a.url)


def _print_progress(step, msg, info=None):
    part = f"[part {info['part']}/{info['parts']}] " if info and isinstance(info.get("parts"), int) and info.get("part") else ""
    print(f"{part}{msg} ...", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except BackendError as e:
        print(f"Problem: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"Problem: {e}", file=sys.stderr)
        return 1


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="enlens", description="Check hypotheses against your own documents, locally "
                                 "(and the SDG / value chain assessment pipeline).")
    ap.add_argument("--ws", default="workspace", help="workspace folder (default: ./workspace)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create the workspace folder and database")
    p = sub.add_parser("export-project", help="write the whole project (database, uploads, original files) to one zip")
    p.add_argument("zip")
    p = sub.add_parser("import-project", help="unpack a project zip into the folder given by --ws (new or empty)")
    p.add_argument("zip")
    p = sub.add_parser("load-vca", help="load the VCA supplementary workbook as gold labels")
    p.add_argument("xlsx")
    p = sub.add_parser("ingest", help="add PDFs, HTML or text files (folders and zips are searched)")
    p.add_argument("inputs", nargs="+")
    p.add_argument("--exclude", action="append", default=[], metavar="PATTERN",
                   help="leave out files whose name matches this pattern, e.g. 'A_18_*' (repeatable)")
    p.add_argument("--ocr", choices=["auto", "off"], default="auto",
                   help="scanned PDF pages: recognise their text when OCR is installed (auto, the default) or not")
    p.add_argument("--ocr-lang", default="eng", help="Tesseract languages for OCR, e.g. eng+nld (default eng)")
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

    def backend_args(p, default="auto"):
        p.add_argument("--backend", default=default, choices=["auto", "ollama", "local", "anthropic", "baseline"],
                       # (Claude Code answers through the queue: enlens prepare, then /enlens-run in Claude Code)
                       help="auto = the first local server running (Ollama, LM Studio, llama.cpp...; the default); "
                            "ollama = a model in Ollama; local = an OpenAI-compatible server on this computer; "
                            "anthropic = the Claude API (cloud: the text read is sent to Anthropic); "
                            "baseline = offline keyword demo")
        p.add_argument("--url", help="ollama: server address (default http://localhost:11434); local: OpenAI-compatible "
                                     "base URL (e.g. http://localhost:1234/v1 for LM Studio)")
        p.add_argument("--num-ctx", default="auto",
                       help="ollama: context length in tokens, or auto (the default): the smallest of 8192, 12288, "
                            "16384 and 32768 that fits the largest task, which leaves the most memory to the model")
        p.add_argument("--think", choices=["on", "off", "judging"],
                       help="ollama: a reasoning model's thinking on or off, or judging: only when it judges excerpts")
        p.add_argument("--think-budget", type=int, default=1500,
                       help="ollama: reasoning tokens before the model is asked to answer at once (default 1500; 0: no "
                            "limit)")
        p.add_argument("--model-seed", type=int, default=42,
                       help="seed sent with every request, so the same input gives the same answer (default 42; -1: none)")

    p = sub.add_parser("run", help="answer pending tasks with a backend")
    p.add_argument("kind", choices=list(tasks.KINDS))
    backend_args(p)
    p.add_argument("--model", help="override the model id stored on the tasks")
    p.add_argument("--limit", type=int)

    def check_args(p):
        p.add_argument("--framework", help="codebook of --code: sdg (default with a code) or a project framework")
        p.add_argument("--code", "--target", dest="code", help="framework code the hypothesis is about, e.g. 6.4")
        p.add_argument("--decompose", action="store_true", help="split the hypothesis into claims that must all hold")
        p.add_argument("--k", type=int, default=8, help="passages to read per claim (default 8)")
        p.add_argument("--per-doc", type=int, default=2, help="at most this many passages from one document first")
        p.add_argument("--no-expand", action="store_true", help="skip the model call that writes search terms")
        p.add_argument("--model", help="model id (default: the first chat model of the local server; for the Claude "
                                       "API models.verify in config.json)")
        p.add_argument("--embed-model", help="semantic search with this embedding model (after `enlens embed`)")
        p.add_argument("--embed-url", help="address of the embedding server (default: --url)")
        p.add_argument("--threshold", type=float, help="confidence from which grades count (default from config)")
        backend_args(p)

    for name, text in (("check", "check one claim or hypothesis against the documents in the workspace"),
                       ("hypothesis", "the same as check")):
        p = sub.add_parser(name, help=text)
        p.add_argument("claim")
        check_args(p)
    p = sub.add_parser("batch", help="check many hypotheses: a text file (one per line) or a CSV with a hypothesis column")
    p.add_argument("file")
    p.add_argument("--out", help="write one row per graded passage to this CSV")
    check_args(p)
    p = sub.add_parser("history", help="hypotheses checked in this workspace, newest first")
    p.add_argument("--threshold", type=float)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--csv", help="write every check (one row per graded passage) to this CSV instead")
    p = sub.add_parser("embed", help="build the semantic index: embed every passage with a local embedding model")
    p.add_argument("--embed-model", required=True, help="e.g. nomic-embed-text, bge-m3 (multilingual), mxbai-embed-large")
    p.add_argument("--embed-url", help="embedding server (default: Ollama at http://localhost:11434; an address ending in "
                                       "/v1 is an OpenAI-compatible server)")
    p.add_argument("--batch-size", type=int, default=32)
    sub.add_parser("detect", help="list the local model servers running on this computer and their models")
    sub.add_parser("frameworks", help="list the frameworks (codebooks) this workspace can use")

    p = sub.add_parser("benchmark", help="score a model on tasks the workspace already answered (nothing is stored)")
    p.add_argument("--model", required=True)
    p.add_argument("--sample", type=int, default=30, help="tasks per kind (default 30)")
    p.add_argument("--kinds", nargs="+", default=["verify_set", "extract"],
                   choices=["verify_set", "extract", "split", "label"])
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", help="write the full result as JSON here")
    backend_args(p)

    p = sub.add_parser("backend-check", help="test the connection to a backend and whether a model is available")
    p.add_argument("--model")
    p.add_argument("--repeatable", action="store_true",
                   help="also ask one short question twice: the same answer twice means repeatable with a fixed seed")
    backend_args(p)

    # 0.7: search, profiles, concepts, themes, references, highlighted PDFs, FlexiConc
    p = sub.add_parser("search", help="every place words occur in the documents, one line per hit (a concordance)")
    p.add_argument("query", help='words, or a phrase in quotes: "electrolyser imports"')
    p.add_argument("--mode", choices=["any", "all", "phrase", "near"], default="any")
    p.add_argument("--near", type=int, default=5, help="near: within this many words (default 5)")
    p.add_argument("--exact", action="store_true", help="match words exactly (no stemming: prices finds prices only)")
    p.add_argument("--all-sections", action="store_true", help="also search reference lists and front matter")
    p.add_argument("--docs", nargs="*", help="only these document ids")
    p.add_argument("--code", help="only passages labelled with this code (framework:code, e.g. sdg:6.4)")
    p.add_argument("--sort", choices=["doc", "left", "right"], default="doc")
    p.add_argument("--limit", type=int, default=50, help="lines to print (the CSV gets all)")
    p.add_argument("--out", help="write every line to this CSV")
    p.add_argument("--collocates", action="store_true", help="also list the words that occur near the hits")
    p = sub.add_parser("profile", help="a codebook profile: which codes each document addresses, how much and where")
    p.add_argument("--framework", default="sdg", help="codebook: sdg (169 targets, default), sdg_goals, or a project CSV")
    p.add_argument("--docs", nargs="*", help="only these document ids")
    p.add_argument("--keywords-only", action="store_true", help="only the keyword-and-meaning pass (no model)")
    p.add_argument("--all-passages", action="store_true", help="the model reads every passage, not only those with a "
                                                               "candidate code")
    p.add_argument("--limit", type=int, help="the model reads at most this many passages (it resumes later)")
    p.add_argument("--level", choices=["code", "group"], default="code", help="group: add codes up by goal")
    p.add_argument("--embed-model", help="also find codes by meaning with this embedding model")
    p.add_argument("--embed-url")
    p.add_argument("--model", help="model id for the model pass")
    p.add_argument("--out", help="write the profile (grid, labels, key terms, how it was made) to this .xlsx")
    backend_args(p)
    p = sub.add_parser("terms", help="the glossary of the corpus (built when needed)")
    p.add_argument("--q", help="only terms containing these words")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--rebuild", action="store_true")
    p.add_argument("--embed-model", help="also propose terms that are possibly the same by meaning")
    p.add_argument("--embed-url")
    p.add_argument("--url", help=argparse.SUPPRESS)
    p.add_argument("--backend", default="ollama", help=argparse.SUPPRESS)
    p = sub.add_parser("concept", help="a concept's card: its wordings, documents, passages and related concepts")
    p.add_argument("name")
    p.add_argument("--lines", type=int, default=10)
    p.add_argument("--references", action="store_true", help="count resolved references (it, the plant) too")
    p = sub.add_parser("themes", help="group the passages into themes (by meaning with embeddings, else by words)")
    p.add_argument("--k", type=int, default=20, help="number of themes (5 to 60, default 20)")
    p.add_argument("--cluster-seed", type=int, default=0, help="the seed of the clustering (same seed, same themes)")
    p.add_argument("--mode", choices=["auto", "meaning", "words"], default="auto")
    p.add_argument("--embed-model")
    p.add_argument("--framework", help="add a theme × code grid from this codebook's profile")
    p.add_argument("--name-with-model", action="store_true", help="let the model name the themes (quotes checked)")
    p.add_argument("--model")
    p.add_argument("--out", help="write the themes to this .xlsx")
    backend_args(p)
    p = sub.add_parser("resolve", help="follow references in a document (it, the plant…) with the model")
    p.add_argument("doc", help="document id")
    p.add_argument("--name", help="only the passages where this name occurs")
    p.add_argument("--model")
    backend_args(p)
    p = sub.add_parser("annotate", help="a copy of a document's PDF with ENLENS's quotes highlighted")
    p.add_argument("doc", help="document id")
    p.add_argument("--hyp", nargs="*", help="only the judgements of these hypotheses")
    p.add_argument("--layers", nargs="*", default=["judgements"],
                   choices=["judgements", "labels", "concepts", "references"])
    p.add_argument("--framework", default="sdg")
    p.add_argument("--concept", help="term id of a concept to highlight (layer concepts)")
    p.add_argument("--no-pdfminer", action="store_true", help="line boxes from pypdf only")
    p.add_argument("--out", required=True)
    p = sub.add_parser("export-flexiconc", help="write the project in the Cross-Doc SDG Explorer's FlexiConc SQLite layout")
    p.add_argument("out")
    p.add_argument("--framework", default="sdg")
    p.add_argument("--embed-model")
    p.add_argument("--theme-run")
    p.add_argument("--no-embeddings", action="store_true")
    p = sub.add_parser("acceptance", help="the 0.7 acceptance measures on a reference workspace (see the manual)")
    p.add_argument("what", choices=["samples", "measure", "search", "queue", "score"],
                   help="samples: write the sheets a person fills in once; measure: score the filled sheets; "
                        "search: the automatic search measure; queue (0.8): a run of one kind and model through "
                        "the queue, on a copy; score (0.8): score every run, write MODEL_CHOICE.md")
    p.add_argument("--kind", choices=["label", "link", "theme", "resolve", "check"], help="queue: the kind of task")
    p.add_argument("--model", help="queue: haiku, sonnet, opus, fable (Claude Code) or local:<model name>")
    p.add_argument("--again", action="store_true", help="queue: the same tasks a second time (repeatability)")
    p.add_argument("--apply", action="store_true", help="score: make the chosen models this installation's defaults")
    p.add_argument("--folder", default="acceptance", help="where the sample sheets are (default ./acceptance)")
    p.add_argument("--queries", nargs="*", help="search: the queries (default: 20 frequent words of the corpus)")

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

    # 0.8: the task queue for Claude Code, and the plugin's set-up
    p = sub.add_parser("prepare", help="prepare tasks in the queue for Claude Code (/enlens-run), without answering them")
    p.add_argument("kind", choices=["label", "link", "theme", "resolve", "check", *tasks.SDG_PREPARE],
                   help="the kinds of the app, or the SDG pack's (split, extract, verify-vca, verify-claims, audit-vca)")
    p.add_argument("text", nargs="?", help="check: the hypothesis (or use --file); resolve: the document id")
    p.add_argument("--file", help="check: a text file (one hypothesis per line) or a CSV with a hypothesis column")
    p.add_argument("--framework", default=None, help="label: the codebook (default sdg)")
    p.add_argument("--docs", nargs="*", help="label: only these document ids")
    p.add_argument("--all-passages", action="store_true", help="label: every passage, not only those with a candidate")
    p.add_argument("--all-documents", action="store_true", help="resolve: every document")
    p.add_argument("--name", help="resolve: only the passages where this name occurs")
    p.add_argument("--run", help="theme: the set of themes to name (default: the latest)")
    p.add_argument("--limit", type=int, help="label, link: at most this many tasks")
    p.add_argument("--decompose", action="store_true", help="check: split the hypothesis into parts first")
    p.add_argument("--no-expand", action="store_true", help="check: no extra search words")
    p.add_argument("--k", type=int, default=None, help="check: passages per claim (default 8); verify-vca: passages "
                                                        "per VCA claim (default thresholds.verify_top_k)")
    p.add_argument("--per-doc", type=int, default=2)
    # the SDG pack (0.8.1): the options of make-tasks
    p.add_argument("--model", help="SDG pack: haiku, sonnet, opus or fable instead of the routed model (kept for "
                                   "these tasks); audit-vca, verify-claims: the second model (default: the auditor)")
    p.add_argument("--per-target", type=int, help="extract: only the top N passages for each of the 169 SDG targets")
    p.add_argument("--any-passage", action="store_true",
                   help="extract --per-target: also rank passages that do not name hydrogen or a derivative")
    p.add_argument("--pairwise", action="store_true", help="verify-vca: one task per claim and passage")
    p.add_argument("--beyond-cited", action="store_true", help="verify-vca: search all documents, not only cited ones")
    p.add_argument("--sample", type=float, help="verify-claims (default 1.0), audit-vca (default 0.1): fraction to check")
    p = sub.add_parser("queue", help="the task queue: what waits for Claude Code; answer it here; order, hold, remove")
    p.add_argument("action", choices=["status", "run", "first", "hold", "go", "reset", "withdraw"],
                   help="status (default); run: answer it here with --backend; first/hold/go/withdraw a kind")
    p.add_argument("kind", nargs="?", help="the kind of task (label, link, theme, expand, decompose, resolve, check, "
                                           "reread, second; the SDG pack: split, extract, verify, verify_set)")
    p.add_argument("--no-routing", action="store_true", help="run: one model for every kind (--model)")
    p.add_argument("--model", help="run: the model (default: the model of each kind, see Settings)")
    p.add_argument("--limit", type=int)
    backend_args(p)
    p = sub.add_parser("claude-setup", help="prepare the ENLENS plugin for Claude Code and print the lines that add it")
    p.add_argument("--no-check", action="store_true", help="do not start the connector to check it")
    p = sub.add_parser("update", help="fetch the newest ENLENS from GitHub into this copy (no new venv, data untouched)")
    p.add_argument("--check", action="store_true", help="only say whether a newer version is waiting")

    a = ap.parse_args(argv)
    if a.cmd == "update":
        from . import update

        try:
            out = update.update(check_only=a.check)
        except update.UpdateError as e:
            print(f"Problem: {e}", file=sys.stderr)
            return 1
        print(out["message"])
        return 0
    if a.cmd == "claude-setup":
        return _claude_setup(a)
    if a.cmd == "detect":
        from .llm import detect_local

        found = detect_local()
        _print({"servers": found} if found else {"servers": [], "hint": "Start Ollama (ollama.com) or LM Studio "
                                                                         "(lmstudio.ai); then run this again."})
        return 0
    if a.cmd == "backend-check":
        try:
            be = _backend(a)
            out = be.check(a.model)
            if a.repeatable:
                from .llm import repeatable

                out["repeatable"] = repeatable(be, a.model or _model(a, be))
            _print(out)
        except BackendError as e:
            print(f"Problem: {e}")
            return 1
        return 0
    if a.cmd == "init":
        ws = Workspace.create(a.ws)
        print(f"Workspace ready at {ws.root.resolve()}")
        return 0
    if a.cmd == "import-project":
        from . import bundle

        try:
            ws = bundle.import_project(a.zip, a.ws)
        except ValueError as e:
            print(f"Problem: {e}", file=sys.stderr)
            return 1
        _print({"workspace": str(ws.root.resolve()), "documents": ws.scalar("SELECT COUNT(*) FROM documents"),
                "hypotheses": ws.scalar("SELECT COUNT(*) FROM hypotheses")})
        return 0
    ws = Workspace.open(a.ws)

    if a.cmd == "export-project":
        from . import bundle

        _print(bundle.export_project(ws, a.zip))
        return 0
    if a.cmd == "load-vca":
        _print(vca.load_into(ws, a.xlsx))
    elif a.cmd == "ingest":
        _print(ingest.ingest(ws, a.inputs, a.exclude, ocr=ingest.OcrOptions(a.ocr, a.ocr_lang)))
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
        be = _backend(a, (a.kind,), ws)
        model = a.model if (a.model or be.name == "anthropic") else _model(a, be, ws)
        _print(tasks.run(ws, a.kind, be, a.limit, model))
    elif a.cmd in ("check", "hypothesis"):
        from . import claimcheck

        be = _backend(a)
        hid = claimcheck.check_hypothesis(ws, a.claim, be, _model(a, be, ws), framework=a.framework or None,
                                          code=a.code, k=a.k, per_doc=a.per_doc, expand=not a.no_expand,
                                          decompose=a.decompose, progress=_print_progress, embedder=_embedder(a))
        _print(_summary(claimcheck.hypothesis_result(ws, hid, a.threshold)))
    elif a.cmd == "batch":
        from . import claimcheck

        items = claimcheck.parse_batch(Path(a.file).read_text(encoding="utf-8-sig"))
        if a.code:
            items = [{**i, "code": i.get("code") or a.code, "framework": i.get("framework") or a.framework or "sdg"}
                     for i in items]
        be = _backend(a)
        res = claimcheck.check_batch(ws, items, be, _model(a, be, ws), embedder=_embedder(a), k=a.k, per_doc=a.per_doc,
                                     expand=not a.no_expand, decompose=a.decompose,
                                     progress=lambda s, m, info=None: print(m, "...", file=sys.stderr) if s == "item" else None)
        rows = [claimcheck.hypothesis_result(ws, h, a.threshold) for h in res["checked"]]
        if a.out:
            out_rows = [r for res_h in rows for r in claimcheck.hypothesis_rows(res_h)]
            _write_csv(a.out, out_rows)
        _print({**res, "results": [{"hyp_id": r["hyp_id"], "status": r["status"], "hypothesis": r["text"]} for r in rows]})
        if res["stopped"]:
            return 1
    elif a.cmd == "history":
        from . import claimcheck

        if a.csv:
            _write_csv(a.csv, claimcheck.export_rows(ws, a.threshold))
            print(f"Written to {a.csv}")
        else:
            _print([{k: h[k] for k in ("hyp_id", "created_at", "status", "text", "code", "parts", "supports", "partly",
                                       "refutes", "passages_read", "model")} for h in claimcheck.history(ws, a.threshold,
                                                                                                         limit=a.limit)])
    elif a.cmd == "embed":
        from . import embed

        kind = "openai" if (a.embed_url or "").rstrip("/").endswith("/v1") else "ollama"
        emb = embed.make_embedder(kind, a.embed_model, a.embed_url)

        def prog(done, total):
            if sys.stderr.isatty():
                sys.stderr.write(f"\r{done:,} of {total:,} passages")
                sys.stderr.flush()
        res = embed.build(ws, emb, batch=a.batch_size, progress=prog)
        if sys.stderr.isatty():
            sys.stderr.write("\n")
        _print(res)
    elif a.cmd == "frameworks":
        from . import frameworks

        _print([fw.info() for fw in frameworks.available(ws).values()])
    elif a.cmd == "benchmark":
        from . import benchmark

        be = _backend(a, tuple(a.kinds))
        res = benchmark.run(ws, be, a.model, kinds=a.kinds, sample=a.sample, seed=a.seed,
                            progress=lambda i, n, tid: print(f"[{i}/{n}] {tid}", file=sys.stderr))
        if a.out:
            Path(a.out).write_text(json.dumps(res, indent=2, ensure_ascii=False))
        try:
            from .home import record_benchmark

            record_benchmark(a.model, res["kinds"])
        except OSError:
            pass
        _print({"model": res["model"], "reference": res["reference"], "kinds": res["kinds"],
                "verdict": benchmark.verdict(res)})
    elif a.cmd == "export-tasks":
        if a.kind in tasks.CORPUS_KINDS:
            print(f"Note: {a.kind} tasks hold passages of your documents. Whoever answers these files (for example "
                  "Claude workers) reads those passages: they leave this computer.", file=sys.stderr)
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
    elif a.cmd in ("search", "profile", "terms", "concept", "themes", "resolve", "annotate", "export-flexiconc",
                   "acceptance"):
        return _cmd_07(a, ws)
    elif a.cmd in ("prepare", "queue"):
        return _cmd_08(a, ws)
    elif a.cmd == "status":
        st = {r[0] + ":" + r[1]: r[2] for r in ws.query("SELECT kind, status, COUNT(*) FROM tasks GROUP BY kind, status")}
        cl = {r[0]: r[1] for r in ws.query("SELECT status, COUNT(*) FROM claims GROUP BY status")}
        _print({"tables": ws.counts(), "tasks": st, "claims": cl})
    return 0


def _cmd_07(a, ws) -> int:
    """The commands of 0.7."""
    if a.cmd == "search":
        from . import concordance

        res = concordance.search(ws, a.query, a.mode, a.docs, a.sort, 0, max(1, a.limit), a.exact, a.near,
                                 all_sections=a.all_sections, code=a.code)
        if a.out:
            rows = []
            for off in range(0, max(res["total"], 1), 1000):
                rows += concordance.table(concordance.search(ws, a.query, a.mode, a.docs, a.sort, off, 1000, a.exact,
                                                             a.near, all_sections=a.all_sections, code=a.code))
            _write_csv(a.out, rows)
            print(f"{len(rows)} lines written to {a.out}", file=sys.stderr)
        out = {k: res[k] for k in ("query", "mode", "words", "total", "passages", "documents", "per_doc")}
        out["lines"] = [f"{x['title'][:40]} ({x['location']}): {x['left']}[{x['node']}]{x['right']}" for x in res["lines"]]
        if a.collocates:
            col = concordance.collocates(ws, a.query, a.mode, a.docs, a.exact, a.near, a.all_sections, code=a.code)
            out["collocates"] = [f"{w['word']} ({w['count']}, PMI {w['pmi']})" for w in col["words"]]
        _print(out)
        return 0
    if a.cmd == "profile":
        from . import profile

        emb = _embedder(a)
        r1 = profile.keyword_pass(ws, a.framework, emb, a.docs)
        out: dict = {"keywords_and_meaning": r1}
        if not a.keywords_only:
            be = _backend(a, ("label",), ws)
            model = _model(a, be, ws)
            out["model_pass"] = profile.run_labels(ws, a.framework, be, model, a.docs, a.all_passages, a.limit,
                                                   progress=lambda i, n: print(f"[{i}/{n}]", file=sys.stderr))
        g = profile.grid(ws, a.framework, a.docs, a.level)
        out["documents"] = [{"title": d["title"], "codes": dict(sorted(g["cells"].get(d["doc_id"], {}).items(),
                                                                       key=lambda kv: -kv[1])[:10])} for d in g["documents"]]
        if a.out:
            from .runs import provenance_table
            from .terms import key_terms_table
            from .claimcheck import write_xlsx

            write_xlsx(profile.grid_table(g), a.out, "Documents by code",
                       extra=[("Labels", profile.labels_table(ws, a.framework, a.docs)),
                              ("Key terms per document", key_terms_table(ws)),
                              ("How these results were made", provenance_table(ws, kinds=("label",)))])
            out["written"] = a.out
        _print(out)
        return 0
    if a.cmd == "terms":
        from . import terms

        if a.rebuild:
            terms.build(ws, embedder=_embedder(a))
        else:
            terms.ensure(ws, embedder=_embedder(a))
        g = terms.glossary(ws, a.q, 0, a.limit)
        _print({"terms": g["terms"], "concepts": g["concepts"], "shown": [
            {"term_id": e["term_id"], "label": e["label"], "wordings": e["wordings"][:6], "documents": e["documents"],
             "mentions": e["mentions"]} for e in g["items"]]})
        return 0
    if a.cmd == "concept":
        from . import terms

        terms.ensure(ws)
        tid = terms.find_term(ws, a.name)
        if not tid:
            print(f"No term of the glossary matches {a.name!r}.", file=sys.stderr)
            return 1
        c = terms.card(ws, tid, 0, a.lines, with_references=a.references)
        _print({"concept": c["label"], "wordings": [w["label"] for w in c["wordings"]], "mentions": c["mentions"],
                "documents": [{"title": d["title"], "mentions": d["mentions"], "first": d.get("first_location")}
                              for d in c["documents"]],
                "related": [{"label": x["label"], "relation": x["relation"], "state": x["state"]}
                            for x in c["related"]["links"]],
                "mentioned_together": [f"{x['label']} ({x['together']} passages, lift {x['lift']})"
                                       for x in c["related"]["together"]],
                "lines": [f"{x['title'][:40]} ({x['location']}): {x['left']}[{x['node']}]{x['right']}" for x in c["lines"]]})
        return 0
    if a.cmd == "themes":
        from . import themes

        emb_model = a.embed_model
        rid = themes.run(ws, a.k, a.cluster_seed, a.mode, emb_model,
                         progress=lambda phase, d, n: print(f"{phase} ...", file=sys.stderr) if not d else None)
        if a.name_with_model:
            be = _backend(a, ("theme",), ws)
            themes.name_with_model(ws, rid, be, _model(a, be, ws))
        v = themes.view(ws, rid, a.framework)
        if a.out:
            from .claimcheck import write_xlsx

            sheets = themes.tables(ws, rid, a.framework)
            write_xlsx(sheets[0][1], a.out, sheets[0][0], extra=sheets[1:])
        _print({"run_id": rid, "mode": v["run"]["mode"], "passages": v["run"]["passages"],
                "themes": [{"theme": t["theme_id"], "name": t["name"], "passages": t["size"],
                            "documents": len(t["documents"]), "key_terms": t["terms"][:6]} for t in v["themes"]]})
        return 0
    if a.cmd == "resolve":
        from . import references

        be = _backend(a, ("resolve",), ws)
        r = references.resolve_document(ws, a.doc, be, _model(a, be, ws), a.name,
                                        progress=lambda i, n: print(f"[{i}/{n}]", file=sys.stderr))
        _print({**r, "chains": [{"name": c["name"], "mentions": [m["text"] for m in c["mentions"]]}
                                for c in references.chains(ws, a.doc)]})
        return 0
    if a.cmd == "annotate":
        from . import annotate

        r = annotate.annotate_document(ws, a.doc, a.hyp, tuple(a.layers), a.framework, a.concept,
                                       use_pdfminer=not a.no_pdfminer)
        Path(a.out).write_bytes(r["body"])
        _print({"written": a.out, "kind": r["content_type"], "quotes": r["marks"], "highlighted": r["placed"],
                "method": r["method"], "not_placed": r["missing"]})
        return 0
    if a.cmd == "export-flexiconc":
        from . import flexiconc_export

        _print(flexiconc_export.export(ws, a.out, a.framework, a.embed_model, a.theme_run, not a.no_embeddings))
        return 0
    if a.cmd == "acceptance":
        from . import acceptance

        if a.what in ("queue", "score"):
            from . import evaluation

            if a.what == "queue":
                if not a.kind or not a.model:
                    print("Problem: give --kind and --model.", file=sys.stderr)
                    return 1
                _print(evaluation.prepare(ws, a.folder, a.kind, a.model, a.again))
            else:
                r = evaluation.score(ws, a.folder, a.apply)
                _print({"runs": [{k: x.get(k) for k in ("kind", "model", "answered", "tasks", "score", "repeatability",
                                                         "seconds_per_task", "passes", "note")} for x in r["runs"]],
                        "chosen": r["chosen"], "report": str(Path(a.folder) / "MODEL_CHOICE.md"), "note": r["note"],
                        **({"applied": r["applied"]} if r.get("applied") else {})})
            return 0
        if a.what == "samples":
            _print(acceptance.make_samples(ws, a.folder))
        elif a.what == "measure":
            _print(acceptance.measure(ws, a.folder))
        else:
            _print(acceptance.search_measure(ws, a.queries))
        return 0
    return 1


def _project_name(ws) -> str:
    """The name Claude Code reaches this workspace by: a project of the data folder, linked if it is not one yet."""
    from . import home

    root = ws.root.resolve()
    for name in home.list_projects():
        if home.project_path(name).resolve() == root:
            return name
    name = home.link_existing(str(root))
    print(f"Linked this folder as the project {name!r}, so Claude Code can reach it.", file=sys.stderr)
    return name


def _cmd_08(a, ws) -> int:
    """The commands of 0.8: prepare tasks for Claude Code; the queue."""
    from . import claimcheck, home, profile, routing, taskqueue
    from . import tasks as tk

    if a.cmd == "prepare":
        if home.local_only():
            print("Problem: this installation keeps everything on this computer (local only): no tasks for Claude Code.",
                  file=sys.stderr)
            return 1
        r = routing.from_settings(home.load_settings(), route="claude_code")
        made: dict = {}
        with tk.queueing():
            if a.kind in tk.SDG_PREPARE:
                try:
                    made = tk.prepare_sdg(ws, a.kind, r, a.model, docs=a.docs, all_passages=a.all_passages,
                                          limit=a.limit, per_target=a.per_target, any_passage=a.any_passage, k=a.k,
                                          per_doc=a.per_doc, pairwise=a.pairwise, beyond_cited=a.beyond_cited,
                                          sample=a.sample)
                except ValueError as e:
                    print(f"Problem: {e}", file=sys.stderr)
                    return 1
            elif a.kind == "label":
                fw = a.framework or home.load_settings().get("profile_framework") or "sdg"
                profile.ensure_pass1(ws, fw)
                plan = profile.label_plan(ws, fw, a.docs, a.all_passages, a.limit)
                made["tasks"] = profile.make_label_tasks(ws, fw, plan["passage_ids"], r.model("label"), a.all_passages)
                with ws.connect() as cx:
                    made["queued"] = tk.mark_queued(cx, [f"label:{fw}:{p}" for p in plan["passage_ids"]])
            elif a.kind == "link":
                from . import terms

                terms.ensure(ws)
                pairs = terms.proposed_pairs(ws, a.limit or 200)
                made["tasks"] = len([terms.make_link_task(ws, x, y, r.model("link")) for x, y in pairs])
            elif a.kind == "theme":
                from . import themes

                run = a.run or (themes.runs(ws) or [{}])[0].get("run_id")
                if not run:
                    print("Problem: there is no set of themes yet: run `enlens themes` first.", file=sys.stderr)
                    return 1
                themes.make_name_tasks(ws, run, r.model("theme"))
                ids = [x[0] for x in ws.query("SELECT task_id FROM tasks WHERE kind='theme' AND substr(task_id, 1, ?) = ? "
                                              "AND status != 'done'", (len(f"theme:{run}:"), f"theme:{run}:"))]
                with ws.connect() as cx:
                    tk.mark_queued(cx, ids)
                made["tasks"] = len(ids)
            elif a.kind == "resolve":
                from . import references

                docs = [d[0] for d in ws.query("SELECT doc_id FROM documents ORDER BY doc_id")] if a.all_documents \
                    else [a.text] if a.text else []
                if not docs:
                    print("Problem: give a document id, or --all-documents.", file=sys.stderr)
                    return 1
                ids = [t for d in docs for t in references.make_tasks(ws, d, r.model("resolve"), a.name)]
                with ws.connect() as cx:
                    tk.mark_queued(cx, [t for t in ids if ws.scalar("SELECT status FROM tasks WHERE task_id=?", (t,))
                                        != "done"])
                made["tasks"] = len(ids)
            else:
                items = claimcheck.parse_batch(Path(a.file).read_text(encoding="utf-8")) if a.file else \
                    ([{"text": a.text}] if a.text else [])
                if not items:
                    print("Problem: give the hypothesis, or --file.", file=sys.stderr)
                    return 1
                batch = claimcheck._new_id("b") if len(items) > 1 else None
                made["checks"] = [claimcheck.queue_check(ws, it["text"], r, k=a.k or 8, per_doc=a.per_doc,
                                                         expand=not a.no_expand, decompose=a.decompose, batch_id=batch)
                                  for it in items]
        name = _project_name(ws)
        q = taskqueue.status(ws, name)
        _print({"prepared": made, "waiting": q["waiting"], "next": f"In Claude Code: {q['command']}",
                "privacy": q["privacy"]})
        return 0
    action = a.action
    if action in ("first", "hold", "go", "reset"):
        _print(taskqueue.set_order(ws, a.kind or "", action))
        return 0
    if action == "withdraw":
        if a.kind in ("decompose", "expand", "check"):
            for (hid,) in ws.query("SELECT hyp_id FROM hypotheses WHERE queue='waiting'"):
                claimcheck.delete_hypothesis(ws, hid)
        _print({"withdrawn": taskqueue.withdraw(ws, [a.kind] if a.kind else None)})
        return 0
    if action == "run":
        be = _backend(a, ("check", "expand", "decompose"), ws)
        model = _model(a, be, ws, "verify")
        if not a.no_routing and not a.model:
            be.router = routing.from_settings({**home.load_settings(), "backend": a.backend}, route=routing.route_of(
                be.name), large=model)
        res = taskqueue.run_here(ws, be, [a.kind] if a.kind else None, a.limit, model=model)
        _print(res)
        return 0
    _print(taskqueue.status(ws, _project_name(ws)))
    return 0


def _claude_setup(a) -> int:
    from . import claude_setup

    try:
        where = claude_setup.write_plugin()
    except ValueError as e:
        print(f"Problem: {e}", file=sys.stderr)
        return 1
    problems = claude_setup.check_files()
    if problems:
        print("Problem: the plugin's files are not as Claude Code expects:\n- " + "\n- ".join(problems), file=sys.stderr)
        return 1
    print(f"The ENLENS plugin for Claude Code is ready in {where}")
    if not a.no_check:
        r = claude_setup.check_connector()
        if not r["ok"]:
            print(f"Problem: {r.get('error') or 'the connector lacks ' + ', '.join(r.get('missing', []))}", file=sys.stderr)
            return 1
        print("The ENLENS connector starts and offers the queue tools.")
    print("\nAdd it to Claude Code (once) by typing these two lines in a terminal:\n")
    for line in claude_setup.commands():
        print("  " + line)
    print("\nThen restart Claude Code and type /enlens-run <project> in it. ENLENS writes nothing to Claude Code's own "
          "settings.")
    return 0


def _summary(r: dict) -> dict:
    from .claimcheck import STATUS_TEXT

    out = {"hyp_id": r["hyp_id"], "hypothesis": r["text"], "status": r["status"],
           "explanation": STATUS_TEXT.get(r["status"]), "status_any_confidence": r["status_any"],
           "balance": r["balance"], "parts": []}
    if r.get("code"):
        out["code"] = f"{r['code']}: {r.get('code_description', '')}"
    for p in r["parts"]:
        out["parts"].append({"claim": p["claim"], "status": p["status"], "rationale": p["rationale"],
                             "search_terms": p["terms"], "errors": p["errors"],
                             "graded": [{k: x[k] for k in ("verdict", "confidence", "quote", "title", "page", "found_by")}
                                        for x in p["passages"] if x["verdict"]],
                             "also_read": [{k: x[k] for k in ("title", "page")} for x in p["passages"] if not x["verdict"]]})
    if len(out["parts"]) == 1:  # one claim: flat, as in 0.4
        part = out.pop("parts")[0]
        out.update(claim_id=r["parts"][0]["claim_id"], rationale=part["rationale"], search_terms=part["search_terms"],
                   errors=part["errors"], graded=part["graded"], also_read=part["also_read"])
    return out


def _write_csv(path: str, rows: list[dict]) -> None:
    import csv

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
