# Privacy and data protection

What ENLENS sends off the computer it runs on, when, to whom, and what it never sends. Written for ethics
applications and data protection impact assessments (DPIAs). For the same facts written for users, see
[Privacy: what leaves your computer](manual/privacy.md). How the methods work is in [METHODS.md](METHODS.md).

Each statement names the module of `src/enlens_claims/` or the manual page it can be checked against. It describes
ENLENS as of version 0.18.1.

## Who processes what

ENLENS is a program the researcher installs and runs on their own computer. It is a small web server that listens on
`127.0.0.1` only by default (`--host` can open it to the network, which nobody needs for ordinary use), with a key per
run (`gui/server.py`); the page loads nothing from the internet. ENLENS's developers
run no service of their own, and the app sends them nothing: there is no telemetry, no account and no analytics.
Releases are downloaded from GitHub ([below](#other-online-services-not-ai)).

| Party | Role | What it receives |
| --- | --- | --- |
| The researcher (and their institution) | Decides what is processed, and how | Everything: the projects stay on their computer |
| Anthropic | Runs the Claude models, when the researcher uses Claude | The passages and text inside the AI tasks Claude answers, from documents Claude may read ([below](#what-goes-to-claude)) |
| A model server on the computer (Ollama, LM Studio and others) | Runs a local model | The text of the tasks it answers; it stays on the computer |
| The team's shared folder, or its storage space at Backblaze, Cloudflare or the institution's drive (WebDAV) | Carries the work a team shares | Only when the researcher sets one up ([Working together](#working-together)) |
| Crossref | Answers a retraction lookup | DOIs, only when the researcher asks ([Other online services](#other-online-services-not-ai)) |
| GitHub | Hosts ENLENS's releases | A request for the latest version ([Other online services](#other-online-services-not-ai)) |

## In short

- **Projects stay on the computer.** The documents, their text, the database, judgements, notes, the research log
  and settings are kept in the data folder (`~/enlens` or `ENLENS_HOME`).
- **Each document has an AI setting**: *Claude may read it*, *Only a local AI*, or *No AI*. ENLENS enforces it in
  code, at the point where every AI task passes (`access.py`).
- **Document text leaves the computer by three ways only**: a Claude route, from documents marked *Claude may read
  it*, each passage written to a ledger as it leaves (`access.record_sent`); a model or embedding server the
  researcher set up at another computer's address, from the same documents; and the team's shared folder or storage
  space, once the researcher sets one up.
- **The whole installation can be made local-only** (`--local-only`): no document text then goes to Claude
  ([Switching everything off](#switching-everything-off)).

Nothing is sent to Claude until the researcher runs a feature that uses the AI. With Claude Code, the default route,
the work then waits until the researcher starts Claude Code
([Start Claude Code](manual/claude-code.md#start-claude-code)). In the app, the first documents added to a new
project ask who may read them, with nothing preselected (`access.default_chosen`). Documents added from the command
line or the connector without a setting take the project's default, which is *Claude may read it* until a default is
chosen (*Only a local AI* on a local-only installation; `access.default`).

## Each document's AI setting

Every document has one of three settings (`access.LEVELS`; [Who may read each document with
AI](manual/privacy.md#who-may-read-each-document-with-ai)):

| Setting | Who may read its text |
| --- | --- |
| *Claude may read it* (`cloud`) | The chosen route: Claude Code, the Claude API, or a model server |
| *Only a local AI* (`local`) | A model server on this computer, or a person |
| *No AI* (`none`) | A person only |

It is set when documents are added (one answer per batch), per document on the Documents page, or in a `manifest.csv`.
An optional note (*Why*, for example "publisher licence") is kept with it. A document can also have a cap: once Claude
has read a given share of its text, it is treated as *Only a local AI* for new tasks (`documents.ai_budget`).

**How it is enforced** (`access.py`, `tasks.py`; [How it is enforced](manual/privacy.md#how-it-is-enforced)):

1. Each AI task is labelled with the most restricted setting of every document it names, at any depth of its
   contents (`access.label_payload`).
2. Before any model is asked, the setting is worked out again from the task's contents, and a task is refused when its
   setting does not allow that model (`access.require`). A *No AI* task is refused on every route; an *Only a local
   AI* task is refused on every route that leaves the computer.
3. Claude Code's queue hands out only tasks Claude may read; the file queue writes only those
   (`tasks.export`).
4. A model server counts as "on this computer" only when its address is `localhost` or a loopback address
   (`access.on_this_computer`). A model server at any other address may read only documents marked *Claude may read
   it*.

The rule is code, not an instruction in a prompt. A feature that forgot to split its work would be stopped by the
guard before anything is sent.

## What goes to Claude

Claude is reached by three routes (`routing.ROUTE_NAMES`, `routing.OFF_COMPUTER`):

| Route | Account | When text leaves |
| --- | --- | --- |
| **Claude Code** (the default) | The researcher's own Claude plan. ENLENS never sees the login | When a Claude Code helper takes a batch of tasks from ENLENS's queue (`taskqueue.py`) |
| **The Claude API** | A key (for example a team's), only after *Allow cloud models* is switched on (`home.py` `allow_cloud`) | When a task is sent (`tasks._send`) |
| **A Claude chat with the connector** | The researcher's own Claude account, in the Claude app or Claude Code | When the connector's tools return results to the chat (`mcp_server.py`) |

**What a task holds.** Depending on its kind (`prompts.py`): the hypothesis or claim, the search words, the excerpts
and the 300 characters before each one (to resolve words such as "it"), each document's title and page, a codebook's
codes, pairs of glossary terms with short passages where each occurs, the passages that best represent a theme,
consecutive passages of one document (references), the passages that hold a code's examples with the code's name and
group (a draft definition, `codedefine.py`), and, when a person asks for an excerpt to be read again, their
comment. A document linked to a bibliography entry is titled by that work's title
(`bibliography.py`). Tasks of documents marked *Only a local AI* or *No AI* are never among them. A code's
definition, *when to use it* and *when not* go with every label task of its codebook, whatever document it labels: a
definition the local model drafted from documents marked *Only a local AI* does too once it is kept, so the editor
says to rewrite it if it gives away what those documents say.

**What a Claude chat sees through the connector.** The project names and the path of the projects folder; document
titles, pages and counts, except that a document marked *No AI* is shown as *Restricted document 3*, because a title
can name a person (`access.restricted_titles`); the hypotheses of the project's checks and their answers, except a
check started from words of a document marked *Only a local AI* or *No AI* (a working document's *Check against the
corpus*), which it neither lists nor opens (`docrole.kept_here`); and the excerpts, search lines and concept details of documents Claude may read. Text of documents marked *Only a local AI*
or *No AI* is reported as counts only, and what a model wrote after reading such text is left out. Excerpts are shown
without the text before them. The connector reads files on the computer when asked to add sources; it sends nothing
of them except what its tools return.

**The Claude Code run ENLENS starts** works in an empty folder away from the projects, has no tool that reads, writes
or searches files, runs commands or browses, and loads none of the researcher's own Claude Code settings, hooks,
instructions or other plugins. All it can see are the tasks ENLENS gives it ([How it is
enforced](manual/privacy.md#how-it-is-enforced)).

**The ledger.** Every passage that leaves for Claude, through any of the three routes, or in the file queue, is written
to the table `ai_sent` at that moment, with the passage, the document, the route, the feature, the task and the time;
for the queue and the API, the passage shown before each excerpt is recorded too (`access.record_sent`). The
Documents page shows the share of each document sent; *Settings → Technical → What was sent to Claude* downloads the
whole list as CSV ([What Claude has read](manual/privacy.md#what-claude-has-read)). Changing a document's setting
applies to everything not yet answered; what Claude has already read stays in the results and the ledger.

**Agreement between routes and model tests** send their samples through the same guard and ledger
(`access.sending`), and are asked only when the researcher presses the button.

## Local models

A model served on the computer (Ollama, LM Studio, llama.cpp, Jan, vLLM) keeps every word on it
([A model on your own computer](manual/local-models.md)). It may read documents marked *Claude may read it* or *Only a
local AI*. Requests go to its address on this computer; nothing about them is sent elsewhere.

Points for an assessment:

- **A model server on another computer** (an address that is not `localhost`) is treated like a cloud route for the
  settings: it may read only documents marked *Claude may read it* (`access.backend_levels`). Passages sent to it are
  **not** written to the ledger, which records Claude routes and the file queue only.
- **Search by meaning** sends passages to the embedding server. An embedding server on another computer receives
  neither passages of documents marked *Only a local AI* or *No AI* nor glossary terms found only in them
  (`embed.py`, `terms.py`); it does receive the text of searches.
- **Getting a model** downloads Ollama's installer from ollama.com and a model from Ollama's library, only when the
  researcher presses the button. No document is sent.

## What never leaves the computer

- The text of documents marked *Only a local AI* or *No AI*, to Claude or to a model server on another computer, in
  any feature, words selected from them and checked against the corpus included: such a check is read by a local
  model only, or, from a document marked *No AI*, by no model (`docrole.origin_floor`). (A team's shared folder or storage space does receive their text and files, unless the switch
  described [below](#working-together) keeps them out.)
- The project's database (`enlens.sqlite`) as a file.
- The answers ENLENS keeps so as not to ask the AI again (`ai_cache`), the search index, the glossary, embeddings,
  earlier versions (*History*) and settings: none of them goes into a zip for a colleague, the shared folder or the
  storage space (`sharing._LOCAL_TABLES`, `sync.common.LOCAL_ONLY`). The kept answers are not tied to one document:
  removing a document leaves them (they answer only the same text again), *Remove everything* clears them, and a
  project that came from a colleague arrives without theirs.
- The researcher's private work, until they press *Share* ([Working together](#working-together)).
- Keys and secrets ([Keys and secrets](#keys-and-secrets)).
- Paths on the computer, in anything shared.
- Zotero data: ENLENS reads it from the Zotero app on this computer (`127.0.0.1`, port 23119), never from Zotero's
  servers, and never changes it (`bibliography.py`).
- Text recognition of scanned pages: Tesseract runs on the computer (`ingest.py`).

## Other online services (not AI)

| Service | What is sent | When | Under `--local-only` |
| --- | --- | --- | --- |
| **Crossref** (`api.crossref.org`), retractions and corrections | DOIs only, with `User-Agent: ENLENS/<version>`; no name, e-mail or project name. A work with a document marked *No AI* is not looked up | Only when the researcher presses *Check for retractions*, or runs `enlens retractions --check` | Off: nothing is sent |
| **GitHub** (`api.github.com`, `github.com`), updates | A request for the latest release, with `User-Agent: enlens-update`; no project data | When a page of the app opens, every two minutes while it is open (one look shared by open tabs), and on *Check for updates*; a download only on *Update* | Not switched off |
| **Anthropic's installer** (`claude.ai`) | A download of Claude Code | Only when the researcher confirms installing it in *Set up Claude* | Refused |

Sources: `retractions.py`, `update.py`, `gui/server.py` (`get_update`), `claude_setup.py`;
[Retractions and corrections](manual/bibliography.md#retractions-and-corrections),
[Update](manual/install.md#update). Like any web request, each of these shows the service the computer's network
address.

*Report a problem* opens a GitHub form in the browser; *Copy technical details* copies the ENLENS version, how it was
installed, the system, the AI route and the update channel, never a path, project, document name or key
([Reporting a problem](manual/settings.md#reporting-a-problem)).

## Working together

Nothing goes to a colleague until the researcher sends it ([Working together](manual/privacy.md#working-together)).
Each item (a check, a set of themes, a codebook, a note) is private until its owner presses *Share*.

**Files sent by hand.** *Send what you shared* makes a zip with the documents and what was shared, and nothing private,
not even in deleted parts of the database file (`sharing.py`). *Download the whole project* holds private work too and
is meant for moving to another computer of one's own.

**A shared folder** (OneDrive, Dropbox, a network drive) is written and read on the computer; the folder's service
carries it, under the institution's terms with that service ([What goes into the shared
folder](manual/privacy.md#what-goes-into-the-shared-folder)).

- *Goes there:* the documents' text and original files, who may read each with AI, the bibliography (without file
  locations), the AI's work on the documents and people's reviews of it, the research log's entries about the
  documents, proposals and roles, the person's name and ENLENS version, and the items shared, whole. A shared check
  carries the words its excerpts quote, the judgements under each person's name and the AI's answers.
- *A switch keeps documents marked Only a local AI or No AI out:* their text and files stay on the computer. Shared
  items about them still carry the words their excerpts quote, notes, judgements and the documents' titles.
- *Never goes there:* private items, checks still in progress, earlier versions, the search index and glossary,
  settings, the database itself and paths. A round that would write anything not shared writes nothing. ENLENS
  refuses a shared folder that contains the project or its own data folder.
- *Who can read it:* anyone with access to the folder. The files are ordinary zip files, neither encrypted nor
  signed ([Who can read the folder](manual/privacy.md#who-can-read-the-folder)).

**A storage space** of the team's own, at Backblaze (B2), Cloudflare (R2) or in a folder of the institution's drive
over WebDAV (SURFdrive, SURF Research Drive, a Nextcloud; `sync/webdav.py`), holds the same things as a shared folder,
sealed (`sync/seal.py`, `sync/space.py`; [Through a storage
space](manual/privacy.md#through-a-storage-space-of-your-teams-own-0180rc2)):

- *Encrypted before it leaves:* each file with the project's key (AES-256-GCM, a fresh 96-bit nonce per file), and
  signed with its writer's own key (Ed25519). A copy takes in a file only when it is signed by the member whose part
  of the space it is in; anything else is set aside.
- *What the company can see:* how many files there are, their sizes and when they change; the team's roster (random
  member identifiers, public keys and dates, signed but not encrypted); nothing of the files' contents, and no names
  of people or documents. Readings and original files are stored under a keyed hash of their names.
- *Where:* ENLENS makes Cloudflare's space in its EU jurisdiction and warns when a Backblaze account is not in an EU
  region (the region is chosen when the account is made) (`sync/r2.py`, `sync/space.py`).
- *Invite links* carry the keys to the space after their `#`, with the project's name and the inviter's name. They
  must be sent privately, work once, and can be withdrawn before use
  ([Inviting a colleague](manual/storage-space.md#inviting-a-colleague)).
- *Removing a member* deletes their storage keys and replaces the project's key for those who stay; what they already
  had stays with them. In a drive it stops sharing the folder with them where ENLENS can (a share it made, or one the
  drive lists for their known account); where it cannot, they can still read and write the folder until the owner
  stops sharing it in the drive's website, and the Team tab says so until then. The person whose drive holds the
  folder keeps it: the team moves to another folder to leave them out.
- *In a drive* (WebDAV): each person signs in with their own account and an **app password**, which opens their whole
  account at the drive, not only the team's folder. ENLENS reads the names of the folders at the top of the drive at
  set-up (to choose a free name) and when joining (to find the shared folder). The drive's administrators see the
  folder's name, which holds the project's name (`ENLENS - <project>`), and the accounts it is shared with; at
  Backblaze and Cloudflare they see random member identifiers instead. Requests go over HTTPS only, with the
  certificate checked; redirects are never followed; an address with a user name or password in it is refused. After
  the drive refuses the app password, ENLENS asks it nothing until a new one is entered. XML answers with a DOCTYPE are
  refused, and every answer is read up to a limit, at every kind of storage space.

**Settings across copies.** Anyone may make a document stricter, and it holds in every copy as soon as it reaches
it. A looser setting
never takes effect on a computer without its user's own click ([The owner and who may read with
AI](manual/privacy.md#the-owner-and-who-may-read-with-ai)). Each copy enforces the settings on its own computer:
what a colleague's copy sent to Claude before a stricter setting reached it is outside this copy's control, and comes
in with their work, with a count of what Claude read there.

## Keys and secrets

- **The storage space's keys** (the project's key, each member's own keys, the storage service's keys, a drive's app
  password) are kept in the system's keychain: macOS Keychain, Windows Credential Manager, or `secret-tool` on Linux. Where none can be used,
  they are kept in files in ENLENS's folder readable by the user only (`keychain.py`). Never in a project, a zip, the
  shared folder or the space.
- **A Claude API key**, if saved, is kept in `credentials.json` in the data folder, readable by the user only, or
  read from `ANTHROPIC_API_KEY` (`home.py`). It is never in a project or a move file.
- **Claude Code's login** is Claude Code's own; ENLENS never sees it.
- **The app's key** for the running server is kept in a file only the user can read (`app-token-<port>.json`).
  Whoever has the link with that key can open ENLENS while it runs ([What goes
  where](manual/privacy.md#what-goes-where)).

## Records for an audit

- **The ledger of what was sent to Claude**: per passage, document, route, feature, task and time, downloadable as
  CSV ([What Claude has read](manual/privacy.md#what-claude-has-read)).
- **The research log**: dated entries the app writes by itself (documents added or removed, who may read a document
  with AI, checks made or removed, codebooks changed, a colleague's work brought in), and entries of the researcher's
  own. The app's entries cannot be removed (`researchlog.py`; [The research log](manual/notes-and-log.md#the-research-log)).
- **How these results were made**, at the end of every Excel download: the models, routes, prompt versions and ENLENS
  versions behind the results ([What every answer records](manual/models.md#what-every-answer-records)).
- **The raw answer of every model**, with its model, route and time, in the project's `results` table.

## Switching everything off

Whoever installs ENLENS can remove every cloud option for good, with `enlens-gui --local-only`, the environment variable
`ENLENS_LOCAL_ONLY=1`, or an empty file named `local_only` in the data folder (`home.local_only`;
[For whoever installs ENLENS](manual/settings.md#for-whoever-installs-enlens)). Then:

- every document counts as *Only a local AI*, and no document can be set to *Claude may read it* (`access.levels`,
  `access.set_documents`);
- the Claude API and Claude Code are hidden and refused, ENLENS never starts Claude Code, its plugin is not written
  (`claude_setup.py`), and the queue hands out no tasks (`taskqueue.py`);
- the Crossref lookup is off.

Two things are not switched off: the update check with GitHub, which sends no project data, and the connector program
itself if someone adds it to a Claude app. Through the connector a chat could still see project names, document
titles and counts, but no document text, since every document counts as *Only a local AI*. Do not add the connector
on a local-only installation.

## What ENLENS cannot promise

- **Anthropic's handling of the text it receives.** Retention, use for training, the location of processing and
  sub-processors are set by Anthropic's terms for the account used (a personal Claude plan, a Team or Enterprise
  plan, or the API), not by ENLENS. *Set up Claude* and *Settings → AI* show which terms apply to each kind of plan
  and link to Anthropic's own page with the date it was checked ([Your Claude account and
  licences](manual/privacy.md#your-claude-account-and-licences)). Check Anthropic's current privacy policy, terms and
  the account's data settings for the application; mark documents that must not reach Anthropic *Only a local AI*.
- **The shared folder's service** (OneDrive, Dropbox, a network drive), **the storage company** and **the
  institution's drive** and its administrators, under the institution's or team's own agreement with them. A service
  may keep earlier or deleted versions for a while.
- **Copies on colleagues' computers.** What a colleague has brought in stays with them after it is unshared.
- **The computer itself.** Projects are only as private as the data folder; on a computer other people use, keep it in
  the user's own folder.
- **Licences of the documents.** Whether a licence allows text and data mining by an outside service is for the
  researcher and their library to check.
- **Local models are not checked** for what they do beyond answering: choose a model server you trust.

## For an ethics application or a DPIA

A short description that can be adapted:

> Analysis used ENLENS [version], which runs on the researcher's computer and keeps all documents and results there.
> Each document was assigned an AI setting. Documents containing personal data [were marked "No AI" / "Only a local
> AI" and were read only by the researcher / by a language model running on the researcher's computer]. [For
> documents marked "Claude may read it", only the passages selected for each task were sent to Anthropic's Claude
> models via [Claude Code on a [plan] account / the Claude API], under Anthropic's [commercial / consumer] terms.]
> Every passage sent was logged by the software, and the log is kept with the project. [Collaboration used a storage
> space at [Backblaze / Cloudflare / the institution's drive (SURFdrive, a Nextcloud)] in the EU, with files encrypted (AES-256-GCM) and signed (Ed25519) before upload;
> the storage provider holds no keys.] [The installation was set to local-only, so no document text could be sent to
> a cloud model.]
