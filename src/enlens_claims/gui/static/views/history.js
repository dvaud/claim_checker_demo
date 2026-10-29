// Results: every hypothesis checked in the project. Counts come from the API at the current strictness.
import { App, api, h, icon, replace, clear, showError, toast, fmt, statusBadge, pageHead, P, debounce, download, emptyState, watchJob, TERMINAL, STATUS_SHORT, strictness } from "../lib.js";
import { ProgressPanel } from "./progress.js";

const ORDER = ["supported", "partially_supported", "contested", "contradicted", "uncertain", "unsupported", "no_passages", "not_checked", "failed", "waiting"];
const STATUS_ICON = { supported: "circle-check", partially_supported: "circle-half", contested: "arrows-opposed", contradicted: "circle-x", uncertain: "help", unsupported: "circle-dashed", no_passages: "search-x", not_checked: "clock", failed: "alert-triangle", waiting: "inbox" };
const ONE_MODEL_NOTE = "Only one AI model is kept in memory at a time, so this takes a while.";

export async function renderHistory(view, params, query) {
  const project = App.project;
  let q = query.q || "", status = query.status || "", batch = query.batch || "";
  const threshold = App.settings().threshold ?? 0.6;
  const watchers = [];
  let rowsNow = [];

  const xlsx = h("button", { class: "btn btn-primary btn-sm", type: "button", title: "Three sheets: a summary, every excerpt read, and the evidence map", onClick: () => download(`/api/projects/${P(project)}/export.xlsx?threshold=${threshold}`).catch(showError) }, icon("download", { size: 14 }), "Download all for Excel (.xlsx)");
  const csv = h("button", { class: "btn btn-sm btn-ghost", type: "button", title: "Technical CSV: ids, raw judgement words, UTC times", onClick: () => download(`/api/projects/${P(project)}/export.csv?threshold=${threshold}`).catch(showError) }, icon("download", { size: 13 }), "CSV for programmers");
  const mapLink = h("a", { class: "btn btn-sm", href: "#/map" }, icon("layers", { size: 14 }), "Show as a map");
  view.appendChild(pageHead("Results", { sub: `Every hypothesis checked in project “${project}”, newest first. Open one to read the evidence.`, actions: [mapLink, xlsx, csv] }));

  const search = h("input", { class: "input", type: "search", placeholder: "Find a hypothesis…", value: q, "aria-label": "Find a hypothesis" });
  const chips = h("div", { class: "chips", role: "group", "aria-label": "Show only" });
  const batchBanner = h("div", { class: "batch-banner", hidden: !batch });
  const strictLine = h("p", { class: "muted small", style: { margin: "0" } }, icon("sliders", { size: 12 }), ` Counting judgements the AI was at least ${Math.round(threshold * 100)}% sure of (${strictness(threshold)}), and every judgement of your own. `, h("a", { href: "#/settings/basics" }, "Change in Settings"));
  const actionsBox = h("div", { class: "hist-actions", hidden: true });
  const jobBox = h("div", { class: "section", hidden: true, "aria-label": "Progress" });
  view.appendChild(h("div", { class: "filters" }, h("div", { class: "filters-top" }, h("div", { class: "search" }, icon("search", { size: 15 }), search)), chips, batchBanner, strictLine, actionsBox));
  view.appendChild(jobBox);
  const tableBox = h("div", { "aria-live": "polite", "aria-busy": "false" });
  view.appendChild(tableBox);

  // Actions on the set shown: read the new documents, ask the second model, see the map.
  function drawActions(rows) {
    clear(actionsBox);
    const withNew = rows.filter((x) => x.docs_added_since > 0);
    const st = App.settings();   // 0.8: on Claude the auditor gives the second opinion
    const auditor = ["claude_code", "anthropic"].includes(st.backend) && st.routing !== false;
    const secondSet = auditor ? (st.use_fable ? "fable" : "opus") : (st.second_model || "").trim();
    const main = auditor ? "" : (st.ollama_model || st.openai_model || "").trim();
    const shown = batch ? "the set shown" : (q || status) ? "the results shown" : "all results";
    const n = rows.length;
    mapLink.href = batch ? `#/map?batch=${encodeURIComponent(batch)}` : "#/map";
    const bits = [];
    if (withNew.length) {
      const btn = h("button", { class: "btn btn-sm btn-primary", type: "button" }, icon("book-open", { size: 13 }), `Read the new documents for ${withNew.length === n ? `all ${n}` : `${withNew.length} of these ${n}`}`);
      btn.addEventListener("click", () => runJob(btn, "read-new", `/api/projects/${P(project)}/read-new`, batch ? { batch } : (q || status) ? { hyp_ids: withNew.map((x) => x.hyp_id) } : {}, "Reading the new documents"));
      bits.push(h("div", { class: "hist-action" }, btn, h("span", { class: "muted small" }, `Documents were added since ${withNew.length === 1 ? "this check was" : "these checks were"} run. The AI reads only the new documents; the checks are not run again, so your reviews are kept.`)));
    }
    if (n) {
      const btn = h("button", { class: "btn btn-sm", type: "button", disabled: !secondSet || secondSet === main }, icon("cpu", { size: 13 }), `Ask a second AI model for ${shown}${batch || q || status ? ` (${n})` : ""}`);
      btn.addEventListener("click", () => runJob(btn, "second-opinion", `/api/projects/${P(project)}/second-opinion`, batch ? { batch } : { hyp_ids: rows.map((x) => x.hyp_id) }, "The second AI model is reading the excerpts"));
      bits.push(h("div", { class: "hist-action" }, btn, h("span", { class: "muted small" }, auditor ? `The auditor (${secondSet}) reads the excerpts already read; its judgements are shown beside the first ones and never change an answer. Excerpts it has read are skipped.` : secondSet && secondSet !== main ? `A second model reads the excerpts already read and its judgements are shown beside the main model's; they never change an answer. Excerpts it has read are skipped. ${ONE_MODEL_NOTE}` : ["No second AI model is chosen yet: ", h("a", { href: "#/settings/second" }, "choose one in Settings"), `. ${ONE_MODEL_NOTE}`])));
    }
    actionsBox.hidden = !bits.length;
    bits.forEach((b) => actionsBox.appendChild(b));
  }

  async function runJob(btn, kind, path, body, title) {
    btn.disabled = true;
    try {
      const r = await api("POST", path, body);
      followJob(r.job.id, title, kind);
    } catch (e) {
      if (e.status === 400 && kind === "second-opinion") toast(e.message, "warn", { action: { href: "#/settings/second", text: "Choose a second model in Settings" } }); else showError(e);
      btn.disabled = false;
    }
  }

  function followJob(jobId, title, kind) {
    const panel = new ProgressPanel({ title, steps: kind === "second-opinion" ? ["grade"] : null, batchWords: kind === "read-new" ? { doing: "reading for hypothesis", done: "hypotheses brought up to date" } : null });
    replace(jobBox, h("div", { class: "section-title" }, h("h2", {}, title), h("span", { class: "muted" }, "you can leave this page; it continues")), panel.el);
    jobBox.hidden = false;
    const w = watchJob(jobId, (job) => panel.update(job));
    watchers.push(w);
    w.promise.then(async (job) => {
      const st = jobBox.querySelector(".section-title h2"); if (st) st.textContent = job.state === "done" ? "Done" : job.state === "cancelled" ? "Stopped" : "Did not work";
      if (job.state === "done") {
        const r = job.result || {};
        if (job.kind === "read-new") {
          const hs = r.hypotheses || [];
          const n = r.passages || 0;
          toast(`The new documents were read for ${hs.length} ${hs.length === 1 ? "result" : "results"}: ${n} more ${n === 1 ? "excerpt" : "excerpts"} read. Reviews are kept.`, "ok", { ttl: 6000 });
        } else if (job.kind === "second-opinion") {
          toast(r.graded ? `The second AI model has read the excerpts of ${r.hypotheses || 0} ${r.hypotheses === 1 ? "result" : "results"}. Where it disagrees with the main model, the result is tagged below.` : "The second AI model had already read every excerpt of these results: nothing new to read.", "ok", { ttl: 6000 });
        }
      } else if (job.state === "error") showError({ message: job.error, kind: job.error_kind });
      await refresh();
    }).catch(showError);
  }

  const syncHash = () => {
    const qs = new URLSearchParams();
    if (q) qs.set("q", q); if (status) qs.set("status", status); if (batch) qs.set("batch", batch);
    const s = qs.toString();
    history.replaceState(null, "", "#/history" + (s ? "?" + s : ""));
  };

  async function refresh() {
    syncHash();
    tableBox.setAttribute("aria-busy", "true");
    const qs = new URLSearchParams({ threshold: String(threshold) });
    if (q) qs.set("q", q); if (status) qs.set("status", status); if (batch) qs.set("batch", batch);
    let r;
    try { r = await api("GET", `/api/projects/${P(project)}/hypotheses?${qs}`); } catch (e) { showError(e); return; }
    rowsNow = r.hypotheses || [];
    drawChips(r.counts || {});
    drawBatch(rowsNow);
    drawActions(rowsNow);
    drawTable(rowsNow, r.counts || {});
    tableBox.setAttribute("aria-busy", "false");
  }

  function drawChips(counts) {
    clear(chips);
    chips.hidden = !!batch;   // the counts cover the whole project, not one set
    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    const chip = (key, label, n) => h("button", { type: "button", class: "chip chip-btn", "aria-pressed": status === key ? "true" : "false", onClick: () => { status = status === key ? "" : key; refresh(); } },
      key ? icon(STATUS_ICON[key], { size: 12 }) : null, h("span", {}, label), h("span", { class: "count" }, String(n)));
    chips.appendChild(chip("", "All", total));
    for (const k of ORDER) if (counts[k] || status === k) chips.appendChild(chip(k, STATUS_SHORT[k] || k, counts[k] || 0));
  }

  function drawBatch(rows) {
    batchBanner.hidden = !batch;
    if (batch) replace(batchBanner, icon("list-checks", { size: 14 }), h("span", {}, `Showing the ${rows.length} ${rows.length === 1 ? "hypothesis" : "hypotheses"} of one set checked together.`), h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => { batch = ""; refresh(); } }, "Show all results"));
  }

  function drawTable(rows, counts) {
    clear(tableBox);
    if (!rows.length) {
      const any = Object.values(counts).some((n) => n);
      tableBox.appendChild(any ? emptyState("search-x", "Nothing matches", "Try other words, or show all results.", h("button", { class: "btn", type: "button", onClick: () => { q = ""; status = ""; batch = ""; search.value = ""; refresh(); } }, "Show all results"))
        : emptyState("history", "No results yet", "Check a hypothesis and its result appears here.", h("a", { class: "btn btn-primary", href: "#/check" }, "Check a hypothesis")));
      return;
    }
    const table = h("table", { class: "table hist-table table-responsive" },
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Hypothesis"), h("th", { scope: "col" }, "Answer"), h("th", { scope: "col" }, "Excerpts that count"), h("th", { scope: "col" }, "Checked"))),
      h("tbody", {}, rows.map((x) => {
        const href = `#/h/${encodeURIComponent(x.hyp_id)}`;
        return h("tr", { class: "row-link", onClick: (e) => { if (e.target.closest("a")) return; location.hash = href; } },
          h("td", { class: "hyp-cell" }, h("a", { href }, x.text || x.claim),
            h("div", { class: "hyp-meta" }, x.code ? h("span", { class: "it" }, icon("star", { size: 11 }), `${x.code_label || "code"} ${x.code}`) : null,
              x.parts > 1 ? h("span", { class: "it" }, icon("split", { size: 11 }), `checked in ${x.parts} parts`) : null,
              x.batch_id ? h("span", { class: "it" }, icon("list-checks", { size: 11 }), "part of a set") : null,
              x.to_review ? h("span", { class: "it to-review" }, icon("eye", { size: 11 }), `${x.to_review} to review`) : null,
              x.corrected ? h("span", { class: "it corrected" }, icon("note", { size: 11 }), `${x.corrected} changed by you`) : null,
              x.docs_added_since ? h("span", { class: "it tag-new-docs", title: `${x.docs_added_since} ${x.docs_added_since === 1 ? "document was" : "documents were"} added to the project after this check; open the result to have the AI read them` }, icon("upload", { size: 11 }), `${x.docs_added_since} ${x.docs_added_since === 1 ? "document" : "documents"} added since`) : null,
              x.disagreements ? h("span", { class: "it tag-disagree", title: "A second AI model judged these excerpts differently from the main model; read them yourself" }, icon("arrows-opposed", { size: 11 }), `models disagree on ${x.disagreements}`) : null,
              x.note ? h("span", { class: "it", title: x.note }, icon("note", { size: 11 }), "has notes") : null)),
          h("td", { "data-label": "Answer", class: "verdict-cell" }, statusBadge(x.status, { short: true }),
            x.status_any && x.status_any !== x.status ? h("div", { class: "muted small", style: { marginTop: "3px" } }, "If the uncertain judgements counted too: ", STATUS_SHORT[x.status_any] || x.status_any) : null),
          h("td", { "data-label": "Excerpts that count" }, evidenceCell(x)),
          h("td", { "data-label": "Checked", class: "small muted nowrap", title: fmt.date(x.created_at) }, fmt.dateShort(x.created_at)));
      })));
    tableBox.appendChild(h("div", { class: "table-wrap" }, table));
    tableBox.appendChild(h("p", { class: "muted small", style: { marginTop: "8px" } }, `${rows.length} ${rows.length === 1 ? "result" : "results"}`));
  }

  search.addEventListener("input", debounce(() => { q = search.value.trim(); refresh(); }, 250));
  await refresh();
  // a job started here earlier (or from the jobs list) and still running: follow it
  try {
    const titles = { "read-new": "Reading the new documents", "second-opinion": "The second AI model is reading the excerpts" };
    const jobs = (await api("GET", "/api/jobs")).jobs || [];
    const mine = query.job ? jobs.find((j) => j.id === query.job) : null;
    const running = mine && titles[mine.kind] ? mine : jobs.find((j) => j.project === project && titles[j.kind] && !TERMINAL.has(j.state));
    if (running) {
      if (TERMINAL.has(running.state)) { if (query.job) { const full = await api("GET", `/api/jobs/${P(running.id)}`); const panel = new ProgressPanel({ title: titles[full.kind], steps: full.kind === "second-opinion" ? ["grade"] : null }); replace(jobBox, h("div", { class: "section-title" }, h("h2", {}, full.state === "done" ? "Done" : "Stopped"), h("span", { class: "muted" }, titles[full.kind])), panel.el); panel.update(full); jobBox.hidden = false; } }
      else followJob(running.id, titles[running.kind], running.kind);
    }
  } catch (_) { /* ignore */ }
  return () => watchers.forEach((w) => w.stop());
}

function evidenceCell(x) {
  const n = (x.supports || 0) + (x.partly || 0) + (x.refutes || 0);
  const unc = x.uncounted || 0;
  if (!n && x.status === "waiting") return h("span", { class: "muted small" }, x.passages_read ? `${x.passages_read} chosen, not read yet` : "not read yet");
  if (!n) return h("span", { class: "muted small" }, unc ? `none; ${unc} too uncertain to count` : `none in ${x.passages_read || 0} read`);
  const c = (k, ic, cls, word) => k ? h("span", { class: `it ${cls}`, title: `${k} ${k === 1 ? "excerpt" : "excerpts"} ${word}` }, icon(ic, { size: 12 }), `${k} ${word}`) : null;
  return h("span", { class: "ev-counts ev-words" }, c(x.supports, "circle-check", "bc-sup", "support"), c(x.partly, "circle-half", "bc-part", "partly"), c(x.refutes, "circle-x", "bc-ref", "contradict"),
    unc ? h("span", { class: "muted small" }, `· ${unc} too uncertain`) : null);
}
