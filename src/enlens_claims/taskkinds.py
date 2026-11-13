"""One registry for the kinds of AI task (0.13.6). See docs/EXTENDING.md.

Each kind of task the AI answers (labels, checks, theme names…) is one `TaskKind`: its prompt, the answer's schema,
where the quote check reads, how it is stored, the model it starts on and steps up to, its Claude Code helper, its
batch size and place in the queue, its names, its answer's token limit, the offline demo's answer and the size of
its prompt. Before 0.13.6 these lived in eight modules (schema, prompts, tasks, routing, taskqueue, runs, llm, home);
those modules' tables (`routing.KINDS`, `taskqueue.ORDER`, `taskqueue.BATCH`, `routing.HELPERS`, `prompts.VERSIONS`,
`llm.OUTPUT_CAP`…) are now views of this registry, so a kind an add-on registers appears in every one of them.

ENLENS's own kinds are registered here as data; the functions that build their prompts, offline answers and size
estimates stay where they were (prompts.py, llm.py, home.py), and tasks.py attaches their store functions.

An add-on registers a kind of its own with `register(TaskKind(...))`. It must say where the quote check reads
(`quote_from`): ENLENS then checks every quote in an answer against that text before the add-on's store function sees
it, and the task goes through the same guard as every other (`access`, `home.local_only()`).
"""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence, Set
from dataclasses import dataclass, replace
from typing import Any, Callable


@dataclass(frozen=True)
class TaskKind:
    name: str
    prompt_version: str | None = None       # recorded with every answer (None: a role, not a task kind: "audit")
    # the prompt (an add-on's kinds; ENLENS's own are built in prompts.py)
    system: Callable[[], str] | None = None
    user: Callable[[dict], str] | None = None
    # the answer
    schema: Any = None                      # a pydantic model the answer must match (add-on kinds)
    quote_from: Callable[[dict], Any] | None = None   # payload -> the text (or texts) every quote must come from
    quote_fields: tuple[str, ...] = ("quote",)        # the answer's keys that hold quotes, at any depth
    store: Callable | None = None           # (cx, task, payload, answer, model) -> (ok, problems)
    certainty: str | None = None            # the answer's list whose items carry `confidence` ("." : the answer's own)
    # the model: Claude (first, steps up to; "auditor" = Opus or Fable) and on a local server (small, large, second)
    claude: tuple[str, str | None] | None = None
    local: str | None = None
    to_auditor: bool = False                # a stepped-up task goes to the auditor (judging excerpts)
    judging: bool = False                   # reasoning helps ("think: judging")
    bulk: bool = False                      # 0.13.10: many tasks at a time, where speed matters (on a Max plan they
                                            # keep the cheaper model; see routing.tier_defaults)
    helper: str | None = None               # the Claude Code plugin's helper agent
    helper_file: str | None = None          # an add-on's own helper: its agent file (.md), copied into the plugin
    helper_model: str | None = None         # that helper's own model (haiku, sonnet, opus)
    # Settings: the row of the model table it is chosen in (kinds sharing a row share the choice)
    row: str | None = None
    row_title: str | None = None
    # the queue (None: never queued for Claude Code)
    batch: int | None = None
    order: float | None = None
    # names
    noun: tuple[str, str] | None = None     # "passage to label", "passages to label"
    short: str | None = None                # "labels": "Paused at 12 of 40 labels"
    title: str | None = None                # the queue panel's heading for the kind
    run_name: str | None = None             # "How these results were made"
    # limits and the rest
    output_cap: int | None = None           # the longest answer, in tokens
    demo: Callable[[dict], dict] | None = None        # the offline demo's answer (add-on kinds)
    size: Callable[[int, int], int] | None = None     # (k, max_chars) -> the longest user prompt, in characters
    task: bool = True                       # a kind of task (False: "audit", a role tasks are routed as)
    corpus: bool = False                    # its passages are the corpus at large (the file queue warns)
    core: bool = False                      # one of ENLENS's own


_REG: dict[str, TaskKind] = {}
_loading = False


def _core(**kw) -> None:
    k = TaskKind(core=True, **kw)
    _REG[k.name] = k


def get(name: str) -> TaskKind | None:
    """The kind called `name`, or None. A name not registered yet loads the add-ons first (they register theirs)."""
    global _loading
    k = _REG.get(name)
    if k is None and not _loading:
        _loading = True
        try:
            from .addons import load

            load()
        except Exception:  # noqa: BLE001 - an add-on that cannot load registers nothing
            pass
        finally:
            _loading = False
        k = _REG.get(name)
    return k


def register(kind: TaskKind) -> TaskKind:
    """Register an add-on's kind of task. Refused: a name ENLENS (or another add-on) uses, a kind without a quote
    check, prompt, store function or prompt version. Registering the same kind again replaces it."""
    if not isinstance(kind, TaskKind):
        raise TypeError("register() takes a TaskKind")
    old = _REG.get(kind.name)
    if old is not None and old.core:
        raise ValueError(f"{kind.name!r} is one of ENLENS's own kinds of task.")
    if not callable(kind.quote_from):
        raise ValueError(f"The kind {kind.name!r} has no quote check: give quote_from, the text every quote in an "
                         "answer must come from.")
    missing = [f for f in ("prompt_version", "system", "user", "store") if not getattr(kind, f)]
    if missing:
        raise ValueError(f"The kind {kind.name!r} needs {', '.join(missing)}.")
    kind = replace(kind, core=False, task=True, row=kind.row or kind.name,
                   row_title=kind.row_title or kind.title or kind.name,
                   claude=kind.claude or ("sonnet", "opus"), local=kind.local or "large",
                   noun=kind.noun or ("task", "tasks"), short=kind.short or "tasks",
                   title=kind.title or kind.name, run_name=kind.run_name or kind.title or kind.name,
                   batch=kind.batch if kind.batch is not None else 5,
                   order=kind.order if kind.order is not None else 1000 + len(_REG),
                   output_cap=kind.output_cap or 2000)
    _REG[kind.name] = kind
    return kind


def unregister(name: str) -> None:
    """Take an add-on's kind away (ENLENS's own stay)."""
    k = _REG.get(name)
    if k is not None and not k.core:
        del _REG[name]


def attach(name: str, **fields) -> None:
    """Give one of ENLENS's own kinds a function defined in another module (its store function, in tasks.py)."""
    _REG[name] = replace(_REG[name], **fields)


# ---------------------------------------------------------------------------------------------
# live views: the tables the other modules keep, read from the registry each time
# ---------------------------------------------------------------------------------------------
class Table(MutableMapping):
    """{kind: one field of it}, for the kinds where the field is set. Setting a value changes the kind (tests do,
    with monkeypatch.setitem)."""

    def __init__(self, attr: str, value: Callable[[TaskKind], Any] | None = None):
        self.attr, self.value = attr, value

    def _of(self, k: TaskKind):
        return self.value(k) if self.value else getattr(k, self.attr)

    def __getitem__(self, name):
        k = get(name) if isinstance(name, str) else None
        v = self._of(k) if k is not None else None
        if v is None:
            raise KeyError(name)
        return v

    def __iter__(self):
        return iter([k.name for k in _REG.values() if self._of(k) is not None])

    def __len__(self):
        return sum(1 for _ in self)

    def __setitem__(self, name, v):
        if self.value:
            raise TypeError(f"the table of {self.attr} is read-only")
        _REG[name] = replace(_REG[name], **{self.attr: v})

    def __delitem__(self, name):
        self[name] = None

    def __repr__(self):
        return repr(dict(self))


class Names(Sequence):
    """The names of the kinds that pass `where`, in registration order (or by `key`)."""

    def __init__(self, where: Callable[[TaskKind], bool], key: Callable[[TaskKind], Any] | None = None):
        self.where, self.key = where, key

    def _list(self) -> list[str]:
        ks = [k for k in _REG.values() if self.where(k)]
        if self.key:
            ks.sort(key=self.key)
        return [k.name for k in ks]

    def __getitem__(self, i):
        return self._list()[i]

    def __len__(self):
        return len(self._list())

    def __contains__(self, name):
        k = get(name) if isinstance(name, str) else None
        return k is not None and self.where(k)

    def __add__(self, other):
        return tuple(self) + tuple(other)

    def __eq__(self, other):
        return isinstance(other, (tuple, list, Names)) and list(self) == list(other)

    __hash__ = None

    def __repr__(self):
        return repr(tuple(self))


class NameSet(Set):
    """The same, as a set (for `kind in JUDGING`)."""

    def __init__(self, where: Callable[[TaskKind], bool]):
        self.names = Names(where)

    def __contains__(self, name):
        return name in self.names

    def __iter__(self):
        return iter(self.names)

    def __len__(self):
        return len(self.names)

    __hash__ = Set._hash

    def __repr__(self):
        return repr(frozenset(self))


class Rows(Sequence):
    """Settings' model table: (row, its kinds, its title), one row per group of kinds, in order of first kind."""

    def _list(self):
        rows: dict[str, list] = {}
        titles: dict[str, str] = {}
        for k in _REG.values():
            if k.row:
                rows.setdefault(k.row, []).append(k.name)
                titles.setdefault(k.row, k.row_title or k.row)
        return [(r, tuple(ks), titles[r]) for r, ks in rows.items()]

    def __getitem__(self, i):
        return self._list()[i]

    def __len__(self):
        return len(self._list())


class HelperModels(Mapping):
    """{helper agent: its own model}: ENLENS's helpers, then each add-on kind's own helper."""

    def __init__(self, base: dict[str, str]):
        self.base = dict(base)

    def _all(self) -> dict[str, str]:
        out = dict(self.base)
        for k in _REG.values():
            if k.helper and k.helper_file and k.helper not in out:
                out[k.helper] = k.helper_model or "sonnet"
        return out

    def __getitem__(self, h):
        return self._all()[h]

    def __iter__(self):
        return iter(self._all())

    def __len__(self):
        return len(self._all())


def addon_helpers() -> dict[str, str]:
    """{helper: its agent file} of the add-on kinds that bring their own helper."""
    return {k.helper: k.helper_file for k in _REG.values() if not k.core and k.helper and k.helper_file}


# ---------------------------------------------------------------------------------------------
# ENLENS's own kinds, as before 0.13.6 (tests/test_task_kinds.py checks every table against its 0.13.5 value).
# Registration order follows Settings' model table.
# ---------------------------------------------------------------------------------------------
_core(name="label", prompt_version="label-v1", certainty="labels", claude=("haiku", "sonnet"), local="small", bulk=True,
      helper="enlens-labeller", row="label", row_title="Codebook labels (profile)", batch=20, order=8,
      noun=("passage to label", "passages to label"), short="labels", title="Codebook labels",
      run_name="Codebook labels", output_cap=1500, corpus=True)
_core(name="link", prompt_version="link-v1", certainty="relations", claude=("haiku", "sonnet"), local="small", bulk=True,
      helper="enlens-linker", row="link", row_title="How concepts relate", batch=10, order=7,
      noun=("pair of terms", "pairs of terms"), short="pairs of terms", title="How concepts relate",
      run_name="How concepts relate", output_cap=700, corpus=True)
_core(name="expand", prompt_version="expand-v2", claude=("sonnet", "opus"), local="large", helper="enlens-namer",
      row="expand", row_title="Search words and splitting a hypothesis", batch=5, order=2,
      noun=("set of search words", "sets of search words"), short="sets of search words", title="Search words",
      run_name="Search words", output_cap=400)
_core(name="decompose", prompt_version="decompose-v1", claude=("sonnet", "opus"), local="large",
      helper="enlens-reader", row="expand", batch=5, order=1,
      noun=("hypothesis to split", "hypotheses to split"), short="hypotheses to split", title="Splitting hypotheses",
      run_name="Splitting a hypothesis", output_cap=800)
_core(name="theme", prompt_version="theme-v1", claude=("sonnet", "opus"), local="large", helper="enlens-namer",
      row="theme", row_title="Theme names", batch=5, order=6, noun=("theme to name", "themes to name"),
      short="theme names", title="Theme names", run_name="Theme names", output_cap=500, corpus=True)
_core(name="resolve", prompt_version="resolve-v1", claude=("sonnet", "opus"), local="large", helper="enlens-reader",
      bulk=True, row="resolve", row_title="References in a document", batch=4, order=9,
      noun=("window of references", "windows of references"), short="windows of references",
      title="References in documents", run_name="References in a document", output_cap=2500, corpus=True)
# checks start on Sonnet (its helper runs at high effort, see agents/enlens-checker.md); an unsure or twice rejected
# judgement goes to the auditor, so the second opinion and the step-up stay on Opus (or Fable)
_core(name="check", prompt_version="check-v5", certainty="evidence", claude=("sonnet", "auditor"), local="large",
      to_auditor=True, judging=True, helper="enlens-checker", row="check",
      row_title="Judging excerpts (checks, reading again)", batch=1, order=3,
      noun=("set of excerpts to judge", "sets of excerpts to judge"), short="sets of excerpts",
      title="Judging excerpts", run_name="Checking hypotheses", output_cap=1500)
_core(name="reread", prompt_version="check-v5", certainty="evidence", claude=("sonnet", "auditor"), local="large",
      to_auditor=True, judging=True, helper="enlens-checker", row="check", batch=1, order=4,
      noun=("excerpt to read again", "excerpts to read again"), short="excerpts to read again",
      title="Reading an excerpt again", run_name="Reading an excerpt again", output_cap=600)
_core(name="second", prompt_version="check-v5", certainty="evidence", claude=("auditor", None), local="second",
      judging=True, helper="enlens-auditor", row="second", row_title="Second opinion (and audits of the SDG pack)",
      batch=1, order=5, noun=("set of excerpts for a second opinion", "sets of excerpts for a second opinion"),
      short="second opinions", title="Second opinions", run_name="Second opinion", output_cap=1500)
_core(name="audit", certainty="evidence", claude=("auditor", None), local="second", helper="enlens-auditor",
      row="second", task=False)
# the SDG pack. extract is bulk work: Sonnet, stepping up to Opus. split sets the reference claims: Opus (the pilot
# used Fable). verify and verify_set judge excerpts, as a check does: Opus, stepping up to the auditor.
_core(name="extract", prompt_version="extract-v1", certainty="claims", claude=("sonnet", "opus"), local="large",
      bulk=True, helper="enlens-extractor", row="extract", row_title="SDG pack: impact claims from passages", batch=8, order=13,
      noun=("passage to extract claims from", "passages to extract claims from"), short="passages to extract",
      title="SDG pack: extracting claims", run_name="Extracting claims (SDG pack)", output_cap=3000)
_core(name="split", prompt_version="split-v2", claude=("opus", "auditor"), local="large", to_auditor=True,
      helper="enlens-extractor", row="split", row_title="SDG pack: splitting the VCA's justifications", batch=5,
      order=10, noun=("justification to split", "justifications to split"), short="justifications to split",
      title="SDG pack: splitting justifications", run_name="Splitting justifications (SDG pack)", output_cap=1500)
_core(name="verify", prompt_version="verify-v2", certainty=".", claude=("opus", "auditor"), local="large",
      to_auditor=True, helper="enlens-checker", row="verify", row_title="SDG pack: checking claims against their sources",
      batch=10, order=12, noun=("claim and passage to check", "claims and passages to check"), short="claims to check",
      title="SDG pack: checking claims", run_name="Checking claims (SDG pack)", output_cap=600)
_core(name="verify_set", prompt_version="verify-set-v2", certainty="evidence", claude=("opus", "auditor"),
      local="large", to_auditor=True, helper="enlens-checker", row="verify", batch=3, order=11,
      noun=("VCA claim to check", "VCA claims to check"), short="VCA claims to check",
      title="SDG pack: checking VCA claims", run_name="Checking VCA claims (SDG pack)", output_cap=1500)


# ---------------------------------------------------------------------------------------------
# the quote check of an add-on's kind
# ---------------------------------------------------------------------------------------------
def quotes_in(obj: Any, fields: tuple[str, ...]) -> list[str]:
    """Every string the answer holds under one of `fields`, at any depth."""
    out: list[str] = []
    if isinstance(obj, dict):
        for key, v in obj.items():
            if key in fields and isinstance(v, str):
                out.append(v)
            else:
                out += quotes_in(v, fields)
    elif isinstance(obj, list):
        for v in obj:
            out += quotes_in(v, fields)
    return out


QUOTE_KEYS = ("quote", "quote_a", "quote_b")  # the keys that hold a quote in ENLENS's own answers (at any depth)


def long_quote_problems(obj: Any, extra_fields: tuple[str, ...] = ()) -> list[str]:
    """The quotes of an answer that are longer than `textutil.MAX_QUOTE_CHARS` (0.17.2, H11), one problem each."""
    from .textutil import long_quote_problem

    seen: list[str] = []
    for q in quotes_in(obj, tuple(dict.fromkeys((*QUOTE_KEYS, *extra_fields)))):
        p = long_quote_problem(q)
        if p and p not in seen:
            seen.append(p)
    return seen


def check_quotes(kind: TaskKind, payload: dict, obj: Any) -> list[str]:
    """The problems with an answer's quotes: each must be found in the text `quote_from` gives (whitespace, case and
    typography aside, as for every quote ENLENS checks)."""
    from .textutil import find_quote

    src = kind.quote_from(payload)
    texts = [src] if isinstance(src, str) else [t for t in (src or []) if isinstance(t, str)]
    problems = []
    for q in quotes_in(obj, kind.quote_fields):
        if not q.strip():
            problems.append("a quote is empty")
        elif not any(find_quote(t, q) is not None for t in texts):
            problems.append(f"quote not found in the passage: {q[:80]!r}. Copy it character for character, or quote a "
                            "shorter contiguous piece of it.")
    return problems
