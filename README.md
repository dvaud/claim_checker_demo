# ENLENS: check topics, codes, hypotheses and more against your own documents, with Claude Code or local models

ENLENS reads your sources (reports, papers, policy documents, interview notes) and tells you whether a hypothesis is
supported, partly supported, contradicted or met with mixed evidence, with the exact words of each source, where they
are (page or paragraph), and a quote checked character by character against the source text. You review the AI's
judgements like a co-coder's: agree, change them, point to the sentence you mean; your judgements count and are kept
next to the AI's in the Excel download. It runs on your computer: documents, history and models stay there unless
you explicitly allow a cloud model (and whoever installs it can switch that off for good).

The app is written for researchers who do not program: plain language on every working screen, technical details
kept under *Technical details* and *Settings → Advanced (for IT staff)*.

Since 0.7 it also lets you explore the documents before and beside checking, and replaces the Cross-Doc SDG
Explorer: a concordance search across all documents, a profile of the codes each document addresses (the SDG targets
or your own codebook), a glossary of terms grouped into concepts, themes across the documents, references followed
inside a document, highlighted PDFs, a quick look at one document, and an export in Cross-Doc's FlexiConc format.
Most of it needs no model; what the AI adds is quoted, checked against the text, and yours to overrule.

Since 0.8 the AI can also be Claude Code, signed in with your own Claude plan. ENLENS prepares the work in a queue
and checks every answer. You type `/enlens-run <project>` in Claude Code, which hands each kind of task to a helper
on the right model (labels on Haiku, theme names on Sonnet, checks on Opus) and steps hard cases up once. ENLENS never
starts Claude Code and never sees its login. A shared installation answers the same queue with the Claude API and
the team's key.

It grew out of the ENLENS green hydrogen pilot (a Value Chain Assessment checked against its cited literature); that
SDG pipeline is still included as an optional pack.

## Start

```bash
pip install -e .                 # Python 3.10+; core needs only pydantic, pypdf, openpyxl
ollama pull qwen3:8b             # any local chat model (Ollama, LM Studio, llama.cpp, Jan, vLLM all work)
ollama pull nomic-embed-text     # optional: search by meaning as well as by words (bge-m3 for mixed languages)
enlens-gui                       # opens http://127.0.0.1:8765
```

The app finds the local model server by itself. Create a project, add documents, and check a hypothesis. No model
yet? The offline demo shows how everything works. Installing it for someone else: `enlens-gui --make-launcher` puts
an ENLENS icon on their Desktop (double-click: no terminal needed; *Quit ENLENS* in the app stops it), and
`--local-only` (or `ENLENS_LOCAL_ONLY=1`) removes the cloud option entirely. Scanned PDFs: `pip install -e '.[ocr]'`
plus Tesseract.

From the command line:

```bash
enlens --ws myproject init
enlens --ws myproject ingest ~/Reports/                    # PDFs, Word (.docx), HTML, text, Markdown, zips
enlens --ws myproject embed --embed-model nomic-embed-text  # optional semantic index
enlens --ws myproject check "Remote work lowers commuting emissions in large cities." --decompose
enlens --ws myproject batch hypotheses.csv --out results.csv
enlens detect                                               # which local model servers are running
enlens --ws myproject search "commuting emissions" --mode phrase --out hits.csv
enlens --ws myproject profile --keywords-only --out profile.xlsx   # SDG targets per document, no model
enlens --ws myproject themes --k 20 --out themes.xlsx
enlens --ws myproject export-flexiconc myproject.sqlite     # for tools that read Cross-Doc's FlexiConc format
```

Inside the Claude app or Claude Code (Claude does the reading on your plan; only the passages shown leave the
computer): `pip install -e '.[connector]' && enlens-mcp --install-claude-desktop`.

Claude Code as the AI behind every task (0.8): in Settings choose *Claude Code (your subscription)*, then once

```bash
pip install -e '.[connector]'
enlens claude-setup                       # prepares the plugin and prints the two lines that add it to Claude Code
```

Press any AI button in ENLENS; then in Claude Code, opened in any folder, type `/enlens-run <project>`.
`enlens prepare label|link|theme|resolve|check` prepares the same work from the command line, and `enlens queue
status|run` shows it or answers it here (`--backend anthropic` for a shared installation).

## Updating

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

## Exploring the documents (0.7)

| Page | What it gives | Model? |
| --- | --- | --- |
| Search | Every place words occur, with the words around them; phrases, near, other forms, words nearby; Excel/CSV | no |
| Profile | The codes each document addresses, how much and where, with the words or quote and reason behind each | keywords first; the AI confirms |
| Concepts | A glossary of terms grouped into concepts (abbreviations, wordings, your links); where each appears | optional |
| Themes | Themes across the documents, by document and by code; rename, merge, move | optional (names) |
| A document | Codes, key terms, references ("it", "they"), search, a highlighted copy | references only |

Every model answer records the model, its exact version (digest), the prompt version and the seed (42 by default,
temperature 0); every Excel download ends with *How these results were made*. Since 0.8 it also records the route
(Claude Code, the Claude API, a local server), the helper, and whether the answer came from the stronger model.

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

## Local first

- The default model service is whatever local server is running. The Claude API is available only after
  *Allow cloud models* is switched on in Settings (or `--backend anthropic` on the command line), and Claude Code only
  after its own confirmation; only the passages inside the tasks it takes leave the computer.
- The app is a small standard-library server on 127.0.0.1 with a per-run token; the page loads nothing from the
  internet (no CDN, fonts or analytics). No Streamlit, no telemetry.
- Projects are plain folders with one SQLite database; settings live in `~/enlens` (or `ENLENS_HOME`).

## Documentation

- [docs/MANUAL.md](docs/MANUAL.md): the manual (app, command line, connector, models, the SDG pack).
- [docs/API.md](docs/API.md): the local app's HTTP API.
- [CHANGELOG.md](CHANGELOG.md): what changed in each release (0.5 to 0.8.1), including the defects fixed.
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
| `bundle.py` | A whole project as one zip (export and import) |
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
| `claude_setup.py`, `claude_plugin/` | The Claude Code plugin: `/enlens-run`, its seven helpers and the connector (0.8) |
| `evaluation.py` | The acceptance runs per kind and model through the queue, and their scores (0.8, G6) |
| `vca.py`, `sources.py`, `analysis.py`, `review.py`, `report.py`, `benchmark.py` | The SDG / value chain assessment pack |

`tools/dev_server.py` runs the app against fake local models (for interface work; `--fresh-user` shows the app as a
new user would find it, with the remote-work demo documents in `tools/demo_corpus/`; `--claude-code` with a fake
Claude Code answering the queue); `tools/pdf_to_text.py` turns a
folder of PDFs into page-preserving text files; `tools/eval_second_pass.py` measures the second sorting pass on the
pilot. The green hydrogen pilot (workspace, report, run notes) is in
`pilot/`.
