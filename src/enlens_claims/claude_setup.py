"""Setting up the ENLENS plugin for Claude Code (0.8, G2): `enlens claude-setup`.

The plugin ships inside the ENLENS package (`claude_plugin/`). Set-up writes it, as a one-plugin marketplace, into
ENLENS's own data folder (`<ENLENS_HOME>/claude-plugin`), with the connector started by this very Python and this
data folder, then checks that the connector starts and offers the queue tools. It prints the two lines that add the
plugin to Claude Code. ENLENS writes nothing to Claude Code's own settings and never starts Claude Code.

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
import shutil
import sys
from pathlib import Path

from . import __version__
from . import home as core

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
