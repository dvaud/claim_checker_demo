"""Prompt templates. Each task kind has a version; results record it so runs stay comparable."""
from __future__ import annotations

import json

from .taxonomy import targets_reference_text

VERSIONS = {"extract": "extract-v1", "split": "split-v2", "verify": "verify-v1", "verify_set": "verify-set-v1",
            "expand": "expand-v1", "check": "check-v1"}

_JSON_RULE = ("Answer with one JSON object and nothing else: no prose, no code fences. "
              "Copy every quote character for character from the text you were given, including odd spacing or "
              "typos from PDF extraction. Never shorten a quote with an ellipsis; quote a shorter contiguous span instead.")

DEFINITIONS = """Definitions used by every task
- Value chain segments: production (electrolysis, its electricity, water and land use, plant construction),
  transportation (storage, conversion to carriers such as ammonia, pipelines, shipping, ports),
  end_use (fuel cells, industry such as steel and fertiliser, power, mobility). Use whole_chain when the text
  is about green hydrogen in general, unclear when you cannot tell.
- direction: positive = helps progress on the SDG target; negative = hinders it; mixed = the text gives both;
  no_effect = the text says there is no effect.
- influence: direct = the activity itself changes the target's outcome (for example water withdrawal at the
  plant); indirect = through an intermediate mechanism (prices, policies, jobs elsewhere, supply chains).
- horizon: short_term = up to 2030, current or near-term; medium_long_term = after 2030 or "long term";
  not_stated = no time is given or implied by the text.
- side: where the effect lands: producer (producing or exporting country), importer, both, unspecified.
- Interaction scores (Nilsson et al. 2016): +3 indivisible, +2 reinforcing, +1 enabling, 0 consistent,
  -1 constraining, -2 counteracting, -3 cancelling."""


def _targets_block() -> str:
    return "SDG targets (use these codes exactly; lettered targets such as 7.b are valid):\n" + targets_reference_text()


def system_prompt(kind: str) -> str:
    if kind == "extract":
        return f"""You extract evidence-backed impact claims from scientific and policy texts about the green hydrogen value chain,
for a Value Chain Assessment against the UN Sustainable Development Goals.

An impact claim says that an activity in the hydrogen value chain (or a hydrogen derivative such as ammonia or e-fuels)
affects one or more SDG targets. Extract only claims the PASSAGE itself states. Do not add general knowledge.
Background facts, definitions and methods are not claims. Return an empty list when there is no claim.

Rules
- One claim per distinct effect. If one effect touches several targets, list them all under targets.
- Choose the most specific target codes that fit; prefer one to three per claim.
- Every claim needs at least one evidence quote with field "claim". Add quotes for place, horizon, condition
  or policy_lever when the passage states them (field names: "place", "horizon", "condition", "policy_lever").
- Quotes must come from the PASSAGE, not from CONTEXT. CONTEXT is only there to resolve words like "it" or "this".
- condition: a circumstance under which the effect holds or disappears (for example "if desalinated water is used").
  policy_lever: an action that would change the effect (for example "local manufacturing of electrolysers").
- interactions: only when the passage states that progress on one SDG target affects another. Leave empty otherwise.
- confidence: your probability that all fields of the claim are correct.

{DEFINITIONS}

Output format
{{"claims": [{{"claim": "one-sentence paraphrase", "activity": "...", "segment": "production",
  "targets": [{{"target": "6.4", "direction": "negative", "influence": "direct"}}],
  "place": "arid regions" or null, "countries": ["Morocco"], "scale": "local|national|regional|global|unspecified",
  "side": "producer|importer|both|unspecified", "horizon": "short_term|medium_long_term|not_stated",
  "condition": null, "policy_lever": null, "confidence": 0.0-1.0,
  "evidence": [{{"field": "claim", "quote": "exact words from the passage"}}]}}],
 "interactions": [{{"from_target": "7.2", "to_target": "6.4", "score": -1, "quote": "exact words"}}],
 "note": null}}
{_JSON_RULE}

{_targets_block()}"""
    if kind == "split":
        return f"""You split an expert's justification from a Value Chain Assessment of green hydrogen into atomic claims.

Each atomic claim states one effect of the green hydrogen value chain on the given SDG target, with its direction,
and where stated the segment, place, time horizon and condition. Keep the expert's meaning; do not add facts.
Each claim needs a quote: the shortest contiguous span of the JUSTIFICATION that states it.
Direction, segment and horizon follow the JUSTIFICATION text. The VCA table cells and horizon are given as
context only: use the cells to choose a segment when the text does not name one, and never copy the table horizon
into a claim; use not_stated unless the text itself gives a time.

{DEFINITIONS}

Output format
{{"claims": [{{"text": "one-sentence claim", "quote": "exact span of the justification",
  "segment": "production|transportation|end_use|whole_chain|unclear", "direction": "positive|negative|mixed|no_effect",
  "place": null, "horizon": "short_term|medium_long_term|not_stated", "condition": null}}]}}
{_JSON_RULE}"""
    if kind == "verify":
        return f"""You check whether a source passage supports a claim about the effects of green hydrogen on an SDG target.

Verdicts
- supports: the passage states the same effect, in the same direction, for the same kind of outcome. It may be
  narrower (for example one country) as long as it is the same effect.
- refutes: the passage states the opposite effect, or that there is no such effect.
- not_enough_info: the passage is on the topic but does not state the effect, or is about something else.
Being on the same topic is not support. Do not use outside knowledge.
For supports and refutes give the shortest quote from the PASSAGE that shows it; for not_enough_info use null.
confidence: your probability that the verdict is right.

Output format
{{"verdict": "supports|refutes|not_enough_info", "confidence": 0.0-1.0, "quote": "exact words" or null,
  "rationale": "one short sentence"}}
{_JSON_RULE}"""
    if kind == "verify_set":
        return f"""You check whether source passages support a claim about the effects of green hydrogen on an SDG target.
The claim comes from an expert assessment; the passages come from the works the expert cited for that target.

Grade each passage that bears on the claim:
- supports: the passage states the claim's effect, in the same direction, for the same kind of outcome. It may be
  narrower or broader in place (one country rather than a region) as long as it is the same effect.
- partially_supports: the passage states a necessary part of the claim but not the whole, so a reader needs one
  further inference to reach the claim. Examples: the mechanism without its effect on the target's outcome; the
  converse case (local value chains raise local benefits, for a claim that import dependence limits them); the
  same effect for another value chain segment or for renewable energy in general rather than hydrogen.
- refutes: the passage states the opposite effect, or that there is no such effect.
Leave out passages that are only on the same topic. Do not use outside knowledge.
For every passage you list, give the shortest quote from THAT passage that shows it, and your probability that
the grade is right. List no passage at all when none bears on the claim.

Output format
{{"evidence": [{{"passage": 2, "verdict": "supports|partially_supports|refutes", "confidence": 0.0-1.0,
  "quote": "exact words from passage 2"}}],
  "rationale": "one or two short sentences on the overall picture"}}
{_JSON_RULE}"""
    if kind == "check":
        return f"""You check whether passages from a set of documents support a claim.

Grade each passage that bears on the claim:
- supports: the passage states the claim's effect or fact, in the same direction, for the same kind of outcome.
  It may be narrower or broader in place (one country rather than a region) as long as it is the same effect.
- partially_supports: the passage states a necessary part of the claim but not the whole, so a reader needs one
  further inference to reach the claim. Examples: the mechanism without its effect on the outcome; the converse
  case (local value chains raise local benefits, for a claim that import dependence limits them); the same effect
  for another part of the value chain, another place or a related technology.
- refutes: the passage states the opposite, or that there is no such effect.
Leave out passages that are only on the same topic. Do not use outside knowledge.
For every passage you list, give the shortest quote from THAT passage that shows it, and your probability that
the grade is right. List no passage at all when none bears on the claim.

Output format
{{"evidence": [{{"passage": 2, "verdict": "supports|partially_supports|refutes", "confidence": 0.0-1.0,
  "quote": "exact words from passage 2"}}],
  "rationale": "one or two short sentences on the overall picture"}}
{_JSON_RULE}"""
    if kind == "expand":
        return """You prepare a search of reports and scientific papers for passages that bear on a claim.

Give search terms: the claim's key words, synonyms and related technical terms, the outcome it is about, and the
words a source would use to state the opposite. Single words or short phrases, at most 20 terms, in the language
of the claim. Do not judge the claim.

Output format
{"terms": ["...", "..."]}
Answer with one JSON object and nothing else: no prose, no code fences."""
    raise ValueError(f"unknown task kind {kind!r}")


def user_prompt(kind: str, payload: dict) -> str:
    if kind == "extract":
        parts = [f"DOCUMENT: {payload.get('title') or 'untitled'}"]
        if payload.get("doi"):
            parts.append(f"DOI: {payload['doi']}")
        if payload.get("page"):
            parts.append(f"PAGE: {payload['page']}")
        if payload.get("context"):
            parts.append(f"CONTEXT (not quotable):\n{payload['context']}")
        parts.append(f"PASSAGE:\n{payload['text']}")
        return "\n\n".join(parts)
    if kind == "split":
        return (f"TARGET {payload['target']}: {payload['description']}\n\n"
                f"VCA cells for this target (segment: influence): {json.dumps(payload.get('cells', {}))}\n"
                f"VCA time horizon: {payload.get('horizon') or 'not given'}\n\n"
                f"JUSTIFICATION:\n{payload['justification']}")
    if kind == "verify":
        return (f"CLAIM (about SDG target {payload['target']}: {payload['target_description']}):\n{payload['claim']}\n\n"
                f"SOURCE: {payload.get('title') or 'untitled'}" + (f", page {payload['page']}" if payload.get("page") else "") + "\n\n"
                f"PASSAGE:\n{payload['text']}")
    if kind == "expand":
        return f"CLAIM:\n{payload['claim']}"
    if kind == "check":
        head = "CLAIM"
        if payload.get("target"):
            head += f" (about SDG target {payload['target']}: {payload.get('target_description', '')})"
        parts = [f"{head}:\n{payload['claim']}"]
        for i, p in enumerate(payload["passages"], 1):
            src = (p.get("title") or "untitled") + (f", page {p['page']}" if p.get("page") else "")
            parts.append(f"P{i} | {src}\n{p['text']}")
        return "\n\n".join(parts)
    if kind == "verify_set":
        parts = [f"CLAIM (about SDG target {payload['target']}: {payload['target_description']}):\n{payload['claim']}"]
        for i, p in enumerate(payload["passages"], 1):
            src = (p.get("title") or "untitled") + (f", page {p['page']}" if p.get("page") else "")
            parts.append(f"P{i} | {src}\n{p['text']}")
        return "\n\n".join(parts)
    raise ValueError(f"unknown task kind {kind!r}")
