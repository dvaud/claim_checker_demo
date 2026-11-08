# Changelog

## 0.15.1 (November 2026): text files and books, read without the clutter

Reader 2 (0.15.0) sets aside what is not a document's own text by where it stands on a PDF's page. A text file has no
pages, and many `.txt` and `.md` files are text copied out of a PDF by a converter: every running head, page number
and printer's line was still in the text, a Markdown file without marked headings had no headings at all, and a whole
page could be one paragraph. Reader 3 finds all of that from the text alone, and reads books and theses from their
table of contents. The reading view gets two quicker corrections, Zotero adds a work's PDF rather than a saved web
page, and the app says in a small note, once, what is new after an update.

### Changes that can alter your results

- **Reader 3, for documents added from now on** (`ingest.READER` 3). Documents already in a project keep their
  reading; *Read with the new reader* (in *Reading*) moves one, its results with it. On a text file, and on any page
  read without positions (OCR, a PDF read from its text layer):
  - **Running heads and footers** are set aside when they come back about once a page, next to a page break or at
    regular intervals, with their numbers aside; a short one in capitals with its page number ("2 INTRODUCTION",
    "THE SYSTEMS LENS 3") is found from two pages, from the contents, or because it interrupts a sentence across a
    page turn. Answers that come back in an interview ("[P] Ja.") come back irregularly, in mid-text, and stay.
  - **Page numbers**: lines that are only a number, counting up a page apart.
  - **Paragraphs and headings**: in text broken into lines of one width, a short line that ends a sentence ends its
    paragraph and a short line on its own is a heading; a Markdown file, web page or Word file that marks fewer than
    three headings gets headings by these rules. A line that ends or holds a sentence, introduces a list or runs on
    into the next block is not taken for a heading.
  - **Publishing details** at the start of a text file that looks published (a copyright line, an ISBN, a printer,
    *Other books by*) are set aside as front matter, as a PDF's author details are.
  - **Repairs**: text printed twice letter by letter ("TTIISS ffiinnaall" → "TIS final"), ligatures a converter broke
    with a space ("fi nd" → "find", but "off the" stays), and, only in a file that lost many of its spaces (2% or more
    of its words of 15 letters or longer), words run together, split into words the document itself writes apart and
    never into word endings ("require ment").
- **Books and theses, in any format**: the table of contents (lines ending in page numbers that go up) is set aside,
  and its entries find the chapter headings. What comes before the first chapter is front matter (an abstract,
  summary or preface stays, and so does a paragraph of text the contents did not name); the notes, the bibliography,
  the index, *About the author* and the acknowledgements found from the contents are set aside. An index is also known
  by its lines ("archetypes, 112–116, 191"), and "Notes" and "Index" headings at the end are known by name.
- **All like this** and **Text starts here / Text ends here** change which passages searches, codes, themes and
  checks read, when you use them.
- **Zotero**: when a work has several files, *Add these files to the project* adds its PDF first, then a Word file,
  then a text file, and a saved web page only when nothing else can be read (it took the first file, often Zotero's
  snapshot of a landing page). A work with neither author nor year is proposed for a document when its long title
  (six words that count or more) stands whole on the document's title page; you confirm it.

### New

- **All like this** in the reading view, on a short block that comes back (a running head, a page number, a label):
  leaves out, or restores, every block that looks the same, their numbers aside.
- **Text starts here** and **Text ends here** (in the first or last third of a document): everything before or after
  is left out, for a book's title pages or its end matter the reader did not find. *Undo start* or *Undo end* takes it
  back; a block you restore there still counts and says *restored by you*. Both are kept by the block's words, so they
  hold when the document is read again, and move with it to a new reader.
- **What is new**: after an update, the first start shows a small note of what changed, once, in the corner; *×* or
  Escape closes it. A new installation shows none.
- **Reading** says when a text file looks copied out of a PDF ("If you have the PDF, add it instead"), when many of its
  words still run together, and when a PDF was read without its layout; lines printed twice and read once are among
  the repairs. A document read by 0.15.0's reader keeps its report beside the offer to move it.
- **A git copy gets the layout reader** (the `pdfminer` extra) at its next `enlens update` after this one, as the
  one-line install always has; without it PDFs are read from their text alone.

### Fixed

- A Markdown file without `#` headings got no headings at all (an empty list of marked headings was taken as "this
  file has none").
- Zotero's saved web page was added instead of the work's PDF, and then counted as the work's document, so the full
  text already in the project was never proposed for it.
- The actions under a block in the reading view could fall under the next row (a left-out block's faded label made a
  layer of its own); they now stand on a small card above it.
- The *File in Zotero* column named the first readable file, not the one *Add these files* takes.

### Privacy

- Nothing new leaves the computer. Reader 3, *All like this* and the start and end marks use no AI. The note of what is
  new is a file inside ENLENS; showing it sends nothing.

### For developers

- `reader3.py`: what reader 3 adds (`text_furniture`, `undouble_lines`, `paragraph_breaks`, `looks_published`,
  `publishing_details`, `book_parts`, `find_contents`, `ligature_words`, `join_ligature_gaps`, `not_a_heading`,
  `damaged_spacing`, `split_runs`, `report_warnings`). `reader.READER` and `ingest.READER` are 3;
  `reader.read_blocks(raw, version)` and `build_document(..., version)` read as 0.15.0 did with `version=2`
  (`tests/test_0_15_1_reader3.py` checks a book's reading by reader 2 against 0.15.0's fingerprint). New block kinds
  `contents` and `index`; *front* is called *Front matter*. In lines without positions, page furniture stays where it
  stood (a block of its own) instead of moving to the end of the page. The report adds `repairs.doubled`,
  `text_layout` and `book`.
- `reader.choose_inclusion(items, choices)` decides what counts (kind, then the start and end marks, then the block's
  own choice) for `apply_choices` and for the preview of a move (`reread.py`); marks are `block_choices` rows
  `start:<fp>:<k>` and `end:<fp>:<k>` (`reader.bound_key`, `bound_index`). `PUT …/documents/<id>/blocks/<n>` takes
  `alike`; `PUT …/documents/<id>/bounds` is new; `?view=blocks` adds `alike`, `share` and `bound` (docs/API.md).
  `App.block_shapes`.
- `GET /api/whats-new` and `gui/static/whats-new.md`, which each release updates (docs/DEVELOPING.md, *Releases*);
  the setting `whats_new_seen`.
- `update.update_git` adds `pdfminer` to a git copy's reinstall when the new version has that extra.
  `update.WITHDRAWN` is empty: 0.15.1 is released for real.
- `bibliography.TITLE_ONLY_WORDS`, `_FILE_RANK`.
- `enlens measure` (the six PDFs of known text): reader 3 reads them as reader 2 does (words that belong 99.9%,
  leftover boilerplate 0). On the test's book copied out of its PDF, reader 3 keeps every word of its text in order
  (recall 100%, precision at least 99%) with no running head, slug, contents line, note or index entry left in it;
  reader 2 left more than ten of them.

New tests: `tests/test_0_15_1_reader3.py` (a book copied out of its PDF, read by reader 3 and, to the byte, by reader
2; interview answers are not running heads; a journal's running heads and page numbers; headings in a Markdown file
without marked ones; ligatures; words run together only where spaces were lost; the report's warnings; where the text
starts and ends; *All like this* and the marks in the reading view, with their errors; a reader-2 document moved to
reader 3 with the person's mark). `tests/test_0_15_1_zotero_files.py` (the PDF before a saved web page; a web page
when it is all there is; Word before text; a long title alone proposed, never linked; not a short or partial one; an
author still outranks it; the whole case of a thesis saved as a web page). `tests/test_0_15_1_whats_new.py` (the
note's format; shown once after an update; never on a new installation or for another version).
`tests/test_0_15_1_updates.py` (a git copy gets `pdfminer`; no number is withdrawn). Tests of 0.15.0 that named
reader 2 as the current one now name `ingest.READER`.

### Not yet done

- Pages are not found again in a text file: a quote from one is cited by paragraph, not page.
- A running head that comes back once, at a sentence's end, and is not in the contents stays in the text.
- Text copied out of a two-column PDF stays interleaved, as the converter wrote it: add the PDF itself.
- Words run together are split only into words the document uses on its own at least twice; a rare word can stay
  joined.
- The update that brings `pdfminer` to a git copy is the next one after 0.15.1 (the update to 0.15.1 runs 0.15.0's
  code): until then, `pip install -e '.[pdfminer]'` in the copy.
- Checked in Chromium on macOS (light, dark, 390 px wide); not tried by hand on Windows.

## 0.15.0 (November 2026): a new reader, and results you can trace

0.15 changes how documents are read. A new reader finds the columns of a PDF, sets aside what is not the
document's own text (running heads, page numbers, author details, acknowledgements, footnotes, the reference list),
keeps tables as tables and repairs words broken over lines. Each document's page now shows its text the way the
reader found it, with the PDF page beside it, a report on how well it read, and *Restore* and *Leave out* for any
part. Documents already in a project keep the reading they have, so nothing you made moves by itself; *Read with the
new reader* moves one when you choose, its results with it. Every result now records the ENLENS version that made
it, and `enlens measure` shows in figures how well each reader reads.

### Changes that can alter your results

- **A new reader for documents added from now on** (reader 2). Search hits, codes, key terms, themes and the
  excerpts a check reads come from other passages than before:
  - **Two columns are read one after the other**, not across; a title or abstract set across the page comes first.
  - **What is not the document's own text is set aside**: running heads and footers, page numbers and line numbers,
    words inside charts, author names, affiliations, e-mails and dates on the first page, acknowledgements, funding,
    conflicts of interest, data availability, licence lines, footnotes and the reference list. They stay in the
    document and in a search of all its text; searches, codes, themes and checks do not read them.
  - **Tables are kept as tables** (rows and cells, with their caption), left out of the passages, and downloadable
    for Excel.
  - **Words are repaired**: a word cut at a line end is joined, a compound keeps its hyphen (reader 1 made
    "long-term" into "longterm"), words that ran together are split where the document writes them apart, and
    ligatures, odd spaces and accents set apart from their letter are put right in the stored text.
  - **A passage is a paragraph** (long ones cut into parts of about equal size, short ones put together), and a
    heading starts a passage with the text under it; reader 1 ran sentences together across paragraphs and headings.
    Paragraphs are numbered as before for text files; in a PDF a heading counts with the text under it.
  - Measured with `enlens measure` on six PDFs of known text: the share of the words in the text that searches and
    the AI read that belong there rose from 85% to 99.9% (the figures are under *For developers*).
- **Restore and Leave out** change which passages searches, codes, themes and checks read, when you use them.
- **Read with the new reader** gives the document you move a new text and new passages.

### New

- **The reading view** (the page of a document read by the new reader): headings, paragraphs, captions and tables
  as they are, a mark where each page begins, and what was set aside folded under *Left out of the text* on each
  page. Point at a block for *Leave out* or *Restore*; a heading goes with its text, and paragraphs that share a
  passage go together. The choice is kept by the block's words, so it holds when the document is read again.
- **Reading**, a panel beside the text: *Read well*, *Read, with something to check* or *Read badly*, with the
  reasons (pages without text, text recognised by OCR, a garbled text layer, most of the text set aside), what was
  repaired, the tables found, how many passages count, and *Show what was left out in the text*. The list of
  documents marks one that read badly, and one read by the earlier reader.
- **Page**, a panel beside the text (PDFs, with the OCR extra): the page of the original with every block the reader
  found outlined (solid: read; dashed: left out). It follows the text as you scroll; click an outline to go to it.
- **Read with the new reader** (in *Reading*, for a document added before 0.15): a preview first, changing nothing
  (how many of its results find their place in the new text, and which do not), then *Move it to the new reader*, all
  or nothing. Each result follows its quote to the same words; a check keeps the excerpt it showed; keyword codes, key
  terms and the search index are made again; work still waiting for the AI is asked again; a set of themes is marked
  out of date where its passages changed; what cannot be placed is kept without a place and listed (its check marks it
  *no place in the new reading*). The Overview's line about earlier versions, and *read before 0.15* in the list of
  documents, say where to find it.
- **Every result says which ENLENS made it.** Each AI answer, codebook label and set of themes, and the run behind
  them, records the ENLENS version; a check records the version that started it; each document the reader that read
  it. *How these results were made*, at the end of every Excel download, has a column *ENLENS version* and a line
  naming the readers. The Overview says, in one quiet line, which results an earlier version made; they stay as they
  were made. Results made before this version say "before 0.15".
- **`enlens measure`**: how well ENLENS reads, in figures, with no AI. It makes six small PDFs whose text it knows (one
  and two columns, running heads, line numbers, front and back matter, a table, footnotes), reads them with each
  reader and reports the words kept, the words that belong, their order, words run together or broken apart, and
  leftover boilerplate. `--folder DIR` measures PDFs with their true text beside them (`tools/arxiv_truth.py` makes a
  folder from open-access arXiv papers); `--ws PROJECT` counts the quotes of a project that still find their place in
  each reader's text, on a copy; `--timings` adds how long reading, search, key terms and themes take. Each release now
  carries `validation-report.md`, made by it: the half of a validation report that needs no AI.
- **Try new versions early.** *Settings → Technical → Which new versions to offer*: *Stable (recommended)* or *Try
  new versions early*, which also offers release candidates (a candidate comes at least a week before each new
  version). Try one on a project you do not share: going back can show sync clashes (nothing is lost). A git copy
  follows its branch and has no choice. The update pop-up says "release candidate" when it offers one.
- **Reporting a problem.** *Settings → Technical → Copy technical details* copies the version, how ENLENS was
  installed, the system, Python, the AI route, whether cloud models are off and the update channel (never a path, a
  project or document name, or a key); *Report a problem* opens a plain-language form on GitHub. A form for ideas, and
  `SECURITY.md` on reporting a security or privacy problem privately.

### Privacy

- Nothing new leaves the computer. The new reader, the reading view, the pictures of pages, `enlens measure` and
  *Read with the new reader* all run on this computer, with no AI. *Copy technical details* holds no path, name or
  key, and goes nowhere until you paste it. `tools/arxiv_truth.py`, a developer's tool never run by the app, is the
  only part that downloads anything (open-access papers from arXiv).

### For developers

- **The reader.** `reader.py` is reader 2 and `ingest.READER` is 2; reader 1 stays as `ingest._build_document_1`, and
  `ingest.read_document(path, reader=…)` reads a file with either and stores nothing. New tables `blocks` (each
  block's kind, whether it is read, its box), `doc_tables` (rows of cells and caption) and `block_choices` (a person's
  Restore and Leave out, kept by `reader.block_fp`); `passages.block` and `documents.reading_json` (the reading
  report); passages of left-out blocks have `section` `left_out`. `reader.apply_choices` sets blocks and passage
  sections from the choices; `ingest.store_blocks` stores a reading. `sync.py` brings in a colleague's blocks and
  tables with their documents; removing a document removes its blocks. `RawDoc.page_sizes`.
- **Read with the new reader**: `reread.py` (`check`, `preview`, `move`): old text aligned to the new sentence by
  sentence, each result moved by its quote near where it was; ids made from passage ids made again, and an old
  passage id that cannot move becomes a tombstone (`<doc>:r1-0005`) that names no passage, so nothing ever points at
  other words; a kept excerpt stores the reader it was shown from, its breaks and quote positions (`tasks.doc_span`
  places later answers in the document as it reads now); `documents.old_fps` (the older text's fingerprints, for a
  later sync fix) and `documents.sent_share` (so the share Claude has read never drops below what was sent);
  quotes across a reader-2 table's cell marks still find their place. `GET …/documents/<id>/reread` (preview),
  `POST` (a job: the move, then search by meaning, the glossary and the keyword pass); refused while another job of the
  project runs. Removing a document also removes answers kept under its old passage ids.
- **The reading view's routes**: `GET …/documents/<id>?view=blocks` gives a reader-2 document block by block with
  kinds, inclusion, boxes and tables; `PUT …/documents/<id>/blocks/<n>`, `GET …/documents/<id>/pages/<n>.png`
  (pypdfium2, one thread at a time), `GET …/documents/<id>/tables/<n>.xlsx`; the document detail adds `reader`,
  `new_reader`, `reading`, `page_images`, `tables`, `paragraphs`, and the list `reading_quality` and
  `reading_warnings` (docs/API.md).
- **Versions on results**: `app_version` in `results`, `runs`, `labels`, `theme_runs`, `hypotheses` and
  `documents`, and `documents.reader` (`store._migrate` gives documents read before 0.15 reader 1). Labels, runs and
  theme runs are written by column name (`profile._INSERT_LABEL`): the positional `INSERT … VALUES` broke as soon as a
  table gained a column. `sync._HOW` keeps `app_version` out of every fingerprint (0.14 cannot: going back from a
  0.15 candidate to 0.14 on a shared project gives sync clashes; docs/DEVELOPING.md). `runs.made_with()`,
  `runs.version_label()`, `runs.RECORDED_SINCE`.
- **Release candidates.** `update.version_tuple()` orders `0.15.0rc1` after every earlier release and before
  `0.15.0`; `tools/release.py` takes `v0.15.0rc1` tags and changelog entries headed 0.15.0rc1 (`release.py prerelease`),
  and a candidate's notes give install lines with its own files; `release.yml` drafts a candidate as a pre-release.
  `update.semver` gives the plugin a candidate's number as semantic versioning. The update channel:
  `settings.update_channel`, `update.highest_release`, `update.is_candidate`; `GET /api/technical-details`.
- **Withdrawn numbers.** 0.15.0 left `update.WITHDRAWN` (now 0.15.1); a running copy of a withdrawn number counts as
  older only while this version is below it (`launcher.is_older`).
- **CI on three systems.** `tests.yml` runs on Linux (Python 3.10 and 3.13), macOS and Windows on every push and pull
  request (macOS and Windows advisory for now, see *Not yet done*), in UTF-8 mode, with the pdfminer extra and a
  `ruff` check for syntax errors and undefined names; tests of programs that exist only on macOS and Linux skip on
  Windows, and the tests that start the app as its icon does wait up to a minute for it. `release.yml` installs the pdfminer extra too, and makes
  `validation-report.md`. `docs/DEVELOPING.md` has *Rolling back a release* and *Changes that alter results*.
- **The new reader in figures** (`enlens measure`). On six PDFs of known text: words that belong 99.9% (reader 1:
  85%), words of the body kept and in order 99.9% (98.9%), running heads, page numbers, author details, table cells and
  footnotes left in the text that searches and the AI read: none (4.3 per document). On ten open-access papers (arXiv,
  their LaTeX source as an approximate true text): words kept 97.8% (97.6%), words run together 6 per paper (14),
  broken apart 10 (35), order 94.9% (96.1%; a little worse on papers with wide figures and tables).
- `pdfmake.py`, a small PDF writer for documents of known text; `tools/dev_server.py --reading` makes a project of
  them, one read by reader 1 with a check on it.

New tests: `tests/test_0_15_0_reader.py` (text repair; the known texts read whole, in order and without boilerplate;
two columns; a page that repeats another is not running heads; tables; passages never mix read and left-out text;
reading is the same twice; without pdfminer; paragraph numbering; what the project stores; a person's choice holds
when the document is stored again; the reading view, Restore and Leave out, a table for Excel, a picture of a page, a
document read before 0.15; moving a document from the app, refused while a job runs; removing a document removes
its records under old passage ids). `tests/test_0_15_0_read_with_new_reader.py` (a check keeps its excerpt and its
quote lands on the same words; judgements, labels and their reviews move; theme runs keep one-to-one members or go
out of date; waiting tasks are asked again and answered ones never collide with new passage ids; no row names an old
passage id with a new meaning; what cannot be placed is reported and points nowhere; the preview writes nothing; a
move is all or nothing; which judgements count is the same before and after, also for a check answered through the
queue; refusals; block choices applied again). `tests/test_0_15_0_measure.py` (the known-text PDFs are the same every
time; the figures on hand-made cases; quotes of a project counted on a copy that is never changed; the report and
`--json`; reader 2 at least as good as reader 1). `tests/test_0_15_0_testing_and_updates.py` (the update channel,
candidates found and drafts skipped, the technical details hold nothing private, the issue forms and
`SECURITY.md`). `tests/test_0_15_0_release_candidates.py`, `tests/test_0_15_0_versions_on_results.py` (the
groundwork). Tests of reader 1's own layout and of theme edits on a made-up corpus pin reader 1; a citation test now
expects reader 2's paragraph passages.

**Not yet done:**
- The roadmap planned a release candidate (0.15.0rc1) in use for a week before 0.15.0; 0.15.0 is released directly,
  so its first patches refine what use shows.
- The new reader was measured on six made-up PDFs and ten machine-learning papers, not yet on a large corpus of
  reports from other fields (`enlens measure --folder`, or `--ws` on a real project). A layout it does not know
  (three columns, a table or figure across two columns, text in boxes) can still come out out of order.
- *Read with the new reader* was tried in tests and on the dev server's documents, not on a real project with checks
  made by Claude Code.
- In a shared project, a colleague whose copy still has a document's older reading brings it in as a second copy at
  the next sync (the document remembers its older text's fingerprint for a later fix).
- After a move, an old passage rarely maps one to one onto a new one in a PDF (the new reader's passages are
  paragraphs): sets of themes that include it are mostly marked out of date, and the AI's codes for it are kept as
  records, so a new AI pass reads its passages again. An excerpt that finds no place still counts in its check's
  answer, as the check read it.
- Tables are found by the line positions pdfminer gives; tables without clear gaps between their columns, and tables
  in scanned pages, are not found. GROBID and Docling are not used.
- Restore and Leave out do not renumber paragraphs; a paragraph restored by hand is cited as part of the one before it.
- The tests had never run on Windows or macOS before; their first runs (on this release's commit) fail there: on
  Windows about a dozen tests fail and the run stops part way; on macOS one test (the app restarting itself in place
  after an update). Those two jobs are advisory (shown, not failing the run) until a 0.15.x patch makes the suite pass
  on them. Linux, on Python 3.10 and 3.13, passes, and the one-line install works on all three systems.

### Coming in 0.16

Working with the text, and the AI mix: notes and highlights, a research log and history, better concepts, retracted
papers flagged, export to NVivo and ATLAS.ti, and, last, a mix of a local model and Claude per kind of task (which
**can change results**, and is announced here one minor release ahead).

## 0.14.6 (November 2026): Claude Code works in a box of its own

Claude Code started by ENLENS needs nothing from your computer but the passages in its tasks. It now gets nothing
else: no tool that can open your files, and nothing from your own Claude Code set-up. Nothing changes in the
installation.

### Privacy

- **Claude Code works in a box of its own.** A run started with *Start Claude Code* now has only one built-in tool,
  the one that starts the helpers (`--tools Agent`): no tool that reads, writes or searches files, runs commands or
  browses exists in it at all; the passages reach it through the ENLENS connector. Before, those tools were denied one
  by one by name, a list that misses whatever tools a later Claude Code adds. Three of its names no longer exist in
  Claude Code. The run also no longer takes anything from your own Claude Code (`--restricted`): not your
  settings or hooks, not your `CLAUDE.md` instructions (which were read into every run and sent with it), not your
  other plugins and their connectors, not the connectors of your claude.ai account. It loads only ENLENS's plugin, as
  ENLENS wrote it (`--plugin-dir`). Nothing changes in the installation: these are options of Claude Code itself.
  ENLENS reads `claude --help` and uses them only when this Claude Code knows them; an older one runs as before.
  Can change results slightly: the helpers no longer receive your own Claude Code instructions, only ENLENS's.
- **The sign-in window keeps Claude Code out of your files.** *Set up Claude* opened Claude Code in your home folder
  for the one-time sign-in. Claude Code may read any file inside the folder it starts in without asking, so anything
  typed into that window after signing in could have had Claude read your documents. The window now starts Claude
  Code in an empty folder of ENLENS's own (`claude-runs/sign-in` in the data folder, emptied each time) without the
  tools for reading and writing files, running commands and browsing. When no window can be opened, the line the
  page shows goes to that folder first. Where Claude Code is installed (`~/.local/bin`) never decided what it can
  read, so the installer is unchanged; its confirmation now says so. Cannot change results.

### For developers

- `claude_setup.known_options()` reads the options of `claude --help` (once per program file); `box_args()` gives
  `--tools Agent`, plus `--restricted --plugin-dir <plugin folder>` for a run when the plugin is written, or the old
  `--disallowedTools` list for a Claude Code that knows neither. `run_args()` takes `options`; `start_run()` adds
  `BOX_ENV` (`ENABLE_CLAUDEAI_MCP_SERVERS=false`). `--strict-mcp-config` was tried and left out: it also drops the
  plugin's own connector.
- `sign_in_folder()` and `sign_in_line()`; `_sign_in_script()` takes the folder and the options;
  `open_sign_in()` returns that folder's line as `command` and the folder.
- `tests/fake_claude_cli.py` answers `--help` (`FAKE_CLAUDE_OPTIONS` plays an older Claude Code).

New tests: `tests/test_0_14_6_claude_code_box.py`: the options are read from Claude Code's help once per program
file; a run gets `--tools Agent --restricted --plugin-dir` and `ENABLE_CLAUDEAI_MCP_SERVERS=false`, an older Claude
Code the old list, and `--restricted` only when the plugin is written; the sign-in script, run with `/bin/sh`, starts
the program in the empty folder with the box's options (and the old list for an older Claude Code); the Windows
script goes to the folder first, quoted for PowerShell; the line to type; the sign-in route; the stand-in signs in
from the boxed window; the install confirmation's text.

**Tried with the real Claude Code (2.1.319) on a Mac, outside the tests:** in the box, a `CLAUDE.md` in a parent
folder and the user's own `~/.claude/CLAUDE.md` were not read, where the old command read both; the run's tools were
`Agent` and the ENLENS connector's alone (the old command also had the user's other plugin, agents and claude.ai
connectors); a helper asked to read a file found no Read tool; a connector tool the run was not allowed
(`add_sources`) was refused; the command `run_args()` builds ran `/enlens-run` and reached the connector; and the
labeller helper reached its three queue tools (against a scratch data folder).

**Not yet done:**
- The sign-in window was not tried with a real sign-in: the script was run with stand-ins, and `--tools` was checked
  in `claude --help` to be an option of every session, not only of `-p`. The window does not use `--restricted`,
  which was not tried with a real sign-in.
- No real run answered a real queue in the box: the pieces were tried one by one (above).
- `--restricted` ignores the person's Claude Code settings, so a proxy or an `apiKeyHelper` set only there no longer
  reaches the runs. ENLENS is used on a Claude plan; a person who needs one there would see the run fail.
- Windows was not tried: the sign-in script for PowerShell is checked as text.
- A box from the operating system (a sandbox around the whole program) was left out: on macOS it needs a profile
  that each Claude Code update can break, on Linux an extra program to install, and Windows has nothing simple.

## 0.14.5 (November 2026): install by double-clicking a file

**Install without Terminal or PowerShell.** Every release now also has the install as a file to download and
double-click, beside the install line, which stays as it was. Each file does what the line does (gets uv, downloads
the ENLENS package and checks it, installs it, makes the icon and opens ENLENS) in a window of its own:

- **Windows: `Install-ENLENS-Windows.cmd`.** Double-click it. The window waits for a key at the end, so you can read
  what happened. The file is not signed, so the browser may warn about it (keep it), and Windows may say it protected
  your PC (*More info*, then *Run anyway*). It is also the easy way to update on Windows, where ENLENS cannot replace
  itself while it runs: quit ENLENS, then double-click the newest copy. The app's update message on Windows now says
  so and gives the file's address.
- **macOS: `Install-ENLENS-macOS.zip`.** Open it and double-click *Install ENLENS.command*, which Terminal runs. It is
  in a zip because a browser drops the mark that lets a downloaded file run. macOS runs a downloaded program at once
  only if a registered Apple developer signed it, and this file is not signed. The first time, macOS says it could not
  verify it: click *Done*, open *System Settings → Privacy & Security*, click *Open Anyway* next to *Install
  ENLENS.command* and confirm with your password. The install line needs none of this, so on a Mac it stays the
  quicker way.
- Linux keeps the install line.

The release notes, the README and section 1 of the manual link both files, and `SHA256SUMS` lists them. The
installers' last line no longer says "run the same line again" (there may have been no line); it says ENLENS tells
you when there is a new version. Nothing here can change results.

### For developers

- `tools/release.py assets` builds both files: the Windows file is `install/Install-ENLENS-Windows.cmd` (new) with
  `install.ps1` below it, and the Mac file is `install.sh` in a zip that marks it as a file that may run. cmd runs the
  head up to its `exit /b`. The head has PowerShell read the whole file, in which the head is one `<# … #>` comment.
  So the file downloads no other script, and the release's Windows machine can try it before the release exists. The
  build stops if the head could end that comment early or if the file is not plain ASCII (cmd reads it in the
  console's code page). `install/install.ps1` is plain ASCII now; it had one `…` in a comment.
- `.github/workflows/release.yml` removes the install on its Windows and macOS machines and installs again with each
  file, the way a double-click runs it: `cmd /c` with no input on Windows; on macOS, unzipped with `ditto` (as
  Archive Utility does) and started directly.
- `installation.double_click_file()` gives the address of the latest release's file for a system.

**Tests:**
- `tests/test_0_14_5_double_click_install.py` (11 tests): the release has both files with their checksums; the Windows
  file is cmd, then `install.ps1` unchanged, with Windows line endings, and the cmd part never reaches PowerShell's
  code; a broken head stops the release; the zip holds `install.sh` marked as runnable; unzipped as a Mac does, it runs
  and installs (stand-ins for uv and curl); the release notes link both files of that release; the workflow tries
  both; on Windows, the update message names the file. Where PowerShell is installed (GitHub's Linux test machine has
  it), a test parses the Windows file with it and checks that the whole cmd part is one comment.

Changed tests: `tests/test_0100_setup_and_moving.py::test_release_check_notes_and_assets` (the release has the two
new files).

**Not yet done:**
- The Windows file has not been double-clicked on a real Windows computer. The release's Windows machine runs it as a
  double-click does, from a removed install, but not with SmartScreen or a browser in the way. Whether Microsoft
  Defender or a browser blocks the file outright will show only once someone downloads it.
- Gatekeeper's *Open Anyway* was not clicked through. On the Mac it was built on, the unzipped file was refused as
  expected ("no usable signature"), and started directly it installed ENLENS into a scratch home folder.
- A signed and notarised macOS installer (a `.pkg`) would open without the System Settings step. It needs an Apple
  Developer account.

## 0.14.4 (November 2026): fixes from a review of the whole app

**0.14.3 was tagged but not released:** its tests failed on the release's Linux machine. 0.14.4 is the same release
with that fixed, and everything below comes with it. The test had found a real defect: on Linux, ENLENS did not
recognise a Claude Code run it had started before a restart (`ps` cut the run's command line at 80 characters), so
the reopened app could not stop the run and would start a second one beside it. It now reads the whole command
line. A test of the optional pdfminer extra is now skipped where the extra is not installed. Nothing here can
change results.

A review of ENLENS by five independent reviewers, each taking one part of the app (checking, privacy and sharing, the
app's server and updates, exploring, and the pages themselves), found the defects below; most were reproduced with a
script before they were fixed, and each fix has a test. Several **can change results**: each says so.

### Privacy

**A local model's summary no longer reaches a Claude chat.** When your main AI was a model on this computer, it also
read documents marked *Only a local AI*, and the connector (`get_check`, `submit_grades`) showed its summary of a
check, and its "about another group" notes on excerpts, to Claude. They are now shown only when every part of the
check read nothing but text Claude may read now; otherwise they are left out and the connector says why. Claude's own
summaries are shown as before. **Can change what Claude is sent.**

**Letting Claude read a document asks first.** Changing a document from *No AI* or *Only a local AI* to *Claude may
read it* (or from *No AI* to *Only a local AI*) saved at once, with only a short message, although the next check
would send its passages to Anthropic. It now asks first and shows the document's note; *Cancel* puts the setting back.
Making a setting stricter stays instant.

**The project zip leaves out removed documents.** *Download as a zip* sent the whole uploads folder, so a document you
had removed (one added by mistake, say) went to your colleague with the zip. Only the files of the project's current
documents and its codebooks go in now. The zip's download link also no longer carries the app's access key in its
address (where it stayed in the browser's history and in the file's "Where from" details). **Can change exports.**

**Glossary terms stay home.** With an embedding server on another computer, terms found only in documents kept from
Claude were sent to it to find wordings of the same concept. Only terms found in documents Claude may read are sent
now. **Can change the "possibly the same" proposals.**

**A colleague's copy of a document follows your stricter setting.** After a sync clash, making a document *Only a
local AI* left your colleague's reading of the same file at *Claude may read it*. A copy now gets the stricter of its
own setting and its original's.

### Checking a hypothesis

**A check whose AI answers failed no longer says "No evidence found".** When the AI's answers for a search could not be
used (after three tries) and some of its excerpts came from *No AI* documents, the result said *No evidence found*,
with no error and no "did not finish" warning. It now says *The check did not work* and shows why. Nothing the AI or
the local model said in a search that failed counts in the answer, the counts, the map or the Excel file. Your own
judgements of its excerpts are kept: they count once another search of the check is answered (*Check again*); while
every search of a check has failed, the answer stays *The check did not work*. **Can change results.**

**Excerpts that wait for your judgement are not "not about it".** A check of documents marked *No AI* said *No
evidence found*, as if the excerpts had been read. It now says *Waiting for your judgement*, on the result, the Results
list, the map, in Excel and to the Claude connector, and each excerpt counts once you judge it. **Can change results.**

**Excel says who really judged each excerpt.** Rows for excerpts no AI read said "Judged by: the AI — Not about the
hypothesis". They now say "nobody yet" and why: kept for your judgement, waiting for your local model, or the AI's
answer could not be used; excerpts of a search that failed are marked *Not counted: the check did not work*. The *AI
model used* column lists every model whose answers the check used and what each did (the stronger model, the local
model for restricted documents, the model that actually answered in Claude Code). **Can change exports.**

**A stricter quote check.** A quote must now match whole words ("legal" is no longer found inside "illegal", and "now
here" no longer matches "nowhere"), may not begin or end inside a number ("rose by 2" is not a quote of "rose by
2,500"), and a judgement's quote needs at least three words or 15 characters. The AI is told so (prompts `check-v5`,
`verify-v2`, `verify-set-v2`). Your own selections are widened to whole words. Results already stored do not change:
on the pilot and three real projects, 7 of 8,653 earlier quotes would now be sent back, none of them a judgement's.
**Can change the results of new checks.**

**A local model's runaway answer no longer stops everything.** An answer cut off at the length limit, or stuck writing
blank space, deleted the whole check (finished parts too) and stopped *Check several*. It is now one failed try: the
task is asked again with the problem listed, and the check goes on. A full context window, or a reasoning allowance
used up, is still said at once, since asking again cannot help.

**The stronger model gets its own three tries.** It could get only two, after which the result showed "stronger model
waiting" for good. A Claude Code helper can now fix a rejected stronger-model answer instead of being told its claim
had lapsed.

**Smaller fixes.**
- The evidence map agrees with the Results list: a document no longer "decides" an answer that is still waiting or
  that failed. The map is also faster.
- *How these results were made* records the prompt version the model was actually given.
- The manual now says what the code always did: a part that failed or waits for you gives no evidence, so the whole
  hypothesis is at most partly supported.

### Exploring the documents

**A phrase finds only the phrase.** The words *the*, *of*, *from* and the like in a quoted phrase were optional, and a
phrase starting with one was counted twice: "the economy" also counted every "economy", and "imports of
electrolysers" also found "imports from electrolysers". The counts per document, the exports and *Words that often
appear nearby* were off. A phrase's own small words are now required where you wrote them. Words typed next to a
quoted phrase must now also be in the passage (they were ignored), and with a document or code chosen, *Words that
often appear nearby* compares with that part of the project rather than all of it. **Can change results.**

**Highlights land where their words stand.** In a highlighted copy, a highlight went to the first place its words
occurred on the page, so every mention of a concept on a page sat on the first one, and a mention such as "it" or
"we" was never highlighted. Each highlight is now placed at its own position, and short mentions are matched as whole
words. **Can change the highlighted copies.**

**The bibliography no longer renames a document after a work it cites.** A document's DOI was guessed as the most
frequent DOI on its first pages, possibly one it only cites, and the document was then linked to that work as *Same
DOI* and renamed after it. A DOI now links on its own only when it is in the file name or on the title page; otherwise
the pair waits under *Please confirm*. In a short document the reference list is no longer read as part of its title
page, so the works it cites stay in *To find*. A decision or *Confirm all* now takes a fraction of a second (it took
about 16 seconds in a library of 1,000 works and 200 documents), and matching is about four times faster. BibTeX web
addresses keep their `~` and `--`, `@string` names (such as journals) are filled in, and only web addresses become
links. **Can change results.**

**Theme edits follow their themes.** Renames, merges, moved passages and removed themes were kept by theme number: after
you added documents and found the themes again, your name "Water" could land on the songbirds theme, and in a small
project edits vanished once it grew. Edits now follow their themes by the passages they share; an edit whose theme is
gone is left behind. A double-clicked *Find the themes* no longer fails. **Can change results.**

**A code you agreed with stays.** A keyword label you accepted or changed was dropped once the AI had read the
passage, although your labels always count. It now stays. **Can change results.**

**Codebooks from European Excel.** A codebook CSV saved with semicolons (Excel in Hungarian and other European
settings) was refused, and one saved in a Windows code page lost its accented letters. Both are read now, and a file in
a codebooks folder that cannot be read is listed with the reason instead of being skipped silently.

**SDG pack: references of different years are told apart.** References without a DOI were identified by their first 48
letters, so *Hydrogen Insights 2021* and *2022* became one reference. **Can change results.**

### Working together

**Sharing fixes.** A colleague's reading of a file that you had removed came back with every file from them; it now
stays removed. A result still running in your copy (waiting for Claude Code, say) was replaced by your colleague's
version and its work lost; it is now kept and the report says it is running here. Colleagues on different ENLENS
versions got a sync clash on every result; they no longer do, and work exchanged with 0.14.0–0.14.2 is still
recognised. A colleague's file can no longer add or replace a judgement or review in your name: only take one back,
as the manual says. **Can change what comes in.**

**A comment no longer hides a colleague's judgement.** In a shared project, adding only a comment to an excerpt made
it fall back to the AI's judgement instead of your colleague's, and editing your comment afterwards (or its *Undo*)
could save your colleague's verdict as yours. *Judgements you reviewed / changed*, *to review* and the Excel counts now
count only your own judgements. **Can change results.**

### Adding documents

**One bad file no longer stops the whole add.** A password-protected or damaged zip, PDF or Word file stopped the whole
add, with nothing added. It is now listed with the reason (for example *password-protected: save a copy without the
password*) and the other files are added.

**Text in other code pages is read as written.** Text and web pages saved in Windows-1250 or -1252 (a Hungarian
Notepad file, an old web page) lost every accented letter, were marked unreadable and could not be searched. ENLENS
now reads the file's byte-order mark, then UTF-8, then the page's declared encoding, then the Windows code page that
fits. Prose in Hungarian, Italian, Polish, Czech, Slovak, Romanian, Croatian, Finnish and the Nordic languages is no
longer marked unreadable. **Newly added documents only; can change results.**

**Text recognition.** *Stop* now stops the text recognition of a long scan (it waited for every page), and scanned
pages of PDFs read with the fallback reader are now recognised (an extra empty page turned recognition off).

**Files picked while documents are being added are kept.** They were dropped without a word when the first run ended
(or added unannounced). *Add* now stays off during a run, and new picks wait for the next one.

### The app

**Notes typed on a waiting result are kept.** While a check waited for Claude Code, the page rebuilt itself every five
seconds, notes box included, so what you typed was lost. The page now waits while you type, and the note is saved when
you click away or leave.

**When ENLENS stops, the page says so.** The Overview said the project had no documents, and other pages went quietly
empty. A banner now says ENLENS has stopped answering and offers to reload, and the pages show the failure.

**More fixes on the pages.**
- The documents table fits the window: *Open* and *Remove* were out of sight at most desktop widths.
- The answer card says when excerpts from documents no AI may read wait for your judgement, and says in words (not
  only colour) where a colleague judged differently from you.
- The panel of work waiting for Claude Code scrolls into view.
- A result opened after another window switched project offers to switch to its project.
- *Check several* marks and skips lines too short to check, numbers failures correctly and no longer shows a waiting
  spinner when it is done.
- The *Let the auditor use Fable* switch saves when you change it, and unsaved settings are marked.
- Search, Profile and Concepts say *Add documents first* in an empty project.
- *Quick look* accepts the Word files its file picker offers.
- "No stronger model is set" now says why: already on the strongest model of your plan, routing off, or one local model.
- Smaller fixes:
  - *Skip to content* works;
  - the Profile grid's cells and help notes with a button work from the keyboard;
  - the phone menu keeps focus;
  - faint labels are easier to read;
  - Search's per-document buttons have a label;
  - Profile explains its two counts;
  - the bring-in dialog stays open until the merge is done;
  - the first-run screen fits a narrow window.

**One Claude Code run per project, stopped on Quit.** Pressing *Start Claude Code* twice, or in two windows, could
start two runs on your plan, and *Stop* reached only the last. There is now one run per project. *Quit ENLENS* and
*Update and restart* left a run going on your plan, which the reopened app could neither see nor stop; they now stop
it first, and an app opened while a run is still going shows it and can stop it.

### Installing and updating

**The Claude Code plugin follows the update.** Updating a one-line install (the app's *Update* button, `enlens update`
or the install line again) left the plugin, and so Claude Code's instructions for ENLENS's tasks, at the old version.
ENLENS now notices, writes it again and has Claude Code take the new copy (`claude plugin marketplace update`,
`claude plugin update`).

**Other fixes.**
- A git copy whose new requirements failed to install (offline, say) is finished by the next update; before, the next
  update said "up to date".
- A copy still running after an update on disk keeps serving the page it started with, instead of the new page
  against its old code.
- The look for a new version can no longer hang on a password prompt.
- On Windows, the Claude Code sign-in and the icon's fallback command work when the user name has an accent (Kovács).

### For developers

- `.github/workflows/tests.yml` runs the tests on every push and pull request to `main` (they ran only on a release
  tag).
- `tools/dev_server.py` never finds the real Claude Code any more: `--claude-code` and `--claude-code-paused` used the
  `claude` on the PATH, read the signed-in account, and *Start Claude Code* would have started a real run.

**Tests:**
- `tests/test_0_14_3_check_status.py` (34 tests)
- `tests/test_0_14_3_privacy_and_sync.py` (20)
- `tests/test_0_14_3_explore.py` (18)
- `tests/test_0_14_3_pages.py` (17)
- `tests/test_0_14_3_setup_and_update.py` (21)
- `tests/test_0_14_4_runs_on_linux.py` (2): a run with a command line longer than 80 characters is recognised;
  another program with that process number is not

Changed tests: `tests/test_0120_results_page.py` (the answer card's caution is built in two parts); `tests/test_0110_upgrade.py::test_the_headless_run_is_closed` (each project's run has its own folder); `tests/test_text_and_taxonomy.py::test_quote_tolerates_pdf_spacing_but_not_paraphrase` (it asserted that "well placed" matches "wellplaced", the word-joining defect); `tests/test_hypotheses.py` (a quote that cut a word; the new prompt version) and `tests/test_0_13_6_task_kinds.py` (the new prompt versions). `tests/fake_claude_cli.py` answers the two plugin update commands.

**Not yet done:**
- On a computer shared by several users, any of them can still read the app's access key from its first page. A fix
  needs another way to hand the key to the browser.
- Not tried on Windows: renaming a project being imported, long paths, stopping a run with `taskkill`, and the PowerShell
  and `cmd` code pages. The written bytes and the logic were checked.
- Not run for real:
  - the Claude Code plugin refresh (checked against the real `claude plugin` help, run with a stand-in);
  - Tesseract on a long scan;
  - real AES-encrypted zips;
  - a real remote embedding server.
- A copy still running after an update can still load new Python modules it had not used yet.
- The new test workflow runs on Linux and Python 3.12 only; Windows, macOS and Python 3.10–3.11 are not in it yet.
- The Profile grid's code names still show only on hover at phone width.
- *Settings* and *Projects* show only the banner when ENLENS has stopped.
- A single short line of Hungarian saved in Windows-1250 can still be read as Windows-1252 (õ for ő); a few
  sentences are read correctly.
- When you have made no judgement of an excerpt and a colleague's judgement with a comment is in force, the
  page shows their comment as *Your comment* (older than this release).

## 0.14.2 (November 2026): the theme is a small icon beside Settings

**The theme is a small icon beside Settings.** The *Theme: system* button at the foot of the sidebar took a row of its
own; it is now an icon at the end of the *Settings* row: a screen (follows your computer), a sun (light) or a moon
(dark). A click goes on to the next one, as before, and the tooltip says which is in use and what a click does. The
choice is kept as before. On a short window the sidebar's foot needs one row less. Nothing here can change results.

The sidebar foot's style rules moved from the 0.10.1 stylesheet into the shared `app.css`.

**Tests:** `tests/test_0_14_2_theme_icon.py` (3 tests): Settings and the theme icon share one row, with *Update* and
*Quit* below it; the icon has no visible label but a name for screen readers and a tooltip, and keeps the stored
choice; the row's CSS uses only the colour tokens.

## 0.14.1 (November 2026): the one-line install works on a Mac again

**The one-line install stopped after its first step on most Macs** (since 0.10.0). In a Terminal that uses a UTF-8
language setting (the usual one, such as en_US.UTF-8 or hu_HU.UTF-8), it ended with "line 65: VERSION…: unbound
variable" before downloading anything; only `curl ... | LC_ALL=C sh` got through. macOS's `sh` took the "…" printed
after the version number for part of a name. The install script now uses plain ASCII only. Linux and Windows were not
affected. Nothing changes for an ENLENS that is already installed (`enlens update` does not use this script), and
nothing here can change results.

**A failed install now says it failed.** After that error, macOS's `sh` still ended with exit status 0 (success): it
runs the script's clean-up step with the status already reset. The script now ends as a failure whenever it stops before
its last line, removes its temporary folder either way, and stops at once on Ctrl-C. Found while testing the fix.

**Why no test saw it.** Linux's `sh` reads the script as intended, the release's tests run on Linux, and the release's
macOS install job installs the package it has just built, which skips the download step where the script stopped.

**Tests:** `tests/test_0_14_1_mac_install.py` (6 tests): `install.sh` is plain ASCII; the install line, piped into `sh`
as people run it, downloads, checks and installs in an en_US.UTF-8 and a hu_HU.UTF-8 language setting and leaves no
temporary folder; an unbound variable, a failed command or `fail` part-way ends with a failure status, installs nothing
and leaves no temporary folder (stand-ins for uv and curl). All six fail on 0.14.0's script on a Mac. On Linux only the
ASCII test can catch the first defect. `tests/test_0_14_0_shared_projects.py`: the withdrawn-number test checks the
running version instead of requiring 0.14.0.

**Not yet done:** the fixed script was tried for real on a Mac in an en_US.UTF-8 setting, in scratch home folders with
the real uv: with the 0.14.1 package built here, and through the download step with the published 0.14.0 package (where
0.14.0's own script stops at line 65). The 0.14.1 package can only be downloaded once this release is published: then
run the install line once on a Mac in a normal Terminal window.

## 0.14.0 (November 2026): work on a project together

Researchers asked to work on one project with a colleague, each on their own computer and their own Claude plan.
Until now a project zip could only become a new project, so two people's work drifted apart as soon as both went on.

**Each of you keeps a copy, and you exchange your work as a file.** *Download as a zip* (as before) is the file you
send. Your colleague makes their copy once with *Import a project (.zip)*; from then on each of you chooses *Bring in
a colleague's work* on the same project and picks the other's newest file. There is no server and no account: the
file goes where you send it, and bringing it in sends nothing anywhere. A short report says what came in. A file of
another project (or from an ENLENS before 0.14, which cannot say) is brought in only after you confirm. A file
brought in twice changes nothing, and two people sending files back and forth end up with the same project.

**How the copies come together.**
- What is new comes in: documents with their original files, results, sets of themes, codebooks (also those kept for
  all projects), the AI's labels and reference chains, links between terms, the bibliography, and the SDG pack's and
  add-ons' rows.
- A result, set of themes or codebook that only one of you changed since you last exchanged it is brought up to
  date. ENLENS remembers each state that was sent or brought in, so it can tell a newer version from one you both
  changed.
- **Sync clash.** When you both changed it, your colleague's version comes in beside yours, marked *sync clash ·
  Anna's version* in the *Results* list and on the result (with a link to the other version), and on the *Projects*
  page. Nothing is replaced: each of you keeps your own version, with the other's beside it. When your colleague
  changes their version again, the copy you have of it is brought up to date (no third copy). To settle a clash,
  delete the version you do not want: the mark goes, a deleted copy does not come back unless they change it again,
  and when you kept their version, it goes on following theirs.
- **The same file, read into other text** (another ENLENS version, or text recognition on one computer and not the
  other): quotes are places in the text, so your colleague's reading comes in as a document of its own, marked *sync
  clash · Anna's reading*, and their results point at it.
- **Each person's judgements.** A judgement of an excerpt is kept under the name of who made it (*Your name*, on the
  *Projects* page). Yours count in your copy; where you have not judged an excerpt, the latest colleague's judgement
  counts and the card says *Anna's judgement*. Where others judged it too, the card says *Also judged: Anna
  contradicts*, marked where you differ. *Take back* removes only yours. The answer says *reviewed by you and Anna*.
  The *Projects* page says how often you and each colleague judged the same excerpts alike, with Cohen's kappa from
  10 excerpts on. *How often you agreed with the AI* counts only your own judgements, and the Excel download says
  who judged each excerpt.
- **Each person's reviews** of labels, links between terms and themes: yours count over a colleague's; *Clear* and
  *Undo* take back only your own.
- AI work you both did on the same document (labels of a codebook, reference chains) is not doubled: yours is kept.
- **Who may read a document with AI: the stricter setting wins**, with a line in the report. When your colleague's
  copy let Claude read a document you keep from Claude, the report says how much it read there.
- **What you removed stays removed**: a document, result or set of themes you removed does not come back. When your
  colleague removed one you still have, the report names it and leaves yours alone.
- A check still running in your colleague's copy comes with a later file.
- Before bringing work in, the project's database is copied to `backups/before-bringing-in.sqlite`.

**For developers.** New modules `sync.py` (`bring_in`, `before_sending`, `peek`, `summary`, `overview`, `copies_of`,
`NotThisProject`) and `people.py` (`me`, `my_name`, `record`, `refresh`, `adopt`, `others`, `agreement`,
`review_order`, `mine_sql`). New tables `people`, `judgements`, `sync_seen`, `sync_copies`, `sync_removed`,
`sync_log`; new columns `verifications.user_by`, `reviews.person_id`, `documents.text_fp`; `meta` `project_uid`
(`Workspace.project_uid()`), `Workspace.removed()`. `claimcheck.set_judgement` writes the person's judgement and
works out the one in force; removing a document, a check or a theme run notes it in `sync_removed`, and adding the
file again takes the note away. `bundle.export_project` stamps `bundle.json` with `project_uid`, `from` and
`sent_at`, and adds the home-folder codebooks the project uses. Settings `your_name` and `person_id`. Command line:
`enlens --ws <folder> bring-in <zip> [--anyway]`. API: `POST
/api/projects/<p>/bring-in` (409 with `not_this_project`, `?anyway=1`), `GET /api/projects/<p>/together`; `clash` on
rows of hypotheses, documents and theme runs, `clash` and `clash_copies` on a result, `judged_by` and `others` on each
excerpt; an `ApiError` can carry more fields (`extra`), and the page keeps them on its error (`e.data`). A feature
`together` in `features.js`, an icon `users`. `update.WITHDRAWN` no longer lists 0.14.0, now a release.

**A shorter README.** README rewritten as a short front door (install, update, what's new, how to cite, privacy); its
detail moved to docs/MANUAL.md and the new docs/DEVELOPING.md.

### Defects, tests, and what is not done

**Found in review and fixed before the release.** An independent review of the merge found eight defects in the first
version; each now has a test. A crafted file could make ENLENS copy any file of the computer into the project (and
so into the next file you send), or write outside the project: a document id is now never a path, and an original
file is copied only from the colleague's zip and only when it is the file the document was read from. Another reading
of a file you keep from AI came in as *Claude may read it*; it now gets your setting of that file. A judgement or
review you took back came back with a colleague's file; taking one back is now kept, and goes from their copies too.
After a sync clash, exchanging files back again replaced your own version with your colleague's and left yours as an
unmarked copy; now each keeps their own and the marks travel. A codebook both of you changed doubled your
colleague's labels when the same file was brought in twice. Excerpts of a copied check had ids the app could not
find again (a stronger model's reading would have added a second row). Another reading of a file showed its
original as *changed since it was added*. Starting over left theme runs that a colleague's file could bring back.
A second review of these fixes found four more, also fixed with a test each: a crafted file could still place a file
in the project folder through the fingerprint of a document's text (fingerprints are now always worked out here, and
a file can only go into the project's `originals`); keeping a colleague's version to settle a clash left it behind
their later changes and brought your deleted version back; a review taken back stayed where its label had another id
in your copy; a check that read a document one of you removed was *brought up to date* at every exchange.

**Tests:** `tests/test_0_14_0_shared_projects.py` (31 tests): the file says which project and who sent it; a
colleague's check and judgements come in under their name, yours win, taking yours back lets theirs count again, and
the agreement and the AI-agreement chart count the right judgements; a file brought in twice changes nothing; a check
changed on one side is brought up to date, both ways; a check both changed comes in as a sync-clash copy, once, and
two people exchanging files end up with the same two versions; the same file read into other text comes in as a
document of its own with the check pointing at it; the stricter AI setting wins with both warnings; removed
documents and checks do not come back, and a colleague's removal is reported; new documents come with their files
and step the corpus on; a file of another project only on purpose; judgements from before 0.14 are the sender's;
label reviews per person (*Clear* takes back only yours); the copy before the merge; the app's two routes, with the
409; the command line; Cohen's kappa; and one test for each defect found in review (a crafted file, another
reading of a file kept from AI, judgements and reviews taken back, each keeping their own version after a clash and a
copy brought up to date, a codebook both changed, excerpt ids made the app's way, the original of another reading,
starting over, a crafted text fingerprint, settling a clash by keeping theirs, a review taken back under another
label id, a check that read a removed document). `tests/test_0_13_6_version_numbers.py`: 0.14.0 is no longer a withdrawn number.
`tests/test_0120_results_page.py`: the answer says who reviewed it (*reviewed by you*, or *by you and Anna*).
`tests/test_0_13_7_local_model.py`: the 0.13.7 line it looks for is now in the changelog, not the README.

**Not yet done:** tested with two simulated people on one computer (two ENLENS folders) and in the browser with the
dev server; not yet between two real computers with real Claude Code. There is no button yet to keep one version of a
sync clash and remove the other in one go (open each and delete the one you do not want). The vectors of search by
meaning are not brought in: your computer makes them for the new documents. A project zip moved to a new computer as
a single project (not with *Move ENLENS to another computer*) makes you a new person there. A colleague's file is
trusted with what people decided: a crafted file could take back judgements or reviews made under your name in your
copy (nothing it holds can reach files outside the project, change who may read a document to a less strict setting,
or replace what you decided with its own). Bring in files only from the colleagues you work with.

## 0.13.11 (November 2026): the local model shows itself, and waits for room

Found in a user test. With Claude Code as the AI, a check whose most important document was marked *Only a local AI*
loaded a 7.6 GB local model on a 16 GB Mac that had 2.7 GB free. The computer all but froze for several minutes (and
was still 7.7 GB into swap afterwards), while the page said only *Waiting for Claude Code*.

**You see the local model at work.** While Claude Code reads its excerpts, the progress now says *Your local model
(qwen3.5:9b) is reading 3 excerpts from documents marked Only a local AI, on this computer*, with what the model is
doing (starting, thinking, writing) and its time, and Stop stops it. Until now it read unseen: the page went on
showing Claude Code's queue, and the job could even look *on hold*. The same line shows on the Claude API, and *Read
them now on this computer* gives way to it with Stop (the button only greyed out for minutes before). The note at the
end says what happened; when no local model could be used, it no longer says the excerpts *were read on this
computer*. A check whose only waiting excerpts are the local model's now says *Waiting for your local model* (on the
result, each part, the Results list and the map), no longer *Waiting for Claude Code* when Claude Code is done.

**Not started without room for it.** Before the local model for documents marked *Only a local AI* is loaded (on
Ollama), ENLENS compares what it needs (its size plus its working memory at the context length used) with the memory
this computer has free, counting the memory of other models Ollama would let go of. When it clearly cannot fit, it is
not started: *qwen3.5:9b was not started: it needs about 8.1 GB of memory, and this computer has about 2.7 GB free
now…*, with what to do (close programs, or choose a smaller local model). In a check, Claude's part finishes and those
excerpts wait, so the check ends instead of waiting for nothing; *Read them now* tries again, and when it is still
short, *Start it anyway* lets you decide. Taking the waiting checks out of the queue no longer removes such a check:
Claude's answers are kept. The check is a lower bound, so it only stops a model that clearly cannot fit. A local
model you chose as the main AI is not checked (you start it yourself, and see it load), nor is a model on LM Studio
or another OpenAI-compatible server, which has its own guard.

**Memory given back.** A local model that takes more than a third of this computer's memory is let go as soon as it
has read the restricted excerpts of a check (of a whole set, for *Check several*), instead of staying loaded for 15
minutes.

**For developers.** `llm.MemoryShort` (a `BackendError`), `llm.free_memory()`, `llm.total_memory()`,
`OllamaBackend.memory_guard` (on for the restricted-documents model, set in `home.make_restricted_backend`),
`memory_need`, `is_loaded`, `check_memory`. `access.Readers` takes `progress`, `should_stop` and `check_memory`, and
has `memory_short`, `read`, `used`, `stopped()` and `free_memory()`. `server.wire` also sets `local_progress` and
`local_should_stop` on the backend. `claimcheck.local_waiting`, `only_local_waits`, `run_local_parts(…, on_start)`,
and `check_hypothesis(…, readers)` (`check_batch` shares one). `Tracker.say`; a note with `{"keep": True}` stays
through a batch; a model report with `"who": "local"`. Jobs end with `error_kind: "memory"`. `POST
…/hypotheses/<id>/read-local` takes `{"force": true}`, and its job has a progress and the result as its `scope`.
Withdrawing checks (`POST …/queue/withdraw`, `enlens queue withdraw`) skips those where `only_local_waits`. A
result, each of its parts, a Results row and a map row carry `status_text` *Waiting for your local model*
(`claimcheck.WAITING_LOCAL`) when only the local model's excerpts wait (a Results row has `status_text` null
otherwise). `tools/dev_server.py --low-memory`.

### Defects, tests, and what is not done

**Defects fixed on the way.** Taking the waiting checks out of the queue (*Remove* in the queue panel, or `enlens
queue withdraw check`) removed a check whose local excerpts still waited, Claude's answers included. When the local
model could not be used, the progress said its excerpts *were read on this computer*; it now says why they wait for
your judgement. The steps of a check by queue were shown one poll late, so *Waiting for Claude Code to propose other
words* still showed while the local model read the excerpts; they are now brought up to date first. A test that did not set its own ENLENS folder read the researcher's real settings (on a Max plan,
two tests of 0.13.6 expected Haiku and got Opus); every test now has a folder of its own.

**Tests:** `tests/test_0_13_11_local_memory.py` (17 tests): the progress names the local model while it reads, on
Claude Code and on the Claude API; a check by queue with no room ends once Claude Code is done, its local excerpts
waiting (not handed to you), and *Read them now* refuses again until *Start it anyway*; Stop leaves them waiting; a
large model is let go after reading and a small one kept; a set of checks loads the local model once; withdrawing
waiting checks keeps a finished one; Ollama's memory check (refused before anything loads, the memory of other loaded
models counted as free, `:latest` names, nothing known: no refusal); the guard on for the restricted-documents model
only; memory figures on this computer; a job refused for memory says so in plain words; notes kept through a set;
*Waiting for your local model* on the result, its part, the Results list and the map. Checked in the app with the
dev server (`tools/dev_server.py --mixed --claude-code`, and `--low-memory`, new: 2.7 GB free and 8.1 GB needed) in
light and dark and at 390 px: the progress while the local model reads, the waiting excerpts, *Read them now* →
*Start it anyway* → the local model reading with Stop.

**Not yet done.** Tried with stand-in models only, and the memory figures on macOS. Loading a real model with too
little memory free was not repeated on purpose. A local model on LM Studio or another OpenAI-compatible server is
not checked for memory (LM Studio has its own guard).

## 0.13.10 (November 2026): how fast Claude Code works, and models that suit your Claude plan

Two additions for Claude Code: a speed beside every *Start Claude Code* (with the helpers of one run to choose, folded
away), and recommended models that follow your Claude plan by themselves.

### Faster or slower, and which helpers

**Faster or slower, beside every Start Claude Code.** Claude Code hands ENLENS's work to helpers, one per kind of
task, each on its own model. Until now it always ran two at once, unless you typed `/enlens-run … --parallel N`
yourself.
- **Speed: Slower · Normal · Faster** sits under every *Start Claude Code* (a check's progress, a result that waits,
  the sidebar's queue panel) and under *Settings → AI → Speed of Claude Code*: one, two or four helpers at once. The
  line beside it says what it does: Faster is done sooner but uses your plan's limits faster; Slower is easiest on
  them. The choice is kept, and the estimates follow it. *Claude Code is working on it* says how many helpers the run
  has.
- **Choose the helpers for this run**, folded away under the speed, lists each helper with work waiting: its model,
  what it would answer and how much waits. Set how many of each work at once (0: that work waits for a later run) and
  how many in all (1 to 8); *Use the speed again*, or picking a speed, undoes it. It holds for one run, and work that
  comes in during the run for a helper not listed (an unsure answer for the auditor, for example) gets one helper.
  When the sidebar shows it twice (the job that waits and the queue panel), a choice made in one shows in the other,
  and the queue panel waits (half a minute at most) while one of its lists is open.
- A typed `/enlens-run` without `--parallel` now goes at the speed chosen in the app, and takes `--helpers
  checker=2,labeller=1` too.

**How it works.** ENLENS now does the sums: `/enlens-run` passes its `kind`, `--parallel` and `--helpers` to the
connector's `queue_status`, and each group says how many helpers to start for it (`start`): one per group in the
queue's order, then more for the groups with more work, never more than a group has batches. The skill starts what
`start` says and asks again only when all its helpers have reported back, so a run never has more helpers at once
than chosen. Before, the model running `/enlens-run` shared the helpers out itself ("a large group can have two
helpers at once"), so four at once on one kind of task did not happen.

**For developers.** Settings' `claude_speed` (`slower` | `normal` | `faster`). `GET …/queue` adds `speed` (the
choice, the helpers at once per speed, the helpers with work waiting) and `start` on each group. `POST
…/queue/claude-code` takes `{"parallel", "helpers"}`; the run's object adds `parallel` and `helpers`. The connector's
`queue_status` takes `kind`, `parallel` and `helpers`. In `taskqueue`: `SPEEDS`, `run_plan`, `run_status`,
`plan_helpers`, `helper_rows`, `clean_helpers`, `clean_parallel`. `claude_setup.run_args(project, claude, plan)` and
`start_run(project, parallel, helpers)`. The stand-in Claude Code (`tests/fake_claude_code.py`,
`tests/fake_claude_cli.py`) follows `start`, `--parallel` and `--helpers`. `docs/API.md` and the manual's *Start
Claude Code* describe it.

### Models that suit your Claude plan

**The recommended model of each task now follows your plan, by itself.** ENLENS finds the plan Claude Code is signed
in with in the background (from `claude auth status`, when the app starts, when it looks at the queue and before a
run) and routes every task by it, also the work that already waits:
- **Free:** no Opus or Fable. Haiku for most tasks (search words, splitting a hypothesis, theme names, references, as
  well as labels and links), stepping up to Sonnet when unsure; judging excerpts, second opinions and the SDG pack's
  reference claims on Sonnet, with nothing above.
- **Pro** (and a plan not known yet): as before, Sonnet for most tasks and Opus sparingly (second opinions, the hard
  cases, the SDG pack's reference claims and checks).
- **Max, Team, Enterprise:** Opus for most tasks, checks included. Haiku and Sonnet only where many tasks come at once
  and speed matters: labels and links (Haiku), references and the SDG pack's extraction (Sonnet, stepping up to Opus).
  A check that starts on Opus has no stronger model unless *Let the auditor use Fable* is on.

Models you chose per task in *Settings → Technical → AI model per task* come first on every plan. That section now
says which plan the recommendations follow (*Your plan, as Claude Code says: Pro*), with a choice by hand for when
Claude Code names it wrongly or not at all. On a Free plan the auditor's name (*Get a second opinion*) and the Fable
switch say Sonnet. The Claude API and local models do not follow the plan.

**For developers.** Settings' `claude_plan` (`auto` | `free` | `pro` | `max`) and `claude_plan_detected` (written by
`claude_setup.note_plan`, not carried to another computer). `routing.plan_tier`, `tier_defaults`, `settings_tier`,
`Router.tier`; a task kind's `bulk` (label, link, resolve, extract; an add-on's kind can set it). `GET /api/routing`
adds `plan`, and each row's `recommended` names the model (the auditor resolved), with `recommended_role`.
`docs/MODEL_CHOICE.md` has the rules per plan.

### Defects, tests, and what is not done

**Defects fixed on the way.** A plan of helpers that asked for more at once than the helpers named add up to (`--parallel
8 --helpers checker=1`) said *8 helpers at once*: it now says what the run can really have. A decimal number of
helpers (2.5) was cut down without a word: it is refused.

**Tests:** `tests/test_0_13_10_helpers_per_run.py` (15 tests): the helpers shared out in the queue's order for each
speed, never more than a group has batches; named helpers start as many as named and the others wait (`not_this_run`);
the plan checked (unknown helpers, 0 to 4, at least one, whole numbers); a plan without numbers follows the speed of
Settings; the connector's `queue_status` with `kind`, `parallel` and `helpers`, also through MCP; the command the app
starts carries `--parallel` and `--helpers`; Start Claude Code at the chosen speed and with helpers chosen for the run
(the stand-in Claude Code answers only their work); the skill follows `start`; the page offers the speed and the fold.
`tests/test_08_queue.py` expects `start` on each group. `tests/test_0_13_10_plan_models.py` (10 tests): plan names
to tiers; Pro and a plan not known keep the table of 0.8; Free has no Opus or Fable anywhere and more Haiku; Max
favours Opus and keeps the fast models for the bulk, a check on Opus steps up only to Fable; models chosen by hand come
first; the Claude API and local models ignore the plan; the plan found in the background (and on start), kept while
signed out, beaten by a plan set by hand, not moved to another computer; waiting work follows a new plan;
`/api/routing`; the page.

**Not yet done.** Tried with the stand-in Claude Code only. Whether a real, signed-in Claude Code starts exactly
`start` helpers at once (and waits for all of them before asking again), and how much faster four helpers make a large
run on a Pro or Max plan, still needs a real run. The helpers' models are chosen per kind of task in Settings as
before; there is no model choice for one run. The plan is read from what a real Claude Code reports as
`subscriptionType` in `claude auth status` (as since 0.11, for the account line); only the stand-in's values were
tried (free, pro, max, team), so a real value spelt otherwise leaves the recommendations as for Pro until it is set
by hand. Claude Code may not run on a Free plan at all; the Free recommendations are there for when it does.

## 0.13.9 (November 2026): only the Zotero works you choose, and a new theme in place of one you remove

Two additions: the *Bibliography* page brings in just the Zotero works you choose (even a single one), and on
*Themes* you can remove a theme you do not need and let ENLENS find a new one in its place. (The theme work was
first written down for a 0.14.0; 0.14.0 stays withdrawn, so it comes out in 0.13.9.)

### Only the Zotero works you choose

Until now the *Bibliography* page brought in a whole Zotero collection or the whole library. A group library without
collections offered only *The whole library*, and there was no way to bring in one paper. 0.13.9 lets you choose the
works one by one.

**What is new.**
- **Choose the works one by one.** Under *Library* and *Collection*, tick *Choose the works one by one*: a list of the
  library's works appears (or of the collection chosen above, without its subcollections), by title, each with its
  authors, year and type. Search it by title, author or year: it is Zotero's own quick search, so it finds what the
  search box in Zotero finds. Ticked works stay ticked while you search or switch collections, and stand above the
  list (click one to leave it out). The button says what it will do: *Bring in 1 work*, *Bring in 3 works*. The first
  100 works are listed; past that, the page says to search. Changing the library starts the choice afresh, as a work
  belongs to one library. A choice is 1 to 500 works.
- **Keeping it up to date.** The summary says *From Zotero: My Library › 3 works you chose*. *Update from Zotero*
  reads those same works again (titles, authors, DOIs and files edited in Zotero follow). A chosen work you delete
  from Zotero goes, and a work added to Zotero does not come along. *Choose other works or a file* (in place of *Use
  another collection or file*) opens the choice with the works chosen last time already ticked, so adding one more is
  one tick away. As always, your confirmations are kept for every work that stays.
- The files Zotero keeps for chosen works (a PDF attached to a work, or a PDF stored on its own in the library) come
  along as for a collection: linked by checksum to a document you have, or offered under *Add these files to the
  project*.

**For developers.** `GET /api/zotero/works?library=&collection=&q=&limit=` lists the top-level works (no notes) by title,
with `more` past the limit (`bibliography.zotero_works`). `POST …/bibliography` takes `{"zotero": {"library",
"items": [keys]}}`; the bibliography's source keeps `items` (the keys Zotero still had), and `{"update": true}` reads
them again (`bibliography.pull_zotero(items=)`, 50 keys per request with `itemKey`). Zotero 10's local API also
returns the children of the works asked for with `itemKey`, and leaks child items into `/items/top` when filtered
with `itemType=-note`: only the works asked for count, and the list filters notes itself.
`bibliography.type_text()` names a work's type for both lists. `docs/API.md` and the manual's *The bibliography:
Zotero* describe it. The stand-in Zotero (`tests/fake_zotero.py`) answers `q`, `sort=title` and `itemKey` (with the
children, as Zotero 10 does).

**Tests:** `tests/test_0_13_9_chosen_works.py` (4 tests): the list of works (sorted by title, without notes or
attachments of works; searched by title, author or year; one collection without its subcollections; `more`; bad keys
refused); pulling
chosen works (in the order chosen, their PDF but not a publisher's page, children not taken for works, a deleted
work left out, none left an error, 0 or 501 works or a bad key refused); through the app (two works linked by file
and DOI, *Update from Zotero* reads the same works, one more work, a collection again, bad requests, Zotero closed);
the page's words and styles.

Checked in headless Chromium with `tools/dev_server.py --corpus social --zotero`: choosing by search, ticking across
searches, *Bring in 2 works*, the summary, and *Choose other works or a file* with the works ticked, in light and
dark and at 390 px, with no console errors. Then clicked through against a real Zotero 10.0.7, read-only: a group
library without collections (where only *The whole library* was on offer before), searched by author, two works
brought in and updated from Zotero; and pulled from it directly, a work with its PDF and a PDF stored on its own.

**Not yet done.** Not tried with a library of thousands of works (the list shows the first 100 and asks for a
search), nor with Zotero 7, whose local API answers `itemKey` without the children.

### Remove a theme, and find a new one in its place

**Remove a theme you do not need, and find a new one in its place.** A set of themes often has one or two that say
nothing about your question (running headers, reference lists, a topic outside your research). Now you can take them
out, and let ENLENS look for a theme it missed.
- **Remove…** on each theme (on the list and on its page) asks *Just remove it* or **Remove and find a new theme**.
  A removed theme's passages are left out of the themes, the grids and the Excel file; it waits under **Removed
  themes** at the foot of the list, crossed out, with **Bring it back**. Its page still opens, so a passage that
  matters can be moved into a theme you keep. The last theme shown, a theme merged into another, and merges or moves
  into a removed theme are refused.
- **A new theme in its place**, found on this computer without AI. Every theme shown is split in two
  inside itself (2-means, the set's seed); the half that fits its theme least well becomes a candidate, the one that
  draws most passages closer to it than to their own theme wins, and it is refined with every other theme fixed. It
  takes only passages the clustering placed (never one you moved), and never one closer to a theme you removed, so
  the removed theme does not come back under another name. The new theme is named by its key terms like the others;
  the themes it takes passages from keep their names (and new representatives where theirs moved). It is marked
  *new: found in place of “…”*, and its page says which themes its passages come from. *Find a new theme in its
  place* also sits beside each removed theme; once per removed theme (remove the new one to find another).
- *Let the AI name the other N themes* names a new theme without renaming the others. *Your changes* counts removed
  and new themes; they belong to that set of themes only (renames, merges and moves still apply again to a new set
  with the same settings).
- Excel: *Found in place of* on the themes, and a *Removed themes* sheet. The FlexiConc export leaves removed themes'
  passages out. The Overview counts the themes shown.
- `PUT …/themes/<run>/edit {what: "remove", theme_id, value: true|false}` and `POST …/themes/<run>/new {replaces}`
  (job `theme-new`); three new columns, added to a project when it opens: `themes.removed_at`, `themes.replaces`,
  `theme_members.found_in` (the theme a passage was in before a new theme took it).

**Tests.** `tests/test_0_13_9_remove_themes.py` (7 tests), on six generated topics in twelve documents: removing
and bringing back (left out of the list, the grids, the counts and the Excel themes; its page opens; a passage moved
out of it; merges and moves into it refused); the last theme and a merged one; a new theme by words (one topic, never
the removed one's, nothing of the removed theme, where its passages came from, representatives kept right, the same
result from the same set, once per removed theme, a second new theme in place of the first, renamed, named by the
AI); by meaning, on planted embeddings, a new theme that splits a mixed one; through the app (refusals, the job, the
export, bringing back); a project from before gains the columns; the page and its rules in `concepts-themes.css` (colour
tokens only). Checked in headless Chrome with `tools/dev_server.py` and the generated corpus: remove and find a new
theme from the list, the new theme's page, the removed theme's page, the removed themes in light and dark and at
390 px, bringing one back, with no console errors and no sideways scroll.

**Not yet done.** A removed theme's passages are not left out of search, the profile or checks: only out of the
themes. A new theme is not named by the AI by itself; press *Let the AI name the other themes*. When the passages
left fit their themes well (a small project, or themes of fewer than six passages), no new theme is found, and the
message says to find the themes again with more themes.

## 0.13.8 (November 2026): Check citations taken out again

After trying it, *Check citations* (0.13.7) does not fit ENLENS: ENLENS is for exploring your documents and checking
hypotheses against them, and checking a draft's citations is a task of its own. It continues as a separate project,
and 0.13.8 takes it out of ENLENS cleanly. Everything else 0.13.7 brought stays: a model on this computer without a
terminal, and the fix for add-ons below.

**What goes.**
- The *Check citations* page, its sidebar entry (between *Check several* and *Results*), its Overview card and its
  job in the sidebar. The *Check hypotheses* row of the Overview has its three cards again (the compact grid's rule is
  back in `v09.css`, as in 0.13.6).
- On the result page: the *In your text:* line, *Back to the citations* and the exception to the single-document
  caution, all only for checks of citations.
- For developers: `citations.py`, `views/citations.js` and its rules in `app.css`; the eight `/citations` endpoints
  (`docs/API.md`) and the job kind `citations`; the tables `cite_texts`, `citations` and `cite_refs` in the schema of
  new projects; `check_hypothesis(extra=)` and `queue_check(extra=)`; a check payload's `claim_context`, `cited` and
  `citing`, and the prompt's *THE CLAIM IN ITS TEXT* (the prompt is `check-v4` as before); `history(citations=)` and
  the filters that kept checks of citations out of Results, the evidence map and the downloads; `access.citing_level`
  and `access.text_floor`; `tools/dev_server.py --citations`; the manual's *Checking citations*;
  `tests/test_0_13_7_citations.py`. The code stays in the history (commit `50d4dfe`, tag `v0.13.7`).

**What stays.**
- **The fix for add-ons found while building it.** An add-on's floor (`access.register_floor`, 0.13.6) on a check's
  payload labelled the round as restricted, yet its excerpts were still routed by their documents' settings alone (to
  the main model, which refused them, or the queue never handed them out). A round still gives each excerpt the most
  restricted of its document's setting and the add-on's floor (`claimcheck._add_round`, now with `access.floor`
  directly), so it goes to the local model or to the person.
- **Your data.** Nothing in your projects is deleted. A project opened with 0.13.7 keeps the three tables, unused.
  Checks made by *Check citations* are ordinary checks now: they show under *Results*, in the evidence map, the
  downloads and the Overview's count; remove one with *Delete* on its result page. One thing to know: such a check of
  a draft marked *Only a local AI* or *No AI* no longer has the draft's setting to go by, so a Claude chat can list
  it through the connector and its unfinished tasks follow the documents' settings alone. Made one with 0.13.7?
  Delete it under *Results*.

**Tests:** `tests/test_0_13_8_citations_removed.py` (3 tests): an add-on's floor goes with every excerpt of a round
(local model, the person, or the main model for a note Claude may read; it fails without the fix); *Check citations*
is gone from the code, the page files, the schema, the prompt and the documentation, and the Overview's compact row
is as in 0.13.6; a project that used *Check citations* keeps its data and opens (its check under Results, opened,
counted and deleted like any other). `tests/test_0_13_6_page_extensions.py` expects the three cards of 0.13.6 again.

Checked in headless Chrome with `tools/dev_server.py`: the sidebar, the Overview and a result page, in light and dark
and at 390 px, with no console errors.

**Not yet done.** Nothing in 0.13.8 needs a real Claude Code or Zotero; the leftover data was tried with a project
made for the test, not with one that used *Check citations* for real.

## 0.13.7 (November 2026): check your citations against their sources, and a local model without a terminal

With the bibliography in place (0.13), ENLENS knows which work each of your documents is. 0.13.7 uses that to check the
citations in a text: a new page, **Check citations**, reads your draft (or a document of the project) for its
citations, takes the claim each one stands for with the sentences around it, and checks it against the cited work's
own document, and no other. A citation whose source says it is marked *Source accurate*; one whose source says only
part of it, says otherwise or does not say it gets a notice, with the excerpt that shows why. Every answer goes
through the quote check, opens on the result page where you can overrule it, and records how it was made. Finding
the citations uses no AI; the checks send what a check of a hypothesis sends, within the AI setting of your text and
of the source's document. And a model on this computer, the most private choice, no longer needs a terminal: ENLENS
notices Ollama when it starts and downloads a model with one button.

**Checking citations.**
- **A text to check**, three ways: paste your draft; choose its file (Word, PDF, text, Markdown, a saved web page),
  read on this computer and then deleted, so it never becomes one of the project's documents and never turns up as
  evidence in another check; or pick a document of the project. For a draft you say who may read it with AI, as for
  documents (*Claude may read it*, *Only a local AI*, *No AI*; the project's choice preselected, changeable later); a
  document keeps its own setting. The page asks for the bibliography first when the project has none.
- **What it finds**: author-year citations in brackets and in the sentence (*(Smith, 2020)*, *(Smith & Jones 2019;
  Lee et al., 2021a, p. 4)*, *(e.g., WHO, 2021)*, *Smith (2020) found that …*, *According to Lindqvist et al. (2025),
  …*, *Smith's (2020) survey shows that …*, *The World Health Organization [WHO] (2019) …*), and numbered ones (*[3]*,
  *[2, 4–5]*, *rose.[3]*) when the text ends with its numbered reference list (without it, the page says how many it
  could not read). The reference list is never read as citations, nor is *(Figure 3, 2020)*.
- **The claim and its context.** The claim of a citation in brackets is the words before it (from the sentence's
  start, or from the citation before it: *X rose (A), while Y fell (B)* gives *X rose* to A and *Y fell* to B); of a
  citation in the sentence, what follows it (*Smith (2020) found that X*: X; *WHO (2019) warned about X*: the whole
  statement). The claim is highlighted in its sentence. The sentences before it (up to 600 characters of the same
  paragraph) go to the AI as context, so it understands *it* and *this effect*; the prompt says the context is never
  to be graded or quoted, and the quote check would refuse a quote from it.
- **Which work.** By the first author's surname and the year: a second author decides between two works of one
  author in one year; *2020a* and *2020b* follow the order of their titles (as APA lists them); particles (*van der
  Berg* and *Berg*), accents (*Müller*, *Muller*), initials (*J. Smith*), organisations and their abbreviations (*WHO*)
  are matched; a word before the name (*In Sweden, Lindqvist (2025)*) is passed over. A work cited with another year is
  not taken but offered, since a wrong year is worth a look. A numbered entry is matched by its DOI, else its title
  with its first author. Citations not yet checked are matched again on every visit, so works and documents added to
  the bibliography later are used without adding the text again.
- **The answers.** *Check 12 citations* checks every citation that is ready, one check per cited work (three works
  in one citation: three checks), each against that work's document only, as *Check several* does (by Claude Code
  through the queue, or by the model of *Settings*; the job is in the sidebar and can be stopped). The page groups
  them: **To look at** (*Only partly supported by the source*, *Not found in the source*, *The source says
  otherwise*, *The source says both*, *Unsure*, *The check did not work* with *Check again*), each with the sentence,
  the cited work and the excerpt that shows the answer best, with its page; **Cannot be checked yet** (*Not in your
  bibliography*, with the works of your bibliography to choose from and *Not a citation*; *Which work is it?*; *Its
  source is not in the project*; *Its document waits for your confirmation*); **Source accurate**; and **Left out**
  (citations introduced by *but see* or *contra*, which are cited for another view, and those you marked; *Put it
  back*).
- **On the result page**, a citation's check says *In your text:* with its sentence, and that it was checked against
  the cited work only; *Back to the citations* leads to the citation. It does not warn that the answer rests on a
  single document, which it does on purpose. Your judgement of an excerpt changes the answer on the Citations page.
  The sidebar keeps *Check citations* lit.
- **Kept apart from your hypotheses**: checks of citations are not in *Results*, the evidence map, the Results
  downloads or the Overview's count of results. The Overview has a *Check citations* card (*4 citations checked*); its
  *Check hypotheses* row keeps its four cards on one line (the rule moved from `v09.css` to `app.css`).
- **Excel**: one row per cited work (#, page of your text, sentence, claim checked, citation, work, title, answer,
  quote from the source, its page, document).

**What leaves the computer.** A check of a citation sends the claim, its sentences and excerpts of the cited source.
A draft marked *Only a local AI* is read by the model on this computer only, also when Claude Code is your AI; one
marked *No AI* is judged by you (every excerpt waits for your judgement); a document keeps its own setting;
*local-only* turns *Claude may read it* into *Only a local AI*. Each excerpt goes to the reader allowed to read both
it and the claim. The AI is asked for search words only when the text may go to it. Every task about a claim is
labelled with the text's setting (and takes a new setting at once), and checks of a text Claude may not read are never
shown to a Claude chat through the connector.

**A model on this computer, without a terminal.** Switching to a privacy option has to be easy for anyone. A model on
this computer was not: the first screen said "This is the technical part… If that is not you, ask them" and listed
`ollama pull qwen3:8b` to type in a terminal, and Settings did the same.
- **Get Ollama, then one button.** With no model server running, *A model on this computer* (first screen and
  *Settings → AI*) shows three steps: get Ollama (free; *Open ollama.com*), open it, download a model here. The page
  looks again every three seconds while it is open and goes on by itself when Ollama starts. With Ollama running but
  no model, **Download qwen3:8b** (about 5 GB), with *Also nomic-embed-text* (about 0.3 GB) for search by meaning:
  a progress bar (*Downloading qwen3:8b (1 of 2)*, *2.1 GB of 5.2 GB*), *Stop* (Ollama keeps what it has and goes on
  from there next time), and a plain reason when it fails (no such model, not enough disk space, offline). Ollama
  fetches the model from ollama.com; none of the person's documents are sent, so it works with `--local-only` too.
- **Chosen when it is done.** On the first screen the downloaded model becomes the AI and is tested at once (*Working.
  The AI model answered.*, then *Next: your project*). The app makes the choice itself when the download ends, so
  closing the tab during a 5 GB download loses nothing; a choice the person made meanwhile stands. Coming back to the
  page during a download shows its progress again, and the sidebar lists it as *Downloading a model*.
- **The same download where a local model is missing:** *Local model for restricted documents* (Claude reads the
  rest; documents marked *Only a local AI* need a model on this computer) and *Settings → Documents → Search by
  meaning* (nomic-embed-text).
- **Fixed: "Use a local model" skipped the model step.** On the first screen it set the automatic choice, which
  counted as set up even with no model server running, so the person went straight on to the project and the first
  AI task failed. The automatic choice now counts as set up only when a model answers.
- Messages that sent people to a terminal (`ollama pull …` in a check's error, the model test, *Save and test*)
  point to the download in *Settings → AI* instead. The README, the manual (*Getting started*, *Settings*, *For whoever
  installs the app*) and `docs/API.md` say so.
- `POST /api/servers/pull` (a job of kind `model-pull`, one at a time, with `use`: `ai`, `restricted` or `embed`);
  `GET /api/servers` gains `suggested`; `llm.OllamaBackend.pull`, `llm.SUGGESTED_MODELS`, `llm.valid_model_name`,
  `llm.pull_error`. Only an Ollama that answers on this computer (or at the address in Settings) is asked.
- `tools/dev_server.py --ollama [empty|later|none]`: an Ollama with no model (its download takes 12 s), one that
  starts 15 s after the app, or none.

**Defects fixed on the way.**
- For developers: an add-on's floor (`access.register_floor`, 0.13.6) on a check's payload labelled the whole round
  as restricted, yet its excerpts were still routed to the main model by their documents' settings alone (refused, or
  never handed out by the queue). A round now gives each excerpt the most restricted of its document's setting and
  the text's (`access.text_floor`), so it goes to the local model or to the person.

**For developers.** `citations.py` (finding citations, their claims and context, matching with the bibliography,
the view, checking), tables `cite_texts`, `citations` and `cite_refs`, eight endpoints (`docs/API.md`, *Checking
citations*), the page `views/citations.js` and its rules in `app.css`. `check_hypothesis` and `queue_check` take
`extra` (kept with the check's options); a check's payload carries `claim_context`, `cited` and `citing` for a claim
from a citation (the prompt shows the context after the claim, as data, like a reader's note: the prompt version
stays `check-v4`). `claimcheck.history(citations=False)` leaves checks of citations out; `access.citing_level` and
`access.text_floor`. A removed document takes the texts read from it along. `tools/dev_server.py --citations`: the
remote-work demo with its Zotero library brought in and a draft to check; the stand-in models of the tests leave the
claim's context out of their reading, as a model is told to.

**How releases are made.** From 0.13.7 a release adds no stylesheet of its own: new rules go into the shared
stylesheets (`app.css`, or the stylesheet of the view it changes), and rules it changes in an older per-release sheet
move there, the sheet going once it is empty. The Update button's rules moved from `v0136.css` into `app.css` (the
sheet is gone), and the Overview's compact grid from `v09.css`. Test files are named `test_<X>_<Y>_<Z>_<topic>.py`;
the 0.13.6 files are renamed so (`test_0136_addons.py` became `test_0_13_6_addons.py`, and likewise its task kinds,
page extensions, update check and version numbers); older ones keep their names.

**Tests:** `tests/test_0_13_7_citations.py` (19 tests): finding citations in a draft (two in one sentence, *According
to*, *found that*, *but see*, a heading, *(Figure 3, 2020)*) and harder ones (several years, initials, *e.g.* with a
page, two works in one bracket, *However, Kim (2017)*, an organisation with its abbreviation, a possessive,
particles); numbered citations with and without their list; an author's reference list not read; matching works
(2020a/b, a second author, *et al.*, particles, accents, initials, organisations, abbreviations, a word before the
name, another year offered, DOI and title of a numbered entry); the state of each citation and a person's word on it;
a bibliography changed later; checking each work against its own document (the excerpts, the context in the prompt,
the answers, the best quote, kept out of the Results, nothing checked twice, a work chosen again); a person's
judgement changing the answer; removing a text; a draft for *Only a local AI* (nothing of it reaches the stand-in
Claude, the local model reads it, hidden from the connector, every task labelled), for *No AI* (no model reads it),
a project document keeping its own setting (and removed with it), local-only; by queue (the context in the queued
tasks; a local draft kept out of the queue, without search words from Claude); through the app (every endpoint, bad
requests, a choice of work, *Not a citation*, the setting and the name, checking by queue with the stand-in Claude
Code, the result page's sentence, the Overview, Excel, a file uploaded and deleted, a document without citations,
removing); in the app with a model that answers at once (and one citation again; a citation's own Excel and the
Results' Excel); the page files (the sidebar entry between *Check several* and *Results*, the route, the registry,
colour tokens only, every route in `docs/API.md`); and the result page's link back and the job's row, in Node.
Checked in headless Chrome with `tools/dev_server.py --citations`: the list and the form, a draft before, during and
after checking, a citation's result page and the Overview, in light and dark and at 390 px, with no console errors.

`tests/test_0_13_7_local_model.py` (14 tests): a download reports its progress and the model then answers; what went
  wrong, in plain words (no such model, no disk space, offline, Ollama not running); stopping; model names (a name
  that is not one is refused); the download from the app (the job, its progress for two models, the names Ollama
  lists, the model test afterwards); the choice made when the download is done (the AI, the restricted model with
  Claude Code, search by meaning), even with the page closed, and a choice made meanwhile that stands; one download at
  a time and *Stop*; a failed download; only an Ollama on this computer is asked; allowed with `--local-only`; the
  messages point to the app; the page files (no terminal on a working screen, the first screen's fix). The stand-in
  Ollama (`tests/fake_servers.py`) lists no model when asked to and downloads with progress. Checked in headless
  Chrome with the dev server (`--ollama empty|later|none`, with and without `--empty` and `--claude-code`): the
  steps, Ollama noticed after it starts, the download, its progress after leaving the page and coming back, the
  choice after closing the tab, the test and *Next*; light, dark and 390 px wide, no console errors. Against the
  real Ollama 0.40.14 on this Mac: the message for a model that does not exist, and the start of a download, stopped
  at once.

**Not yet done.** A whole model downloaded by a real Ollama from the app (the tests use the stand-in; the real one was
asked only for a model that does not exist and for the start of a download), and the download on Windows and Linux.
ENLENS cannot install Ollama itself: getting it is still one download from ollama.com. LM Studio and the other
servers get no download button (their own apps download models). Citations: not tried with a real Claude Code or a real Zotero 7 (only the stand-ins); how well real models
judge a claim with its context is untested beyond the stand-ins. Footnote citations (Chicago notes), superscript
numbers and citations in a Word file's footnotes are not read; a numbered citation needs its reference list in the
same text. The claim is cut from its sentence by rules: a claim that opens with *it* relies on the context, and there
is no way yet to edit a claim before checking it. A citation of several works checks each work on its own, not the
claim against them together. A text that changed is added again (remove the old one). The connector (a Claude chat)
has no tool for citations yet.

## 0.13.6 (November 2026): updates that announce themselves, and room for add-ons

The *Update* button now appears only when there is something to install, with a pop-up that says so, and *Settings*
can look for an update by hand. Underneath, apps built on ENLENS (Margin is one) get room of their own: pages, jobs,
tables, rules about who may read their text and kinds of AI task, added in their own files instead of edits to
ENLENS's. Every answer still goes through the quote check, a person can overrule it, and nothing more leaves the
computer.

**Version numbers.** 0.14.0, 0.15.0 and 0.15.1 are withdrawn. They changed nothing for people using ENLENS (only what
an app built on it can add), so they did not call for new minor versions; their changes are part of 0.13.6, under
*Room for add-ons* below, and their commits keep their old titles. From now on a new feature, the overhaul of a whole
part of ENLENS or a large fix raises the minor number (0.X.0); other changes worth trying at once raise the last
number (0.X.y); small edge cases and background work wait for the next release.
- A computer that installed 0.14.0, 0.15.0 or 0.15.1 with the install line does not see 0.13.6 as newer: paste the
  install line once more. A git copy updates as usual.
- A copy of a withdrawn version that is still running counts as older (`update.WITHDRAWN`), so opening ENLENS from
  its icon quits it and starts 0.13.6, as after any update.

**Updates that announce themselves.**
- **The Update button shows only when there is an update.** ENLENS looks for a new version when the page opens,
  every two minutes after, and when you come back to a tab that was in the background. When it finds one, a pop-up
  in the corner says which version, with *Update and restart* and *Later*, and *Update to 0.13.7* appears at the
  bottom of the sidebar until you update. *Later* puts the pop-up away for that version. A look that fails (offline,
  a git copy edited by hand) stays quiet.
- **Check for updates** in *Settings → Technical → Updates*: look now, and read why a look failed. The version at the
  top right of every Settings tab opens it.
- **Light on GitHub.** For the one-line install, the app's look reads the newest version from GitHub's release page
  (where `…/releases/latest` redirects to), which GitHub's limit of 60 API requests an hour for each address does not
  count, so several computers in one office can look every two minutes; the API is asked only when the page does not
  say, and to install. The server keeps an answer for 100 seconds, so the open tabs share one look;
  `GET /api/update?fresh=1` looks again now. `enlens update --check` asks the API, as before.

**Room for add-ons** (docs/EXTENDING.md). Until now an app built on ENLENS had to edit ENLENS's own files to add a
page's API, a job, a table, a rule about who may read its text, a kind of AI task or a page: the route table, the job
lists, the database schema, the access checks, eight modules for a kind of task, the sidebar, `app.js`, the Overview
and the result page. Every one of those edits clashed with the next ENLENS release. Each now has an extension point,
so an add-on adds them in files of its own. ENLENS on its own is unchanged: every extension point is empty, and the
sidebar, the Overview, the job list and the result page look and work as in 0.13.5.

*The server.*
- **Routes.** An add-on module's `ROUTES` (method, pattern, handler) are tried after ENLENS's own, with the same
  token. A handler is a function `handler(h, *groups, q)` or the name of one of ENLENS's handlers. `DOWNLOADS` names
  the handlers a plain link may call with `?token=`.
- **Extra keys.** `state(app)` adds keys to `GET /api/state`, `overview(ws)` to a project's Overview. They never
  replace one of ENLENS's keys, and a hook that fails adds nothing (the page still opens).
- **A public interface for jobs.** `App.start_job`, `App.start_queued_job`, `App.follow_queued` and `App.wire` are
  the public names of `_job`, `_model_job`, `_follow_queued` and `_wire` (which keep working); `App.ws`,
  `App.backend` and `App.queue_mode` are documented as public. An add-on's job is listed in `/api/jobs` and the
  sidebar, can be stopped (its waiting tasks leave the queue), and is *not running* while its tasks wait for Claude
  Code with nothing answering them.

*The database.*
- **Tables and columns.** An add-on's `SCHEMA`, `MIGRATIONS` and `INDEXES` run in every project as it is opened,
  after ENLENS's own and in the same idempotent way (a column is added only when missing). Odd table or column names
  are refused.
- **Where a hypothesis comes from.** Hypotheses gain two columns, `origin` and `origin_id`, and
  `claimcheck.create_hypothesis` (the new public name of `new_hypothesis`, which keeps working) takes `origin=` and
  `origin_id=`, as do `check_hypothesis` and `queue_check`. *Check several* records `batch` and its batch id; a
  hypothesis typed by a person has none. Results and the history return both.

*Access.*
- `access.register_floor(fn)`: an add-on says how far a task's text may go because of what it knows about it (text
  the add-on manages, with an AI setting of its own). The task keeps the most restricted of that and its documents'
  settings: a floor can only restrict, never loosen, and one that fails counts as *No AI*.
- `access.register_hidden(fn)`: hypotheses the connector must not show; `list_checks` leaves them out and the other
  tools refuse to open them.
- Both feed the checks ENLENS already makes, so `local_only()` and the per-document settings still decide. ENLENS
  loads the add-ons before it labels a task, so a hook an add-on registers when it is imported always counts.

*One registry for the kinds of AI task.* A new kind of AI task touched eight modules: its schema (`schema.py`), its
prompt and prompt version (`prompts.py`), its store function (`tasks.py`), its models, step-up and Claude Code helper
(`routing.py`), its batch size, place in the queue and names (`taskqueue.py`), its name in *How these results were
made* (`runs.py`), its answer's token limit and offline answer (`llm.py`) and its size estimate (`home.py`). Each
kind is now described once, in `taskkinds.py`, and an add-on can register a kind of its own.
- **One definition per kind.** A `TaskKind` holds the name, prompt version and prompt builders; the answer's schema,
  where the quote check reads and the store function; the Claude models (first, steps up to), the local model, the
  helper, Settings' row; the batch size and place in the queue; the names (singular, plural, the queue's line, the
  run's name); the answer's token limit, the offline demo's answer and the size estimate.
- **The tables are built from it.** `routing.KINDS`, `ROWS`, `ROW_OF`, `CLAUDE_DEFAULTS`, `LOCAL_DEFAULTS`,
  `HELPERS`, `HELPER_MODEL`, `TO_AUDITOR`, `prompts.VERSIONS`, `tasks.KINDS`, `CORPUS_KINDS`, `HANDLERS`,
  `taskqueue.BATCH`, `ORDER`, `NOUN`, `SHORT`, `KIND_TITLE`, `llm.JUDGING`, `OUTPUT_CAP` and the run names are live
  views of the registry, so a kind registered later appears in all of them. Each equals its 0.13.5 value (a test
  writes the 0.13.5 values out). `routing.KINDS` and `tasks.KINDS` list the same kinds in another order (where order
  never mattered); `routing.certainty` reads which list of an answer carries confidences from the registry.
- **The quote check is required.** `taskkinds.register` refuses a kind without `quote_from` (or without a prompt,
  prompt version or store function), and a name ENLENS uses. ENLENS checks an add-on kind's answers against its
  schema and every quote against the text `quote_from` gives before the add-on's store function sees them. A quote
  not found says *quote not found in the passage* and how to fix it (copy it character for character, or quote a
  shorter piece), as ENLENS's own kinds say.
- **The guard and local-only hold.** An add-on's tasks are made, labelled, queued and refused like ENLENS's own.
- **Its own helper.** A kind may bring a Claude Code helper agent (`helper_file`, `helper_model`): the plugin ENLENS
  writes carries it, and the plugin check holds it to the queue's tools.

*The page.* Adding a page meant editing the route table, the sidebar in `index.html`, the job lists in `app.js`, the
Overview and the result page. Each has its extension point, read from one module, `registry.js`.
- **Page modules.** A fork fills in `static/extensions.js` (ENLENS ships `export default {};`, and releases never
  edit it); an add-on package puts `extensions.js` in its `STATIC` folder and `GET /api/state` lists it in
  `addon_pages`. The page loads them after the state arrives; one that fails is left out.
- **What a page module adds** (`applyExtensions` in `registry.js`, which never replaces one of ENLENS's entries):
  pages (after ENLENS's own routes), features (a sidebar entry with its AI mark after its section's entries, and an
  Overview card with its own state line), sections (a sidebar heading and an Overview section), job kinds (a job's
  icon, name and link in the sidebar; the link may be a function of the job, for apps with a page per item, such as
  Margin's drafts), welcome cards (first run), and origins (the result page's link back to where a hypothesis comes
  from).
- **Job kinds in one place.** `linkFor`, `kindIcon`, `kindText` and `withJob` moved from `app.js` into
  `JOB_KINDS` (`registry.js`). A job of a kind nobody names shows its own title (it showed its kind's code).
- **The Overview is built from `FEATURES` and `SECTIONS`.** Each section's line and card size moved into
  `SECTIONS`; *Read one document* is the Documents feature's Overview card, and Bibliography has none, as before.
- **The result page's back-link** comes from the registry: a check of several still says *part of a set*; a
  hypothesis an add-on made says where it comes from in the line under it, and links back to it above it.

**Tests.** The test files of the withdrawn versions are renamed after 0.13.6 (`test_0140_addons.py`,
`test_0150_task_kinds.py` and `test_0151_page_extensions.py` became `test_0136_addons.py`, `test_0136_task_kinds.py`
and `test_0136_page_extensions.py`), as is the stylesheet (`v0136.css`).
- `test_0136_update_check.py`: the kept answer, `?fresh=1`, a failed look, the release page, the shared state in Node,
  the page files; `test_0131_update_button.py` reads the look from `lib.js`, and `test_0101_settings_and_version.py`
  follows the version tag to *Updates*. Checked in headless Chrome with the dev server (`--update`, `--update none`),
  light and dark.
- `test_0136_addons.py` (17 tests): ENLENS alone adds nothing; the public names; with the stand-in add-on
  (`tests/fake_extension`) a route, its token, a download by link, a state key and an Overview key that cannot replace
  ENLENS's, a job of its own that is *not running* until a stand-in Claude Code takes its tasks and then finishes, and
  one stopped with its tasks withdrawn; its table and migration in a new project and in an older one; a hypothesis
  with an origin (and *Check several*'s); a floor that keeps a task on the local model (and out of the queue, and
  refused to Claude Code), cannot loosen a document's setting, and keeps a removed note's text here; a failing floor;
  local-only; a hypothesis hidden from the connector's list and refused when asked for; a fork adding routes in
  `gui/extensions.py`; an add-on that cannot take over ENLENS's route; a failing hook.
- `test_0136_task_kinds.py` (30 tests): every table against its 0.13.5 value; a test can still change a table
  (`monkeypatch.setitem`); registering a kind (refused without a quote check, a store function or with ENLENS's name;
  its defaults; taken away again); the quote check itself and its message; and the stand-in add-on's kind
  (`fake_tag`, tags for a note, each quoting it) in every table, routed on Claude Code, the Claude API and a local
  server, with its own Settings row and certainty, through the queue (a made-up quote and a broken answer refused
  before anything is stored, a good one stored with its route), stepping up when unsure, answered by the offline demo,
  named in *How these results were made*, its helper in the Claude Code plugin, its size estimate, and kept on this
  computer when its note is *Only a local AI* or the installation is local-only.
- `test_0136_page_extensions.py` (5 tests, two run in Node): ENLENS alone keeps its Overview (its sections, cards and
  order), its job rows (a check, a second opinion on three hypotheses, adding documents, looking before checking, an
  unknown kind) and its *part of a set* link (with and without an origin); the stand-in add-on's page module adds a
  section, a feature with a sidebar entry and its state line, a page, a job kind (with a link that depends on the
  job), a welcome card and an origin, twice without adding anything twice and without replacing ENLENS's *Check a
  hypothesis*; the server lists its module; the page code reads the registry. Checked in headless Chrome with the dev
  server: with the stand-in add-on (the name *Fieldnotes*, the *Notes* sidebar entry with its AI mark, the Overview's
  *Your notes* section, the add-on's page, a result's *Back to the note* and *from a note*), and ENLENS alone
  (Overview, Results, Settings), with no console errors.
- `test_0136_version_numbers.py`: a withdrawn version still running counts as older; the changelog lists none of
  them, and its versions go down from the top.

**Not yet done.** A hypothesis an add-on creates but never checks (no parts yet) cannot be opened on the result page
(a script error); ENLENS itself never makes one. An add-on's sidebar entry is added after the page loads, so it
appears a moment after ENLENS's own. The page does not yet know an add-on's kinds of AI task by name in its own
lists.

## 0.13.5 (November 2026): fixes found while building on ENLENS, and room for apps built on it

Margin, a writing companion built on ENLENS, found a few ENLENS defects on the way, fixed them first and now gives
them back. 0.13.5 also starts making room for apps built on ENLENS: until now such an app had to edit ENLENS's own
files to change even its name or colours, and every one of those edits clashed with the next ENLENS release. For
people who use ENLENS nothing changes apart from the fixes: every answer still goes through the quote check, a person
can overrule it, and nothing more leaves the computer.

**Fixes.**
- **Accented names in zips.** Zips made with Finder's *Compress* do not mark their file names as UTF-8, so accented
  names came out garbled ("másolat" became "ma╠üsolat"). A name is now read again as UTF-8 when it is that.
- **A project folder zipped by hand.** *Import a project* takes a zip of the project's folder itself (Finder's
  *Compress*, Windows' *Send to compressed folder*), not only one made with *Download as a zip*. Its documents are
  pointed at the unpacked copies. A zip holding several projects says so and names them.
- **A smoother icon.** The icon is drawn four times larger and scaled down, so its edges are smooth at every size
  (the icon files that ship with ENLENS are drawn again).
- **"Second opinion" everywhere.** 0.11.2 renamed the second AI model *second opinion*, but a few places still said
  "second model": the job's name in the sidebar and progress panel (*Second AI model*), its progress lines (*The
  second model is reading 12 excerpts*), the line under a result, the errors when none is chosen, when it is the
  main model or not installed, *How these results were made*, and the setting in *Settings*. They now say *second
  opinion* (or *the model for second opinions*). The Excel columns keep naming the model (*Second model*).
- **Release workflow.** The macOS one-line install test is its own job, and the draft release no longer waits for it
  (GitHub's Mac runners can be unavailable for hours). Check that it is green before publishing.
- **Steadier tests.** `test_make_backend` asked the computer's real Ollama, so it failed when an Ollama with a model
  was running; it now asks a closed port. The restart test counted a restart that began between two of its reads as
  an error instead of "not answering yet". `test_08_queue.py` expected the Claude API to start checks on Opus; since
  0.13.3 they start on Sonnet.

**Room for apps built on ENLENS** (docs/EXTENDING.md).
- **The local layer**: a short list of files ENLENS creates once and its releases never edit: `site.css`,
  `brand.json`, `gui/extensions.py`, `docs/ADDON_API.md` and `docs/ADDON_MANUAL.md`.
- **`site.css` last.** `index.html` marks the end of ENLENS's stylesheets with `<!-- release stylesheets end -->`;
  each release adds its sheet above it, and `site.css` (empty in ENLENS) always loads last.
- **Theme tokens in `tokens.css`.** The colour, type, shadow and size tokens moved from the top of `app.css` into
  `tokens.css`, loaded first. Another look overrides them in `site.css`; nobody edits `app.css` for it. Nothing
  changes on screen.
- **One branding file.** `brand.json` holds the app's name, tagline, welcome title and text, short description and
  logo. `GET /api/state` returns it as `brand`, and the page takes the name in the sidebar, the window title, the
  welcome screen and the *Update*, *Restart* and *Quit* buttons and messages from it.
- **Add-on modules.** A fork fills in `gui/extensions.py`; a separate package names its module under the entry point
  `enlens.extensions`. ENLENS reads both (`enlens_claims/addons.py`); in 0.13.5 a module can set `BRAND` and a
  folder of page files (`STATIC`, served at `/static/addons/<add-on>/`, its `site.css` added to `/static/site.css`).
  An add-on that fails to load is left out and ENLENS starts anyway.

**Tests.** `test_0135_fixes.py`: a Finder zip's accented name, a project folder zipped by hand (and a zip with two
projects, and one with none), a downloaded project still importing, the icon's smooth edges, no "second model" left
in the places listed. `test_0135_local_layer.py`: the marker and `site.css` last, `site.css` empty, the tokens in
`tokens.css` only, `brand.json` in `/api/state`, the page naming the app from it, the local layer's files, and the
stand-in add-on (`tests/fake_extension/`, found through its entry point) changing the name and the look without any
change to `index.html`, `app.css` or the page code; a fork doing the same in `gui/extensions.py`; a broken add-on
leaving ENLENS running. `tests/_static.py` (`release_sheets`, `assert_sheet_after`) replaces the "linked last"
checks of `test_0133_app_wide_polish.py` and `test_0134_claude_account.py`; the routes-are-documented tests read
every `docs/*API*.md`.

**Not yet done.** Other pages still say "ENLENS" in their help texts (Settings, Projects, Documents): they describe
ENLENS's own install and update, and are left for the page extension points (0.13.6). Add-ons cannot yet add routes,
jobs, tables or AI tasks: that is 0.13.6.

## 0.13.4 (November 2026): which Claude account answers

Claude Code works on the Claude plan it is signed in to, and until now ENLENS only said *Claude, on your plan*: with
an account at home and one at the university, there was no way to see from ENLENS which one was answering (and so
which terms apply to the text it reads). 0.13.4 names the account. Nothing else changes: every answer still goes
through the quote check, a person can overrule it, and nothing more leaves the computer.

- **The sidebar's *Claude, on your plan* line names the account.** Hovering it (or reaching it with the Tab key)
  opens a small card: *Signed in to Claude Code as you@university.nl*, the plan (*Team plan · University of
  Amsterdam*), where the text goes and where to change it. It replaces the browser's own tooltip, which appeared
  late and said less. It opens quickly, stays open while the pointer is on it (so the address can be copied), and
  Escape closes it. When Claude Code is not signed in or not installed yet, the card says so and points to *Settings
  → AI*. The organisation is named only on a Team or Enterprise plan: on Pro and Max it is usually Claude's own
  "…'s Organization", which adds nothing. The other AI routes keep the same card without an account (where the text goes,
  the model, where to change it).
- **Settings → AI** says the same under *Signed in with your Claude plan* (*you@university.nl · Team plan ·
  University of Amsterdam*; it said *Pro, Max, Team or Enterprise*), so it can be seen on a phone too, where there is
  no hover.
- **`enlens claude-setup`** ends with *Claude Code is signed in as you@university.nl, Team plan (University of
  Amsterdam).*
- **Where it comes from:** `claude auth status`, which ENLENS already asked whether Claude Code is signed in. ENLENS
  now keeps three more of its fields (`email`, `orgName`, `authMethod`) in the set-up status, only while Claude Code
  says it is signed in, as one line of plain text each (control characters removed, at most 200 characters). The
  login itself stays with Claude Code. The address is only shown (in the page and on the command line): ENLENS does
  not write it into its files (the settings, a check's record, an export), nor into `/api/state` or the queue's
  answers, and with `--local-only` Claude Code is not asked at all.
- **One answer for the whole page.** The sidebar, the *Overview*'s AI line and *Settings → AI* share what Claude
  Code last said (asked again after a minute at most, and at once when *Settings → AI* reads it afresh, e.g. after
  *Check again* or a sign-in), instead of the Overview and Settings each asking for themselves.

**Tests.** `test_0134_claude_account.py` (10 tests): the account from the stand-in Claude Code (Team, Enterprise,
Max), signed out, an older Claude Code that names no account, a Claude Console account, odd values (line breaks,
escape codes, a 500-character address, a number), `--local-only`, the address in `/api/claude-setup` and not in
`/api/state` or the queue, `enlens claude-setup`'s line, the page code and the stylesheet. The stand-in
(`tests/fake_claude_cli.py`) now reports an address (`FAKE_CLAUDE_EMAIL`, `FAKE_CLAUDE_ORG` and `FAKE_CLAUDE_PLAN`
change it). `test_0133_app_wide_polish.py` lets a later release's stylesheet follow `v0133.css`.
Checked in Chrome: the card on hover and on keyboard focus, Escape, signed out, a very long address and
organisation (they wrap inside the card), light and dark, and *Settings → AI* at 390 px, with no console errors.

**Not yet done.** Tried against the real Claude Code 2.1.318 only to learn the fields `claude auth status` prints
(`email`, `orgName`, `subscriptionType`); the app itself was tried with the stand-in. A Claude Code signed in with an
API key, or through Amazon Bedrock or Google Vertex, names no Claude account: the card then says Claude Code does
not say which account it is signed in to (untested with a real one). Switching accounts stays in Claude Code
(`claude auth logout`, then *Set up Claude* signs you in again; see the manual's troubleshooting table).

## 0.13.3 (November 2026): every page as calm as the result page, and titles from Zotero

0.12 rebuilt the result page against eleven written criteria (the answer at a glance, a clear order, a small type
scale, one main button per section, short copy, scannable cards, low visual noise, the dark theme, phones, nothing
lost, polish); the other pages kept their 0.11 layout and type sizes. 0.13.3 brings what that page taught to every
page, without redesigning any of them: the same pages, easier to scan. Checks also move to Sonnet, and a document
linked to a work of your bibliography takes the work's title. Every answer still goes through the quote check and a
person can overrule it. What leaves the computer is the same, except that an AI task made after a document is linked
carries the work's title instead of the file's (see *Titles from your bibliography*).

**One look on every page.**
- **A few type sizes and two weights.** Page titles, section titles (1.05rem), text, and one small size (.875rem) for
  everything secondary. Bold only for headings, the page's main button and the labels of form fields; every other
  button, the folds (*More options*, *What happens when you check*, *Start over or remove the project*) and the links
  inside notices were semi-bold and are now regular.
- **One card style:** a thin edge, no shadow; the *Overview* cards no longer jump on hover. In *Settings → AI*, *What
  happens to the text Claude reads* is no longer a third box inside the Claude box inside the card.
- **Colour only where it means something.** The sidebar's **AI** marks and the AI line above each title were purple,
  the colour of *Mixed evidence*, and *No AI needed* was green, the colour of *Supports*: they are grey now (a filled
  mark: needs AI; a dashed one: optional). Grey too: *N to review* in *Results* (it was amber, the colour of *partly
  supports*) and what is already made on the *Overview* (*3 results*, *57 terms*, which were green). An answer in the
  *Results* list is a soft colour without a border (a bordered pill reads as a button), and *Only uncertain evidence*
  is grey, so amber keeps one meaning.
- **The line above a title** reads *Explore the documents · No AI needed*, in sentence case and the regular weight
  (it was spaced capitals and a coloured pill); on a phone a wrapped line never begins with "·".

**Short copy, the details one step away.**
- **Subtitles of one line** on *Documents*, *Bibliography*, *Search*, *Profile*, *Concepts*, *Themes*, *Check a
  hypothesis*, *Check several*, *Results* and the *Evidence map*. They no longer repeat the project's name, which is
  in the sidebar and the top bar (*Every hypothesis checked in this project, newest first.*).
- **Help marks (?)** as on the result page, for what a passage is (*Search*, in the results' heading: it was a
  paragraph under it), what a second opinion does (*Results*: the line beside the button now says *For comparison
  only: the answers do not change.*; it was four sentences), the auditor (*Settings → AI*, *Let the auditor use
  Fable*: one line) and how the AI labels passages (*Profile*: one sentence, and its count line is no longer bold in
  the middle of the text).
- **The Overview cards** say what each feature does; what it is for is the card's tooltip (it was a second, grey
  paragraph). The AI line says *Only the passages inside its tasks are sent to Anthropic. Ready.*
- **Check a hypothesis:** the line under the buttons says how long a check takes; *Look before checking* explains
  itself in its tooltip, as it already did.
- **The document page:** *Open the original* and *Download a highlighted copy* are two quiet links on one line; where
  the original opens is in its tooltip (the sentence beside it and *The text as the app reads it.* are gone).

**Downloads as quiet links.** *Results*: *Download all: Excel (.xlsx) · CSV (for programmers)* under *Show as a map*
(the head had three buttons, one of them a filled main button). *Search*: *Download Excel (.xlsx) · CSV* (two
buttons). *Profile*, *Themes* and the *Evidence map*: *Download Excel (.xlsx)*; on *Profile* it appears once there is
a profile to download (it was a disabled button before).

**Checks on Sonnet.** Judging excerpts (a check, and reading one excerpt again) goes to Sonnet instead of Opus; the
plugin's checker helper runs Sonnet at high effort. A judgement it is unsure of (certainty under 0.6), two rejected
answers and *Ask a stronger model* still go to the auditor (Opus, or Fable when switched on), and second opinions
stay on the auditor. On the Claude API, checks use `claude-sonnet-5-5`, and the model field of *Settings → AI* (it
said *Model for judging excerpts*) is now the *Stronger model* a task steps up to. *Settings → Technical → AI model
per task* can set checks back to Opus. (`routing.CLAUDE_DEFAULTS`, `HELPER_MODEL`,
`claude_plugin/agents/enlens-checker.md`, `docs/MODEL_CHOICE.md`.)

**Titles from your bibliography.** A document linked to a work of the bibliography (the same file, the same DOI, or a
pair you confirmed or linked by hand) is now called by the work's title from Zotero, or from the exported file. This
applies everywhere: the Documents list, the document page, Search, a check's excerpts and its exports. A PDF's own
title is often a file name, a running head or a draft's first line (*RMI_report_final_v3 (draft for comments)*).
- The title read from the file is kept. The document page shows it under the bibliography line (*Title in the file:
  …*), and so does the *Linked* list on *Bibliography*, whose filter finds it too. It is not shown when the two
  differ only in case, accents, quote marks or dashes.
- When no work is linked any more (*Unlink*, another collection or file, *Remove the bibliography*), the document
  gets its own title back. A title edited in Zotero follows with *Update from Zotero*. A document linked to several
  works takes the first one's.
- The matching always reads the file's own title, so a borrowed title never proposes a work.
- A check made before the link keeps on record the title the AI was shown. Its result page and exports show the title
  the document has now, as the list of documents behind an answer already did. AI tasks made after the link carry the
  work's title; documents marked *No AI* are still *Restricted document N* to Claude Code.
- For developers: `documents.file_title` (a migration) holds the file's own title while the work's replaces it, and
  `bibliography._sync_titles` runs at the end of every match and when the bibliography is removed. `GET
  …/documents/<id>` and the Bibliography's pairs add `file_title` (`docs/API.md`). The keyword index rebuilds when a
  title changes, through a `titles_version` in its cache key, without marking themes, glossaries or profiles out of
  date.

**Defects fixed.**
- On a phone, the *Search* page scrolled sideways: the hidden labels of each line's buttons escaped the table's
  frame. The frames of the tables that scroll (Search, the documents, the evidence map, the search inside a document)
  now hold them.
- *Profile* showed a disabled *Download for Excel* button before any profile existed.
- On a phone, the bibliography line of the document page wrapped as a row: the library icon could stand alone on a
  line, and a line could begin with "· Open in Zotero". Each part now has its own line beside the icon.
- A note opened from a help mark near the right edge of the window ran off it (the second opinion's on *Results*); it
  now moves left to stay in view, on every page (`popNote`).

**Tests:** `tests/test_0133_app_wide_polish.py`: the stylesheet linked last and served, colour tokens only; the type
sizes and the two weights; cards without shadows and no third box in *Settings*; grey AI marks, states and counts,
answers without borders; downloads as links on *Results*, *Search* and *Profile* (shown only once there is a
profile); the help marks; every page subtitle one short line without the project's name; the document page's two
links; the table frames that hold their hidden labels; the bibliography line of the document page on a phone.
`tests/test_0133_zotero_titles.py`: links by file and by DOI (the file's title kept); proposed and unlinked documents
(own title); a confirmed proposal; unlinked and linked again; another bibliography with the same title but no DOI or
year (the matching reads the file's own title); a title edited in Zotero; a document with no title of its own; the
bibliography removed; Search's index rebuilt with the new titles; a check made before the link shows the new title
while its stored task keeps the old one; the endpoints and the two pages. `tests/test_08_queue.py` follows checks to
Sonnet (the router, the queue and the checker helper's model and effort). Checked in Chrome with the dev server (the
social corpus, the stand-in Claude Code and Zotero): every page in light and dark at 1280 px and at 390 px; no
console errors, and no page scrolls sideways.

**Not yet done.**
- Not a redesign: *Settings*, the add area of *Documents* and the concept and theme pages keep their layout and only
  take the shared rules; the sidebar keeps its smaller type. *Bibliography*'s *Download the list* is still a button.
- Checks on Sonnet were tried with the stand-in Claude Code only. A plugin set up before 0.13.3 runs its checker
  helper on Sonnet already (ENLENS names the model for each batch) but at the normal effort until the plugin is
  written again: `enlens update` does that (then `/plugin marketplace update enlens` in Claude Code), or `enlens
  claude-setup` on a git copy.
- Titles from the bibliography were tried with the stand-in Zotero only. There is no way yet to keep the file's own
  title for one linked document.
- Checked in Chrome only; the head of *Results* stacks its button and links with `:has()` (Safari 15.4, Firefox 121
  and later).

## 0.13.2 (November 2026): the result page, finished

0.12 rebuilt the result page and had it scored against eleven written criteria by an independent reviewer, round
after round; 0.12.0 was released while that work was still going. 0.13.2 brings the last rounds' changes: the same
page, easier to scan and with a few defects fixed. Every answer still goes through the quote check, a person can
overrule it, and nothing about what leaves the computer changed.

**Easier to read.**
- A short heading that opens a paragraph of the document (*Recommendations.*, *Services to citizens.*) is shown as a
  small heading above its paragraph, instead of reading as a sentence of the context around the quote; the window's
  paragraphs sit closer together.
- An excerpt the AI did not count says **Not counted** and then **Certainty: low**, the same certainty label as every
  other card (it said *Not counted · certainty: low*).
- A hypothesis checked in parts: each part's documents are on a line under the part (*3 documents for, one of them
  also against*: a document with excerpts on both sides is counted once), and the answer says *Part 1 decides the
  answer.*, with the rule (the hypothesis holds only if every part does) in its tooltip. A part's heading reads
  **Part 1:** and then the claim in regular weight.
- *Ask another AI model* says what has happened first and what is not set last (*No stronger model is set. Set one in
  Settings.*).
- An excerpt read for another part too says *also in part 1*; your judgement there is in its tooltip. When every
  matching excerpt has been read, the line says *Every matching excerpt has been read.*
- *Quote another sentence: select it in the excerpt, then* **Use it** (it said *Use selected text*, a button that did
  nothing until text was selected).

**Defects fixed.**
- A card's source line could break so that a line began with "·"; the separator now stays with the place (*·
  paragraph 6 of 8*).
- A sentence selected across the "…" the card shows where it leaves text out was refused as "not text from this
  excerpt".
- A phone turned between portrait and landscape (or a window resized across 600 px) kept the other width's excerpt
  window until the next change; the cards are drawn again.
- On a phone, the strictness help mark made its line taller than the line under it.

**Tests:** `tests/test_0132_result_page_polish.py`: the run-in heading's pattern (run in Node), the uncounted card's
two facts, a document on two sides counted once (run in Node), the source line's separator, a selection across "…",
the redraw on a width change, the models card's order. Checked in Chrome with the dev server (the social corpus): a
single and a split hypothesis, light and dark, 1280 and 390 px wide; no console errors.

**Not yet done.** The run-in heading is recognised by its form (up to four words and a full stop at the start of a
paragraph): a paragraph that opens with a very short sentence (*Prices rose.*) is shown the same way. *In context*
shows the text as it is.

## 0.13.1 (November 2026): update ENLENS from the app

Updating meant quitting ENLENS, typing `enlens update` in Terminal or PowerShell (or pasting the install line again)
and opening ENLENS again: three steps in two places, for researchers who rarely open a terminal. 0.13.1 adds
**Update ENLENS** at the bottom of the sidebar: it looks for a newer version, installs it the way this ENLENS was
installed, and restarts ENLENS on the same address. The open page waits and then opens the new version by itself.
Projects, results and settings are never touched. Nothing about what is sent to an AI changed.

**Update ENLENS.**
- One click looks for a new version: the latest published release (one-line install), or new commits on the branch
  a git copy follows. Up to date: a short message says so. Otherwise a dialog says which version is ready and what
  will happen (*Update and restart*), and warns when a check or documents being added are still running: they stop,
  as with *Quit ENLENS*, and a stopped check leaves nothing behind.
- The update is the same as `enlens update`: the release's package checked against its checksums and installed with
  uv, or `git pull` with the requirements reinstalled only when they changed. When it fails (offline, files of a git
  copy edited by hand), the reason is shown and nothing restarts. With the one-line install on Windows, where a
  running program cannot replace itself, it says to quit ENLENS and run the install line again.
- The restart keeps the address and port, so the open tab finds the new version: while it restarts, the page says
  *Starting ENLENS* with the new version's number and reloads by itself (after 90 s without an answer, it says how to
  open ENLENS again). Started from the ENLENS icon, ENLENS is restarted as the icon starts it, without opening another
  browser tab.
- A second click while it updates is refused, so nothing is installed twice.

**Restart now.** When ENLENS was updated while it kept running (`enlens update`, `git pull`, the install line), the
notice *ENLENS X is installed, but Y is still running* now has **Restart now**, which starts the new version in its
place, instead of *Quit ENLENS* and opening ENLENS again.

**For developers.** `GET /api/update`, `POST /api/update` and `POST /api/restart` (`docs/API.md`); `GET /api/state`
adds `can_restart`. `serve()` restarts with `os.execv` on macOS and Linux (the same process and terminal) and starts a
new process on Windows; `restart_command()` builds the command. `tools/dev_server.py --update` is a stand-in update
that restarts the dev server in place (`--update commits | on-disk | none | fails` for the other cases). The button
and its endpoints come from Margin 0.2.1, where they were made first.

**Tests:** `tests/test_0131_update_button.py`: the check (a newer release, new commits on a git copy, up to date, a
reason it cannot update), *Update and restart* (installs once, then restarts once; a second click refused; nothing
restarts when up to date or when the update fails, and it can be tried again), a newer version already on disk (only
a restart), a copy that cannot restart itself, *Restart now*, the restart command, the page's button, the routes in
`docs/API.md`, and a real ENLENS started as the icon starts it that restarts in place (same port, new token, the same
process) and still quits cleanly. Checked in the browser with the stand-in update: the button, the dialog, the
restart and the page coming back by itself, *Restart now* on the notice, a failed update; light and dark, 390 px.

**Not yet done:** not tried against a real published release (the tests and the dev server use stand-ins for
GitHub, git and uv), nor restarted from the real ENLENS icon on a Mac or on Windows. The first version with the
button must still be installed the old way (`enlens update` or the install line); from 0.13.1 on, the button does it.

## 0.13.0 (November 2026): your Zotero bibliography next to your documents

Researchers keep their literature in Zotero, and most of it has no PDF in the project: until now ENLENS knew only the
documents added to it, so finding out which works were still missing, and which PDFs already added were which work,
was done by hand, and a PDF without metadata stayed "download (3).pdf". 0.13 adds a **Bibliography** page: bring in a
Zotero collection (or the whole library) in one click, and ENLENS links each work to the document you already have,
lists the works still to find, and the documents Zotero does not have. Zotero is read from the Zotero app on this
computer, never through the internet, and only read. No AI is used; nothing about what is sent to Claude changed.

**Bringing in a bibliography.**
- From Zotero 7 or later through its local API (`http://127.0.0.1:23119/api/`, switched on once in Zotero under
  *Settings → Advanced → Allow other applications on this computer to communicate with Zotero*): My Library or a group
  library, a collection with or without its subcollections, or the whole library. No Zotero account or key. The page
  says plainly when Zotero is not open, does not allow it yet (with the box to tick), or is too old (Zotero 6).
- Or a file exported from Zotero, Mendeley, EndNote and others: **BibTeX** (accents, `@string`, organisations in
  braces, Zotero's `file` field), **RIS**, **CSL JSON** (Zotero's item links kept) and **Zotero's CSV**.
- *Update from Zotero* reads the same collection again; *Use another collection or file* replaces it. A person's
  decisions follow each work, even to another source (by its Zotero key, else its DOI, else its title and year).

**Matching works and documents, without adding anything twice.**
- Linked by themselves: the **same file** (a file Zotero keeps for the work has the checksum of a document already
  added) or the **same DOI** (from the document's first pages or file name; Zotero's DOI field, its *Extra* field, or
  a doi.org address).
- **Proposed** (*Please confirm*): the work's title on a document's first pages, with an author or the year; a title of
  one or two words needs both. Each pair shows the work and the document side by side, the place on the document
  where the title stands (highlighted, with its page), and what was found. *Same work*, *Not the same* (never proposed
  again), *Confirm all*; *Undo* in the message.
- Not fooled by a document that only cites a work: the title must stand on the first pages as a phrase, or nearly all
  its words close together on the title page, not spread over the text ("In the 2024 staff survey…" is not the
  survey). Editions of one report: the year printed nearest the title decides; near ties are shown for the person.
- Documents added later are matched as they come in (the message after adding says how many were linked and how
  many wait), and a document removed sends its work back to *To find*.

**The lists.**
- *To find*: authors, year, type, where published, a DOI link, the web address and *Open in Zotero*, with a filter,
  and **Download the list** (Excel: title, authors, year, type, published in, DOI, DOI link, web address, Zotero link,
  file in Zotero): the to-download list.
- **Zotero's files in one go**: when Zotero keeps a PDF (or a saved web page, a Word file) for works without a
  document, *Add these files to the project* reads them where Zotero keeps them (nothing copied), after the usual
  question of who may read them with AI (the project's choice preselected), and links each to its work.
- *Linked* (how: same file, same DOI, you confirmed it, you linked it; *Unlink*) and *Not in the bibliography* (*Link
  to a work* by hand); *Link a document* on a work to find.
- A linked document shows its reference (*Verhoeven and Okafor (2025)*) under its file name in the Documents list, and
  in the document viewer with its DOI and *Open in Zotero*. *More ways to add* on the Documents page points to it.

**Usability problems fixed on the way.**
- The DOI in a document's header was plain text; it is a link to the publisher's page now.

**For developers.** `bibliography.py` (the Zotero client, the four file formats, storage and matching), tables
`bib_items` and `bib_links`, nine endpoints (`docs/API.md`, *The bibliography*), the page `views/bibliography.js` and
`v013.css`. `tests/fake_zotero.py` is a stand-in for Zotero's local API, used by the tests and by
`tools/dev_server.py --zotero` (`--zotero api_off | old | closed` for the other states; with `--corpus social`, a
library for the remote-work demo documents).

**Tests:** `tests/test_0130_bibliography.py`: each file format (accents, organisations, file paths, continued RIS
lines, Zotero links in CSL JSON and CSV, a file that is not a bibliography); Zotero's states (ready with a group
library, the box not ticked, Zotero 6, not open) and that only this computer is asked; pulling a collection with and
without subcollections, the whole library and a group library, notes left out, DOIs from *Extra* and doi.org
addresses, attachments' files but not web links; the matching (same file, same DOI, a title with the year near it, an
edition only mentioned, a document that cites a work, short titles); a person's word kept across matches and across a
change of source; a removed document; the whole flow through the app (bring in, the documents' references, adding
Zotero's file with its AI setting, a document added later, confirming, the Excel and CSV lists, updating, a file,
bad requests, Zotero switched off); the page's shell, styles (colour tokens only) and that every new route is in
`docs/API.md`. Checked in Chrome with the stand-in Zotero: bringing in a collection, each list, confirming, linking by
hand, adding Zotero's file, the Documents list and the document viewer, Zotero not open and not allowed; light and
dark, 390 px; no console errors.

**Not yet done:** not tried with a real Zotero 7 (only the stand-in, built from Zotero's documentation of the local
API; in particular the attachments' file paths through `/file/view/url`, and group libraries). Zotero's web API
(api.zotero.org, for a library not on this computer) is not used. Results, citations in exports and the Search still
name a document by the title read from its file, not by its work in the bibliography. Files Zotero keeps as linked
files relative to a base folder are found only through Zotero itself, not from an exported file.

## 0.12.0 (November 2026): a calmer result page, and work that says when it is not running

After the checks have run, the result page is where the actual work starts: reading the answer, reviewing the
evidence and deciding what to believe. It had grown into the busiest page of the app, with many type styles close
together, buttons inside explanations, long descriptions and the information all mixed. 0.12 rebuilds it to be the
easiest page to read, judged against written criteria by an independent reviewer (below). And the sidebar no longer
says *1 task running* when nothing runs. Every answer still goes through the quote check, a person can overrule it,
every result records how it was made, and nothing about what leaves the computer changed.

**The sidebar says when nothing runs.**
- Work that waits for Claude Code while nothing answers it showed *1 task running* with a pulsing dot, beside *1
  waiting for Claude Code*, in the same colour. It now shows **1 task not running · Waiting for Claude Code to
  start**, in amber with a still pause mark; its panel has *Start Claude Code* and lists the job as *not running*.
  With work of both kinds it says *1 running · 1 not running*. Once Claude Code takes the work (started from ENLENS,
  or `/enlens-run` typed in Claude Code taking or answering a batch, or an answer in the last two minutes) it is
  *running* again.
- API: each job of `GET /api/jobs` and of `/api/state` has `on_hold` (`taskqueue.answering`, `Job.waits_on_queue`,
  `App.job_views`).
- The jobs and queue panels of the sidebar open in place with a frame of their own (their rule to open upwards never
  applied, so they opened as loose text over the sidebar).

**The result page, rebuilt to be read.** Before it was changed, eleven criteria were written down for it (the answer
at a glance, a clear order of sections, a small type scale, one main button per section, short copy, scannable
evidence cards, low visual noise, the dark theme, phones, nothing lost, polish). An independent reviewer (Claude
Fable 5.1 at extra-high effort, a new one each round, given only the criteria, screenshots of seven states and the
code) scored the page against them, and the page was changed and checked again until every criterion scored well.
- **The answer first, in one card**: the answer, who says what (one row per document, a coloured dot per side and
  where: *supports it: paragraph 9 · contradicts it: paragraph 5*), one caution in one sentence (*It rests on a
  single document and on two excerpts you have not reviewed.*), and one button, **Next to review**. A hypothesis
  checked in parts lists its parts in a small grid (each with its answer and its documents for and against, a
  document on both sides counted once) under one line on which part decides the answer; the caution then counts only
  that part's excerpts. Beside the answer: *judged by the AI*, *partly reviewed by you* or *reviewed by you*. It
  replaces *The AI's first reading*, a coloured warning, two sentences on the documents, a sentence on uncertain
  judgements, *Reviewed by you: 0 of 8*, a *What to do next* box and a paragraph on strictness.
- **Then the evidence**, with *Cards* and *Table* as two tabs beside its title and two short lines under it: *2 of 4
  excerpts count at normal strictness (?)* and *Every quote is checked against its document; your judgement overrides
  the AI's.* A part of a split hypothesis has a plain heading (*Part 1: …*) and lists its own documents above its
  excerpts. The excerpts not about the hypothesis stay folded under the cards, and *Read more excerpts* and *Search
  with other words* follow the evidence they add to.
- **An excerpt card in a fixed order**: the judgement with at most two quiet facts (*Certainty: medium*, *Not counted
  · certainty: low*, *Second opinion: partly supports*, *You agreed with the AI*), the document and the place, then
  the quote with one sentence before and after it (no longer the whole excerpt of up to a page), highlighted in its
  judgement's colour (green, amber, red, also in the dark theme). The same row of actions on every card: **Agree**,
  **Not about this** (new: dismisses an excerpt in one click, with Undo; it moves to the excerpts not about the
  hypothesis), **Judge differently…** (*Edit judgement…* once you have judged: the other judgements, each with its
  colour dot, under a line that says what your judgement is now; another sentence as the quote; a comment), then two
  links, **In context** (the whole excerpt, and from there the whole document at this place, the original file or a
  highlighted copy) and **Details** (the AI's certainty, how the excerpt was found, *Ask the AI to read this again*).
  An excerpt you have judged sits back on the page (no fill, a dashed edge); one that does not count comes after
  those that do. Ten cards fit in about three screens, where they took six or more.
- **Then the other AI models, notes and downloads**: *Ask another AI model* says what has happened (a second opinion
  read 16 excerpts and judged 4 differently; no stronger model is set) and has *Ask a stronger model* and *Get a
  second opinion* side by side, what each does in its tooltip (the two long explanations, the model picker's
  paragraph and the boxes inside the box are gone; the models are named in its help mark and under *Technical
  details*). *Download* is one quiet link per file with one line on what it holds; CSV and JSON are one line *(for
  programmers)*. *Technical details* (the strictness for this page only, the models and settings, the search words,
  the AI's notes) and *Delete this result* close the page.
- **Type and colour**: four type sizes and two weights (bold only for headings, the main button and *Agree*); the
  serif only for the hypothesis and the documents' text; green, amber, red and purple only for judgements, amber also
  for the one caution, the accent colour only for actions and links (one link style on the page). No bold labels in
  running text, no icons on labels, at most two levels of boxes.
- **While a check waits** for Claude Code, the answer card is the waiting notice with *Start Claude Code* and one
  line; how it works, the command to type and what is sent sit in a fold (*How it works*).
- **On a phone** (390 px) a card shows the sentence before the quote and the quote, its three judging buttons stay on
  one line with *In context* and *Details* under them, tap-sized, the parts grid and who says what keep one fact per
  line, and nothing scrolls sideways.

**Usability problems fixed on the way.**
- Dates were written in the computer's own language and order (such as *2026. nov. 4. 19:36*) in an English page: now
  *4 Nov 2026, 19:36* everywhere.
- A quote that opens with a dummy subject (*There is no evidence that…*, *It is unclear whether…*, *It seems…*) was
  flagged as starting with a word whose reference should be checked; it no longer is (`references.EXPLETIVE`).
- *Only uncertain evidence* had a question-mark icon, read as a help mark; it has a dotted circle.
- **Next to review** goes to the judgements that count first, then those flagged (a second opinion that differs, a
  note about another group), then the rest, and those with only a comment last; past the evidence it says it goes on
  to the excerpts not about the hypothesis; from the *Table* it switches to the cards it goes to.
- A comment is saved on Enter or when you leave the field (a judgement picked meanwhile takes it along); a comment
  typed and then *In context* or *Use selected text* clicked was lost, or failed to save with an error in the
  browser; it is now saved first, or kept in the field until the judgement is chosen.

**Tests:** `tests/test_0120_results_page.py`: a job waiting on Claude Code is `on_hold` while nothing answers and not
once a stand-in Claude Code takes a batch (over the API, with `tests/fake_claude_cli.py`); an answer more than two
minutes old does not count as answering; the sidebar's words; the order of the result page's sections; the compact
card with *Not about this*; the excerpt window (run in Node: the sentences shown around a quote); dummy subjects are
not references; *Next to review* from the table. Checked in Chrome with the dev server (the social corpus, and the
stand-in Claude Code for the waiting and uncertain states): seven states of the result page, light and dark, 1280 and
390 px wide, judging, dismissing, undoing, a comment, *In context*, *Details*, *Next to review*; the sidebar with
work not running and running; no console errors.

**Not yet done.**
- The sidebar's *not running* was checked with the stand-in Claude Code only; with a real, signed-in Claude Code
  started from ENLENS or typed in a terminal (`/enlens-run`), it should turn to *running* within one redraw of the
  sidebar (5 s) once a batch is taken.
- The excerpt window cuts at sentence ends found by a simple rule (full stops, question and exclamation marks):
  abbreviations such as *e.g.* or *Fig. 3* can shorten the sentence shown before the quote; *In context* shows it
  all.
- The result page was reviewed in Chrome only (Safari and Firefox not checked); the other pages keep their 0.11
  layout and type sizes.

## 0.11.3 (November 2026): a Start Claude Code button you cannot miss

While a check (or any AI work) waits for Claude Code, its step keeps the spinner, and the progress panel's dot keeps
pulsing, so a researcher who has not pressed **Start Claude Code** yet could take the work for already under way and
wait for nothing. Every answer still goes through the quote check, a person can overrule it, every result records how
it was made, and nothing about what leaves the computer changed.

**Start Claude Code asks for attention when it is left unpressed.**
- About five seconds after work starts waiting with nothing answering it, the button pulses (a ring in the accent
  colour, every 1.6 s) and the line beside it says **Nothing runs until you press it.** Then it works on your Claude
  plan, in the background, and stops by itself when nothing waits. With reduced motion in the computer's settings it
  has a still ring instead.
- The pulse stops when the button is pressed, and on its own once something answers the work: Claude Code started
  from ENLENS, or typed in Claude Code (`/enlens-run`) and taking a batch. The button looks again every 5 s while it
  pulses.
- The same everywhere the button is: a check's progress, a result that waits, the sidebar's queue panel. The
  five seconds count per project, so the sidebar (drawn again every 5 s) and a waiting result (every 5 s) neither
  start them over nor make the pulse stutter (it keeps in step across redraws). The button is changed in place, never
  replaced under the pointer.

**Usability problems fixed on the way.**
- A follow-up on a result that waits for Claude Code (a stronger model for the whole result, new in 0.11.2; a second
  opinion; reading an excerpt again; reading new documents) said only "waiting for Claude Code (type /enlens-run Demo
  in Claude Code)", with no button. Its line now carries **Start Claude Code** (which pulses the same way) and the
  command to type, as every other place where work waits does.
- The button that stops a Claude Code started from ENLENS is called **Stop Claude Code**: beside a job's own *Stop*
  (the progress panel, and now a follow-up's line), two buttons both called *Stop* did different things.
- *Claude Code is working on it* keeps its dot beside its words in a narrow place (390 px, the sidebar).

**Tests:** `tests/test_0113_start_nudge.py`: the queue says when work waits unanswered (the page's rule: Claude Code
chosen and found, work waiting, nothing answering it, nothing started from ENLENS running), and stops saying so when
a batch is taken by a Claude Code typed elsewhere or when Claude Code runs from ENLENS; nothing to nudge on another
route; the page's rule, styles and the follow-up's button. Checked in Chrome with the dev server's stand-in Claude Code
(`--claude-cli`): a check's progress, the sidebar, a stronger model's follow-up line, light and dark, 390 px, reduced
motion, pressing the button; no console errors.

**Not yet done:** not tried with a real signed-in Claude Code (only the stand-in). The spinner of the waiting step
itself is unchanged: the button now says that nothing runs, but the step still spins until Claude Code takes the work.

## 0.11.2 (November 2026): a stronger model's answer, and two clear ways to ask another model

When a check steps up to a stronger model (on its own for an unsure or twice-rejected answer, or because a person
asked), the stronger model's judgements already replaced the first ones excerpt by excerpt, but nothing at the top of
the result said that the answer had changed, and the two ways to have another model read the excerpts were easy to
mix up: *Ask a stronger model* (a small button under each search; replaces the judgements) and *Ask a second AI
model* (in *Keep this result up to date*; shown beside them only). Every answer still goes through the quote check, a
person can overrule it, every result records how it was made, and nothing about what leaves the computer changed.

**The stronger model's reading is the answer, with a trace of the first one.**
- A result whose answer a stronger model changed shows that answer with a small mark beside it: **Supported**
  *at first: partly supported*. Hover or click it: which model judged first, which read again, how many judgements
  it changed. Unreviewed, the answer is introduced as "The stronger model's reading:" instead of "The AI's first
  reading:". Each part of a split hypothesis carries its own mark, and the parts list the short one.
- The Results list shows the same mark (*was partly supported*) next to the answer, and the Excel *Summary* sheet
  has the column "Answer before a stronger model read it again".
- Nothing is hidden: each changed excerpt keeps "Read again by a stronger model (the first reading was by …): was
  Partly supports, now Supports", and the first judgement stays under *Technical details*. A person's own judgement
  counts in both readings, so the mark appears only where the models' change made the difference.
- API: `status_first`, `status_before_stronger` and `stronger` on the hypothesis and on each part, `can_step_up` per
  search round, `status_before_stronger` on each row of the Results list (`claimcheck.first_reading`,
  `_before_stronger`, `stronger_eligible`).

**Two distinct choices: replace or compare.**
- *Keep this result up to date* now has one block, **Ask another AI model to read these excerpts**, with two
  side-by-side options that say what they do: **Stronger model** (*replaces the AI's judgements*: the answer can
  change, once per search) with *Ask a stronger model (opus)*, and **Second opinion** (*only for comparison*: never
  changes the answer) with *Get a second opinion*. Each says what has happened so far (read again, how many
  judgements changed, what the answer was before; how many excerpts the second opinion judged differently).
- *Ask a stronger model* now works on the whole result (`POST /api/projects/<p>/hypotheses/<h>/stronger`, one job
  for every search not read again yet) instead of a small button under each search; the searches keep their one-line
  note ("A stronger model read these excerpts again; its reading counts"). When the AI chosen in Settings has no
  stronger model, the block says so instead of hiding the option.
- "Second AI model" is called **second opinion** everywhere it is shown (the Results action *Get a second opinion
  for all results*, the tag *second opinion differs on N*, the table column, *Next where it differs*, Settings →
  *Model for second opinions*), and the routing and Fable texts in Settings say which of the two replaces.

**The second opinion on an excerpt, made readable.** The chip "Second AI model: Partly supports (70%) — disagrees
with the first AI" (or "…with your judgement (the first AI said …)") is replaced by one line that shows every reading
at once: *Second opinion differs* (or *agrees*) · **The AI:** Supports (80%) · **Second opinion (opus):** Partly
supports (70%) · **You:** … when you judged it, with a (?) that explains what a second opinion is. When the second
opinion quotes another sentence, *Highlight the quote of: The AI | Second opinion* flips which quote the passage
highlights (the second opinion's in a different colour, and the line under the passage says whose it is); both
judgements stay in view either way.

**Tests:** `tests/test_0112_stronger_model.py`: the stronger reading is the answer and the first one is reported, on
the result, each part and the Results list; no mark when the stronger model agrees; a person's judgements count in
both readings; the whole-result endpoint over the API (404, 400 when already read, 400 when the route has no
stronger model); the page's two choices.

**Not yet done:** tried with the stand-in Claude Code of the dev server (the job, the waiting state and the redraw);
not yet with a real signed-in Claude Code, where the stronger model is the auditor (Opus, or Fable when switched on).
On the Claude routes the stronger model for checks is the auditor, which with Fable off is Opus, the same model that
checks: stepping up then reads again with the same model (as in 0.8). The Map does not show the mark yet.

## 0.11.1 (November 2026): a deep clean after 0.11

No new features. Much had been added between 0.7 and 0.11, so every part of the code was read again for defects,
misbehaviour, redundant code and needless work: the server and the launcher, the checks and the model tasks, the
AI-access guard, the queue and the model backends, the documents and the exploring layer, settings, updating and the
install scripts, the SDG pack, and the page. What follows is what was found and fixed. Every answer still goes
through the quote check, a person can overrule it, every result records how it was made, and `local_only()` is
honoured everywhere (one more place now).

**What Claude may see (three defects of 0.11).**
- A check's written summary was overwritten by the local model's note, because the `:local` part is answered after
  the main part and both stored their rationale on the claim. The summary is shown to a Claude chat through the
  connector's `get_check`, so a local model paraphrasing a licensed passage could have handed its words to the
  cloud. The summary and the model of a claim are now the main part's only (`tasks._store_check`).
- Removing a document never relabelled the tasks still waiting that held its passages (a check by queue, a theme name,
  a concept link), so Claude Code could still be handed the removed document's text. `remove_document` now relabels
  them, as a changed setting does; a task of a removed document counts as *No AI* and leaves the queue.
- The connector's `add_sources` reported a *No AI* document's title in its warnings (`list_documents` hides it as
  *Restricted document 3*). Hidden there too.

**Defects in checks and judgements.**
- A check queued again under a new prompt version (`enlens refresh`) wiped a person's own judgements when the new
  answer was stored. A judgement now survives any second answer, and the earlier AI judgement joins the excerpt's
  history ("answered again").
- The Results list and a result page disagreed about *waiting*: the list looked at the last task row only (with 0.11
  that is usually the `:person` or `:local` part) and never treated a `:local` part not read yet as waiting. One rule
  (`_round_waiting`) for both.
- A judgement on an excerpt no model read (waiting for you) counted as a correction of the AI (the result's
  "Judgements you changed", the Excel summary). It is a review, not a change.
- The single part a person reworded under *Look before checking* was lost when the check went by queue (the wording
  was stored only for two or more parts). Stored for one part too.
- A `:local` part whose answers were rejected three times was invisible: the round said done, the excerpt said read by
  "ai", no error was shown. The result now says so (`local_failed`), lists the technical details, and *Read them again
  on this computer* tries the part once more (`POST …/read-local` retries failed local parts); the progress says it
  while the check runs.
- The progress panel did not know the `note` step 0.11 added (the local model could not be reached, the local
  excerpts were read on this computer): it opened a phantom part and said nothing. Notes are kept and shown under the
  steps (`notes` in the tracker's state).
- `more_passages` reported a wrong round number when nothing more was found (the number of parts plus one).
- The SDG pack's `verify_set` prompt was not told about excerpts read elsewhere when a set was split (the check prompt
  was); it is now.
- The ledger over-reported for a Claude chat: the connector shows the chat the excerpts alone, but the passage before
  each (its context in the app) was recorded as sent. `record_sent(context=False)` for that route; the chat's
  `refers_to` instruction no longer mentions text it is never shown.
- A model test by queue (comparing labels, the benchmark) wrote every passage to the ledger before Claude Code took
  anything, so a test stopped at once still said they were sent. The copy's own ledger is carried into the project's
  afterwards, so only what Claude Code took is recorded.

**Waiting, stopping, claiming.**
- A check waiting for Claude Code never stopped waiting when its document was set to *Only a local AI* meanwhile
  (the task had left the queue; no session would ever answer it). `wait_for` now returns with a plain message.
- *Stop* had no effect while Ollama or another local server was still reading the prompt: the response is sent
  with the first token, so there was nothing to close yet, and the model went on generating the whole answer (and
  the next task queued behind it). The reader now closes the response the moment it arrives.
- The Claude API client retries once at most (the SDK's default of two could hold a task for three times the
  timeout; a Stop in the app took effect only when the call returned).
- `enlens queue run` (answering the queue here) claimed each task unconditionally, overwriting a claim a Claude Code
  session had made in between, so both answered it. It is now the same compare-and-set as `next_tasks`, and a task
  taken meanwhile is skipped.

**Settings, projects, the app.**
- On a `--local-only` installation whose settings file still said `allow_cloud: true` (from before the switch), every
  settings save was refused ("Cloud models are switched off…"), the page sends the stored value back, and the switch
  to clear it is hidden in local-only mode: nothing could be changed at all. `load_settings` now turns both cloud
  permissions off under `local_only()`.
- `POST /api/settings/key` was the one cloud setting that did not honour `local_only()`: 403 now.
- A quick look failed with "Invalid cross-device link" when the data folder is on another disk than the temporary
  folder (Windows `--home D:\…`, a tmpfs `/tmp`), leaving an empty project behind. `shutil.move`, and nothing is left
  on failure. The three raw-body uploads (documents, project zips, quick looks) share one body reader.
- Creating a project whose name was a stale link (the linked folder gone) made the new project at the old external
  path; it is made in the data folder and the link dropped.
- Started from the icon, Ollama was launched only when it was the main AI: with Claude as the main AI and Ollama as
  the local model for restricted documents (or the embedding server), it was not, and *Only a local AI* excerpts
  silently fell to your judgement. It starts whenever any route uses it.
- Numbers in JSON bodies (`k`, `n`, `limit`, `seed`) answered with Python's own message when they were not numbers;
  now "k must be a whole number." like the query values. `start_label_compare` checks the codebook and whether AI
  labels exist before starting a job instead of failing inside it. `GET …/passages/<id>/terms` gives 404 for an
  unknown passage as its siblings do. `POST /api/quit` is documented in `docs/API.md`.
- `enlens prepare theme` made naming tasks whose representatives included *Only a local AI* passages; the queue
  refused them, so such themes were never named. It asks for Claude-readable representatives only, as the app does,
  and counts what was queued. `enlens prepare link` counted pairs for which no task was made. `enlens prepare check
  --file` dropped the `framework` and `code` columns of the CSV. `enlens queue withdraw` without a kind removed the
  tasks of every kind but left the waiting hypotheses behind. `make-tasks audit-vca` re-checked every claim
  (`--sample` defaulted to 1.0 instead of the pack's 0.1).
- `enlens update` on a git copy read the installed extras after the merge, against the new `pyproject.toml`: an extra
  whose packages grew counted as "not installed" and was dropped by the reinstall (OCR or pdfminer silently gone
  after an update). They are read before the merge. On Python 3.10 without `tomli` every extra was dropped (the
  table is now read line by line there). On a detached HEAD the advice was a command git refuses; it says `git
  checkout main`. `update_release` ignored a failed `post-install` and did not pin uv to its own Python as the
  install line does.
- `install.sh` piped uv's installer into `sh`: a failed download went unnoticed and the line ended with "uv was
  installed, but cannot be found". It downloads to a file first and says "Are you online?"; `install.ps1` checks the
  installer's exit code.
- Choosing the Claude API on a one-line install said `pip install 'enlens-claims[anthropic]'`, which a uv tool
  install cannot do; the message now gives the `uv tool install` line for the release's wheel.
- `evaluation.py` had a backslash inside an f-string expression: a SyntaxError on Python 3.10 and 3.11 (the one-line
  install uses 3.12, so it showed only on git copies; four tests failed there). The whole suite passes on 3.11 now.
- A Claude Code plugin file with an opening `---` and no closing one made `check_files` raise instead of listing the
  problem; a `.docx` that is not a zip, has no document inside or holds malformed XML stopped the whole ingest
  instead of being listed under *failed* with the rest going on; a very long "sentence" cut at the length limit lost
  one character where there was no space to cut at.
- The Profile's keyword pass cached each code's denominator by the address of the index's `idf` dictionary; after the
  index was rebuilt (documents added, another project opened) CPython reused the address and the old corpus's
  denominators were used (verified: a coverage of 0.021 where 0.105 was right). The totals now live for one pass.

**Needless work removed (measured on a 150-document, 13,000-passage, one-million-mention project).**
- The label lookups per passage (`WHERE framework=? AND passage_id=?`, two or three per passage in an AI pass) were
  planned over the framework index alone (a project has no statistics): 5.9 ms each at 52,000 labels against 0.014 ms
  with an index on `(passage_id, framework)`, which every project gets on its next open; `DELETE … WHERE task_id=?`
  per answered label task was a full scan (an index on `task_id`).
- Removing a document ran four statements per passage, each a full scan of embeddings, theme members, tasks and
  results (0.62 s for an 87-passage document with 13,000 tasks; tens of seconds on a large project, holding the
  write lock). One set-based statement per table.
- `passages_with_code` (every Search with a code filter) read every label of the codebook (0.47 s at 36,000); the
  code is now in the query. A theme's page read every member of the run with its text (0.115 s per page); only the
  theme's own, merged and moved-in rows are read. The glossary read every mention of the corpus per page (280 ms at a
  million); a term's own document count is kept with it. The term build re-tokenised the same spelling for every
  mention (a third of the build); spellings are cached per build. Term vectors of terms a rebuild dropped stayed for
  good (a few MB a rebuild); pruned.
- A search export ran the whole search once per thousand lines (50 times for 50,000 hits); once now.
- The Results list with a filter ran the five whole-table reads of `history` twice; once, with the counts over all
  and the filter applied in memory. An Excel download computed the history and every result two or three times
  (one sheet each); a `ResultCache` computes them once for all the sheets.
- `_usable_embedder` ran the full embedding status (three counts over the embeddings) per check, per batch item and
  per result page; one row is enough. The document viewer's blocks view also fetched up to 200 passage texts it
  never used. The FlexiConc export was read into memory as a whole (hundreds of MB with embeddings); streamed.
  "Ask a stronger model" probed the model server twice. The quick-look list was rewritten on every `/api/state`.
  `advance_queued` read the settings and built a router per hypothesis per 2-second poll; once per call. Changing a
  document's setting on a big project took seconds because the project's default was re-read per task (1.25 s with
  nothing changed for 8,000 tasks); read once, and unchanged rows are not written. The chain numbering of references
  was O(chains × mentions) after every window; one pass. The FlexiConc themes loop walked every sentence of a
  document per passage; bisection.
- The page: the queue notice (with *Start Claude Code*) was rebuilt on every 500 ms poll, losing focus and letting a
  second click send a second start; the `/queue` request kept being sent for boxes no longer on the page (about two a
  second while Claude Code ran); the "Look before checking" watcher and the Settings watchers (model test, Claude Code
  install) kept polling after leaving the page; a job's end drew the queue panel twice; the Documents table was
  rebuilt (a fresh request) after every setting change, losing the ticks, and the Profile drew twice on load; a
  follow-up on a result fetched it twice.

**Redundant code removed.** `gui/core.py` (a 0.4 alias of `home`), `home._first_chat_model`, `access.split_by_level`,
`llm.OpenAICompatibleBackend`, `_probe` (folded into `models(timeout)`), `OllamaBackend.reserve`, `ingest.doc_text`,
`references.references_table`, `_payload_json`, `stamp`, an unused connection in `profile.compare_sample`, the
`terms_by_doc` cache nobody wrote, `installation.post_install(quiet)`, duplicated name tables (`ROUTE_NAMES`,
`OFF_COMPUTER` live in `routing.py` only), three term-cleaning routines (one, `schema.clean_terms`), two
`round_base`, `_installation` beside `installation.info()`, the no-op entries of `MODEL_JOB_KINDS`, two identical
branches in `analysis.interaction_table`, `REPEAT_SAMPLE`, inner imports of modules already imported, and seven
guards around `make_embedder` that already does the check. In the page: dead exports (`frag`, `iconText`,
`GRADE_VERB`, `FOUND_BY*`, `balanceSentence`, `GRADE_ICON`, `PROMISE`, `plainSection`, the unreachable "starred"
codes), unused imports, five copies each of `plural`/`shortTitle`/`runningJob`/`heatCell`/`jobCard` folded into
`lib.js` and `progress.js`, 74 CSS rules whose classes no file uses (the 0.6 evidence-balance block, the pre-0.9
settings layout, radio cards…), the duplicate rules at the end of `v09.css` folded into their originals, and the nav
`title` attributes `app.js` overwrote. `features.js` marks Documents and Results as *AI optional* (both start AI
jobs: "Let the AI read this document", "Read the new documents", a second opinion). The auditor's name is computed
in one place (`auditorName` in `lib.js`); the typed-model input has a label; the part sections of a result can take
focus. The release's CSS is in `gui/static/v0111.css`.

Tests: 37 new (`tests/test_0111_bug_hunt.py`), one per defect above where it can be shown: the summary after a
chatty local model and the connector's view of it; the queue after a document is removed; the chat's ledger rows;
the hidden title; waiting that ends when the task leaves the queue; a task Claude Code took meanwhile; a model test
stopped before a batch; relabelling only what changed; a person's judgement after a second answer; the list and the
page agreeing; a judgement on a person's excerpt; the reworded single part; the round number; a failed local part
and its retry; the verifier's prompt; local-only with a stale `allow_cloud`; a stale link; the tracker's notes; the
app's plain numbers, 404 and the 403 key; Ollama started for the restricted model; a Stop before the first token;
the API client's retries; the extra hint; `prepare` by queue, `prepare check --file`, `queue withdraw`; the update's
extras and the detached HEAD; the pyproject reader; the installer; a bad Word file; the forced cut; coverage totals;
the indexes and the set-based removal; `passages_with_code`; a theme's passages under merges and moves; the search
export; the front matter; the page files. Two 0.9 and 0.5 tests follow the changes (`history` and `sources` marked
optional; `pick_chat_model` instead of the removed alias; the connector test imports `home`).

**Not yet done.**
- The Stop while a local server reads the prompt, the Claude API's retries and the one-line install's `curl` change
  were tested with stand-ins and by reading; a real Ollama, a real key and a real Mac or Windows were not at hand.
  The install line is exercised by the release workflow on the three systems.
- Two optimisations the review measured were left for later as larger changes: `history()` and `evidence_map()`
  still parse every check task's payload (full passage texts) only to count passages and collect document ids, and
  the term build's `_grams` still tests every token pair (`_edge_ok`); both matter only on projects of hundreds of
  documents.
- `annotate.check_placement` (the F7 acceptance measure) has no caller yet; it stays for that measure.
- Everything in the *Not yet done* of 0.11.0 still stands (a real signed-in Claude Code with `--disallowedTools`,
  the account kind from `claude auth status`, a real local model reading restricted excerpts).

## 0.11.0 (October 2026): per-document AI settings

Until now the choice was all or nothing: `local_only()` switched cloud models off for a whole installation and a
project ran on one route, so a single licensed PDF or interview transcript forced the whole project onto a local
model. 0.11 lets one project mix documents Claude may read with documents that must stay on the computer, and the
code makes it impossible for a restricted document's text to reach a cloud model. The promise, in the app's words:
*Documents you mark as local stay on this computer. ENLENS never sends their text to Claude, in any feature, and
shows you how much of every other document it has sent.* Every model answer still goes through the quote check, a
person can overrule it, every result records how it was made, and `local_only()` is honoured everywhere.

**Three settings per document** (`documents.ai_access`; NULL: the project's default, `ai_access_default` in the
project's config): *Claude may read it* (`cloud`), *Only a local AI* (`local`: a model server on this computer, or a
person) and *No AI* (`none`: a person only; Search, the keyword Profile, Concepts and Themes still work).
- *Adding documents* asks *Who may read these documents with AI?*, one answer for everything added at once. A new
  project asks with nothing preselected; its first answer becomes the default, which is preselected afterwards.
- The Documents page has a column *AI* with a dropdown per document, a checkbox per row to change several together,
  and a note per document (*Why*, e.g. "publisher licence"), kept and exported with the project; it changes nothing.
- `manifest.csv` may have `ai_access` and `ai_note` columns (per file, for large corpora; a wrong value is reported).
- The connector's `create_project` and `add_sources` take `ai_access`.
- A `--local-only` installation defaults to *Only a local AI* and does not offer Claude.

**Enforcement: one guard where tasks are made and run** (new module `access.py`), never an instruction in a prompt.
- `tasks._insert_task` (every task of every feature passes through it) walks the payload for `passage_id` and
  `doc_id` at any depth and stores the most restricted setting in the new column `tasks.access`. A task without
  document text (search words, parts of a hypothesis) is `cloud`; passages of a removed document count as `none`.
- `tasks.run_one` (and `answer_again`, the old `run`, the label comparison, the model test) refuses, before any model
  is asked, a `local` task on a route that leaves the computer and a `none` task on any route (`AccessError`). A model
  server counts as on this computer only at a loopback address (localhost, 127.x, ::1): one on another machine is
  treated like Claude. With Claude Code, a task the queue would never hand out is refused instead of waited for.
- The queue only ever holds and hands out `cloud` tasks (`mark_queued`, `next_tasks`, `status` and the sidebar count
  check `access` too), so Claude Code never sees the rest. The file queue (`enlens export`) writes only `cloud` tasks.
- Changing a setting applies to every task not answered yet (`access.relabel`); a queued task that is no longer
  `cloud` leaves the queue. What Claude already read stays in the results and the ledger.
- Search by meaning: an embedding server on another computer is not given restricted passages (they are found by
  their words; the status no longer counts them as missing).
- The guard is the backstop: features split their work themselves (below), and a feature that forgets fails loudly
  (`tests/test_0110_no_leak.py` proved it by switching the split off: the guard stopped the first task).

**Mixed processing, feature by feature.** Finding passages is unchanged, so restricted documents still compete for
every check on equal terms; only the reading is split.
- *Checking a hypothesis* (one check, several, a further round, documents added since, a check by queue, a check in a
  Claude chat): a round's excerpts are split into the part the main model may read (`check:<id>`, `…:r<n>`), the
  local part (`…:local`, read by the local model for restricted documents) and the person's part (`…:person`, no
  model: its excerpts are stored as *Waiting for your judgement*). The round is shown as one; each excerpt says who
  read it (Claude, the local model, or you), from the provenance already recorded. The overall answer counts every
  excerpt; a model is told how many excerpts of the round it is not shown, so its note speaks only for its own.
  With a main model on this computer, cloud and local excerpts are read together (no split needed).
- A local part whose local model is not chosen, or cannot be reached, waits for a person instead, and the progress
  says so. A check by queue reads its local part in the app while the app follows it; a check made in a Claude chat
  (or while the app was closed) shows *N excerpts wait for the local model · Read them now on this computer* on its
  result (`POST …/hypotheses/<id>/read-local`).
- Excerpts waiting for you are listed under *Waiting for your judgement* (no longer among "not about this"), with
  the judging options open; they have no *Agree with the AI* and no *Ask the AI to read this again*.
- *Second opinion* and *Read again* follow the excerpt's document: a second opinion on a local excerpt only from a
  second model on this computer; reading again a *No AI* excerpt is refused (409) with a plain message.
- *Profile's AI pass*: each passage goes to its document's reader; *All passages* of a local document run locally, of
  a *No AI* document are skipped (`skipped_restricted`). The setting is looked at again before each passage, so a cap
  reached meanwhile takes effect.
- *Theme names*: representatives from documents the reader may read (topped up from the theme's other passages);
  a theme whose passages are all restricted is named by the local model or keeps its key terms. Key terms sent are
  only words found in the passages sent.
- *Concept links*: snippets from documents the reader may read. A term found only in restricted documents is linked
  by the local model, or not at all. The roadmap allowed "from its labels alone", but a term's label is words of the
  documents, so 0.11 does not send it; *Propose wordings* likewise sends only wordings found in documents Claude may
  read.
- *References*: follow the document; a *No AI* document is refused with a plain message.
- *The SDG pack*: `extract` and `verify` follow their passages; `verify_set` splits like a check (`…:local`), and
  passages of *No AI* documents are left out (the pack has no person's judgement of a single passage).
- *Hypothesis parts and search words*: no document text, unchanged.

**The Claude Code run and the connector.**
- The headless run started from the app is denied Claude Code's own tools that read or write files, run commands or
  fetch pages (`--disallowedTools Bash,Read,Grep,Glob,Write,Edit,WebFetch,…`, which holds for the helper agents too;
  `--allowedTools` only pre-approves) and starts in an empty folder (`~/enlens/claude-runs/work/`, emptied first),
  away from the projects' databases, which hold every document's full text.
- The connector's tools filter restricted documents: `search_corpus` gives lines from documents Claude may read and
  the other hits as `restricted_hits`; `find_concept` example lines and wordings only from them; `document_profile` a
  restricted document's codes, shares and pages without quotes; `start_check` and `more_passages` only the excerpts
  Claude may read, the others counted (`restricted_passages`) and left to the local model or the user; `get_check`
  quotes only from documents Claude may read, restricted evidence as counts and verdicts; `list_documents` each
  document's setting, and the title of a *No AI* document as *Restricted document 3*. The queue tools are covered by
  the guard.

**The ledger of what was sent, and a cap per document.**
- New table `ai_sent(passage_id, doc_id, route, task_id, sent_at, feature)`: one row per passage (and per passage
  shown before it as context) at the moment it leaves: before a Claude API call, when Claude Code takes a batch,
  when a Claude chat is shown excerpts or lines through the connector, when the file queue writes a batch. Local and
  person reading write nothing.
- The Documents page column *Sent to Claude* shows the share of each document's text in distinct passages sent;
  clicking it lists the passages with feature, route and date. *Settings → Technical → What was sent to Claude*
  downloads the list as CSV (`GET …/ai-sent.csv`), for records such as a data management plan.
- The cap (the roadmap's stretch goal; shipped because the ledger landed cleanly): *Claude may read at most N %* per
  document (`documents.ai_budget`). Once reached, its further passages count as *Only a local AI* for new tasks and
  *All passages* of the Profile is not sent for it. It is checked when tasks are made.

**Your Claude account.** *Set up Claude* and *Settings → AI* (Claude API) show *What happens to the text Claude
reads*: the account kind when `claude auth status` reports a plan, otherwise a choice (*Pro or Max*, *Team, Enterprise
or the Claude API*, setting `account_type`). Personal plans: consumer terms; training when the model-improvement
setting is on (5 years' retention, 30 days when off), with a link to turn it off. Commercial: no training, 30 days.
EU-only: mark those documents *Only a local AI*. The panel cites Anthropic's Claude Code data-usage page and the date
its wording was checked (30 October 2026); ENLENS decides nothing there. *Settings → AI* also gets *Local model for
restricted documents* (`restricted_server`, `restricted_model`; a model of a server on this computer, or none).

**Upgrading.** A normal commit on `main`; `enlens update` and a reopen are enough, no new venv. Migrations add
`documents.ai_access`, `ai_note`, `ai_budget`, `tasks.access` and `ai_sent`. A project made before 0.11, on its first
open: its default becomes *Claude may read it* (`local` on a `--local-only` installation), so nothing changes silently;
the tasks not answered yet get their setting (a queued one no longer `cloud` leaves the queue); answers given on a
Claude route (from their recorded provenance) enter the ledger with the time of the answer, and the column says
"since 0.11, plus earlier results ENLENS recorded"; the Documents page shows a one-time banner, *New in 0.11: choose
which documents Claude may read*. Project zips (export, import, *Move ENLENS to another computer*) carry each
document's setting and note; importing a zip made before 0.11 asks the question once for all its documents.

**Answers to the roadmap's open questions.**
- The account kind: read from `claude auth status` when it reports a plan (`subscriptionType`, `subscription` or
  `plan`), else the person picks; the field names are not confirmed against a real Claude Code (below).
- The tool restriction: `--disallowedTools` (present in Claude Code for long) rather than `--tools` (newer), so an
  older Claude Code does not refuse to start; not tried against a real one (below).
- *Only a local AI* without a local model: neither silent nor a question at check time. The excerpts wait for your
  judgement, the progress line and the result say so, and *Settings → AI* is where a local model is chosen.
- The cap: shipped in 0.11 (above).
- Titles of *No AI* documents are hidden where Claude would see them (the connector). The app's own exports (Excel,
  project zips) keep them: they are the researcher's files, and a zip must keep them to move a project.

**Usability, on the way.** The new CSS is in `gui/static/v011.css` (colour tokens of `app.css` only; light and dark,
and 390 px wide, checked with screenshots and no console errors). The banner's link to the column *AI* goes to the
first dropdown on a phone, where the table head is hidden.

Tests: 35 new. `tests/test_0110_no_leak.py`: a project with one document per setting, each restricted one carrying a
marker in every sentence; every task kind (search words, parts, check, further rounds, a batch, second opinion, read
again, labels over all passages, theme names, concept links, references, the SDG pack's extract and verify_set, the
file queue) through a recording stand-in for Claude, the queue through the stand-in Claude Code, and every connector
tool; no marker in anything Claude was given, and nothing marked *No AI* reached the local model either.
`test_0110_access_guard.py` (labels at any depth, refusals before the backend, a model server on another computer, the
queue holding only cloud tasks even when forced, a changed setting applied to tasks not answered yet, the default and
the question once, the manifest, the cap, addresses, embeddings on another computer); `test_0110_mixed_check.py` (one
round, three readers, shown as one; no local model; a local model that cannot be reached; a local main model; a check
in a Claude chat read later on this computer); `test_0110_ledger.py` (rows on send only, by route; the share; the cap
stopping further reading; the CSV and the Documents endpoints); `test_0110_upgrade.py` (a 0.10 project opens
unchanged with its ledger backfilled once; on a local-only installation queued tasks leave; zips carry the settings;
a 0.10 zip asks once; the headless run's arguments and empty folder; the account kind from `claude auth status`);
`test_0110_connector.py`; `test_0110_page.py`.

**Not yet done.**
- The headless run with `--disallowedTools` and the empty working folder was tried only with the stand-in
  (`tests/fake_claude_cli.py`). Needs a real, signed-in Claude Code: does `/enlens-run` still work with those tools
  denied (it needs only Agent and the ENLENS tools), and does the version people run accept the flag?
- Whether a real `claude auth status` reports the plan, and under which field name; until then most people pick their
  account kind in the panel.
- A real local model reading restricted excerpts while Claude reads the rest (only stand-ins were used), and a person
  trying the Documents page, the import question and a mixed result with a real corpus.
- The cap is checked when tasks are made. A label pass by queue hands Claude Code batches of up to 20 at once, so a
  capped document can go over by one batch (a check by one round of excerpts).
- The roadmap's acceptance gates for 0.10 still stand (a fresh Mac and Windows account to a finished check).

## 0.10.2 (October 2026): the icon has its picture, and opens the new version

Two problems met right after updating to 0.10.1 on a Mac. No analysis changes: every answer still goes through the
quote check, a person can overrule it, and every result records how it was made.

**The icon has its picture, always.** The ENLENS icon was drawn when it was made, with the Python package Pillow;
without Pillow (a git copy installed without the `ocr` extra) it silently came out as a blank square on macOS and a
plain shortcut on Windows. The picture now ships with ENLENS (`gui/icons/ENLENS.icns`, up to 1024 pixels for the
Desktop at full size, and `ENLENS.ico`), drawn once by `tools/make_icons.py` from the same logo; Pillow is only a
fallback if the files are missing. An icon made without its picture is given it when ENLENS starts
(`launcher.repair_icons`): on macOS the ENLENS app (and only an app made by `--make-launcher`) gets `ENLENS.icns`
and its Info.plist names it, nothing else changes; on Windows, when the data folder has no `ENLENS.ico`, it is
written and the ENLENS shortcuts on the Desktop and in the Start menu are pointed at it. Linux already used
`logo.svg`.

**The icon opens the version that is installed.** After an update (`git pull`, `enlens update`, the install line),
the copy still running was the old version, and double-clicking the icon only showed it again: the new page files
(read from disk) with the old program, so Settings showed the old version number with the new layout.
- Double-clicking the icon while an **older** version runs now quits it, as *Quit ENLENS* would, and starts this
  version (`launcher.is_older`, `launcher.stop_older`; the log says so). When a check or another job runs in it, it
  is left alone and opened, because quitting would stop that work. A newer copy running is just opened.
- `/api/state` says which version is installed now (`installed_version`, read from the package on disk). When it is
  newer than the running one, every page shows *ENLENS X is installed, but Y is still running* with a *Quit ENLENS*
  button, and the version label in Settings shows *Y · X installed*. (A copy older than 0.10.2 cannot say this; the
  icon handles that case.)

Tests: 10 new (`tests/test_0102_icon_and_restart.py`): the icon files (valid ICNS with the 1024-pixel image, ICO
with five sizes, in the package data); the macOS app and the Windows shortcut get their picture without Pillow; a
blank macOS icon repaired, its start script and other apps untouched, and only once; blank Windows shortcuts pointed
at the picture (a stand-in for PowerShell); which running copy is older; quitting it only when nothing runs; two
real launches, the second quitting an "older" first copy and starting in its place; `installed_version` in the
state; the page files. Two 0.10.1 tests no longer pin the version number (the same fix as for the 0.10.0 tests in
0.10.1).

**Not yet done.**
- The repaired and the shipped icon were checked as files here, not shown by a real Finder or Windows Explorer.
  macOS caches icons: a repaired app is given a new date so Finder notices, but `killall Finder` may still be needed.
  The Windows repair (PowerShell setting `IconLocation` on the existing shortcuts) was tested only with a stand-in.
- Replacing an older copy was tested with two real launches on Linux, not from a real macOS or Windows icon.

## 0.10.1 (October 2026): Settings beside Theme and Quit, and the version in sight

A small polish release, and the first made with the new release workflow from start to finish. No analysis changes:
every answer still goes through the quote check, a person can overrule it, and every result records how it was made.

- **Settings moved to the foot of the sidebar,** in one short list with *Theme* and *Quit ENLENS*, under the line
  that says where text goes. The list above now holds only what you do with the documents (Overview, Documents,
  Explore the documents, Check hypotheses); what you set up for the app is in one place at the bottom, on the
  desktop and in the menu on a phone. *Theme* and *Quit ENLENS* are aligned with Settings (same icon width, padding
  and hover) instead of sitting as two small buttons. Settings still shows as the current page on every Settings
  tab.
- **The version on every Settings tab.** The title row of Settings shows *Version X.Y.Z*; clicking it opens
  *Technical → Where your data is*, which says how this copy was installed and how to update it. Before, the
  version was only in that card, three clicks away, so after `enlens update` there was no quick way to see whether
  the new version was running.
- **Fixed on the way: the release tests no longer break on every new version.** Three 0.10.0 tests had `0.10.0`
  written into them (the message after `post-install`, `enlens update` finding a newer release, and
  `tools/release.py check`/`notes`/`assets`), so the first thing any new tag did was fail its own release workflow
  at *Test and build*. They now follow the package's version, with the next patch as the "newer release".
- The release's CSS is in `gui/static/v0101.css` (colour tokens of `app.css` only; light and dark checked, and at
  390 px wide).

Tests: 5 new (`tests/test_0101_settings_and_version.py`): Settings, Theme and Quit together at the foot and Settings
gone from the list of features; Settings still marked as the current page; the version on the Settings page and
its link; `/api/state` and the page carry the version; the page files. The 0.9 test of the sidebar order no longer
expects Settings at the end of the list of features. Three tests in `tests/test_0100_setup_and_moving.py` follow the version (above).

**Not yet done.**
- Everything in the *Not yet done* of 0.10.0 still stands; in particular this is the first tag whose release
  workflow, draft and publish are to be followed through end to end (check *Actions → Release* after the push).

## 0.10.0 (October 2026): from GitHub to the icon in one line

Getting from the GitHub page to an ENLENS icon took eleven separate actions in 0.9.1, seven of them in a terminal
(git, Python, a venv, pip, `--make-launcher`, Claude Code, its sign-in). 0.10 is Phase 1 of the set-up roadmap, with
the parts of Phases 2 and 3 that live inside the app: one pasted line, then one button. No analysis changes: every
answer still goes through the quote check, a person can overrule it, and every result records how it was made.

**The one-line install.**
- `install/install.sh` (macOS, Linux) and `install/install.ps1` (Windows), attached to every GitHub Release with the
  release's version filled in. The line (`curl -fsSL …/releases/latest/download/install.sh | sh`, or `irm
  …/install.ps1 | iex` in PowerShell) gets uv unless it is there, downloads the release's wheel and checks it against
  the release's `SHA256SUMS`, installs it with `uv tool install` into its own Python 3.12 (uv-managed only, so a
  Homebrew upgrade cannot break it; no git, no venv, no pip, no administrator rights), with the `connector`, `fast`,
  `pdfminer` and `ocr` extras, and runs `enlens post-install`: it records how ENLENS was installed, makes the icon,
  repairs the Claude Code plugin, and opens ENLENS. Running the line again updates. `ENLENS_LOCAL_ONLY=1` and
  `ENLENS_HOME=` are built into the icon; `ENLENS_WHEEL=` installs a local build. The PowerShell script never calls
  `exit`, which would close the window `irm | iex` runs in.
- `installation.py`: how this copy was installed (`git`, `script`, `package`, `pip`), from a marker
  `<sys.prefix>/enlens-install.json` the installers write (a git copy needs none). *Settings → Technical* says it and
  how to update. `enlens post-install [--by script|package|pip|none] [--no-icon] [--open] [--home]`.
- `enlens update` follows the installation: a git copy pulls as in 0.8.2; a one-line install asks GitHub for the
  latest release, downloads its wheel, refuses it unless it matches `SHA256SUMS`, installs it with uv in the same
  place (so the icon and the plugin keep their Python) and runs `post-install` from the new version; on Windows, where
  a running program cannot replace itself, it gives the install line instead. A pip install is told about the line.
- **Releases.** `.github/workflows/release.yml` (the repo had no `.github/` and no workflow): a tag `vX.Y.Z` checks
  that the tag, `pyproject.toml`, `__init__.py` and the top CHANGELOG entry agree (`tools/release.py check`), runs the
  tests, builds the wheel, fills the version into the two scripts and writes `SHA256SUMS` (`tools/release.py assets`),
  tries the one-line install of that build on Linux, macOS and Windows runners (the connector must start and offer
  the queue tools), and uploads everything to a **draft** release whose notes are this entry with the install lines
  on top (`tools/release.py notes`). You check the draft and press Publish; the line always takes the latest
  published release. *Run workflow* by hand builds test copies without a release.

**Set up Claude, in one button.** On the first screen and in *Settings → AI*, *Set up Claude* does every Claude step
still open, in order, and skips what is done:
- Claude Code missing: it shows the command of Anthropic's native installer (`curl -fsSL
  https://claude.ai/install.sh | bash`; `irm https://claude.ai/install.ps1 | iex` on Windows) and runs it after you
  confirm, as a background job (`POST /api/claude-setup/claude-code`); a failure says so and links Anthropic's set-up
  page. `find_claude()` also looks for `~/.local/bin/claude.exe` (Windows).
- Not signed in: it opens a Terminal (macOS) or PowerShell (Windows) window, or the first terminal found on Linux,
  already running `claude` (`POST /api/claude-setup/sign-in`), and checks every few seconds until Claude Code says it
  is signed in; *I have signed in* checks at once, *Stop waiting* stops. No window: the line to type. ENLENS still
  never sees the login.
- The plugin: added straight away, with no second button. The checklist ticks each step as it is done.
- *Set it up yourself instead* keeps the three steps to type.
- **The plugin follows the installation.** When the plugin names another Python or another data folder (ENLENS moved,
  or was installed again), the app writes it again on start and runs the two set-up commands again, quietly, in the
  background (`claude_setup.repair()`); `post-install` and `enlens update` do the same. The Claude desktop app's
  connector entry is pointed at this Python when the one it names is gone (`mcp_server.repair_desktop()`).

**Move ENLENS to another computer.** *Projects → Move ENLENS to another computer → Download everything (.zip)*
(`GET /api/move.zip`): every project (each as its own project zip, `bundle.export_all`) and the settings, never a
saved Claude API key; quick looks not kept stay behind; projects used in place come along as copies. The new
computer's first screen offers *Import from another computer*, and *Import a project (.zip)* takes both kinds of zip
(`POST /api/projects/import`). Each project keeps its name (`name (2)` when taken). The settings come along only when
the computer has no project yet (a computer in use keeps its own, and its current project), and on a `--local-only`
installation never the choice of a cloud AI.

**Scanned PDFs: Tesseract offered, and found.** When a scanned page stays without text because Tesseract is missing,
the notice after adding documents, the Documents page and *Settings → Documents* say how to get it on this system
(Homebrew's `brew install tesseract`, the Windows installer the Tesseract project links to, `apt install
tesseract-ocr`), instead of "ask IT to install Tesseract". ENLENS now finds Tesseract where those installers put it
when it is not on the PATH (`ingest.find_tesseract()`; also used for highlighted copies).

**Usability problems fixed on the way.**
- *Check again* on the Claude Code checklist (and every `GET /api/claude-setup?refresh=1`) showed the status of up to
  half a minute before: the query's value is a list, so `refresh` was never seen. Signing in or installing Claude Code
  was therefore not noticed until the cache ran out.
- A Mac app started from its icon has no Homebrew folder on its PATH, and the Windows Tesseract installer does not add
  itself to the PATH: an installed Tesseract was reported missing. See above.
- After a scanned document, "turn it on in Settings" opened the *Checking* tab; the setting is under *Documents*.
- *Copy* on a terminal line (set-up commands, the Tesseract line) said "Paste it in Claude Code"; it names the
  terminal now.

Tests: 21 new (`tests/test_0100_setup_and_moving.py`): the installation kinds and marker; `post-install` (marker,
icon, plugin repaired with the stand-in `claude`); the plugin repaired only when it names another Python or data
folder, never when local only; the Claude desktop entry; `enlens update` from a release (up to date, waiting,
installed with uv, a wrong checksum refused, Windows, offline) and by kind; `install.sh` with stand-ins for uv and
curl (download, checksum, the uv command, `post-install`; a wrong checksum installs nothing; a local package and the
options; the raw script refuses without a version); the PowerShell script's shape; `tools/release.py` and the
workflow; *Set up Claude* through the API (the stand-in installer `tests/fake_claude_installer.py`, the sign-in window,
the plugin; a failed install; local only; `refresh=1`); moving everything (no key, a fresh computer takes the
settings, one in use keeps its own, local only); Tesseract found and offered; the page files. One 0.8.2 test now
expects the pip install's new message. `tools/dev_server.py --claude-install` shows the whole button with
stand-ins; `--no-tesseract` the Tesseract offer.

**Not yet done.**
- The one-line install was run for real on Linux only (uv, a managed Python 3.12, the icon entry, the marker).
  `install.ps1` was not run (no PowerShell in the build environment), and `install.sh` was not run on a Mac: the
  release workflow tries both on GitHub's runners when the tag is pushed; check that run before publishing.
- The install line works only once a release is **published** (`releases/latest`); the draft from the tag must be
  published first. Until then `enlens update` on a one-line install says it cannot ask GitHub.
- *Set up Claude* against a real Claude Code: Anthropic's installer, the sign-in window on macOS (`open -a Terminal`
  with a `.command` file) and Windows (`Start-Process powershell`), and `claude auth status` after signing in were
  tested only with stand-ins. Re-running `claude plugin marketplace add` / `install` after a move relies on both
  being idempotent, as tested with Claude Code 2.1.312 in 0.9.
- Packaged apps (dmg, setup.exe, AppImage), the in-app update button and signing (Phases 2 to 4) are for later
  releases; the marker already knows the kind `package`.
- Gate A of the roadmap (a fresh Mac and Windows account reach a finished check with the line and the button) is
  for a person to run.

## 0.9.1 (October 2026): link buttons readable on hover

- **A primary button made from a link stays readable under the mouse.** On the Overview, *Finish the set-up* (and
  *Set up Claude Code*) turned into an empty teal bar when hovered, most visibly in the dark theme; so did other
  link buttons such as *Add documents* on the first-run page. The general link hover colour (`a:hover`) outranked
  the button's own, so the text took the colour of its own hover background. Link buttons now keep their button
  colours (`a.btn:hover`, `a.btn-primary:hover`, `a.btn-danger:hover`, `a.btn-outline-danger:hover`).
- Tests: 1 new (`tests/test_090_subscription_first.py`): link buttons keep their colours on hover.

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
