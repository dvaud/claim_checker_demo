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

0.13.10: on Claude Code the recommended models follow the researcher's Claude plan, found in the background from
`claude auth status` (Settings' claude_plan_detected; claude_plan "auto" unless set by hand). Free: no Opus or
Fable, Haiku for most tasks and Sonnet where excerpts are judged or reference claims set. Pro (and a plan not known):
the table below, Sonnet for most tasks and Opus sparingly. Max, Team and Enterprise: Opus for most tasks, Haiku and
Sonnet only for the kinds with many tasks at a time (`bulk`), where speed matters. Models chosen per task in
Settings come first on every plan.
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
RANK = {a: i for i, a in enumerate(ALIASES)}   # 0.13.10: where the plan moved a model, a step up goes higher
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


# 0.18.1 (N2): how much thought Claude gives each kind of task, beside every Start Claude Code (Settings'
# claude_thought). Balanced is the table of the kinds (and the plan's tier). Efficient starts each kind one step lower
# on the ladder (Opus -> Sonnet -> Haiku), Intelligence one step higher (Haiku -> Sonnet -> Opus); a kind that starts
# on the auditor keeps it (Fable stays its own switch). Models chosen per task in Settings come first. Where a helper
# takes an effort (the Claude Code plugin's agents), Efficient asks for low and Intelligence for high effort.
THOUGHTS = ("efficient", "balanced", "intelligence")
THOUGHT_TITLES = {"efficient": "Energy efficient", "balanced": "Balanced", "intelligence": "Intelligence"}
THOUGHT_EFFORT = {"efficient": "low", "balanced": None, "intelligence": "high"}


def _shift(alias: str | None, by: int, floor: str | None = None) -> str | None:
    """An alias moved along LADDER (never past its ends; "auditor" and other names are kept)."""
    if alias not in LADDER or not by:
        return alias
    i = max(0, min(len(LADDER) - 1, LADDER.index(alias) + by))
    if floor in LADDER:
        i = max(i, LADDER.index(floor))
    return LADDER[i]


# 0.18.1 (I1): which route answers each kind when Claude and a local model are both set (Settings' ai_mix), by row of
# Settings' table. "best" is everything on Claude (the local model reads only documents marked Only a local AI, as
# before 0.18.1). The SDG pack's rows stay on Claude in "balanced": they set and judge reference claims.
MIXES = ("best", "balanced", "mostly_local")
MIX_TITLES = {"best": "Best quality", "balanced": "Balanced", "mostly_local": "Mostly local"}
MIX_LOCAL_ROWS = {"best": frozenset(),
                  "balanced": frozenset({"label", "link", "expand", "theme", "resolve"}),
                  "mostly_local": frozenset({"label", "link", "expand", "theme", "resolve", "check", "extract", "split",
                                             "verify"})}
MIX_ROUTES = ("claude_code",)  # the main routes a mix lends work from (the Claude API: not yet, see the changelog)


def mix_rows(settings: dict) -> frozenset[str]:
    """The rows of Settings' table the local model answers first under the chosen mix: none unless the main route is
    Claude Code and a local model is chosen (Settings' local model for restricted
    documents, on this computer)."""
    mix = settings.get("ai_mix") or "best"
    if mix not in MIX_LOCAL_ROWS or mix == "best":
        return frozenset()
    if route_of(settings.get("backend", "auto")) not in MIX_ROUTES:
        return frozenset()
    if not (settings.get("restricted_server") and settings.get("restricted_model")):
        return frozenset()
    return MIX_LOCAL_ROWS[mix]


def mix_kinds(settings: dict) -> frozenset[str]:
    """The kinds of task (and roles) the local model answers first under the chosen mix (see mix_rows)."""
    rows = mix_rows(settings)
    return frozenset(k for k in KINDS if ROW_OF.get(k) in rows) if rows else frozenset()


def judging_changes(kind: str, obj) -> bool:
    """I2: whether a local answer would change a decision, so it goes to Claude even when sure: an answer that judges
    an excerpt as contradicting (a contradiction decides a hypothesis's answer: one part contradicted, and it does not
    hold). Kinds that do not judge excerpts never do."""
    k = taskkinds.get(kind)
    if not (k and k.judging) or not isinstance(obj, dict):
        return False
    items = obj.get(k.certainty) if k.certainty and k.certainty != "." else [obj]
    return any(isinstance(x, dict) and x.get("verdict") == "refutes" for x in items or [])


# 0.13.10: the Claude plans, as three tiers of recommended models ("" = not known: as Pro)
TIERS = ("free", "pro", "max")
TIER_TITLES = {"free": "Free", "pro": "Pro", "max": "Max, Team or Enterprise"}


def plan_tier(plan: str | None) -> str:
    """The tier of the plan Claude Code names (`subscriptionType`): free, pro, or max for Max, Team and Enterprise;
    "" when it names none or one not known."""
    p = str(plan or "").strip().lower()
    if not p:
        return ""
    if "team" in p or "enterprise" in p or "max" in p:
        return "max"
    if "pro" in p:
        return "pro"
    if "free" in p:
        return "free"
    return ""


def tier_defaults(kind: str, tier: str) -> tuple[str, str | None]:
    """(the model a kind starts on, the model it steps up to) recommended on a plan tier, from the table of the kind
    (CLAUDE_DEFAULTS, the recommendation for Pro). "auditor" stays a role: Opus, Fable when switched on, Sonnet on
    Free (Router._auditor)."""
    first, up = CLAUDE_DEFAULTS[kind]
    if first == "auditor" or tier not in ("free", "max"):
        return first, up
    k = taskkinds.get(kind)
    if tier == "free":
        # no Opus or Fable: Haiku first, stepping up to Sonnet; judging excerpts and setting reference claims on Sonnet
        careful = bool(k and (k.judging or k.to_auditor))
        return ("sonnet", None) if careful else ("haiku", "sonnet")
    # max: Opus for most tasks (stepping up to the auditor where it reads the hard cases, which matters with Fable);
    # the kinds with many tasks keep their cheaper models, as speed matters there
    if k and k.bulk:
        return first, up
    return "opus", ("auditor" if kind in TO_AUDITOR else None)


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
    tier: str = ""                   # 0.13.10, Claude Code: the plan's tier (free | pro | max; "" = not known: as pro)
    thought: str = "balanced"        # 0.18.1 (N2), Claude routes: efficient | balanced | intelligence

    # -- the table ------------------------------------------------------------------------------
    def _auditor(self) -> str:
        if self.route == "claude_code" and self.tier == "free":
            return "sonnet"   # no Opus or Fable on a Free plan
        return "fable" if self.fable else "opus"

    def _defaults(self, kind: str) -> tuple[str, str | None]:
        first, up = tier_defaults(kind, self.tier if self.route == "claude_code" else "")
        by = {"efficient": -1, "intelligence": 1}.get(self.thought, 0)
        if not by or self.route not in ("claude_code", "anthropic"):
            return first, up
        top = self._ladder()[-1]  # Free has no Opus: never moved past Sonnet
        k = taskkinds.get(kind)
        # judging excerpts and setting reference claims never go below Sonnet (as on the Free plan)
        new = _shift(first, by, floor="sonnet" if k and (k.judging or k.to_auditor) else None)
        if new in LADDER and LADDER.index(new) > LADDER.index(top):
            new = top
        if up in LADDER and new in LADDER and LADDER.index(up) <= LADDER.index(new):
            # a step up is always to a stronger model; none left: the auditor where the kind has one
            i = LADDER.index(new) + 1
            up = self._ladder()[i] if i < len(self._ladder()) else ("auditor" if kind in TO_AUDITOR else None)
        return new, up

    def effort(self, kind: str) -> str | None:
        """0.18.1 (N2): the effort a helper of Claude Code is asked for, when the thought chosen asks one (None: the
        helper's own)."""
        if self.route != "claude_code" or kind not in KINDS:
            return None
        return THOUGHT_EFFORT.get(self.thought)

    def _ladder(self) -> tuple[str, ...]:
        return LADDER[:2] if self.route == "claude_code" and self.tier == "free" else LADDER

    def first(self, kind: str) -> str | None:
        """The model a task of this kind starts on (an alias on Claude routes, a model name locally)."""
        if kind not in KINDS:
            return None
        chosen = self.overrides.get(kind) or self.overrides.get(ROW_OF.get(kind, ""))
        if self.route in ("claude_code", "anthropic"):
            m = chosen or self._defaults(kind)[0]
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
            nxt = self._defaults(kind)[1]
            ladder = self._ladder()
            if (self.overrides.get(kind) or self.overrides.get(ROW_OF.get(kind, ""))) and start in LADDER:
                # a model chosen in Settings steps up to the next one on the ladder (or the auditor at the top)
                i = LADDER.index(start)
                nxt = ladder[i + 1] if i + 1 < len(ladder) else ("auditor" if kind in TO_AUDITOR else None)
            if nxt is None:
                return None
            nxt = self._auditor() if nxt == "auditor" else nxt
            # 0.13.10: where the plan moved a kind's model (Free; Max for the kinds it raised to Opus), only ever up
            # to a stronger model: a check that starts on Opus has no stronger one unless Fable is on. The SDG pack's
            # Opus tasks still have their hard cases read again by the auditor, as since 0.8.1.
            # 0.18.1 (N2): so does a thought other than Balanced, on either Claude route
            moved = self.tier == "free" or (self.tier == "max" and self._defaults(kind)[0] != CLAUDE_DEFAULTS[kind][0]) \
                or self.thought != "balanced"
            if (self.route == "claude_code" or self.thought != "balanced") and moved and nxt in RANK and start in RANK and RANK[nxt] <= RANK[start]:
                return None
            return nxt
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
            rec = self._defaults(k)[0] if self.route in ("claude_code", "anthropic") else LOCAL_DEFAULTS[k]
            out.append({"row": row, "kinds": list(kinds), "title": title, "model": self.first(k),
                        "step_up": self.step_up(k), "helper": self.helper(k), "chosen": self.overrides.get(row),
                        # 0.13.10: for the plan, the auditor named (Opus, Fable, or Sonnet on Free)
                        "recommended": self._auditor() if rec == "auditor" else rec,
                        "recommended_role": "auditor" if rec == "auditor" else ""})
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
                  opus_id=settings.get("anthropic_model") or API_IDS["opus"],
                  tier=settings_tier(settings) if route == "claude_code" else "",
                  thought=settings.get("claude_thought") if settings.get("claude_thought") in THOUGHTS else "balanced")


def settings_tier(settings: dict) -> str:
    """The tier the recommendations follow (0.13.10): the plan set by hand in Settings, else the one Claude Code
    said (found in the background), else "" (not known: as Pro)."""
    chosen = str(settings.get("claude_plan") or "auto")
    if chosen in TIERS:
        return chosen
    detected = str(settings.get("claude_plan_detected") or "")
    return detected if detected in TIERS else ""


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
