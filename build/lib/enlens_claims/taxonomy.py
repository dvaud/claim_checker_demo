"""SDG targets and the fixed vocabularies of the claim schema."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

SEGMENTS = ("production", "transportation", "end_use")
SEGMENT_LABELS = {"production": "H2 production", "transportation": "H2 transportation", "end_use": "H2 end-use"}
CLAIM_SEGMENTS = SEGMENTS + ("whole_chain", "unclear")
DIRECTIONS = ("positive", "negative", "mixed", "no_effect")
INFLUENCES = ("direct", "indirect", "unclear")
HORIZONS = ("short_term", "medium_long_term", "not_stated")
HORIZON_LABELS = {"short_term": "short term (to 2030)", "medium_long_term": "medium to long term (after 2030)", "not_stated": "not stated"}
SCALES = ("local", "national", "regional", "global", "unspecified")
SIDES = ("producer", "importer", "both", "unspecified")
VERDICTS = ("supports", "refutes", "not_enough_info")
# set-wise verification grades each passage it cites; passages it leaves out count as not_enough_info
EVIDENCE_VERDICTS = ("supports", "partially_supports", "refutes")

# Nilsson, Griggs & Visbeck (2016) seven-point scale for interactions between targets.
NILSSON = {3: "indivisible", 2: "reinforcing", 1: "enabling", 0: "consistent", -1: "constraining", -2: "counteracting", -3: "cancelling"}


@dataclass(frozen=True)
class Target:
    code: str
    goal: int
    goal_name: str
    description: str


@lru_cache(maxsize=1)
def targets() -> dict[str, Target]:
    path = resources.files("enlens_claims").joinpath("data/sdg_targets.csv")
    out: dict[str, Target] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[row["code"]] = Target(row["code"], int(row["goal"]), row["goal_name"], row["description"])
    return out


def goal_names() -> dict[int, str]:
    return {t.goal: t.goal_name for t in targets().values()}


def normalise_target(code: object) -> str | None:
    """Map spellings such as 'SDG 6.4', 'Target 7.B', '6.4.' to a valid code, else None."""
    if code is None:
        return None
    s = str(code).strip().lower()
    s = re.sub(r"^(sdg|target|goal)\s*", "", s)
    m = re.search(r"(\d{1,2})\s*\.\s*([0-9]{1,2}|[a-z])\b", s)
    if not m:
        return None
    c = f"{int(m.group(1))}.{m.group(2)}"
    return c if c in targets() else None


def goal_of(code: str) -> int:
    return int(code.split(".")[0])


def target_sort_key(code: str) -> tuple[int, int, str]:
    g, t = code.split(".")
    return (int(g), int(t) if t.isdigit() else 100, t)


def targets_reference_text() -> str:
    """Compact list of all 169 targets for prompts and worker instructions."""
    lines = []
    goal = None
    for code in sorted(targets(), key=target_sort_key):
        t = targets()[code]
        if t.goal != goal:
            goal = t.goal
            lines.append(f"\nSDG {t.goal}: {t.goal_name}")
        lines.append(f"{code} {t.description}")
    return "\n".join(lines).strip()
