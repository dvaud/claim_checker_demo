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
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .llm import (AnthropicBackend, BackendError, BaselineBackend, LocalBackend, OllamaBackend, detect_local,
                  is_chat_model)
from . import routing, taskkinds
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
    # 0.13.10: how fast Claude Code started from the app works: slower (one helper at once), normal (two) or faster
    # (four; it uses the plan's limit sooner). Chosen beside every Start Claude Code, and under Settings → AI.
    "claude_speed": "normal",
    # 0.18.1 (N2): how much thought Claude gives each kind of task, chosen beside every Start Claude Code and kept here:
    # efficient (a lighter model per kind), balanced (the recommended models) or intelligence (a stronger model per
    # kind, more effort where a helper takes one). Claude only: a local model keeps its own choice.
    "claude_thought": "balanced",
    # 0.18.1 (I1): which route answers each kind of task when Claude and a local model are both set: best (Claude for
    # everything, the local model only for documents marked Only a local AI, as before), balanced (labels, links, search
    # words, theme names and references on the local model) or mostly_local (all but second opinions on the local
    # model). An unsure local answer steps up to Claude (I2), only for documents Claude may read.
    "ai_mix": "best",
    # 0.18.1 (I4): when Claude Code says the plan's usage limit is reached: wait (the queue waits for the next start)
    # or local (the local model answers what waits, where it may)
    "at_limit": "wait",
    # 0.13.10: the recommended model of each task follows the Claude plan (routing.tier_defaults): the plan Claude Code
    # names, found in the background whenever ENLENS asks Claude Code how it is (free | pro | max; "" not known), unless
    # set by hand under Settings → Technical (auto | free | pro | max)
    "claude_plan": "auto",
    "claude_plan_detected": "",
    "task_models": {},                 # per-task models chosen in Settings: {"claude": {row: alias}, "local": {row: model}}
    "local_small_model": "",           # local: the small model for labels and links ("" = the main model does all)
    "routing": True,                   # the Claude API and local servers use the model of each task (G3)
    # 0.11: per-document AI settings. The local model that reads documents marked "Only a local AI" when the main
    # model is Claude ("" = none: those excerpts wait for a person), on a server on this computer; and the kind of
    # Claude account, for the panel "What happens to the text Claude reads" ("" = not said yet)
    "restricted_server": "",           # "" | ollama | openai
    "restricted_model": "",
    "account_type": "",                # "" | personal | commercial
    # 0.14: shared projects. The name colleagues see beside your judgements, and the random id that stands for you
    # in every project you share (made once, see people.py)
    "your_name": "",
    "person_id": "",
    # 0.15: "stable" (the latest full release) or "early" (also release candidates, which come out a week or more
    # before each new version); a git copy follows main and has no channel
    "update_channel": "stable",
    # 0.15.1: the version whose "what's new" note was last shown (once, after an update; see gui/server.py)
    "whats_new_seen": "",
    # 0.18 (L3): how often each project with a shared folder looks for colleagues' new work (gui/poller.py), in
    # minutes; paused for the whole app, or for the projects named (this computer's choice: never in a project)
    "sync_every_minutes": 2,
    "sync_paused": False,
    "sync_paused_projects": [],
    # roles (DESIGN-roles §3.2, §4.11): this installation's own id, written into the shared folder (`head.json`), so a
    # copy of this data folder on another computer is stopped before it writes there under the same person. Made once
    # (`installation_id`), and made anew when the data folder is not the one it was made in (`installation_place`: a
    # copied or restored folder). Neither is ever in a move zip (bundle.MACHINE_SETTINGS)
    "installation_id": "",
    "installation_place": "",
}

BACKEND_LABELS = {"claude_code": "Claude Code (your subscription)", "auto": "Local model (automatic)",
                  "ollama": "Ollama", "openai": "Local OpenAI-compatible server", "anthropic": "Claude API (cloud)",
                  "baseline": "Offline demo"}
CLOUD_BACKENDS = {"anthropic"}
OFF_COMPUTER = routing.OFF_COMPUTER   # the passages read leave this computer


def home() -> Path:
    h = Path(os.environ.get("ENLENS_HOME") or Path.home() / "enlens").expanduser()
    (h / "projects").mkdir(parents=True, exist_ok=True)
    return h


class _Lock:
    """One change at a time of the small files of the data folder (settings.json, links.json, quicklook.json,
    benchmarks.json): each is read, changed and written back, by requests, jobs and the poller at once, and by other
    programs too (the connector Claude Code runs, the command line). Held by one thread of this program (it may take
    it again inside), and across programs through a lock on the file `.lock` of the data folder; when that file
    cannot be locked within a few seconds the change goes ahead (the lock is for rare collisions, not a gate).
    Reading needs no lock: a file is always put in place whole (`_write_whole`)."""

    def __init__(self) -> None:
        self._thread = threading.RLock()
        self._depth = 0
        self._fd: int | None = None

    def __enter__(self) -> "_Lock":
        self._thread.acquire()
        if self._depth == 0:
            self._fd = self._lock_file()
        self._depth += 1
        return self

    def __exit__(self, *exc) -> None:
        self._depth -= 1
        if self._depth == 0 and self._fd is not None:
            fd, self._fd = self._fd, None
            try:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            finally:
                os.close(fd)
        self._thread.release()

    @staticmethod
    def _lock_file() -> int | None:
        try:
            fd = os.open(home() / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        except OSError:
            return None
        for attempt in range(100):  # about five seconds
            try:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except OSError:
                time.sleep(0.05)
        os.close(fd)
        return None


LOCK = _Lock()


class Unreadable(OSError):
    """A file of the data folder is there and cannot be read this moment: nothing may be written in its place."""


def _write_whole(path: Path, text: str, private: bool = False) -> None:
    """Write a file of the data folder whole: under another name beside it, then put in its place. A reader (another
    thread, the connector, the command line) then finds the file as it was or as it is now, never half of it:
    written in place, settings.json was empty for a moment, read as "no settings", and the defaults read then were
    written back (the name and the person's id gone, a new id made). `private`: readable by this user only, and
    made that way, so it is never briefly world-readable."""
    part = path.with_name(f".{path.name}.{os.getpid()}-{threading.get_ident()}.part")
    try:
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o666)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        if private:
            try:
                os.chmod(part, 0o600)
            except OSError:  # pragma: no cover - e.g. some Windows file systems
                pass
        for attempt in range(8):
            try:
                os.replace(part, path)
                return
            except PermissionError:  # Windows: another program reads the file this very moment
                if attempt == 7:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        try:
            part.unlink()
        except OSError:
            pass


def _read_json(path: Path, tries: int = 6):
    """The JSON a small file of the data folder holds, or None when there is no such file. A file that cannot be read
    this moment (Windows, while it is being put in place or a virus scanner holds it) or does not parse is tried
    again before that is believed; then the error is raised: ValueError (what it holds is not JSON) or Unreadable."""
    for attempt in range(tries):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except ValueError:
            if attempt == tries - 1:
                raise
        except OSError as e:
            if attempt == tries - 1:
                raise Unreadable(f"ENLENS could not read {path.name} in its data folder just now ({e}). Nothing was "
                                 "changed: try again in a moment.") from e
        time.sleep(0.03 * (attempt + 1))
    return None


def _read_dict(path: Path, strict: bool) -> dict:
    """A small file of the data folder that holds a JSON object ({} when there is none, or it holds something else).
    `strict` (before a change is written back): a file that cannot be read raises Unreadable instead of counting as
    empty, so what it holds is never replaced by the one change."""
    try:
        data = _read_json(path)
    except ValueError:
        return {}
    except Unreadable:
        if strict:
            raise
        return {}
    return data if isinstance(data, dict) else {}


def _stored_settings() -> dict | None:
    """settings.json as it is stored (None: there is none). A damaged file gives way to the copy kept from before the
    last change (settings.json.bak), and is put aside as settings.json.damaged when there is none. Raises Unreadable
    when the file is there and cannot be read this moment."""
    p = home() / "settings.json"
    try:
        got = _read_json(p)
    except ValueError:
        try:
            got = _read_json(p.with_name("settings.json.bak"))
        except (ValueError, OSError):
            got = None
        if not isinstance(got, dict):
            try:
                os.replace(p, p.with_name("settings.json.damaged"))
            except OSError:
                pass
    return got if isinstance(got, dict) else None


def _write_private(path: Path, text: str) -> None:
    """Write a file readable by this user only (created that way, so it is never briefly world-readable)."""
    _write_whole(path, text, private=True)


# ---------------------------------------------------------------------------------------------
# settings and key
# ---------------------------------------------------------------------------------------------
_TO_CHANGE = threading.local()


@contextmanager
def to_change():
    """Inside it, `load_settings()` is strict: for the settings read in order to be changed and written back, or to
    make a person's id. (Said this way, not as an argument, so `load_settings()` keeps taking none: tests and
    add-ons put their own in its place.)"""
    was = getattr(_TO_CHANGE, "on", False)
    _TO_CHANGE.on = True
    try:
        yield
    finally:
        _TO_CHANGE.on = was


def load_settings(strict: bool = False) -> dict:
    """The settings. `strict` (or inside `to_change()`: before they are changed and written back, and before a
    person's id is made): a settings file that is there and cannot be read this moment raises Unreadable; otherwise
    the defaults stand in for it, for showing only (written back, they took the person's name and id with them)."""
    s = dict(DEFAULTS)
    try:
        stored = _stored_settings()
    except Unreadable:
        if strict or getattr(_TO_CHANGE, "on", False):
            raise
        stored = None
    if isinstance(stored, dict):
        try:
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
    if local_only():
        # whoever installed ENLENS switched cloud models off for good: the subscription default becomes the local
        # one, and the cloud permissions a settings file may still carry are off (0.11.1: with `allow_cloud` still
        # true from before, every settings change was refused, so nothing could be changed at all)
        if s.get("backend") in OFF_COMPUTER:
            s["backend"] = "auto"
        s["allow_claude_code"] = False
        s["allow_cloud"] = False
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
        if k == "sync_paused_projects":  # 0.18: a list of project names
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise ValueError("sync_paused_projects must be a list of project names.")
            out[k] = sorted({x.strip() for x in v if x.strip()})
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
    if "claude_speed" in out and out["claude_speed"] not in ("slower", "normal", "faster"):
        raise ValueError("claude_speed must be slower, normal or faster.")
    if "claude_thought" in out and out["claude_thought"] not in ("efficient", "balanced", "intelligence"):
        raise ValueError("claude_thought must be efficient, balanced or intelligence.")
    if "ai_mix" in out and out["ai_mix"] not in ("best", "balanced", "mostly_local"):
        raise ValueError("ai_mix must be best, balanced or mostly_local.")
    if "at_limit" in out and out["at_limit"] not in ("wait", "local"):
        raise ValueError("at_limit must be wait or local.")
    if "claude_plan" in out and out["claude_plan"] not in ("auto", "free", "pro", "max"):
        raise ValueError("claude_plan must be auto, free, pro or max.")
    if "claude_plan_detected" in out and out["claude_plan_detected"] not in ("", "free", "pro", "max"):
        raise ValueError("claude_plan_detected must be free, pro, max or empty.")
    if "update_channel" in out and out["update_channel"] not in ("stable", "early"):
        raise ValueError("update_channel must be stable or early.")
    if "ocr" in out and out["ocr"] not in ("auto", "off"):
        raise ValueError("ocr must be auto or off.")
    if "ocr_lang" in out and not re.fullmatch(r"[A-Za-z_]{2,}(\+[A-Za-z_]{2,})*", out["ocr_lang"] or ""):
        raise ValueError("ocr_lang must be Tesseract language codes joined by +, for example eng or eng+nld.")
    if "restricted_server" in out and out["restricted_server"] not in ("", "ollama", "openai"):
        raise ValueError("restricted_server must be ollama, openai or empty (no local model for restricted documents).")
    if "account_type" in out and out["account_type"] not in ("", "personal", "commercial"):
        raise ValueError("account_type must be personal, commercial or empty.")
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
    if "sync_every_minutes" in out and not 1 <= out["sync_every_minutes"] <= 60:
        raise ValueError("sync_every_minutes must be between 1 and 60.")
    if "themes_k" in out and not 2 <= out["themes_k"] <= 60:
        raise ValueError("themes_k must be between 2 and 60.")
    if "your_name" in out:
        out["your_name"] = " ".join(out["your_name"].split())
        if len(out["your_name"]) > 60:
            raise ValueError("Your name can be at most 60 characters.")
    if "person_id" in out and not re.fullmatch(r"p[0-9a-f]{12}", out["person_id"] or ""):
        raise ValueError("person_id is made by ENLENS itself.")
    if "installation_id" in out and not re.fullmatch(r"[0-9a-f]{16}", out["installation_id"] or ""):
        raise ValueError("installation_id is made by ENLENS itself.")
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
    with LOCK:
        p = home() / "settings.json"
        try:  # the settings as they were, kept beside them: what a damaged file gives way to (`_stored_settings`)
            if isinstance(_read_json(p, tries=1), dict):
                shutil.copyfile(p, p.with_name("settings.json.bak"))
        except (ValueError, OSError):
            pass
        _write_whole(p, json.dumps({"_version": SETTINGS_VERSION, **{k: s.get(k, v) for k, v in DEFAULTS.items()}},
                                   indent=2))


def update_settings(changes: dict) -> dict:
    with LOCK, to_change():  # read, changed and written as one step: two changes at once each kept only its own
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
    elif kind in ("expand", "decompose"):
        user = 4000 + retry
    else:  # 0.13.6: an add-on's kind says how long its prompt can be
        k_ = taskkinds.get(kind)
        user = (k_.size(k, max_chars) if k_ is not None and k_.size else 4000) + retry
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
                               "Ollama has no chat model yet. Download one in Settings → AI (one button).")
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
            raise BackendError("A local model server is running but has no chat model. With Ollama, download one "
                               "in Settings → AI (one button); with another server, load a model in it.")
        raise BackendError("No local model server is running. Install or start Ollama (free) in Settings → AI, one "
                           "button, then download a model there; or open LM Studio, or choose the offline demo in "
                           "Settings.")
    return BaselineBackend(), "baseline"


def main_reads_local(settings: dict) -> bool:
    """Whether the main model may read documents marked "Only a local AI": a model server on this computer (or the
    offline demo), not Claude."""
    from .access import on_this_computer

    b = settings.get("backend", "auto")
    if b in OFF_COMPUTER:
        return False
    if b == "baseline":
        return True
    if b == "openai":
        return on_this_computer(settings.get("openai_url") or "")
    if b == "ollama":
        return on_this_computer(settings.get("ollama_url") or "")
    return True  # auto: detect_local only looks on this computer's addresses (and the configured ones, checked again
    # by the guard when a task is run: see access.backend_levels)


def restricted_choice(settings: dict) -> dict:
    """The local model for documents marked "Only a local AI", as Settings shows it: {"server", "model", "url",
    "same_as_main"} or {} when there is none (those excerpts then wait for a person's judgement)."""
    if main_reads_local(settings):
        return {"same_as_main": True, "server": settings.get("backend"), "model": ""}
    srv, model = settings.get("restricted_server") or "", settings.get("restricted_model") or ""
    if not srv or not model:
        return {}
    url = settings.get("ollama_url") if srv == "ollama" else settings.get("openai_url")
    return {"same_as_main": False, "server": srv, "model": model, "url": url}


def make_restricted_backend(settings: dict):
    """(backend, model) for the tasks of documents marked "Only a local AI" when the main model is Claude, or None
    when no local model is chosen. Raises BackendError when the chosen one is not on this computer."""
    from .access import on_this_computer

    choice = restricted_choice(settings)
    if not choice or choice.get("same_as_main"):
        return None
    if not on_this_computer(choice.get("url") or ""):
        raise BackendError(f"The local model for restricted documents must run on this computer; "
                           f"{choice.get('url')} is another computer.")
    key = "ollama_model" if choice["server"] == "ollama" else "openai_model"
    changed = {**settings, "backend": choice["server"], key: choice["model"], "routing": False}
    be, model = _make_backend(changed, "", ("check", "reread"))
    if model != choice["model"]:
        raise BackendError(f"The local model for restricted documents, {choice['model']}, is not installed on the model "
                           "server. Install it, or choose another one in Settings → AI.")
    be.model_note = None
    if hasattr(be, "memory_guard"):
        be.memory_guard = True  # 0.13.11: it starts beside Claude unasked: never on a computer without room for it
    return be, model


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
    n = re.sub(r"\s+", " ", n)[:60].strip().strip(".")
    return re.sub(r"\.(importing)$", r" \1", n)  # 0.14.3: that ending marks a project zip being imported


def _links(strict: bool = False) -> dict[str, str]:
    """The linked projects. `strict`: before they are changed and written back (`_read_dict`)."""
    return {str(k): str(v) for k, v in _read_dict(home() / "links.json", strict).items()}


def _save_links(links: dict[str, str]) -> None:
    _write_whole(home() / "links.json", json.dumps(links, indent=2))


def list_projects() -> list[str]:
    # 0.14.3: a project zip being imported is unpacked and checked in "<name>.importing" first: not a project yet
    own = {p.name for p in (home() / "projects").iterdir() if (p / "enlens.sqlite").exists()
           and not p.name.endswith(".importing")}
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
    with LOCK:
        links = _links(strict=True)
        if n in links:  # a link whose folder is gone (0.11.1): the new project is made in the data folder, not there
            links.pop(n)
            _save_links(links)
    return Workspace.create(home() / "projects" / n)


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


def close_project(path: str | Path) -> None:
    """0.15.7: forget the project at `path` that open_project keeps, closing its connections in every thread, before
    its folder is moved or removed (Windows refuses while its database is open)."""
    hit = _OPEN.pop(str(Path(path).resolve()), None)
    if hit:
        hit[1].close_all()


def release_open_projects() -> None:
    """0.15.7: close this thread's connections to every project open_project keeps (they reopen on the next use).
    The connector does this after each call on Windows, so a project it read can still be removed in the app while
    Claude Code runs."""
    for _stamp, ws in list(_OPEN.values()):
        ws.close()


def link_existing(path: str, name: str | None = None, clean: bool = False) -> str:
    """Make an existing workspace folder (for example the pilot) appear as a project, without copying it. Roles
    (DESIGN-roles §4.11): it is cleaned as a project from a zip is (`bundle.clean_linked`): always its rows alone
    (triggers and views go) and its config.json. A folder another person made raises NeedsCleaning (what would go:
    `bundle.check_linked`) unless `clean`; with `clean` it also loses its record of a shared folder, the file paths of
    the other computer and what was stored for speed."""
    from . import bundle

    src = Path(path).expanduser().resolve()
    if not (src / "enlens.sqlite").exists():
        raise ValueError(f"No workspace (enlens.sqlite) in {src}.")
    n = safe_name(name or src.name) or "workspace"
    if n in list_projects() or (home() / "projects" / n).exists():
        raise ValueError(f"A project called {n!r} already exists.")
    report = bundle.check_linked(src)
    if report["other"] and not clean:
        who = report["other"].get("name") or "a colleague"
        raise NeedsCleaning(report, f"This folder is {who}’s project. ENLENS will clean it like a project brought in "
                                    "from a file: its record of a shared folder, file paths on the other computer, and "
                                    "what was stored for speed go. The documents and the work stay.")
    close_project(src)  # (a connection this program holds on it: the cleaning writes through its own)
    bundle.clean_linked(src, other=bool(report["other"]))
    with LOCK:
        links = _links(strict=True)
        links[n] = str(src)
        _save_links(links)
    return n


def remove_project(name: str) -> str:
    """Unlink a linked project (its folder is untouched), or move an own project to the trash folder."""
    with LOCK:
        links = _links(strict=True)
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
    close_project(p)  # 0.15.7: Windows cannot move a folder whose database is still open
    trash = home() / "trash"
    trash.mkdir(exist_ok=True)
    dest = trash / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
    move_folder(p, dest)
    return f"moved to {dest}"


class FolderInUse(OSError):
    """0.15.7: a folder could not be moved because a program still has a file in it open (Windows)."""


def move_folder(src: Path, dest: Path, tries: int = 6) -> None:
    """0.15.7: move a project's folder whole. On the same disk a rename, which moves everything or nothing (shutil.move
    copied the folder and then deleted the original, so a file held open on Windows left half a project behind).
    Windows refuses while a program has a file in it open: a connection nobody uses any more is freed and it is tried
    again for a few seconds, then FolderInUse says so in words. Another disk (a data folder moved elsewhere): copied."""
    import gc

    for attempt in range(tries):
        try:
            os.rename(src, dest)
            return
        except PermissionError:
            if os.name != "nt":
                raise
            if attempt == tries - 1:
                raise FolderInUse(f"{src.name} could not be moved: a file in it is still open, in ENLENS or another "
                                  "program (a search index, a sync tool, an antivirus check). Wait a moment and try "
                                  "again.") from None
            gc.collect()
            time.sleep(0.25 * (attempt + 1))
        except OSError:
            shutil.move(str(src), str(dest))
            return


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
        raise ValueError("Choose a model for second opinions in Settings first.")
    if b == "baseline":
        raise ValueError("The offline demo cannot give second opinions. Choose a local model in Settings.")
    key = {"anthropic": "anthropic_model", "openai": "openai_model"}.get(b, "ollama_model")
    changed = {**settings, key: second}
    if b == "auto":
        changed.update(ollama_model=second, openai_model=second)
    be, model = make_backend(changed, api_key, kinds=("second",))
    if model != second:
        raise BackendError(f"The model for second opinions, {second}, is not installed on the model server. Install it, or "
                           "choose another one in Settings.")
    return be, model


# ---------------------------------------------------------------------------------------------
# 0.7: quick looks (one document dropped on the start page), and the model test's speeds
# ---------------------------------------------------------------------------------------------
QUICKLOOK_DAYS = 7


def _quicklooks(strict: bool = False) -> dict[str, dict]:
    """The quick looks not kept yet. `strict`: before they are changed and written back (`_read_dict`)."""
    return _read_dict(home() / "quicklook.json", strict)


def mark_temporary(name: str, **about) -> None:
    """Note a project as temporary (a quick look, a model test's scratch copy): it goes to the trash after
    QUICKLOOK_DAYS days unless it is kept."""
    with LOCK:
        data = _quicklooks(strict=True)
        data[name] = {"created_at": time.time(), **about}
        _save_quicklooks(data)


def forget_temporary(name: str) -> bool:
    """Take a project off the list of temporary ones (it was kept, or it is gone). Whether it was on it."""
    with LOCK:
        data = _quicklooks(strict=True)
        if name not in data:
            return False
        del data[name]
        _save_quicklooks(data)
        return True


def _save_quicklooks(data: dict) -> None:
    _write_whole(home() / "quicklook.json", json.dumps(data, indent=2))


def create_quicklook(filename: str, came_from: str | None = None) -> Workspace:
    """A temporary project named after a file, for a quick look at one document. It is moved to the trash after
    QUICKLOOK_DAYS days unless it is kept (`keep_project`)."""
    stem = re.sub(r"\.(pdf|docx|html?|txt|md|zip)$", "", Path(filename or "document").name, flags=re.I)
    name = unique_project_name(stem or "Quick look")
    ws = create_project(name)
    mark_temporary(ws.root.name, file=Path(filename or "").name, **{"from": came_from})
    return ws


def is_temporary(name: str) -> dict | None:
    """{created_at, expires_at, file} for a quick look not kept yet, else None."""
    q = _quicklooks().get(name)
    if not q:
        return None
    return {**q, "expires_at": q.get("created_at", 0) + QUICKLOOK_DAYS * 86400}


def quicklook_origin(name: str) -> str | None:
    """The project a quick look was opened from (0.17: its codebooks can be used there), if it is still a project.
    A quick look opened from another quick look comes from that one's project."""
    q = _quicklooks().get(name)
    src = q.get("from") if q else None
    if src in _quicklooks():  # opened while another quick look was the open project
        src = _quicklooks()[src].get("from")
    if not src or src == name or src not in list_projects():
        return None
    return src


def keep_project(name: str) -> bool:
    return forget_temporary(name)


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
        except FolderInUse:
            # 0.15.7: tried again later, not forgotten (it stayed a project for good). Removing it took it off the
            # list before the move was tried: it goes back on, as the list is now (not as it was read above: what
            # another request or a model test noted meanwhile was written over)
            with LOCK:
                now = _quicklooks(strict=True)
                if name not in now:
                    now[name] = q
                    _save_quicklooks(now)
            continue
        except (KeyError, OSError):
            pass
        forget_temporary(name)  # (written only when it was still on the list: not on every /api/state, 0.11.1)
    return moved


def record_benchmark(model: str, kinds: dict) -> None:
    """Keep the model test's median seconds per task of each kind (estimates of long runs use them)."""
    p = home() / "benchmarks.json"
    with LOCK:
        data = _read_dict(p, strict=True)
        data.setdefault(model, {}).update({k: v.get("seconds_median") for k, v in kinds.items()
                                           if v.get("seconds_median")})
        _write_whole(p, json.dumps(data, indent=2))


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


# roles (DESIGN-roles §4.11): stubs of the groundwork (S0), built in P3. Nothing calls them yet
class NeedsCleaning(ValueError):
    """A folder to link was made by another person: the page asks before it is cleaned like an import (`report`:
    what `bundle.check_linked` found)."""

    def __init__(self, report: dict, message: str = "This folder was made by another person: clean it first.") -> None:
        super().__init__(message)
        self.report: dict = report


def _place() -> str:
    """Where this data folder is, as the file system knows it (device and folder number): a copy of the folder, on
    this computer or another, or one restored from a backup, is somewhere else. "" when the file system has no numbers."""
    try:
        st = os.stat(home())
    except OSError:
        return ""
    return f"{st.st_dev}:{st.st_ino}" if st.st_ino else ""


def installation_id() -> str:
    """This installation's own id (the setting `installation_id`, 16 hex digits, made once; never in a move zip). A
    data folder copied to another computer (or restored, or moved) gets a new one there: the shared folder's guard
    (sync/folder.py) then tells the two computers apart. A new id alone never stops a round: the guard also looks at
    this copy's own record of the folder."""
    import secrets

    def mine(s: dict) -> str | None:
        iid, place = str(s.get("installation_id") or ""), str(s.get("installation_place") or "")
        here = _place()
        return iid if re.fullmatch(r"[0-9a-f]{16}", iid) and (place == here or not here) else None

    iid = mine(load_settings())
    if iid:
        return iid
    with LOCK:  # made once: two requests at once must not each make their own
        with to_change():
            iid = mine(load_settings())
        if not iid:
            iid = secrets.token_hex(8)
            update_settings({"installation_id": iid, "installation_place": _place()})
    return iid


def new_identity(name: str) -> str:
    """*Use both computers* (DESIGN-roles §4.11, §5.6): this computer becomes a person of its own in every project, a
    new person id with the name given. What was done here so far keeps the first id, so it is shown as the other
    computer's work (the owner can mark both as one person: `ownership.set_same_as`). Returns the new id."""
    import uuid

    clean = " ".join(str(name or "").split())
    if not clean:
        raise ValueError("Give the name you use on this computer.")
    with LOCK:
        pid = "p" + uuid.uuid4().hex[:12]
        update_settings({"person_id": pid, "your_name": clean})
    return pid
