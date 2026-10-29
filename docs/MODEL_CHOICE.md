# Which model each task needs (G6)

This is the report the 0.8 roadmap asks for: for every kind of task, which model is good enough and how long it takes,
measured on the pilot, and the default that follows. **It is not filled in yet.** The runs need the sample sheets
filled in by a person once, pass marks the team sets before any run is scored, and real Claude Code sessions. Until
then the defaults below are the roadmap's starting points.

## How the runs are made

```bash
enlens --ws pilot acceptance samples                      # once: acceptance/*.csv for a person to fill in
# the team writes acceptance/pass_marks.json, e.g. {"label": 0.6, "link": 0.8, "theme": 0.8, "resolve": 0.8, "check": 0.8}
enlens --ws pilot acceptance queue --kind label --model haiku     # a copy of the pilot with label tasks for Haiku
/enlens-run "pilot eval label haiku"                                # in Claude Code: answers them
enlens --ws pilot acceptance queue --kind label --model local:qwen3:8b
enlens --ws "<the copy's folder>" queue run --backend ollama        # the local model answers its copy
enlens --ws pilot acceptance queue --kind label --model haiku --again   # the same tasks again: repeatability
enlens --ws pilot acceptance score                                  # writes acceptance/MODEL_CHOICE.md
enlens --ws pilot acceptance score --apply                          # the cheapest passing model becomes the default
```

Each run works on its own copy of the pilot, so the models' answers never mix with each other or with the pilot's.
Every run also records seconds per task, which the queue's estimates use.

| Task kind | Sample (filled once by a person) | Measure | Models compared |
| --- | --- | --- | --- |
| label | f2_labels.csv: 200 passages with their codes | kappa on "code present"; recall of the keyword pass | Haiku, Sonnet, Opus, the local model |
| link | f3_pairs.csv: 50 term pairs, same or not | share of pairs judged as the person did | Haiku, Sonnet |
| theme | g6_theme_names_<model>.csv, written after each run: fitting name or not | share of names fitting | Sonnet, Opus |
| resolve | f5_pronouns.csv: quotes opening with "it" or "they", the right referent | share where the chain names it | Sonnet, Opus |
| check | the pilot's checked VCA claims (reference answers); g6_checks.csv: a person's status | agreement with the reference status and per excerpt; with the person | Sonnet, Opus, the local model |
| all kinds | the same tasks answered twice (`--again`) | share of identical decisions | each model above |

A kind where no affordable model passes keeps a person in the loop: its answers stay marked provisional.

## Results

Not measured yet. `enlens acceptance score` writes the tables here (one per kind: model, tasks answered, score,
repeatability, seconds per task, pass mark, passes) with the chosen default and why.

## Defaults until then

| Task kind | Claude default | Steps up to | Local default |
| --- | --- | --- | --- |
| label | Haiku | Sonnet | the small model |
| link | Haiku | Sonnet | the small model |
| expand, decompose | Sonnet | Opus | the main model |
| theme | Sonnet | Opus | the main model |
| resolve | Sonnet | Opus | the main model |
| check, reread | Opus | the auditor (Opus, or Fable if switched on) | the main model |
| second | the auditor | none | the second model |
| SDG pack: extract | Sonnet | Opus | the main model |
| SDG pack: split | Opus | the auditor | the main model |
| SDG pack: verify, verify_set | Opus | the auditor | the main model |
| SDG pack: audits (audit-vca, verify-claims) | the auditor, or the model given | none | the second model |

### Why these defaults for the SDG pack (0.8.1)

The SDG pack's tasks reach Claude Code only when they are prepared for the queue (`enlens prepare split|extract|
verify-vca|verify-claims|audit-vca`). Its defaults follow the rule of the others, the cheapest model likely to be good
enough, with what the pilot used as the anchor (split on Fable 5.1, extract and the VCA checks on Opus 5.5, audits
on Fable 5.1):

- **extract: Sonnet, stepping up to Opus.** It is the bulk of the pack (319 tasks on the pilot with
  `--per-target 6`, thousands with every screened passage) and the batch's system prompt already carries the 169
  targets. Every claim has a confidence, so a claim Sonnet is unsure of (under 0.6) sends the passage to Opus; claims
  under `accept_confidence` (0.8) wait for a person in any case, and every quote is checked. Haiku was not chosen:
  coding claims against 169 targets with directions and interactions is the hardest coding task ENLENS has.
- **split: Opus, stepping up to the auditor.** Few tasks (61 on the pilot), but its claims become the reference that
  every VCA check and every acceptance run is measured against, and the format has no confidence to step up on.
  This is the one kind where a cheaper model saves little and a wrong answer costs the most.
- **verify, verify_set: Opus, stepping up to the auditor.** They judge excerpts, as `check` does, and the pilot's
  answers to them are the reference of the `check` acceptance run.
- **audits: the auditor, never stepping up.** An audit is a second model's reading; with *Let the auditor use
  Fable* off the auditor is Opus, the same model as the first reading, so give `--model fable` (or switch Fable on)
  for a real second model, as the pilot did.

The acceptance runs do not cover the SDG pack's kinds yet. Until they do, the *Model test* in Settings (which now
works with Claude Code) or `enlens benchmark` (local models, the Claude API) compares a model with the pilot's
answers on extract and verify_set.
