# ENLENS: explore your documents, and check what they say, with Claude on your own plan

ENLENS reads your sources (reports, papers, policy documents, interview notes) and helps you find your way through
them before you claim anything: every place a word occurs, the codes each document addresses (the SDG targets or
your own codebook), a glossary of terms grouped into concepts you can follow from one document to the next, themes
across the documents, what "it" and "they" refer to, highlighted copies, and an export in Cross-Doc's FlexiConc
format. Most of that needs no AI at all; what the AI adds is quoted, checked against the text, and yours to overrule.

When you have a statement to test, ENLENS also checks it: supported, partly supported, contradicted or mixed
evidence, with the exact words of each source, where they are (page or paragraph), and a quote checked character by
character against the source text. You review the AI's judgements like a co-coder's; your judgements count and are
kept next to the AI's in the Excel download.

**Subscription first (0.9).** The AI is Claude, through Claude Code signed in with your own Claude plan (Pro, Max,
Team or Enterprise). ENLENS sets Claude Code up by itself and starts it when you press *Start Claude Code*; each kind
of task goes to the right model (labels on Haiku, theme names on Sonnet, checks on Opus). Your documents, results
and reviews stay on your computer: only the passages inside the AI's tasks are sent to Anthropic. A model on your own
computer (Ollama, LM Studio…) and a shared installation on the Claude API remain available, and whoever installs it
can switch everything off the computer off for good (`--local-only`).

The app is written for researchers who do not program: plain language on every working screen; each feature says
what it does and whether it uses the AI; technical details are kept under *Technical details* and
*Settings → Technical*. It grew out of the Cross-Doc SDG Explorer and the ENLENS green hydrogen pilot (a Value Chain
Assessment checked against its cited literature); that SDG pipeline is still included as an optional pack.

## Start

Paste one line (0.10). It needs no git, no Python and no venv of your own, and ends with the ENLENS icon in its
usual place and ENLENS open in your browser:

| System | Where | Paste this |
| --- | --- | --- |
| macOS, Linux | Terminal | `curl -fsSL https://github.com/dvaud/claim_checker_demo/releases/latest/download/install.sh \| sh` |
| Windows | PowerShell | `powershell -ExecutionPolicy Bypass -c "irm https://github.com/dvaud/claim_checker_demo/releases/latest/download/install.ps1 \| iex"` |

The line gets [uv](https://docs.astral.sh/uv/) (which brings its own Python 3.12), downloads the ENLENS package of
the latest release, checks it against the release's `SHA256SUMS`, installs it, and makes the icon (macOS:
Applications and Desktop; Windows: Start menu and Desktop; Linux: the applications menu). Running it again installs
the newest release; your projects (in `~/enlens`) stay where they are. `ENLENS_LOCAL_ONLY=1` or `ENLENS_HOME=<folder>`
before the line are built into the icon.

Then press **Set up Claude** on the first screen: it installs [Claude Code](https://claude.com/claude-code) if it is
missing (with Anthropic's installer, after showing you the command), opens a window where you sign in once with your
Claude plan, and adds the ENLENS plugin (or, from a terminal, `enlens claude-setup`). Then create a project, add
documents, and explore. Used ENLENS on another computer? *Import from another computer* on the first screen brings
every project and the settings (made there with *Projects → Move ENLENS to another computer*). Wherever AI
work waits (labels, theme names, a check…), press **Start Claude Code**: ENLENS starts it in the background on that
project's work and the results appear as they come in. You can also type `/enlens-run <project>` in Claude Code
yourself.

No Claude plan? Choose *A model on this computer* (first screen or *Settings → AI*):

```bash
ollama pull qwen3:8b             # any local chat model (Ollama, LM Studio, llama.cpp, Jan, vLLM all work)
ollama pull nomic-embed-text     # optional: search by meaning as well as by words (bge-m3 for mixed languages)
```

Installing it for someone else: the line above, on their account (*Quit ENLENS* in the app stops it);
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

## Updating

Installed with the line above: run it again, or `enlens update` (it takes the latest GitHub Release, checked against
its checksums, and installs it in the same place; on Windows, quit ENLENS and run the line again). Then reopen
ENLENS from its icon. The data folder, `~/enlens`, is never touched.

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
and reinstalls only when its requirements changed. Restart the app afterwards (*Quit ENLENS*, then the icon). Run
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
| Judging excerpts, reading one again | Opus | the auditor | the main model |
| Second opinion | the auditor (Opus, or Fable if switched on) | | the second model |

A task steps up once: when its answer's certainty is under 0.6, after two rejected answers, or when you press *Ask a
stronger model*. The defaults are starting points until the runs on the pilot (`enlens acceptance queue|score`,
see docs/MODEL_CHOICE.md) set them.

## Privacy

- Claude Code (the default from 0.9) runs on your own Claude plan. ENLENS never sees its login: Claude Code uses its
  own. Started from the app, it may use only the four ENLENS queue tools and its helpers (`--allowedTools`), and
  only the passages inside the tasks it takes are sent to Anthropic. Stop it at any time; what it had taken waits
  again.
- A model on this computer keeps every word on it. The Claude API is available only after *Allow cloud models* is
  switched on (or `--backend anthropic` on the command line). `--local-only` hides both cloud options for good.
- The app is a small standard-library server on 127.0.0.1 with a per-run token; the page loads nothing from the
  internet (no CDN, fonts or analytics). No Streamlit, no telemetry.
- Projects are plain folders with one SQLite database; settings live in `~/enlens` (or `ENLENS_HOME`).

## Documentation

- [docs/MANUAL.md](docs/MANUAL.md): the manual (app, command line, connector, models, the SDG pack).
- [docs/API.md](docs/API.md): the local app's HTTP API.
- [CHANGELOG.md](CHANGELOG.md): what changed in each release (0.5 to 0.10.0), including the defects fixed.
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
| `ingest.py`, `textutil.py`, `store.py` | Documents and passages with page offsets, layout (paragraphs, headings), local OCR, text normalisation, the workspace database |
| `bundle.py` | A whole project as one zip (export and import); every project and the settings, to move to another computer (0.10) |
| `installation.py`, `update.py` | How this copy was installed (git copy, the one-line install, a package, pip) and `enlens post-install`; `enlens update` for each (0.10) |
| `home.py` | Settings, projects, the optional cloud key |
| `gui/` | The local app: `server.py` (API and jobs), `static/` (the page), `progress.py`, `launcher.py` (the ENLENS icon) |
| `concordance.py` | Search (0.7): concordance lines, modes, other forms, collocates |
| `profile.py` | Codebook profiles: the keyword and meaning pass, the AI's labels, grids, a person's labels |
| `terms.py` | The glossary (C-value terms, abbreviations), concepts and their links, key terms |
| `themes.py` | Themes: spherical k-means (numpy or pure Python), c-TF-IDF names, a person's edits |
| `references.py` | References inside a document (chains), and what a quote's "it" refers to |
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
`--claude-install` with Claude Code still to be installed and signed in to, `--no-tesseract` without Tesseract, 0.10);
`tools/pdf_to_text.py` turns a
folder of PDFs into page-preserving text files; `tools/eval_second_pass.py` measures the second sorting pass on the
pilot. The green hydrogen pilot (workspace, report, run notes) is in
`pilot/`.
