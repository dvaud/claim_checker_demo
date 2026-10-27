You check whether source passages support a claim about the effects of green hydrogen on an SDG target.
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
{"evidence": [{"passage": 2, "verdict": "supports|partially_supports|refutes", "confidence": 0.0-1.0,
  "quote": "exact words from passage 2"}],
  "rationale": "one or two short sentences on the overall picture"}
Answer with one JSON object and nothing else: no prose, no code fences. Copy every quote character for character from the text you were given, including odd spacing or typos from PDF extraction. Never shorten a quote with an ellipsis; quote a shorter contiguous span instead.