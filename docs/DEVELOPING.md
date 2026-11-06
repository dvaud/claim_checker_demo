# Developing ENLENS

For people who change ENLENS's code or run it from a git copy. Researchers who use ENLENS need only the
[README](../README.md) and the [manual](MANUAL.md).

## A git copy

Install ENLENS once from its git copy, and every later version is one command, in the same folder and the same venv
(the data folder, `~/enlens`, is never touched):

```bash
git clone https://github.com/dvaud/claim_checker_demo.git ~/enlens-app && cd ~/enlens-app   # once
python3 -m venv .venv && source .venv/bin/activate && pip install -e '.[connector]'
enlens-gui --make-launcher                                                                  # once: the Desktop icon

enlens update            # later: fetch the new version (add --check to only look)
```

Because the install is editable (`-e`), the app runs the code in that folder: `enlens update` pulls the new version
and reinstalls only when its requirements changed. Then open ENLENS from its icon: an older version still running is
quit and the new one started (0.10.2), and if something still runs in it, the page says to quit and reopen. Run it as
`~/enlens-app/.venv/bin/enlens update` if the venv is not active. The optional extras (`fast`, `anthropic`, `ocr`,
`pdfminer`, `dev`) are in [section 1 of the manual](MANUAL.md#1-install).

ENLENS is installed in three ways (`installation.py`): a git copy, the one-line install (`install/install.sh` and
`install/install.ps1`: uv and the release's wheel) and, later, packages. A release has to work for all three: a normal
commit on `main` that never needs a new venv, and a published GitHub Release with its files.

## Tests

```bash
pip install -e '.[dev,fast,connector,anthropic,pdfminer,ocr]'   # every extra, so no test is skipped for a missing one
python -m pytest -q -rs
```

The release workflow installs only `.[dev,connector,fast]`, so the tests that need `anthropic` or the OCR extra are
skipped there: run the whole suite on your own computer before a release. Tests never touch a real Claude Code, uv or
the network: `tests/conftest.py` points `ENLENS_CLAUDE` nowhere and gives every test its own `ENLENS_HOME`;
`tests/fake_claude_cli.py`, `tests/fake_claude_installer.py`, `tests/fake_servers.py` and `tests/fake_zotero.py` stand
in for the real programs. A release's tests go in a new file `tests/test_<X>_<Y>_<Z>_<topic>.py`; older files keep
their names. [docs/USER_TESTS.md](USER_TESTS.md) has the first-time user tests behind the app (0.5.1 to 0.7.0).

## Trying the app

`tools/dev_server.py` runs the app against fake local models, for interface work, with a Demo project:

| Option | What you get |
| --- | --- |
| `--corpus social` | the remote-work demo documents (`tools/demo_corpus/`) instead of the hydrogen ones |
| `--fresh-user`, `--empty` | the app as a new user finds it (a folder of documents ready to add), or with no project at all |
| `--claude-code`, `--claude-code-paused` | a fake Claude Code answering the queue (0.8), or chosen with nothing answering |
| `--claude-cli`, `--claude-install` | a stand-in `claude` program the app sets up and starts (0.9); Claude Code still to install and sign in to (0.10) |
| `--no-tesseract` | as if Tesseract were not installed (0.10) |
| `--mixed` | documents with each AI setting, the fake local model reading the restricted one (0.11) |
| `--zotero`, `--update`, `--ollama`, `--low-memory` | a stand-in Zotero (0.13), a stand-in newer version (0.13.1), a local model still to get (0.13.7), too little memory for it (0.13.11) |

`--home FOLDER` keeps its data apart and `--port` sets the port. Look at every page you touched in the light and dark
themes and at 390 px wide.

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
| `sync.py` | Shared projects (0.14): a colleague's project zip merged into your copy (newer versions, sync clashes, removed items, the stricter AI setting) |
| `people.py` | Shared projects (0.14): who you are to colleagues, each person's own judgements and reviews, and how often two people agreed |
| `installation.py`, `update.py` | How this copy was installed (git copy, the one-line install, a package, pip) and `enlens post-install`; `enlens update` for each (0.10) |
| `home.py` | Settings, projects, the optional cloud key |
| `gui/` | The local app: `server.py` (API and jobs), `static/` (the page; `features.js` describes each feature once), `progress.py`, `launcher.py` (the ENLENS icon), `icons/` (its picture, drawn by `tools/make_icons.py`) |
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
| `claude_setup.py`, `claude_plugin/` | The Claude Code plugin: `/enlens-run`, its helpers and the connector (0.8); finding Claude Code, adding the plugin to it and starting it for a project's queue (0.9) |
| `evaluation.py` | The acceptance runs per kind and model through the queue, and their scores (0.8, G6) |
| `addons.py` | The local layer for apps built on ENLENS (0.13.5): see [EXTENDING.md](EXTENDING.md) |
| `vca.py`, `sources.py`, `analysis.py`, `review.py`, `report.py`, `benchmark.py` | The SDG / value chain assessment pack |

Outside `src/enlens_claims/`: `install/install.sh` and `install/install.ps1` are the one-line install (keep
`install.sh` plain ASCII: macOS's `sh`, bash 3.2, misreads a non-ASCII letter right after a `$NAME`, a test checks it);
`.github/workflows/release.yml` turns a tag `vX.Y.Z` into a draft GitHub Release with `tools/release.py` (below);
`tools/pdf_to_text.py` turns a folder of PDFs into page-preserving text files; `tools/eval_second_pass.py` measures the
second sorting pass on the pilot; `tools/make_icons.py` draws the icon files. The green hydrogen pilot (workspace,
report, run notes) is in `pilot/`. The app's HTTP API is in [API.md](API.md); building an app on ENLENS without
editing its files is in [EXTENDING.md](EXTENDING.md).

## Releases

- The version stands in `pyproject.toml`, `src/enlens_claims/__init__.py` and the top `## X.Y.Z` entry of
  `CHANGELOG.md`. `python tools/release.py check vX.Y.Z` stops the release unless they and the tag agree.
- `.github/workflows/release.yml` runs on the tag: the tests, the package, the two install scripts with the version
  filled in, `SHA256SUMS`, a try of the install line on Linux, macOS and Windows, and a draft GitHub Release. Publish
  the draft by hand; never make a release by hand, which would lack the files the install line needs.
- The `CHANGELOG.md` entry (what changed and why, the defects fixed, the tests added, and *Not yet done*) becomes the
  release notes. Update `docs/MANUAL.md` where behaviour changed and `docs/API.md` for new routes.
- Update the README as the next section says.

## The README

**Who it is for.** Researchers who use ENLENS in their work, and people who read or review that work. Most do not
program, so write plainly: say what each thing does for the researcher, not how it works.

**What it is for.** It is the front door: what ENLENS is, how to install and update it, what is new, how to cite it,
and where to go next. It is the only place for nothing: every fact in it also lives in the manual, the changelog or
this file, and the README links there instead of copying. Aim for about 100 lines. ENLENS's README is its own: Margin's
sync (`tools/sync_enlens.py` in Margin) keeps Margin's README and leaves ENLENS's alone.

**Its sections, in this order:**

1. **Title and one line**: what ENLENS is, in one sentence, then a screenshot of the main screen (the Overview, light
   theme, desktop width: `docs/images/overview.png`).
2. **Install**: the one-line install for macOS/Linux and for Windows, then *Set up Claude* on the first screen; a few
   numbered steps a non-programmer can follow.
3. **Update**: `enlens update`, or the install line again; quit and reopen ENLENS. Equally short.
4. **What ENLENS does**: about six bullets, one sentence each, each linking to its section of the manual: exploring
   the documents; checking a statement, with quotes checked against the source; reviewing the AI's judgements like a
   co-coder's, and the Excel download; the bibliography; a model on your own computer, or none (`--local-only`); the
   SDG and value chain pack.
5. **New in 0.X**: three to five bullets for the current minor series. Each says what the change does for the
   researcher, and whether it **can change results** (a new parser, prompt, model or rule). A bullet that needs more
   than two lines belongs in the manual.
6. **How to cite ENLENS**: the `CITATION.cff` entry and the release's DOI. Until those exist (J4 item 1), the
   repository's address and the version the reader used.
7. **Privacy and your documents**: one paragraph on what stays on the computer, what goes to Anthropic and when, and
   how to turn that off. It links to the privacy statement (J4), or to section 8 of the manual until that exists.
8. **Documentation**: links to the manual, the methods document (J4, once it exists), the API, `docs/MODEL_CHOICE.md`
   and the add-on guides.
9. **For developers**: one line linking to this file.

**At each release:**

- Update only **New in 0.X**. When a new minor series starts, replace its bullets: the old ones are in the changelog.
  (Once J1 is built, `release.py prepare` writes this section from the changelog.)
- Touch the other sections only when the release changed what they describe. Take a new screenshot when the Overview
  looks different (`tools/dev_server.py --corpus social --claude-code`, Playwright at 1280 × 800).
- Before committing, check that every link resolves (files and headings), that each *New in* bullet matches its
  changelog entry, and that the README is still about 100 lines. (J2 item 6 makes CI check this later.)
