// The live progress panel of a check (also used for batches and "read more"): updated in place from the job's
// progress every poll, so running spinners do not restart and the page does not flicker.
import { App, h, icon, replace, clear, fmt, cancelJob, toast, showError, queueNotice } from "../lib.js";

const STEP_ICON = { pending: "circle", running: "loader", done: "circle-check" };
const plainPhase = (phase) => ({ waiting: "The AI is getting ready and reading", thinking: "The AI is thinking it over", writing: "The AI is writing down its judgement", done: "The AI has finished" }[phase] || "The AI is working");

export class ProgressPanel {
  // `steps`: the step keys to show (a "look before checking" job only has the "terms" step; the others stay pending)
  // `batchWords`: how the position in a set is worded ({doing: "checking hypothesis", done: "hypotheses checked"})
  constructor({ onStop, title, steps, batchWords } = {}) {
    this.onStop = onStop;
    this.steps = steps ? new Set(steps) : null;
    this.batchWords = batchWords || { doing: "checking hypothesis", done: "hypotheses checked" };
    this.rows = new Map();     // key -> row element
    this.partEls = new Map();  // part number -> block
    this.el = h("div", { class: "progress progress-running", "aria-label": title || "Progress" });
    this.msg = h("div", { class: "msg" }, "Starting…");
    this.live = h("div", { class: "visually-hidden", "aria-live": "polite", "aria-atomic": "true" });
    this.elapsed = h("span", { class: "elapsed" }, "0 s");
    this.stopBtn = h("button", { class: "btn btn-sm btn-outline-danger", type: "button", onClick: () => this.stop() }, icon("stop", { size: 13 }), "Stop");
    this.head = h("div", { class: "progress-head" }, h("span", { class: "running-dot", "aria-hidden": "true" }), this.msg, this.elapsed, this.stopBtn);
    this.batchBox = h("div", { class: "batch-box", hidden: true });
    this.decompBox = h("div", { class: "decomp-box", hidden: true });
    this.partsBox = h("div", { class: "parts-box" });
    this.modelBox = h("div", { class: "model-line", hidden: true });
    this.expect = h("p", { class: "muted small expect" }, App.settings().backend === "claude_code"
      ? "Claude Code reads it when you type the command above in it. You can move around the app, or close it: the check waits in the queue, and its answer appears under Results."
      : "An AI model running on your own computer can take a few minutes. You can move around the app meanwhile; the check keeps running.");
    this.techOpen = false;
    this.body = h("div", { class: "progress-body" }, this.batchBox, this.decompBox, this.partsBox, this.modelBox, this.expect);
    this.el.append(this.head, this.body, this.live);
    this.jobId = null;
    this.batchIndex = null;
    this.lastLive = "";
    this.liveAt = 0;
  }

  async stop() {
    if (!this.jobId) return;
    this.stopBtn.disabled = true;
    replace(this.stopBtn, icon("loader", { size: 13 }), "Stopping…");
    try { await cancelJob(this.jobId); } catch (e) { showError(e); this.stopBtn.disabled = false; replace(this.stopBtn, icon("stop", { size: 13 }), "Stop"); }
    if (this.onStop) this.onStop();
  }

  // Draw the job (state + progress).
  update(job) {
    this.jobId = job.id;
    const p = job.progress || {};
    const running = job.state === "queued" || job.state === "running";
    this.el.classList.toggle("progress-running", running);
    this.el.classList.toggle("progress-done", job.state === "done");
    this.el.classList.toggle("progress-error", job.state === "error" || job.state === "cancelled");
    this.stopBtn.hidden = !running;
    const dot = this.head.querySelector(".running-dot");
    if (dot) dot.hidden = !running;

    let message = p.message || (job.state === "queued" ? "Waiting for the AI (another task is using it)" : "Starting");
    if (job.state === "done") message = "Done";
    else if (job.state === "error") message = "Stopped because something went wrong";
    else if (job.state === "cancelled") message = "Stopped";
    this.expect.hidden = !running;
    this.msg.textContent = message;
    const secs = p.elapsed !== undefined ? p.elapsed : job.seconds;
    this.elapsed.textContent = fmt.secs(secs || 0);

    // a batch moved on to its next hypothesis: the steps start over
    if (p.batch && p.batch.index !== this.batchIndex) {
      this.batchIndex = p.batch.index;
      clear(this.partsBox); this.partEls.clear(); this.rows.clear();
    }
    // batch position
    if (p.batch && p.batch.total) {
      this.batchBox.hidden = false;
      const finished = !running;
      const doneCount = finished ? p.batch.index : p.batch.index - 1;
      const pct = Math.round((doneCount / p.batch.total) * 100);
      replace(this.batchBox,
        h("div", { class: "row", style: { justifyContent: "space-between" } }, h("strong", {}, finished ? `${doneCount} of ${p.batch.total} ${this.batchWords.done}` : `${doneCount} of ${p.batch.total} done · ${this.batchWords.doing} ${p.batch.index}`), h("span", { class: "muted small" }, `${pct}%`)),
        h("div", { class: "progress-bar", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": p.batch.total, "aria-valuenow": doneCount }, h("span", { style: { width: `${Math.max(2, pct)}%` } })),
        h("p", { class: "batch-current" }, p.batch.text || ""));
    } else this.batchBox.hidden = true;

    // decomposition
    if (p.decompose) {
      this.decompBox.hidden = false;
      const d = p.decompose;
      const row = this.row("decompose", d.label, d.state, d.detail, d.seconds);
      const list = h("ol", { class: "decomp-parts" }, (d.parts || []).map((t) => h("li", {}, t)));
      replace(this.decompBox, row, d.parts && d.parts.length ? list : null);
    } else this.decompBox.hidden = true;

    // parts and their steps
    const parts = p.parts || [];
    const seen = new Set();
    for (const part of parts) {
      seen.add(part.part);
      let block = this.partEls.get(part.part);
      if (block && block.dataset.text !== (part.text || "")) {
        const t = block.querySelector(".part-title");
        if (t) replace(t, h("span", { class: "pn" }, part.part ? `Part ${part.part}` : "Hypothesis"), part.text || "");
        block.dataset.text = part.text || "";
      }
      if (!block) {
        block = h("div", { class: "part-block" });
        block.dataset.text = part.text || "";
        if (parts.length > 1 || part.part > 0) {
          block.appendChild(h("p", { class: "part-title" }, h("span", { class: "pn" }, part.part ? `Part ${part.part}` : "Hypothesis"), part.text || ""));
        }
        block.appendChild(h("ul", { class: "step-list" }));
        this.partEls.set(part.part, block);
        this.partsBox.appendChild(block);
      }
      const ul = block.querySelector(".step-list");
      for (const s of part.steps || []) {
        if (this.steps && !this.steps.has(s.key)) continue;
        const key = `${part.part}:${s.key}`;
        let row = this.rows.get(key);
        if (!row) { row = this.row(key, s.label, s.state, s.detail, s.seconds); ul.appendChild(row); }
        else this.setRow(row, s.state, s.detail, s.seconds);
      }
    }

    // model activity: one plain sentence; tokens, speed and the raw text behind "technical details"
    const m = p.model;
    if (m && (running || m.phase === "done")) {
      this.modelBox.hidden = false;
      const phaseIcon = { waiting: "clock", thinking: "sparkles", writing: "type", done: "circle-check", queue: "inbox" }[m.phase] || "cpu";
      const plain = m.plain || plainPhase(m.phase);
      const tech = h("details", { class: "fold tech", open: this.techOpen }, h("summary", {}, "Technical details"),
        h("div", { class: "tech-body" }, h("div", { class: "mono small" }, m.line || ""),
          m.tail && m.phase !== "done" ? h("div", { class: "model-tail", "aria-hidden": "true" }, h("span", {}, m.tail)) : null));
      tech.addEventListener("toggle", () => { this.techOpen = tech.open; });
      if (m.phase === "queue") replace(this.modelBox, queueNotice({ ...(m.queue || {}), text: plain }));
      else replace(this.modelBox,
        h("div", { class: "ml-head" }, icon(phaseIcon, { size: 14 }), h("span", {}, running && (m.seconds || 0) >= 1 ? `${plain} · ${fmt.secs(m.seconds)}` : plain)),
        tech);
    } else this.modelBox.hidden = true;

    // errors
    if (job.state === "error") {
      let err = this.body.querySelector(".progress-err");
      if (!err) { err = h("div", { class: "notice notice-error progress-err", style: { marginTop: "10px" } }); this.body.appendChild(err); }
      replace(err, icon("alert-circle"), h("div", {},
        h("p", {}, job.error_kind === "backend" ? "The AI model stopped answering, so the check could not finish." : job.error_kind === "internal" ? "Something went wrong inside the app." : (job.error || "The check could not finish.")),
        job.error_kind === "backend" || job.error_kind === "internal" ? h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("div", { class: "mono small" }, job.error || "")) : null,
        job.error_kind === "backend" ? h("a", { href: "#/settings" }, "Check the AI model in Settings") : null));
    }

    // screen readers: announce the message at most every 4 s, and state changes at once
    const announce = `${message}${running ? "" : "."}`;
    const now = Date.now();
    if (announce !== this.lastLive && (!running || now - this.liveAt > 4000)) {
      this.live.textContent = announce + (running ? ` (${fmt.secs(secs || 0)})` : "");
      this.lastLive = announce;
      this.liveAt = now;
    }
  }

  row(key, label, state, detail, seconds) {
    const li = h("li", { class: `step step-${state}` },
      h("span", { class: "st-icon" }, icon(STEP_ICON[state] || "circle", { size: 16 })),
      h("span", {}, h("span", { class: "st-label" }, label), h("span", { class: "st-detail" }, detail || "")),
      h("span", { class: "st-time" }, seconds !== null && seconds !== undefined ? fmt.secs(seconds) : ""));
    li.dataset.state = state;
    this.rows.set(key, li);
    return li;
  }

  setRow(li, state, detail, seconds) {
    if (li.dataset.state !== state) {
      li.className = `step step-${state}`;
      li.dataset.state = state;
      replace(li.querySelector(".st-icon"), icon(STEP_ICON[state] || "circle", { size: 16 }));
    }
    const d = li.querySelector(".st-detail");
    if (d.textContent !== (detail || "")) d.textContent = detail || "";
    const t = li.querySelector(".st-time");
    const txt = seconds !== null && seconds !== undefined ? fmt.secs(seconds) : "";
    if (t.textContent !== txt) t.textContent = txt;
  }

  // One line with the time each step took (for the result page).
  static summary(progress) {
    if (!progress) return "";
    const bits = [];
    if (progress.decompose && progress.decompose.state === "done") bits.push(`splitting into parts ${fmt.secs(progress.decompose.seconds)}`);
    const totals = {};
    for (const part of progress.parts || []) for (const s of part.steps || []) if (s.state === "done" && s.seconds !== null) totals[s.label] = (totals[s.label] || 0) + s.seconds;
    for (const [label, secs] of Object.entries(totals)) bits.push(`${label.toLowerCase()} ${fmt.secs(secs)}`);
    return bits.join(" · ");
  }
}

// One line for a short job inside a card (reading one excerpt again, reading the new documents): what the AI is
// doing, the time, and a Stop button. `update(job)` redraws it from the job.
export class MiniJob {
  constructor({ title, onStop } = {}) {
    this.title = title || "Working";
    this.msg = h("span", { class: "mini-msg" }, this.title, "…");
    this.time = h("span", { class: "mini-time" }, "");
    this.stopBtn = h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: async () => {
      if (!this.jobId) return;
      this.stopBtn.disabled = true;
      try { await cancelJob(this.jobId); } catch (e) { showError(e); this.stopBtn.disabled = false; }
      if (onStop) onStop();
    } }, icon("stop", { size: 12 }), "Stop");
    this.el = h("div", { class: "mini-job", role: "status" }, h("span", { class: "running-dot", "aria-hidden": "true" }), this.msg, this.time, this.stopBtn);
    this.jobId = null;
  }
  update(job) {
    this.jobId = job.id;
    const p = job.progress || {};
    const running = job.state === "queued" || job.state === "running";
    const m = p.model;
    let text = `${this.title}…`;
    if (job.state === "queued") text = `${this.title}: waiting for the AI (another task is using it)`;
    else if (running && m && m.phase === "queue") text = `${this.title}: ${m.queue && m.queue.paused ? "paused" : "waiting for Claude Code"} (type ${(m.queue && m.queue.command) || "/enlens-run"} in Claude Code)`;
    else if (running && p.queue) text = `${this.title}: waiting for Claude Code (type ${p.queue.command || "/enlens-run"} in Claude Code)`;
    else if (running && m && m.phase && m.phase !== "done") text = `${this.title}: ${(m.plain || plainPhase(m.phase)).replace(/^The AI/, "the AI")}`;
    else if (running && p.message) text = `${this.title}: ${p.message}`;
    if (job.state === "done") text = "Done.";
    else if (job.state === "error") text = "Stopped because something went wrong.";
    else if (job.state === "cancelled") text = "Stopped.";
    this.msg.textContent = text;
    this.time.textContent = running ? fmt.secs(p.elapsed !== undefined ? p.elapsed : job.seconds || 0) : "";
    this.stopBtn.hidden = !running;
    this.el.classList.toggle("mini-done", !running);
    const dot = this.el.querySelector(".running-dot"); if (dot) dot.hidden = !running;
  }
}

// A simple bar for ingest / index jobs.
export function simpleProgress(job, labelFn) {
  const p = job.progress || {};
  const total = p.total || 0, done = p.done || 0;
  const pct = total ? Math.round((done / total) * 100) : 0;
  const running = job.state === "queued" || job.state === "running";
  const label = labelFn ? labelFn(p, job) : (p.file ? `${done} of ${total} · ${p.file}` : total ? `${done} of ${total}` : "Starting…");
  return h("div", { class: "stack", style: { gap: "6px" } },
    running && p.queue ? queueNotice(p.queue) : null,
    h("div", { class: "row", style: { justifyContent: "space-between" } }, h("span", { class: "it" }, running ? h("span", { class: "running-dot", "aria-hidden": "true" }) : null, h("strong", {}, label)), h("span", { class: "muted small" }, fmt.secs(job.seconds))),
    h("div", { class: "progress-bar " + (running && !total ? "indeterminate" : ""), role: "progressbar", "aria-valuemin": 0, "aria-valuemax": total || 100, "aria-valuenow": total ? done : null, "aria-label": label },
      h("span", { style: { width: `${Math.max(2, pct)}%` } })));
}

export { toast };
