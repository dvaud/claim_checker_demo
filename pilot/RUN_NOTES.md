# Pilot run notes: green hydrogen VCA

Run in October 2026 with `enlens-claims` 0.1. These notes cover what was run, in which order, what changed along
the way and why, and what it cost. The findings and their interpretation are in the team document (the "Pilot
results" tab of the ENLENS overview doc). The numbers are in `report/report.html` and `report/metrics.json`.

## Inputs

- **VCA:** supplementary workbook of Peyerl & van der Zwaan (2024), `43621_2024_374_MOESM1_ESM.xlsx`. The loaded totals
  match the paper (169 targets, 61 justified, 30 direct, 119 indirect, 86 positive, 63 negative, 47 short term,
  14 medium to long term). 97 reference entries, of which 4 are duplicates (merged) and 3 needed fixed DOIs
  (`reference_fixes.csv`), leaving 93 distinct works.
- **Sources:** legally free copies only (publisher open access, official agency sites, legal repositories), collected
  by the user. Nothing came from paywalled or institution-only access. They were converted on the user's computer with
  `tools/pdf_to_text.py` and uploaded as `enlens_text.zip` (39 files plus `manifest.csv`).
  - `A_18` was left out (`--exclude 'A_18_*'`). It is the agenda of the launch event, not the TERI report.
  - `A_10` (Azadnia et al. 2023) has a text layer without a character map, so it is unreadable after page 1. It stays
    linked to its reference but does not count as an available source.
  - `B_27` (IEA SDG7 data and projections) is a web landing page of 2,400 characters with no report text. It is
    flagged "very short" in the report.
  - Result: 38 documents, 11,312 passages (8,779 body text). 38 references are linked through the manifest, and
    50 of the 61 justified targets have at least one readable cited source.
  - Targets without one: 5.5 and 17.16 (only A_10 or A_18 would cover them), plus 6.4, 6.a, 8.1, 9.2, 10.2, 11.2,
    12.7, 13.2 and 15.9.

## Commands, in order

```bash
enlens --ws pilot init
enlens --ws pilot load-vca 43621_2024_374_MOESM1_ESM.xlsx
enlens --ws pilot make-tasks split                     # 61 tasks, Fable 5.1, prompt split-v2 -> 217 VCA claims
# (split ran before the corpus was final; reset-corpus keeps it)
enlens --ws pilot reset-corpus --yes                   # dropped the earlier markdown version of the corpus
enlens --ws pilot ingest enlens_text.zip --exclude 'A_18_*'
enlens --ws pilot match-sources
enlens --ws pilot coverage
enlens --ws pilot screen                               # 7,635 passages screened in
enlens --ws pilot make-tasks verify-vca --k 6          # 178 verify_set tasks (39 VCA claims have no source)
enlens --ws pilot make-tasks extract --per-target 6    # 319 tasks (+ 40 from the calibration batch)
enlens --ws pilot export-tasks verify_set --batch-size 15
enlens --ws pilot export-tasks extract --batch-size 40
# Claude Opus 5.5 workers answered the batches (file queue), each running check-results on its own file
enlens --ws pilot import-results pilot/results/extract pilot/results/verify_set
enlens --ws pilot make-tasks audit-vca --sample 0.1 --model claude-fable-5-1       # 14 tasks
enlens --ws pilot make-tasks verify-claims --sample 0.1 --model claude-fable-5-1   # 34 tasks
# Claude Fable 5.1 workers answered both audit batches
enlens --ws pilot import-results pilot/results/verify_set/batch_0013.jsonl pilot/results/verify/batch_0001.jsonl
enlens --ws pilot evaluate
enlens --ws pilot report
```

## What changed during the run, and why

1. **Calibration batches first.** One batch of each task kind was run before the rest.
   - 72 of 75 one-passage checks (`verify`, pairwise) found no support, often where a passage stated part of the
     claim (the mechanism, the converse case, the same effect for renewables in general). Verification was
     redesigned as `verify_set`: one task per VCA claim showing up to 6 passages (at most 2 per document first),
     with a `partially_supports` grade. The pairwise answers are kept in `results/calibration/` and were not
     imported.
   - 25 of the 40 extraction passages chosen by per-target ranking did not mention hydrogen; they came mostly from
     a general energy outlook. Per-target selection now ranks only passages that name hydrogen or a derivative
     (themselves or in the preceding passage). The 40 calibration answers were imported: they are valid claims
     from their passages, but they were selected under the earlier rule.
2. **Ingest fixes from the uploaded corpus.**
   - Detection of glyph-code garble beyond `(cid:N)`, which caught A_10.
   - Note files (`problems.txt`) are no longer ingested as documents. One had been, and was matched to two
     references.
   - The `--exclude` option.
   - Unreadable documents no longer count as available sources.
3. **Workers.** `check-results` was added so each worker could validate its file before handing it back. Two
   parallel workers shared a scratch folder in the first wave and overwrote each other's helper scripts; one
   worker's lines landed in another's file and were moved back. All results files were checked to hold exactly
   their batch's task ids before import. Later workers each had their own folder.
4. **Report.**
   - Partial support, a threshold sensitivity table and the VCA text-versus-colour check were added.
   - Target presence is now scored over all 169 targets (within the justified targets every target is positive,
     so κ was meaningless).
   - Interaction tables show only pairs found in two or more documents.
   - A Sources table flags unreadable and very short documents.
   - The second-model audit summary was added.

## Checks on the results

- **Second model on VCA checks** (Fable 5.1, 14 claims, same passages): same status for 12 of 14 (86%). Grounded
  or not: κ 0.59. Same grade per passage: 93%. Fable was a little more generous: it graded one claim partial and
  one supported where Opus found nothing.
- **Second model on extracted claims** (Fable 5.1, 34 claims): all 34 judged stated by their passage. 11 of 34 were
  noted as having a loosely fitting SDG target (for example generic economic benefits coded 8.1 rather than 8.5,
  emissions coded 13.2).
- **Recall check by hand** (10 VCA claims with no graded passage; full-text search of their cited documents):
  - 7 have nothing anywhere in the cited documents;
  - 2 have partial support that retrieval missed (different wording: "repurposing" rather than "upgrading");
  - 1 has a weak contradiction.
  - All four 3.9 claims in the sample cite a clean-cooking paper with no hydrogen content and the IEA landing page.
- **Concentration:** 158 of 346 claims come from one paper (Mneimneh et al. 2023), which maps hydrogen to the SDGs in
  long tables. Effects are counted by documents, not claims. Target-presence agreement is the same without that
  paper (κ 0.51).
- **Scope slips:** a few extracted claims concern fossil hydrogen or natural-gas-based fertiliser rather than green
  hydrogen (for example 2.c fertiliser prices, 13.2 emissions of today's hydrogen). The extraction prompt does not
  yet record the hydrogen type.

## Cost

These are the subagent token totals reported for each worker run. They are an indication, not a bill.

| Step | Tasks | Tokens |
| --- | ---: | ---: |
| Calibration (75 pairwise checks, 40 extractions) | 115 | 0.22M |
| Set-wise VCA checks, 12 batches | 178 | 1.35M |
| Extraction, 8 batches | 319 | 1.03M |
| Fable audits | 48 | 0.21M |
| Recall check by hand | 10 claims | 0.16M |
| **Total after the split** |  | **about 3.0M** |

The run was approved at about 2.6M tokens. The overrun is the second-model audits and the recall check, which were
added to test the main result.

## Files

- `enlens.sqlite`: the workspace database. It holds the full text of the source documents, so share it only where
  the documents' licences allow.
- `tasks/`, `results/`: every batch sent to a worker and every answer, including the calibration batches
  (`results/calibration/`).
- `report/`: `report.html` plus CSVs (`claims.csv`, `effects.csv`, `interactions.csv`, `vca_claims.csv`,
  `vca_consistency.csv`, `label_recovery_*.csv`) and `metrics.json`.
- `recall_check.json`: the hand search for the 10 claims above.
