# ENLENS local app: HTTP API

The app (`enlens-gui`) is a small HTTP server on `127.0.0.1` (default port 8765) that serves one static page
(`src/enlens_claims/gui/static/`) and a JSON API under `/api/`. Everything stays on the computer; text goes only to
the model service chosen in Settings.

## Rules

- **Token.** Every API call sends the run's token as the header `X-Enlens-Token`; without it, or with an old one,
  401. The endpoints a plain link opens (the exports `…/export.csv|json|xlsx|zip`, the original file
  `…/documents/<id>/file`, the page pictures `…/pages/<n>.png`, and the 0.7 downloads: search, profile and themes
  exports, highlighted copies, the FlexiConc file) also accept `?token=`: the page uses it for an `<img>` and for
  "open the PDF at this page", which `fetch` cannot do.
- **How a client gets the token** (0.17.2). `GET /` never carries it, whatever the `Host` (any account on the computer
  could fetch it); `index.html` has `{{ENLENS_VERSION}}` and `{{ENLENS_RUN}}` (a random id of this run, not a
  secret) filled in. The app opens `http://127.0.0.1:<port>/#token=<token>` in the browser (and prints it, unless
  started from the icon, whose output goes to a log). The page reads it from `location.hash`, keeps it in
  `sessionStorage` and takes it out of the address bar; a tab without it asks the app's other tabs in the same browser
  (a `BroadcastChannel` named `enlens-token`) and keeps the first answer the API accepts. A program on this computer
  reads it from `app-token-<port>.json` in the data folder: `{"url", "port", "pid", "token"}`, written whole when
  the app starts (mode 0600 on macOS and Linux; on Windows the user's profile folder protects it, and with a data
  folder outside the profile the file is in `%LOCALAPPDATA%\ENLENS`) and removed when it stops (`gui/launcher.py`
  `token_path`, `read_token`, `open_link`). On Linux the browser is given a file `open-<port>.html` beside it (also
  0600) that sends it on to the link, so the token is on no program's command line (`launcher.browse`). Every start has a new token, except a restart after an update
  (below).
- **Host.** Requests must name `127.0.0.1:<port>`, `localhost:<port>` or `[::1]:<port>` in `Host`; requests carrying an
  `Origin` other than their own `Host` are refused (403).
- **Network mode** (`enlens-gui --host 0.0.0.0`): `Host` may also be an IP address of the computer (never a domain
  name: that could be DNS rebinding). As on `127.0.0.1`, the token comes in the link printed in the terminal,
  `http://<address>:<port>/#token=<token>`.
- **Content Security Policy** on the page: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
  img-src 'self' data:; font-src 'self' data:; connect-src 'self'`. No inline `<script>`, no external resources.
- **Static files**: `GET /static/<file>` serves files from the `static/` folder (also `/<file>` with an extension).
  Any path without an extension returns `index.html` (use hash routing anyway: `#/check`, `#/h/<id>` …).
  0.13.5: `GET /static/site.css` is the installation's own `site.css` followed by each add-on package's;
  `GET /static/addons/<add-on>/<file>` serves an add-on package's page files (docs/EXTENDING.md).
- **JSON in, JSON out.** Request bodies are JSON objects (`Content-Type: application/json`), except uploads (raw bytes).
- **Errors**: status 4xx/5xx with `{"error": "plain-language message", "kind": "request" | "backend" | "internal"}`.
  `kind: "backend"` (HTTP 502) means the model service is the problem (not running, model missing, key wrong): offer
  a link to Settings. 401 means the token is missing or from an earlier run: open ENLENS from its icon (or run
  `enlens-gui`).
- **Jobs.** Long work returns `{"job": Job}` at once; poll `GET /api/jobs/<id>` (about every 500 ms while
  `state` is `queued` or `running`). Jobs that use the chat model run one at a time; others wait in `queued`.
  0.17.0: jobs of one project that change the same things wait their turn in `queued` too, with `waiting_for` saying
  for which job (see Jobs below).
- Times: hypotheses and documents carry ISO 8601 UTC strings (`created_at`); jobs carry Unix seconds.
- Ids are opaque strings. URL-encode project names (they may contain spaces).

## Statuses

A *hypothesis* is checked as one claim, or (with `decompose`) split into 2–5 *parts* that must all hold; each part
is a claim with its own check. Each passage read gets a grade or none:

| grade (`verdict`) | meaning |
| --- | --- |
| `supports` | the passage states the claim |
| `partially_supports` | it states a necessary part; one inference remains |
| `refutes` | it states the opposite / no such effect |
| `null` | read, nothing relevant ("not enough information") |

Grades count towards a status only when `confidence >= threshold` (default 0.6, a user setting; every read endpoint
takes `?threshold=`). Claim and hypothesis statuses (texts and explanations are in `GET /api/state` → `statuses`):

| status | text in the app |
| --- | --- |
| `supported` | Supported by your documents |
| `partially_supported` | Partly supported |
| `contested` | Mixed evidence (support and contradiction both present) |
| `contradicted` | Contradicted by your documents |
| `unsupported` | No evidence found (in the excerpts read) |
| `uncertain` | Only uncertain evidence: excerpts were judged, but none at or above the threshold |
| `no_passages` | Nothing in your documents matched |
| `not_checked` | Not finished yet; *Waiting for your judgement* (`status_text`) when every excerpt read waits for the person |
| `failed` | The check did not work |

0.14.3: an excerpt no model may read (`read_by: "you"`) counts towards no status until the person judges it (before,
it counted as "not about the hypothesis", so a check of *No AI* documents said "No evidence found"). A round whose
main part failed is failed, even when its other excerpts were read by the local model or wait for the person, and
none of the AI's judgements in it count anywhere (status, `balance`, `who`, `counted`, the Results list, the map).

Texts are in `GET /api/state` → `statuses` (`text`, `help`, and `next`: what a reader can do next).
A person can overrule the AI's judgement of any excerpt read (`PUT …/judgements/…`, below); their judgement replaces
the AI's in every status and count, always counts whatever the threshold, and is shown beside the AI's.
`status_any` is the same status counting every grade whatever its confidence (show it when it differs: "if the
uncertain judgements counted too: …"). `balance` = `{docs_supporting, docs_partly, docs_refuting, docs_both,
docs_counted, excerpts_uncounted, lean}`: a document counts as supporting if one of its counted excerpts supports, as
partly supporting only if none supports, as refuting if one refutes (so it can be on both sides: `docs_both`);
`docs_counted` counts each document once. `lean` runs from -1 (only contradicted) to +1 (only supported), `null`
when nothing was graded. `who` lists the same documents by side (see the hypothesis endpoint).

## Endpoints

### App state and settings

`GET /api/state` →
```json
{"version": "0.7.0", "home": "/Users/me/enlens",
 "settings": {"backend": "auto", "allow_cloud": false, "anthropic_model": "claude-opus-5-5",
              "ollama_url": "http://localhost:11434", "ollama_model": "", "openai_url": "http://localhost:1234/v1",
              "openai_model": "", "num_ctx": "auto", "think": "off", "think_budget": 1500, "embed_backend": "ollama", "embed_model": "",
              "embed_url": "", "threshold": 0.6, "k": 8, "per_doc": 2, "expand": true, "decompose": false,
              "second_pass": false, "project": "Demo", "benchmark_reference": "", "second_model": "",
              "ocr": "auto", "ocr_lang": "eng"},
 "backend_label": "Ollama · qwen3:8b",
 "backend_labels": {"auto": "Local model (automatic)", "ollama": "Ollama", "openai": "Local OpenAI-compatible server",
                    "anthropic": "Claude API (cloud)", "baseline": "Offline demo"},
 "projects": [{"name": "Demo", "linked": false, "documents": 3, "hypotheses": 3, "ok": true, "path": "…"}],
 "local_only": false,
 "context": {"setting": "auto", "num_ctx": 8192, "needed": 6171, "thinking_allowance": false},
 "ocr": {"available": true, "missing": [], "languages": ["eng", "nld"]},
 "project": "Demo",
 "key": {"session": false, "env": false, "stored": false},
 "statuses": [{"status": "supported", "text": "Supported by a source", "help": "…"}, …],
 "jobs": [Job summaries of queued/running jobs],
 "brand": {"name": "ENLENS", "tagline": "explore and check your documents", "welcome_title": "…", "welcome_text": "…",
           "description": "…", "logo": "/static/logo.svg"}}
```
`brand` (0.13.5): the app's name and words, from `static/brand.json` and any add-on's `BRAND` (docs/EXTENDING.md).
0.13.6: an add-on may add keys of its own (its `state(app)`); they never replace one of these. Its routes are documented
in `docs/ADDON_API.md` and come after ENLENS's own (docs/EXTENDING.md). `GET /api/projects/<p>/overview` may carry an
add-on's counts the same way, and a hypothesis's result and history rows carry `origin` and `origin_id` (where it
comes from: `batch`, an add-on's own kind, or none).
`backend` values: `auto` (first local server found: Ollama, then LM Studio, llama.cpp, Jan, vLLM), `ollama`,
`openai` (an OpenAI-compatible local server at `openai_url`), `anthropic` (cloud; allowed only when `allow_cloud`),
`baseline` (offline demo, word overlap). Text leaves the computer only with `anthropic`.

New in 0.6:
- `num_ctx`: `"auto"` (the default) or a number. With `"auto"` the app uses the smallest of 8,192, 12,288, 16,384
  and 32,768 tokens that holds the largest task the settings can produce (the check prompt, `k` excerpts of 1,100
  characters with their headers, the answer, and 4,096 tokens of reasoning unless `think` is `off`). It stays the
  same between requests (Ollama reloads the model when it changes), and leaves the most memory to the model.
  `context` in the state says what that is now: `num_ctx` (the length used), `needed` (the estimate), `setting`;
  with a fixed number, `too_small: true` when the estimate is larger. Show it under *Advanced*. Settings files of
  0.5 hold the old default 16384: it is read as `"auto"`.
- `second_pass` (default `false`): sort the best candidates again by how closely they word the hypothesis (see
  "Checking"). It did slightly worse on the pilot, so it is off; it is an *Advanced* option.
- `second_model`: a second local chat model (on the same server) for "Ask a second AI model" (see "Results").
- `think` (0.6.1): `"off"` (the default), `"judging"` (reason only when judging excerpts: checks, re-reads and the
  second model; not when splitting a hypothesis or proposing search words), `"on"`, or `"default"` (the model's
  own default). `think_budget` (default 1500; 0 = no limit, else 256–16,384): reasoning tokens after which the
  model is stopped and asked to answer at once, with its reasoning so far as notes (Ollama only). The model report in
  a job's `progress.model` then has `budget` and `budget_reached`, and its `stats` `thinking_tokens` and
  `budget_reached`.
- `ocr` (`"auto"` | `"off"`) and `ocr_lang` (Tesseract languages joined by `+`, e.g. `"eng+nld"`): reading scanned
  PDF pages. `ocr` in the state: `available` (Tesseract and the Python parts are installed), `missing` (what is
  not: `"tesseract"`, `"pypdfium2"`, `"pillow"`), `languages` (installed Tesseract languages).

New in 0.7:
- `seed` (default 42; 0–2,147,483,647): sent with every model request (Ollama and OpenAI-compatible servers), with
  temperature 0, so the same input gives the same answer where the server honours it (`POST /api/servers/repeatable`
  tests that). Recorded with every answer.
- `profile_framework` (default `"sdg"`, the 169 targets; `"sdg_goals"` for the 17 goals, or a codebook of the
  project): the codebook of the Profile page, the Codes panel and the keyword pass run when documents are added.
- `themes_k` (default 20; 2–60): how many themes a new set looks for.
- Adding documents (`POST …/ingest`) now ends with two phases, `glossary` and `codes`: the term index and the keyword
  pass of `profile_framework`. Their results are in the job's `result.glossary` and `result.codes`.

When no model is chosen, or the chosen Ollama model is not installed, the app picks one: a chat model the server
already holds in memory first (so nothing extra is loaded), then the most recently pulled one, then the first
in alphabetical order. `POST /api/servers/test` then says so in `warning`.

`PUT /api/settings` body: any subset of `settings` → `{"settings": {...}, "backend_label": "..."}`.
400 with a message for invalid values (e.g. `backend: "anthropic"` while `allow_cloud` is false, or any cloud setting
while `local_only` is true). `project` sets the current project.

`local_only` (in the state) is true when whoever installed the app switched cloud models off for good
(`enlens-gui --local-only`, `ENLENS_LOCAL_ONLY=1`, or a file `local_only` in the data folder): hide the cloud option.

`POST /api/settings/key` `{"key": "sk-ant-…", "remember": false}` → `{"key": {...}}`. Without `remember` the key is
kept in memory for this run only. `DELETE /api/settings/key` forgets both. 403 when `local_only` is true (0.11.1).

`POST /api/quit` → `{"stopping": true, "jobs_stopped": n}`: stops the app ("Quit ENLENS" in the sidebar) once the
running jobs have stopped (at most 20 s); 409 when this copy was not started in a way that can be stopped from here.
0.14.3: every Claude Code run started from the app (`queue/claude-code`) is stopped first, and its batches go back to
the queue; the same for `POST /api/restart` and `POST /api/update`. Each run's process id is kept in
`<data folder>/claude-runs/<project>-<hash>.run.json`, so an app started later still sees a run that kept working
(`runner.running`), can stop it, and does not start a second.

"Update ENLENS" in the sidebar (0.13.1). `GET /api/state` says `can_quit` and `can_restart`: whether this copy can stop
itself, and restart itself (started with `enlens-gui` or from the ENLENS icon; the button is shown only then, and
since 0.13.6 only when there is an update).

- `GET /api/update` → `{"available": bool, "on_disk": bool, "version": running, "latest": "0.13.2" | null,
  "changes": n | null}`: whether a newer ENLENS waits, the way this copy was installed (the latest GitHub Release
  for the one-line install: `latest`; new commits on the branch a git copy follows: `changes`), or is installed
  already while this copy kept running (`on_disk`, `latest` is that version). 409 with the reason when it cannot be
  updated from here (files of a git copy edited by hand, a download package, no network).
  0.13.6: the page asks when it opens and every two minutes, and shows the button only when `available`. The answer
  (or the 409 and its reason) is kept for 100 seconds, so the open tabs share one look; `GET /api/update?fresh=1`
  (*Check for updates* in Settings) looks again now. A version already on disk is seen at once. The one-line install
  reads the newest version from where `github.com/…/releases/latest` redirects to, which GitHub's API limit does not
  count; the API is asked only when that page does not say. `POST /api/update` forgets the kept answer.
  0.14.3: while an update runs the answer is the kept one (or `available: true`) with `"updating": true`, and no
  `git fetch` is made beside the update's own git commands; a git command never asks for a password (stdin closed,
  `GIT_TERMINAL_PROMPT=0`, ssh in batch mode) and is stopped after 90 s.
- `GET /api/whats-new` (0.15.1) → `{"note": {"version", "title", "subtitle", "points": [...]}}` or `{"note": null}`. The
  note is `gui/static/whats-new.md` (`# 0.15.1: Title`, `*subtitle*`, a few lines starting with `-`). It is served only
  when its version is the running one and the setting `whats_new_seen` is not that version, and that setting is set
  the moment it is served, so the page shows it once, on the first start after an update. A new installation (no
  project yet, or no settings file) is marked silently and gets `null`; a malformed file is `null`, never an error.
  0.15.4: before it, once, an update on Windows that did not finish: `{"note": {"kind": "problem", "version":
  running, "title": "The update to X did not finish", "subtitle", "points": [what happened, what to do]}}`, from the
  result `handover.py` left in `updates/result.json` of the data folder (removed when read; a result that says the
  update worked is only removed).
  After 0.17.2 what is new is read only when asked, so the answer is `{"note", "changes", "unread"}`: `note` is only
  the Windows problem above (once) or `null`; `changes` is the running version's note, `{"version", "title",
  "subtitle", "points", "url"}` (`url`: the version's release page on GitHub), or `null`, served every time and marking
  nothing; `unread` is true when an update brought it and this person has not opened it (`whats_new_seen` is not the
  running version; never on a new installation, which is still marked silently). While `unread` the page shows a small note in the
  corner (after 0.18.0rc1: the title and *Read what's new*; in 0.18.0rc1 a sidebar button); Settings has it always.
- `POST /api/whats-new/read` `{}` (after 0.17.2) → `{"unread": false}`: the note was read or closed; `whats_new_seen`
  becomes the running version.

- `POST /api/update` `{}` → `{"updated": true, "restarting": true, "handover": false, "from", "version",
  "jobs_stopped": n}`: installs it as `enlens update` does, then restarts on the same address and port (running jobs
  are stopped first, as for Quit; at most 20 s); `{"updated": false, "restarting": false, "version"}` when nothing
  newer waits. 409 when the update fails (nothing restarts; the reason is the error), when this copy cannot restart
  itself, and for a second request while one is updating or restarting. 0.15.4, the one-line install on Windows:
  `"handover": true`: the new version is downloaded and checked, then the app quits and `handover.py` installs it and
  starts the app again on the same address (`server.handover_command`); the page waits up to five minutes. Before
  0.15.4 this was a 409 that said to quit and run the install line again.
- 0.15: *Try new versions early*: the setting `update_channel` (`"stable"`, the default, or `"early"`, validated by
  `PUT /api/settings`) says whether the check and `enlens update` of a one-line install also take release candidates:
  `early` asks GitHub's list of releases (`/releases?per_page=30`, drafts skipped) and takes the highest version
  (`update.version_tuple`); `stable` asks `/releases/latest`, which is never a pre-release. A git copy follows
  `main` and ignores it. `GET /api/update` carries `"candidate": true` when `latest` is a release candidate, and
  changing the channel makes the next look ask again.
- `GET /api/technical-details` (0.15) → `{"text": "ENLENS version: …\nInstalled: …\nSystem: …\nPython: …\nAI route: …\nLocal
  only: yes|no\nUpdate channel: …"}`: a short block for a problem report (*Copy technical details* in Settings →
  Technical). It holds no path, project or document name, user name or key.
- `POST /api/restart` `{}` → `{"restarting": true, "jobs_stopped": n}`: restarts into the version on disk (*Restart
  now* on the banner *ENLENS X is installed, but Y is still running*); 409 when this copy cannot restart itself.

0.17.2: the restarted copy keeps the access token (it is handed over in the environment, `ENLENS_RESTART_TOKEN`,
which the new copy takes out at once; on Windows the update starts handover.py with it in that program's environment
only, and handover.py gives it to the copy it starts and to nothing else), so the open
tabs, which keep it, reach the new copy. A restart that cannot have its old port back takes a new token. The page
waits until `/` answers with a new `enlens-run` (or answers again after not answering) and reloads. On macOS and Linux the same process becomes the new version (`os.execv`),
in the same terminal; on Windows a new one is started and the old one ends. Started from the icon, it is restarted
as the icon starts it (`--launcher`, output to `logs/enlens.log`), without opening a new browser tab.

`GET /api/servers` → local model servers running now (probed in parallel, < 1 s):
```json
{"servers": [{"kind": "ollama", "url": "http://localhost:11434", "version": "0.12.3",
              "models": ["bge-m3:latest", "qwen3:8b"], "chat_models": ["qwen3:8b"], "embedding_models": ["bge-m3:latest"],
              "loaded": ["qwen3:8b"], "modified": {"qwen3:8b": "2026-09-30T08:12:00Z", "bge-m3:latest": "…"}},
             {"kind": "openai", "url": "http://localhost:1234/v1", "models": […], "chat_models": […], "embedding_models": […]}],
 "suggested": [{"name": "qwen3:8b", "use": "chat", "size": "about 5 GB"},
               {"name": "nomic-embed-text", "use": "embed", "size": "about 0.3 GB"}]}
```
`suggested` (0.13.7): the models the page offers to download into Ollama with one button. `ollama_app` (0.15.6):
whether Ollama is on this computer, running or not: `{"installed", "path", "system": "windows" | "mac" | "linux",
"how": "app" | "terminal", "line", "manual"}` (`how`: the app installs it itself, or on Linux opens a terminal window
running Ollama's own `line`; `manual`: Ollama's installer file, for doing it by hand).

`GET /api/ollama` (0.15.6) → what the page shows before Ollama is installed from the app: `ollama_app`'s fields plus
`"size": {"bytes", "exact"}` (the download for this kind of computer, as ollama.com says it now, kept an hour; when
ollama.com cannot be asked, the size known in November 2026, `exact` false: 1.7 GB for Windows, 230 MB for macOS),
`"needs"` (the free disk space asked for: four times the download, for the file and Ollama unpacked), `"free"` (free
space in the temporary folder) and `"from"` (the address it downloads).

`POST /api/ollama/install` (0.15.6) → installs Ollama without a terminal, as `POST /api/claude-setup/claude-code` installs
Claude Code. Windows and macOS: `{"job": …}` of kind `ollama-install` (one at a time) that downloads Ollama's own
installer (`OllamaSetup.exe`, `Ollama-darwin.zip`: the files ollama.com's install lines download), checks that it is
Ollama's (Windows: the Authenticode signature is valid and its signer is `O=Ollama Inc.`, as Ollama's install.ps1
checks; macOS: `codesign --verify --deep --strict` against Ollama's Developer ID team, 3MU9H2V9Y9), installs it for this
user (Windows: the installer's silent per-user mode, `%LOCALAPPDATA%\Programs\Ollama`, no administrator rights; macOS:
`/Applications`, else `~/Applications`) and starts it hidden. Its `progress` is `{"step": "download" | "check" |
"install" | "start", "done", "total"}` (bytes while downloading); `POST /api/jobs/<id>/cancel` stops it while it
downloads, and nothing is installed. Its `result` is `{"path", "running"}` (`running`: Ollama answered within a
minute). An Ollama already on the computer is only started (`"already": true`). A failed install is a job `error` in
plain words (not enough disk space, offline, a file that is not Ollama's: nothing is installed from it). Linux:
`{"terminal": {"opened", "window", "command"}}`: a terminal window runs Ollama's own line, which asks for the password
(it installs for everyone and sets up a service); `command` is the line to type when no window could be opened.
Nothing of the person's is sent, so it is allowed with `--local-only` too. 0.18.0rc2: `suggested` is what fits THIS
computer (`modeladvice.suggested`), and `advice` says more: `{"computer": {"memory", "disk_free", "gpu", "system",
"unified", "words"}, "chat": {"pick", "smaller", "larger", "options", "reason"}, "embed": {…}, "what_is_a_model"}`;
a model is `{"name", "use", "role": "recommended"|"smaller"|"larger", "size", "bytes", "speed": "quick"|"fair"|"slow",
"speed_text", "good_for", "tight", "note"}`. Only models that fit the memory (the size and the memory its context takes,
at most 50 % of the memory for the recommended one, 65 % for a larger one; a graphics card's own memory where
`nvidia-smi` reports one) and the disk (the download and 2 GB to spare) are listed; when none fits, `pick` is null and
`reason` says why. `advice` is null when the computer cannot be read, and `suggested` then keeps the old
`qwen3:8b` and `nomic-embed-text`.

`POST /api/ollama/start` (0.15.6) → starts the Ollama that is on this computer but not running, hidden: `{"started",
"path"}`; 409 when Ollama is not on this computer. The page notices it within a few seconds. 0.18.0rc2: it starts nothing
when Ollama answers already (`{"started": false, "running": true}`) or was started by ENLENS in the last 45 seconds
(`{"started": false, "starting": true}`): the card calls it by itself whenever Ollama is on the computer and does not
answer.

`POST /api/servers/pull` (0.13.7) → downloads models into the Ollama running on this computer, so a local model needs
no terminal. Body `{"models": ["qwen3:8b", "nomic-embed-text"]}` (one to four names as Ollama's library writes them;
or `{"model": "qwen3:8b"}`), optionally `"url"`, an Ollama address as `GET /api/servers` lists it, and `"use"`: `ai`
(the AI that reads the documents: `backend` ollama and its model, plus the embedding model if one was downloaded),
`restricted` (the local model for documents marked *Only a local AI*) or `embed` (search by meaning). With `use` the
app chooses the downloaded models itself when the download is done, so closing the page does not lose the choice,
unless those settings were changed meanwhile (then the person's choice stands and `chosen` is null). Ollama fetches
the models from ollama.com itself; nothing of the person's is sent, so it is allowed with `--local-only` too. Returns
`{"job": …}` of kind `model-pull` (one at a time: while one runs, its job is returned). Its `progress` is
`{"model", "index", "count", "status", "done", "total"}` (bytes of the model being downloaded, as Ollama reports
them); its `result` `{"url", "models", "listed": {name: the name Ollama lists, e.g. "nomic-embed-text:latest"}, "chosen":
{the settings it chose} | null}`.
`POST /api/jobs/<id>/cancel` stops it (Ollama keeps what it has and goes on from there next time). 400 for a name that
is not one, 409 when no Ollama answers on this computer (or at the address in Settings). A failed download is a job
`error` in plain words (no such model, not enough disk space, offline).

`POST /api/servers/test` → tests the configured chat model (and embedding model if set):
`{"ok": true, "backend": "ollama", "model": "qwen3:8b", "model_available": true, "message": "Ollama 0.12.3 is running. …",
"warning": null | "…", "details": {"parameters": "8B", "quantization": "Q4_K_M", "trained_context": 40960},
"embedding": {"ok": true, "model": "bge-m3", "dimensions": 1024} | {"ok": false, "model": "…", "error": "…"},
"context": {"setting": "auto", "num_ctx": 8192, "needed": 6171, "thinking_allowance": false}}`
(502 `kind: backend` when the server cannot be reached). `loaded` (in `GET /api/servers`): the models in memory now
(Ollama, and LM Studio); `modified`: when each was pulled (Ollama).

### Projects

`GET /api/projects` → `{"projects": [summary]}`.
`POST /api/projects` `{"name": "Morocco"}` → `{"project": summary}` (also becomes the current project).
`POST /api/projects/link` `{"path": "/path/to/workspace", "name": "Pilot"}` → links an existing workspace folder
(not copied). When the folder is another person's project (its people do not include this person) the answer is 409 with
`{"error", "report": {"other": {"name"} | null, "triggers": n, "views": n, "config": [keys changed], "bib_paths": n,
"cache": bool}}` and nothing is linked; the same request with `"clean": true` cleans it like a project brought in from a
file (a shared-folder record, file paths of the other computer, and what was stored for speed go; the documents and
the work stay) and links it. `DELETE /api/projects/<p>` `{"confirm": "<p>"}` → `{"result": "unlinked" | "moved to …/trash/…"}`.

`GET /api/projects/<p>/export.zip` → the whole project as one zip, to give to a colleague or move to another
computer: a consistent copy of the database, `config.json`, the project's codebooks, and the original file of every
document the project has (at its place in `uploads/` or `inputs/`, or as `originals/<doc_id>/<name>` when it was read
from outside the project folder). 0.14.3: nothing else of `uploads/` (before, the whole folder, so the file of a
removed document went along).
Built in a temporary file and sent in chunks; the file name is readable ("ENLENS project - Demo - 2026-10-28.zip").
0.17.0: `?scope=shared` → only what you shared, to send to a colleague ("ENLENS shared work - …zip"): every private item
is taken out of the copy of the database (`sharing.strip`, then VACUUM), a withdrawn item leaves only its mark, the
codebooks not shared stay here, and the tables about this copy only (versions, the log of work brought in, the
glossary) are empty; the documents and their files go along. `?scope=all` (the default) is the whole project, as
before; either way each item says whose it is. Another `scope` → 400.

`GET /api/projects/<p>/export.qdpx` → 0.18.7 (G5): the project for NVivo, ATLAS.ti and MAXQDA, as a REFI-QDA project (`urn:QDA-XML:project:1.0`: `project.qde` and `sources/<guid>.txt`): every document as its passages joined, the codebooks with labels and the project's own as codes, the hypotheses as codes with *Supports*, *Partly supports* and *Contradicts*, the labels and judgements that count as codings on their quotes (coded by the person or by "ENLENS AI (<model>)"), notes and highlights as memos on their words, and the research log as one memo (`qdpx.export_project`; its docstring has every rule). `?framework=<name>` keeps one codebook (400 for an unknown one); `?threshold=` the strictness a judgement counts at (else Settings'). Built in a temporary file and sent in chunks ("ENLENS for NVivo - Demo - 2026-11-14.qdpx"). GUIDs are uuid5 of ENLENS's ids: two exports give the same.
`POST /api/projects/import?name=<name>` with the zip as the raw body → `{"project": summary}` (it becomes the
current project). Without `name` the project keeps the name it had, with " (2)" added when that is taken; a `name`
that is taken → 409. 400 for a file that is not a zip, or a zip without a project (`enlens.sqlite`). Paths in the zip
cannot leave the new project folder, and its size is capped. 0.14.3: the database is checked and opened before the
project is put in place: a damaged zip or one whose database cannot be read → 400 with a plain message, and nothing
is left in `projects/`.

**Shared projects (0.14).** The zip's `bundle.json` also says which project it is and who sent it: `"project_uid"`,
`"from": {"id": "p…", "name": "Anna"}`, `"sent_at"`; codebooks the project uses from the home folder come along in
`frameworks/`. A copy made with *Import* keeps the project's `project_uid`.
`POST /api/projects/<p>/bring-in` with a colleague's project zip as the raw body merges it into this copy
(`sync.bring_in`) → `{"report": …, "project": summary}`. The report: `{"from": {"id", "name"}, "project", "version",
"at", "lines": ["From Anna: 1 new result.", …], "documents": {"new": [titles], "clash": [{"title", "doc_id"}],
"removed_here", "removed_there", "other_reading": [{"title", "doc_id", "placed", "not_placed", "notes_lost"}] (0.17.0: a
reading known as an earlier or later one of a document here: the colleague's results placed on yours)}, "checks": {"new", "updated", "same", "yours_newer", "clash": [{"hyp_id", "of",
"text"}], "running": [texts], "running_here": [texts], "removed_here", "removed_there"}, "themes": {"new", "updated",
"clash": [{"run_id", "of"}], "removed_here", "running_here": [run ids]}, "codebooks": {"new", "updated", "clash":
[{"name", "of"}], "merged": [{"name", "theirs", "added", "removed", "clash", "kept_removed"}] (0.17.0: code names)},
"judgements", "reviews", "labels", "labels_kept_yours", "links", "other_rows", "bibliography":
null | "new" | "merged" | "kept_yours", "ai_access": [{"title", "doc_id", "yours", "theirs", "now", "why": "theirs" |
"yours" | "default", "claude_read_here" | "claude_read_there"}]}`; it is kept in `sync_log`. `running_here`
(0.14.3): results and theme runs the colleague changed whose work in this copy is not done yet (waiting for Claude
Code, taken by a helper, a part for the local model): this copy's version stays as it is (before, it was replaced and
that work deleted). 0.17.0: a file of a newer sync format than this copy knows (`bundle.json`'s `sync_needs` above
this ENLENS's format, `sync/formats.py`) → 400 with a plain message, also with `?anyway=1`. A file not known to be a
copy of this project (another project's, or one made before 0.14) →
409 with `"not_this_project": {"project_uid", "from", "name", "version"}`; `?anyway=1` brings it in all the same (and remembers that project's id). 400 for a file that is not a project zip, or
the zip of *Move ENLENS to another computer*. Before the merge the database is copied to
`backups/before-bringing-in.sqlite`.
**Private until shared (0.17.0, `sharing.py`, `gui/api_sharing.py`).** What a person makes is an *item*: `kind` one of
`check` (key: the hypothesis id), `themes` (the theme run's id), `codebook` (its name), `note` (the note's id), `log`
(an entry a person wrote), `link` (two terms' ids, `a|b`). Each is `private`, `shared` or `withdrawn` (shared once,
taken back); only its owner (who made it) shares it or takes it back.
- `GET /api/projects/<p>/sharing[?kind=&state=]` → `{"items": [{"kind", "key", "title", "state", "mine", "owner":
  {"id", "name"} | null (made before 0.17.0, maker not known), "can_change", "at", "by", "here" (false: withdrawn and no
  longer in the project), "needs": [{"kind", "key"}] (shared with it)}], "counts": {kind: {state: n}}, "me": {"id",
  "name"}, "kinds": {kind: {"one", "many"}}}`. An unknown kind or state → 400.
- `GET /api/projects/<p>/sharing/<kind>/<key>` → `{"item": {…as above…}}` (404 when the project holds no such item).
- `POST /api/projects/<p>/sharing/share {"items": [{"kind", "key"}], "why"?}` (or one item as `{"kind", "key"}`) →
  `{"shared": [{"kind", "key", "title"}], "also": [...] (shared because a shared item needs it: a check's codebook),
  "already": [...]}`. `POST …/sharing/unshare` (same body) → `{"withdrawn": [...], "not_shared": [...]}`. Both write a
  research log entry (kinds `shared`, `unshared`, group `together`) with `why`. 404 for an item the project does not
  hold, 403 for a colleague's, 400 for a body without items.
When a colleague's work comes in, the report says what its owner took back (`"shares": {"shared": [titles],
"withdrawn": [titles], "withheld": [titles]}`: `withheld`, items its owner had taken back that this copy did not hold,
which do not come in).

**The shared folder (0.17.0, roadmap L5: `sync/folder.py`, `gui/api_folder.py`).** A folder the team already shares
(OneDrive, Dropbox, a network drive), chosen once per project and kept in the project's `config.json`
(`shared_folder`; never in the database or a zip). Each copy writes what its person shared into its own subfolder
(`<folder>/ENLENS-<project id, 8>/<person id>/`) as numbered bundles that are never rewritten, and brings in what the
others wrote with the merge rules of `bring-in`. The project's database never goes into the folder; documents' readings
and original files are stored there once for the whole team.
- `GET /api/projects/<p>/shared-folder` → `{"folder": path | null, "team_folder": path | null, "reachable": bool |
  null, "keep_out": {"mine", "colleagues": [names], "in_force", "last_known": true (only while the folder cannot be
  read: the colleagues who had the switch on when it last was)}, "me": {"id", "name", "last_written": n | null,
  "last_written_at"}, "people": [{"id", "name", "app_version", "sync_format", "keep_out", "last_bundle",
  "read_up_to", "last_read_at", "waiting" (their bundles not brought in yet), "has_read_mine" (how far they read
  yours)}], "problems": [{"kind", "person": {"id", "name"} | null, "message", "seq"}], "not_here": [{"doc_id",
  "title", "from"}] (documents colleagues keep out of the folder that this copy does not hold: add the file yourself),
  "job": the round running now (a job view) | null, "last_round": the last round since the app started (a job view
  with `result` or `error`) | null}`. Nothing is changed or written. `kind` of a problem: `unreachable` (the folder
  cannot be reached: a drive not connected, a folder moved), `other_project` (the folder of that name holds another
  project), `gap` (a colleague's bundle the cloud service has not brought yet), `arriving` (one still being copied, or
  the project's own `project.json` not brought yet), `damaged` (not what its name says, or its database cannot be read:
  left aside, and that colleague's later work waits behind it), `newer_format` (made by a newer ENLENS: update; that
  colleague's work waits, the others' comes in), `too_large` (a bundle, or a document's reading, larger than ENLENS
  reads: left aside, that colleague's later work waits behind it), `documents` (documents their work reads have not
  arrived yet),
  `failed` (their work could not be merged: nothing of it changed, the others' came in), `other_computer` (another
  computer writes into this person's subfolder: nothing is written or deleted from this copy until the person presses
  *Use both computers*, `POST /api/second-computer`). Each `message` is in plain
  words, ready to show; every one except `other_project` goes away by itself on a later round. A copy held up at a
  colleague's bundle says so in its own subfolder (`waiting.json`); when that bundle is damaged or gone on its
  writer's computer too, or names a reading no copy can write again, the writer's copy starts afresh at its next round
  (one bundle with everything it shares), and the colleague goes on from there.
- `GET /api/cloud-folders` → `{"folders": [{"name", "path", "service"}], "picker": bool}` (0.18.0rc2, L7): the cloud
  folders this computer has, by plain name (`service`: `onedrive`, `googledrive`, `box`, `dropbox`, `other`): on a Mac
  those in `~/Library/CloudStorage/` and `~/Dropbox`; on Windows the folders `%OneDrive%`, `%OneDriveCommercial%` and
  `%OneDriveConsumer%` name, and Dropbox's (`info.json`); on Linux `~/Dropbox` and Dropbox's `info.json`. `picker`:
  whether `POST /api/choose-folder` has a folder window to open. Only folders that exist are listed.
- `POST /api/choose-folder {"prompt"?, "start"?}` → `{"path": str | null, "available": bool}`: opens the system's own
  folder window (macOS `osascript`, Windows PowerShell, Linux `zenity` or `kdialog`) and answers when it is closed;
  `path` is null when it was cancelled, closed too late (10 minutes), failed or there is no such window
  (`available` false). 409 while another folder window is open. Never reads or writes anything in the folder.
- `GET /api/projects/<p>/shared-folder/find` → `{"found": [path], "team": "ENLENS-xxxxxxxx"}`: the folders, among the
  cloud folders and up to three levels below them, that already hold this project's team folder (a colleague set it
  up); each is a shared folder to choose. Looks about two seconds at most; hidden folders are skipped.
- `PUT /api/projects/<p>/shared-folder {"path", "keep_out"?}` → the status above. The folder must exist, be writable,
  not be inside the project's own folder, and not hold the project nor ENLENS's own folder (the cloud service would
  copy the project's database to the team): 400 in plain words otherwise. The project's folder in it (`ENLENS-…`)
  chosen by mistake stands for the folder that holds it. The research log notes the choice (kind `sync`).
- `DELETE /api/projects/<p>/shared-folder` → the status: the project stops using the folder (nothing in it is
  removed; what came in stays).
- `PUT /api/projects/<p>/shared-folder/keep-out {"keep_out": bool}` → the status. On: documents marked *Only a local
  AI* or *No AI* stay out of the folder (their readings, files, the AI work on them, and their passages in what a
  shared check handed to the AI); colleagues add those files themselves, and checks that read them still come in
  (their excerpts, with the words they quote, kept as records until the file is added). It holds in every copy once
  anyone in the team has it on (`keep_out.in_force`). Off by default. 400 without a boolean. What a copy wrote of
  such a document before (the switch turned on later, or the document marked later) is removed from its own subfolder
  at its next round, and it starts afresh there with one bundle; what colleagues brought in already stays with them,
  and the cloud service may keep earlier versions of files. An item taken back (*Unshare*) leaves the folder the same
  way, in the copy of its owner and of any colleague who wrote it too. A document a colleague keeps out, whose file
  this copy's person adds themselves, takes the colleague's setting at once (research log kind `ai-access`,
  `data.from: "colleague"`).
- `POST /api/projects/<p>/shared-folder/sync` → `{"job": view}` (kind `folder-sync`): *Sync now*, one round (bring in
  what colleagues wrote, then write what changed: a copy writes with its colleagues' decisions already in force). One round per
  project at a time: a second request returns the running job. 400 when no folder is chosen. The job's `progress`
  is `{"step": "write" | "read" | "files", "message", "index"?, "total"?}`; its `result`: `{"at", "folder", "wrote":
  {"seq" (null: nothing changed), "snapshot", "items": [{"kind", "key", "state", "title"}], "documents", "readings",
  "files", "rows", "waiting": [{"kind", "key", "title"}] (shared items with work under way: written when done),
  "kept_out", "taken_out" (documents whose words this round removed from this copy's subfolder: the switch)}, "read":
  [{"id", "name", "bundles": [first, last] | null, "report": the bring-in report (above, with
  `"via": "folder"`, `"bundles"` and `documents.not_here: [{"title", "doc_id", "kept_out"}]`) | null}], "files" (original
  files fetched that arrived after their documents), "problems": [as above]}`. A folder that cannot be reached is a
  problem in the result, not an error: nothing changed. Each colleague's work brought in is logged as from a zip
  (`sync_log`, research log kind `sync`). 0.17.0 (M6): a round never runs beside adding documents, the new reader or
  another round of the project: it waits its turn (`waiting_for`); it runs beside checks.

**A storage space of the team's own (0.18.0rc2, roadmap L6: `sync/space.py`, `sync/seal.py`, `sync/storage.py`,
`sync/b2.py`, `sync/r2.py`, `gui/api_space.py`).** An online storage space (an S3 bucket at Backblaze B2 or Cloudflare
R2) in place of a shared folder. Each copy keeps a copy of the space on this computer (`<ENLENS folder>/spaces/<space
id>/`), laid out as a shared folder; a round brings the space's news into it (every file opened and checked: sealed
for that place, signed by the member whose part it is in), runs the shared folder's round on it, and sends this copy's
part back, sealed (AES-256-GCM with the project's key, Ed25519 signatures). The project's `config.json` says where the
space is (`shared_space`, no keys); the keys are in the system's keychain (`keychain.py`). With a space, `GET
…/shared-folder` has `"space"` (below) and `"folder"` is the copy on this computer; *Sync now* and the poller are the
folder's (a space is looked at every 10 minutes at most, and about 20 s after a change). The round's `result` has
`"space"` (where it is, in words), `"sent"` (files sent) and, when the team moved, `"moved"`. More problem kinds:
`denied` (the space refused this copy's key: removed from the team, or a key deleted), `full` (the service's cap or
billing), `set_aside` (a file or the list of members not signed as it must be: nothing of it came in), `no_keys` (this
computer has not got the space's keys: a project copied from elsewhere; ask for a new invite).
- `GET …/shared-folder` → as above, with `"space": null | {"id", "service": "b2" | "r2" | "dir", "where", "region",
  "in_eu", "keeper" (this copy keeps the space's keys: it invites, removes and moves), "joined" (the keeper's copy has
  let this copy in), "members": [{"part", "person", "name", "me", "keeper", "removed", "since"}], "invites": [{"part",
  "made_at", "label"}] (not used yet), "set_aside": [{"part", "why", "message", "at"}], "keychain": "macos" |
  "windows" | "secret-tool" | "file"}`.
- `GET /api/space/links` → the services' pages the set-up opens (`b2_signup`, `b2_keys`, `b2_caps`, `r2_signup`,
  `r2_dashboard`, `r2_token`: the link that fills in Cloudflare's token form).
- `POST /api/projects/<p>/space/b2 {"key_id", "app_key"}` → `{"job": view}` (kind `space-setup`): the owner's set-up
  with a Backblaze master application key. The job checks the key and the region, makes a key of ENLENS's own (or keeps
  the master key, with a warning, when that key may not make keys), a private bucket keeping only each file's latest
  version, and a test file; its `result` is the status above with `"warnings": [text]` (not in the EU; the master key
  kept). 400 without both halves; 409 when the project has a space already; a wrong key, maintenance or no connection
  end the job with `error` in plain words, nothing set up.
- `POST /api/projects/<p>/space/r2 {"token", "account_id"?}` → `{"job": view}`: the same at Cloudflare R2 (a bucket in
  the EU jurisdiction). When the token reaches several accounts and none is named, the job's `result` has `"accounts":
  [{"id", "name"}]` and nothing is set up.
- `POST /api/projects/<p>/space/invites {"label"?}` → `{"link", "message", "part", "status"}`: a new part with its own
  storage keys, and an invite link (`enlens://join#…`, holding those keys, the project's keys and a one-time secret);
  `message` is ready to send. The keeper's copy only (400 otherwise). The keeper's next round lets the colleague in.
- `DELETE /api/projects/<p>/space/invites/<part>` → the status: an invite not used yet is withdrawn (its keys deleted).
- `DELETE /api/projects/<p>/space/members/<part>` → the status: the colleague's keys are deleted and the project's key
  is replaced for those who stay. The keeper's copy only.
- `POST /api/projects/<p>/space/move {"service": "b2", "key_id", "app_key"} | {"service": "r2", "token",
  "account_id"?}` → `{"job": view}`: a new space; every member gets a part and keys there, sealed to them in the old
  space, and their copies follow at their next round. The `result` has `"moved": {"told": n, "not_told": [names]}`
  (the old space could not be reached: send them new invites).
- `POST /api/projects/<p>/space/join {"link"}` → the status: this project joins the team's space (409 when it has one).
- `POST /api/join-team {"link", "name"?}` → `{"project"}`: *Join a team* under Projects: a new project (named as the
  inviter's, or `name`), joined, and made the current project. 400 in plain words for a link that is cut off or not an
  invite.
- `DELETE /api/projects/<p>/space` → the status: this copy stops using the space and forgets its keys (nothing in the
  space is removed). `DELETE …/shared-folder` does the same for a project with a space.
- `POST /api/projects/<p>/space/dir {"path"}`: a space kept in a folder of this computer, sealed as at a service, for
  trying the Team tab (only with `ENLENS_TRY_SPACES=1`, as `tools/dev_server.py --space` sets it; 404 otherwise).

**Looking by itself every couple of minutes (0.17.0, roadmap L3: `gui/poller.py`, `gui/api_poller.py`).** A thread of
the app starts a round (`folder.sync_now`, the job above, marked `"background": true`) for each project with a shared
folder: about 15 s after the app starts, then every `sync_every_minutes` (default 2) after the last round ended (a round
by hand counts), and about 20 s after the last change made through the app in that project (any POST, PUT or DELETE
under `/api/projects/<p>/` except uploads, *Sync now* and the poller's own routes, and the end of any other job of the
project; each change starts the 20 s again). Never while paused, never without a folder, never two rounds at once for
one project, and never beside adding documents or the new reader (running): then the round waits, without a job in the
queue, and starts at the first look after that job ended. Its own rounds show in the sidebar only when one takes
longer than 20 s. A round whose problems are all `unreachable` means offline: the
next try waits 1, 2, 4, 8 … times the interval, at most 30 minutes (or the interval, if longer), and changes do not
bring it forward; a round that reaches the folder (the poller's or one by hand) brings the interval back. Idle
(2026-11-12): after three of its own rounds in a row that found nothing to write or read, each further idle round
doubles the wait, up to four intervals and at most 15 minutes (or the interval, if longer): 2, 2, 2, 4, then 8 minutes
with the default. A change in the project, a round that found something or met a problem, and a round by hand bring
the interval back. An idle round writes nothing to disk (`tests/test_idle_writes.py`). The thread
stops when the app quits (no round starts once quitting has begun).
- `GET /api/projects/<p>/sync-poller` → `{"project", "folder": bool (a shared folder is chosen), "paused": bool (this
  project, on this computer), "paused_all": bool (the whole app), "state", "every_seconds", "next_round_at": ISO UTC |
  null, "next_round_in": seconds | null (null while paused, without a folder, or while a round runs), "offline": null |
  {"since": ISO, "failures": n (rounds in a row), "retry_seconds": the back-off}, "busy": null | {"id", "kind", "title",
  "message"} (the job that holds a due round back), "round": the round queued or running now (a job summary, by hand
  or not) | null, "last_round": null | {"job", "background", "state": "done" | "error" | "cancelled", "finished_at":
  ISO, "offline": bool, "problems": [as above], "came_in": n (as `came_in.count` counts), "error"}, "came_in":
  {"count", "seen_through", "rounds": [{"id", "at", "from": {"id", "name"}, "bundles": [first, last], "lines":
  [sentence], "count"}]}}`. `state`: `off` (no shared folder), `paused`, `waiting` (until `next_round_at`), `due`
  (starting at the next look, within seconds), `busy`, `running`, `offline`. `came_in`: what came in through the
  folder since the person last looked, newest first (at most 30 rounds listed; `count` covers all): each colleague's
  merge from the folder (by the poller or by hand, kept in the project's `sync_log`, so it survives a restart) that
  brought something to count: new and updated documents, results, sets of themes and codebooks, judgements, notes,
  research log entries, items withdrawn by their owner, and sync clashes (labels and links are not counted). 404 for
  a project that is not there.
- `PUT /api/projects/<p>/sync-poller {"paused": bool}` → the state. Paused, no round starts by itself (*Sync now*
  still works); resumed, a round comes soon. 400 without a boolean.
- `POST /api/projects/<p>/sync-poller/seen {"through"?: id}` → the state: what came in up to the entry `through` of
  `came_in.rounds` (all of it without `through`) is seen. The mark is kept in the project's `meta`
  (`sync_came_in_seen`, never sent to a colleague) and never goes back. 400 when `through` is not a whole number.
- `GET /api/sync-poller` → `{"every_minutes", "paused", "running": bool (the thread runs), "projects": [the state of
  each project with a shared folder]}`.
- `PUT /api/sync-poller {"paused"?: bool, "every_minutes"?: 1–60}` → the same. 400 for anything else.
- Settings (also through `PUT /api/settings`): `sync_every_minutes` (1–60, default 2), `sync_paused` (default false),
  `sync_paused_projects` (a list of project names). They belong to this computer.

**One owner, Co-owners and Members (0.17.0, roadmap L2; roles after it: `ownership.py`, `sync/owner_merge.py`,
`gui/api_owner.py`).** A shared project has one Owner, any number of Co-owners and, for everyone else, Members (no row
needed). What its documents *are* (which documents, how each is read, who may read each with AI) is for the Owner and
the Co-owners to decide: their own changes are the project's at once, and they answer proposals. Only the Owner sets
roles and hands the project over. A Member may still change the documents in their own copy: each such change is a
*proposal* (kind, severity): `add` (a document added, low:
accepted at once by the owner's setting, on by default), `reread` (read with the new reader, medium), `blocks` (*Leave
out* / *Restore*, where the text starts or ends, medium), `remove` (high), `loosen` (more AI may read a document,
high). The proposer's copy keeps the change, except a looser AI setting, which waits in every copy, theirs too. A
document a Member adds reaches every copy at once, provisionally, and leaves the others when the owner declines
it; every other proposal changes nothing elsewhere until the owner accepts it. A *stricter* AI setting is never a
proposal: it holds in every copy at once; a *looser* one is never put into force in a copy by a file: it is an *offer*
its person answers (`offers`, `POST owner/loosening`). Who the owner is travels as a chain of records (`ownership`),
and each copy *pins* the record it follows for each place in the chain (no clock decides; another founder or a
take-over is a *question*, `questions`); roles (`roles`), the proposals, the answers and the documents as the
Owner and Co-owners decided them (`canon`, merged part by part by what each writer knew) travel in zips and through
the shared folder; `canon_seen` (how far this copy followed) and the pins stay in the copy. Two different answers to
one proposal, given without each other's, count for nothing (`clash`). Sync format 4. A project made with 0.17.0 is its maker's
(the record is written when it first leaves the computer: a zip or the shared folder); a project exchanged before
0.17.0 has no owner, and works as before, until someone says *Become the owner*. All routes are under
`/api/projects/<p>/`; errors: 403 (only the owner, or an Owner or Co-owner, or only the proposer, in words), 404 (no such proposal, person,
question or document), 409 (a proposal that no longer waits; nothing to make here), 400 (a body that says nothing usable).
- `GET owner` → the view:
  `{"owner": {"id", "name", "me"} | null, "me": person id, "is_owner", "since": ISO | null (when the record that made
  the owner was written), "how": "made" | "claim" | "handover" | "takeover" | null, "can_claim" (no owner yet: *Become
  the owner*), "can_take_over": words why | null (the owner has left the shared folder, or was not heard of for 14
  days), "accept_adds" (the owner's setting; true in any other copy), "role": "owner" | "co" | "member" (this
  copy's person), "can_write" (Owner or Co-owner: this person's changes to the documents hold at once),
  "can_set_roles" (Owner only), "people": [{"id", "name", "me", "owner", "role": "owner" | "co" | "member",
  "same_as": person id | null (another person this one is marked the same as), "needs_update": bool (a Co-owner whose
  ENLENS is too old to act as one)}] (this copy's person first), "proposals": [{"id", "kind", "severity": "low" | "medium" | "high", "doc",
  "title", "what" (the change in words: "removing “Annual report 2024” from the project"), "by": {"id", "name",
  "me"}, "at", "state": "waiting" | "accepted" | "declined" | "taken_back" | "replaced" | "moot", "note" (why it needs
  no answer any more, in words) | null, "reason" (the owner's) | null, "decided_by": {…} | null, "decided_at",
  "auto" (accepted at once by the setting), "mine", "can_decide", "can_take_back", "here" (the document is in this
  copy), "conflicts": [ids of the other waiting proposals for the document], "detail"}] (newest first; each also has
  `"clash": {"accepted": [person ids], "declined": [person ids]} | null`: set when it was answered both ways and
  neither answer counts, `state` then reads `waiting` with `note` "answered both ways"), "waiting": n (in a copy that
  may decide, all that wait, the questions, offers, refused rows and proposals answered both ways included;
  otherwise this person's own), "to_apply": [{"doc", "title", "kind": "reread",
  "note", "can_force"}] (a new reading the owner accepted that this copy did not make by itself: some of its results
  would find no place, or it cannot be read now), "documents": {doc id: {"state": "proposed" | "declined" | "waiting",
  "text"}}, "job": the move job of the project queued or running (a job view) | null,
  "questions": [{"id", "seq", "kind": "founder" | "takeover" | "other", "owner": person, "by": person, "why", "now":
  person (the owner this copy follows)}] (a change of owner this copy's person has not answered), "offers": [{"doc",
  "title", "from" (the level here), "to" (the level offered), "by": person}] (a looser AI setting offered, never
  applied), "removed": [{"doc", "title", "at", "by": person, "why", "cause": "removed" | "declined", "until"}] (can be
  restored until then: 30 days), "clashes": [{"id", "kind": "part" | "answer", "doc", "title", "part": "state" |
  "read" | "ai" | "blocks", "events", "counts", "people"}] (what was settled at the same time; for `"answer"` also
  "proposal", "what", "accepted", "declined": a proposal answered both ways), "refused": [{"kind", "key", "via",
  "title", "at"}] (a change in this person's name that a file carried and was not taken), "notices": [{"kind":
  "handover" | "role", "text"}] (shown once)}`. A `person` is `{"id", "name", "me"}`. `detail` by kind: `add`
  `{sha1, text_fp, reader, ai_access, state_n, again}`; `reread` `{from_fp, from_reader, to_fp, to_reader}`; `blocks`
  `{digest, blocks_n, left_out, restored, undone, bounds}`; `remove` `{removed_at, state_n}`; `loosen` `{from, to,
  ai_n}`. A copy names its own person "you". Before it answers, what this copy's person changed since the last look is
  written down as proposals (and, in the owner's copy, as the project's); when other work holds the project's
  database just then (a move, a merge) that waits for the next look, and the view shows what stands.
- `POST owner/claim {}` → the view: *Become the owner* of a project with none. 403 when it has one, and for a project
  never exchanged (its maker is its owner already). Two claims made at once: the earlier counts, then the smaller id.
- `POST owner/hand-over {"to": person id, "why"?}` → the view. Only the owner (403); `to` missing or oneself → 400; a
  person the project does not know → 404. The owner's own changes up to that moment become the project's first.
  Proposals that wait are then the new owner's to answer; the new owner's own earlier proposals stay proposals.
- `POST owner/take-over {"why"?}` → the view, when `can_take_over` says why; 403 otherwise (in words), and for the
  owner. A Co-owner may when the owner has left; a Member only when no Co-owner was heard of for 14 days either. It is
  a question in every other copy (`questions`), never a fact there.
- `PUT owner/settings {"accept_adds": bool}` → the view. Only the owner (403); not a boolean → 400. Turned on, the
  additions that wait are accepted at once. It is this copy's own and holds for one time as the owner: a new owner,
  and an owner who has the project back, start at the default (on).
- `POST owner/proposals/<id>/accept {"reason"?}` and `…/decline {"reason"?}` → the view. Only the owner or a Co-owner (403); an
  unknown id → 404; one that no longer waits → 409. Accepted, the change is made in the owner's copy at once (a
  document not here is fetched from the shared folder; a new reading is made by a job, below) and reaches every copy
  with its next round or zip. Declined, nothing changes in the project; the proposer's copy keeps its change (a
  document they added stays in their copy only). `POST …/take-back {}` → the view: only the proposer (403); one that no
  longer waits → 409.
- `POST owner/apply {"doc", "force"?: bool}` → the view with `"job"`: make here now the new reading the owner accepted
  (`to_apply`). `force`: results that find no place in the new reading are kept as records (as when a person moves a
  document from its own page); without it the document moves only when every result finds its place. 400 without
  `doc`, 404 for a document not here, 409 when it is read as the project reads it already.
- **Roles, questions, offers, removals and clashes (all under `/api/projects/<p>/owner`; each answers with the view; 403
  not allowed, 404 no such thing, 409 no longer so):**
  - `PUT roles/<person> {"role": "co" | "member"}` or `{"same_as": person id | null}` → the view. Only the Owner (403).
    Making a Member again writes the Owner's rows and the answers that counted again first, so nothing accepted goes
    and no proposal opens again.
  - `POST questions/<id> {"answer": "follow" | "keep"}`: follow the record the question names (the owner it names
    becomes the owner this copy follows), or keep the one followed now (the question is not asked again).
  - `POST loosening {"docs": [doc ids] | null, "allow": bool}`: answer offers. `allow: true` sets the level offered in
    this copy for those documents; `false` keeps them stricter. `docs: null` is every offer. An offer left alone is
    kept stricter. A stricter setting is never an offer.
  - `POST removed/<doc>/restore`: put back a document removed in the last 30 days (404 when there is no such archive,
    or it is older). A Member's restore also proposes it to the owner.
  - `POST clashes/<id>` (*Leave it so*): writes the part again as it is, so the clash goes in every copy. For a
    clash of kind `"answer"` use accept or decline of the proposal.
  - `POST take-back {}`: after a hand-over in this person's name that they did not make (`refused` of kind
    `ownership`): takes the project back with a take-over of this person's own, which every other copy is asked about.
  - `POST refused/<kind>/<key>/dismiss`: forget one `refused` row.
- **Codebooks:** `POST …/codebooks/<name>/follow` and the `offer` of a codebook are under *Codebooks* below.
- **The move job:** a new reading the owner accepted is made in each copy by one job of kind `new_reader` (lane
  `reader`: alone in its project, see Jobs), started when the owner accepts it, when a round of the shared folder that
  brought the decision in ends, and after `bring-in` of a zip; `"background": true` unless started by `apply`. Only
  documents whose file is here and on which no work runs are started; a document a waiting move covers already is not
  started twice. Its `result`: `{"moved": [{"doc_id", "title", "reason", "not_placed"}], "kept": [the same, with the
  reason it stayed as it is], "stopped", "owner": true, …}` and what adding documents does after it.
- Added fields elsewhere (nothing else changed): `GET documents` → each document has `"proposal": {"state", "text"} |
  null` (the view's `documents`, without a look at the shared folder); `PUT documents/ai-access` → `"proposed": [doc
  ids]` (in a collaborator's copy, a setting looser than the project's is not made but proposed; the same again while
  one waits proposes nothing more, again after a decline it is a new proposal); `bring-in`'s report → `"owner"` (what
  this copy then did: `{"owner", "proposed", "accepted", "applied", "moves", "fetch", "notes"}`) and `"proposals":
  {"new": [{"id", "kind", "title", "by"}], "decided": n, "owner": id | null (it changed)}`; its `documents` gain
  `"not_wanted": [titles]` (the owner removed them from the project or did not accept them: they did not come in) and
  `"removals": {"proposed" | "owner" | "declined" | "taken_back": [titles]}` (a colleague's removal, as what it is:
  `removed_there` still lists them all); a folder round's `result` → `"moves_due": [doc ids]`; a document's stub in the
  shared folder may carry `"canon_ai"` (how far that copy followed the owner's AI setting of it). A copy made with
  *Import* from a colleague's zip starts as the project has its documents: what the colleague changed and the owner has
  not accepted stays theirs.
- Research log kinds (group `together`): `proposal`, `proposal-accepted`, `proposal-declined`, `proposal-taken-back`,
  `owner`; each written once, by the copy of the person who acted, and it travels. A removal or an AI setting made in a
  copy because the owner said so is `document-removed` (with `why`) or `ai-access` (`data.from: "owner"`).

`GET /api/projects/<p>/together` → `{"uid", "me": {"id", "name"}, "people": [{"id", "name"}], "history": [{"at",
"from", "lines"}] (newest first, 5), "clashes": [{"kind": "check" | "document" | "themes" | "codebook", "key",
"of_key", "name", "at"}] (only those whose two versions are both still here: deleting one settles it), "agreement": [{"person_id", "name", "both", "agreed", "rate", "kappa"}]}`
(`kappa` null below 10 excerpts in common).
Settings: `your_name` (at most 60 characters) is the name colleagues see; `person_id` is made by ENLENS. A sync-clash
copy is marked where it is listed: `clash: {"of", "name", "at"}` on each row of `GET …/hypotheses`, each document of
`GET …/documents` and each run of `GET …/themes`; `GET …/hypotheses/<id>` has `clash` (with `of_text`) and
`clash_copies: [{"hyp_id", "of", "name", "at"}]`. Each excerpt of a result has `judged_by` ("you", a colleague's
name, or null) and `others: [{"mine", "name", "verdict", "note", "at"}]` (the other people's judgements of it).

`GET /api/projects/<p>` →
```json
{"name": "Demo", "linked": false, "documents": 3, "hypotheses": 3, "ok": true, "path": "…", "passages": 4,
 "search": {"model": "nomic-embed-text", "passages": 4, "embedded": 4, "complete": true, "models": ["nomic-embed-text"]},
 "frameworks": [{"name": "sdg", "title": "UN Sustainable Development Goals (169 targets)", "label": "SDG target",
                 "source": "bundled", "codes": 169}]}
```
`search`: semantic index state for the embedding model in Settings (`model` "" when embeddings are off; then search
is by keywords only). `embedded < passages` → offer "Build semantic index" (`POST …/index`).

### Sources

`GET /api/projects/<p>/documents` →
```json
{"documents": [{"doc_id": "dab20f86eee", "title": "Water footprint of …", "kind": "pdf", "pages": 3, "chars": 937,
                "passages": 2, "claims": 0, "file": "paper_a.pdf", "added": "2026-10-27 21:27",
                "check": "" | "unreadable text layer" | "very short: check it is the cited work",
                "scanned": "" | "Scanned: text recognised (OCR)" | "Scanned: text recognised (OCR) on 3 of 12 pages"
                           | "Scanned: no text on 2 of 12 pages. Ask IT to install Tesseract to read it.",
                "ocr_pages": 0, "scanned_pages": 0}],
 "search": {…as above…}}
```
`check` non-empty = a quality warning to show. `scanned` non-empty: show it as a note on the document (the text of
recognised pages may contain recognition errors).

Uploading (one request per file, all files of one upload share a `batch` id chosen by the page, `[A-Za-z0-9_-]`):
`POST /api/projects/<p>/uploads?batch=<b>&name=<file name>` with the raw file as body →
`{"batch": "b", "name": "report.pdf", "size": 123}`. Accepted: `.pdf .html .htm .txt .md .zip` (zips are opened,
also nested; a `manifest.csv` inside, columns `file, reference, doi`, names the works). Max 2 GB per file.

`POST /api/projects/<p>/ingest` `{"batch": "b", "exclude": "A_18_* draft*"}` or `{"path": "/Users/me/Reports"}`
(read a folder, zip or file in place, without uploading) → `{"job": Job}` (kind `ingest`).
Ingest job `progress`: `{"done": 3, "total": 12, "file": "report.pdf"}` (then `{"phase": "embedding", "done", "total"}`
while the new passages get vectors). `result`:
```json
{"files": 12, "added": 10, "duplicates": 1, "empty": 1, "passages": 2381, "declared": 0,
 "empty_files": ["scan.pdf"], "mostly_unreadable": ["garbled.pdf"], "failed": ["x.pdf: …"], "excluded": […],
 "ocr": ["scan2.pdf"], "scanned_no_text": ["scan.pdf"],
 "not_in_manifest": […], "documents_added": [document rows as in GET documents],
 "semantic_index": {"added": 2381, "embedded": 2381, "passages": 2381, "complete": true, …} | absent,
 "semantic_index_error": "…" | absent}
```
0.14.3: `failed` also lists a zip, or a file in a zip, that could not be unpacked (`"sources.zip: password-protected
zip: save a copy without the password and add that (report.pdf)"`, `"…: damaged zip: copy or download it again (…)"`),
a damaged Word file and a password-protected PDF (`"x.pdf: password-protected: …"`, before reported as a file without
text); the other files are added. `"stopped": true` when Stop was pressed, also during the text recognition (OCR) of a
scanned PDF, which is then not added.
(optional keys are absent when empty). `ocr`: PDFs whose scanned pages were read by OCR (on this computer, at low
priority). `scanned_no_text`: PDFs with scanned pages that stayed without text (OCR off or not installed): say
"Scanned: no text. Ask IT to install Tesseract to read it." A wholly scanned PDF without OCR is also in
`empty_files` and is not added.

`GET /api/projects/<p>/documents/<doc_id>?offset=0&limit=50` → document details with its passages:
`{"doc_id", "title", "file_title", "file", "kind", "n_pages", "n_chars", "doi", "added_at", "total_passages", "offset",
"passages": [{"passage_id", "seq", "page", "section": "body"|"references"|"reference_like"|"unreadable", "text"}]}`.
With `&view=blocks` (use `limit=500`) it adds the document as a reader cites it: `"blocks": [{"label": "Page 2,
paragraph 3" | "Paragraph 6" | "Page 2" | "The whole text", "n", "page": 2 | null, "paragraph": 3 | null, "start",
"end", "text", "headings": [{"at", "end", "text"}]}]` and `"total_blocks"`. PDFs added from 0.6 on are cited by
paragraph within each page; PDFs added earlier by page; files without pages by paragraph. `start`/`end` are
document offsets of `text`, so a quote at `doc_start + quote_start` (from a result) falls in the block whose range
contains it, at `doc_start + quote_start - start` in its `text`. `headings` are the block's heading lines (offsets
in `text`): show them as headings (bold). The detail also has `"original": {"available": true, "name":
"report.pdf", "reason": ""}` (see below).

`GET /api/projects/<p>/documents/<doc_id>/file` (also `?token=`, for a plain link) → the original file, as the
reader knows it: a PDF inline (`application/pdf`; link to `…/file?token=…#page=3` to open it at a page), a web page
as `text/html` with `Content-Security-Policy: sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src
data:` (no scripts, nothing from the internet, and it cannot reach the app), a text file as `text/plain`. Only the
file recorded when the document was added is served. When it is no longer there (or changed since), the response
is `text/plain` starting with the reason ("The original file is no longer at …; the text the app read is shown
here.") followed by the text the app read. `?check=1` → `{"doc_id", "kind", "name", "available", "reason"}` without
the file: use it to show "Open the original" only when `available`, and the `reason` otherwise.

Opening it at the quote: for a PDF add `#page=N`; for a text file add `&quote=<the quote>` and `#quote`: the file is
then shown as a page with the quote highlighted (found as quotes are), scrolled to it (no script; the same sandbox
policy as web pages; without a match the plain file is sent); for a web page add a text fragment,
`#:~:text=<first words>,<last words>` (browsers that support it scroll to and highlight that text).

**0.15: how a document was read, and the reading view.** The detail adds `"reader"` (1: read before 0.15; 2: the new
reader), `"new_reader"` (the reader new documents get), `"reading"` (the reading report: `{"reader", "engine":
"pdfminer"|"pypdf"|"text", "pages", "pages_with_text", "ocr_pages", "scanned_pages", "multi_column_pages",
"repairs": {"hyphens_joined", "hyphens_kept", "words_split", "ligatures", "spaces", "accents"}, "tables", "blocks":
{kind: n}, "left_out_chars": {kind: n}, "included_share", "passages", "body_passages", "unreadable_passages", "words",
"warnings": [sentence], "quality": "good"|"fair"|"poor"}`; for a document read before 0.15 `{"reader": 1, "older":
true, "pages", "ocr_pages", "scanned_pages", "passages", "body_passages", "unreadable_passages", "warnings": [],
"quality": null}`), `"page_images"` (a picture of each page can be had), `"tables"` and `"paragraphs"` (counts).
With `&view=blocks`, a document read by the new reader comes block by block in reading order (`limit` up to 1000):
each block adds `"kind"` (`title`, `heading`, `abstract`, `body`, `caption`, `table`, `footnote`, `front`, `back`,
`references`, `figure`, `furniture`), `"kind_text"` (in words), `"included"` (searches, codes, themes and checks read
it), `"changed"` (a person restored or left it out), `"box"` (`[x0, top, x1, bottom]` on the page in points from the
top left, or null) and, for a table, `"table": {"n", "caption", "rows": [[cell]]}`. `label` is "Page 2, paragraph 3"
where a paragraph begins, empty where the paragraph above goes on (under its heading, or across a column), and the
kind in words for a block left out. Passages add `"block"` (the kind of block they were made from; null for reader 1),
and their `section` may be `"left_out"`.

`PUT /api/projects/<p>/documents/<doc_id>/blocks/<n>` `{"included": true|false, "alike": false}` → *Restore* or
*Leave out* a block: `{"blocks": [block], "group": [n], "together": n, "alike": n, "doc": {...}}`. `group`: the blocks
chosen (those sharing a passage with it change together). `blocks`: every block that changed, as `?view=blocks` lists
them now, wherever they are in the document (0.16: the first 1000 blocks of the group only before); since a choice is
kept by the block's words, that includes blocks elsewhere with the same words. `doc`: the reading's figures now
(`left_out`, `passages_read`, `passages_all`, as the document's own answer has them), so the reading view shows the
change in place. The choice is kept by the block's words (`block_choices`) and applied again when the document is
read again; choosing what the reader chose (and the start and end marks below imply) removes it. 0.15.1: with
`"alike": true`, every block that looks the same (blocks of up to 200 characters, their numbers and roman numerals
aside: a running head, a page number) changes too; `alike` in the answer is how many. 404 for no such block, 400 when
`included` or `alike` is not a boolean.

`PUT /api/projects/<p>/documents/<doc_id>/bounds` (0.15.1) `{"side": "start"|"end", "block": n|null}` → *Text starts
here* or *Text ends here* at block `n` (`null`: undo): what comes before the start, or after the end, is left out; a
block the person restored there still counts. Kept in `block_choices` as `<side>:<fingerprint>:<k>` (the k-th block
with those words), so it holds when the document is read again. `{"side", "block", "changed", "left_out",
"restored", "blocks", "doc"}`: 0.16: `blocks` are the blocks that changed and the blocks that carry or carried the
mark, as `?view=blocks` lists them now; `doc` as above. 400 for another side, a start after the end (or an end before the start), or a block that is not a
number; 404 for no such block, or a document without blocks (read before 0.15).

In `?view=blocks` (0.15.1), each block also has `alike` (how many other blocks look the same), `share` (where it
stands in the document, 0 to 1) and `bound` (`"start"`, `"end"` or null); `changed` is also true for a block with a
choice of its own.

`GET /api/projects/<p>/documents/<doc_id>/pages/<n>.png?scale=1.5` (also `?token=`, for an `<img>`) → page `n` of the
original PDF as a PNG (`scale` 0.5 to 3 times 72 dots per inch), drawn with pypdfium2 (the OCR extra); 404 with the
reason when the original is missing or not a PDF, the extra is not installed, or there is no such page. A block's
`box` times `scale` is its place in pixels.

`GET /api/projects/<p>/documents/<doc_id>/tables/<n>.xlsx` → a table the reader found, for Excel: its caption, where
it comes from, then its rows (cells that read as numbers are numbers).

`GET /api/projects/<p>/documents/<doc_id>/reread` → whether the document can be read with the new reader now and what
that would do, changing nothing: `{"ok": false, "reason", "reader", "new_reader", "doc_id", "title"}` when it cannot
(read by the new reader already, the original missing or changed, a task of it waiting or out with Claude Code, almost
no text in the new reading), otherwise the report: `{"ok": true, "moved": false, "doc_id", "title", "reader",
"new_reader", "counts": {kind: {"moved", "not_placed", "left_out"}}` (kinds: `check`, `judgement`, `second_opinion`,
`label`, `claim`, `sdg_check`, `theme_member`), `"not_placed": [{"kind", "kind_text", "what", "quote", "page", "where",
"left_out_kind", "why"}]` (page in the old reading), `"left_out": [{… "note"}]` (placed, in text the new reader leaves
out; page in the new reading), `"remade"`, `"tasks": {"asked_again", "moved", "kept_as_records"}`, `"themes":
{"runs_kept_up_to_date", "runs_out_of_date", "runs"}`, `"passages": {"before", "after", "one_to_one", "body_before",
"body_after"}`, `"ai_share": {"before", "after"}`, `"addons": [{"table", "rows"}]`, `"reading"` (the new reading
report), `"warnings": [sentence]}` (`reread.py`). `POST …/reread` → `{"job"}` (kind `reread`): the move in one
transaction (all or nothing), then the document's search by meaning, the glossary and the keyword pass, as after adding
a document; the job's result is `{"report": {… "moved": true}, "glossary", "codes", …}`. 409 with the reason when it
cannot be done. 0.17.0: while another job of the project runs, the move waits its turn (`waiting_for`) instead of a 409;
the same document asked for again returns the job already there. A move that finds, once its turn comes, that it can no
longer be done ends with `error_kind: "request"` and the reason; nothing changed.

`POST /api/projects/<p>/new-reader` `{"doc_ids"?: [doc_id]}` (0.15.7) → `{"job"}` (kind `new_reader`): the documents an
earlier reader read (only those of `doc_ids`, when given; others are ignored) moved one after the other, each as `POST
…/reread` does, but only when every result finds its place (`reread.move(keep_all=True)`); then, once, search by
meaning, the glossary and the keyword pass. The job's result is `{"moved": [{"doc_id", "title", "results",
"left_out"}], "kept": [{"doc_id", "title", "reason", "not_placed"?}], "stopped", "glossary", "codes", …}`: `kept` are
left as they were, `not_placed` (how many results would have had no place) when that is the reason. Stopping it keeps
the documents moved so far. 400 for `doc_ids` that is not a list; 409 when none is left to move. 0.17.0: while another
job of the project runs, it waits its turn (`waiting_for`) instead of a 409. 0.18.0rc2: `{"keep_unplaced": true}` (the person's *Move anyway*) moves a document even when some results find no
place: those are kept as records that point nowhere, as a move from the document's own page does
(`reread.move(keep_all=False)`). `moved` entries also give `no_place`, `kept` entries `cannot: true` when the document
cannot be read again now, and the result has `summary`: `{"moved", "left_as_they_were", "results_moved",
"results_without_place", "moved_anyway"}`. The list of documents (`GET …/documents`) gives `new_reader`
(`ingest.READER`) beside each document's `reader`.

`POST /api/projects/<p>/new-reader/preview` `{"doc_ids"?: [doc_id]}` (0.18.0rc2) → `{"job"}` (kind
`new_reader_preview`): the dry run before moving several documents; same `doc_ids` rules, errors and 409 as the move.
Each document is read again by the current reader (`reread.preview`; nothing is stored or changed). The job's result is
`{"documents": [{"doc_id", "title", "ok", "reason", "results", "no_place", "left_out", "not_placed": [{"kind_text",
"what", "quote", "page", "where", "left_out_kind", "why"}]}], "stopped", "summary": {"documents", "clean",
"would_lose", "cannot", "results_without_place"}}`: `clean` documents move with every result in place, `would_lose`
documents have `no_place` results that would find none, `cannot` documents cannot be read again now (`reason`).

`PUT /api/projects/<p>/documents/<doc_id>/reading-checked` `{"checked": bool}` (0.15.7) → `{"checked": {"by", "name",
"at"} | null}`: the person marks the reading as checked (or takes it back). It is kept in the reading report, so a new
reading asks again; the list of documents gives `reading_checked` beside `reading_quality`. 400 for a `checked` that is
not true or false; 404 for no such document; 409 for one read before 0.15 (it has no reading report). The document's
`reading` also has `places` (0.15.7, not stored): for each warning, `"page"`, `"left_out"` or null, where to look.

`DELETE /api/projects/<p>/documents/<doc_id>[?why=<reason>]` → `{"removed": {...counts}}` (past checks keep their
evidence; 0.16: the reason, up to 2,000 characters, goes into the research log, as `{"why": "…"}` in the body does;
the project's notes on the document are kept).
`DELETE /api/projects/<p>/documents` `{"confirm": true}` → removes every document **and every check**.

#### Who may read each document with AI (0.11)

Every document has one of three settings: `cloud` (Claude may read it: the chosen route), `local` (only a model
server on this computer, or a person) and `none` (a person only). A document without its own setting follows the
project's default. The setting is enforced where tasks are made and run (see `access.py`), never by a prompt.

- `GET /api/projects/<p>/documents` adds to each document `ai_access` (the setting that applies now), `own` (its own
  setting, or null for the project's default), `note`, `budget` (a cap in percent, or null), `budget_reached`,
  `sent` (the share of its text Claude has read, 0 to 1) and `sent_passages`; and to the answer `ai_access`
  (`{"default", "chosen", "ask", "banner", "counts": {"cloud", "local", "none"}, "local_only", "ledger_since"}`) and
  `restricted_model` (the local model for restricted documents, `{}` for none). `GET /api/projects/<p>` has the same
  `ai_access` block. `ask`: the project's default was never chosen (made before 0.11 and imported, or through the
  connector): ask once. `banner`: the one-time note of an existing project.
- `PUT /api/projects/<p>/documents/ai-access` `{"doc_ids": [...], "ai_access": "cloud"|"local"|"none"|null,
  "note": "…", "budget": 10|""}` (each key optional; `ai_access` null returns them to the default; `budget` "" removes
  the cap) → `{"documents": n, "tasks_changed": n, …the documents answer}`. Tasks not answered yet take the new
  setting at once; a queued one that is no longer `cloud` leaves the queue. 400 for an unknown setting, 404 for an
  unknown document; `cloud` is refused on a `--local-only` installation.
- `PUT /api/projects/<p>/ai-access` `{"default": "cloud"|"local"|"none"}` and/or `{"dismiss_banner": true}` →
  `{"ai_access": {…}}`.
- `POST /api/projects/<p>/ingest` takes `ai_access` (who may read the new documents; the first answer in a project
  becomes its default) and `ai_note`. A `manifest.csv` may have `ai_access` and `ai_note` columns per file; an unknown
  value is listed under `manifest_problems`.
- `GET /api/projects/<p>/documents/<doc_id>/ai-sent` → what Claude has read of a document: `{"doc_id", "share",
  "since", "passages": [{"passage_id", "seq", "page", "preview", "times", "first", "last", "features", "routes"}]}`.
- `GET /api/projects/<p>/ai-sent.csv` (also `?token=`) → the ledger: one row per passage sent (Sent at, Route,
  Feature, Document, Document id, Passage id, Page, Task).
- `POST /api/projects/<p>/hypotheses/<hyp_id>/read-local` → job (kind `read-local`): the excerpts of the check that
  wait for the local model (made in a Claude chat, or while the app was closed) are read by it; without one they wait
  for a person. `result`: `{"hyp_id", "parts", "status"}`. 0.13.11: the job has a check's `progress` (the local
  model's line carries `"who": "local"` and `name`); when this computer has too little memory free for the model it
  ends in `error_kind: "memory"` and the excerpts keep waiting. Body `{"force": true}` starts the model anyway (the
  page's *Start it anyway*).
- `/api/state` adds `restricted` (as `restricted_model` above). Settings: `restricted_server` (`""`, `ollama`,
  `openai`), `restricted_model`, `account_type` (`""`, `personal`, `commercial`).
- The result of a check: each excerpt has `read_by` (`claude`, `local`, `ai`, `you`, `waiting`), `access` (its
  document's setting), `waiting_for_you` (no model may read it and no person has judged it) and `waiting_local`; each
  round in `rounds_info` has `parts` (`[{"task_id", "read_by", "passages", "status"}]`); parts and hypotheses count
  `waiting_for_you` and `waiting_local`. A round's excerpts are split into the task Claude reads (`check:<id>` or
  `…:r<n>`), the local model's (`…:local`) and a person's (`…:person`, answered by no model); it is shown as one round.
  Reading an excerpt again (`POST …/reread/…`) is refused with 409 when no model may read its document.

`POST /api/projects/<p>/index` → job (kind `index`) that embeds passages without a vector; progress `{"done", "total"}`;
result: the `search` state plus `added` and `remaining`; 400 when no embedding model is set.

`GET /api/projects/<p>/passages/<passage_id>?around=1` → a passage with its neighbours, for "show in context":
`{"passage_id", "doc_id", "title", "page", "passages": [{"passage_id", "page", "text", "section", "current": bool,
"start", "breaks"}]}` (404 when the document was removed since; `breaks` as on excerpts, below).

### Frameworks (optional codebooks)

`GET /api/projects/<p>/frameworks` → `{"frameworks": [info], "problems": [{"file", "source", "error"}]}` (always includes
`sdg`; `problems` lists codebook files in the folders that could not be used, with the reason). A CSV may be separated by
commas, semicolons or tabs.
`GET /api/projects/<p>/frameworks/<name>` → `{"framework": {...info, "items": [{"code", "description", "group", "group_name"}]}}`.
`POST /api/projects/<p>/frameworks` `{"name": "h2", "csv": "code,description\nH1,…", "title": "…", "label": "hypothesis code"}`
→ `{"framework": info}`; 400 with the row problem. `DELETE /api/projects/<p>/frameworks/<name>`.
0.16: the Codebooks page uses the routes under *Your record* below; these four stay.
`GET /api/projects/<p>/suggest?text=<claim>&framework=sdg&n=5` → `{"codes": [{"code": "6.4", "group": "6",
"description": "…", "score": 16.9}]}` (keyword match; empty for texts under 10 characters).

### Checking

`POST /api/projects/<p>/checks`
```json
{"text": "Green hydrogen production increases water stress in arid regions.",
 "framework": "sdg", "code": "6.4",          // optional
 "decompose": false, "expand": true,         // defaults from settings
 "k": 8, "per_doc": 2,                        // passages to read per claim; at most this many per document first
 "doc_ids": ["d…"],                           // optional: only these documents
 "semantic": true,                            // use the semantic index when the project has one
 "second_pass": false,                        // default from settings (see below)
 "parts": ["…", {"text": "…", "role": "outcome"}],   // optional, from "Look before checking": the parts to check
 "terms": [["aquifer", "desalination"], []],  // optional: the extra search words, one list per part
 "edited": {"parts": false, "terms": true}}   // optional: whether the person changed what the AI proposed
```
→ `{"job": Job}` (kind `check`). 400 for a text under 10 characters or an unknown code (or a part under 10
characters: "Part 2 is too short…"); 502 when no model service is usable. The job's `result` is
`{"hyp_id": "h…", "status": "contested"}`.

With `parts`, the hypothesis is not split by the model: one part = checked as written (1–6 parts). With `terms`, the
model writes no extra search words: each part is searched with its own words plus that list (`[]`: its own words
only); a flat list is the list of a hypothesis checked as one part. The hypothesis's `options.prepared` records
`{"parts": bool, "terms": bool, "edited_parts": bool, "edited_terms": bool}`.

`second_pass`: after the keyword (and meaning) search, the best 3 × k candidates are sorted again, without any
model, by how closely they word the hypothesis (the best sentence's share of its words, weighted by how rare they
are, and its word pairs found side by side), in steps of 0.1 so the first order decides between equals. Recorded as
`options.second_pass`. On the pilot (178 VCA claims with cited sources, `tools/eval_second_pass.py`) it brought
slightly fewer excerpts from the cited sources into the top 8 (147 against 154), so it is off by default.

#### Look before checking

`POST /api/projects/<p>/prepare` `{"text": "…", "decompose": true, "expand": true, "framework", "code"}` → job
(kind `prepare`, uses the model, progress like a check). `result`:
```json
{"parts": [{"text": "Hybrid work improves wellbeing.", "role": "outcome"}, {"text": "…", "role": "outcome"}],
 "terms": [["well-being", "life satisfaction"], ["isolation", "younger workers"]],
 "split": true}
```
`terms` are the AI's extra search words for each part (the part's own words are always searched, so they are left
out). Nothing is kept in the project. Show the parts as editable lines and the words as removable chips, then send
the check with `parts`, `terms` and `edited`.

Check job `progress` (poll it to draw the live panel):
```json
{"message": "Reading 8 passages with qwen3:8b", "elapsed": 23.4,
 "decompose": null | {"label": "Splitting into claims", "state": "running"|"done", "detail": "3 claims to check",
                      "seconds": 3.2, "parts": ["…", "…"]},
 "parts": [{"part": 1, "text": "…" | null,
            "steps": [{"key": "terms", "label": "Search terms", "state": "pending"|"running"|"done",
                       "detail": "9 search terms: …", "seconds": 2.3, "info": {"terms": […]}},
                      {"key": "rank", "label": "Passages", …, "info": {"passages": 8, "documents": 5}},
                      {"key": "grade", "label": "Reading and grading", …, "info": {"graded": 3, "ok": true}}]}],
 "model": null | {"phase": "waiting"|"thinking"|"writing"|"done", "seconds": 12.0, "prompt_tokens": 2700,
                  "thinking_tokens": 0, "answer_tokens": 140, "rate": 11.7, "cap": 1500, "thinks": false,
                  "tail": "latest words the model wrote", "line": "Model is writing its answer · 12 s · 140 answer tokens · 11.7 tokens/s"},
 "batch": null}
```
`parts` grows as the check moves on (one entry per claim checked so far; `part` 0 = the hypothesis as written).
The `terms` step is absent when `expand` is false. `model` is filled by local servers while they stream.

`POST /api/jobs/<id>/cancel` → stops the job (a stopped check leaves nothing in the history).

The check prompt is `check-v3`: for each excerpt the AI may add a `scope_note`, a short phrase such as "about
fully remote workers, not hybrid", when the excerpt is about another group, setting, place or period than the
hypothesis names; such an excerpt supports it at most partly (the app applies that rule when it stores the answer).
No extra model call. Excerpts read with `check-v2` (0.5) have no note.

`POST /api/projects/<p>/claims/<claim_id>/more` `{"k": 8, "terms": ["repurposing", "pipeline reuse"]}` → job
(kind `more`): reads the next best passages for one claim (none shown before), with new search terms if given, and
grades them as a further round. `result`: `{"claim_id", "hyp_id", "round": 2, "passages": 8 | 0, "ok": true}`
(`passages: 0` = nothing further matches).

Batches: `POST /api/projects/<p>/batches/preview` `{"text": "…"}` → `{"items": [{"text", "framework", "code"}], "count"}`.
`text` is one hypothesis per line (lines starting with `#` skipped) or CSV with a column `hypothesis` (or `claim`,
`text`, `statement`) and optional `framework`, `code` (or `target`). At most 500.
`POST /api/projects/<p>/batches` `{"text": "…"}` or `{"items": […]}`, plus the check options → job (kind `batch`).
Batch job `progress` is the check progress of the current hypothesis plus
`"batch": {"index": 3, "total": 12, "text": "…"}`. `result`:
`{"batch_id": "b…", "checked": ["h…", …], "errors": [{"index", "text", "error"}], "stopped": null | "message", "total": 12}`.
`GET …/hypotheses?batch=<batch_id>` lists that batch, in the order the hypotheses were given.

Near-duplicates (0.18, roadmap N1; `nearduplicates.py`, by key words, no AI):
`POST /api/projects/<p>/hypotheses/similar` `{"lines": ["…", "…"]}` (at most 500) →
```json
{"pairs": [{"a": 0, "b": 1, "score": 0.75, "differ": []},
           {"a": 1, "b": 2, "score": 1.0, "differ": ["indicate", "predicted"]}],
 "before": [[{"hyp_id": "h…", "text": "…", "created_at": "2026-11-03T10:12:00+00:00", "score": 0.8, "differ": [],
              "who": {"id": "p…", "name": "Anna", "mine": false}}], []]}
```
`pairs`: lines of the list (0-based) that say nearly the same; `differ` names the words that make them claim different
things (strength, direction, a negation), and then the page offers no merge. `before`: per line, the hypotheses checked
before in the project that say nearly the same and claim the same (the closest first, at most 3): yours (`mine`) or a
colleague's that came in through sync (`name`; `who` is null when the project does not know who checked it). A
colleague's check they took back (withdrawn) is left out.

### Results

`GET /api/projects/<p>/hypotheses?threshold=0.6&q=<words>&status=<status>&batch=<id>&limit=<n>` →
```json
{"hypotheses": [{"hyp_id": "h…", "claim_id": "…", "created_at": "2026-10-27T21:26:09+00:00", "text": "…",
                 "framework": "", "code": "", "status": "contested", "status_any": "contested",
                 "supports": 2, "partly": 2, "refutes": 2, "uncounted": 1, "corrected": 0, "reviewed": 3, "to_review": 5,
                 "docs_supporting": 2, "docs_partly": 1, "docs_refuting": 1, "passages_read": 8, "parts": 2,
                 "model": "qwen3:8b", "batch_id": "", "lean": 0.4, "code_label": "", "note": ""}],
 "counts": {"contested": 2, "unsupported": 1}, "threshold": 0.6}
```
newest first; `counts` cover the whole project (not the filter). 0.6 adds `docs_added_since` (documents added to the
project since the check that it has not read from: tag "documents added since") and `disagreements` (excerpts
where a second opinion differs from the AI's judgement: tag "second opinion differs on N"). 0.11.2 adds
`status_before_stronger`: the answer the first model gave when a stronger model read excerpts again and changed it
(else null). `supports`/`partly`/`refutes` count the excerpts whose
judgement counts at this threshold, `uncounted` those below it; `docs_*` count documents as the result page does;
`reviewed` counts the excerpts you judged (agreeing or not), `corrected` those where you changed the AI's judgement,
`to_review` the excerpts read that you have not judged yet (0.14.3: your own judgements, not a colleague's, as on the
result and in Excel).
`status_text` is null, or the words for a status that says more than its code: *Waiting for your local model*, or
(0.14.3) *Waiting for your judgement*.

`GET /api/projects/<p>/hypotheses/<hyp_id>?threshold=0.6` (404 when there is no such result; 0.14.3: the answer then
carries `"in_project": "<name>"` when another project holds it, as happens when another window switched the project) →
```json
{"hyp_id": "h…", "text": "…", "framework": "sdg" | null, "code": "6.4" | null,
 "code_description": "…", "code_label": "SDG target",           // present with a code
 "created_at": "…", "options": {"k": 8, "per_doc": 2, "expand": true, "decompose": true, "doc_ids": [],
                                "backend": "ollama", "model": "qwen3:8b", "search": "keywords+meaning", "embed_model": "…"},
 "decomposed": true, "model": "qwen3:8b", "batch_id": null, "note": null | "user's note", "threshold": 0.6,
 "status": "contested", "status_any": "contested", "status_text": "Mixed evidence",
 "balance": {"docs_supporting": 2, "docs_partly": 1, "docs_refuting": 1, "docs_both": 1, "docs_counted": 3,
             "excerpts_uncounted": 2, "lean": 0.42},
 "who": [{"doc_id": "dab…", "title": "…", "side": "supports" | "partly" | "refutes", "excerpts": 2,
          "locations": ["paragraph 6 of 8"], "both_sides": false}],
 "documents_in_project": 6, "passages_in_project": 31, "excerpts_read": 16,
 "reviewed": 3, "corrected": 1, "to_review": 13, "to_review_relevant": 5,
 "incomplete": false,                      // a part failed or is not graded yet (not: it waits for your judgement)
 "models_used": [{"model": "sonnet", "roles": ["search words", "judging the excerpts"]},
                 {"model": "opus", "roles": ["judging again as the stronger model"]}],   // 0.14.3
 "rationale": "…" | null,                  // the model's summary (single-part hypotheses)
 "parts": [{
    "claim_id": "u…", "hyp_id": "h…", "part": 1, "role": "outcome" | null, "claim": "…",
    "status": "supported", "status_any": "supported", "balance": {…}, "rationale": "…" | null,
    "terms": ["…"], "model": "qwen3:8b", "rounds": 1, "round_status": "done", "errors": [],
    "target": "6.4" | null, "target_description": "…", "threshold": 0.6, "options": {…}, "created_at": "…",
    "passages": [{"n": 1, "round": 1, "passage_id": "dab…:0001", "doc_id": "dab…", "title": "…", "page": 2 | null,
                  "text": "full passage text", "found_by": "keywords" | "meaning" | "both",
                  "verdict": "supports" | "partially_supports" | "refutes" | null, "confidence": 0.82 | null,
                  "quote": "…" | null, "quote_start": 31 | null, "quote_end": 97 | null, "in_corpus": true}]
 }]}
```
Each passage also has: `ai_verdict` (the AI's own grade or null), `user_verdict` (`supports`, `partially_supports`,
`refutes`, `not_relevant` or null) and `user_note`, `verdict` (the one that counts: the person's if given),
`counted` (true when it counts at this threshold), `certainty` ("high" ≥ 0.8, "medium" ≥ 0.6, "low"), `reviewed`
(a person judged it) and `changed` (their judgement differs from the AI's), `location` (where the quote is: "page 2",
"paragraph 6 of 8"; without a quote, the excerpt's span; documents stored before 0.5.1: "about 40% into the
document"), `span` (what the whole excerpt covers: "paragraphs 1–6 of 8", "pages 2–3"), `doc_start` (the document
offset where the excerpt starts), `position_pct`, `quote_by` ("the AI", "you" when the person chose the sentence, or
null) and `ai_quote` (the AI's own quote). Each part also has `who` and `balance`. Each part has
`rounds_info`: `[{"round", "status", "passages", "terms": [words searched for in that round], "ai_note": "the AI's own
note on that round's excerpts"}]`, and (this endpoint only) `more_available`: false when "read more" would find
nothing new. `who` lists the documents behind the answer by side, with the same rule as `balance` (a document with
counted excerpts both for and against appears twice, `both_sides: true`). `to_review_relevant` counts the AI's
judgements for or against that you have not reviewed yet. 0.14.3: the hypothesis's `reviewed`, `corrected`,
`to_review`, `to_review_relevant` and `disagreements_to_review` count your own judgements (the Excel columns say "you"; in a shared project a colleague's judgement counts in the
answer where you made none, but it is not yours). `models_used` lists every model whose accepted answers the check
used, in the order they first answered, with what each did (from the answers themselves: a stronger model, the local
model for restricted documents, a model changed in Settings before Claude Code answered); `model` stays the one chosen
when the check started. Each passage has `ai_read`: false when no model's judgement of it is stored (an excerpt no
AI may read, or one whose part waits or failed); `round_failed`: its round's check failed, so no AI judgement of it
counts (`counted` false; a person's own counts only when another round of the check was answered); and `my_verdict`:
your own verdict (null when you gave none). In a shared project the verdict in force (`user_verdict`) may be a
colleague's while `user_note` is your comment: a client that saves your comment sends `my_verdict` with it, never
`user_verdict`, or the colleague's verdict would be saved as yours.
New in 0.6, on each passage:
- `breaks`: `[{"at": 82, "kind": "paragraph"}, {"at": 120, "kind": "heading", "end": 127}]` (offsets in `text`):
  where a new paragraph or a heading begins inside the excerpt, from the layout found when the document was added.
  Start a new paragraph at each `at`; show `text[at:end]` of a heading as a bold line. Empty for documents added
  before 0.6 (show the text as one block, as before).
- `location` / `span` for PDFs added from 0.6 on: "page 2, paragraph 3" / "page 2, paragraphs 1–4" or "pages 2–3".
- `scope_note`: the AI's note that the excerpt is about another group ("about fully remote workers, not hybrid"),
  or null. Show it as a chip: "About another group: …".
- `reread` (bool) and `ai_history`: `[{"verdict", "confidence", "quote", "scope_note", "model", "at",
  "replaced_at"}]`, oldest first: the AI's earlier judgements of this excerpt, when it was asked to read it again.
  `ai_verdict` / `confidence` / `quote` are its latest. Show "Read again by the AI: was Supports (75%), now Partly
  supports (59%)". `reread_info` (null, or `{"hint", "rationale", "model", "at"}`) is about the latest re-read: the
  person's comment given as a hint (null: none) and the AI's reason, which says whether the hint changed its
  judgement. Show the reason with the new judgement.
- `second`: null, or the second model's judgement `{"model", "verdict" (null = not about the hypothesis),
  "confidence", "quote", "scope_note", "at", "agrees"}`; `agrees` compares it with the main AI's own judgement
  (`ai_verdict`). Show "Second model: Contradicts (70%), disagrees".

Each part also has `disagreements` (excerpts where the two models disagree). The hypothesis has `second_models`
(the second models that read it), `second_read` (excerpts with a second judgement), `disagreements`,
`disagreements_to_review` (of them, not reviewed by a person yet: send "Next to review" there first),
`docs_added_since` (`[{"doc_id", "title", "added_at", "matching"}]`: documents added to the project after the check
that none of its rounds read from; `matching` = it has an excerpt that shares a word with the hypothesis) and
`docs_added_since_matching`. Say "2 documents were added since this check; 1 has matching excerpts. Read them."

`passages` are sorted: supports, partly, refutes (counted ones first, each by confidence), then the ones with no grade. Highlight
`text[quote_start:quote_end]` (character offsets into `text`). A grade with `confidence < threshold` is shown but
marked weak ("below the threshold"). `in_corpus: false` = the document was removed since (no "show in context").
`errors` lists why grading failed (status `failed`).

`PUT /api/projects/<p>/claims/<claim_id>/judgements/<passage_id>` `{"verdict": "refutes", "note": "the next sentence
says the opposite", "quote": "Loneliness did not rise among hybrid workers of any age."}` → `{"saved": true}`: the
person's own judgement of one excerpt (`supports`, `partially_supports`, `refutes`, `not_relevant`; `null` removes it,
with its sentence, and the AI's counts again). Agreeing with the AI = sending the AI's own verdict (`not_relevant`
for an excerpt it found not about the hypothesis). `quote` (optional) is the sentence the judgement rests on: text of
this excerpt (400 otherwise); left out, an earlier one is kept; `""` removes it. From 0.6, `{"verdict": null,
"note": "…"}` keeps only a comment: it is not a judgement (`reviewed` stays false, the AI's judgement counts, and it
is not counted as agreeing with the AI). "Go back to the AI's judgement" with the comment kept is `{"verdict": null,
"note": "<the comment>"}`; `{"verdict": null}` removes both.

`POST /api/projects/<p>/claims/<claim_id>/reread/<passage_id>` `{"note": "…"}` (optional) → job (kind `reread`):
the AI reads this one excerpt again, alone, with the check prompt. The person's comment (`note`; left out: the
comment saved with their judgement, if any) is added as a hint ("A reader noted: …"). The new judgement replaces the
AI's for this excerpt and the earlier one goes to `ai_history`; a person's own judgement is not changed and still
counts. `result`: `{"claim_id", "passage_id", "hyp_id", "ok", "before": {"verdict", "confidence"}, "after":
{"verdict", "confidence", "scope_note", "rationale"} | null}`. 404 when the excerpt was not read for this claim.

`POST /api/projects/<p>/hypotheses/<hyp_id>/read-new` → job (kind `read-new`): reads the documents added since
the check (those with matching excerpts), for every part, as a further round restricted to them; the check is not
run again, so reviews are kept. Documents without a matching excerpt are only marked as looked at, so the
hypothesis no longer counts them. `POST /api/projects/<p>/read-new` `{}` (every hypothesis with documents added
since), `{"hyp_ids": […]}` or `{"batch": "b…"}` → one job that does this for each, one after the other (400 when
none has new documents). `result`: `{"hypotheses": [{"hyp_id", "documents", "matching", "passages", "rounds"}],
"passages"}`.

`GET /api/projects/<p>/hypotheses/<hyp_id>/unread` (roadmap N5, 0.18.7) → the documents this check never showed an
excerpt of, asked again of the keyword search with each part's claim and search words (no model reads anything):
`{"hyp_id", "checked": false before the check read anything, "considered": documents it could have read,
"matching": [{"doc_id", "title"}] (an excerpt holds at least two different words of a part and its search words),
"matching_n", "one_word_n" (single words in common only), "no_word": [{"doc_id", "title"}], "no_word_n"}`; each list
sorted by title and cut at 200 (the counts are whole). Theory documents, documents added after the check (its
documents added since), documents with no readable text and those a limited check was limited away from are left
out. A neutral count: it changes no result. `POST /api/projects/<p>/hypotheses/<hyp_id>/read-unread` → job (kind
`read-unread`): reads the `matching` group for every part (each part the documents that hold its own words, within
its limit) as a further round limited to them, as `read-new` does; the check is not run again, so reviews are kept.
400 when there are none. `result`: `{"hyp_id", "documents", "passages", "rounds": [{"claim_id", "round", "passages",
"ok"}]}`.

`POST /api/projects/<p>/second-opinion` `{"hyp_ids": […]}` or `{"batch": "b…"}` → job (kind `second-opinion`): the
second model of Settings (`second_model`) grades every excerpt these checks already read, with the same prompt. Its
judgements are kept apart (`second` on each excerpt) and never change an answer. Only one model is in memory at a
time: the main model is unloaded first and the second one at the end (Ollama; LM Studio and other
OpenAI-compatible servers have no standard way to unload, so the server's own setting decides there). Excerpts the
second model already graded are not asked again. 400 when no second model is chosen or it is the main one; 502 when
it is not installed. `result`: `{"hypotheses", "rounds", "graded", "skipped", "failed", "unloaded": ["qwen3:8b",
"llama3.1:8b"]}`, counted in rounds of excerpts (`skipped`: rounds this second model had already graded).

The progress of the shorter model jobs has only the steps they make: `prepare` the "terms" step (and `decompose`),
`reread` and `second-opinion` the "grade" step.

#### Evidence map

`GET /api/projects/<p>/map?batch=&threshold=` →
```json
{"threshold": 0.6,
 "hypotheses": [{"hyp_id": "h…", "text": "…", "status": "supported", "status_text": "Supported by your documents",
                 "docs_counted": 1, "single_document": true, "batch_id": ""}],
 "documents": [{"doc_id": "d…", "title": "…", "answers": 2, "decides": 2, "key": true, "in_project": true}],
 "cells": {"h…": {"d…": {"side": "supports" | "partly" | "refutes" | "both", "excerpts": 2}}},
 "documents_without_evidence": 3}
```
Cells follow the rule of `who` (judgements that count at this strictness; a person's always count): `both` = the
document has counted excerpts for and against. `single_document`: the answer rests on one document. A document
`decides` an answer when leaving out its excerpts would change that answer; `key` = it decides at least two answers
and at least a fifth of them. `documents` lists only documents with counted excerpts (most answers first);
`documents_without_evidence` counts the others. Draw a grid with symbols as well as colours (+, (+), −, ±).

#### Calibration

`GET /api/projects/<p>/calibration` →
```json
{"bins": [{"from": 0.0, "to": 0.5, "judged": 0, "agreed": 0, "rate": null},
          {"from": 0.5, "to": 0.6, …}, {"from": 0.6, …}, {"from": 0.7, …}, {"from": 0.8, …}, {"from": 0.9, "to": 1.0, …}],
 "total": 34, "agreed": 27, "minimum": 20, "threshold": 0.6,
 "suggestion": {"threshold": 0.7, "reason": "When the AI was at least 70% sure, you agreed with it in 85% of the 26
                excerpts you judged."} | null,
 "note": "" | "Judge at least 20 of the AI's judgements to get a suggestion (12 so far)."}
```
From the excerpts a person judged that also have an AI judgement for or against: how often they gave the same
judgement, by the AI's certainty (marking an AI "supports" as not about the hypothesis is a disagreement). A comment
alone is not a judgement. For an excerpt the AI was asked to read again, its first judgement is compared (the
later ones may follow the person's own hint). The
suggestion is the lowest strictness from which on agreement is at least 80% (starting at a bin with at least 3
judgements), once at least 20 were judged. Show it next to the strictness: a small chart and "Use 70%".

`DELETE /api/projects/<p>/hypotheses/<hyp_id>[?why=<reason>]` → `{"deleted": "h…"}` (0.16: `why` as for a document).
`PUT /api/projects/<p>/hypotheses/<hyp_id>/note` `{"note": "…"}` → `{"saved": true}`.
`GET /api/projects/<p>/hypotheses/<hyp_id>/export.xlsx` → an Excel file for people, in the app's own words and local
times, with two sheets: *Summary* (one row per hypothesis: answer, answer for each part, documents per side, excerpts
that count / too uncertain / read, judgements reviewed and changed by you, excerpts you have not reviewed yet, notes,
code, strictness, every AI model whose answers the check used and what each did, for a methods section) and
*Excerpts* (every excerpt read: judgement, judged by, the AI's own judgement, AI certainty, counted in the answer,
quote and who chose it, document, where, the person's comment, the full excerpt, notes, code). 0.14.3: an excerpt no
AI judged says so: *Judged by* "nobody yet" (until you judge it) and *AI's own judgement* "Not read by an AI: kept for
your own judgement", "Not read yet: it waits for your local model" or "Not read: the AI's answer could not be used".
`.csv` and `.json` give the technical forms.
`GET /api/projects/<p>/export.xlsx?threshold=` → the same for every check of the project, plus a sheet *Map* (the
evidence map: one row per hypothesis, one column per document, + supports, (+) partly, − contradicts, ± both, with
the number of excerpts that count); `export.csv` the technical CSV (ids, raw verdicts, UTC times). File names are
readable ("ENLENS results - <project> - <date>.xlsx"). From 0.6 the *Excerpts* sheet also has "About another group
(AI's note)" and "AI's earlier judgement (before reading it again)", and, when a second model read any of the
excerpts, "Second model", "Second model's judgement", "Second model's certainty", "The two models agree". The
*Summary* sheet has "Excerpts where the second opinion differs" (0.11.2; before: "…a second model disagrees"),
"Answer before a stronger model read it again" (0.11.2), "Documents added since the check" and (0.18.7, roadmap N5)
"Documents with the search words never read".

### Exploring the documents (0.7)

All of these work without a model except where a job says *the AI*. Model jobs run one at a time like checks, and
every answer they store records the model, its digest, the prompt version, the seed and the settings
(`provenance`); every Excel download of these pages ends with the sheet *How these results were made*.

#### Search (F1)

- `GET /api/projects/<p>/search?q=&mode=any|all|phrase|near|meaning&near=5&exact=1&all=1&docs=a,b&code=sdg:6.4&sort=doc|left|right&offset=0&limit=200`
  → `{query, mode, words, total, passages, documents, per_doc: [{doc_id, title, hits, passages}], lines: [{n,
  doc_id, title, passage_id, page, location, left, node, right, marks, start, end}], other_forms: [{word, count}],
  rarest, offset, limit}`. `start`/`end` are document offsets (open `#/doc/<id>?q=<start>-<end>`). `exact` turns
  stemming off; `all` includes reference lists and front matter; `other_forms` are words of the documents that
  start like a searched word but are not found by it (*commuters* for *commuting*). `mode=meaning` (needs an
  embedding model) returns `{passages: [...]}`, whole passages ranked by keywords and meaning together.
- `GET /api/projects/<p>/search.csv|xlsx?…` the same lines (all of them, up to 50,000); the Excel file adds *Per
  document* and *Words around it*.
- `GET /api/projects/<p>/collocates?q=…&window=5&order=typical|often` → `{hits, window, window_words, min_count,
  order, words: [{word, stem, count, corpus, pmi}]}`: words within `window` (1–15) words of the hits, seen there at
  least `min_count` times (3, or one in a thousand hits); `typical` ranks by pointwise mutual information.

#### Profiles with a codebook (F2)

- `GET /api/projects/<p>/profile?framework=sdg&level=code|group&docs=` → the keyword pass status (`pass1`), the
  grid documents × codes (`grid`), counts by source (`stats`), the codebooks (`frameworks`, each with `groups`).
  0.16: `pass1.codebook_changed` is true when the codebook's codes or the words they are matched by changed since the
  keyword pass; `removed_codes` is `[{"code", "labels"}]`, codes taken out of the codebook whose labels wait and are
  not counted; `stale_codes` is `{code: {"since", "passages"}}`, codes whose wording changed after the AI labelled
  with them. Labels first follow the codebook's renames and merges (`codebooks.follow`).
- `POST /api/projects/<p>/profile/keywords {framework?}` → job: the keyword (and meaning) pass, seconds.
- `GET /api/projects/<p>/profile/plan?framework=&docs=&all=1` → `{passages, with_candidates, already_read,
  to_read, estimate_seconds, run: {now, last, changed}}`; `changed` lists what differs from the last run (model,
  digest, prompt, seed, settings).
- `POST /api/projects/<p>/profile/label {framework?, doc_ids?, all_passages?, limit?, passage_ids?}` → job: the AI reads the
  passages (task `label`, prompt `label-v1`; 0.16: `passage_ids`, a list, reads only these passages, as
  `POST …/codebooks/<name>/relabel` does). Its result: `{read, failed, planned, stopped, changes: {confirmed,
  not_confirmed, added}}`.
- `POST /api/projects/<p>/profile/compare {…}` → job: a second model labels the same sample (`benchmark` measure).
- `GET /api/projects/<p>/profile/calibration?framework=` → how often people agreed with the AI per certainty.
- `GET /api/projects/<p>/profile.xlsx?framework=&level=` → *Documents by code*, every label with its quote, reason
  or matched words, and *Key terms per document*.
- `GET /api/projects/<p>/documents/<id>/profile?framework=` → the codes of one document, each with its passages,
  locations, quotes, reasons, matched words and who labelled them.
- `POST /api/projects/<p>/labels {framework, passage_id, code, quote?, relevance?, direction?, note?}` → a label
  of a person's own. `PUT /api/projects/<p>/labels/<label_id> {decision: accept|change|reject|clear, relevance?,
  direction?, note?}`.

#### Terms and concepts (F3) and key terms (F6)

- `GET /api/projects/<p>/terms?q=&sort=&offset=&limit=` → the glossary (`status`, `terms`, `concepts`).
  `POST /api/projects/<p>/terms/build` → job: rebuild it (seconds; also run after documents are added).
  The answer's `stale` is `documents_changed` or `words_changed` (0.17: what it leaves out changed).
- `GET /api/projects/<p>/terms/words` → what the glossary and key terms leave out (0.17): `languages`
  (`code`, `name`, `passages`, `on`) found by the last build, `off` (codes switched off), `own` (the
  project's own words and phrases), `status`, `max_own`. `PUT` with `off` (a list of codes; not `en`) and/or
  `own` (a list, or one per line) saves them (400 on an unknown code or a word over 80 characters); the
  glossary is then out of date: `POST .../terms/build` makes it again.
- `GET /api/projects/<p>/concepts?name=…` → the concept a wording belongs to. `GET /api/projects/<p>/concepts/<term_id>?refs=1&offset=&limit=`
  → the card: `wordings` (with `joined_by` and `joins`), `documents` (with `first`, `first_end`,
  `first_location`), `lines`, `related`, `suggested_wordings`.
- `PUT /api/projects/<p>/concepts/links {a, b, decision: accept|reject|change|add, relation?: same|broader|narrower|related|different, note?}`.
  A person's `different` keeps a wording from being proposed again.
- `POST /api/projects/<p>/concepts/judge {pairs?}` → job: the AI judges proposed pairs (task `link`).
  `POST /api/projects/<p>/concepts/<term_id>/wordings` → job: the AI proposes other wordings the documents use.
- `GET /api/projects/<p>/documents/<id>/terms?n=15` → key terms with their places (`spans`) for underlining;
  `GET /api/projects/<p>/passages/<id>/terms` → the key terms of one passage.

#### Themes (F4)

- `GET /api/projects/<p>/themes` → `{runs, auto_mode, auto_why, k}`; each run has `themes_now` (after merges and
  removals).
- `POST /api/projects/<p>/themes {k?, seed?, mode?: auto|meaning|words}` → job: a new set of themes (spherical
  k-means, in numpy when it is installed and otherwise in plain Python, with the same result; the same documents and
  settings give the same themes). A small project gets fewer themes than `k`
  (about three passages a theme); fewer than 5 passages is an error.
- `GET /api/projects/<p>/themes/<run>?framework=` → the themes (names, key terms, size, documents,
  representative passages), `removed` (the themes a person removed, without a `number`), `doc_grid` and
  `code_grid` (without the removed themes' passages). Each theme has `removed`, `removed_at`, `replaces` (`{theme_id,
  name}` of the removed theme a new theme was found in place of, or null), `replaced_by` and `drawn_from` (`[{theme_id,
  name, passages}]`: the themes a new theme took its passages from); `edits` also counts `removed` and `added`.
  `GET …/themes/<run>/<theme_id>?offset=&limit=` → one theme (a removed one too) and its passages (built from that theme alone: `themes.view(only=)`). `DELETE
  …/themes/<run>[?why=<reason>]` (0.16: `why` as for a document).
- `PUT /api/projects/<p>/themes/<run>/edit {what: rename|merge|move|remove, theme_id?, value?, passage_id?, why?}`
  (0.16: `why`, an optional reason, goes into the research log; each edit also keeps the state before it as a version):
  rename, merge and move are kept as reviews, so they survive a new set with the same settings; `value: null` (or
  `""` for a name) undoes. `remove` with `value: true` leaves a theme and its passages out of the themes, `false`
  brings it back; it belongs to this set only. A removed theme takes no merge and no moved passage (400), and the
  last theme shown cannot be removed.
- `POST /api/projects/<p>/themes/<run>/new {replaces: <theme_id>}` → job (`theme-new`, scope: the run): a new theme
  in place of a removed one, on this computer and without AI (one more k-means step with the other centres fixed;
  it takes only passages closer to it than to their own theme and to every removed theme). Its result is
  `{theme_id, replaces}`. A theme that is not removed, or already has a new theme in its place, is a 400. 0.17.0: while
  another new theme is being found for the same set, it waits its turn (`waiting_for`) instead of a 409; the same
  removed theme asked for again returns the job already there.
- `POST /api/projects/<p>/themes/<run>/name` → job: the AI names the themes (task `theme`, quotes checked).
- `GET /api/projects/<p>/themes/<run>/export.xlsx`.

#### References (F5)

- `GET /api/projects/<p>/documents/<id>/references?start=&end=` → `{status, chains}`; with `start`/`end` (a
  selection) the chain it belongs to.
- `POST /api/projects/<p>/documents/<id>/references {name?}` → job: the AI follows references window by window
  (task `resolve`), or only around one name. Result: `{windows, read, failed, already_read, chains}`.
- Checks (prompt `check-v4`) give each judged excerpt `refers_to` (what a quote's "it" or "they" means) and flag
  `reference_missing` when a quote opens with a pronoun and nothing says what it refers to.

#### Highlighted copies (F7)

- `GET /api/projects/<p>/documents/<id>/annotated.pdf?hyp=h1,h2&layers=judgements,labels,concepts,references&framework=&concept=&threshold=`
  → the PDF with highlight annotations (exact boxes with pdfminer, lines otherwise, OCR for scanned pages) and a
  note listing quotes it could not place; an HTML copy for other documents. Header `X-Enlens-Placed: placed/marks`.
- `GET /api/projects/<p>/hypotheses/<id>/annotated.zip?layers=&threshold=` → every document behind one answer.

#### Quick look and FlexiConc (F8)

- `POST /api/quicklook?name=<file>` (raw body) → `{project, job}`: a temporary project for one document, opened at
  once; `project.temporary = {created_at, expires_at, file, from}`. It goes to the trash after 7 days unless
  `POST /api/projects/<p>/keep`. Removing it (`DELETE /api/projects/<p>`) opens another project.
- `GET /api/projects/<p>/flexiconc.sqlite?framework=` → the project in the FlexiConc layout of the Cross-Doc SDG
  Explorer: `documents`, `sentences` (with a code label, confidence and consensus), `chains`, `clusters` and, when
  the project has an embedding model, `embeddings`.

#### Repeatable answers

- `POST /api/servers/repeatable` → `{model, repeatable, seed, digest, note}`: the same short question sent twice
  with the seed of the settings (`seed`, default 42) and temperature 0.

### The task queue, model routing and the Claude Code plugin (0.8)

With `settings.backend = "claude_code"` (it needs `allow_claude_code: true`, refused with `--local-only`) every job
that would call a model prepares tasks in the queue and waits for them: its Job has `"queue": true`, does not wait
for the model's turn, and its `progress` carries `queue`: `{"phase": "queue", "text": "Waiting for Claude Code: 3
passages to label", "waiting", "being_answered", "estimate", "paused", "paused_text", "command": "/enlens-run P",
"privacy"}` (checks, batches: under `progress.model` with `phase: "queue"`). Cancelling such a job takes its tasks
that no session has taken yet out of the queue; a check by queue is removed whole.

- `GET /api/projects/<p>/queue` → `{"project", "kinds": [{"kind", "title", "waiting", "being_answered", "done",
  "failed", "stronger_model", "model", "step_up", "helper", "held", "estimate_seconds", "estimate", "run_total",
  "run_done"}], "groups": [{"kind", "model", "helper", "waiting"}], "order": [...], "held": [...], "waiting",
  "being_answered", "paused", "paused_text"?, "last_answer_at", "privacy", "command", "claim_minutes", "route",
  "setup": {...as GET /api/claude-setup}}`. Reading it also takes the next steps of checks by queue.
- `POST /api/projects/<p>/queue/order` `{"kind", "action": "first" | "hold" | "go" | "reset"}` → `{"order", "held"}`.
- `POST /api/projects/<p>/queue/withdraw` `{"kind"}` → `{"withdrawn", "checks_removed"}`.
- `POST /api/projects/<p>/queue/run` `{"kinds"?: [...]}` → job (kind `queue-run`): the AI model of Settings answers
  the queue here, kind by kind (400 when Settings name Claude Code).
- `POST /api/projects/<p>/tasks/<task_id>/stronger` → job (kind `stronger`): "Ask a stronger model": the task (a
  round of a check: `rounds_info[].task_id`) is read once more by the model it steps up to; 400 when it already was,
  or when this route has no stronger model.
- `POST /api/projects/<p>/hypotheses/<h>/stronger` (0.11.2) → job (kind `stronger`, `scope` the hypothesis id):
  "Ask a stronger model" for a whole result: every search with `can_step_up` is read once more by the model checks
  step up to; the job's result is `{"hyp_id", "task_ids", "answered", "model"}`. 404 for an unknown hypothesis, 400
  when the route has no stronger model or every search was already read again. The result page uses this one.
- `GET /api/routing` → `{"route", "route_name", "rows": [{"row", "kinds", "title", "model", "step_up", "helper",
  "chosen", "recommended"}], "aliases", "fable", "local_small_model", "second_model", "step_up_below", "routing"}`.
- `GET /api/claude-setup` → `{"folder", "ready", "commands": ["claude plugin marketplace add …", "claude plugin
  install enlens-run@enlens"], "terminal": "enlens claude-setup", "in_claude_code": [...], "local_only"}`;
  `POST /api/claude-setup` writes the plugin into the data folder and adds `"problems": []`.
- Settings (`PUT /api/settings`): `allow_claude_code`, `use_fable`, `task_models` (`{"claude": {"label": "sonnet"},
  "local": {"label": "llama3.2:3b"}}`), `local_small_model`, `routing` (default true).
- `GET /api/state` adds `queue: {"waiting"}` for the current project.
- Results: a hypothesis has status `waiting` while a check by queue is not finished; `GET …/hypotheses/<id>` adds
  `stronger_model`, `stronger_reason` (0.14.3: why `stronger_model` is null: `"model_per_task_off"` (the setting is off,
  or demo mode), `"top_model"` (Claude already runs checks on the strongest model of the plan), `"one_local_model"`,
  or `"none"`; null when there is one), `queue_command`, `queue`, and per part `rounds_info[]` `task_id`, `stepped_up`,
  `stronger_waiting`, `waiting`; an excerpt's `ai_history[].why` is `"stepped up"` for a stronger model's reading.
  0.11.2 adds, on the hypothesis and on each part, `status_first` (the answer from the first model's readings),
  `status_before_stronger` (the same when it differs from `status`, else null) and `stronger` (`{}` or
  `{"excerpts", "changed", "first_models", "models"}`: the excerpts a stronger model read again and how many it
  judged differently), and per round `can_step_up`. `status` is always the stronger model's reading.
- Themes carry `number` (1 to n in the order shown) and `merged_from_names`; `PUT …/concepts/links` accepts
  `decision: "undo"`.

### Subscription first, Claude Code set up and started from the app, the overview (0.9)

- A new installation's settings have `backend: "claude_code"` and `allow_claude_code: true`. With `--local-only` the
  default is `"auto"` (and `allow_claude_code` false).
- `GET /api/claude-setup[?refresh=1]` adds `"status"`: `{"found", "path", "version", "signed_in": true | false |
  null, "written", "installed": true | false | null, "plugin_version", "ready", "local_only"}` (from `claude
  --version`, `claude auth status` and `claude plugin list --json`; cached for 30 s, `refresh=1` reads again).
- 0.13.4: the status adds `"email"`, `"org_name"` and `"auth_method"`: the account Claude Code says it is signed in
  to (`email`, `orgName`, `authMethod` of `claude auth status`), `""` when it is not signed in or does not say; one
  line of text each, at most 200 characters. (`"plan"` and `"account"`, from 0.11, are its plan and the kind of
  terms.) Only the set-up status carries them (here, and in `POST /api/servers/test`'s `"claude"`): not
  `/api/state`, not the queue's `"claude"`.
- `POST /api/claude-setup` `{}` prepares the plugin and, when Claude Code is found, adds it to Claude Code →
  `{..., "steps": [{"step", "ok", "text"}], "status", "commands", "problems"}`; `{"write_only": true}` only writes
  the plugin (as 0.8); `{"check": true}` also starts the connector to check it.
- `POST /api/projects/<p>/queue/claude-code` → `{"running", "started_at", "seconds", "exit_code", "report",
  "stopped"}`: starts Claude Code headless for the project's queue (`claude -p "/enlens-run:enlens-run <p>"
  --tools Agent --restricted --plugin-dir <plugin folder> --allowedTools Agent
  mcp__plugin_enlens-run_enlens__{queue_status,next_tasks,submit_answers,release}`, with
  `ENABLE_CLAUDEAI_MCP_SERVERS=false`, in an empty folder; an older Claude Code without those options gets
  `--disallowedTools` with the file, shell and web tools instead), one run per project; adds the plugin first if
  needed. 400 when Settings do not name Claude Code, when Claude Code is not found,
  or with `--local-only`.
- `POST /api/projects/<p>/queue/claude-code/stop` → the same object: stops it, and gives the batches it had taken
  back to the queue at once.
- `GET /api/projects/<p>/queue` adds `"runner"` (as above, or `{"running": false}`), and on the Claude Code route
  `"can_start"` and `"claude": {"found", "signed_in", "installed", "ready"}`.
- `POST /api/servers/test` on the Claude Code route answers from the set-up status: `model_available` is whether it
  is ready, `claude` the status, `warning` when it is not signed in.
- `GET /api/projects/<p>/overview` → `{"documents", "passages", "profile": {"framework", "keyword", "labels",
  "documents"}, "concepts": {"terms", "concepts"}, "themes": {"runs", "themes", "latest"}, "references",
  "hypotheses", "waiting"}`: what each feature has made, for the Overview page. 0.16 adds `"notes"`, `"log"` (entries)
  and `"codebooks"` (those of your own: not the bundled ones).

### Set-up in one button, moving to another computer (0.10)

- `GET /api/claude-setup` adds `"installer"` (the line of Anthropic's Claude Code installer for this system:
  `curl -fsSL https://claude.ai/install.sh | bash`, or `irm https://claude.ai/install.ps1 | iex` on Windows) and
  `"docs"` (Anthropic's set-up page).
- `POST /api/claude-setup/claude-code` `{}` → job (kind `claude-install`): runs that installer (the page shows the
  command and asks first). `result`: `{"ok", "text", "status"}`; the job ends in `error` when Claude Code could not
  be installed. 409 when Claude Code is already found; 403 with `--local-only`.
- `POST /api/claude-setup/sign-in` `{}` → `{"opened", "window", "command", "folder"}`: opens a terminal window
  (Terminal on macOS, PowerShell on Windows, the first terminal found on Linux) already running `claude`, for the
  one-time sign-in, in the empty `folder` (`<data folder>/claude-runs/sign-in`) and without the file, shell and web
  tools; `opened: false` when no window could be opened (the page then shows `command`, the line to type, which goes
  to that folder first). The page
  then reads `GET /api/claude-setup?refresh=1` every few seconds until `status.signed_in` is true, and adds the
  plugin. 400 when Claude Code is not found, or with `--local-only`.
- On start, the app writes the Claude Code plugin again (and runs the two set-up commands again, quietly) when the
  plugin names another Python or another data folder than this ENLENS (it moved, or was installed again).
- `GET /api/move.zip` (a download; the token may be given as `?token=`) → one zip with every project (each as the
  zip of `GET /api/projects/<p>/export.zip`, under `projects/NNN.zip`) and `enlens-move.json`: `{"format":
  "enlens-move", "version", "made", "projects": [{"name", "file", "documents", "linked", "missing"}], "current",
  "settings"}`. Quick looks not kept are left out, and so is a saved Claude API key.
- `POST /api/projects/import` with that zip asks first, in two steps. Step one imports nothing: it answers `{"move":
  peek, "token"}`, where `peek` is `{"made", "version", "projects": [{"name", "documents"}], "person": {"id",
  "name"}, "settings": {key: value shown}, "servers": [{"key", "url", "here": bool}] (addresses of servers; `here`:
  on this computer), "fresh": bool (this computer has no project)}`; the upload waits under `token`. Step two,
  `POST /api/move {"token", "mode": "moving" | "both", "name"?, "settings": bool, "servers": [keys]}` →
  `{"moved": {"projects": [{"from", "name", "documents"}], "settings": bool, "current", "made", "version"}, "project":
  summary of the current one}`. `mode` has no default (400). `"moving"` only when `fresh` (else 409): this person's id
  and name are taken first, then the projects come in as this person's own. `"both"`: a new person here, called
  `name`; the projects come in as a colleague's do. `settings` takes the other computer's settings; an address that is
  not on this computer is taken only when its key is in `servers`, else that back end goes back to its default; the
  installation id never comes. A project whose name is taken comes in as `name (2)`. With `--local-only`, never the
  choice of a cloud AI. An unknown or used `token` → 404.
- `POST /api/second-computer {"name"}` → `{"person": {"id", "name"}}`: use both computers. This computer becomes a second
  person (a new id, the name given); what it did so far stays under the first id. Answers the folder problem
  the problem of `GET …/shared-folder` (`kind` `other_computer`, and `"other_computer": {"since": ISO} | null` beside
  `problems`) that stops a copy from writing into a folder where another computer already writes under the same name.
- `GET /api/state` adds `"installation": {"kind": "git" | "script" | "package" | "pip", "system": "mac" | "windows"
  | "linux", "line", "releases"}`, and `ocr` adds `"install"` when Tesseract is missing: `{"text", "command", "link",
  "link_text"}` for this system.

### How fast Claude Code works, and which helpers it starts (0.13.10)

- Settings (`PUT /api/settings`): `claude_speed`: `"slower"` | `"normal"` (default) | `"faster"`, one, two or four
  helpers at once when the app starts Claude Code (400 for anything else).
- `GET /api/projects/<p>/queue` adds `"speed": {"chosen", "options": {"slower": 1, "normal": 2, "faster": 4},
  "max_parallel": 8, "max_per_helper": 4, "helpers": [{"helper", "name", "models", "kinds", "waiting", "batches"}],
  "all_helpers": [...]}` (`helpers`: the helpers with work waiting, with the titles of the kinds they would answer;
  `batches`: how many batches that is, the most helpers that can work on it at once). Each of `"groups"` adds
  `"start"`: how many helpers a run at the chosen speed starts for it now, and the estimates count with that speed.
- `POST /api/projects/<p>/queue/claude-code` takes `{"parallel"?: 1 to 8, "helpers"?: {"enlens-checker": 2,
  "enlens-labeller": 1}}` (`"checker"` works too; 0 to 4 each, at least one above 0) for that run; with neither, the
  speed of Settings. The command gets `--parallel N` and, with helpers, `--helpers checker=2,labeller=1` (the ones
  given 0 left out: they do nothing in that run). With helpers, `parallel` is at most what they add up to (their sum,
  at most 8, when not given). Whole numbers only (2.0 is 2; 2.5 is refused). 400 for a bad plan. The run's object
  adds `"parallel"` (the helpers it can have at once) and `"helpers"` (`{"checker": 2, …}` or null).
- The connector's `queue_status` takes `kind`, `parallel` and `helpers` (`"checker=2,labeller=1"`), as `/enlens-run`
  was given them; without `parallel` it uses the speed of Settings. Its `groups` carry `start` (one per group in the
  queue's order, then more for the groups with more batches; with `helpers`, each helper at most as many as named),
  only for the kind asked and the helpers named; the answer adds `"parallel"` and, with `helpers`, `"helpers"` and
  `"not_this_run"` (the groups of the helpers left out). `/enlens-run` starts what `start` says, and asks again only
  when all its helpers have reported back (`taskqueue.run_status`, `run_plan`, `plan_helpers`).

### Models that suit the Claude plan (0.13.10)

- Settings: `claude_plan` (`"auto"`, the default: follow the plan Claude Code names; or `"free"` | `"pro"` | `"max"`)
  and `claude_plan_detected` (`""` | `"free"` | `"pro"` | `"max"`: the tier of `subscriptionType` from `claude auth
  status`, written in the background by `claude_setup.status()` when Claude Code is signed in and the tier changed,
  and once when the app starts; Team and Enterprise are `"max"`). Not carried by *Move ENLENS to another computer*.
- `GET /api/routing` adds `"plan": {"tier", "chosen", "detected", "titles"}` (`tier`: the one the recommendations
  follow, `""` when not known: as Pro). Each row's `"recommended"` is now the model itself (the auditor named: opus,
  fable, or sonnet on Free), with `"recommended_role": "auditor"` where it is the auditor's.
- In `routing`: `TIERS`, `plan_tier(plan)`, `tier_defaults(kind, tier)`, `settings_tier(settings)`, `Router.tier`.
  A kind registered by an add-on can say `bulk=True` (many tasks at a time: keeps its models on Max).

### The bibliography: Zotero, or an exported file (0.13)

A project can hold one bibliography: the works of a Zotero library or collection, read from the Zotero app on this
computer through its local API (Zotero 7 or later, `http://127.0.0.1:23119/api/`, switched on in Zotero under
*Settings → Advanced → Allow other applications on this computer to communicate with Zotero*), or of a file exported
from a reference manager (BibTeX, RIS, CSL JSON, Zotero's CSV). Nothing goes over the internet; Zotero is only read.

- `GET /api/zotero` → `{"state": "ready" | "not_running" | "api_off" | "too_old" | "failed", "url", "libraries":
  [{"id": "user" | "group-<id>", "name"}], "detail"}` (`libraries` when ready).
- `GET /api/zotero/collections?library=user` → `{"collections": [{"key", "name", "parent", "items", "depth"}]}` in
  tree order (`items`: the works directly in it). 409 with `kind` `zotero_<state>` when Zotero cannot be read.
- `GET /api/zotero/works?library=user&collection=<key>&q=<words>&limit=100` (0.13.9) → `{"works": [{"key", "title",
  "cite", "type"}], "more"}`: the top-level works of a library, or of one collection (not its subcollections), by title,
  without notes; `q` is Zotero's quick search (title, creators, year); `more` when there are more than `limit` (at most
  200). 409 as above.
- `POST /api/projects/<p>/bibliography` → job (kind `bibliography`), one of:
  `{"zotero": {"library": "user", "collection": "<key>" | null, "subcollections": true}}` (null: the whole library),
  `{"zotero": {"library": "user", "items": ["<key>", …]}}` (0.13.9: only these works, 1 to 500 of them),
  `{"file": {"name": "refs.bib", "text": "…"}}`, or `{"update": true}` (the same Zotero library and collection, or the
  same chosen works, again).
  It replaces the bibliography; a person's decisions are kept for every work that is in the new one too (by its key,
  else its DOI, else its title and year). `progress`: `{"phase": "works" | "attachments" | "files" | "checksums" |
  "matching", "done", "total"}`. `result`: the counts below. 400 for a file that is not a bibliography, a file without
  works, `update` of a bibliography read from a file, or `items` that are not 1 to 500 Zotero keys. Chosen works
  that Zotero no longer has are left out (and out of the next update); none left is an error of the job.
- `GET /api/projects/<p>/bibliography` → `{"bibliography": null}` before one is brought in; else
  `{"bibliography": {"kind": "zotero" | "file", "library", "library_name", "collection", "collection_name",
  "subcollections", "items" (0.13.9: the chosen works' Zotero keys), "name", "format", "format_text", "pulled_at",
  "works"}, "counts": {"works", "linked", "confirm",
  "to_find", "not_in", "files"}, "linked": [Pair], "confirm": [Pair], "to_find": [Work], "not_in": [Document],
  "ai_access": project info}`. A Work: `{"key", "title", "cite": "Verhoeven and Okafor (2025)", "authors", "year",
  "type", "container", "doi", "url", "link": "zotero://select/…" | null, "file": name of a file Zotero keeps | null}`.
  A Pair: `{"work", "doc": {"doc_id", "title", "file", "kind", "pages", "added_at", "file_title"}, "status": "auto" |
  "confirmed" | "probable", "method": "file" | "doi" | "title" | "person", "score"}`; a probable one adds
  `"evidence": {"title": "whole" | "main" | "words", "author", "year", "excerpt", "start", "end", "page"}` (the
  title's place on the document, `start`/`end` within `excerpt`).
- How a work and a document are linked: by themselves when a file the work has and the document are the same file
  (the same checksum) or they have the same DOI (`auto`); proposed (`probable`) when the work's title stands on the
  document's first pages with an author or the year (a title of one or two words needs both); a document or work
  already linked gets no proposal, and a pair a person rejected is never proposed again. Adding documents matches
  them again: the ingest job's `result` adds `"bibliography": {"linked", "confirm"}` for the new documents.
- A linked document (`auto` or `confirmed`) takes its work's title (0.13.3): its `title` everywhere (the documents,
  search, a check's excerpts and exports) is the work's, and `file_title` (in a Pair's `doc` and in
  `GET …/documents/<doc_id>`) is the title read from the file, `null` when the two are the same or the document is not
  linked. When no work is linked any more (`different`, another bibliography, `DELETE`), the file's own title comes
  back. A document linked to several works takes the first one's (the bibliography's order). The matching always reads
  the file's own title.
- `PUT /api/projects/<p>/bibliography/links` `{"item_key", "doc_id", "decision": "same" | "different" | "clear"}` →
  the view above. `same` confirms a proposal or links by hand; `different` rejects a proposal or undoes a link;
  `clear` forgets the person's word.
- `POST /api/projects/<p>/bibliography/confirm-all` `{}` → `{"confirmed": n, …the view}`.
- `POST /api/projects/<p>/bibliography/files` `{"ai_access": "cloud" | "local" | "none", "item_keys": [...]?}` → an
  ingest job (title "Adding Zotero's files") of the files the bibliography has for works without a document, read
  where they are. 400 when there is none.
- `GET /api/projects/<p>/bibliography/to-find.xlsx` and `.csv` (downloads; `?token=` allowed): the works without a
  document: Title, Authors, Year, Type, Published in, DOI, DOI link, Web address, Open in Zotero, File in Zotero.
- `DELETE /api/projects/<p>/bibliography` `{}` → `{"removed": n, …the view}`: the works and links go; documents and
  Zotero are not touched.
- `GET /api/projects/<p>/documents` adds `"bib"` per document (`{"cite", "title", "doi", "link", "url", "type",
  "container"}` of its linked work, or null); `GET /api/projects/<p>/documents/<id>` adds the same `"bib"`.

### Results across versions (0.15)

- `GET /api/projects/<p>/documents` adds `"reader"` (the reader that read the document's text: 1 for every document
  read before 0.15, 2 from 0.15), `"app_version"` (the ENLENS version that read it; null before 0.15),
  `"reading_quality"` (`"good"`, `"fair"`, `"poor"`; null for a document read before 0.15) and `"reading_warnings"`
  (sentences) per document. The reading view's routes are under *Documents* above.
- `GET /api/projects/<p>/overview` adds `"made_with"`: `{"version": "0.15.0", "reader": 2, "documents": [{"reader",
  "app_version", "label", "n", "older"}], "results": [{"what": "checks" | "theme_runs" | "labels" | "answers",
  "app_version", "label", "n", "older"}], "older": bool}`. `label` is the version as people read it ("before 0.15"
  when it was not recorded); `older` marks results an earlier version made, and documents an earlier reader read.
  People's own labels are not counted: they do not depend on a version.
- The sheet *How these results were made* of every Excel download has a column *ENLENS version* and ends with a row
  saying which reader read the project's documents.

### Your record: research log, notes, earlier versions, codebooks (0.16)

Everything here runs on this computer, without AI. Errors are the usual `{"error"}`: 400 for a value that cannot be
used, 404 for something that is not there, 403 (`PermissionError`) for a colleague's note or log entry, which only
they can change. The downloads (`…/log.md|xlsx`, `…/notes.md|xlsx`, `…/codebooks/<name>.csv`) also accept `?token=`.

#### The research log

An entry: `{"entry_id", "at", "person_id", "who", "mine", "kind", "group", "text", "title", "subject_kind",
"subject_id", "why", "edited_at", "version_id", "has_version", "can_edit", "can_why", "data", "app_version"}`.
`kind` `entry` is a person's own; every other kind is written by the app (documents added or removed, `ai-access`,
`reread`, checks added or removed, `evidence-added`, themes found, removed, renamed, merged or restored, codebooks
made, changed, moved, copied or removed, `restored`, `sync`). `group` is one of `entries`, `documents`, `checks`,
`themes`, `codebooks`, `history`, `together`. `has_version` says an earlier version from before the change exists
(`version_id`, see *Earlier versions*).

- `GET /api/projects/<p>/log?group=&q=&subject_kind=&subject_id=&offset=&limit=` → `{"entries": [entry], "total",
  "groups": {group: count}, "group_names"}`, newest first (`limit` up to 2000, default 200). `q` matches the text,
  the title and the reason.
- `POST /api/projects/<p>/log {"text", "subject_kind"?, "subject_id"?, "title"?}` → `{"entry"}`: an entry of your own
  (at most 10,000 characters; empty is a 400).
- `PUT /api/projects/<p>/log/<entry_id> {"text"?, "why"?}` → `{"entry"}`. `why` (at most 2,000 characters; `""`
  takes it away) can be set on any entry of yours; `text` only on an entry of your own (`kind` `entry`).
- `DELETE /api/projects/<p>/log/<entry_id>` → `{"deleted"}`: only your own entries (400 for the app's); it does not come
  back when a colleague's copy is brought in.
- `GET /api/projects/<p>/log.md` and `…/log.xlsx`: the whole log, oldest first. Markdown has a heading per day; the
  sheet *Research log* has *When (UTC)*, *Who*, *What*, *Entry*, *About*, *Why* and *ENLENS version*, with the usual
  *How these results were made* sheet.

#### Notes and highlights

A note: `{"note_id", "doc_id", "title", "present", "start", "end", "quote", "text", "colour", "page", "lost", "mine",
"who", "created_at", "edited_at"}`. `start` and `end` are character offsets into the document's text; `quote` is the
words, checked against the text when the note is made (a selection cut inside a word is widened). `text` is empty for
a plain highlight. `colour` is `yellow`, `green`, `blue` or `pink`. When the document was read again, the words are
found again and `start`, `end` and `page` follow them; `lost` is true when they cannot be found (the note is kept).
`present` is false for a note on a removed document (kept).

- `GET /api/projects/<p>/notes?q=&doc=&colour=&mine=1&offset=&limit=` → `{"notes", "total", "documents": [{"doc_id",
  "title", "present", "notes"}], "colours"}`, newest first. `q`: every word of it, in the note or its words.
- `GET /api/projects/<p>/documents/<doc_id>/notes` → `{"notes", "colours"}` in the order of the text (404 for an
  unknown document).
- `POST /api/projects/<p>/notes {"doc_id", "start", "end", "quote"?, "text"?, "colour"?}` → `{"note"}`. Without
  `colour`, yellow. A selection of more than 4,000 characters, or words that are not in the text, is a 400.
- `PUT /api/projects/<p>/notes/<note_id> {"text"?, "colour"?}` → `{"note"}`; `DELETE …/notes/<note_id>` →
  `{"deleted"}`. Only your own notes (403 for a colleague's).
- `POST /api/projects/<p>/notes/<note_id>/evidence {"claim_id", "verdict", "comment"?}` → `{"hyp_id", "claim_id",
  "passage_id", "new"}`: the passage holding the note's words becomes an excerpt of that part of a check, judged by
  you (`verdict`: `supports`, `partially_supports`, `refutes` or `not_relevant`), with the note's words as the sentence
  you point to; `new` is false when the check showed the passage already (your judgement of it is set). 400 when the
  words are no longer in the text, run across two passages, or lie in text left out of the reading.
- `GET /api/projects/<p>/notes.md` and `…/notes.xlsx`: every note (columns *Document*, *Page*, *Words*, *Note*,
  *Colour*, *Who*, *Made (UTC)*, *Changed (UTC)*, *Found in the text now*).

#### Earlier versions

`kind` is `themes` (key: the run id), `check` (key: the hypothesis id) or `codebook` (key: its name). A version is
kept before each change a person makes: theme names, merges, moves and removals; your own judgements, comments,
sentences and the check's note; a codebook. Not the themes found, nor the AI's answers. The latest 200 of each are
kept. Versions of themes and checks are in the project's database (the `versions` table); bringing in a colleague's
work does not take over theirs, nor give them yours. (A project zip is a copy of the whole database, so it carries them
too: a move to another computer keeps them.) A codebook's are beside its file.

- `GET /api/projects/<p>/history/<kind>/<key>` → `{"kind", "key", "title", "versions": [{"version_id", "at", "label",
  "person_id", "who", "mine"}]}`, newest first.
- `GET /api/projects/<p>/history/<kind>/<key>/<version_id>` → `{"kind", "key", "title", "version", "changes": [{"what",
  "before", "after"}], "same"}`: what changed from that version to now, in words.
- `POST /api/projects/<p>/history/<kind>/<key>/<version_id>/restore {}` → `{"restored": true, "changes"}`, or
  `{"restored": false, "changes": []}` when it is the same as now. The state it replaces is kept as a version first,
  and the research log gets a `restored` entry that points to it.

#### Codebooks

A codebook stays a CSV file (see *Frameworks* above), kept `project` (`<project>/frameworks/`) or `home` (all projects),
with a side file for what a spreadsheet cannot hold: a stable id for each code, renames, merges and rewordings, removed
codes, where each example was found, the groups and their order. The old routes under `…/frameworks` still work.

- `GET /api/projects/<p>/codebooks` → `{"codebooks": [info + {"where": "project" | "home" | "bundled", "labels",
  "checks", "profile_default"}], "problems": [...]}`. Labels first follow renames and merges.
- `GET /api/projects/<p>/codebooks/<name>` → `{"codebook": {"title", "label", "directional", "groups": [{"group",
  "group_name"}], "codes": [{"code", "uid", "description", "group", "include", "exclude", "keywords", "examples":
  [{"quote", "doc_id", "title", "page"}]}], "where", "editable", "shadows_home", "in_home", "used": {"labels",
  "by_code", "checks"}, "removed": [{"code", "uid", "labels", …}], "stale": {code: {"since", "passages"}},
  "versions", "profile_default", "clashes"}}`. `include` is *When to use it*, `exclude` *When not to use it*, `keywords`
  *Words it is matched by*. A code's `uid` is empty for a code not saved yet. `clashes` (0.17.0): codes you and a
  colleague both changed since you last exchanged the codebook, merged code by code when their work came in: `[{"uid",
  "code" (yours now; null when you had removed it), "removed_here", "theirs": {"code", "description", "group",
  "group_name", "include", "exclude", "keywords", "examples"}, "person_id", "name", "at"}]`.
- `POST /api/projects/<p>/codebooks/<name>/follow {"follow": bool}` → `{"codebook"}`: answer the `offer` of `GET
  …/codebooks/<name>` (`{"name", "from": person, "events": [{"op", "from", "to"}], "labels"}` | null): renames and
  merges by someone other than the codebook's maker. `true` moves this copy's labels with them, `false` keeps them.
  The maker's own move everyone's labels at once; none deletes a label.
- `POST /api/projects/<p>/codebooks/<name>/clashes/<uid> {"keep": "mine" | "theirs", "why"?}` → `{"codebook"}` (0.17.0):
  keep your version (theirs is set aside) or theirs (it replaces yours, or comes back when you had removed it; labels
  follow a new name as after any edit). A version is kept and the research log says so. 404 when there is no such
  clash.
- `POST /api/projects/<p>/codebooks {"name", "title"?, "where"?: "project" | "home", "start"?: "fresh" | "themes" |
  "copy" | "csv", "source"?, "label"?}` → `{"codebook"}`. `source`: `{"codes": [...]}` (drafts from
  `GET …/codebooks/sources`, the ones kept), `{"of": "<codebook name>"}` or `{"csv": "<text>"}`. The columns of a CSV
  are `code`, `description`, `group`, `group_name`, `when_to_use`, `when_not_to_use`, `keywords` (separated by `;`) and
  `examples` (one per line); `code` and `description` are required. A cell that starts with an apostrophe before text a
  spreadsheet would run as a formula (`'=1+1`, `'@x`, `'-x`) loses that one apostrophe: it is what the CSV download
  adds (below). Any other cell is read as written. A name that is taken gets a number.
- `GET /api/projects/<p>/codebooks/sources?all=1` → `{"runs": [{"run_id", "project", "here", "created_at", "themes":
  [{"name", "size", "code": {"code", "description", "described", "keywords", "examples"}}]}]}`: the sets of themes a
  codebook can start from (removed themes left out); `all` adds those of every project.
- `PUT /api/projects/<p>/codebooks/<name> {"codebook": {…as above…}, "merges"?: [{"from": uid, "into": uid}], "why"?}`
  → `{"changes": [words], "version_id", "codebook"}`: writes the editor's state. A code without a `uid` is new; one
  that is gone is removed (its labels wait), unless named in `merges` (its labels go to the other). A bundled codebook
  is a 400. Each saved change keeps the earlier state as a version and goes into the research log with `why`.
- `DELETE /api/projects/<p>/codebooks/<name>[?why=]` → `{"deleted"}`. Labels made with it stay.
- `POST …/codebooks/<name>/move {"to": "home" | "project"}` → `{"codebook"}`: keep it with all projects, or with this
  one. `POST …/codebooks/<name>/copy-here {}` → `{"codebook"}`: this project's own copy of one kept with all projects.
- `POST …/codebooks/example {"quote", "doc_id"?}` → `{"example": {"doc_id", "title", "page", "start", "end", …}}`: where
  words are in the documents (400 when they are not).
- `POST …/codebooks/<name>/try {"codebook"?}` → job (`codebook-try`, no model): for each code of the saved codebook,
  or of the state sent, `{"passages", "documents", "codes": {code: {"passages", "documents", "examples", "share",
  "note"}}}`; `note` says a code matches nothing, or more than a quarter of the passages.
- `POST …/codebooks/<name>/relabel {"code"}` → `{"passages", "job"}`: the AI labels again the passages it labelled with
  that code before its wording changed (a label job with `passage_ids`); 409 when there are none.
- `GET /api/projects/<p>/codebooks/<name>.csv` → the codebook as a CSV file (the columns above). As in every CSV
  ENLENS writes, a cell that starts with `=`, `@`, a tab or a carriage return, or with `+` or `-` unless it is a number
  (or `- ` and a space), gets a leading apostrophe, so a spreadsheet shows it and does not run it; reading a codebook
  takes that apostrophe off (`review.csv_cell` and `review.csv_uncell`, exact inverses). Codebook files written before
  0.17.2 have none; the download adds them.

### Theory documents, a codebook from theory, concepts and reader 5 (0.18.1)

**A document's role** (roadmap K2 part 1, `docrole.py`). A document marked as theory is the lens the research is read
through: still read, searched and noted, but left out of themes, codebook labels, the excerpts a check reads and key
terms.

- `GET /api/projects/<p>/codebooks/<name>.qdc` → 0.18.7 (G5): the codebook as a REFI-QDA codebook (`urn:QDA-XML:codebook:1.0`) for NVivo, ATLAS.ti and MAXQDA: its groups as parent codes, each code's definition, when to use it and when not, keywords and examples as its description (`qdpx.codebook_xml`). 404 for an unknown codebook.
- `GET /api/projects/{p}/document-roles` → `{"roles": {doc id: "theory"}, "nonscientific": [doc ids]}` (only the
  documents with a role; 0.18.6: and those marked Non-scientific).
- `GET /api/projects/{p}/documents/{d}/role` → `{"doc_id", "role": "theory" | null, "impact": {"themes": [{"run_id",
  "created_at", "passages"}], "labels": [{"framework", "name", "passages"}], "checks": [{"hyp_id", "text",
  "excerpts"}]}}`: what was made with the document in.
- `PUT /api/projects/{p}/documents/{d}/role` `{"role": "theory" | null, "why"?}` → `{"doc_id", "role", "changed",
  "impact"}`. 400 for any other role, 404 for no such document. Under an owner, a Member's mark becomes a proposal at
  the Team tab's next look (as *Leave out* does).
- 0.18.6: `GET …/documents/{d}/role` also gives `"nonscientific": bool` and, when it is, `"answers": [{"hyp_id",
  "text", "status", "status_text", "all", "all_text"}]` (each check that read it, its answer now and counting the
  non-scientific documents). `PUT /api/projects/{p}/documents/{d}/nonscientific` `{"nonscientific": true | false,
  "why"?}` → `{"doc_id", "nonscientific", "changed", "checks", "answers": [{"hyp_id", "text", "was", "was_text",
  "now", "now_text"}]}` (the answers the mark changed). 400 for a value that is not a boolean, 404 for no such
  document. A check's result gains `status_all_sources`, and each excerpt `nonscientific`; a part or a check that only
  non-scientific documents speak to has the status text *No scientific evidence found*.
- 0.18.8 (K3, `nonscientific.py`): `PUT /api/projects/{p}/hypotheses/{h}/nonscientific` `{"count": true | false,
  "why"?}` → `{"hyp_id", "count_nonscientific", "changed", "was", "was_text", "now", "now_text"}`: count the
  non-scientific documents in this check alone (stored in the hypothesis's options, so it travels with the check);
  400 for a value that is not a boolean, 404 for no such check. A result gains `count_nonscientific`,
  `count_nonscientific_why`, `nonscientific_read` (excerpts of such documents read) and `status_without_nonscientific`
  (the answer without them, where they count), each part `count_nonscientific`, each excerpt `nonscientific_counted`.
  `GET /api/projects/{p}/nonscientific-suggestions` → `{"suggested": {doc id: "a newspaper article"}}` (from the
  bibliography's item type; never marked by itself); `GET …/documents/{d}/nonscientific-suggestion` →
  `{"doc_id", "suggestion": {"item_type", "words", "text"} | null}`; `POST …/documents/{d}/nonscientific-suggestion`
  `{"answer": "no", "why"?}` → `{"doc_id", "declined": true}` (kept in the research log). The evidence map's cells
  gain `nonscientific` and `counted` (false: read, not counted), its documents `nonscientific`, its hypotheses
  `count_nonscientific`, and it has `nonscientific_shown`.

**A codebook from a theory document** (roadmap K2 part 2, `theorycodes.py`, no AI).

- `GET /api/projects/{p}/codebook-theory` → `{"documents": [{"doc_id", "title", "theory"}]}`, theory documents first.
- `GET /api/projects/{p}/codebook-theory/{d}` → `{"doc_id", "title", "role", "concepts": [{"term", "how": "defined" |
  "heading" | "frequent", "count", "definition": {"quote", "start", "end", "page"} | null, "code": {a draft code},
  "suggested": [examples from the evidence documents: {"quote", "doc_id", "title", "page", "start", "end",
  "project"}]}]}`.
- Then `POST /api/projects/{p}/codebooks` with `"start": "theory"` and `"source": {"codes": [the drafts kept, with the
  examples ticked], "doc_id"}`; an example from a theory document is dropped.

**Concepts: paths, time and groups** (roadmap D3, D4, `conceptpaths.py`).

- `GET /api/projects/{p}/concept-paths?from={term id}&to={term id}[&k=3]` → `{"from", "to", "paths": [{"cost", "steps":
  [{"from": {"node", "label"}, "to", "kind": "link" | "together", "relation", "pmi", "bridges": [{"passage_id",
  "doc_id", "title", "page", "location", "text", "start"}], "sentences"?}]}]}`. 400 without both terms, 404 for a term
  the glossary does not know.
- `GET /api/projects/{p}/concept-time/{term id}` → `{"node", "label", "with_year", "years": [{"year",
  "documents_in_group", "documents", "passages", "mentions", "wordings": [{"label", "mentions"}], "neighbours":
  [{"node", "label", "together", "pmi"}]}], "no_year": {the same} | null}`; years from the bibliography.
- `POST /api/projects/{p}/concept-groups/{term id}` `{"groups": {name: [doc ids]}}` (two to six sets, not stored) →
  `{"node", "label", "groups": [{"name", "documents_in_group", "theory_left_out", …the same profile}]}`.

Links found from the text (roadmap D2, `textrelations.py`) need no route of their own: they are rows of the concept
page's `related.links` with `"source": "pattern"` and their `"sentences"` (`[{"doc_id", "title", "page", "start",
"end", "quote"}]`); relations gain `effect`, `effect_of`, `replaces` and `replaced_by`.

**Reader 5: figures and tables from their rules** (roadmap A6, `reader5.py`).

- `GET /api/projects/{p}/documents/{d}/figures/{n}.png[?scale=0.5–3]` (also `&token=…`, for an `<img>`, as the page
  pictures take it) → the picture of block `n`: the crop of the original PDF's page at the block's box (`x0..y1`,
  points from the top left of the page, with a small margin), as a PNG; `scale` times 72 dots per inch, default 2. It
  is drawn from the original each time it is asked for, as the *Page* panel's picture is: nothing of it is stored or
  sent to an AI. It serves a block of kind `figure`, and also a `table` found from its rules. 404 with the reason when
  there is no such block, the block is of another kind or has no box (a figure from a Word file or web page has only
  its alternative text), the original is missing or not a PDF, or the OCR extra (pypdfium2) is not installed.
- A document's blocks (`GET …/documents/{d}?view=blocks`) may hold `kind: "figure"`: `included: false` (never read
  by searches, codes, themes or checks), its `page` and `box`, the words inside it as its `text`, and `label` *Figure*
  (before 0.18.1: *Text in a figure*). A picture without words has `start == end` (and no passage). Its caption is the `caption` block just
  after it (or, failing that, just before).
- The reading report (`reading`, `documents.reading_json`) gains `figures` (how many were found) and
  `tables_joined` (tables that ran over a page and were joined into one).

### The assessment in words, retractions, agreement between routes, answers a page at a time (0.18.1)

**The assessment in words (N4).** `GET …/hypotheses/<id>` carries `assessment`: `{"sentences": [{"text", "rule",
"refs"}], "moved_by": {"text", "rule", "refs", "from", "to"} | null}`. Each sentence comes from one rule (`verdict`,
`against`, `for`, `concentration`, `part`, `below-strictness`, `waiting-for-you`, `waiting-local`, `moved-by`);
`refs` are `"<claim_id>/<passage_id>"` of the excerpts it rests on. Made by rules, never by an AI; excerpts of
documents not readable by Claude are counted, never quoted. `PUT …/judgements/<claim_id>/<passage_id>` now also
answers `{"status_before", "status", "moved"}` (`moved`: the sentence naming this judgement when it changed the
answer, also written into the research log as kind `verdict-moved`, else null).

#### Retractions and corrections

Looks the DOIs of the bibliography's works and of the documents up in Crossref, which carries Retraction Watch's
retractions and the publishers' corrections and expressions of concern. Only when asked. Off under local-only (400,
nothing sent). Only DOIs are sent, with a plain `User-Agent: ENLENS/<version>`. A work whose document is marked
No AI is not looked up. The Crossref address can be set with `ENLENS_CROSSREF_URL` (tests use a stand-in).

| Route | Answer |
| --- | --- |
| `GET /api/projects/<name>/retractions` | What the last lookups found: `{"local_only", "checked_at" (the latest lookup or null), "checked", "affected", "by_doi": {doi: {"checked_at", "notices"}}, "by_item": {item_key: [notice]}, "by_doc": {doc_id: [notice]}, "plan": {"ask", "no_ai"}}`. A notice is `{"type": "retraction", "correction", "expression_of_concern", …, "doi": the notice's DOI, "date", "source", "work_doi", "checked_at"}`. Only works with a notice are listed. |
| `POST /api/projects/<name>/retractions/check` | Starts the lookup as a job (`{"job"}`; `progress` has `done` and `total` DOIs; one at a time per project). Its result: `{"looked_up", "no_ai", "notices", "capped", "checked_at"}`. 400 under local-only or when there is no DOI to ask about. |

`GET …/bibliography` gives each work a `notices` list, and `retractions: {checked_at, affected, local_only}` beside `counts`.

#### Agreement between routes (I5)

The local model and Claude answer the same sample of an answered kind of task, and
Cohen's kappa compares their decisions (the grade of each excerpt for `check`, `reread` and `second`; whether each
candidate code applies for `label`; the relation of each pair of terms for `link`). Only tasks whose documents Claude
may read are used. An answer a task already has from a route is reused; only what is missing is asked. Nothing is stored
in the project (the passages sent to Claude are noted in the ledger). Kappa from 0.8 is good, from 0.6 fair, below
that poor.

| Route | Answer |
| --- | --- |
| `GET /api/projects/<name>/agreement/plan` | `{"kinds": [{"kind", "answered", "name", "noun"}], "problem": a sentence when it cannot start (Claude not the main AI, no local model, local-only) or null, "claude": the main backend, "plan": null}`. With `?kind=label&n=30` (n 10 to 100), `plan` is `{"kind", "n" (tasks compared), "ask_local", "ask_claude" (tasks each route would be asked), "left_out" (answered tasks Claude may not read)}`. 400 for a kind without a decision. |
| `POST /api/projects/<name>/agreement` | Body `{"kind", "n"}`. Starts a job (`{"job"}`, kind `agreement`; `progress` has `done` and `total` tasks). Its result: `{"kind", "n", "compared", "failed", "kappa" (null when undefined), "agree" (share of identical decisions), "decisions", "verdict" (a plain sentence), "left_out", "asked": {"local", "claude"}, "items": [{"task_id", "decisions", "same", "local", "claude" ("stored" or "asked")} or {"task_id", "error"}], "thresholds": {"good": 0.8, "fair": 0.6}}`. 400 when it cannot start. |

**The answers a page at a time (H5).** `GET …/hypotheses?offset=<n>&limit=<n>` (with the same `q`, `status`, `batch`
and `threshold`) answers one page of the list: `hypotheses` holds at most `limit` rows (100 when not given, at most
1,000) from row `offset`, in the same order as the whole list, and `total` (the rows after the filters), `offset` and
`limit` are added. `counts` still cover every hypothesis. Without `offset` the answer is what it always was.

### Jobs

`GET /api/jobs` → `{"jobs": [Job summary]}` newest first. `GET /api/jobs/<id>` → full Job:
```json
{"id": "fdd6a426a6f0", "kind": "check" | "prepare" | "batch" | "more" | "reread" | "read-new" | "read-unread" |
         "second-opinion" | "ingest" | "index" | "benchmark" | "label" | "link" | "theme-names" | "resolve" | "stronger" | "queue-run" |
         "claude-install" | "bibliography" | "new_reader" | "theme-new" | "folder-sync" | …,
 "title": "…", "queue": false,
 "project": "Demo" | null, "state": "queued" | "running" | "done" | "error" | "cancelled",
 "created_at": 1793136448.87, "started_at": … | null, "finished_at": … | null, "seconds": 19.9,
 "error": null | "message", "error_kind": null | "backend" | "memory" | "request" | "internal",
 "waiting_for": null | {"id", "kind", "title", "message": "Queued: starts when “…” has finished"},
 "background": false,
 "progress": {…kind-specific…}, "result": {…} | null}
```
Summaries (in lists) omit `progress` and `result`. Jobs live until the app is closed. `background`: started by the app
itself (a round of the shared folder by the poller), not by the person.

**Jobs wait their turn (0.17.0, roadmap M6: `api_common.Jobs`, `LANES`).** Jobs of one project that change the same
things never run at the same time: the later one stays `queued`, with `waiting_for` naming the job it waits for (the
one just ahead of it in the project's queue, else the one running), and starts when its turn comes, first come first
served. It can be cancelled while it waits (`POST /api/jobs/<id>/cancel`: it leaves at once, `cancelled`, and the ones
behind it move up). Which jobs wait for which:
- *the new reader* (`new_reader`, and `reread` of one document, not of an excerpt) runs alone in its project: it waits
  until no other job of the project runs, and while it runs every other job waits for it (a job holding passage ids
  from before the move would put its results on passages that are gone). While it still waits, it (and search by
  meaning or another move waiting behind it) holds back only search by meaning and other moves, so a move waiting
  behind a check that waits for Claude Code never stalls the rest of the project;
- *adding documents* (`ingest`), *search by meaning* (`index`) and *a round of the shared folder* (`folder-sync`):
  adding waits for the other three and they for it; two of the same kind never run together; search by meaning and a
  round run beside each other;
- *new themes for one set of themes* (`theme-new`) run one after the other (two would take the same passages);
- everything else (checks, labels, themes, the glossary, codebooks tried out, the bibliography …) runs beside the
  others, except the new reader, as before; jobs that use the chat model still take turns for it, and a job waiting
  for its project's turn does not hold the model.
When both are asked for, the new reader goes first: search by meaning that still waits moves behind it (the other
waiting jobs keep their places), so no passage is prepared twice; search by meaning asked for while the new reader
waits or runs waits for it. `waiting_for` is null once the job has its
turn (a job that then waits only for the chat model is `queued` with `waiting_for` null, as before).

### Testing a model

`POST /api/benchmark` `{"reference": "/path/to/pilot", "kinds": ["verify_set", "extract"], "n": 10}` → job (kind
`benchmark`): runs the chosen model on tasks a reference workspace already answered and compares. Progress
`{"done", "total", "task", "model"}`. `result`: `{"model", "backend", "verdict": ["Checking claims: usable for a first
pass; …"], "table": [{"measure": "Usable answers on the first try", "Checking claims": "90%"}], "kinds": {…raw…}}`.
