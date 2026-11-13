### New

- **The assessment in words.** Under a hypothesis's answer, a few sentences say what it rests on: how many documents
  stand on each side, the contradicting side quoted (and both sides when the evidence is mixed), a warning when one
  document, one year or one kind of document carries most of the support, what holds for each part, and what is not
  counted (below your strictness, or waiting for your judgement or the local model). They are made by fixed rules
  from the judgements, never written by an AI, so they read the same each time. When your own judgements give another
  answer than the AI's alone, it names the judgement that moved it ("Your judgement on Jones 2022, page 12 turned
  this from Supported to Mixed evidence"), and the research log records each such change. The Excel summary, CSV and
  JSON carry it too. Excerpts of documents no AI may read, or only a local one, are counted, never quoted. Cannot
  change results.

### For developers

- `assessment.assess(ws, hyp_id, res)` → `{"sentences": [{"text", "rule", "refs"}], "moved_by"}`, in
  `hypothesis_result(...)["assessment"]`; `claimcheck.set_judgement` now returns
  `{"hyp_id", "before", "after", "moved"}` and logs `verdict-moved`, at the strictness the page shows
  (`threshold`, also in the body of `PUT …/judgements/…`). Tests: `tests/test_assessment.py`.

### Not yet done

- The words of an AI are not offered beside the rules' sentences (the roadmap keeps that for later, marked as the
  AI's).
