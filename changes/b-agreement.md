### New

- **See whether your local model is good enough for a kind of task.** *Settings → AI → Agreement between routes*
  has your local model and Claude answer the same sample of your own tasks of one kind (checks, second readings,
  labels or links), and shows how often they decide the same, with Cohen's kappa and a plain sentence: from 0.8 good
  enough, from 0.6 fair, below that poor. Before it starts, the box says how many tasks are asked of each route (an
  answer a task already has is reused, so only what is missing is asked), and how many are left out because Claude may
  not read their documents. It runs only when you press the button, as it uses your plan (or API credit). Nothing is
  stored in the project's results; what is sent to Claude is noted in the list of what left your computer.
  Cannot change results.

### For developers

- `benchmark.agreement`, `agreement_plan`, `agreement_kinds`, `kappa`; `GET …/agreement/plan` and
  `POST …/agreement`. Tests: `tests/test_agreement_between_routes.py`.

### Not yet done

- Themes, search words, hypothesis splits and term resolutions have no decision to compare, so they are left out.
- Only the sample's agreement is shown; it is not kept between visits.
