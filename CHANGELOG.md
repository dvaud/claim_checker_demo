# Changelog

## 0.9.0 (October 2026): subscription first, exploring first

0.9 changes no analysis: every answer still goes through the quote check, a person can overrule it, and every result
records how it was made. It changes what a researcher meets first: the AI is Claude on their own plan, set up and
started from the app, and the app opens on exploring the documents, with checking hypotheses second.

**Subscription first.**
- A new installation answers with **Claude Code on the researcher's own Claude plan** (`backend: "claude_code"`,
  `allow_claude_code: true` by default). Nothing is sent before the researcher starts Claude Code (a button or
  `/enlens-run`); then only the passages inside the tasks it takes go to Anthropic. An installation that already
  chose a model keeps it when it is updated (its settings file names it). With `--local-only` the default stays the
  local model (`auto`) and Claude Code cannot be chosen.
- **Set up Claude Code** (first screen, *Settings → AI*): a checklist (Claude Code on this computer, signed in with
  your plan, the ENLENS plugin added) and one button that prepares the plugin and adds it to Claude Code itself, by
  running the two commands a person used to type (`claude plugin marketplace add …`, `claude plugin install
  enlens-run@enlens`; both tested idempotent with Claude Code 2.1.312). What only a person can do (install Claude
  Code, sign in once) is said plainly; *Set it up from a terminal instead* keeps the two lines. `enlens claude-setup`
  does the same from a terminal (`--print-only`: only print them). ENLENS finds `claude` on the PATH or where its
  installers put it; `ENLENS_CLAUDE` names it.
- **Start Claude Code.** Wherever AI work waits (a check, labels, theme names…) and in the sidebar's queue panel,
  *Start Claude Code* starts it in the background for that project (`claude -p "/enlens-run:enlens-run <project>"`,
  allowed only the four ENLENS queue tools and its helpers, run in the ENLENS folder). The page says *Claude Code is
  working on it*, with *Stop*; it stops by itself when nothing waits; *Stop* gives the batches it had taken back to
  the queue at once instead of after 30 minutes; a run that ends with a problem shows the end of its report. The
  first start adds the plugin if that was not done yet. Typing `/enlens-run <project>` in Claude Code still works
  and is shown one line below. ENLENS still never sees the Claude login. **Not yet done:** a run in a signed-in
  Claude Code from the button; the command line was checked against Claude Code 2.1.312 (the skill resolves as
  `enlens-run:enlens-run` with its seven helpers, with the model API blocked), and the whole path with a stand-in.
- *Save and test* on Claude Code says whether it is set up (and signed in) instead of always "working".
- The sidebar's privacy line on Claude Code is the normal case, not a warning: *Claude, on your plan · Only the
  passages of AI tasks leave this computer*.

**Exploring first, clear separations.**
- New **Overview** page, the start page of a project (and of the app): *Explore the documents* first (Search,
  Profile, Concepts, Themes, Read one document), *Check hypotheses* second (Check a hypothesis, Check several,
  Results). Each feature has one line on what it does, one on what it is for, whether it uses the AI, and what is
  already made in the project (a profile, a glossary, a set of themes, results). It also says which AI is in use
  and what is left to set up, and holds *Quick look at one document* (moved from the check page) and *Add
  documents*. `GET /api/projects/<p>/overview` gives the counts.
- The sidebar is ordered the same way: Overview, Documents, **Explore the documents**, **Check hypotheses**,
  Settings. Each feature carries an **AI mark**: filled *AI* (needs the AI: checks), dashed *AI* (works without it;
  the AI can add to it: Profile, Concepts, Themes), no mark (never uses the AI: Search, Documents, Results), with a
  legend under the list and a tooltip saying what the feature does.
- Above every feature's title: the part of the app it belongs to and its AI use (*Explore the documents · No AI
  needed*). One description of every feature (`static/features.js`) feeds the sidebar, the Overview and the titles.
- The welcome screen leads with exploring ("Explore your documents, and check what they say"); its first step is
  the AI (Claude Code, with *No Claude plan? Other options*: a local model, or no AI for now).

**Less clutter, fewer menus inside menus.**
- **Settings as five flat tabs**: *AI*, *Checking*, *Exploring*, *Documents*, *Technical*. In 0.8 the choice of the
  AI was folded inside *Advanced (for IT staff)* together with seven other sections; now it is the first tab, as
  four large choices (Claude Code, recommended; a model on this computer, with the local server as one choice inside
  it; no AI; the Claude API for a team key). Old links to a section open its tab. On the Claude Code route the
  Technical tab leaves out what only a local model uses (the second model, the context length).
- The sidebar shows the jobs box only when there are jobs, and the queue panel only when work waits or Claude Code
  is working; *Theme* and *Quit ENLENS* share a row.
- Profile: the explanation of what a passage is moved into *Technical details*.

**Usability fixes found on the way.**
- The check page's "Set up the AI model" link went to the first-run page even when a project existed; it opens
  *Settings → AI*.
- Switching projects from a theme or concept page returned to that page of the other project, where it does not
  exist; it opens the Overview (as from a result or a document).
- With Claude Code, the AI-labelling and references notes said the passages were sent "to the Claude API"; they now
  say Claude Code reads them on your plan.
- Settings links in Search, Documents and the check options pointed at *Settings → Advanced*; they name the tab.

Tests: 9 new (`tests/test_090_subscription_first.py`): the defaults (and local only), set-up with Claude Code missing
and with a stand-in `claude` (`tests/fake_claude_cli.py`), the run command's allowed tools, *Start Claude Code*
answering a project's queue and *Stop* returning its batches, the overview counts, the model test, and the order and
AI marks of the sidebar. A test never touches a real Claude Code (`conftest.py` points `ENLENS_CLAUDE` nowhere).
`tools/dev_server.py --claude-cli` runs the app with the stand-in.

## 0.8.2 (October 2026): readable heat grids, updating in place

- **The heat grids stay readable on hover.** On *Profile → Documents by goal/target* and on *Themes* (documents and
  codes by theme), the row under the mouse lost its colours: the row hover (`.row-link:hover .map-cell`) outranked
  the heat levels, so the darkest cells showed their white (light theme) or near-black (dark theme) numbers on the
  pale hover background, about 1.1:1, and could not be read. The levels now outrank the hover (`.map-table
  td.pf-cell.pf-lN`, the same for `th-`); the hovered row is still marked by its document cell and its empty cells,
  and a cell under the mouse by its outline.
- **The darkest cell in the light theme is darker** (`--heat-4`, a new token): its white numbers went from 3.3:1 to
  4.7:1 against the background. The dark theme is unchanged (4.7:1).
- **`enlens update`.** ENLENS installed once from a git copy (clone, venv, `pip install -e .`) now updates itself:
  `enlens update` fetches the new version from GitHub into the same folder and moves forward only; it reinstalls
  into the same Python only when `pyproject.toml` changed (keeping the extras already installed), refreshes the
  Claude Code plugin if one was set up, and says to restart the app if it is running. It stops, changing nothing,
  if files of the copy were edited by hand. `enlens update --check` only says whether a new version is waiting.
  The data folder is never touched. See the README, *Updating*.
- Tests: 7 new (`tests/test_082_update_and_grid.py`): the heat levels outrank every row-hover rule, the darkest cell
  has its token in all three theme blocks, and `enlens update` on real git copies (up to date, code only, new
  requirements, local changes, not a git copy).

## 0.8.1 (October 2026): Claude Code for every AI task

0.8 sent every AI button of the app to Claude Code, but three kinds of work still could not use it. They can now.

- **The SDG pack through the queue.** `enlens prepare split|extract|verify-vca|verify-claims|audit-vca` makes the
  pack's tasks (the options of `make-tasks`) and puts them in the queue; `/enlens-run` answers them. The pack's
  tasks still never enter the queue on their own: `make-tasks`, `run` and the file queue are unchanged, and the
  test that the pilot makes no new tasks still holds.
  - Routing (`routing.py`) knows the pack's kinds: extract on Sonnet (stepping up to Opus), split on Opus, verify and
    verify_set on Opus (both stepping up to the auditor). The reasons are in `docs/MODEL_CHOICE.md`. Settings'
    *AI model per task* has a row for each of them.
  - Audits (audit-vca, verify-claims) get the role "audit" (new column `tasks.role`). They are routed like a second
    opinion, to the auditor (or the `--model` given), and they keep that model: an audit never steps up.
  - A seventh helper, `enlens-extractor` (Sonnet), answers extract and split. The checker also answers verify and
    verify_set, and the auditor the audits.
  - The queue: batch sizes for the pack's kinds, which are handed out after the app's own work. A batch's system
    prompt now counts against the connector's 25,000-token cap (extract's holds the 169 targets, about 11,000
    tokens). The other kinds' batches are unchanged.
  - Groups are told apart by helper as well as kind and model. `next_tasks` takes `helper`, and `/enlens-run`
    passes it, so each answer records the helper that gave it.
- **Model tests with Claude Code.** *Compare a sample* of labels and the *Model test* no longer refuse Claude Code.
  Their tasks wait in the queue of a temporary copy of the project, which is removed afterwards
  (`taskqueue.answer_on_copy`), so nothing is stored. The model test answers each kind on its routed model, or the
  alias given.
- **Repeatable answers?** said nothing useful for Claude Code: it called the model directly and failed. It now says
  that Claude Code takes no seed.
- Tests: 8 new (`tests/test_081_claude_code_everywhere.py`), among them a check that every task kind has a model, a
  helper and a batch size on Claude Code. The fake Claude Code passes `helper` like the skill does.

## 0.8.0 (October 2026): Claude Code on your own plan, a model per task

0.8 lets a researcher use Claude Code, signed in with their own Claude plan, as the AI behind every ENLENS task, and
adds the tools to prove on the pilot which model each task needs (G1 to G7 of the 0.8 roadmap). It adds no new
exploring features. The 0.7 rules hold: every answer goes through the quote check, a person can overrule it, and
every result records how it was made. Four rules are added: the researcher runs Claude Code and ENLENS never does;
one queue feeds every AI; each kind of task gets the cheapest model that is good enough; checking itself does not
change.

**The task queue (G1).** *Settings → AI model service → Claude Code (your subscription)*, behind a confirmation
(the passages inside the tasks Claude Code takes are sent to Anthropic). Every AI button then prepares tasks
instead of calling a model: profile labels, concept links, theme names, references, checks, reading an excerpt
again, second opinions and other wordings of a concept. The page says what waits, for example *Waiting for Claude
Code: 120 passages to label · about 25 minutes*, with the command to type and a copy button. The progress moves as
answers arrive, and the result appears as before.
- Tasks in the queue are marked (`tasks.queued`). Tasks of 0.7 and of the SDG pack never are, so `/enlens-run` never
  answers the pack's work.
- A batch handed out is a claim (table `task_claims`: who took it, when, model, helper). Two sessions never get the
  same task, and a claim not answered within 30 minutes lapses: its tasks are handed out again.
- **A check by queue.** The search and the choice of excerpts run in ENLENS at once; only the model's steps wait
  (search words, the split into parts, the judging). Each step is taken when the answer before it arrives, in the
  app or in the connector, so a check finishes even when the app was closed meanwhile. Until then it is listed as
  *Waiting for Claude Code*. Stop withdraws it, as a stopped check leaves nothing behind.
- **The queue panel** (sidebar, under the jobs): per kind what waits, is being answered and is done; the model,
  helper and estimate; *Do first*, *Hold* / *Go on*, *Remove*; the command to type; and the privacy line. When the
  route is not Claude Code, *Answer them here instead* answers the queue with the AI model of Settings.
- The app's waiting jobs do not hold the model's turn, and the app reads the queue every few seconds.
- Command line: `enlens prepare label|link|theme|resolve|check`, and `enlens queue status|run|first|hold|go|withdraw`.
  `queue run --backend anthropic` answers the queue unattended (the shared installation).

**The Claude Code plugin (G2).** `enlens claude-setup` writes the plugin into the ENLENS data folder
(`claude-plugin/`, a marketplace of one plugin), checks that the connector starts and offers the queue tools, and
prints the two lines that add it to Claude Code (`claude plugin marketplace add …`, `claude plugin install
enlens-run@enlens`). Settings offers the same as *Prepare the plugin*. ENLENS writes nothing to Claude Code's own
settings, never starts Claude Code and never handles its login.
- `/enlens-run <project> [kind] [--parallel N]`: the orchestrator skill. It hands each group of tasks (kind and
  model) to a helper agent and reports what is done and what is left. It never reads a task itself.
- Six helpers, each limited to the connector's queue tools: `enlens-labeller` and `enlens-linker` (Haiku),
  `enlens-namer` and `enlens-reader` (Sonnet), `enlens-checker` and `enlens-auditor` (Opus). A task routed to
  another model goes to its helper with Claude Code's per-call model choice.
- The connector gains `queue_status`, `next_tasks` (a claim, the versioned system prompt once, each task's prompt,
  at most about 15,000 tokens a batch), `submit_answers` (every answer quote-checked; per task *stored* or
  *problems*) and `release`.
- The plugin's files were checked with Claude Code 2.1.312 (`claude plugin validate`, installed from the data
  folder: one skill, six agents, one connector). **Not yet done:** a run in a signed-in Claude Code, and a check of
  which model each helper actually ran on (G5). The skill is named so that its command is `/enlens-run`; if Claude
  Code shows it with its plugin's prefix (`/enlens-run:enlens-run`), autocomplete offers it on `/enlens-run`.

**Model routing (G3).** New module `routing.py`. Each kind of task has its own model on all three routes:
- Claude Code and the Claude API: labels and links on Haiku (stepping up to Sonnet), search words, splitting,
  theme names and references on Sonnet (to Opus), judging excerpts on Opus (to the auditor), second opinions by
  the auditor. The auditor is Opus, or Fable when *Let the auditor use Fable* is on.
- Local servers: a small model for labels and links (Settings, `local_small_model`) and the main model for the
  rest. With no small model chosen, the main model does everything and nothing steps up, exactly as in 0.7.
- **Stepping up, once.** A task goes to the stronger model when its answer's certainty (the lowest confidence it
  gives) is under 0.6, when two answers in a row were rejected (the third attempt goes to the stronger model), or
  when a person presses *Ask a stronger model* on a round of a check. Both answers are kept (`results.step`); the
  stronger model's counts. A person's own judgements stay. If the stronger model's answer does not pass, the first
  one stays. With local models the second readings come after the run, so each model is loaded once.
- *Settings → Advanced → AI model per task*: the model, what it steps up to and the helper per kind, a choice per
  kind, *Use the recommended models*, and (Claude API and local) *one model for everything, as in 0.7*.
- On the Claude API the second opinion comes from the auditor, so no second local model is needed.

**Time, limits and stopping (G4).** Claims are small (20 labels, 1 check) and lapse after 30 minutes, so a stop
costs at most one batch and the next `/enlens-run` continues. The researcher's own requests come first, then small
jobs, then the bulk. Estimates come from the measured seconds per task of each kind and model; before any are
measured the panel says so. When answers stop arriving the app says *Paused at 340 of 7,868 labels. To go on, type
/enlens-run Pilot in Claude Code.*

**Privacy and records (G5).** Choosing Claude Code shows what leaves the computer once, with a confirmation, and the
queue panel repeats it. `--local-only` hides the option and makes the connector refuse `next_tasks`. Each answer
records its route, helper, model as set for the helper, prompt version, whether it stepped up and when its batch was
claimed (`results.route`, `helper`, `step`, `claimed_at`). *How these results were made* shows them per kind, says
that Claude Code answers are not repeatable by seed, and counts the answers that stepped up.

**Proving it on the pilot (G6).** New module `evaluation.py`. `enlens acceptance queue --kind K --model M [--again]`
makes a copy of the reference workspace with that kind's sample tasks waiting for that model. The copy keeps each
model's answers apart from the others and from the pilot's. Claude models are answered with `/enlens-run "<copy>"`,
a local model with `enlens queue run`. `enlens acceptance score [--apply]` scores every run: labels by kappa against
f2, links against f3, theme names against a sheet written per model, references against f5, and checks against the
pilot's reference answers and a person's g6 sheet. It also measures repeatability (`--again`) and seconds per task.
It writes `acceptance/MODEL_CHOICE.md`, and with `--apply` makes the cheapest passing model the installation's
default. The team sets the pass marks first (`acceptance/pass_marks.json`). **Not measured yet:** the runs need the
filled sheets and real Claude Code sessions; `docs/MODEL_CHOICE.md` holds the empty report and the current
defaults.

**Carried over from 0.7 (G7).**
- *Cross-Doc in the docs*: no document refers to Cross-Doc users. The user tests note that round 8's testers were
  told they had used it, as a premise only.
- *Letter-spaced PDFs*: for the glossary and key terms, pieces such as "Elec tr oly ser" are read as one word
  when the documents write it whole at least as often and one piece is not a word of its own. The text, search and
  quotes keep the text as read. On the pilot the glossary loses its fragments ("Elec tr oly ser", "tr", "er", "ma",
  "pr") and keeps phrases such as "net zero", and the key terms hold no fragments.
- *Undo for concept links*: removing a link (*Not right*, *No, not the same*) has an Undo, as a rejected code has;
  `PUT …/concepts/links` takes `decision: "undo"`.
- *Theme numbers*: themes are numbered 1 to n in the order shown (`number`), with no gaps after a merge. The stable
  `theme_id` stays for links, edits and the FlexiConc export.
- *Word files*: `.docx` is read with the standard library: paragraphs, headings (Title, Heading 1 to 9), tables
  row by row, pages where Word marked them, and the title from the document properties. A Word file reads like its
  PDF (same text, pages and passages in the tests). Uploads, quick looks and folders accept it; *Open the original*
  downloads it.
- Comparing profiles waits for a later release.

**Tests.** 173 automated tests (21 new). The new ones play `/enlens-run` with a fake Claude Code through the
connector, in process and over MCP, with a wrong quote on the first try of each kind. They check every AI button by
queue, two sessions at once, a lapsed claim, a stop at a random point followed by a new session (every task answered
once, no claim left open), routing on the three routes (the fake Claude API and fake Ollama), stepping up once,
*Ask a stronger model*, local only, the plugin's files (and `claude plugin validate` when Claude Code is installed),
the connector starting as Claude Code starts it, the command line, the SDG pack (0 new tasks on the pilot, none in
the queue), an acceptance run scored end to end, and the G7 items. `tools/dev_server.py --claude-code` runs the app
with a fake Claude Code answering, and `--claude-code-paused` with none.

**Not in 0.8 yet** (the roadmap's gates): a run in a real, signed-in Claude Code; the team's confirmation of the terms;
the G6 runs and pass marks; and the test with two or three real researchers.

### Compatibility

- New columns, added when a project is opened: `tasks.queued`, `queued_at`, `claimed_by`, `claimed_at`, `step`,
  `again`, `forced_model`; `results.route`, `helper`, `step`, `claimed_at`; `hypotheses.queue`; `user_claims.stage`.
  New table `task_claims`.
- New settings: `allow_claude_code`, `use_fable`, `task_models`, `local_small_model`, `routing` (on). On the Claude
  API, search words, splitting, labels and the other kinds now use their own model. `anthropic_model` is the model
  for judging excerpts; switch `routing` off for one model everywhere.
- The SDG pack is unchanged: its tasks are never routed and never queued.
- Prompts are unchanged (`check-v4`, `label-v1`, …).

## 0.7.0 (October 2026): explore the documents; Cross-Doc SDG Explorer replaced

0.7 builds the whole design roadmap (F1 to F8, reproducibility and testing) so that ENLENS does what people used the
Cross-Doc SDG Explorer for. Its outcomes are rebuilt with ENLENS's own parts (keyword index, optional embeddings,
model tasks with checked quotes, review screens); SpanBERT, fastcoref, SciCo, PreSumm, FAISS and Integrated Gradients
are not ported. The core stays light (pydantic, pypdf, openpyxl; numpy with `fast`, pdfminer and OCR as extras). The
SDG pack is untouched: on the pilot, `make-tasks` for every SDG kind creates 0 new tasks.

New pages under **Explore the documents**, and what they replace:

- **Search (F1)**, for Cross-Doc's concordance and token strip: any / all / phrase / near (N words), exact words,
  reference lists on request, per-document counts first, sort by document or by the words before or after, clickable
  words (Shift-click: a phrase), *other forms in the documents* (words the stemmer keeps apart, e.g. *commuters*),
  words nearby (window 2–10, by count or by PMI), Excel/CSV, a check started from a line, search by meaning.
  `textutil.token_spans` gives the tokenizer's words with offsets, so search and checks use one rule.
- **Profile (F2)**, for SDG-BERT's labels: a keyword (and meaning) pass on adding documents gives a provisional
  profile in seconds; the AI pass (task `label`, prompt `label-v1`) confirms codes with a quote and a reason, and says
  how many keyword codes it confirmed, did not confirm, and added. Count by target or goal (`sdg_goals`, 17 codes, is
  bundled), grids, a person's labels (agree, change, reject, add; Undo), calibration, a second-model comparison.
- **Concepts (F3)**, for global coreference and SciCo: a glossary by C-value (running heads and page furniture left
  out), Schwartz–Hearst abbreviations, wordings close in meaning, links judged by the AI (task `link`) and by people,
  concept cards (wordings, documents and first place, lines, related concepts), wordings proposed by the AI that a
  person can accept or refuse for good.
- **Themes (F4)**, for clusters and their summaries: deterministic spherical k-means on embeddings or terms,
  c-TF-IDF key terms, names by the AI with checked quotes (task `theme`), rename / merge / move kept as reviews, grids
  by document and by code, Excel. 2 to 60 themes; a small project gets about three passages a theme at least.
- **References (F5)**, for fastcoref/LingMess: chains followed by the AI window by window (task `resolve`); checks
  (prompt `check-v4`) say what a quote's "it" or "they" refers to, and flag quotes that open with a pronoun and do not.
- **Key terms and reasons (F6)**, for keyphrases and token attributions: key terms per document and passage, the words
  that found each excerpt and each keyword label, the AI's reason with every label.
- **Highlighted copies (F7)**, for `pdf_highlight_post.py`: PDF highlight annotations with exact boxes (pdfminer),
  whole lines (pypdf) or OCR, a note for quotes not placed, HTML copies for other documents; per document, per
  answer (zip) and per document column of the evidence map.
- **Quick look and FlexiConc (F8)**: one document in a temporary project (kept or discarded; trash after 7 days), and
  the project as Cross-Doc's FlexiConc SQLite (`documents`, `sentences`, `chains`, `clusters`, `embeddings`), from the
  Projects page or `enlens export-flexiconc`.

**Reproducibility.** Every model request carries a seed (setting `seed`, 42) at temperature 0; every answer records
the model, its digest (Ollama) or file (LM Studio), the prompt version, the seed and the settings; runs warn when any
of these changed since the last run; *Settings → Advanced → Repeatable results* (and `backend-check --repeatable`)
tests whether a server gives the same answer twice; every Excel download ends with *How these results were made*.

**Also new.** Settings *Exploring the documents* (`profile_framework`, `themes_k`); codebooks marked as aims a text
can help or hinder; the CLI commands `search`, `profile`, `terms`, `concept`, `themes`, `resolve`, `annotate`,
`export-flexiconc`, `acceptance`; the connector tools `search_corpus`, `document_profile`, `find_concept`; benchmark
kind `label`; 38 API endpoints (docs/API.md).

**Measured on the pilot** (38 documents, 8,778 body passages; this computer, no model): the passage index 3 s; a
search under 1 s (median 0.35 s over the 20 most frequent terms, and hit counts equal to a case-insensitive regular
expression for all 20); the keyword pass 12 s; the glossary 22 s (6,000 terms, 87 abbreviation links, 83 concepts);
themes by words about 40 s; the FlexiConc export 13 s. The keyword pass puts 62% of the codes of the pilot's
extraction answers among a passage's top 8 candidates (a proxy for the F2 recall measure).

**Not measured yet** (they need people or a real model): the acceptance measures of F2 to F7 (`enlens acceptance
samples` writes the sheets; the team sets the pass marks first), and the quality of the AI passes with a local model;
the tests run against a stand-in model.

**Tests.** 152 automated tests (19 new for 0.7: offsets, concordance against regular expressions, abbreviations,
running heads, k-means determinism, highlight boxes inside the page, the FlexiConc layout read back, retries after a
wrong quote for every new task kind, the new CLI commands and API endpoints). Two simulated first-time users (round
8, see docs/USER_TESTS.md) found the problems fixed before release: listed there.

## 0.6.1 (October 2026): reasoning within a time limit

A reasoning model could take more than 1,800 seconds on a check of a single document. For example, qwen3.5:9b
writes about 20 tokens a second, may reason for longer than its allowance of 4,096 tokens, then loses its answer
to the output cap and is asked again, up to three times, for every step of the check. 0.6.1 bounds that time.

- **Reasoning only when judging** (`think: "judging"`, *Settings → Advanced → Reasoning: Only when judging
  excerpts*). The model reasons when it judges excerpts: the check itself, *Ask the AI to read this again* and the
  second model. It does not reason when it splits a hypothesis or proposes search words. Those calls stay as fast
  as with reasoning off. Ollama's `think` is a per-request option, so switching it per step does not reload the
  model.
- **A reasoning budget** (`think_budget`, default 1,500 tokens; 0 = no limit). When a model is still reasoning at
  the budget, ENLENS stops that request and asks again without reasoning, giving the reasoning so far as notes. The
  model must still quote only from the passages, and every quote is checked as before. At 20 tokens a second, a
  judgement then takes at most about 75 seconds of reasoning, and an answer is never lost to the output cap. The
  budget applies whenever reasoning is on (`judging`, `on`, or the model's default).
- The progress panel says when the budget was used up ("answering from its notes now"). The model's statistics
  record `thinking_tokens` and `budget_reached`.
- The automatic context length makes room for the budget twice: once for reasoning, once as notes. With
  `judging`, 8 excerpts per check and a budget of 1,500 tokens, it is 12,288 tokens; with reasoning off it stays
  8,192.
- Command line: `--think on|off|judging` and `--think-budget N` (default 1500) on every model command, so
  `enlens benchmark … --think judging` compares a model with and without reasoning on the pilot's tasks.

Whether reasoning helps depends on the model. Small models do not always judge better with it, and it can make
copying quotes word for word worse. Run the test with `--think off` and `--think judging` before relying on it.

## 0.6.0 (October 2026): look before checking, a second opinion, and an icon to start it

0.6 builds the fifteen features agreed after 0.5.1 and adds an icon that starts the app without a terminal. Through
all of them the owner's standing requirement holds: the local model gets as much of the computer as possible.
ENLENS loads no model of its own, makes one model call at a time, keeps heavy tools optional, streams files, and
runs OCR at low priority on one thread.

Two simulated first-time users tested it: a labour sociologist with ten goals covering the new features, then,
after the fixes, a public-administration researcher on the parts that had caused trouble.
- "It is obvious what to do": 7/10 and 7/10.
- "It is obvious what is happening and what the result means": 7/10 and 8/10.

0.5.1's last round gave 8/10 and 6/10. Both testers' findings were fixed (see docs/USER_TESTS.md).

### Model choice and memory

- **Default model.** When no model is chosen, or the chosen one is not installed, the app picks one the server
  already holds in memory (Ollama `/api/ps`, LM Studio `/api/v0/models`), so nothing extra is loaded. Failing that,
  it takes the most recently pulled model, then the first in alphabetical order. The command line does the same,
  and *Test the AI model* says when it fell back.
- **Context length `auto`** (the new default). The app uses the smallest of 8,192, 12,288, 16,384 and 32,768 tokens
  that holds the largest task the settings can produce. That is 8,192 for 8 excerpts without reasoning, which
  frees about 1.2 GB of memory for qwen3:8b compared with 16,384. The length stays the same between requests, so
  Ollama never reloads the model. A request that reads more excerpts at once gets a length that fits, and the
  command line's `run` fits the largest pending task. Settings files of 0.5 hold the old default 16,384: they are
  read as `auto`. A number chosen in 0.6 is kept.
- **Unloading.** `OllamaBackend.unload()` frees a model at once (`keep_alive: 0`). LM Studio and other
  OpenAI-compatible servers have no standard way to unload a model, so there it does nothing.

### Documents

- **Paragraphs and headings** are found when a document is added, without changing its stored text (the SDG pack
  reads exactly the same text and passages as before).
  - Text and web pages: paragraphs are blocks between blank lines, numbered as in 0.5.1.
  - PDFs: a new paragraph starts at each page, at a vertical gap or an indent (positions read in the same
    extraction pass), after a short line that ends a sentence, and at a numbered section.
  - Headings: `<h1>`–`<h6>` in web pages, `#` lines in Markdown, and short lines without closing punctuation
    elsewhere.
  - Quotes in PDFs are cited as "page 2, paragraph 3". Excerpts carry `breaks`, so the app shows their paragraphs
    and bold headings ("…2024 Summary. Remote work…" no longer runs together).
  - Documents added earlier have no layout and look as before.
- **Open the original.** `GET …/documents/<id>/file` serves only the file recorded for the document, resolved
  against the project folder when needed, and streamed. A PDF opens at the page. A text file opens with the quote
  highlighted. A web page is served sandboxed (no scripts, no internet, no access to the app) and scrolls to the
  quote in browsers that support text fragments. When the file has moved or changed, the response says so plainly
  and shows the text the app read.
- **Scanned PDFs.** With the extra `ocr` (pypdfium2, pillow) and the program Tesseract, pages with less than 30
  characters of text are read by OCR. Each page is rendered alone at 200 dpi and freed afterwards, and Tesseract
  runs with one thread at low priority. The settings are `ocr` (auto or off) and `ocr_lang`. The Documents list
  says "Scanned: text recognised (OCR)", or "Scanned: no text. Ask IT to install Tesseract to read it."

### Checks

- **Look before checking** (`POST …/prepare`): the parts the AI would split a hypothesis into and the extra
  search words it proposes, to edit before the check. `check_hypothesis(…, parts=, terms=, edited=)` then skips
  those model calls and records what the person changed (`options.prepared`).
- **About another group.** The prompt `check-v3` lets the AI add a `scope_note` per excerpt ("about fully remote
  workers, not hybrid"). Such an excerpt supports a hypothesis at most partly; the app applies that rule when it
  stores the answer. This costs no extra model call. The SDG pack's prompts are unchanged.
- **Read one excerpt again** (`POST …/claims/<id>/reread/<passage>`). The AI grades the excerpt alone, with the
  person's comment as a hint, and says why. Its earlier judgements are kept (`ai_history`), and a person's own
  judgement still counts.
- **The second sorting pass is off by default.** It re-sorts the best 3 × k candidates by how closely they word
  the hypothesis, without a model. It was evaluated on the pilot first, with 178 VCA claims that have readable
  cited sources (`tools/eval_second_pass.py`). It brought slightly fewer excerpts from the cited sources into the
  top k: 147 instead of 154 at k = 8, and 125 instead of 126 at k = 6. Variants with other weights did not do
  better, so it is an Advanced setting (`second_pass`) and off, as the handoff asked ("keep it only if it does not
  get worse").

### Results

- **Evidence map** (`GET …/map`; *Show as a map*). One row per hypothesis and one column per document, with
  symbols as well as colours. It flags answers that rest on one document, and documents that decide answers
  (leaving them out would change those answers). The all-results Excel file gains a *Map* sheet.
- **Calibration** (`GET …/calibration`; in Settings next to the strictness): how often the person agreed with the
  AI at each band of AI certainty. After 20 judgements it suggests the lowest strictness from which they agreed
  at least 80% of the time ("Use 70%"). An excerpt that was read again is compared on the AI's first judgement.
- **Documents added since a check.**
  - The Results list gets a tag "documents added since".
  - The result page says how many documents were added and how many have matching excerpts.
  - *Read them* reads those documents as a further round. The check is not run again, so reviews are kept.
  - *Read the new documents for all N* does this for every result in one job.
- **A second AI model** (setting `second_model`; `POST …/second-opinion`). Another local model grades the
  excerpts already read, with the same prompt. The main model is unloaded first and the second one at the end,
  so two models are never in memory together. Its judgements are stored apart (table `second_opinions`) and never
  change an answer. Cards show "Second AI model: Contradicts (70%), disagrees", and *Next to review* goes to
  disagreements first. The Results list gets "models disagree on N", and Excel gets columns for it.
- **A project as one zip** (`GET …/export.zip`, `POST /api/projects/import`, `enlens export-project` /
  `import-project`). The zip holds a consistent copy of the database (SQLite's backup API), `config.json`, the
  codebooks, `uploads/`, and the original files kept outside the project. It is written to a temporary file and
  streamed. Import unpacks with the zip-slip guard and a size budget, and points the documents at their files.

### Starting without the terminal

- **`enlens-gui --make-launcher`** puts an ENLENS icon on the Desktop:
  - macOS: an app, also in ~/Applications;
  - Windows: a shortcut that runs `pythonw`, also in the Start menu;
  - Linux: a menu entry.

  The icon calls the Python ENLENS was installed in, so another `enlens-gui` earlier on the PATH cannot get in
  the way.
- **Double-clicking the icon** runs `enlens-gui --launcher`. If ENLENS is already running, it opens it again.
  Otherwise it starts the app in the background, writes its output to `logs/enlens.log`, starts the Ollama app
  when the model service is Ollama on this computer and not running, and opens the browser.
- **Quit ENLENS** in the sidebar (`POST /api/quit`) stops the app. It asks first when a check is running, and
  stopped checks clean up before the app exits.
- Tested on Linux, where the icon was built, run and run again. On macOS and Windows only the icon files were
  checked; a trial on those systems is pending.

### Fixes and smaller changes

- A request body that no endpoint read could be taken for the start of the next request on the same connection.
  Unread bodies are now drained.
- From the user tests:
  - a judged card keeps its place on the screen and says where it moved;
  - *Next to review* moves forward through disagreements, excerpts about another group, then those that count;
    *Next disagreement* cycles through the disagreements;
  - a *Table* view lists every excerpt read with the AI's, your and the second model's judgement;
  - the second model is also compared with your own judgement;
  - marking the sentence you mean waits for your judgement instead of recording agreement;
  - a re-read's hint can be saved as your comment, and the app warns that the AI may simply follow it;
  - every card of a split hypothesis names its part.
- A comment saved without a judgement is a comment, not "you agreed with the AI".
  `PUT …/judgements/…` with `{"verdict": null, "note": …}` keeps it. *Go back to the AI's judgement* now keeps
  the comment, as it says.
- `reset_corpus` now also removes paragraph rows, which were left behind before.
- Files are checksummed in chunks; a large PDF is no longer read into memory to compute its checksum.
- The progress of short jobs lists only the steps they make.

### Compatibility

- New columns and tables are added to existing projects when they are first opened (through `MIGRATIONS`):
  - columns `paragraphs.page`, `documents.ocr_pages`, `documents.scanned_pages`, `verifications.scope_note`,
    `verifications.ai_history_json`, `verifications.reread_json` and `hypotheses.docs_checked_at`;
  - tables `headings` and `second_opinions`.
- Task kinds `reread` and `second`, both using the prompt `check-v3`. The `check` prompt is now `check-v3`;
  results record it.
- The SDG pack is byte-identical to 0.5.1: `clean_page`, `tokens_v1`, the sentence regex, its prompts and its
  answer schemas. A fingerprint of these, and of the text, pages and passages of a test corpus, is unchanged.
- The API additions are listed in docs/API.md ("New in 0.6").

## 0.5.1 (October 2026): an app for researchers who don't program

0.5.0 made ENLENS a local hypothesis checker; 0.5.1 makes its app clear to a social scientist who has never
programmed, using it for the first time on a computer someone else set up.

It was tested that way five times by simulated first-time users (sociologists and a public-administration researcher who
had never programmed), each round fixing what they found (the fixes after the fifth test were checked with scripted
browser flows). "It is obvious what to do" stayed at 8/10; "it is obvious what is happening and what the result
means" went from 4/10 to 6/10. Most of the remaining distrust was about the stand-in AI's wrong judgements in the
test setup, which the app let the testers catch and correct.

- Plain language on every working screen ("excerpt", "judgement", "AI certainty", "strictness", "Mixed evidence");
  model names, ids, tokens and CSV/JSON only under *Technical details* and *Settings → Advanced (for IT staff)*.
- One consistent story on a result: the answer, the documents it rests on (named), who says what, and the evidence
  list always agree; an unreviewed answer is shown as *the AI's first reading*; a caution when it rests on a single
  document or on one or two unchecked judgements; for split hypotheses, which part decides the answer.
- Reviewing like a co-coder: *Agree with the AI* / *Judge it differently* (saves at once, with Undo), comments,
  *Mark the sentence you mean*, *Next to review* (judgements that count first), place kept while cards move.
- Strictness has one home (Settings), says honestly that the AI's certainty is its own estimate, applies to all
  results, and reports which answers and counts changed; *Back to normal (60%)*.
- Looking harder says what it found ("Just now: 5 more excerpts read…"), marks new excerpts, shows the words of each
  search, and says when everything that matches has been read. A search with other words reads only excerpts that
  contain them.
- *Check several* starts as soon as hypotheses are pasted and ends with each answer listed, in the order typed.
- The cloud option sits apart, behind a confirmation; `enlens-gui --local-only` (or `ENLENS_LOCAL_ONLY=1`, or a file
  `local_only` in the data folder) removes it for good.
- `tools/dev_server.py --fresh-user` shows the app as a new user finds it, with a demo corpus on remote work.

### New in the results

- **Your own judgements**: agree with the AI's judgement of an excerpt, change it, comment on it, and point to the
  sentence you mean. Your judgement replaces the AI's in the answer, the counts and the exports, always counts, and
  is kept next to the AI's; the result shows how much you reviewed and how often you agreed with the AI.
- **"Only uncertain evidence"** (`uncertain`): excerpts were judged, but none as surely as the strictness asks. Before,
  this showed as "nothing found".
- **Who says what**, from the same rule as the counts: a document is supporting if one of its counted excerpts
  supports, partly supporting only if none does, contradicting if one contradicts (so it can be on both sides).
- **Locations you can cite**: pages for PDFs, paragraphs for text and web pages ("quote in paragraph 6 of 8"), and a
  document view by page or paragraph that opens at the highlighted quote.
- **Excel downloads**: a summary sheet (one row per hypothesis) and every excerpt read, with who judged it, the AI's
  own judgement and certainty, the quote and who chose it, where it is, comments and notes; local dates.
- Text files take their title from their first line.

### Compatibility

- Status texts are the app's plain words ("Supported by your documents", "Mixed evidence", …); new status
  `uncertain`. Status codes are unchanged.
- New columns (`verifications.user_*`) and a `paragraphs` table are added to existing projects on first open.
  Paragraph locations apply to documents added from 0.5.1 on; older ones show "about 40% into the document".
- `continue_check` / `more_passages` with `terms` read only passages that contain at least one of the terms.
- The API gains `PUT …/claims/<id>/judgements/<passage_id>`, `…/export.xlsx`, `?view=blocks` on documents and
  `local_only` in the state; see docs/API.md.

### Suggested next steps (from the user tests)

- Preview and edit the split into parts, and the AI's extra search words, before a check runs.
- Flag excerpts about another group than the hypothesis names (fully remote vs. hybrid, all ages vs. young).

## 0.5.0 (October 2026): a local-first hypothesis checker

0.4 checked single SDG claims, by default through the Claude API, in a Streamlit app. 0.5 checks **any hypothesis**
against your own documents, **locally by default**, in a new dependency-free app. The SDG / value chain assessment
pipeline of the green hydrogen pilot is kept as an optional pack and gives the same results as 0.4.

### Hypotheses

- **Decomposition**: a hypothesis can be split by the model into 2–5 claims that must all hold; each is searched and
  graded on its own and the verdict combines them (a contradicted part makes the hypothesis contradicted).
- **"Contested"**: support and contradiction above the threshold together (shown as *Mixed evidence* from 0.5.1).
  In 0.4 a single supporting passage made a claim "stated by a source" however many passages refuted it.
- **Evidence balance**: documents supporting / partly / refuting, and a lean from −1 to +1.
- **Rounds in the app**: *Read more passages* and *Search again with other terms* (before, only the connector could).
- **Show in context** (neighbouring passages), **notes** on a check, **remove one document** (past checks keep their
  evidence), a **document viewer**.
- **Batches**: one hypothesis per line or a CSV (comma, semicolon or tab; `hypothesis`, optional `framework`, `code`),
  in the app and with `enlens batch FILE --out results.csv`.
- **Frameworks**: optional codebooks a hypothesis can be tagged with. The 169 SDG targets ship as one; add your own as
  a CSV (`code, description[, group, group_name]`) per project or for all projects.
- Generic prompts (`check-v2`, `expand-v2`, new `decompose-v1`); the pack's prompts are unchanged.
- 0.4 checks are migrated into the new `hypotheses` table on first open.

### Local first

- **Model servers found automatically**: Ollama, LM Studio, llama.cpp, Jan, vLLM (`enlens detect`; backend `auto`, the
  new default in the app and on the command line).
- **OpenAI-compatible backend rewritten**: streams (progress, stall detection, Stop), sends the answer's JSON schema and
  falls back to `json_object` or no format, has `check()` and `models()`, and turns network problems into plain
  messages. In 0.4 it sent only `json_object`, which LM Studio rejects.
- **The Claude API is opt-in**: the app uses it only after *Allow cloud models* (with a notice that passages leave the
  computer); on the command line only with `--backend anthropic`.
- **Semantic search with local embeddings** (optional): Ollama or OpenAI-compatible embedding models, vectors stored in
  the project, keyword and semantic rankings fused (reciprocal rank fusion). `enlens embed`, or *Build semantic index*.
- **Multilingual search**: the tokenizer keeps letters of every language (0.4 turned "économie" into "conomie").
- **The app** (`enlens-gui`, now http://127.0.0.1:8765) is a standard-library HTTP server with a static page: no
  Streamlit, no CDN, no fonts or analytics from the internet. A token per run, Host and Origin checks (no DNS
  rebinding, no cross-site requests), a strict Content Security Policy. `--host 0.0.0.0` serves the network only by IP
  address and hands the token out only in the link printed in the terminal.
- `<think>` blocks of local reasoning models are ignored when reading answers.

### The app

Redesigned from scratch (designed and built by a Fable 5.1 sub-agent against `docs/API.md`): a guided first run
(project → documents; the model is set up once under Settings), a persistent indicator of where text goes, live progress per claim with the model's
activity, a result page built for auditing (verdict, balance, per-part evidence with the verified quote highlighted,
weak grades marked, found by keywords / meaning), history with filters and threshold, batches, sources with quality
warnings and the semantic index, settings incl. frameworks and *Test a model*. Light and dark themes, keyboard
accessible, works down to 380 px wide, no external resources. Long work runs as background jobs that can be stopped.

### Faster

Measured on the pilot workspace (38 documents, 11,312 passages):

| | 0.4.1 | 0.5.0 |
| --- | --- | --- |
| First check (builds the keyword index) | 3.4 s | 1.4 s |
| 30 further checks (offline baseline) | 1.5 s | 0.6 s |
| History of 32 checks | 97 ms | 3 ms |
| Export of all checks | 180 ms | 10 ms |
| `make-tasks verify-vca` | 32.7 s | 3.2 s |
| `make-tasks extract --per-target 6` | 5.0 s | 1.4 s |
| `screen` | 12.4 s | 4.8 s |
| Tokenising the corpus | 3.0 s | 0.9 s (pack) / 1.2 s (hypotheses) |

How: BM25 as an inverted index (a query touches only passages containing its terms; scores bit-identical to 0.4), one
index per set of sources instead of one per VCA claim, per-thread SQLite connections with `synchronous=NORMAL`, indexes
on verifications/tasks/claims, history computed in four queries, a translate-table normaliser, cached stemming,
binary search for page numbers, a thread-safe index cache per corpus state.

### The SDG pack stays as it was

The pack keeps 0.4's tokenizer, sentence splitter and prompts. On the pilot, `make-tasks verify-vca` and
`make-tasks extract --per-target 6` queue no new tasks, the tokens of all 8,778 body passages, the BM25 rankings, the
per-target selection and all 11,312 screen scores are identical to 0.4, and `load-vca` and `match-sources` give the
same results.

### Defects fixed

Found by an independent review of 0.4.1 (each confirmed with a reproduction; regression tests added):

High
- A zip named `...zip` (for example inside an uploaded zip) unpacked into the workspace itself and could overwrite
  `enlens.sqlite` and `config.json`, destroying the project.
- The Turkish capital "İ" shifted every quote offset after it and crashed quote checking when a quote ended at the
  end of a passage; the task stayed pending, so every later `run` stopped at it (also `import-results`,
  `check-results`, the connector's `submit_grades`).
- Re-splitting a justification left the old claim's grades under the same position id (`6.4#1`), so the report showed
  a new claim as supported by quotes graded for another.
- Re-answering an extraction task (`refresh`) undid reviewer decisions; rejected claims came back and never returned to
  the review queue.

Medium
- A failing answer deleted the earlier valid claims of an extraction task (the deletion was committed).
- Two zips with the same file name (from different folders) overwrote each other; one corpus was silently lost.
- The app's *Remove all documents* on a linked pilot also deleted all extracted claims and VCA verifications (now
  refused while pipeline results exist).
- `ingest` held the database write lock for the whole run; checks in the app or connector failed with "database is
  locked" (now one transaction per document).
- `export-tasks` numbered batches by count, so after a batch file was removed the next export overwrote another.
- `tools/pdf_to_text.py` deleted a sources folder called `enlens_text`, and lost one of two PDFs with the same name in
  different subfolders.
- `make-tasks verify-vca` rebuilt the BM25 index for every VCA claim, inside the write transaction (≈12 minutes with
  `--beyond-cited`).
- `review-import` failed on CSVs saved by Excel (byte-order mark, Windows-1252); so did manifests.
- `refresh KIND --model M` switched audit tasks to the main model, so audits compared a model with itself.
- The claim checker's passage index could go stale after removing and re-adding documents (keyed on counts).

Low
- `match-sources` deleted links added by hand (now kept with method `manual`).
- The same claim checked twice within a second raised an IntegrityError (ids were text + second).
- The connector's `create_project` left an empty project behind when the path was mistyped.
- Quotes were rejected when the source had decomposed accents or soft hyphens.
- The zip-slip guard was a string-prefix check (`../src_evil/` escaped a folder `src`).
- Reports of one organisation from different years were merged as one reference.
- Invalid influence values in review imports were stored.
- A results line that is valid JSON but not an object crashed `import-results` and `check-results`.
- The saved API key file was briefly readable by other users.
- Nested zips had no size limit (now one 8 GB budget per ingest).

Found while rebuilding:
- The claim's own words were meant to count double in the search; BM25 ignored repeated query terms, so they did not.
- The tokenizer dropped accented and non-Latin letters, and stemmed inconsistently ("stress"/"stresses",
  "price"/"prices" never matched).
- `backend-check --backend local` crashed (no `check()`); local-server network errors surfaced as tracebacks.
- `check` and `run` with `--backend ollama` used the Claude model name stored in `config.json` ("Ollama has no
  model claude-opus-5-5").
- Re-storing an extraction deleted stated interactions with a `LIKE` prefix that also matched other tasks
  (passage numbers ≥ 10,000; `_` in ids).
- One unreadable file aborted a whole ingest, and nothing of that run was saved.
- A failed capability lookup was cached, so Ollama's reasoning setting was ignored after Ollama started late.
- The checker's index cache was cleared on every miss (projects evicted each other) and was not thread-safe.
- File names in the documents table kept Windows paths.

A second review of the 0.5 code before release found and fixed twelve more (among them: parallel jobs failing with
"database is locked" under deferred transactions, `--host` handing out the token, path checks on framework deletion
and uploads, Stop not reaching the Claude API, semicolon CSVs, overlapping ingests).

### Compatibility

- `enlens-gui` no longer needs Streamlit; the `gui` extra is empty. New extra `fast` (numpy).
- Default backend is `auto` (local). For the 0.4 behaviour pass `--backend anthropic`. Settings of a 0.4 install that
  used the Claude API with a key keep it (cloud allowed); otherwise the app starts local.
- Status texts: "Stated by a source" is now "Supported by a source"; new status `contested`.
- `claimcheck.check_claim`, `result`, `history`, `open_check`, `submit_grades`, `more_passages` keep their signatures
  (history rows gain `hyp_id`, `parts`, `lean`); `gui.core` re-exports `home`.

### Suggested next steps (not in 0.5)

- Pick the default local model by recency (Ollama reports when each model was pulled) instead of alphabetically.
- An evidence map after a batch: hypotheses × documents, to spot verdicts that rest on one source.
- Export and import a project as a zip, to back up or share a corpus with its checks.
- Local OCR for scanned PDFs (ocrmypdf) during ingest.
- A local reranker (cross-encoder) after the hybrid search.
- A calibration view: your agreement with grades at each confidence, to set the threshold.
- Re-check hypotheses whose verdict may change after new documents are added.
- Grade with two local models and flag disagreements.
