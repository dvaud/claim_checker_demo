// Themes (F4): the passages of the project grouped into themes, as an overview before forming hypotheses. A set of
// themes (a "run") is shown as a list with size bars, a theme × document grid and, with a profile, a theme × code
// grid; a person can rename themes, merge two, move a passage, and let the AI name them. Older sets are kept.
import { featureEyebrow } from "../features.js";
import { App, api, h, icon, replace, clear, toast, showError, fmt, pageHead, watchJob, P, emptyState, TERMINAL, dialog, confirmDialog, download, rangeControl, passageNode, navigate, store } from "../lib.js";
import { simpleProgress, MiniJob } from "./progress.js";

const PASSAGES = 30;   // passages per page on a theme's page
const plural = (n, one, many) => `${fmt.num(n)} ${n === 1 ? one : many || one + "s"}`;
const searchHref = (q) => `#/search?q=${encodeURIComponent(q)}&mode=phrase`;
const runHref = (rid) => `#/themes/${encodeURIComponent(rid)}`;
const themeHref = (rid, tid) => `#/themes/${encodeURIComponent(rid)}/${encodeURIComponent(tid)}`;
const shortTitle = (t, n = 60) => { t = (t || "untitled").replace(/\s+/g, " ").trim(); return t.length > n ? t.slice(0, n - 2).trimEnd() + "…" : t; };
const modeWords = (m) => (m === "meaning" ? "by meaning" : "by words");
const NAMED_BY = { terms: "named by its key terms", model: "named by the AI", person: "named by you" };
const PHASE = { terms: "Updating the glossary of terms…", cluster: "Grouping the passages into themes…", name: "Naming the themes by their key terms…" };

// A sentence to start a hypothesis from: the theme's name when the AI or a person gave it, else its first key term.
function starter(t) {
  const s = t.name_source !== "terms" ? t.name : (t.terms && t.terms[0]) || t.name;
  return (s && /^[a-z]/.test(s) ? s[0].toUpperCase() + s.slice(1) : s || "") + " ";
}

async function runningJob(project, kinds, test) {
  try {
    const jobs = (await api("GET", "/api/jobs")).jobs || [];
    return jobs.find((j) => j.project === project && kinds.includes(j.kind) && !TERMINAL.has(j.state) && (!test || test(j))) || null;
  } catch (_) { return null; }
}

function jobError(job) {
  return h("div", { class: "notice notice-error" }, icon("alert-circle"), h("div", {},
    h("p", {}, job.error_kind === "backend" ? "The AI model stopped answering." : job.error_kind === "internal" ? "Something went wrong inside the app." : (job.error || "It could not finish.")),
    job.error_kind === "backend" || job.error_kind === "internal" ? h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("div", { class: "mono small" }, job.error || "")) : null,
    job.error_kind === "backend" ? h("a", { href: "#/settings" }, "Check the AI model in Settings") : null));
}

// ---------------------------------------------------------------------------------------------
// "Find themes": how many, the mode chosen automatically, and the job's progress
// ---------------------------------------------------------------------------------------------
function findCard(project, info, watchers, { again } = {}) {
  const k0 = Math.min(60, Math.max(2, Number(store("themes.k")) || info.k || 20));
  const range = rangeControl("How many themes", { min: 2, max: 60, step: 1, value: k0, format: (v) => `${v} themes`, ends: ["Fewer themes", "More themes"],
    help: "Fewer themes give a broad overview; more themes split it into narrower topics. A small project gets fewer themes than asked: about three passages a theme at least." });
  const meaning = info.auto_mode === "meaning";
  const how = h("p", { class: "muted small", style: { margin: "0 0 12px" } }, meaning
    ? "The passages are grouped by meaning (with search by meaning), which takes seconds."
    : "The passages are grouped by the words they share, because search by meaning is not set up for most of them. On many documents this can take a few minutes.");
  const tech = h("details", { class: "fold" }, h("summary", {}, "Technical details"),
    h("div", { class: "mono small" }, `mode: ${info.auto_mode} (${info.auto_why}) · spherical k-means, seed 0 · the same documents and settings give the same themes`));
  const btn = h("button", { class: "btn btn-primary", type: "button" }, icon("shapes", { size: 14 }), again ? "Find themes again" : "Find themes");
  const box = h("div", { "aria-live": "polite" });
  const card = h("section", { class: "card", "aria-labelledby": again ? null : "th-find-h", "aria-label": again ? "Find the themes again" : null },
    again ? null : h("div", { class: "card-head" }, h("h2", { id: "th-find-h" }, "Find the themes of your documents")),
    again ? h("p", { style: { marginTop: 0 } }, "A new set of themes is made; this one is kept, so you can compare them (for example before and after adding documents). Your renames, merges and moves apply again to a new set with the same number of themes.") : null,
    range, how, h("div", { class: "btn-row" }, btn), box, tech);

  function follow(jobId, k) {
    btn.disabled = true;
    range.input.disabled = true;
    const stop = h("button", { class: "btn btn-sm btn-outline-danger", type: "button" }, icon("stop", { size: 13 }), "Stop");
    stop.addEventListener("click", async () => { stop.disabled = true; try { await api("POST", `/api/jobs/${P(jobId)}/cancel`); } catch (e) { showError(e); stop.disabled = false; } });
    const pb = h("div", { class: "grow" });
    replace(box, h("div", { class: "row th-job", style: { marginTop: "12px", alignItems: "flex-start" } }, pb, stop));
    const w = watchJob(jobId, (job) => {
      replace(pb, simpleProgress(job, (p) => {
        const base = PHASE[p.phase] || "Starting…";
        return p.phase === "cluster" && k ? `Grouping the passages into ${k} themes…` : base;
      }));
      if (TERMINAL.has(job.state)) stop.hidden = true;
    });
    watchers.push(w);
    w.promise.then((job) => {
      btn.disabled = false; range.input.disabled = false;
      if (job.state === "done" && job.result && job.result.run_id) {
        toast("The themes are ready.", "ok", { small: true });
        navigate(runHref(job.result.run_id));
      } else if (job.state === "error") replace(box, h("div", { style: { marginTop: "12px" } }, jobError(job)));
      else replace(box, h("p", { class: "muted", style: { margin: "12px 0 0" } }, "Stopped. No new set of themes was made."));
    }).catch(showError);
  }
  btn.addEventListener("click", async () => {
    const k = range.input.valueAsNumber;
    store("themes.k", k);
    btn.disabled = true;
    try { const r = await api("POST", `/api/projects/${P(project)}/themes`, { k }); follow(r.job.id, k); }
    catch (e) { showError(e); btn.disabled = false; }
  });
  card.follow = follow;
  return card;
}

// ---------------------------------------------------------------------------------------------
// #/themes: the newest set of themes (or, without one, how to find them)
// ---------------------------------------------------------------------------------------------
export async function renderThemes(view, params, query) {
  const project = App.project;
  const info = await api("GET", `/api/projects/${P(project)}/themes`);
  const runs = info.runs || [];
  if (runs.length) return renderRun(view, runs[0].run_id, info, query);
  const watchers = [];
  view.appendChild(pageHead("Themes", { eyebrow: featureEyebrow("themes"), sub: `What the documents of project “${project}” are about, grouped into themes: an overview before you form hypotheses. Each theme shows its key terms, how many passages it holds, the documents they come from, and the passages that represent it best.` }));
  const card = findCard(project, info, watchers);
  view.appendChild(card);
  const running = await runningJob(project, ["themes"]);
  if (running) card.follow(running.id, null);
  view.appendChild(h("div", { class: "section" }, emptyState("shapes", "No themes yet", "Choose how many themes you want and press “Find themes”. Nothing is sent anywhere: the themes are found on this computer, and the AI is only asked if you let it name them afterwards.")));
  return () => watchers.forEach((w) => w.stop());
}

export async function renderThemeRun(view, [runId], query) {
  const project = App.project;
  const info = await api("GET", `/api/projects/${P(project)}/themes`);
  return renderRun(view, runId, info, query);
}

// ---------------------------------------------------------------------------------------------
// one set of themes
// ---------------------------------------------------------------------------------------------
async function renderRun(view, runId, info, query) {
  const project = App.project;
  const base = `/api/projects/${P(project)}/themes/${P(runId)}`;
  const runs = info.runs || [];
  const latest = runs.length && runs[0].run_id === runId;
  const watchers = [];
  let tab = ["list", "docs", "codes"].includes(query.view) ? query.view : (store("themes.view") || "list");
  let framework = App.settings().profile_framework || "sdg";
  let frameworks = [];
  const codeInfo = new Map();   // framework -> {code: description}
  let v;
  try { v = await api("GET", `${base}?framework=${encodeURIComponent(framework)}`); }
  catch (e) {
    if (e.status === 404) {
      view.appendChild(pageHead("Themes"));
      view.appendChild(emptyState("search-x", "No such set of themes", "It was deleted, or it belongs to another project.", h("a", { class: "btn", href: "#/themes" }, "Show the newest themes")));
      return;
    }
    throw e;
  }
  api("GET", `/api/projects/${P(project)}/frameworks`).then((r) => { frameworks = r.frameworks || []; if (tab === "codes") drawTab(); }).catch(() => {});

  const head = h("div");
  const notes = h("div");
  const nameJob = h("div");
  const tabs = h("div", { class: "view-toggle", role: "group", "aria-label": "How to show the themes" });
  const tabBox = h("div");
  const runsBox = h("section", { class: "section", "aria-labelledby": "th-runs-h" });
  const again = findCard(project, info, watchers, { again: true });
  const againFold = h("details", { class: "fold th-again" }, h("summary", {}, "Find the themes again (more or fewer themes, or after adding documents)"), h("div", { style: { marginTop: "8px" } }, again));
  view.append(head, notes, nameJob, againFold, tabs, tabBox, runsBox);

  async function reload() {
    try { v = await api("GET", `${base}?framework=${encodeURIComponent(framework)}`); } catch (e) { showError(e); return; }
    const y = window.scrollY;
    draw();
    window.scrollTo(0, y);  // stay where the person was
  }

  function draw() {
    const r = v.run;
    const nDocs = (v.documents || []).length;
    const namedByModel = v.themes.filter((t) => t.name_source === "model").length;
    const nameBtn = h("button", { class: "btn btn-sm", type: "button", disabled: !!nameJob.firstChild }, icon("sparkles", { size: 13 }), namedByModel ? "Let the AI name the themes again" : "Let the AI name the themes");
    nameBtn.addEventListener("click", () => nameThemes(nameBtn));
    const xlsx = h("button", { class: "btn btn-sm", type: "button", onClick: () => download(`${base}/export.xlsx?framework=${encodeURIComponent(framework)}`).catch(showError) }, icon("download", { size: 13 }), "Download for Excel (.xlsx)");
    replace(head, pageHead("Themes", {
      eyebrow: latest ? featureEyebrow("themes") : h("span", {}, icon("history", { size: 12 }), ` An earlier set of themes, found ${fmt.date(r.created_at)} · `, h("a", { href: "#/themes" }, "Show the newest")),
      sub: `${plural(v.themes.length, "theme")} in ${plural(r.passages, "passage")} of ${plural(nDocs, "document")} of project “${project}”, found ${modeWords(r.mode)} on ${fmt.date(r.created_at)}. Open a theme to read its passages.`,
      actions: [nameBtn, xlsx],
    }));
    clear(notes);
    if (r.stale) notes.appendChild(h("div", { class: "notice notice-warn", style: { marginBottom: "12px" } }, icon("alert-triangle"),
      h("p", {}, "Documents were added or removed since these themes were found, so they leave out the changes. Find the themes again to include them; this set is kept, so you can compare.")));
    const ed = v.edits || {};
    const bits = [ed.renamed ? plural(ed.renamed, "theme") + " renamed" : null, ed.merged ? plural(ed.merged, "merge") : null, ed.moved ? plural(ed.moved, "passage") + " moved" : null].filter(Boolean);
    if (bits.length) notes.appendChild(h("p", { class: "muted small", style: { margin: "0 0 10px" } }, icon("note", { size: 12 }), ` Your changes: ${bits.join(", ")}. They are kept, and apply again when the themes are found again with the same number of themes.`));
    drawTabs();
    drawTab();
    drawRuns();
  }

  function drawTabs() {
    const btn = (val, label, ic) => h("button", { class: "btn btn-sm seg-btn" + (tab === val ? " seg-on" : ""), type: "button", "aria-pressed": tab === val ? "true" : "false",
      onClick: () => { tab = val; store("themes.view", val); drawTabs(); drawTab(); } }, icon(ic, { size: 13 }), label);
    replace(tabs, h("span", { class: "muted small" }, "Show:"), btn("list", "List", "list-checks"), btn("docs", "By document", "grid"), btn("codes", "By code", "tag"));
  }

  function drawTab() {
    clear(tabBox);
    if (tab === "docs") tabBox.appendChild(docGrid());
    else if (tab === "codes") tabBox.appendChild(codeGrid());
    else tabBox.appendChild(themeList());
  }

  // ---- the list, with size bars
  function themeList() {
    const max = Math.max(1, ...v.themes.map((t) => t.size));
    const ol = h("ol", { class: "th-list" });
    for (const t of v.themes) {
      const href = themeHref(runId, t.theme_id);
      const docs = t.documents || [];
      const pct = Math.round((t.size / max) * 100);
      const reps = t.representatives || [];
      const li = h("li", { class: "th-item card" },
        h("div", { class: "th-item-head" },
          h("span", { class: "th-num", "aria-hidden": "true" }, String(t.number ?? t.theme_id)),
          h("div", { class: "th-item-main" },
            h("h3", { class: "th-name" }, h("a", { href }, t.name)),
            h("div", { class: "th-meta" },
              h("span", { class: "chip" + (t.name_source === "person" ? " chip-yours" : "") }, NAMED_BY[t.name_source] || ""),
              t.merged_from && t.merged_from.length ? h("span", { class: "chip" }, `${t.merged_from.length === 1 ? "1 theme" : `${t.merged_from.length} themes`} merged in`) : null,
              t.moved_in ? h("span", { class: "chip" }, `${plural(t.moved_in, "passage")} moved here`) : null))),
        t.description ? h("p", { class: "th-desc" }, t.description) : null,
        t.quotes && t.quotes.name && t.quotes.name.quote && t.name_source === "model" ? h("p", { class: "muted small th-quote" }, icon("quote", { size: 12 }), " The AI's name rests on: ", h("q", { class: "serif" }, t.quotes.name.quote)) : null,
        h("div", { class: "th-size" },
          h("div", { class: "th-bar", "aria-hidden": "true" }, h("span", { style: { width: `${Math.max(2, pct)}%` } })),
          h("span", { class: "th-size-text" }, `${plural(t.size, "passage")} from ${plural(docs.length, "document")}`)),
        t.terms && t.terms.length ? h("div", { class: "chips th-terms", role: "list", "aria-label": "Key terms" }, t.terms.map((w) => h("a", { class: "chip chip-btn", role: "listitem", href: searchHref(w), title: `Search the documents for “${w}”` }, w))) : null,
        docs.length ? h("p", { class: "th-docs muted small" }, "Mostly from ", docs.slice(0, 3).map((d, i) => [i ? "; " : "", h("a", { href: `#/doc/${encodeURIComponent(d.doc_id)}`, title: d.title }, shortTitle(d.title, 50)), ` (${d.passages})`]), docs.length > 3 ? ` and ${plural(docs.length - 3, "other document")}` : "", ".") : null,
        reps.length ? h("details", { class: "fold th-reps" }, h("summary", {}, `The ${reps.length === 1 ? "passage that represents" : `${reps.length} passages that represent`} it best`),
          h("div", { class: "stack", style: { gap: "8px", marginTop: "6px" } }, reps.map((p) => repCard(p, t)))) : null,
        h("div", { class: "btn-row th-acts" },
          h("a", { class: "btn btn-sm", href }, icon("eye", { size: 13 }), "Open"),
          h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => renameTheme(t) }, icon("type", { size: 13 }), "Rename"),
          h("button", { class: "btn btn-sm btn-ghost", type: "button", disabled: v.themes.length < 2, onClick: () => mergeTheme(t) }, icon("split", { size: 13 }), "Merge into…")));
      ol.appendChild(li);
    }
    return ol;
  }

  // ---- the theme × document grid (the map component)
  function docGrid() {
    const docs = v.documents || [];
    const grid = v.doc_grid || {};
    const max = Math.max(1, ...Object.values(grid).flatMap((row) => Object.values(row)));
    const wrap = h("div");
    wrap.appendChild(h("p", { class: "muted small", style: { margin: "0 0 8px" } }, "How many passages of each document fall in each theme. The darker the cell, the more passages."));
    const table = h("table", { class: "map-table th-grid" },
      h("caption", { class: "visually-hidden" }, "Themes by document: the number of passages"),
      h("thead", {}, h("tr", {}, h("th", { scope: "col", class: "map-hyp-head" }, "Theme"),
        docs.map((d) => h("th", { scope: "col", class: "map-doc-head" }, h("a", { href: `#/doc/${encodeURIComponent(d.doc_id)}`, title: d.title || "untitled" }, h("span", { class: "map-doc-title" }, shortTitle(d.title))))))),
      h("tbody", {}, v.themes.map((t) => {
        const row = grid[String(t.theme_id)] || {};
        const href = themeHref(runId, t.theme_id);
        return h("tr", { class: "row-link", onClick: (e) => { if (e.target.closest("a")) return; location.hash = href; } },
          h("th", { scope: "row", class: "map-hyp" }, h("a", { href }, t.name), h("div", { class: "map-hyp-meta muted small" }, plural(t.size, "passage"))),
          docs.map((d) => heatCell(row[d.doc_id] || 0, max, `${shortTitle(d.title)} in “${t.name}”`)));
      })));
    wrap.appendChild(h("p", { class: "muted small map-scroll-hint", style: { margin: "0 0 6px" } }, icon("arrow-right", { size: 12 }), " The grid scrolls sideways: drag or swipe it to see every document."));
    wrap.appendChild(h("div", { class: "map-wrap", tabindex: "0", role: "region", "aria-label": "Themes by document (scrolls sideways)" }, table));
    return wrap;
  }

  function heatCell(n, max, label) {
    // on a log scale, so one very large cell does not leave all the others pale
    const level = n ? Math.max(1, Math.min(4, Math.ceil((4 * Math.log1p(n)) / Math.log1p(max)))) : 0;
    return h("td", { class: `map-cell th-cell th-l${level}`, title: `${label}: ${plural(n, "passage")}` },
      h("span", { class: "visually-hidden" }, `${label}: `), n ? String(n) : h("span", { "aria-label": "none" }, "·"));
  }

  // ---- the theme × code grid (with a profile)
  function codeGrid() {
    const wrap = h("div");
    const cg = v.code_grid;
    const choices = frameworks.length > 1 ? h("label", { class: "row th-fw", style: { gap: "8px", marginBottom: "8px" } }, h("span", { class: "muted small" }, "Codebook"),
      h("select", { class: "select input-sm", onChange: async (e) => { framework = e.target.value; await reload(); } },
        frameworks.map((f) => h("option", { value: f.name, selected: f.name === framework }, f.title || f.name)))) : null;
    if (choices) wrap.appendChild(choices);
    if (!cg || !(cg.codes || []).length) {
      wrap.appendChild(emptyState("tag", "No codes found in these passages yet", "Find the codes of the codebook first on the Profile page: the grid then shows which codes each theme holds.", h("a", { class: "btn", href: "#/profile" }, icon("tag", { size: 14 }), "Go to Profile")));
      return wrap;
    }
    const desc = codeInfo.get(cg.framework);
    if (!desc) api("GET", `/api/projects/${P(project)}/frameworks/${P(cg.framework)}`).then((r) => {
      const m = {};
      for (const it of (r.framework && r.framework.items) || []) m[it.code] = it.description;
      codeInfo.set(cg.framework, m);
      if (tab === "codes") drawTab();
    }).catch(() => codeInfo.set(cg.framework, {}));
    const fwLabel = (frameworks.find((f) => f.name === cg.framework) || {}).label || "code";
    const cells = cg.cells || {};
    const max = Math.max(1, ...Object.values(cells).flatMap((row) => Object.values(row)));
    wrap.appendChild(h("p", { class: "muted small", style: { margin: "0 0 8px" } }, `How many passages of each theme carry each ${fwLabel} (found by keywords, by the AI, or by you on the Profile page). The darker the cell, the more passages.`));
    const table = h("table", { class: "map-table th-grid th-codes" },
      h("caption", { class: "visually-hidden" }, `Themes by ${fwLabel}: the number of passages`),
      h("thead", {}, h("tr", {}, h("th", { scope: "col", class: "map-hyp-head" }, "Theme"),
        cg.codes.map((code) => h("th", { scope: "col", class: "th-code-head", title: desc && desc[code] ? `${code}: ${desc[code]}` : code }, code)))),
      h("tbody", {}, v.themes.map((t) => {
        const row = cells[String(t.theme_id)] || {};
        const href = themeHref(runId, t.theme_id);
        return h("tr", { class: "row-link", onClick: (e) => { if (e.target.closest("a")) return; location.hash = href; } },
          h("th", { scope: "row", class: "map-hyp" }, h("a", { href }, t.name)),
          cg.codes.map((code) => heatCell(row[code] || 0, max, `${fwLabel} ${code} in “${t.name}”`)));
      })));
    wrap.appendChild(h("p", { class: "muted small map-scroll-hint", style: { margin: "0 0 6px" } }, icon("arrow-right", { size: 12 }), " The grid scrolls sideways: drag or swipe it to see every code."));
    wrap.appendChild(h("div", { class: "map-wrap", tabindex: "0", role: "region", "aria-label": `Themes by ${fwLabel} (scrolls sideways)` }, table));
    return wrap;
  }

  // ---- the list of sets of themes
  function drawRuns() {
    clear(runsBox);
    runsBox.appendChild(h("div", { class: "section-title" }, h("h2", { id: "th-runs-h" }, `Sets of themes (${runs.length})`), h("span", { class: "muted" }, "Kept until you delete them, to compare the themes before and after adding documents.")));
    runsBox.appendChild(h("div", { class: "table-wrap" }, h("table", { class: "table table-responsive th-runs" },
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Found"), h("th", { scope: "col" }, "How"), h("th", { scope: "col", class: "num" }, "Themes"), h("th", { scope: "col", class: "num" }, "Passages"), h("th", { scope: "col" }, "Note"), h("th", { scope: "col" }, h("span", { class: "visually-hidden" }, "Actions")))),
      h("tbody", {}, runs.map((r) => h("tr", { class: r.run_id === runId ? "th-run-now" : "" },
        h("td", { class: "nowrap" }, r.run_id === runId ? h("strong", {}, fmt.date(r.created_at)) : h("a", { href: runHref(r.run_id) }, fmt.date(r.created_at)), r.run_id === runId ? h("span", { class: "muted small" }, " (shown)") : null),
        h("td", { "data-label": "How" }, modeWords(r.mode)),
        h("td", { class: "num", "data-label": "Themes" }, String(r.themes_now ?? r.k)),
        h("td", { class: "num", "data-label": "Passages" }, fmt.num(r.passages)),
        h("td", { "data-label": "Note" },
          r.stale ? h("span", { class: "warn-chip" }, icon("alert-triangle", { size: 12 }), "documents changed since") : h("span", { class: "it muted small" }, icon("check", { size: 12 }), "up to date"),
          r.named_by_model ? h("span", { class: "muted small" }, ` · ${r.named_by_model} named by the AI`) : null),
        h("td", { class: "actions" },
          r.run_id !== runId ? h("a", { class: "btn btn-sm btn-ghost", href: runHref(r.run_id) }, icon("eye", { size: 13 }), "Open") : null,
          h("button", { class: "btn btn-sm btn-ghost", type: "button", "aria-label": `Delete the set of themes found ${fmt.date(r.created_at)}`, onClick: () => deleteRun(r) }, icon("trash", { size: 13 }), "Delete"))))))));
  }

  async function deleteRun(r) {
    const ok = await confirmDialog({ title: "Delete this set of themes?", message: `The ${r.themes_now ?? r.k} themes found ${fmt.date(r.created_at)} are deleted, with the names the AI gave them. Your renames, merges and moves are kept for a new set with the same number of themes.`, confirmText: "Delete" });
    if (!ok) return;
    try {
      await api("DELETE", `/api/projects/${P(project)}/themes/${P(r.run_id)}`);
      toast("Set of themes deleted.", "ok", { small: true });
      if (r.run_id === runId) navigate("#/themes");
      else { const i = runs.indexOf(r); if (i >= 0) runs.splice(i, 1); drawRuns(); }
    } catch (e) { showError(e); }
  }

  // ---- editing
  async function edit(body, ok) {
    try { await api("PUT", `${base}/edit`, body); toast(ok, "ok", { small: true, ttl: 3000 }); await reload(); return true; }
    catch (e) { showError(e); return false; }
  }
  async function renameTheme(t) {
    const input = h("input", { class: "input", type: "text", value: t.name, maxlength: 80, id: "th-rename" });
    const body = h("div", {}, h("label", { class: "field" }, h("span", { class: "field-label" }, "New name"), input),
      h("p", { class: "muted small" }, `Key terms: ${(t.terms || []).slice(0, 6).join(", ")}`));
    const actions = [{ text: "Cancel", value: null }];
    if (t.name_source === "person") actions.push({ text: "Use the name it had before", value: "" });
    actions.push({ text: "Save", value: "save", primary: true });
    const r = await dialog({ title: "Rename the theme", body, actions, onOpen: () => { input.select(); input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); input.closest("dialog").querySelector(".btn-primary").click(); } }); } });
    if (r === null) return;
    const name = r === "" ? "" : input.value.trim();
    if (r === "save" && (!name || name === t.name)) return;
    await edit({ what: "rename", theme_id: t.theme_id, value: name }, name ? "Theme renamed." : "The earlier name is back.");
  }
  async function mergeTheme(t) {
    const others = v.themes.filter((x) => x.theme_id !== t.theme_id);
    const sel = h("select", { class: "select", id: "th-merge" }, others.map((x) => h("option", { value: String(x.theme_id) }, `${x.number ?? x.theme_id}. ${x.name} (${plural(x.size, "passage")})`)));
    const body = h("div", {}, h("p", {}, "All passages of ", h("strong", {}, `“${t.name}”`), ` (${plural(t.size, "passage")}) join the theme you choose. You can undo it on that theme's page.`),
      h("label", { class: "field" }, h("span", { class: "field-label" }, "Merge into"), sel));
    const r = await dialog({ title: "Merge two themes", body, actions: [{ text: "Cancel", value: null }, { text: "Merge", value: "merge", primary: true }] });
    if (r !== "merge") return;
    await edit({ what: "merge", theme_id: t.theme_id, value: Number(sel.value) }, "Themes merged.");
  }

  // ---- the AI names the themes
  function nameThemes(btn) {
    btn.disabled = true;
    api("POST", `${base}/name`, {}).then((r) => followNames(r.job.id)).catch((e) => { showError(e); btn.disabled = false; });
  }
  function followNames(jobId) {
    const m = new MiniJob({ title: "The AI names the themes" });
    replace(nameJob, h("div", { style: { marginBottom: "12px" } }, m.el,
      h("p", { class: "muted small", style: { margin: "6px 0 0" } }, "The AI reads the passages that represent each theme and gives it a short name and a description, each with a quote that is checked against the passage. Names you gave yourself are kept.")));
    const w = watchJob(jobId, (job) => {
      m.update(job);
      const p = job.progress || {};
      if (p.total && (job.state === "running" || job.state === "queued")) m.time.textContent = `theme ${Math.min(p.done || 0, p.total)} of ${p.total} · ${m.time.textContent}`;
    });
    watchers.push(w);
    w.promise.then(async (job) => {
      clear(nameJob);
      if (job.state === "done") {
        const res = job.result || {};
        toast(`The AI named ${plural(res.named || 0, "theme")}${res.failed ? `; ${res.failed} could not be named (their quotes did not check out)` : ""}.`, res.failed ? "warn" : "ok");
      } else if (job.state === "error") showError({ message: job.error, kind: job.error_kind });
      else toast("Stopped. The themes named so far keep their names.", "info", { small: true });
      await reload();
    }).catch(showError);
    const b = head.querySelector(".page-head-actions .btn"); if (b) b.disabled = true;
  }

  draw();
  const running = await runningJob(project, ["themes"]);
  if (running) { again.follow(running.id, null); againFold.open = true; }
  const naming = await runningJob(project, ["theme-names"]);
  if (naming) followNames(naming.id);
  return () => watchers.forEach((w) => w.stop());
}

// A passage that represents a theme: its document, where, and its text (with the AI's checked quotes marked).
function repCard(p, t) {
  const quotes = t && t.quotes ? Object.values(t.quotes).filter((q) => q && q.passage_id === p.passage_id && q.quote) : [];
  let s = null, e = null;
  if (quotes.length) { const i = (p.text || "").indexOf(quotes[0].quote); if (i >= 0) { s = i; e = i + quotes[0].quote.length; } }
  return h("article", { class: "th-passage" },
    h("div", { class: "ev-src" }, icon("file-text", { size: 14 }), h("a", { href: `#/doc/${encodeURIComponent(p.doc_id)}${p.start != null && p.end != null ? `?q=${p.start}-${p.end}&whole=1` : ""}`, class: "title", title: "Open the document at this passage" }, p.title || "untitled"),
      p.location ? h("span", { class: "page" }, p.location) : null),
    passageNode(p.text, s, e, "p", "passage"));
}

// ---------------------------------------------------------------------------------------------
// one theme: its passages as cards, its terms, and the edits
// ---------------------------------------------------------------------------------------------
export async function renderTheme(view, [runId, themeId], query) {
  const project = App.project;
  const base = `/api/projects/${P(project)}/themes/${P(runId)}`;
  let offset = Math.max(0, Number(query.offset) || 0);
  let d;
  const fetchIt = () => api("GET", `${base}/${P(themeId)}?offset=${offset}&limit=${PASSAGES}`);
  try { d = await fetchIt(); }
  catch (e) {
    if (e.status === 404) {
      view.appendChild(pageHead("Theme", { eyebrow: h("a", { href: runHref(runId), class: "it" }, icon("shapes", { size: 12 }), "All themes") }));
      view.appendChild(emptyState("search-x", "No such theme", "It was merged into another theme, or its set of themes was deleted.", h("a", { class: "btn", href: runHref(runId) }, "Show all themes")));
      return;
    }
    throw e;
  }
  const head = h("div");
  const body = h("div");
  view.append(head, body);

  async function reload(scrollTo) {
    try { d = await fetchIt(); }
    catch (e) {
      if (e.status === 404) { toast("This theme was merged into another one.", "info"); navigate(runHref(runId)); return; }
      showError(e); return;
    }
    draw();
    if (scrollTo) { const el = document.getElementById(scrollTo); if (el) el.scrollIntoView({ block: "start" }); }
  }
  async function edit(b, ok) {
    try { await api("PUT", `${base}/edit`, b); toast(ok, "ok", { small: true, ttl: 3000 }); return true; }
    catch (e) { showError(e); return false; }
  }

  function draw() {
    const t = d.theme;
    const docs = t.documents || [];
    document.title = `${t.name} · Themes · ENLENS`;
    const renameBtn = h("button", { class: "btn btn-sm", type: "button" }, icon("type", { size: 13 }), "Rename");
    renameBtn.addEventListener("click", async () => {
      const input = h("input", { class: "input", type: "text", value: t.name, maxlength: 80 });
      const actions = [{ text: "Cancel", value: null }];
      if (t.name_source === "person") actions.push({ text: "Use the name it had before", value: "" });
      actions.push({ text: "Save", value: "save", primary: true });
      const r = await dialog({ title: "Rename the theme", body: h("label", { class: "field" }, h("span", { class: "field-label" }, "New name"), input), actions,
        onOpen: () => { input.select(); input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); input.closest("dialog").querySelector(".btn-primary").click(); } }); } });
      if (r === null) return;
      const name = r === "" ? "" : input.value.trim();
      if (r === "save" && (!name || name === t.name)) return;
      if (await edit({ what: "rename", theme_id: t.theme_id, value: name }, name ? "Theme renamed." : "The earlier name is back.")) reload();
    });
    const mergeBtn = h("button", { class: "btn btn-sm btn-ghost", type: "button", disabled: !d.others.length }, icon("split", { size: 13 }), "Merge into…");
    mergeBtn.addEventListener("click", async () => {
      const sel = h("select", { class: "select" }, d.others.map((x) => h("option", { value: String(x.theme_id) }, `${x.number ?? x.theme_id}. ${x.name}`)));
      const r = await dialog({ title: "Merge two themes", body: h("div", {}, h("p", {}, "All passages of ", h("strong", {}, `“${t.name}”`), " join the theme you choose. You can undo it on that theme's page."), h("label", { class: "field" }, h("span", { class: "field-label" }, "Merge into"), sel)),
        actions: [{ text: "Cancel", value: null }, { text: "Merge", value: "merge", primary: true }] });
      if (r !== "merge") return;
      if (await edit({ what: "merge", theme_id: t.theme_id, value: Number(sel.value) }, "Themes merged.")) navigate(themeHref(runId, sel.value));
    });
    replace(head, h("header", { class: "page-head" },
      h("div", { class: "page-head-main" },
        h("p", { class: "eyebrow" }, h("a", { href: runHref(runId), class: "it" }, icon("shapes", { size: 12 }), "All themes")),
        h("h1", { id: "page-title", tabindex: "-1", class: "serif th-title" }, t.name),
        h("div", { class: "result-meta", style: { marginTop: "6px" } },
          h("span", {}, `Theme ${t.number ?? t.theme_id}`), h("span", { class: "sep" }, "·"),
          h("span", {}, `${plural(t.size, "passage")} from ${plural(docs.length, "document")}`), h("span", { class: "sep" }, "·"),
          h("span", {}, NAMED_BY[t.name_source] || ""))),
      h("div", { class: "page-head-actions" },
        h("a", { class: "btn btn-primary btn-sm", href: `#/check?text=${encodeURIComponent(starter(t))}` }, icon("flask", { size: 13 }), "Check a hypothesis about this theme"),
        renameBtn, mergeBtn)));

    clear(body);
    // the AI's description, with its checked quotes
    if (t.description || (t.name_source === "model" && t.quotes)) {
      const q = t.quotes || {};
      body.appendChild(h("section", { class: "card th-about", "aria-label": "What the AI says this theme is about" },
        t.description ? h("p", { class: "th-desc", style: { marginTop: 0 } }, t.description) : null,
        [["name", "The name rests on"], ["description", "The description rests on"]].filter(([k]) => q[k] && q[k].quote).map(([k, label]) =>
          h("p", { class: "muted small th-quote" }, icon("quote", { size: 12 }), ` ${label}: `, h("q", { class: "serif" }, q[k].quote))),
        h("p", { class: "muted small", style: { marginBottom: 0 } }, `${t.name_source === "model" ? "Named and described" : "Described"} by the AI${t.model ? ` (${t.model})` : ""}; its quotes were checked against the passages.`)));
    }
    if (t.merged_from && t.merged_from.length) {
      body.appendChild(h("div", { class: "notice notice-info", style: { margin: "12px 0" } }, icon("info"),
        h("div", {}, h("p", {}, `You merged ${t.merged_from.length === 1 ? "a theme" : `${t.merged_from.length} themes`} into this one: ${(t.merged_from_names || t.merged_from.map((x) => ({ name: String(x) }))).map((x) => `“${x.name}”`).join(", ")}.`),
          h("div", { class: "btn-row", style: { marginTop: "6px" } }, (t.merged_from_names || t.merged_from.map((x) => ({ theme_id: x, name: String(x) }))).map((x) => h("button", { class: "btn btn-sm", type: "button", onClick: async (e) => {
            e.currentTarget.disabled = true;
            if (await edit({ what: "merge", theme_id: x.theme_id, value: null }, `“${x.name}” is a theme of its own again.`)) reload();
          } }, `Separate “${shortTitle(x.name, 40)}” again`))))));
    }
    // key terms and documents
    body.appendChild(h("section", { class: "section", "aria-labelledby": "th-t-h" },
      h("div", { class: "section-title" }, h("h2", { id: "th-t-h" }, "Key terms"), h("span", { class: "muted" }, "The words that set this theme apart. Click one to search the documents for it.")),
      h("div", { class: "chips" }, (t.terms || []).map((w) => h("a", { class: "chip chip-btn", href: searchHref(w) }, icon("text-search", { size: 12 }), w)))));
    body.appendChild(h("section", { class: "section", "aria-labelledby": "th-d-h" },
      h("div", { class: "section-title" }, h("h2", { id: "th-d-h" }, `The documents it comes from (${docs.length})`)),
      h("ul", { class: "th-doclist" }, docs.slice(0, 12).map((x) => h("li", {}, h("a", { href: `#/doc/${encodeURIComponent(x.doc_id)}`, title: x.title }, shortTitle(x.title, 90)), h("span", { class: "muted small" }, plural(x.passages, "passage"))))),
      docs.length > 12 ? h("details", { class: "fold" }, h("summary", {}, `${plural(docs.length - 12, "other document")}`),
        h("ul", { class: "th-doclist" }, docs.slice(12).map((x) => h("li", {}, h("a", { href: `#/doc/${encodeURIComponent(x.doc_id)}`, title: x.title }, shortTitle(x.title, 90)), h("span", { class: "muted small" }, plural(x.passages, "passage")))))) : null));
    // passages
    const reps = new Set((t.representatives || []).map((p) => p.passage_id));
    const sec = h("section", { class: "section", "aria-labelledby": "th-p-h" },
      h("div", { class: "section-title" }, h("h2", { id: "th-p-h" }, `Its passages (${fmt.num(d.total)})`), h("span", { class: "muted" }, "Those closest to the heart of the theme first.")));
    const pager = () => d.total > PASSAGES ? h("div", { class: "pager" },
      h("span", { class: "muted small" }, `${fmt.num(d.offset + 1)}–${fmt.num(d.offset + d.passages.length)} of ${fmt.num(d.total)}`),
      h("div", { class: "btn-row" },
        h("button", { class: "btn btn-sm", type: "button", disabled: d.offset <= 0, onClick: () => { offset = Math.max(0, d.offset - PASSAGES); history.replaceState(null, "", `${themeHref(runId, themeId)}${offset ? `?offset=${offset}` : ""}`); reload("th-p-h"); } }, icon("chevron-left", { size: 13 }), "Previous"),
        h("button", { class: "btn btn-sm", type: "button", disabled: d.offset + PASSAGES >= d.total, onClick: () => { offset = d.offset + PASSAGES; history.replaceState(null, "", `${themeHref(runId, themeId)}?offset=${offset}`); reload("th-p-h"); } }, "Next", icon("chevron-right", { size: 13 })))) : null;
    { const pg = pager(); if (pg) sec.appendChild(pg); }
    if (!d.passages.length) sec.appendChild(emptyState("shapes", "No passage left in this theme", "Its passages were moved to other themes."));
    const list = h("div", { class: "stack th-passages" });
    for (const p of d.passages) {
      const sel = h("select", { class: "select input-sm", "aria-label": "Move this passage to the theme" },
        h("option", { value: "" }, "Move to another theme…"), d.others.map((x) => h("option", { value: String(x.theme_id) }, `${x.number ?? x.theme_id}. ${shortTitle(x.name, 50)}`)));
      const moveBtn = h("button", { class: "btn btn-sm", type: "button", disabled: true }, "Move");
      sel.addEventListener("change", () => { moveBtn.disabled = !sel.value; });
      moveBtn.addEventListener("click", async () => {
        moveBtn.disabled = true;
        const to = d.others.find((x) => String(x.theme_id) === sel.value);
        if (await edit({ what: "move", passage_id: p.passage_id, value: Number(sel.value) }, `Passage moved to “${to ? to.name : sel.value}”.`)) reload();
        else moveBtn.disabled = false;
      });
      const undo = p.moved ? h("button", { class: "link-btn", type: "button", onClick: async () => { if (await edit({ what: "move", passage_id: p.passage_id, value: null }, "The passage is back in the theme it was found in.")) reload(); } }, "Undo the move") : null;
      list.appendChild(h("article", { class: "th-passage card" },
        h("div", { class: "ev-src" }, icon("file-text", { size: 14 }),
          h("a", { href: `#/doc/${encodeURIComponent(p.doc_id)}${p.start != null && p.end != null ? `?q=${p.start}-${p.end}&whole=1` : ""}`, class: "title", title: "Open the document at this passage" }, p.title || "untitled"),
          p.location ? h("span", { class: "page" }, p.location) : null),
        (reps.has(p.passage_id) || p.moved) ? h("div", { class: "th-flags" },
          reps.has(p.passage_id) ? h("span", { class: "chip chip-code" }, icon("star", { size: 11 }), "represents the theme best") : null,
          p.moved ? h("span", { class: "chip chip-yours" }, "moved here by you") : null, undo ? [" ", undo] : null) : null,
        passageNode(p.text, null, null, "p", "passage"),
        h("div", { class: "th-move" }, sel, moveBtn,
          h("details", { class: "th-tech" }, h("summary", { class: "muted small" }, "Technical details"), h("div", { class: "mono small" }, `passage ${p.passage_id} · similarity to the theme's centre ${Number(p.similarity).toFixed(3)}`)))));
    }
    sec.appendChild(list);
    { const pg = pager(); if (pg) sec.appendChild(pg); }
    body.appendChild(sec);
  }

  draw();
}
