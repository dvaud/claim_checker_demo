"""0.17.0: one Hypotheses page in place of Check a hypothesis, Check several and Results. One box takes one hypothesis
or a list (its mode follows the text), the progress of the check the page follows is under it, then every answer with
the checks still running or waiting their turn at the top. The evidence map is the place's other view. Checked as the
browser files they are, like the other page tests, and through the API the page relies on."""
from __future__ import annotations

import re
import time
from pathlib import Path

from test_app import CLAIM, api, home  # noqa: F401  (fixtures)

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"


def _js(name):
    return (STATIC / name).read_text(encoding="utf-8")


def _css():
    """Every ENLENS stylesheet of the page, in link order (0.17.0: tests/_static.py all_css; site.css is left out)."""
    from _static import all_css

    return all_css()


def _fn(src, start, end="\n  }\n"):
    i = src.index(start)
    return src[i:src.index(end, i)]


# ------------------------------------------------------------------ one place, three pages gone
def test_the_three_old_pages_are_one():
    views = STATIC / "views"
    assert not (views / "check.js").exists() and not (views / "batch.js").exists()
    for p in STATIC.rglob("*.js"):
        src = p.read_text(encoding="utf-8")
        assert "views/check.js" not in src and "views/batch.js" not in src and "renderHistory" not in src, p.name
    hyp = _js("views/hypotheses.js")
    assert "export async function renderHypotheses(view, params, query)" in hyp
    assert "export async function renderMap(view, params, query)" in _js("views/map.js")
    # the answers are part of the page: no head of their own, and the address they keep is the page's
    hist = _js("views/history.js")
    assert "export async function answersList(box, query, opts = {})" in hist and "pageHead(" not in hist
    assert '"#/hypotheses" + (s ? "?" + s : "")' in hist and "#/history" not in hist
    assert "Show as a map" not in hist and "Show as a map" not in hyp


def test_the_head_and_the_tabs():
    hyp = _js("views/hypotheses.js")
    assert 'pageHead("Hypotheses", { eyebrow: featureEyebrow("check"), sub: ' in hyp and "actions: downloads }" in hyp
    assert 'viewTabs("hypotheses", "answers")' in hyp
    # the downloads of every answer, as one quiet line of links
    head = hyp[hyp.index("const downloads = downloadLinks(["):hyp.index("const tabs = viewTabs(")]
    assert '"Excel (.xlsx)"' in head and '"CSV"' in head and "export.xlsx" in head and "export.csv" in head
    # the notices of the old Check page
    assert "No AI model is set up yet, so checks cannot run." in hyp and "Add documents first." in hyp
    # the map is the place's other view, and a set stays one set from one tab to the other
    m = _js("views/map.js")
    assert 'pageHead("Hypotheses", {' in m and 'eyebrow: featureEyebrow("check")' in m and 'viewTabs("hypotheses", "map")' in m
    assert "`#/hypotheses?batch=${encodeURIComponent(batch)}`" in m and "#/history" not in m
    assert "`#/map?batch=${encodeURIComponent(batch)}`" in hyp and "onBatch: setMapTab" in hyp


# ------------------------------------------------------------------ the box
def test_one_box_for_one_hypothesis_or_a_list():
    hyp = _js("views/hypotheses.js")
    # 0.17.0 (design guide): the box is made by the textarea() helper (hyp: true), not a hand-spelled textarea
    box = hyp[hyp.index("const ta = textarea({"):hyp.index("\n", hyp.index("const ta = textarea({"))]
    assert 'placeholder: "A hypothesis, or several: one per line"' in box and "maxlength" not in box
    assert "ta.style.height = `${ta.scrollHeight + 2}px`" in hyp   # it grows with its text
    # the mode follows the text: two non-empty lines or more (a CSV has its header and a row) are a list
    mode = _fn(hyp, "export function composerMode(text)", "\n}\n")
    assert '.filter((l) => l.trim()).length >= 2 ? "list" : "single"' in mode
    # a list: the server reads it as the check will, a moment after the typing stops
    assert "/batches/preview" in hyp and "const previewSoon = debounce(preview, 400);" in hyp
    assert "checked one after the other" in hyp and "too short and will be skipped" in hyp
    # 0.17.0 (design guide): the fold helper makes the summary
    assert 'fold({ class: "hyp-list-fold", hidden: true }, "Show the list"' in hyp
    # a list hides what belongs to one hypothesis: the split hint, Look before checking, the codebook tag
    apply = _fn(hyp, "function applyMode()")
    assert "lookWrap.hidden = many;" in apply and "if (tagRow) tagRow.hidden = many;" in apply and "splitHint.hidden = true;" in apply
    # the button says how many: "Check" for one hypothesis, "Check 3" for a list
    buttons = _fn(hyp, "function drawButtons()")
    assert '"Check"' in buttons and "`Check ${list.ready}`" in buttons
    # one way to load a file in both modes; the text it brings decides the mode
    assert "Load a spreadsheet (CSV) or text file" in hyp and "ta.value = await f.text(); onText();" in hyp


def test_the_ai_marks_and_the_line_on_who_reads():
    hyp = _js("views/hypotheses.js")
    # one AI mark for the row of buttons (the 0.17 rule), after both of them, not one beside each
    assert 'h("div", { class: "btn-row hyp-actions" }, runBtn, lookWrap, aiTag("uses"))' in hyp
    assert hyp.count("aiTag(") == 1 and "hyp-btn-group" not in hyp
    # "Look before checking" uses the AI only to split the hypothesis and find other words: its tooltip follows them
    assert 'o.decompose || o.expand ? "Uses the AI."' in hyp
    assert "options.addEventListener(\"change\", () => {\n    drawLookTag();" in hyp
    # which AI reads, from the settings, with the icon of the sidebar's AI line
    reads = _fn(hyp, "export function readsLine()", "\n}\n")
    assert "App.privacy()" in reads and "reads the excerpts it needs" in reads and "icon(p.icon" in reads
    assert "`${p.label}, reads the excerpts it needs.`" in reads   # "Claude, on your plan, reads the excerpts it needs."
    assert "readsLine()," in hyp


def test_keys_and_the_draft():
    hyp = _js("views/hypotheses.js")
    keys = hyp[hyp.index('form.addEventListener("keydown"'):]
    assert '(e.ctrlKey || e.metaKey) && e.key === "Enter"' in keys and "form.requestSubmit()" in keys
    # Enter alone makes a new line in the box; in a small field it does not start a check
    assert 'e.key === "Enter" && e.target.tagName === "INPUT"' in keys
    submit = hyp[hyp.index('form.addEventListener("submit"'):hyp.index('form.addEventListener("keydown"')]
    assert 'composerMode(ta.value) === "list") checkList(); else checkOne();' in submit
    # one draft for both modes; a list left on the old Check several page comes along once
    assert 'session("draft")' in hyp and 'session("batchDraft", null)' in hyp and 'session("batchDraft",' not in hyp.replace('session("batchDraft", null)', "")


def test_progress_then_the_answers_then_how_it_works():
    hyp = _js("views/hypotheses.js")
    order = [hyp.index("view.appendChild(form);"), hyp.index("view.appendChild(progressBox);"),
             hyp.index("view.appendChild(answersBox);"), hyp.index('"What happens when you check"')]
    assert order == sorted(order)
    # one hypothesis: its job, then its result page; a list: its job, the summary, and the answers refresh
    one = _fn(hyp, "function followCheck(")
    assert "navigate(`#/h/${encodeURIComponent(job.result.hyp_id)}`)" in one
    many = _fn(hyp, "function followBatch(")
    assert "answers.refresh()" in many and "summary(job)" in many
    assert "answers.showBatch(r.batch_id)" in hyp and "#/history" not in hyp
    # a job the page is sent to (?job=, the sidebar, a row of the answers) or followed before a reload
    assert "[query.job, session(\"activeCheck\"), session(\"activeBatch\")]" in hyp


def test_running_checks_are_rows_at_the_top_of_the_answers():
    hist = _js("views/history.js")
    assert 'const CHECK_KINDS = ["check", "batch"];' in hist and 'api("GET", "/api/jobs")' in hist
    row = _fn(hist, "function jobRow(j)")
    assert "`#/hypotheses?job=${encodeURIComponent(j.id)}`" in row
    assert '"Waiting its turn"' in row and '"Checking…"' in row and 'j.state === "queued"' in row
    draw = _fn(hist, "function drawTable()")
    assert "jobs.map(jobRow), rows.map(" in draw
    # a check being made has its answer row from the start: it is shown once, as the running check
    assert "UNFINISHED.has(x.status)" in draw and "norm(x.text || x.claim).startsWith(t)" in draw
    assert "running.filter((j) => j.id !== skip)" in draw   # the one the page follows is shown above, not here
    # the other jobs the answers follow when sent to them
    assert '"read-new": "Reading the new documents"' in hist and '"second-opinion":' in hist and 'more: "Looking for more evidence"' in hist
    css = _css()
    # 0.17.0 (design guide): the state of a running check is a workState(), no .badge-job pill any more
    assert 'workState("running", "Checking…")' in hist
    assert ".hyp-job-row" in css and ".hyp-compose .textarea-hyp" in css


def test_the_result_page_says_all_hypotheses():
    res = _js("views/result.js")
    assert "All results" not in res and "Back to results" not in res and "#/history" not in res
    # 0.17.0 (design guide, changed on purpose): the way back is a back link (link({ kind: "back" })), not a hand-made one
    assert 'link({ kind: "back", href: "#/hypotheses" }, "All hypotheses")' in res
    assert "`#/hypotheses?batch=${encodeURIComponent(r.batch_id)}`" in res   # after deleting one of a set


# ------------------------------------------------------------------ the API behind it
def _project(api, corpus):
    assert api("PUT", "/api/settings", {"backend": "baseline"})[0] == 200
    api("POST", "/api/projects", {"name": "Demo"})
    for f in sorted(corpus.iterdir()):
        api("POST", f"/api/projects/Demo/uploads?batch=b1&name={f.name}", raw=f.read_bytes())
    st, r = api("POST", "/api/projects/Demo/ingest", {"batch": "b1"})
    assert api.wait(r["job"]["id"])["state"] == "done"


def test_a_list_and_a_spreadsheet_read_as_the_page_counts_them(api, corpus):
    _project(api, corpus)
    st, r = api("POST", "/api/projects/Demo/batches/preview", {"text": CLAIM + "\nshort\nHydrogen export hubs create local jobs.\n"})
    assert st == 200 and [len(i["text"]) >= 10 for i in r["items"]] == [True, False, True]   # 2 to check, 1 too short
    csv = "hypothesis,code\n\"" + CLAIM + "\",6.4\nok,\n"
    st, r = api("POST", "/api/projects/Demo/batches/preview", {"text": csv})
    assert st == 200 and r["items"][0]["code"] == "6.4" and r["items"][0]["framework"] == "sdg" and r["items"][1]["text"] == "ok"
    st, r = api("POST", "/api/projects/Demo/batches/preview", {"text": "\n".join(f"Hypothesis number {i} holds." for i in range(501))})
    assert st == 400 and "At most 500" in r["error"]   # shown in the box's line, and Check waits


def test_a_running_check_is_found_and_matched_to_its_answer_row(api, corpus):
    _project(api, corpus)
    # Claude Code chosen and nothing answering: the check waits in the queue, its answer row is there already
    assert api("PUT", "/api/settings", {"backend": "claude_code"})[0] == 200
    text = "Green  hydrogen production,   made with water from desalination plants on dry coasts, can increase water " \
           "stress in arid regions where groundwater is already scarce and farming competes for it."
    st, r = api("POST", "/api/projects/Demo/checks", {"text": text, "k": 2})
    assert st == 200
    job_id = r["job"]["id"]
    st, b = api("POST", "/api/projects/Demo/batches", {"items": [{"text": CLAIM}, {"text": "Hydrogen export hubs create local jobs."}], "k": 2})
    assert st == 200
    try:
        t0 = time.time()
        while True:
            rows = api("GET", "/api/projects/Demo/hypotheses")[1]["hypotheses"]
            if rows or time.time() - t0 > 20:
                break
            time.sleep(0.1)
        jobs = {j["id"]: j for j in api("GET", "/api/jobs")[1]["jobs"]}
        j = jobs[job_id]
        assert j["kind"] == "check" and j["project"] == "Demo" and j["state"] in ("queued", "running")
        assert "on_hold" in j and "seconds" in j
        assert jobs[b["job"]["id"]]["kind"] == "batch" and jobs[b["job"]["id"]]["title"] == "2 hypotheses"   # "A list of 2 hypotheses"
        # the page's rule (history.js drawTable): an unfinished answer whose text starts with a running check's title
        norm = lambda t: " ".join((t or "").split())  # noqa: E731
        mine = [x for x in rows if x["status"] in ("not_checked", "waiting") and norm(x["text"]).startswith(norm(j["title"]))]
        assert len(j["title"]) == 120 and len(mine) == 1 and norm(mine[0]["text"]) == norm(text)
    finally:
        for jid in (job_id, b["job"]["id"]):
            api("POST", f"/api/jobs/{jid}/cancel")
            api.wait(jid)


def test_the_old_addresses_still_lead_here():
    app = _js("app.js")
    for path in ("hypotheses", "check", "batch", "history"):
        assert re.search(r"\[/\^\\/" + path + r"\$/, \"[a-z]+\", renderHypotheses\]", app), path
    assert re.search(r"\[/\^\\/map\$/, \"[a-z]+\", renderMap\]", app)


def test_the_map_download_is_a_small_icon_and_the_running_box_has_room():
    mp = _js("views/map.js")
    # 0.17.0 (design guide): an iconButton({ icon, size, label, title }) now draws it
    line = mp[mp.index('class: "map-doc-dl"'):]
    line = line[:line.index("})))));") + 1]
    assert 'title: "Download this PDF with the quotes highlighted"' in line and "label: `Download ${short(d.title)}" in line
    # (changed on purpose: the small icon button, 24 px, the guide's smallest control)
    assert 'icon: "download", sm: true, size: 13' in mp and '"highlighted")' not in line
    assert "btn-ghost map-doc-dl" not in mp
    # the box of a running "read more" has air above it, whatever it shows (running, done, failed)
    assert 'class: "grow more-status"' in _js("views/result.js")
    from _static import rule  # 0.17.0: reads the cascade, so it holds when the rule moves

    assert rule(".result .more-status:not(:empty)")["margin-top"] == "12px"
