"""Model routing (0.8, G3): which model answers each kind of task, and when a task goes up to a stronger one.

Each task kind has a default model. The cheap model answers first; a task it finds hard goes up one step, once:

- when its answer's certainty is under STEP_UP_BELOW (the lowest confidence among the labels, links or excerpt
  judgements it gives; an answer that lists nothing, or a kind without confidences, never steps up this way);
- when two answers in a row were rejected (a quote not found, a code that does not exist): the third and last
  attempt goes to the stronger model;
- when a person asks for it ("Ask a stronger model").

The same table serves the three routes:

- Claude Code (the researcher's own plan): the queue hands each kind to a helper agent of the ENLENS plugin, on the
  model named here (`haiku`, `sonnet`, `opus`, `fable`);
- the Claude API (a shared installation with the team's key): the same aliases, as API model ids;
- local models: "the small model" (label, link) and "the large model" (the rest); with no small model chosen, the
  large one does everything and nothing steps up, exactly as in 0.7.

The SDG / value chain pack's kinds (extract, split, verify, verify_set) are routed too, but only for tasks that are
in the queue (`enlens prepare extract|split|verify-vca|verify-claims|audit-vca`): `enlens run` and the file queue
answer them with the model on the task, as before. A second-model audit of the pack (audit-vca, verify-claims) has
the role "audit" (`tasks.role`): it is routed as "audit", like a second opinion, never as the kind it uses.

A backend carries its `Router` (`backend.router`); `tasks.run_one` asks it for the model of each task. A backend
without one (the command line with --model, the tests of 0.7) answers with the model it is given, as before.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import taskkinds

STEP_UP_BELOW = 0.6

# 0.13.6: the kinds the router knows, their models and helpers, and Settings' rows are views of the registry
# (taskkinds.py), so a kind an add-on registers is routed like ENLENS's own. "audit" is a role (a second-model audit
# of the SDG pack's answers, see `task_kind`), not a kind of task.
SDG_KINDS = ("split", "extract", "verify", "verify_set")
KINDS = taskkinds.Names(lambda k: k.claude is not None)
# how the Settings table groups them (one row each): (row, its kinds, its title)
ROWS = taskkinds.Rows()
ROW_OF = taskkinds.Table("row")

ALIASES = ("haiku", "sonnet", "opus", "fable")
# the Claude API's ids for the aliases (Models overview, October 2026); "opus" follows Settings' anthropic_model
API_IDS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5",
           "fable": "claude-fable-5-1"}
LADDER = ("haiku", "sonnet", "opus")

# kind: (first model, the model it steps up to; "auditor" = Opus, or Fable when the researcher switched it on).
# The reasons for each choice are with the kinds, in taskkinds.py.
CLAUDE_DEFAULTS = taskkinds.Table("claude")
LOCAL_DEFAULTS = taskkinds.Table("local")

# the helper agents of the Claude Code plugin (G2), by kind; a stepped-up check goes to the auditor
HELPERS = taskkinds.Table("helper")
HELPER_MODEL = taskkinds.HelperModels({"enlens-labeller": "haiku", "enlens-linker": "haiku", "enlens-namer": "sonnet",
                                       "enlens-reader": "sonnet", "enlens-extractor": "sonnet",
                                       "enlens-checker": "sonnet", "enlens-auditor": "opus"})
# the kinds whose stepped-up tasks go to the auditor (they judge excerpts, or set the reference claims)
TO_AUDITOR = taskkinds.Names(lambda k: k.to_auditor)

ROUTE_NAMES = {"claude_code": "Claude Code", "anthropic": "Claude API", "local": "local model server",
               "ollama": "local model server", "baseline": "offline demo", "file": "file queue",
               "chat": "Claude app (connector)"}
OFF_COMPUTER = frozenset({"anthropic", "claude_code"})   # the backends whose passages leave this computer


def route_of(backend_name: str) -> str:
    """The route family of a backend name: claude_code, anthropic, local (Ollama and other local servers) or
    baseline."""
    if backend_name in ("claude_code", "anthropic", "baseline"):
        return backend_name
    return "local"


def task_kind(t) -> str:
    """The kind a task is routed as: its role when it has one ("audit"), else its kind. `t`: a task row or dict."""
    try:
        role = t["role"]
    except (KeyError, IndexError):
        role = None
    return role or t["kind"]


def certainty(kind: str, obj) -> float | None:
    """The certainty of an answer: the lowest confidence it gives (labels, links, excerpt judgements); None when it
    gives none (an empty answer, or a kind without confidences)."""
    if not isinstance(obj, dict):
        return None
    k = taskkinds.get(kind)
    items = k.certainty if k else None  # 0.13.6: the answer's list whose items carry a confidence, from the registry
    if items == ".":  # one verdict with its confidence (verify)
        c = obj.get("confidence")
        return float(c) if isinstance(c, (int, float)) and not isinstance(c, bool) else None
    if not items:
        return None
    confs = []
    for x in obj.get(items) or []:
        if isinstance(x, dict) and isinstance(x.get("confidence"), (int, float)):
            confs.append(float(x["confidence"]))
    return min(confs) if confs else None


@dataclass
class Router:
    """The model of each task on one route. `overrides`: {kind or row: model} chosen in Settings."""

    route: str                       # claude_code | anthropic | local | baseline
    fable: bool = False              # the auditor runs on Fable (Claude routes) when switched on
    overrides: dict = field(default_factory=dict)
    large: str = ""                  # local: the main model
    small: str = ""                  # local: the small model ("" = the large one)
    second: str = ""                 # local: the second model of Settings
    opus_id: str = API_IDS["opus"]   # the Claude API's id for "opus" (Settings' anthropic_model)

    # -- the table ------------------------------------------------------------------------------
    def _auditor(self) -> str:
        return "fable" if self.fable else "opus"

    def first(self, kind: str) -> str | None:
        """The model a task of this kind starts on (an alias on Claude routes, a model name locally)."""
        if kind not in KINDS:
            return None
        chosen = self.overrides.get(kind) or self.overrides.get(ROW_OF.get(kind, ""))
        if self.route in ("claude_code", "anthropic"):
            m = chosen or CLAUDE_DEFAULTS[kind][0]
            return self._auditor() if m == "auditor" else m
        if self.route == "local":
            if chosen:
                return chosen
            role = LOCAL_DEFAULTS[kind]
            return {"small": self.small or self.large, "large": self.large, "second": self.second}[role] or None
        return None

    def step_up(self, kind: str) -> str | None:
        """The model a hard task goes up to, or None (no stronger model on this route)."""
        if kind not in KINDS:
            return None
        start = self.first(kind)
        if self.route in ("claude_code", "anthropic"):
            nxt = CLAUDE_DEFAULTS[kind][1]
            if (self.overrides.get(kind) or self.overrides.get(ROW_OF.get(kind, ""))) and start in LADDER:
                # a model chosen in Settings steps up to the next one on the ladder (or the auditor at the top)
                i = LADDER.index(start)
                nxt = LADDER[i + 1] if i + 1 < len(LADDER) else ("auditor" if kind in TO_AUDITOR else None)
            if nxt is None:
                return None
            return self._auditor() if nxt == "auditor" else nxt
        if self.route == "local":
            if LOCAL_DEFAULTS[kind] == "small" and self.small and self.large and self.small != self.large \
                    and start != self.large:
                return self.large
            return None
        return None

    def model(self, kind: str, step: int = 0) -> str | None:
        return self.step_up(kind) if step else self.first(kind)

    def helper(self, kind: str, step: int = 0) -> str | None:
        """The plugin's helper agent for a task (Claude Code only): a stepped-up check goes to the auditor."""
        if self.route != "claude_code":
            return None
        if step and kind in TO_AUDITOR:
            return "enlens-auditor"
        return HELPERS.get(kind)

    def api_id(self, alias: str | None) -> str | None:
        """The Claude API's model id for an alias (a full id is kept)."""
        if alias is None:
            return None
        if alias == "opus":
            return self.opus_id or API_IDS["opus"]
        return API_IDS.get(alias, alias)

    def call_model(self, kind: str, step: int = 0) -> str | None:
        """The model name to send to the backend: an API id on the Claude API, the alias for Claude Code, the model
        name on a local server."""
        m = self.model(kind, step)
        return self.api_id(m) if self.route == "anthropic" else m

    def table(self) -> list[dict]:
        """One row per group of kinds, for Settings and "How these results were made"."""
        out = []
        for row, kinds, title in ROWS:
            k = kinds[0]
            out.append({"row": row, "kinds": list(kinds), "title": title, "model": self.first(k),
                        "step_up": self.step_up(k), "helper": self.helper(k), "chosen": self.overrides.get(row),
                        "recommended": (CLAUDE_DEFAULTS[k][0] if self.route in ("claude_code", "anthropic")
                                        else LOCAL_DEFAULTS[k])})
        return out


def from_settings(settings: dict, route: str | None = None, large: str = "") -> Router:
    """The router the settings describe. `large`: the main model a local backend uses."""
    route = route or route_of(settings.get("backend", "auto"))
    models = settings.get("task_models") or {}
    if not isinstance(models, dict):
        models = {}
    family = "claude" if route in ("claude_code", "anthropic") else "local"
    overrides = {k: v for k, v in (models.get(family) or {}).items() if isinstance(v, str) and v.strip()}
    return Router(route=route, fable=bool(settings.get("use_fable")), overrides=overrides, large=large,
                  small=(settings.get("local_small_model") or "").strip() if route == "local" else "",
                  second=(settings.get("second_model") or "").strip(),
                  opus_id=settings.get("anthropic_model") or API_IDS["opus"])


def clean_task_models(value) -> dict:
    """Validate the per-task model choices of Settings: {"claude": {row: alias}, "local": {row: model name}}."""
    if value in (None, "", {}):
        return {}
    if not isinstance(value, dict):
        raise ValueError("task_models must be an object: {\"claude\": {...}, \"local\": {...}}.")
    out: dict = {}
    for family, rows in value.items():
        if family not in ("claude", "local"):
            raise ValueError("task_models has two parts: claude and local.")
        if not isinstance(rows, dict):
            raise ValueError(f"task_models.{family} must be an object of task kind: model.")
        clean = {}
        for row, m in rows.items():
            if row not in ROW_OF and row not in {r for r, _k, _t in ROWS}:
                raise ValueError(f"Unknown task kind {row!r} in task_models.")
            m = "" if m is None else str(m).strip()
            if not m:
                continue
            if family == "claude" and m not in ALIASES and not m.startswith("claude-"):
                raise ValueError(f"For Claude, choose haiku, sonnet, opus or fable (not {m!r}).")
            clean[row] = m
        if clean:
            out[family] = clean
    return out
