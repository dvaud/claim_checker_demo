# Building on ENLENS

An app built on ENLENS (Margin is one) adds its features **in files of its own**, plus a short list of files that
ENLENS creates once and never edits again: the **local layer**. A new ENLENS release then merges without clashes,
because it never touches what the app wrote.

ENLENS stays complete on its own: every extension point below is empty, or ENLENS's default, in ENLENS, and nothing
changes for people who use ENLENS itself.

## Two ways to build on ENLENS

- **A fork** (a copy of ENLENS's repository, like Margin) fills in the local-layer files listed below. Its own new
  modules, views and tests live in files ENLENS does not have.
- **A separate package** installed next to ENLENS names an add-on module under the Python entry point group
  `enlens.extensions`, in its `pyproject.toml`:

  ```toml
  [project.entry-points."enlens.extensions"]
  fieldnotes = "fieldnotes_addon"
  ```

Both give ENLENS an **add-on module**: the fork's is `enlens_claims/gui/extensions.py`, a package's is the module its
entry point names. ENLENS reads both (`enlens_claims/addons.py`: the fork's first, then each package's by name).
ENLENS reads only the names a module defines and keeps its own default for every other one. An add-on that fails to
load is left out, ENLENS still starts, and the error is printed and kept (`addons.errors()`).

## The local layer

ENLENS releases **never edit** these files. ENLENS ships each one empty, or holding ENLENS's own values.

| File | What it is for |
| --- | --- |
| `src/enlens_claims/gui/static/site.css` | The installation's own look. Linked last, so it wins. |
| `src/enlens_claims/gui/static/brand.json` | The app's name and words. |
| `src/enlens_claims/gui/extensions.py` | The fork's add-on module. |
| `src/enlens_claims/gui/static/extensions.js` | The fork's page module (0.15.1). |
| `docs/ADDON_API.md` | The routes the app adds, documented like `docs/API.md`. |
| `docs/ADDON_MANUAL.md` | The manual for what the app adds. |

## The look: `site.css` and the theme tokens

`index.html` links ENLENS's stylesheets in release order, then a fixed comment, then `site.css`:

```html
<link rel="stylesheet" href="/static/tokens.css">
<link rel="stylesheet" href="/static/app.css">
…
<link rel="stylesheet" href="/static/v0134.css">
<!-- release stylesheets end -->
<link rel="stylesheet" href="/static/site.css">
```

Each release adds its own stylesheet just above the comment, so `site.css` always loads last.

The colours, faces, shadows and sizes are **tokens** (CSS custom properties) in `tokens.css`, for the light theme,
the dark theme chosen by the system, and the dark theme chosen in the app. A different look overrides them in
`site.css`; nobody edits `app.css` or `tokens.css` for it:

```css
:root { --accent: #8a3b12; --accent-strong: #6d2e0e; --font-ui: "Inter", system-ui, sans-serif; }
:root[data-theme="dark"] { --accent: #f0a46c; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --accent: #f0a46c; } }
```

A **package** puts its page files in a folder and names it in its add-on module:

```python
from pathlib import Path
STATIC = Path(__file__).with_name("static")
```

They are served at `/static/addons/<add-on>/…`. Its `site.css`, when there is one, is added to `/static/site.css`
after the installation's own.

## The name: `brand.json`

```json
{
  "name": "ENLENS",
  "tagline": "explore and check your documents",
  "welcome_title": "Explore your documents, and check what they say",
  "welcome_text": "ENLENS reads your reports, papers and interview notes. …",
  "description": "Explore your documents and check hypotheses against them, with verified quotes.",
  "logo": "/static/logo.svg"
}
```

`GET /api/state` returns it as `brand`, and the page takes the app's name, tagline, logo and welcome screen from
there. A package sets any of these keys in its add-on module instead (other keys are ignored):

```python
BRAND = {"name": "Fieldnotes", "tagline": "notes from the field", "logo": "/static/addons/fieldnotes/logo.svg"}
```

Page code names the app with `appName()` (or `brand()`) from `lib.js`, never with a fixed "ENLENS".

## Routes, downloads and extra keys (0.14)

An add-on module adds routes to the app's API. They are tried after ENLENS's own, so an add-on cannot take over one
of ENLENS's routes, and every one needs the page's token like ENLENS's:

```python
def get_drafts(h, name, q):            # h: the request handler; h.app: the app; h._body(): the JSON body
    ws = h.app.ws(name)                 # the project (404 when there is none)
    return {"drafts": [dict(r) for r in ws.query("SELECT draft_id, title FROM drafts")]}

def get_drafts_csv(h, name, q):         # a download: it sends its own answer and returns None
    h._send(200, b"draft_id,title\n", "text/csv; charset=utf-8")

ROUTES = [("GET", r"/api/projects/([^/]+)/drafts", get_drafts),
          ("GET", r"/api/projects/([^/]+)/drafts\.csv", get_drafts_csv)]
DOWNLOADS = {"get_drafts_csv"}          # handlers a plain link may call with ?token=
```

A handler is a function `handler(h, *groups, q)` (the pattern's groups, URL-decoded, then the query string) or the
name of one of ENLENS's handler methods. Document the routes in `docs/ADDON_API.md`.

Two functions add keys to what the page reads. A key ENLENS has (or an earlier add-on added) is never replaced, and a
hook that fails adds nothing:

```python
def state(app):  return {"drafts_enabled": True}                       # GET /api/state
def overview(ws): return {"drafts": ws.scalar("SELECT COUNT(*) FROM drafts")}   # a project's Overview
```

## Jobs (0.14)

Long work runs as a job, the same way ENLENS's own does. The app's public interface:

| Method | What it does |
| --- | --- |
| `app.ws(name)` | The project, or a 404 for the page. |
| `app.backend(kinds=…)` | The main model's backend and model, as Settings say. |
| `app.queue_mode()` | Whether Claude Code answers (the AI's tasks wait in the queue for it). |
| `app.start_job(kind, title, name, fn, uses_model=True, withdraw=(), ws=None)` | A job; `fn(job)` does the work. |
| `app.start_queued_job(kind, title, name, fn, withdraw=None)` | A job that uses the AI; `fn(job, backend, model, progress)`. |
| `app.follow_queued(job, ws, hyp_ids, tracker)` | Follow checks made by queue until Claude Code has answered them. |
| `app.wire(job, backend, tracker=None)` | Let a backend see the job's Stop and report its progress. |

An add-on's job is a job like any other: it is listed in `GET /api/jobs` and the sidebar, it can be stopped
(`POST /api/jobs/<id>/cancel`; `fn` checks `job.cancel.is_set()`), and it is *not running* (`on_hold`) while its tasks
wait in the queue with nothing answering them. `withdraw` names the kinds of task that Stop takes back out of the
queue. The names before 0.14 (`_job`, `_model_job`, `_follow_queued`, `_wire`) keep working.

## Tables and columns (0.14)

```python
SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts(draft_id TEXT PRIMARY KEY, title TEXT, text TEXT, ai_access TEXT, created_at TEXT);
"""
MIGRATIONS = [("drafts", "ai_note", "TEXT")]           # (table, column, type): added when a project lacks it
INDEXES = "CREATE INDEX IF NOT EXISTS ix_drafts_created ON drafts(created_at);"
```

Every project runs them as it is opened, after ENLENS's own and in the add-ons' order: `SCHEMA`, then the
`MIGRATIONS`, then `INDEXES`. Write them so that running them again changes nothing (`IF NOT EXISTS`); a column is
added only when it is missing. Table and column names are plain names (letters, digits and `_`).

**Where a hypothesis comes from.** `claimcheck.create_hypothesis(ws, text, …, origin="draft", origin_id=draft_id)`
records it in the hypothesis's `origin` and `origin_id` columns, so an add-on that makes hypotheses needs no column
or argument of its own. `check_hypothesis` and `queue_check` take the same two arguments. ENLENS uses `origin="batch"`
for *Check several*; a hypothesis typed by a person has none. Results and the history return both.

## Access (0.14)

Two hooks feed the checks ENLENS already makes. They only ever restrict more:

```python
from enlens_claims import access

def draft_floor(cx, payload, dflt):
    """A task holding a draft's text may go no further than the draft's own AI setting."""
    d = payload.get("draft_id") if isinstance(payload, dict) else None
    if not d:
        return None                     # nothing to say about this task
    row = cx.execute("SELECT ai_access FROM drafts WHERE draft_id=?", (d,)).fetchone()
    return (row[0] or dflt or "cloud") if row else "none"

def drafts_kept_here(ws):
    """The hypotheses the connector (a Claude chat) must not show."""
    return {r[0] for r in ws.query("SELECT h.hyp_id FROM hypotheses h JOIN drafts d ON h.origin='draft' "
                                   "AND h.origin_id=d.draft_id WHERE COALESCE(d.ai_access, 'cloud') != 'cloud'")}

access.register_floor(draft_floor)
access.register_hidden(drafts_kept_here)
```

- `register_floor(fn)`: `fn(cx, payload, dflt)` returns `"cloud"`, `"local"`, `"none"` or None. Every task takes the
  most restricted of its documents' settings and every floor's, so a task holding a draft marked *Only a local AI*
  is never handed to Claude Code, and the guard refuses it to any cloud model. A floor that fails counts as `none`.
- `register_hidden(fn)`: `fn(ws)` returns hypothesis ids. The connector leaves them out of `list_checks` and refuses
  to open them. A hook that fails hides every hypothesis.

ENLENS loads the add-ons before it decides anything, so hooks an add-on registers when it is imported always count.

## A kind of AI task of its own (0.15)

Every kind of task the AI answers is one `TaskKind` in `enlens_claims/taskkinds.py`. The tables the other modules
keep (`routing.KINDS`, `CLAUDE_DEFAULTS`, `HELPERS`, `taskqueue.ORDER`, `BATCH`, the names, `prompts.VERSIONS`,
`llm.OUTPUT_CAP`, `llm.JUDGING`, `tasks.HANDLERS`…) are views of the registry, so a kind an add-on registers is
queued, routed, stepped up, answered offline, stored and named like ENLENS's own:

```python
from pydantic import BaseModel
from enlens_claims import taskkinds

class ClaimsOut(BaseModel):
    claims: list[dict]

def store_claims(cx, t, payload, answer, model):     # answer: already checked against ClaimsOut and every quote
    for c in answer["claims"]:
        cx.execute("INSERT INTO draft_claims(draft_id, quote, claim) VALUES (?,?,?)",
                   (payload["draft_id"], c["quote"], c["claim"]))
    return True, []                                    # (ok, problems): problems send the answer back

taskkinds.register(taskkinds.TaskKind(
    name="draft_claims", prompt_version="draft-claims-v1",
    system=lambda: "You list the claims in a part of a draft…",   # the system prompt
    user=lambda payload: f"PART OF A DRAFT:\n{payload['text']}",  # the task's own prompt
    schema=ClaimsOut, quote_from=lambda payload: payload["text"], store=store_claims,
    certainty="claims",                 # the answer's list whose items carry `confidence` (an unsure answer steps up)
    claude=("sonnet", "opus"), local="large", helper="enlens-reader",
    batch=4, order=2.5,                 # the queue: tasks per batch; after "expand" (2), before "check" (3)
    noun=("part of a draft", "parts of a draft"), short="parts of drafts", title="Claims in drafts",
    run_name="Finding the claims in a draft", output_cap=1500,
    demo=lambda payload: {"claims": []},          # the offline demo's answer
    size=lambda k, max_chars: 6000))              # the longest task prompt, in characters
```

**The quote check is required.** A kind without `quote_from` is refused. ENLENS checks every answer of an add-on's
kind before its store function sees it: against `schema`, then every string under a key in `quote_fields` (default
`quote`), at any depth, must be found in the text `quote_from(payload)` gives (case, spacing and typography aside).
An answer that fails goes back with its problems, as for ENLENS's own kinds.

**The guard holds.** A task of an add-on's kind is made with `tasks._insert_task` like any other, so it takes the
setting of the documents (and floors) its payload names, is handed to Claude Code only when that is *cloud*, is
refused to a cloud model otherwise, and nothing leaves the computer under `--local-only`.

**Its own helper (optional).** `helper_file` (an agent `.md` in the plugin's format, tools limited to the queue's)
and `helper_model` give the kind a Claude Code helper of its own; the plugin ENLENS writes then carries it.

**Defaults.** What a kind does not say: its own Settings row, Sonnet stepping up to Opus (a large local model), a
batch of 5 at the end of the queue, an answer of up to 2,000 tokens.

## The page (0.15.1)

A page module adds pages, sidebar entries, Overview cards, job names, welcome cards and the result page's link back
to where a hypothesis comes from. A fork fills in `static/extensions.js` (ENLENS ships `export default {};`); a
package puts `extensions.js` in its `STATIC` folder, and `GET /api/state` lists it in `addon_pages` for the page to
import. The default export is an object, or a function returning one; every part is optional:

```js
import { h, api, App, P, pageHead } from "/static/lib.js";   // ENLENS's page helpers

async function renderDrafts(view, groups, query) {
  view.appendChild(pageHead("Drafts", { eyebrow: "Your writing" }));
  const r = await api("GET", `/api/projects/${P(App.project)}/drafts`);
  …
}

export default {
  sections: { writing: { title: "Your writing", short: "Writing", sub: "Check your own text against the documents." } },
  features: {
    drafts: { section: "writing", title: "Drafts", icon: "file-pen", href: "#/drafts", ai: "uses", nav: true,
              what: "Check the claims of a draft against your documents.",
              state: (o) => o.drafts ? [true, `${o.drafts} drafts`] : [false, "None yet"] },   // o: the Overview's counts
  },
  routes: [[/^\/drafts$/, "drafts", renderDrafts]],
  jobKinds: { "draft-check": { icon: "file-pen", text: "Checking a draft's claims", link: "#/drafts", withJob: true } },
  welcome: [{ icon: "file-pen", title: "Check a draft", text: "Paste your text: every claim is checked." }],
  origins: { draft: { eyebrow: "Back to the draft", meta: "from a draft", href: (id) => `#/drafts/${id}` } },
};
```

- **features** describe a part of the app once (`features.js`): `nav: true` gives it a sidebar entry with its AI
  mark, after the entries of its section (or under a new heading); the Overview shows a card in its section, with
  `state(o)` as its line (`overview: false` keeps it off; `overview: {section, order, title, what}` moves or words
  it). **sections** add a part of the app: a sidebar heading and an Overview section, after ENLENS's.
- **routes** (`PAGE_ROUTES`): `[pattern, the feature it lights up in the sidebar, render(view, groups, query)]`, tried
  after ENLENS's own pages.
- **jobKinds**: a job's row in the sidebar: its icon, name, link and whether the link follows the job (`?job=<id>`).
  The link may be a function of the job, for a page per item: `link: (j) => \`#/drafts/${j.scope}\``.
  A kind nobody names shows the job's own title.
- **welcome**: cards on the first-run welcome screen, under the welcome text (`brand.json`).
- **origins**: for a hypothesis made with `origin=` (0.14), the result page's eyebrow and meta line link back to it.

All of it lives in `registry.js` (`applyExtensions`), which never replaces one of ENLENS's entries. A page module
that fails to load is left out and the page still works.

## Rules that no add-on gets round

`home.local_only()` (switched off cloud models), the per-document AI settings and the quote check apply to anything
an add-on adds. ENLENS checks them; an add-on never has to, and cannot switch them off.

## Tests

Every extension point is tried with a stand-in add-on, `tests/fake_extension/`, the way `tests/fake_claude_cli.py`
stands in for Claude Code. The `addon` fixture turns it on through its entry point, as if it were installed; the
`local_addon` fixture fills in `gui/extensions.py` as a fork would (`tests/addon_fixtures.py`).

Tests of a release's stylesheet say which sheets it follows, not that it is linked last: `assert_sheet_after(sheet,
earlier)` in `tests/_static.py`. The routes-are-documented tests read every `docs/*API*.md`.

## Keeping it small, and stable

The interface is the names listed here. Changing one counts as a breaking change: it is written up in
`CHANGELOG.md`, and the old form keeps working for one minor version.
