[Manual](../MANUAL.md) › Which model does what

# Which model does what, and what is recorded

> **In short**
> - Each kind of AI task goes to the model that suits it: many quick labels on a small model, judging on a larger one.
> - On Claude Code, the recommended models follow your Claude plan. A model you choose yourself always comes first.
> - Every answer records how it was made, and every Excel download ends with *How these results were made*.

## The model of each kind of task

| Task | Claude Code and the Claude API | Steps up to | A local model |
| --- | --- | --- | --- |
| Codebook labels, concept links | Haiku | Sonnet | the small model, if chosen |
| Search words, splitting a hypothesis, theme names, references | Sonnet | Opus | the main model |
| Judging excerpts, reading one again | Sonnet (high effort) | the auditor | the main model |
| Second opinion | the auditor (Opus, or Fable if switched on) | | the second model |

These are the models for a **Pro** plan on Claude Code; other plans follow the next table. A model chosen in
*Settings → Technical → AI model per task* comes first. A task **steps up** once: when its answer's certainty is
under 0.6, after two rejected answers, or when you press *Ask a stronger model*. The defaults are starting points
until runs on the pilot set them ([MODEL_CHOICE.md](../MODEL_CHOICE.md); `enlens acceptance queue|score`).

### Models that suit your Claude plan

On Claude Code, ENLENS finds your plan by itself in the background (from `claude auth status`: when the app starts,
when it looks at the queue and before a run), and work that waits follows a new plan at once.

| Plan | Recommended models |
| --- | --- |
| Free | No Opus or Fable. Haiku for most tasks (search words, splitting a hypothesis, theme names, references, labels, links), stepping up to Sonnet when unsure; judging excerpts, second opinions and the SDG pack's reference claims on Sonnet. |
| Pro, or a plan not known yet | Sonnet for most tasks, Haiku for the many labels and links, Opus for second opinions and the hard cases (and the SDG pack's reference claims and checks). |
| Max, Team, Enterprise | Opus for most tasks, checks included. Haiku and Sonnet only where there are many tasks at a time and speed matters: labels and links (Haiku), references and the SDG pack's extraction (Sonnet, stepping up to Opus). A check on Opus has no stronger model unless *Let the auditor use Fable* is on, and the result page says so. |

Should Claude Code name the plan wrongly, or not at all (signed in with an API key), set it under *Settings →
Technical → AI model per task → The recommendations follow*. The Claude API and local models do not follow the plan.
Claude Code itself may need a paid plan.

**Fable.** The auditor (second opinions, and checks read again by a stronger model) runs on Opus (on a Free plan,
Sonnet). *Let the auditor use Fable* (*Settings → AI*) switches it to Fable. In Claude Code, Fable can be billed from
usage credits instead of your plan; its model picker then says *Requires usage credits*.

**Cost.** With the Claude API, one part of a hypothesis is two calls of a few thousand tokens. With Claude Code it
counts against your plan's limits; with a local model it costs only time.

## What every answer records

| Recorded | Notes |
| --- | --- |
| The model and its exact version (digest) | Claude Code gives no digest. |
| The prompt version | Changes when a prompt changes, so old and new answers stay apart. |
| The seed (42 by default) and temperature 0 | Claude Code takes no seed, so its answers are not repeatable the way a seeded local model's are. |
| The route (Claude Code, the Claude API, a local server) and the helper | With Claude Code, also the model set for that helper and when its batch was claimed and answered. |
| Whether the answer came from the stronger model | |
| The ENLENS version that made it | Every answer, codebook label and set of themes; each check records the version that started it. |
| The reader that read each document | See [How documents are read](reading.md). |

*How these results were made* (at the end of every Excel download, and in the app) lists them per kind of task. The
acceptance runs (`enlens acceptance queue … --again`) measure how much two readings by Claude Code differ.

## Results across versions

Researchers compare results across versions, so ENLENS never redoes anything by itself:

- When a project holds results an earlier version made, the *Overview* says so in one line under its cards. Those
  results stay as they were made.
- A new reader reads only documents added after the update. The documents you have keep their text, and every quote
  and judgement in them stays where it is, until you move one to the new reader
  ([How documents are read](reading.md#read-with-the-new-reader)).
- A change that can give other answers for the same documents is listed in the changelog under *Changes that can
  alter your results*, and announced one minor release ahead.

---

Next: [Settings →](settings.md)
