# ENLENS local app: HTTP API

The app (`enlens-gui`) is a small HTTP server on `127.0.0.1` (default port 8765) that serves one static page
(`src/enlens_claims/gui/static/`) and a JSON API under `/api/`. Everything stays on the computer; text goes only to
the model service chosen in Settings.

## Rules

- **Token.** `GET /` returns `index.html` with `{{ENLENS_TOKEN}}` replaced by a random token for this run (and
  `{{ENLENS_VERSION}}` by the version). Every API call sends it as the header `X-Enlens-Token`. The endpoints a
  plain link opens (the exports `…/export.csv|json|xlsx|zip`, the original file `…/documents/<id>/file`, and the
  0.7 downloads: search, profile and themes exports, highlighted copies, the FlexiConc file) also accept `?token=`.
- **Host.** Requests must name `127.0.0.1:<port>`, `localhost:<port>` or `[::1]:<port>` in `Host`; requests carrying an
  `Origin` other than their own `Host` are refused (403).
- **Network mode** (`enlens-gui --host 0.0.0.0`): `Host` may also be an IP address of the computer (never a domain
  name: that could be DNS rebinding). The page is served without the token (`{{ENLENS_TOKEN}}` becomes empty); the
  token comes in the link printed in the terminal, `http://<address>:<port>/#token=<token>`, which the page reads
  from `location.hash` and keeps in `sessionStorage`.
- **Content Security Policy** on the page: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
  img-src 'self' data:; font-src 'self' data:; connect-src 'self'`. No inline `<script>`, no external resources.
- **Static files**: `GET /static/<file>` serves files from the `static/` folder (also `/<file>` with an extension).
  Any path without an extension returns `index.html` (use hash routing anyway: `#/check`, `#/h/<id>` …).
- **JSON in, JSON out.** Request bodies are JSON objects (`Content-Type: application/json`), except uploads (raw bytes).
- **Errors**: status 4xx/5xx with `{"error": "plain-language message", "kind": "request" | "backend" | "internal"}`.
  `kind: "backend"` (HTTP 502) means the model service is the problem (not running, model missing, key wrong): offer
  a link to Settings. 401 means the token is wrong: ask to reload.
- **Jobs.** Long work returns `{"job": Job}` at once; poll `GET /api/jobs/<id>` (about every 500 ms while
  `state` is `queued` or `running`). Jobs that use the chat model run one at a time; others wait in `queued`.
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
| `not_checked` | Not finished yet |
| `failed` | The check did not work |

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
 "jobs": [Job summaries of queued/running jobs]}
```
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
kept in memory for this run only. `DELETE /api/settings/key` forgets both.

`GET /api/servers` → local model servers running now (probed in parallel, < 1 s):
```json
{"servers": [{"kind": "ollama", "url": "http://localhost:11434", "version": "0.12.3",
              "models": ["bge-m3:latest", "qwen3:8b"], "chat_models": ["qwen3:8b"], "embedding_models": ["bge-m3:latest"],
              "loaded": ["qwen3:8b"], "modified": {"qwen3:8b": "2026-09-30T08:12:00Z", "bge-m3:latest": "…"}},
             {"kind": "openai", "url": "http://localhost:1234/v1", "models": […], "chat_models": […], "embedding_models": […]}]}
```

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
(not copied). `DELETE /api/projects/<p>` `{"confirm": "<p>"}` → `{"result": "unlinked" | "moved to …/trash/…"}`.

`GET /api/projects/<p>/export.zip` → the whole project as one zip, to give to a colleague or move to another
computer: a consistent copy of the database, `config.json`, the project's codebooks, `uploads/`, and the original
file of every other document (as `originals/<doc_id>/<name>` when it was read from outside the project folder).
Built in a temporary file and sent in chunks; the file name is readable ("ENLENS project - Demo - 2026-10-28.zip").
`POST /api/projects/import?name=<name>` with the zip as the raw body → `{"project": summary}` (it becomes the
current project). Without `name` the project keeps the name it had, with " (2)" added when that is taken; a `name`
that is taken → 409. 400 for a file that is not a zip, or a zip without a project (`enlens.sqlite`). Paths in the zip
cannot leave the new project folder, and its size is capped.

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
(optional keys are absent when empty). `ocr`: PDFs whose scanned pages were read by OCR (on this computer, at low
priority). `scanned_no_text`: PDFs with scanned pages that stayed without text (OCR off or not installed): say
"Scanned: no text. Ask IT to install Tesseract to read it." A wholly scanned PDF without OCR is also in
`empty_files` and is not added.

`GET /api/projects/<p>/documents/<doc_id>?offset=0&limit=50` → document details with its passages:
`{"doc_id", "title", "file", "kind", "n_pages", "n_chars", "doi", "added_at", "total_passages", "offset",
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

`DELETE /api/projects/<p>/documents/<doc_id>` → `{"removed": {...counts}}` (past checks keep their evidence).
`DELETE /api/projects/<p>/documents` `{"confirm": true}` → removes every document **and every check**.

`POST /api/projects/<p>/index` → job (kind `index`) that embeds passages without a vector; progress `{"done", "total"}`;
result: the `search` state plus `added` and `remaining`; 400 when no embedding model is set.

`GET /api/projects/<p>/passages/<passage_id>?around=1` → a passage with its neighbours, for "show in context":
`{"passage_id", "doc_id", "title", "page", "passages": [{"passage_id", "page", "text", "section", "current": bool,
"start", "breaks"}]}` (404 when the document was removed since; `breaks` as on excerpts, below).

### Frameworks (optional codebooks)

`GET /api/projects/<p>/frameworks` → `{"frameworks": [info]}` (always includes `sdg`).
`GET /api/projects/<p>/frameworks/<name>` → `{"framework": {...info, "items": [{"code", "description", "group", "group_name"}]}}`.
`POST /api/projects/<p>/frameworks` `{"name": "h2", "csv": "code,description\nH1,…", "title": "…", "label": "hypothesis code"}`
→ `{"framework": info}`; 400 with the row problem. `DELETE /api/projects/<p>/frameworks/<name>`.
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
where a second model disagrees with the main one: tag "models disagree on N"). `supports`/`partly`/`refutes` count the excerpts whose
judgement counts at this threshold, `uncounted` those below it; `docs_*` count documents as the result page does;
`reviewed` counts the excerpts a person judged (agreeing or not), `corrected` those where they changed the AI's
judgement, `to_review` the excerpts read that nobody judged yet.

`GET /api/projects/<p>/hypotheses/<hyp_id>?threshold=0.6` →
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
 "incomplete": false,                      // a part failed or is not graded yet
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
judgements for or against that nobody reviewed yet.
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

`DELETE /api/projects/<p>/hypotheses/<hyp_id>` → `{"deleted": "h…"}`.
`PUT /api/projects/<p>/hypotheses/<hyp_id>/note` `{"note": "…"}` → `{"saved": true}`.
`GET /api/projects/<p>/hypotheses/<hyp_id>/export.xlsx` → an Excel file for people, in the app's own words and local
times, with two sheets: *Summary* (one row per hypothesis: answer, answer for each part, documents per side, excerpts
that count / too uncertain / read, judgements reviewed and changed by the person, excerpts not reviewed yet, notes,
code, strictness, the AI model for a methods section) and *Excerpts* (every excerpt read: judgement, judged by, the
AI's own judgement, AI certainty, counted in the answer, quote and who chose it, document, where, the person's
comment, the full excerpt, notes, code). `.csv` and `.json` give the technical forms.
`GET /api/projects/<p>/export.xlsx?threshold=` → the same for every check of the project, plus a sheet *Map* (the
evidence map: one row per hypothesis, one column per document, + supports, (+) partly, − contradicts, ± both, with
the number of excerpts that count); `export.csv` the technical CSV (ids, raw verdicts, UTC times). File names are
readable ("ENLENS results - <project> - <date>.xlsx"). From 0.6 the *Excerpts* sheet also has "About another group
(AI's note)" and "AI's earlier judgement (before reading it again)", and, when a second model read any of the
excerpts, "Second model", "Second model's judgement", "Second model's certainty", "The two models agree". The
*Summary* sheet has "Excerpts where a second model disagrees" and "Documents added since the check".

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
- `POST /api/projects/<p>/profile/keywords {framework?}` → job: the keyword (and meaning) pass, seconds.
- `GET /api/projects/<p>/profile/plan?framework=&docs=&all=1` → `{passages, with_candidates, already_read,
  to_read, estimate_seconds, run: {now, last, changed}}`; `changed` lists what differs from the last run (model,
  digest, prompt, seed, settings).
- `POST /api/projects/<p>/profile/label {framework?, doc_ids?, all_passages?, limit?}` → job: the AI reads the
  passages (task `label`, prompt `label-v1`). Its result: `{read, failed, planned, stopped, changes: {confirmed,
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

- `GET /api/projects/<p>/themes` → `{runs, auto_mode, auto_why, k}`; each run has `themes_now` (after merges).
- `POST /api/projects/<p>/themes {k?, seed?, mode?: auto|meaning|words}` → job: a new set of themes (spherical
  k-means; the same documents and settings give the same themes). A small project gets fewer themes than `k`
  (about three passages a theme); fewer than 5 passages is an error.
- `GET /api/projects/<p>/themes/<run>?framework=` → the themes (names, key terms, size, documents,
  representative passages), `doc_grid` and `code_grid`. `GET …/themes/<run>/<theme_id>?offset=&limit=` → one theme
  and its passages. `DELETE …/themes/<run>`.
- `PUT /api/projects/<p>/themes/<run>/edit {what: rename|merge|move, theme_id?, value?, passage_id?}`: kept as
  reviews, so they survive a new set with the same settings; `value: null` (or `""` for a name) undoes.
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
- `GET /api/routing` → `{"route", "route_name", "rows": [{"row", "kinds", "title", "model", "step_up", "helper",
  "chosen", "recommended"}], "aliases", "fable", "local_small_model", "second_model", "step_up_below", "routing"}`.
- `GET /api/claude-setup` → `{"folder", "ready", "commands": ["claude plugin marketplace add …", "claude plugin
  install enlens-run@enlens"], "terminal": "enlens claude-setup", "in_claude_code": [...], "local_only"}`;
  `POST /api/claude-setup` writes the plugin into the data folder and adds `"problems": []`.
- Settings (`PUT /api/settings`): `allow_claude_code`, `use_fable`, `task_models` (`{"claude": {"label": "sonnet"},
  "local": {"label": "llama3.2:3b"}}`), `local_small_model`, `routing` (default true).
- `GET /api/state` adds `queue: {"waiting"}` for the current project.
- Results: a hypothesis has status `waiting` while a check by queue is not finished; `GET …/hypotheses/<id>` adds
  `stronger_model`, `queue_command`, `queue`, and per part `rounds_info[]` `task_id`, `stepped_up`,
  `stronger_waiting`, `waiting`; an excerpt's `ai_history[].why` is `"stepped up"` for a stronger model's reading.
- Themes carry `number` (1 to n in the order shown) and `merged_from_names`; `PUT …/concepts/links` accepts
  `decision: "undo"`.

### Subscription first, Claude Code set up and started from the app, the overview (0.9)

- A new installation's settings have `backend: "claude_code"` and `allow_claude_code: true`. With `--local-only` the
  default is `"auto"` (and `allow_claude_code` false).
- `GET /api/claude-setup[?refresh=1]` adds `"status"`: `{"found", "path", "version", "signed_in": true | false |
  null, "written", "installed": true | false | null, "plugin_version", "ready", "local_only"}` (from `claude
  --version`, `claude auth status` and `claude plugin list --json`; cached for 30 s, `refresh=1` reads again).
- `POST /api/claude-setup` `{}` prepares the plugin and, when Claude Code is found, adds it to Claude Code →
  `{..., "steps": [{"step", "ok", "text"}], "status", "commands", "problems"}`; `{"write_only": true}` only writes
  the plugin (as 0.8); `{"check": true}` also starts the connector to check it.
- `POST /api/projects/<p>/queue/claude-code` → `{"running", "started_at", "seconds", "exit_code", "report",
  "stopped"}`: starts Claude Code headless for the project's queue (`claude -p "/enlens-run:enlens-run <p>"
  --allowedTools Agent mcp__plugin_enlens-run_enlens__{queue_status,next_tasks,submit_answers,release}`), one run per
  project; adds the plugin first if needed. 400 when Settings do not name Claude Code, when Claude Code is not found,
  or with `--local-only`.
- `POST /api/projects/<p>/queue/claude-code/stop` → the same object: stops it, and gives the batches it had taken
  back to the queue at once.
- `GET /api/projects/<p>/queue` adds `"runner"` (as above, or `{"running": false}`), and on the Claude Code route
  `"can_start"` and `"claude": {"found", "signed_in", "installed", "ready"}`.
- `POST /api/servers/test` on the Claude Code route answers from the set-up status: `model_available` is whether it
  is ready, `claude` the status, `warning` when it is not signed in.
- `GET /api/projects/<p>/overview` → `{"documents", "passages", "profile": {"framework", "keyword", "labels",
  "documents"}, "concepts": {"terms", "concepts"}, "themes": {"runs", "themes", "latest"}, "references",
  "hypotheses", "waiting"}`: what each feature has made, for the Overview page.

### Set-up in one button, moving to another computer (0.10)

- `GET /api/claude-setup` adds `"installer"` (the line of Anthropic's Claude Code installer for this system:
  `curl -fsSL https://claude.ai/install.sh | bash`, or `irm https://claude.ai/install.ps1 | iex` on Windows) and
  `"docs"` (Anthropic's set-up page).
- `POST /api/claude-setup/claude-code` `{}` → job (kind `claude-install`): runs that installer (the page shows the
  command and asks first). `result`: `{"ok", "text", "status"}`; the job ends in `error` when Claude Code could not
  be installed. 409 when Claude Code is already found; 403 with `--local-only`.
- `POST /api/claude-setup/sign-in` `{}` → `{"opened", "window", "command": "claude"}`: opens a terminal window
  (Terminal on macOS, PowerShell on Windows, the first terminal found on Linux) already running `claude`, for the
  one-time sign-in; `opened: false` when no window could be opened (the page then shows the line to type). The page
  then reads `GET /api/claude-setup?refresh=1` every few seconds until `status.signed_in` is true, and adds the
  plugin. 400 when Claude Code is not found, or with `--local-only`.
- On start, the app writes the Claude Code plugin again (and runs the two set-up commands again, quietly) when the
  plugin names another Python or another data folder than this ENLENS (it moved, or was installed again).
- `GET /api/move.zip` (a download; the token may be given as `?token=`) → one zip with every project (each as the
  zip of `GET /api/projects/<p>/export.zip`, under `projects/NNN.zip`) and `enlens-move.json`: `{"format":
  "enlens-move", "version", "made", "projects": [{"name", "file", "documents", "linked", "missing"}], "current",
  "settings"}`. Quick looks not kept are left out, and so is a saved Claude API key.
- `POST /api/projects/import` also takes that zip → `{"moved": {"projects": [{"from", "name", "documents"}],
  "settings": bool, "current", "made", "version"}, "project": summary of the current one}`. A project whose name is
  taken comes in as `name (2)`. The settings come along only when this computer has no project yet; with
  `--local-only`, never the choice of a cloud AI.
- `GET /api/state` adds `"installation": {"kind": "git" | "script" | "package" | "pip", "system": "mac" | "windows"
  | "linux", "line", "releases"}`, and `ocr` adds `"install"` when Tesseract is missing: `{"text", "command", "link",
  "link_text"}` for this system.

### Jobs

`GET /api/jobs` → `{"jobs": [Job summary]}` newest first. `GET /api/jobs/<id>` → full Job:
```json
{"id": "fdd6a426a6f0", "kind": "check" | "prepare" | "batch" | "more" | "reread" | "read-new" | "second-opinion" |
         "ingest" | "index" | "benchmark" | "label" | "link" | "theme-names" | "resolve" | "stronger" | "queue-run" |
         "claude-install" | …,
 "title": "…", "queue": false,
 "project": "Demo" | null, "state": "queued" | "running" | "done" | "error" | "cancelled",
 "created_at": 1793136448.87, "started_at": … | null, "finished_at": … | null, "seconds": 19.9,
 "error": null | "message", "error_kind": null | "backend" | "request" | "internal",
 "progress": {…kind-specific…}, "result": {…} | null}
```
Summaries (in lists) omit `progress` and `result`. Jobs live until the app is closed.

### Testing a model

`POST /api/benchmark` `{"reference": "/path/to/pilot", "kinds": ["verify_set", "extract"], "n": 10}` → job (kind
`benchmark`): runs the chosen model on tasks a reference workspace already answered and compares. Progress
`{"done", "total", "task", "model"}`. `result`: `{"model", "backend", "verdict": ["Checking claims: usable for a first
pass; …"], "table": [{"measure": "Usable answers on the first try", "Checking claims": "90%"}], "kinds": {…raw…}}`.
