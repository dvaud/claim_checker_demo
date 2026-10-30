# ENLENS: usage manual

ENLENS helps you **explore** your own documents and **check hypotheses** against them. Exploring comes first: every
place a word occurs, the codes each document addresses (the SDG targets or your own codebook), a glossary of terms
grouped into concepts you follow across documents, themes, references inside a document, highlighted copies. Most of
it needs no AI. When you have a statement that could be true or false ("Green hydrogen production increases water
stress in arid regions", "Remote work lowers commuting emissions in large cities"), ENLENS finds the passages of your
sources that bear on it, has a language model grade each one, verifies every quoted word against the source text,
and reports whether the sources support, partly support, contest or contradict the hypothesis, with the document,
page and quote behind every grade.

It is **subscription first** (0.9): the AI is Claude, through Claude Code signed in with your own Claude plan, which
ENLENS sets up and starts for you. Your documents, results and reviews stay on your computer; only the passages
inside the AI's tasks are sent to Anthropic. A model served on your own computer by Ollama, LM Studio, llama.cpp, Jan
or vLLM keeps every word on it, and the Claude API with a team key serves a shared installation. Whoever installs the
app can remove every cloud option for good (`--local-only`).

The first application was the green hydrogen Value Chain Assessment (VCA) by Peyerl and van der Zwaan (2024,
*Discover Sustainability* 5:199). The pipeline built for it (impact claims tagged with UN SDG targets, compared with
an expert table, summarised in a report) is included as the **SDG pack**, sections 9 to 14.

---

## 1. Install

**The one-line install (0.10).** No git, no Python and no venv of your own. Paste one line, and ENLENS ends up as an
icon in its usual place:

| System | Where | Paste this |
| --- | --- | --- |
| macOS, Linux | Terminal | `curl -fsSL https://github.com/dvaud/claim_checker_demo/releases/latest/download/install.sh \| sh` |
| Windows | PowerShell | `powershell -ExecutionPolicy Bypass -c "irm https://github.com/dvaud/claim_checker_demo/releases/latest/download/install.ps1 \| iex"` |

It says what it does in four steps: it gets **uv** (a small installer for Python programs, from Astral) unless it is
already there; downloads the ENLENS package of the latest release and checks it against the release's checksums
(`SHA256SUMS`); installs ENLENS with uv, which brings its own Python 3.12 and keeps it apart from any other Python on
the computer (no administrator rights); and makes the **ENLENS icon** (macOS: Applications and the Desktop; Windows:
the Start menu and the Desktop; Linux: the applications menu) and opens ENLENS. The package includes the connector,
faster search (numpy), pdfminer and the Python parts of text recognition, so no feature needs a later install. Then
press **Set up Claude** on the first screen (section 3, *First use*). Running the same line again installs the newest
release over this one (on Windows quit ENLENS first); your projects in `~/enlens` stay as they are. Options go before
the line as environment variables: `ENLENS_LOCAL_ONLY=1` (nothing may leave the computer, built into the icon),
`ENLENS_HOME=<folder>` (another data folder, built into the icon), `ENLENS_VERSION=0.10.0` (that release).

**From a git copy (developers).** Python 3.10 or newer:

```bash
pip install -e '.[connector]'    # the app, the command line and the Claude Code plugin's connector (recommended)
pip install -e .                 # core only: pydantic, pypdf, openpyxl; the app and the command line
pip install -e '.[fast]'         # numpy: faster semantic search on large projects
pip install -e '.[anthropic]'    # the Claude API (cloud, opt-in)
pip install -e '.[ocr]'          # read scanned PDFs on this computer (also needs the program Tesseract, below)
pip install -e '.[dev]'          # pytest
```

**Scanned PDFs (optional).** A PDF page without a text layer is a picture of text. With the `ocr` extra and the
program Tesseract installed, ENLENS recognises the text of such pages on this computer, one page at a time, at low
priority and on one processor thread, so a local model working at the same time is not slowed down. Install
Tesseract with `brew install tesseract tesseract-lang` (macOS), `sudo apt install tesseract-ocr tesseract-ocr-nld`
(Debian/Ubuntu; one package per language) or the installer for Windows that the Tesseract project links to (UB
Mannheim). Since 0.10 ENLENS also finds Tesseract where these installers put it when that folder is not on the PATH
(Homebrew's folder for an app started from its icon, `C:\Program Files\Tesseract-OCR` on Windows), and notices a new
installation within a minute. Choose the languages in Settings (`eng+nld` for English and Dutch). Without Tesseract a
scanned PDF is listed as "Scanned: no text", and the app says how to get Tesseract on this system (after adding the
document, and in *Settings → Documents*). The one-line install brings the `ocr` extra; only Tesseract is separate.

**Updating.** `enlens update` updates ENLENS the way it was installed (0.10). Installed with the one-line install,
it asks GitHub for the latest release, downloads its package, checks it against the release's checksums, installs it
over this one with uv and brings the Claude Code plugin up to date; on Windows, where a running program cannot
replace itself, it says to quit ENLENS and run the install line again (which does the same). The version you have
is at the top of every *Settings* tab; *Settings → Technical* says how this copy was installed. Installed from the git copy of ENLENS (`git clone …`, then `pip install -e .` in a
venv) every new version is also `enlens update` (0.8.2): it fetches the version from GitHub into the same folder, reinstalls into the
same Python only when the requirements changed (with the extras already installed), refreshes the Claude Code
plugin if one was set up, and says to restart the app if it is running. It changes nothing if files of the copy
were edited by hand, and never touches the data folder. `enlens update --check` only looks.

**An icon instead of the terminal.** The one-line install makes it. From a git copy, run once, as the person who will
use the app:

```bash
enlens-gui --make-launcher                     # add --home FOLDER and/or --local-only if the app is used that way
```

It puts an **ENLENS** icon on the Desktop (macOS: also an app in the user's Applications folder; Windows: also in the
Start menu; Linux: also in the applications menu). Double-clicking it starts ENLENS in the background, with no
terminal window, and opens it in the browser; double-clicking it again while it runs just opens it again. If the
model service is Ollama on this computer and it is not running, the Ollama app is started too. The icon calls the
Python ENLENS was installed in, so another `enlens-gui` earlier on the PATH (for example an old one in Anaconda)
cannot get in the way. **Quit ENLENS** at the bottom of the sidebar stops it (it asks first when a check is still
running). What the app would print goes to `logs/enlens.log` in the data folder. On Linux desktops that ask for it,
right-click the Desktop icon and choose *Allow launching* once.

Check the install with the tests (about 15 seconds, no network):

```bash
pytest
```

A local model server: install [Ollama](https://ollama.com) and pull a chat model (`ollama pull qwen3:8b`), or start
the server of [LM Studio](https://lmstudio.ai) (Developer → Start server) with a model loaded. Optionally pull an
embedding model for search by meaning: `ollama pull nomic-embed-text` (English) or `ollama pull bge-m3` (many
languages, so an English hypothesis also finds Dutch or French passages). Section 5 helps choose.

The commands are `enlens-gui` (the app), `enlens` (or `python -m enlens_claims`; every command takes `--ws FOLDER`,
default `./workspace`) and `enlens-mcp` (the connector).

---

## 2. Concepts

The app speaks plain language; the command line, the API and the code use the technical names. Both are listed.

| In the app | Technical name | Meaning |
| --- | --- | --- |
| Project | Project / workspace | A folder with `config.json` and `enlens.sqlite`. The app keeps its projects in `~/enlens/projects` (or `ENLENS_HOME`); the command line works on any folder given with `--ws`. Both use the same format. |
| Document | Document | One source file (PDF, Word .docx, HTML, TXT or MD; zips are opened). Its text is stored once; every offset points into it. Its paragraphs and headings are kept, so a quote can be cited as "paragraph 6 of 8" (text and web pages) or "page 2, paragraph 3" (PDFs added from 0.6 on; older ones by page). Scanned pages can be read by OCR. |
| Excerpt | Passage | A run of whole sentences (up to about 1,100 characters, some 180 words) inside a document. Excerpts are what the AI reads. Reference lists and unreadable text are skipped. |
| Hypothesis | Hypothesis | What you check. Checked as written, or split into 2 to 5 *parts* that must all hold, each checked on its own. |
| Part | Claim | One statement that is checked: the hypothesis itself, or one of its parts. |
| Judgement | Grade / verdict | What the AI says about one excerpt: *supports*, *partly supports* (an important part is stated; something remains to be inferred), *contradicts* (`refutes`), or *not about this hypothesis*. With a quote and a certainty. |
| Your judgement | User verdict | Your own judgement of an excerpt. It replaces the AI's in the answer and the counts, always counts, and is kept next to the AI's. Agreeing with the AI is a review; choosing another judgement is a change. You can point to the sentence you mean. |
| AI certainty | Confidence | The AI's own estimate (0–100%) of how sure it is. It is not a check of whether it is right: high (≥ 80%), medium (≥ 60%), low. |
| Strictness | Threshold | How sure the AI must be for a judgement to count (default 60%). Weaker judgements stay visible, marked *not counted*. It applies to every result, old and new. |
| Search | Round | One set of excerpts read for a part. *Look for more evidence* and *Search with other words* add searches. |
| Search by meaning | Semantic index | Optional: a vector per excerpt from a local embedding model, so excerpts are found by meaning as well as by shared words. |
| About another group | Scope note | The AI's note that an excerpt is about another group, setting, place or period than the hypothesis names ("about fully remote workers, not hybrid"). Such an excerpt supports the hypothesis at most partly. |
| Second AI model | Second opinion | Another local model that reads the same excerpts again, to show where two models disagree. Its judgements never change an answer. |
| Codebook | Framework | An optional list of codes a hypothesis can be tagged with (like codes in NVivo or Atlas.ti). The 169 SDG targets ship with ENLENS; add your own as a CSV. The AI sees the code's text. |

### Answers

| In the app | Status | Meaning |
| --- | --- | --- |
| Supported by your documents | `supported` | At least one excerpt says what the hypothesis says (and counts), and none says the opposite. |
| Partly supported | `partially_supported` | No excerpt says it all, but one says an important part of it. |
| **Mixed evidence** | `contested` | Some excerpts support the hypothesis (fully or partly) and others contradict it. Read both sides: do they concern the same place, group or period? |
| Contradicted by your documents | `contradicted` | An excerpt says the opposite, and none supports it. |
| Only uncertain evidence | `uncertain` | Excerpts were judged, but the AI was not sure enough about any of them for your strictness. Judge them yourself, or lower the strictness. |
| No evidence found | `unsupported` | None of the excerpts read was about the hypothesis. This is not proof that no document says it: look for more evidence, search with other words, or add documents. |
| Nothing in your documents matched | `no_passages` | No excerpt shares words (or meaning) with the hypothesis. |
| The check did not work | `failed` | The AI's answers did not pass the checks three times. |

A split hypothesis combines its parts, which must all hold: a part contradicted → contradicted (even when other
parts are supported); otherwise a part with mixed evidence → mixed evidence; every part supported → supported; some
parts (partly) supported → partly supported; only uncertain evidence → only uncertain evidence; otherwise nothing
found. The app says which part decides ("Part 2 has mixed evidence, so the whole hypothesis has mixed evidence").
Parts whose check failed are left out (the result says it is incomplete).

**Who says what** lists the documents behind an answer by side. A document counts as supporting if one of its
counted excerpts supports, as partly supporting only if none supports, and as contradicting if one contradicts, so a
document can be on both sides (the app says so). The lean (−1 only contradicting, +1 only supporting) summarises the
excerpts read; it is not a measure of truth.

---

## 3. The app

```bash
enlens-gui                 # opens http://127.0.0.1:8765 in your browser
```

Options: `--home FOLDER` (where projects, history and settings live; default `~/enlens`), `--port 8600`,
`--headless` (do not open a browser), `--local-only` (no cloud option at all; see *For whoever installs the app*),
`--make-launcher` (the ENLENS icon, see section 1).
The app listens on this computer only and answers only to the page it served (a token per run). `--host 0.0.0.0`
exposes it to your network: the page then does not carry the token, so open the link the terminal prints (it ends
in `#token=…`), and only by IP address; do this only on a network you trust. Stop it with Ctrl+C or *Quit ENLENS*. Nothing is loaded
from the internet: no CDN, no fonts, no analytics.

The app is written for researchers who do not program: plain words on every working screen, model names and other
technical details only under *Technical details* and *Settings → Technical*. Each feature says, above its title,
which part of the app it belongs to (*Explore the documents* or *Check hypotheses*) and whether it uses the AI; in
the sidebar a filled **AI** mark means the feature needs the AI, a dashed one that the AI is optional, and no mark
that it never uses the AI (0.9).

**The sidebar (0.9).** *Overview* (the start page of a project), *Documents*, then **Explore the documents**
(Search, Profile, Concepts, Themes) and **Check hypotheses** (Check a hypothesis, Check several, Results). At the
bottom, under the line that says where text goes, *Settings*, *Theme* and *Quit ENLENS* sit together (0.10.1); every
*Settings* tab shows the version of ENLENS at the top right, and clicking it opens *Technical → Where your data is*
(how this copy was installed and how to update it). The *Overview* shows every feature with one line on what it does, whether it uses the AI and what is
already made in the project (a profile, a glossary, a set of themes, results), and the AI in use with what is left
to set up. *Quick look at one document* is there too.

### First use

The welcome screen has three steps (0.9). **The AI**: ENLENS uses Claude Code, signed in with your Claude plan. The
step shows a checklist (Claude Code on this computer, signed in, the ENLENS plugin added) and one button, **Set up
Claude** (0.10), that does every step still open, in order:

1. Claude Code is not on the computer: ENLENS shows the command of Anthropic's installer (`curl -fsSL
   https://claude.ai/install.sh | bash`, or `irm https://claude.ai/install.ps1 | iex` on Windows) and runs it when you
   choose *Install Claude Code*. It needs no administrator rights and takes a minute or two. *Anthropic's set-up
   page* is linked for doing it yourself.
2. Not signed in: ENLENS opens a Terminal (macOS) or PowerShell (Windows) window already running Claude Code. Sign in
   there with your Claude plan (it opens a page in your browser) and close the window; ENLENS checks every few
   seconds and continues by itself (*I have signed in* checks at once). ENLENS never sees your login. If no window
   can be opened, the page shows the line to type.
3. The plugin is not added: ENLENS adds it (as in 0.9).

*Set it up yourself instead* keeps the lines to type. *No Claude plan? Other options* offers a model on this computer
or no AI for now. When whoever installed the app chose a local model, this step is skipped. Then name a **project**
(one per set of documents); used ENLENS on another computer before? *Import from another computer* brings every
project and the settings in one go (section 7). Then **add documents**: choose
files (PDF, Word .docx, HTML, text, Markdown, zip) or a folder. A Word file keeps its paragraphs, headings and the pages
Word marked (0.8); older .doc files are not read: save them as .docx or PDF. The list shows the
title read from each file and warns about unreadable text and very short files (often a landing page instead of the
report). *Open an existing ENLENS project folder (advanced)* links a project made with the command line, without
copying it.

The sidebar always says where text goes: *Claude, on your plan · Only the passages of AI tasks leave this computer*
(the default from 0.9), *Private · The AI runs on this computer* with a local model, or that excerpts are sent to the
Claude API if a shared installation allowed it (section 6).

### Checking a hypothesis

Write one sentence that could be true or false and press *Check* (Ctrl+Enter). When it contains "and", "but" or a
semicolon, the app offers to **check each part separately**. *What happens when you check* explains the four
steps (search, read, verify, answer). *More options*: let the AI think of other words your documents might use,
tag the hypothesis with a code, and limit the check to some documents.

**Look before checking** shows first how the hypothesis will be checked: the parts the AI would split it into (with
*Check each part separately*) and the extra words it would search for. Change a part, remove one or add one; remove
search words that do not fit and add words your documents use; then *Check*. The result records that you set them.

While it runs, the panel shows each step as it finishes: the parts, the other words searched for, how many excerpts
from how many documents, the AI reading them; *Technical details* shows what the model is doing second by second.
*Stop* ends the check and leaves nothing behind. You can use the rest of the app meanwhile.

### Reading and reviewing a result

The answer box says:

- the answer, shown as **the AI's first reading** (an outlined badge) until you have reviewed the judgements, then
  *Partly reviewed by you* and *Reviewed by you*;
- what it rests on: the documents by name and the number of excerpts that count, with a caution when it rests on a
  single document or when one or two unchecked AI judgements decide it;
- how many judgements were too uncertain to count, how many excerpts you reviewed and changed, and how often you
  agreed with the AI (an agreement figure, like an inter-coder check);
- *What to do next*, and your strictness (*Change in Settings*).

**Who says what** names the documents on each side with their locations. Below, every excerpt read is shown with
its judgement, the AI's certainty, whether it counts, the document and where in it ("quote in paragraph 6 of 8 · the
excerpt covers paragraphs 1–6", "quote on page 2"), and the excerpt with the verified quote highlighted. *Show more
of the document* shows the paragraphs around it; *Open the whole document here* shows the document by paragraph or
page, with the quote highlighted, and *Back to the result* returns to the excerpt. Excerpts the AI found not about
the hypothesis are listed at the bottom, so you can check those too. Excerpts are shown with their paragraphs and
headings as in the document. **Open the original** opens the file itself: a PDF at the page, a text file with the
quote highlighted, a web page scrolled to the quote (in browsers that support it).

An orange **About another group** flag means the AI thinks the excerpt is about another group, place or period than
your hypothesis (fully remote workers for a hypothesis about hybrid work): it then counts at most as partly
supporting. Decide yourself whether it is about your hypothesis.

**Ask the AI to read this again** sends one excerpt back to the AI, alone, with your comment as a hint (why you doubt
it). The card then says "Read again by the AI: was Supports (75%), now Partly supports (59%)", with the AI's reason;
the earlier judgements are under *Technical details*. Your own judgement, if you gave one, still counts.

To review, use **Agree with the AI** or **Judge it differently** (supports, partly supports, contradicts, not about
this; each saves at once, with Undo). Add a comment, and **mark the sentence you mean** (select it in the excerpt, or
pick it from a list) when the AI highlighted the wrong one. Your judgement replaces the AI's in the answer and in the
downloads, always counts whatever the strictness, and shows "AI said: …" beside it. *Go back to the AI's judgement*
undoes a change. *Next to review* goes to the excerpts you have not reviewed, those that count first. Agreeing with
an uncertain AI judgement makes it yours, so it then counts. A comment saved without a judgement stays a comment: it
is not a review and does not count as agreeing. After a save, the card keeps its place on the screen and says where
it moved in the list.

**Keep this result up to date** (under the answer):

- When documents were added to the project after the check, it says how many and how many have matching excerpts.
  *Read them* reads those documents as a further search; the check is not run again, so your reviews are kept.
- **Ask a second AI model** has another local model (chosen there or in Settings) read the same excerpts. Each card
  then shows "Second AI model: Contradicts (70%) — disagrees" or "agrees", and *Next to review* goes to the
  disagreements first. Only one model is kept in the computer's memory at a time: the main model is unloaded while
  the second one reads, so this takes a while. The second model's judgements never change the answer; yours do.

**Look harder**: *Look for more evidence* reads the next excerpts that match the same words; *Search with other
words* reads excerpts containing words you type (documents often say "telework" where the hypothesis says "remote
work"). New excerpts are marked *new*, a *Just now* line says what was found, and each search shows the words it
used. When everything that matches has been read, the button says so.

Add **notes** (saved automatically). **Download for Excel (.xlsx)**: a *Summary* sheet (one row per hypothesis:
answer, answer per part, documents per side, excerpts counted and too uncertain, your reviews and changes, notes,
strictness, the AI model for a methods section) and an *Excerpts* sheet (every excerpt read: judgement, judged by
you or the AI, the AI's own judgement and certainty, counted or not, quote and who chose it, document, where, your
comment, the AI's note about another group, its earlier judgement when it read an excerpt again, the second model's
judgement when one was asked, the full excerpt). CSV and JSON are under *Technical details*, for programmers.

### Results and checking several

**Results** lists every hypothesis with its answer, the excerpts that count (and how many were too uncertain), tags
such as *part of a set*, *checked in 2 parts*, *N to review*, *N changed by you*, *has notes*, *N documents added
since*, *models disagree on N*, and the date. Search, filter by answer, open one, or **Download all for Excel** (with a
*Map* sheet). *Read the new documents for all N* brings every result with documents added since up to date in one go;
*Ask a second AI model* does the same for the second model.

**Show as a map** shows all results (or one set) as a grid: one row per hypothesis, one column per document, and in
each cell + supports, (+) partly supports, − contradicts or ± both, with the number of excerpts that count. It flags
answers that rest on one document, and documents that *decide* answers (leaving them out would change those answers),
which are the ones to read most carefully.

**Projects** (the project menu → *Manage projects*): *Download as a zip* puts the whole project in one file (the
database, the documents and their original files, the codebooks) for a co-author or another computer; *Import a
project (.zip)* opens such a file as a new project. *Download the whole project (.zip)* is also on the Results page.

**Check several** checks many hypotheses one after the other: paste them one per line, or load a CSV with a column
`hypothesis` (or `claim`, `text`, `statement`) and optional `framework` and `code` columns. *Show the list* previews
what will be checked; *Check all N* runs them. A hypothesis that cannot be checked is listed and the next one is
checked; a problem with the AI stops the set and keeps what was done. The end screen lists each answer.

### Exploring the documents (0.7)

Before or alongside checking hypotheses, the pages under **Explore the documents** show what the documents say and
where. They replace the Cross-Doc SDG Explorer. Search, key terms, the keyword profile, the glossary and themes by
words need no AI model; the AI only adds readings on top, and every one of them quotes the text and is checked
against it.

**Search.** Every place words occur, one line per place with the words before and after (a concordance), with the
count per document first. *Find* any of the words, all of them in one passage, a phrase, or words near each other
(within N words). Without *exact words only*, a word also finds its other endings ("price" finds "prices"); forms the
search does not include are listed under the count (*Other forms in the documents: commuters*), to add with one
click. Click a word in a line to add it to the search, Shift-click to make a phrase. Sort by document, by the words
before or by the words after. *Words that often appear nearby* lists the words within 2 to 10 words of the places
found, most often or most typical first (point at one for both figures). Every line opens the document at its words,
and its flask button starts a check of what the line says. Download all lines for Excel or as CSV. A *passage* is
the stretch of text the app reads as one unit, up to about 1,100 characters; the location (page, paragraph) is that
of the original.

**Profile.** Which codes of a codebook (the 169 SDG targets by default, the 17 goals, or your own CSV) each document
addresses, how much and where. When documents are added, the app finds candidate codes in seconds by their
keywords (and by meaning, with an embedding model): a *provisional* profile. *Let the AI label the passages* has the
AI read each passage with a candidate code and say which codes really apply (main topic or mentioned; for the SDGs,
whether the passage says it helps or hinders the aim), with a quote and a reason; afterwards it says how many keyword
codes it confirmed, did not confirm, and added. Count by code or by group (the SDG goals). The grid opens the passages
behind each cell. In a document, the **Codes** panel shows every code with its passages, quotes, reasons or the
words that found it (highlighted in the text): agree, change how it applies, reject (with Undo), or add a code of
your own; your labels always count. *Technical details* show the model, its exact version (digest), the prompt and
the seed, and warn when they differ from the last run.

**Concepts.** A glossary of the terms the documents use (one or more words, found by the C-value method; running
heads and page furniture are left out), grouped into concepts: abbreviations and their long forms ("proton exchange
membrane (PEM)"), wordings close in meaning (with an embedding model), links the AI proposes and you accept, and
links of your own. A concept card shows how the documents write it (*Not the same* splits a wording off), which
documents discuss it and where it first appears, every line where it occurs, and related concepts (the same,
broader, narrower, related, often together). *Ask the AI for other wordings* lists wordings the documents use;
add them, or say *Not the same* and they are not proposed again.

**Themes.** What the documents are about, grouped into themes (spherical k-means on the passages' embeddings, or on
their terms without an embedding model; the same documents and settings always give the same themes). Each theme has
key terms, a size, the documents it comes from and the passages that represent it best; grids show themes by document
and by code. Rename, merge and move passages (kept and reapplied to a new set with the same settings); *Let the AI
name the themes* gives names and short descriptions with checked quotes. A small project gets fewer themes than
asked (about three passages a theme).

**In a document.** Besides *Codes*: **Key terms** (the terms that set the document apart; point at one to underline it
in the text), **References** (*Follow the references*: the AI reads the document three passages at a time and links
"it", "they" or "the study" to the name they stand for; select a name in the text to see every later mention), and
**Search** in the document. *Download a highlighted copy* gives the PDF with highlights for the judgements, codes,
concepts or references you choose (exact boxes with the `pdfminer` extra, whole lines otherwise, text recognition for
scanned pages), and a note listing any quote it could not place; other documents come as an HTML copy.

**In a result.** A quote that starts with "it" or "they" says what it refers to (*"it" = green hydrogen*); when the
AI did not say, the excerpt is flagged *Check what the quote's first word refers to*. *Highlighted copy* on an
excerpt, *Highlighted documents (.zip)* in the downloads, and *highlighted* under each document of the evidence map
give the documents with the quotes marked.

**Quick look.** *Quick look at one document* (on the start page, *Check a hypothesis*, and on *Manage projects*) reads one file into a
temporary project and opens it at its key terms: search it, see its codes and references at once. A banner offers
*Keep as a project* or *Discard now*; otherwise it goes to the trash after 7 days.

**For FlexiConc / Cross-Doc** (Projects page) downloads the project as one SQLite file in the FlexiConc layout of
the Cross-Doc SDG Explorer (documents, sentences with their code, reference chains, theme clusters and, with an
embedding model, embeddings), for tools that read that format.

### Settings

Settings has five tabs, each one page with nothing folded inside another (0.9):

- **AI**: which AI reads your documents, as four choices: **Claude Code** (recommended: your own Claude plan),
  **A model on this computer** (automatic, Ollama, or an OpenAI-compatible server such as LM Studio, with the
  address, model and reasoning switch), **No AI (demo)**, and the **Claude API (team key)** for a shared
  installation, behind a confirmation and *Allow cloud models*. With Claude Code: the set-up checklist and *Set up
  Claude Code* (section 6) and *Let the auditor use Fable*. *Save and test* says whether the AI answers (with Claude
  Code: whether it is set up).
- **Checking**: the **strictness** (how sure the AI must be before a judgement counts; it saves at once, applies to
  every result, and reports which answers and counts changed; *Back to normal (60%)*), with **how often you agreed
  with the AI, by its certainty**: a small chart from the excerpts you judged; after 20 judgements it may suggest a
  strictness ("When the AI was at least 70% sure, you agreed with it in 85% … *Use 70%*"); and how new checks start
  (other words, parts, how many excerpts to read and at most how many from one document).
- **Exploring**: the codebook of the profiles, how many themes a new set looks for, and the **codebooks**: view the
  codes, add a CSV codebook, remove one; a CSV codebook can be marked as aims a text can help or hinder, like the SDG
  targets.
- **Documents**: **reading scanned PDFs** (on or off, and the languages) and the embedding model for **search by
  meaning**.
- **Technical**: **AI model per task** (which model answers each kind of task, what it steps up to, the helper on
  Claude Code, a choice per kind, *Use the recommended models*, and for local servers the small model for labels and
  links); with a local model, the **second AI model** and the **context length** (automatic by default, see section
  5) with *Sort the best excerpts again by wording* (off; see the changelog of 0.6.0); **Repeatable results** (the
  seed sent with every request, 42 by default, and a test of whether the server gives the same answer twice); *Test a
  model before trusting it* (section 5); and where your data is.

Old links to a section (`#/settings/second`, `#/settings/calibration`…) open its tab.

When no local model is chosen, or the chosen one is not installed, the app uses one the model server already holds
in memory (so nothing extra is loaded), else the most recently downloaded one, and the test says so.

### For whoever installs the app

- A new installation uses Claude Code on the researcher's own plan (0.9). To use a model on this computer instead,
  choose it once in *Settings → AI* (or let *automatic* find Ollama or LM Studio) and press *Save and test*; an
  installation that already chose a local model keeps it when it is updated. With an embedding model set
  (*Settings → Documents*), new documents are indexed for search by meaning right away.
- To make sure nothing can ever be sent to a cloud model, start the app with `enlens-gui --local-only`, set
  `ENLENS_LOCAL_ONLY=1`, or create an empty file named `local_only` in the data folder. The cloud options (the
  Claude API and Claude Code) are then hidden, the default becomes the local model (*automatic*), the app and its
  API refuse to switch to them, ENLENS never starts Claude Code, and the connector refuses to hand out queued tasks.
- Keep the data folder (`--home`) somewhere that is backed up: it holds the projects, their results and the settings.
- Install it with the one-line install (section 1): it makes the icon. With `ENLENS_LOCAL_ONLY=1` and
  `ENLENS_HOME=<folder>` before the line, both are built into the icon. From a git copy, give the user an icon with
  `enlens-gui --make-launcher` (section 1), with the same `--home` and `--local-only` you would start it with.
- For scanned PDFs, install Tesseract and the `ocr` extra (section 1); Settings shows whether it is available.

**Cost and time.** With a local model, a check costs nothing but time: from seconds to several minutes per call
depending on the model and the computer. With the Claude API one part is two calls of a few thousand tokens.

---

## 4. The command line for hypotheses

```bash
enlens --ws myproject init
enlens --ws myproject ingest ~/Reports/ more.zip
enlens --ws myproject embed --embed-model nomic-embed-text          # optional semantic index
enlens --ws myproject check "Green hydrogen production increases water stress in arid regions." --code 6.4
enlens --ws myproject check "..." --decompose --embed-model nomic-embed-text
enlens --ws myproject batch hypotheses.csv --out results.csv
enlens --ws myproject history --limit 20                            # or --csv all_checks.csv
enlens --ws myproject frameworks
enlens detect                                                       # local servers and their models
```

`check` (or `hypothesis`) prints the verdict, the balance, and per claim the graded passages with quotes and the
passages read without result, as JSON. Options: `--decompose`, `--framework NAME --code CODE` (`--target` still works
for SDG targets), `--k`, `--per-doc`, `--no-expand`, `--threshold`, `--embed-model` and `--embed-url`.

Backends (`--backend`, every model command): `auto` (default: the first local server running, Ollama first), `ollama`
(`--url`, `--num-ctx`, `--think on|off`), `local` (an OpenAI-compatible server, `--url http://localhost:1234/v1`),
`anthropic` (the Claude API: the text read is sent to Anthropic), `baseline` (offline keyword demo). Without
`--model`, a local backend uses a chat model its server already holds in memory, else the most recently downloaded
one, and says which; the Claude API uses `models.verify` of `config.json`. `--num-ctx` is `auto` by default: the
smallest of 8,192, 12,288, 16,384 and 32,768 tokens that fits the largest task (for `run`, the largest pending task).

```bash
enlens --ws myproject ingest scans/ --ocr auto --ocr-lang eng+nld   # scanned pages read by OCR (default: auto, eng)
enlens --ws myproject export-project myproject.zip                  # the whole project in one zip
enlens import-project myproject.zip --ws copy_of_project            # into a new (or empty) folder
```

Exploring the documents (0.7):

```bash
enlens --ws myproject search "electrolyser imports" --mode phrase --out hits.csv   # also --mode any|all|near --near 5
enlens --ws myproject search water --collocates                                    # the words around the hits
enlens --ws myproject terms --rebuild                                              # the glossary; --q water filters
enlens --ws myproject concept "proton exchange membrane" --references              # a concept card as JSON
enlens --ws myproject profile --keywords-only --out profile.xlsx                   # codes by keywords, no model
enlens --ws myproject profile --framework sdg_goals --level group --limit 50       # the AI labels 50 passages
enlens --ws myproject themes --k 20 --mode auto --name-with-model --out themes.xlsx
enlens --ws myproject resolve <doc_id> [--name "the plant"]                        # follow references
enlens --ws myproject annotate <doc_id> --hyp <hyp_id> --layers judgements labels --out highlighted.pdf
enlens --ws myproject export-flexiconc project.sqlite [--no-embeddings]
enlens --ws pilot acceptance samples|measure|search                                 # the 0.7 acceptance measures
enlens --ws pilot acceptance queue --kind label --model haiku [--again]           # 0.8: a run through the queue
enlens --ws pilot acceptance score [--apply]                                      # 0.8: score the runs (docs/MODEL_CHOICE.md)
enlens --ws myproject prepare label|link|theme|resolve|check ["hypothesis"]       # 0.8: tasks for Claude Code
enlens --ws myproject queue status|run|first|hold|go|withdraw [kind]              # 0.8: the queue (run: answer it here)
enlens claude-setup                                                               # 0.8: the Claude Code plugin
```

Every model command takes `--model-seed N` (default: the seed of the settings, 42). `enlens backend-check
--repeatable` asks the model the same question twice and says whether the answers match. `export-tasks` warns when
asked for the 0.7 kinds (`label`, `link`, `theme`, `resolve`): the file queue works for them, but their tasks are
made per project run and are usually answered in the app.

---

## 5. Local models

What ENLENS asks of a model is harder than chat: quotes copied word for word, fine judgement between "partly
supports" and "same topic", and answers in a fixed JSON format. Ollama and the OpenAI-compatible servers are given
the answer's JSON schema, so even small models give valid JSON; the rest depends on the model.

- **Size.** Rough guide by memory (October 2026; check your server's library for current models): about 16 GB runs
  models of 8 to 12 billion parameters, 32 GB runs 27 to 32 billion, 64 GB or more runs the largest. Larger models
  judge better and are slower. If memory allows, an 8-bit version copies quotes more reliably than a 4-bit one.
- **Context.** ENLENS sets the context length on every Ollama request (Ollama's own default is much smaller and
  cuts long prompts without warning). By default it is automatic: the smallest of 8,192, 12,288, 16,384 and 32,768
  tokens that holds the largest task the settings can produce (8 excerpts without reasoning: 8,192). The model's
  working memory grows with it (for qwen3:8b about 1.2 GB at 8,192 tokens and 2.4 GB at 16,384), so this leaves the
  most memory for the model itself. It stays the same between requests, because Ollama reloads the model when it
  changes. Settings → Technical shows the length in use and takes a fixed number instead. With LM Studio or
  llama.cpp set it when loading the model (16,384 covers every task of the app).
- **Memory.** ENLENS loads no model of its own and makes one model call at a time. The second AI model unloads the
  main model first (Ollama) and unloads itself when it is done, so two models are never in memory together; LM
  Studio and other OpenAI-compatible servers have no standard way to unload a model, so there their own setting
  (LM Studio can be set to keep only one model loaded) decides.
- **Reasoning.** For models that reason before answering (Qwen 3 and 3.5, for example), *Settings → AI →
  Reasoning* (Ollama) has four choices:
  - *Off*, the fastest;
  - *Only when judging excerpts*: reasoning where it can help, not for search words or splitting a hypothesis;
  - *On for every step*;
  - *Model's default*.

  The **reasoning budget** (default 1,500 tokens) keeps reasoning within a time limit. A model still reasoning at
  the budget is stopped and asked to answer at once from its notes. At 20 tokens a second that is at most about 75
  seconds of reasoning per judgement, and with *Only when judging excerpts* a check takes a minute or two per part
  instead of half an hour. Whether reasoning judges better depends on the model: compare it with
  `enlens --ws pilot benchmark --model … --think off` and `--think judging` before relying on it. Reasoning text
  that a server puts before the answer is ignored.
- **Embeddings.** `nomic-embed-text` (fast, English), `mxbai-embed-large`, or `bge-m3` (multilingual). Building the
  index embeds every passage once (minutes for ten thousand passages); after that a search costs one short call.
  With numpy installed (`.[fast]`) the comparison is instant; without it, about half a second per search on ten
  thousand passages.

**Test a model before trusting it**: Settings → *Test a model*, or

```bash
enlens --ws pilot benchmark --backend ollama --model qwen3:8b --sample 30
```

It runs the model on tasks the pilot already answered with Claude Opus 5.5 and reports, per task kind: the share of
usable answers, of answers with a quote not in the text, agreement with the reference (same status, and Cohen's κ
beyond chance), and seconds per task. Nothing is stored. The verdict line uses rules of thumb: at least 90% usable
and κ 0.6 is "good enough to use, with review"; at least 75% and κ 0.4 is "usable for a first pass". Agreement with
Opus is not correctness, but a model that disagrees with it often will also disagree with your reviewers.

Confidences are the model's own estimates. They are not calibrated until you compare them with your own judgement:
Settings shows how often you agreed with the AI at each certainty, from the excerpts you judged, and after 20
judgements suggests the lowest strictness from which you agreed at least 80% of the time.

---

## 6. The connector for the Claude app and Claude Code

The connector lets Claude check claims and hypotheses against your documents inside an ordinary chat. Claude does the
reading and grading on your Claude plan, with no API key; only the passages shown to it (about 8,000 characters a
round) leave the computer. The connector, a small program on your computer, keeps the projects, picks the passages,
checks every quote against the source and keeps the history. It uses the same projects as the app, so a check made
in the chat appears in the app's History (graded by "claude (chat)") and the other way round.

### Set it up

```bash
pip install -e '.[connector]'
enlens-mcp --install-claude-desktop      # adds the connector to the Claude desktop app's config (keeps a .bak copy)
```

Quit and reopen the Claude desktop app. `enlens-mcp --print-config` prints the block for the desktop app's config file
(to add by hand) and the exact `claude mcp add …` command for Claude Code. Both start the connector with the Python
it was installed in. Use `--home FOLDER` with either command if your projects are not in `~/enlens`.

### Use it

Write in the chat as you would to a colleague:

- "Make a new project called Morocco from ~/Downloads/morocco_sources.zip" (give a path; files attached to the chat do
  not reach the connector)
- "Use my pilot folder ~/enlens/pilot as a project called Pilot"
- "In Pilot, check this hypothesis: hydrogen leakage along the value chain undercuts its climate benefits, because
  leaked hydrogen extends the lifetime of methane." (Claude splits a compound hypothesis into parts and checks each)
- "Read more passages" or "Try a different search" when nothing was found
- "Show me my recent checks in Pilot"

- "In Pilot, where do the documents talk about electrolyser imports?" or "Which SDG targets does the IEA Africa
  outlook address?" or "What does Pilot call PEM electrolysis, and in which documents?" (0.7)

The connector's tools: `list_projects`, `create_project`, `add_sources`, `use_folder_as_project`, `list_documents`,
`list_frameworks`, `suggest_targets`, `start_check`, `submit_grades`, `more_passages`, `get_check`, `list_checks`,
and since 0.7 `search_corpus` (concordance lines, so Claude can look around before proposing a hypothesis),
`document_profile` (a document's codes with their passages) and `find_concept` (a concept's wordings and documents).
A recorded demo of a session is in `docs/connector_demo.html` (made with 0.4; the flow is the same).

If the Claude app does not show the connector, check its connector settings for an error. Running `enlens-mcp` in a
terminal shows any start-up problem (it then waits for the app; stop it with Ctrl+C).

### Claude Code as the AI behind every task (0.8; the default from 0.9)

With Claude Code, signed in with your own Claude plan, every AI button of ENLENS is answered by Claude: profile
labels, concept links, theme names, references, checks, reading an excerpt again, second opinions, the model tests
(*Compare a sample* of labels, the *Model test*), and the SDG pack's tasks (section 10, step 5). ENLENS prepares
the work in a queue and checks every answer as it checks any other; Claude Code does only the reading. ENLENS never
sees your Claude login (Claude Code uses its own) and never runs on anyone else's plan. For a shared installation
that runs unattended, use the Claude API with the team's key instead (the same queue and the same models per task:
`enlens queue run --backend anthropic`).

**Set it up once.** In ENLENS, the first screen or *Settings → AI → Claude Code*: press **Set up Claude** (0.10). It
installs Claude Code if it is missing (after showing you the command), opens a window for the one-time sign-in with
your Claude plan and waits for it (section 3, *First use*), then writes the plugin into your ENLENS folder
(`claude-plugin/`) and adds it to Claude Code by
running the same two commands you would type (`claude plugin marketplace add …`, `claude plugin install
enlens-run@enlens`); nothing else in Claude Code's settings changes. The checklist then shows three ticks. From a
terminal, `enlens claude-setup` does the same (`--print-only` only prints the two lines). ENLENS finds the `claude`
program on the PATH or where its installers put it; `ENLENS_CLAUDE=/path/to/claude` names it. When ENLENS is moved
or installed again (a new Python), it writes the plugin again on its next start and adds it again, quietly (0.10);
the Claude desktop app's connector entry is pointed at the new Python too when the old one is gone.

**Start Claude Code (0.9).** Press an AI button in ENLENS. The page says what waits, for example *Waiting for
Claude Code: 120 passages to label · about 25 minutes*, with **Start Claude Code**. ENLENS then starts Claude Code
in the background for that project (`claude -p "/enlens-run:enlens-run <project>"`, run in the ENLENS folder),
allowed only the four ENLENS queue tools and its helpers, so a passage that tries to give it instructions can do
nothing else. The page and the sidebar's queue panel say *Claude Code is working on it*, with *Stop*; it stops by
itself when nothing waits. *Stop* returns the batches it had taken to the queue at once. If a run ends with a
problem (a usage limit, for example), the page shows the end of its report. The first start also adds the plugin if
that was not done yet.

**Or type it yourself.** The same work can be started in Claude Code, opened in any folder:

```
/enlens-run Pilot              # every kind of task waiting in the project Pilot
/enlens-run Pilot label        # only the labels
/enlens-run Pilot --parallel 4 # four helpers at once: faster, but it uses your plan's limit faster (default 2)
```

`/enlens-run` hands each kind of task to a helper agent on the model ENLENS names for it (labels and links on
Haiku, theme names, references and search words on Sonnet, checks on Opus; for the SDG pack, extraction on Sonnet,
splitting the VCA and checking its claims on Opus, audits on the auditor; *AI model per task* in Settings) and
reports what is done and what is left. The helpers can use only the ENLENS queue tools: they see nothing but the
passages handed out and write nothing but answers. Every answer is quote-checked; a wrong quote is sent back and
answered again. An unsure answer (certainty under 0.6), or one rejected twice, goes once to a stronger model.

You follow the progress in ENLENS: on the page that waits, and in the **queue panel** under the jobs in the
sidebar (per kind: waiting, being answered, done, the model and helper, the estimate; *Do first*, *Hold*, *Remove*).
A check waits under Results as *Waiting for Claude Code*: its search runs in ENLENS at once, and only its search
words, parts and judging wait. It finishes when the answers arrive, even if the app was closed meanwhile.

**Stopping.** A run can stop at any moment (a usage limit, a closed laptop, Ctrl+C). A batch taken and not answered
returns to the queue after 30 minutes, and the next `/enlens-run` continues where it stopped; nothing is lost. When
answers stop arriving, ENLENS says *Paused at 340 of 7,868 labels. To go on, type /enlens-run Pilot in Claude Code.*
*Stop* on a waiting page takes its tasks that no session has taken yet out of the queue (a waiting check is removed
whole).

**Fable.** The auditor (second opinions, and checks read again by a stronger model) runs on Opus. *Let the auditor
use Fable* switches it to Fable. In Claude Code, Fable can be billed from usage credits instead of your plan; its
model picker then says *Requires usage credits*.

**What is recorded.** Claude Code gives no seed and no model digest, so its answers are not repeatable the way a
seeded local model's are. Each answer records its route (Claude Code), helper, the model set for that helper,
prompt version, whether it stepped up, and when its batch was claimed and answered; *How these results were made*
lists them per kind. The acceptance runs (`enlens acceptance queue … --again`) measure how much two readings differ.

**Model tests with Claude Code.** *Compare a sample* (profile labels) and the *Model test* (Settings) put their
tasks in the queue of a temporary copy of the project, named on the waiting page (type `/enlens-run "<that
name>"`). The copy is removed when the test ends, so nothing is stored; the labels are read by the label model, and
the model test answers each kind on its own model. *Test: repeatable answers?* says that Claude Code takes no seed.

**The connector's queue tools** (used by the plugin; not meant for a chat): `queue_status`, `next_tasks` (a batch,
claimed for 30 minutes), `submit_answers` (each answer quote-checked: stored, or its problems), `release`.

---

## 7. Data

| Table | Holds |
| --- | --- |
| hypotheses | Every hypothesis checked: text, framework and code, options, the parts found, note, batch |
| user_claims | Each claim checked (a hypothesis as written, or one of its parts) with its search terms and the model's summary; its grades are in `verifications` with `subject_kind` `user_claim` |
| documents, pages, passages | Source text, page spans, passages with `section` (body, references, reference_like, unreadable) and screen score |
| embeddings | One vector per passage and embedding model (float32, unit length) |
| tasks, results | Every model call, its payload and status; every answer with model, prompt version, validity and errors |
| verifications | One row per passage read, with its grade, quote and offsets; a person's judgement (`user_*`), the AI's scope note, and its earlier judgements when it read the excerpt again (`ai_history_json`, `reread_json`) |
| paragraphs, headings | Where each paragraph (with its page) and heading of a document starts, found when it was added |
| second_opinions | A second model's grade of each excerpt it read again (never used for an answer) |
| task_claims | 0.8: the batches of queued tasks handed out to Claude Code: who took them, when, model, helper; `tasks.queued`, `claimed_by`, `step`, `again` and `results.route`, `helper`, `step` belong with it |
| meta | Thresholds used by the pack, and the corpus version (search indexes are rebuilt when it changes) |
| vca_targets, vca_refs, doc_refs, claims, claim_targets, evidence, interactions, vca_claims, reviews | The SDG pack (section 13) |

Open it with any SQLite tool. Offsets in `evidence` and `verifications` index into `documents.text`. Removing one
document keeps past checks intact (each check stores the passages it showed); removing all documents also removes
every check.

**Moving to another computer (0.10).** *Projects → Move ENLENS to another computer → Download everything (.zip)*
makes one file with every project (each as its own project zip: database, uploads, original files) and the settings.
A saved Claude API key is left out, and so are quick looks not kept; projects used in place from another folder come
along as copies. On the new computer, install ENLENS and choose the file under *Import from another computer* on the
first screen (or *Projects → Import a project (.zip)*, which takes both kinds of zip). Each project keeps its name
(`name (2)` when the name is taken). The settings come along only when the new computer has no project yet, and on a
`--local-only` installation never the choice of a cloud AI.

---

## 8. Privacy and copyright

With a local model nothing leaves the computer. With the Claude API (app or `--backend anthropic`) the hypothesis and
the passages read are sent to Anthropic; with the connector, the passages shown to Claude are part of your chat; with
Claude Code (0.8), the passages inside the tasks it takes are sent to Anthropic on your own plan. For
paywalled literature, check with your library whether your licences allow text and data mining with an outside
service, or keep to a local model.

---
## 9. The SDG pack: impact claims and the Value Chain Assessment

The pilot's pipeline turns a set of source documents into **impact claims**: statements that an activity in a value
chain affects a UN SDG target, in a direction, in a segment of the chain, at a place and time, under a condition,
each with the exact words from the source. The claims are compared with an expert Value Chain Assessment (VCA) and
summarised into a report. It asks five questions of the literature:

1. Does the cited literature support the VCA's judgements? (Each justification is split into claims and checked.)
2. Which SDG targets does green hydrogen affect, in which direction and in which segment?
3. Where do synergies and trade-offs between targets appear?
4. When do the effects occur, and where do they land (producer or importer, which countries)?
5. Under which conditions do effects change, and which policy levers are named?

It also measures how well evidence extracted from the sources rebuilds the VCA's own labels, so you can judge
whether the method is good enough to extend the VCA to other value chains.

The pack keeps the passage selection of 0.4 exactly (its own tokenizer), so re-running `make-tasks` on a 0.4
workspace queues no new work. Vocabularies:

- Segments: `production`, `transportation`, `end_use`, plus `whole_chain` and `unclear`.
- Direction: `positive` (helps progress on the target), `negative` (hinders it), `mixed`, `no_effect`.
- Influence: `direct`, `indirect`, `unclear` (VCA definitions).
- Horizon: `short_term` (to 2030), `medium_long_term` (after 2030), `not_stated`.
- Interaction scores between targets: Nilsson et al. (2016) scale from −3 (cancelling) to +3 (indivisible).
- Targets: all 169 SDG targets, including lettered ones such as `7.b` and SDG 17 (`src/enlens_claims/data/sdg_targets.csv`).
- Status of an extracted claim: `auto` (accepted automatically), `needs_review`, `accepted`, `changed`, `rejected`.
- Task kinds: `split` (justification to VCA claims), `extract` (passage to impact claims), `verify_set` (which of up
  to six passages from the cited sources support a VCA claim), `verify` (one passage, one claim: second checks),
  and for hypotheses `decompose`, `expand` and `check`.

### Quick start with the offline baseline

The `baseline` backend is a keyword heuristic with the same output format as the models. It needs no key and no
network, so it is the fastest way to see the whole pipeline work. Its results are a floor, not findings.

```bash
enlens --ws demo init
enlens --ws demo load-vca path/to/43621_2024_374_MOESM1_ESM.xlsx
enlens --ws demo ingest path/to/sources.zip          # folders and zips are searched
enlens --ws demo match-sources
enlens --ws demo screen
enlens --ws demo make-tasks split
enlens --ws demo run split --backend baseline
enlens --ws demo make-tasks verify-vca
enlens --ws demo run verify_set --backend baseline
enlens --ws demo make-tasks extract
enlens --ws demo run extract --backend baseline
enlens --ws demo report                               # demo/report/report.html
```

---

## 10. The full workflow

### Step 1. Load the VCA

```bash
enlens --ws pilot init
enlens --ws pilot load-vca 43621_2024_374_MOESM1_ESM.xlsx
```

The loader reads sheet "(T3) SDGs & Targets - Analyses". The influence cells in that sheet are empty; the sign is the
cell colour (red negative, green positive, bold colour direct, light colour indirect). The command prints totals.
For the published workbook they must read 169 targets, 61 justified, 30 direct, 119 indirect, 86 positive,
63 negative, 47 short term and 14 medium to long term, as in the paper. If they do not, the colours were not read
correctly; see Troubleshooting.

### Step 2. Add sources

```bash
enlens --ws pilot ingest uploads/sources.zip more_reports/
enlens --ws pilot match-sources
enlens --ws pilot coverage
```

- Any file names work. Files are matched to the VCA references by DOI (from the file name, metadata or first pages)
  or by the words of the reference (title, organisation, year).
- `coverage` lists, for each justified target, how many of its cited sources are available. Targets with none are
  reported as "source missing" everywhere, never as unsupported, and are left out of the agreement scores.
- A `manifest.csv` next to the files (columns `file`, `reference`, `doi`; more columns are ignored) says exactly
  which reference each file is. Several rows may point at one file when the same work is cited in different ways;
  every row is linked. Manifest links take precedence over DOI and title matching.
- The VCA's reference lists contain a few errors (cut-off or wrong DOIs, the same work cited twice). The loader
  applies `src/enlens_claims/data/reference_fixes.csv` (actions `doi` and `same_as`) and then merges references
  whose title words overlap strongly. `load-vca` reports how many were fixed and merged. Add rows to that file when
  you find more.
- Duplicate files (same bytes) are skipped. Scanned PDFs without a text layer come out empty; run OCR first. A file
  that cannot be read is listed under `failed` and the others are added.
- Notes that travel with a corpus (`problems.txt`, `README.md`, `notes.txt`) are not ingested. When a manifest is
  present, `ingest` lists files it does not mention under `not_in_manifest`, so you can see what was added unlinked.
- `--exclude PATTERN` leaves out files by name, for example a download that turned out to be the wrong document:
  `enlens --ws pilot ingest enlens_text.zip --exclude 'A_18_*'`. Repeat it for several patterns.
- Text layers without a character map come out as `(cid:53)` codes or as shifted letters and control characters
  (`5HQHZDEOH DQG` for `Renewable and`). Such passages get section `unreadable` and are never sent to a model.
  `ingest` lists documents that are mostly unreadable, and they do not count as available sources in `coverage`.
  Get another copy of the file (the publisher's version often has a proper text layer) or run OCR.
- `coverage` and the report's Sources table flag very short documents: a web landing page or an event agenda saved
  instead of the report itself still matches the reference, but holds no evidence.

**Large PDF folders.** `tools/pdf_to_text.py` turns a folder of PDFs into small text files, one form-feed character
between pages, so page numbers survive. It copies HTML files and `manifest.csv` and writes `enlens_text.zip` next
to the folder, which `ingest` reads like the PDFs. It needs only `pypdf`:

```bash
pip install pypdf
python3 tools/pdf_to_text.py path/to/sources path/to/manifest.csv
```

**Adding sources later.** Ingest the new files into the same workspace, then run `match-sources`, `screen` and the
`make-tasks` commands again. Task ids are fixed by their content, so only new work is created: passages that now rank
among the top N for a target, and VCA claims whose best passages changed (they get a further task for the new set;
earlier answers are kept and counted together). Nothing already answered is asked again.

**Starting over with another copy of the corpus.** `enlens --ws pilot reset-corpus --yes` removes documents and
everything derived from them (passages, claims, verifications and their tasks) but keeps the VCA and its split
claims, so the split does not have to be paid for again.

### Step 3. Screen passages

```bash
enlens --ws pilot screen
```

A transparent heuristic marks passages that mention hydrogen (or its derivatives) and impact terms, and score
against the SDG target texts. Only screened passages go to extraction unless you pass `--all-passages`. This step
stands in for a fast decision model; see section 12 for replacing it. Lower `thresholds.screen_min_score` in
`config.json` (default 2.0) to let more passages through.

### Step 4. Create model tasks

```bash
enlens --ws pilot make-tasks split                    # 61 justifications to VCA claims
enlens --ws pilot make-tasks extract --per-target 6   # the 6 best passages for each of the 169 targets
```

Extracting every screened passage of a large corpus is expensive (the pilot corpus has 7,600). `--per-target N`
ranks passages against each SDG target's text and keeps the top N per target, so every target, not only the VCA's,
gets the same chance. Only passages that name hydrogen or a derivative (or whose preceding passage does, which the
task shows as context) are ranked; without that rule, general energy passages crowd out the value chain. Pass
`--any-passage` to drop it, or leave out `--per-target` to extract every screened passage.

After the split tasks have answers:

```bash
enlens --ws pilot make-tasks verify-vca --k 6    # one task per VCA claim, with its 6 best passages from cited sources
```

Each `verify_set` task shows one VCA claim and up to `--k` passages (default `thresholds.verify_top_k`), at most
`--per-doc` (default 2) from one document before the rest are filled by score, so one long report cannot crowd out
the others. The model grades only the passages that bear on the claim: `supports`, `partially_supports` (a
necessary part of the claim is stated and one inference remains: the mechanism without its effect on the target,
the converse case, or the same effect for another segment or for renewables in general) or `refutes`. Passages it
leaves out count as not enough information.

`--pairwise` makes the older design instead: one `verify` task per claim and passage, with three verdicts. In the
pilot, 72 of 75 pairwise checks found no support, often because the passage stated part of the claim; set-wise
checks with a partial grade read the same text and say more.

Other options: `--model` records a different model on the tasks; `--limit N` creates only N tasks (useful for a
trial); `--beyond-cited` searches all documents, not only those the VCA cites.

Second opinions with another model:

```bash
enlens --ws pilot make-tasks audit-vca --sample 0.1 --model claude-fable-5-1      # 10% of answered VCA checks
enlens --ws pilot make-tasks verify-claims --sample 0.1 --model claude-fable-5-1  # 10% of extracted claims
```

Audit answers to VCA checks are stored apart (`subject_kind` `vca_claim_audit`) and never change a claim's status;
`evaluate` and the report compare them with the first answers. `refresh KIND --model M` switches the main tasks to M
but leaves audits and second checks with the model they were made for.

### Step 5. Answer the tasks

Four ways, which can be mixed per task kind:

**Claude Code on your own plan** (0.8.1; the passages handed out are sent to Anthropic). `prepare` makes the tasks
as `make-tasks` does and puts them in the queue; `/enlens-run` answers them with a helper per kind:

```bash
enlens --ws pilot prepare split                       # Opus (enlens-extractor), one task per VCA target
enlens --ws pilot prepare verify-vca --k 6            # Opus (enlens-checker), one VCA claim and its passages
enlens --ws pilot prepare extract --per-target 6      # Sonnet (enlens-extractor); unsure claims go to Opus
enlens --ws pilot prepare audit-vca --sample 0.1      # the auditor (Opus, or Fable when switched on)
enlens --ws pilot prepare verify-claims --sample 0.1 --model fable   # a second check of extracted claims
# then in Claude Code:  /enlens-run pilot   (or /enlens-run pilot extract)
```

`--model haiku|sonnet|opus|fable` keeps one model for those tasks instead of the routed one. The audits keep their
model and never step up, so they stay a second model's reading. The pack's tasks enter the queue only through
`prepare`: `make-tasks` and `run` work as before. `enlens queue run --backend anthropic` answers the same queue
unattended with the same models.

**a) Claude API** (cloud: the passages are sent to Anthropic)

```bash
export ANTHROPIC_API_KEY=...
enlens --ws pilot run split --backend anthropic
enlens --ws pilot run extract --backend anthropic
enlens --ws pilot run verify_set --backend anthropic
```

The tasks record the model of `config.json` (`claude-opus-5-5` …); with the Claude API that model is used.

**b) A local model** (text stays on your machine; `--backend auto` is the default):

```bash
ollama pull qwen3:8b                                        # once
enlens backend-check --backend ollama --model qwen3:8b      # is it running, is the model there?
enlens --ws pilot run verify_set --model qwen3:8b
```

Without `--model` a local backend uses the first chat model its server offers (the Claude model names stored on
the tasks do not exist on a local server).

The context length is set on every request (`--num-ctx`, default 16,384), and the answer is forced into the task's
JSON format. `--think off` switches off the reasoning of thinking models, which is faster. Other OpenAI-compatible
servers (LM Studio, llama.cpp, Jan, vLLM) work with `--backend local --url http://localhost:1234/v1`: the answer format
is passed as a JSON schema where the server accepts it (json_object or none otherwise); set the context length on the
server, because that endpoint cannot pass it.

Local models are cheaper and private but weaker. Test them before trusting them (section 5).

**c) File queue** (any worker, including Claude in a chat or an agent):

```bash
enlens --ws pilot export-tasks extract --batch-size 25
# the worker reads tasks/extract/SYSTEM.md and WORKER_GUIDE.md, answers each line of tasks/extract/batch_*.jsonl,
# and writes results/extract/batch_*.jsonl lines: {"task_id": ..., "model": ..., "output": {...}}
enlens --ws pilot check-results pilot/results/extract/batch_0001.jsonl   # the worker checks its own file
enlens --ws pilot import-results pilot/results/extract
enlens --ws pilot requeue extract       # put exported tasks that got no answer back in the queue
```

`check-results` applies every check the import applies (schema, quotes, passage numbers) without storing anything,
and lists the problems per line, so a worker can fix its file before handing it back. The worker guide asks workers
to judge every task themselves and use code only to write and check JSON.

Running several workers at once (the pilot ran up to 15 Claude agents in parallel): give each worker its own batch
file, its own results file and its own folder for helper scripts. In the pilot, two workers that shared a scratch
folder overwrote each other's helper scripts and one wrote lines into the other's results file. Before importing,
check that every results file holds exactly the task ids of its batch.

Whatever the route, every answer is validated before it is stored:

- The JSON must match the schema; loose spellings ("end-use", "SDG 6.4") are normalised.
- Every quote must be found in the text the model was given. Matching ignores case, typographic quotes and dashes,
  ligatures and whitespace (PDF text often splits words), but nothing else: a paraphrase or an added number fails.
- A claim whose main quote is not found is dropped. A task with no usable answer is retried, with the problems
  listed in the next prompt, up to three attempts. An answer that is not accepted changes nothing stored before.
- Claims with confidence below `thresholds.accept_confidence` (default 0.8) get status `needs_review`.

Check progress at any time:

```bash
enlens --ws pilot status
```

### Step 6. Review

```bash
enlens --ws pilot review-export queue.csv --audit 0.05
```

The CSV holds claims that need review, a random 5% audit sample of auto-accepted claims, and VCA claims found
unsupported or contradicted. Fill in `decision` with `accept`, `change` or `reject`. For `change`, give any of:

- `corrected_targets`: `6.4:negative:direct; 2.4:negative:indirect`
- `corrected_segment`: one of the segment values
- `corrected_horizon`: one of the horizon values

```bash
enlens --ws pilot review-import queue.csv --reviewer "initials"
enlens --ws pilot gold-export gold.jsonl
```

Rows with an invalid correction (also an unknown direction or influence) are reported and change nothing. The file
may be saved by Excel (UTF-8 with or without byte-order mark, or Windows-1252). Reviewed items do not reappear in
later queues. When a task is answered again (`refresh`), a reviewed claim with the same text keeps the decision;
a claim whose text changed has its review marked superseded and comes back to the queue.
`gold.jsonl` is the growing gold set: use it to compare prompts, models and thresholds.

### Step 7. Evaluate and report

```bash
enlens --ws pilot evaluate             # metrics as JSON
enlens --ws pilot report               # pilot/report/report.html plus CSVs
enlens --ws pilot report --strict      # only auto-accepted and reviewed claims
```

---

## 11. Reading the report

The report has one section per question. Every number traces to `claims.csv`, which holds each claim with its quote,
source and page.

**1. Does the cited literature support the VCA's judgements?** Status per VCA claim:

| Status | Meaning |
| --- | --- |
| supported | At least one passage from a cited source states the effect (grade supports, confidence at least `support_confidence`, default 0.6). |
| partially_supported | No passage states the whole effect, but one states a necessary part of it, so one inference step remains. |
| contradicted | A passage states the opposite and none supports it, fully or partly. |
| unsupported | Sources were available and checked, but no passage states the effect. The judgement may rest on reasoning beyond the sources, or retrieval missed the passage. |
| source_missing | None of the cited sources was provided, or the ones provided are unreadable. |
| not_checked | Verification tasks have not been answered yet. |

A second table shows the same statuses at other confidence thresholds. Partial grades usually carry lower
confidence than full support, so the share of partially supported claims depends strongly on the threshold; read
the whole table rather than one row.

**Do the VCA's texts and colours agree?** Each VCA claim with a clear direction is compared with the colour of the
VCA's own cell for its segment. Claims that point the other way are listed for the authors. Many are mitigations
inside the justification of a negative cell ("local manufacturing reduces the risk"), some are real mismatches.

**Can the method rebuild the VCA labels?** Claims extracted independently are aggregated per target and segment and
compared with the VCA:

- *Target has an effect*: over all 169 targets, so the targets the VCA leaves empty are the negatives. Precision
  (share of targets the evidence marks that the VCA also marks), recall (share of VCA targets the evidence finds),
  F1 and Cohen's κ (agreement beyond chance).
- *Cell*: the same per target × segment, within the justified targets that have a source available.
- *Sign*, *direct or indirect*, *time horizon*: agreement where both mark something.

Low recall with high precision usually means the sources were incomplete or the screen was too strict. Disagreement
on sign is the most informative: read those claims in `claims.csv`.

**2. Effects.** One row per target, one column per segment: sign and the number of documents. The sign is positive or
negative when one side has at least twice the documents of the other, otherwise mixed.

**3. Synergies and trade-offs.** *Stated* interactions are those a passage states, scored on the Nilsson scale.
*Inferred* pairs come from one document linking the same activity, segment and place to two targets: synergy (both
helped), trade-off (one helped, one hindered), shared pressure (both hindered). Inferred pairs are candidates for
expert scoring, not findings. The report lists only pairs found in two or more documents, because one long
document (in the pilot, a paper that maps hydrogen to many SDGs) can link dozens of targets; all pairs are in
`interactions.csv`.

**4–6. Timing, geography, conditions.** Claims by horizon and direction; countries named and whether effects land
with producers or importers; the conditions and policy levers that change an effect.

**7. Gaps.** Target and segment cells the VCA leaves empty but two or more documents mark, and targets with no sources.

**Sources.** Every document with its pages, passages, number of claims and the VCA targets that cite it, with checks
for unreadable or very short files.

**Method notes.** How the evidence was produced, and the agreement between the first answers and the second-model
audits.

---

## 12. Models and configuration

`config.json` in the workspace:

```json
{
  "models": {"screen": "heuristic", "split": "claude-fable-5-1", "extract": "claude-opus-5-5", "verify": "claude-opus-5-5"},
  "thresholds": {"screen_min_score": 2.0, "accept_confidence": 0.8, "support_confidence": 0.6, "verify_top_k": 6},
  "passages": {"max_chars": 1100, "min_chars": 200}
}
```

Suggested split, following Anthropic's guidance that Opus 5.5 is the default and Fable 5.1 is for work where Opus
falls short: Opus 5.5 for the high-volume extraction and verification; Fable 5.1 for the 61 justification splits,
for resolving conflicts, and for a second check on a sample (`make-tasks verify-claims --sample 0.1 --model
claude-fable-5-1`), which measures whether the more expensive model changes outcomes. A cheaper model (Haiku 5.5)
or a dedicated classifier can replace the screen once it is benchmarked on reviewed passages.

Every stored result records the model and the prompt version (`extract-v1`, `split-v2`, `verify-v1`,
`verify-set-v1`; for hypotheses `decompose-v1`, `expand-v2`, `check-v2`). When you change
a prompt in `prompts.py`, bump its version so old and new results stay distinguishable, then queue the affected tasks
again with `enlens refresh KIND` (add `--model` to switch model at the same time). Earlier answers stay in the
`results` table.

## 13. The pack's tables

| Table | Holds |
| --- | --- |
| documents, pages, passages | Source text, page spans, passages with `section` (body, references, reference_like, unreadable) and screen score |
| vca_targets, vca_refs, doc_refs | Gold labels, cited references, and which document matched which reference (method manifest, doi, title, or manual: rows you add by hand with method `manual` survive `match-sources`) |
| tasks, results | Every task, its payload and status; every answer with model, prompt version, validity and errors |
| claims, claim_targets, evidence | Extracted claims, their targets with direction and influence, and quotes with offsets and page |
| interactions | Stated interactions (with quote) and inferred candidate pairs |
| vca_claims, verifications | Split justifications; one row per checked passage with its grade and quote. `subject_kind` is `vca_claim`, `vca_claim_audit` (second opinion) or `claim` (second check of an extracted claim) |
| reviews | Reviewer decisions and corrections |

Open it with any SQLite tool. Offsets in `evidence` and `verifications` index into `documents.text`.

---

## 14. Using the pack for other value chains or policy documents

- **Another value chain**: you need the screen terms (`H2_RE` in `retrieve.py`), the segment definitions (`prompts.py`)
  and, for evaluation, an expert table in the same layout, or reviewed claims as gold.
- **Policy documents**: ingest them like any source. Policy levers and conditions are extracted from them as from papers.
  For a policy layer, run `make-tasks extract --docs <ids>` on those documents only and read section 6 of the report.
- **The Netherlands angle**: no VCA justification mentions the Netherlands; Dutch and EU policy documents and national
  studies have to be added as sources first.

For checking hypotheses about any subject, no pack is needed: sections 3 and 4.

---

## 15. Limits

- Grades and claims are model output until reviewed. The quote check proves the quoted words exist; it does not prove the fields
  follow from them.
- The corpus is what you provide. Paywalled sources you cannot or will not process leave targets as "source missing".
- Text comes from the PDF text layer. Tables and figures are read as text, which is often garbled; scanned pages need OCR.
- "Nothing found" is about the passages read, not the documents: read more passages or search with other words.
- The screen is a heuristic. Measure its recall on reviewed passages before relying on it for a new topic.
- Inferred interactions are co-occurrence within a document, not causal statements.
- Verification reads only the top `--k` passages per claim (a hypothesis check: `k` per claim per round; semantic search
  narrows the gap). In the pilot, a manual search of the full cited documents
  for 10 claims with no graded passage found partial support for 2 and a weak contradiction for 1; the other 7 had
  nothing anywhere in their sources. Retrieval misses some evidence, mostly where the source uses other words
  ("repurposing" for "upgrading").
- Model confidences in the pilot were low (extraction mean 0.46), so with the default `accept_confidence` of 0.8
  every claim went to review. Calibrate the threshold against reviewer decisions before using the auto status.

## 16. Troubleshooting

| Problem | Fix |
| --- | --- |
| `load-vca` totals differ from the paper | The workbook layout or colours changed. Check `_fill_sign` in `vca.py`; theme colour 9 is read as green. |
| A document did not match its reference | Put the DOI in the file name (`10.1016_j.ijhydene.2022.11.024.pdf`), use a `manifest.csv`, or add a `doc_refs` row by SQL with method `manual`. |
| Many quotes fail | Look at `results.errors_json`. Usually the model tidied PDF text; the retry prompt tells it to copy exactly. |
| Tasks stuck as `exported` | `enlens requeue KIND`. |
| "No Claude API key" | Export `ANTHROPIC_API_KEY` or enter it in Settings, or use a local model or the file queue. |
| "No local model server is running" | Start Ollama (or `ollama serve`) or LM Studio's server; `enlens detect` lists what is found. Or choose `--backend baseline` / the offline demo to try things out. |
| "Cloud models are switched off" / "Allow cloud models first" | The Claude API sends the passages read to Anthropic, so the app asks you to allow it first (Settings → Model service). |
| "The local server … has no model" | Load the model in LM Studio, start llama.cpp with it, or name another with `--model` / in Settings. |
| A semantic search error about vector sizes | The embedding model changed since the index was built: Sources → *Build semantic index*. |
| "Remove all documents" is refused | The project also holds results of the SDG pack (extracted claims, VCA verifications). Remove documents one by one, or run `enlens --ws FOLDER reset-corpus --yes` if you mean it. |
| Empty document, or "Scanned: no text" | No text layer (scanned). Install Tesseract and the `ocr` extra (section 1) and add the file again, or run OCR yourself (`ocrmypdf in.pdf out.pdf`). |
| Double-clicking the ENLENS icon does nothing | Look at `logs/enlens.log` in the data folder. Run the install line again (one-line install), or `enlens-gui --make-launcher` again after moving or reinstalling Python (git copy). On macOS, if the icon was copied from another computer, right-click it and choose *Open* once. |
| The install line stops with "does not match the release's checksum" | The download was cut off or changed on the way; nothing was installed. Run the line again later. |
| The install line on Windows says uv could not install ENLENS | ENLENS is probably running: choose *Quit ENLENS* in it and run the line again. |
| *Set up Claude* cannot install Claude Code | No network, or the installer was blocked. Install it with Anthropic's set-up page (linked under *Technical details*), then press *Set up Claude* again. |
| *Set up Claude* keeps waiting for the sign-in | Finish signing in in the window it opened (and in the browser page that window opened), then press *I have signed in*. No window? Open Terminal or PowerShell, type `claude`, and sign in. |
| "The original file is no longer at …" | The file was moved or renamed after it was added; the app still has its text. Put it back, or add it again. |
| A document is listed under `mostly_unreadable` | The PDF's fonts have no character map. Get another copy (often the publisher's) or OCR it, `reset-corpus` or ingest the new copy, and run `match-sources` again. |
| A source is flagged "very short" | It is probably a landing page or an agenda, not the cited work. Replace it, or leave it out with `--exclude`. |
| The app says it cannot reach Ollama | Start the Ollama app (or `ollama serve`) and check the address in Settings (default `http://localhost:11434`). |
| "Ollama has no model ..." | Download it: `ollama pull <model>`, then pick it again in Settings. |
| Test connection warns about Ollama's cloud | The model runs on Ollama's servers, which do not support the JSON format the app needs, and the text leaves your computer. Pick a model downloaded with `ollama pull`. |
| "This task needs about N tokens of context" | Set the context length to automatic in Settings → Technical (the default), or raise it (`--num-ctx`). 16,384 covers every task of the app. |
| A check with a local model takes very long | The progress panel shows where the time goes. Long "loading the model and reading the prompt": the model is too large for the memory (check Activity Monitor) or the computer is swapping. Long "reasoning": set *Reasoning* to off. |
| "… sent nothing for 600 seconds" | The model did not start or stopped answering: usually too little memory. Close other apps or choose a smaller model. |
| "… used its whole allowance … on reasoning" | The model kept reasoning without answering. Give reasoning a budget (Settings → AI, the default 1,500 tokens), choose *Only when judging excerpts*, or set it off. |
| A check with reasoning takes half an hour | Set *Reasoning* to *Only when judging excerpts* with a budget (1,500 tokens is the default; lower it for a slow computer). |
| "… got stuck writing blank space" | A known failure of some models with fixed-format answers. Try again, set *Reasoning* to off, or choose another model. |
| "The Claude API rejected the key" | Copy the key again from console.anthropic.com; check it has credit. |
| Two workers' answers ended up in one results file | Give each worker its own scratch folder. Move the stray lines to the right file; `import-results` accepts any order. |
