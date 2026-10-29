---
name: enlens-run
description: Work through an ENLENS project's task queue (labels, concept links, theme names, references, search words, checks, and the SDG pack's extractions, splits, VCA checks and audits) with the ENLENS helper agents, each on the model ENLENS names for that kind of task. Use when the user types /enlens-run with a project name.
argument-hint: "<project> [kind] [--parallel N]"
disable-model-invocation: true
allowed-tools: {{TOOL_PREFIX}}queue_status Agent
---

# Run an ENLENS project's queue

ENLENS (on this computer) has prepared tasks for you in a queue. Your job is only to hand them to the ENLENS helper
agents and report progress. ENLENS keeps the documents, checks every quote and stores the answers; the researcher
follows the progress in the ENLENS app.

Arguments: `$ARGUMENTS`

- The first argument is the project's name (in quotes when it has spaces). If there is none, call `queue_status`
  without a project to list the projects that have work waiting, and ask which one.
- An optional second argument is one kind of task (label, link, theme, expand, decompose, resolve, check, reread,
  second, or the SDG pack's split, extract, verify, verify_set): then work only on that kind.
- `--parallel N` sets how many helpers work at the same time (default 2). More is faster but uses the plan's limit
  faster.

## Steps

1. Call `queue_status` with the project. It lists `groups`: each has a `kind`, a `model`, a `helper` and how many
   tasks wait. If it says the project is local only, tell the user and stop. If nothing waits, say so and stop.
2. Start helpers, at most N at the same time (several Agent calls in one message), in the order the groups are
   listed. For each group start the subagent named `enlens-run:<helper>` (for example `enlens-run:enlens-labeller`).
   Pass the `model` parameter with the group's model whenever it differs from that helper's own model
   (labeller and linker: haiku; namer, reader and extractor: sonnet; checker and auditor: opus). Give it this prompt,
   filled in:

   > Project: <project>. Kind: <kind>. Model: <model>. Helper: <helper>. Take batches with
   > next_tasks(project="<project>", kind="<kind>", model="<model>", helper="<helper>",
   > taken_by="<helper> in Claude Code") and answer them as your instructions say,
   > until next_tasks returns no claim or you have finished 5 batches. Then report how many tasks you stored and how
   > many still had problems.

   A large group can have two helpers at once; the queue never gives the same task to both.
3. When helpers report back, call `queue_status` again and start helpers for what still waits, until nothing waits
   (or only held kinds wait).
4. Finish with a short report: per kind, what was answered and what is left, and that the results are in the ENLENS
   app. Do not show passages or answers.

## Rules

- Never read, summarise or answer the tasks yourself, and never call next_tasks or submit_answers yourself: the
  helpers do that, each with its own model.
- If you hit a usage limit, or the user stops you, just stop. A batch that was handed out and not answered returns to
  the queue after 30 minutes; typing /enlens-run again later continues where it stopped. Nothing is lost.
- Some answers come back for a second reading by a stronger model: they show up as a new group with that model.
  Treat them like any other group.
