# The validation gold set (roadmap J4.3, ENLENS 0.18.4)

Known right answers that ENLENS's AI answers are scored against, for the AI half of the validation report
(`validation-report-ai.md`, made by `enlens validate report`, see `src/enlens_claims/validation.py`). The half without
AI is `enlens measure`.

## What it holds

- **The corpus:** the six documents of `tools/demo_corpus/` (read from there, never copied) and seven more in
  `documents/` (about 5,000 words): a trade-union survey, an employer's evaluation, a randomised trial, a city transport
  memo, a study of managers, an occupational health report and an opinion column. All on remote work, and **all
  invented**: every person, organisation, place and figure is fictional. Each paragraph of the new documents is 300 to
  900 characters, so that ENLENS reads it as one passage.
- **`hypotheses.csv`:** 30 hypotheses with the verdict ENLENS should reach over the whole corpus: 7 supported,
  6 partly supported, 6 contradicted, 5 contested (mixed evidence), 6 with nothing found; 6 of them compound (two
  claims that must both hold). Each gives the deciding quotes and how each grades. The verdicts follow ENLENS's own
  rules: the check prompt's grades (`prompts.py`, kind `check`) and how grades and parts make a verdict
  (`verdicts.claim_status`, `verdicts.aggregate`).
- **`codebook.csv`:** 10 codes made for this corpus (code, description).
- **`labels.csv`:** 110 passages (every body passage of the 13 documents) with the codes each is mainly about
  (`codes`, scored) and the codes it only touches in passing (`mentioned`, scored neither way). 16 have no code. A
  passage is found by its file and its opening words (`anchor`); `enlens validate prepare` stops when an anchor is in
  no passage or in more than one, which happens when a new reader cuts the documents differently.

## How it was made

1. One AI (Claude Sonnet, as a subagent) wrote the seven documents and the answers together, so each right answer
   was made by construction, following ENLENS's rules as written above (`AUTHORING_NOTES.md` are its notes).
2. A second AI (Claude Opus, a fresh subagent) checked every verdict and every label against the document text alone,
   searching the whole corpus for evidence the author missed. It agreed with all 30 verdicts and 106 of 110 labels.
3. The four label disagreements were settled by hand (13 November 2026), each in the reviewer's favour (the row's
   `note` starts with "review:"), and the codebook's two overlaps it found were removed: work-life balance belongs to
   WELLBEING only, and shared office days count as TEAMWORK when they are kept for working together.
4. Neither AI ever saw a model's answers to these tasks. The set was then frozen: `enlens validate` records its
   fingerprint in every run, and a report made from a run on an older version of the set says so.

## Its limits

- **Invented and tidy.** The documents were written to make the right answers clear; real documents are longer, less
  tidy and more ambiguous. The figures are closer to an upper bound than to a forecast.
- **Small.** One hypothesis is about three points of accuracy; a change of a few points between runs means little.
- **English only, one subject, one codebook.**
- **Written by AI.** Checked by a second AI and by hand, but it may still hold mistakes. Calls a careful reader could
  make differently, all kept after the review: H10 (consultations for back and neck complaints stand in for sickness
  absence: partly), H15 (staff naming the policy as a reason to stay, with a caveat in the same passage: partly), H21
  (more delivery vans read as the reason congestion did not fall, rather than as support: contradicted), H24 (eight
  of 31 managers "at least once": graded supports, contested either way) and H26 (bigger gains for long commutes
  fit "by cutting travel time" without testing it: partly). Demo passages that join two headed sections (*Office
  space* with *Services to citizens*; *Career worries* with *Recommendations*) are the hardest to label as one unit.

## Changing it

Change it only on purpose, and record a new run afterwards (`docs/DEVELOPING.md`, *The validation report*). Do not add
files to `tools/demo_corpus/`: interface tests and the first-run copy use it. Recorded runs are in `runs/`.
