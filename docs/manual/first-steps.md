[Manual](../MANUAL.md) › First steps

# First steps

> **In short**
> - The first screen has three steps: **the AI** (*Set up Claude* does it all), **a project**, then **documents**.
> - No Claude plan? Choose a model on your own computer, or no AI for now.
> - The sidebar always says where your text goes.

## The first screen

<img src="../images/manual/first-use.png" alt="The first screen: the AI step with its checklist and the Set up Claude button" width="800">

### 1. The AI

ENLENS uses **Claude Code**, signed in with your own Claude plan. The step shows a checklist (Claude Code on this
computer, signed in, the ENLENS plugin added) and one button, **Set up Claude**, which does every step still open, in
order:

| Step still open | What *Set up Claude* does |
| --- | --- |
| Claude Code is not on the computer | Shows the command of Anthropic's installer (`curl -fsSL https://claude.ai/install.sh \| bash`, or `irm https://claude.ai/install.ps1 \| iex` on Windows) and runs it when you choose *Install Claude Code*. No administrator rights; a minute or two. *Anthropic's set-up page* is linked if you would rather do it yourself. |
| Not signed in | Opens a Terminal (macOS) or PowerShell (Windows) window already running Claude Code. Sign in there with your Claude plan (it opens a page in your browser), then close the window. ENLENS checks every few seconds and goes on by itself; *I have signed in* checks at once. If no window can be opened, the page shows the line to type. |
| The plugin is not added | Adds the ENLENS plugin to Claude Code. |

ENLENS never sees your login: it stays with Claude Code. The sign-in window starts in an empty folder of ENLENS
(`claude-runs/sign-in` in the data folder), with Claude Code's tools for reading files, running commands and browsing
switched off, so it cannot open your files. ENLENS runs Claude Code the same way for its work
([how this is enforced](privacy.md#how-it-is-enforced)).

*Set it up yourself instead* keeps the lines to type.

**No Claude plan?** *No Claude plan? Other options* offers a model on this computer, or no AI for now. A model on
this computer needs no terminal:

1. With no model server running, the step says how to get **Ollama** (free, from ollama.com) and notices by itself
   when it starts.
2. With Ollama running but no model yet, *Download qwen3:8b* (about 5 GB) gets one, with *Also nomic-embed-text* for
   search by meaning, a progress bar and *Stop* (Ollama keeps what it has and goes on from there).
3. The downloaded model becomes the AI and is tested at once.

Ollama fetches the model from ollama.com; none of your documents are sent. When whoever installed the app already
chose a local model that answers, this step is skipped. More in [A model on your own computer](local-models.md).

### 2. A project

Name a **project**: one per set of documents. Used ENLENS on another computer before? *Import from another computer*
brings every project and the settings in one go ([Moving to another computer](together.md#moving-to-another-computer)).

### 3. Documents

Choose files or a folder. ENLENS reads:

| Kind | Notes |
| --- | --- |
| PDF | Text, columns and tables are read from the layout ([How documents are read](reading.md)). Scanned pages need [Tesseract](install.md#scanned-pdfs-optional). |
| Word (.docx) | Keeps its paragraphs, headings and the pages Word marked. Older .doc files are not read: save them as .docx or PDF. |
| Web pages (HTML), text (.txt), Markdown (.md) | Files that are not UTF-8 (a Hungarian text saved by Notepad, an old Latin-1 page) are read as they were written. |
| Zip | Opened, and the files inside are added. |

Then ENLENS asks **who may read these documents with AI**: Claude, only a local AI, or no AI
([Privacy](privacy.md#who-may-read-each-document-with-ai)).

The list shows the title read from each file and warns about unreadable text and very short files (often a landing
page saved instead of the report). A file that cannot be read (password-protected, damaged) is listed with the reason,
and the others are added. *Stop* also stops the text recognition of a long scanned PDF.

*Open an existing ENLENS project folder (advanced)* links a project made with the command line, without copying it.

## Finding your way

![The Overview of a project](../images/overview.png)

**The sidebar**, from top to bottom:

| Part | What is there |
| --- | --- |
| Project | *Overview* (the start page of a project), *Documents*, *Bibliography* |
| **Explore the documents** | *Search*, *Profile*, *Concepts*, *Themes* ([Explore](explore.md)) |
| **Check hypotheses** | *Check a hypothesis*, *Check several*, *Results* ([Check](check.md)) |
| Bottom | The line that says where text goes, *Settings* (with the theme icon), *Update to …* (only when there is an update), *Quit ENLENS* |

**AI marks.** Beside each feature, a filled **AI** mark means it needs the AI, a dashed one that the AI is optional,
and no mark that it never uses the AI. The marks are grey: green, amber, red and purple are kept for judgements and
answers.

**The theme icon** at the end of the *Settings* row: a screen follows your computer, a sun is light, a moon is dark.
Click it for the next one; hover it to see which is in use.

**The Overview** shows every feature with one line on what it does, whether it uses the AI and what is already made
in the project (a profile, a glossary, a set of themes, results), and the AI in use with anything left to set up.
Hover a card for what the feature is for. *Quick look at one document* is here too ([Explore](explore.md#quick-look)).

**Where your text goes.** The line at the bottom of the sidebar always says it:

| The line says | Meaning |
| --- | --- |
| *Claude, on your plan · Only the passages of AI tasks leave this computer* | The default: Claude Code on your plan. |
| *Private · The AI runs on this computer* | A local model. |
| Excerpts are sent to the Claude API | A shared installation that allowed the Claude API. |

Hover the line (or reach it with <kbd>Tab</kbd>) for a short card: with Claude Code it names the account Claude Code
is signed in to (*Signed in to Claude Code as you@university.nl*, and on a Team or Enterprise plan the organisation),
where the text goes and where to change it. <kbd>Esc</kbd> closes it. *Settings → AI* and `enlens claude-setup` name
the account too; ENLENS reads it from Claude Code (`claude auth status`).

**Every page looks alike.** A title and one short line under it; a longer explanation behind a small **(?)** that
opens on hover or click; downloads as one quiet line of links (*Download Excel (.xlsx) · CSV*). Model names and
other technical facts sit under *Technical details* and *Settings → Technical*, never on a working screen.

---

Next: [Check a hypothesis →](check.md)
