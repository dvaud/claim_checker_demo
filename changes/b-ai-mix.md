### New

- **How much thought, not how fast.** Beside every *Start Claude Code*, *Energy efficient · Balanced · Intelligence*
  replaces *Slower · Normal · Faster*: it says which Claude models answer each kind of task, and how hard they think.
  Balanced is the recommended table; Energy efficient starts each kind one model lower (judging excerpts never below
  Sonnet), Intelligence one higher, with low or high effort asked of the helpers. The choice is kept, and is the same
  one as in *Settings → AI*. How many helpers work at once is now chosen only in *Settings → AI* (*Helpers at once*).
  *Let the auditor use Fable* stays its own switch. Can change results, as any change of model can: each answer
  records its model.
- **The mix of local and Claude.** With Claude Code and a local model both set, *Settings → AI → The mix of local and
  Claude* shares the work: *Mostly local* (the local model answers every kind of task but second opinions),
  *Balanced* (labels, concept links, search words, theme names and references on the local model; Claude judges
  excerpts) or *Best quality* (Claude for everything, as before: the default). The local model answers first, on this
  computer; an answer it is unsure of, that fails the quote check, or that judges an excerpt as contradicting goes
  up to Claude, only for documents Claude may read, and the local answer counts meanwhile. Claude Code's helpers leave
  the local model's share alone while it answers (the queue lists it *for your local model*); when the chosen local
  model cannot be used (it is not installed, or its server is off), Claude Code answers instead. Can change results.
- **At your plan's usage limit.** When Claude Code stops at your plan's usage limit, the queue page says so (and when
  it resets, if Claude Code said), and *Settings → AI → At your plan's usage limit* chooses what happens: wait and
  continue later (the default), or let the local model answer what waits, where it may. Can change results, when the
  local model answers.

### For developers

- `routing.THOUGHTS`, `Router.thought`, `Router.effort(kind)`; `routing.MIXES`, `mix_kinds(settings)`,
  `judging_changes`; `tasks.mix_local`, `answer_locally_first`, `answer_mix_waiting`; `taskqueue.limit_reached`,
  `status()["for_local"]`, `["thought"]`, `["effort"]`, each kind's `effort`; settings `claude_thought`, `ai_mix`,
  `at_limit`; `tasks.lent_to_local`, `to_claude` (the local model holds a task it answers: `claimed_by` `local-…`); `POST …/queue/run` with Claude Code answers the mix's share here (`{"local": "all"}`: everything it
  may). Tests: `tests/test_ai_mix.py`.

### Not yet done

- The mix lends work from Claude Code only. With the Claude API as the main route, one route still answers every
  task (and the local model reads only documents marked *Only a local AI*).
- An unsure answer of the local model for a document marked *Only a local AI* is not passed to a larger local model
  or to you; it counts, as before.
- The Claude Code plugin's `/enlens-run` does not yet pass the effort the queue names to its helpers (the models it
  does).
