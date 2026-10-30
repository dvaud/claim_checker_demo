// Settings: model service, embeddings, check defaults, frameworks, model test, data folder.
import { App, api, h, icon, replace, clear, toast, showError, fmt, pageHead, watchJob, P, field, switchControl, rangeControl, confirmDialog, dialog, download, VERSION, session, TERMINAL, strictness, statusBadge, copyLine, tesseractHelp } from "../lib.js";
import { forgetFrameworks, loadFramework } from "./options.js";
import { simpleProgress } from "./progress.js";

// 0.9: Settings as five flat tabs (no section folded inside another). Old links to a section (#/settings/second,
// #/settings/calibration…) open its tab and scroll to it.
const TABS = [["model", "AI", "cpu"], ["basics", "Checking", "flask"], ["explore", "Exploring", "network"], ["documents", "Documents", "book-open"], ["advanced", "Technical", "sliders"]];
const TAB_OF = { model: "model", ai: "model", basics: "basics", calibration: "basics", explore: "explore", frameworks: "explore", documents: "documents", ocr: "documents", embeddings: "documents",
  advanced: "advanced", routing: "advanced", second: "advanced", context: "advanced", repeatable: "advanced", test: "advanced", data: "advanced" };

export async function renderSettings(view, [section]) {
  const s = { ...App.settings() };
  const tab = TAB_OF[section] || "model";
  let servers = [];
  if (tab === "model" || tab === "advanced" || tab === "documents") {
    try { servers = (await api("GET", "/api/servers")).servers || []; } catch (_) { servers = []; }
  }
  view.appendChild(pageHead("Settings", { actions: versionTag(), sub: {
    model: "Which AI reads your documents: Claude Code on your own Claude plan, a model on this computer, or none.",
    basics: "How strict a check is, and how new checks start.",
    explore: "The defaults of the Profile and Themes pages, and your codebooks.",
    documents: "Reading scanned PDFs, and search by meaning.",
    advanced: "For whoever installs the app. Most people never change anything here.",
  }[tab] }));
  view.appendChild(h("nav", { class: "settings-tabs", "aria-label": "Settings" },
    TABS.map(([id, label, ic]) => h("a", { href: `#/settings/${id}`, "aria-current": id === tab ? "page" : null }, icon(ic, { size: 14 }), label))));
  const main = h("div", { class: "stack", style: { gap: "20px" } });
  view.appendChild(main);
  if (tab === "model") main.append(modelSection(s, servers));
  else if (tab === "basics") main.append(basicsSection(s));
  else if (tab === "explore") main.append(exploreSection(s), await frameworksSection());
  else if (tab === "documents") main.append(sectionCard("ocr", "Reading scanned PDFs", "", ocrBlock(s)), embedSection(s, servers));
  else {
    // a local model's own settings (second model, context length) only when a local model answers
    const local = ["auto", "ollama", "openai"].includes(s.backend || "auto");
    main.append(...[routingSection(s, servers), local ? secondModelSection(s, servers) : null, local ? contextSection(s) : null, reproSection(s), testSection(s), dataSection()].filter(Boolean));
    if (!local) main.appendChild(h("p", { class: "muted small" }, icon("info", { size: 13 }), " The settings of a model on this computer (a second model, the context length) show here when a local model is chosen under AI."));
  }
  if (section && section !== tab) setTimeout(() => { const t = document.getElementById(`s-${section}`); if (t) t.scrollIntoView({ block: "start" }); }, 80);
}

// ---------------------------------------------------------------------------------------------
function basicsSection(s) {
  const state = h("span", { class: "save-state", "aria-live": "polite" });
  const strictState = h("span", { class: "save-state", "aria-live": "polite" });
  const thr = rangeControl("How sure the AI must be before a judgement counts", { min: 0.3, max: 0.95, step: 0.05, value: s.threshold ?? 0.6, format: (v) => `${strictness(v)} (${Math.round(Number(v) * 100)}%)`, ends: ["relaxed", "strict"], help: "The AI says how sure it is of each judgement; 60% means it said it was at least 60% sure. Judgements below this are shown but not counted. Your own judgements always count. Changing this updates all results, old and new." });
  const changes = h("div", { "aria-live": "polite" });
  async function reportChanges(oldT, newT) {
    if (!App.project) return;
    try {
      const [a, b] = await Promise.all([api("GET", `/api/projects/${P(App.project)}/hypotheses?threshold=${oldT}`), api("GET", `/api/projects/${P(App.project)}/hypotheses?threshold=${newT}`)]);
      const before = new Map((a.hypotheses || []).map((x) => [x.hyp_id, x]));
      const rows = (b.hypotheses || []).filter((x) => before.has(x.hyp_id));
      const counts = (x) => `${x.supports || 0} support, ${x.partly || 0} partly, ${x.refutes || 0} contradict, ${x.uncounted || 0} too uncertain`;
      const answerDiff = rows.filter((x) => before.get(x.hyp_id).status !== x.status);
      const countDiff = rows.filter((x) => before.get(x.hyp_id).status === x.status && counts(before.get(x.hyp_id)) !== counts(x));
      const item = (x, withStatus) => h("li", {}, h("a", { href: `#/h/${encodeURIComponent(x.hyp_id)}`, class: "serif" }, x.text || x.claim), " ",
        withStatus ? [statusBadge(before.get(x.hyp_id).status, { short: true }), " → ", statusBadge(x.status, { short: true }), " "] : null,
        h("span", { class: "muted small" }, `(${counts(before.get(x.hyp_id))} → ${counts(x)})`));
      const bits = [];
      if (answerDiff.length) bits.push(h("p", {}, h("strong", {}, `${answerDiff.length} ${answerDiff.length === 1 ? "answer" : "answers"} changed:`)), h("ul", { class: "changes-list" }, answerDiff.map((x) => item(x, true))));
      else bits.push(h("p", {}, h("strong", {}, "No answer changed"), countDiff.length ? `, but in ${countDiff.length} ${countDiff.length === 1 ? "result" : "results"} a different number of excerpts counts now:` : "."));
      if (countDiff.length) bits.push(answerDiff.length ? h("p", { style: { marginTop: "6px" } }, `In ${countDiff.length} more ${countDiff.length === 1 ? "result" : "results"} the answer stayed, but a different number of excerpts counts now:`) : null, h("ul", { class: "changes-list" }, countDiff.map((x) => item(x, false))));
      replace(changes, h("div", { class: `notice ${answerDiff.length ? "notice-info" : "notice-ok"}`, style: { marginTop: "10px" } }, icon(answerDiff.length ? "info" : "circle-check"), h("div", {}, bits)));
    } catch (e) { showError(e); }
  }
  // strictness saves on release and reports what changed
  let savingStrict = false;
  async function saveStrict(newT) {
    if (savingStrict) return;
    savingStrict = true;
    const oldT = App.settings().threshold ?? 0.6;
    try {
      if (Math.abs(oldT - newT) > 1e-9) {
        await save({ threshold: newT }, strictState);
        strictState.textContent = `Saved: all results now count judgements the AI was at least ${Math.round(newT * 100)}% sure of.`;
        await reportChanges(oldT, newT);
        loadCalibration();
      } else strictState.textContent = "Saved.";
    } catch (_) { /* shown */ }
    savingStrict = false;
  }
  thr.input.addEventListener("change", () => saveStrict(thr.input.valueAsNumber));
  const backBtn = h("button", { class: "btn btn-sm", type: "button", onClick: () => { thr.input.value = 0.6; thr.input.dispatchEvent(new Event("input", { bubbles: true })); saveStrict(0.6); } }, "Back to normal (60%)");
  const k = rangeControl("How many excerpts the AI reads per check", { min: 1, max: 20, step: 1, value: s.k ?? 8, help: "More finds more evidence but takes longer." });
  const perDoc = rangeControl("At most this many from one document", { min: 1, max: 10, step: 1, value: s.per_doc ?? 2 });
  const expand = switchControl("Also search for other words (synonyms)", !!s.expand, { help: "The AI suggests other words your documents might use." });
  const decompose = switchControl("Check each part of a hypothesis separately", !!s.decompose, { help: "For hypotheses with several claims in one sentence." });
  const calibration = h("div", { class: "calibration", id: "s-calibration", "aria-live": "polite" });
  const useSuggestion = (t) => { thr.input.value = t; thr.input.dispatchEvent(new Event("input", { bubbles: true })); saveStrict(t); };
  const strictForm = h("div", {},
    thr,
    h("p", { class: "notice notice-warn", style: { margin: "0 0 10px" } }, icon("alert-triangle"), h("span", {}, "The AI's certainty is its own estimate, not a check of whether it is right. A stricter setting counts fewer judgements, but can still count wrong ones. Reading the excerpts and judging them yourself is the reliable check.")),
    h("div", { class: "save-row" }, backBtn, h("span", { class: "muted small" }, "Saved as soon as you let go of the slider."), strictState),
    changes,
    calibration);
  const loadCalibration = async () => {
    if (!App.project) { clear(calibration); return; }
    try { replace(calibration, calibrationBlock(await api("GET", `/api/projects/${P(App.project)}/calibration`), useSuggestion)); }
    catch (e) { clear(calibration); }
    // linked to from a result ("how often you agree"): the block is loaded after the page, so scroll to it now
    if (/#\/settings\/calibration$/.test(location.hash)) { calibration.scrollIntoView({ block: "start" }); const t = calibration.querySelector(".cal-title"); if (t) { t.setAttribute("tabindex", "-1"); t.focus(); } }
  };
  loadCalibration();
  const saveDefaults = async () => { try { await save({ k: k.input.valueAsNumber, per_doc: perDoc.input.valueAsNumber, expand: expand.input.checked, decompose: decompose.input.checked }, state); } catch (_) { /* shown */ } };
  for (const c of [k.input, perDoc.input, expand.input, decompose.input]) c.addEventListener("change", saveDefaults);
  const form = h("div", {},
    h("div", { class: "fields-2" }, h("div", {}, expand, decompose), h("div", {}, k, perDoc)),
    h("div", { class: "save-row" }, h("span", { class: "muted small" }, "Saved as soon as you change something. New checks start with these; each check can still change them under More options."), state));
  return sectionCard("basics", "Checking hypotheses", "",
    h("h3", { style: { marginBottom: "6px" } }, "Strictness"),
    strictForm,
    h("h3", { style: { margin: "22px 0 6px" } }, "How new checks start"),
    form);
}

// Calibration: how often the person agreed with the AI, by the AI's certainty, as a small bar chart with a text
// equivalent; and the suggested strictness with its reason, when there is enough data.
function calibrationBlock(c, useSuggestion) {
  const bins = c.bins || [];
  const total = c.total || 0;
  const pct = (x) => `${Math.round(x * 100)}%`;
  const box = h("div", { class: "cal-box" });
  box.appendChild(h("h4", { class: "cal-title" }, icon("scale", { size: 14 }), " How often you agreed with the AI, by its certainty"));
  if (!total) {
    box.appendChild(h("p", { class: "muted small", style: { margin: 0 } }, "Nothing to show yet: when you review excerpts (agree with the AI or judge them differently), this shows how often you agreed, for each level of the AI's certainty, and suggests a strictness. ", c.note || ""));
    return box;
  }
  // the chart: one column per band, height = agreement rate; an empty band is drawn as a dashed outline
  const chart = h("div", { class: "cal-chart", role: "img", "aria-label": `Agreement with the AI by its certainty: ${bins.map((b) => `${pct(b.from)} to ${pct(b.to)}: ${b.judged ? `${b.agreed} of ${b.judged} (${pct(b.rate || 0)})` : "none judged"}`).join("; ")}.` });
  const current = c.threshold ?? 0.6;
  for (const b of bins) {
    const rate = b.judged ? (b.rate ?? b.agreed / b.judged) : null;
    const counted = b.from >= current - 1e-9;
    const col = h("div", { class: "cal-col" + (counted ? " cal-counted" : "") },
      h("span", { class: "cal-val" }, rate === null ? "–" : pct(rate)),
      h("div", { class: "cal-bar-wrap" },
        rate === null ? h("div", { class: "cal-bar cal-empty", style: { height: "100%" } }) : h("div", { class: "cal-bar", style: { height: `${Math.max(3, Math.round(rate * 100))}%` } })),
      h("div", { class: "cal-lab" }, `${pct(b.from)}–${pct(b.to)}`),
      h("div", { class: "cal-n" }, b.judged ? `${b.agreed} of ${b.judged}` : "none"));
    chart.appendChild(col);
  }
  box.appendChild(chart);
  box.appendChild(h("p", { class: "muted small cal-foot" }, `From the ${total} AI judgements for or against that you reviewed: you agreed with ${c.agreed || 0} (${pct(total ? (c.agreed || 0) / total : 0)}). Bands at or above your strictness (${pct(current)}) are shaded; the number under each bar is how many you agreed with of those you judged.`));
  // text equivalent for screen readers and for anyone who prefers a table
  box.appendChild(h("details", { class: "fold" }, h("summary", {}, "As a table"),
    h("table", { class: "table cal-table" }, h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "AI certainty"), h("th", { scope: "col", class: "num" }, "You judged"), h("th", { scope: "col", class: "num" }, "You agreed"), h("th", { scope: "col", class: "num" }, "Agreement"))),
      h("tbody", {}, bins.map((b) => h("tr", {}, h("td", {}, `${pct(b.from)} to ${pct(b.to)}`), h("td", { class: "num" }, String(b.judged)), h("td", { class: "num" }, String(b.agreed)), h("td", { class: "num" }, b.judged ? pct(b.rate ?? b.agreed / b.judged) : "–")))))));
  if (c.suggestion && c.suggestion.threshold !== undefined) {
    const t = Number(c.suggestion.threshold);
    const same = Math.abs(t - current) < 1e-9;
    box.appendChild(h("div", { class: `notice ${same ? "notice-ok" : "notice-info"}`, style: { marginTop: "10px" } }, icon(same ? "circle-check" : "info"),
      h("div", {}, h("p", {}, h("strong", {}, same ? `Your strictness (${pct(t)}) fits your reviews. ` : `Suggested strictness: ${pct(t)}. `), c.suggestion.reason || ""),
        same ? null : h("button", { class: "btn btn-sm btn-primary", type: "button", style: { marginTop: "8px" }, onClick: () => useSuggestion(t) }, `Use ${pct(t)}`))));
  } else if (c.note) {
    box.appendChild(h("p", { class: "muted small", style: { margin: "8px 0 0" } }, icon("info", { size: 12 }), " ", c.note));
  }
  return box;
}

// Reading scanned PDFs: on/off and the languages, with what the computer can do.
function ocrBlock(s) {
  const st = (App.state && App.state.ocr) || {};
  const state = h("span", { class: "save-state", "aria-live": "polite" });
  const on = switchControl("Read scanned PDF pages (text recognition)", (s.ocr || "auto") !== "off", { help: "A scanned PDF is a picture of the pages. With text recognition (OCR) the app reads the text on them, on this computer, slowly and with some errors; the Documents page says which documents were read this way." });
  const lang = h("input", { class: "input input-sm", type: "text", value: s.ocr_lang || "eng", placeholder: "eng", maxlength: 60, style: { maxWidth: "16em" } });
  const installed = st.languages && st.languages.length ? st.languages : [];
  const langField = field("Languages of the scanned documents", lang, { help: `Three-letter codes, joined with +, for example eng+nld for English and Dutch.${installed.length ? ` Installed on this computer: ${installed.join(", ")}.` : ""}` });
  const saveOcr = async () => { try { await save({ ocr: on.input.checked ? "auto" : "off", ocr_lang: lang.value.trim() || "eng" }, state); } catch (_) { /* shown */ } };
  on.input.addEventListener("change", saveOcr);
  lang.addEventListener("change", saveOcr);
  const box = h("div", {});
  if (st.available === false) {
    box.appendChild(h("div", { class: "notice notice-warn", style: { marginBottom: "10px" } }, icon("alert-triangle"), h("div", {}, h("p", {}, h("strong", {}, "To read scanned PDFs, install Tesseract."), " Until then, scanned pages stay without text and a wholly scanned PDF cannot be added."),
      st.install ? tesseractHelp(st) : h("p", { class: "small" }, "What is missing is listed under Settings → Technical."))));
  } else if (st.available) {
    box.appendChild(h("p", { class: "muted small", style: { margin: "0 0 8px" } }, icon("circle-check", { size: 13 }), " Text recognition is installed on this computer."));
  }
  box.append(on, langField, h("div", { class: "save-row" }, h("span", { class: "muted small" }, "Saved as soon as you change something. Applies to documents added from now on."), state));
  return box;
}

// A plain reading of the model test, with the technical lines folded away.
export function plainTestResult(r) {
  const ok = r.ok && r.model_available;
  const emb = r.embedding;
  return h("div", { class: "stack", style: { gap: "8px" } },
    h("div", { class: `notice ${ok ? "notice-ok" : "notice-warn"}` }, icon(ok ? "circle-check" : "alert-triangle"),
      h("div", {}, h("p", {}, h("strong", {}, ok ? "Working. " : "Not quite. "), ok ? "The AI model answered. Checks can run." : (r.model_available === false ? "The service runs, but the chosen model is not installed on it." : "The AI model did not answer as expected.")),
        emb ? h("p", { class: "small" }, emb.ok ? "Search by meaning is working too." : "Search by meaning is not working: documents are searched by their words only.") : null,
        r.warning ? h("p", { class: "small" }, r.warning) : null,
        h("details", { class: "fold" }, h("summary", {}, "Technical details"), testResult(r)))));
}

function sectionCard(id, title, lead, ...children) {
  return h("section", { class: "card settings-section", id: `s-${id}`, "aria-labelledby": `s-${id}-h` },
    h("h2", { id: `s-${id}-h`, tabindex: "-1" }, title), lead ? h("p", { class: "lead" }, lead) : null, ...children);
}

async function save(changes, stateEl) {
  if (stateEl) stateEl.textContent = "Saving…";
  try {
    const r = await api("PUT", "/api/settings", changes);
    App.state.settings = r.settings;
    App.state.backend_label = r.backend_label;
    for (const fn of App.listeners) fn(App.state);
    if (stateEl) stateEl.textContent = "Saved.";
    return r;
  } catch (e) {
    if (stateEl) stateEl.textContent = "";
    showError(e);
    throw e;
  }
}

// ---------------------------------------------------------------------------------------------
function modelSection(s, servers) {
  const localOnly = !!(App.state && App.state.local_only);
  let allowCC = !!s.allow_claude_code;
  const state = h("span", { class: "save-state", "aria-live": "polite" });
  const detail = h("div", {});
  let backend = s.backend || "auto";
  const isLocal = (b) => ["auto", "ollama", "openai"].includes(b);
  const allowCloud = switchControl("Allow cloud models", !!s.allow_cloud, { help: "" });
  const cloudBox = h("div", { class: "cloud-box" }, allowCloud, h("p", {}, icon("alert-triangle", { size: 13 }), " With the Claude API the hypothesis and the excerpts read leave this computer and are billed to the key."));

  // 0.9: subscription first: four large choices, Claude Code first
  const ROUTES = [
    ["claude_code", "Claude Code", "cloud", "Recommended", "Claude reads the excerpts on your own Claude plan (Pro or Max). ENLENS prepares the work, starts Claude Code for you and checks every quote.", "Only the passages inside the tasks go to Anthropic"],
    ["local", "A model on this computer", "house", "", "Ollama, LM Studio, llama.cpp, Jan or vLLM. Free and fully private; needs a capable computer and judges less well than Claude.", "Nothing leaves this computer"],
    ["baseline", "No AI (demo)", "cpu", "", "A word-overlap stand-in, to see how the app works. Search, keyword profiles, the glossary and themes work fully without AI.", "Nothing leaves this computer"],
    ["anthropic", "Claude API (team key)", "key", "", "For a shared installation: the Claude API with the team's key, billed per use.", "The excerpts read go to Anthropic"],
  ];
  const routeOf = (b) => (isLocal(b) ? "local" : b);
  const radiosWrap = h("div", { class: "route-cards", role: "radiogroup", "aria-label": "Which AI reads the documents" });
  const select = (key) => { for (const inp of radiosWrap.querySelectorAll("input")) inp.checked = inp.value === key; };
  for (const [key, title, ic, badge, sub, where] of ROUTES) {
    if (localOnly && (key === "claude_code" || key === "anthropic")) continue;
    const input = h("input", { type: "radio", name: "route", value: key, checked: routeOf(backend) === key });
    input.addEventListener("change", async () => {
      const prev = routeOf(backend);
      if (key === "claude_code" && !allowCC) {
        const ok = await dialog({
          title: "Let Claude Code read the excerpts, on your own Claude plan?",
          body: h("div", {}, h("p", {}, "The AI buttons of ENLENS then prepare tasks; Claude Code answers them, started by ENLENS when you press Start Claude Code, or by you with /enlens-run."),
            h("p", {}, h("strong", {}, "The passages inside the tasks Claude Code takes are sent to Anthropic."), " Your documents, results and reviews stay on this computer, and every answer is checked here against the text."),
            h("p", { class: "muted small" }, "ENLENS never sees your Claude login and never runs on anyone else's plan.")),
          actions: [{ text: "Keep the AI on this computer", value: false, id: "dlg-safe" }, { text: "Use Claude Code", value: true, primary: true }],
        });
        if (!ok) { select(prev); return; }
        allowCC = true;
      }
      if (key === "anthropic" && prev !== "anthropic") {
        const ok = await dialog({
          title: "Use the Claude API with a team key?",
          body: h("div", {}, h("p", {}, "With the Claude API, the hypothesis and the excerpts of your documents that the AI reads are sent to Anthropic's servers, and the use is billed to an account key."),
            h("p", { class: "muted small" }, "For one researcher, Claude Code on your own plan is simpler. Nothing is sent before you also switch on “Allow cloud models”, enter a key and save.")),
          actions: [{ text: "Back", value: false, primary: true, id: "dlg-safe" }, { text: "Continue with the Claude API", value: true }],
          onOpen(dlg) { const b = dlg.querySelector("#dlg-safe"); if (b) b.focus(); },
        });
        if (!ok) { select(prev); return; }
      }
      backend = key === "local" ? (isLocal(s.backend) ? s.backend : "auto") : key;
      drawDetail();
    });
    radiosWrap.appendChild(h("label", { class: "route-card" }, input,
      h("span", { class: "rc-top" }, icon(ic, { size: 16 }), title, badge ? h("span", { class: "rc-badge" }, badge) : null),
      h("span", { class: "rc-sub" }, sub),
      h("span", { class: "rc-where" }, icon(key === "claude_code" || key === "anthropic" ? "cloud" : "house", { size: 12 }), where)));
  }
  const lockedLine = localOnly ? h("p", { class: "muted small" }, icon("shield", { size: 13 }), " Cloud models are switched off on this computer by whoever installed ENLENS.") : null;
  // which local server (the three local routes of 0.8, as one choice)
  const localKind = () => {
    const sel = h("select", { class: "select" }, [["auto", "Automatic: the first server found"], ["ollama", "Ollama"], ["openai", "LM Studio, llama.cpp, Jan, vLLM (OpenAI-compatible)"]].map(([v, t]) => h("option", { value: v, selected: backend === v }, t)));
    sel.addEventListener("change", () => { backend = sel.value; drawDetail(); });
    return field("Local model server", sel);
  };

  const ollamaSrv = servers.find((x) => x.kind === "ollama");
  const openaiSrv = servers.find((x) => x.kind !== "ollama");
  const fields = {};
  const modelPicker = (id, current, models, placeholder) => {
    const wrap = h("div", { class: "field" });
    const sel = h("select", { class: "select", id });
    const txt = h("input", { class: "input", type: "text", id: id + "-txt", value: current || "", placeholder });
    if (models && models.length) {
      sel.appendChild(h("option", { value: "" }, "Choose a model…"));
      for (const m of models) sel.appendChild(h("option", { value: m, selected: m === current }, m));
      if (current && !models.includes(current)) sel.appendChild(h("option", { value: current, selected: true }, `${current} (not installed)`));
      sel.appendChild(h("option", { value: "__other" }, "Other (type a name)…"));
      sel.addEventListener("change", () => { txt.hidden = sel.value !== "__other"; if (sel.value === "__other") txt.focus(); });
      txt.hidden = true;
      wrap.append(h("label", { class: "field-label", for: id }, "Chat model"), sel, txt);
      wrap.value = () => (sel.value === "__other" ? txt.value.trim() : sel.value);
    } else {
      wrap.append(h("label", { class: "field-label", for: id + "-txt" }, "Chat model"), txt, h("div", { class: "field-help" }, "No server answered just now, so the installed models could not be listed. Type the model name."));
      wrap.value = () => txt.value.trim();
    }
    return wrap;
  };

  function serverList() {
    if (!servers.length) return h("div", { class: "notice notice-warn" }, icon("alert-triangle"), h("div", {}, h("p", {}, "No local model server answered. Start Ollama (ollama.com), then download a model, for example ", h("code", {}, "ollama pull qwen3:8b"), ". Or start LM Studio / llama.cpp with a model loaded."),
      h("button", { class: "btn btn-sm", type: "button", style: { marginTop: "6px" }, onClick: () => location.reload() }, icon("refresh", { size: 13 }), "Scan again")));
    return h("div", { class: "server-list" }, servers.map((sv) => h("div", { class: "server" }, icon("circle-check", { size: 14 }),
      h("div", {}, h("strong", {}, sv.kind === "ollama" ? `Ollama ${sv.version || ""}` : `OpenAI-compatible server`), h("span", { class: "muted" }, ` at ${sv.url}`),
        h("div", { class: "sv-models" }, `Chat: ${(sv.chat_models || []).join(", ") || "none"} · Embedding: ${(sv.embedding_models || []).join(", ") || "none"}`)))));
  }

  function drawDetail() {
    clear(detail);
    fields.ollama_url = h("input", { class: "input input-mono", type: "url", value: s.ollama_url || "", placeholder: "http://localhost:11434" });
    fields.openai_url = h("input", { class: "input input-mono", type: "url", value: s.openai_url || "", placeholder: "http://localhost:1234/v1" });
    fields.anthropic_model = h("input", { class: "input input-mono", type: "text", value: s.anthropic_model || "", placeholder: "claude-opus-5-5" });
    fields.think = h("select", { class: "select" }, [["off", "Off (fastest)"], ["judging", "Only when judging excerpts"], ["on", "On for every step"], ["default", "Model's default"]].map(([v, t]) => h("option", { value: v, selected: (s.think || "default") === v }, t)));
    fields.think_budget = h("input", { class: "input", type: "number", min: 0, max: 16384, step: 250, value: s.think_budget ?? 1500, "aria-label": "Reasoning budget in tokens" });
    const budgetHelp = () => {
      const n = Number(fields.think_budget.value) || 0;
      return n ? `The AI reasons for at most about ${n.toLocaleString()} tokens, then answers from its notes: at 20 tokens a second that is about ${Math.round(n / 20 / 60 * 10) / 10 || "<1"} min of reasoning per call. 0 = no limit (can take very long).` : "No limit: a reasoning model can take many minutes per call.";
    };
    const budgetNote = h("div", { class: "field-help" }, budgetHelp());
    fields.think_budget.addEventListener("input", () => { budgetNote.textContent = budgetHelp(); });
    const thinkRow = () => h("div", { class: "fields-2" },
      field("Reasoning (thinking models only)", fields.think, { help: "Reasoning can make judgements more careful but makes each check slower. “Only when judging excerpts” reasons where it can help and not for search words or splitting a hypothesis. Test it before relying on it (Test a model, with reasoning on and off)." }),
      h("div", { class: "field" }, h("label", { class: "field-label" }, "Reasoning budget (tokens)", fields.think_budget), budgetNote));
    if (isLocal(backend)) detail.append(localKind());
    if (backend === "auto") {
      detail.append(serverList(), h("p", { class: "muted small" }, "The first server found is used. If a chat model is named below for Ollama or an OpenAI-compatible server, it is preferred when that server has it."),
        fields.ollamaModel = modelPicker("m-ollama", s.ollama_model, ollamaSrv ? ollamaSrv.chat_models : [], "e.g. qwen3:8b"), thinkRow());
      fields.ollamaModel.querySelector(".field-label").textContent = "Preferred Ollama model";
    } else if (backend === "ollama") {
      detail.append(serverList(), h("div", { class: "fields-2" }, field("Ollama address", fields.ollama_url), fields.ollamaModel = modelPicker("m-ollama", s.ollama_model, ollamaSrv ? ollamaSrv.chat_models : [], "e.g. qwen3:8b")),
        thinkRow(), h("p", { class: "muted small" }, "Context length: set automatically; see Settings → Technical."));
    } else if (backend === "openai") {
      detail.append(serverList(), h("div", { class: "fields-2" }, field("Server address", fields.openai_url, { help: "The /v1 base URL of LM Studio, llama.cpp, Jan, vLLM…" }), fields.openaiModel = modelPicker("m-openai", s.openai_model, openaiSrv ? openaiSrv.chat_models : [], "leave empty for the first model listed")));
    } else if (backend === "anthropic") {
      detail.append(cloudBox, field("Model for judging excerpts", fields.anthropic_model, { help: "For example claude-opus-5-5. The other kinds of task use their own model: see “AI model per task” under Technical." }), keyBox(), fableSwitch());
    } else if (backend === "claude_code") {
      detail.append(claudeCodeBox(), fableSwitch());
    } else {
      detail.append(h("div", { class: "notice notice-info" }, icon("info"), h("p", {}, "The offline demo grades passages by word overlap, without a model. It shows how the app works; its results are not findings.")));
    }
  }

  function fableSwitch() {
    fields.use_fable = switchControl("Let the auditor use Fable", !!s.use_fable, { help: "The auditor gives second opinions and reads the hard cases again (unsure judgements, rejected quotes). It runs on Opus unless this is on. In Claude Code, Fable can be billed from usage credits instead of your plan's limits; the model picker then says “Requires usage credits”." });
    return fields.use_fable;
  }

  // Claude Code (0.9): a checklist of what is ready, one button that sets up what is not, and how a run starts.
  function claudeCodeBox() {
    return h("div", { class: "stack", style: { gap: "10px" } }, claudeSetupCard());
  }

  function keyBox() {
    const k = (App.state && App.state.key) || {};
    const have = k.env ? "from the environment variable ANTHROPIC_API_KEY" : k.stored ? "saved on this computer" : k.session ? "for this session" : "";
    const input = h("input", { class: "input input-mono", type: "password", placeholder: "sk-ant-…", autocomplete: "off", "aria-label": "Claude API key" });
    const remember = h("input", { type: "checkbox", id: "key-remember", checked: !!k.stored });
    const st = h("span", { class: "save-state", "aria-live": "polite" });
    const setBtn = h("button", { class: "btn btn-sm", type: "button", onClick: async () => {
      if (!input.value.trim()) { input.focus(); return; }
      try { const r = await api("POST", "/api/settings/key", { key: input.value.trim(), remember: remember.checked }); App.state.key = r.key; input.value = ""; st.textContent = remember.checked ? "Key saved on this computer." : "Key kept for this session."; toast("API key set.", "ok"); }
      catch (e) { showError(e); }
    } }, icon("key", { size: 13 }), "Use this key");
    const forget = h("button", { class: "btn btn-sm btn-ghost", type: "button", hidden: !(k.session || k.stored), onClick: async () => {
      try { const r = await api("DELETE", "/api/settings/key"); App.state.key = r.key; st.textContent = "Key forgotten."; forget.hidden = true; } catch (e) { showError(e); }
    } }, "Forget the key");
    return h("div", { class: "card card-plain", style: { padding: "12px 14px" } },
      h("div", { class: "field-label" }, "API key"),
      have ? h("div", { class: "notice notice-ok", style: { margin: "6px 0 10px" } }, icon("circle-check"), h("p", {}, `A key is set (${have}).`)) : h("p", { class: "muted small" }, "From console.anthropic.com. Without a key, cloud checks fail."),
      h("div", { class: "row" }, input),
      h("div", { class: "row", style: { marginTop: "8px" } }, h("label", { class: "it small", for: "key-remember" }, remember, " Remember on this computer (readable by your user only)"), setBtn, forget, st));
  }

  const saveBtn = h("button", { class: "btn btn-primary", type: "submit" }, icon("check", { size: 14 }), "Save");
  const testBtn = h("button", { class: "btn", type: "button" }, icon("zap", { size: 14 }), "Save and test");
  const testOut = h("div", { class: "test-result", "aria-live": "polite" });

  const collect = () => {
    const c = { backend, allow_cloud: allowCloud.input.checked };
    if (backend === "claude_code") c.allow_claude_code = allowCC;
    if (fields.use_fable && (backend === "claude_code" || backend === "anthropic")) c.use_fable = fields.use_fable.input.checked;
    if (fields.ollama_url) c.ollama_url = fields.ollama_url.value.trim();
    if (fields.openai_url) c.openai_url = fields.openai_url.value.trim();
    if (fields.ollamaModel) c.ollama_model = fields.ollamaModel.value();
    if (fields.openaiModel) c.openai_model = fields.openaiModel.value();
    if (fields.anthropic_model) c.anthropic_model = fields.anthropic_model.value.trim();
    if (fields.think && (backend === "ollama" || backend === "auto")) {
      c.think = fields.think.value;
      c.think_budget = Math.max(0, Math.round(Number(fields.think_budget.value) || 0));
    }
    return c;
  };
  const form = h("form", { onSubmit: async (e) => { e.preventDefault(); try { await save(collect(), state); Object.assign(s, App.settings()); toast(`AI: ${App.state.backend_label}`, "ok"); } catch (_) { /* shown */ } } },
    radiosWrap, lockedLine, detail, h("div", { class: "save-row" }, saveBtn, testBtn, state));
  testBtn.addEventListener("click", async () => {
    testBtn.disabled = true;
    replace(testOut, h("div", { class: "notice" }, h("span", { class: "spinner" }, icon("loader")), h("p", {}, "Testing the model service…")));
    try {
      await save(collect(), state);
      Object.assign(s, App.settings());
      const r = await api("POST", "/api/servers/test");
      replace(testOut, testResult(r));
    } catch (e) {
      replace(testOut, h("div", { class: "notice notice-error" }, icon("alert-circle"), h("div", {}, h("p", {}, e.message), e.kind === "backend" ? h("p", { class: "small" }, "Is the server running? For Ollama: start it, then ", h("code", {}, "ollama pull <model>"), ".") : null)));
    }
    testBtn.disabled = false;
  });
  drawDetail();
  return sectionCard("model", "Which AI reads your documents", "", form, testOut);
}

export function testResult(r) {
  const bits = [];
  const d = r.details || {};
  bits.push(h("div", { class: `notice ${r.model_available ? "notice-ok" : "notice-warn"}` }, icon(r.model_available ? "circle-check" : "alert-triangle"), h("div", {}, h("p", {}, r.message || (r.ok ? "The model answers." : "Problem")),
    d.trained_context ? h("p", { class: "small" }, `Trained for ${fmt.num(d.trained_context)} tokens of context.`) : null)));
  if (r.warning) bits.push(h("div", { class: "notice notice-warn" }, icon("alert-triangle"), h("p", {}, r.warning)));
  if (r.embedding) {
    bits.push(r.embedding.ok ? h("div", { class: "notice notice-ok" }, icon("sparkles"), h("p", {}, `Embedding model ${r.embedding.model} answers (${r.embedding.dimensions} dimensions).`))
      : h("div", { class: "notice notice-warn" }, icon("alert-triangle"), h("p", {}, `Embedding model ${r.embedding.model}: ${r.embedding.error}`)));
  }
  return h("div", { class: "stack", style: { gap: "8px" } }, bits);
}

// ---------------------------------------------------------------------------------------------
// 0.8: the model of each kind of task, and when a task goes up to a stronger one.
function routingSection(s, servers) {
  const state = h("span", { class: "save-state", "aria-live": "polite" });
  const body = h("div", {}, h("p", { class: "muted small" }, "Loading…"));
  const chat = [...new Set(servers.flatMap((x) => x.chat_models || []))];
  async function draw() {
    let r;
    try { r = await api("GET", "/api/routing"); } catch (e) { replace(body, h("p", { class: "muted small" }, e.message)); return; }
    const claude = r.route === "claude_code" || r.route === "anthropic";
    const chosen = ((App.settings().task_models || {})[claude ? "claude" : "local"]) || {};
    const selects = {};
    const rows = r.rows.map((row) => {
      let ctl;
      if (row.row === "second" && !claude) ctl = h("span", { class: "muted small" }, "Set under “Second AI model” below.");
      else if (claude) {
        ctl = h("select", { class: "select select-sm", "aria-label": `Model for ${row.title}` }, h("option", { value: "" }, `${row.recommended === "auditor" ? (r.fable ? "fable" : "opus") : row.recommended} (recommended)`),
          r.aliases.map((a) => h("option", { value: a, selected: chosen[row.row] === a }, a)));
        selects[row.row] = ctl;
      } else {
        ctl = h("input", { class: "input input-sm input-mono", type: "text", list: "routing-models", value: chosen[row.row] || "", placeholder: row.recommended === "small" ? "the small model" : "the main model", "aria-label": `Model for ${row.title}` });
        selects[row.row] = ctl;
      }
      const up = !row.step_up ? "none" : (r.route === "claude_code" && ["check", "split", "verify"].includes(row.row) ? `${row.step_up} (auditor)` : row.step_up);
      return h("tr", {}, h("td", {}, row.title), h("td", { class: "mono small" }, row.model || "the main model"), h("td", { class: "mono small" }, up),
        r.route === "claude_code" ? h("td", { class: "mono small" }, row.helper || "") : null, h("td", {}, ctl));
    });
    const small = h("input", { class: "input input-mono", type: "text", list: "routing-models", value: r.local_small_model || "", placeholder: "none: the main model does everything" });
    const one = switchControl("Use the model of each task (recommended)", r.routing, { help: "Off: one model for everything, as in ENLENS 0.7." });
    const saveBtn = h("button", { class: "btn btn-primary btn-sm", type: "button", onClick: async () => {
      const mine = {};
      for (const [k, el] of Object.entries(selects)) if (el.value && el.value.trim()) mine[k] = el.value.trim();
      const all = { ...(App.settings().task_models || {}) };
      if (Object.keys(mine).length) all[claude ? "claude" : "local"] = mine; else delete all[claude ? "claude" : "local"];
      const changes = { task_models: all, routing: one.input.checked };
      if (!claude) changes.local_small_model = small.value.trim();
      try { await save(changes, state); draw(); } catch (_) { /* shown */ }
    } }, icon("check", { size: 13 }), "Save");
    const resetBtn = h("button", { class: "btn btn-sm", type: "button", onClick: async () => {
      const all = { ...(App.settings().task_models || {}) };
      delete all[claude ? "claude" : "local"];
      try { await save({ task_models: all, routing: true }, state); draw(); toast("The recommended models are used again.", "ok"); } catch (_) { /* shown */ }
    } }, icon("refresh", { size: 13 }), "Use the recommended models");
    replace(body,
      h("p", { class: "small" }, `Route now: ${r.route_name}. ${claude ? "Each kind of task starts on the cheapest model that is good enough and goes up one step on its own when it is hard." : "With a small model chosen, labels and links start on it and go up to the main model when they are hard; without one the main model does everything, as in 0.7."}`),
      h("div", { class: "table-wrap" }, h("table", { class: "table routing-table" },
        h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Task"), h("th", { scope: "col" }, "Model"), h("th", { scope: "col" }, "Steps up to"), r.route === "claude_code" ? h("th", { scope: "col" }, "Helper") : null, h("th", { scope: "col" }, "Your choice"))),
        h("tbody", {}, rows))),
      h("datalist", { id: "routing-models" }, chat.map((m) => h("option", { value: m }))),
      claude ? null : field("Small model (labels and links)", small, { help: "A smaller local model for the many label and link tasks. Leave it empty to use the main model for everything." }),
      h("p", { class: "muted small" }, icon("info", { size: 13 }), ` A task goes up to the stronger model once: when its answer's certainty is under ${Math.round(r.step_up_below * 100)}%, when two answers in a row were rejected (a quote not found), or when you press “Ask a stronger model” on a result. Both answers are kept; the stronger model's counts.`),
      r.route === "claude_code" ? null : one,
      h("p", { class: "muted small" }, "The recommended models are the starting points of ENLENS 0.8; the team's runs on the pilot set them (", h("code", {}, "enlens acceptance score --apply"), ")."),
      h("div", { class: "save-row" }, saveBtn, resetBtn, state));
  }
  draw();
  return sectionCard("routing", "AI model per task", "Which model answers each kind of task. Most people never change this.", body);
}

// ---------------------------------------------------------------------------------------------
// A second local chat model for "Ask a second AI model" on results.
function secondModelSection(s, servers) {
  const state = h("span", { class: "save-state", "aria-live": "polite" });
  const main = (s.backend === "openai" ? s.openai_model : s.ollama_model) || "";
  const models = [...new Set(servers.flatMap((x) => x.chat_models || []))].filter((m) => m !== main);
  const current = s.second_model || "";
  const sel = h("select", { class: "select", id: "second-model" }, h("option", { value: "" }, "None (no second opinion)"),
    models.map((m) => h("option", { value: m, selected: m === current }, m)),
    current && !models.includes(current) ? h("option", { value: current, selected: true }, `${current} (not installed now)`) : null);
  const txt = h("input", { class: "input input-mono", type: "text", placeholder: "or type a model name", value: "", "aria-label": "Second model, typed" });
  const saveBtn = h("button", { class: "btn btn-primary btn-sm", type: "button", onClick: async () => {
    const v = txt.value.trim() || sel.value;
    if (v && v === main) { toast("That is the main model. Choose a different one for the second opinion.", "warn"); return; }
    try { await save({ second_model: v }, state); txt.value = ""; toast(v ? `Second AI model: ${v}` : "Second AI model: none", "ok", { ttl: 2500 }); } catch (_) { /* shown */ }
  } }, icon("check", { size: 13 }), "Save");
  return sectionCard("second", "Second AI model", "For “Ask a second AI model” on a result: another chat model on the same server reads the same excerpts, and its judgements are shown beside the main model's. Where the two disagree, the excerpt deserves a careful read. Second judgements never change an answer.",
    h("div", { class: "fields-2" }, field("Second model", sel, { help: models.length ? `Chat models on the server now, apart from the main one (${main || "none chosen"}).` : "No server answered just now, so the installed models could not be listed." }), field("Not listed?", txt, { help: "Type its name as the server knows it, e.g. llama3.1:8b." })),
    h("p", { class: "muted small" }, icon("info", { size: 13 }), " Only one model is kept in memory at a time: the main model is unloaded before the second one reads, and the second one is unloaded when it is done. So a second opinion takes a while, and is best asked for several results at once (under Results)."),
    h("div", { class: "save-row" }, saveBtn, state));
}

// The context length the model is given, and the second sorting pass: for whoever installs the app.
function contextSection(s) {
  const st = App.state || {};
  const state = h("span", { class: "save-state", "aria-live": "polite" });
  const ctxLine = h("div", { class: "notice", style: { marginBottom: "10px" } });
  const drawCtx = () => {
    const c = (App.state && App.state.context) || {};
    const n = c.num_ctx ? fmt.num(c.num_ctx) : "?";
    const k = App.settings().k ?? 8;
    const auto = String(c.setting ?? App.settings().num_ctx ?? "auto").toLowerCase() === "auto";
    replace(ctxLine, icon(c.too_small ? "alert-triangle" : "info"), h("div", {},
      h("p", {}, h("strong", {}, auto ? "Automatic: " : "Fixed: "), `${n} tokens, ${c.too_small ? "which is " : ""}${c.too_small ? "too small for" : "enough for"} ${k} excerpts per check${c.needed ? ` (the largest task needs about ${fmt.num(c.needed)} tokens${c.thinking_allowance ? ", including room for reasoning" : ""})` : ""}.`),
      c.too_small ? h("p", { class: "small" }, "Part of the prompt would be cut off. Choose Automatic, a larger number, or fewer excerpts per check.") : null));
    ctxLine.className = `notice ${c.too_small ? "notice-warn" : "notice-ok"}`;
  };
  drawCtx();
  const isAuto = String(s.num_ctx ?? "auto").toLowerCase() === "auto";
  const mode = h("select", { class: "select", id: "ctx-mode" }, h("option", { value: "auto", selected: isAuto }, "Automatic (recommended)"), h("option", { value: "number", selected: !isAuto }, "A fixed number of tokens"));
  const num = h("input", { class: "input", type: "number", id: "ctx-num", min: 2048, max: 262144, step: 1024, value: isAuto ? 16384 : Number(s.num_ctx), hidden: isAuto });
  const numLabel = h("label", { class: "field-label", for: "ctx-num", hidden: isAuto }, "Tokens");
  const saveCtx = async () => {
    const v = mode.value === "auto" ? "auto" : Math.max(2048, Number(num.value) || 16384);
    try { await save({ num_ctx: v }, state); await App.refresh(); drawCtx(); } catch (_) { /* shown */ }
  };
  mode.addEventListener("change", () => { num.hidden = numLabel.hidden = mode.value !== "number"; if (mode.value === "auto") saveCtx(); else num.focus(); });
  num.addEventListener("change", saveCtx);
  const secondPass = switchControl("Sort the best excerpts again by wording", !!s.second_pass, { help: "After the search, the best candidates are sorted once more by how closely they word the hypothesis (no AI involved). Off by default: on the pilot it did slightly worse, bringing a few fewer excerpts from the cited sources into the top 8 (147 against 154 of 178)." });
  secondPass.input.addEventListener("change", async () => { try { await save({ second_pass: secondPass.input.checked }, state); } catch (_) { /* shown */ } });
  return sectionCard("context", "Context length and search order", "How much text the local model is given at once, and an optional extra sorting step. The defaults suit most computers.",
    ctxLine,
    h("div", { class: "fields-2" }, field("Context length", mode, { help: "Ollama reloads the model when this changes, so it is kept the same between requests. Automatic leaves the most memory to the model: 8,192, 12,288, 16,384 or 32,768 tokens, whichever is the smallest that fits." }), h("div", { class: "field" }, numLabel, num)),
    secondPass,
    h("div", { class: "save-row" }, h("span", { class: "muted small" }, "Saved as soon as you change something."), state));
}

// ---------------------------------------------------------------------------------------------
function embedSection(s, servers) {
  const state = h("span", { class: "save-state", "aria-live": "polite" });
  const kind = h("select", { class: "select" }, [["ollama", "Ollama"], ["openai", "OpenAI-compatible server"], ["off", "Off (keywords only)"]].map(([v, t]) => h("option", { value: v, selected: (s.embed_backend || "ollama") === v }, t)));
  const all = [...new Set(servers.flatMap((x) => x.embedding_models || []))];
  const model = h("input", { class: "input input-mono", type: "text", value: s.embed_model || "", placeholder: "e.g. nomic-embed-text", list: "embed-models" });
  const datalist = h("datalist", { id: "embed-models" }, all.map((m) => h("option", { value: m })));
  const url = h("input", { class: "input input-mono", type: "url", value: s.embed_url || "", placeholder: "optional" });
  const row = h("div", { class: "fields-3" }, field("Server kind", kind), field("Embedding model", model, { help: all.length ? `Installed: ${all.join(", ")}` : "For Ollama: ollama pull nomic-embed-text" }), field("Address (optional)", url, { help: "Leave empty to use the chat server's address." }));
  const toggle = () => { row.querySelectorAll(".field")[1].hidden = row.querySelectorAll(".field")[2].hidden = kind.value === "off"; };
  kind.addEventListener("change", toggle); toggle();
  const form = h("form", { onSubmit: async (e) => { e.preventDefault(); try { await save({ embed_backend: kind.value, embed_model: model.value.trim(), embed_url: url.value.trim() }, state); toast("Saved. Set up search by meaning under Documents if needed.", "ok"); } catch (_) { /* shown */ } } },
    row, datalist, h("div", { class: "save-row" }, h("button", { class: "btn btn-primary", type: "submit" }, icon("check", { size: 14 }), "Save"), state));
  return sectionCard("embeddings", "Search by meaning (embeddings)", "With an embedding model, excerpts are found by meaning as well as by shared words. It is set up per project under Documents.", form);
}

// ---------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------
async function frameworksSection() {
  const project = App.project;
  const list = h("div", {});
  const card = sectionCard("frameworks", "Codebooks", "Optional. A codebook is a list of codes, like in NVivo or Atlas.ti; a hypothesis can be tagged with one code, and the AI reads the code's description alongside it. The UN SDG targets are built in. Add your own as a spreadsheet (CSV) with columns code and description, and optionally group and group_name.", list);
  async function reload() {
    clear(list);
    if (!project) { list.appendChild(h("p", { class: "muted" }, "Create a project first: codebooks belong to a project.")); return; }
    let fws = [];
    try { fws = (await api("GET", `/api/projects/${P(project)}/frameworks`)).frameworks || []; } catch (e) { showError(e); }
    for (const f of fws) {
      list.appendChild(h("div", { class: "fw-row" },
        h("div", { class: "grow" }, h("div", { class: "fw-title" }, f.title || f.name), h("div", { class: "fw-sub" }, `${f.codes} codes · each is called ${/^[aeiouAEIOU]|^SDG/.test(f.label) ? "an" : "a"} “${f.label}” · ${f.source === "bundled" ? "built in" : "added by you"} · short name ${f.name}`),
          f.name === "sdg" ? h("div", { class: "fw-sub" }, "Built in: the 169 targets of the UN Sustainable Development Goals. You can ignore it or add your own.") : null),
        h("button", { class: "btn btn-sm", type: "button", onClick: () => viewFramework(f) }, icon("eye", { size: 13 }), "View codes"),
        f.source !== "bundled" ? h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: async () => {
          const ok = await confirmDialog({ title: `Delete the codebook “${f.title || f.name}”?`, message: "Results tagged with its codes keep the code's text.", confirmText: "Delete" });
          if (!ok) return;
          try { await api("DELETE", `/api/projects/${P(project)}/frameworks/${P(f.name)}`); forgetFrameworks(); toast("Codebook deleted.", "ok"); reload(); } catch (e) { showError(e); }
        } }, icon("trash", { size: 13 }), "Delete") : null));
    }
    list.appendChild(h("div", { style: { marginTop: "10px" } }, h("button", { class: "btn", type: "button", onClick: () => uploadFramework(reload) }, icon("upload", { size: 14 }), "Add a codebook from a spreadsheet (CSV)")));
  }
  async function viewFramework(f) {
    let fw;
    try { fw = await loadFramework(project, f.name); } catch (e) { showError(e); return; }
    const input = h("input", { class: "input", type: "search", placeholder: "Filter…", "aria-label": "Filter codes" });
    const tbl = h("div", { class: "picker-list" });
    const draw = () => {
      clear(tbl);
      const q = input.value.trim().toLowerCase();
      let n = 0;
      for (const i of fw.items || []) {
        if (q && !(`${i.code} ${i.description} ${i.group_name || ""}`.toLowerCase().includes(q))) continue;
        n++;
        tbl.appendChild(h("div", { class: "picker-item", style: { cursor: "default" } }, h("span", { class: "pi-code" }, i.code), h("span", { class: "pi-desc" }, i.description, i.group_name ? h("span", { class: "muted" }, ` — ${i.group_name}`) : null)));
        if (n > 500) break;
      }
      if (!n) tbl.appendChild(h("div", { class: "muted small", style: { padding: "8px" } }, "No code matches."));
    };
    input.addEventListener("input", draw); draw();
    await dialog({ title: fw.title || fw.name, body: h("div", {}, h("p", { class: "muted small" }, `${fw.codes} codes · label “${fw.label}”`), input, tbl), wide: true });
  }
  await reload();
  return card;
}

function uploadFramework(done) {
  const name = h("input", { class: "input", type: "text", placeholder: "e.g. remote", pattern: "[A-Za-z0-9_-]+", maxlength: 30 });
  const title = h("input", { class: "input", type: "text", placeholder: "e.g. Hydrogen value-chain hypotheses" });
  const label = h("input", { class: "input", type: "text", placeholder: "e.g. hypothesis code" });
  const csv = h("textarea", { class: "textarea input-mono", rows: 6, placeholder: "code,description,group,group_name\nR1,Working from home reduces commuting,C,Commuting" });
  const file = h("input", { type: "file", accept: ".csv,text/csv", class: "input" });
  file.addEventListener("change", async () => { const f = file.files && file.files[0]; if (f) { csv.value = await f.text(); if (!name.value) name.value = f.name.replace(/\.csv$/i, "").replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 30); } });
  const err = h("div", { class: "field-error", role: "alert" });
  const directional = switchControl("The codes are aims a text can help or hinder", false, { help: "Like the SDG targets. Labels then also say whether a passage helps the aim, hinders it, or does not say." });
  dialog({
    title: "Add a codebook", wide: true,
    body: h("div", {}, h("div", { class: "fields-3" }, field("Short name", name, { help: "letters, digits, - and _" }), field("Title", title), field("Label", label, { help: "shown before a code" })),
      field("CSV file", file), field("…or paste the CSV", csv), directional, err),
    actions: [{ text: "Cancel", value: null }, { text: "Add", value: true, primary: true, async onClick() {
      err.textContent = "";
      try { await api("POST", `/api/projects/${P(App.project)}/frameworks`, { name: name.value.trim(), csv: csv.value, title: title.value.trim() || undefined, label: label.value.trim() || undefined, directional: directional.input.checked }); forgetFrameworks(); toast("Codebook added.", "ok"); done(); }
      catch (e) { err.textContent = e.message; return false; }
      return true;
    } }],
    onOpen() { name.focus(); },
  });
}

// ---------------------------------------------------------------------------------------------
// 0.7: the defaults of document profiles and themes
function exploreSection(s) {
  const state = h("span", { class: "save-state", "aria-live": "polite" });
  const shortFw = (f) => (f.title && /\(\d+ \w+\)/.test(f.title) ? f.title : `${f.title || f.name} (${f.codes} codes)`);
  const fwSel = h("select", { class: "select", id: "set-profile-fw" }, h("option", { value: s.profile_framework || "sdg", selected: true }, s.profile_framework || "sdg"));
  (async () => {
    if (!App.project) return;
    try {
      const fws = (await api("GET", `/api/projects/${P(App.project)}/frameworks`)).frameworks || [];
      replace(fwSel, ...fws.map((f) => h("option", { value: f.name, selected: f.name === (s.profile_framework || "sdg") }, shortFw(f))));
    } catch (_) { /* keep the saved name */ }
  })();
  fwSel.addEventListener("change", async () => { try { await save({ profile_framework: fwSel.value }, state); } catch (_) { /* shown */ } });
  const k = rangeControl("Themes per set", { min: 2, max: 60, step: 1, value: s.themes_k ?? 20 });
  k.input.addEventListener("change", async () => { try { await save({ themes_k: k.input.valueAsNumber }, state); } catch (_) { /* shown */ } });
  return sectionCard("explore", "Exploring the documents", "The defaults of the Profile and Themes pages. You can change both on those pages too.",
    h("div", { class: "stack", style: { gap: "14px" } },
      field("Codebook of the profiles", fwSel, { help: "Which codes the Profile page and the Codes panel of a document look for, and which codes new documents get when they are added." }),
      h("div", {}, k, h("p", { class: "field-help" }, "How many themes a new set looks for. A small project gets fewer: about three passages a theme at least."))),
    h("div", { class: "save-row" }, h("span", { class: "muted small" }, "Saved as soon as you change something."), state));
}

// the seed that keeps model answers repeatable, and a test of whether the server honours it
function reproSection(s) {
  const state = h("span", { class: "save-state", "aria-live": "polite" });
  const seed = h("input", { class: "input input-mono", type: "number", id: "set-seed", min: 0, max: 2147483647, step: 1, value: s.seed ?? 42 });
  seed.addEventListener("change", async () => {
    const v = Math.round(Number(seed.value));
    if (!Number.isFinite(v) || v < 0 || v > 2147483647) { toast("The seed is a whole number from 0 to 2,147,483,647.", "warn"); return; }
    try { await save({ seed: v }, state); } catch (_) { /* shown */ }
  });
  const out = h("div", { "aria-live": "polite" });
  const test = h("button", { class: "btn", type: "button" }, icon("play", { size: 14 }), "Test: repeatable answers?");
  test.addEventListener("click", async () => {
    test.disabled = true;
    replace(out, h("p", { class: "muted small" }, "Asking the model the same short question twice…"));
    try {
      const r = await api("POST", "/api/servers/repeatable", {});
      replace(out, h("div", { class: `notice ${r.repeatable ? "notice-ok" : "notice-warn"}` }, icon(r.repeatable ? "check" : "alert-triangle"),
        h("div", {}, h("p", {}, h("strong", {}, r.repeatable ? "Repeatable" : "Not guaranteed"), r.model ? ` · ${r.model}` : ""),
          h("p", { class: "small" }, r.note || ""),
          h("p", { class: "small muted" }, `Tested: the same request (search words for a short hypothesis) sent twice, with seed ${App.settings().seed ?? 42} and temperature 0.${r.digest ? ` Exact version: ${String(r.digest).slice(0, 19)}…` : ""} It says whether this server repeats itself; the version and settings behind each result are in “How these results were made” in every Excel download and under Technical details on the Profile page.`))));
    } catch (e) { replace(out); showError(e); }
    test.disabled = false;
  });
  return sectionCard("repeatable", "Repeatable results", "Every model request is sent with a fixed seed and temperature 0, and every result records the model and, when the server reports it, its exact version (the digest), so the same documents and settings give the same answers. Whether a server honours the seed differs: test it here.",
    h("div", { class: "fields-2" },
      field("Seed", seed, { help: "Any whole number. Changing it can change the answers; it is shown in “How these results were made”." })),
    h("div", { class: "save-row" }, test, state),
    out);
}

// ---------------------------------------------------------------------------------------------
function testSection(s) {
  const ref = h("input", { class: "input input-mono", type: "text", value: s.benchmark_reference || "", placeholder: "/path/to/pilot" });
  const n = rangeControl("Tasks per kind", { min: 5, max: 50, step: 5, value: 10 });
  const kVerify = h("input", { type: "checkbox", checked: true, id: "k-verify" });
  const kExtract = h("input", { type: "checkbox", id: "k-extract" });
  const kLabel = h("input", { type: "checkbox", id: "k-label" });
  const out = h("div", { "aria-live": "polite", style: { marginTop: "10px" } });
  const run = h("button", { class: "btn btn-primary", type: "button" }, icon("play", { size: 14 }), "Run test");
  let watcher = null;
  run.addEventListener("click", async () => {
    const kinds = [kVerify.checked && "verify_set", kExtract.checked && "extract", kLabel.checked && "label"].filter(Boolean);
    if (!ref.value.trim() || !kinds.length) { toast("Give the reference folder and tick at least one task kind.", "warn"); return; }
    run.disabled = true;
    try {
      const r = await api("POST", "/api/benchmark", { reference: ref.value.trim(), kinds, n: n.input.valueAsNumber });
      follow(r.job.id);
    } catch (e) { showError(e); run.disabled = false; }
  });
  function follow(jobId) {
    const holder = h("div", { class: "card card-plain" }, h("div", { class: "card-head" }, h("h3", {}, "Testing"), h("button", { class: "btn btn-sm btn-outline-danger", type: "button", onClick: () => api("POST", `/api/jobs/${P(jobId)}/cancel`).catch(showError) }, icon("stop", { size: 13 }), "Stop")), h("div", { class: "pb" }));
    replace(out, holder);
    watcher = watchJob(jobId, (job) => {
      const p = job.progress || {};
      replace(holder.querySelector(".pb"), simpleProgress(job, () => p.total ? `Task ${Math.min((p.done || 0) + 1, p.total)} of ${p.total}${p.task ? " · " + p.task : ""}` : "Starting…"),
        p.model && p.model.line ? h("div", { class: "model-line", style: { marginTop: "8px" } }, h("div", { class: "ml-head" }, icon("cpu", { size: 14 }), h("span", {}, p.model.line))) : null);
      if (TERMINAL.has(job.state)) { const b = holder.querySelector(".btn-outline-danger"); if (b) b.hidden = true; }
    });
    watcher.promise.then((job) => {
      run.disabled = false;
      if (job.state === "done") drawResult(holder, job.result || {});
      else if (job.state === "error") replace(holder.querySelector(".pb"), h("div", { class: "notice notice-error" }, icon("alert-circle"), h("p", {}, job.error || "The test failed.")));
      else replace(holder.querySelector(".pb"), h("p", { class: "muted" }, "Stopped."));
    }).catch((e) => { run.disabled = false; showError(e); });
  }
  function drawResult(holder, r) {
    const cols = r.table && r.table.length ? Object.keys(r.table[0]).filter((c) => c !== "measure") : [];
    replace(holder.querySelector(".pb"),
      h("p", {}, h("strong", {}, `${r.model || ""}`), h("span", { class: "muted" }, ` (${r.backend || ""})`)),
      h("ul", { style: { paddingLeft: "1.2em" } }, (r.verdict || []).map((l) => h("li", {}, l))),
      cols.length ? h("div", { class: "table-wrap" }, h("table", { class: "table bench-table" }, h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Measure"), cols.map((c) => h("th", { scope: "col", class: "num" }, c)))),
        h("tbody", {}, (r.table || []).map((row) => h("tr", {}, h("td", {}, row.measure), cols.map((c) => h("td", { class: "num" }, String(row[c] ?? "–")))))))) : null,
      h("div", { class: "btn-row", style: { marginTop: "10px" } }, h("button", { class: "btn btn-sm", type: "button", onClick: () => {
        const blob = new Blob([JSON.stringify(r, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob); const a = h("a", { href: url, download: `benchmark_${(r.model || "model").replace(/[^A-Za-z0-9_-]/g, "_")}.json` }); document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 2000);
      } }, icon("download", { size: 13 }), "Download the full result")));
  }
  return sectionCard("test", "Test a model before trusting it", "For technical users. It compares the chosen local model with reference answers saved in a project (for the pilot, those were made earlier with Claude Opus 5.5). Nothing is sent anywhere and nothing is stored. This measures agreement with the reference, not correctness.",
    field("Reference workspace folder", ref, { help: "For example the pilot folder that ships with the package." }),
    h("div", { class: "fields-2" }, n, h("div", { class: "field" }, h("span", { class: "field-label" }, "Tasks"), h("label", { class: "it", for: "k-verify" }, kVerify, " Checking claims"), h("label", { class: "it", for: "k-extract" }, kExtract, " Extracting claims"), h("label", { class: "it", for: "k-label" }, kLabel, " Labelling with codes"))),
    h("div", { class: "save-row" }, run, App.settings().backend === "anthropic" ? h("span", { class: "muted small" }, "With the Claude API this is billed: one call per task.") : null),
    out);
}

// 0.10.1: the version, on every Settings tab; it opens Technical → Where your data is, which says how this copy was
// installed and how to update it
function versionTag() {
  const st = App.state || {};
  const v = st.version || VERSION;
  if (!v) return null;
  return h("a", { class: "version-tag", href: "#/settings/data", title: "How ENLENS was installed and how to update it (Technical)" },
    icon("info", { size: 14 }), h("span", {}, "Version ", h("strong", {}, v)));
}

// 0.10: how this copy was installed, and how it is updated
function installedWith(inst) {
  if (!inst || !inst.kind) return null;
  const how = { git: ["from a git copy", "Update: enlens update"], script: ["with the one-line install", "Update: run the install line again (or enlens update)"],
    package: ["from the download for this system", "Update: download the newest version"], pip: ["with pip", "Update: pip install --upgrade, or switch to the one-line install"] }[inst.kind];
  return h("div", { class: "muted small", style: { fontWeight: 400 } }, `Installed ${how[0]}. ${how[1]}.`);
}

// ---------------------------------------------------------------------------------------------
function dataSection() {
  const st = App.state || {};
  const ocr = st.ocr || {};
  return sectionCard("data", "Where your data is", "Everything the app keeps lives in one folder on this computer.",
    h("dl", { class: "kv-grid" },
      h("div", { class: "kv" }, h("dt", {}, "Data folder"), h("dd", {}, h("code", { class: "path", title: st.home || "" }, ...String(st.home || "").split(/(?<=[\/\\])/).flatMap((seg) => [seg, h("wbr")])))),
      h("div", { class: "kv" }, h("dt", {}, "Projects"), h("dd", {}, `${(st.projects || []).length}`, " · ", h("a", { href: "#/projects" }, "manage"))),
      h("div", { class: "kv" }, h("dt", {}, "Version"), h("dd", {}, `ENLENS ${st.version || VERSION}`, installedWith(st.installation))),
      h("div", { class: "kv" }, h("dt", {}, "Network"), h("dd", {}, "This computer only · nothing is loaded from the internet")),
      h("div", { class: "kv" }, h("dt", {}, "Text recognition (OCR) for scanned PDFs"), h("dd", {}, ocr.available ? `installed (Tesseract${ocr.languages && ocr.languages.length ? `, languages: ${ocr.languages.join(", ")}` : ""})`
        : ["not available", ocr.missing && ocr.missing.length ? h("div", { class: "muted small", style: { fontWeight: 400 } }, `Missing: ${ocr.missing.map((m) => ({ tesseract: "the Tesseract program (tesseract-ocr)", pypdfium2: "the Python package pypdfium2", pillow: "the Python package pillow" }[m] || m)).join("; ")}.${ocr.missing.includes("tesseract") ? " How to get Tesseract: Settings → Documents." : ""}${ocr.missing.some((m) => m !== "tesseract") ? " The Python parts: pip install 'enlens-claims[ocr]', then restart the app." : ""}`) : null]))),
    h("p", { class: "muted small", style: { marginTop: "12px" } }, "Each project is a folder with a database, the added files and the settings. Removed projects go to a trash folder inside the data folder."));
}

// ---------------------------------------------------------------------------------------------
// 0.9: setting up Claude Code, as a checklist: Claude Code found, signed in, the ENLENS plugin added.
// 0.10: one button, "Set up Claude", does every step it can, in order, and skips what is done: it installs Claude Code
// with Anthropic's installer (after the person has seen and confirmed the command), opens a window where the person
// signs in with their Claude plan (ENLENS never sees the login) and waits for it, then adds the plugin. Doing it by
// hand stays one fold below. Used in Settings → AI and on the first-run page.
export function claudeSetupCard(opts = {}) {
  const box = h("div", { class: "card card-plain cc-card", style: { padding: "14px 16px" } }, h("p", { class: "muted small" }, "Looking for Claude Code on this computer…"));
  const log = h("div", { class: "cc-progress", "aria-live": "polite" });
  let info = { status: {}, commands: [] };
  let busy = false;
  let stopWaiting = null;
  const step = (ok, title, text) => h("li", { class: `cc-step ${ok === true ? "ok" : ok === false ? "bad" : ""}` },
    h("span", { class: "cc-mark", "aria-hidden": "true" }, ok === true ? icon("check", { size: 12 }) : ok === false ? "!" : "?"),
    h("div", {}, h("strong", {}, title), text ? h("span", { class: "small" }, text) : null));
  const say = (...children) => replace(log, h("div", { class: "cc-now" }, ...children));
  const working = (text) => say(h("span", { class: "spinner" }, icon("loader", { size: 13 })), h("span", {}, text));
  const fresh = async () => { info = await api("GET", "/api/claude-setup?refresh=1"); return info.status || {}; };

  async function installClaudeCode() {
    const line = info.installer || "curl -fsSL https://claude.ai/install.sh | bash";
    const ok = await confirmDialog({
      title: "Install Claude Code?", confirmText: "Install Claude Code", danger: false,
      message: h("div", { class: "stack", style: { gap: "10px" } },
        h("p", {}, "Claude Code is the program that lets Claude work on your own Claude plan. ENLENS will run Anthropic's installer for it, which downloads Claude Code from claude.ai and puts it in your user folder. It needs no administrator rights and takes a minute or two."),
        h("p", { class: "small muted" }, "The command it runs:"), copyLine(line, "Copy", "a terminal"),
        h("p", { class: "small muted" }, "Prefer to do it yourself? Follow ", h("a", { href: info.docs || "https://code.claude.com/docs/en/setup", target: "_blank", rel: "noopener" }, "Anthropic's set-up page"), ", then press Set up Claude again.")),
    });
    if (!ok) { replace(log); return false; }
    working("Installing Claude Code… (a minute or two)");
    const r = await api("POST", "/api/claude-setup/claude-code", {});
    const job = await watchJob(r.job.id, null, 1000).promise;
    if (job.state !== "done") {
      say(icon("alert-circle", { size: 14 }), h("div", {}, h("p", {}, "Claude Code could not be installed from here."),
        h("p", { class: "small" }, "Install it with ", h("a", { href: info.docs || "https://code.claude.com/docs/en/setup", target: "_blank", rel: "noopener" }, "Anthropic's set-up page"), ", then press Set up Claude again."),
        job.error ? h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("div", { class: "mono small" }, job.error)) : null));
      return false;
    }
    return true;
  }

  // Opens the sign-in window and waits (checking every few seconds) until Claude Code says it is signed in.
  async function signIn() {
    let opened = { opened: false };
    try { opened = await api("POST", "/api/claude-setup/sign-in", {}); } catch (e) { opened = { opened: false, error: e.message }; }
    return new Promise((resolve) => {
      let timer = null;
      let done = false;
      const finish = (v) => { if (done) return; done = true; clearTimeout(timer); stopWaiting = null; resolve(v); };
      stopWaiting = () => finish(false);
      const checkNow = h("button", { class: "btn btn-sm", type: "button", onClick: () => poll(true) }, "I have signed in");
      const cancel = h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => { finish(false); replace(log); } }, "Stop waiting");
      say(h("span", { class: "spinner" }, icon("loader", { size: 13 })), h("div", {},
        opened.opened ? h("p", {}, `A ${opened.window} window opened with Claude Code. Sign in there with your Claude plan (it opens a page in your browser), then close that window. ENLENS is waiting and continues by itself.`)
          : h("div", {}, h("p", {}, "Sign in to Claude Code once: open a terminal (Terminal on a Mac, PowerShell on Windows), type the line below, and follow the steps."), copyLine("claude", "Copy", "a terminal")),
        h("p", { class: "small muted" }, "ENLENS never sees your login: Claude Code keeps it."),
        h("div", { class: "btn-row", style: { marginTop: "6px" } }, checkNow, cancel)));
      const started = Date.now();
      async function poll(now) {
        clearTimeout(timer);
        if (done) return;
        if (!box.isConnected && !now) { finish(false); return; }
        let st = {};
        try { st = await fresh(); } catch (_) { /* try again */ }
        if (st.signed_in === true) { finish(true); return; }
        if (now && st.signed_in !== false) { finish(true); return; }  // Claude Code does not say: carry on
        if (now) toast("Claude Code does not say it is signed in yet. Finish signing in, then press the button again.", "warn");
        if (Date.now() - started > 15 * 60 * 1000) { finish(false); replace(log, h("p", { class: "small" }, "Stopped waiting for the sign-in. Press Set up Claude again when you have signed in.")); return; }
        timer = setTimeout(() => poll(false), 4000);
      }
      timer = setTimeout(() => poll(false), 4000);
    });
  }

  async function addPlugin() {
    working("Adding the ENLENS plugin to Claude Code…");
    const r = await api("POST", "/api/claude-setup", {});
    info = { ...info, ...r };
    const bad = (r.steps || []).filter((x) => !x.ok);
    if (bad.length) {
      say(icon("alert-circle", { size: 14 }), h("div", {}, h("p", {}, "The plugin could not be added: ", bad[0].step),
        h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("div", { class: "mono small" }, bad[0].text))));
      return false;
    }
    return true;
  }

  async function setUp() {
    if (busy) return;
    busy = true;
    draw(true);
    const now = async () => { const st = await fresh(); draw(true); return st; };  // the checklist follows each step
    let ok = true;
    try {
      working("Checking what is ready…");
      let st = await now();
      if (!st.found) {
        ok = (await installClaudeCode()) && (st = await now()).found;
      }
      if (ok && st.signed_in === false) {
        ok = await signIn();
        if (ok) st = await now();
      }
      if (ok && (!st.ready || st.installed !== true)) {
        ok = await addPlugin();
        if (ok) st = await fresh();
      }
      if (ok) { replace(log); if (st.ready) toast("Claude is set up.", "ok"); }
    } catch (e) { replace(log); showError(e); ok = true; }
    busy = false;
    draw(!ok);
  }

  function draw(keepLog) {
    const st = info.status || {};
    const ready = !!st.ready && st.signed_in !== false;
    if (ready && opts.onReady) opts.onReady();
    if (!keepLog && !busy) replace(log);
    const btn = h("button", { class: `btn ${ready ? "btn-sm" : "btn-primary"}`, type: "button", disabled: busy, onClick: () => (ready ? fresh().then(() => draw()).catch(showError) : setUp()) },
      icon(ready ? "refresh" : "zap", { size: 14 }), ready ? "Check again" : "Set up Claude");
    const manual = h("details", { class: "fold" }, h("summary", {}, "Set it up yourself instead"),
      h("ol", { class: "cc-manual small" },
        h("li", {}, "Install Claude Code (", h("a", { href: info.docs || "https://code.claude.com/docs/en/setup", target: "_blank", rel: "noopener" }, "Anthropic's set-up page"), "), in a terminal:", info.installer ? copyLine(info.installer, "Copy", "a terminal") : null),
        h("li", {}, "Sign in once: type ", h("code", {}, "claude"), " in a terminal and follow the steps."),
        (info.commands || []).length ? h("li", {}, "Add the ENLENS plugin with these two lines in a terminal, then restart Claude Code:", info.commands.map((c) => copyLine(c, "Copy", "a terminal"))) : null));
    replace(box,
      h("div", { class: "field-label" }, ready ? "Claude is ready" : "Set up Claude (once)"),
      h("ol", { class: "cc-steps" },
        step(st.found ? true : busy ? null : false, "Claude Code on this computer", st.found ? (st.version || "found") : "Not on this computer yet. The button installs it with Anthropic's installer (it shows you the command first)."),
        step(st.signed_in === true ? true : st.signed_in === false ? false : null, "Signed in with your Claude plan",
          st.signed_in === true ? "Pro, Max, Team or Enterprise" : st.signed_in === false ? "Not yet. The button opens a window where you sign in once." : "Claude Code asks you to sign in once; the button opens the window for it."),
        step(st.installed === true ? true : st.found ? false : null, "The ENLENS plugin added to Claude Code",
          st.installed ? "It adds /enlens-run, its helpers and the ENLENS connector." : "The button adds it (nothing else in Claude Code is changed).")),
      h("div", { class: "btn-row" }, btn),
      log,
      h("p", { class: "muted small", style: { marginTop: "10px" } }, "Then press ", h("strong", {}, "Start Claude Code"), " wherever work waits (or in the sidebar): ENLENS starts Claude Code in the background on this project's work, and the results appear as they come in. You can also type ", h("code", {}, `/enlens-run ${App.project || "<project>"}`), " in Claude Code yourself."),
      manual);
  }
  api("GET", "/api/claude-setup").then((r) => { info = r; draw(); }).catch(() => draw());
  return box;
}
