"""Live progress of a check: which step is running, and what the model is doing right now.

A check reports its steps (decomposition, then per claim: search terms, passages, grading) and the local model
reports every second while it works (loading and reading the prompt, reasoning, or writing its answer, with tokens,
speed and the latest words). `Tracker` keeps both as plain data for the app, which polls it; `model_line` turns a
model report into one line of text for the command line and the app.
"""
from __future__ import annotations

import threading
import time

STEPS = [("terms", "Other wordings"), ("rank", "Finding excerpts"), ("grade", "Reading the excerpts")]
PHASE = {"waiting": "loading the model and reading the prompt", "thinking": "reasoning",
         "writing": "writing its answer", "done": "finished"}
PLAIN_PHASE = {"waiting": "The AI is getting ready and reading", "thinking": "The AI is thinking it over",
               "writing": "The AI is writing down its judgement", "done": "The AI has finished"}


def _secs(s: float) -> str:
    s = int(round(s))
    return f"{s} s" if s < 90 else f"{s // 60} min {s % 60:02d} s"


def model_line(info: dict) -> str:
    """One line on what the model is doing, from the backend's progress report."""
    if info.get("phase") == "done" and info.get("stats"):
        st = info["stats"]
        parts = []
        if st.get("load_seconds", 0) >= 1:
            parts.append(f"loaded the model in {_secs(st['load_seconds'])}")
        if st.get("prompt_tokens") and st.get("prompt_seconds"):
            rate = st["prompt_tokens"] / st["prompt_seconds"] if st.get("prompt_seconds") else None
            parts.append(f"read {st['prompt_tokens']:,} prompt tokens in {_secs(st['prompt_seconds'])}"
                         + (f" ({rate:,.0f}/s)" if rate else ""))
        if st.get("output_tokens"):
            if st.get("output_seconds"):
                rate = st["output_tokens"] / st["output_seconds"]
                parts.append(f"wrote {st['output_tokens']:,} tokens in {_secs(st['output_seconds'])} ({rate:,.1f}/s)")
            else:
                parts.append(f"wrote {st['output_tokens']:,} tokens")
        return "Model finished: " + ", ".join(parts) if parts else "Model finished."
    phase = info.get("phase", "waiting")
    text = f"Model is {PHASE.get(phase, phase)} · {_secs(info.get('seconds', 0))}"
    if phase == "waiting":
        text += f" · prompt of about {info.get('prompt_tokens', 0):,} tokens"
        if info.get("seconds", 0) > 120:
            text += " · slow start: the model may still be loading, or the computer is short of memory"
    else:
        if info.get("thinking_tokens"):
            text += f" · {info['thinking_tokens']:,} reasoning tokens"
        if info.get("answer_tokens"):
            text += f" · {info['answer_tokens']:,} answer tokens"
        if info.get("rate"):
            text += f" · {info['rate']:.1f} tokens/s"
        if info.get("budget_reached"):
            text += " · reasoning budget used up: answering from its notes now"
        elif info.get("budget") and phase == "thinking":
            text += f" · reasoning budget {info['budget']:,} tokens"
        used = info.get("thinking_tokens", 0) + info.get("answer_tokens", 0)
        if not info.get("budget") and info.get("cap") and used > 0.6 * info["cap"]:
            text += f" · {used:,} of at most {info['cap']:,} tokens used"
    return text


class Tracker:
    """Collects step and model reports of one check (or a batch of checks) as data the app can poll.

    Use `step` as the check's progress callback and `model_report` as the backend's.
    """

    def __init__(self, expand: bool = True, clock=time.time, steps: tuple[str, ...] | None = None):
        self.clock = clock
        self.expand = expand
        self.only = steps  # the steps this kind of job has (default: all of a check)
        self.t0 = clock()
        self.lock = threading.Lock()
        self.decompose: dict | None = None
        self.parts: list[dict] = []
        self.model: dict | None = None
        self.message = "Starting"
        self.batch: dict | None = None
        self._part_key = None
        self.ended: float | None = None

    def finish(self) -> None:
        """Freeze the clocks: the elapsed times stay as they were when the work ended."""
        with self.lock:
            self.ended = self.ended or self.clock()

    def _part(self, info: dict) -> dict:
        key = (info.get("index"), info.get("part", 0))
        if key != self._part_key or not self.parts:
            if self.parts and key[0] != (self._part_key or (None,))[0]:
                self.parts = []  # the next hypothesis of a batch
            self._part_key = key
            steps = {k: {"label": label, "state": "pending", "detail": "", "seconds": None}
                     for k, label in STEPS if (self.expand or k != "terms") and (self.only is None or k in self.only)}
            self.parts.append({"part": info.get("part", 0), "text": info.get("claim"), "steps": steps})
        return self.parts[-1]

    def step(self, kind: str, msg: str, info: dict | None = None) -> None:
        info = info or {}
        with self.lock:
            now = self.clock()
            if kind == "item":
                self.batch = {"index": info.get("index"), "total": info.get("total"), "text": info.get("text")}
                self.decompose, self.parts, self._part_key, self.model = None, [], None, None
                self.message = msg
                return
            key = kind.removesuffix("_done")
            done = kind.endswith("_done")
            if key == "decompose":
                if done and self.decompose is None:  # parts chosen by the person: nothing was split
                    self.decompose = {"label": "Parts to check", "state": "done", "detail": msg, "t0": now,
                                      "seconds": 0.0, "parts": info.get("parts")}
                elif done:
                    self.decompose.update(state="done", detail=msg, seconds=now - self.decompose["t0"],
                                          parts=info.get("parts"))
                else:
                    self.decompose = {"label": "Splitting into parts", "state": "running", "detail": msg, "t0": now,
                                      "seconds": None}
                self.message = msg
                return
            part = self._part(info)
            s = part["steps"].get(key)
            if s is None:
                return
            if done:
                s.update(state="done", detail=msg, seconds=now - (s.get("t0") or now))
                if info:
                    s["info"] = {k: v for k, v in info.items() if k not in ("part", "parts", "claim", "index")}
            else:
                s.update(state="running", detail=msg, t0=now)
                self.model = None
            self.message = msg

    def model_report(self, info: dict) -> None:
        with self.lock:
            self.model = dict(info)

    def state(self) -> dict:
        with self.lock:
            now = self.ended or self.clock()
            parts = []
            for p in self.parts:
                steps = []
                for k, s in p["steps"].items():
                    secs = s["seconds"] if s["state"] == "done" else (now - s["t0"] if s.get("t0") else None)
                    steps.append({"key": k, "label": s["label"], "state": s["state"], "detail": s["detail"],
                                  "seconds": round(secs, 1) if secs is not None else None, **({"info": s["info"]} if
                                                                                                s.get("info") else {})})
                parts.append({"part": p["part"], "text": p["text"], "steps": steps})
            dec = None
            if self.decompose:
                d = self.decompose
                secs = d["seconds"] if d["state"] == "done" else now - d["t0"]
                dec = {"label": d["label"], "state": d["state"], "detail": d["detail"], "seconds": round(secs, 1),
                       "parts": d.get("parts")}
            model = None
            if self.model and self.model.get("phase") == "queue":  # 0.8: the work waits in the queue for Claude Code
                m = self.model
                model = {"phase": "queue", "seconds": round(float(m.get("seconds") or 0), 1),
                         "plain": m.get("text") or "Waiting for Claude Code",
                         "line": m.get("paused_text") or f"To answer it, type {m.get('command', '/enlens-run')} in "
                                                         "Claude Code.",
                         "queue": {k: m.get(k) for k in ("waiting", "being_answered", "estimate", "paused",
                                                          "paused_text", "command", "privacy")}}
            elif self.model:
                m = self.model
                model = {k: m.get(k) for k in ("phase", "prompt_tokens", "thinking_tokens", "answer_tokens", "cap", "thinks")}
                model["seconds"] = round(float(m.get("seconds") or 0), 1)
                model["rate"] = round(m["rate"], 1) if m.get("rate") else None
                model["tail"] = " ".join((m.get("tail") or "").split())[-240:]
                model["line"] = model_line(m)
                model["plain"] = PLAIN_PHASE.get(m.get("phase") or "waiting", "The AI is working")
                if model["phase"] == "waiting" and model["seconds"] > 60:
                    model["plain"] += " (a model on your own computer can take a few minutes to start)"
            return {"message": self.message, "elapsed": round(now - self.t0, 1), "decompose": dec, "parts": parts,
                    "model": model, "batch": dict(self.batch) if self.batch else None}

    def summary(self) -> str:
        """One line with the time each step took, for the command line."""
        st = self.state()
        bits = []
        if st["decompose"]:
            bits.append(f"splitting {_secs(st['decompose']['seconds'])}")
        for p in st["parts"]:
            for s in p["steps"]:
                if s["state"] == "done" and s["seconds"] is not None:
                    bits.append(f"{s['label'].lower()} {_secs(s['seconds'])}")
        return " · ".join(bits)
