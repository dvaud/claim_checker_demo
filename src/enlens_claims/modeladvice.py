"""0.18.0rc2 (M8): which local model to suggest on THIS computer.

Until now every computer was offered the same model (qwen3:8b, about 5 GB). Here a small pure function, `advise`, takes
what the computer has (memory, free disk space, the system, a graphics card's memory) and gives, for reading and
judging ("chat") and for search by meaning ("embed"), one recommended model with a smaller, quicker one and a larger,
more careful one beside it, each in plain words: its download size, how quick it will be here and what it is good for.
A model is offered only when it fits the memory and the disk with room to spare (the same measure the app uses before it
starts a model: the size of the model plus the memory its context needs, llm.KV_BYTES_PER_TOKEN).

`computer()` reads the facts (cheap, kept for a minute: the page asks every few seconds); `advise()` decides and does no
reading, so it can be tested with made-up computers."""
from __future__ import annotations

import os
import shutil
import subprocess
import time

GB = 1 << 30
# the context the advice reckons with: the app's smallest working length (llm.py: it picks the smallest that fits)
CONTEXT_TOKENS = 8192
# a model is offered when what it needs is at most this share of the memory it would run in ("room to spare": the system,
# the browser and the documents need the rest); the recommended one stays within COMFORT, a larger one may go to TIGHT
COMFORT = 0.5
TIGHT = 0.65
GPU_SHARE = 0.9          # of a graphics card's own memory a model may take
DISK_MARGIN = 2 * GB     # free space to leave after the download
SMALL_DISK_SHARE = 1.2   # a download is unpacked beside the files Ollama already holds

# Ollama's library, sizes as the library lists them (4-bit builds). `good` is for a researcher who does not program.
CHAT = (
    {"name": "qwen3:1.7b", "bytes": int(1.4 * GB), "label": "small",
     "good": "Short, simple checks. It misses more and can misread a long passage."},
    {"name": "qwen3:4b", "bytes": int(2.6 * GB), "label": "small",
     "good": "Everyday checks on a modest computer: careful enough for a first look at your documents."},
    {"name": "qwen3:8b", "bytes": int(5.2 * GB), "label": "medium",
     "good": "A good balance: it reads and judges passages well, and is the one most people choose."},
    {"name": "qwen3:14b", "bytes": int(9.3 * GB), "label": "large",
     "good": "The most careful: best for long or difficult passages, and the slowest."},
)
EMBED = (
    {"name": "nomic-embed-text", "bytes": int(0.3 * GB), "label": "small",
     "good": "Search by meaning for documents in English. Small and quick."},
    {"name": "bge-m3", "bytes": int(1.2 * GB), "label": "medium",
     "good": "Search by meaning across many languages (Hungarian, Dutch, German and more), more precise; a bigger download."},
)
WHAT_IS_A_MODEL = ("A model is the program that does the reading and judging. It is one large file kept on this "
                   "computer, so nothing you read with it leaves the computer; a bigger model reads more carefully, "
                   "but needs more memory and answers more slowly.")


def computer(home_dir: str | None = None) -> dict:
    """What this computer has: {"memory", "disk_free", "system", "unified", "gpu"} (bytes; None when it cannot be read).
    `unified`: a Mac with Apple silicon, where the graphics memory is the same memory. `gpu`: the memory of the largest
    NVIDIA card where `nvidia-smi` is installed (asked once a minute, quickly), else None."""
    now = time.time()
    hit = _FACTS.get(home_dir)
    if hit and now - hit[0] < 60:
        return dict(hit[1])
    from . import llm
    from .installation import system

    name = system()
    where = home_dir or os.path.expanduser("~")
    try:
        free = shutil.disk_usage(where).free
    except OSError:
        free = None
    facts = {"memory": llm.total_memory(), "disk_free": free, "system": name,
             "unified": name == "mac" and _machine() in ("arm64", "aarch64"), "gpu": _gpu_memory(name)}
    _FACTS[home_dir] = (now, facts)
    return dict(facts)


_FACTS: dict = {}


def _machine() -> str:
    import platform

    return platform.machine().lower()


def _gpu_memory(system: str) -> int | None:
    """The memory of the largest NVIDIA graphics card, only where `nvidia-smi` is on the computer (Windows, Linux)."""
    if system == "mac" or not shutil.which("nvidia-smi"):
        return None
    from .procs import no_window

    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=3, **no_window()).stdout
        mib = [int(x) for x in out.split() if x.strip().isdigit()]
        return max(mib) * (1 << 20) if mib else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _need(model: dict, use: str) -> int:
    """What running the model asks of the memory: its size, and for a chat model the memory its context takes."""
    from .llm import KV_BYTES_PER_TOKEN

    return model["bytes"] + (CONTEXT_TOKENS * KV_BYTES_PER_TOKEN if use == "chat" else 0)


def _gb(n: int) -> str:
    n = n / GB
    return f"{round(n)} GB" if n >= 10 or abs(n - round(n)) < 0.05 else f"{n:.1f} GB"


def _size_text(n: int) -> str:
    return f"about {_gb(n)}"


def _fit(model: dict, use: str, facts: dict) -> dict | None:
    """How `model` would run here, or None when it does not fit the memory or the disk with room to spare:
    {"where": "graphics card" | "memory", "share": how much of that memory it takes}."""
    mem, gpu, disk = facts.get("memory"), facts.get("gpu"), facts.get("disk_free")
    if disk is not None and disk < model["bytes"] * SMALL_DISK_SHARE + DISK_MARGIN:
        return None
    need = _need(model, use)
    options = []
    if gpu and need <= GPU_SHARE * gpu:
        options.append({"where": "graphics card", "share": need / gpu})
    if mem is None:
        return options[0] if options else {"where": "memory", "share": 0.0}   # cannot tell: not refused (the app checks again at the start)
    if need <= TIGHT * mem:
        options.append({"where": "memory", "share": need / mem})
    # the graphics card when the model sits comfortably in it, else wherever it takes the smaller share
    return next((o for o in options if o["share"] <= COMFORT), min(options, key=lambda o: o["share"], default=None))


def _speed(model: dict, use: str, facts: dict, fit: dict) -> tuple[str, str]:
    """(how quick, in words): quick on a graphics card or on a Mac's own memory, else by the size of the model."""
    if use == "embed":
        return "quick", "Quick: it only has to read each passage once, when search by meaning is set up."
    if fit["where"] == "graphics card":
        return "quick", "Quick: it runs on your graphics card. An answer takes seconds."
    if facts.get("unified"):
        big = model["bytes"] > 8 * GB
        return ("fair", "Fair: about half a minute for an answer on this Mac.") if big else \
            ("quick", "Quick: it runs on this Mac's own memory. An answer takes seconds.")
    gb = model["bytes"] / GB
    if gb <= 2:
        return "fair", "Fair: it runs on the processor, about half a minute for an answer."
    if gb <= 3:
        return "fair", "Fair: it runs on the processor, about a minute for an answer."
    return "slow", "Slow: it runs on the processor, a few minutes for a long answer. Fine for a check you leave running."


def _option(model: dict, use: str, role: str, facts: dict, fit: dict) -> dict:
    speed, speed_text = _speed(model, use, facts, fit)
    share = fit["share"]
    return {"name": model["name"], "use": use, "role": role, "size": _size_text(model["bytes"]), "bytes": model["bytes"],
            "speed": speed, "speed_text": speed_text, "good_for": model["good"], "tight": share > COMFORT,
            "note": ("It takes most of this computer's memory: close other programs while it works."
                     if share > COMFORT else "")}


def _ladder(rungs: tuple, use: str, facts: dict) -> dict:
    """The recommended rung and its neighbours, from the ones that fit."""
    fits = [(m, _fit(m, use, facts)) for m in rungs]
    ok = [(i, m, f) for i, (m, f) in enumerate(fits) if f]
    if not ok:
        need = rungs[0]["bytes"]
        disk, mem = facts.get("disk_free"), facts.get("memory")
        if disk is not None and disk < need * SMALL_DISK_SHARE + DISK_MARGIN:
            why = (f"There is not enough free disk space for even the smallest model ({_size_text(need)}): this computer "
                   f"has {_gb(disk)} free. Free some space and try again.")
        else:
            why = (f"This computer has {_gb(mem or 0)} of memory, which is too little for a local model that reads "
                   "well. Use Claude instead (Settings → AI), or a computer with more memory.")
        return {"pick": None, "smaller": None, "larger": None, "options": [], "reason": why}
    comfy = [t for t in ok if t[2]["share"] <= COMFORT] or ok[:1]
    pi, pm, pf = comfy[0] if use == "embed" else comfy[-1]   # search by meaning starts with the small one
    pick = _option(pm, use, "recommended", facts, pf)
    smaller = next((_option(m, use, "smaller", facts, f) for i, m, f in reversed(ok) if i < pi), None)
    larger = next((_option(m, use, "larger", facts, f) for i, m, f in ok if i > pi), None)
    options = [o for o in (smaller, pick, larger) if o]
    return {"pick": pick, "smaller": smaller, "larger": larger, "options": options, "reason": ""}


def advise(facts: dict) -> dict:
    """The advice for a computer described by `facts` ({"memory", "disk_free", "system", "unified", "gpu"}; any may be
    None). {"computer": {...in words...}, "chat": ladder, "embed": ladder, "what_is_a_model"}; a ladder is {"pick",
    "smaller", "larger", "options", "reason"} where `reason` says why nothing is offered."""
    chat = _ladder(CHAT, "chat", facts)
    embed = _ladder(EMBED, "embed", facts)
    parts = []
    if facts.get("memory"):
        parts.append(f"{_gb(facts['memory'])} of memory")
    if facts.get("gpu"):
        parts.append(f"a graphics card with {_gb(facts['gpu'])}")
    elif facts.get("unified"):
        parts.append("Apple silicon (the graphics use the same memory)")
    if facts.get("disk_free") is not None:
        parts.append(f"{_gb(facts['disk_free'])} free disk space")
    words = "This computer has " + ", ".join(parts) + "." if parts else ""
    return {"computer": {"memory": facts.get("memory"), "disk_free": facts.get("disk_free"), "gpu": facts.get("gpu"),
                         "system": facts.get("system"), "unified": bool(facts.get("unified")), "words": words},
            "chat": chat, "embed": embed, "what_is_a_model": WHAT_IS_A_MODEL}


def suggested(advice: dict | None = None) -> list[dict]:
    """The recommended models in the old shape of `llm.SUGGESTED_MODELS` ({"name", "use", "size"}), for the page's
    one-button download; falls back to those when the computer cannot be read."""
    from . import llm

    try:
        adv = advice or advise(computer())
    except Exception:  # noqa: BLE001 - the advice is a convenience: never break the card
        return [dict(m) for m in llm.SUGGESTED_MODELS]
    out = []
    for use in ("chat", "embed"):
        pick = adv[use]["pick"]
        if pick:
            out.append({"name": pick["name"], "use": use, "size": pick["size"]})
    return out
