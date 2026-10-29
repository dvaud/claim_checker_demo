"""A fake Claude Code for tests (0.8): plays /enlens-run through the connector's queue tools.

It does what the plugin's orchestrator and helpers do: queue_status, then for every group next_tasks with the group's
kind and model, an answer for every task, submit_answers, and a fix of every task reported with problems. The answers
come from the fake model's canned answers (fake_servers._answer), so they follow the text; the first answer of each
kind that has quotes carries a wrong quote, to prove that a wrong quote is sent back and answered again.

    run(project)                      # through an in-process connector (mcp.Client on build_server())
    run(project, tools=DirectTools()) # straight on the queue functions (no MCP package needed)
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import fake_servers  # noqa: E402

WRONG = "a quote that is nowhere in the text"


def _spoil(obj):
    """The same answer with its first quote replaced by words that are not in the text (None: it has no quote)."""
    obj = copy.deepcopy(obj)

    def walk(x):
        if isinstance(x, dict):
            for k in ("quote", "quote_a", "span"):
                if isinstance(x.get(k), str) and x[k]:
                    x[k] = WRONG
                    return True
            return any(walk(v) for v in x.values())
        if isinstance(x, list):
            return any(walk(v) for v in x)
        return False

    return obj if walk(obj) else None


class DirectTools:
    """The four queue tools without MCP: the same functions the connector calls."""

    def __init__(self):
        from enlens_claims import home, taskqueue

        self.home, self.q = home, taskqueue

    def _ws(self, project):
        return self.home.open_project(project)

    def queue_status(self, project):
        ws = self._ws(project)
        self.q.advance(ws)
        return self.q.status(ws, project)

    def next_tasks(self, project, kind=None, n=None, model=None, taken_by=None, helper=None):
        return self.q.next_tasks(self._ws(project), kind, n, model, taken_by, helper)

    def submit_answers(self, claim, answers, project=None):
        for name in self.home.list_projects():
            ws = self.home.open_project(name)
            if ws.scalar("SELECT 1 FROM task_claims WHERE claim_id=?", (claim,)):
                return self.q.submit(ws, claim, answers)
        raise KeyError(claim)

    def release(self, claim):
        for name in self.home.list_projects():
            ws = self.home.open_project(name)
            if ws.scalar("SELECT 1 FROM task_claims WHERE claim_id=?", (claim,)):
                return self.q.release(ws, claim)
        raise KeyError(claim)


class McpTools:
    """The four queue tools through an MCP client connected to the ENLENS connector. The client lives in one task of
    an event loop on its own thread (its context must be entered and left in the same task); calls go to it."""

    def __init__(self, client, loop):
        self.c, self.loop = client, loop

    def _call(self, name, args):
        fut = asyncio.run_coroutine_threadsafe(
            self.c.call_tool(name, {k: v for k, v in args.items() if v is not None}), self.loop)
        r = fut.result(120)
        if r.is_error:
            raise RuntimeError(r.content[0].text)
        return json.loads(r.content[0].text)

    def queue_status(self, project):
        return self._call("queue_status", {"project": project})

    def next_tasks(self, project, kind=None, n=None, model=None, taken_by=None, helper=None):
        return self._call("next_tasks", {"project": project, "kind": kind, "n": n, "model": model, "taken_by": taken_by,
                                         "helper": helper})

    def submit_answers(self, claim, answers, project=None):
        return self._call("submit_answers", {"claim": claim, "answers": answers})

    def release(self, claim):
        return self._call("release", {"claim": claim})


class FakeClaudeCode:
    """One Claude Code session. `answer(kind, system, prompt, model)` makes the answers (default: the fake model);
    `wrong_first`: spoil the first answer of each kind; `stop_after`: stop after this many batches (a usage limit)
    without answering the last batch taken (it stays claimed and lapses)."""

    def __init__(self, tools, name="session-1", wrong_first=True, answer=None, stop_after=None):
        self.tools, self.name = tools, name
        self.wrong_first = wrong_first
        self.spoiled: set[str] = set()
        self.answer = answer or (lambda kind, system, prompt, model: fake_servers._answer(system, prompt))
        self.stop_after = stop_after
        self.batches = 0
        self.log: list[dict] = []   # one entry per batch: kind, model, helper, tasks, stored, problems

    def batch(self, project, kind=None, model=None, helper=None) -> dict | None:
        """Take one batch and answer it (fixing problems); None when nothing waits."""
        got = self.tools.next_tasks(project, kind=kind, model=model, taken_by=f"{self.name}", helper=helper)
        if not got.get("claim"):
            return None
        self.batches += 1
        entry = {"claim": got["claim"], "kind": got["kind"], "model": got["model"], "helper": got["helper"],
                 "tasks": [t["task_id"] for t in got["tasks"]], "stored": 0, "problems": 0, "resent": 0}
        self.log.append(entry)
        if self.stop_after is not None and self.batches > self.stop_after:
            entry["abandoned"] = True
            return entry
        answers = []
        good = {}
        for t in got["tasks"]:
            obj = self.answer(got["kind"], got["system"], t["prompt"], got["model"])
            good[t["task_id"]] = obj
            if self.wrong_first and got["kind"] not in self.spoiled:
                bad = _spoil(obj)
                if bad is not None:
                    self.spoiled.add(got["kind"])
                    answers.append({"task_id": t["task_id"], "answer": bad})
                    continue
            answers.append({"task_id": t["task_id"], "answer": obj})
        r = self.tools.submit_answers(got["claim"], answers)
        entry["stored"] += r["stored"]
        entry["problems"] += r["with_problems"]
        for _round in range(3):
            if not r["open"]:
                break
            # a real helper would read the problems and fix the answer; the fake answers again, with the problems
            # listed in the prompt as ENLENS shows them on a retry, which gives the right answer
            again = []
            for tid in r["open"]:
                again.append({"task_id": tid, "answer": good[tid]})
            entry["resent"] += len(again)
            r = self.tools.submit_answers(got["claim"], again)
            entry["stored"] += r["stored"]
        return entry

    def run(self, project, kind=None, max_batches=500) -> dict:
        """/enlens-run <project> [kind]: work through the groups until nothing waits."""
        while self.batches < max_batches:
            st = self.tools.queue_status(project)
            groups = [g for g in st["groups"] if kind is None or g["kind"] == kind]
            if not groups:
                break
            g = groups[0]
            e = self.batch(project, g["kind"], g["model"], g.get("helper"))
            if e is None or e.get("abandoned"):
                break
        return {"batches": self.batches, "log": self.log}


def run(project, kind=None, tools=None, **kw) -> dict:
    """Play /enlens-run once, through an in-process connector unless `tools` is given."""
    if tools is not None:
        return FakeClaudeCode(tools, **kw).run(project, kind)
    import threading

    from mcp import Client

    from enlens_claims.mcp_server import build_server

    loop = asyncio.new_event_loop()
    ready, done = threading.Event(), None
    box: dict = {}

    async def hold():
        nonlocal done
        done = asyncio.Event()
        async with Client(build_server()) as client:
            box["client"] = client
            ready.set()
            await done.wait()

    th = threading.Thread(target=lambda: loop.run_until_complete(hold()), daemon=True)
    th.start()
    if not ready.wait(30):
        raise RuntimeError("the connector did not start")
    try:
        return FakeClaudeCode(McpTools(box["client"], loop), **kw).run(project, kind)
    finally:
        loop.call_soon_threadsafe(done.set)
        th.join(30)
        loop.close()
