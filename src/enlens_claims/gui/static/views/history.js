// The answers: every hypothesis checked in the project, newest first, with the checks still running or waiting their
// turn at the top. 0.17.0: no page of its own any more (it was Results): the Hypotheses page shows it under the box
// where hypotheses are written. Counts come from the API at the current strictness.
import { App, api, h, icon, replace, clear, showError, failedLoad, toast, fmt, statusBadge, P, debounce, emptyState, watchJob, TERMINAL, STATUS_SHORT, strictness, auditorName, strongerMark, helpMark, onJobsChanged, button, link, input, workState , choice, searchField} from "../lib.js";
import { ProgressPanel } from "./progress.js";
import { STATUS_ICON } from "../icons.js";

const ORDER = ["supported", "partially_supported", "contested", "contradicted", "uncertain", "unsupported", "no_passages", "not_checked", "failed", "waiting"];
const ONE_MODEL_NOTE = "Only one AI model is kept in memory at a time, so this takes a while.";
const CHECK_KINDS = ["check", "batch"];   // the jobs shown as rows at the top: a check, and a list being checked
const LOOK_AGAIN = 3000;                  // how often the running checks are looked at while there are any (ms)
const UNFINISHED = new Set(["not_checked", "waiting"]);   // a check being made has its answer row from the start
const norm = (t) => String(t || "").split(/\s+/).filter(Boolean).join(" ");

// Draws the answers into `box` and returns { refresh, showBatch(id), stop }.
// `query`: the page's own (q, status, batch, job). `opts.following()`: the id of the check the page follows above the
// answers (its progress is shown there, so it is not a row here); `opts.onBatch(batch)`: the set shown changed (the
// page's Evidence map tab keeps it); `opts.write()`: puts the cursor where a hypothesis is written.
export async function answersList(box, query, opts = {}) {
  const project = App.project;
  let q = query.q || "", status = query.status || "", batch = query.batch || "";
  const threshold = App.settings().threshold ?? 0.6;
  const watchers = [];
  let rowsNow = [], countsNow = {}, running = [], drawn = false, stopped = false, timer = null;

  const searchBox = searchField({ placeholder: "Find a hypothesis…", value: q, "aria-label": "Find a hypothesis" });
  const search = searchBox.input;
  const chips = h("div", { class: "chips" });
  const batchBanner = h("div", { class: "batch-banner", hidden: !batch });
  const strictLine = h("p", { class: "muted small hist-strict-note" }, icon("sliders", { size: 12 }), ` Counting judgements the AI was at least ${Math.round(threshold * 100)}% sure of (${strictness(threshold)}), and every judgement of your own. `, link({ href: "#/settings/basics" }, "Change in Settings"));
  const actionsBox = h("div", { class: "hist-actions", hidden: true });
  const jobBox = h("div", { class: "section", hidden: true, "aria-label": "Progress" });
  const tableBox = h("div", { "aria-live": "polite", "aria-busy": "false" });
  replace(box,
    h("div", { class: "section-title" }, h("h2", { id: "answers-title" }, "Answers"), h("span", { class: "muted" }, "newest first")),
    h("div", { class: "filters" }, h("div", { class: "filters-top" }, searchBox), chips, batchBanner, strictLine, actionsBox),
    jobBox, tableBox);

  // Actions on the set shown: read the new documents, ask the second model.
  function drawActions(rows) {
    clear(actionsBox);
    const withNew = rows.filter((x) => x.docs_added_since > 0);
    const st = App.settings();   // 0.8: on Claude the auditor gives the second opinion
    const auditor = auditorName(st);
    const secondSet = auditor || (st.second_model || "").trim();
    const main = auditor ? "" : (st.ollama_model || st.openai_model || "").trim();
    const shown = batch ? "the set shown" : (q || status) ? "the answers shown" : "all answers";
    const n = rows.length;
    const bits = [];
    if (withNew.length) {
      const btn = button({ kind: "main", sm: true }, icon("book-open", { size: 13 }), `Read the new documents for ${withNew.length === n ? `all ${n}` : `${withNew.length} of these ${n}`}`);
      btn.addEventListener("click", () => runJob(btn, "read-new", `/api/projects/${P(project)}/read-new`, batch ? { batch } : (q || status) ? { hyp_ids: withNew.map((x) => x.hyp_id) } : {}, "Reading the new documents"));
      bits.push(h("div", { class: "hist-action" }, btn, h("span", { class: "muted small" }, `Documents were added since ${withNew.length === 1 ? "this check was" : "these checks were"} run. The AI reads only the new documents; the checks are not run again, so your reviews are kept.`)));
    }
    if (n) {
      const btn = button({ sm: true, disabled: !secondSet || secondSet === main }, icon("arrows-opposed", { size: 13 }), `Get a second opinion for ${shown}${batch || q || status ? ` (${n})` : ""}`);
      btn.addEventListener("click", () => runJob(btn, "second-opinion", `/api/projects/${P(project)}/second-opinion`, batch ? { batch } : { hyp_ids: rows.map((x) => x.hyp_id) }, "A second opinion: another model reads the excerpts"));
      // 0.13.3: one short line beside the button; the whole explanation is in its help mark
      const ready = secondSet && secondSet !== main;
      const why = `Another model (${secondSet || "the model for second opinions"}${auditor ? ", the auditor" : ""}) reads the excerpts already read, for comparison only: its judgements are shown beside the first AI's and never change an answer. Excerpts it has read are skipped.${auditor ? " A stronger model, which does replace the judgements, is asked for on each result." : ` ${ONE_MODEL_NOTE}`}`;
      bits.push(h("div", { class: "hist-action" }, btn, h("span", { class: "muted small" },
        ready ? ["For comparison only: the answers do not change.", helpMark("About a second opinion", why)]
          : ["No model for second opinions is chosen yet: ", h("a", { href: "#/settings/second" }, "choose one in Settings"), "."])));
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
      if (e.status === 400 && kind === "second-opinion") toast(e.message, "warn", { action: { href: "#/settings/second", text: "Choose a model for second opinions in Settings" } }); else showError(e);
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
          toast(`The new documents were read for ${hs.length} ${hs.length === 1 ? "answer" : "answers"}: ${n} more ${n === 1 ? "excerpt" : "excerpts"} read. Reviews are kept.`, "ok", { ttl: 6000 });
        } else if (job.kind === "second-opinion") {
          toast(r.graded ? `The second opinion is in for ${r.hypotheses || 0} ${r.hypotheses === 1 ? "answer" : "answers"}. Where it differs from the first AI, the answer is tagged below; the answers are unchanged.` : "Every excerpt of these answers already has a second opinion: nothing new to read.", "ok", { ttl: 6000 });
        } else if (job.kind === "more" && r.hyp_id) {
          const n = r.passages || 0;
          toast(`${n} more ${n === 1 ? "excerpt was" : "excerpts were"} read for this answer.`, "ok", { ttl: 6000, action: { href: `#/h/${encodeURIComponent(r.hyp_id)}`, text: "Open the answer" } });
        }
      } else if (job.state === "error") showError({ message: job.error, kind: job.error_kind });
      await refresh();
    }).catch(showError);
  }

  // 0.17.0: the page is Hypotheses; the filters are kept in its address (a reload or a link shows the same answers)
  const syncHash = () => {
    const qs = new URLSearchParams();
    if (q) qs.set("q", q); if (status) qs.set("status", status); if (batch) qs.set("batch", batch);
    const s = qs.toString();
    history.replaceState(null, "", "#/hypotheses" + (s ? "?" + s : ""));
  };

  // The checks of this project still running or waiting their turn (the one the page follows above too: its answer
  // row is left out while its progress is shown there).
  async function runningChecks() {
    try {
      const jobs = (await api("GET", "/api/jobs")).jobs || [];
      return jobs.filter((j) => j.project === project && CHECK_KINDS.includes(j.kind) && !TERMINAL.has(j.state));
    } catch (_) { return running; }
  }

  async function refresh() {
    syncHash();
    if (opts.onBatch) opts.onBatch(batch);
    tableBox.setAttribute("aria-busy", "true");
    const qs = new URLSearchParams({ threshold: String(threshold) });
    if (q) qs.set("q", q); if (status) qs.set("status", status); if (batch) qs.set("batch", batch);
    let r;
    try { [r, running] = await Promise.all([api("GET", `/api/projects/${P(project)}/hypotheses?${qs}`), runningChecks()]); } catch (e) { failedLoad(tableBox, e); tableBox.setAttribute("aria-busy", "false"); return; }
    if (stopped) return;
    rowsNow = r.hypotheses || [];
    countsNow = r.counts || {};
    drawChips(countsNow);
    drawBatch(rowsNow);
    drawActions(rowsNow);
    drawTable();
    tableBox.setAttribute("aria-busy", "false");
    lookLater();
  }

  // While checks run, look again now and then: a row that is gone has become an answer.
  async function lookAtRunning() {
    if (stopped || !drawn) return;
    const before = running.map((j) => `${j.id}:${j.state}:${j.on_hold}`).join(",");
    const now = await runningChecks();
    if (stopped) return;
    const ended = running.some((j) => !now.find((x) => x.id === j.id));
    running = now;
    if (ended) { await refresh(); return; }
    if (now.map((j) => `${j.id}:${j.state}:${j.on_hold}`).join(",") !== before) drawTable();
    lookLater();
  }
  function lookLater() {
    if (timer) clearTimeout(timer);
    timer = running.length && !stopped ? setTimeout(lookAtRunning, LOOK_AGAIN) : null;
  }
  const offJobs = onJobsChanged(() => { lookAtRunning(); });

  function drawChips(counts) {
    clear(chips);
    chips.hidden = !!batch;   // the counts cover the whole project, not one set
    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    // a filter of the list: a choice (docs/DESIGN.md, Choices), each answer with its icon and the rows it would show;
    // the chosen one pressed again shows all
    const options = [["", "All", total], ...ORDER.filter((k) => counts[k] || status === k)
      .map((k) => [k, [icon(STATUS_ICON[k], { size: 12 }), h("span", {}, STATUS_SHORT[k] || k)], counts[k] || 0])];
    chips.appendChild(choice({ label: "Show the answers that are", filter: true, value: status, options,
      onPick: (k) => { status = status === k ? "" : k; refresh(); } }));
  }

  function drawBatch(rows) {
    batchBanner.hidden = !batch;
    if (batch) replace(batchBanner, icon("list-checks", { size: 14 }), h("span", {}, `Showing the ${rows.length} ${rows.length === 1 ? "hypothesis" : "hypotheses"} of one set checked together.`), button({ kind: "quiet", sm: true, onClick: () => { batch = ""; refresh(); } }, "Show all answers"));
  }

  // A check still running, or waiting for the one before it: a row that opens its progress.
  function jobRow(j) {
    const href = `#/hypotheses?job=${encodeURIComponent(j.id)}`;
    const waiting = j.state === "queued" || j.on_hold;
    const many = j.kind === "batch";
    const badge = waiting
      ? workState("waiting", "Waiting its turn")
      : workState("running", "Checking…");
    if (waiting) badge.title = j.on_hold ? "Its tasks wait in the queue for Claude Code." : "Another check is using the AI: this one starts when it is done.";
    return h("tr", { class: "row-link hyp-job-row", onClick: (e) => { if (e.target.closest("a")) return; location.hash = href; } },
      h("td", { class: "hyp-cell" }, link({ kind: "title", serif: true, href }, many ? `A list of ${j.title}` : j.title),
        many ? h("div", { class: "hyp-meta" }, h("span", { class: "it" }, icon("list-checks", { size: 11 }), "checked one after the other")) : null),
      h("td", { "data-label": "Answer", class: "verdict-cell" }, badge),
      h("td", { "data-label": "Excerpts that count" }, h("span", { class: "muted small" }, "not read yet")),
      h("td", { "data-label": "Checked", class: "small muted nowrap" }, waiting ? "" : `for ${fmt.secs(j.seconds)}`));
  }

  function drawTable() {
    drawn = true;
    clear(tableBox);
    // a check being made already has its answer row ("Not finished yet", or waiting for Claude Code): while it runs,
    // its row up here (or its progress above) stands for it, so it is not shown twice. A job's title is the start of
    // its hypothesis.
    const checking = running.filter((j) => j.kind === "check").map((j) => norm(j.title)).filter(Boolean);
    const rows = rowsNow.filter((x) => !(UNFINISHED.has(x.status) && checking.some((t) => norm(x.text || x.claim).startsWith(t))));
    const skip = opts.following ? opts.following() : null;
    const jobs = batch || status || q ? [] : running.filter((j) => j.id !== skip);   // the rows of running checks belong to the whole list
    if (!rows.length && !jobs.length) {
      const any = Object.values(countsNow).some((n) => n);
      tableBox.appendChild(any ? emptyState("search-x", "Nothing matches", "Try other words, or show all answers.", button({ onClick: () => { q = ""; status = ""; batch = ""; search.value = ""; refresh(); } }, "Show all answers"))
        : emptyState("history", "No answers yet", "Write a hypothesis above and check it: its answer appears here, with the quotes.", opts.write ? button({ onClick: () => opts.write() }, icon("flask", { size: 14 }), "Write a hypothesis") : null));
      return;
    }
    const table = h("table", { class: "table hist-table table-responsive" },
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Hypothesis"), h("th", { scope: "col" }, "Answer"), h("th", { scope: "col" }, "Excerpts that count"), h("th", { scope: "col" }, "Checked"))),
      h("tbody", {}, jobs.map(jobRow), rows.map((x) => {
        const href = `#/h/${encodeURIComponent(x.hyp_id)}`;
        return h("tr", { class: "row-link", onClick: (e) => { if (e.target.closest("a")) return; location.hash = href; } },
          h("td", { class: "hyp-cell" }, link({ kind: "title", serif: true, href }, x.text || x.claim),
            h("div", { class: "hyp-meta" }, x.code ? h("span", { class: "it" }, icon("star", { size: 11 }), `${x.code_label || "code"} ${x.code}`) : null,
              x.parts > 1 ? h("span", { class: "it" }, icon("split", { size: 11 }), `checked in ${x.parts} parts`) : null,
              x.batch_id ? h("span", { class: "it" }, icon("list-checks", { size: 11 }), "part of a set") : null,
              x.clash ? h("span", { class: "it tag-clash", title: "You both changed this check: this version came in beside the other one, so nothing was lost. Open it to compare." }, icon("copy", { size: 11 }), `sync clash · ${x.clash.name === "you" ? "your" : `${x.clash.name}’s`} version`) : null,
              x.to_review ? h("span", { class: "it to-review" }, icon("eye", { size: 11 }), `${x.to_review} to review`) : null,
              x.corrected ? h("span", { class: "it corrected" }, icon("note", { size: 11 }), `${x.corrected} changed by you`) : null,
              x.docs_added_since ? h("span", { class: "it tag-new-docs", title: `${x.docs_added_since} ${x.docs_added_since === 1 ? "document was" : "documents were"} added to the project after this check; open the answer to have the AI read them` }, icon("upload", { size: 11 }), `${x.docs_added_since} ${x.docs_added_since === 1 ? "document" : "documents"} added since`) : null,
              x.disagreements ? h("span", { class: "it tag-disagree", title: "A second opinion (another AI model, for comparison only) judged these excerpts differently from the first AI. The answer is unchanged: open it and read them yourself." }, icon("arrows-opposed", { size: 11 }), `second opinion differs on ${x.disagreements}`) : null,
              x.note ? h("span", { class: "it", title: x.note }, icon("note", { size: 11 }), "has notes") : null)),
          h("td", { "data-label": "Answer", class: "verdict-cell" }, statusBadge(x.status, { short: true, text: x.status_text || undefined }), " ", strongerMark(x.status_before_stronger, {}, { compact: true, plain: true }),
            x.status_any && x.status_any !== x.status ? h("div", { class: "muted small hist-any-line" }, "If the uncertain judgements counted too: ", STATUS_SHORT[x.status_any] || x.status_any) : null),
          h("td", { "data-label": "Excerpts that count" }, evidenceCell(x)),
          h("td", { "data-label": "Checked", class: "small muted nowrap", title: fmt.date(x.created_at) }, fmt.dateShort(x.created_at)));
      })));
    tableBox.appendChild(h("div", { class: "table-wrap" }, table));
    tableBox.appendChild(h("p", { class: "muted small hist-count-line" }, `${rows.length} ${rows.length === 1 ? "answer" : "answers"}${jobs.length ? `; ${jobs.length} still being checked` : ""}`));
  }

  search.addEventListener("input", debounce(() => { q = search.value.trim(); refresh(); }, 250));
  await refresh();
  // a job started here earlier (or from the jobs list) and still running: follow it. Looking for more evidence is
  // started on a result page and followed there; here only when the jobs list sends it (?job=)
  try {
    const titles = { "read-new": "Reading the new documents", "second-opinion": "A second opinion: another model reads the excerpts", more: "Looking for more evidence" };
    const jobs = (await api("GET", "/api/jobs")).jobs || [];
    const mine = query.job ? jobs.find((j) => j.id === query.job) : null;
    const runningJob = mine && titles[mine.kind] ? mine : jobs.find((j) => j.project === project && titles[j.kind] && j.kind !== "more" && !TERMINAL.has(j.state));
    if (runningJob) {
      if (TERMINAL.has(runningJob.state)) { if (query.job) { const full = await api("GET", `/api/jobs/${P(runningJob.id)}`); const panel = new ProgressPanel({ title: titles[full.kind], steps: full.kind === "second-opinion" ? ["grade"] : null }); replace(jobBox, h("div", { class: "section-title" }, h("h2", {}, full.state === "done" ? "Done" : "Stopped"), h("span", { class: "muted" }, titles[full.kind])), panel.el); panel.update(full); jobBox.hidden = false; } }
      else followJob(runningJob.id, titles[runningJob.kind], runningJob.kind);
    }
  } catch (_) { /* ignore */ }

  return {
    refresh,
    // the answers of one list checked together (the summary of a list just checked links here)
    showBatch(id) { batch = id || ""; q = ""; status = ""; search.value = ""; return refresh(); },
    stop() { stopped = true; if (timer) clearTimeout(timer); offJobs(); watchers.forEach((w) => w.stop()); },
  };
}

function evidenceCell(x) {
  const n = (x.supports || 0) + (x.partly || 0) + (x.refutes || 0);
  const unc = x.uncounted || 0;
  if (!n && x.status === "waiting") return h("span", { class: "muted small" }, x.passages_read ? `${x.passages_read} chosen, not read yet` : "not read yet");
  if (!n) return h("span", { class: "muted small" }, unc ? `none; ${unc} too uncertain to count` : `none in ${x.passages_read || 0} read`);
  // counts of excerpts, in words: a judgement's colour and circle icon belong to its pill (docs/DESIGN.md 3.1)
  const c = (k, word) => k ? h("span", { title: `${k} ${k === 1 ? "excerpt" : "excerpts"} ${word}` }, `${k} ${word}`) : null;
  return h("span", { class: "ev-counts" }, c(x.supports, "support"), c(x.partly, "partly"), c(x.refutes, "contradict"),
    unc ? h("span", { class: "muted" }, `${unc} too uncertain`) : null);
}
