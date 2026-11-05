# Changelog

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
