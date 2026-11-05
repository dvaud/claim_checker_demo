// 0.13.6: a model on this computer, without a terminal. Ollama is a free program that runs AI models on the
// computer. When nothing runs: how to get it, and the page notices by itself when it starts. When Ollama runs
// without a model: one button downloads the suggested one (Ollama fetches it from ollama.com; none of the person's
// documents are sent), with its progress and a Stop button. Used by the first screen, Settings → AI (and Documents,
// for search by meaning) and the card for documents marked Only a local AI.
import { api, h, icon, replace, showError, watchJob, TERMINAL, appName } from "../lib.js";

const OLLAMA_SITE = "https://ollama.com/download";
const LOOK_EVERY = 3000;

export async function lookForServers() {
  try { return await api("GET", "/api/servers"); } catch (_) { return { servers: [], suggested: [] }; }
}

export const hasChatModel = (servers) => (servers || []).some((sv) => (sv.chat_models || []).length > 0);

const size = (n) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round((n || 0) / 1e6))} MB`);

// What to show while no model on this computer can answer; null when one can.
// info: GET /api/servers. opts: use ("ai", "restricted" or "embed": what the server chooses the downloaded model for
// when the download is done, even if the page was closed); onReady({ url, chat, embed, chosen }) after a download;
// onFound(info) when a server or a model appears (looked for every 3 s while this is on the page); embed: false offers
// no model for search by meaning; only: "embed" offers just that one (null when Ollama has one).
export function localModelHelp(info, opts = {}) {
  const servers = (info && info.servers) || [];
  const suggested = (info && info.suggested) || [];
  const chat = suggested.find((m) => m.use === "chat");
  const emb = suggested.find((m) => m.use === "embed");
  const ollama = servers.find((sv) => sv.kind === "ollama");
  if (opts.only === "embed") return ollama && emb && !(ollama.embedding_models || []).length ? pullBox(ollama, null, emb, opts) : null;
  if (hasChatModel(servers)) return null;
  if (ollama && chat) return pullBox(ollama, chat, opts.embed === false || (ollama.embedding_models || []).length ? null : emb, opts);
  if (servers.length) {
    return watchFor(h("div", { class: "local-help" },
      h("p", {}, h("strong", {}, "A model server is running, but it offers no model yet."), " Load a model in it (in LM Studio: choose a model and load it). This page notices by itself."),
      looking("Looking for a model…")), hasChatModel, opts.onFound);
  }
  return watchFor(h("div", { class: "local-help" },
    h("ol", { class: "guide", "aria-label": "Steps" },
      step(1, ["Get ", h("strong", {}, "Ollama"), ", a free program that runs AI models on your own computer. ",
        h("a", { class: "btn btn-sm", href: OLLAMA_SITE, target: "_blank", rel: "noopener" }, "Open ollama.com", icon("external-link", { size: 12 }))]),
      step(2, ["Install it and open it. ", appName(), " notices by itself."]),
      step(3, ["Download a model here, with one button. No terminal needed."])),
    looking("Looking for Ollama on this computer…"),
    h("p", { class: "muted small" }, "LM Studio, llama.cpp, Jan or vLLM work too: start one with a model loaded.")),
    (servers2) => servers2.length > 0, opts.onFound);
}

function step(n, children) {
  return h("li", { class: "guide-step" }, h("span", { class: "n" }, String(n)), h("div", {}, ...children));
}

function looking(text) {
  return h("p", { class: "muted small it local-looking" }, h("span", { class: "running-dot", "aria-hidden": "true" }), text);
}

// Look again every few seconds while `el` is on the page; `done(servers)` true: hand the new look to onFound.
// It stops once `el` has left the page (or was never put on it).
function watchFor(el, done, onFound) {
  if (!onFound) return el;
  let busy = false, ticks = 0;
  const timer = setInterval(async () => {
    ticks += 1;
    if (!el.isConnected) { if (el.dataset.seen || ticks > 3) clearInterval(timer); return; }
    el.dataset.seen = "1";
    if (busy) return;
    busy = true;
    const info = await lookForServers();
    busy = false;
    if (el.isConnected && done(info.servers || [])) { clearInterval(timer); onFound(info); }
  }, LOOK_EVERY);
  return el;
}

// The download: the suggested model (and the one for search by meaning, if wanted), its progress, Stop.
function pullBox(ollama, chat, emb, opts) {
  const alsoEmb = chat && emb ? h("input", { type: "checkbox", id: "pull-embed", checked: true }) : null;
  const first = chat || emb;
  const btn = h("button", { class: `btn ${chat ? "btn-primary" : ""}`, type: "button" }, icon("download", { size: 14 }), `Download ${first.name}`);
  const area = h("div", { class: "local-pull", "aria-live": "polite" });
  const box = h("div", { class: "local-help" },
    chat ? h("p", {}, h("strong", {}, `Ollama ${ollama.version || ""} is running`.replace("  ", " ")), ", but it has no model yet. Download one:")
      : h("p", {}, h("strong", {}, "Ollama has no model for search by meaning yet."), " Download one, and it is chosen here:"),
    h("p", { class: "muted small" }, `${first.name}: ${first.size}. Ollama downloads it from ollama.com; none of your documents are sent. It can take a while, and ${appName()} keeps working meanwhile.`),
    alsoEmb ? h("label", { class: "it small", for: "pull-embed" }, alsoEmb, ` Also ${emb.name} (${emb.size}), for search by meaning: it finds excerpts that use other words.`) : null,
    h("div", { class: "btn-row" }, btn),
    area);
  const names = () => [first.name, ...(alsoEmb && alsoEmb.checked ? [emb.name] : [])];
  const follow = (job) => {
    btn.hidden = true;
    if (alsoEmb) alsoEmb.disabled = true;
    const stop = h("button", { class: "btn btn-sm btn-ghost", type: "button" }, icon("stop", { size: 13 }), "Stop");
    stop.addEventListener("click", async () => { stop.disabled = true; try { await api("POST", `/api/jobs/${job.id}/cancel`); } catch (e) { showError(e); stop.disabled = false; } });
    const label = h("strong", {}, "Starting the download…");
    const amount = h("span", { class: "muted small" });
    const bar = h("span", { style: { width: "2%" } });
    const meter = h("div", { class: "progress-bar indeterminate", role: "progressbar", "aria-label": "Download", "aria-valuemin": 0, "aria-valuemax": 100 }, bar);
    replace(area, h("div", { class: "stack", style: { gap: "6px" } },
      h("div", { class: "row", style: { justifyContent: "space-between" } }, h("span", { class: "it" }, h("span", { class: "running-dot", "aria-hidden": "true" }), label), stop),
      meter, amount));
    const w = watchJob(job.id, (j) => {
      if (area.isConnected) area.dataset.seen = "1";
      else if (area.dataset.seen) { w.stop(); return; }   // the page was left: the download goes on without it
      const p = j.progress || {};
      const of = p.count > 1 ? ` (${p.index + 1} of ${p.count})` : "";
      const checking = /verifying|writing|success/.test(p.status || "");
      label.textContent = !p.model ? "Starting the download…" : checking ? `Checking ${p.model}${of}…` : `Downloading ${p.model}${of}`;
      const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
      meter.classList.toggle("indeterminate", !p.total);
      meter.setAttribute("aria-valuenow", p.total ? String(pct) : "");
      bar.style.width = `${Math.max(2, pct)}%`;
      amount.textContent = p.total ? `${size(p.done)} of ${size(p.total)}` : "";
    }, 1000);
    w.promise.then((j) => {
      if (j.state === "done") {
        const r = j.result || {};
        const got = r.models || [];
        replace(area, h("div", { class: "notice notice-ok" }, icon("circle-check"), h("p", {}, `Downloaded: ${got.join(" and ")}.`)));
        const listed = (m) => (m && got.includes(m.name) ? (r.listed || {})[m.name] || m.name : "");
        if (opts.onReady) opts.onReady({ url: r.url || ollama.url, chat: listed(chat), embed: listed(emb), chosen: r.chosen || null });
        return;
      }
      btn.hidden = false;
      if (alsoEmb) alsoEmb.disabled = false;
      btn.lastChild.textContent = `Download ${first.name} again`;
      replace(area, j.state === "cancelled"
        ? h("p", { class: "muted small" }, "Stopped. Ollama keeps what it has; the download goes on from there.")
        : h("div", { class: "notice notice-error" }, icon("alert-circle"), h("p", {}, j.error || "The download did not finish.")));
    }).catch(showError);
  };
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try { follow((await api("POST", "/api/servers/pull", { models: names(), url: ollama.url, use: opts.use || "" })).job); }
    catch (e) { showError(e); }
    btn.disabled = false;
  });
  // a download that is already running (started on another page, or before a reload): show it instead of the button
  api("GET", "/api/jobs").then((r) => {
    const j = ((r && r.jobs) || []).find((x) => x.kind === "model-pull" && !TERMINAL.has(x.state));
    if (j) follow(j);
  }).catch(() => {});
  return box;
}
