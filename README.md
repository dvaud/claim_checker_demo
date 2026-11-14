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

<!-- new-in:start (written by `python tools/release.py prepare`: change the changelog entry, not this) -->
## New in 0.19.0rc1: Your own drafts, a concept map, codebooks from other programs, and a university drive for the team

- **Your own working documents.** Keep your drafts and notes in the project beside the corpus: in *Documents*, open a row → *Role* → *Mark as my working document*, or use the same button on the document's page.
- **A concept map.** *Concepts* has a second tab, *Map*: the concepts mentioned in the most passages, joined by a line when the documents mention two together more often than by chance (pointwise mutual information, not…
- **Bring in a codebook from NVivo, ATLAS.ti or MAXQDA.** *Codes* › *Codebooks* › *New codebook* › *From NVivo, ATLAS.ti or MAXQDA* takes a REFI-QDA codebook (`.qdc`), or the codebook of a REFI-QDA project (`.qdpx`), and makes it a codebook of your own.
- **A code's definition drafted from its examples.** In the codebook editor, open a code with two examples or more and press *Draft from the examples*: the AI reads only the passages that hold those examples (with the code's name and group) and drafts…
- **Count non-scientific documents in one check.** When newspapers, blogs or company brochures are the material a hypothesis is about, they are its evidence.
<!-- new-in:end -->

How it works: [Work together](docs/manual/together.md) in the manual. Every release, with what was not tested:
[CHANGELOG.md](CHANGELOG.md).

## How to cite ENLENS

Cite the repository and name the version you used (it is at the top of every *Settings* tab). For version 0.15.0,
for example:

> ENLENS, version 0.15.0. https://github.com/dvaud/claim_checker_demo

Every Excel download ends with *How these results were made*: the models, their versions and the prompt versions
behind each answer. It belongs in your methods section or supplementary material.

## Privacy and your documents

Your documents, results, judgements and settings stay on your computer unless you choose to share them with colleagues.
With Claude (the default), only the passages
inside the AI's tasks are sent to Anthropic, through Claude Code on your own Claude plan (or the Claude API, when a
shared installation switched it on), and only from documents marked *Claude may read it*; ENLENS records every passage
it sends (*Sent to Claude* on the *Documents* page). Claude Code, as ENLENS starts it, has no tool that can open your
files, so those passages are all it sees. To keep a document from Claude, mark it *Only a local AI* or *No
AI*. To keep everything on the computer, choose *A model on this computer* in *Settings → AI*, or put
`ENLENS_LOCAL_ONLY=1` before `sh` in the install line, which removes every cloud option for good. Apart from the AI you
chose
and looking for a new version on GitHub, ENLENS sends nothing anywhere on its own and has no telemetry. Working with
colleagues, only what you share goes to them, with the documents: in a file you send, or in a folder your team shares
that you choose, which holds the documents' text and files and only what you share of your own work, so whoever can
open that folder (and the cloud service behind it) can read it; you can keep documents marked *Only a local AI* or *No
AI* out of it ([what it holds](docs/manual/privacy.md#working-together)). The details, and what Anthropic's terms say
for each plan, are in [Privacy](docs/manual/privacy.md) in the manual; for an ethics application or a data protection
assessment, [docs/PRIVACY.md](docs/PRIVACY.md).

## Documentation

- [The manual](docs/MANUAL.md): a one-page start, then a short page per task: the app, Claude Code, local models,
  privacy, the command line and the SDG pack.
- [How ENLENS works, for a methods section](docs/METHODS.md), and [what leaves the computer, for an ethics
  application](docs/PRIVACY.md).
- [Which model each task needs](docs/MODEL_CHOICE.md): how the models are chosen, and (once made) the runs on the pilot.
- [The app's HTTP API](docs/API.md), for scripts and other programs.
- Add-ons: [building an app on ENLENS](docs/EXTENDING.md), with an add-on's own [manual](docs/ADDON_MANUAL.md) and
  [API](docs/ADDON_API.md).
- [What changed in each release](CHANGELOG.md), with the defects fixed, and [what comes next](docs/ROADMAP.md).

## For developers

A git copy, the tests, the layout of the code and how a release is made: [docs/DEVELOPING.md](docs/DEVELOPING.md).
