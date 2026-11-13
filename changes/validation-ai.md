### New

- **The validation report's AI half.** Each release now carries `validation-report-ai.md` beside
  `validation-report.md`: how often ENLENS's AI gives the right answer on a small gold set of invented documents on
  remote work, whose right answers are known (about 30 hypotheses to check and 100 passages to label with a codebook
  made for it). Per kind it gives the share of right answers and Cohen's kappa, how many answers were first rejected
  for a quote that is not in the text, and how often a second run gave the same answer. It is made from a recorded,
  dated run, and says its limits: invented, tidy documents, a small set, English only. Changes no result.

### For developers

- **`enlens validate prepare | score | report`** (`validation.py`): a new project from the gold set in
  `tools/validation/` with its checks and labels queued; the answered project (and a second pass, `--again`) scored
  into `tools/validation/runs/<date>-<route>.json`, every answer with its model, prompt version, ENLENS version and
  date; and the report made from the newest run file with no AI, as the release workflow does. When to record a new
  run, and how: docs/DEVELOPING.md.

### Not yet done

- No reference set of real documents filled in by a person: the gold set is invented, small and in English only.
- The recorded run is on Claude only. A run on a local model (Ollama) is not recorded yet: it needs a computer with
  memory to spare for the model.
