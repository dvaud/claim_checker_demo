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
and reinstalls only when its requirements changed or a new release tag came (the version is made from the git tag, so
the clone must keep its tags: a shallow `--depth 1` clone has none and shows version 0.0.0). Then open ENLENS from its icon: an older version still running is
quit and the new one started (0.10.2), and if something still runs in it, the page says to quit and reopen. Run it as
`~/enlens-app/.venv/bin/enlens update` if the venv is not active. The optional extras (`fast`, `anthropic`, `ocr`,
`pdfminer`, `dev`) are in [the manual](manual/install.md#from-a-git-copy-developers).

ENLENS is installed in three ways (`installation.py`): a git copy, the one-line install (`install/install.sh` and
`install/install.ps1`: uv and the release's wheel) and, later, packages. A release has to work for all three: a normal
commit on `main` that never needs a new venv, and a published GitHub Release with its files.

## Tests

```bash
pip install -e '.[dev,fast,connector,anthropic,pdfminer,ocr]'   # every extra, so no test is skipped for a missing one
python -m pytest -q --testmon tests/test_<what you changed>.py   # while working: the tests your change affects
python -m pytest -q -rs -n 4 --durations=15                      # the whole suite, alone on the computer, before a release
```

**CI is where the whole suite runs** (2026-11-12). `.github/workflows/tests.yml` runs it on every push to `main` and
every pull request, on Linux (Python 3.10, and 3.13 with every optional extra: the Claude API, OCR with Tesseract,
PyYAML), macOS and Windows (0.15; required since 0.15.7), with a quick `ruff` check for syntax errors and undefined
names. Each machine runs the tests side by side (`-n auto`), each test with a 10-minute limit (`--timeout=600`: a test
that hangs fails with its stack), and Windows, the slowest, is split over four machines (`ENLENS_TEST_SHARD=k/4`, a
split made in `tests/conftest.py`), so a run takes about 8 minutes. The 25 slowest tests of each machine are listed at
the end of its log: read them before guessing why a run got slower. Side by side, the heaviest tests take several
times longer than alone, so a test that waits for a job, a thread or a process to end waits for that end, not for a
fixed time. The jobs other than Linux 3.13 install only `dev,connector,fast,pdfminer`, so a test that needs another
extra must skip without it (`pytest.importorskip`). `.github/workflows/nightly.yml` runs the random runs (below) with
30 seeds each night. The release workflow does not run the suite again: it takes the result of the Tests run on the
tagged commit (*Releases*).

**On a laptop, run little.** A full run once wrote ~25 GB and, three at a time, ran a 16 GB Mac out of memory. So:
- while working, run the tests of what you changed; `pytest-testmon` (in the `dev` extra) records which tests touch
  which code, and `--testmon` reruns only those (its first run is a full one; its data is `.testmondata` in the
  copy). pytest's cache is on, one per git copy: `--lf` reruns the last failures and `--ff` runs them first;
- a run of the whole suite (no test file named, no `-m`) leaves out the tests marked `heavy`; CI runs them, and
  `ENLENS_ALL_TESTS=1`, or naming their file, runs them here. Mark a test `heavy` when it writes hundreds of MB or
  runs for many seconds;
- the seeded random runs of the 0.18 roles (`random`: `test_roles_random.py`, `test_owner_random.py`)
  run 2 seeds here, 10 in CI (`CI` set) and 30 with `ENLENS_LONG_RANDOM=1`;
- one test run at a time on the computer, at most `-n 4`; the whole suite only once, after merging and before a
  release;
- a passing test's `tmp_path` is removed when it ends (`tmp_path_retention_policy = "failed"`); a failing one's stays;
- tests use SQLite without forced flushes (`ENLENS_TEST_FAST_SQLITE`, set by `tests/conftest.py`); a test that needs
  the real flushes and journal is marked `durable`;
- `ENLENS_TEST_TMP=<folder>`, or a volume named `ENLENS-TESTS`, puts every test file there instead of the system's
  temporary folder. On a Mac a 1 GB RAM disk stops test runs wearing the SSD:
  `diskutil erasevolume APFS ENLENS-TESTS $(hdiutil attach -nomount ram://2097152)`; it takes that much memory until
  ejected (`diskutil eject ENLENS-TESTS`), so make one only when memory is free.

**How much a test writes.** `tools/writemeter.py`, loaded by `tests/conftest.py`, measures the bytes each test writes
(macOS, Linux and Windows). A test not marked `heavy` that writes more than `ENLENS_WRITE_BUDGET_MB` (default 200)
warns (`WriteBudgetWarning`), so a new heavy test is caught the day it is added; `ENLENS_WRITES=15` lists the 15 tests
that wrote the most at the end of a run, `ENLENS_WRITES_JSON=<file>` keeps every test's number, and `--durations=15`
the slowest.

Tests never touch a real Claude Code, uv or the network: `tests/conftest.py` points `ENLENS_CLAUDE` nowhere, gives
every test its own `ENLENS_HOME` (and keeps secrets in files there, `ENLENS_KEYCHAIN=file`, never the computer's
keychain) and reads added documents one at a time (`ENLENS_READ_WORKERS=1`, so a stand-in a test puts in this process
is what reading sees; `tests/test_speed.py` reads at once on purpose); `tests/fake_claude_cli.py`,
`tests/fake_claude_installer.py`, `tests/fake_servers.py` and `tests/fake_zotero.py` stand in for the real programs. A
release's tests go in a new file `tests/test_<X>_<Y>_<Z>_<topic>.py`; older files keep their names.
[docs/USER_TESTS.md](USER_TESTS.md) has the first-time user tests behind the app (0.5.1 to 0.7.0).

## Trying the app

`tools/dev_server.py` runs the app against fake local models, for interface work, with a Demo project. Open the
`link:` it prints (0.17.2: the page carries no token; the bare address says how to open ENLENS):

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

`--home FOLDER` keeps its data apart and `--port` sets the port. The dev server stops by itself after 60 minutes
(`--max-minutes`, 0 = never) and when the Claude Code process that started it ends (`--watch-pid` names another), so a
forgotten one does not keep running. Look at every page you touched in the light and dark
themes and at 390 px wide.

## Layout

| Module | Role |
| --- | --- |
| `claimcheck.py` | Hypotheses: decomposition, creating checks, rounds, the local parts, check runs, the queue's checks, chat checks, new documents read, second opinions, history, batches. It re-exports every name of the four modules below, so `claimcheck.<name>` keeps working for add-ons and imports (0.18.1, H6) |
| `verdicts.py` | The statuses and what a person's judgement does to a verification row: `effective`, `claim_status`, `balance`, `who_says_what`, `aggregate`. Pure: imports nothing from `claimcheck` |
| `check_results.py` | Reading a check's results: `locate`, `result`, `hypothesis_result`, the models used, new documents |
| `check_exports.py` | The evidence map, calibration, spreadsheet rows, `summary_table`, `write_xlsx` |
| `judgements.py` | A person's judgement, re-reading an excerpt, removing a hypothesis or claim, the note. `check_results.py`, `check_exports.py` and `judgements.py` reach what stays in `claimcheck.py` as `_cc.name` at call time (patching `claimcheck.<name>` still works) |
| `search.py`, `embed.py`, `retrieve.py` | Hybrid ranking over the keyword index, local embeddings; BM25 (inverted index, in memory) |
| `searchindex.py` | The keyword index made from each document's words kept on disk (0.16, H2): `cache/search.sqlite`, one row per document, used again while its passages and `textutil.py` are unchanged; the index in memory is one snapshot (`PackedBM25`, `retrieve.BM25`'s ranking number for number), without passage text (read when needed). `connect_cache` opens a cache file and makes a damaged one again |
| `frameworks.py`, `taxonomy.py` | Optional codebooks (SDG targets bundled, custom CSVs) |
| `codebooks.py` | Your own codebook (0.16, K1): made fresh, from themes, as a copy or from a CSV, kept with one project or with all; the editor's state, saved with a side file `<name>.json` (a stable id for each code, renames, merges and rewordings, removed codes, where each example quote was found); labels follow renames and merges (`follow`, in every project using it, when opened) and wait under removed codes; `stale` and `relabel_passages` for a code reworded after the AI labelled with it; `try_codes` (the keyword pass, no AI); each saved change is a version (`history.py`) and a research log entry |
| `codenames.py` | Short code names for a codebook made from themes (0.16.1), without AI: words of each theme's name, the shortest that is not too generic for the documents (most passages using it in the theme), a ladder from less to more specific, no two themes alike |
| `researchlog.py` | The research log (0.16, F4): `record` writes an entry in the transaction of the change it records (so it is undone with it); the entries a person adds, their *why*; `entries`, `table` and `markdown` read it; `merge` brings in a colleague's entries (`sync.py`) |
| `keychain.py` | Secrets kept in the system's keychain (0.18.0rc2, L6): a storage space's keys, the project's keys, each copy's own keys; macOS `security` (the secret never on a command line), Windows Credential Manager, `secret-tool`, or a file in ENLENS's folder readable by this user only (`ENLENS_KEYCHAIN=file`: tests and the dev server always) |
| `notes.py` | Notes and highlights (0.16, F2): a span of a document's text with its words as `quote`, checked as every quote is and found again by its words when the text is read again (`move`, which also sets the page, or `lost`; listing notes writes only when a note's place changed); search and downloads; `use_as_evidence` (the passage holding the words becomes an excerpt the person judged); `merge` for a colleague's notes |
| `history.py` | Earlier versions (0.16, F5): the state of a set of themes, a person's judgements in a check or a codebook kept before each change (`snapshot`); `compare` says what differs in words, `restore` puts it back after keeping the present state; the `versions` table is not merged by `sync.py`; `codebooks.py` keeps its own beside its file |
| `llm.py` | Ollama, OpenAI-compatible local servers (LM Studio, llama.cpp…), server detection, Claude API, offline baseline |
| `tasks.py`, `schema.py`, `prompts.py` | Model tasks, validation with the quote check, versioned prompts |
| `access.py` | Who may read each document with AI (0.11): the settings, the guard on every task, which model reads what, the ledger of what was sent to Claude, the cap |
| `ingest.py`, `textutil.py`, `store.py` | Documents and passages with page offsets, layout (paragraphs, headings), local OCR, text normalisation, the workspace database; `ingest.read_document` reads a file with any reader and stores nothing |
| `readworker.py` | A reading process (0.16, H3): `ingest` reads up to three added files at once, each in one of these (the same Python with the app's `sys.path`, started through `procs.no_window()`), and stores them in the order of the files; tasks and answers are length-prefixed pickles on its standard input and output; `ingest._read_whole` is the one reading both use. They end with the app (`ingest.end_reading_processes`, at exit and before a restart) and by themselves when it is gone |
| `reader.py` | The reader of 0.15 (reader 2; `read_blocks(raw, version=3)` adds `reader3.py`): lines with their boxes (pdfminer), page furniture, columns and reading order, blocks and their kinds, tables, text repair, passages that never mix what is read with what is left out, the reading report, a person's Restore and Leave out and *Text starts / ends here* (`choose_inclusion`, `apply_choices`) |
| `reader3.py` | What reader 3 (0.15.1) adds, on the text alone: running heads and page numbers by repetition in lines without positions, text printed twice, paragraphs in hard-wrapped text, headings where a file marks none, a book's contents, front and end matter and index, ligatures broken by a space, words run together, and the report's warnings |
| `reader4.py` | What reader 4 (0.17.2) adds: a text file with one paragraph per line read paragraph by paragraph (its Word changes, content controls and nested tables, are in `ingest._read_docx`) |
| `reread.py` | *Read with the new reader* (0.15): a document of a project read again by the new reader, its results moved by their quotes, all or nothing |
| `measure.py`, `pdfmake.py` | `enlens measure` (0.15): how well each reader reads PDFs of known text (made by `pdfmake`, a small PDF writer), quotes that still find their place, timings, determinism; the validation report of each release |
| `bundle.py` | A whole project as one zip (export and import); every project and the settings, to move to another computer (0.10) |
| `sync/` | Shared projects (0.14): a colleague's project zip merged into your copy (newer versions, sync clashes, removed items, the stricter AI setting). A package since 0.17.0, every name importable from `sync` as before: `common.py` (tables and columns treated alike, `text_fp`), `fingerprints.py` (the units compared and how a newer version is told), `merge.py` (`_Merge`, the rules step by step), `codebook_merge.py` (its part for codebooks: merged code by code when both changed one), `readings.py` (a colleague's other reading of a document placed on yours), `share_merge.py` (who shared what, by the owner's word), `owner_merge.py` (0.17.0, L2: who the project's owner is, proposals, decisions and the documents as accepted, each by its own rule), `formats.py` (the format of what is exchanged), `report.py` (the report in words, the overview), `__init__.py` (the exchange as a zip), `folder.py` (0.17.0, L5: the exchange through a folder the team shares: each copy writes the items its person shared as numbered bundles into its own subfolder and brings in the others' through the same merge), `changes.py` (what changed since the folder's last round: triggers count each table's and each item's changes, so a round looks only at those; this computer's own, never in a zip), and 0.18.0rc2 (L6) a storage space of the team's own: `space.py` (set-up, invites and joining, the roster of members and its keeper, removal and new keys, moving the team; a round brings the space into a copy of it on this computer, runs `folder.py`'s round there, and sends this copy's part back), `seal.py` (each file encrypted with the project's key and signed by its writer, with `cryptography`), `storage.py` (a storage: list, read, write whole, remove; a folder, or S3 with Signature V4 over `urllib`), `b2.py` and `r2.py` (Backblaze's and Cloudflare's own interfaces, for keys and buckets), `_web.py` (their one HTTP layer, with retries) |
| `sharing.py` | Private until shared (0.17.0, L1): the items a person makes (checks, sets of themes, codebooks, notes, own log entries, links), their state (`shares`: private, shared, withdrawn; only the owner decides), *Share* and *Unshare*, the listing, `rows_of` (the one definition of the rows an item covers) and `ProjectRows` (the project's rows that are no one's item), and `strip`, which takes everything not shared out of a copy of the database for a colleague's zip |
| `ownership.py` | One owner, Co-owners and Members (0.17.0, L2; roles and pins after it): who the owner is. Each copy *pins* the record it follows for each place in the chain (`chain` reads only the pins; no clock decides): a hand-over by the owner it follows is pinned at once, anything else (another first owner, a take-over) is a question to its person (`owner_questions`, `follow_owner`, `keep_owner`). Roles (`roles`, `role_of`, `may_write`, `set_role`, `set_same_as`: Owner and Co-owners write the project's documents at once, Members propose). `canon` (the documents as the project holds them) is merged part by part (`state`, `read`, `ai`, `blocks`) by what each writer *knew* (`hist_json`), never by the highest number; parts changed at the same time are kept safe and listed (`clashes`). A proposal answered both ways counts for neither answer (`_decisions`, `knew_json`). `settle` is the one look a copy takes at itself: it writes proposals, or the project's rows for a writer, and follows the rest. A file never loosens an AI setting here (`hold_loosening`, `offers`, `answer_loosening`), never changes the owner, never acts under this copy's own id (`sync_refused`, `take_back`) and never destroys a document for good (`removed.py`: an archive per document, 30 days). Files are still unsigned: those four rules are what stands where a signature would. `adopt` (a copy made from a colleague's zip), the moves of a new reading, `view` (what the Team tab and the Documents page show). Rows of a third person arrive "via" the sender (`sync_via`, `sync/merge.py`) |
| `people.py` | Shared projects (0.14): who you are to colleagues, each person's own judgements and reviews, and how often two people agreed |
| `installation.py`, `update.py` | How this copy was installed (git copy, the one-line install, a package, pip) and `enlens post-install`; `enlens update` for each (0.10) |
| `handover.py` | The update on Windows (0.15.4): run outside ENLENS's own folder with the Python uv installed, it waits for the app to quit, installs the new version, starts the app again and leaves what happened in `updates/result.json`. Standard library only (a test holds it to that); `ENLENS_RELEASE_API` points the update at a stand-in for GitHub (the release's Windows test) |
| `procs.py` | `no_window()`: every program the package starts gets no console window on Windows (0.15.3; a test holds every `subprocess` call to it, or to a `# console: …` reason) |
| `home.py` | Settings, projects, the optional cloud key |
| `gui/static/` (the look) | `tokens.css` (the tokens, light and dark), `app.css` (base elements, the shell, layout utilities), `components.css` (every component, one section each, numbered as in [DESIGN.md](DESIGN.md)), `views.css` (each page's own pieces and their placement), `site.css` (an installation's own look, last); `lib.js` makes each component (`button()`, `link()`, `card()`…), `views/design.js` is the live reference at `#/design`. New CSS goes into its component's section, or into its page's block of `views.css` when only that page has the piece; never a new sheet, never an inline style. [DESIGN.md](DESIGN.md) says which element to use; `tests/test_design.py` keeps its rules |
| `gui/` | The local app: `server.py` (the server, `App`, `Handler`, the routes), `api_documents.py`, `api_explore.py`, `api_checks.py`, `api_setup.py`, `api_record.py`, `api_sharing.py`, `api_folder.py`, `api_poller.py`, `api_owner.py` and `api_space.py` (the endpoints of `Handler`: documents and reading, search and profiles, checks and the queue, settings and setup, the research log, notes, history and codebooks, what is shared, the shared folder, the poller, the owner and the proposals, with the job that makes a new reading the owner accepted, and the storage space), `app_library.py` and `app_queue.py` (bibliography and search, the task queue: parts of `App`), `api_common.py` (errors, jobs and the queue in which a project's jobs wait their turn, shared helpers), `poller.py` (the thread that looks in each project's shared folder every couple of minutes), `static/` (the page; `features.js` describes each feature once), `progress.py`, `launcher.py` (the ENLENS icon), `icons/` (its picture, drawn by `tools/make_icons.py`) |
| `concordance.py` | Search (0.7): concordance lines, modes, other forms, collocates |
| `profile.py` | Codebook profiles: the keyword and meaning pass, the AI's labels, grids, a person's labels |
| `terms.py` | The glossary (C-value terms, abbreviations), concepts and their links, key terms. 0.16 (H3): each document's reading kept in `cache/glossary.sqlite` and used again while its text and the joiner's decisions for it are unchanged; only changed mentions are written; the result is a build from scratch's, mention for mention (`tests/test_recompute.py`). 0.17.2: `term_mentions` is WITHOUT ROWID with one index (`store.PLACES_TABLE`); a document's places are a range of passage ids (`store.passage_range`) and `doc_id` stays empty (kept, with the table's name, for an older ENLENS that opens the file: never rename it or give another table no rowid, as an older ENLENS reads every table it does not know by rowid); the rows are written in key order. A table of the old shape, or a glossary an older ENLENS made, is dropped on opening and the glossary made again; the file is made smaller once (`store._drop_old_places`, `tests/test_db_size.py`) |
| `themes.py` | Themes: spherical k-means (numpy or pure Python: `_kmeans_sparse_np` does the same float operations in the same order as `_kmeans_sparse_py`, which defines the result, so both give the same themes to the last bit), c-TF-IDF names, a person's edits |
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

**Where new CSS goes** (the rules are [DESIGN.md](DESIGN.md), section 9; `tests/test_design.py` holds them):

| What you are adding | Where it goes |
| --- | --- |
| A new look for an existing element (a size, a kind, a state) | A variant of its component: in its section of `components.css`, as an option of its helper in `lib.js` (its class in the `UI` table), on `#/design` (`views/design.js`) and in DESIGN.md's entry, in the same commit |
| A new kind of element no entry fits | A new numbered section in DESIGN.md, the same section in `components.css`, a helper in `lib.js`, a section on `#/design` |
| How one page arranges its pieces (spacing, columns, order) | Its page's block of `views.css` (`/* ==== Search */`), under the page's own class names, which may only place a component: margins, sizes, grid and flex placement, never its colour, font, edge or padding |
| A piece only one page has (the concordance's columns, a result's answer) | The page's block of `views.css`, under the page's own class; when a second page needs it, it moves into `components.css` as a component. A box is never such a piece: a box in a card is `inset()`, a box of its own `card({ sm: true })`, a message `notice()` |
| A colour | A token in `tokens.css`, light and dark, named for its meaning; never a hex value or a theme rule anywhere else |
| A size or weight of type | One of the type scale's tokens (`--fs-*`, `--fw-*`); a new step is a new token |

No release adds a stylesheet, and no page sets a style inline except a value computed at run time (a bar's width).

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

- **One version, from the tag (0.18.1).** The version is typed nowhere in the code: `setuptools-scm` makes it from
  the git tag `vX.Y.Z` (or `vX.Y.ZrcN`) when the package is built, and `enlens_claims.__version__` reads it from the
  installed package (`importlib.metadata`). A commit after a tag is `X.Y.Z.post3` (later than the tag, earlier than the
  next release); a source archive without git is `0.0.0`, which the app treats as older than every release. So every
  build that matters needs the tags: the workflows check out with `fetch-depth: 0`, and a clone made for a build needs
  `git fetch --tags`. The only thing written by hand is the top `## X.Y.Z` entry of `CHANGELOG.md`, which the release
  pull request writes; `python tools/release.py check vX.Y.Z` stops the release unless it and the tag agree, and
  `python tools/release.py assets dist --expect vX.Y.Z` that the wheel carries the tag's version. A git copy reads its
  version from `git describe` (`update.version_in`), and `enlens update` installs it again (`pip install -e`) when a new
  tag comes, so the installed package's version follows.
- `.github/workflows/release.yml` runs on the tag: the package, the two install scripts with the version
  filled in, the same as files to double-click (`Install-ENLENS-Windows.cmd`, `Install-ENLENS-macOS.zip`; 0.14.5),
  `SHA256SUMS`, a try of the install line on Linux, macOS and Windows and of the files on Windows and macOS, and a
  draft GitHub Release. Publish
  the draft by hand; never make a release by hand, which would lack the files the install line needs.
- **The release pull request (0.18.1).** `python tools/release.py prepare X.Y.Z "<title>"` shows what it would do
  (a dry run); with `--go` it makes the branch `release/X.Y.Z` from where you are (the working tree must be clean),
  joins the fragments into the changelog (below), writes the README's *New in* and the app's *What's new* from that
  entry, commits, pushes and opens the pull request "ENLENS X.Y.Z" with `gh pr create`. Read the entry in the pull
  request, write its opening paragraph, and if you change the entry run `python tools/release.py sync-notes` (it
  rewrites *New in* and *What's new* from the newest entry; `--check` only compares). **Merging it tags the merge
  commit:** `.github/workflows/tag-release.yml` runs for a merged pull request from a branch `release/X.Y.Z` of this
  repository, checks the changelog and the fragments with `release.py`, makes the tag `vX.Y.Z` and starts `release.yml`
  for it. (A tag made with the workflow's own token starts no workflow, so `tag-release.yml` dispatches `release.yml`
  with the tag as its ref; no personal token is needed.) `release.yml` then waits for the Tests run of the merge
  commit, as below, and drafts the release. A tag pushed by hand still works as before.
- **The order of a release** (2026-11-12; with the pull request, the tests run on it and on the merge, and the tag
  follows the merge, so the steps below are what the pull request does for you): run the whole suite on your own computer, alone (*Tests*: about 2 minutes;
  optional now that CI runs every extra, but it catches a defect before it costs a push), push
  the release commit to `main` (`git push origin <commit>:refs/heads/main`), wait for its Tests run to be green (about
  8 minutes: `gh run list --workflow tests.yml`, then `gh run watch <id> --exit-status`), and only then push the tag.
  The release workflow then takes about 2 minutes: it finds that Tests has passed on the tagged commit and does not
  run the suite again. A red Tests run so costs a commit, not a version number (0.14.3's tag, pushed with a commit
  that failed on Linux, could never be released). A tag pushed together with its commit (`git push --follow-tags`)
  also works: the release workflow's *tests* job waits for the Tests run of that commit while the package is built and
  tried beside it, and a failed run stops the draft. It runs the suite itself, on Linux only, when the commit has no
  Tests run (none, or one cancelled by a later push to `main`).
- **Repeatable builds (0.18.1).** `uv.lock` pins every package CI installs: the workflows run `uv lock --check` and
  `uv sync --frozen --extra …`, the Linux every-extra job takes every extra (a test checks it still does). After
  changing a dependency in `pyproject.toml` run `uv lock` and commit the file. The `ci` extra holds what only CI's
  every-extra job needs (PyYAML for the workflow tests, ruff). Dependabot (`.github/dependabot.yml`) opens a weekly pull
  request for new package versions and new versions of Actions; read its diff, let the Tests run, merge. **Every action
  is pinned by its full commit hash**, the tag as a comment (`uses: actions/checkout@3d3c… # v7.0.1`; a test checks it).
  To look up a hash: `gh api repos/<owner>/<repo>/git/ref/tags/<tag>` (an annotated tag answers with a tag object: ask
  `git/tags/<sha>` for the commit). The build's own requirements (`setuptools-scm`, `setuptools`) are not in the
  lock: `uv build` takes their newest versions.
- **Provenance (0.18.1).** `release.yml` attests every file of the release (`actions/attest-build-provenance`: which
  workflow and commit built it, signed by GitHub). Anyone can check a download:
  `gh attestation verify enlens_claims-X.Y.Z-py3-none-any.whl --repo dvaud/claim_checker_demo`. It sits beside
  `SHA256SUMS`: the checksums say a file arrived whole, the attestation that it came from this repository.
- **After publishing (0.18.1).** `.github/workflows/published-install.yml` runs the real install line of the published
  release on Linux, macOS and Windows when a release is published, and every Monday on the latest release; it
  checks that the installed version is the release's, that the install is recorded as a one-line install and that
  the connector starts, and (on a publish) that the wheel's attestation verifies. A red run does not undo the
  release: see *Rolling back a release*. Run it by hand from the Actions tab with a tag to try an older release.
- The `CHANGELOG.md` entry (what changed and why, the defects fixed, the tests added, and *Not yet done*) becomes the
  release notes. Update the manual where behaviour changed (*The manual*, below) and `docs/API.md` for new routes.
- **Changelog fragments (0.18.1).** A change does not edit `CHANGELOG.md`: it adds `changes/<topic>.md`, made of
  `### <Section>` headings and their text ([`changes/README.md`](../changes/README.md)), so two branches never edit
  the same lines. At the release, `python tools/release.py fragments X.Y.Z "<title>" --dry-run` shows the entry,
  the same without `--dry-run` writes it at the top of `CHANGELOG.md` and deletes the fragments; then write the entry's
  opening paragraph by hand. The release workflow refuses a tag while fragments are left
  (`python tools/release.py fragments --check`).
- Each release updates `gui/static/whats-new.md` (`# X.Y.Z: Title`, `*subtitle*`, then a few extremely short points,
  one `-` line each; since 0.18.1 `release.py prepare` and `sync-notes` write it from the changelog entry: the points
  are the headlines of its *New* and *Changes that can alter your results* bullets, the subtitle the first sentence of
  the entry's opening paragraph; edit the entry, not the note). When its version matches the running one, the app offers it, never shows it by itself: after an
  update the sidebar has *What's new* until it is opened, and Settings has it always.
- The README's *New in* is written by `prepare` (between its two `<!-- new-in -->` markers); update the manual and
  the other sections of the README as the last two sections say.
- **Release candidates (0.15).** The roadmap ([`docs/ROADMAP.md`](ROADMAP.md): what each release builds, and what
  waits; Margin keeps its own plans in its own repository) gives every minor release a release candidate, in use for at least a
  week: a `## 0.15.0rc1` changelog entry, tagged `v0.15.0rc1` (the package's version is made from the tag).
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
  `reader.read_blocks(raw, version=2)` still reads exactly as 0.15.0 did, which a test checks to the byte), 4 adds
  `reader4.py` and reads Word files otherwise (0.17.2; a Word file whose text reader 4 reads otherwise keeps reader
  3's text in `RawDoc.before_4`, so `build_document(raw, version=3)` reads as before from any raw). Check a change
  with `tools/reader_fingerprints.py` (a folder of files, before and after) and `tools/reader_fingerprints_pytest.py`
  (every document the tests read). A change
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

- Write nothing in **New in**: `python tools/release.py prepare` (or `sync-notes`) writes it, between its two
  `<!-- new-in:start -->` and `<!-- new-in:end -->` markers, from the newest changelog entry: the *New* and *Changes
  that can alter your results* bullets, each cut to its headline and first sentence, with whether it can change results.
  Change the changelog entry to change it; `tests/test_doc_links.py` fails when the two differ.
- Touch the other sections only when the release changed what they describe. Take a new screenshot when the Overview
  looks different (`tools/dev_server.py --corpus social --claude-code`, Playwright at 1280 × 800).
- CI checks the rest (0.18.1: `tests/test_doc_links.py` and `tests/test_manual.py`): every relative link in the README,
  the changelog and `docs/` resolves, every feature of the app has a section in the manual (a heading in a
  `docs/manual/` page that names it, or an entry in the test's `SECTION_OF`), and *New in* matches the changelog. Keep
  the README about 100 lines, and a copy of the changelog or the manual out of it.

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
| `first-steps.md` | The first screen (*Set up Claude*, a project, documents), the sidebar (places and views, the finder, the AI mark, the status area) and the rest of the app's frame |
| `check.md` | *Hypotheses*: writing and checking one hypothesis or several, what a check does, the answers, parts |
| `review.md` | The result page, excerpt cards and their actions, other AI models, downloads, the list of answers, the evidence map |
| `explore.md` | Search, Codes (by document), Concepts, Themes, a document's panels, Quick look, FlexiConc |
| `reading.md` | The readers, the reading view, *Read with the new reader*, `enlens measure` |
| `bibliography.md` | Zotero and exported bibliographies, the four lists, matching |
| `together.md` | Shared projects (private until shared, the shared folder and the Team tab, the three roles), sync clashes, project zips, moving to another computer |
| `storage-space.md` | A storage space of the team's own (0.18.0rc2): which company, the owner's set-up at Backblaze or Cloudflare, invites and *Join a team*, the Team tab's section, removing a colleague, moving |
| `shared-folder.md` | Choosing the shared folder (cloud folders by name, the system's folder window, how a colleague finds the team's folder, making a shared folder available offline) |
| `roles.md` | Roles in a shared project: proposals and who answers them, what *Waiting for your word* holds (answered both ways, changes of owner, AI offers, 30-day removals, settled at the same time), the people list, a second computer |
| `privacy.md` | What leaves the computer, who may read each document with AI, enforcement, what Claude read, what the shared folder holds |
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
