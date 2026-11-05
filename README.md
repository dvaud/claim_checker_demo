# ENLENS: explore your documents, and check what they say, with Claude on your own plan

ENLENS helps researchers find their way through their own reports, papers and interview notes, and check whether
they support a statement, with every quote checked against the source. It runs on your computer.

## Install

1. **Paste one line.** On a Mac or Linux, open *Terminal*; on Windows, open *PowerShell*. Paste the line for your
   system and press Enter:

   | System | Where | Paste this |
   | --- | --- | --- |
   | macOS, Linux | Terminal | `curl -fsSL https://github.com/dvaud/claim_checker_demo/releases/latest/download/install.sh \| sh` |
   | Windows | PowerShell | `powershell -ExecutionPolicy Bypass -c "irm https://github.com/dvaud/claim_checker_demo/releases/latest/download/install.ps1 \| iex"` |

   It needs no git, no Python and no administrator rights. When it is done, ENLENS opens in your browser and its
   icon is in the usual place (macOS: Applications and Desktop; Windows: Start menu and Desktop; Linux: the
   applications menu).
2. **Press *Set up Claude*** on the first screen. It installs Claude Code if it is missing (it shows you the command
   first), opens a window where you sign in once with your Claude plan, and adds the ENLENS plugin.
3. **Name a project and add your documents** (PDF, Word, web pages, text, or a zip of them). ENLENS asks who may read
   them with AI: *Claude may read them*, *Only a local AI*, or *No AI*. Using Zotero? The *Bibliography* page brings in
   a collection and the PDFs Zotero keeps.
4. **Explore and check.** Where AI work waits (labels, theme names, a check), press **Start Claude Code**; the
   results appear as they come in.

Used ENLENS on another computer? Choose *Import from another computer* on the first screen (on the old computer:
*Projects → Move ENLENS to another computer*). No Claude plan? See *Other ways to run it* below.

## Update

ENLENS looks for a new version when it opens and every two minutes after. When there is one:

1. A pop-up in the corner says so, and **Update to …** appears at the bottom of the sidebar.
2. Choose **Update and restart** (in the pop-up, or from the sidebar button). ENLENS installs it and starts again;
   the page opens the new version by itself.

*Later* puts the pop-up away for that version; the sidebar button stays until you update. To look yourself, use
**Check for updates** in *Settings → Technical*.

On **Windows** (installed with the install line), quit ENLENS (*Quit ENLENS*) and paste the install line again in
PowerShell instead. Still on 0.13.0 or earlier (there is no *Update* button yet)? Quit ENLENS, type
`enlens update` in Terminal or PowerShell (or paste the install line again), and open ENLENS again from its icon.

Your projects and settings (in the folder `enlens` in your home folder) are never touched. Installed from a git copy
instead? The *Update* button and `enlens update` pull the new version (see *For developers*).

## New in 0.13: your Zotero bibliography next to your documents

- **Bring in a Zotero collection in one click.** The new *Bibliography* page reads a collection (or your whole
  library, or a group library) from the Zotero app on your computer: Zotero 7 or later, with *Settings → Advanced →
  Allow other applications on this computer to communicate with Zotero* ticked once. Nothing goes over the internet,
  and Zotero is only read. No Zotero app at hand? Use a file exported from Zotero, Mendeley or EndNote (BibTeX, RIS,
  CSL JSON or Zotero's CSV).
- **No document added twice.** Each work is linked to the document you already have: by itself when it is the same
  file or has the same DOI; when only its title, an author or the year are on the document's first pages, the pair
  waits for one click (*Same work* or *Not the same*), shown next to the place where the title stands. A PDF you
  added as "download (3).pdf" now shows *Verhoeven and Okafor (2025)* in the Documents list.
- **Your list of works to find.** Every work without a document, with its authors, year, DOI link, web address and
  *Open in Zotero*, and *Download the list* as a spreadsheet. The PDFs Zotero already keeps for them are added in one
  go, read where Zotero keeps them, each linked to its work. Documents you add later are matched as they come in.
- **Documents Zotero does not have** are listed too, so you see the gaps in your library as well.
- Your decisions are kept when you update from Zotero or switch to another collection or file.
- **Update ENLENS from the app (0.13.1).** *Update ENLENS* at the bottom of the sidebar looks for a new version,
  installs it and restarts ENLENS; the open page comes back by itself. No terminal needed. When a new version was
  installed while ENLENS kept running, the notice at the top of every page has *Restart now*.
- **A clearer result page (0.13.2).** Short headings of the document show as headings above the quote, an excerpt
  that does not count says *Not counted* and its certainty like every other card, and a hypothesis in parts counts a
  document on both sides once.
- **Every page as calm as the result page (0.13.3).** One short line under each title, bold only for headings and
  the main button, grey AI marks (green, amber, red and purple now always mean a judgement), longer explanations
  behind a small (?), and downloads as one quiet line of links. On a phone, *Search* no longer scrolls sideways.
- **Checks on Sonnet (0.13.3).** Judging excerpts goes to Sonnet at high effort instead of Opus; an unsure
  judgement, *Ask a stronger model* and second opinions still go to Opus (or Fable).
- **Titles from Zotero (0.13.3).** A document linked to a work in your bibliography takes the work's title from Zotero
  everywhere in ENLENS. The title in the file stays visible on the document page and comes back if you unlink the
  work.
- **Which Claude account answers (0.13.4).** Hover *Claude, on your plan* at the bottom of the sidebar to see the
  account Claude Code is signed in to (*you@university.nl*, *Team plan · University of Amsterdam*). *Settings → AI*
  names it too.
- **Fixes (0.13.5).** Accented file names in zips made with Finder's *Compress* come out right; *Import a project*
  takes a project folder zipped by hand; a smoother icon; *second opinion* everywhere. For developers: room for apps
  built on ENLENS (`site.css`, `brand.json`, add-on modules; see [docs/EXTENDING.md](docs/EXTENDING.md)).
- **Updates that announce themselves (0.13.6).** The *Update* button shows only when there is an update: ENLENS
  looks every two minutes, and a pop-up says which version is ready. *Check for updates* is in *Settings →
  Technical*.
- **Room for add-ons (0.13.6).** For developers: an app built on ENLENS adds routes, jobs, tables, its own rules for
  who may read its text, kinds of AI task (quote check included) and pages, in files of its own
  ([docs/EXTENDING.md](docs/EXTENDING.md)). Nothing changes in the app.
- **Version numbers (0.13.6).** 0.14.0, 0.15.0 and 0.15.1 were withdrawn: they changed nothing in the app, and their
  changes are part of 0.13.6. Installed one of them with the install line? Paste the install line once more.

## Earlier releases

- **0.12**: a calmer result page: one card with the answer, at most one caution and *Next to review*; every
  excerpt card reads the same way, with *Agree*, *Not about this* (one click, with *Undo*) and *Judge differently*;
  the sidebar says *not running* when work waits for Claude Code and nothing answers it.
- **0.11**: choose who may read each document with AI (*Claude may read it*, *Only a local AI*, *No AI*), enforced in
  every feature, with a record of what Claude has read; 0.11.1 a deep clean (about forty defects fixed, large projects
  much faster); 0.11.2 a stronger model's answer becomes the answer, with a mark of the first one; 0.11.3 *Start Claude
  Code* asks for attention while work waits for it.
- **0.10**: install with one pasted line and update with `enlens update`; *Set up Claude* in one button; move every
  project to another computer; the icon always opens the version installed.
- **0.9**: subscription first (Claude Code on your own plan is the AI) and exploring first (Overview, Search,
  Profile, Concepts, Themes before checking).
- **0.8**: Claude Code answers every AI task through a queue, with the right model for each kind of task.
- **0.7**: explore the documents (search, codebook profiles, a glossary of concepts, themes, references), replacing
  the Cross-Doc SDG Explorer.
- **0.5 and 0.6**: the hypothesis checker for researchers who do not program: checked quotes, your own judgements,
  a second opinion, look before checking.

The full notes of every release are in `CHANGELOG.md`.

## What ENLENS does

ENLENS reads your sources (reports, papers, policy documents, interview notes) and helps you find your way through
them before you claim anything: every place a word occurs, the codes each document addresses (the SDG targets or
your own codebook), a glossary of terms grouped into concepts you can follow from one document to the next, themes
across the documents, what "it" and "they" refer to, highlighted copies, and an export in Cross-Doc's FlexiConc
format. Most of that needs no AI at all; what the AI adds is quoted, checked against the text, and yours to overrule.

When you have a statement to test, ENLENS also checks it: supported, partly supported, contradicted or mixed
evidence, with the exact words of each source, where they are (page or paragraph), and a quote checked character by
character against the source text. You review the AI's judgements like a co-coder's; your judgements count and are
kept next to the AI's in the Excel download.

The AI is Claude, through Claude Code signed in with your own Claude plan (Pro, Max, Team or Enterprise). ENLENS sets
Claude Code up by itself and starts it when you press *Start Claude Code*; each kind of task goes to the right model
(labels on Haiku, theme names and checks on Sonnet, second opinions on Opus). Your documents, results and reviews
stay on your computer: only the passages inside the AI's tasks, from documents Claude may read, are sent to
Anthropic. A model on your own computer (Ollama, LM Studio…) and a shared installation on the Claude API remain
available, and whoever installs it can switch everything off the computer off for good (`--local-only`).

The app is written for researchers who do not program: plain language on every working screen; each feature says
what it does and whether it uses the AI; technical details are kept under *Technical details* and
*Settings → Technical*. It grew out of the Cross-Doc SDG Explorer and the ENLENS green hydrogen pilot (a Value Chain
Assessment checked against its cited literature); that SDG pipeline is still included as an optional pack.

## Other ways to run it

What the install line does: it gets [uv](https://docs.astral.sh/uv/) (which brings its own Python 3.12), downloads
the ENLENS package of the latest release, checks it against the release's `SHA256SUMS`, installs it, and makes the
icon. `ENLENS_LOCAL_ONLY=1` or `ENLENS_HOME=<folder>` before the line are built into the icon. Instead of the button,
`enlens claude-setup` sets up Claude from a terminal, and `/enlens-run <project>` in Claude Code answers a project's
waiting work yourself.

No Claude plan? Choose *A model on this computer* (first screen or *Settings → AI*):

```bash
ollama pull qwen3:8b             # any local chat model (Ollama, LM Studio, llama.cpp, Jan, vLLM all work)
ollama pull nomic-embed-text     # optional: search by meaning as well as by words (bge-m3 for mixed languages)
```

Installing it for someone else: the install line, on their account (*Quit ENLENS* in the app stops it);
`ENLENS_LOCAL_ONLY=1` removes every option that sends text off the computer. Scanned PDFs need the program
Tesseract; the app says how to get it on that system when it meets a scanned page.

From the command line:

```bash
enlens --ws myproject init
enlens --ws myproject ingest ~/Reports/                    # PDFs, Word (.docx), HTML, text, Markdown, zips
enlens --ws myproject search "commuting emissions" --mode phrase --out hits.csv
enlens --ws myproject profile --keywords-only --out profile.xlsx   # SDG targets per document, no model
enlens --ws myproject themes --k 20 --out themes.xlsx
enlens --ws myproject export-flexiconc myproject.sqlite     # for tools that read Cross-Doc's FlexiConc format
enlens --ws myproject prepare label                         # AI work for Claude Code; then /enlens-run myproject
enlens --ws myproject check "Remote work lowers commuting emissions in large cities." --decompose --backend ollama
enlens --ws myproject batch hypotheses.csv --out results.csv --backend ollama
enlens detect                                               # which local model servers are running
```

`enlens prepare label|link|theme|resolve|check` prepares AI work for Claude Code from the command line, and `enlens
queue status|run` shows it or answers it here (`--backend anthropic` for a shared installation). Inside the Claude
app (Claude reads on your plan; only the passages shown leave the computer): `enlens-mcp --install-claude-desktop`.

## For developers (a git copy)

Install ENLENS once from its git copy, and every later version is one command, in the same folder and the same
venv (the data folder, `~/enlens`, is never touched):

```bash
git clone https://github.com/<you>/<repo>.git ~/enlens-app && cd ~/enlens-app   # once
python3 -m venv .venv && source .venv/bin/activate && pip install -e '.[connector]'
enlens-gui --make-launcher                                                       # once: the Desktop icon

enlens update            # later: fetch the new version (add --check to only look)
```

Because the install is editable (`-e`), the app runs the code in that folder: `enlens update` pulls the new version
and reinstalls only when its requirements changed. Then open ENLENS from its icon: an older version still running is
quit and the new one started (0.10.2), and if something still runs in it, the page says to quit and reopen. Run
it as `~/enlens-app/.venv/bin/enlens update` if the venv is not active.

## Exploring the documents (the main part of the app)

| Page | What it gives | Model? |
| --- | --- | --- |
| Search | Every place words occur, with the words around them; phrases, near, other forms, words nearby; Excel/CSV | no |
| Profile | The codes each document addresses, how much and where, with the words or quote and reason behind each | keywords first; the AI confirms |
| Concepts | A glossary of terms grouped into concepts (abbreviations, wordings, your links); where each appears | optional |
| Themes | Themes across the documents, by document and by code; rename, merge, move | optional (names) |
| A document | Codes, key terms, references ("it", "they"), search, a highlighted copy | references only |

The *Overview* page (the start page of a project) shows these first, each with what it does, whether it uses the
AI and what is already made; checking hypotheses comes second. In the sidebar a filled **AI** mark means the feature
needs the AI, a dashed one that the AI is optional, and no mark that it never uses the AI.

Where the parts of the Cross-Doc SDG Explorer went:

| Cross-Doc | ENLENS |
| --- | --- |
| Single-document concordance (AND / OR), token strip | Search (any / all / phrase / near), across all documents or one |
| SDG classifier, dual consensus | Profile: keywords and meaning first, the AI confirms with a quote and a reason |
| Explainability (integrated gradients, span masking, keyphrases) | Key terms per document and passage; the words and reason behind every label |
| Coreference (fastcoref, LingMess) | References in a document (the AI follows "it" and "they"); checks say what a quote's "it" is |
| Global coreference (trie) across documents | Concepts: one concept followed across every document, with its wordings |
| SciCo clusters, communities and summaries | Themes, named by the AI with checked quotes |
| `pdf_highlight_post.py` | Highlighted copies of a document, an answer, a column of the evidence map |
| FlexiConc SQLite | *For FlexiConc / Cross-Doc* on the Projects page, `enlens export-flexiconc` |

Every model answer records the model, its exact version (digest), the prompt version and the seed (42 by default,
temperature 0); every Excel download ends with *How these results were made*. Since 0.8 it also records the route
(Claude Code, the Claude API, a local server), the helper, and whether the answer came from the stronger model.

## What a check does

1. *(optional)* The model splits the hypothesis into the claims that must all hold ("decompose").
2. *(optional)* It writes search terms for each claim: synonyms, technical words, the opposite phrasing.
3. The best passages are picked by keywords (BM25), fused with semantic search when the project has embeddings,
   at most a few per document so one long report cannot fill every slot.
4. The model grades each passage that bears on the claim: supports, partly supports, refutes, with a quote and a
   confidence. Every quote is verified against the passage; answers that fail are retried with the problems listed.
5. The answer counts the judgements the AI is sure enough about (the *strictness*, 60% by default) and yours:
   **supported**, **partly supported**, **mixed evidence** (`contested`), **contradicted**, **only uncertain
   evidence**, or **no evidence found**, with who says what per document. A split hypothesis combines its parts
   (every part must hold), and the app says which part decides.

You can look at the parts and search words before a check runs and change them, review and correct every judgement,
ask the AI to read one excerpt again with your comment, ask a second local model for its judgements and see where
the two disagree, look for more evidence or search with other words, read documents added later without losing your
reviews, open the document at the quote (by page and paragraph) or the original file, see all results as a map of
which documents decide which answers, see how often you agree with the AI at each certainty, add notes, download a
result or all results for Excel (summary, every excerpt with who judged it, the map) or as CSV/JSON, and hand the
whole project to a colleague as one zip.

## A model per task (0.8)

| Task | Claude Code and the Claude API | Steps up to | Local |
| --- | --- | --- | --- |
| Codebook labels, concept links | Haiku | Sonnet | the small model (if chosen) |
| Search words, splitting, theme names, references | Sonnet | Opus | the main model |
| Judging excerpts, reading one again | Sonnet (high effort) | the auditor | the main model |
| Second opinion | the auditor (Opus, or Fable if switched on) | | the second model |

A task steps up once: when its answer's certainty is under 0.6, after two rejected answers, or when you press *Ask a
stronger model*. The defaults are starting points until the runs on the pilot (`enlens acceptance queue|score`,
see docs/MODEL_CHOICE.md) set them.

## Privacy

- Claude Code (the default from 0.9) runs on your own Claude plan. ENLENS never sees its login: Claude Code uses its
  own. Started from the app, it may use only the four ENLENS queue tools and its helpers (`--allowedTools`), is
  denied its own file, shell and web tools (`--disallowedTools`, 0.11) and starts in an empty folder; only the
  passages inside the tasks it takes are sent to Anthropic. Stop it at any time; what it had taken waits again.
- Documents marked *Only a local AI* or *No AI* (0.11) are never sent to Claude: every task is labelled with the most
  restricted setting of the documents it names and refused before a model it does not allow is asked; the queue
  hands Claude Code only what Claude may read; the connector gives Claude counts instead of their text. Every passage
  that does go to Claude is recorded (*Sent to Claude* on the Documents page, a CSV under *Settings → Technical*).
- A model on this computer keeps every word on it. The Claude API is available only after *Allow cloud models* is
  switched on (or `--backend anthropic` on the command line). `--local-only` hides both cloud options for good.
- The app is a small standard-library server on 127.0.0.1 with a per-run token; the page loads nothing from the
  internet (no CDN, fonts or analytics). No Streamlit, no telemetry.
- Projects are plain folders with one SQLite database; settings live in `~/enlens` (or `ENLENS_HOME`).

## Documentation

- [docs/MANUAL.md](docs/MANUAL.md): the manual (app, command line, connector, models, the SDG pack).
- [docs/API.md](docs/API.md): the local app's HTTP API.
- [docs/EXTENDING.md](docs/EXTENDING.md): building an app on ENLENS without editing its files (0.13.5): the local
  layer, add-on modules, and what each extension point does.
- [CHANGELOG.md](CHANGELOG.md): what changed in each release (0.5 to 0.11.3), including the defects fixed.
- [docs/USER_TESTS.md](docs/USER_TESTS.md): the first-time user tests behind the app (0.5.1 to 0.7.0).
- [docs/MODEL_CHOICE.md](docs/MODEL_CHOICE.md): which model each task needs, measured on the pilot (0.8: the method
  and the empty tables, until the runs are made).

## Layout

| Module | Role |
| --- | --- |
| `claimcheck.py` | Hypotheses: decomposition, checks, statuses, a person's judgements, who says what, rounds, re-reads, second opinions, new documents, the evidence map, calibration, batches, history, Excel |
| `search.py`, `embed.py`, `retrieve.py` | Cached keyword index, local embeddings and hybrid ranking; BM25 (inverted index) |
| `frameworks.py`, `taxonomy.py` | Optional codebooks (SDG targets bundled, custom CSVs) |
| `llm.py` | Ollama, OpenAI-compatible local servers (LM Studio, llama.cpp…), server detection, Claude API, offline baseline |
| `tasks.py`, `schema.py`, `prompts.py` | Model tasks, validation with the quote check, versioned prompts |
| `access.py` | Who may read each document with AI (0.11): the settings, the guard on every task, which model reads what, the ledger of what was sent to Claude, the cap |
| `ingest.py`, `textutil.py`, `store.py` | Documents and passages with page offsets, layout (paragraphs, headings), local OCR, text normalisation, the workspace database |
| `bundle.py` | A whole project as one zip (export and import); every project and the settings, to move to another computer (0.10) |
| `installation.py`, `update.py` | How this copy was installed (git copy, the one-line install, a package, pip) and `enlens post-install`; `enlens update` for each (0.10) |
| `home.py` | Settings, projects, the optional cloud key |
| `gui/` | The local app: `server.py` (API and jobs), `static/` (the page), `progress.py`, `launcher.py` (the ENLENS icon), `icons/` (its picture, drawn by `tools/make_icons.py`) |
| `concordance.py` | Search (0.7): concordance lines, modes, other forms, collocates |
| `profile.py` | Codebook profiles: the keyword and meaning pass, the AI's labels, grids, a person's labels |
| `terms.py` | The glossary (C-value terms, abbreviations), concepts and their links, key terms |
| `themes.py` | Themes: spherical k-means (numpy or pure Python), c-TF-IDF names, a person's edits |
| `references.py` | References inside a document (chains), and what a quote's "it" refers to |
| `bibliography.py` | The bibliography (0.13): Zotero read through its local API, BibTeX / RIS / CSL JSON / CSV files, matching works with documents |
| `annotate.py` | Highlighted PDFs (pdfminer boxes, pypdf lines, OCR) and HTML copies |
| `flexiconc_export.py`, `runs.py`, `acceptance.py` | The FlexiConc export; runs and "How these results were made"; the 0.7 acceptance measures |
| `mcp_server.py` | The connector for the Claude app and Claude Code (0.8: also the queue tools) |
| `taskqueue.py`, `routing.py` | The task queue for Claude Code (claims, order, estimates, waiting) and the model of each kind of task (0.8) |
| `claude_setup.py`, `claude_plugin/` | The Claude Code plugin: `/enlens-run`, its seven helpers and the connector (0.8); finding Claude Code, adding the plugin to it and starting it for a project's queue (0.9) |
| `evaluation.py` | The acceptance runs per kind and model through the queue, and their scores (0.8, G6) |
| `vca.py`, `sources.py`, `analysis.py`, `review.py`, `report.py`, `benchmark.py` | The SDG / value chain assessment pack |

`install/install.sh` and `install/install.ps1` are the one-line install; `.github/workflows/release.yml` turns a
tag `vX.Y.Z` into a draft GitHub Release (tests, the package, the two scripts with the version filled in,
`SHA256SUMS`, and a try of the install line on Linux, macOS and Windows) with `tools/release.py`.
`tools/dev_server.py` runs the app against fake local models (for interface work; `--fresh-user` shows the app as a
new user would find it, with the remote-work demo documents in `tools/demo_corpus/`; `--claude-code` with a fake
Claude Code answering the queue; `--claude-cli` with a stand-in `claude` program the app sets up and starts, 0.9;
`--claude-install` with Claude Code still to be installed and signed in to, `--no-tesseract` without Tesseract, 0.10;
`--zotero` with a stand-in Zotero for the Bibliography page, 0.13);
`tools/pdf_to_text.py` turns a
folder of PDFs into page-preserving text files; `tools/eval_second_pass.py` measures the second sorting pass on the
pilot. The green hydrogen pilot (workspace, report, run notes) is in
`pilot/`.
