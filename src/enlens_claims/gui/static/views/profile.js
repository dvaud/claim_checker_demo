// Profile (F2): a codebook profile of the project's documents. Which codes of a codebook (the 169 SDG targets, the
// 17 goals, or a person's own) each document addresses, how much and where. Two passes: keywords and meaning (no AI,
// seconds, a provisional profile) and, optionally, the AI reading the passages with a candidate code. Every label
// says why it is there; a person can agree, change or reject it (in the document viewer, Codes panel).
// The pieces shared with the document viewer (the AI-labelling card, job cards, wording) are exported from here.
import { featureEyebrow } from "../features.js";
import { App, api, h, icon, replace, clear, toast, showError, fmt, pageHead, watchJob, P, emptyState, TERMINAL, download, switchControl, navigate } from "../lib.js";
import { simpleProgress } from "./progress.js";

export const plural = (n, one, many) => `${fmt.num(n)} ${n === 1 ? one : many || one + "s"}`;
export const shortTitle = (t, n = 70) => { t = (t || "untitled").replace(/\s+/g, " ").trim(); return t.length > n ? t.slice(0, n - 2).trimEnd() + "…" : t; };
const pct = (x) => `${Math.round((x || 0) * 100)}%`;

// Who put a label there, in the app's words
export const SOURCE_WORDS = { keywords: "found by keywords", meaning: "found by meaning", both: "keywords and meaning agree", model: "labelled by the AI", person: "added by you" };
export const RELEVANCE_WORDS = { main: "main topic", mentioned: "mentioned" };
export const DIRECTION_WORDS = { helps: "helps", hinders: "hinders", mixed: "mixed", not_stated: "direction not stated" };

// "about 12 minutes" from seconds (null when unknown)
export function aboutTime(sec) {
  if (sec === null || sec === undefined) return null;
  if (sec < 50) return "less than a minute";
  if (sec < 90) return "about a minute";
  if (sec < 3600) return `about ${Math.round(sec / 60)} minutes`;
  const hrs = sec / 3600;
  return hrs < 1.5 ? "about an hour" : `about ${Math.round(hrs * 2) / 2} hours`.replace(".5", "½");
}

// κ in words (as the model test reports agreement)
function kappaWord(k) {
  if (k === null || k === undefined) return "";
  return k >= 0.8 ? "very good" : k >= 0.6 ? "good" : k >= 0.4 ? "moderate" : "low";
}

// What differs from the last labelling run, one plain sentence each (runs.plan `changed`)
const shown = (v) => (v === null || v === undefined || v === "" ? "not recorded" : String(v));
const CHANGED = {
  model: (c) => `The AI model changed: ${shown(c.was)} → ${shown(c.now)}.`,
  digest: () => "The model's exact version changed: same name, but a different model file.",
  prompt_version: (c) => `The instructions given to the AI changed (prompt version ${shown(c.was)} → ${shown(c.now)}).`,
  seed: (c) => `The seed (which keeps answers repeatable) changed: ${shown(c.was)} → ${shown(c.now)}.`,
  backend: (c) => `The AI server changed: ${shown(c.was)} → ${shown(c.now)}.`,
  num_ctx: (c) => `The context length changed: ${shown(c.was)} → ${shown(c.now)}.`,
  think: (c) => `The reasoning setting changed: ${shown(c.was)} → ${shown(c.now)}.`,
  think_budget: (c) => `The reasoning budget changed: ${shown(c.was)} → ${shown(c.now)}.`,
};
export function changedLines(changed) {
  return (changed || []).map((c) => (CHANGED[c.field] || ((x) => `${x.field} changed: ${shown(x.was)} → ${shown(x.now)}.`))(c));
}

// A running job of one of these kinds for this project, if any.
export async function runningJob(project, kinds) {
  try {
    const jobs = (await api("GET", "/api/jobs")).jobs || [];
    return jobs.find((j) => j.project === project && kinds.includes(j.kind) && !TERMINAL.has(j.state)) || null;
  } catch (_) { return null; }
}

// A job in a card: a bar with what it is doing, its time and a Stop button. `onEnd(job)` runs when it ends.
export function jobCard(box, jobId, title, labelFn, onEnd, opts = {}) {
  const stop = h("button", { class: "btn btn-sm btn-outline-danger", type: "button" }, icon("stop", { size: 13 }), "Stop");
  const pb = h("div", { "aria-live": "polite" });
  const head = h(opts.small ? "h3" : "h2", {}, title);
  const holder = h("div", { class: "card" + (opts.plain ? " card-plain" : "") }, h("div", { class: "card-head" }, head, stop), pb);
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
      replace(pb, h("p", { class: "muted", style: { margin: 0 } }, opts.stoppedText || "Stopped. What was done so far is kept."));
    }
    if (onEnd) onEnd(job);
  }).catch(showError);
  return w;
}

export const keywordLabel = (p) => (p.total ? `Reading the passages: ${fmt.num(p.done || 0)} of ${fmt.num(p.total)}` : "Reading the passages…");
export const labelLabel = (p) => (p.total ? `The AI has read ${fmt.num(Math.max(0, (p.done || 0) - 1))} of ${fmt.num(p.total)} ${p.total === 1 ? "passage" : "passages"}` : "The AI is getting ready…");
const compareLabel = (p) => (p.total ? `The AI labels the sample again: ${fmt.num(Math.max(0, (p.done || 0) - 1))} of ${fmt.num(p.total)}` : "The AI is getting ready…");

// Start the keyword-and-meaning pass and follow it in `box`; `onEnd(job)` when it ends.
export function startKeywordPass(project, framework, box, watchers, onEnd, btn) {
  if (btn) btn.disabled = true;
  api("POST", `/api/projects/${P(project)}/profile/keywords`, { framework })
    .then((r) => watchers.push(jobCard(box, r.job.id, "Finding the codes by keywords and meaning", keywordLabel, onEnd)))
    .catch((e) => { showError(e); if (btn) btn.disabled = false; });
}

// The card "Let the AI read the passages": what it would read and how long it takes, what changed since the last
// labelling run (with "Label a sample (up to 50) again first"), and the run itself with progress and Stop.
// `docIds`: only these documents (the document viewer); `onEnd(job)` after a run.
export function aiLabelCard({ project, framework, docIds = null, watchers, onEnd, onStart, compact = false }) {
  const base = `/api/projects/${P(project)}`;
  const hid = "pf-ai-h-" + Math.random().toString(36).slice(2, 7);
  const el = h("section", { class: "pf-ai" + (compact ? " pf-ai-compact" : " card section"), "aria-labelledby": hid });
  const jobBox = h("div", { hidden: true });
  const body = h("div", {}, h("p", { class: "muted small", style: { margin: 0 } }, "Looking at what the AI would read…"));
  let all = false;
  let limit = "";
  let compareResult = null;
  let running = false;
  const one = docIds && docIds.length === 1;
  el.append(h(compact ? "h3" : "h2", { id: hid, class: "pf-ai-title" }, icon("sparkles", { size: compact ? 14 : 16 }), one ? " Let the AI read this document" : " Let the AI read the passages"), body, jobBox);

  async function load() {
    if (running) return;
    const qs = new URLSearchParams({ framework });
    if (docIds) qs.set("docs", docIds.join(","));
    if (all) qs.set("all", "1");
    let plan;
    try { plan = await api("GET", `${base}/profile/plan?${qs}`); }
    catch (e) { replace(body, h("div", { class: "notice notice-error" }, icon("alert-circle"), h("p", {}, e.message || "Could not see what the AI would read."))); return; }
    draw(plan);
  }

  function draw(plan) {
    const run = plan.run || {};
    const where = App.privacy();
    const toRead = plan.to_read || 0;
    const lim = Number(limit) > 0 ? Math.min(Number(limit), toRead) : toRead;
    const est = plan.estimate_seconds && toRead ? Math.round((plan.estimate_seconds * lim) / toRead) : null;
    const bits = [];
    bits.push(h("p", { class: compact ? "small" : "", style: { margin: "6px 0" } },
      toRead === 0 && plan.already_read ? "The AI has read all these passages. " : plan.already_read ? "Passages the AI has not read yet count with their keyword codes (provisional). " : "The keyword profile is provisional. ",
      "The AI reads ", all ? "every passage" : "each passage with a candidate code", ", says which codes really apply (as the main topic or a mention), and gives a quote and a reason for each. It resumes where it stopped and never reads a passage twice."));
    const counts = all
      ? `${plural(plan.passages || 0, "passage")}${one ? " in this document" : ""}: ${fmt.num(plan.already_read || 0)} already read, ${fmt.num(toRead)} to read.`
      : `${plural(plan.with_candidates || 0, "passage")} of ${fmt.num(plan.passages || 0)}${one ? " in this document" : ""} ${plan.with_candidates === 1 ? "has" : "have"} a candidate code: ${fmt.num(plan.already_read || 0)} already read, ${fmt.num(toRead)} to read.`;
    bits.push(h("p", { class: "pf-ai-counts", style: { margin: "0 0 6px" } }, h("strong", {}, counts), est ? ` ${cap(aboutTime(est))} with this model.` : toRead ? " How long it takes is not known yet: it is measured on the first passages." : ""));
    if (where.where === "cloud") bits.push(h("p", { class: "muted small it", style: { margin: "0 0 6px" } }, icon("cloud", { size: 13 }), ` ${where.sent || "The passages are sent to the Claude API (cloud)."}`));
    if (run.error) {
      bits.push(h("div", { class: "notice notice-warn" }, icon("alert-triangle"), h("div", {}, h("p", {}, "The AI model is not available, so it cannot label passages now."),
        h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("div", { class: "mono small" }, run.error)), h("a", { href: "#/settings" }, "Check the AI model in Settings"))));
      replace(body, bits);
      return;
    }
    // options
    const sw = switchControl("Read every passage, not only those with a candidate code", all, { help: "Slower. Finds codes the keywords missed." });
    sw.input.addEventListener("change", () => { all = sw.input.checked; load(); });
    const limIn = h("input", { class: "input input-sm pf-limit", type: "number", min: "1", step: "1", inputmode: "numeric", value: limit, placeholder: "all", "aria-describedby": hid + "-lim" });
    limIn.addEventListener("change", () => { limit = limIn.value.trim(); draw(plan); const again = el.querySelector(".pf-limit"); if (again) again.focus(); });
    const limRow = h("label", { class: "row pf-limit-row" }, h("span", { class: "small" }, "Read at most"), limIn, h("span", { class: "small" }, "passages this time"));
    const opts = h("details", { class: "fold pf-ai-opts", open: all || !!limit }, h("summary", {}, "Options"), h("div", { style: { marginTop: "6px" } }, sw, limRow,
      h("p", { class: "field-help", id: hid + "-lim" }, "To try the AI on a few passages first. Leave it empty to read them all; you can stop at any time.")));
    // what changed since the last run
    const changed = run.changed || [];
    const startBtn = h("button", { class: "btn btn-primary" + (compact ? " btn-sm" : ""), type: "button", disabled: !lim }, icon("sparkles", { size: 14 }),
      !toRead ? "Nothing left to read" : changed.length ? `Label ${plural(lim, "passage")} anyway` : `Let the AI label ${plural(lim, "passage")}`);
    startBtn.addEventListener("click", () => start(startBtn));
    if (changed.length) {
      const last = run.last || {};
      const cmpBox = h("div");
      const cmpBtn = h("button", { class: "btn btn-sm", type: "button" }, icon("scale", { size: 13 }), "Label a sample (up to 50) again first");
      cmpBtn.addEventListener("click", () => compare(cmpBtn, cmpBox, plan));
      bits.push(h("div", { class: "notice notice-warn pf-changed" }, icon("alert-triangle"), h("div", { class: "grow" },
        h("p", {}, h("strong", {}, `Something changed since the last labelling${last.started_at ? ` (${fmt.date(last.started_at)})` : ""}. `), "New labels may differ from the earlier ones for that reason alone:"),
        h("ul", { class: "pf-changed-list" }, changedLines(changed).map((t) => h("li", {}, t))),
        h("p", {}, "Label a sample the AI already labelled again with the new settings, to see how much the labels agree before you go on."),
        h("div", { class: "btn-row", style: { marginTop: "6px" } }, cmpBtn), cmpBox,
        compareResult ? compareNote(compareResult) : null,
        h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("table", { class: "table pf-tech-table" },
          h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Setting"), h("th", { scope: "col" }, "Last run"), h("th", { scope: "col" }, "Now"))),
          h("tbody", {}, changed.map((c) => h("tr", {}, h("td", {}, c.field), h("td", { class: "mono small" }, shown(c.was)), h("td", { class: "mono small" }, shown(c.now))))))))));
    }
    if (toRead) bits.push(h("div", { class: "btn-row", style: { marginTop: "8px" } }, startBtn));
    else bits.push(h("p", { class: "it", style: { margin: "4px 0" } }, icon("circle-check", { size: 14 }), all ? " The AI has read every passage." : " The AI has read every passage with a candidate code."));
    bits.push(opts);
    bits.push(h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("dl", { class: "ev-tech-list" },
      h("div", {}, h("dt", {}, "AI model"), h("dd", {}, shown(run.now && run.now.model))),
      h("div", {}, h("dt", {}, "Exact version"), h("dd", { class: "mono" }, shown(run.now && run.now.digest))),
      h("div", {}, h("dt", {}, "Prompt"), h("dd", {}, shown(run.now && run.now.prompt_version))),
      h("div", {}, h("dt", {}, "Seed"), h("dd", {}, shown(run.now && run.now.seed))),
      h("div", {}, h("dt", {}, "Seconds per passage"), h("dd", {}, run.seconds_per_task ? String(run.seconds_per_task) : "not measured yet")),
      run.last ? h("div", {}, h("dt", {}, "Last labelling run"), h("dd", {}, `${fmt.date(run.last.started_at)} · ${shown(run.last.model)} · ${plural(run.last.tasks || 0, "passage")}`)) : null)));
    replace(body, bits);
  }

  function compareNote(r) {
    if (!r.compared) return h("p", { class: "small", style: { marginTop: "6px" } }, "The AI could not label the sample again", r.errors ? ` (${plural(r.errors, "answer")} could not be read)` : "", ".");
    return h("div", { class: "pf-compare", role: "status" },
      h("p", {}, h("strong", {}, `The AI labelled ${plural(r.compared, "passage")} again with ${r.model || "the model now set"}. `),
        r.kappa !== null && r.kappa !== undefined ? `Agreement with the earlier labels beyond chance: κ = ${Number(r.kappa).toFixed(2)} (${kappaWord(r.kappa)}). ` : "",
        r.same_codes !== null && r.same_codes !== undefined ? `${pct(r.same_codes)} of the passages got exactly the same codes.` : "",
        r.errors ? ` ${plural(r.errors, "answer")} could not be read.` : ""),
      h("p", { class: "muted small" }, r.kappa !== null && r.kappa < 0.6 ? "The labels differ noticeably: labels made before and after the change are not quite comparable. Say so when you report them." : "Nothing was stored: the earlier labels are unchanged."));
  }

  async function compare(btn, box, plan) {
    btn.disabled = true;
    let r;
    try { r = await api("POST", `${base}/profile/compare`, { framework, n: 50 }); }
    catch (e) { showError(e); btn.disabled = false; return; }
    watchers.push(jobCard(box, r.job.id, "Labelling a sample again to compare", compareLabel, (job) => {
      if (job.state === "done") { compareResult = job.result || {}; box.hidden = true; draw(plan); }
      else btn.disabled = false;
    }, { small: true, plain: true, stoppedText: "Stopped. Nothing was stored." }));
  }

  async function start(btn) {
    btn.disabled = true;
    const lim = Number(limit) > 0 ? Math.floor(Number(limit)) : undefined;
    const payload = { framework, all_passages: all };
    if (docIds) payload.doc_ids = docIds;
    if (lim) payload.limit = lim;
    let r;
    try { r = await api("POST", `${base}/profile/label`, payload); }
    catch (e) { showError(e); btn.disabled = false; return; }
    if (onStart) onStart(r.job.id);
    follow(r.job.id);
  }

  function follow(jobId) {
    running = true;
    body.hidden = true;
    watchers.push(jobCard(jobBox, jobId, "The AI labels passages", labelLabel, (job) => {
      running = false;
      if (job.state === "done") {
        const res = job.result || {};
        const ch = res.changes || {};
        toast(`The AI read ${plural(res.read || 0, "passage")}${res.failed ? `; ${res.failed} could not be read` : ""}. Of the codes the keywords found there, it confirmed ${fmt.num(ch.confirmed || 0)} and did not confirm ${fmt.num(ch.not_confirmed || 0)}; it added ${fmt.num(ch.added || 0)} the keywords had missed.`, res.failed ? "warn" : "ok", { ttl: 12000 });
        jobBox.hidden = true;
      }
      body.hidden = false;
      load();
      if (onEnd) onEnd(job);
    }, { small: compact, plain: compact, stoppedText: "Stopped. The passages read so far keep their labels; start again to go on where it stopped." }));
  }

  load();
  return { el, follow, reload: load };
}

const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

// A heat cell of the documents × codes grid: on a log scale, so one very large cell does not leave the others pale.
function heatCell(n, max, label, onClick) {
  const level = n ? Math.max(1, Math.min(4, Math.ceil((4 * Math.log1p(n)) / Math.log1p(max)))) : 0;
  return h("td", { class: `map-cell pf-cell pf-l${level}`, title: `${label}: ${plural(n, "passage")}`, onClick: n ? onClick : null },
    h("span", { class: "visually-hidden" }, `${label}: `), n ? String(n) : h("span", { "aria-label": "none" }, "·"));
}

// "How often you agreed with the AI" (the settings page's chart, for codebook labels)
function calibrationBox(c) {
  const bins = c.bins || [];
  const box = h("div", { class: "cal-box" });
  box.appendChild(h("h3", { class: "cal-title" }, icon("scale", { size: 14 }), " How often you agreed with the AI, by its certainty"));
  const chart = h("div", { class: "cal-chart", role: "img", "aria-label": `Agreement with the AI's labels by its certainty: ${bins.map((b) => `${pct(b.from)} to ${pct(b.to)}: ${b.judged ? `${b.agreed} of ${b.judged} (${pct(b.rate || 0)})` : "none judged"}`).join("; ")}.` });
  for (const b of bins) {
    const rate = b.judged ? (b.rate ?? b.agreed / b.judged) : null;
    chart.appendChild(h("div", { class: "cal-col cal-counted" },
      h("span", { class: "cal-val" }, rate === null ? "–" : pct(rate)),
      h("div", { class: "cal-bar-wrap" }, rate === null ? h("div", { class: "cal-bar cal-empty", style: { height: "100%" } }) : h("div", { class: "cal-bar", style: { height: `${Math.max(3, Math.round(rate * 100))}%` } })),
      h("div", { class: "cal-lab" }, `${pct(b.from)}–${pct(b.to)}`),
      h("div", { class: "cal-n" }, b.judged ? `${b.agreed} of ${b.judged}` : "none")));
  }
  box.appendChild(chart);
  box.appendChild(h("p", { class: "muted small cal-foot" }, `From the ${plural(c.total, "label")} of the AI you reviewed: you agreed with ${c.agreed || 0} (${pct(c.total ? (c.agreed || 0) / c.total : 0)}). Changing a label's relevance or direction counts as agreeing that the code applies; rejecting it does not. The number under each bar is how many you agreed with of those you reviewed.`));
  box.appendChild(h("details", { class: "fold" }, h("summary", {}, "As a table"),
    h("table", { class: "table cal-table" }, h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "AI certainty"), h("th", { scope: "col", class: "num" }, "You reviewed"), h("th", { scope: "col", class: "num" }, "You agreed"), h("th", { scope: "col", class: "num" }, "Agreement"))),
      h("tbody", {}, bins.map((b) => h("tr", {}, h("td", {}, `${pct(b.from)} to ${pct(b.to)}`), h("td", { class: "num" }, String(b.judged)), h("td", { class: "num" }, String(b.agreed)), h("td", { class: "num" }, b.judged ? pct(b.rate ?? b.agreed / b.judged) : "–")))))));
  return box;
}

// ---------------------------------------------------------------------------------------------
// the Profile page
// ---------------------------------------------------------------------------------------------
export async function renderProfile(view, params, query) {
  const project = App.project;
  const base = `/api/projects/${P(project)}`;
  const watchers = [];
  let framework = query.framework || App.settings().profile_framework || "sdg";
  let savedLevel = null;
  try { savedLevel = localStorage.getItem("enlens.profile.level"); } catch (_) { /* no storage */ }
  let level = (query.level || savedLevel) === "group" ? "group" : "code";
  let prof;
  const fetchProfile = () => api("GET", `${base}/profile?framework=${encodeURIComponent(framework)}&level=${level}`);
  try { prof = await fetchProfile(); }
  catch (e) {
    if (e.status === 400 && framework !== "sdg") { toast(`The codebook “${framework}” is not available: showing the SDG targets.`, "warn"); framework = "sdg"; prof = await fetchProfile(); }
    else throw e;
  }
  let docs = null;   // the project's documents, for "open one document's profile"
  api("GET", `${base}/documents`).then((r) => { docs = r.documents || []; drawControls(); drawSummary(); }).catch(() => {});

  const head = h("div");
  const controls = h("div", { class: "pf-controls" });
  const jobBox = h("section", { class: "section", hidden: true, "aria-label": "Progress" });
  const statusBox = h("div");
  const aiBox = h("div");
  const topBox = h("div");
  const gridBox = h("section", { class: "section", "aria-labelledby": "pf-grid-h" });
  const calBox = h("div");
  view.append(head, controls, jobBox, statusBox, aiBox, topBox, gridBox, calBox);
  let ai = null;

  const fwInfo = () => (prof.frameworks || []).find((f) => f.name === framework) || { name: framework, title: framework, label: "code" };
  const groupWord = () => (/^sdg/.test(framework) ? "goal" : "group");

  function keepUrl() {
    const s = new URLSearchParams();
    if (framework !== (App.settings().profile_framework || "sdg")) s.set("framework", framework);
    if (level !== "code") s.set("level", level);
    const qs = s.toString();
    history.replaceState(null, "", "#/profile" + (qs ? "?" + qs : ""));
  }

  async function reload() {
    try {
      prof = await fetchProfile();
      if (level === "group" && fwInfo().groups === 0) { level = "code"; prof = await fetchProfile(); }  // a codebook without groups
    } catch (e) { showError(e); return; }
    draw();
  }

  function draw() {
    const xlsx = h("button", { class: "btn btn-sm", type: "button", disabled: !prof.pass1.done,
      onClick: (e) => { const b = e.currentTarget; b.disabled = true; download(`${base}/profile.xlsx?framework=${encodeURIComponent(framework)}&level=${level}`).catch(showError).finally(() => { b.disabled = false; }); } },
      icon("download", { size: 13 }), "Download for Excel (.xlsx)");
    replace(head, pageHead("Profile", { eyebrow: featureEyebrow("profile"),
      sub: `Which codes of a codebook the documents of project “${project}” address, how much and where. Every label says why it is there, and you can agree, change or reject it in the document.`,
      actions: [xlsx],
    }));
    drawControls();
    drawSummary();
    drawGrid();
    drawCalibration();
  }

  function drawControls() {
    const fws = prof.frameworks || [];
    const sel = h("select", { class: "select input-sm", id: "pf-fw" }, fws.map((f) => h("option", { value: f.name, selected: f.name === framework }, (f.title && /\(\d+ \w+\)/.test(f.title) ? f.title : `${f.title || f.name} (${plural(f.codes, "code")})`))));
    sel.addEventListener("change", async () => {
      framework = sel.value;
      // the codebook of document profiles is a setting: new documents get its codes when they are added
      try { await api("PUT", "/api/settings", { profile_framework: framework }); await App.refresh(); } catch (_) { /* the page still works */ }
      keepUrl();
      await reload();
      const again = document.getElementById("pf-fw"); if (again) again.focus();
    });
    const seg = (val, label) => h("button", { class: "btn btn-sm seg-btn" + (level === val ? " seg-on" : ""), type: "button", "aria-pressed": level === val ? "true" : "false",
      onClick: async () => { if (level === val) return; level = val; try { localStorage.setItem("enlens.profile.level", val); } catch (_) { /* no storage */ } keepUrl(); await reload(); const b = controls.querySelector(`[data-level="${val}"]`); if (b) b.focus(); }, dataset: { level: val } }, label);
    const fw = fwInfo();
    const docSel = docs && docs.length ? h("select", { class: "select input-sm", id: "pf-doc", "aria-label": "Open the profile of one document" },
      h("option", { value: "" }, "Open one document's profile…"), docs.map((d) => h("option", { value: d.doc_id }, shortTitle(d.title || d.file, 80)))) : null;
    if (docSel) docSel.addEventListener("change", () => { if (docSel.value) navigate(`#/doc/${encodeURIComponent(docSel.value)}?tab=codes${framework !== (App.settings().profile_framework || "sdg") ? `&framework=${encodeURIComponent(framework)}` : ""}`); });
    replace(controls,
      h("div", { class: "pf-control" }, h("label", { class: "field-label", for: "pf-fw" }, "Codebook"), sel,
        h("span", { class: "field-help" }, "New documents get this codebook's codes when they are added. ", h("a", { href: "#/settings/frameworks" }, "Add your own codebook (CSV)"))),
      fw.groups === 0 ? null : h("div", { class: "pf-control" }, h("span", { class: "field-label", id: "pf-level-l" }, "Count by"),
        h("div", { class: "btn-row pf-seg", role: "group", "aria-labelledby": "pf-level-l" }, seg("code", fw.label ? cap(fw.label) : "Code"), seg("group", /^sdg/.test(framework) ? "Goal" : "Group"))),
      docSel ? h("div", { class: "pf-control" }, h("label", { class: "field-label", for: "pf-doc" }, "Show the profile of"), docSel) : null);
  }

  function drawSummary() {
    clear(statusBox); clear(topBox);
    const p1 = prof.pass1 || {};
    const fw = fwInfo();
    if (!p1.done) {
      clear(aiBox); ai = null;
      if (!jobBox.hidden) return;
      statusBox.appendChild(emptyState("tag", "No profile with this codebook yet",
        `First the app finds the ${fw.label || "code"}s of “${fw.title || framework}” in every passage by their keywords${App.settings().embed_backend === "off" ? "" : " and by meaning"}. It takes seconds, runs on this computer, and gives a provisional profile at once. The AI can then read the passages to confirm or correct it.`,
        h("button", { class: "btn btn-primary", type: "button", onClick: (e) => startKeywordPass(project, framework, jobBox, watchers, keywordsEnded, e.currentTarget) }, icon("tag", { size: 14 }), "Find the codes by keywords")));
      return;
    }
    if (p1.stale && jobBox.hidden) {
      statusBox.appendChild(h("div", { class: "notice notice-warn", style: { marginBottom: "14px" } }, icon("alert-triangle"),
        h("div", { class: "grow" }, h("p", {}, "Documents were added or removed since the codes were found by keywords, so the profile leaves out the changes."),
          h("button", { class: "btn btn-sm", type: "button", style: { marginTop: "8px" }, onClick: (e) => startKeywordPass(project, framework, jobBox, watchers, keywordsEnded, e.currentTarget) }, icon("refresh", { size: 13 }), "Find the codes again (seconds)"))));
    }
    const st = prof.stats || {};
    const by = st.by_source || {};
    const g = prof.grid || {};
    const nDocs = (App.state.projects.find((x) => x.name === project) || {}).documents ?? (docs ? docs.length : null);
    const withNone = nDocs !== null && nDocs !== undefined ? Math.max(0, nDocs - (st.documents || 0)) : 0;
    const provisionalOnly = !by.model && !by.person;
    const sources = [["model", "by the AI"], ["person", "by you"], ["both", "by keywords and meaning together"], ["keywords", "by keywords"], ["meaning", "by meaning"]]
      .filter(([k]) => by[k]).map(([k, t]) => `${fmt.num(by[k])} ${t}`);
    statusBox.appendChild(h("section", { class: "card pf-summary", "aria-label": "Summary" },
      h("p", { class: "pf-lead" }, h("strong", {}, `${plural(st.labels || 0, "label")} in ${plural(st.passages || 0, "passage")} of ${plural(st.documents || 0, "document")}`),
        withNone ? ` (${plural(withNone, "document")} without any ${fw.label || "code"})` : "", "."),
      h("p", { class: "muted small", style: { margin: "2px 0 0" } }, `Labelled ${sources.join(", ") || "by nobody yet"}. `,
        provisionalOnly ? h("span", { class: "chip chip-weak" }, "provisional") : null,
        provisionalOnly ? " The AI has not read any passage yet: the profile rests on keywords" + (p1.meaning_model ? " and meaning" : "") + " alone." : g.provisional ? ` The AI has read ${plural(prof.read_by_model || 0, "passage")}; passages it has not read count with their keyword codes (provisional).` : ` The AI has read ${plural(prof.read_by_model || 0, "passage")}.`),
      h("details", { class: "fold" }, h("summary", {}, "Technical details"),
        h("p", { class: "muted small", style: { margin: "4px 0 6px" } }, "A passage is the stretch of text the app reads as one unit, up to about 1,100 characters: a few paragraphs together, or part of a long one. A passage can have several codes, so there are more labels than passages; the AI may confirm fewer codes than the keywords proposed."),
        h("dl", { class: "ev-tech-list" },
        h("div", {}, h("dt", {}, "Codebook"), h("dd", {}, `${fw.title || framework} (${framework})`)),
        h("div", {}, h("dt", {}, "Keyword pass"), h("dd", {}, `${fmt.date(p1.at)} · ${plural(p1.passages || 0, "passage")}`)),
        h("div", {}, h("dt", {}, "By meaning"), h("dd", {}, p1.meaning_model || "not used (no search by meaning)")),
        h("div", {}, h("dt", {}, "Read by the AI"), h("dd", {}, fmt.num(prof.read_by_model || 0)))))));
    if (!ai) { ai = aiLabelCard({ project, framework, watchers, onEnd: () => reload() }); replace(aiBox, ai.el); }
    // the codes addressed most
    const codes = [...(g.codes || [])].sort((a, b) => b.passages - a.passages || b.documents - a.documents).slice(0, 8);
    if (codes.length) {
      const max = Math.max(1, ...codes.map((c) => c.passages));
      topBox.appendChild(h("section", { class: "section", "aria-labelledby": "pf-top-h" },
        h("div", { class: "section-title" }, h("h2", { id: "pf-top-h" }, level === "group" ? `The ${groupWord()}s addressed most` : `The ${fw.label || "code"}s addressed most`)),
        h("ol", { class: "pf-top" }, codes.map((c) => h("li", {},
          h("span", { class: "pf-top-code" }, c.code),
          h("span", { class: "pf-top-desc" }, c.description || ""),
          h("span", { class: "pf-top-bar", "aria-hidden": "true" }, h("span", { style: { width: `${Math.max(2, Math.round((c.passages / max) * 100))}%` } })),
          h("span", { class: "pf-top-n" }, `${plural(c.passages, "passage")} · ${plural(c.documents, "document")}`))))));
    }
  }

  function keywordsEnded(job) {
    if (job.state === "done") {
      const r = job.result || {};
      jobBox.hidden = true;
      toast(`Codes found by keywords${r.meaning ? " and meaning" : ""} in ${plural(r.with_candidates || 0, "passage")}.`, "ok");
    }
    ai = null;
    reload();
  }

  function drawGrid() {
    clear(gridBox);
    if (!prof.pass1.done) return;
    const g = prof.grid || {};
    const fw = fwInfo();
    const unit = level === "group" ? groupWord() : (fw.label || "code");
    gridBox.appendChild(h("div", { class: "section-title" }, h("h2", { id: "pf-grid-h" }, `Documents by ${unit}`),
      h("span", { class: "muted" }, "How many passages of each document carry each code. Click a document to see where.")));
    const codes = g.codes || [], gdocs = g.documents || [], cells = g.cells || {};
    if (!codes.length || !gdocs.length) {
      gridBox.appendChild(emptyState("tag", "No code found yet", "No passage has a code that counts. The AI can read the passages with a candidate code, or try another codebook."));
      return;
    }
    const max = Math.max(1, ...Object.values(cells).flatMap((row) => Object.values(row)));
    const docHref = (d, code) => `#/doc/${encodeURIComponent(d.doc_id)}?tab=codes${framework !== (App.settings().profile_framework || "sdg") ? `&framework=${encodeURIComponent(framework)}` : ""}${code ? `&code=${encodeURIComponent(code)}` : ""}`;
    const table = h("table", { class: "map-table pf-grid" },
      h("caption", { class: "visually-hidden" }, `Documents by ${unit}: the number of passages`),
      h("thead", {}, h("tr", {}, h("th", { scope: "col", class: "map-hyp-head" }, "Document"),
        codes.map((c) => h("th", { scope: "col", class: "pf-code-head", title: `${cap(unit)} ${c.code}: ${c.description || ""} · ${plural(c.passages, "passage")} in ${plural(c.documents, "document")}` },
          h("span", { "aria-hidden": "true" }, c.code), h("span", { class: "visually-hidden" }, `${unit} ${c.code}: ${shortTitle(c.description, 60)}`))))),
      h("tbody", {}, gdocs.map((d) => {
        const row = cells[d.doc_id] || {};
        const href = docHref(d);
        return h("tr", { class: "row-link", onClick: (e) => { if (e.target.closest("a, td.pf-cell")) return; location.hash = href; } },
          h("th", { scope: "row", class: "map-hyp pf-doc" }, h("a", { href, title: d.title }, shortTitle(d.title, 90)), h("div", { class: "map-hyp-meta muted small" }, `${plural(d.passages, "passage")} with a code`)),
          codes.map((c) => heatCell(row[c.code] || 0, max, `${shortTitle(d.title, 50)}, ${unit} ${c.code}`, () => { location.hash = docHref(d, c.code); })));
      })));
    gridBox.appendChild(h("div", { class: "pf-grid-key muted small" },
      h("span", {}, g.provisional ? h("span", { class: "chip chip-weak" }, "provisional") : null, g.provisional ? " Includes codes found by keywords that the AI has not checked yet. " : ""),
      h("span", {}, "The darker the cell, the more passages. Hover over a column for its text; click a cell to see those passages in the document.")));
    gridBox.appendChild(h("p", { class: "muted small map-scroll-hint", style: { margin: "0 0 6px" } }, icon("arrow-right", { size: 12 }), ` The grid scrolls sideways: drag or swipe it to see every ${unit}.`));
    gridBox.appendChild(h("div", { class: "map-wrap", tabindex: "0", role: "region", "aria-label": `Documents by ${unit} (scrolls sideways)` }, table));
  }

  async function drawCalibration() {
    clear(calBox);
    if (!prof.pass1.done) return;
    let c;
    try { c = await api("GET", `${base}/profile/calibration?framework=${encodeURIComponent(framework)}`); } catch (_) { return; }
    if (!c || !c.total) return;
    calBox.appendChild(h("section", { class: "section calibration", "aria-label": "How often you agreed with the AI" }, calibrationBox(c)));
  }

  draw();
  keepUrl();
  const running = await runningJob(project, ["keywords", "label"]);
  if (running && running.kind === "keywords") { clear(statusBox); watchers.push(jobCard(jobBox, running.id, "Finding the codes by keywords and meaning", keywordLabel, keywordsEnded)); }
  else if (running && running.kind === "label" && ai) ai.follow(running.id);
  return () => watchers.forEach((w) => w.stop());
}
