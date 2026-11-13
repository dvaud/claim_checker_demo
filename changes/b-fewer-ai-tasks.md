### Changes that can alter your results

- **The same question is not asked twice.** An AI answer that passed the checks is kept by the question asked: the
  kind of task, its instructions, the model and the text it read (not the task's name). When a task asks the same
  question again, of the same model (a check run again on the same excerpts, a document read again by a new reader,
  the same passage in two documents), it is answered from the kept answer, after the quote check against its own
  text; one that does not fit is not used and the model is asked. Readings asked again on purpose (*Read again*,
  *Ask a stronger model*, second opinions) and model tests are always asked fresh. Each such answer says so in *How
  these results were made* (its route ends in *(kept answer)*). Faster, cheaper and more private; can change results,
  as a kept answer stands where the model, asked again, might have answered otherwise.
- **A small codebook once per batch.** When Claude Code takes a batch of passages to label whose candidate codes are
  40 or fewer in all, the codes' descriptions come once with the batch, and each passage names only its codes. Fewer
  tokens of your plan; can change results, as the model reads the same codes laid out differently.

### For developers

- Table `ai_cache` (key = SHA-256 of the kind, prompt version, model, system and user prompt); `tasks.cache_key`,
  `cached_answer`, `answer_from_cache`, `avoided(ws)` (tasks answered from kept answers, per kind);
  `ingest_result(..., cached=True)`; `prompts.shared_codebook`, `user_prompt(..., codes_once=True)`; a batch of
  `next_tasks` says `codebook_once`. Tests: `tests/test_fewer_ai_tasks.py`.

### Not yet done

- `enlens measure` and the validation report do not show the tasks avoided yet (`tasks.avoided` is ready).
- Passages are not screened further on this computer before the AI reads them (H4's first half): the keyword and
  meaning passes already choose what a label or a check reads.
