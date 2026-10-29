"""The app's data folder: settings, the optional cloud key, and projects.

Everything lives in one folder on this computer, ENLENS_HOME (default ~/enlens):
- settings.json      choices made in Settings (local model server, models, search options)
- credentials.json   the Claude API key, only when cloud models are allowed and "remember" is ticked (user-only)
- projects/<name>/   one workspace per project, the same format the command line uses
- links.json         projects that live in another folder (linked, not copied)
- frameworks/*.csv   codebooks available to every project (a project's own frameworks/ folder adds more)

Local first: the default model service is whatever local server is running (Ollama, LM Studio, llama.cpp...).
The Claude API is used only after "Allow cloud models" is switched on, because the text read then leaves the
computer.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

from .llm import (AnthropicBackend, BackendError, BaselineBackend, LocalBackend, OllamaBackend, detect_local,
                  is_chat_model)
from .store import Workspace

DEFAULTS = {
    # 0.9: subscription first. A new installation answers with Claude Code on the researcher's own Claude plan; the
    # tasks wait in the project's queue on this computer and leave it only when the researcher runs Claude Code
    # (or presses "Start Claude Code" in the app). Local-only installations fall back to "auto" (see load_settings).
    "backend": "claude_code",          # claude_code | auto | ollama | openai | anthropic | baseline
    "allow_cloud": False,              # the Claude API can be used only when this is on
    "anthropic_model": "claude-opus-5-5",
    "ollama_url": "http://localhost:11434",
    "ollama_model": "",
    "openai_url": "http://localhost:1234/v1",
    "openai_model": "",
    "num_ctx": "auto",                 # "auto" (the smallest that fits the settings' largest task) or a number
    "think": "off",                    # default | on | off | judging (on only when judging excerpts); off is fastest
    "think_budget": 1500,              # reasoning tokens before the model is asked to answer (0: no limit)
    "embed_backend": "ollama",         # ollama | openai | off
    "embed_model": "",                 # e.g. nomic-embed-text or bge-m3; empty = keyword search only
    "embed_url": "",                   # empty = the address of the chosen server kind
    "threshold": 0.6,
    "k": 8,
    "per_doc": 2,
    "expand": True,
    "decompose": False,
    "second_pass": False,              # sort the best excerpts again by wording (off: it did worse on the pilot)
    "project": "",
    "benchmark_reference": "",
    "second_model": "",                # a second local chat model, to compare its judgements with the main model's
    "ocr": "auto",                     # auto: read scanned PDF pages when OCR (Tesseract) is installed; off: never
    "ocr_lang": "eng",                 # Tesseract languages, e.g. eng+nld
    # 0.7
    "seed": 42,                        # sent with every model request, so the same input gives the same answer
    "profile_framework": "sdg",        # the codebook of document profiles: the 169 SDG targets (or sdg_goals: 17)
    "themes_k": 20,                    # how many themes a run looks for (2 to 60; fewer in a small project)
    # 0.8
    "allow_claude_code": True,         # Claude Code (the researcher's own plan) may answer (0.9: on by default)
    "use_fable": False,                # the auditor (second opinions, hard checks) runs on Fable instead of Opus
    "task_models": {},                 # per-task models chosen in Settings: {"claude": {row: alias}, "local": {row: model}}
    "local_small_model": "",           # local: the small model for labels and links ("" = the main model does all)
    "routing": True,                   # the Claude API and local servers use the model of each task (G3)
}

BACKEND_LABELS = {"claude_code": "Claude Code (your subscription)", "auto": "Local model (automatic)",
                  "ollama": "Ollama", "openai": "Local OpenAI-compatible server", "anthropic": "Claude API (cloud)",
                  "baseline": "Offline demo"}
CLOUD_BACKENDS = {"anthropic"}
OFF_COMPUTER = {"anthropic", "claude_code"}   # the passages read leave this computer


def home() -> Path:
    h = Path(os.environ.get("ENLENS_HOME") or Path.home() / "enlens").expanduser()
    (h / "projects").mkdir(parents=True, exist_ok=True)
    return h


def _write_private(path: Path, text: str) -> None:
    """Write a file readable by this user only (created that way, so it is never briefly world-readable)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - e.g. some Windows file systems
        pass


# ---------------------------------------------------------------------------------------------
# settings and key
# ---------------------------------------------------------------------------------------------
def load_settings() -> dict:
    p = home() / "settings.json"
    s = dict(DEFAULTS)
    if p.exists():
        try:
            stored = json.loads(p.read_text(encoding="utf-8"))
            s.update({k: v for k, v in stored.items() if k in DEFAULTS})
            # 0.5 wrote its default context length (16,384) into every settings file: from 0.6 that default is
            # "auto", which uses less of the computer's memory; a length chosen in 0.6 or later is kept
            if not stored.get("_version") and stored.get("num_ctx") == 16384:
                s["num_ctx"] = "auto"
            # a 0.4 install defaulted to the Claude API; keep it only for people who had chosen it with a key
            if stored.get("backend") == "anthropic" and "allow_cloud" not in stored:
                s["allow_cloud"] = bool(env_key() or stored_key())
        except (json.JSONDecodeError, OSError):
            pass
    if local_only() and s.get("backend") in OFF_COMPUTER:
        # whoever installed ENLENS switched cloud models off for good: the subscription default becomes the local one
        s["backend"] = "auto"
        s["allow_claude_code"] = False
    return s


def clean_settings(changes: dict) -> dict:
    """Validate a partial settings update. Raises ValueError with a readable message."""
    out = {}
    for k, v in changes.items():
        if k not in DEFAULTS:
            raise ValueError(f"Unknown setting {k!r}.")
        d = DEFAULTS[k]
        if k == "task_models":
            from .routing import clean_task_models

            out[k] = clean_task_models(v)
            continue
        if k == "num_ctx":
            if str(v).strip().lower() in ("auto", ""):
                v = "auto"
            else:
                try:
                    v = int(v)
                except (TypeError, ValueError):
                    raise ValueError("num_ctx must be auto or a whole number.") from None
        elif isinstance(d, bool):
            v = bool(v)
        elif isinstance(d, int):
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise ValueError(f"{k} must be a whole number.") from None
        elif isinstance(d, float):
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{k} must be a number.") from None
        else:
            v = "" if v is None else str(v).strip()
        out[k] = v
    if "backend" in out and out["backend"] not in BACKEND_LABELS:
        raise ValueError(f"backend must be one of {', '.join(BACKEND_LABELS)}.")
    if "think" in out and out["think"] not in ("default", "on", "off", "judging"):
        raise ValueError("think must be default, on, off or judging.")
    if "think_budget" in out and not (out["think_budget"] == 0 or 256 <= out["think_budget"] <= 16384):
        raise ValueError("think_budget must be 0 (no limit) or between 256 and 16,384 tokens.")
    if "ocr" in out and out["ocr"] not in ("auto", "off"):
        raise ValueError("ocr must be auto or off.")
    if "ocr_lang" in out and not re.fullmatch(r"[A-Za-z_]{2,}(\+[A-Za-z_]{2,})*", out["ocr_lang"] or ""):
        raise ValueError("ocr_lang must be Tesseract language codes joined by +, for example eng or eng+nld.")
    if "embed_backend" in out and out["embed_backend"] not in ("ollama", "openai", "off"):
        raise ValueError("embed_backend must be ollama, openai or off.")
    if "threshold" in out and not 0 <= out["threshold"] <= 1:
        raise ValueError("threshold must be between 0 and 1.")
    if "k" in out and not 1 <= out["k"] <= 20:
        raise ValueError("k must be between 1 and 20.")
    if "per_doc" in out and not 1 <= out["per_doc"] <= 10:
        raise ValueError("per_doc must be between 1 and 10.")
    if "num_ctx" in out and out["num_ctx"] != "auto" and not 2048 <= out["num_ctx"] <= 262144:
        raise ValueError("num_ctx must be between 2,048 and 262,144.")
    if "seed" in out and not 0 <= out["seed"] <= 2 ** 31 - 1:
        raise ValueError("seed must be a whole number from 0 to 2,147,483,647.")
    if "themes_k" in out and not 2 <= out["themes_k"] <= 60:
        raise ValueError("themes_k must be between 2 and 60.")
    if "profile_framework" in out and not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", out["profile_framework"] or ""):
        raise ValueError("profile_framework must be the short name of a codebook, for example sdg or sdg_goals.")
    return out


def local_only() -> bool:
    """Whether cloud models are switched off for good on this computer (by whoever installed the app): the
    environment variable ENLENS_LOCAL_ONLY=1, `enlens-gui --local-only`, or a file named `local_only` in the data
    folder. The app then hides the cloud option and refuses to switch to it."""
    flag = os.environ.get("ENLENS_LOCAL_ONLY", "").strip().lower() in ("1", "true", "yes", "on")
    try:
        return flag or (home() / "local_only").exists()
    except OSError:
        return flag


SETTINGS_VERSION = 2  # 2: written by 0.6 (num_ctx "auto" is the default)


def save_settings(s: dict) -> None:
    (home() / "settings.json").write_text(json.dumps({"_version": SETTINGS_VERSION,
                                                      **{k: s.get(k, v) for k, v in DEFAULTS.items()}}, indent=2),
                                          encoding="utf-8")


def update_settings(changes: dict) -> dict:
    s = load_settings()
    s.update(clean_settings(changes))
    if local_only() and (s["backend"] in OFF_COMPUTER or s["allow_cloud"] or s.get("allow_claude_code")):
        raise ValueError("Cloud models are switched off on this computer by whoever installed ENLENS: "
                         "everything stays on this computer.")
    if s["backend"] in CLOUD_BACKENDS and not s["allow_cloud"]:
        raise ValueError("Allow cloud models first: with the Claude API the passages read leave this computer.")
    if s["backend"] == "claude_code" and not s.get("allow_claude_code"):
        raise ValueError("Confirm Claude Code first: the passages inside the tasks it takes are sent to Anthropic.")
    save_settings(s)
    return s


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
    _write_private(home() / "credentials.json", json.dumps({"anthropic_api_key": key}))


def forget_key() -> None:
    p = home() / "credentials.json"
    if p.exists():
        p.unlink()


def pick_chat_model(models: list[str], loaded: list[str] | tuple = (), modified: dict | None = None) -> str:
    """The chat model to use when none is chosen (or the chosen one is not installed), loading nothing extra:

    1. a chat model the server already holds in memory (the first one it lists: the most recently used);
    2. otherwise the most recently pulled or downloaded one (Ollama's `modified_at`);
    3. otherwise the first in alphabetical order.
    """
    chat = sorted(m for m in models if is_chat_model(m))
    if not chat:
        return ""
    for m in loaded or ():
        if m in chat:
            return m
    when = {m: (modified or {}).get(m) or "" for m in chat}
    if any(when.values()):
        return max(chat, key=lambda m: (when[m], [-ord(c) for c in m]))  # newest; ties alphabetical
    return chat[0]


def _first_chat_model(models: list[str]) -> str:
    """Kept for callers of 0.5: the alphabetical choice, now `pick_chat_model` without server information."""
    return pick_chat_model(models)


def best_model(be) -> str:
    """The chat model a backend should use when none is chosen: see `pick_chat_model`."""
    inv = be.inventory() if hasattr(be, "inventory") else {"models": be.models()}
    return pick_chat_model(inv.get("models") or [], inv.get("loaded") or (), inv.get("modified") or {})


def _installed(model: str, models: list[str]) -> bool:
    return bool(model) and (model in models or f"{model}:latest" in models)


def task_tokens(kind: str, k: int = 8, thinks: bool = False, max_chars: int = 1100, budget: int = 0) -> int:
    """A conservative estimate of the context a task needs: its system prompt, the longest user prompt the settings
    allow (k excerpts of `max_chars` with their headers, the claim, a retry's list of problems) and the answer.
    With reasoning: room for it (with a `budget`, the budget twice: once reasoning, once as notes for the answer)."""
    from . import prompts
    from .llm import OUTPUT_CAP, THINK_ALLOWANCE, estimate_tokens

    system = estimate_tokens(prompts.system_prompt(kind))
    retry = 1600  # "YOUR PREVIOUS ANSWER HAD THESE PROBLEMS" with up to ten problems
    if kind in ("check", "second"):
        # claim (and its hypothesis), code description, excerpts, and (check-v4) the text before each excerpt
        user = 2000 + 400 + k * (max_chars + 160 + 360) + retry
    elif kind == "verify_set":
        user = 2000 + 400 + k * (max_chars + 160) + retry
    elif kind == "reread":
        user = 2400 + max_chars + 160 + 1200 + retry       # one excerpt and a reader's comment
    elif kind == "verify":
        user = 2400 + max_chars + 160 + retry
    elif kind == "extract":
        user = 800 + max_chars + 500 + retry               # title, DOI, context, passage
    elif kind == "split":
        user = 6000 + retry
    elif kind == "label":
        user = 600 + 8 * 400 + 600 + max_chars + retry      # codebook, 8 candidate codes, context, passage
    elif kind == "theme":
        user = 800 + 3 * (max_chars + 160) + retry
    elif kind == "link":
        user = 2 * (100 + 3 * 400) + retry
    elif kind == "resolve":
        user = 300 + 3 * (max_chars + 40) + retry
    else:  # expand, decompose
        user = 4000 + retry
    room = (2 * budget + 64 if budget else THINK_ALLOWANCE) if thinks else 0
    return system + estimate_tokens("x" * user) + OUTPUT_CAP.get(kind, 2000) + room


def thinking(settings: dict) -> tuple[bool | None, frozenset | None, int]:
    """What the settings say about reasoning: (think for OllamaBackend, the task kinds it is limited to or None, the
    budget in tokens). "judging": on for judging excerpts only (check, read again, second model), off otherwise."""
    from .llm import JUDGING

    mode = settings.get("think", "default")
    budget = int(settings.get("think_budget") or 0) if mode != "off" else 0
    if mode == "judging":
        return True, JUDGING, budget
    return {"on": True, "off": False}.get(mode), None, budget


def context_plan(settings: dict, kinds: tuple[str, ...] = ("check", "expand", "decompose", "reread"),
                 thinks: bool | None = None,
                 max_chars: int = 1100) -> dict:
    """The context length the settings ask for: a fixed number, or with "auto" the smallest of
    llm.CONTEXT_TIERS that fits the largest task of `kinds` at the settings' number of excerpts.

    `thinks` None: the model may reason unless reasoning is switched off (the conservative guess). The result is
    the same for the same settings and model, so Ollama never has to reload the model between requests.
    """
    from .llm import fit_context

    if thinks is None:
        thinks = settings.get("think", "default") != "off"
    _think, only, budget = thinking(settings)
    k = int(settings.get("k") or 8)
    need = max(task_tokens(kd, k, thinks and (only is None or kd in only), max_chars, budget) for kd in kinds)
    setting = settings.get("num_ctx", "auto")
    if str(setting).lower() == "auto":
        return {"setting": "auto", "num_ctx": fit_context(need), "needed": need, "thinking_allowance": thinks}
    return {"setting": int(setting), "num_ctx": int(setting), "needed": need, "thinking_allowance": thinks,
            **({"too_small": True} if need > int(setting) else {})}


def _seed(settings: dict) -> int | None:
    v = settings.get("seed", 42)
    return None if v in (None, "") else int(v)


def _ollama(settings: dict, url: str, model: str, think, kinds=("check", "expand", "decompose")) -> OllamaBackend:
    _t, only, budget = thinking(settings)
    be = OllamaBackend(base_url=url, think=think, think_kinds=only, think_budget=budget, seed=_seed(settings))
    thinks = None
    if str(settings.get("num_ctx", "auto")).lower() == "auto":
        if think is not None:
            thinks = bool(think)
        else:  # "default": ask the model whether it reasons (one short request; on failure assume it does)
            caps = be._can_think(model)
            thinks = True if caps is None else caps
    be.num_ctx = context_plan(settings, kinds, thinks)["num_ctx"]
    return be


def make_backend(settings: dict, api_key: str = "", kinds: tuple[str, ...] = ("check", "expand", "decompose")):
    """The backend and model id the settings describe. Raises BackendError for problems the user can fix.

    Without a chosen model, or when the chosen one is not installed, the model is picked by `pick_chat_model`
    (one already in memory first); `be.model_note` then says so. `kinds` are the task kinds the backend will run,
    for an automatic context length.
    """
    be, model = _make_backend(settings, api_key, kinds)
    if settings.get("routing", True) and getattr(be, "name", "") != "baseline":
        from .routing import from_settings

        be.router = from_settings(settings, large=model)  # 0.8: the model of each kind of task (G3)
        if getattr(be, "name", "") == "anthropic":
            model = be.router.call_model("check") or model
        elif getattr(be, "name", "") == "claude_code":
            model = be.router.model("check") or model
    return be, model


def _make_backend(settings: dict, api_key: str = "", kinds: tuple[str, ...] = ("check", "expand", "decompose")):
    b = settings.get("backend", "auto")
    think = thinking(settings)[0]
    if b == "claude_code":
        from .llm import ClaudeCodeBackend

        if local_only():
            raise BackendError("Cloud models are switched off on this computer by whoever installed ENLENS. "
                               "Choose a local model in Settings.")
        if not settings.get("allow_claude_code"):
            raise BackendError("Claude Code is not confirmed yet. Choose it again in Settings and confirm.")
        return ClaudeCodeBackend(), "opus"
    if b == "anthropic":
        if local_only():
            raise BackendError("Cloud models are switched off on this computer by whoever installed ENLENS. "
                               "Choose a local model in Settings.")
        if not settings.get("allow_cloud"):
            raise BackendError("Cloud models are switched off. Allow them in Settings to use the Claude API "
                               "(the passages read are then sent to Anthropic), or choose a local model.")
        return AnthropicBackend(api_key=api_key or env_key() or stored_key() or None), settings["anthropic_model"]
    if b == "ollama":
        chosen = settings.get("ollama_model") or ""
        probe = OllamaBackend(base_url=settings["ollama_url"], timeout=3)
        try:
            inv = probe.inventory(timeout=3)
        except BackendError:
            inv = None  # not reachable now: the model call will say so plainly
        model, note = chosen, None
        if inv is not None and not _installed(chosen, inv["models"]):
            model = pick_chat_model(inv["models"], inv["loaded"], inv["modified"])
            if model and chosen:
                note = f"{chosen} is not installed; {model} is used instead."
        if not model:
            raise BackendError("Choose an Ollama model in Settings." if inv is None or inv["models"] else
                               "Ollama has no chat model yet. Install one, for example: ollama pull qwen3:8b")
        be = _ollama(settings, settings["ollama_url"], model, think, kinds)
        be.model_note = note
        return be, model
    if b == "openai":
        be = LocalBackend(base_url=settings["openai_url"], seed=_seed(settings))
        try:
            inv = be.inventory()
        except BackendError:
            if settings.get("openai_model"):  # not reachable now: the model call will say so plainly
                be.model_note = None
                return be, settings["openai_model"]
            raise
        chosen = settings.get("openai_model") or ""
        model = chosen if chosen in inv["models"] else pick_chat_model(inv["models"], inv["loaded"])
        if not model:
            raise BackendError(f"The server at {settings['openai_url']} lists no chat model. Load one first.")
        be.model_note = f"{chosen} is not offered by the server; {model} is used instead." if chosen and model != chosen else None
        return be, model
    if b == "auto":
        found = detect_local(ollama_url=settings.get("ollama_url"), extra=[settings.get("openai_url") or ""])
        for srv in found:
            models = srv["models"]
            if srv["kind"] == "ollama":
                model = (settings.get("ollama_model") if _installed(settings.get("ollama_model") or "", models)
                         else pick_chat_model(models, srv.get("loaded") or (), srv.get("modified") or {}))
                if model:
                    return _ollama(settings, srv["url"], model, think, kinds), model
            else:
                model = (settings.get("openai_model") if settings.get("openai_model") in models
                         else pick_chat_model(models, srv.get("loaded") or ()))
                if model:
                    return LocalBackend(base_url=srv["url"], seed=_seed(settings)), model
        if found:
            raise BackendError("A local model server is running but has no chat model. With Ollama: "
                               "ollama pull qwen3:8b (or another model), then try again.")
        raise BackendError("No local model server is running. Start Ollama (ollama.com) or LM Studio (lmstudio.ai), "
                           "or choose the offline demo in Settings.")
    return BaselineBackend(), "baseline"


def make_embedder(settings: dict):
    """The embedder for semantic search, or None when it is off or no embedding model is chosen."""
    from .embed import make_embedder as _make

    kind, model = settings.get("embed_backend", "off"), settings.get("embed_model", "")
    if kind == "off" or not model:
        return None
    url = settings.get("embed_url") or (settings.get("ollama_url") if kind == "ollama" else settings.get("openai_url"))
    return _make(kind, model, url)


def backend_label(settings: dict) -> str:
    b = settings.get("backend", "auto")
    model = {"auto": settings.get("ollama_model") or settings.get("openai_model") or "first model found",
             "anthropic": "a model per task" if settings.get("routing", True) else settings.get("anthropic_model"),
             "claude_code": "a helper and model per task", "ollama": settings.get("ollama_model") or "no model chosen",
             "openai": settings.get("openai_model") or "first model listed", "baseline": "word overlap, no model"}.get(b, "")
    return f"{BACKEND_LABELS.get(b, b)} · {model}"


# ---------------------------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------------------------
def safe_name(name: str) -> str:
    n = re.sub(r"[^\w .-]", "", name or "", flags=re.UNICODE).strip().strip(".")
    return re.sub(r"\s+", " ", n)[:60].strip().strip(".")


def _links() -> dict[str, str]:
    p = home() / "links.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_links(links: dict[str, str]) -> None:
    (home() / "links.json").write_text(json.dumps(links, indent=2), encoding="utf-8")


def list_projects() -> list[str]:
    own = {p.name for p in (home() / "projects").iterdir() if (p / "enlens.sqlite").exists()}
    linked = {n for n, path in _links().items() if (Path(path) / "enlens.sqlite").exists()}
    return sorted(own | linked, key=str.lower)


def project_path(name: str) -> Path:
    link = _links().get(name)
    return Path(link) if link else home() / "projects" / name


def is_linked(name: str) -> bool:
    return name in _links() or (home() / "projects" / name).is_symlink()


def create_project(name: str) -> Workspace:
    n = safe_name(name)
    if not n:
        raise ValueError("Give the project a name (letters, digits, spaces, dots, dashes).")
    if n in list_projects() or (project_path(n) / "enlens.sqlite").exists():
        raise ValueError(f"A project called {n!r} already exists.")
    return Workspace.create(project_path(n))


_OPEN: dict[str, tuple[float, Workspace]] = {}


def open_project(name: str) -> Workspace:
    """Open a project (kept open for reuse: opening runs the schema checks)."""
    path = project_path(name)
    key = str(path.resolve())
    hit = _OPEN.get(key)
    try:
        stamp = (path / "enlens.sqlite").stat().st_ino
    except OSError:
        stamp = None
    if hit and hit[0] == stamp:
        return hit[1]
    ws = Workspace.open(path)
    _OPEN[key] = (stamp, ws)
    return ws


def link_existing(path: str, name: str | None = None) -> str:
    """Make an existing workspace folder (for example the pilot) appear as a project, without copying it."""
    src = Path(path).expanduser().resolve()
    if not (src / "enlens.sqlite").exists():
        raise ValueError(f"No workspace (enlens.sqlite) in {src}.")
    n = safe_name(name or src.name) or "workspace"
    if n in list_projects() or (home() / "projects" / n).exists():
        raise ValueError(f"A project called {n!r} already exists.")
    links = _links()
    links[n] = str(src)
    _save_links(links)
    return n


def remove_project(name: str) -> str:
    """Unlink a linked project (its folder is untouched), or move an own project to the trash folder."""
    links = _links()
    if name in links:
        del links[name]
        _save_links(links)
        return "unlinked"
    p = home() / "projects" / name
    keep_project(name)  # a quick look that is removed is not one any more
    if p.is_symlink():
        p.unlink()
        return "unlinked"
    if not (p / "enlens.sqlite").exists():
        raise KeyError(name)
    _OPEN.pop(str(p.resolve()), None)
    trash = home() / "trash"
    trash.mkdir(exist_ok=True)
    dest = trash / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.move(str(p), str(dest))
    return f"moved to {dest}"


def upload_folder(ws: Workspace, batch: str | None = None) -> Path:
    """The folder that one upload batch is written to (inside the project)."""
    b = re.sub(r"[^A-Za-z0-9_-]", "", batch or "") or time.strftime("%Y%m%d-%H%M%S")
    folder = ws.root / "uploads" / b
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def save_uploads(ws: Workspace, files: list[tuple[str, bytes]]) -> Path:
    """Write uploaded files into the project's uploads folder; returns the folder to ingest."""
    folder = upload_folder(ws)
    for name, data in files:
        (folder / (Path(name.replace("\\", "/")).name or "upload")).write_bytes(data)
    return folder


def make_second_backend(settings: dict, api_key: str = ""):
    """The backend for the second model of Settings (on the same server as the main model), and its name."""
    b = settings.get("backend", "auto")
    if b in ("claude_code", "anthropic") and settings.get("routing", True):
        # 0.8: on Claude the second opinion comes from the auditor (Opus, or Fable when switched on)
        be, _m = make_backend(settings, api_key, kinds=("second",))
        alias = be.router.model("second") or "opus"
        return be, (be.router.api_id(alias) if b == "anthropic" else alias)
    second = (settings.get("second_model") or "").strip()
    if not second:
        raise ValueError("Choose a second model in Settings first.")
    if b == "baseline":
        raise ValueError("The offline demo has no second model. Choose a local model in Settings.")
    key = {"anthropic": "anthropic_model", "openai": "openai_model"}.get(b, "ollama_model")
    changed = {**settings, key: second}
    if b == "auto":
        changed.update(ollama_model=second, openai_model=second)
    be, model = make_backend(changed, api_key, kinds=("second",))
    if model != second:
        raise BackendError(f"The second model {second} is not installed on the model server. Install it, or choose "
                           "another second model in Settings.")
    return be, model


# ---------------------------------------------------------------------------------------------
# 0.7: quick looks (one document dropped on the start page), and the model test's speeds
# ---------------------------------------------------------------------------------------------
QUICKLOOK_DAYS = 7


def _quicklooks() -> dict[str, dict]:
    p = home() / "quicklook.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_quicklooks(data: dict) -> None:
    (home() / "quicklook.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def create_quicklook(filename: str, came_from: str | None = None) -> Workspace:
    """A temporary project named after a file, for a quick look at one document. It is moved to the trash after
    QUICKLOOK_DAYS days unless it is kept (`keep_project`)."""
    stem = re.sub(r"\.(pdf|docx|html?|txt|md|zip)$", "", Path(filename or "document").name, flags=re.I)
    name = unique_project_name(stem or "Quick look")
    ws = create_project(name)
    data = _quicklooks()
    data[ws.root.name] = {"created_at": time.time(), "file": Path(filename or "").name, "from": came_from}
    _save_quicklooks(data)
    return ws


def is_temporary(name: str) -> dict | None:
    """{created_at, expires_at, file} for a quick look not kept yet, else None."""
    q = _quicklooks().get(name)
    if not q:
        return None
    return {**q, "expires_at": q.get("created_at", 0) + QUICKLOOK_DAYS * 86400}


def keep_project(name: str) -> bool:
    data = _quicklooks()
    if name not in data:
        return False
    del data[name]
    _save_quicklooks(data)
    return True


def cleanup_quicklooks(now_: float | None = None) -> list[str]:
    """Move quick looks older than QUICKLOOK_DAYS days that were not kept to the trash. Returns their names."""
    data = _quicklooks()
    if not data:
        return []
    t = time.time() if now_ is None else now_
    moved = []
    for name, q in list(data.items()):
        if t - float(q.get("created_at") or t) < QUICKLOOK_DAYS * 86400:
            continue
        try:
            if name in list_projects():
                remove_project(name)
            moved.append(name)
        except (KeyError, OSError):
            pass
        data.pop(name, None)
    _save_quicklooks(data)
    return moved


def record_benchmark(model: str, kinds: dict) -> None:
    """Keep the model test's median seconds per task of each kind (estimates of long runs use them)."""
    p = home() / "benchmarks.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (json.JSONDecodeError, OSError):
        data = {}
    data.setdefault(model, {}).update({k: v.get("seconds_median") for k, v in kinds.items() if v.get("seconds_median")})
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def benchmark_medians() -> dict:
    p = home() / "benchmarks.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def unique_project_name(name: str) -> str:
    """`name`, or `name (2)`, `name (3)`… when a project of that name exists."""
    base = safe_name(name) or "Imported project"
    n, i = base, 2
    while n in list_projects() or (home() / "projects" / n).exists():
        n = f"{base[:54]} ({i})"
        i += 1
    return n
