"""Output schemas for each model task. Loose spellings are normalised before validation."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from .taxonomy import (CLAIM_SEGMENTS, DIRECTIONS, EVIDENCE_VERDICTS, HORIZONS, INFLUENCES, SCALES, SIDES, VERDICTS,
                       normalise_target)

_ALIASES = {
    "end-use": "end_use", "enduse": "end_use", "end use": "end_use", "use": "end_use",
    "transport": "transportation", "storage": "transportation", "distribution": "transportation",
    "whole chain": "whole_chain", "all": "whole_chain", "value chain": "whole_chain",
    "medium_to_long_term": "medium_long_term", "medium-long": "medium_long_term", "long_term": "medium_long_term",
    "medium_term": "medium_long_term", "short": "short_term", "none": "not_stated", "unknown": "not_stated",
    "not stated": "not_stated", "n/a": "not_stated", "neutral": "no_effect", "none_effect": "no_effect",
    "support": "supports", "supported": "supports", "partial": "partially_supports",
    "partially_supported": "partially_supports", "partly_supports": "partially_supports", "partial_support": "partially_supports", "refute": "refutes", "contradicts": "refutes",
    "nei": "not_enough_info", "not enough info": "not_enough_info", "insufficient": "not_enough_info",
    "unspecified_scale": "unspecified", "exporter": "producer", "exporting": "producer", "importing": "importer",
}


def _norm_enum(v: object) -> object:
    if not isinstance(v, str):
        return v
    s = v.strip().lower()
    s = _ALIASES.get(s, s)
    s = s.replace("-", "_").replace(" ", "_")
    return _ALIASES.get(s, s)


class EvidenceQuote(BaseModel):
    field: str = "claim"
    quote: str


class TargetEffect(BaseModel):
    target: str
    direction: Literal[DIRECTIONS]
    influence: Literal[INFLUENCES] = "unclear"

    @field_validator("target", mode="before")
    @classmethod
    def _target(cls, v):
        code = normalise_target(v)
        if not code:
            raise ValueError(f"unknown SDG target {v!r}; use a code such as '6.4' or '7.b'")
        return code

    @field_validator("direction", "influence", mode="before")
    @classmethod
    def _enum(cls, v):
        return _norm_enum(v)


class ImpactClaimOut(BaseModel):
    claim: str = Field(min_length=10)
    activity: str = Field(min_length=2)
    segment: Literal[CLAIM_SEGMENTS]
    targets: list[TargetEffect] = Field(min_length=1)
    place: Optional[str] = None
    countries: list[str] = Field(default_factory=list)
    scale: Literal[SCALES] = "unspecified"
    side: Literal[SIDES] = "unspecified"
    horizon: Literal[HORIZONS] = "not_stated"
    condition: Optional[str] = None
    policy_lever: Optional[str] = None
    confidence: float = Field(ge=0, le=1)
    evidence: list[EvidenceQuote] = Field(min_length=1)

    @field_validator("segment", "scale", "side", "horizon", mode="before")
    @classmethod
    def _enum(cls, v):
        return _norm_enum(v) if v is not None else v

    @field_validator("countries", mode="before")
    @classmethod
    def _countries(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [c.strip() for c in v.split(",") if c.strip()]
        return v


class InteractionOut(BaseModel):
    from_target: str
    to_target: str
    score: int = Field(ge=-3, le=3)
    quote: str

    @field_validator("from_target", "to_target", mode="before")
    @classmethod
    def _target(cls, v):
        code = normalise_target(v)
        if not code:
            raise ValueError(f"unknown SDG target {v!r}")
        return code


class ExtractOut(BaseModel):
    claims: list[dict] = Field(default_factory=list)       # validated one by one as ImpactClaimOut
    interactions: list[dict] = Field(default_factory=list)  # validated one by one as InteractionOut
    note: Optional[str] = None


class VcaClaimOut(BaseModel):
    text: str = Field(min_length=10)
    quote: str
    segment: Literal[CLAIM_SEGMENTS] = "unclear"
    direction: Literal[DIRECTIONS]
    place: Optional[str] = None
    horizon: Literal[HORIZONS] = "not_stated"
    condition: Optional[str] = None

    @field_validator("segment", "direction", "horizon", mode="before")
    @classmethod
    def _enum(cls, v):
        return _norm_enum(v) if v is not None else v


class SplitOut(BaseModel):
    claims: list[VcaClaimOut] = Field(min_length=1)


class VerifyOut(BaseModel):
    verdict: Literal[VERDICTS]
    confidence: float = Field(ge=0, le=1)
    quote: Optional[str] = None
    rationale: Optional[str] = None

    @field_validator("verdict", mode="before")
    @classmethod
    def _enum(cls, v):
        return _norm_enum(v)


class PassageEvidence(BaseModel):
    passage: int = Field(ge=1, description="number of the passage as shown (P1 = 1)")
    verdict: Literal[EVIDENCE_VERDICTS]
    confidence: float = Field(ge=0, le=1)
    quote: str = Field(min_length=3)

    @field_validator("verdict", mode="before")
    @classmethod
    def _enum(cls, v):
        return _norm_enum(v)

    @field_validator("passage", mode="before")
    @classmethod
    def _num(cls, v):
        if isinstance(v, str):
            v = v.strip().upper().lstrip("P")
        return v


class VerifySetOut(BaseModel):
    evidence: list[PassageEvidence] = Field(default_factory=list)
    rationale: Optional[str] = None


class ExpandOut(BaseModel):
    terms: list[str] = Field(min_length=1)

    @field_validator("terms", mode="before")
    @classmethod
    def _clean(cls, v):
        if isinstance(v, str):
            v = [t for t in v.replace(";", ",").split(",")]
        out: list[str] = []
        for t in v or []:
            t = str(t).strip().strip("\"'")
            if t and len(t) <= 80 and t.lower() not in {x.lower() for x in out}:
                out.append(t)
        return out[:40]


# ---------------------------------------------------------------------------------------------
# JSON schemas for constrained decoding (Ollama's `format`); validation still runs on every answer
# ---------------------------------------------------------------------------------------------
def _inline(schema: dict) -> dict:
    """Resolve $ref/$defs so the schema is one self-contained tree, and drop titles and descriptions."""
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            return {k: walk(v) for k, v in node.items() if k not in ("$defs", "title", "description", "default")}
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node
    return walk(schema)


def _require_all(node):
    """Ask for every property: constrained decoders then always write the key (null where allowed)."""
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node["required"] = list(node["properties"])
        for v in node.values():
            _require_all(v)
    elif isinstance(node, list):
        for v in node:
            _require_all(v)
    return node


def output_schema(kind: str) -> dict:
    """The JSON schema a model's answer for this task kind must follow."""
    from .taxonomy import targets

    if kind == "extract":
        claim = _inline(ImpactClaimOut.model_json_schema())
        claim["properties"]["targets"]["items"]["properties"]["target"] = {"type": "string", "enum": sorted(targets())}
        inter = _inline(InteractionOut.model_json_schema())
        for k in ("from_target", "to_target"):
            inter["properties"][k] = {"type": "string", "enum": sorted(targets())}
        s = {"type": "object", "properties": {"claims": {"type": "array", "items": claim},
                                              "interactions": {"type": "array", "items": inter},
                                              "note": {"anyOf": [{"type": "string"}, {"type": "null"}]}}}
    elif kind == "split":
        s = _inline(SplitOut.model_json_schema())
    elif kind == "verify":
        s = _inline(VerifyOut.model_json_schema())
    elif kind in ("verify_set", "check"):
        s = _inline(VerifySetOut.model_json_schema())
    elif kind == "expand":
        s = _inline(ExpandOut.model_json_schema())
    else:
        raise ValueError(f"no output schema for task kind {kind!r}")
    return _require_all(s)
