"""Prompt templates. Each task kind has a version; results record it so runs stay comparable."""
from __future__ import annotations

import json

from .taxonomy import targets_reference_text

VERSIONS = {"extract": "extract-v1", "split": "split-v2", "verify": "verify-v1", "verify_set": "verify-set-v1",
            "expand": "expand-v2", "check": "check-v4", "decompose": "decompose-v1",
            "reread": "check-v4",   # reading one excerpt again uses the check prompt
            "second": "check-v4",   # so does a second model grading the excerpts already read
            # 0.7
            "label": "label-v1", "link": "link-v1", "theme": "theme-v1", "resolve": "resolve-v1"}

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
    if kind in ("check", "reread", "second"):
        return f"""You check whether passages from a set of documents support a claim or hypothesis.

Grade each passage that bears on the claim:
- supports: the passage states the claim's effect, finding or fact, in the same direction, for the same kind of
  outcome. It may be narrower or broader in place, time or population (one country rather than a region) as long
  as it is the same effect.
- partially_supports: the passage states a necessary part of the claim but not the whole, so a reader needs one
  further inference to reach the claim. Examples: the mechanism without its effect on the outcome; the converse
  case (a passage that local production raises local benefits, for a claim that dependence on imports limits them);
  the same effect for another group, place, period or a closely related subject; a weaker or conditional version.
- refutes: the passage states the opposite, that there is no such effect, or a finding that cannot hold if the
  claim is true.
Leave out passages that are only on the same topic, that merely mention the words of the claim, or that report
what others expect without evidence. Do not use outside knowledge.
For every passage you list, give the shortest quote from THAT passage that shows it, and your probability that
the grade is right.
scope_note: when a passage is about another group, setting, place or period than the claim names (fully remote
workers for a claim about hybrid workers, all ages for a claim about young employees, another country or decade),
say so in a few words, for example "about fully remote workers, not hybrid". Such a passage is graded no higher
than partially_supports. Use null when the passage is about what the claim names.
refers_to: when your quote depends on a word such as "it", "this", "they" or "the plant" whose meaning comes from
earlier text, give the named form it refers to ("the planned electrolyser plant in Aqaba"), copied exactly from the
passage or from the text BEFORE it, which is shown above some passages for this purpose only. Use null when the quote
names what it is about. Never grade a passage on the text before it.
List no passage at all when none bears on the claim.

Output format
{{"evidence": [{{"passage": 2, "verdict": "supports|partially_supports|refutes", "confidence": 0.0-1.0,
  "quote": "exact words from passage 2", "scope_note": null, "refers_to": null}}],
  "rationale": "one or two short sentences on the overall picture"}}
{_JSON_RULE}"""
    if kind == "label":
        return f"""You label a passage from a report or paper with the codes of a codebook that it addresses.

You are given the passage, the text just before it (CONTEXT, to resolve words like "it"; never label or quote it),
and candidate codes found by a keyword and meaning search. The candidates are only suggestions: label a code only
when the PASSAGE itself addresses it. You may add another code of the same codebook if the passage clearly addresses
it better; write its code exactly as the codebook does.

For every code that applies:
- relevance: main = the passage is about this code's subject; mentioned = the passage touches it in passing.
- direction (only when the codebook's codes are aims a text can help or hinder, as it says below; otherwise
  not_stated): helps = the passage says something advances the aim; hinders = something works against it;
  mixed = both; not_stated = the passage does not say.
- confidence: your probability that the label is right.
- quote: the shortest span of the PASSAGE that shows why the code applies, copied exactly.
- reason: why the code applies, in at most 200 characters.
Label nothing when no code applies; an empty list is a valid answer. Do not use outside knowledge.

Output format
{{"labels": [{{"code": "6.4", "relevance": "main|mentioned", "direction": "helps|hinders|mixed|not_stated",
  "confidence": 0.0-1.0, "quote": "exact words from the passage", "reason": "at most 200 characters"}}],
 "note": null}}
{_JSON_RULE}"""
    if kind == "link":
        return f"""You judge how terms used in a set of documents relate, from the way the documents use them.

Each term comes with short passages where it occurs. For each pair of terms, give the relation:
- same: the documents use both for the same thing (a synonym, an abbreviation, another spelling);
- broader: the first term (a) is a broader category that includes the second (b);
- narrower: the first term (a) is a kind or part of the second (b);
- related: different things that are discussed together or depend on each other;
- different: unrelated, or different things that share words.
Judge from the passages, not from outside knowledge. For each side give one quote, copied exactly from a passage of
that term, that shows how the documents use it. confidence: your probability that the relation is right.

Output format
{{"relations": [{{"a": 1, "b": 2, "relation": "same|broader|narrower|related|different", "confidence": 0.0-1.0,
  "quote_a": "exact words from a passage of term 1", "quote_b": "exact words from a passage of term 2"}}]}}
{_JSON_RULE}"""
    if kind == "theme":
        return f"""You name a theme: a group of passages from a set of documents that discuss the same subject.

You are given the passages that represent the theme best and the key terms that set it apart from the rest of the
documents. Give
- name: at most six words, the subject the passages share (not a sentence, no quotation marks);
- name_quote: one quote, copied exactly from one of the passages, that shows the passages are about that subject;
- description: one sentence on what the passages discuss, using only what they say;
- description_quote: one quote, copied exactly from one of the passages, that supports the description.
Do not use outside knowledge and do not summarise beyond the passages.

Output format
{{"name": "at most six words", "name_quote": {{"passage": 1, "quote": "exact words"}},
 "description": "one sentence", "description_quote": {{"passage": 2, "quote": "exact words"}}}}
{_JSON_RULE}"""
    if kind == "resolve":
        return f"""You find chains of references in consecutive passages of one document: the places that refer to the same
thing (a plant, a policy, a country, a group of people, a technology).

A chain has a name (the clearest named form of the thing in the passages) and its mentions: named forms
("the Aqaba electrolyser plant"), short names ("the plant"), and pronouns ("it", "its", "they", "this project").
Give only chains with at least two mentions, and only things the passages name at least once. Leave out generic
words that do not point back to something ("it is important that").
For every mention give
- passage: the number of the passage it is in;
- span: three to twelve words copied exactly from that passage, containing the mention, so its place is clear;
- mention: the exact words of the mention, as they stand inside the span;
- named: true for a named form, false for a pronoun or a short description.

Output format
{{"chains": [{{"name": "the Aqaba electrolyser plant",
  "mentions": [{{"passage": 1, "span": "the Aqaba electrolyser plant will start", "mention": "the Aqaba electrolyser plant", "named": true}},
               {{"passage": 2, "span": "It requires 1.5 million cubic metres", "mention": "It", "named": false}}]}}]}}
{_JSON_RULE}"""
    if kind == "expand":
        return """You prepare a search of reports and scientific papers for passages that bear on a claim.

Give search terms: the claim's key words, synonyms and related technical terms, the outcome it is about, the
measures a study would report, and the words a source would use to state the opposite. Single words or short
phrases, at most 20 terms, in the language of the claim; if the claim is not in English, add the main terms in
English too. Do not judge the claim.

Output format
{"terms": ["...", "..."]}
Answer with one JSON object and nothing else: no prose, no code fences."""
    if kind == "decompose":
        return """You split a hypothesis into the claims that must all hold for it to be true, so each can be checked
against documents on its own.

Rules
- Each part is one plain, self-contained sentence that a source could state or contradict. Repeat the subject
  instead of writing "it" or "this".
- Together the parts say what the hypothesis says: keep its meaning, direction, place, time and conditions; do not
  add facts, causes or qualifications of your own, and do not judge whether they are true.
- Give 2 to 5 parts. If the hypothesis is already one simple claim, return it unchanged as the only part.
- role: condition (a circumstance it assumes), mechanism (how the effect comes about), outcome (the effect itself),
  comparison (more or less than something else), scope (where, when or for whom), component (anything else).

Output format
{"parts": [{"text": "one checkable sentence", "role": "mechanism"}], "note": null}
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
        out = f"CLAIM:\n{payload['claim']}"
        if payload.get("context"):
            out += f"\n\nIt is part of this hypothesis:\n{payload['context']}"
        return out
    if kind == "decompose":
        return f"HYPOTHESIS:\n{payload['hypothesis']}"
    if kind in ("check", "reread", "second"):
        head = "CLAIM"
        if payload.get("target"):
            label = payload.get("framework_label") or "SDG target"
            head += f" (about {label} {payload['target']}: {payload.get('target_description', '')})"
        parts = [f"{head}:\n{payload['claim']}"]
        for i, p in enumerate(payload["passages"], 1):
            src = (p.get("title") or "untitled") + (f", page {p['page']}" if p.get("page") else "")
            if p.get("context"):  # check-v4: the text just before, for refers_to only
                parts.append(f"BEFORE P{i} (for refers_to only; not to be graded or quoted as evidence):\n…{p['context']}")
            parts.append(f"P{i} | {src}\n{p['text']}")
        if payload.get("read_elsewhere"):  # 0.11: the round's other excerpts come from documents kept from this model
            n = payload["read_elsewhere"]
            parts.append(f"{n} other {'excerpt' if n == 1 else 'excerpts'} for this claim {'comes' if n == 1 else 'come'} "
                         "from documents you are not shown; they are judged separately. Grade only the passages above, "
                         "and in your rationale speak only for them.")
        if payload.get("reader_note"):  # a person's comment when they ask for one excerpt to be read again
            parts.append(f"A reader noted (a hint to check against the passage, not evidence): {payload['reader_note']}")
        if kind == "reread":
            parts.append("This passage is read again on request. In \"rationale\", say in one or two sentences why you "
                         "grade it as you do" + (", and whether the reader's note changed your judgement and why."
                                                 if payload.get("reader_note") else "."))
        return "\n\n".join(parts)
    if kind == "label":
        parts = [f"CODEBOOK: {payload.get('framework_title') or payload['framework']} (a code is called a "
                 f"{payload.get('code_label') or 'code'}). Directions apply: "
                 f"{'yes' if payload.get('directional') else 'no (use not_stated)'}."]
        cands = payload.get("candidates") or []
        parts.append("CANDIDATE CODES:\n" + ("\n".join(f"{c['code']}: {c['description']}" for c in cands)
                                              if cands else "(none found by the search: name codes only if the passage "
                                                            "clearly addresses them)"))
        parts.append(f"DOCUMENT: {payload.get('title') or 'untitled'}" + (f", page {payload['page']}" if payload.get("page") else ""))
        if payload.get("context"):
            parts.append(f"CONTEXT (not to be labelled or quoted):\n…{payload['context']}")
        parts.append(f"PASSAGE:\n{payload['text']}")
        return "\n\n".join(parts)
    if kind == "link":
        parts = []
        for t in payload["terms"]:
            lines = [f"TERM {t['n']}: {t['label']}"]
            for j, sn in enumerate(t["snippets"], 1):
                lines.append(f"  passage {t['n']}.{j} ({sn.get('title') or 'untitled'}): {sn['text']}")
            parts.append("\n".join(lines))
        n = len(payload["terms"])
        pairs = ", ".join(f"({a}, {b})" for a in range(1, n + 1) for b in range(a + 1, n + 1))
        parts.append(f"Give the relation for each pair: {pairs}.")
        return "\n\n".join(parts)
    if kind == "theme":
        parts = [f"KEY TERMS: {', '.join(payload.get('terms') or [])}"]
        for p in payload["passages"]:
            src = (p.get("title") or "untitled") + (f", page {p['page']}" if p.get("page") else "")
            parts.append(f"P{p['n']} | {src}\n{p['text']}")
        return "\n\n".join(parts)
    if kind == "resolve":
        parts = [f"DOCUMENT: {payload.get('title') or 'untitled'}"]
        if payload.get("name"):
            parts.append(f"Look in particular for the chain of: {payload['name']}")
        for p in payload["passages"]:
            parts.append(f"P{p['n']}" + (f" (page {p['page']})" if p.get("page") else "") + f"\n{p['text']}")
        return "\n\n".join(parts)
    if kind == "verify_set":
        parts = [f"CLAIM (about SDG target {payload['target']}: {payload['target_description']}):\n{payload['claim']}"]
        for i, p in enumerate(payload["passages"], 1):
            src = (p.get("title") or "untitled") + (f", page {p['page']}" if p.get("page") else "")
            parts.append(f"P{i} | {src}\n{p['text']}")
        return "\n\n".join(parts)
    raise ValueError(f"unknown task kind {kind!r}")
