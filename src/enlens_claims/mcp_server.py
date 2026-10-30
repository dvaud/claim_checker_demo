"""The ENLENS connector: lets Claude, in the Claude app or Claude Code, check claims and hypotheses against your own
documents.

Claude does the reading and grading, on your Claude plan. This program, running on your computer, does the rest:
it keeps the projects, picks the passages, checks every quote against the source text and keeps the history. It
uses the same projects folder as the browser app (`enlens-gui`), so checks made in either show up in both.

    enlens-mcp                          # run the connector (the Claude app starts it; you rarely run it yourself)
    enlens-mcp --print-config           # the settings block for the Claude desktop app
    enlens-mcp --install-claude-desktop # add that block to the desktop app's config file (a backup is kept)
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from . import __version__, claimcheck, frameworks, ingest
from . import home as core
from .sources import document_overview

INSTRUCTIONS = """ENLENS checks claims and hypotheses against the user's own documents (reports and papers kept in
local projects on this computer). Only the passages you are shown leave the computer.

How to check a claim:
1. Find the project: use the one the user names; if there are several and none is named, call list_projects and ask.
2. Write 5 to 15 search terms: the claim's key words, synonyms, technical terms, the outcome it concerns, and words
   a source would use to state the opposite. Then call start_check.
3. Read every passage returned. Grade only those that bear on the claim, following the rules returned with them.
   Quote the shortest span that shows the grade, copied exactly from that passage. Use no outside knowledge.
4. Call submit_grades. If it reports problems, fix exactly those and call it again.
5. Tell the user the status and give each quote with its document and page. Do not paste whole passages unless
   asked. If nothing was found, offer to read more passages (more_passages), or to search again with other wording
   (more_passages with new search_terms): sources often use other words than the claim. "contested" means some
   passages support the claim and others contradict it: report both sides.

A compound hypothesis ("X raises Y because Z", "A and B"): split it into the claims that must all hold, check each
with its own start_check, and combine: a part contradicted = contradicted (even if other parts are supported);
otherwise a part contested = contested; every part supported = supported; some parts (partly) supported = partially
supported; nothing found = unsupported.

Looking around first (no hypothesis needed): search_corpus lists every place words occur, one line per hit, with
the documents and pages; find_concept shows a concept's wordings, documents and related concepts; document_profile
says which codes (by default the 169 SDG targets) a document addresses, how much and where.

Adding sources: the user gives a path to a zip, a folder or files on this computer (attachments in the chat do not
reach this connector). Call create_project or add_sources with that path.

The task queue (0.8): work the ENLENS app prepared for Claude Code. In Claude Code the /enlens-run command of the ENLENS
plugin works through it with helper agents: queue_status says what waits (per kind, with the model and helper for
each); a helper takes a batch with next_tasks, answers every task as its instruction says, and sends the answers with
submit_answers (each quote is checked; problems come back to fix); release gives a batch back. Do not answer queued
tasks in a chat: the helpers each run on the model ENLENS names for that kind of task."""

server = None  # created in build_server(); module-level for `mcp dev`-style tooling


class Grade(BaseModel):
    passage: int = Field(ge=1, description="Passage number as shown (1 for P1)")
    verdict: Literal["supports", "partially_supports", "refutes"]
    confidence: float = Field(ge=0, le=1, description="Your probability that the grade is right")
    quote: str = Field(min_length=3, description="Shortest span of that passage that shows the grade, copied exactly")
    scope_note: str | None = Field(None, description="When the passage is about another group, setting, place or "
                                                     "period than the claim names, say so in a few words (then the "
                                                     "grade is at most partially_supports); otherwise null")
    refers_to: str | None = Field(None, description="When the quote depends on a word like 'it' or 'the plant', the "
                                                    "named form it refers to, copied exactly from the passage or from "
                                                    "the text shown before it; otherwise null")


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------
def _project(name: str | None):
    projects = core.list_projects()
    if not projects:
        raise ValueError("There are no projects yet. Create one with create_project and a path to the sources.")
    if not name:
        if len(projects) == 1:
            return projects[0], core.open_project(projects[0])
        raise ValueError(f"Several projects exist; say which one: {', '.join(projects)}")
    match = [p for p in projects if p.lower() == name.strip().lower()] or \
            [p for p in projects if name.strip().lower() in p.lower()]
    if len(match) != 1:
        raise ValueError(f"No single project matches {name!r}. Projects: {', '.join(projects)}")
    return match[0], core.open_project(match[0])


def _find_check(check_id: str):
    for name in core.list_projects():
        ws = core.open_project(name)
        if ws.scalar("SELECT 1 FROM user_claims WHERE claim_id=?", (check_id,)):
            return name, ws
    raise ValueError(f"No check {check_id!r} in any project.")


def _summary(ws, check_id: str) -> dict:
    r = claimcheck.result(ws, check_id)
    evidence = [{"grade": p["verdict"], "confidence": p["confidence"], "quote": p["quote"], "document": p["title"],
                 "page": p["page"], **({"about_another_group": p["scope_note"]} if p.get("scope_note") else {})}
                for p in r["passages"] if p["verdict"]]
    out = {"check_id": check_id, "claim": r["claim"], "status": r["status"],
           "status_text": claimcheck.STATUS_TEXT.get(r["status"], r["status"]),
           "status_at_any_confidence": r["status_any"], "confidence_threshold": r["threshold"],
           "passages_read": len(r["passages"]), "rounds": r["rounds"], "evidence": evidence,
           "summary": r["rationale"], "target": r["target"]}
    if r["status_any"] != r["status"]:
        low = sum(1 for e in evidence if (e["confidence"] or 0) < r["threshold"])
        out["note"] = (f"Counting every grade: {claimcheck.STATUS_TEXT.get(r['status_any'], r['status_any']).lower()}. "
                       f"{low} grade(s) fell below the confidence threshold of {r['threshold']:g}; mention them as weak evidence.")
    return out


def _find_claim(claim: str):
    """The project that handed out this batch."""
    for name in core.list_projects():
        ws = core.open_project(name)
        if ws.scalar("SELECT 1 FROM task_claims WHERE claim_id=?", (claim,)):
            return name, ws
    raise ValueError(f"No batch {claim!r} in any project. Take a new one with next_tasks.")


def _check_path(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.exists():
        raise ValueError(f"Nothing at {p}. Give the full path of a zip, a folder or a file on this computer.")
    return p


def _ingest(ws, path: str, exclude: list[str] | None) -> dict:
    p = _check_path(path)
    before = {d["doc_id"] for d in document_overview(ws)}
    stats = ingest.ingest(ws, [p], exclude=exclude or None)
    added = [d for d in document_overview(ws) if d["doc_id"] not in before]
    out = {"documents_added": len(added), "usable_documents_added": sum(1 for d in added if not d["check"]),
           "readable_passages_added": sum(d["passages"] for d in added), "already_in_project": stats["duplicates"],
           "without_text": stats["empty"]}
    warn = [{"title": d["title"], "warning": d["check"]} for d in added if d["check"]]
    if warn:
        out["warnings"] = warn
    if stats.get("excluded"):
        out["excluded"] = stats["excluded"]
    return out


# ---------------------------------------------------------------------------------------------
# the server
# ---------------------------------------------------------------------------------------------
def _friendly(fn):
    """Turn the problems a user or Claude can fix into tool errors whose message reaches Claude."""
    import functools

    from mcp.server.mcpserver.exceptions import ToolError

    from .llm import BackendError

    @functools.wraps(fn)
    def inner(*a, **kw):
        try:
            return fn(*a, **kw)
        except KeyError as e:
            raise ToolError(f"Not found: {e.args[0] if e.args else e}") from e
        except (ValueError, FileNotFoundError, BackendError) as e:
            raise ToolError(str(e)) from e
    return inner


def build_server():
    from mcp.server.mcpserver import MCPServer

    s = MCPServer("enlens", title="ENLENS hypothesis checker", instructions=INSTRUCTIONS, version=__version__)

    @s.tool(description="List the projects (sets of documents) with their number of documents and checks.")
    @_friendly
    def list_projects() -> dict:
        out = []
        for name in core.list_projects():
            ws = core.open_project(name)
            out.append({"project": name, "documents": ws.scalar("SELECT COUNT(*) FROM documents"),
                        "checks": ws.scalar("SELECT COUNT(*) FROM user_claims")})
        return {"projects": out, "folder": str(core.home() / "projects")}

    @s.tool(description="Create a project and read its sources from a path on this computer: a zip, a folder, or a "
                        "PDF/HTML/text file. A manifest.csv inside (columns file, reference, doi) names each work.")
    @_friendly
    def create_project(name: str, sources_path: str, exclude: Optional[list[str]] = None) -> dict:
        _check_path(sources_path)  # before creating: a mistyped path must not leave an empty project behind
        ws = core.create_project(name)
        return {"project": ws.root.name, **_ingest(ws, sources_path, exclude)}

    @s.tool(description="Add sources to an existing project from a path on this computer (zip, folder or file).")
    @_friendly
    def add_sources(project: str, sources_path: str, exclude: Optional[list[str]] = None) -> dict:
        name, ws = _project(project)
        return {"project": name, **_ingest(ws, sources_path, exclude)}

    @s.tool(description="Use an existing ENLENS workspace folder (for example the pilot) as a project, without copying it.")
    @_friendly
    def use_folder_as_project(path: str, name: Optional[str] = None) -> dict:
        return {"project": core.link_existing(path, name)}

    @s.tool(description="List a project's documents with pages, passages and warnings (unreadable or very short files).")
    @_friendly
    def list_documents(project: Optional[str] = None) -> dict:
        name, ws = _project(project)
        docs = document_overview(ws)
        return {"project": name, "documents": [{"id": d["doc_id"], "title": d["title"], "pages": d["pages"],
                                                 "passages": d["passages"], "warning": d["check"] or None} for d in docs]}

    @s.tool(description="Suggest codes of a framework (by default the 169 SDG targets) whose wording is close to a "
                        "claim (keyword match, a starting point only). list_frameworks shows the project's frameworks.")
    @_friendly
    def suggest_targets(claim: str, framework: str = "sdg", project: Optional[str] = None) -> dict:
        ws = _project(project)[1] if (project or framework != "sdg") else None
        return {"targets": [{"code": t["code"], "text": t["description"]}
                            for t in claimcheck.suggest_targets(claim, framework=framework, ws=ws)]}

    @s.tool(description="List the frameworks (codebooks such as the SDG targets) a project can tag claims with.")
    @_friendly
    def list_frameworks(project: Optional[str] = None) -> dict:
        name, ws = _project(project)
        return {"project": name, "frameworks": [fw.info() for fw in frameworks.available(ws).values()]}

    @s.tool(description="Start a check: picks the passages of the project that best match the claim and your search "
                        "terms, and returns them numbered, with the grading rules. Grade them with submit_grades.")
    @_friendly
    def start_check(claim: str, search_terms: list[str], project: Optional[str] = None, target: Optional[str] = None,
                    passages: int = 8, per_document: int = 2, document_ids: Optional[list[str]] = None,
                    framework: Optional[str] = None) -> dict:
        name, ws = _project(project)
        if target:
            frameworks.resolve(ws, framework or "sdg", target)  # a clear message for an unknown code
        r = claimcheck.open_check(ws, claim, terms=search_terms, target=target, k=max(1, min(int(passages), 15)),
                                  per_doc=max(1, int(per_document)), doc_ids=document_ids, framework=framework)
        out = {"project": name, **r}
        if not r["passages"]:
            out["note"] = "No passage shares words with the claim or the search terms. Try other terms."
        else:
            out["rules"] = claimcheck.chat_rules()
            out["next"] = "Read every passage, then call submit_grades with the check_id (an empty list if none bears on it)."
        return out

    @s.tool(description="Send your grades for the passages of the open round. Each quote is checked against its "
                        "passage; problems come back to fix. Returns the check's status and evidence when accepted.")
    @_friendly
    def submit_grades(check_id: str, grades: list[Grade], summary: str) -> dict:
        _, ws = _find_check(check_id)
        r = claimcheck.submit_grades(ws, check_id, [g.model_dump() for g in grades], summary)
        if not r["accepted"]:
            return {**r, "next": "Fix exactly these problems and call submit_grades again."}
        return {"accepted": True, **_summary(ws, check_id)}

    @s.tool(description="Read more passages for a check, none shown before, as a new round to grade. Give new "
                        "search_terms to search again with other wording; without them the next best passages for the "
                        "earlier terms come back.")
    @_friendly
    def more_passages(check_id: str, passages: int = 8, search_terms: Optional[list[str]] = None) -> dict:
        _, ws = _find_check(check_id)
        r = claimcheck.more_passages(ws, check_id, k=max(1, min(int(passages), 15)), terms=search_terms)
        if r["passages"]:
            r["rules"] = claimcheck.chat_rules()
            r["next"] = "Grade these with submit_grades; earlier grades are kept."
        else:
            r["note"] = "No further passages match."
        return r

    @s.tool(description="The current status and evidence of a check.")
    @_friendly
    def get_check(check_id: str) -> dict:
        _, ws = _find_check(check_id)
        return _summary(ws, check_id)

    @s.tool(description="Recent checks in a project, newest first, with their status.")
    @_friendly
    def list_checks(project: Optional[str] = None, limit: int = 20) -> dict:
        name, ws = _project(project)
        rows = claimcheck.history(ws)[: max(1, int(limit))]
        return {"project": name, "checks": [{"check_id": h["claim_id"], "checked_at": h["created_at"], "claim": h["claim"],
                                              "status": h["status"],
                                              "status_text": claimcheck.STATUS_TEXT.get(h["status"], h["status"]),
                                              "passages_read": h["passages_read"], "graded_by": h["model"]} for h in rows]}

    @s.tool(description="Search the project's documents for words or a phrase (in quotes) and list every place they "
                        "occur, one line per hit with the words around it, the document and the page. Modes: any (any "
                        "word), all (all words in one passage), phrase, near (within `near` words). Counts per document "
                        "come first. Use it to look around before proposing or checking a hypothesis.")
    @_friendly
    def search_corpus(query: str, project: Optional[str] = None, mode: str = "any", near: int = 5,
                      exact: bool = False, lines: int = 30, offset: int = 0,
                      document_ids: Optional[list[str]] = None) -> dict:
        from . import concordance

        name, ws = _project(project)
        r = concordance.search(ws, query, mode, document_ids, "doc", max(0, int(offset)), max(1, min(int(lines), 200)),
                               exact, near)
        return {"project": name, "query": query, "hits": r["total"], "passages": r["passages"],
                "documents": [{"document": d["title"], "hits": d["hits"]} for d in r["per_doc"][:30]],
                "lines": [{"document": x["title"], "where": x["location"], "text": f"{x['left']}[{x['node']}]{x['right']}",
                           "passage_id": x["passage_id"]} for x in r["lines"]],
                "more": max(0, r["total"] - offset - len(r["lines"]))}

    @s.tool(description="Which codes of a codebook (by default the 169 SDG targets; sdg_goals for the 17 goals) a "
                        "document addresses, how much (passages, share of the document) and where (pages), each label "
                        "with its quote and reason. Labels by keywords and meaning are provisional until the model pass "
                        "has read the passages (in the app).")
    @_friendly
    def document_profile(document_id: str, project: Optional[str] = None, framework: str = "sdg",
                         codes: int = 15) -> dict:
        from . import profile

        name, ws = _project(project)
        profile.ensure_pass1(ws, framework)
        d = profile.doc_profile(ws, framework, document_id)
        return {"project": name, "document": d["title"], "codebook": d["framework_title"],
                "read_by_the_model": d["read_by_model"], "passages": d["passages"],
                "codes": [{"code": c["code"], "text": c["description"], "passages": c["passages"],
                           "share": c["share"], "pages": c["pages"][:20],
                           "examples": [{"quote": i["quote"], "reason": i["reason"], "where": i["location"],
                                         "by": i["source"], "provisional": i["provisional"]} for i in c["items"][:3]]}
                          for c in d["codes"][:max(1, int(codes))]]}

    @s.tool(description="A concept of the project's glossary (for example 'PEM electrolysis'): the wordings it goes by, "
                        "the documents that discuss it with counts and the first page, passages where it occurs, and "
                        "related concepts (the same, broader, narrower, or often mentioned together).")
    @_friendly
    def find_concept(name: str, project: Optional[str] = None, lines: int = 10) -> dict:
        from . import terms

        pname, ws = _project(project)
        terms.ensure(ws)
        tid = terms.find_term(ws, name)
        if not tid:
            raise ValueError(f"No term of the glossary matches {name!r}. Try a shorter wording.")
        c = terms.card(ws, tid, 0, max(1, min(int(lines), 50)))
        return {"project": pname, "concept": c["label"], "wordings": [w["label"] for w in c["wordings"]],
                "mentions": c["mentions"],
                "documents": [{"document": d["title"], "mentions": d["mentions"], "first": d.get("first_location")}
                              for d in c["documents"][:30]],
                "lines": [{"document": x["title"], "where": x["location"], "text": f"{x['left']}[{x['node']}]{x['right']}"}
                          for x in c["lines"]],
                "related": [{"concept": x["label"], "relation": x["relation"], "state": x["state"]}
                            for x in c["related"]["links"]],
                "mentioned_together": [{"concept": x["label"], "passages": x["together"], "lift": x["lift"]}
                                       for x in c["related"]["together"]]}

    # ---- 0.8: the task queue (Claude Code's /enlens-run) ------------------------------------------
    @s.tool(description="What waits in a project's task queue for Claude Code: per kind of task, how many wait, are "
                        "being answered, are done; the groups to hand to helpers (kind, model, helper); estimates. "
                        "Without a project: the projects that have work waiting.")
    @_friendly
    def queue_status(project: Optional[str] = None) -> dict:
        from . import taskqueue

        if not project:
            out = []
            for name in core.list_projects():
                ws = core.open_project(name)
                n = ws.scalar("SELECT COUNT(*) FROM tasks WHERE COALESCE(queued, 0)=1 AND (status IN ('pending', "
                              "'retry') OR (status='done' AND again=1))") or 0
                if n:
                    out.append({"project": name, "waiting": n})
            return {"projects_with_work": out, "local_only": core.local_only()}
        name, ws = _project(project)
        taskqueue.advance(ws)
        q = taskqueue.status(ws, name)
        return {k: q[k] for k in ("project", "groups", "kinds", "waiting", "being_answered", "paused", "held",
                                  "privacy", "local_only", "command", "claim_minutes")} | (
            {"paused_text": q["paused_text"]} if q.get("paused_text") else {})

    @s.tool(description="Take a batch of waiting tasks (a claim): tasks of one kind for one model (and helper, when "
                        "given), each with its prompt, and one system instruction for all of them. Answer every task "
                        "as the instruction says and send the answers with submit_answers. A batch not answered in 30 "
                        "minutes returns to the queue.")
    @_friendly
    def next_tasks(project: str, kind: Optional[str] = None, n: Optional[int] = None, model: Optional[str] = None,
                   taken_by: Optional[str] = None, helper: Optional[str] = None) -> dict:
        from . import taskqueue

        name, ws = _project(project)
        return {"project": name, **taskqueue.next_tasks(ws, kind, n, model, taken_by, helper)}

    @s.tool(description="Send the answers of a batch: answers = [{task_id, answer}], each answer the JSON object the "
                        "instruction asks for. Each one is checked (quotes against the text) and stored, or comes back "
                        "with its problems to fix and send again.")
    @_friendly
    def submit_answers(claim: str, answers: list[dict]) -> dict:
        from . import taskqueue

        _name, ws = _find_claim(claim)
        return taskqueue.submit(ws, claim, answers)

    @s.tool(description="Give a batch's unanswered tasks back to the queue now (for example when stopping early).")
    @_friendly
    def release(claim: str) -> dict:
        from . import taskqueue

        _name, ws = _find_claim(claim)
        return taskqueue.release(ws, claim)

    @s.prompt(title="Check a claim", description="Check a claim or hypothesis against the documents of a project")
    def check_claim(claim: str, project: str = "") -> str:
        where = f" in the project {project!r}" if project else ""
        return (f"Check this claim against my documents{where} with the ENLENS connector, following its instructions, "
                f"and report the status with the quotes and pages:\n\n{claim}")

    return s


# ---------------------------------------------------------------------------------------------
# command line: run, or set up the Claude desktop app
# ---------------------------------------------------------------------------------------------
def desktop_config_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if system == "Windows":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def config_block() -> dict:
    """Start the connector with this very Python, so the app uses the environment it was installed in."""
    return {"command": sys.executable, "args": ["-m", "enlens_claims.mcp_server"], "env": {"ENLENS_HOME": str(core.home())}}


def install_desktop(path: Path | None = None) -> Path:
    """Add (or update) the 'enlens' server in the desktop app's config; the previous file is kept as .bak."""
    path = path or desktop_config_path()
    data: dict = {}
    if path.exists():
        text = path.read_text(encoding="utf-8")
        data = json.loads(text) if text.strip() else {}
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    data.setdefault("mcpServers", {})["enlens"] = config_block()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def repair_desktop(path: Path | None = None) -> bool:
    """0.10: when the Claude desktop app's config starts ENLENS's connector with a Python that no longer exists (ENLENS
    was moved or installed again elsewhere) for this same data folder, point it at this Python. Returns whether it
    was changed. Any other entry, or a config that names another data folder, is left alone."""
    path = path or desktop_config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
        entry = data["mcpServers"]["enlens"]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    cmd = str(entry.get("command") or "")
    if cmd == sys.executable or (entry.get("env") or {}).get("ENLENS_HOME") != str(core.home()) or Path(cmd).exists():
        return False
    install_desktop(path)
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="enlens-mcp", description="The ENLENS connector for the Claude app and Claude Code.")
    ap.add_argument("--home", help="folder with projects and settings (default: ~/enlens, or ENLENS_HOME)")
    ap.add_argument("--print-config", action="store_true", help="print the block to add to claude_desktop_config.json")
    ap.add_argument("--install-claude-desktop", action="store_true",
                    help="add the connector to the Claude desktop app's config file (keeps a .bak copy)")
    a = ap.parse_args(argv)
    if a.home:
        os.environ["ENLENS_HOME"] = str(Path(a.home).expanduser().resolve())
    if a.print_config:
        b = config_block()
        print("Claude desktop app: add this to claude_desktop_config.json (or run enlens-mcp --install-claude-desktop)")
        print(json.dumps({"mcpServers": {"enlens": b}}, indent=2))
        print("\nClaude Code: run this once")
        print(f'claude mcp add enlens -e ENLENS_HOME="{b["env"]["ENLENS_HOME"]}" -- "{b["command"]}" ' + " ".join(b["args"]))
        return 0
    if a.install_claude_desktop:
        p = install_desktop()
        print(f"Added the ENLENS connector to {p}. Quit and reopen the Claude desktop app to load it.")
        return 0
    try:
        build_server().run("stdio")
    except ImportError:
        print("The connector needs the MCP package: pip install 'enlens-claims[connector]'", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
