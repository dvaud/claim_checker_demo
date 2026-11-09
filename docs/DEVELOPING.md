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
`pdfminer`, `dev`) are in [the manual](manual/install.md#from-a-git-copy-developers).

ENLENS is installed in three ways (`installation.py`): a git copy, the one-line install (`install/install.sh` and
`install/install.ps1`: uv and the release's wheel) and, later, packages. A release has to work for all three: a normal
commit on `main` that never needs a new venv, and a published GitHub Release with its files.

## Tests

```bash
pip install -e '.[dev,fast,connector,anthropic,pdfminer,ocr]'   # every extra, so no test is skipped for a missing one
python -m pytest -q -rs
```

`.github/workflows/tests.yml` runs the suite on every push to `main` and every pull request, on Linux (Python 3.10
and 3.13), macOS and Windows (0.15; required since 0.15.7, when the suite first passed on all three), with the extras `dev,connector,fast,pdfminer` and a quick `ruff` check for syntax
errors and undefined names; the release workflow runs it again on the tag. Neither installs `anthropic` or the OCR
extra, so the tests that need them are skipped there: run the whole suite on your own computer before a release. Tests never touch a real Claude Code, uv or
the network: `tests/conftest.py` points `ENLENS_CLAUDE` nowhere, gives every test its own `ENLENS_HOME` and reads
added documents one at a time (`ENLENS_READ_WORKERS=1`, so a stand-in a test puts in this process is what reading
sees; `tests/test_0_16_0_speed.py` reads at once on purpose);
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
| `--reading` | a project *Reading* with the PDFs of known text of `enlens measure`, one of them read by the reader of 0.14 and with a check on it (0.15: the reading view, *Read with the new reader*) |
| `--zotero`, `--update`, `--ollama`, `--low-memory` | a stand-in Zotero (0.13), a stand-in newer version (0.13.1; `--update windows`, `windows-fails`: the hand-over of Windows, 0.15.4), a local model still to get (0.13.7), too little memory for it (0.13.11) |

`--home FOLDER` keeps its data apart and `--port` sets the port. Look at every page you touched in the light and dark
themes and at 390 px wide.

## Layout

| Module | Role |
| --- | --- |
| `claimcheck.py` | Hypotheses: decomposition, checks, statuses, a person's judgements, who says what, rounds, re-reads, second opinions, new documents, the evidence map, calibration, batches, history, Excel |
| `search.py`, `embed.py`, `retrieve.py` | Hybrid ranking over the keyword index, local embeddings; BM25 (inverted index, in memory) |
| `searchindex.py` | The keyword index made from each document's words kept on disk (0.16, H2): `cache/search.sqlite`, one row per document, used again while its passages and `textutil.py` are unchanged; the index in memory is one snapshot (`PackedBM25`, `retrieve.BM25`'s ranking number for number), without passage text (read when needed). `connect_cache` opens a cache file and makes a damaged one again |
| `frameworks.py`, `taxonomy.py` | Optional codebooks (SDG targets bundled, custom CSVs) |
| `codebooks.py` | Your own codebook (0.16, K1): made fresh, from themes, as a copy or from a CSV, kept with one project or with all; the editor's state, saved with a side file `<name>.json` (a stable id for each code, renames, merges and rewordings, removed codes, where each example quote was found); labels follow renames and merges (`follow`, in every project using it, when opened) and wait under removed codes; `stale` and `relabel_passages` for a code reworded after the AI labelled with it; `try_codes` (the keyword pass, no AI); each saved change is a version (`history.py`) and a research log entry |
| `codenames.py` | Short code names for a codebook made from themes (0.16.1), without AI: words of each theme's name, the shortest that is not too generic for the documents (most passages using it in the theme), a ladder from less to more specific, no two themes alike |
| `researchlog.py` | The research log (0.16, F4): `record` writes an entry in the transaction of the change it records (so it is undone with it); the entries a person adds, their *why*; `entries`, `table` and `markdown` read it; `merge` brings in a colleague's entries (`sync.py`) |
| `notes.py` | Notes and highlights (0.16, F2): a span of a document's text with its words as `quote`, checked as every quote is and found again by its words when the text is read again (`move`, or `lost`); search and downloads; `use_as_evidence` (the passage holding the words becomes an excerpt the person judged); `merge` for a colleague's notes |
| `history.py` | Earlier versions (0.16, F5): the state of a set of themes, a person's judgements in a check or a codebook kept before each change (`snapshot`); `compare` says what differs in words, `restore` puts it back after keeping the present state; the `versions` table is not merged by `sync.py`; `codebooks.py` keeps its own beside its file |
| `llm.py` | Ollama, OpenAI-compatible local servers (LM Studio, llama.cpp…), server detection, Claude API, offline baseline |
| `tasks.py`, `schema.py`, `prompts.py` | Model tasks, validation with the quote check, versioned prompts |
| `access.py` | Who may read each document with AI (0.11): the settings, the guard on every task, which model reads what, the ledger of what was sent to Claude, the cap |
| `ingest.py`, `textutil.py`, `store.py` | Documents and passages with page offsets, layout (paragraphs, headings), local OCR, text normalisation, the workspace database; `ingest.read_document` reads a file with any reader and stores nothing |
| `readworker.py` | A reading process (0.16, H3): `ingest` reads up to three added files at once, each in one of these (the same Python with the app's `sys.path`, started through `procs.no_window()`), and stores them in the order of the files; tasks and answers are length-prefixed pickles on its standard input and output; `ingest._read_whole` is the one reading both use. They end with the app (`ingest.end_reading_processes`, at exit and before a restart) and by themselves when it is gone |
| `reader.py` | The reader of 0.15 (reader 2; `read_blocks(raw, version=3)` adds `reader3.py`): lines with their boxes (pdfminer), page furniture, columns and reading order, blocks and their kinds, tables, text repair, passages that never mix what is read with what is left out, the reading report, a person's Restore and Leave out and *Text starts / ends here* (`choose_inclusion`, `apply_choices`) |
| `reader3.py` | What reader 3 (0.15.1) adds, on the text alone: running heads and page numbers by repetition in lines without positions, text printed twice, paragraphs in hard-wrapped text, headings where a file marks none, a book's contents, front and end matter and index, ligatures broken by a space, words run together, and the report's warnings |
| `reread.py` | *Read with the new reader* (0.15): a document of a project read again by the new reader, its results moved by their quotes, all or nothing |
| `measure.py`, `pdfmake.py` | `enlens measure` (0.15): how well each reader reads PDFs of known text (made by `pdfmake`, a small PDF writer), quotes that still find their place, timings, determinism; the validation report of each release |
| `bundle.py` | A whole project as one zip (export and import); every project and the settings, to move to another computer (0.10) |
| `sync.py` | Shared projects (0.14): a colleague's project zip merged into your copy (newer versions, sync clashes, removed items, the stricter AI setting) |
| `people.py` | Shared projects (0.14): who you are to colleagues, each person's own judgements and reviews, and how often two people agreed |
| `installation.py`, `update.py` | How this copy was installed (git copy, the one-line install, a package, pip) and `enlens post-install`; `enlens update` for each (0.10) |
| `handover.py` | The update on Windows (0.15.4): run outside ENLENS's own folder with the Python uv installed, it waits for the app to quit, installs the new version, starts the app again and leaves what happened in `updates/result.json`. Standard library only (a test holds it to that); `ENLENS_RELEASE_API` points the update at a stand-in for GitHub (the release's Windows test) |
| `procs.py` | `no_window()`: every program the package starts gets no console window on Windows (0.15.3; a test holds every `subprocess` call to it, or to a `# console: …` reason) |
| `home.py` | Settings, projects, the optional cloud key |
| `gui/` | The local app: `server.py` (the server, `App`, `Handler`, the routes), `api_documents.py`, `api_explore.py`, `api_checks.py`, `api_setup.py` and `api_record.py` (the endpoints of `Handler`: documents and reading, search and profiles, checks and the queue, settings and setup, the research log, notes, history and codebooks), `app_library.py` and `app_queue.py` (bibliography and search, the task queue: parts of `App`), `api_common.py` (errors, jobs, shared helpers), `static/` (the page; `features.js` describes each feature once), `progress.py`, `launcher.py` (the ENLENS icon), `icons/` (its picture, drawn by `tools/make_icons.py`) |
| `concordance.py` | Search (0.7): concordance lines, modes, other forms, collocates |
| `profile.py` | Codebook profiles: the keyword and meaning pass, the AI's labels, grids, a person's labels |
| `terms.py` | The glossary (C-value terms, abbreviations), concepts and their links, key terms. 0.16 (H3): each document's reading kept in `cache/glossary.sqlite` and used again while its text and the joiner's decisions for it are unchanged; only changed mentions are written; the result is a build from scratch's, mention for mention (`tests/test_0_16_0_recompute.py`) |
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
`install/Install-ENLENS-Windows.cmd` is the head of the Windows file to double-click (0.14.5: `tools/release.py` puts
`install.ps1` below it, so keep both plain ASCII, and no `#>` in the head, which PowerShell reads as one comment);
`.github/workflows/release.yml` turns a tag `vX.Y.Z` into a draft GitHub Release with `tools/release.py` (below);
`tools/pdf_to_text.py` turns a folder of PDFs into page-preserving text files; `tools/arxiv_truth.py` downloads a fixed
list of open-access arXiv papers with the text of their LaTeX source, for `enlens measure --folder`; `tools/eval_second_pass.py` measures the
second sorting pass on the pilot; `tools/make_icons.py` draws the icon files; `tools/manual_screenshots.py` takes the
manual's pictures (*The manual*, below). The green hydrogen pilot (workspace,
report, run notes) is in `pilot/`. The app's HTTP API is in [API.md](API.md); building an app on ENLENS without
editing its files is in [EXTENDING.md](EXTENDING.md).

## Releases

- The version stands in `pyproject.toml`, `src/enlens_claims/__init__.py` and the top `## X.Y.Z` entry of
  `CHANGELOG.md`. `python tools/release.py check vX.Y.Z` stops the release unless they and the tag agree.
- `.github/workflows/release.yml` runs on the tag: the tests, the package, the two install scripts with the version
  filled in, the same as files to double-click (`Install-ENLENS-Windows.cmd`, `Install-ENLENS-macOS.zip`; 0.14.5),
  `SHA256SUMS`, a try of the install line on Linux, macOS and Windows and of the files on Windows and macOS, and a
  draft GitHub Release. Publish
  the draft by hand; never make a release by hand, which would lack the files the install line needs.
- The `CHANGELOG.md` entry (what changed and why, the defects fixed, the tests added, and *Not yet done*) becomes the
  release notes. Update the manual where behaviour changed (*The manual*, below) and `docs/API.md` for new routes.
- Each release updates `gui/static/whats-new.md` (`# X.Y.Z: Title`, `*subtitle*`, then a few extremely short points,
  one `-` line each). The app shows it once, after an update, when its version matches the running one.
- Update the README and the manual as the last two sections say.
- **Release candidates (0.15).** The roadmap gives every minor release a release candidate, in use for at least a
  week: `0.15.0rc1` in `pyproject.toml`, `__init__.py` and a `## 0.15.0rc1` changelog entry, tagged `v0.15.0rc1`.
  The workflow drafts it as a GitHub pre-release, which the install line and the app's *Update* never take (GitHub's
  *latest* is the latest full release); its notes give install lines with its own files. A copy of a candidate is
  offered the release when it comes (`update.version_tuple` puts `0.15.0rc1` after every earlier release and before
  `0.15.0`). A git copy on `main` gets a candidate's commit as it gets every commit. When the release comes, its
  changelog entry replaces the candidates' entries.
- **Withdrawn numbers.** `update.WITHDRAWN` counts a running copy of a withdrawn number as older only while this
  version is below it. It is empty since 0.15.1: 0.14.0, 0.15.0 and 0.15.1, withdrawn in 0.13.6, were each released
  for real later and left it then.
- **The validation report (0.15).** The release workflow runs `enlens measure --report` and attaches
  `validation-report.md` to the release: how well each reader reads the documents of known text, and that reading is
  the same twice. The half that needs AI comes with 0.16.

## Rolling back a release

A release turns out bad (it loses something, or will not start):

1. Mark it as a pre-release on GitHub: `gh release edit vX.Y.Z --prerelease`. GitHub's *latest* is then the release
   before it, so the one-line install (`…/releases/latest/download/install.sh`) installs that one again, and the
   stable *Update* button of everyone who has not yet updated skips the bad one. Nobody is moved backwards: people
   who already have it keep it until the fix comes. (People on *Try new versions early* still see it, as they see
   any pre-release.)
2. Write the fix as a patch release (`X.Y.Z+1`), with its own changelog entry that says what went wrong. It becomes
   the latest release as soon as it is published, and everyone is offered it.
3. Never delete a published release or its tag: copies, notes and links point to them. Marking is enough.

Someone who wants to go back by hand uses the install line of the earlier release from its release page, which has
its own files: `https://github.com/dvaud/claim_checker_demo/releases/download/vX.Y.Z/install.sh` (or `install.ps1` on
Windows). The projects in `~/enlens` are not touched by an install, so going back loses nothing; a project shared with
colleagues can show sync clashes after going back (both versions are kept).

## Changes that alter results

Researchers compare results across versions, so a change that can give other answers for the same documents is
recorded and announced:

- **The reader.** `ingest.READER` numbers the way a file becomes text and passages: 1 is `ingest._build_document_1`
  (0.5 to 0.14), 2 is `reader.py` (0.15.0), 3 is `reader.py` with `reader3.py` (0.15.1;
  `reader.read_blocks(raw, version=2)` still reads exactly as 0.15.0 did, which a test checks to the byte). A change
  that gives a document other text or passages raises it, and goes
  in a module of its own. Each document records the reader that read it (`documents.reader`), and documents already
  in a project are never read again by themselves: only new documents get the new reader, so every quote and
  judgement in the old ones stays where it is, until a person moves one (`reread.py`). Measure a change with
  `enlens measure` before and after.
- **The version on results.** Every AI answer (`results`), run, label, theme run and check records `app_version`.
  A new kind of result records it too, and writes its rows by column name (a positional `INSERT … VALUES` breaks when
  a column is added). `app_version` is never part of a sync fingerprint (`sync._HOW`). 0.14 does not know to leave
  it out: someone who tries a 0.15 candidate on a shared project and goes back to 0.14 gets a sync clash on each check
  and set of themes made with the candidate (both versions are kept, so nothing is lost). Try a candidate on a project
  you do not share.
- **The changelog** lists such a change under *Changes that can alter your results*, and the README's *New in* says
  **can change results**. A change of that kind is announced in the release notes one minor release ahead.

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
6. **How to cite ENLENS**: the repository's address and the version the reader used. (ENLENS has no `CITATION.cff`
   or DOI, by choice.)
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
- Before committing, check that every link resolves (files and headings: `tests/test_manual.py` checks the README's
  relative links), that each *New in* bullet matches its changelog entry, and that the README is still about 100
  lines. (J2 item 6 makes CI check the rest later.)

## The manual

**Who it is for.** The researchers who use ENLENS, most of whom do not program; then whoever installs it for others;
last, people who use the command line or the SDG pack. A reader comes with one question ("how do I check this?",
"does Claude read my interviews?") and has a few minutes, not an hour: the manual is built so they find the page and
can stop reading once they have their answer.

**Its shape.** A hub and short pages, not one long file:

- **`docs/MANUAL.md`, the hub.** What ENLENS is, a diagram of how it fits together, a five-minute start, the table of
  pages (grouped: *Get going*, *Your work*, *The AI and your privacy*, *Reference*, *SDG pack*) and *I want to…* (a
  task, and the page and heading that answers it). It holds no fact of its own beyond the five-minute start, and stays
  under 1,200 words.
- **`docs/manual/<topic>.md`, one page per task or question.** Each stays under 5,000 words (a test holds both
  limits); a page that grows past it is split, and the new page goes into the hub's table. Every fact lives on one
  page; other pages link to it rather than repeat it.

| Page | Covers |
| --- | --- |
| `install.md` | The one-line install, the files to double-click, Tesseract, a git copy, updating, the icon |
| `first-steps.md` | The first screen (*Set up Claude*, a project, documents), the sidebar and the rest of the app's frame |
| `check.md` | Writing and checking a hypothesis, what a check does, the answers, parts, *Check several* |
| `review.md` | The result page, excerpt cards and their actions, other AI models, downloads, *Results*, the map |
| `explore.md` | Search, Profile, Concepts, Themes, a document's panels, Quick look, FlexiConc |
| `reading.md` | The readers, the reading view, *Read with the new reader*, `enlens measure` |
| `bibliography.md` | Zotero and exported bibliographies, the four lists, matching |
| `together.md` | Shared projects, sync clashes, project zips, moving to another computer |
| `privacy.md` | What leaves the computer, who may read each document with AI, enforcement, what Claude read |
| `claude-code.md` | Setting up and starting Claude Code, speed and helpers, the queue; the connector for a Claude chat |
| `local-models.md` | Getting, tuning and testing a model on this computer |
| `models.md` | The model of each kind of task and of each Claude plan; what every answer records; results across versions |
| `settings.md` | The five tabs, release candidates, reporting a problem, installing for others |
| `glossary.md`, `troubleshooting.md` | Look-up pages: the words of the app; problems by topic, and the limits |
| `command-line.md` | `enlens-gui`, `enlens` and the project's database |
| `sdg-pack.md` | The SDG pack: its pipeline, report, configuration and tables |

**The current version only.** The manual says what ENLENS does now; the changelog is the history. No version after a
feature ("Themes (0.7)") and no "before, it …": when behaviour changes, the page is rewritten, not annotated. A
version stays only where the reader's next step depends on it: a fix that needs a given version ("installers before
0.15.2 misread …"), what happens to documents or results made before a version, or a promise ("from 0.16 on").

**How a page is built**, in this order (the test checks the first three):

1. The way back to the hub: `[Manual](../MANUAL.md) › <title>` on the first line.
2. One `# Title`, in plain words.
3. `> **In short**` with three bullets: what the page lets you do, and the one or two things a reader must not miss.
   (The look-up pages, `glossary.md` and `troubleshooting.md`, have none.)
4. Sections in the order a reader does things. Headings are plain words without versions: they are the anchors that
   the hub, the README and other pages link to, so renaming one means updating its links (the test finds them).
5. On the pages of the main path, a last line `Next: [<page> →](<page>.md)`, in the order of the hub's table.

**Writing it.** Plain words that say what a thing does for the researcher, in UK spelling. Labels of the app in
italics, exactly as the app writes them (*Set up Claude*); a word being defined in bold. Paragraphs of at most about
five lines, wrapped at 120 characters. Then pick the form that fits what is said:

| What is said | Form |
| --- | --- |
| A procedure | Numbered steps |
| Things a reader compares or looks up (buttons and what they do, settings, options, problems and fixes) | A table |
| A flow with branches, or between people or programs | A Mermaid diagram: at most about seven boxes, no colours of its own (GitHub draws it in the light and dark themes) |
| Something a reader must not miss (privacy, losing work) | A callout, `> [!NOTE]`, `[!TIP]`, `[!IMPORTANT]`, `[!WARNING]` or `[!CAUTION]`: at most two a page |
| Exact rules, technical options, lists for specialists | Folded: `<details><summary>…</summary>` with a blank line after `<summary>` (never a step a reader needs) |
| Reasons and context | Short prose |

**Pictures.** The pictures are in `docs/images/manual/` and are made by `tools/manual_screenshots.py` from the dev
server, never by hand, so they can always be made again. Each is embedded as
`<img src="../images/manual/NAME.png" alt="what it shows" width="800">`. The hub's picture is the README's
(`docs/images/overview.png`). When a release changes a screen that a picture shows, run the script and look at every
picture it made:

```bash
~/.local/share/uv/tools/playwright/bin/python -I tools/manual_screenshots.py [--only result map]
```

(Any Python with Playwright and Chromium will do; the dev server itself runs in the project's `.venv`.) A new picture
is a line in the script's `SHOTS` and a function `shot_<name>`. `result.png` carries numbered marks, and the table
under it in `review.md` follows their order. The test fails for a picture that is missing, one that no page shows, or
one over 300 KB. Margin's sync brings the pages and pictures across; run the script there too, so its pictures show
its own name.

**At each release:**

- Find the page in the table above (or `grep -rn` in `docs/manual`), and change it where behaviour changed. A new
  feature goes on the page of its task, as a section; a new page only for a new task, added to the hub's table (and to
  *I want to…* when readers will look for it).
- Delete what no longer holds; the changelog keeps it.
- Retake the pictures of screens the release changed.
- `python -m pytest tests/test_manual.py`: every page reached from the hub, every link and anchor of the manual, the
  README and this file, the pictures, the shape and length of each page.
- A change to the manual alone is not a release: commit it on `main`, and the next release names it in its changelog
  entry (under *Documentation*).
