# ENLENS

ENLENS helps researchers explore their own reports, papers and interview notes and check whether they support a
statement, with every quote checked against the source, on their own computer and with Claude on their own plan.

![The Overview of an ENLENS project: exploring the documents first, then checking](docs/images/overview.png)

## Install

1. **Paste one line.** On a Mac or Linux, open *Terminal*; on Windows, open *PowerShell*. Paste the line for your
   system and press Enter:

   | System | Where | Paste this |
   | --- | --- | --- |
   | macOS, Linux | Terminal | `curl -fsSL https://github.com/dvaud/claim_checker_demo/releases/latest/download/install.sh \| sh` |
   | Windows | PowerShell | `powershell -ExecutionPolicy Bypass -c "irm https://github.com/dvaud/claim_checker_demo/releases/latest/download/install.ps1 \| iex"` |

   It needs no git, no Python and no administrator rights. When it is done, ENLENS opens in your browser, and its
   icon is with your other programs. **Or download a file and double-click it:**
   [Install-ENLENS-Windows.cmd](https://github.com/dvaud/claim_checker_demo/releases/latest/download/Install-ENLENS-Windows.cmd)
   on Windows,
   [Install-ENLENS-macOS.zip](https://github.com/dvaud/claim_checker_demo/releases/latest/download/Install-ENLENS-macOS.zip)
   on a Mac. Windows and macOS ask you to allow it the first time:
   [how](docs/manual/install.md#or-download-a-file-and-double-click-it).
2. **Press *Set up Claude*** on the first screen. It installs Claude Code if it is missing (it shows you the command
   first), opens a window where you sign in once with your Claude plan, and connects ENLENS to it.
3. **Name a project and add your documents** (PDF, Word, web pages, text, or a zip of them). ENLENS asks who may read
   them with AI: *Claude may read them*, *Only a local AI*, or *No AI*.
4. **Explore and check.** Where AI work waits, press **Start Claude Code**; the results appear as they come in.

No Claude plan? Choose *A model on this computer* on the first screen. Used ENLENS on another computer? Choose
*Import from another computer*. Installing it for someone else, and every option:
[Install and update](docs/manual/install.md) in the manual.

## Update

1. Type `enlens update` in Terminal or PowerShell, or run the install line or file again (on Windows, quit ENLENS
   and close Claude Code first).
2. Quit ENLENS (*Quit* at the bottom of the sidebar, or *Settings* › *Technical*) and open it again from its icon.

ENLENS also tells you when a new version is ready; *Update and restart* in its pop-up does both steps for you (on
Windows from 0.15.4 on). Your projects and settings (the `enlens` folder in your home folder) are never touched.

## What ENLENS does

- **[Explore your documents](docs/manual/explore.md)** before you claim anything: every place a word
  occurs, the codes each document addresses (the SDG targets or your own codebook), a glossary, themes, references.
- **[Check a statement against them](docs/manual/check.md)**: supported, partly supported,
  contradicted or mixed evidence, with the words of each source and every quote checked against the source text.
- **[Review the AI's judgements](docs/manual/review.md)** as you would a co-coder's: your
  judgements count, and the Excel download keeps them next to the AI's.
- **[Keep your bibliography beside your documents](docs/manual/bibliography.md)**: bring in a Zotero
  collection or a reference file, and see which works you have and which you still need to find.
- **[Use a model on your own computer](docs/manual/local-models.md)**, or no AI for some documents; whoever installs
  ENLENS can remove every cloud option for good (`--local-only`).
- **[The SDG and value chain pack](docs/manual/sdg-pack.md)**:
  impact claims tagged with UN SDG targets and compared with an expert Value Chain Assessment.

## New in 0.16: notes, a research log and your own codebook

- **Notes and highlights** on the exact words of a document: select words, then *Highlight* or *Note*. Search them
  all under *Documents* › *Notes*, and use a note as evidence in a check. Cannot change results.
- **A research log** that ENLENS keeps as you work (documents added, checks dropped and why, themes removed, codebook
  changes), with your own entries and reasons, to download for an appendix or an audit. Cannot change results.
- **Compare and restore** earlier versions of a set of themes, your judgements in a check, or a codebook. A restore
  puts back what you had before, and can be undone the same way.
- **Your own codebook**, made in the app fresh or from the themes found: definitions, when to use each code and when
  not, the words it is matched by, checked examples, and *Try it* without AI. Made from the themes, each code gets a
  short name from the theme's words, as specific as your documents need (0.16.1). Labels follow renames and merges.
  **Can change results** for codebooks you change: the AI reads when to use a code, and a removed code's labels stop
  counting until it comes back.
- **Quicker on large projects**: several documents read at once, a glossary and search that keep what they read.
  Cannot change results.

How it works: [notes, the research log and earlier versions](docs/manual/notes-and-log.md) and
[your own codebook](docs/manual/codebooks.md) in the manual. Every release, with what was not tested:
[CHANGELOG.md](CHANGELOG.md).

## How to cite ENLENS

Cite the repository and name the version you used (it is at the top of every *Settings* tab). For version 0.15.0,
for example:

> ENLENS, version 0.15.0. https://github.com/dvaud/claim_checker_demo

Every Excel download ends with *How these results were made*: the models, their versions and the prompt versions
behind each answer. It belongs in your methods section or supplementary material.

## Privacy and your documents

Your documents, results, judgements and settings stay on your computer. With Claude (the default), only the passages
inside the AI's tasks are sent to Anthropic, through Claude Code on your own Claude plan (or the Claude API, when a
shared installation switched it on), and only from documents marked *Claude may read it*; ENLENS records every passage
it sends (*Sent to Claude* on the *Documents* page). Claude Code, as ENLENS starts it, has no tool that can open your
files, so those passages are all it sees. To keep a document from Claude, mark it *Only a local AI* or *No
AI*. To keep everything on the computer, choose *A model on this computer* in *Settings → AI*, or put
`ENLENS_LOCAL_ONLY=1` before `sh` in the install line, which removes every cloud option for good. Apart from the AI you chose
and looking for a new version on GitHub, ENLENS sends nothing anywhere and has no telemetry; bringing in a colleague's
work only reads the file they sent you. The details, and what Anthropic's terms say for each plan, are in
[Privacy](docs/manual/privacy.md) in the manual.

## Documentation

- [The manual](docs/MANUAL.md): a one-page start, then a short page per task: the app, Claude Code, local models,
  privacy, the command line and the SDG pack.
- [Which model each task needs](docs/MODEL_CHOICE.md): how the models are chosen, and (once made) the runs on the pilot.
- [The app's HTTP API](docs/API.md), for scripts and other programs.
- Add-ons: [building an app on ENLENS](docs/EXTENDING.md), with an add-on's own [manual](docs/ADDON_MANUAL.md) and
  [API](docs/ADDON_API.md).
- [What changed in each release](CHANGELOG.md), with the defects fixed, and [what comes next](docs/ROADMAP.md).

## For developers

A git copy, the tests, the layout of the code and how a release is made: [docs/DEVELOPING.md](docs/DEVELOPING.md).
