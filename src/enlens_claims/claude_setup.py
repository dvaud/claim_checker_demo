"""Setting up the ENLENS plugin for Claude Code (0.8, G2): `enlens claude-setup`.

The plugin ships inside the ENLENS package (`claude_plugin/`). Set-up writes it, as a one-plugin marketplace, into
ENLENS's own data folder (`<ENLENS_HOME>/claude-plugin`), with the connector started by this very Python and this
data folder, then checks that the connector starts and offers the queue tools.

0.9 (subscription first): when the `claude` program is found, set-up also adds the plugin to Claude Code itself, by
running the same two commands a person would type (`claude plugin marketplace add …`, `claude plugin install …`);
otherwise it prints them. `status()` says what is ready (Claude Code found, signed in, the plugin added), and
`start_run()` starts Claude Code for one project's queue, in the background, when the researcher presses
"Start Claude Code" in the app (`claude -p "/enlens-run:enlens-run <project>"`, allowed only the ENLENS queue tools
and its helpers). ENLENS still never sees the Claude login: Claude Code uses its own.

Layout written:

    claude-plugin/.claude-plugin/marketplace.json         the marketplace "enlens"
    claude-plugin/plugins/enlens-run/.claude-plugin/plugin.json
    claude-plugin/plugins/enlens-run/SKILL.md            /enlens-run (the orchestrator)
    claude-plugin/plugins/enlens-run/agents/*.md         the seven helpers, each with its model and the queue tools only
    claude-plugin/plugins/enlens-run/.mcp.json           the ENLENS connector (enlens-mcp)
    claude-plugin/plugins/enlens-run/README.md
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import __version__
from . import home as core
from .store import now

PLUGIN = "enlens-run"        # the plugin's name: its root skill is /enlens-run
MARKETPLACE = "enlens"
SERVER = "enlens"            # the connector's name inside the plugin
# Claude Code names a plugin's MCP tools mcp__plugin_<plugin>_<server>__<tool>
TOOL_PREFIX = f"mcp__plugin_{PLUGIN}_{SERVER}__"
QUEUE_TOOLS = ("queue_status", "next_tasks", "submit_answers", "release")
HELPERS = ("enlens-labeller", "enlens-linker", "enlens-namer", "enlens-reader", "enlens-extractor", "enlens-checker",
           "enlens-auditor")
SOURCE = Path(__file__).with_name("claude_plugin")


def folder() -> Path:
    return core.home() / "claude-plugin"


def plugin_folder() -> Path:
    return folder() / "plugins" / PLUGIN


def commands(where: Path | None = None) -> list[str]:
    where = where or folder()
    return [f'claude plugin marketplace add "{where}"', f"claude plugin install {PLUGIN}@{MARKETPLACE}"]


def mcp_config() -> dict:
    return {"mcpServers": {SERVER: {"command": sys.executable, "args": ["-m", "enlens_claims.mcp_server"],
                                    "env": {"ENLENS_HOME": str(core.home())}}}}


def _fill(text: str) -> str:
    return text.replace("{{TOOL_PREFIX}}", TOOL_PREFIX).replace("{{VERSION}}", __version__)


def write_plugin(target: Path | None = None) -> Path:
    """Write the marketplace with the plugin (replacing an earlier copy). Returns the marketplace folder."""
    if core.local_only():
        raise ValueError("This installation keeps everything on this computer (local only): the Claude Code plugin is "
                         "not available here.")
    root = target or folder()
    plug = root / "plugins" / PLUGIN
    if plug.exists():
        shutil.rmtree(plug)
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (plug / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (plug / "agents").mkdir(parents=True, exist_ok=True)
    (root / ".claude-plugin" / "marketplace.json").write_text(_fill((SOURCE / "marketplace.json").read_text("utf-8")),
                                                               encoding="utf-8")
    (plug / ".claude-plugin" / "plugin.json").write_text(_fill((SOURCE / "plugin.json").read_text("utf-8")),
                                                          encoding="utf-8")
    for name in ("SKILL.md", "README.md"):
        (plug / name).write_text(_fill((SOURCE / name).read_text("utf-8")), encoding="utf-8")
    for f in sorted((SOURCE / "agents").glob("*.md")):
        (plug / "agents" / f.name).write_text(_fill(f.read_text("utf-8")), encoding="utf-8")
    (plug / ".mcp.json").write_text(json.dumps(mcp_config(), indent=2), encoding="utf-8")
    return root


def frontmatter(path: Path) -> dict:
    """The YAML front matter of a skill or agent file, read as `key: value` lines (all this plugin uses)."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    head = text[4:text.index("\n---", 4)]
    out = {}
    for line in head.splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def check_files(root: Path | None = None) -> list[str]:
    """Problems with the written plugin (empty when every file is as Claude Code expects)."""
    root = root or folder()
    plug = root / "plugins" / PLUGIN
    problems = []
    for p in (root / ".claude-plugin" / "marketplace.json", plug / ".claude-plugin" / "plugin.json", plug / ".mcp.json"):
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            problems.append(f"{p.name}: {e}")
    skill = frontmatter(plug / "SKILL.md") if (plug / "SKILL.md").exists() else {}
    if skill.get("name") != PLUGIN:
        problems.append("SKILL.md: the skill must be named enlens-run")
    allowed = set(TOOL_PREFIX + t for t in QUEUE_TOOLS)
    for h in HELPERS:
        f = plug / "agents" / f"{h}.md"
        if not f.exists():
            problems.append(f"agents/{h}.md is missing")
            continue
        fm = frontmatter(f)
        for key in ("name", "description", "model", "tools"):
            if not fm.get(key):
                problems.append(f"agents/{h}.md has no {key}")
        tools = {t.strip() for t in fm.get("tools", "").split(",") if t.strip()}
        if tools - allowed:
            problems.append(f"agents/{h}.md may use more than the ENLENS queue tools: {sorted(tools - allowed)}")
    return problems


def check_connector(timeout: float = 60) -> dict:
    """Start the connector as Claude Code will (this Python, `-m enlens_claims.mcp_server`) and list its tools."""
    import asyncio

    try:
        from mcp import Client, StdioServerParameters  # noqa: F401
    except ImportError:
        return {"ok": False, "error": "The connector needs the MCP package: pip install 'enlens-claims[connector]'"}
    cfg = mcp_config()["mcpServers"][SERVER]

    async def run():
        from mcp import Client, StdioServerParameters

        params = StdioServerParameters(command=cfg["command"], args=cfg["args"], env={**cfg["env"]})
        async with Client(params) as c:
            return sorted(t.name for t in (await c.list_tools()).tools)

    try:
        names = asyncio.run(asyncio.wait_for(run(), timeout))
    except Exception as e:  # noqa: BLE001 - report it plainly
        return {"ok": False, "error": f"The connector did not start: {type(e).__name__}: {e}"}
    missing = [t for t in QUEUE_TOOLS if t not in names]
    return {"ok": not missing, "tools": names, "missing": missing}


def setup_info() -> dict:
    """For the app: whether the plugin is written for this installation, and the lines to type."""
    plug = plugin_folder()
    ready = False
    try:
        cfg = json.loads((plug / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"][SERVER]
        ready = cfg.get("command") == sys.executable and (plug / "SKILL.md").exists()
    except (OSError, ValueError, KeyError):
        ready = False
    return {"folder": str(folder()), "ready": ready, "commands": commands(), "terminal": "enlens claude-setup",
            "in_claude_code": [f'/plugin marketplace add "{folder()}"', f"/plugin install {PLUGIN}@{MARKETPLACE}"],
            "local_only": core.local_only()}


# ---------------------------------------------------------------------------------------------
# 0.9: finding Claude Code, adding the plugin to it, and starting it for a project's queue
# ---------------------------------------------------------------------------------------------
SLASH = f"/{PLUGIN}:{PLUGIN}"   # how Claude Code names the plugin's skill (typing /enlens-run offers it)


def find_claude() -> str:
    """The `claude` program: ENLENS_CLAUDE, the PATH, or where its installers put it. "" when not found."""
    env = os.environ.get("ENLENS_CLAUDE", "").strip()
    if env:
        return env if Path(env).exists() else ""
    found = shutil.which("claude")
    if found:
        return found
    h = Path.home()
    for c in (h / ".claude" / "local" / "claude", h / ".local" / "bin" / "claude", Path("/opt/homebrew/bin/claude"),
              Path("/usr/local/bin/claude"), h / ".npm-global" / "bin" / "claude",
              h / "AppData" / "Roaming" / "npm" / "claude.cmd"):
        if c.exists():
            return str(c)
    return ""


def _cmd(path: str) -> list[str]:
    """How to call the program found: a Python script (the tests' and dev server's stand-in) runs with this Python."""
    return [sys.executable, path] if path.endswith(".py") else [path]


def _run(args: list[str], timeout: float = 60) -> tuple[int, str]:
    args = _cmd(args[0]) + list(args[1:])
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=str(core.home()),
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, f"{type(e).__name__}: {e}"
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


_STATUS: dict = {"at": 0.0, "value": None}


def status(refresh: bool = False) -> dict:
    """What is ready for Claude Code, for the app's set-up checklist (cached for half a minute):
    `found` (and `path`, `version`), `signed_in` (True, False, or None when Claude Code does not say), the plugin
    `written` for this installation and `installed` in Claude Code (None when that could not be read), and `ready`
    (found and installed: the app can start Claude Code)."""
    if not refresh and _STATUS["value"] is not None and time.time() - _STATUS["at"] < 30:
        return _STATUS["value"]
    info = setup_info()
    out = {"found": False, "path": "", "version": "", "signed_in": None, "written": info["ready"], "installed": None,
           "plugin_version": "", "ready": False, "local_only": core.local_only()}
    path = "" if out["local_only"] else find_claude()
    if path:
        out.update(found=True, path=path)
        code, text = _run([path, "--version"], timeout=20)
        if code == 0:
            out["version"] = text.splitlines()[0].strip() if text else ""
        code, text = _run([path, "auth", "status"], timeout=20)
        try:
            out["signed_in"] = bool(json.loads(text[text.index("{"):]).get("loggedIn"))
        except (ValueError, AttributeError):
            out["signed_in"] = None
        code, text = _run([path, "plugin", "list", "--json"], timeout=30)
        try:
            plugins = json.loads(text[text.index("["):])
            mine = [p for p in plugins if p.get("id") == f"{PLUGIN}@{MARKETPLACE}"]
            out["installed"] = bool(mine and mine[0].get("enabled", True))
            out["plugin_version"] = (mine[0].get("folderVersion") or mine[0].get("version") or "") if mine else ""
        except (ValueError, AttributeError):
            out["installed"] = None
    out["ready"] = bool(out["found"] and out["written"] and out["installed"] is not False)
    _STATUS.update(at=time.time(), value=out)
    return out


def install(check: bool = False) -> dict:
    """Prepare the plugin and, when Claude Code is found, add it to Claude Code (the two commands of `commands()`).
    Returns {"steps": [{"step", "ok", "text"}], "status": status(), "commands": [...]}; never raises for Claude Code's
    own problems (they are reported in the steps)."""
    steps = []
    root = write_plugin()
    problems = check_files(root)
    steps.append({"step": "Prepare the ENLENS plugin", "ok": not problems,
                  "text": "; ".join(problems) or f"Written to {root}"})
    if check:
        r = check_connector()
        steps.append({"step": "Start the ENLENS connector", "ok": r["ok"],
                      "text": r.get("error") or ("Offers the queue tools." if r["ok"] else
                                                 "Missing: " + ", ".join(r.get("missing", [])))})
    path = find_claude()
    if not path:
        steps.append({"step": "Add the plugin to Claude Code", "ok": False,
                      "text": "Claude Code was not found on this computer. Install it from claude.com/claude-code, "
                              "then press Set up again (or type the two lines below in a terminal)."})
    else:
        for line, args in zip(commands(root), ([path, "plugin", "marketplace", "add", str(root)],
                                               [path, "plugin", "install", f"{PLUGIN}@{MARKETPLACE}"])):
            code, text = _run(args, timeout=120)
            steps.append({"step": line, "ok": code == 0, "text": re.sub(r"\x1b\[[0-9;]*m", "", text)[-600:]})
            if code != 0:
                break
    _STATUS["value"] = None
    return {"steps": steps, "status": status(refresh=True), "commands": commands(root)}


# -- starting Claude Code for one project's queue (the "Start Claude Code" button) ------------------------
_RUNS: dict[str, dict] = {}
_RUNS_LOCK = threading.Lock()


def run_args(project: str, claude: str = "") -> list[str]:
    """The command that answers one project's queue headless, allowed only the ENLENS queue tools and the helpers."""
    tools = ["Agent"] + [TOOL_PREFIX + t for t in QUEUE_TOOLS]
    quoted = '"' + project.replace('"', "") + '"'
    return _cmd(claude or find_claude() or "claude") + ["-p", f"{SLASH} {quoted}", "--output-format", "text",
                                                       "--allowedTools", *tools]


def _log_path(project: str) -> Path:
    d = core.home() / "claude-runs"
    d.mkdir(parents=True, exist_ok=True)
    return d / ((re.sub(r"[^A-Za-z0-9_-]+", "_", project).strip("_") or "project") + ".log")


def run_state(project: str) -> dict:
    """Whether Claude Code, started from the app, is working on this project's queue; the end of its report."""
    with _RUNS_LOCK:
        r = _RUNS.get(project)
    if not r:
        return {"running": False}
    code = r["proc"].poll()
    tail = ""
    try:
        tail = r["log"].read_text(encoding="utf-8", errors="replace")[-1200:].strip()
    except OSError:
        pass
    return {"running": code is None, "started_at": r["started_at"], "seconds": int(time.time() - r["t0"]),
            "exit_code": code, "report": tail if code is not None else "", "stopped": r.get("stopped", False)}


def start_run(project: str) -> dict:
    """Start Claude Code (headless, signed in with its own login) on the project's queue. One run per project."""
    if core.local_only():
        raise ValueError("Cloud models are switched off on this computer: Claude Code is not available.")
    st = run_state(project)
    if st.get("running"):
        return st
    path = find_claude()
    if not path:
        raise ValueError("Claude Code was not found on this computer. Install it (claude.com/claude-code), or type "
                         f"{SLASH.split(':')[0]} {project} in Claude Code yourself.")
    if not setup_info()["ready"] or status().get("installed") is False:
        install()  # the plugin is prepared and added on the first start: no separate set-up needed
    log = _log_path(project)
    fh = open(log, "w", encoding="utf-8")
    kwargs = {"start_new_session": True} if os.name != "nt" else {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    proc = subprocess.Popen(run_args(project, path), cwd=str(core.home()), stdout=fh, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, **kwargs)
    fh.close()
    with _RUNS_LOCK:
        _RUNS[project] = {"proc": proc, "log": log, "t0": time.time(),
                          "started_at": now()}
    return run_state(project)


def stop_run(project: str) -> dict:
    """Stop Claude Code started from the app. Batches it had taken return to the queue (claims lapse)."""
    with _RUNS_LOCK:
        r = _RUNS.get(project)
    if r and r["proc"].poll() is None:
        r["stopped"] = True
        try:
            r["proc"].terminate()
            r["proc"].wait(timeout=10)
        except (OSError, subprocess.SubprocessError):
            try:
                r["proc"].kill()
            except OSError:
                pass
    return run_state(project)
