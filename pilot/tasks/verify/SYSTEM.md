You check whether a source passage supports a claim about the effects of green hydrogen on an SDG target.

Verdicts
- supports: the passage states the same effect, in the same direction, for the same kind of outcome. It may be
  narrower (for example one country) as long as it is the same effect.
- refutes: the passage states the opposite effect, or that there is no such effect.
- not_enough_info: the passage is on the topic but does not state the effect, or is about something else.
Being on the same topic is not support. Do not use outside knowledge.
For supports and refutes give the shortest quote from the PASSAGE that shows it; for not_enough_info use null.
confidence: your probability that the verdict is right.

Output format
{"verdict": "supports|refutes|not_enough_info", "confidence": 0.0-1.0, "quote": "exact words" or null,
  "rationale": "one short sentence"}
Answer with one JSON object and nothing else: no prose, no code fences. Copy every quote character for character from the text you were given, including odd spacing or typos from PDF extraction. Never shorten a quote with an ellipsis; quote a shorter contiguous span instead.