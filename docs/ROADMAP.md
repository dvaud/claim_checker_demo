# ENLENS roadmap

Where ENLENS is going, and what each release builds. Items move to `CHANGELOG.md` as they are built; this file keeps
what is planned and why. Written 6 November 2026 as a roadmap shared with Margin, revised 8 November 2026 after a
review against ENLENS 0.14.6's code, and moved here on 10 November 2026. Margin, a writing companion built on ENLENS's
code, keeps its own plans (drafts, citations written back into Word, finding literature, the outline) in its own
repository; everything in this file is built in ENLENS, and Margin brings it in.

The items keep their letters (A to N), so a changelog entry that names one (A1, H3, K1) still points here. A letter
missing from a section (B1 to B4, C, E, …) is one of Margin's own.

## The rule: as little AI as possible

ENLENS should be a tool that a few prompts to a chatbot cannot replace: it keeps your corpus, your decisions
and your history; it gives the same answer twice; every step can be traced; and most of it runs on your computer
without any model. So every feature is built at the **lowest level that does the job well**:

| Level | What it means | Examples |
| --- | --- | --- |
| **0 · No AI** | Plain code: rules, statistics, text matching, the document's layout | search, C-value terms, k-means themes, kappa |
| **1 · Local program** | A program or library on this computer, still no language model | Tesseract, GROBID, an embedding model for search by meaning |
| **2 · Local model** | A language model on this computer (Ollama, LM Studio…) | labelling passages when no Claude may read them |
| **3 · Claude** | Only where 0–2 cannot do it well enough, and only for documents Claude may read | a hard check, a second opinion |

Each item below says its level. Where an item has an AI part, the AI part is optional, the rest works without it, and
what the AI says is still quoted, checked against the text and yours to overrule. Online lookups that are not AI
(OpenAlex, Crossref) still send words off the computer: they follow each document's AI setting and are switched off
by `--local-only`.

**Where it is built.** Everything here is built in ENLENS. Margin is built on ENLENS's code and brings in each ENLENS
release with its sync (`tools/sync_enlens.py` in Margin), so a feature both apps need, or one that changes code they
share (`ingest.py`, `terms.py`, `routing.py`, `llm.py`, the task queue), is built here once and never twice.

## Where things stand (13 November 2026)

| Release | What it built, and what waits |
| --- | --- |
| **0.15** | Released as 0.15.0 (8 November 2026), with patches up to 0.15.7: A0 to A5, H1, CI on three systems and the beta channel (J1 items 1 and 6), the rollback runbook (J1 item 10), versions on results (J4.2), issue forms and `SECURITY.md` (J4.5), and the half of the validation report that needs no AI (J4.3). J4.1 is dropped: ENLENS gives no citation file or DOI, by choice. |
| **0.16** | Released as 0.16.0 (9 November 2026) and 0.16.1: H3, H2, H6 for `gui/server.py`, F4, F2, F5 and K1. Not built yet, and waiting for a later release: A6, D1 to D4, B5, G5, the AI mix (I5, H4, I1, I2, I4), H5, and `docs/METHODS.md` and `docs/PRIVACY.md` (J4.4). |
| **0.17** | Released as 0.17.0 (12 November 2026): the sidebar of seven places, key terms without each language's common words, small fixes from use (M1, M2, M4, M6), the design guide (`docs/DESIGN.md`) with one look on every page, and working together, live: L1 to L5 (private until shared, one owner, a shared folder looked at every couple of minutes, the Team tab). Its release candidates were 0.17.0rc1 to rc5. Not tried yet between two computers on a real OneDrive, Dropbox or network drive, nor on a real Windows PC; four smaller points wait for a later release ([below](#017-working-together-live)). |
| **0.18** | Released as 0.18.0 (13 November 2026), after three candidates: Owner, Co-owner and Member roles with merges no file can abuse; a storage space of the team's own (L6, at Backblaze or Cloudflare, sealed and signed), an easier shared folder (L7), M3, M7, M8 and N1. Not tried yet with real accounts at the two services, nor by a team on real computers. |
| **0.18.1** | Every open item that was not an XL, entirely new feature (planned 13 November 2026, built in two parts side by side): A6 (reader 5), B5, D2 to D4, H4, H5, H6 for `claimcheck.py`, I1, I2, I4, I5, K2 (Level 0), N2, N4, the rest of J4.2, J4.4, J1 items 3 to 5, 7 to 9 and 11, J2 items 2, 5 and 6, and the open points of L after 0.17.0. Left: D1, G5 and N3 (large new features), J4.3's AI half, J1.2 and J2.4 (below). |
| **0.18.4** | The half-built items (13 November 2026): K2's AI draft of a theory's concepts, the AI half of the validation report (J4.3: an invented gold set and a recorded run on Claude), branch and tag rules on GitHub (J1.2), the manual arranged by purpose (J2.4), and `views/sources.js` split (H6). Left: D1, G5 and N3 (large new features), a recorded run on a local model, and the tries only a team can make. |

## Releases 0.15 to 0.17

The ENLENS candidates in two releases (agreed 8 November 2026). 0.15 changes how documents are read; 0.16 builds on
that text and changes how the AI is used. Each has one main change to results, so its test and its validation report
measure that change alone. An item marked **⚠ results** can give different answers for the same documents; its
release notes list it under *Changes that can alter your results*.

**Each release: build, test, refine.** The items are built in the order below. Then a release candidate
(`0.15.0rc1`) is in use for at least a week (J0), with further candidates while testing finds problems, and then the
release. Its patches (0.15.1, …) refine what use shows; new features wait for the next release. 0.15 goes out as one
release (decided 8 November 2026): the work before it is not released as a 0.14.x patch.

### 0.15: text you can trust, and results you can trace

1. **Groundwork** (built on the branch `fix-before-0.15`): which reader read each document (A0, first half), the
   ENLENS version on every result (J4.2), and the release-candidate tooling (J1 item 6, first half).
2. **What the test needs:** CI on all three systems on every push (J1 item 1), *Try new versions early* in Settings
   so testers get each candidate (J1 item 6, second half), a rollback runbook (J1 item 10), and plain-language issue
   forms with `SECURITY.md` (J4.5).
3. **H1 `enlens measure`**, run on today's reader first: the figure A1 is measured against.
4. **A1 the new reader** · ⚠ results. In its own module, raising `ingest.READER`.
5. **A2 block kinds, then A3 tables** · ⚠ results. Both change what becomes a passage, so they change results in the
   same release as A1.
6. **A5 the reading report**: it reports what A1 to A3 did.
7. **Read with the new reader** (A0, second half): it can only be built and tried once there is a second reader.
8. **A4 the reading view**, with *Restore* and *Leave out*: it needs A2 and A3, and a person's corrections are kept
   when a document is read again.
9. **Before the candidate:** `CITATION.cff` and a DOI (J4.1), the half of the validation report that needs no AI
   (J4.3), and *Coming in 0.16* in the notes (J4.6).

### 0.16: working with the text, and the AI mix

1. **H3 recompute only what changed, then H2 faster search**: speed first, measured by H1, before features add load.
   H2 keeps the ranking in Python, so it does not change results.
2. **A6 tables, figures and images** · ⚠ results. Early, so concepts (D) and everything after read the new text, and
   far from the AI mix, so the validation report can tell the two changes apart.
3. **F4 the research log, then F2 notes and highlights, then F5 history**: the log first, so it records everything
   after it; history needs the log.
4. **K1 your own codebook**: after F4 and F5, so every change to a codebook is in the log and can be undone.
5. **D1 to D4 concepts**: relations found from sentences (D2) work far better on 0.15's clean text.
6. **B5 retractions**: ENLENS's first online lookup of works, following each document's AI setting and
   `--local-only` from the first day.
7. **G5 export to NVivo and ATLAS.ti**: after F2, so notes go out as memos, and after K1, so a codebook made in
   ENLENS goes out with its definitions.
8. **The AI mix, last** · ⚠ results. I5 agreement between routes first (it shows whether the local model is good
   enough before anything is routed to it), then H4 fewer and smaller AI tasks, then I1 presets, I2 stepping up from
   the local model to Claude, and I4 carrying on at the plan's limit. I3 is done.
9. **H5 a lighter page, and H6 splitting `gui/server.py`.**
10. **Before the candidate:** the AI half of the validation report (J4.3, from a recorded run), `docs/METHODS.md` and
   `docs/PRIVACY.md` (J4.4, written once the reader and the AI mix are settled), and the rest of J2 (items 2 and 4
   to 6) and of J1 (items 2 to 5, 7 to 9 and 11).

0.16 is the larger, but apart from A6 and the AI mix its features add to ENLENS without changing results. If it grows
too long, the AI mix can become a release of its own. H6 is ongoing: each release splits the module it changes most.

### 0.17: the navigation redesign

The owner's call (9 November 2026): the navigation redesign (the sidebar of seven places, the Hypotheses page, the
right-hand panel, the feature finder, the design guide) reworks how the whole app is reached, so it is 0.17.0. Its
first release candidate, `0.17.0rc1`, went out on 9 November 2026 to try the navigation; the design guide's styling
came in `0.17.0rc5` (11 November 2026), as a first version that 0.17.0 refines.

### 0.17: working together, live

The owner's call (9 November 2026): sharing and sync is a release of its own, after the navigation redesign (0.17.0rc1 to rc5),
which gives it its home: the right-hand panel. Its items are in **L. Working together, live**, below. The first
decision, how the copies reach each other (L5): through a folder the team already shares, with no server. Built in this
order, each step tested before the next:

1. **Groundwork and L1**: private until shared; a codebook changed in two copies merged code by code; a document read
   with the new reader stays one document across copies; a format number on what copies exchange, so a newer file is
   refused in words instead of merged wrongly.
2. **L5**: the exchange through a shared folder, with the switch that keeps documents marked *Only a local AI* or *No
   AI* out of it.
3. **L3 with M6** (the folder looked at by itself; jobs that wait their turn), then **L4** (the Team tab, *Share* and
   *Unshare* on each item's page).
4. **L2**: one owner, and proposals by severity.
5. **Finishing**: a round that stops part-way when ENLENS quits, the work box, and the manual's pages.

Built in 0.17.0 (November 2026). Still to do, after 0.17.0 (the last four built in 0.18.1):

- Try it between two computers through a real OneDrive, Dropbox and network drive, and on a real Windows PC. The
  first try on OneDrive (12 November 2026) found the set-up clunky: [L6 and L7](#l-working-together-live).
- A collaborator's own removal of a document can, in one case, be undone without a word: count it as done only when
  their proposal for it is older than the owner's last change.
- *Become the owner* on a project shared before 0.17.0 turns every earlier removal into a proposal at once: propose only
  those made after the project has an owner, or say so before it is claimed.
- After a take-over, a former owner's late answer to a proposal the new owner has not answered still shows as
  *Accepted* on its card, although it changes no document (the same fix as the point before).
- The randomised test of L2 does not yet try take-overs, zips, the documents switch or the Team tab opened offline;
  add them, with the rule that no setting loosens and no document leaves without the current owner's word.

### Fixed before 0.15 (done)

What a review found that had to change before 0.15 started. All four were dealt with in 0.15.0: results are tied to
the reading of each document (A0, with the ENLENS version on every result, J4.2); the version check, the release
workflow and the withdrawn numbers were made ready for release candidates (J1 item 6); H1 measures reading quality
against a known right answer as well as speed; and 0.15's notes announced its new reading (J4.6).

---

## A. Text parsing and display

Today text from PDFs often runs together, tables come out garbled, and a passage can hold material that matters in
the paper but not in ENLENS (running heads, affiliations, licences, funding, line numbers, captions). Bad text costs
everywhere: search finds noise, themes form around boilerplate (the *Remove theme* feature exists partly because of
this), labels and checks read junk, and quotes fail to place.

**A0. Each document keeps the reading it has** · Level 0 · ENLENS 0.15, built
- Every result points into a document's text: a check's grades and people's judgements, labels and their reviews,
  theme members, references, the SDG pack's claims and evidence, by passage and character position. A document read
  again by a new reader gets other text and passages, so all of them would point at the wrong words.
- Each document records the reader that read it (`ingest.READER`, `documents.reader`, 1 for every document so far),
  and a new reader reads only documents added after the update. **Built.**
- *Read with the new reader* moves one document over when the researcher chooses. (Not "Read again", which is the
  AI reading an excerpt again.) The design:
  - It needs the original file, unchanged, and waits until none of the document's tasks is queued or out with
    Claude Code.
  - Every result is moved by finding its quote again in the new text, nearest to where it was; its passage, offsets
    and page follow. Ids made from passage ids (labels, grades) are made again, and the reviews that name them follow.
  - A check keeps the excerpt it showed as its record: only its pointers into the document move, and its highlights
    are placed within that excerpt.
  - What is derived is made again: keyword labels, the term index, the document's embeddings, inferred interactions
    and reference chains. Tasks named by the old passages are dropped, so they are asked again.
  - A theme run keeps its members where the passages map one to one, and is marked out of date where they do not.
  - The researcher gets a list of everything that could not be placed.
  - Open: a colleague who still has the old reading brings it in as a second copy at the next sync (`sync.py` treats
    other text as another document). The document should remember its old text's fingerprint, so both are known as
    one.
  - Built with A1: it can only be tried once there is a second reader.

**A1. Layout-aware reading of PDFs** · Level 0, Level 1 optional · ENLENS candidate (`ingest.py`) · ⚠ results
- Use the positions pdfminer gives (the `pdfminer` extra) to find columns and reading order, so two columns are not
  read across as one line.
- Join lines broken mid-sentence and hyphens split over lines; split words that run together (`ofthe`,
  `climatechange`) with the corpus's own vocabulary as the dictionary.
- Repair the text layer: ligatures (ﬁ, ﬂ), odd spaces, soft hyphens, broken Unicode.
- Optional local programs for hard cases: GROBID (a local server: sections, references, figures) or Docling. Used
  when installed, never required.
- *Review notes:*
  - ENLENS has starting points. `clean_page` joins words hyphenated across lines, but also joins `long-` + `term`
    into `longterm`: fix that here. `textutil` maps ligatures and soft hyphens, but only to match quotes, not in the
    stored text. `_pdf_breaks` finds paragraphs from line positions, and `references_start` finds the reference list.
  - The new reader goes in its own module from the start: `ingest.py` has 1,233 lines and A1 to A3 would double it.
    It raises `ingest.READER` (A0).
  - pdfminer is optional; the core reader is pypdf. Without pdfminer, documents are still read with pypdf. CI
    installs the extra, so A1 is tested there.
  - On a small or badly read corpus, the corpus's own vocabulary is the broken text. Word splitting needs a base word
    list as well, and splits only when both halves are common words.
  - GROBID needs Java, and Docling downloads several GB of models: heavy on a 16 GB Mac. Leave both until the
    rule-based reader has been measured (H1).

**A2. Know what each part of a document is** · Level 0 · ENLENS candidate · ⚠ results
- Classify every block: body text, heading, abstract, front matter (authors, affiliations, emails, received and
  accepted dates), back matter (acknowledgements, funding, conflicts of interest, author contributions, data
  availability, licence, "Downloaded from…"), caption, table, footnote, references, page furniture (running heads
  and page and line numbers, found by repeating across pages).
- Rules from position, font size, repetition and keyword cues; no model.
- By default only body text, headings, the abstract and (for checks) captions become passages. The rest is kept,
  not deleted: shown greyed out, searchable on request, and used where it helps (the reference list for citations,
  the affiliations for the bibliography).
- *Review notes:* store a block kind on every passage and let each feature filter by it; "captions for checks" would
  otherwise give different features different passages. Showing blocks greyed out needs the reading view (A4), which
  comes after the reading report in 0.15: until then the report (A5) lists the left-out blocks.

**A3. Tables as tables** · Level 0, Level 1 optional · ENLENS candidate · ⚠ results
- Find tables from aligned text positions (as pdfplumber does) and keep them as rows and cells, with their caption.
- A table is shown as a table, can be downloaded for Excel, and is left out of passages unless you include it (a
  table read as prose is what makes most of today's garbled passages).
- GROBID or Docling, when installed, for tables the rules cannot rebuild.

**A4. A clean reading view** · Level 0 · ENLENS candidate (revised: it said "Margin first, then ENLENS", but the
sync only brings ENLENS into Margin, so nothing could take it the other way, and shared work is built in ENLENS)
- The document page shows the text as a clean reflowed article: headings, paragraphs, tables, captions apart, page
  markers in the margin, and what was set aside folded under *Left out of the text*.
- Side by side with the original page (an image of the PDF page via `pypdfium2`), so you can see what the parser
  did.
- *Restore* on any block that was left out wrongly; *Leave out* on one that should not count. Your corrections are
  kept and applied again when the document is read anew.

**A5. A reading report per document** · Level 0 · ENLENS candidate
- How well the document was read: share of text recovered, columns found, words repaired, blocks left out by kind,
  tables found, pages that needed OCR. A warning on documents that read badly, before they spoil a check.

**A6. Tables, figures and images, kept light** · Level 0 · ⚠ results · built in 0.18.1 (`reader5.py`, reader 5)
- Added 9 November 2026, after using 0.15: tables are found only when their columns have clear gaps between them, and
  figures and images do not come in at all. The user wants them "as intended", but only if the project does not
  grow: it is meant to hold a very large corpus.
- Tables also from their ruled lines (the lines and boxes the PDF layout reader gives), not only from the gaps between
  columns, and a table that runs on to the next page joined into one.
- Figures and images as blocks of their own: where they stand on the page, their caption ("Figure 3. …") and the words
  inside them (left out of passages, as now). The picture is drawn from the original PDF when it is shown, as the
  *Page* panel already does, and never stored: a figure costs a page number, a box and its caption. In Word files
  and web pages, only an image's caption and alternative text.
- In the reading view a figure shows its picture, caption and *Open the page*. Captions can count for checks (A2);
  the picture itself is never sent to an AI.
- Reader 4 (raising `ingest.READER`), measured with `enlens measure` on known-text PDFs with ruled tables and
  figures before it ships.
- *Kept out:* stored image files, and reading the text inside pictures (OCR of figures): both heavy for a large corpus.
  Tables in scanned pages stay unfound without GROBID or Docling (A1).
## B. Close the writing loop

B1 to B4 and B6 (citations in Word, reference lists, the reference-list check, re-checking a draft) are Margin's.

**B5. Retractions and corrections** · Level 0 (online lookup, not AI) · built in 0.18.1 (`retractions.py`; works with a DOI only)
- Check every work in the bibliography and every cited work against Crossref's Retraction Watch data; warn on the
  claim's card and in the bibliography.
- *Review note:* this is ENLENS's first online lookup of works (it has no Crossref or OpenAlex code yet), so the
  per-document AI setting check and `--local-only` come with it from the first day.

## D. Connecting concepts

D5 (concepts in the writing) is Margin's.

**D1. A concept map** · Level 0 · ENLENS candidate (`terms.py`, the Concepts page)
- A graph of the concepts that occur together in passages (weighted by how much more often than by chance, such as
  PMI, not by raw counts), clustered, with the links you and the AI accepted drawn in their types (same, broader,
  narrower, related, needs, shapes, clashes with). Filter by document, theme, code or year.
- *Already in ENLENS:* `concordance.py` computes PMI, and `concept_links` stores typed relations with quotes.

**D2. Relations found from the text** · Level 0 · built in 0.18.1 (`textrelations.py`)
- Propose links from the sentences themselves, without AI: "X such as Y", "Y and other X" (broader and narrower),
  "X, also called Y" (the same), "X leads to / causes / reduces Y" (an effect), "X instead of Y" (replaces). Each
  proposal comes with its sentences; you accept or reject it as you do now.

**D3. Paths between two concepts** · Level 0 · built in 0.18.1 (`conceptpaths.py`)
- Pick two concepts and see how the documents get from one to the other: the chain of concepts between them, and
  for each step the passages that join them (the bridge passages). This is a way into an argument the corpus already
  makes.

**D4. Concepts over time and across groups** · Level 0 · built in 0.18.1 (`conceptpaths.py`)
- How a concept's wording and its neighbours change by publication year (from the bibliography) or between groups of
  documents you define (policy against academic, one country against another).

## F. Reading and notes

F1 (a reading queue) and F3 (Zotero annotations) are Margin's. F2, F4 and F5 are built (0.16.0).

**F2. Notes and highlights on passages** · Level 0 · ENLENS candidate
- Your own notes tied to exact words of a document, searchable, and usable as evidence for a claim (quote-checked
  like everything else).

**F4. The research log** · Level 0 · ENLENS candidate
- A dated record of decisions (codebook changes, claims dropped and why, themes removed, documents added), kept by
  itself, with room for your own entries. Valuable for reflexivity in qualitative work, and as an audit trail.

**F5. History inside the app** · Level 0 · ENLENS candidate
- Versions of a project you can go back to: drafts (with what changed between them), codebooks, theme sets,
  decisions and reviews. *Compare with an earlier version* and *Restore*, with the research log (F4) as their story.

## G. Exchange with other tools

G1 to G4 (the rest of Margin's writing companion) are Margin's.

**G5. Export to NVivo and ATLAS.ti** · Level 0 · built (unreleased)
- Codes, labels, quotes, memos and your decisions as a REFI-QDA (`.qdpx`) project.
- Built: `qdpx.py` writes the project (documents as text, codebooks and hypotheses as codes, the labels and judgements
  that count as codings by the person or "ENLENS AI (model)", notes and the research log as memos) and a codebook alone
  as `.qdc`, from the Hypotheses, Codes, result and codebook pages and `enlens export-qdpx` / `export-qdc`.

## H. Optimisation across the board

**H1. Measure first** · ENLENS candidate · ENLENS 0.15
- A benchmark on a large corpus (several hundred PDFs) that times reading documents, search, terms, themes, the
  profile and page loads, and counts AI tasks and their size per feature. Run it each release; optimise what it shows.
- Revised: it also measures **reading quality** against a known right answer, since timing cannot show whether A1
  helped. Two sources of right answers: PDFs made from known text (one and two columns, running heads, line numbers,
  words hyphenated across lines), small enough for the repository; and a fixed list of open-access arXiv papers whose
  LaTeX source gives the true text, downloaded by a script (several hundred PDFs cannot go in the repository, for size
  and copyright).
- The figures: words that match the true text; words run together or broken apart; boilerplate left in passages; how
  many quotes in existing projects still find their place.
- Named `enlens measure`: `enlens benchmark` already scores a model against reference answers.
- Its figures that need no AI are the first half of the validation report (J4.3), in 0.15.

**H2. Faster search** · Level 0 · ENLENS candidate
- A SQLite FTS5 index (in Python's own `sqlite3`) instead of scanning passages, kept up to date as documents come
  and go.
- *Review note:* FTS5 can change results (⚠). It ranks with its own BM25 (k1 = 1.2) and word splitting; ENLENS ranks
  with its own BM25 (k1 = 1.5), and that ranking decides which passages a check reads. Use FTS5 only to narrow the
  candidates and keep the ranking in Python, or keep ENLENS's own index in SQLite. FTS5 is not built into every
  Python, so it needs a fallback.

**H3. Recompute only what changed** · Level 0 · ENLENS candidate
- Adding one document should not redo terms, embeddings, profiles or themes for all of them: cache by passage hash
  and update incrementally.

**H4. Fewer and smaller AI tasks** · Level 0 · built in 0.18.1 (kept answers, a small codebook once per batch)
- Screen passages on this computer (keywords, embeddings, rules) so the AI reads only those that can matter; never
  ask twice for the same passage, prompt and model (cache by hash); send small codebooks once per batch, not once
  per passage. Every AI task avoided is faster, cheaper and more private.
- *Review note:* a task is already never stored twice under the same id (`tasks._insert_task`), and its id names its
  passage (`label:<codebook>:<passage>`). What this adds is a cache by passage text, prompt and model, so the same
  text is not asked again under another id.

**H5. A lighter page** · Level 0 · built in 0.18.1 (lists that load as you scroll, a judgement updated in place)
- Long lists (passages, search lines, claims) load as you scroll; heavy views compute in the background with
  progress; startup kept short.

**H6. Tidier code** · ENLENS candidate · `gui/server.py` split in 0.16, `claimcheck.py` in 0.18.1, `views/sources.js` in 0.18.4
- Split the largest modules along the features they serve, so later changes stay small and syncs conflict less. The
  largest are `gui/server.py` (3,410 lines) and `claimcheck.py` (2,829). Not left to the end: each release splits
  the module it changes most, and the new reader starts in its own module (A1).

## I. A mix of local and cloud AI

Today one route (Claude Code, the Claude API or a local model) answers every task, and each document's AI setting
limits what may go to Claude. A mix would use a local model where it is good enough and Claude only where it is
needed. · Level 2 and 3 · ENLENS candidate (`routing.py`, `llm.py`, the task queue)

*Already in ENLENS:* I3 is done (the mixed check of ENLENS 0.11). I1 and I2 are in part: `routing.py` picks a model
per kind of task, honours Settings, has defaults for each Claude plan, and steps up below 0.6 certainty, after two
rejected answers or on request; new are the presets and the step from the local model to Claude. I5 has its core:
`benchmark.py` compares a model with reference answers by kappa, and I5 runs that on a sample of real work.

**I1. A route per kind of task** · built in 0.18.1 (with Claude Code as the main route)
- In *Settings → AI*: for example labels, links and theme names on the local model; checks and second opinions on
  Claude. Presets: *Mostly local*, *Balanced*, *Best quality*.

**I2. Step up only when unsure** · built in 0.18.1
- The local model answers first; when it is unsure (the certainty ENLENS already measures), the quote check fails,
  or its answer would change a decision, the task goes to Claude, but only for documents Claude may read. Otherwise
  it goes to a larger local model or waits for you.

**I3. Each document's setting, per task** · done (ENLENS 0.11)
- A task's passages decide its route: a check over documents with mixed settings sends to Claude only the passages
  Claude may read, and the rest to the local model, with the result saying which route read what.

**I4. When the plan's limit is reached** · built in 0.18.1
- Carry on locally, or wait and continue later, as you choose, instead of stopping.

**I5. Agreement between routes** · built in 0.18.1 (results not kept between visits)
- A sample of tasks answered by both routes, with their agreement (kappa, which ENLENS already computes), so you can
  see whether the local model is good enough for each kind of task on your own corpus.

## J. Version control, releases, documentation and the ENLENS sync

How real products handle these, and what ENLENS and Margin would take from them. This is developer work: no AI is
involved. J1 and J2 apply to **both apps**; J3 (the sync) and J5 are Margin's only and stay in Margin's roadmap; J4
is ENLENS's only. When J is built, both release guides change with it: the shared steps go into the main ENLENS
guide (Part A of the `margin-release` skill), so Margin's Part B shrinks to what is truly Margin's.

### J0. One pipeline, two products

ENLENS and Margin get **the same pipeline**: the same workflows, the same `tools/release.py` commands, the same
changelog fragments, documentation checks, branch names and steps. What differs is held in one short **product
profile** per app (the same file that J3 stage 2 introduces for the app's name, folders and port), plus each app's own
README and changelog. So:

- **Built once, in ENLENS.** The pipeline is shared code like any shared feature: built in ENLENS first and brought
  into Margin by the sync. Margin never edits the shared pipeline files; it changes only its profile, which the sync
  leaves alone (as it does `README.md` and `CHANGELOG.md` today).
- **The same habits.** A release is the same few commands in either repository, so switching between them needs no
  thought, and a fix to the pipeline reaches both.
- **Recognisably distinct.** Different names, looks, version numbers, release pace and, above all, audiences:

| | **ENLENS**: for scientists who rely on it | **Margin**: its author's own companion |
| --- | --- | --- |
| Who the releases serve | researchers using it in their work, and those who read or review that work | its author, to see what is going on |
| Pace | careful: a release candidate before each minor release, in use for at least a week | as fast as useful: release when ready, release candidates optional |
| CI | public repository: free minutes, all three systems on every push, required checks before merging | private: Linux on every push, three systems on release tags, checks advisory |
| Release notes | plain language, grouped: *New*, *Changes that can alter your results*, *Fixed*, *Privacy* | short: what changed, what came from ENLENS, what is next |
| README | a front door for scientists: what it does, install, how to cite, privacy, the manual | a short front page and the overview of J5 |
| Extras | J4: citable versions, results you can trust across versions, a validation report, methods and privacy documents | J5: an overview of both apps and the roadmap |

### J1. A release pipeline (both apps)

**Now.** In both apps, pushing a tag `vX.Y.Z` runs `release.yml`: check that the versions agree, run the tests,
build the wheel, try the one-line install on Linux, Windows and macOS, then make a draft release that a person
publishes. That is a sound base (checksums, an install test, a person in the loop). The gaps are between
releases: the version is typed in three places, the tests are renamed at every release, and there is no way to try
a release before everyone gets it. (Since ENLENS 0.14.4, `tests.yml` runs the tests on every push to `main`, on
Linux only and without the anthropic, OCR and pdfminer extras.)

**How real products do it, and the plan:**

1. **Continuous integration (CI) on every push.** A second workflow, `ci.yml`, runs the tests and a linter (`ruff`) on
   every push and pull request, on Linux, with the oldest and newest Python ENLENS supports (3.10 and 3.13). The full
   three-system install test stays on release tags. *Why*: a fault is found the hour it is made, while it is cheap
   to fix. Which systems run on a push is a profile setting: ENLENS runs all three systems on every push (since
   0.15.7 all three are required); Margin's profile can run Linux on pushes and all three systems on release tags.
2. **Work on branches, merge through pull requests.** Each feature gets a branch (`feature/word-citations`) and a
   pull request into `main` that CI must pass. Merge with *squash*, so `main` keeps one commit per feature. *Why*: even
   alone, `main` then stays releasable, and each change has a record of what and why. A branch ruleset can
   require the checks to pass before a merge; without one, the habit and CI's red mark do the job. *Done in 0.18.4:*
   a ruleset on `main` asks for a pull request whose seven *Tests* jobs are green, another keeps release tags from
   being moved or deleted; repository admins may bypass both (`docs/DEVELOPING.md`, *Rules on GitHub*).
3. **One version number, from the tag.** The version comes from the git tag (`setuptools-scm`, which fits
   the setuptools build), and `enlens_claims.__version__` reads it from the installed package (`importlib.metadata`).
   *Why*: nothing to bump by hand, and `release.py check` has one thing less to compare. The changelog heading stays
   written by hand.
4. **Changelog fragments.** Each change adds a small file, `changes/<topic>.md`, instead of editing `## Unreleased`;
   the release step joins them into the new `## X.Y.Z` entry and deletes them (as `towncrier` or `scriv` do).
   Prose written for researchers stays as it is. *Why*: two branches, or a branch and an ENLENS sync, never edit the
   same lines of `CHANGELOG.md`, which ends a common source of merge conflicts.
5. **A release pull request.** `python tools/release.py prepare` decides nothing but does all the typing: it
   collects the fragments into the changelog, updates *New in* in the README (J2), and opens a pull request
   "ENLENS X.Y.Z" or "Margin X.Y.Z". Merging it tags the commit, and the tag starts `release.yml` as now. *Why*: the
   release is reviewed as one change before it exists (the pattern of `release-please`, without its commit-message
   rules).
6. **Pre-releases and a beta channel.** `v0.10.0rc1` makes a GitHub pre-release. *Settings → Technical → Updates*
   gets *Stable* (the default) and *Try new versions early*, and the update button follows the chosen channel. *Why*:
   a release is used on your own computer for a few days before everyone else gets it. ENLENS's profile requires a
   release candidate before every minor release; Margin's does not. *ENLENS 0.15, in progress:* the candidate half is
   built (the version check orders `0.15.0rc1` before `0.15.0`, `release.py` takes candidate tags and gives their notes
   install lines of their own, `release.yml` drafts them as pre-releases, and the withdrawn 0.15.0 and 0.15.1 can be
   released for real). The beta channel in Settings comes in 0.15 (step 2). Going back from a 0.15 candidate to
   0.14 on a shared project gives sync clashes on what the candidate made (nothing is lost), so candidates are tried
   on projects not shared.
7. **Repeatable installs.** A `uv.lock` file pins every dependency that CI and the install use, and Dependabot opens a
   pull request when a dependency or a GitHub Action has a new version. Actions are pinned by their commit hash, not
   a moving tag. *Why*: the same release builds the same way next month, and an update is a change you see.
8. **Provenance.** `actions/attest-build-provenance` records which workflow and commit built each release file
   (next to the `SHA256SUMS` there already), so anyone can check a wheel came from this repository.
9. **After publishing.** A job installs from the published release with the real install line on all three
   systems, and runs once a week too (the macOS runners that hold up releases are tested then, not on release day).
   *Why*: the draft test cannot catch a fault in what the public install line downloads.
10. **Rolling back.** A short runbook in `docs/DEVELOPING.md`: a bad release is marked as a pre-release so "latest"
    falls back to the one before, the update button skips it, and the fix follows as a patch release.
11. **Tests named by topic, not version.** `tests/test_word_citations.py` rather than `test_m0_10_0_…`, never renamed.
    *Why*: renaming at every release is churn, and a test's name should say what it guards. In 0.18.1 the existing
    files were renamed too, once, at the owner's request.

**Order:** 1, 3, 4 and 11 first (small, and the others build on them); then 2, 5 and 7; then 6, 8, 9 and 10. For
ENLENS this changed (8 November 2026): what testing 0.15 needs comes first (items 1, 6 and 10, in 0.15), the rest in
0.16.

**Built in 0.18.1:** items 3 (setuptools-scm), 4 (`changes/`), 5 (`release.py prepare` and `tag-release.yml`), 7
(`uv.lock`, Dependabot, actions pinned by hash), 8 (provenance), 9 (`published-install.yml`) and 11 (the tests renamed
by topic, the old files included, at the owner's request). Item 2 waits for a branch ruleset, which only the owner can
switch on.

### J2. README and documentation (both apps)

**Now.** Both READMEs have the same layout (Margin's about 320 lines, ENLENS's about 350), set by the main release
guide. *Install* and *Update* are clear, but the *New in* section and *Earlier releases* repeat `CHANGELOG.md`;
*Exploring the documents*, *What a check does*, *A model per task* and *Privacy* repeat `docs/MANUAL.md`; and the git
copy and the *Layout* table are for developers in the middle of a page for researchers. Each release edits text in
two or three places, and they drift apart.

**How real products do it.** The README is the front door: what it is, a picture, how to install, where to go
next. Release notes live in the changelog and the GitHub Release. Documentation is written once and linked, never
copied, and often arranged by what the reader needs (the Diátaxis split: tutorials to learn, how-to guides for a
task, reference to look up, explanations to understand). Contributor material lives in its own file.

**The plan:**

1. **A README of about 100 lines, written for its audience** (each app's README stays its own and is not synced):
   - *ENLENS*, for scientists: one line on what it is and a screenshot; *Install*; *Update*; *What ENLENS does* (six
     or so bullets, each linking to its manual section); *New in 0.X* (three to five bullets, with whether they can
     change results); *How to cite ENLENS* (J4); *Privacy and your documents* in one paragraph, linking to the privacy
     statement; links to the manual and methods; *For developers* as a link.
   - *Margin*, for its author: one line on what it is; *Install*; *Update*; *New in 0.X*; *What Margin adds to ENLENS*
     (its own features, a few lines); *Where things stand* (J5); *For developers* as a link.
2. **No copies.** *Earlier releases* leaves the README (the changelog and GitHub Releases hold them). The feature
   descriptions move into the manual, where they mostly are already. Margin's manual keeps coming through the sync
   with its own sections added, so it costs no extra writing.
3. **`docs/DEVELOPING.md`** for developers: the git copy, the *Layout* table, tests, the dev server, the release
   (J1) and the ENLENS sync (J3). `docs/EXTENDING.md` stays for add-ons.
4. **The manual in parts:** *Getting started* (a first project, start to finish), a how-to page per feature,
   reference (settings, the command line, the API) and explanations (privacy, how a check works, limits). Optionally
   published as a site (MkDocs on GitHub Pages) built by CI.
5. **Generated, not copied:** `release.py prepare` writes *New in 0.X* from the changelog; the app's *What's new*,
   shown once after an update, reads the same entry.
6. **Checked by CI:** links between documents resolve; every feature in `features.js` has a manual section; the
   README's *New in* matches the changelog.

Items 1 and 3 are done in ENLENS (0.14.0: the README of about 100 lines, `docs/DEVELOPING.md`); items 2, 5 and 6 in
0.18.1 (*New in* between markers, written by `release.py sync-notes`; `tests/test_doc_links.py`). Item 4 in 0.18.4:
the hub groups its pages by what the reader needs (*Start here*, a tutorial with the demo documents; *How to…*;
*Look it up*; *How it works*, four explanation pages), and the task pages keep the steps. A published site (MkDocs)
is not made: the manual stays in the repository, where Margin's sync finds it. Items 3 to 6 are
shared files, built in ENLENS and synced. The README order in the main release guide (Part A)
changes to ENLENS's new one; Margin's order goes into Part B.

### J4. ENLENS for scientists (ENLENS only)

What a tool needs when its users publish with it, review with it, or have to justify it to an ethics board.

1. **Citable versions.** A `CITATION.cff` file (GitHub then shows *Cite this repository*) and a DOI for every release
   through Zenodo's GitHub link, so a paper can cite the exact version it used. The README's *How to cite ENLENS*
   gives both. *Dropped (8 November 2026):* ENLENS gives no citation file or DOI, by choice; the README's *How to cite ENLENS*
   gives the repository's address and the version used.
2. **Results you can trust across versions.** Each release note says, under *Changes that can alter your results*,
   whether the same documents can now give different answers (a new parser, as A1 would be; a new prompt, model or
   rule). Every result already records how it was made; it also records the ENLENS version, and a project opened in a
   newer version says which of its results were made with an older one. Old results stay readable. *ENLENS 0.15,
   built:* every AI answer, run, label and theme run records `app_version`, and a check the version that started it;
   *How these results were made* names it; the Overview says which results an earlier version made, and since 0.18.1
   a check's, a set of themes' and the Codes page's own head.
3. **A validation report per release.** The parts that need no AI (reading documents, search, terms, themes, their
   determinism) are measured by the release workflow on the demo and pilot corpora; figures that need AI come from a
   recorded, dated run. The report goes with the release notes, so a change in accuracy is seen, not guessed. The
   half that needs no AI comes in 0.15 with H1, as 0.15 is the first release that changes results. The AI half came in
   0.18.4: `enlens validate` scores a recorded run against an invented gold set in `tools/validation/` (30
   hypotheses, 110 labelled passages, written by one agent and checked by another, neither seeing a model's answers),
   and the release attaches its report beside the first half. The first run (Claude through Claude Code, 13 November
   2026): 93% right verdicts and 99% right code decisions, the same verdict on a second pass for 97% of hypotheses.
   Not yet: a recorded run on a local model, and right answers from a real project labelled by a person.
4. **Methods and privacy documents.** `docs/METHODS.md`: how a check, labels, concepts and themes work, with their
   references, written so it can back a methods section. `docs/PRIVACY.md`: what leaves the computer, when, to whom,
   and what never does, written for ethics applications and data protection assessments. *Built in 0.18.1.*
5. **Reporting a problem without knowing GitHub.** Issue forms in plain language (what you did, what you expected,
   and the app's technical details pasted with one button), a contact for privacy and security problems
   (`SECURITY.md`), and a note on which versions get fixes.
6. **Changes announced ahead.** A feature that is removed or works differently is announced one minor release
   before, in the notes and in the app. For 0.15, which has no 0.14.x before it, the release candidate and its notes
   are the notice; 0.15's notes announce 0.16's AI mix.

### Order for J as a whole

1. In ENLENS: J1 items 1, 3, 4 and 11, the product profile (J0) and J2 items 3 and 6. Sync them into Margin.
2. In Margin: J3 stage 1 and J5 items 1 and 2.
3. In ENLENS: J2's new README and the rest of J1, then J4 (citation first, as it is the smallest). Sync.
4. Both: J3 stage 2, then stage 3 when ready.

## K. Your own codebook

**K1. A codebook editor** · Level 0, Level 2 or 3 optional · ENLENS candidate (`frameworks.py`, the sync, a page of
its own)
- Make and change a codebook in the app, for one project or for all your projects: codes with a name, a definition,
  when to use it and when not, example quotes from the corpus (quote-checked) and the words it is matched by, in
  groups. Drag to reorder and to move between groups; rename, merge, split and remove codes.
- **Two ways to start.** *Start fresh*: an empty codebook. *From the themes*: the themes already found in the corpus
  (any set of themes in this project, or in your other projects for a codebook used across them) are offered as draft
  codes, each with its name and description (where the AI named it), its key terms as the words it is matched by, and
  its best passages as examples. Removed themes are not offered. Tick the ones to keep, then edit them as above. An
  existing codebook (a CSV you added, or a copy of the SDG targets) opens in the same editor.
- **Within or across projects.** Keep a codebook in the project or with all your projects (the two `frameworks/`
  folders there are today), and move it between them. A project that needs its own changes to a shared codebook
  takes a copy.
- **Try it before labelling** (Level 0): for each code, how many passages and documents the keyword pass would pick,
  with a few of them, so a code that matches nothing or nearly everything shows before any AI labels.
- **Changing a codebook in use.** Labels follow a rename and a merge. A code whose definition changed shows that its
  labels were made with the earlier wording and offers to label only those passages again. A removed code's labels
  wait under *Removed codes* rather than being deleted. Each change goes into the research log (F4) and the
  codebook's history (F5). An edit changes no result by itself.
- **In and out.** CSV stays the file, so a codebook still opens in a spreadsheet. A REFI-QDA codebook (`.qdc`) can be
  brought in from and sent to NVivo, ATLAS.ti and MAXQDA, with G5. Codebooks already sync between colleagues; an
  edit made on both sides comes in as a sync-clash copy, as today.
- Optional (Level 2, then 3): a draft definition and *when to use it* for a code, from its example passages only,
  marked as a draft to rewrite. The editor is complete without it.
- *Already in ENLENS:* codebooks as CSV files (code, description, group), kept in a project or for all projects;
  added, viewed and removed in *Settings → Exploring*; marked as aims a text can help or hinder; brought in by the
  sync. The themes page shows which codes each theme holds. Nothing edits a codebook in the app, and themes cannot
  become codes.

**K2. Theory documents: the lens, not the evidence** · Level 0, Level 2 or 3 optional · built in 0.18.1 (Level 0) and 0.18.4 (the AI draft)
(`store.py` for the mark; `themes.py`, `profile.py`, `retrieve.py` and `terms.py` for leaving theory out;
`codebooks.py` and the K1 editor for codes from theory)
- **Why** (the Tovertafel project, 13 November 2026). Nicolini's *Practice theory, work, and organization* and
  Meadows' *Thinking in Systems* are not about the Tovertafel: they are the theoretical framework the research is done
  through. ENLENS treats them as evidence. They are 21% of the project's passages (1,033 of 4,896), and:
  - 6 of the latest 30 themes are 66–96% these two books, two of them under names that sound like fieldwork (*Rooms
    as physical settings* is 80% Meadows, *Organisational hierarchies* 66%);
  - codebooks made from those themes carry it on: *Resources needed for implementation* is matched by *fish, yield,
    price, profits* (Meadows' fishery), and *Feedback loops* has a Meadows sentence and a staff interview as its
    examples side by side, so the labeller learns to find text like Meadows', not feedback loops in a care home;
  - 146 of 1,435 labelling tasks coded the two books against the Tovertafel codebooks;
  - 7 of 18 check tasks gave 2–4 of their 10 excerpts to the books; none of those 21 was used as evidence, so they
    only took the place of excerpts that might have been.
- **1. Mark a document as theory, and leave it out of the evidence** (Level 0). A document's role is *Theory* (the
  framework the research is read through) or not, set by the researcher in the Documents list and on the document's
  page, never guessed: a study that *uses* practice theory (*A social practice theory approach to … quizzes in
  dementia care*) is still evidence. A theory document is still read, searched, opened and noted as now, but it is
  left out of the themes, the labelling with codebooks, the excerpts a check reads, the key terms, the glossary's
  counts and the evidence map. Marking or unmarking changes no result by itself: the page says which themes, labels
  and checks were made with it in, and offers to make them again without it. Synced like any decision about a
  document. In code the mark needs its own name (for example `role = "theory"`): *framework* already means a codebook.
- **2. A codebook from your theory** (Level 0, Level 2 or 3 optional). A third way to start in the K1 editor, beside
  *Start fresh* and *From the themes*: *From a theory document*. Codes are the theory's concepts (from Nicolini:
  practice, sayings and doings, materials and tools, routines, zooming in and out; from Meadows: stock, flow,
  reinforcing and balancing loop, delay, leverage point, system traps, bounded rationality, resilience, hierarchy),
  each with its **definition quoted from the theory with its page**. Its **examples come from the evidence**, never
  from the theory, and only once the researcher confirms them, so the labeller then finds a reinforcing loop in a care
  home that never says "loop" (staff fear a resident will fail at the game, switch it on less, and grow less sure of
  it). Level 0 offers the candidate concepts from the document's own structure and key terms (headings, glossary
  terms, words set in italics or defined in the text: *a stock is …*); the optional AI part drafts the list and the
  definitions, each quote checked against the text as everywhere, marked as a draft to edit. The codebook is then an
  ordinary K1 codebook: edited, tried before labelling, used in checks and exports.
- Related: N3 (your own working documents) is the other document that is kept in a project but is never a source;
  both are a document's role, one mark with three values (evidence, theory, working document), built with N3.
- *Already in ENLENS:* a check can be limited to some documents by hand; the reader recognises *Theory* and
  *Theoretical framework* as section headings (`reader.py`). Nothing marks a whole document as theory, and every
  document counts as evidence everywhere.

**K3. Non-scientific documents: read, never counted** · Level 0 · built (13 November 2026, unreleased)
(`docrole.py` for the mark, `verdicts.set_aside` for the rule)
- **Why.** A news article, a press release or a company brochure can say what a hypothesis says, but it reports no
  method or data of its own. It should not make a hypothesis supported, mixed or contradicted by itself.
- **The rule** (chosen by the researcher on a second opinion from Fable, 13 November 2026). A document marked
  *Non-scientific* stays in themes, codebook labels, the excerpts a check reads and key terms, and its excerpts are
  judged as any other, but no judgement of them counts in an answer, on either side, the person's own neither. Support
  from non-scientific documents only gives *No scientific evidence found*; beside scientific support they do not raise
  *Partly supported*; a non-scientific contradiction makes nothing *Mixed evidence*. Each answer keeps the one it would
  have counting them (`status_all_sources`), and the assessment in words says what they say and that answer.
- The mark sits beside the role (a theory document can carry it too), set by the researcher, never guessed. Unlike the
  role it changes answers at once: the reply and the research log list the answers it changed. It travels as *Leave
  out* does.
- Not done: a per-hypothesis exception (when newspapers are the material a hypothesis is about, they are its
  evidence), a suggestion from the bibliography's item type (newspaper, blog, web page), and a mark of its own on the
  evidence map (non-scientific documents leave it, as documents that decide nothing).

## L. Working together, live

The owner's model (9 November 2026). Until 0.17.0 (0.14, `sync.py`) colleagues exchanged a project as one zip file by
hand: what is new comes in, each person's judgements are kept under their name, and nothing decided is replaced. L
keeps those merge rules and makes the exchange continuous and selective. **L1 to L5 are built in 0.17.0**; each item
ends with what was decided. The known limits are in the 0.17.0 changelog entry, under *Not yet done*. **L6 and L7**
(planned 12 November 2026, built in 0.18.0rc2) make the set-up easier: a storage space of the team's own
(recommended), and an easier shared folder.

**L1. Private until shared** · Level 0 · built in 0.17.0 (`sharing.py`, the `sync/` package)
- Everything a person makes is theirs alone until they share it: checks of hypotheses, notes and highlights, research
  log entries, codes and codebooks, sets of themes, concepts and their links. "I could check five hypotheses, but
  until I find an interesting one there is no reason for others to see it."
- Sharing is a deliberate act, from the right-hand panel and from the item's own page, and can be taken back
  (unshared items stop syncing; what a colleague already has stays with them, marked as withdrawn).
- *Decided:* per item, and only its maker shares or takes it back; sharing a check shares its codebook. What is no
  one's own (the documents, their AI settings, the bibliography, the AI's work on the documents) stays shared. A
  project exchanged before 0.17.0 counts as shared, item by item. The zip for a colleague holds only what was shared;
  the whole-project zip, for moving, says whose each item is.

**L2. One owner, several collaborators** · Level 0 · built in 0.17.0 (`ownership.py`)
- Each shared project has one owner. Collaborators may change the corpus: add documents, change how one is read,
  remove one. Such a change is a proposal; the owner accepts it according to its severity, for example: adding a
  document, low (accepted at once or with one click); reading a document again or changing its passages, medium;
  removing a document or changing who may read it with AI, high (always the owner's decision).
- Everyone keeps their own working version of the project; accepted corpus changes reach every copy.
- *Decided:* the owner is the project's maker; a project exchanged before 0.17.0 has none until someone chooses *Become
  the owner*. An added document reaches every copy at once, provisionally (the owner's setting accepts it at once, on
  by default), and leaves the others when declined; reading again and *Leave out* / *Restore* wait for the owner;
  removing a document and letting more AI read one are always the owner's word. A stricter AI setting is never a
  proposal, and a looser one takes effect nowhere until the owner accepts it. The owner hands over; a colleague may
  take over when the owner left the folder or was not heard of for 14 days. Proposals and answers travel in zips too.

**L3. Near-live, and light** · Level 0 · built in 0.17.0 (`gui/poller.py`)
- Each copy looks for new shared items every couple of minutes (adjustable; off while offline), brings them in with
  `sync.py`'s rules, and says what came in, in the right-hand panel. No constant connection and no heavy process.
- *Decided:* every 2 minutes (1 to 60, for all projects), soon after ENLENS starts and about 20 seconds after a change;
  paused per project or for all; offline, it tries less and less often (up to every 30 minutes). What came in is kept
  until marked seen. A round runs as a job of the project's queue (M6) and stops between two steps when ENLENS quits.

**L4. The right-hand panel as the place for it** · Level 0 · built in 0.17.0 (`views/team.js`)
- The panel built with the navigation redesign (the research log beside any page) becomes the home of personal notes
  and of the team: what I shared, what came in, proposals waiting for the owner, and Share / Unshare on any item.
- *Decided:* a *Team* tab beside the *Research log*: the folder and its state, *Sync now* and *Pause*, what came in
  with *Mark as seen*, the people, what you shared, documents not on this computer, proposals, the two downloads.
  *Share* and *Unshare* also sit on each item's page and card; codes both people changed are compared in the codebook
  editor.

**L5. How the copies reach each other** (decide first) · built in 0.17.0 (`sync/folder.py`)
- A shared folder the team already has (OneDrive, Dropbox, a university network drive): no server, nothing new to
  run, the documents stay within the institution's storage; each copy writes its shared items there and reads the
  others'. Fits ENLENS's privacy promise best.
- Or a small server: closer to live, but someone must run it, and documents and quotes would pass through it, which
  needs its own privacy statement (J4.4).
- The zip exchange stays, for one-off sharing and for colleagues without the shared folder.
- Privacy carries over: a document marked *Only a local AI* or *No AI* keeps that setting in every copy (the stricter
  setting wins, as in `sync.py` today), and a shared item never carries text a colleague's settings would not allow.
- *Decided:* the shared folder; no server. Each copy writes what its person shared, as numbered files, into a folder
  of its own there and brings in the others' through the same merge as a zip; each document's text and file are
  stored once for the team. A switch per project (off by default; once anyone turns it on, it holds for all) keeps the
  documents marked *Only a local AI* or *No AI* out of the folder; shared items still carry the words they quote.
  What is written is not signed: the folder is shared only with the team.

**Seen in use (12 November 2026).** Setting up the shared folder on a second Mac through OneDrive is clunky: each
colleague needs the OneDrive app, has to add the shared folder to their own files on OneDrive's website (*Add shortcut
to My files*), find it under `~/Library/CloudStorage/` and paste its path. The owner's wish: as little of this as
possible, for teams outside an institution too, free for a research group, and nothing that depends on one person
running something for years. So, in this order of recommendation:

1. **A storage space of the team's own** (L6), at an online storage service: no folder, no sync app, and colleagues
   join from an invite link.
   - a. **Backblaze**: recommended for most research groups (no card, an EU region, each colleague's key limited to
     their own part).
   - b. **Cloudflare**: recommended for large teams that grow quickly (downloads are always free, so many colleagues
     joining costs nothing; it asks for a card).
2. **A folder the team already shares** (L7): OneDrive, Dropbox, SURFdrive, a network drive. Built in 0.17.0 (L5),
   made easier to set up.

The zip stays for one-off exchanges.

**L6. A storage space of the team's own (recommended)** · Level 0 · built in 0.18.0rc2 (`sync/space.py`, `seal.py`,
`storage.py`, `b2.py`, `r2.py`, `views/team-space.js`)

*In plain words:* the team rents a private storage space, free at a team's size, at a company that keeps files online
(technically an *S3 bucket*: S3 is the common language such services speak). ENLENS puts the team's shared work there
and fetches colleagues' work from it by itself. Nobody installs anything or looks for a folder. The owner sets it up
once, in about five minutes; colleagues open an invite link in ENLENS and are in.

What it does, at either service:
- **No server, no sync app, nothing for anyone to maintain.** ENLENS writes and reads the storage itself, with the
  layout `sync/folder.py` already uses (each copy writes only its own part, numbered files are never rewritten,
  `head.json` is written last, a document once for the team). Speed is not a goal: a round every 10 minutes is enough.
- **The storage never reads the work.** Everything is encrypted on the computer before it leaves it, with the
  project's key, which travels only in the invite link after its `#` (never sent to a server). Each person's bundles
  are signed with their own key, and a copy brings in only what its writer signed: a file put in someone else's part
  is set aside. (L5 decided that what is written is not signed; with storage outside the institution it is.)
- **Colleagues never leave ENLENS.** *Invite a colleague* makes a link holding their own access and the project's
  key: no account at the service, no app, no folder.
- **The storage is never the only copy.** Every copy holds the whole project. Storage lost, unpaid or deleted is
  replaced with *Move to another storage space*: the copies write everything once more (the snapshot a copy writes
  when it starts afresh in a folder). Removing a colleague deletes their access, and the project's key is replaced for
  those who stay; what the colleague already has stays with them, as with *Unshare*.
- **The owner's role carries the storage's access** (L2): handed over with the project, so the team never depends on
  the person who set it up.
- **What it costs: nothing at a team's size.** Both give 10 GB free (a corpus of a few hundred PDFs is 1 to 3 GB,
  plus small bundles); looking for changes every 10 minutes is about 4,300 calls a month per person, free at both.

**L6a. Backblaze B2: recommended for most research groups**
- *Tried 12 November 2026:* the sign-up page opens from a plain link
  (`www.backblaze.com/sign-up/b2-cloud-storage-backup-archive`); it asks for an email address and a password only (no
  card, no robot check), and the **storage region is chosen on the sign-up form** (CA East, EU Central, US East, US
  West): ENLENS's steps must say *choose EU Central* before *Create Account*, as it cannot be changed afterwards. The
  dashboard has *Buckets*, *Application Keys* and *Caps & Alerts*. Backblaze's site was down for maintenance the same
  evening: the set-up must say so in plain words and offer to try again later.
- *Free tier (Backblaze's pricing pages, November 2026):* the first 10 GB of storage; uploads, downloads and listings
  free since 2026 (one newer kind of call has 2,500 free a day, which ENLENS does not need); downloads free up to three
  times what is stored each month (only many colleagues joining in one month could go over, by cents). Above the free
  tier: about $6.95 per TB a month (third-party figure).
- **The owner's steps:** (1) sign up, choosing EU Central; (2) under *Application Keys*, *Generate New Master
  Application Key*, and paste its *keyID* and *applicationKey* into ENLENS. That is all: B2's interface for programs
  covers the rest, so ENLENS then, by itself:
  - checks where the data is (the address B2 gives back names the region, such as `eu-central-003`) and says so, or
    warns when it is not in the EU;
  - makes a key of its own with only the rights it needs (buckets and keys, not billing), keeps it in the system's
    keychain and forgets the master key; it suggests generating a new master key afterwards, which voids the pasted
    one;
  - makes the bucket: private, keeping only the latest version of a file (otherwise old versions count towards the
    10 GB), with a random name;
  - writes, reads back and deletes a test file;
  - for each invite, makes the colleague's two keys: one that may write only their own part (B2 keys can be limited
    to a bucket and a name prefix, so the storage itself enforces one writer per part) and one that may read the
    team's;
  - removing a colleague deletes their keys; *Move to another storage space* and deleting the bucket at the end of a
    project use the same key.
- **To check before building:** whether a key made in the dashboard can make other keys (if not, the master key is
  the only way in, as above); what *Caps & Alerts* shows for an account without a card, and what such an account does
  at the free tier's limit (Backblaze has no interface for caps, so ENLENS can only point to the page). A script that
  plays the whole set-up on a test account (sign in, own key, bucket, test file, a colleague's keys, a refused write
  outside their part, clean-up) was written on 12 November 2026 and waits for Backblaze's maintenance to end.

**L6b. Cloudflare R2: recommended for large teams that grow quickly**
- *Why for them:* downloads are free without limit, so many colleagues joining, or one large corpus fetched often,
  costs nothing; the free tier gives 10 GB, 1 million uploads and listings and 10 million downloads a month. But a
  card is needed, and access can be limited to a bucket, not to one person's part, so the signatures are what keeps
  each part its writer's.
- *Tried 12 November 2026:* a new account and a token need no card, but **switching R2 on asks for one** (nothing is
  charged within the free tier). The link that fills in the token form works:
  `dash.cloudflare.com/profile/api-tokens?permissionGroupKeys=[{"key":"workers_r2","type":"edit"}]&accountId=*&name=ENLENS`
  opens it with the name *ENLENS* and *Workers R2 Storage: Edit* on all accounts, ready for *Create Token*. Opened while
  signed out, it led through the login page to an *Invalid redirect_uri* error on sign-up: ENLENS shows the token
  link only once the owner says they are signed in.
- **The owner's steps:** (1) sign up (typing `dash.cloudflare.com/sign-up`); (2) switch R2 on, with a card; (3) the
  token link, then *Create Token*, and paste the token into ENLENS. ENLENS then makes the bucket (in Cloudflare's EU
  jurisdiction), tests it, and for each invite a token limited to the bucket. To give each colleague their own token,
  the owner's token also needs the right to make tokens: a powerful token, kept in the keychain and asked for only
  when inviting or removing someone.
- **To check before building:** whether the page after *Create Token* also shows the S3 access values (an *Access
  Key ID* and *Secret Access Key*), which would save ENLENS a step.

**Order of work for L6:** first a storage layer under `sync/folder.py` (list, read, write a file whole, remove), which
today works on paths throughout; the folder becomes one kind of storage. Then the storage space over S3 with
encryption and signatures, then invite and join in the Team tab, then the one-click set-up for Backblaze and then
Cloudflare (keys on B2, tokens on R2: the only part written per service), then *Move to another storage space* and
removing a colleague. WebDAV (SURFdrive, SURF Research Drive, a university's Nextcloud) can come later on the same
layer.

*Built (14 November 2026, unreleased): WebDAV* (`storage.py` `WebDAVStorage`, `sync/webdav.py`, `views/team-space.js`),
a third kind of storage space on the same layer, with sealing, signatures, the mirror and keeper = owner unchanged.
The owner gives the drive's WebDAV address (SURFdrive's is offered; a Nextcloud's is
`https://<host>/remote.php/dav/files/<user>/`), their user name and an app password (keychain only); ENLENS makes a
folder `ENLENS - <project>` and tests it. A file is written under a hidden temporary name and moved into place, so a
reader never sees half of one on any server. WebDAV has no keys ENLENS can make for others: each member uses their own
account and app password, and the owner shares the folder, by ENLENS through the OCS Share API where the drive has it
(read, change, add, remove; no resharing), otherwise in the drive's website. The invite carries the drive and the
folder, no password; joining asks for the member's own and finds the shared folder (by its name, then any folder at
their root or in `Shared` that holds the team's roster), or lets them choose. An invite's drive name must be its
address's; a drive not used on this computer before (and not SURF's) is confirmed by the member before their password
goes there. One share per user name; removing unshares when nobody staying uses that account; as on R2, the
signatures keep each part its writer's. A hand-over never passes the old owner's app password on; the folder stays in
the first owner's drive (only they share it), so the new owner is pointed to a move into their own drive. *Move to another
storage space* works to and from WebDAV; members follow a move to a drive only from a drive at the same address (else
their copy leaves the old space and asks for a new invite). *Not tried with a real SURFdrive, SURF Research Drive or
Nextcloud account*: built against a stand-in that follows RFC 4918 and Nextcloud's documents (whether SURFdrive's
`nonshib-webdav` address offers the OCS Share API, where shares land, and the exact refusals are unchecked).

*Decided (12 November 2026):* a storage space of the team's own is the recommended way, Backblaze first, Cloudflare
beside it; the shared folder (L7) and the zip stay. Not chosen: **an ENLENS server**, also one ENLENS sets up at a
cloud host with one click (it costs money and needs someone to keep it secure for years); **OneDrive or Google Drive
through their own programming interfaces** (an app registered with Microsoft or Google, which an institution's
administrators often refuse); **a GitHub repository** (accounts, size limits, not meant for storage); **free servers**
such as Oracle's (a card, servers taken back when idle, still a server to keep up); **one member's computer as the
team's host** (colleagues cannot reach a laptop behind most networks, and the team stops when it sleeps).

*Built (0.18.0rc2), and decided while building:*
- **The storage layer** (`storage.py`: list, read, write whole, remove; a folder, or S3 with Signature V4 over the
  standard library) sits under the folder's rules rather than inside them: each copy keeps a copy of the space on its
  computer (`<ENLENS folder>/spaces/<id>/`), laid out as a shared folder, and `folder.py`'s round runs on it unchanged.
  A round brings the space's news into that copy (each file checked), runs, and sends the copy's own part back,
  `head.json` last. So every rule of the folder (roles, privacy, the merge) holds without being written twice.
- **Sealing** with `cryptography` (now a dependency; `pdfminer.six`, in every one-line install, needed it already):
  AES-256-GCM with the project's key, Ed25519 signatures by each member's own key, documents' readings and files under
  a keyed hash of their names. People's names, the documents' text and titles never reach the storage readable.
- **Trust:** the space's *keeper* (whoever set it up; then whoever is the project's owner, L2) signs the list of members
  (`space/roster.json`) and the project's keys sealed to each member (`space/keys.json`). An invite gives a part, its
  storage keys, the project's keys and a one-time secret; the colleague's first file proves the secret, and the
  keeper's next round lets them in. A hand-over to a new owner is signed into the roster (the old keeper signs no later
  one), with the storage keys sealed to the new keeper. Removing a member starts a new key *epoch*.
- **Every 10 minutes at most** (the poller), and about 20 seconds after a change, as with the folder.
- *Not checked against the real services* (no account could be used for tests): Backblaze's v4 calls and its key
  limited to a name prefix, whether a key ENLENS makes may make keys (if not, the master key is kept, with a warning),
  Cloudflare's token link with the right to make tokens (`api_tokens`), and the services' exact words for caps and
  maintenance. Built against stand-ins that follow the services' documents.

**L7. An easier shared folder** · Level 0 · built in 0.18.0rc2 (`views/team.js`, `sync/cloud_folders.py`,
`gui/folder_picker.py`)
- For teams that already share a folder, or cannot use an online storage service: OneDrive, Dropbox, SURFdrive for
  Dutch institutions, a network drive, or Syncthing (computer to computer, no cloud, both computers on at once). It
  works today (L5); what is clunky is choosing the folder.
- *Choose folder…* opens the system's own folder picker instead of asking for a pasted path.
- The cloud folders this computer already has are offered by name: on a Mac those in `~/Library/CloudStorage/`
  (OneDrive, Google Drive, Box) and `~/Dropbox`; on Windows the folders named by `%OneDrive%` and
  `%OneDriveCommercial%`, and Dropbox's.
- What a colleague is sent to join names the shared folder, and their ENLENS finds it among their cloud folders: they
  confirm, not search. When it is not there, one line says what to do (on OneDrive: *Add shortcut to My files* on
  OneDrive's website, and *Always Keep on This Device* so files are not fetched only when opened).

## M. Small fixes from use (November 2026)

Seen while using 0.17.0rc2, and small enough to come before the next feature. Built in 0.17.0rc3: the Overview's
cards and footers in one layout, without its AI box; one AI mark under the hypothesis box; the Evidence map's download
as a small icon; a gap above a running check; the Search page's titles, with every searched word marked, in search by
meaning too; and search by meaning set up only once per project. Built in 0.17.0rc4: M1, M2 and M4. Built in
0.17.0: M5 and M6. Built in 0.18.0rc2: M3, M7 and M8.

**M1. The research log panel makes room for the page** · Level 0 · built in 0.17.0rc4
- With the panel open, the page's content runs right up to it, and at 90% zoom the panel covers the page and cuts the
  *Research log* button in half. The open panel should keep its width at any zoom, sit flush right and leave the page
  a margin.

**M2. A quick look uses its project's codebooks** · Level 0 · built in 0.17.0rc4
- A quick look opened from a project says "Unknown framework" when the codebook chosen for the whole app is kept in
  that project only. Decided: a quick look started from a project can use that project's codebooks.

**M3. Search by meaning set up from the Search page** · Level 1 · built in 0.18.0rc2
- When a model for search by meaning is chosen in Settings but the open project is not set up for it, the Search page
  offers to set it up there, with its progress, instead of a hint that points elsewhere.

**M4. One clear way to open a document from Search** · Level 0 · built in 0.17.0rc4
- Today the title and a bare book icon both open it, and neither looks like it. One visible way, and the icon actions
  labelled.

**M5. Marks to try in mockups** · Level 0 · built in 0.17.0
- The active page tab without the white folder tab (an underline or a tinted pill); a document icon before each title
  in a theme's *Mostly from* line; *reviewed by you* beside a verdict as a small badge, with the words as its tooltip.

**M6. Jobs wait their turn** · Level 0 · built in 0.17.0
- Reading documents with the new reader while another job of the project runs is refused with "Wait until … has
  finished". It should wait in a queue, say so plainly, and be cancellable. When both are asked for, the new reader
  runs before search by meaning, so nothing is prepared twice. Until then, setting up search by meaning while the new
  reader runs is not stopped.
- *Decided:* each project has a queue (*Queued: starts when … has finished*, with *Cancel*). The new reader runs alone
  in its project; adding documents, search by meaning and rounds of the shared folder wait for each other; checks,
  codes, themes and the glossary run beside each other. A job that waits holds no AI model.

**M7. Moving many documents to the new reader** · Level 0 · built in 0.18.0rc2
- Say beforehand how many can move cleanly; report in one line and a compact table instead of one sentence per
  document; one combined review of the results that would lose their place, then *Move anyway*; and *Review next* to
  walk the documents one at a time.

**M8. A local model that works without a terminal** · Level 0 · built in 0.18.0rc2
- Seen on Windows after *Install Ollama*: the person still had to open Ollama, and then a terminal, before a model
  would answer. Someone who has never used a terminal, and doesn't know what a model is, stops there. ENLENS should
  go from the installed program to a model that answers by itself: start Ollama, wait until it answers, then offer the
  model straight away. Nothing to open, nothing to type. Find out first where this run stopped: the installer didn't
  start Ollama, or ENLENS didn't notice it.
- Recommend models for this computer, instead of one model for every computer (today `qwen3:8b`, about 5 GB). Read its
  memory (and a graphics card's, where there is one), free disk space and system, then suggest one model, with a
  smaller, faster one and a larger, better one beside it. Each shows its download size, how quick it will be here and
  what it is good for, in plain words, with one line on what a model is. The same for search by meaning.

## N. Ideas for later

**N1. Near-duplicate hypotheses** · Level 0 · built in 0.18.0
- Lines of a list that say nearly the same are pointed out before checking ("Lines 1 and 2 are very close: check them
  as one?"), and so is a very similar hypothesis checked before in the project (a colleague's too, once L is built).
  Key words only, no AI. An offer, never an automatic merge: lines that differ in strength (*can be observed*,
  *indicates*, *predicts*) stay apart.

**N2. How much thought, not how fast** · Level 3 · built in 0.18.1 (*Let the auditor use Fable* stays its own switch)
- The choice beside *Start Claude Code* becomes *Energy efficient*, *Balanced* and *Intelligence*: which models, and
  how much effort, answer each kind of task. How many helpers run at once moves to Settings.

**N3. Your own working documents** · Level 0 · built (14 November 2026, unreleased) (`docrole.py`)
- A tab under Documents for the researcher's own drafts and notes: kept in the project, read, coded and checked
  against the corpus like any document, but never a source (not in search results used as evidence, the glossary, the
  themes or the evidence map). Build it with K2's theory mark: one role per document with three values.
- *Built:* the role `working` beside `theory` (one role per document: evidence, theory or working document), set in
  *Documents* (a row's panel → *Role*) or on the document's page, and travelling in a shared project as the theory mark
  does. The Documents list grouped by *Role* has *Your working documents*; grouped by the answers, they stand apart
  from *Behind no answer*. A working document is read, searched, opened and noted as any other, and left out of
  themes, the excerpts a check reads (unless the check is limited to it by hand), key terms and the glossary, the
  concepts over time and across groups, a code's examples and the documents behind no answer.
- *Decided (the two open questions):* **its codes** are found as any document's (keyword pass and AI labelling), shown
  on its own page and as its own row at the foot of the profile's grid, and never added into a code's totals or the
  profile's counts: they show what the draft covers beside the corpus. **Its claims are not found by themselves**: no
  rule finds a draft's claims well enough without AI (Level 0), and Margin already has the AI claim finder. Instead,
  any words selected in a working document's text offer *Check against the corpus*, which opens *Hypotheses* with
  them filled in.
- *Not done:* a document page that lists the checks started from it (a check does not record the sentence it came
  from), and the role in the bulk bar (one document at a time, as theory).

**N4. The assessment in words** · Level 0 · built in 0.18.1
- A short written assessment on each hypothesis's page, under its verdict, made by rules from the judgements and
  never written by an AI: every sentence comes from the grades, the quotes and the person's own notes, so it reads the
  same twice and can be traced. For example: "Mixed evidence. Three documents support the hypothesis and one
  contradicts it: *no measurable change in yields* (Jones 2022, p. 12). Most of the support comes from one document
  (Smith 2021, 4 of 6 excerpts). For the second part, *because irrigation expanded*, nothing was found."
- Each sentence has one rule: the verdict and how many documents stand on each side (`claim_status`, `balance`); the
  contradicting side always quoted, so mixed evidence shows both sides; a warning when one document, year or kind of
  document carries most of the support; each part of the hypothesis, what holds and what has no evidence
  (`aggregate`); and what is not counted (excerpts below the strictness setting, and those waiting for the person's
  own judgement).
- **It follows the person's judgement.** It is made again whenever a judgement changes (`effective`), and says what
  the change did: "Your judgement on Jones 2022, p. 12 turned this from Supported to Mixed evidence." The verdict
  with and without the person's judgements is compared to find the change that moved it, and the change goes into the
  research log (F4).
- Shown on the hypothesis page, and in the report and exports. It changes no verdict, so it is not a change to results.
- *Left to the reader:* whether two excerpts that disagree concern a different place, group or period, and how strong
  each source is. The text points to these and does not decide them. If an AI's wording is ever wanted, it is a
  separate draft sentence marked as the AI's (as in K1), never mixed into the sentences made by rules.

**N5. Documents behind no answer** · Level 0 · built (unreleased)
- *The wish:* once several hypotheses are checked, see which documents the answers rest on, and which none do, so a
  corpus is not read through the same three documents. A neutral count, never a verdict on a document: one behind no
  answer may be off the hypotheses' topic, or say it in other words.
- *Built:* how many answers each document is behind, counted as the evidence map counts (an excerpt that counts at the
  strictness; a person's judgement always counts; `document_answers`, `GET /map/documents`). The Documents list can
  be grouped by it (*Behind no answer*, *Behind answers*, *Theory*) and sorted by it (*Most answers*); the line then
  says the number, and a document's panel says it always. After five checked hypotheses one quiet line above the list
  says how many documents are behind none, with *Show them*; the evidence map's line on documents with no excerpt
  that counts links to the same group.
- *Built, the per-hypothesis half:* on a hypothesis's page, under the evidence, a small card *Documents not read in
  this check* splits the documents none of whose excerpts any round of any part showed (the excerpts of documents
  marked *Only a local AI* or *No AI* count as shown) into those that hold the check's words and those that share no
  word with it (`unread_documents`, `GET …/hypotheses/<id>/unread`, fetched after the page is drawn). A check keeps
  only the excerpts it picks, so the keyword search is asked again with each part's claim and search words. The
  stricter bar (`docs_matching(min_words=2)`): an excerpt holds at least two *different* words (stems) of a part and
  its search words, or every one of them when there are fewer; documents sharing one word only are counted apart.
  *Read these* (`read_unread_documents`, job `read-unread`) reads them as a further round limited to them, each part
  the documents that hold its own words, within its limit, as for documents added since; *Search with other words*
  opens the existing box for the second group. Left out: theory documents, documents added after the check or after
  its new documents were last read (its *documents added since*), documents with no readable body text (not read,
  reading failed, or all of it left out), and documents a limited check was limited away from. Non-scientific
  documents are in it. The Excel summary has *Documents with the search words never read*. Changes no result.
