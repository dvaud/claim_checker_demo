// 0.17.0: "Work waiting for Claude Code", a section of Settings › AI (#/settings/queue). What waits for Claude Code in
// this project, kind by kind: do first, hold or go on, remove; Start Claude Code with its speed and helpers; or answer
// it with the AI model of Settings. (Until 0.16.1 this was the queue panel at the foot of the sidebar; the sidebar now
// shows only the work's essentials, in its status area, and links here.)
import { App, api, h, icon, replace, toast, showError, confirmDialog, P, watchJob, startClaude, button, card, tag } from "../lib.js";

export function queueSection() {
  const body = h("div", { class: "queue-section", "aria-live": "polite" });
  const section = card({ class: "settings-section", id: "s-queue", "aria-labelledby": "s-queue-h" },
    h("h2", { id: "s-queue-h", tabindex: "-1" }, "Work waiting for Claude Code"),
    h("p", { class: "lead" }, "What the AI buttons of this project prepared for Claude Code, kind by kind. Claude Code answers it on your Claude plan; you choose what comes first, hold a kind, or take it out."),
    body);
  let timer = null;
  let defers = 0;
  async function draw() {
    clearTimeout(timer);
    if (!section.isConnected && body.dataset.drawn) return;   // the page moved on
    // not while a list of "Choose the helpers for this run" is open (redrawing would close it), for half a minute at most
    const el = document.activeElement;
    if (body.contains(el) && el.matches(".sc-helpers select") && defers < 6) { defers += 1; timer = setTimeout(draw, 5000); return; }
    defers = 0;
    body.dataset.drawn = "1";
    if (!App.project) { replace(body, h("p", { class: "muted small" }, "Open a project first.")); return; }
    let q;
    try { q = await api("GET", `/api/projects/${P(App.project)}/queue`); } catch (e) { replace(body, h("p", { class: "muted small" }, e.message)); return; }
    const s = App.settings();
    const act = async (kind, action) => {
      try { await api("POST", `/api/projects/${P(App.project)}/queue/order`, { kind, action }); draw(); } catch (e) { showError(e); }
    };
    const remove = async (k) => {
      const ok = await confirmDialog({ title: `Take the ${k.title.toLowerCase()} out of the queue?`, message: `The ${k.waiting.toLocaleString()} tasks no session has taken yet are removed${["check", "expand", "decompose"].includes(k.kind) ? ", and the checks still waiting are removed whole (as a stopped check)" : ""}. Answers already stored stay.`, confirmText: "Remove" });
      if (!ok) return;
      try { const r = await api("POST", `/api/projects/${P(App.project)}/queue/withdraw`, { kind: k.kind }); toast(`${r.withdrawn} tasks taken out of the queue.`, "ok"); App.refresh().catch(() => {}); draw(); } catch (e) { showError(e); }
    };
    const kinds = (q.kinds || []).filter((k) => k.waiting || k.being_answered);
    const head = q.runner && q.runner.running ? `Claude Code is working: ${(q.waiting + q.being_answered).toLocaleString()} to go`
      : q.waiting ? (q.paused ? `Paused: ${q.waiting.toLocaleString()} waiting` : `${(q.waiting + q.being_answered).toLocaleString()} waiting for Claude Code`)
      : q.being_answered ? `Claude Code is answering ${q.being_answered}` : "Nothing waits.";
    const parts = [h("p", { class: "qp-head" }, icon(q.paused ? "pause" : "inbox", { size: 14 }), " ", h("strong", {}, head)),
      h("p", { class: "muted small qp-privacy" }, icon("cloud", { size: 12 }), " ", q.privacy || "")];
    if (q.paused && q.paused_text) parts.push(h("p", { class: "small qp-paused" }, q.paused_text));
    if (!kinds.length) parts.push(h("p", { class: "muted small" }, "Press an AI button (a check, Label with the AI, Name the themes…): its work waits here for Claude Code."));
    for (const k of kinds) {
      parts.push(h("div", { class: "qp-row" + (k.held ? " qp-held" : "") },
        h("div", { class: "qp-title" }, h("strong", {}, k.title), k.held ? tag({}, "held") : null),
        h("div", { class: "muted small" }, `${k.waiting.toLocaleString()} waiting${k.being_answered ? ` · ${k.being_answered} being answered` : ""}${k.done ? ` · ${k.done.toLocaleString()} done` : ""}${k.stronger_model ? ` · ${k.stronger_model} for a stronger model` : ""}`),
        h("div", { class: "muted small" }, [k.helper ? `${k.helper} on ${k.model}` : k.model ? `on ${k.model}` : "", k.estimate ? ` · ${k.estimate}` : ""].join("")),
        h("div", { class: "qp-actions" },
          (q.order || [])[0] !== k.kind ? button({ kind: "quiet", sm: true, onClick: () => act(k.kind, "first") }, icon("arrow-up", { size: 12 }), "Do first") : null,
          button({ kind: "quiet", sm: true, onClick: () => act(k.kind, k.held ? "go" : "hold") }, icon(k.held ? "play" : "pause", { size: 12 }), k.held ? "Go on" : "Hold"),
          button({ kind: "danger", sm: true, onClick: () => remove(k) }, icon("trash", { size: 12 }), "Remove"))));
    }
    if (kinds.length || s.backend === "claude_code") parts.push(h("div", { class: "qp-start" }, startClaude(App.project, { command: q.command })));
    if (kinds.length && s.backend !== "claude_code") {
      parts.push(h("div", { class: "qp-here" }, button({ sm: true, onClick: async () => {
        try { const r = await api("POST", `/api/projects/${P(App.project)}/queue/run`, {}); toast("The AI model of Settings answers the queue now.", "ok"); watchJob(r.job.id, () => {}).promise.then(() => draw()); } catch (e) { showError(e); }
      } }, icon("play", { size: 13 }), "Answer them here instead"), h("span", { class: "muted small" }, ` with ${App.state.backend_label}`)));
    }
    replace(body, ...parts);
    if (q.waiting || q.being_answered || (q.runner && q.runner.running)) timer = setTimeout(draw, 5000);
  }
  draw();
  return section;
}
