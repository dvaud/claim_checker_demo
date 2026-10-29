// Settings: model service, embeddings, check defaults, frameworks, model test, data folder.
import { App, api, h, icon, replace, clear, toast, showError, fmt, pageHead, watchJob, P, field, switchControl, rangeControl, confirmDialog, dialog, download, VERSION, session, TERMINAL, strictness, statusBadge, copyLine } from "../lib.js";
import { forgetFrameworks, loadFramework } from "./options.js";
import { simpleProgress } from "./progress.js";

export async function renderSettings(view, [section]) {
  const s = { ...App.settings() };
  let servers = [];
  try { servers = (await api("GET", "/api/servers")).servers || []; } catch (_) { servers = []; }

  view.appendChild(pageHead("Settings", { sub: "The basics are all most people need. Everything technical is under Advanced." }));
  const scrollTo = (id) => { const t = document.getElementById(`s-${id}`); if (!t) return; const adv = t.closest("details"); if (adv) adv.open = true; t.scrollIntoView({ behavior: "smooth", block: "start" }); const hd = t.querySelector("h2"); if (hd) hd.focus(); };
  const nav = h("nav", { class: "settings-nav", "aria-label": "Settings sections" },
    [["basics", "Basics"], ["explore", "Exploring"], ["frameworks", "Codebooks"], ["advanced", "Advanced"]].map(([id, label]) => h("a", { href: `#/settings/${id}`, onClick: (e) => { e.preventDefault(); history.replaceState(null, "", `#/settings/${id}`); scrollTo(id); } }, label)));
  const main = h("div", { class: "stack", style: { gap: "20px" } });
  view.appendChild(h("div", { class: "settings-layout" }, nav, main));

  const advanced = h("details", { class: "fold settings-section", id: "s-advanced" },
    h("summary", {}, h("h2", { tabindex: "-1", style: { display: "inline" } }, "Advanced (for IT staff)"), h("span", { class: "muted small", style: { marginLeft: "8px" } }, "AI model service, search by meaning, model test, data folder")),
    h("p", { class: "muted", style: { margin: "8px 0 0" } }, "Settings for whoever installs the app. You don't need to change anything here."),
    h("div", { class: "stack", style: { gap: "20px", marginTop: "12px" } }, modelSection(s, servers), routingSection(s, servers), secondModelSection(s, servers), contextSection(s), embedSection(s, servers), reproSection(s), testSection(s), dataSection()));
  main.append(basicsSection(s), exploreSection(s), await frameworksSection(), advanced);
  if (section) {
    const adv = ["model", "routing", "second", "context", "embeddings", "repeatable", "test", "data", "advanced"].includes(section);
    if (adv) advanced.open = true;
    setTimeout(() => { const t = document.getElementById(`s-${section}`); if (t) t.scrollIntoView({ block: "start" }); }, 50);
  }
}

// ---------------------------------------------------------------------------------------------
function basicsSection(s) {
  const p = App.privacy();
  const state = h("span", { class: "save-state", "aria-live": "polite" });
  const strictState = h("span", { class: "save-state", "aria-live": "polite" });
  const testOut = h("div", { class: "test-result", "aria-live": "polite" });
  const testBtn = h("button", { class: "btn", type: "button" }, icon("zap", { size: 14 }), "Test the AI model");
  testBtn.addEventListener("click", async () => {
    testBtn.disabled = true;
    replace(testOut, h("div", { class: "notice" }, h("span", { class: "spinner" }, icon("loader")), h("p", {}, "Asking the AI model for a short answer…")));
    try {
      const r = await api("POST", "/api/servers/test");
      replace(testOut, plainTestResult(r));
    } catch (e) {
      replace(testOut, h("div", { class: "notice notice-error" }, icon("alert-circle"), h("div", {}, h("p", {}, h("strong", {}, "Not working. "), "The AI model is not answering. Whoever set up the app for you can fix this under Advanced."), h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("div", { class: "mono small" }, e.message)))));
    }
    testBtn.disabled = false;
  });
  const modelRow = h("div", { class: `privacy privacy-${p.where} privacy-wide` }, icon(p.icon, { size: 18 }),
    h("div", {}, h("strong", {}, p.label), h("span", {}, p.plain), h("div", { class: "muted small", style: { marginTop: "2px" } }, p.where === "local" ? "Set up by whoever installed the app. Which model it is, and how to change it, is under Advanced." : "Which model it is, and how to change it, is under Advanced.")));

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
  const ocr = ocrBlock(s);
  const saveDefaults = async () => { try { await save({ k: k.input.valueAsNumber, per_doc: perDoc.input.valueAsNumber, expand: expand.input.checked, decompose: decompose.input.checked }, state); } catch (_) { /* shown */ } };
  for (const c of [k.input, perDoc.input, expand.input, decompose.input]) c.addEventListener("change", saveDefaults);
  const form = h("div", {},
    h("div", { class: "fields-2" }, h("div", {}, expand, decompose), h("div", {}, k, perDoc)),
    h("div", { class: "save-row" }, h("span", { class: "muted small" }, "Saved as soon as you change something. New checks start with these; each check can still change them under More options."), state));
  const secondSet = (s.second_model || "").trim();
  return sectionCard("basics", "Basics", "",
    h("h3", { style: { marginBottom: "6px" } }, "The AI model"),
    modelRow,
    h("div", { class: "btn-row", style: { margin: "10px 0 4px" } }, testBtn, h("span", { class: "muted small" }, "Change the model under Advanced.")),
    testOut,
    h("p", { class: "muted small", style: { margin: "8px 0 0" } }, icon("cpu", { size: 13 }), secondSet ? " A second AI model is set up for “Ask a second AI model” on results. " : " No second AI model is set up yet; “Ask a second AI model” on results needs one. ", h("a", { href: "#/settings/second", onClick: (e) => { e.preventDefault(); history.replaceState(null, "", "#/settings/second"); const t = document.getElementById("s-second"); if (t) { const adv = t.closest("details"); if (adv) adv.open = true; t.scrollIntoView({ behavior: "smooth", block: "start" }); const hd = t.querySelector("h2"); if (hd) hd.focus(); } } }, "Choose it under Advanced")),
    h("h3", { style: { margin: "22px 0 6px" } }, "Strictness"),
    strictForm,
    h("h3", { style: { margin: "22px 0 6px" } }, "How new checks start"),
    form,
    h("h3", { style: { margin: "22px 0 6px" } }, "Reading scanned PDFs"),
    ocr);
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
    box.appendChild(h("div", { class: "notice notice-warn", style: { marginBottom: "10px" } }, icon("alert-triangle"), h("div", {}, h("p", {}, h("strong", {}, "To read scanned PDFs, ask IT to install Tesseract."), " Until then, scanned pages stay without text and a wholly scanned PDF cannot be added. What is missing is listed under Advanced."))));
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
  const labels = (App.state && App.state.backend_labels) || {};
  const subs = { auto: "The first local server found: Ollama, then LM Studio, llama.cpp, Jan, vLLM.", ollama: "A model served by Ollama on this computer.", openai: "LM Studio, llama.cpp, Jan, vLLM… at a local address.", anthropic: "The excerpts read are sent to Anthropic's servers, billed to the team's API key. For a shared installation.", claude_code: "Claude Code, signed in with your own Claude plan, reads the excerpts; ENLENS prepares the work and checks every quote.", baseline: "No AI: a word-overlap stand-in. For trying the app only; its results are not findings." };
  const icons = { auto: "house", ollama: "house", openai: "house", anthropic: "cloud", claude_code: "cloud", baseline: "cpu" };
  let allowCC = !!s.allow_claude_code;
  const state = h("span", { class: "save-state", "aria-live": "polite" });
  const radios = h("div", { class: "radio-cards", role: "radiogroup", "aria-label": "Model service, on this computer" });
  let radiosWrap = null;
  const detail = h("div", {});
  let backend = s.backend || "auto";
  const allowCloud = switchControl("Allow cloud models", !!s.allow_cloud, { help: "" });
  const cloudBox = h("div", { class: "cloud-box" }, allowCloud, h("p", {}, icon("alert-triangle", { size: 13 }), " With a cloud model the hypothesis and the excerpts read leave this computer and are billed to your key. Local models never send anything."));
  allowCloud.input.addEventListener("change", () => { if (backend !== "anthropic" && !allowCloud.input.checked) cloudBox.remove(); });

  const cloudGroup = h("div", { class: "cloud-group" }, h("div", { class: "cloud-group-title" }, icon("cloud", { size: 14 }), "Not on this computer"),
    h("p", { class: "small", style: { margin: "0 0 8px" } }, "Excerpts of your documents would be sent to Anthropic's servers. You will be asked to confirm."));
  for (const key of ["auto", "ollama", "openai", "baseline", "claude_code", "anthropic"]) {
    const input = h("input", { type: "radio", name: "backend", value: key, checked: backend === key });
    input.addEventListener("change", async () => {
      if (key === "claude_code" && backend !== "claude_code") {
        const ok = await dialog({
          title: "Let Claude Code read the excerpts, on your own Claude plan?",
          body: h("div", {}, h("p", {}, "The AI buttons of ENLENS then prepare tasks instead of asking a model. You run Claude Code yourself and type /enlens-run there; it takes the tasks in small batches."),
            h("p", {}, h("strong", {}, "The passages inside the tasks Claude Code takes are sent to Anthropic."), " Your documents, results and reviews stay on this computer, and every answer is checked here against the text."),
            h("p", { class: "muted small" }, "ENLENS never starts Claude Code, never sees your Claude login and never runs on anyone else's plan. Nothing is sent before you save and run /enlens-run.")),
          actions: [{ text: "Keep the AI on this computer", value: false, primary: true, id: "dlg-safe" }, { text: "Use Claude Code", value: true }],
          onOpen(dlg) { const b = dlg.querySelector("#dlg-safe"); if (b) b.focus(); },
        });
        if (!ok) { const prev = radiosWrap.querySelector(`input[value="${backend}"]`); if (prev) prev.checked = true; return; }
        allowCC = true;
      }
      if (key === "anthropic" && backend !== "anthropic") {
        const ok = await dialog({
          title: "Use a cloud AI instead of the one on this computer?",
          body: h("div", {}, h("p", {}, "With the Claude API, the hypothesis and the excerpts of your documents that the AI reads are sent to Anthropic's servers on the internet, and the use is billed to an account key."),
            h("p", {}, "Until now everything stayed on this computer. Results you already have are not sent anywhere."),
            h("p", { class: "muted small" }, "Nothing is sent before you also switch on “Allow cloud models”, enter a key and save.")),
          actions: [{ text: "Keep the AI on this computer", value: false, primary: true, id: "dlg-safe" }, { text: "Continue with the cloud option", value: true }],
          onOpen(dlg) { const b = dlg.querySelector("#dlg-safe"); if (b) b.focus(); },
        });
        if (!ok) { const prev = radiosWrap.querySelector(`input[value="${backend}"]`); if (prev) prev.checked = true; return; }
      }
      backend = key; drawDetail();
    });
    const cloudish = key === "anthropic" || key === "claude_code";
    const cardEl = h("label", { class: "radio-card" + (cloudish ? " radio-card-cloud" : "") }, input, h("span", {}, h("span", { class: "rc-title it" }, icon(icons[key], { size: 14 }), labels[key] || key), h("span", { class: "rc-sub" }, subs[key])));
    if (cloudish) cloudGroup.appendChild(cardEl); else radios.appendChild(cardEl);
  }
  const lockedLine = h("p", { class: "muted small", style: { marginTop: "10px" } }, icon("shield", { size: 13 }), " Cloud models are switched off on this computer by whoever installed ENLENS.");
  radiosWrap = h("div", {}, h("div", { class: "muted small", style: { margin: "0 0 6px" } }, "On this computer"), radios, App.state && App.state.local_only ? lockedLine : cloudGroup);

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
    if (backend !== "anthropic" && allowCloud.input.checked) detail.append(cloudBox);
    if (backend === "auto") {
      detail.append(serverList(), h("p", { class: "muted small" }, "The first server found is used. If a chat model is named below for Ollama or an OpenAI-compatible server, it is preferred when that server has it."),
        fields.ollamaModel = modelPicker("m-ollama", s.ollama_model, ollamaSrv ? ollamaSrv.chat_models : [], "e.g. qwen3:8b"), thinkRow());
      fields.ollamaModel.querySelector(".field-label").textContent = "Preferred Ollama model";
    } else if (backend === "ollama") {
      detail.append(serverList(), h("div", { class: "fields-2" }, field("Ollama address", fields.ollama_url), fields.ollamaModel = modelPicker("m-ollama", s.ollama_model, ollamaSrv ? ollamaSrv.chat_models : [], "e.g. qwen3:8b")),
        thinkRow(), h("p", { class: "muted small" }, "Context length: set automatically; see “Context length and search order” below."));
    } else if (backend === "openai") {
      detail.append(serverList(), h("div", { class: "fields-2" }, field("Server address", fields.openai_url, { help: "The /v1 base URL of LM Studio, llama.cpp, Jan, vLLM…" }), fields.openaiModel = modelPicker("m-openai", s.openai_model, openaiSrv ? openaiSrv.chat_models : [], "leave empty for the first model listed")));
    } else if (backend === "anthropic") {
      detail.append(cloudBox, field("Model for judging excerpts", fields.anthropic_model, { help: "For example claude-opus-5-5. The other kinds of task use their own model: see “AI model per task” below." }), keyBox(), fableSwitch());
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

  // Claude Code: what the researcher does once (the plugin), and how a run is started.
  function claudeCodeBox() {
    const box = h("div", { class: "card card-plain", style: { padding: "12px 14px" } });
    const draw = (info) => {
      replace(box,
        h("div", { class: "field-label" }, "Set up Claude Code (once)"),
        info.ready ? h("div", { class: "notice notice-ok", style: { margin: "6px 0 10px" } }, icon("circle-check"), h("p", {}, "The ENLENS plugin is prepared for this installation. If you have not added it to Claude Code yet, type these two lines in a terminal:"))
          : h("p", { class: "small" }, "Claude Code needs the ENLENS plugin: it adds the /enlens-run command, the helpers and the ENLENS connector. Prepare it here (or type ", h("code", {}, "enlens claude-setup"), " in a terminal), then type the two lines it shows."),
        info.ready ? h("div", {}, info.commands.map((c) => copyLine(c))) : h("button", { class: "btn btn-sm", type: "button", onClick: async () => {
          try { const r = await api("POST", "/api/claude-setup", {}); if (r.problems && r.problems.length) toast(r.problems.join("; "), "warn"); draw(r); } catch (e) { showError(e); }
        } }, icon("download", { size: 13 }), "Prepare the plugin"),
        h("p", { class: "muted small", style: { marginTop: "8px" } }, "Then restart Claude Code. To run the work an AI button prepared, open Claude Code in any folder and type ", h("code", {}, `/enlens-run ${App.project || "<project>"}`), ". You follow the progress here. A run can stop at any moment (a usage limit, a closed laptop); the next /enlens-run continues where it stopped."),
        h("p", { class: "muted small" }, icon("shield", { size: 13 }), " ENLENS never starts Claude Code, never sees your Claude login, and writes nothing to Claude Code's settings."));
    };
    api("GET", "/api/claude-setup").then(draw).catch(() => draw({ ready: false, commands: [] }));
    return h("div", { class: "stack", style: { gap: "10px" } },
      h("div", { class: "cloud-box" }, h("p", {}, icon("alert-triangle", { size: 13 }), " With Claude Code the passages inside the tasks it takes are sent to Anthropic, on your own Claude plan. Your documents, results and reviews stay here.")),
      box);
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
  const form = h("form", { onSubmit: async (e) => { e.preventDefault(); try { await save(collect(), state); Object.assign(s, App.settings()); toast(`Model service: ${App.state.backend_label}`, "ok"); } catch (_) { /* shown */ } } },
    radiosWrap, detail, h("div", { class: "save-row" }, saveBtn, testBtn, state));
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
  return sectionCard("model", "AI model service", "Which model reads and judges the excerpts. Local servers keep every word on this computer.", form, testOut);
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

// ---------------------------------------------------------------------------------------------
function dataSection() {
  const st = App.state || {};
  const ocr = st.ocr || {};
  return sectionCard("data", "Where your data is", "Everything the app keeps lives in one folder on this computer.",
    h("dl", { class: "kv-grid" },
      h("div", { class: "kv" }, h("dt", {}, "Data folder"), h("dd", {}, h("code", { class: "path", title: st.home || "" }, ...String(st.home || "").split(/(?<=[\/\\])/).flatMap((seg) => [seg, h("wbr")])))),
      h("div", { class: "kv" }, h("dt", {}, "Projects"), h("dd", {}, `${(st.projects || []).length}`, " · ", h("a", { href: "#/projects" }, "manage"))),
      h("div", { class: "kv" }, h("dt", {}, "Version"), h("dd", {}, `ENLENS ${st.version || VERSION}`)),
      h("div", { class: "kv" }, h("dt", {}, "Network"), h("dd", {}, "This computer only · nothing is loaded from the internet")),
      h("div", { class: "kv" }, h("dt", {}, "Text recognition (OCR) for scanned PDFs"), h("dd", {}, ocr.available ? `installed (Tesseract${ocr.languages && ocr.languages.length ? `, languages: ${ocr.languages.join(", ")}` : ""})`
        : ["not available", ocr.missing && ocr.missing.length ? h("div", { class: "muted small", style: { fontWeight: 400 } }, `Missing: ${ocr.missing.map((m) => ({ tesseract: "the Tesseract program (tesseract-ocr)", pypdfium2: "the Python package pypdfium2", pillow: "the Python package pillow" }[m] || m)).join("; ")}. Install them, then restart the app.`) : null]))),
    h("p", { class: "muted small", style: { marginTop: "12px" } }, "Each project is a folder with a database, the added files and the settings. Removed projects go to a trash folder inside the data folder."));
}
