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


def _none_words(v):
    if v is None:
        return None
    v = " ".join(str(v).split())
    return None if v.lower().strip(" .") in ("", "null", "none", "n/a", "no", "same", "nothing") else v


class CheckEvidence(PassageEvidence):
    """A grade of the hypothesis checker (check-v3): may say the passage is about another group or setting; (check-v4)
    may name what its quote refers to, quoted from the passage or the text before it."""
    scope_note: Optional[str] = Field(None, max_length=200)
    refers_to: Optional[str] = Field(None, max_length=200)

    @field_validator("scope_note", mode="before")
    @classmethod
    def _note(cls, v):
        v = _none_words(v)
        return v.strip(" .")[:200] if v else None

    @field_validator("refers_to", mode="before")
    @classmethod
    def _ref(cls, v):
        v = _none_words(v)
        return v.strip()[:200] if v else None


class CheckOut(BaseModel):
    evidence: list[CheckEvidence] = Field(default_factory=list)
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


PART_ROLES = ("condition", "mechanism", "outcome", "comparison", "scope", "component")


class HypothesisPart(BaseModel):
    text: str = Field(min_length=10, max_length=400)
    role: Literal[PART_ROLES] = "component"

    @field_validator("role", mode="before")
    @classmethod
    def _role(cls, v):
        v = _norm_enum(v) if v is not None else "component"
        return v if v in PART_ROLES else "component"


class DecomposeOut(BaseModel):
    parts: list[HypothesisPart] = Field(min_length=1, max_length=6)
    note: Optional[str] = None

    @field_validator("parts", mode="before")
    @classmethod
    def _strings(cls, v):  # a plain list of sentences is accepted too
        if isinstance(v, list):
            return [{"text": x} if isinstance(x, str) else x for x in v]
        return v


# ---------------------------------------------------------------------------------------------
# 0.7: codebook labels (label-v1), links between terms (link-v1), theme names (theme-v1), reference chains (resolve-v1)
# ---------------------------------------------------------------------------------------------
class CodeLabel(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    relevance: Literal["main", "mentioned"] = "mentioned"
    direction: Literal["helps", "hinders", "mixed", "not_stated"] = "not_stated"
    confidence: float = Field(ge=0, le=1)
    quote: str = Field(min_length=3)
    reason: str = Field("", max_length=200)

    @field_validator("code", mode="before")
    @classmethod
    def _code(cls, v):
        return str(v).strip() if v is not None else v

    @field_validator("relevance", mode="before")
    @classmethod
    def _rel(cls, v):
        v = _norm_enum(v) if v is not None else "mentioned"
        return {"main_topic": "main", "primary": "main", "central": "main", "mention": "mentioned",
                "minor": "mentioned", "secondary": "mentioned"}.get(v, v)

    @field_validator("direction", mode="before")
    @classmethod
    def _dir(cls, v):
        v = _norm_enum(v) if v is not None else "not_stated"
        return {"positive": "helps", "help": "helps", "negative": "hinders", "hinder": "hinders",
                "both": "mixed", "no_effect": "not_stated", "unclear": "not_stated"}.get(v, v)

    @field_validator("reason", mode="before")
    @classmethod
    def _reason(cls, v):
        return " ".join(str(v or "").split())[:200]


class LabelOut(BaseModel):
    labels: list[CodeLabel] = Field(default_factory=list)
    note: Optional[str] = None


LINK_RELATIONS = ("same", "broader", "narrower", "related", "different")


class TermLink(BaseModel):
    a: int = Field(ge=1)
    b: int = Field(ge=1)
    relation: Literal[LINK_RELATIONS]
    confidence: float = Field(ge=0, le=1)
    quote_a: str = Field(min_length=3)
    quote_b: str = Field(min_length=3)

    @field_validator("relation", mode="before")
    @classmethod
    def _rel(cls, v):
        v = _norm_enum(v)
        return {"synonym": "same", "equivalent": "same", "identical": "same", "parent": "broader",
                "child": "narrower", "hypernym": "broader", "hyponym": "narrower", "unrelated": "different",
                "co_occurs": "related"}.get(v, v)


class LinkOut(BaseModel):
    relations: list[TermLink] = Field(min_length=1)


class QuoteRef(BaseModel):
    passage: int = Field(ge=1)
    quote: str = Field(min_length=3)

    @field_validator("passage", mode="before")
    @classmethod
    def _num(cls, v):
        if isinstance(v, str):
            v = v.strip().upper().lstrip("P")
        return v


class ThemeOut(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    name_quote: QuoteRef
    description: str = Field(min_length=10, max_length=300)
    description_quote: QuoteRef

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v):
        v = " ".join(str(v or "").split()).strip(" .\"'")
        if len(v.split()) > 6:
            raise ValueError("the name must have at most six words")
        return v

    @field_validator("description", mode="before")
    @classmethod
    def _desc(cls, v):
        return " ".join(str(v or "").split())


class Mention(BaseModel):
    passage: int = Field(ge=1)
    span: str = Field(min_length=3, max_length=300)
    mention: str = Field(min_length=1, max_length=200)
    named: bool = False

    @field_validator("passage", mode="before")
    @classmethod
    def _num(cls, v):
        if isinstance(v, str):
            v = v.strip().upper().lstrip("P")
        return v


class Chain(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    mentions: list[Mention] = Field(min_length=1)


class ResolveOut(BaseModel):
    chains: list[Chain] = Field(default_factory=list)


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
    elif kind == "verify_set":
        s = _inline(VerifySetOut.model_json_schema())
    elif kind in ("check", "reread", "second"):
        s = _inline(CheckOut.model_json_schema())
    elif kind == "expand":
        s = _inline(ExpandOut.model_json_schema())
    elif kind == "decompose":
        s = _inline(DecomposeOut.model_json_schema())
    elif kind == "label":
        s = _inline(LabelOut.model_json_schema())
    elif kind == "link":
        s = _inline(LinkOut.model_json_schema())
    elif kind == "theme":
        s = _inline(ThemeOut.model_json_schema())
    elif kind == "resolve":
        s = _inline(ResolveOut.model_json_schema())
    else:
        raise ValueError(f"no output schema for task kind {kind!r}")
    return _require_all(s)
