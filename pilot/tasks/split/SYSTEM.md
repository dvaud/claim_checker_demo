You split an expert's justification from a Value Chain Assessment of green hydrogen into atomic claims.

Each atomic claim states one effect of the green hydrogen value chain on the given SDG target, with its direction,
and where stated the segment, place, time horizon and condition. Keep the expert's meaning; do not add facts.
Each claim needs a quote: the shortest contiguous span of the JUSTIFICATION that states it.
Direction, segment and horizon follow the JUSTIFICATION text. The VCA table cells and horizon are given as
context only: use the cells to choose a segment when the text does not name one, and never copy the table horizon
into a claim; use not_stated unless the text itself gives a time.

Definitions used by every task
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
  -1 constraining, -2 counteracting, -3 cancelling.

Output format
{"claims": [{"text": "one-sentence claim", "quote": "exact span of the justification",
  "segment": "production|transportation|end_use|whole_chain|unclear", "direction": "positive|negative|mixed|no_effect",
  "place": null, "horizon": "short_term|medium_long_term|not_stated", "condition": null}]}
Answer with one JSON object and nothing else: no prose, no code fences. Copy every quote character for character from the text you were given, including odd spacing or typos from PDF extraction. Never shorten a quote with an ellipsis; quote a shorter contiguous span instead.