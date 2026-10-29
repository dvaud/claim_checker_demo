// Concepts (F3): a searchable glossary of the terms the documents use, grouped into concepts, and the card of one
// concept: its wordings, the documents that discuss it, the passages as concordance lines, and related concepts
// (a person accepts or rejects the links proposed by search by meaning or by the AI).
import { featureEyebrow } from "../features.js";
import { App, api, h, icon, replace, clear, toast, showError, fmt, pageHead, watchJob, P, emptyState, TERMINAL, debounce, navigate, switchControl } from "../lib.js";
import { simpleProgress, MiniJob } from "./progress.js";

const PAGE = 50;       // glossary entries per page
const LINES = 50;      // concordance lines per page

// "green hydrogen" -> "Green hydrogen" (a name written with capitals stays as it is)
const cap = (s) => (s && /^[a-z]/.test(s) && !/[A-Z]/.test(s) ? s[0].toUpperCase() + s.slice(1) : s || "");
const plural = (n, one, many) => `${fmt.num(n)} ${n === 1 ? one : many || one + "s"}`;
const searchHref = (q) => `#/search?q=${encodeURIComponent(q)}&mode=phrase`;
const conceptHref = (tid) => `#/concepts/${encodeURIComponent(tid)}`;
const checkHref = (text) => `#/check?text=${encodeURIComponent(text)}`;
const shortTitle = (t, n = 70) => { t = (t || "untitled").replace(/\s+/g, " ").trim(); return t.length > n ? t.slice(0, n - 2).trimEnd() + "…" : t; };

// A job shown in a card: a bar with what it is doing, its time and a Stop button. `onEnd(job)` runs when it ends.
function jobCard(box, jobId, title, labelFn, onEnd) {
  const stop = h("button", { class: "btn btn-sm btn-outline-danger", type: "button" }, icon("stop", { size: 13 }), "Stop");
  const pb = h("div", { "aria-live": "polite" });
  const head = h("h2", {}, title);
  const holder = h("div", { class: "card" }, h("div", { class: "card-head" }, head, stop), pb);
  stop.addEventListener("click", async () => {
    stop.disabled = true;
    try { await api("POST", `/api/jobs/${P(jobId)}/cancel`); } catch (e) { showError(e); stop.disabled = false; }
  });
  box.hidden = false;
  replace(box, holder);
  const w = watchJob(jobId, (job) => {
    replace(pb, simpleProgress(job, labelFn));
    if (TERMINAL.has(job.state)) stop.hidden = true;
  });
  w.promise.then((job) => {
    if (job.state === "error") {
      head.textContent = "It did not work";
      replace(pb, h("div", { class: "notice notice-error" }, icon("alert-circle"), h("div", {},
        h("p", {}, job.error_kind === "backend" ? "The AI model stopped answering." : job.error_kind === "internal" ? "Something went wrong inside the app." : (job.error || "It could not finish.")),
        job.error_kind === "backend" || job.error_kind === "internal" ? h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("div", { class: "mono small" }, job.error || "")) : null,
        job.error_kind === "backend" ? h("a", { href: "#/settings" }, "Check the AI model in Settings") : null)));
    } else if (job.state === "cancelled") {
      head.textContent = "Stopped";
      replace(pb, h("p", { class: "muted", style: { margin: 0 } }, "Stopped. Nothing was changed."));
    }
    if (onEnd) onEnd(job);
  }).catch(showError);
  return w;
}

const glossaryLabel = (p) => (p.total ? `Reading the documents: ${fmt.num(p.done || 0)} of ${fmt.num(p.total)} passages` : "Reading the documents…");

// A running job of one of these kinds for this project, if any.
async function runningJob(project, kinds) {
  try {
    const jobs = (await api("GET", "/api/jobs")).jobs || [];
    return jobs.find((j) => j.project === project && kinds.includes(j.kind) && !TERMINAL.has(j.state)) || null;
  } catch (_) { return null; }
}

// ---------------------------------------------------------------------------------------------
// the glossary
// ---------------------------------------------------------------------------------------------
export async function renderConcepts(view, params, query) {
  const project = App.project;
  // #/concepts?name=… opens the concept of a typed name (for links from elsewhere in the app)
  if (query.name) {
    try {
      const r = await api("GET", `/api/projects/${P(project)}/concepts?name=${encodeURIComponent(query.name)}`);
      location.replace(conceptHref(r.term_id));
      return;
    } catch (e) { if (e.status !== 404) showError(e); else toast(`No concept of the glossary matches “${query.name}”.`, "info"); }
  }
  let q = query.q || "", sort = ["docs", "mentions", "name"].includes(query.sort) ? query.sort : "docs", offset = Math.max(0, Number(query.offset) || 0);
  const watchers = [];

  view.appendChild(pageHead("Concepts", { eyebrow: featureEyebrow("concepts"), sub: `The terms the documents of project “${project}” use, grouped into concepts. Open one to follow it across the documents: where it appears, how it is written, and what it is related to.` }));

  const jobBox = h("section", { class: "section", hidden: true, "aria-label": "Progress" });
  const statusBox = h("div");
  const search = h("input", { class: "input", type: "search", placeholder: "Find a concept…", value: q, "aria-label": "Find a concept" });
  const sortSel = h("select", { class: "select input-sm", "aria-label": "Sort the concepts" },
    [["docs", "Most documents first"], ["mentions", "Most mentions first"], ["name", "A to Z"]].map(([v, t]) => h("option", { value: v, selected: v === sort }, t)));
  const filters = h("div", { class: "filters" }, h("div", { class: "filters-top" }, h("div", { class: "search" }, icon("search", { size: 15 }), search), sortSel));
  const live = h("p", { class: "visually-hidden", "aria-live": "polite" });
  const listBox = h("div", { "aria-busy": "false" });
  const judgeBox = h("div");
  view.append(jobBox, statusBox, filters, live, listBox, judgeBox);

  function keepUrl() {
    const s = new URLSearchParams();
    if (q) s.set("q", q);
    if (sort !== "docs") s.set("sort", sort);
    if (offset) s.set("offset", String(offset));
    const qs = s.toString();
    history.replaceState(null, "", "#/concepts" + (qs ? "?" + qs : ""));
  }

  function build(btn) {
    if (btn) btn.disabled = true;
    api("POST", `/api/projects/${P(project)}/terms/build`, {})
      .then((r) => follow(r.job.id))
      .catch((e) => { showError(e); if (btn) btn.disabled = false; });
  }
  function follow(jobId) {
    filters.hidden = true;
    watchers.push(jobCard(jobBox, jobId, "Building the glossary", glossaryLabel, async (job) => {
      filters.hidden = false;
      if (job.state === "done") { jobBox.hidden = true; toast("The glossary is ready.", "ok", { small: true }); }
      await load();
    }));
  }

  let seq = 0;
  async function load() {
    const my = ++seq;
    listBox.setAttribute("aria-busy", "true");
    const qs = new URLSearchParams({ offset: String(offset), limit: String(PAGE), sort });
    if (q) qs.set("q", q);
    let g;
    try { g = await api("GET", `/api/projects/${P(project)}/terms?${qs}`); } catch (e) { showError(e); listBox.setAttribute("aria-busy", "false"); return; }
    if (my !== seq) return;
    listBox.setAttribute("aria-busy", "false");
    draw(g);
  }

  function draw(g) {
    clear(statusBox); clear(listBox); clear(judgeBox);
    if (!g.built) {
      filters.hidden = true;
      listBox.appendChild(emptyState("network", "No glossary yet", "The glossary lists the terms your documents use, how often and in which documents, and groups the ones that mean the same thing (an abbreviation and its long form, for example). It is made on this computer in a few seconds to a minute; nothing is sent anywhere.",
        jobBox.hidden ? h("button", { class: "btn btn-primary", type: "button", onClick: (e) => build(e.currentTarget) }, icon("network", { size: 14 }), "Make the glossary") : null));
      return;
    }
    filters.hidden = !jobBox.hidden;
    if (g.stale) {
      statusBox.appendChild(h("div", { class: "notice notice-warn", style: { marginBottom: "14px" } }, icon("alert-triangle"),
        h("div", { class: "grow" }, h("p", {}, "Documents were added or removed since the glossary was made, so the counts may be out of date."),
          jobBox.hidden ? h("button", { class: "btn btn-sm", type: "button", style: { marginTop: "8px" }, onClick: (e) => build(e.currentTarget) }, icon("refresh", { size: 13 }), "Update the glossary") : null)));
    }
    const total = g.total || 0;
    live.textContent = q ? `${plural(total, "concept")} match “${q}”.` : `${plural(total, "concept")}.`;
    if (!total) {
      listBox.appendChild(emptyState("search-x", q ? "No concept matches" : "The glossary is empty", q ? `No term of the glossary contains “${q}”. Try another word, or search the documents for it.` : "No term occurs often enough in at least two documents.",
        q ? h("a", { class: "btn", href: searchHref(q) }, icon("text-search", { size: 14 }), "Search the documents for it") : null));
      return;
    }
    const pager = () => h("div", { class: "pager" },
      h("span", { class: "muted small" }, `${fmt.num(g.offset + 1)}–${fmt.num(Math.min(total, g.offset + g.items.length))} of ${plural(total, "concept")}`),
      total > PAGE ? h("div", { class: "btn-row" },
        h("button", { class: "btn btn-sm", type: "button", disabled: g.offset <= 0, onClick: () => { offset = Math.max(0, g.offset - PAGE); keepUrl(); load(); } }, icon("chevron-left", { size: 13 }), "Previous"),
        h("button", { class: "btn btn-sm", type: "button", disabled: g.offset + PAGE >= total, onClick: () => { offset = g.offset + PAGE; keepUrl(); load(); } }, "Next", icon("chevron-right", { size: 13 }))) : null);
    listBox.appendChild(pager());
    listBox.appendChild(h("div", { class: "table-wrap" }, h("table", { class: "table table-responsive ct-gloss" },
      h("caption", { class: "visually-hidden" }, "Glossary of concepts"),
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Concept"), h("th", { scope: "col", class: "num" }, "Documents"), h("th", { scope: "col", class: "num" }, "Passages"), h("th", { scope: "col", class: "num" }, "Mentions"))),
      h("tbody", {}, g.items.map((e) => {
        const others = (e.wordings || []).filter((w) => w !== e.label);
        const href = conceptHref(e.term_id);
        return h("tr", { class: "row-link", onClick: (ev) => { if (ev.target.closest("a")) return; location.hash = href; } },
          h("td", { class: "ct-name" }, h("a", { href }, e.label),
            others.length ? h("div", { class: "ct-also" }, `also written: ${others.slice(0, 6).join(", ")}${others.length > 6 ? ` and ${others.length - 6} more` : ""}`) : null),
          h("td", { class: "num", "data-label": "Documents" }, fmt.num(e.documents)),
          h("td", { class: "num", "data-label": "Passages" }, fmt.num(e.passages)),
          h("td", { class: "num", "data-label": "Mentions" }, fmt.num(e.mentions)));
      })))));
    if (total > PAGE) listBox.appendChild(pager());
    listBox.appendChild(h("p", { class: "muted small" }, `The glossary was made ${fmt.date(g.built_at)} from ${plural(g.terms, "term")}; ${g.concepts ? `${plural(g.concepts, "concept")} ${g.concepts === 1 ? "has" : "have"} more than one wording` : "no concept has more than one wording yet"}. A term is listed when it occurs at least three times in at least two documents.`));
    drawJudge();
  }

  function drawJudge() {
    const btn = h("button", { class: "btn btn-sm", type: "button" }, icon("sparkles", { size: 13 }), "Let the AI judge the proposed pairs");
    const mini = h("div");
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      let r;
      try { r = await api("POST", `/api/projects/${P(project)}/concepts/judge`, {}); }
      catch (e) {
        btn.disabled = false;
        if (e.status === 400 && /no pair/i.test(e.message)) toast("There is no proposed pair left to judge: search by meaning proposed none, or they were all judged.", "info");
        else showError(e);
        return;
      }
      const m = new MiniJob({ title: "The AI judges the proposed pairs" });
      mini.appendChild(m.el);
      const w = watchJob(r.job.id, (job) => m.update(job));
      watchers.push(w);
      w.promise.then((job) => {
        if (job.state === "done") { const res = job.result || {}; toast(`The AI judged ${plural(res.judged || 0, "pair")}${res.failed ? `; ${res.failed} could not be judged` : ""}. Open a concept to see its links.`, "ok"); }
        else if (job.state === "error") showError({ message: job.error, kind: job.error_kind });
        btn.disabled = false;
        load();
      }).catch(showError);
    });
    judgeBox.appendChild(h("details", { class: "fold section" }, h("summary", {}, "Terms that may mean the same"),
      h("div", { class: "card card-plain", style: { marginTop: "8px" } },
        h("p", { style: { marginTop: 0 } }, "With search by meaning, the glossary proposes pairs of terms that may mean the same (shown as “possibly the same” on a concept). Accept or reject them on the concept. The AI can judge the pairs nobody has judged yet; it never compares all the terms."),
        h("div", { class: "btn-row" }, btn), mini)));
  }

  search.addEventListener("input", debounce(() => { q = search.value.trim(); offset = 0; keepUrl(); load(); }, 250));
  sortSel.addEventListener("change", () => { sort = sortSel.value; offset = 0; keepUrl(); load(); });

  const running = await runningJob(project, ["terms"]);
  if (running) follow(running.id);
  await load();
  return () => watchers.forEach((w) => w.stop());
}

// ---------------------------------------------------------------------------------------------
// the card of one concept
// ---------------------------------------------------------------------------------------------
const SOURCE_TEXT = { meaning: "proposed by search by meaning", model: "judged by the AI", person: "added by you", abbreviation: "an abbreviation defined in the documents" };
// a link from search by meaning joins wordings only once a person accepted it
const JOINED_TEXT = { meaning: "you", model: "the AI", person: "you", abbreviation: "an abbreviation in the documents" };
// relations as seen from this concept ("this concept is broader than the other": the other is narrower)
const GROUPS = [
  ["same", "Possibly the same", "Terms that may mean the same as this concept. If you accept, they become wordings of it."],
  ["narrower", "Broader concepts", "This concept is part of these."],
  ["broader", "Narrower concepts", "These are part of this concept."],
  ["related", "Related to it", null],
  ["different", "Judged not the same", null],
];
const RELATION_CHOICES = [["same", "is the same as"], ["broader", "is broader than (includes)"], ["narrower", "is narrower than (is part of)"], ["related", "is related to"], ["different", "is different from"]];

export async function renderConcept(view, [termId], query) {
  const project = App.project;
  const base = `/api/projects/${P(project)}`;
  const watchers = [];
  let offset = Math.max(0, Number(query.offset) || 0);
  let refs = query.refs === "1";
  let allDocs = false;
  let c;
  try { c = await fetchCard(); }
  catch (e) {
    if (e.status === 404) {
      view.appendChild(pageHead("Concept", { eyebrow: h("a", { href: "#/concepts", class: "it" }, icon("network", { size: 12 }), "All concepts") }));
      view.appendChild(emptyState("search-x", "No such concept", "The glossary was made again since this link was made, or the term no longer occurs often enough. Find it in the glossary.", h("a", { class: "btn", href: "#/concepts" }, "Go to the glossary")));
      return;
    }
    throw e;
  }

  async function fetchCard() {
    return api("GET", `${base}/concepts/${P(termId)}?offset=${offset}&limit=${LINES}${refs ? "&refs=1" : ""}`);
  }

  const head = h("div");
  const body = h("div");
  view.append(head, body);
  const jobBox = h("section", { class: "section", hidden: true, "aria-label": "Progress" });
  const wordJob = h("div");     // the AI proposing other wordings
  const linkJob = h("div");     // the AI judging one pair
  let jobRunning = false;

  async function reload() {
    try { c = await fetchCard(); } catch (e) { showError(e); return; }
    draw();
  }

  function draw() {
    replace(head, h("header", { class: "page-head" },
      h("div", { class: "page-head-main" },
        h("p", { class: "eyebrow" }, h("a", { href: "#/concepts", class: "it" }, icon("network", { size: 12 }), "All concepts")),
        h("h1", { id: "page-title", tabindex: "-1", class: "serif ct-title" }, c.label),
        h("div", { class: "result-meta", style: { marginTop: "6px" } },
          h("span", {}, plural(c.mentions, "mention")), h("span", { class: "sep" }, "·"),
          h("span", {}, plural(c.passages, "passage")), h("span", { class: "sep" }, "·"),
          h("span", {}, plural((c.documents || []).length, "document")),
          c.wordings.length > 1 ? [h("span", { class: "sep" }, "·"), h("span", {}, `${c.wordings.length} wordings`)] : null)),
      h("div", { class: "page-head-actions" },
        h("a", { class: "btn btn-primary btn-sm", href: checkHref(cap(c.label) + " ") }, icon("flask", { size: 13 }), "Check a hypothesis about this concept"),
        h("a", { class: "btn btn-sm", href: searchHref(c.label) }, icon("text-search", { size: 13 }), "Search for it"))));
    document.title = `${c.label} · Concepts · ENLENS`;
    clear(body);
    body.appendChild(jobBox);
    if (c.stale && jobBox.hidden) {
      const btn = h("button", { class: "btn btn-sm", type: "button", style: { marginTop: "8px" } }, icon("refresh", { size: 13 }), "Update the glossary");
      btn.addEventListener("click", () => {
        btn.disabled = true;
        api("POST", `${base}/terms/build`, {}).then((r) => {
          watchers.push(jobCard(jobBox, r.job.id, "Updating the glossary", glossaryLabel, async (job) => {
            if (job.state === "done") { jobBox.hidden = true; toast("The glossary is up to date.", "ok", { small: true }); }
            await reload();
          }));
          draw();
        }).catch((e) => { showError(e); btn.disabled = false; });
      });
      body.appendChild(h("div", { class: "notice notice-warn", style: { marginBottom: "14px" } }, icon("alert-triangle"),
        h("div", {}, h("p", {}, "Documents were added or removed since the glossary was made, so these counts may be out of date."), btn)));
    }
    body.append(wordingsCard(), docsSection(), relatedCard(), linesSection());
  }

  // ---- wordings, and other wordings the AI proposes
  function wordingsCard() {
    const list = h("ul", { class: "ct-wordings" }, c.wordings.map((w) => h("li", {},
      h("a", { href: searchHref(w.label), class: "ct-wording serif", title: `Search the documents for “${w.label}”` }, w.label),
      h("span", { class: "muted small" }, `${plural(w.mentions, "mention")} in ${plural(w.documents, "document")}`),
      w.joined_by && w.joined_by.length ? h("span", { class: "chip" }, `joined by ${[...new Set(w.joined_by.map((s) => JOINED_TEXT[s] || s))].join(" and ")}`) : null,
      w.joins && w.joins.length ? h("button", { class: "btn btn-sm btn-ghost", type: "button", title: `Split “${w.label}” off: it does not mean the same as the other wordings`, onClick: async (e) => {
        const b = e.currentTarget; b.disabled = true;
        try {
          for (const j of w.joins) await api("PUT", `${base}/concepts/links`, { a: j.a, b: j.b, decision: "reject" });
          toast(`“${w.label}” is no longer a wording of this concept.`, "ok", { small: true, ttl: 3000 });
          if (w.term_id === termId) location.hash = `#/concepts/${encodeURIComponent(termId)}`; else await reload();
        } catch (err) { showError(err); b.disabled = false; }
      } }, icon("x", { size: 12 }), "Not the same") : null)));
    const ask = h("button", { class: "btn btn-sm", type: "button", disabled: jobRunning }, icon("sparkles", { size: 13 }), "Ask the AI for other wordings");
    ask.addEventListener("click", async () => {
      ask.disabled = true;
      let r;
      try { r = await api("POST", `${base}/concepts/${P(termId)}/wordings`, {}); } catch (e) { showError(e); ask.disabled = false; return; }
      jobRunning = true;
      const m = new MiniJob({ title: "The AI proposes other wordings" });
      replace(wordJob, m.el);
      const w = watchJob(r.job.id, (job) => m.update(job));
      watchers.push(w);
      w.promise.then(async (job) => {
        jobRunning = false;
        if (job.state === "done") {
          const n = ((job.result || {}).suggested || []).length;
          toast(n ? `${plural(n, "other wording")} ${n === 1 ? "is" : "are"} used in the documents.` : "The AI proposed no other wording that the documents use.", n ? "ok" : "info");
        } else if (job.state === "error") showError({ message: job.error, kind: job.error_kind });
        clear(wordJob);
        await reload();
      }).catch((e) => { jobRunning = false; showError(e); });
    });
    const sug = c.suggested_wordings || [];
    const sugBox = sug.length ? h("div", { class: "ct-suggest" },
      h("h3", {}, "Other wordings the AI proposes"),
      h("p", { class: "muted small", style: { margin: "0 0 8px" } }, "Only wordings the documents use are listed. Add one if it means the same as this concept, or say it does not and it is not proposed again."),
      h("ul", { class: "ct-wordings" }, sug.map((s) => {
        const add = h("button", { class: "btn btn-sm", type: "button" }, icon("plus", { size: 13 }), "Add as the same");
        add.addEventListener("click", () => saveLink({ a: termId, b: s.term_id, decision: "add", relation: "same" }, add, `“${s.label}” is now a wording of this concept.`));
        return h("li", {}, h("a", { href: conceptHref(s.term_id), class: "ct-wording serif" }, s.label),
          h("span", { class: "muted small" }, `${plural(s.mentions, "mention")} in ${plural(s.documents, "document")}`), add,
          h("button", { class: "btn btn-sm btn-ghost", type: "button", title: "It does not mean the same: it is not proposed again",
            onClick: (e) => saveLink({ a: termId, b: s.term_id, decision: "add", relation: "different" }, e.currentTarget, `“${s.label}” is not proposed again for this concept.`) }, icon("x", { size: 13 }), "Not the same"));
      }))) : null;
    return h("section", { class: "card section", "aria-labelledby": "ct-w-h" },
      h("div", { class: "card-head" }, h("h2", { id: "ct-w-h" }, "How the documents write it"), ask),
      list, wordJob, sugBox);
  }

  // ---- documents that discuss it
  function docsSection() {
    const docs = c.documents || [];
    const sw = switchControl("Count references too (“it”, “they”, “the study”)", refs, { help: "Adds the mentions that refer to this concept without naming it, in documents whose references were followed (open a document and choose “Follow references”)." });
    sw.input.addEventListener("change", async () => {
      refs = sw.input.checked;
      sw.input.disabled = true;
      await reload();
      const again = body.querySelector('section[aria-labelledby="ct-d-h"] .switch-input');
      if (again) again.focus();
    });
    const sec = h("section", { class: "section", "aria-labelledby": "ct-d-h" },
      h("div", { class: "section-title" }, h("h2", { id: "ct-d-h" }, `Documents that discuss it (${docs.length})`)), sw);
    if (!docs.length) { sec.appendChild(emptyState("book-open", "No document mentions it", "The documents may have changed since the glossary was made.")); return sec; }
    if (refs && c.references_total !== undefined) sec.appendChild(h("p", { class: "muted small" }, c.references_total ? `${plural(c.references_total, "reference")} without the name ${c.references_total === 1 ? "refers" : "refer"} to it.` : "No reference without the name was found: the references of these documents may not have been followed yet."));
    sec.appendChild(h("div", { class: "table-wrap", style: { marginTop: "10px" } }, h("table", { class: "table table-responsive ct-docs" },
      h("caption", { class: "visually-hidden" }, "Documents that discuss this concept"),
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Document"), h("th", { scope: "col", class: "num" }, "Mentions"), refs ? h("th", { scope: "col", class: "num" }, "References") : null, h("th", { scope: "col", class: "num" }, "Passages"), h("th", { scope: "col" }, "First appears"))),
      h("tbody", {}, (allDocs ? docs : docs.slice(0, 10)).map((d) => h("tr", {},
        h("td", {}, h("div", { class: "doc-title", title: d.title }, h("a", { href: `#/doc/${encodeURIComponent(d.doc_id)}` }, d.title || "untitled"))),
        h("td", { class: "num", "data-label": "Mentions" }, fmt.num(d.mentions)),
        refs ? h("td", { class: "num", "data-label": "References" }, fmt.num(d.references || 0)) : null,
        h("td", { class: "num", "data-label": "Passages" }, fmt.num(d.passages)),
        h("td", { class: "nowrap", "data-label": "First appears" }, d.first_location ? (d.first != null && d.first_end != null ? h("a", { href: `#/doc/${encodeURIComponent(d.doc_id)}?q=${d.first}-${d.first_end}`, title: "Open the document at this place" }, d.first_location) : d.first_location) : "—")))))));
    if (docs.length > 10) sec.appendChild(h("div", { class: "btn-row", style: { marginTop: "8px" } }, h("button", { class: "btn btn-sm btn-ghost", type: "button", "aria-expanded": allDocs ? "true" : "false",
      onClick: () => { allDocs = !allDocs; replace(sec, ...docsSection().childNodes); const b = sec.querySelector("button[aria-expanded]"); if (b) b.focus(); } }, icon(allDocs ? "chevron-up" : "chevron-down", { size: 13 }), allDocs ? "Show the first 10 only" : `Show all ${docs.length} documents`)));
    return sec;
  }

  // ---- related concepts
  async function saveLink(body, btn, done, opts = {}) {
    if (btn) btn.disabled = true;
    try {
      await api("PUT", `${base}/concepts/links`, body);
      // a removed link gets an Undo, as a rejected code does (0.8): the link and its concept come back
      const undo = opts.undo ? { text: "Undo", onClick: async () => {
        try { await api("PUT", `${base}/concepts/links`, { a: body.a, b: body.b, decision: "undo" }); toast("Undone: the link is back.", "ok", { small: true, ttl: 2500, group: "link" }); await reload(); } catch (e) { showError(e); }
      } } : null;
      toast(done || "Saved.", "ok", { small: true, ttl: undo ? 8000 : 3000, group: "link", ...(undo ? { button: undo } : {}) });
      await reload();
    } catch (e) { showError(e); if (btn) btn.disabled = false; }
  }

  function judgePair(lk, btn) {
    btn.disabled = true;
    api("POST", `${base}/concepts/judge`, { pairs: [[lk.a, lk.b]] }).then((r) => {
      jobRunning = true;
      const m = new MiniJob({ title: `The AI judges “${c.label}” and “${lk.label}”` });
      replace(linkJob, m.el);
      const w = watchJob(r.job.id, (job) => m.update(job));
      watchers.push(w);
      w.promise.then(async (job) => {
        jobRunning = false;
        if (job.state === "done") toast(job.result && job.result.judged ? "The AI has judged the pair: see what it says below." : "The AI could not judge the pair.", job.result && job.result.judged ? "ok" : "warn");
        else if (job.state === "error") showError({ message: job.error, kind: job.error_kind });
        clear(linkJob);
        await reload();
      }).catch((e) => { jobRunning = false; showError(e); });
    }).catch((e) => { showError(e); btn.disabled = false; });
  }

  function linkRow(lk) {
    const proposed = lk.state === "proposed";
    const who = [SOURCE_TEXT[lk.source] || lk.source];
    if (lk.source === "model" && lk.confidence !== null && lk.confidence !== undefined) who[0] += `, ${Math.round(lk.confidence * 100)}% sure`;
    if (lk.decision === "accept") who.push("accepted by you");
    else if (lk.decision === "change") who.push("changed by you");
    const actions = h("div", { class: "btn-row ct-link-acts" });
    if (proposed) {
      actions.append(
        h("button", { class: "btn btn-sm", type: "button", onClick: (e) => saveLink({ a: lk.a, b: lk.b, decision: "accept" }, e.currentTarget, "Accepted.") }, icon("check", { size: 13 }), lk.relation === "same" ? "Yes, the same" : "Yes, right"),
        h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: (e) => saveLink({ a: lk.a, b: lk.b, decision: "reject" }, e.currentTarget, "Rejected.", { undo: true }) }, icon("x", { size: 13 }), lk.relation === "same" ? "No, not the same" : "No"));
      if (lk.source === "meaning") actions.append(h("button", { class: "btn btn-sm btn-ghost", type: "button", disabled: jobRunning, onClick: (e) => judgePair(lk, e.currentTarget) }, icon("sparkles", { size: 13 }), "Ask the AI"));
    } else if (lk.source !== "abbreviation") {
      actions.append(h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: (e) => saveLink({ a: lk.a, b: lk.b, decision: "reject" }, e.currentTarget, "Removed.", { undo: true }) }, icon("x", { size: 13 }), "Not right"));
    }
    // another relation (as seen from this concept)
    const sel = h("select", { class: "select input-sm", "aria-label": `How “${c.label}” relates to “${lk.label}”` },
      RELATION_CHOICES.map(([v, t]) => h("option", { value: v, selected: v === lk.relation }, `${shortTitle(c.label, 30)} ${t} ${shortTitle(lk.label, 30)}`)));
    const change = h("details", { class: "ct-change" }, h("summary", { class: "btn btn-sm btn-ghost" }, "Another relation…"),
      h("div", { class: "row", style: { marginTop: "6px", gap: "6px" } }, sel,
        h("button", { class: "btn btn-sm", type: "button", onClick: (e) => saveLink({ a: lk.this_term, b: lk.term_id, decision: "change", relation: sel.value }, e.currentTarget, "Changed.") }, "Save")));
    actions.append(change);
    const quotes = [lk.quote_a, lk.quote_b].filter(Boolean);
    return h("li", { class: "ct-link" + (proposed ? " ct-proposed" : "") },
      h("div", { class: "ct-link-main" },
        h("a", { href: conceptHref(lk.term_id), class: "serif ct-link-name" }, lk.label),
        proposed ? h("span", { class: "chip chip-weak" }, "not confirmed") : null,
        h("span", { class: "muted small" }, who.join(" · "))),
      quotes.length ? h("details", { class: "fold ct-why" }, h("summary", {}, "The passages the AI pointed to"), h("ul", { class: "ct-quotes" }, quotes.map((t) => h("li", { class: "serif" }, "“", t, "”")))) : null,
      actions);
  }

  function relatedCard() {
    const rel = c.related || { links: [], together: [] };
    // one row per pair (a pair can have a link from search by meaning and one from the AI): the confirmed one wins
    const byPair = new Map();
    for (const lk of rel.links || []) {
      const key = `${lk.a}|${lk.b}`;
      const old = byPair.get(key);
      if (!old || (old.state !== "confirmed" && (lk.state === "confirmed" || (lk.confidence || 0) > (old.confidence || 0)))) byPair.set(key, lk);
    }
    const links = [...byPair.values()];
    const sec = h("section", { class: "card section", "aria-labelledby": "ct-r-h" }, h("div", { class: "card-head" }, h("h2", { id: "ct-r-h" }, "Related concepts")), linkJob);
    let any = false;
    for (const [rel_, title, help] of GROUPS) {
      const rows = links.filter((l) => l.relation === rel_).sort((x, y) => (x.state === "proposed" ? 0 : 1) - (y.state === "proposed" ? 0 : 1) || x.label.localeCompare(y.label));
      if (!rows.length) continue;
      any = true;
      const n = rows.filter((l) => l.state === "proposed").length;
      sec.appendChild(h("div", { class: "ct-group" },
        h("h3", {}, title, n ? h("span", { class: "chip chip-weak", style: { marginLeft: "8px" } }, `${n} to judge`) : null),
        help ? h("p", { class: "muted small", style: { margin: "0 0 6px" } }, help) : null,
        h("ul", { class: "ct-links" }, rows.map(linkRow))));
    }
    if (!any) sec.appendChild(h("p", { class: "muted", style: { marginTop: 0 } }, "No other concept is linked to this one yet. Add a link yourself below."));
    // add a link of one's own
    const input = h("input", { class: "input input-sm", type: "text", list: "ct-term-list", autocomplete: "off", placeholder: "another term…", "aria-label": "The other term" });
    const dl = h("datalist", { id: "ct-term-list" });
    input.addEventListener("input", debounce(async () => {
      const t = input.value.trim();
      if (t.length < 2) return;
      try {
        const g = await api("GET", `${base}/terms?q=${encodeURIComponent(t)}&limit=10`);
        replace(dl, (g.items || []).filter((e) => e.term_id !== termId).map((e) => h("option", { value: e.label })));
      } catch (_) { /* suggestions only */ }
    }, 250));
    const sel = h("select", { class: "select input-sm", "aria-label": "How the two relate" }, RELATION_CHOICES.map(([v, t]) => h("option", { value: v }, t)));
    const save = h("button", { class: "btn btn-sm", type: "button" }, icon("plus", { size: 13 }), "Add the link");
    const msg = h("p", { class: "field-error", role: "alert", hidden: true });
    save.addEventListener("click", async () => {
      const t = input.value.trim();
      msg.hidden = true;
      if (!t) { input.focus(); return; }
      let other;
      try { other = (await api("GET", `${base}/concepts?name=${encodeURIComponent(t)}`)).term_id; }
      catch (e) { if (e.status === 404) { msg.textContent = `No term of the glossary matches “${t}”.`; msg.hidden = false; return; } showError(e); return; }
      if (c.wordings.some((w) => w.term_id === other)) { msg.textContent = `“${t}” is already a wording of this concept.`; msg.hidden = false; return; }
      saveLink({ a: termId, b: other, decision: "add", relation: sel.value }, save, "Link added.");
    });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); save.click(); } });
    sec.appendChild(h("details", { class: "fold ct-add" }, h("summary", {}, "Add a link yourself"),
      h("div", { class: "ct-add-form" }, h("span", { class: "serif" }, shortTitle(c.label, 40)), sel, input, dl, save), msg));
    // co-occurrence
    const tog = rel.together || [];
    if (tog.length) {
      sec.appendChild(h("div", { class: "ct-group" },
        h("h3", {}, "Often mentioned together"),
        h("p", { class: "muted small", style: { margin: "0 0 6px" } }, "Concepts that appear in the same passages more often than chance would make them. The number is how many passages they share."),
        h("div", { class: "colloc" }, tog.map((t) => h("a", { class: "chip chip-btn", href: conceptHref(t.term_id), title: `${plural(t.together, "passage")} together, ${t.lift} times more often than chance` }, t.label, h("span", { class: "count" }, String(t.together)))))));
    }
    return sec;
  }

  // ---- the passages as concordance lines
  function linesSection() {
    const lines = c.lines || [];
    const total = c.mentions || 0;
    const sec = h("section", { class: "section", "aria-labelledby": "ct-l-h" },
      h("div", { class: "section-title" }, h("h2", { id: "ct-l-h" }, "Where it appears"), h("span", { class: "muted" }, "Each mention in its sentence. Click one to open the document there.")));
    if (!lines.length) { sec.appendChild(emptyState("search-x", "No mention to show", null)); return sec; }
    const pager = () => total > LINES ? h("div", { class: "pager" },
      h("span", { class: "muted small" }, `Mentions ${fmt.num(c.offset + 1)}–${fmt.num(c.offset + lines.length)} of ${fmt.num(total)}`),
      h("div", { class: "btn-row" },
        h("button", { class: "btn btn-sm", type: "button", disabled: c.offset <= 0, onClick: () => page(Math.max(0, c.offset - LINES)) }, icon("chevron-left", { size: 13 }), "Previous"),
        h("button", { class: "btn btn-sm", type: "button", disabled: c.offset + LINES >= total, onClick: () => page(c.offset + LINES) }, "Next", icon("chevron-right", { size: 13 })))) : null;
    { const pg = pager(); if (pg) sec.appendChild(pg); }
    sec.appendChild(h("div", { class: "kwic-wrap" }, h("table", { class: "kwic" },
      h("caption", { class: "visually-hidden" }, `Mentions of ${c.label} in their context`),
      h("tbody", {}, lines.map((l) => {
        const href = `#/doc/${encodeURIComponent(l.doc_id)}?q=${l.start}-${l.end}`;
        const where = `${shortTitle(l.title, 40)}${l.location ? `, ${l.location}` : ""}`;
        return h("tr", {},
          h("td", { class: "kw-left" }, h("span", {}, l.left)),
          h("td", { class: "kw-node" }, h("a", { href, class: "ct-node", title: `Open ${l.title || "the document"}${l.location ? ` at ${l.location}` : ""}` }, h("mark", {}, l.node))),
          h("td", { class: "kw-right" }, l.right),
          h("td", { class: "kw-where" }, h("a", { href, title: l.title }, where)));
      })))));
    { const pg = pager(); if (pg) sec.appendChild(pg); }
    return sec;
  }

  async function page(o) {
    offset = o;
    try { c = await fetchCard(); } catch (e) { showError(e); return; }
    draw();
    const t = document.getElementById("ct-l-h");
    if (t) t.scrollIntoView({ block: "start" });
  }

  draw();
  const running = await runningJob(project, ["terms"]);
  if (running) {
    watchers.push(jobCard(jobBox, running.id, "Updating the glossary", glossaryLabel, async (job) => { if (job.state === "done") jobBox.hidden = true; await reload(); }));
  }
  return () => watchers.forEach((w) => w.stop());
}
