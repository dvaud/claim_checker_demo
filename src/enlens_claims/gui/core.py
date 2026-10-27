"""Everything the GUI needs that is not drawing: settings, projects, the API key and backends.

Data lives in one folder, ENLENS_HOME (default ~/enlens):
- settings.json      choices made in Settings
- credentials.json   the Claude API key, only when "remember" is ticked (readable by you alone)
- projects/<name>/   one workspace per project, the same format the command line uses
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from ..llm import AnthropicBackend, BaselineBackend, OllamaBackend
from ..store import Workspace

DEFAULTS = {
    "backend": "anthropic",            # anthropic | ollama | baseline
    "anthropic_model": "claude-opus-5-5",
    "ollama_url": "http://localhost:11434",
    "ollama_model": "",
    "num_ctx": 16384,
    "think": "default",                # default | on | off
    "threshold": 0.6,
    "k": 8,
    "per_doc": 2,
    "expand": True,
    "project": "",
    "benchmark_reference": "",
}

BACKEND_LABELS = {"anthropic": "Claude API", "ollama": "Ollama", "baseline": "Offline demo"}


def home() -> Path:
    h = Path(os.environ.get("ENLENS_HOME") or Path.home() / "enlens").expanduser()
    (h / "projects").mkdir(parents=True, exist_ok=True)
    return h


# ---------------------------------------------------------------------------------------------
# settings and key
# ---------------------------------------------------------------------------------------------
def load_settings() -> dict:
    p = home() / "settings.json"
    s = dict(DEFAULTS)
    if p.exists():
        try:
            s.update({k: v for k, v in json.loads(p.read_text()).items() if k in DEFAULTS})
        except (json.JSONDecodeError, OSError):
            pass
    return s


def save_settings(s: dict) -> None:
    (home() / "settings.json").write_text(json.dumps({k: s.get(k, v) for k, v in DEFAULTS.items()}, indent=2))


def stored_key() -> str:
    p = home() / "credentials.json"
    if p.exists():
        try:
            return json.loads(p.read_text()).get("anthropic_api_key", "")
        except (json.JSONDecodeError, OSError):
            return ""
    return ""


def env_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "")


def remember_key(key: str) -> None:
    p = home() / "credentials.json"
    p.write_text(json.dumps({"anthropic_api_key": key}))
    try:
        os.chmod(p, 0o600)
    except OSError:  # pragma: no cover - e.g. some Windows file systems
        pass


def forget_key() -> None:
    p = home() / "credentials.json"
    if p.exists():
        p.unlink()


def make_backend(settings: dict, api_key: str = ""):
    """The backend and model id the settings describe. Raises BackendError for problems the user can fix."""
    b = settings.get("backend", "anthropic")
    if b == "anthropic":
        return AnthropicBackend(api_key=api_key or env_key() or stored_key() or None), settings["anthropic_model"]
    if b == "ollama":
        think = {"on": True, "off": False}.get(settings.get("think", "default"))
        if not settings.get("ollama_model"):
            from ..llm import BackendError
            raise BackendError("Choose an Ollama model in Settings.")
        return (OllamaBackend(base_url=settings["ollama_url"], num_ctx=int(settings["num_ctx"]), think=think),
                settings["ollama_model"])
    return BaselineBackend(), "baseline"


def backend_label(settings: dict) -> str:
    b = settings.get("backend", "anthropic")
    model = {"anthropic": settings.get("anthropic_model"), "ollama": settings.get("ollama_model") or "no model chosen",
             "baseline": "word overlap, no model"}[b]
    return f"{BACKEND_LABELS[b]} · {model}"


# ---------------------------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------------------------
def safe_name(name: str) -> str:
    n = re.sub(r"[^A-Za-z0-9 _.-]", "", name).strip().strip(".")
    return re.sub(r"\s+", " ", n)[:60]


def list_projects() -> list[str]:
    return sorted(p.name for p in (home() / "projects").iterdir() if (p / "enlens.sqlite").exists())


def project_path(name: str) -> Path:
    return home() / "projects" / name


def create_project(name: str) -> Workspace:
    n = safe_name(name)
    if not n:
        raise ValueError("Give the project a name (letters, digits, spaces, dots, dashes).")
    if (project_path(n) / "enlens.sqlite").exists():
        raise ValueError(f"A project called {n!r} already exists.")
    return Workspace.create(project_path(n))


def open_project(name: str) -> Workspace:
    return Workspace.open(project_path(name))


def link_existing(path: str, name: str | None = None) -> str:
    """Make an existing workspace folder (for example the pilot) appear as a project, without copying it."""
    src = Path(path).expanduser().resolve()
    if not (src / "enlens.sqlite").exists():
        raise ValueError(f"No workspace (enlens.sqlite) in {src}.")
    n = safe_name(name or src.name) or "workspace"
    dest = project_path(n)
    if dest.exists() or dest.is_symlink():
        raise ValueError(f"A project called {n!r} already exists.")
    try:
        dest.symlink_to(src, target_is_directory=True)
    except OSError as e:  # pragma: no cover - symlinks can be restricted on Windows
        raise ValueError(f"Could not link the folder ({e}). Copy it into {home() / 'projects'} instead.") from e
    return n


def save_uploads(ws: Workspace, files: list[tuple[str, bytes]]) -> Path:
    """Write uploaded files into the project's uploads folder; returns the folder to ingest."""
    folder = ws.root / "uploads" / time.strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in files:
        clean = Path(name).name or "upload"
        (folder / clean).write_bytes(data)
    return folder
