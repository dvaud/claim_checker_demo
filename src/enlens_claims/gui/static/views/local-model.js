// 0.13.7: a model on this computer, without a terminal. Ollama is a free program that runs AI models on the
// computer. When nothing runs: how to get it, and the page notices by itself when it starts. When Ollama runs
// without a model: one button downloads the suggested one (Ollama fetches it from ollama.com; none of the person's
// documents are sent), with its progress and a Stop button. Used by the first screen, Settings → AI (and Documents,
// for search by meaning) and the card for documents marked Only a local AI.
// 0.15.6: ollama.com now leads with a line for a terminal, so "Get Ollama" no longer links there: one button installs
// Ollama (after a dialog that says how big the download is on this computer and how much room it needs), with its
// progress and Stop, or starts the Ollama that is installed but not running. On Linux, Ollama's installer asks for the
// password, so the button opens a terminal window running Ollama's own line.
import { api, h, icon, replace, showError, watchJob, TERMINAL, appName, confirmDialog, dialog, copyLine } from "../lib.js";

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
  return watchFor(getOllama((info && info.ollama_app) || {}), (servers2) => servers2.length > 0, opts.onFound);
}

// 0.15.6: no model server is running. Ollama installed: one button starts it. Not installed: one button installs it.
function getOllama(app) {
  const area = h("div", { class: "local-pull", "aria-live": "polite" });
  const others = "LM Studio, llama.cpp, Jan or vLLM work too: start one with a model loaded.";
  const manual = app.installed ? h("p", { class: "muted small" }, others) : h("p", { class: "muted small" }, "Prefer to do it yourself? ",
    h("a", { href: app.manual || OLLAMA_SITE, target: "_blank", rel: "noopener" }, app.how === "terminal" ? "Ollama's instructions for Linux" : "Download Ollama's installer"),
    ` and open it. ${others}`);
  let steps;
  if (app.installed) {
    const btn = h("button", { class: "btn btn-sm btn-primary", type: "button" }, icon("play", { size: 13 }), "Start Ollama");
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const r = await api("POST", "/api/ollama/start", {});
        if (r.job) { followInstall(r.job, area, btn); return; }   // an install is still running: its progress instead
        startedWait(area, btn);
      } catch (e) { showError(e); btn.disabled = false; }
    });
    steps = [step(1, [h("strong", {}, "Ollama"), " is on this computer, but it is not running. ", btn]),
      step(2, ["Download a model here, with one button. No terminal needed."])];
  } else {
    const btn = h("button", { class: "btn btn-sm btn-primary", type: "button" }, icon("download", { size: 13 }), "Install Ollama");
    btn.addEventListener("click", () => installOllama(app, btn, area));
    steps = [step(1, ["Get ", h("strong", {}, "Ollama"), ", a free program that runs AI models on your own computer. ", btn]),
      step(2, app.how === "terminal" ? ["Its installer runs in a terminal window and asks for your password. ", appName(), " notices Ollama by itself."]
        : [appName(), " installs it for you and starts it. It shows the size of the download first."]),
      step(3, ["Download a model here, with one button. No terminal needed."])];
  }
  const box = h("div", { class: "local-help" }, h("ol", { class: "guide", "aria-label": "Steps" }, ...steps), area,
    looking("Looking for Ollama on this computer…"), manual);
  // an install that is already running (started on another page, or before a reload): show it instead of the button,
  // also when Ollama looks installed: the installer writes "ollama app.exe" first and the rest after it
  if (app.how !== "terminal") {
    api("GET", "/api/jobs").then((r) => {
      const j = ((r && r.jobs) || []).find((x) => x.kind === "ollama-install" && !TERMINAL.has(x.state));
      if (j) followInstall(j, area, steps[0].querySelector("button"));
    }).catch(() => {});
  }
  return box;
}

// After Start Ollama: the page notices Ollama within a few seconds (and moves on); after a minute without it, say so.
function startedWait(area, btn) {
  const look = area.parentElement && area.parentElement.querySelector(".local-looking");
  if (look) look.hidden = true;
  replace(area, looking("Ollama is starting…"));
  setTimeout(() => {
    if (!area.isConnected) return;
    if (look) look.hidden = false;
    btn.disabled = false;
    replace(area, h("p", { class: "muted small" }, "Ollama did not answer within a minute. Open the Ollama app yourself, or press Start Ollama again."));
  }, 60000);
}

const INSTALL_STEPS = { download: "Downloading Ollama", check: "Checking that it is Ollama's own installer…", install: "Installing Ollama…", start: "Starting Ollama…" };

// The dialog first: what is downloaded, from where, how big it is on this kind of computer, and the room it needs.
async function installOllama(app, btn, area) {
  btn.disabled = true;
  let plan;
  try { plan = await api("GET", "/api/ollama"); } catch (e) { showError(e); btn.disabled = false; return; }
  btn.disabled = false;
  const sz = (plan.size || {}).bytes || 0;
  const exact = (plan.size || {}).exact;
  const amount = sz ? `${exact ? "" : "about "}${size(sz)}` : "";
  const where = { windows: "Windows", mac: "macOS", linux: "Linux" }[plan.system] || "this computer";
  const yourself = h("p", { class: "small muted" }, "Prefer to do it yourself? ", h("a", { href: plan.manual || OLLAMA_SITE, target: "_blank", rel: "noopener" }, plan.how === "terminal" ? "Ollama's instructions for Linux" : "Download Ollama's installer"), ` and open it. ${appName()} notices Ollama by itself.`);
  if (plan.free && plan.needs && plan.free < plan.needs) {
    await dialog({ title: "Not enough free disk space", actions: [{ text: "OK", value: false, primary: true }],
      body: h("div", { class: "stack", style: { gap: "10px" } },
        h("p", {}, `Ollama for ${where} is a download of ${amount}. Installing it needs about ${size(plan.needs)} of free disk space, and this computer has ${size(plan.free)} free.`),
        h("p", {}, "Make room, then press Install Ollama again."), yourself) });
    return;
  }
  const facts = h("ul", { class: "small", style: { margin: 0, paddingLeft: "18px" } },
    amount ? h("li", {}, h("strong", {}, `Download: ${amount}`), ` (Ollama for ${where}, from ollama.com).`) : null,
    plan.needs ? h("li", {}, `Free disk space needed: about ${size(plan.needs)}${plan.free ? `; this computer has ${size(plan.free)} free` : ""}.`) : null,
    h("li", {}, "On a slow connection it takes a while. ", appName(), " keeps working meanwhile, and Stop ends the download."));
  const ok = await confirmDialog({
    title: "Install Ollama?", danger: false,
    confirmText: plan.how === "terminal" ? "Open the installer" : amount ? `Download ${amount} and install` : "Install Ollama",
    message: h("div", { class: "stack", style: { gap: "10px" } },
      plan.how === "terminal"
        ? h("p", {}, "Ollama is a free program that runs AI models on your own computer. On Linux its installer asks for your password, because it installs Ollama for everyone on this computer. ", appName(), " opens a terminal window running Ollama's own installer: type your password there.")
        : h("p", {}, "Ollama is a free program that runs AI models on your own computer. ", appName(), " downloads Ollama's installer from ollama.com, checks that it is signed by Ollama, and installs it ",
          plan.system === "mac" ? "in your Applications folder." : "in your user folder. It needs no administrator rights.", " Then it starts Ollama."),
      facts,
      h("p", { class: "small" }, icon("shield", { size: 13 }), " None of your documents are sent."),
      plan.how === "terminal" ? h("div", {}, h("p", { class: "small muted" }, "The line it runs:"), copyLine(plan.line, "Copy", "a terminal")) : null,
      yourself),
  });
  if (!ok) return;
  btn.disabled = true;
  try {
    const r = await api("POST", "/api/ollama/install", {});
    if (r.job) { followInstall(r.job, area, btn); return; }
    btn.disabled = false;
    if (r.terminal) {
      replace(area, r.terminal.opened
        ? h("p", { class: "small" }, `A ${r.terminal.window} window opened with Ollama's installer. Type your password there; ${appName()} notices Ollama by itself.`)
        : h("div", {}, h("p", { class: "small" }, "No terminal window could be opened. Open one, type this line and follow its steps:"), copyLine(r.terminal.command, "Copy", "a terminal")));
    } else if (r.started) startedWait(area, btn);
  } catch (e) { showError(e); btn.disabled = false; }
}

// The install's progress: the download with its size and a Stop button, then checking, installing and starting.
function followInstall(job, area, btn) {
  if (btn) btn.hidden = true;
  const look = area.parentElement && area.parentElement.querySelector(".local-looking");
  if (look) look.hidden = true;   // it is being installed: not "looking for" it
  const stop = h("button", { class: "btn btn-sm btn-ghost", type: "button" }, icon("stop", { size: 13 }), "Stop");
  stop.addEventListener("click", async () => { stop.disabled = true; try { await api("POST", `/api/jobs/${job.id}/cancel`); } catch (e) { showError(e); stop.disabled = false; } });
  const label = h("strong", {}, "Starting the download…");
  const amount = h("span", { class: "muted small" });
  const bar = h("span", { style: { width: "2%" } });
  const meter = h("div", { class: "progress-bar indeterminate", role: "progressbar", "aria-label": "Installing Ollama", "aria-valuemin": 0, "aria-valuemax": 100 }, bar);
  replace(area, h("div", { class: "stack", style: { gap: "6px" } },
    h("div", { class: "row", style: { justifyContent: "space-between" } }, h("span", { class: "it" }, h("span", { class: "running-dot", "aria-hidden": "true" }), label), stop),
    meter, amount));
  const w = watchJob(job.id, (j) => {
    if (area.isConnected) area.dataset.seen = "1";
    else if (area.dataset.seen) { w.stop(); return; }   // the page was left: the install goes on without it
    const p = j.progress || {};
    const downloading = !p.step || p.step === "download";
    stop.hidden = !downloading;   // once it is downloaded, checking and installing take a minute and are not cut short
    label.textContent = p.step ? INSTALL_STEPS[p.step] || "Installing Ollama…" : "Starting the download…";
    const pct = downloading && p.total ? Math.round((p.done / p.total) * 100) : 0;
    meter.classList.toggle("indeterminate", !(downloading && p.total));
    meter.setAttribute("aria-valuenow", downloading && p.total ? String(pct) : "");
    bar.style.width = `${Math.max(2, pct)}%`;
    amount.textContent = downloading && p.total ? `${size(p.done)} of ${size(p.total)}` : "";
  }, 1000);
  w.promise.then((j) => {
    if (j.state === "done") {
      const r = j.result || {};
      replace(area, r.running
        ? h("div", { class: "notice notice-ok" }, icon("circle-check"), h("p", {}, "Ollama is installed and running. A moment, and the next step appears here."))
        : h("div", { class: "notice" }, icon("info"), h("p", {}, "Ollama is installed, but it did not answer yet. Open it from ", r.path && /\.app$/.test(r.path) ? "Applications" : "the Start menu", ", and ", appName(), " notices it by itself.")));
      return;
    }
    if (btn) { btn.hidden = false; btn.disabled = false; }
    if (look) look.hidden = false;
    replace(area, j.state === "cancelled"
      ? h("p", { class: "muted small" }, "Stopped. Nothing was installed.")
      : h("div", { class: "notice notice-error" }, icon("alert-circle"), h("p", {}, j.error || "Ollama could not be installed.")));
  }).catch(showError);
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
