// 0.11: who may read each document with AI. The three settings, the question asked when documents are added (and
// once for a project that has none), the setting of each document on the Documents page, what Claude has read of a
// document, and the panel "What happens to the text Claude reads" (Set up Claude, Settings → AI).
import { App, api, h, icon, replace, toast, showError, fmt, P, dialog, button, iconButton, link, notice, card, choice, input, select, fold, tag, optionCards } from "../lib.js";
import { localModelHelp } from "./local-model.js";

export const LEVEL = {
  cloud: { title: "Claude may read it", many: "Claude may read them", short: "Claude", icon: "cloud",
    sub: "Read by the AI you chose: Claude Code, the Claude API, or a local model." },
  local: { title: "Only a local AI", many: "Only a local AI", short: "Local AI", icon: "house",
    sub: "Read only by a model on this computer, or by you. Never sent to Claude." },
  none: { title: "No AI", many: "No AI", short: "No AI", icon: "cpu",
    sub: "Only you judge its excerpts. Search, the keyword profile, concepts and themes still work." },
};
const CHECKED = "30 October 2026";
const DATA_USAGE = "https://code.claude.com/docs/en/data-usage";
const PRIVACY_SETTING = "https://claude.ai/settings/data-privacy-controls";

const localOnly = () => !!(App.state && App.state.local_only);
export const levels = () => (localOnly() ? ["local", "none"] : ["cloud", "local", "none"]);

export function accessBadge(level, opts = {}) {
  const L = LEVEL[level] || LEVEL.none;
  return tag({ class: `access-badge access-${level}`, title: L.title, icon: L.icon }, opts.long ? L.title : L.short,
    opts.count !== undefined ? `: ${opts.count} ${opts.count === 1 ? "document" : "documents"}` : null);   // a number says what it counts
}

// The question "Who may read these documents with AI?": three choices, one preselected (or none, the first time).
export function accessChoice({ value = null, name = "ai-access", many = true, onChange } = {}) {
  const wrap = h("fieldset", { class: "access-choice" },
    h("legend", { class: "field-label" }, many ? "Who may read these documents with AI?" : "Who may read this document with AI?"));
  wrap.value = value;
  // option cards holding real radio inputs (docs/DESIGN.md 4.7)
  wrap.appendChild(optionCards({ name, value, class: "access-options", label: many ? "Who may read these documents with AI?" : "Who may read this document with AI?",
    options: levels().map((lv) => ({ value: lv, icon: LEVEL[lv].icon, title: many ? LEVEL[lv].many : LEVEL[lv].title, text: LEVEL[lv].sub })),
    onPick: (lv) => { wrap.value = lv; if (onChange) onChange(lv); } }));
  return wrap;
}

// The small dropdown of the Documents table. `own` null: the project's default applies.
export function accessSelect(doc, projectDefault, onPick) {
  const sel = select({ sm: true, class: "access-select", "aria-label": `Who may read ${doc.title || doc.file} with AI` },
    levels().map((lv) => h("option", { value: lv, selected: doc.ai_access === lv }, LEVEL[lv].title)));
  sel.dataset.level = doc.ai_access;
  sel.addEventListener("change", () => { sel.dataset.level = sel.value; onPick(sel.value === projectDefault && !doc.own ? null : sel.value); });
  return sel;
}

// A project without a default (made before 0.11 and imported, or made through the connector): asked once.
export function accessAskCard(project, info, onDone) {
  let picked = null;
  const btn = button({ kind: "main", disabled: true }, icon("check", { size: 14 }), "Use this for the project");
  const pick = accessChoice({ name: "ask-default", onChange: (v) => { picked = v; btn.disabled = false; } });
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try { await api("PUT", `/api/projects/${P(project)}/ai-access`, { default: picked }); toast(`${LEVEL[picked].many}: this applies to every document without its own setting.`, "ok"); onDone(); }
    catch (e) { showError(e); btn.disabled = false; }
  });
  return card({ class: "access-ask", "aria-label": "Who may read these documents with AI" },
    h("h2", {}, icon("cloud", { size: 16 }), "Who may read this project's documents with AI?"),
    h("p", { class: "muted" }, "Say it once for the whole project; you can change single documents below. Until you choose, Claude may read them, as before."),
    pick, h("div", { class: "btn-row aia-actions" }, btn));
}

export function accessBanner(project, onDismiss) {
  const close = iconButton({ icon: "x", size: 14, label: "Dismiss", title: null, onClick: async () => {
    try { await api("PUT", `/api/projects/${P(project)}/ai-access`, { dismiss_banner: true }); } catch (_) { /* shown next time */ }
    onDismiss();
  } });
  return notice({ kind: "info", icon: "info", class: "access-banner", role: "status" },
    h("div", { class: "grow" }, h("p", {}, h("strong", {}, "New in 0.11: choose which documents Claude may read. "),
      "Mark a licensed PDF or an interview transcript as ", h("em", {}, "Only a local AI"), " or ", h("em", {}, "No AI"),
      " in the column ", link({ kind: "jump", onClick: () => { const t = document.querySelector(".access-select") || document.getElementById("ai-column"); if (t) { t.scrollIntoView({ block: "center" }); t.focus(); } } }, "AI"),
      ". Everything else stays as it was.")), close);
}

// What Claude has read of a document, its note and its cap.
export async function docAccessDialog(project, doc, projectDefault, onSaved) {
  let sent = { passages: [], share: doc.sent || 0 };
  try { sent = await api("GET", `/api/projects/${P(project)}/documents/${P(doc.doc_id)}/ai-sent`); } catch (e) { showError(e); }
  let level = doc.ai_access;
  const pick = accessChoice({ value: level, many: false, name: "doc-access", onChange: (v) => { level = v; capBox.hidden = v !== "cloud"; } });
  const note = input({ maxlength: 300, value: doc.note || "", placeholder: "e.g. publisher licence, contains interview data", id: "acc-note" });
  const cap = input({ sm: true, type: "number", min: 1, max: 100, step: 1, value: doc.budget ?? "", placeholder: "none", id: "acc-cap", class: "aia-cap" });
  const capBox = h("div", { class: "field", hidden: level !== "cloud" },
    h("label", { class: "field-label", for: "acc-cap" }, "Claude may read at most"),
    h("div", { class: "row aia-cap-row" }, cap, h("span", {}, "% of this document")),
    h("div", { class: "field-help" }, "Optional. Once Claude has read that much, the rest is treated as Only a local AI. A check that is running may go over by one round."));
  const share = Math.round((sent.share || 0) * 1000) / 10;
  const list = sent.passages.length ? h("ul", { class: "sent-list" }, sent.passages.slice(0, 200).map((x) =>
    h("li", {}, h("a", { href: `#/doc/${encodeURIComponent(doc.doc_id)}` }, x.page ? `Page ${x.page}` : `Passage ${x.seq != null ? x.seq + 1 : ""}`),
      h("span", { class: "muted small" }, ` · ${x.features.join(", ")} · ${x.routes.join(", ")} · ${fmt.dateShort(x.last)}${x.times > 1 ? ` · ${x.times} times` : ""}`),
      x.preview ? h("div", { class: "small sent-preview" }, x.preview, "…") : null)))
    : h("p", { class: "muted small" }, "Claude has read nothing of this document" + (sent.since ? " since ENLENS began keeping this list." : "."));
  const body = h("div", { class: "stack aia-body" },
    pick,
    h("div", { class: "field" }, h("label", { class: "field-label", for: "acc-note" }, "Why (optional)"), note,
      h("div", { class: "field-help" }, "A note for your records, exported with the project. It changes nothing.")),
    capBox,
    h("div", {}, h("h3", { class: "h-small" }, `What Claude has read: ${share}%`), list,
      sent.since ? h("p", { class: "muted small" }, `Since 0.11 (${fmt.dateShort(sent.since)}), plus the earlier results ENLENS recorded.`) : null));
  await dialog({ title: doc.title || doc.file, body, wide: true, actions: [{ text: "Cancel", value: null }, { text: "Save", primary: true, onClick: async () => {
    const changes = { doc_ids: [doc.doc_id], note: note.value.trim() };
    if (level !== doc.ai_access || (doc.own == null && level !== projectDefault)) changes.ai_access = level === projectDefault && doc.own == null ? null : level;
    if (level === "cloud") changes.budget = cap.value === "" ? "" : Number(cap.value);
    try { const r = await api("PUT", `/api/projects/${P(project)}/documents/ai-access`, changes); onSaved(r); return true; }
    catch (e) { showError(e); return false; }
  } }] });
}

// "What happens to the text Claude reads": in plain words, with the source and the date it was checked.
export function termsPanel(opts = {}) {
  const st = App.state || {};
  const said = opts.account || (st.settings || {}).account_type || "";
  const box = card({ as: "div", class: "terms-panel" });
  const draw = (kind) => {
    const choose = choice({ label: "Your kind of Claude account", class: "terms-pick", value: kind,
      options: [["personal", "Pro or Max (personal)"], ["commercial", "Team, Enterprise or the Claude API"]],
      onPick: async (k) => {
        try { const r = await api("PUT", "/api/settings", { account_type: k }); App.state.settings = r.settings; } catch (e) { showError(e); return; }
        draw(k);
      } });
    const facts = {
      personal: [h("p", {}, h("strong", {}, "Consumer terms apply. "), "Anthropic may use your chats and Claude Code sessions to train its models when your account's model-improvement setting is on, and then keeps that data for 5 years (30 days when it is off). ",
        h("strong", {}, "Turn that setting off before Claude reads licensed documents: "), h("a", { href: PRIVACY_SETTING, target: "_blank", rel: "noopener" }, "Claude privacy settings"), ".")],
      commercial: [h("p", {}, h("strong", {}, "Commercial terms apply. "), "Anthropic does not train its models on what Claude Code is sent, unless your organisation chose to share it, and keeps it for 30 days. Ask your organisation about a data processing agreement for personal data.")],
    }[kind];
    replace(box,
      h("h3", { class: "h-small" }, icon("cloud", { size: 14 }), "What happens to the text Claude reads"),
      h("p", { class: "small" }, "Only the excerpts inside the AI's tasks leave this computer, and only from documents Claude may read: documents marked Only a local AI or No AI are never sent."),
      opts.detected && kind ? h("p", { class: "small muted" }, `Claude Code says your plan is ${opts.detected}.`) : h("p", { class: "small muted" }, "Which kind of account do you use?"),
      opts.detected && kind ? null : choose,
      facts ? h("div", { class: "small" }, facts) : null,
      h("p", { class: "small" }, h("strong", {}, "Your documents must stay in the EU? "), "Mark them ", h("em", {}, "Only a local AI"), ": Claude processes data outside the EU."),
      h("p", { class: "muted small" }, "From ", h("a", { href: DATA_USAGE, target: "_blank", rel: "noopener" }, "Anthropic's Claude Code data-usage page"), `, checked on ${CHECKED}. The terms can change; that page is the authority. ENLENS decides nothing here: this helps you choose each document's setting.`));
  };
  draw(opts.kind || said || "");
  return box;
}

// Settings → AI: the local model that reads documents marked Only a local AI while Claude reads the rest.
export function restrictedModelCard(s, servers, save, info = { servers }) {
  const chosen = (App.state && App.state.restricted) || {};
  const sect = card({ class: "settings-section", id: "s-restricted", "aria-labelledby": "s-restricted-h" },
    h("h2", { id: "s-restricted-h", tabindex: "-1" }, "Local model for restricted documents"));
  if (chosen.same_as_main) {
    sect.append(h("p", { class: "lead" }, "The AI you chose runs on this computer, so it also reads the documents marked Only a local AI. Documents marked No AI wait for your own judgement."));
    return sect;
  }
  const state = h("span", { class: "save-state", "aria-live": "polite" });
  const options = [h("option", { value: "" }, "None: I judge those excerpts myself")];
  for (const srv of servers || []) {
    for (const m of srv.chat_models || []) options.push(h("option", { value: `${srv.kind}|${m}`, selected: s.restricted_server === srv.kind && s.restricted_model === m }, `${m} (${srv.kind === "ollama" ? "Ollama" : "local server"})`));
  }
  if (s.restricted_model && !options.some((o) => o.selected)) options.push(h("option", { value: `${s.restricted_server}|${s.restricted_model}`, selected: true }, `${s.restricted_model} (not running now)`));
  const sel = select({ id: "restricted-model" }, ...options);
  sel.addEventListener("change", async () => {
    const [server, model] = sel.value ? sel.value.split("|") : ["", ""];
    try { await save({ restricted_server: server, restricted_model: model }, state); const st = await api("GET", "/api/state"); App.state.restricted = st.restricted; toast(model ? `Documents marked Only a local AI are read by ${model}.` : "Excerpts from documents marked Only a local AI wait for your judgement.", "ok"); }
    catch (_) { /* shown */ }
  });
  sect.append(h("p", { class: "lead" }, "Claude never reads documents marked Only a local AI. Choose a model on this computer to read their excerpts in a check, the Profile and the other features; without one, they wait for your own judgement."),
    h("div", { class: "save-row" }, field2("Local model", sel, servers && servers.length ? "Chat models of the model servers running on this computer." : "No model server is running on this computer just now (Ollama, LM Studio…)."), state));
  // 0.13.7: no model on this computer yet: get Ollama, or download a model into it with one button
  const rerender = () => window.dispatchEvent(new HashChangeEvent("hashchange"));
  const help = localModelHelp(info, { embed: false, use: "restricted", onFound: rerender, onReady: async (r) => {
    try { await App.refresh(); } catch (_) { /* shown on the page */ }
    toast(r.chosen ? `Documents marked Only a local AI are read by ${r.chat}.` : `${r.chat} is downloaded: choose it above.`, "ok");
    rerender();
  } });
  // with no model server at all, the steps to get one stay folded: most people who use Claude never need them
  if (help) sect.append((servers || []).length ? help : fold({}, "Get a model on this computer (free, no terminal)", help));
  return sect;
}

function field2(label, control, help) {
  return h("div", { class: "field grow" }, h("label", { class: "field-label", for: control.id }, label), control, h("div", { class: "field-help" }, help));
}
