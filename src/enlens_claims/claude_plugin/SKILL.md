---
name: enlens-run
description: Work through an ENLENS project's task queue (labels, concept links, theme names, codes from a theory document, code definitions from examples, references, search words, checks, and the SDG pack's extractions, splits, VCA checks and audits) with the ENLENS helper agents, each on the model ENLENS names for that kind of task. Use when the user types /enlens-run with a project name.
argument-hint: "<project> [kind] [--parallel N] [--helpers checker=2,labeller=1]"
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
- An optional second argument is one kind of task (label, link, theme, theory_codes, code_definition, expand,
  decompose, resolve, check, reread, second, or the SDG pack's split, extract, verify, verify_set): then work only on that kind.
- `--parallel N` sets how many helpers work at the same time (1 to 8; without it, the speed chosen in the ENLENS
  app: normally 2). More is faster but uses the plan's limit faster.
- `--helpers checker=2,labeller=1` names the helpers for this run and how many of each may work at the same time;
  the helpers not named do nothing in this run (their work keeps waiting).

## Steps

1. Call `queue_status` with the project, and with `kind`, `parallel` and `helpers` exactly as the arguments give them
   (leave out what the arguments do not give). It lists `groups`: each has a `kind`, a `model`, a `helper`, how many
   tasks wait, and `start`: how many helpers to start for that group now. ENLENS has already shared the helpers out
   over the groups; follow `start`, do not work it out yourself. If it says the project is local only, tell the user
   and stop. If no group has a `start` of 1 or more, say that nothing waits for this run and stop.
2. Start, in one message (several Agent calls), `start` helpers for each group, in the order the groups are listed.
   For each group start the subagent named `enlens-run:<helper>` (for example `enlens-run:enlens-labeller`).
   Pass the `model` parameter with the group's model whenever it differs from that helper's own model
   (labeller and linker: haiku; namer, reader, extractor and checker: sonnet; auditor: opus). Give each of them this
   prompt, filled in:

   > Project: <project>. Kind: <kind>. Model: <model>. Helper: <helper>. Take batches with
   > next_tasks(project="<project>", kind="<kind>", model="<model>", helper="<helper>",
   > taken_by="<helper> in Claude Code") and answer them as your instructions say,
   > until next_tasks returns no claim or you have finished 5 batches. Then report how many tasks you stored and how
   > many still had problems.

   A group can have several helpers at once; the queue never gives the same task to two of them.
3. When every helper you started has reported back (`start` counts on none of yours still working, so never ask
   again while one is), call `queue_status` again (with the same `kind`, `parallel` and `helpers`) and start what
   `start` says, until no group has a `start` of 1 or more.
4. Finish with a short report: per kind, what was answered and what is left (and, with `--helpers`, what waits for
   the helpers not named: `not_this_run`), and that the results are in the ENLENS app. Do not show passages or
   answers.

## Rules

- Never read, summarise or answer the tasks yourself, and never call next_tasks or submit_answers yourself: the
  helpers do that, each with its own model.
- If you hit a usage limit, or the user stops you, just stop. A batch that was handed out and not answered returns to
  the queue after 30 minutes; typing /enlens-run again later continues where it stopped. Nothing is lost.
- Some answers come back for a second reading by a stronger model: they show up as a new group with that model.
  Treat them like any other group.
