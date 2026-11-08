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

**Or download a file and double-click it (0.14.5).** Every release also has the install as a file, for whoever would
rather not open Terminal or PowerShell. It does what the line does (the four steps above) in a window of its own; the
options above need the line.

| System | Download | The first time |
| --- | --- | --- |
| Windows | [Install-ENLENS-Windows.cmd](https://github.com/dvaud/claim_checker_demo/releases/latest/download/Install-ENLENS-Windows.cmd) | Double-click it. The browser may warn about the file: keep it. Windows may say it protected your PC: click *More info*, then *Run anyway*. The window waits for a key at the end, so you can read what happened. |
| macOS | [Install-ENLENS-macOS.zip](https://github.com/dvaud/claim_checker_demo/releases/latest/download/Install-ENLENS-macOS.zip) | Open the zip (Safari opens it for you) and double-click *Install ENLENS.command*. macOS says it could not verify the file: click *Done*, open *System Settings → Privacy & Security*, scroll to *Security*, click *Open Anyway* next to *Install ENLENS.command* and confirm with your password or Touch ID. Terminal opens and installs ENLENS. |

Windows and macOS trust a downloaded program at once only when a registered developer has signed it, and these files
are not signed; hence the questions. They are the install scripts of the line: the Windows file is a few lines for the
command prompt followed by `install.ps1`, the Mac file is `install.sh`, and the release's `SHA256SUMS` lists their
checksums. On a Mac the line is quicker, since nothing asks about it. On Linux, use the line.

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

**Installing it for someone else.** Run the install line on their account, so that the icon and the data folder are
theirs (*Quit ENLENS* in the app stops it). `ENLENS_LOCAL_ONLY=1` before the line removes every option that sends text
off the computer. Scanned PDFs also need Tesseract (above); the app says how to get it on that system when it meets a
scanned page. Section 3, *For whoever installs the app*, has the rest.

**Updating.** `enlens update` updates ENLENS the way it was installed (0.10). Installed with the one-line install,
it asks GitHub for the latest release, downloads its package, checks it against the release's checksums, installs it
over this one with uv and brings the Claude Code plugin up to date (0.14.3: also in Claude Code itself, whose own copy of the
plugin is updated too, so the new instructions are used from the next run); on Windows, where a running program cannot
replace itself, it says to quit ENLENS and run the install line again, or double-click a newly downloaded
`Install-ENLENS-Windows.cmd` (0.14.5); either does the same. The version you have
is at the top of every *Settings* tab; *Settings → Technical* says how this copy was installed. Installed from the git copy of ENLENS (`git clone …`, then `pip install -e .` in a
venv) every new version is also `enlens update` (0.8.2): it fetches the version from GitHub into the same folder, reinstalls into the
same Python only when the requirements changed (with the extras already installed), refreshes the Claude Code
plugin if one was set up, and says to restart the app if it is running. If installing the requirements fails (offline),
the next `enlens update` installs them (0.14.3; before, it said *up to date* and left the copy without them). A look
for a new version never waits for a password and gives up after 90 seconds. It changes nothing if files of the copy
were edited by hand, and never touches the data folder. `enlens update --check` only looks.

**Update ENLENS in the app (0.13.1).** *Update ENLENS* at the bottom of the sidebar does the same as `enlens update`
without a terminal: it looks for a new version (the latest release, or new commits for a git copy), says which one is
ready, and with *Update and restart* installs it and restarts ENLENS on the same address. The open page shows
*Starting ENLENS …* and opens the new version by itself; started from the icon, ENLENS is restarted the same way,
without a new browser tab. Anything still running (a check, documents being added) stops first, as with *Quit
ENLENS*, and the dialog says so. If the update fails, the reason is shown and nothing restarts. With the one-line
install on Windows it says to quit ENLENS and run the install line or the Windows file again (a running program cannot
replace itself there).

**Only when there is an update (0.13.6).** The button is not in the sidebar all the time any more. ENLENS looks for a
new version when the page opens, every two minutes after, and when you come back to a tab that was in the
background. When it finds one, a pop-up in the corner says which version (*ENLENS 0.13.7 is available*), with *Update
and restart* and *Later*, and the button appears at the bottom of the sidebar as *Update to 0.13.7*. *Later* puts the
pop-up away for that version; the button stays until you update. A look that fails (offline, files of a git copy
edited by hand) stays quiet. To look yourself, or to read why a look failed, use **Check for updates** in *Settings
→ Technical → Updates* (the version at the top right of every Settings tab opens it). For the one-line install,
ENLENS reads the newest version from GitHub's release page, which GitHub's limit of 60 questions an hour does not
count, so several computers in one office can look every two minutes.

**An icon instead of the terminal.** The one-line install makes it. From a git copy, run once, as the person who will
use the app:

```bash
enlens-gui --make-launcher                     # add --home FOLDER and/or --local-only if the app is used that way
```

It puts an **ENLENS** icon on the Desktop (macOS: also an app in the user's Applications folder; Windows: also in the
Start menu; Linux: also in the applications menu). Double-clicking it starts ENLENS in the background, with no
terminal window, and opens it in the browser; double-clicking it again while it runs just opens it again. After an
update (`enlens update`, `git pull`, the install line again), the copy still running is the old version: the icon
then quits it and starts the new one (0.10.2), unless a check or documents being added still run in it, in which
case it opens it and every page says *ENLENS X is installed, but Y is still running*, with a *Restart now* button
(0.13.1; before, *Quit ENLENS*);
the version label in Settings says the same. The icon's picture ships with ENLENS (0.10.2; before, it needed the
Python package Pillow, and without it the icon was blank); an icon made without its picture gets it the next time
ENLENS starts. If the
model service is Ollama on this computer and it is not running, the Ollama app is started too. The icon calls the
Python ENLENS was installed in, so another `enlens-gui` earlier on the PATH (for example an old one in Anaconda)
cannot get in the way. **Quit ENLENS** at the bottom of the sidebar stops it (it asks first when a check is still
running). What the app would print goes to `logs/enlens.log` in the data folder. On Linux desktops that ask for it,
right-click the Desktop icon and choose *Allow launching* once.

Check the install with the tests (about 15 seconds, no network):

```bash
pytest
```

A local model server: install [Ollama](https://ollama.com) and open it; the app then downloads a chat model with one
button (*Download qwen3:8b*, about 5 GB, 0.13.7), and with it, if you like, an embedding model for search by meaning
(nomic-embed-text). In a terminal it is `ollama pull qwen3:8b` and `ollama pull nomic-embed-text` (English) or
`ollama pull bge-m3` (many languages, so an English hypothesis also finds Dutch or French passages). Or start the
server of [LM Studio](https://lmstudio.ai) (Developer → Start server) with a model loaded. Section 5 helps choose.

The commands are `enlens-gui` (the app), `enlens` (or `python -m enlens_claims`; every command takes `--ws FOLDER`,
default `./workspace`) and `enlens-mcp` (the connector).

---

## 2. Concepts

**What ENLENS is for.** ENLENS reads your sources (reports, papers, policy documents, interview notes) and helps you
find your way through them before you claim anything; when you have a statement to test, it checks it against them.
Most of the exploring needs no AI at all. What the AI adds is quoted, checked against the text, and yours to
overrule: you review its judgements as you would a co-coder's, and your judgements count and are kept next to the
AI's in the Excel download. The AI is Claude, through Claude Code on your own Claude plan, and each kind of task goes
to the model that suits it (section 12). ENLENS grew out of the Cross-Doc SDG Explorer (section 3, *Exploring the
documents*, says where its parts went) and the ENLENS green hydrogen pilot, a Value Chain Assessment checked against
its cited literature, whose pipeline is still included as the SDG pack (sections 9 to 14).

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
| Second opinion | Model for second opinions | Another model that reads the same excerpts on its own, to show where it differs. Its judgements never change an answer. |
| Stronger model | Model routing (*Steps up to*) | The model a check steps up to: it reads the excerpts again and its judgements replace the first ones; the answer shows what it was at first. |
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
| Not finished yet | `not_checked` | No excerpt has been judged yet. *Waiting for your judgement* when the excerpts read all come from documents no AI may read: judge them yourself (0.14.3; before, this said *No evidence found*). |
| The check did not work | `failed` | The AI's answers did not pass the checks three times. |

Excerpts that wait for your own judgement (documents marked *No AI*) count towards no answer until you judge them;
nobody has read them, so they are not "not about the hypothesis" (0.14.3).

A split hypothesis combines its parts, which must all hold: a part contradicted → contradicted (even when other
parts are supported); otherwise a part with mixed evidence → mixed evidence; every part supported → supported; some
parts (partly) supported → partly supported; only uncertain evidence → only uncertain evidence; otherwise nothing
found. The app says which part decides ("Part 2 has mixed evidence, so the whole hypothesis has mixed evidence").
A part whose check failed, or that waits for your judgement, gives no evidence either way, but the whole hypothesis
is then at most partly supported: it holds only if every part does, and that part is not known yet (a failed part
makes the result say it is incomplete).

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
that it never uses the AI (0.9). The marks are grey (0.13.3): green, amber, red and purple are kept for the
judgements and answers.

**One look on every page (0.13.3).** Every page follows the rules of the result page: a title and one short line
under it; a few type sizes, and bold only for headings and the page's main button; cards with a thin edge and no
shadow; a longer explanation behind a small **(?)** that opens on hover or click (what a passage is, what a second
opinion does, the auditor, how the AI labels passages); and downloads as one quiet line of links (*Download
Excel (.xlsx) · CSV*) instead of buttons. The *Overview* cards say what each feature does; hover a card for what it
is for.

**The sidebar (0.9).** *Overview* (the start page of a project), *Documents*, *Bibliography* (0.13), then **Explore the documents**
(Search, Profile, Concepts, Themes) and **Check hypotheses** (Check a hypothesis, Check several, Results). At the
bottom, under the line that says where text goes, *Settings*, *Update to …* (0.13.1; since 0.13.6 only when
there is an update) and *Quit ENLENS* sit together (0.10.1). The small icon at the end of the *Settings* row is the
theme (since 0.14.2; before, a row of its own): a screen means it follows your computer, a sun light, a moon dark;
click it for the next one, and hover it to see which is in use. Every
*Settings* tab shows the version of ENLENS at the top right, and clicking it opens *Technical → Updates* (0.13.6:
*Check for updates*, then how this copy was installed under *Where your data is*). The *Overview* shows every feature with one line on what it does, whether it uses the AI and what is
already made in the project (a profile, a glossary, a set of themes, results), and the AI in use with what is left
to set up. *Quick look at one document* is there too.

### First use

The welcome screen has three steps (0.9). **The AI**: ENLENS uses Claude Code, signed in with your Claude plan. The
step shows a checklist (Claude Code on this computer, signed in, the ENLENS plugin added) and one button, **Set up
Claude** (0.10), that does every step still open, in order:

1. Claude Code is not on the computer: ENLENS shows the command of Anthropic's installer (`curl -fsSL
   https://claude.ai/install.sh | bash`, or `irm https://claude.ai/install.ps1 | iex` on Windows) and runs it when you
   choose *Install Claude Code*. It needs no administrator rights and takes a minute or two. *Anthropic's set-up
   page* is linked for doing it yourself. Where the program is kept does not decide what it can read: what Claude
   Code may open depends on the folder it starts in and on its tools and permissions, and ENLENS starts it only in an
   empty folder of its own, with its tools for reading files, running commands and browsing switched off (see
   *How it is enforced* in section 8).
2. Not signed in: ENLENS opens a Terminal (macOS) or PowerShell (Windows) window already running Claude Code, in an
   empty folder of ENLENS (`claude-runs/sign-in` in the data folder) and with the same tools switched off, so it
   cannot open your files. Sign in there with your Claude plan (it opens a page in your browser) and close the
   window; ENLENS checks every few seconds and continues by itself (*I have signed in* checks at once). ENLENS never
   sees your login. If no window can be opened, the page shows the line to type, which goes to that folder first.
3. The plugin is not added: ENLENS adds it (as in 0.9).

*Set it up yourself instead* keeps the lines to type. *No Claude plan? Other options* offers a model on this computer
or no AI for now. **A model on this computer needs no terminal (0.13.7):** with no model server running, the step says
how to get Ollama (free, from ollama.com) and notices by itself when it starts; with Ollama running but no model yet,
*Download qwen3:8b* (about 5 GB) downloads one, with *Also nomic-embed-text* for search by meaning, a progress bar
and *Stop* (Ollama keeps what it has and goes on from there). Ollama fetches the model from ollama.com; none of your
documents are sent. The downloaded model becomes the AI and is tested at once. When whoever installed the app chose a
local model that answers, this step is skipped. Then name a **project**
(one per set of documents); used ENLENS on another computer before? *Import from another computer* brings every
project and the settings in one go (section 7). Then **add documents**: choose
files (PDF, Word .docx, HTML, text, Markdown, zip) or a folder. A Word file keeps its paragraphs, headings and the pages
Word marked (0.8); older .doc files are not read: save them as .docx or PDF. The list shows the
title read from each file and warns about unreadable text and very short files (often a landing page instead of the
report). A file that cannot be read is listed with the reason and the others are added (0.14.3: also a
password-protected PDF or zip, a damaged zip or Word file; before, one of these stopped the whole add, and a
password-protected PDF was called a file without text). Text and web page files that are not UTF-8, such as a
Hungarian text saved by Notepad (Windows-1250) or an old Latin-1 page, are read as they were written (0.14.3; before,
their accented letters were lost). *Stop* also stops the text recognition of a long scanned PDF. *Open an existing
ENLENS project folder (advanced)* links a project made with the command line, without copying it.

The sidebar always says where text goes: *Claude, on your plan · Only the passages of AI tasks leave this computer*
(the default from 0.9), *Private · The AI runs on this computer* with a local model, or that excerpts are sent to the
Claude API if a shared installation allowed it (section 6). Hover that line, or reach it with the Tab key, for a
short card (0.13.4): on Claude Code it names the account Claude Code is signed in to (*Signed in to Claude Code as
you@university.nl*, *Team plan · University of Amsterdam*; the organisation only on a Team or Enterprise plan),
then where the text goes and where to change it. Escape closes it. *Settings → AI* names the account as well, under
*Signed in with your Claude plan*, and so does `enlens claude-setup`. ENLENS reads it from Claude Code (`claude auth
status`); the login itself stays with Claude Code.

### Checking a hypothesis

Write one sentence that could be true or false and press *Check* (Ctrl+Enter). When it contains "and", "but" or a
semicolon, the app offers to **check each part separately**. *What happens when you check* explains the four
steps (search, read, verify, answer). *More options*: let the AI think of other words your documents might use,
tag the hypothesis with a code, and limit the check to some documents.

**What a check does.**

1. *(optional)* The AI splits the hypothesis into the claims that must all hold (*Check each part separately*).
2. *(optional)* It writes other words for each claim: synonyms, technical words, the opposite phrasing.
3. The best excerpts are picked by their words (BM25), combined with search by meaning when the project has it, at
   most a few per document so that one long report cannot fill every place.
4. The AI judges each excerpt that bears on the claim (supports, partly supports, contradicts), with a quote and a
   certainty. Every quote is checked character by character against the excerpt, as whole words (0.14.3: "legal"
   is not found in "illegal", "now here" not in "nowhere"), and a judgement's quote has at least three words (or 15
   characters). An answer that fails is sent back with its problems listed; so is an answer a local model could not
   finish (cut off, stuck): the check goes on with its other parts (0.14.3).
5. The answer counts the judgements the AI is sure enough about (the *strictness*, 60% by default) and yours (section
   2, *Answers*). A split hypothesis combines its parts, and the app says which part decides.

**Look before checking** shows first how the hypothesis will be checked: the parts the AI would split it into (with
*Check each part separately*) and the extra words it would search for. Change a part, remove one or add one; remove
search words that do not fit and add words your documents use; then *Check*. The result records that you set them.

While it runs, the panel shows each step as it finishes: the parts, the other words searched for, how many excerpts
from how many documents, the AI reading them; *Technical details* shows what the model is doing second by second.
Remarks about the round (excerpts of restricted documents read on this computer, or waiting for you) appear under
the steps. *Stop* ends the check and leaves nothing behind; with a model on this computer it also stops the model
while it is still reading the prompt (0.11.1). You can use the rest of the app meanwhile.

### Reading and reviewing a result

The page reads from top to bottom in four parts (0.12): the answer, the evidence, the other AI models, then notes and
downloads. *Technical details* and *Delete this result* close it. It keeps to a few type sizes; green, amber and red
are the judgements (supports, partly supports, contradicts) and purple is mixed evidence.

**The answer** is one card:

- the answer, and beside it who judged it: *judged by the AI*, *partly reviewed by you* or *reviewed by you* (hover
  it for the AI model);
- **who says what**: one row per document, with a coloured dot per side and where, e.g. *supports it: paragraph 9 ·
  contradicts it: paragraph 5*. A hypothesis checked in parts lists its parts instead, each with its answer and its
  documents for and against, under one line on which part decides the answer (*Part 1 decides the answer*; hover it:
  the hypothesis holds only if every part does). A document with excerpts on both sides counts once (*3 documents
  for, one of them also against*). Click a part to go to its evidence;
- at most one caution, when the answer is fragile: *It rests on a single document and on two excerpts you have not
  reviewed* (or one of the two; for a hypothesis checked in parts, only the parts that decide the answer count);
- documents added to the project since the check, when there are any, with *Read them* (a further search for this
  result; the check is not run again, so your reviews are kept);
- **Next to review**: it goes to the excerpts you have not reviewed, the judgements that count in the answer first
  (where a second opinion differs, or the AI flagged another group, before the others), then the rest, then those you
  only commented on. Past the evidence it goes on to the excerpts the AI found not about the hypothesis.

When the AI was too unsure to count any excerpt, the card says so in one sentence, and *Next to review* takes you to
them: your own judgement always counts.

**The evidence** has **Cards** and a compact **Table** (one row per excerpt, with your decisions; click a row to open
its card) beside its title, and two lines under it: how many excerpts count at your strictness (the (?) explains
strictness and offers *Try another strictness on this page*), and *Every quote is checked against its document; your
judgement overrides the AI's.* A hypothesis checked in parts shows each part under its own heading (*Part 1: …*) with
its own documents above its excerpts.

Each excerpt card shows, in this order: its judgement with at most two quiet facts (*Certainty: medium*; *Not
counted* and *Certainty: low* when it is below your strictness; *Second opinion: partly supports*, with its colour
dot; *You agreed with the AI*; *Your judgement (the AI said …)*); the document and where the quote is (*paragraph 6
of 8*); and the quote, highlighted in its judgement's colour, with one sentence before and after it (on a phone, the
sentence before it). A short heading that opens a paragraph of the document (*Recommendations.*) is shown as a small
heading above it (0.13.2). An excerpt read for another part too says *also in part 1*; hover it for your judgement
there. Cards that do not count come after those that do; cards you have judged sit back (no fill, a dashed edge). One
row of actions, the same on every card:

- **Agree** makes the AI's judgement yours (it then counts, whatever the AI's certainty); a note at the bottom says
  so, and whether the answer changed, with *Undo*. The card then says *You agreed with the AI*, and the button
  becomes **Take back**.
- **Not about this** dismisses the excerpt in one click (0.12): your judgement *Not about this* moves it to the
  excerpts that are not about the hypothesis, under the cards. *Undo* is offered.
- **Judge differently…** (*Edit judgement…* once you have judged; *Judge this excerpt…* when no AI may read it): the
  other judgements, each with its colour dot, under a line that says what your judgement is now (each saves at once,
  with *Undo*), a comment (saved on Enter or when you leave the field), and the sentence you mean when the AI
  highlighted the wrong one (select it in the excerpt, then *Use it*; or pick it from a list). Your judgement
  replaces the AI's in the answer and in the downloads, always counts whatever the strictness, and the card shows
  what the AI said. A comment without a judgement stays a comment: it is not a review.
- **In context** shows the whole excerpt the AI read, with *Open the whole document at this place* (by paragraph or
  page, the quote highlighted; *Back to the result* returns to the excerpt), *the original file* (a PDF at the page,
  a text file with the quote highlighted, a web page scrolled to the quote in browsers that support it) and *a
  highlighted copy* of the document (a PDF, or a web page for a text document), with this hypothesis's judgements
  highlighted.
- **Details**: *Ask the AI to read this again* (one excerpt, alone, with your comment as a hint; the card then says
  what it was and what it is now, and your own judgement still counts), the AI's certainty as a percentage, how the
  excerpt was found, and the technical facts (span, id, earlier judgements).

After a save, the card keeps its place on the screen and says where it moved in the list. *About another group* under
a quote means the AI thinks the excerpt is about another group, place or period than your hypothesis (fully remote
workers for a hypothesis about hybrid work): it then counts at most as partly supporting. Excerpts the AI found not
about the hypothesis are folded under the cards, so you can check those too.

Under the cards, **Read more excerpts** reads the next excerpts that match the same words; **Search with other
words** reads excerpts containing words you type (documents often say "telework" where the hypothesis says "remote
work"). New excerpts are marked *new*, a *Just now* line in the answer says what was found, and when everything that
matches has been read, the line above the buttons says so.

**Ask another AI model** says what has happened (what a second opinion found; that no stronger model is set, with
*Set one in Settings*), then has two buttons side by side (0.11.2); each button's tooltip says what it does, and the
(?) explains the difference:

- **Ask a stronger model** (*it replaces the AI's judgements; the answer can change*): the model checks step up to
  (on Claude the auditor, Opus or Fable) reads every search of the result again, once. Its judgements take the place
  of the first AI's. The answer then shows a small mark beside it, e.g. **Supported** *at first: partly supported*
  (hover or click it for which models and how many judgements changed), and each changed excerpt shows both readings.
  The same happens on its own when an answer was unsure or rejected twice. Your own judgements stay and count either
  way. When the AI chosen in Settings has no stronger model, the card says so, with *Set one* (Settings).
- **Get a second opinion** (*shown only for comparison: it never changes the answer*): another model (on Claude the
  auditor; with a local model, a second local model chosen there or in Settings) reads the same excerpts on its own.
  Each card then says *Second opinion: …* beside the AI's judgement, *Next to review* goes to the excerpts where it
  differs first, and when it points to another sentence, *Highlight the quote of: the AI / the second opinion*
  switches which quote is highlighted. With local models only one is kept in memory at a time, so this takes a while.

Add **notes** (saved as you type). **Download**, one link per file: *Excel (.xlsx)*: a *Summary* sheet (one row per
hypothesis: answer, answer per part, documents per side, excerpts counted and too uncertain, your reviews and
changes, notes, strictness, and for a methods section every AI model whose answers the check used, with what each
did: search words, judging, judging again as the stronger model, the excerpts of documents marked *Only a local AI*)
and an *Excerpts* sheet (every excerpt read: judgement, judged by you, a colleague, the AI or nobody yet, the AI's own
judgement and certainty, or why no AI judged it (*Not read by an AI: kept for your own judgement*, *Not read: the
AI's answer could not be used*), counted or not, quote and who chose it, document, where, your comment, the AI's
note about another group, its earlier judgement when it read an excerpt
again, the second model's judgement when one was asked, the full excerpt); *Highlighted documents (.zip)*; *Whole
project (.zip)*; and *CSV · JSON (for programmers)*. *Technical details* has the strictness slider (this page only),
the models and settings of the check, what each search looked for and the AI's note on what it read.

A check still **waiting for Claude Code** shows only the waiting card (with *Start Claude Code*), any excerpts
already read, and your notes; the rest appears when the answer is in.

### Results and checking several

**Results** lists every hypothesis with its answer, the excerpts that count (and how many were too uncertain), tags
such as *part of a set*, *checked in 2 parts*, *N to review*, *N changed by you*, *has notes*, *N documents added
since*, *second opinion differs on N*, and the date; an answer a stronger model changed carries the small mark *was
partly supported* (or whatever it was at first). Search, filter by answer, open one, or download them all
(*Download all: Excel (.xlsx)*, with a *Map* sheet, or *CSV (for programmers)*, under *Show as a map*). *Read the new
documents for all N* brings every result with documents added since up to date in one go; *Get a second opinion for
all results* does the same for second opinions (for comparison only: the answers do not change; its (?) says more).

**Show as a map** shows all results (or one set) as a grid: one row per hypothesis, one column per document, and in
each cell + supports, (+) partly supports, − contradicts or ± both, with the number of excerpts that count. It flags
answers that rest on one document, and documents that *decide* answers (leaving them out would change those answers),
which are the ones to read most carefully.

**Projects** (the project menu → *Manage projects*): *Download as a zip* puts the whole project in one file (the
database, the documents and their original files, the codebooks) for a co-author or another computer; the file of a
document you removed stays on this computer (0.14.3). *Import a project (.zip)* opens such a file as a new project; a
damaged zip, or one whose database cannot be read, is refused with a plain message and leaves nothing behind.
*Download the whole project (.zip)* is also on the Results page.

**Check several** checks many hypotheses one after the other: paste them one per line, or load a CSV with a column
`hypothesis` (or `claim`, `text`, `statement`) and optional `framework` and `code` columns. *Show the list* previews
what will be checked; *Check all N* runs them. A hypothesis that cannot be checked is listed and the next one is
checked; a problem with the AI stops the set and keeps what was done. The end screen lists each answer.

### Exploring the documents (0.7)

Before or alongside checking hypotheses, the pages under **Explore the documents** show what the documents say and
where. They replace the Cross-Doc SDG Explorer. Search, key terms, the keyword profile, the glossary and themes by
words need no AI model; the AI only adds readings on top, and every one of them quotes the text and is checked
against it.

| Page | What it gives | AI? |
| --- | --- | --- |
| Search | Every place words occur, with the words around them; phrases, near, other forms, words nearby; Excel/CSV | no |
| Profile | The codes each document addresses, how much and where, with the words or quote and reason behind each | keywords first; the AI confirms |
| Concepts | A glossary of terms grouped into concepts (abbreviations, wordings, your links); where each appears | optional |
| Themes | Themes across the documents, by document and by code; rename, merge, move, remove | optional (names) |
| A document | Codes, key terms, references ("it", "they"), search, a highlighted copy; 0.15: how it was read, the page beside the text, Restore and Leave out | references only |

**Search.** Every place words occur, one line per place with the words before and after (a concordance), with the
count per document first. *Find* any of the words, all of them in one passage, a phrase, or words near each other
(within N words); in a phrase search, words typed next to a "quoted phrase" must also be in the passage. Without *exact words only*, a word also finds its other endings ("price" finds "prices"); forms the
search does not include are listed under the count (*Other forms in the documents: commuters*), to add with one
click. Click a word in a line to add it to the search, Shift-click to make a phrase. Sort by document, by the words
before or by the words after. *Words that often appear nearby* lists the words within 2 to 10 words of the places
found, most often or most typical first (point at one for both figures; in one document or one code, "typical" is measured against that document's or code's own passages). Every line opens the document at its words,
and its flask button starts a check of what the line says. Download all lines for Excel or as CSV. A *passage* is
the stretch of text the app reads as one unit, up to about 1,100 characters (from 0.15 a paragraph: see *How
documents are read*); the location (page, paragraph) is that of the original.

**Profile.** Which codes of a codebook (the 169 SDG targets by default, the 17 goals, or your own CSV) each document
addresses, how much and where. When documents are added, the app finds candidate codes in seconds by their
keywords (and by meaning, with an embedding model): a *provisional* profile. *Let the AI label the passages* has the
AI read each passage with a candidate code and say which codes really apply (main topic or mentioned; for the SDGs,
whether the passage says it helps or hinders the aim), with a quote and a reason; afterwards it says how many keyword
codes it confirmed, did not confirm, and added. Count by code or by group (the SDG goals). The grid opens the passages
behind each cell. In a document, the **Codes** panel shows every code with its passages, quotes, reasons or the
words that found it (highlighted in the text): agree, change how it applies, reject (with Undo), or add a code of
your own; your labels always count (a keyword label you agreed with or changed stays even after the AI has read the
passage). *Technical details* show the model, its exact version (digest), the prompt and
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
and by code. Rename, merge and move passages (kept, and carried to a new set with the same settings after documents were added:
an edit follows its theme by the passages they share, and stays behind when no theme of the new set has them); *Let the AI
name the themes* gives names and short descriptions with checked quotes. A small project gets fewer themes than
asked (about three passages a theme).

A theme that is not relevant to you (running headers, reference lists, a topic outside your question) can be
**removed**: its passages are left out of the themes, the grids and the downloads, and it waits under *Removed
themes* at the foot of the list, where *Bring it back* undoes it. *Remove and find a new theme* also looks for a new
theme in its place, on this computer and without AI: among the passages that fit their own theme least well, it
finds the group that sits closer to a new centre than to the theme it is in, and moves it into a new theme named by
its key terms (the themes it takes passages from keep their names). It never takes passages that are closer to a
theme you removed, so the removed theme does not come back under another name. A new theme says which theme it
replaces and where its passages come from; remove it too to find another. Removals and new themes belong to that
set of themes only.

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

**Where the parts of the Cross-Doc SDG Explorer went.**

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

### How documents are read (0.15)

Before anything else, ENLENS turns each file into text and cuts the text into passages: what search, codes,
themes, concepts and checks read. The part that does this is the *reader*. ENLENS 0.15.0 has a new one (reader 2),
and 0.15.1 adds to it for text files and books (reader 3, below); documents added earlier keep the reading they have
until you move them over (below).

**What the new reader does with a PDF.** It looks at where each line stands on the page (with the `pdfminer` extra,
which the one-line install has; without it, it reads the PDF's text layer, without columns or tables):

- **Columns** are read one after the other, not across, and a title or abstract set across the page comes first.
- **What is not the document's own text is set aside**: running heads and footers, page numbers, line numbers in the
  margin, the words inside charts and diagrams, author names, affiliations, e-mail addresses and dates on the first
  page (*author and article details*), acknowledgements, funding, conflicts of interest, data availability and
  licence notes (*end notes*), footnotes, and the reference list. They stay in the document and in a search of all its text, but searches, codes, themes and checks
  do not read them, so themes no longer form around journal names and checks no longer read a funding note.
- **Tables are kept as tables**, with their caption, rows and cells; they are left out of the passages (a table read
  as prose is what made most garbled passages), and each can be downloaded for Excel.
- **Words are repaired**: a word cut at a line end is joined ("exam-ple" → "example"), a compound keeps its hyphen
  ("long-term", "non-fiction"), words that ran together are split only where the document itself writes them apart
  ("ofthe" → "of the"), and ligatures (ﬁ, ﬂ), odd spaces and accents set apart from their letter are put right.
- **A passage is a paragraph** (long ones are cut into parts of about equal size, short ones put together), and a
  heading starts a new passage with the text under it. Paragraphs are numbered as quotes are cited: per page in a
  PDF, a heading with the text under it counting as one; every block between blank lines in a text file.

Word files, web pages and text files are read as before, with the same repairs, their headings and the reference
list set aside in the same way.

**Text files and books (0.15.1, reader 3).** Many `.txt` and `.md` files are text copied out of a PDF by a converter:
every running head and page number is still in the text, while the pages, the headings and often the spaces between
words are gone. Reader 3 reads such files with rules on the text alone (no AI):

- **Running heads and footers** are found because they come back about once a page, next to a page break or at
  regular intervals ("Frontiers in Neurology 04 frontiersin.org", a printer's line drawn twice letter by letter);
  a short one in capitals with its page number ("2 INTRODUCTION") is found from two pages, or from the contents.
  Answers that come back in an interview ("[P] Ja.") come back irregularly, in the middle of the text: they stay.
- **Page numbers**: lines that are only a number, counting up a page apart.
- **Paragraphs and headings**: a short line that ends a sentence ends its paragraph, and a short line standing on
  its own is a heading. A Markdown file, web page or Word file that marks fewer than three headings gets headings
  this way too (before, a Markdown file without marked headings had none).
- **Books and theses**: the table of contents is found (lines ending in page numbers that go up) and set aside, and
  its entries find the chapter headings in the text. What comes before the first chapter (half title, other books
  by the author, the copyright page, the dedication, lists of figures) is set aside as *front matter*, but an
  abstract, summary or preface stays. The notes, the bibliography, the index, *About the author* and the
  acknowledgements at the end are set aside. An index is also known by its lines ("archetypes, 112–116, 191").
- **Repairs**: text printed twice ("TTIISS ffiinnaall" → "TIS final"), ligatures a converter broke with a space ("fi
  nd" → "find"), and, only in a file that lost many of its spaces, words run together ("peoplelivingwithdementia" →
  "people living with dementia", using the words the document itself writes apart; never into word endings).

*Reading* says when a text file looks copied out of a PDF, when many of its words still run together, and when a PDF
was read without its layout (the `pdfminer` extra missing). If you have the PDF, add it instead: it reads better. A
git copy of ENLENS gets the `pdfminer` extra at its next `enlens update` (0.15.1), as the one-line install always
has.

**The reading view.** A document's page shows its text the way the new reader found it: headings, paragraphs,
captions and tables, a mark where each page begins, and what was set aside folded under *Left out of the text* on
each page. Point at a block, and under where it is cited comes **Leave out** (searches, codes, themes and checks
will not read it) or **Restore** (they will); a table also has **Excel**. A heading goes with the text under it, and short paragraphs that share a passage go together. Your
choice is kept by the block's words, so it holds when the document is read again; *restored by you* or *left out by
you* stands beside it. Changing what counts makes keyword codes, key terms and themes out of date, as adding a
document does.

Two more, from 0.15.1. **All like this** (on a short block that comes back, such as a running head or a page number)
leaves out, or restores, every block that looks the same, their numbers aside: one click for a running head on every
page. **Text starts here** (on a block in the first third of the document) and **Text ends here** (in the last third)
leave out everything before or after it: a book's title pages, or its notes, bibliography and index, when the reader
did not find them. *the text starts here (you said)* stands beside the block, with *Undo start* (or *Undo end*). A
block you restore before the start or after the end still counts. Both are kept by the block's words, so they hold
when the document is read again.

**Reading** (a panel beside the text) says how well the document was read: *Read well*, *Read, with something to
check* or *Read badly*, with the reasons (pages without text, text recognised from scanned pages, a garbled text
layer, most of the text set aside), how many pages had columns, what was repaired, the tables found, and how many
of its passages features read. *Show what was left out in the text* unfolds everything that was set aside. The list
of documents marks the ones that need a look.

**Page** (beside the text, for PDFs, with the OCR extra) shows the page of the original PDF with every block the
reader found outlined: solid for what counts, dashed for what was left out. It follows the text as you scroll; click
an outline to go to that block in the text.

**Read with the new reader.** A document added before 0.15 (or, for reader 3, before 0.15.1) keeps the reading it
has, so every quote and judgement in it stays where it is. Its *Reading* panel offers **Read with the new reader**. ENLENS first reads the original file
again and shows what would happen, changing nothing: how many of your results (a check's grades and your
judgements, codes and your reviews of them, themes, references) find their place in the new text, and which do not.
**Move it to the new reader** then does it in one step, or not at all: each result follows its quote to the same
words in the new text; a check keeps the excerpt it showed; keyword codes, key terms and the document's search index
are made again; work still waiting for the AI about it is asked again; a set of themes is marked out of date where
its passages changed. What cannot be placed is kept without a place in the text and listed (its check marks it *no
place in the new reading*). It needs the original
file, unchanged, and no task of the document out with Claude Code. In a project shared with colleagues, move a
document on both copies: until then, a colleague's older reading comes in as a second copy of it.

**`enlens measure`** shows in figures how well ENLENS reads, with no AI: it makes small PDFs whose text it knows (one
and two columns, running heads, line numbers, front and back matter, a table, footnotes), reads them with each
reader, and reports the share of the words kept, the share that belong, whether they come in order, words run
together or broken apart, and leftover boilerplate. `--folder DIR` measures PDFs with a `.txt` of their true text
beside them; `--ws PROJECT` checks how many of a project's quotes still find their place in each reader's text (on a
copy: the project is never changed), `--timings` adds how long reading, search, key terms and themes take, and
`--report FILE.md` writes it as a report. Each release carries this report as `validation-report.md`.

### The bibliography: Zotero (0.13)

*Bibliography* (in the sidebar, under *Documents*) puts your Zotero library, one collection of it, or just the works
you choose, next to the project's documents. It answers three questions: which works of the bibliography do I have, which do I still need
to find, and which documents are not in my bibliography. It uses no AI.

**Bringing it in.** ENLENS reads Zotero from the Zotero app on this computer: Zotero 7 or later, open, with *Settings
→ Advanced → Allow other applications on this computer to communicate with Zotero* ticked once. Choose the library
(My Library, or a group library), a collection (or *The whole library*) and whether its subcollections come along,
and press *Bring in the bibliography*. To bring in only some works, even a single one, tick *Choose the works one by
one* (0.13.9): a list of the library's works appears (or of the collection chosen above), searched by title, author
or year as in Zotero's own search box. Tick the works you want; they stay ticked while you search or switch
collections, and stand above the list (click one to leave it out). Press *Bring in 1 work* (or *2 works*, and so on). Nothing goes over the internet, no Zotero account or key is needed, and Zotero
is only read, never changed. The page says plainly when Zotero is not open, does not allow it yet (with the box to
tick), or is too old. Without the app, *Use an exported file instead* takes a file exported from Zotero (right-click a
collection → *Export Collection…*: BibTeX, RIS, CSL JSON or CSV) or from Mendeley, EndNote and other reference
managers (BibTeX or RIS). With Zotero's CSV and BibTeX the paths of the files Zotero keeps come along too.

**The four lists.** Four tiles at the top count them and open each one:

- *Please confirm*: a work whose title stands on the first pages of a document, with an author or the year (the
  reference list of a short document is not read as its first pages), or whose DOI the document only mentions somewhere
  on its first pages (it may cite the work). A work with neither author nor year (Zotero often saves a *Web Page*
  that way) is proposed when its title is long (six words that count or more) and stands whole on the document's
  title page (0.15.1). The work
  and the document are side by side, with the place on the document where the title stands, highlighted, and what was
  found (*Found on page 1: the whole title, the author Lindqvist, the year 2025*). *Same work* links them; *Not the
  same* means the pair is never proposed again. *Confirm all* takes every pair at once.
- *To find*: the works without a document, with their authors, year, type, where they were published, a DOI link,
  their web address and *Open in Zotero*. *Download the list* gives them as a spreadsheet, your to-download list.
  When Zotero keeps a file (a PDF, a saved web page, a Word file) for some of them, a card offers *Add these files to
  the project*: they are read where Zotero keeps them (nothing is copied), after you say who may read them with AI
  (the project's choice is preselected), and each is linked to its work. When a work has several, the real document
  is added (0.15.1): its PDF first, then a Word file, then a text file, and a saved web page (Zotero's snapshot of a
  landing page) only when nothing else can be read. *Link a document* says by hand which
  document a work is.
- *Linked*: each work with its document, and how they were linked: *Same file* (a file Zotero keeps for the work is
  the very file you added, by its checksum), *Same DOI* (the document prints the work's DOI on its title page or in its file name), *You confirmed it* or
  *You linked it*. *Unlink* undoes a link for good (*Undo* in the message brings it back). A linked document is
  called by its work's title everywhere in ENLENS (0.13.3); when the file's own title says something else, it stays
  under the file name (*Title in the file: …*).
- *Not in the bibliography*: the documents no work is linked to. Add them to Zotero and press *Update from Zotero*, or
  *Link to a work* by hand.

**Keeping it up to date.** *Update from Zotero* reads the same collection again, or the same chosen works (a work
deleted from Zotero goes; a work added to Zotero does not come along). *Use another collection or file* replaces the
bibliography; for chosen works it is called *Choose other works or a file*, and the works you chose last time start
ticked, so adding one more is one tick away. Your decisions are kept for every work that is still there, even when it comes from
another source (by its Zotero key, else its DOI, else its title and year). Documents you add later are matched as
they come in: the message after adding says how many were linked and how many wait for you. A document linked to a
work takes the work's title (0.13.3): in the Documents list, on the document page, in Search, in a check's excerpts
and in the exports. The document page also shows the title read from the file, which comes back when no work is
linked any more; a title edited in Zotero follows with *Update from Zotero*. The document also shows its reference
(*Verhoeven and Okafor (2025)*) in the Documents list, and on the document page with its DOI and *Open in Zotero*.
*Remove the bibliography* takes the works and links out of the project; documents and Zotero
stay as they are.

**What the matching does not do.** A scanned PDF without a text layer has no title to find until text recognition
(OCR) has read it. The same title in different years (an annual report) is told apart by the year printed nearest the
title; when both are close, both pairs are shown for you to choose. A book and one of its chapters, or a translation,
are at best proposed. A document that only cites a work is not taken for it: the title must stand on its first pages
as a title, not as words spread over them.

### Working on a project together (0.14)

Two or more researchers can work on one project, each on their own computer and their own Claude plan. Each keeps a
copy of the project, and you exchange your work as a file: there is no server and no account, and nothing goes
anywhere you do not send it yourself.

1. **Your name.** On the *Projects* page, under *Work together*, type the name colleagues should see beside your
   judgements and press *Save*. (Judgements made before 0.14 are yours: they get your name the first time you send
   the project.)
2. **Send your work.** *Download as a zip* on the project, as before, and send the file (e-mail, a shared folder, a
   USB stick). Since 0.14 the file says which project it is and who sent it.
3. **Bring in a colleague's work.** The first time, your colleague chooses *Import a project (.zip)*, which makes
   their copy. From then on, each of you chooses *Bring in a colleague's work* on the same project and picks the
   other's newest file. A short report says what came in. A file from another project (or from an ENLENS before
   0.14, which cannot say) is brought in only after you confirm, for when you mean to combine two projects.

How the two copies come together:

- **What is new comes in:** documents with their original files, results, sets of themes, codebooks (also those kept
  for all your projects, in the ENLENS folder), the AI's labels and reference chains, links between terms, and the
  bibliography (when you have none, or it comes from the same Zotero collection or file). New documents get the
  setting for new documents of your copy when it is stricter than theirs.
- **Newer versions replace older ones.** A result your colleague changed (a note, excerpts read again, more
  excerpts) and you did not is brought up to date, and the other way round. ENLENS remembers each state of a result
  that was sent or brought in, so it can tell a newer version from one you both changed. Colleagues on different
  ENLENS versions work together as well (0.14.3: before, a version that stored one more detail per excerpt made every
  result a sync clash; states remembered by 0.14.0 to 0.14.2 are still recognised).
- **A sync clash keeps both.** When you both changed the same result, set of themes or codebook, your colleague's
  version comes in as a copy beside yours, marked *sync clash · Anna's version* in the *Results* list, with a notice
  and a link to the other version on the result. Compare them, keep the one you want and delete the other.
  Each of you keeps your own version, with the other's beside it; bringing in the same file again makes no second
  copy. When your colleague changes their version again, your copy of it is brought up to date. To settle the clash,
  delete the version you do not want: the *sync clash* mark goes. A copy you deleted does not come back unless they
  change it again; when you kept theirs and deleted yours, it goes on following their changes.
- **The same file, read into other text.** Every quote is a place in a document's text. When you both added the same
  file but the two computers read it differently (another ENLENS version, or text recognition on one computer and
  not the other), your colleague's reading comes in as a document of its own, marked *sync clash · Anna's reading*
  on the *Documents* page, and their results point at it.
- **Each person's judgements.** A judgement of an excerpt is kept under the name of who made it. In your copy, yours
  count. Where you have not judged an excerpt, the latest colleague's judgement counts, and the card says *Anna's
  judgement*; a comment of yours is not a judgement, so it does not set hers aside (0.14.3). When others judged an
  excerpt too, the card lists them (*Also judged: Anna contradicts*), marked where you differ. *Take back* removes
  only your own judgement: a colleague's then counts again. *How often you agreed
  with the AI* (Settings → Checking) counts only your own judgements. The *Projects* page says how often you and each
  colleague judged the same excerpts alike, with Cohen's kappa once you share 10 or more.
- **Each person's reviews.** Your verdicts on labels, links between terms and themes count over a colleague's on the
  same thing. *Clear* and *Undo* take back only your own.
- **AI work both of you did** on the same document (labels of a codebook, reference chains) is not doubled: yours is
  kept.
- **Who may read a document with AI.** The stricter of the two settings wins (*No AI* over *Only a local AI* over
  *Claude may read it*), and the report says so. Your colleague's reading of a file you have (*sync clash · Anna's
  reading*) is never less restricted than your document of that file: make yours stricter and theirs follows
  (0.14.3). When your colleague's copy let Claude read a document you keep from Claude, what Claude made of it there
  comes in with the rest, and the report tells you how many excerpts Claude read. Nothing is sent anywhere by
  bringing work in.
- **What you removed stays removed.** A document, result or set of themes you removed does not come back, nor does
  a colleague's reading of a file that you removed (0.14.3). When your colleague removed something you still have,
  the report names it and leaves it in your copy.
- **Not brought in yet:** a check still running in your colleague's copy (bring in a later file when it is done),
  and the vectors of search by meaning (your computer makes them for the new documents, as for any it adds). A result
  or set of themes still running in *your* copy (waiting for Claude Code, or being read) keeps your version for now,
  even when your colleague's is newer, and the report says so; bring in their file again when it is done, and their
  version comes in beside yours (0.14.3: before, yours was replaced and the work under way was lost).

Before bringing work in, ENLENS keeps a copy of the project's database as it was (`backups/before-bringing-in.sqlite`
in the project folder, replaced each time). To go back, quit ENLENS and put that file in place of `enlens.sqlite`.
From a terminal, `enlens --ws <project folder> bring-in <zip>` does the same as the button (`--anyway` for a file
not known to be this project).

To move to a new computer yourself, use *Move ENLENS to another computer* (it keeps who you are), not a single project
zip: a new installation is a new person, and your own judgements would come back under your old name.

Bring in files only from the colleagues you work with. Nothing in a file can reach files outside the project, loosen
who may read a document with AI, or replace what you decided: a judgement or review under your name in a colleague's
file is not brought in (0.14.3; before, a crafted file could replace your judgement). But a file is trusted with
what people decided, so a crafted one could take back judgements or reviews made under your name.

### Settings

Settings has five tabs, each one page with nothing folded inside another (0.9):

- **AI**: which AI reads your documents, as four choices: **Claude Code** (recommended: your own Claude plan),
  **A model on this computer** (automatic, Ollama, or an OpenAI-compatible server such as LM Studio, with the
  address, model and reasoning switch), **No AI (demo)**, and the **Claude API (team key)** for a shared
  installation, behind a confirmation and *Allow cloud models*. With Claude Code: the set-up checklist and *Set up
  Claude Code* (section 6) and *Let the auditor use Fable*. *Save and test* says whether the AI answers (with Claude
  Code: whether it is set up). With a model on this computer chosen but none installed, the same steps as on the
  first screen: get Ollama, then *Download qwen3:8b* (0.13.7). *Local model for restricted documents* offers the
  download too, and *Settings → Documents* downloads nomic-embed-text for search by meaning when Ollama has no
  embedding model.
- **Checking**: the **strictness** (how sure the AI must be before a judgement counts; it saves at once, applies to
  every result, and reports which answers and counts changed; *Back to normal (60%)*), with **how often you agreed
  with the AI, by its certainty**: a small chart from the excerpts you judged; after 20 judgements it may suggest a
  strictness ("When the AI was at least 70% sure, you agreed with it in 85% … *Use 70%*"); and how new checks start
  (other words, parts, how many excerpts to read and at most how many from one document).
- **Exploring**: the codebook of the profiles, how many themes a new set looks for, and the **codebooks**: view the
  codes, add a CSV codebook (commas or semicolons, UTF-8 or a Windows code page: a spreadsheet saved in Hungarian or another European setting works; a file in a codebooks folder that cannot be used is listed with the reason), remove one; a CSV codebook can be marked as aims a text can help or hinder, like the SDG
  targets.
- **Documents**: **reading scanned PDFs** (on or off, and the languages) and the embedding model for **search by
  meaning**.
- **Technical**: **AI model per task** (which model answers each kind of task, what it steps up to, the helper on
  Claude Code, a choice per kind, *Use the recommended models*, and for local servers the small model for labels and
  links; on Claude Code, since 0.13.10, *The recommendations follow* your Claude plan, see *Models that suit your
  Claude plan* below); with a local model, the **model for second opinions** and the **context length** (automatic by default, see section
  5) with *Sort the best excerpts again by wording* (off; see the changelog of 0.6.0); **Repeatable results** (the
  seed sent with every request, 42 by default, and a test of whether the server gives the same answer twice); *Test a
  model before trusting it* (section 5); and where your data is. 0.15: **Which new versions to offer** and **Copy
  technical details** (below).

**Trying new versions early (0.15).** ENLENS offers full releases only, by default. From 0.16 on, a *release
candidate* (a try-out of the next version) comes out at least a week before each new version. To be offered candidates, choose *Try new
versions early* under *Settings → Technical → Which new versions to offer*; *Stable (recommended)* goes back. Try a
candidate on a project you do not share with colleagues: going back to the stable version can show sync clashes on
what the candidate made (nothing is lost). A copy installed from git follows its branch and has no such choice.

**Reporting a problem (0.15).** *Settings → Technical → Copy technical details* copies a few lines for a problem
report: the ENLENS version, how it was installed, the system and Python, the AI route, whether cloud models are
switched off and the update channel; never a path, a project or document name, or a key. *Report a problem* opens a
short form on GitHub (a free GitHub account is needed) to paste them in; please paste no text from documents that
must stay private. A security or privacy problem is reported privately instead: see `SECURITY.md` in the repository.

Old links to a section (`#/settings/second`, `#/settings/calibration`…) open its tab.

When no local model is chosen, or the chosen one is not installed, the app uses one the model server already holds
in memory (so nothing extra is loaded), else the most recently downloaded one, and the test says so.

### For whoever installs the app

- A new installation uses Claude Code on the researcher's own plan (0.9). To use a model on this computer instead,
  choose it once in *Settings → AI* (or let *automatic* find Ollama or LM Studio) and press *Save and test*; with
  Ollama running, *Download qwen3:8b* there gets a model without a terminal (0.13.7); an
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
enlens --ws myproject ingest ~/Reports/ more.zip                    # PDF, Word (.docx), HTML, text, Markdown, zips
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

**Getting one.** No Claude plan, or documents that must stay on your computer? Choose *A model on this computer* (the
first screen or *Settings → AI*), get [Ollama](https://ollama.com/download) (free) and open it: ENLENS notices it and
downloads a model with one button (section 3, *First use*). LM Studio, llama.cpp, Jan and vLLM work too, as
OpenAI-compatible servers. In a terminal instead:

```bash
ollama pull qwen3:8b             # any local chat model
ollama pull nomic-embed-text     # optional: search by meaning as well as by words (bge-m3 for mixed languages)
```

To use a local model only for some documents, mark them *Only a local AI* (section 8). To make sure nothing is ever
sent to a cloud model, see *For whoever installs the app* in section 3 (`--local-only`).

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
- **Memory.** ENLENS loads no model of its own and makes one model call at a time. A second opinion unloads the
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
nothing else. The page and the sidebar's queue panel say *Claude Code is working on it*, with *Stop Claude Code*;
it stops by itself when nothing waits. *Stop Claude Code* returns the batches it had taken to the queue at once.
Pressing *Start* twice (or in two tabs) starts one run, and each project's run works in a folder of its own (0.14.3).
*Quit ENLENS* and *Update and restart* stop the runs first; a run that was still working when ENLENS closed (it was
closed some other way) is recognised when ENLENS opens again: the page shows it as working, *Stop Claude Code* stops it,
and *Start* does not start a second one beside it. If a
run ends with a problem (a usage limit, for example), the page shows the end of its report. The first start also
adds the plugin if that was not done yet.

**How fast it works (0.13.10).** Under **Start Claude Code** is **Speed: Slower · Normal · Faster**. Claude Code
hands the work to helpers (one per kind of task, each on its own model); the speed is how many work at once: Slower
one, Normal two (as before), Faster four. Faster is done sooner but uses your plan's limits faster; Slower takes longer
and is easiest on them. The choice is kept, is the same beside every *Start Claude Code*, and is also under *Settings
→ AI → Speed of Claude Code*. A run already working keeps the speed it started with; the line *Claude Code is working
on it* says how many helpers it has (*· 4 helpers at once*).

For one run you can also choose the helpers yourself: **Choose the helpers for this run**, folded away under the
speed, lists each helper that has work waiting, with its model, what it would answer and how much waits (*Labeller
haiku · Codebook labels · 7,868 waiting*). Set how many of each work at once (0 leaves that work waiting for a later
run) and **Helpers at once, in all** (1 to 8). The fold then says *changed* and the speed above it greys out; *Use the
speed again*, or picking a speed (even the one shown), undoes it. Work that comes in during the run for a helper not listed (an unsure answer for the auditor,
a check's excerpts after its search words) gets one helper. The choice is for that run only: after *Start Claude
Code* the fold is back to the speed. Which model each helper uses stays under *Settings → Technical → AI model per
task*.

Until it is pressed, nothing is answered: the step that waits keeps its spinner, so from 0.11.3 a **Start Claude
Code** left unpressed for about five seconds while work waits (and nothing answers it) pulses, and the line beside it
says *Nothing runs until you press it.* (with reduced motion in the computer's settings, it has a still ring
instead). The pulse stops once it is pressed, or once Claude Code started some other way takes the work. The button
is wherever work waits: a check's progress, a result that waits, the sidebar's queue panel, and since 0.11.3 also
the line of a follow-up on a result (reading an excerpt again, reading new documents, a second opinion, a stronger
model), which used to say only which command to type.

**Or type it yourself.** The same work can be started in Claude Code, opened in any folder:

```
/enlens-run Pilot              # every kind of task waiting in the project Pilot
/enlens-run Pilot label        # only the labels
/enlens-run Pilot --parallel 4 # four helpers at once: faster, but it uses your plan's limit faster
/enlens-run Pilot --helpers checker=2,labeller=1   # only these helpers, as many of each at once (0.13.10)
```

Without `--parallel`, a typed run goes at the speed chosen in ENLENS (two helpers at once unless you changed it;
0.13.10). With `--helpers`, the helpers not named do nothing in that run, and `--parallel` (if given) caps the total.
The helpers' names are labeller, linker, namer, reader, extractor, checker and auditor. ENLENS works out how many
helpers each kind of task gets, in the queue's order, and never more than it has batches for. The speed counts the
helpers of one run: Claude Code started both from ENLENS and in a terminal at the same time runs both runs' helpers.

`/enlens-run` hands each kind of task to a helper agent on the model ENLENS names for it (labels and links on
Haiku, theme names, references, search words and checks on Sonnet; for the SDG pack, extraction on Sonnet,
splitting the VCA and checking its claims on Opus, audits on the auditor; *AI model per task* in Settings) and
reports what is done and what is left. The helpers can use only the ENLENS queue tools: they see nothing but the
passages handed out and write nothing but answers. Every answer is quote-checked; a wrong quote is sent back and
answered again. An unsure answer (certainty under 0.6), or one rejected twice, goes once to a stronger model.

You follow the progress in ENLENS: on the page that waits, and in the **queue panel** under the jobs in the
sidebar (per kind: waiting, being answered, done, the model and helper, the estimate; *Do first*, *Hold*, *Remove*).
Work that waits for Claude Code while nothing answers it (Claude Code not started from ENLENS, no `/enlens-run`
taking or answering a batch, no answer in the last two minutes) is **not running**, and the jobs line above the queue
panel says so in amber with a pause mark: *1 task not running · Waiting for Claude Code to start*, with *Start Claude
Code* in its panel (0.12). Once Claude Code takes the work it says *1 task running* again, with the pulsing dot.
A check waits under Results as *Waiting for Claude Code*: its search runs in ENLENS at once, and only its search
words, parts and judging wait. It finishes when the answers arrive, even if the app was closed meanwhile.

**Stopping.** A run can stop at any moment (a usage limit, a closed laptop, Ctrl+C). A batch taken and not answered
returns to the queue after 30 minutes, and the next `/enlens-run` continues where it stopped; nothing is lost. When
answers stop arriving, ENLENS says *Paused at 340 of 7,868 labels. To go on, type /enlens-run Pilot in Claude Code.*
*Stop* on a waiting page takes its tasks that no session has taken yet out of the queue (a waiting check is removed
whole).

**Models that suit your Claude plan (0.13.10).** On Claude Code the recommended model of each task follows the plan
Claude Code is signed in with. ENLENS finds it by itself, in the background (from `claude auth status`, when the app
starts, when it looks at the queue and before a run), and work that waits follows a new plan at once:

| Plan | Recommended models |
| --- | --- |
| Free | No Opus or Fable. Haiku for most tasks (search words, splitting a hypothesis, theme names, references, labels, links), stepping up to Sonnet when unsure; judging excerpts, second opinions and the SDG pack's reference claims on Sonnet. |
| Pro (and a plan not known yet) | As before: Sonnet for most tasks, Haiku for the many labels and links, Opus for second opinions and the hard cases (and the SDG pack's reference claims and checks). |
| Max, Team, Enterprise | Opus for most tasks, checks included. Haiku and Sonnet only where there are many tasks at a time and speed matters: labels and links (Haiku), references and the SDG pack's extraction (Sonnet, stepping up to Opus). A check on Opus has no stronger model unless *Let the auditor use Fable* is on (the result page says so in those words). |

A model you chose for a kind of task (*AI model per task*) comes first on every plan. Should Claude Code name the
plan wrongly, or not at all (signed in with an API key), set it under *Settings → Technical → AI model per task →
The recommendations follow*. The Claude API and local models do not follow the plan. Note that Claude Code itself
may need a paid plan.

**Fable.** The auditor (second opinions, and checks read again by a stronger model) runs on Opus (on a Free plan:
Sonnet). *Let the auditor
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
| `reader`, `app_version` | 0.15: `documents.reader` is the reader that read a document's text (1 for every document read before 0.15) and `documents.app_version` the ENLENS version that read it; `app_version` in `results`, `runs`, `labels`, `theme_runs` and `hypotheses` is the version that made each (empty: made before 0.15) |
| bib_items, bib_links | 0.13: the bibliography's works (title, creators, year, DOI, web address, Zotero link, the files Zotero keeps with their checksums) and which document each is (`status`: `auto` for the same file or DOI, `probable`, `confirmed` or `rejected` by a person; `method`: `file`, `doi`, `title`, `person`); where it came from is in `meta` (`bibliography`); 0.13.3: `documents.file_title` keeps the file's own title while a linked work's title replaces it (`meta` `titles_version` rebuilds the keyword index) |
| people, judgements | 0.14: the people whose work is in the project (id and name), and each person's own judgement of an excerpt; the one in force is copied to `verifications.user_*`, with `user_by`; `reviews.person_id` says who made a review |
| sync_seen, sync_copies, sync_removed, sync_log | 0.14: every state of a result, set of themes or codebook that was sent or brought in (its fingerprint); a colleague's version kept beside yours (a sync clash); what was removed here; each colleague's work brought in, with its report. `documents.text_fp` is a fingerprint of a document's text; `meta` `project_uid` says which project a copy belongs to |
| vca_targets, vca_refs, doc_refs, claims, claim_targets, evidence, interactions, vca_claims, reviews | The SDG pack (section 13) |

Open it with any SQLite tool. Offsets in `evidence` and `verifications` index into `documents.text`. Removing one
document keeps past checks intact (each check stores the passages it showed); removing all documents also removes
every check.

**Moving to another computer (0.10).** *Projects → Move ENLENS to another computer → Download everything (.zip)*
makes one file with every project (each as its own project zip: database, the original file of each document) and
the settings.
A saved Claude API key is left out, and so are quick looks not kept; projects used in place from another folder come
along as copies. On the new computer, install ENLENS and choose the file under *Import from another computer* on the
first screen (or *Projects → Import a project (.zip)*, which takes both kinds of zip). Each project keeps its name
(`name (2)` when the name is taken). The settings come along only when the new computer has no project yet, and on a
`--local-only` installation never the choice of a cloud AI.

---

## 8. Privacy and copyright

**What stays on your computer.** Projects are plain folders with one SQLite database each; they and the settings live
in `~/enlens` (or `ENLENS_HOME`). With Claude Code (the default from 0.9), only the passages inside the tasks it takes,
from documents Claude may read, are sent to Anthropic, on your own Claude plan; ENLENS never sees its login. The
Claude API is used only after *Allow cloud models* is switched on (or `--backend anthropic` on the command line), and
a model on this computer keeps every word on it. `--local-only` hides both cloud options for good (section 3, *For
whoever installs the app*). The app is a small standard-library server on 127.0.0.1 with a token per run; the page
loads nothing from the internet (no CDN, fonts or analytics), and there is no telemetry. Apart from the AI you chose,
ENLENS itself goes online only to look for a new version on GitHub (section 1), and, when you ask for them, to get
Claude Code or a local model. Bringing in a colleague's work (section 3) reads the file on this computer and sends
nothing.

**Zotero (0.13).** The Bibliography page reads Zotero through the Zotero app's own connection on this computer
(`127.0.0.1`, port 23119), never through Zotero's servers, and only reads. The works' details stay in the project;
nothing about them is sent to Claude.

### Who may read each document with AI (0.11)

One project can mix documents Claude may read with documents that must stay on the computer: a licensed PDF, an
interview transcript. Every document has one of three settings:

| Setting | Who may read its text |
| --- | --- |
| *Claude may read it* | the AI you chose: Claude Code, the Claude API, or a local model |
| *Only a local AI* | a model server on this computer, or you |
| *No AI* | you only; Search, the keyword Profile, Concepts and Themes without AI still work |

> Documents you mark as local stay on this computer. ENLENS never sends their text to Claude, in any feature, and
> shows you how much of every other document it has sent.

**Where you set it.** When you add documents, the page asks *Who may read these documents with AI?*; one answer
covers everything added at once. The first answer in a new project becomes its default (nothing is preselected the
first time); later the default is preselected. On the Documents page the column *AI* has a small dropdown per
document; tick several documents to change them together. A note (*Why*, for example "publisher licence") is kept
with the document and exported with the project; it changes nothing. For large corpora, a `manifest.csv` may have
`ai_access` (cloud, local or none) and `ai_note` columns. Projects made before 0.11 keep *Claude may read it* for every
document, so nothing changes until you change it; a project zip made before 0.11 asks once when it is imported. On an
installation without cloud models (`--local-only`) the default is *Only a local AI* and Claude is not offered.

**What happens in each feature.** Finding passages is unchanged: every document competes for every check. Only the
reading is split. In a check, Claude reads the excerpts it may; those marked *Only a local AI* go to the local model
chosen in *Settings → AI → Local model for restricted documents*; those marked *No AI* (and the local ones when no
local model is chosen, or it cannot be reached) are shown as *Waiting for your judgement*, with your own judgement
open on the excerpt. The round stays one round, and each excerpt says who read it. The answer counts every
excerpt that was judged: the AI's, the local model's and yours. An excerpt waiting for your judgement counts once you
judge it; until then the answer rests on the others, and when every excerpt waits for you it is *Waiting for your
judgement* (0.14.3; before, those excerpts counted as not about the hypothesis). When the AI's own answers failed,
the check *did not work*, whatever the local model read, and none of that search's AI judgements count in any
answer, count, map or download (0.14.3; Excel marks them *Not counted: the check did not work*). The AI's written
note speaks only for the excerpts
it read, and is told how many others there are. A second opinion, reading an excerpt again, the Profile's AI pass,
theme names, concept links and references follow the same
rule: a task takes the setting of the most restricted document it touches. A theme whose passages are all
restricted is named by the local model or keeps its key terms; two concepts found only in restricted documents are
linked by the local model or not at all (a term's words are words of the documents). A check started in a Claude chat
(the connector) shows Claude only the excerpts it may read; the result page then offers *Read them now on this
computer* for the local ones. When the local model's answers for its excerpts cannot be used (three tries), the
result says so and shows them without a judgement; *Read them again on this computer* tries once more (0.11.1, for
instance after choosing another local model), or you judge them yourself. The check's written summary is always the
main model's, never the local model's note. When the main model itself runs on this computer, it also reads the
excerpts marked *Only a local AI*, so its summary and its notes on excerpts (*about another group*) are not shown in
a Claude chat (the connector says it left them out; 0.14.3, before they were shown). Search by meaning: an embedding server on another computer does not receive the
restricted passages (they are found by their words), nor the glossary's terms found only in them (0.14.3).

**The local model and your computer's memory (0.13.11).** While Claude (or Claude Code) reads its excerpts, the
progress says when your local model reads the ones marked *Only a local AI*: *Your local model (…) is reading 3
excerpts…*, with what it is doing and Stop. A local model needs about as much memory as its size (a 9-billion-
parameter model about 8 GB). ENLENS does not start it (on Ollama) when this computer has clearly too little free:
starting it anyway pushes every other program into swap and can all but freeze the computer. The check then finishes
with the rest, the progress says why, and those excerpts wait on the result (*Waiting for your local model*). Close programs you do not need and press
*Read them now on this computer*, or choose a smaller local model in *Settings → AI*. If it still says too little is
free, *Start it anyway* starts it regardless. A model that takes more than a third of this computer's memory is let go
as soon as it has read, instead of being kept for 15 minutes. A local model you chose as the main AI is not checked
this way: you start it yourself and see it load.

**How it is enforced.** In code, where every AI task is made and run, never by an instruction in a prompt: each task
is labelled with the most restricted setting of the documents it names, a task is refused before any model is asked
when its setting does not allow that model, and the queue for Claude Code only ever hands out tasks Claude may read.
The connector's tools (search, concepts, document profiles, checks) give Claude counts instead of restricted text,
leave out what a model wrote in its own words (a check's summary, its notes on excerpts) when it read restricted
text, and show a document marked *No AI* as *Restricted document 3*, because a title can name a person. A project
zip (*Download as a zip*) holds the files of the documents the project has now, not those of documents you removed
(0.14.3). The Claude Code run that ENLENS starts works in a box of its own (0.14.6): it starts in an empty folder, away from
the projects' databases, and has no tool that reads, writes or searches files, runs commands or browses, only the
one that starts the helpers. It takes nothing from your own Claude Code either: not your settings, hooks or
`CLAUDE.md` instructions, not your other plugins or the connectors of your claude.ai account; it loads only
ENLENS's plugin. So all it can see are the passages ENLENS puts in its tasks. These are options of Claude Code itself
(`--tools`, `--restricted`, `--plugin-dir`), used when your Claude Code knows them; an older Claude Code is only
denied the file, shell and web tools by name. The window ENLENS opens for the sign-in also starts in an empty folder
without those tools (it used to start in your home folder, where Claude Code could read your files without asking).

**What Claude has read.** ENLENS writes down every passage at the moment it leaves for Claude (Claude Code, the Claude
API, a Claude chat through the connector). The column *Sent to Claude* shows the share of each document's text;
click it for the passages, when and for which feature. *Settings → Technical → What was sent to Claude* downloads the
whole list (CSV), for example for a data management plan. For a project made before 0.11 the list starts with the
results ENLENS recorded then. Changing a document to *Only a local AI* applies to everything not yet answered; what
Claude already read stays in the results and the list. Removing a document takes its passages out of everything
still waiting for Claude Code (0.11.1). A check that was waiting for Claude Code when a document's setting changed
stops waiting and says so: the excerpts are then for the local model or for you.

**A cap.** In a document's dialog you can set *Claude may read at most N %*. Once Claude has read that much, its
further passages are treated as *Only a local AI*. It is checked when tasks are made, so a check that is running can
go over by one round of excerpts.

**Your Claude account.** *Set up Claude* and *Settings → AI* show *What happens to the text Claude reads*: on a
personal plan (Pro, Max) consumer terms apply, and Anthropic may use your sessions for training when the account's
model-improvement setting is on (turn it off at claude.ai/settings/data-privacy-controls before Claude reads licensed
documents); Team, Enterprise and the Claude API are under commercial terms. Documents that must stay in the EU:
mark them *Only a local AI*. The panel cites Anthropic's data-usage page and the date it was checked; that page is the
authority.

### Models and licences

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
  that cannot be read is listed under `failed` with the reason and the others are added (0.14.3: also a zip, or a
  file in a zip, that is damaged or password-protected, and a password-protected PDF; the connector's
  `create_project` and `add_sources` return them as `could_not_read`).
- Notes that travel with a corpus (`problems.txt`, `README.md`, `notes.txt`) are not ingested. When a manifest is
  present, `ingest` lists files it does not mention under `not_in_manifest`, so you can see what was added unlinked.
- `--exclude PATTERN` leaves out files by name, for example a download that turned out to be the wrong document:
  `enlens --ws pilot ingest enlens_text.zip --exclude 'A_18_*'`. Repeat it for several patterns.
- Text layers without a character map come out as `(cid:53)` codes or as shifted letters and control characters
  (`5HQHZDEOH DQG` for `Renewable and`). Such passages get section `unreadable` and are never sent to a model.
  (0.14.3: prose in Hungarian, Italian, Polish, Czech, Slovak, the Nordic languages, Finnish, Romanian or Croatian
  is no longer taken for it; documents added before keep their passages as they were read.)
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

### The model of each kind of task (0.8)

Every feature of the app, not only the SDG pack, sends each kind of task to its own model:

| Task | Claude Code and the Claude API | Steps up to | Local |
| --- | --- | --- | --- |
| Codebook labels, concept links | Haiku | Sonnet | the small model (if chosen) |
| Search words, splitting, theme names, references | Sonnet | Opus | the main model |
| Judging excerpts, reading one again | Sonnet (high effort) | the auditor | the main model |
| Second opinion | the auditor (Opus, or Fable if switched on) | | the second model |

On Claude Code these are the models for a Pro plan; on other plans they follow the plan (section 6, *Models that suit
your Claude plan*). A model chosen in *Settings → Technical → AI model per task* comes first. A task steps up once:
when its answer's certainty is under 0.6, after two rejected answers, or when you press *Ask a stronger model*. The
defaults are starting points until the runs on the pilot (`enlens acceptance queue|score`, see
[MODEL_CHOICE.md](MODEL_CHOICE.md)) set them.

**What every answer records.** The model, its exact version (digest), the prompt version and the seed (42 by default,
temperature 0); since 0.8 also the route (Claude Code, the Claude API, a local server), the helper, and whether the
answer came from the stronger model. Claude Code gives no seed and no digest (section 6, *What is recorded*). Every
Excel download ends with *How these results were made*.

**Results across versions (0.15).** Every answer, codebook label and set of themes also records the ENLENS version
that made it, each check the version that started it, and each document the *reader* that read its text (the part of ENLENS that turns a file into
text and passages). *How these results were made* names both. When a project holds results an earlier version made,
the *Overview* says so in one line under its cards. They stay as they were made: nothing is redone by itself. A new
reader (0.15) reads only the documents added after the update, so the documents you have keep their text, and every
quote and judgement in them stays where it is, until you move one to the new reader (*How documents are read*).

### The SDG pack's models

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

Every stored result records the model and the prompt version (`extract-v1`, `split-v2`, `verify-v2`,
`verify-set-v2`; for hypotheses `decompose-v1`, `expand-v2`, `check-v5`). When you change
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
| The ENLENS icon is a blank square (macOS) or a plain shortcut (Windows) | It was made before 0.10.2 without Pillow. Open ENLENS once with 0.10.2 or later: it gives the icon its picture (macOS: if Finder still shows the blank one, `killall Finder`). Or make the icon again: `enlens-gui --make-launcher`. |
| Settings shows an older version after updating | That copy was still running. Choose *Restart now* on the notice at the top of the page (0.13.1), or *Quit ENLENS* and open ENLENS from its icon (0.10.2 does this by itself when nothing runs). |
| There is no *Update* button in the sidebar | It shows only when there is an update (0.13.6). To look now, or to see why a look failed: *Settings → Technical → Check for updates*. |
| *Update* says it cannot update | It says why. Offline: try again later. Files of a git copy edited by hand: keep them with `git stash` (or undo them), then update. One-line install on Windows: choose *Quit ENLENS* and run the install line again in PowerShell. |
| The page keeps saying *Starting ENLENS …* | After 90 seconds it says ENLENS did not come back: open it again from its icon (or with `enlens-gui`), and look at `logs/enlens.log` in the data folder for the reason. |
| Double-clicking the ENLENS icon does nothing | Look at `logs/enlens.log` in the data folder. Run the install line again (one-line install), or `enlens-gui --make-launcher` again after moving or reinstalling Python (git copy). On macOS, if the icon was copied from another computer, right-click it and choose *Open* once. |
| The install line stops with "does not match the release's checksum" | The download was cut off or changed on the way; nothing was installed. Run the line again later. |
| The install line on Windows says uv could not install ENLENS | ENLENS is probably running: choose *Quit ENLENS* in it and run the line again. |
| macOS says *Install ENLENS.command* was "Not Opened" | The file is not signed by an Apple developer. Click *Done*, then allow it once in *System Settings → Privacy & Security → Open Anyway* (section 1), or paste the install line in Terminal instead. |
| Windows says it protected your PC, or the browser calls *Install-ENLENS-Windows.cmd* uncommon | The file is not signed. Keep it, then *More info → Run anyway* (section 1), or paste the install line in PowerShell instead. |
| *Set up Claude* cannot install Claude Code | No network, or the installer was blocked. Install it with Anthropic's set-up page (linked under *Technical details*), then press *Set up Claude* again. |
| Claude Code answers with the wrong Claude account | The sidebar card (hover *Claude, on your plan*) and *Settings → AI* name the account it uses. To switch, type `claude auth logout` in Terminal or PowerShell, then press *Check again* and *Set up Claude* in *Settings → AI*: it opens the sign-in window, where you sign in with the other account. |
| *Set up Claude* keeps waiting for the sign-in | Finish signing in in the window it opened (and in the browser page that window opened), then press *I have signed in*. No window? Open Terminal or PowerShell, type the line the page shows (it goes to an empty folder of ENLENS, then starts `claude`), and sign in. |
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
| "… got stuck writing blank space" | A known failure of some models with fixed-format answers. Try again, set *Reasoning* to off, or choose another model. From 0.14.3 this (and an answer cut off at the length limit) is one failed try of that task: it is asked again, and the check goes on with its other parts. |
| "The Claude API rejected the key" | Copy the key again from console.anthropic.com; check it has credit. |
| Two workers' answers ended up in one results file | Give each worker its own scratch folder. Move the stray lines to the right file; `import-results` accepts any order. |
