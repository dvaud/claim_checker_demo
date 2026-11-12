"""0.14.3: the front end and its UX review. The pages are checked as the browser files they are (the same way as the
other page tests), the two server answers they rely on over the API."""
from __future__ import annotations

from pathlib import Path

from enlens_claims import claimcheck, ingest
from enlens_claims import home as ehome
from test_0112_stronger_model import HYP, Hedging  # noqa: F401
from test_app import api, home  # noqa: F401,E402  (fixtures)

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"


def _js(name):
    return (STATIC / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------ the server's two answers
def test_a_result_of_another_project_says_which(api, corpus):
    api("PUT", "/api/settings", {"backend": "baseline", "embed_backend": "off"})
    a, b = ehome.create_project("A"), ehome.create_project("B")
    ingest.ingest(a, [corpus])
    hid = claimcheck.check_hypothesis(a, HYP, Hedging(), "m", k=3, per_doc=2)
    st, body = api("GET", f"/api/projects/B/hypotheses/{hid}")
    assert st == 404 and body["in_project"] == "A"
    st, body = api("GET", "/api/projects/B/hypotheses/nothing-here")
    assert st == 404 and "in_project" not in body
    assert api("GET", f"/api/projects/A/hypotheses/{hid}")[0] == 200


def test_the_reason_there_is_no_stronger_model(api, corpus):
    ws = ehome.create_project("S")
    ingest.ingest(ws, [corpus])
    hid = claimcheck.check_hypothesis(ws, HYP, Hedging(), "m", k=3, per_doc=2)
    api("PUT", "/api/settings", {"backend": "baseline", "embed_backend": "off"})
    h = api("GET", f"/api/projects/S/hypotheses/{hid}")[1]
    assert h["stronger_model"] is None and h["stronger_reason"] == "model_per_task_off"
    api("PUT", "/api/settings", {"backend": "claude_code", "routing": False})
    h = api("GET", f"/api/projects/S/hypotheses/{hid}")[1]
    assert h["stronger_model"] is None and h["stronger_reason"] == "model_per_task_off"
    api("PUT", "/api/settings", {"backend": "claude_code", "routing": True, "claude_plan": "max"})
    h = api("GET", f"/api/projects/S/hypotheses/{hid}")[1]
    if h["stronger_model"] is None:
        assert h["stronger_reason"] == "top_model"
    else:
        assert h["stronger_reason"] is None


def test_the_page_words_each_reason():
    js = _js("views/result.js")
    for reason in ("top_model", "model_per_task_off", "one_local_model"):
        assert f'why === "{reason}"' in js
    assert "No stronger model is set. " not in js.split("current.stronger_reason")[0]


# ------------------------------------------------------------------ the result page
def test_notes_survive_the_reload_of_a_waiting_check():
    js = _js("views/result.js")
    assert "function armWait()" in js and "noteDirty" in js
    assert 'document.activeElement.id === "note"' in js                      # not while typing
    assert 'ta.addEventListener("blur"' in js and "saveNoteOnLeave" in js   # saved at once on blur and on leaving
    assert "if (!box.isConnected) return;" in js                             # no timer on a page that is gone (23)
    assert "waitTimer = setTimeout(() => load()" not in js
    assert "run.cancel" in _js("lib.js")


def test_the_answer_card_names_excerpts_that_wait_and_colleagues_who_differ():
    js = _js("views/result.js")
    assert "forYouLine" in js and "for your judgement: the answer may change" in js
    assert "[baseCaution, forYouLine]" in js          # said in addition to the other caution
    assert "judged differently from you" in js and "(differs from yours)" in js


def test_the_project_zip_is_downloaded_with_the_token_in_a_header():
    js = _js("views/result.js")
    fn = js[js.index("export function projectZipLink"):]
    fn = fn[:fn.index("\n}\n")]
    assert "zipButton(" in fn  # 0.18: the two downloads (what you shared, the whole project) live in share.js
    share = _js("views/share.js")
    fn = share[share.index("export async function downloadProject"):]
    fn = fn[:fn.index("\n}\n")]
    assert 'download(`/api/projects/${P(project)}/export.zip${shared ? "?scope=shared" : ""}`)' in fn
    assert "token=" not in fn and "TOKEN" not in fn


def test_a_result_in_another_project_offers_the_switch():
    js = _js("views/result.js")
    assert "e.data.in_project" in js and "Switch to" in js


# ------------------------------------------------------------------ documents
def test_loosening_an_ai_setting_is_asked_about_and_a_table_that_fits():
    js = _js("views/sources.js")
    assert "confirmLoosen" in js and "cannot be taken back" in js
    assert 'if (!(await confirmLoosen(ids, level))) { await reloadDocs(); return; }' in js
    # Open and Remove sit in the title cell, not in a last column that was out of sight
    assert 'class: "doc-actions"' in js and 'h("td", { class: "actions" }' not in js
    assert "docs[at] = d" in js


def test_files_picked_during_a_run_are_kept_for_the_next():
    js = _js("views/sources.js")
    assert "let adding = false" in js and "|| adding;" in js
    assert "for (const f of sent)" in js and "files.length = 0; drawFiles()" not in js


# ------------------------------------------------------------------ the app is not answering
def test_a_failed_request_is_never_no_documents():
    assert "catch (_) { o = {}; }" not in _js("views/overview.js")
    lib, app = _js("lib.js"), _js("app.js")
    assert "export const Connection" in lib and "connection(true)" in lib and "connection(false)" in lib
    assert "enlens-connection" in app and "has stopped answering" in app
    assert 'id="stopped-banner"' in _js("index.html")
    for view in ("history.js", "sources.js", "concepts.js", "bibliography.js"):
        assert "failedLoad(" in _js(f"views/{view}")
    assert "showError(e); }\n  const st" not in _js("views/search.js")


# ------------------------------------------------------------------ sidebar, keyboard, contrast
def test_the_queue_panel_scrolls_into_view_and_the_skip_link_works():
    app = _js("app.js")
    # 0.17.0: the foot of the sidebar stays in the window, so an open panel is always in view: keepInView went
    # (tests/test_0_17_0_sidebar.py)
    assert "keepInView(" not in app and "sidebarScrollInit();" in app
    assert 'querySelector(".skip-link")' in app and "e.preventDefault()" in app
    assert "main.inert = open" in app and "main.inert = false" in app


def test_help_notes_keep_focus_and_heat_cells_have_buttons():
    lib = _js("lib.js")
    assert "pop.contains(e.relatedTarget)" in lib
    from _static import rule  # 0.17.0: reads the cascade, so it holds when the rules move

    assert '"heat-btn"' in lib and rule(".heat-btn")


def test_text_colours_pass_contrast():
    from _static import rule  # 0.17.0: reads the cascade, so it holds when the rules move

    assert rule(".faint")["color"] == "var(--muted)"
    assert rule(".nav-group")["color"] == "var(--muted)"


# ------------------------------------------------------------------ batch, settings, explore pages
def test_check_several_leaves_out_lines_the_check_would_refuse():
    js = _js("views/hypotheses.js")   # 0.17.0: Check several is the list mode of the Hypotheses page
    assert "MIN_CHARS = 10" in js and "it.text.length >= MIN_CHARS" in js
    assert "(e.index ?? 0) + 1" not in js                               # the back end counts from 1
    pr = _js("views/progress.js")
    assert "this.partsBox.hidden = finished" in pr and "res.checked.length" in pr


def test_settings_say_what_is_not_saved():
    js = _js("views/settings.js")
    assert "save({ use_fable: on }, st)" in js and "Not saved yet: press Save." in js


def test_explore_pages_of_an_empty_project_say_add_documents_first():
    for view in ("search.js", "profile.js", "concepts.js"):
        assert "addDocumentsFirst(" in _js(f"views/{view}")
    assert "export function noDocuments" in _js("lib.js")


def test_small_fixes():
    from _static import rule  # 0.17.0: reads the cascade, so it holds when the rules move

    ql = _js("views/quicklook.js")
    assert "docx" in ql.split("const OK")[1].split("\n")[0]            # the pattern accepts what the chooser offers
    # 0.17.0 (design guide): the wrapping button is button({ wrap: true }); the helper adds the btn-wrap class
    assert "wrap: true" in _js("views/setup.js") and rule(".btn-wrap")
    assert "lock.on" in _js("views/projects.js") and "lock && lock.on" in _js("lib.js")
    assert "https?:" in _js("views/bibliography.js")
    assert "per-doc-label" in _js("views/search.js")
    assert "weak match by meaning" in _js("views/profile.js")
