// Shared plumbing: API client, DOM helpers, formatting, toasts, dialogs, job polling and app state.
import { icon } from "./icons.js";

// ---------------------------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------------------------
// The page carries its token; when the app listens on the network it does not, and the token comes in the link
// printed in the terminal (#token=…), kept for this tab only.
function readToken() {
  const meta = (document.querySelector('meta[name="enlens-token"]') || {}).content || "";
  if (meta && !meta.startsWith("{{")) return meta;
  const m = /(?:^#|&)token=([A-Za-z0-9_-]+)/.exec(location.hash || "");
  try {
    if (m) { sessionStorage.setItem("enlens-token", m[1]); history.replaceState(null, "", location.pathname + "#/"); return m[1]; }
    return sessionStorage.getItem("enlens-token") || "";
  } catch (_) { return m ? m[1] : ""; }
}
export const TOKEN = readToken();
export const VERSION = (document.querySelector('meta[name="enlens-version"]') || {}).content || "";

export class ApiError extends Error {
  constructor(status, message, kind) {
    super(message);
    this.status = status;
    this.kind = kind || "request";
  }
}

export async function api(method, path, body, opts = {}) {
  const headers = { "X-Enlens-Token": TOKEN };
  let payload;
  if (body instanceof Blob || body instanceof ArrayBuffer) {
    headers["Content-Type"] = "application/octet-stream";
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, { method, headers, body: payload, signal: opts.signal });
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw new ApiError(0, "The app is not answering. Is it still running in the terminal?", "internal");
  }
  if (opts.raw) {
    if (!res.ok) {
      let msg = res.statusText;
      try { msg = (await res.json()).error || msg; } catch (_) { /* not json */ }
      throw new ApiError(res.status, msg, res.status === 502 ? "backend" : "request");
    }
    return res;
  }
  let data = null;
  const text = await res.text();
  try { data = text ? JSON.parse(text) : {}; } catch (_) { data = { error: text || "Unreadable answer from the app." }; }
  if (!res.ok) {
    const msg = (data && data.error) || `Request failed (${res.status}).`;
    throw new ApiError(res.status, res.status === 401 ? (TOKEN ? "The page's token is no longer valid. Reload the page." : "Open the link that enlens-gui printed in its terminal: it carries the access token.") : msg,
      (data && data.kind) || (res.status === 502 ? "backend" : "request"));
  }
  return data;
}

export const P = (name) => encodeURIComponent(name);

// ---------------------------------------------------------------------------------------------
// DOM helpers (text is always set with textContent: never innerHTML)
// ---------------------------------------------------------------------------------------------
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs && typeof attrs === "object" && !(attrs instanceof Node) && !Array.isArray(attrs)) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "dataset") Object.assign(el.dataset, v);
      else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === "html") throw new Error("innerHTML is not allowed");
      else if (v === true) el.setAttribute(k, "");
      else el.setAttribute(k, String(v));
    }
  } else if (attrs !== undefined) {
    children.unshift(attrs);
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    if (c instanceof Node) el.appendChild(c);
    else el.appendChild(document.createTextNode(String(c)));
  }
  return el;
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

export function replace(el, ...children) {
  clear(el);
  append(el, children);
  return el;
}

export function frag(...children) {
  return append(document.createDocumentFragment(), children);
}

export { icon };

export function iconText(name, text, cls) {
  return h("span", { class: "it " + (cls || "") }, icon(name), h("span", {}, text));
}

// A passage with its quote highlighted: text nodes around a <mark>, built from character offsets.
// With `breaks` (0.6: [{at, kind: "paragraph" | "heading", end}], offsets in the unbroken text) the text is laid out
// as paragraphs, headings as a bold line; the quote offsets still refer to the unbroken text, so the highlight
// continues across a break.
export function passageNode(text, start, end, tag = "p", cls = "passage", breaks = null) {
  text = String(text || "");
  const ok = Number.isInteger(start) && Number.isInteger(end) && start >= 0 && start < end && end <= text.length;
  const segments = breakSegments(text, breaks);
  if (!segments) {
    const el = h(tag, { class: cls });
    if (ok) append(el, [text.slice(0, start), h("mark", { class: "quote" }, text.slice(start, end)), text.slice(end)]);
    else el.textContent = text;
    return el;
  }
  // several paragraphs: a block container (a <p> cannot hold <p>s), each segment on its own line
  const el = h(tag === "span" ? "span" : "div", { class: `${cls} passage-broken` });
  for (const seg of segments) {
    const line = h(tag === "span" ? "span" : "p", { class: seg.heading ? "passage-heading" : "passage-para" });
    const s0 = seg.start, s1 = seg.end;
    if (ok && start < s1 && end > s0) {
      const a = Math.max(start, s0), b = Math.min(end, s1);
      append(line, [text.slice(s0, a), h("mark", { class: "quote" }, text.slice(a, b)), text.slice(b, s1)]);
    } else line.textContent = text.slice(s0, s1);
    el.appendChild(line);
  }
  return el;
}

// The segments of a text cut at its breaks: [{start, end, heading}], trimmed of the whitespace that joins
// paragraphs in the unbroken text (offsets stay those of the unbroken text). null when there is nothing to cut.
export function breakSegments(text, breaks) {
  if (!Array.isArray(breaks) || !breaks.length) return null;
  const cuts = breaks.filter((b) => b && Number.isInteger(b.at) && b.at >= 0 && b.at <= text.length).sort((a, b) => a.at - b.at);
  if (!cuts.length) return null;
  const raw = [];
  let pos = 0;
  for (const b of cuts) {
    if (b.at > pos) raw.push({ start: pos, end: b.at, heading: false });
    if (b.kind === "heading" && Number.isInteger(b.end) && b.end > b.at) {
      raw.push({ start: b.at, end: Math.min(b.end, text.length), heading: true });
      pos = Math.min(b.end, text.length);
    } else pos = Math.max(pos, b.at);
  }
  if (pos < text.length) raw.push({ start: pos, end: text.length, heading: false });
  const out = [];
  for (const seg of raw) {
    let s = seg.start, e = seg.end;
    while (s < e && /\s/.test(text[s])) s++;
    while (e > s && /\s/.test(text[e - 1])) e--;
    if (e > s) out.push({ start: s, end: e, heading: seg.heading });
  }
  return out.length > 1 || (out.length === 1 && out[0].heading) ? out : null;
}

// A short note that opens on hover or focus and stays open on click or tap (no native tooltip): used for defined
// terms and for chips that need a sentence of explanation.
export function popNote(trigger, explanation, opts = {}) {
  const pop = h("span", { class: "pop" + (opts.wide ? " pop-wide" : ""), role: "note", hidden: true }, explanation);
  let pinned = false;
  trigger.setAttribute("aria-expanded", "false");
  const show = (on) => { pop.hidden = !on; trigger.setAttribute("aria-expanded", on ? "true" : "false"); };
  trigger.addEventListener("click", () => { pinned = !pinned; show(pinned); });
  trigger.addEventListener("mouseenter", () => show(true)); trigger.addEventListener("mouseleave", () => { if (!pinned) show(false); });
  trigger.addEventListener("focus", () => show(true)); trigger.addEventListener("blur", () => { if (!pinned) show(false); });
  trigger.addEventListener("keydown", (e) => { if (e.key === "Escape") { pinned = false; show(false); } });
  return h("span", { class: "defined-wrap" }, trigger, pop);
}

// A grade with its certainty in the app's words: "Supports (75%)", "not about this hypothesis".
export function gradeWords(verdict, confidence) {
  if (!verdict) return "not about this hypothesis";
  const pct = confidence !== null && confidence !== undefined ? ` (${Math.round(Number(confidence) * 100)}%)` : "";
  return `${GRADE_TEXT[verdict] || verdict}${pct}`;
}

// ---------------------------------------------------------------------------------------------
// formatting
// ---------------------------------------------------------------------------------------------
export const fmt = {
  date(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso).slice(0, 16).replace("T", " ");
    return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  },
  dateShort(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10);
    const now = new Date();
    const sameYear = d.getFullYear() === now.getFullYear();
    return d.toLocaleDateString(undefined, sameYear ? { month: "short", day: "numeric" } : { year: "numeric", month: "short", day: "numeric" });
  },
  unix(sec) {
    return sec ? fmt.date(new Date(sec * 1000).toISOString()) : "";
  },
  secs(s) {
    if (s === null || s === undefined || Number.isNaN(Number(s))) return "";
    s = Number(s);
    if (s < 10) return `${s.toFixed(1)} s`;
    s = Math.round(s);
    if (s < 90) return `${s} s`;
    const m = Math.floor(s / 60), r = s % 60;
    if (m < 60) return `${m} min ${String(r).padStart(2, "0")} s`;
    return `${Math.floor(m / 60)} h ${m % 60} min`;
  },
  num(n) {
    return n === null || n === undefined ? "" : Number(n).toLocaleString();
  },
  conf(c) {
    return c === null || c === undefined ? "" : Number(c).toFixed(2);
  },
  plural(n, one, many) {
    return `${fmt.num(n)} ${n === 1 ? one : (many || one + "s")}`;
  },
  bytes(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} kB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
  },
};

// Plain vocabulary, used consistently on every screen. Technical names stay available in "details" places.
export const GRADE_TEXT = { supports: "Supports", partially_supports: "Partly supports", refutes: "Contradicts" };
export const GRADE_VERB = { supports: "support it", partially_supports: "partly support it", refutes: "contradict it" };
export const FOUND_BY = { keywords: "found because it uses the same words", meaning: "found by search by meaning (other words, same thing)", both: "found by the same words and by search by meaning" };
export const FOUND_BY_SHORT = { keywords: "same words", meaning: "search by meaning", both: "same words + search by meaning" };
// Short status words for dense places (tables, chips); the full texts from /api/state are used on the answer card.
export const STATUS_SHORT = { supported: "Supported", partially_supported: "Partly supported", contested: "Mixed evidence", contradicted: "Contradicted", uncertain: "Only uncertain evidence", unsupported: "No evidence found", no_passages: "Nothing matched", not_checked: "Not finished", failed: "Did not work", waiting: "Waiting for Claude Code" };
export const KIND_TEXT = { pdf: "PDF", html: "web page", text: "text", txt: "text", md: "Markdown", markdown: "Markdown", docx: "Word" };

// The AI's certainty in words. The number stays in the details.
export function certainty(conf) {
  if (conf === null || conf === undefined) return null;
  const c = Number(conf);
  const word = c >= 0.8 ? "high" : c >= 0.6 ? "medium" : "low";
  return { word, text: `${word} certainty`, long: `The AI was ${word === "high" ? "quite sure" : word === "medium" ? "fairly sure" : "not very sure"} (${c.toFixed(2)} on a scale from 0 to 1).` };
}
// The strictness setting (the confidence threshold) in words.
export function strictness(t) {
  const v = Number(t);
  if (v <= 0.4) return "very relaxed";
  if (v <= 0.55) return "relaxed";
  if (v <= 0.65) return "normal";
  if (v <= 0.8) return "strict";
  return "very strict";
}
// One sentence counting documents, from the backend's balance (a document can be on more than one side).
export function docsCountSentence(bal) {
  if (!bal || !bal.docs_counted) return "No document has an excerpt that counts.";
  const sup = bal.docs_supporting || 0, part = bal.docs_partly || 0, ref = bal.docs_refuting || 0, both = bal.docs_both || 0, counted = bal.docs_counted || 0;
  const docs = (n) => `${n} ${n === 1 ? "document" : "documents"}`;
  const bits = [];
  if (sup) bits.push(`${docs(sup)} ${sup === 1 ? "supports" : "support"} it`);
  if (part) bits.push(`${docs(part)} partly ${part === 1 ? "supports" : "support"} it`);
  if (ref) bits.push(`${docs(ref)} ${ref === 1 ? "contradicts" : "contradict"} it`);
  const list = (xs) => xs.length > 1 ? xs.slice(0, -1).join(", ") + " and " + xs[xs.length - 1] : xs[0] || "";
  if (both && counted === 1) {
    const kinds = [sup && "supporting", part && "partly supporting", ref && "contradicting"].filter(Boolean);
    return `One document has excerpts on both sides: ${list(kinds)} ones. No other document counts.`;
  }
  let text = list(bits);
  text = text.charAt(0).toUpperCase() + text.slice(1);
  if (both) text += ` (${both === 1 ? "one document has" : both + " documents have"} excerpts on both sides)`;
  return text + ".";
}
// How a status reads inside a sentence about one part.
export const PART_PHRASE = { supported: "is supported", partially_supported: "is only partly supported", contested: "has mixed evidence", contradicted: "is contradicted", uncertain: "has only uncertain evidence", unsupported: "has no evidence", no_passages: "matched nothing in the documents", not_checked: "is not finished", failed: "could not be checked" };
export function partsSentence(parts, status) {
  if (!parts || !parts.length) return "";
  const bad = parts.filter((p) => p.status !== "supported");
  if (!bad.length) return "Every part is supported, so the whole hypothesis is supported.";
  const names = bad.map((p) => `Part ${p.part} ${PART_PHRASE[p.status] || p.status}`);
  const list = names.length > 1 ? names.slice(0, -1).join(", ") + " and " + names[names.length - 1] : names[0];
  return `The hypothesis holds only if every part holds. ${list}, so the whole hypothesis ${PART_PHRASE[status] || status}.`;
}

// One sentence on the overall direction of the evidence, from the document counts.
export function balanceSentence(bal) {
  if (!bal) return "";
  const sup = bal.docs_supporting || 0, part = bal.docs_partly || 0, ref = bal.docs_refuting || 0;
  const total = sup + part + ref;
  const docs = (n) => `${n} ${n === 1 ? "document" : "documents"}`;
  const parts = [];
  if (sup) parts.push(`${docs(sup)} ${sup === 1 ? "supports" : "support"} it`);
  if (part) parts.push(`${sup ? docs(part) : docs(part)} partly ${part === 1 ? "supports" : "support"} it`);
  if (ref) parts.push(`${docs(ref)} ${ref === 1 ? "contradicts" : "contradict"} it`);
  if (!total) return "None of the excerpts read gives evidence for or against it.";
  const list = parts.length > 1 ? parts.slice(0, -1).join(", ") + " and " + parts[parts.length - 1] : parts[0];
  const lean = bal.lean;
  let head = "";
  if (lean === null || lean === undefined) head = "";
  else if (lean >= 0.5) head = "Leans clearly towards support: ";
  else if (lean > 0.15) head = "Leans towards support: ";
  else if (lean <= -0.5) head = "Leans clearly against: ";
  else if (lean < -0.15) head = "Leans against: ";
  else head = "The evidence is balanced: ";
  return head + list.charAt(0).toUpperCase() + list.slice(1) + ".";
}

// ---------------------------------------------------------------------------------------------
// toasts
// ---------------------------------------------------------------------------------------------
export function toast(message, kind = "info", opts = {}) {
  const box = document.getElementById("toasts");
  if (!box) return;
  const names = { info: "info", ok: "circle-check", warn: "alert-triangle", error: "alert-circle" };
  if (opts.group) for (const old of box.querySelectorAll(`.toast[data-group="${opts.group}"]`)) old.remove();
  const t = h("div", { class: `toast toast-${kind}${opts.small ? " toast-small" : ""}`, role: kind === "error" ? "alert" : "status", dataset: opts.group ? { group: opts.group } : null },
    icon(names[kind] || "info"),
    h("div", { class: "toast-body" }, h("div", {}, message),
      opts.detail ? h("details", { class: "toast-detail" }, h("summary", {}, "Technical details"), h("div", { class: "mono small" }, opts.detail)) : null,
      opts.action ? h("a", { href: opts.action.href, class: "toast-link" }, opts.action.text) : null,
      opts.button ? h("button", { class: "btn btn-sm toast-btn", type: "button", onClick: () => { t.remove(); opts.button.onClick(); } }, opts.button.text) : null),
    h("button", { class: "icon-btn", type: "button", "aria-label": "Dismiss", onClick: () => t.remove() }, icon("x")));
  box.appendChild(t);
  const ttl = opts.ttl || (kind === "error" ? 15000 : opts.button ? 9000 : 5000);
  setTimeout(() => { t.classList.add("toast-out"); setTimeout(() => t.remove(), 300); }, ttl);
  return t;
}

// Errors in plain words; the technical message is kept behind "Technical details".
export function showError(e, extra = {}) {
  const msg = e && e.message ? e.message : String(e);
  if (e && e.kind === "backend") {
    toast("The AI model is not answering, so the check cannot run.", "error", { detail: msg, action: { href: "#/settings", text: "Check the AI model in Settings" }, ...extra });
  } else if (e && e.status === 401) {
    toast("This page is no longer connected to the app. Reload the page.", "error", { detail: msg, ...extra });
  } else if (e && e.status === 0) {
    toast("The app is not answering. Is it still running?", "error", { detail: msg, ...extra });
  } else if (e && e.kind === "internal") {
    toast("Something went wrong inside the app.", "error", { detail: msg, ...extra });
  } else {
    toast(msg, "error", extra);
  }
}

// ---------------------------------------------------------------------------------------------
// dialogs (native <dialog>: focus trap and Escape come for free)
// ---------------------------------------------------------------------------------------------
export function dialog({ title, body, actions, danger, onOpen, wide }) {
  return new Promise((resolve) => {
    const dlg = h("dialog", { class: "dialog" + (wide ? " dialog-wide" : ""), "aria-labelledby": "dlg-title" });
    const close = (value) => { dlg.close(); dlg.remove(); resolve(value); };
    const btns = (actions || [{ text: "Close", value: null }]).map((a) =>
      h("button", {
        type: "button",
        class: "btn " + (a.primary ? (danger ? "btn-danger" : "btn-primary") : "btn-ghost"),
        id: a.id,
        disabled: a.disabled,
        onClick: async () => {
          if (a.onClick) { const r = await a.onClick(dlg); if (r === false) return; }
          close(a.value);
        },
      }, a.text));
    append(dlg, [
      h("div", { class: "dialog-head" }, h("h2", { id: "dlg-title" }, title),
        h("button", { class: "icon-btn", type: "button", "aria-label": "Close", onClick: () => close(null) }, icon("x"))),
      h("div", { class: "dialog-body" }, body),
      h("div", { class: "dialog-actions" }, btns),
    ]);
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(null); });
    dlg.addEventListener("click", (e) => { if (e.target === dlg) close(null); });
    document.getElementById("dialogs").appendChild(dlg);
    dlg.showModal();
    if (onOpen) onOpen(dlg);
  });
}

export function confirmDialog({ title, message, confirmText = "Confirm", typeToConfirm, danger = true }) {
  let input = null;
  const body = h("div", {}, typeof message === "string" ? h("p", {}, message) : message);
  const actions = [{ text: "Cancel", value: false }, { text: confirmText, value: true, primary: true, id: "dlg-confirm", disabled: !!typeToConfirm }];
  if (typeToConfirm) {
    input = h("input", { class: "input", type: "text", autocomplete: "off", "aria-label": `Type ${typeToConfirm} to confirm` });
    append(body, [h("label", { class: "field" }, h("span", { class: "field-label" }, "Type ", h("code", {}, typeToConfirm), " to confirm"), input)]);
  }
  return dialog({
    title, body, actions, danger,
    onOpen(dlg) {
      if (input) {
        const btn = dlg.querySelector("#dlg-confirm");
        input.addEventListener("input", () => { btn.disabled = input.value.trim() !== typeToConfirm; });
        input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !btn.disabled) btn.click(); });
        input.focus();
      }
    },
  });
}

// ---------------------------------------------------------------------------------------------
// downloads through fetch, so the token travels in a header rather than a link
// ---------------------------------------------------------------------------------------------
export async function download(path, filename) {
  const res = await api("GET", path, undefined, { raw: true });
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const m = /filename="?([^";]+)"?/.exec(cd);
  const name = filename || (m && m[1]) || "download";
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: name });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

// ---------------------------------------------------------------------------------------------
// jobs
// ---------------------------------------------------------------------------------------------
export const TERMINAL = new Set(["done", "error", "cancelled"]);

// Polls one job until it ends. onTick(job) runs for every poll. Returns {promise, stop}.
export function watchJob(jobId, onTick, interval = 500) {
  let stopped = false;
  let timer = null;
  let first = true;
  let failures = 0;
  const promise = new Promise((resolve, reject) => {
    const tick = async () => {
      if (stopped) return;
      if (first) { first = false; jobsChanged(); }
      let job;
      try {
        job = await api("GET", `/api/jobs/${P(jobId)}`);
      } catch (e) {
        if (stopped) return;
        if (e.status === 404 || ++failures > 20) { reject(e); return; }
        timer = setTimeout(tick, interval * 3);   // the app may be busy; try again
        return;
      }
      failures = 0;
      if (stopped) return;
      try { if (onTick) onTick(job); } catch (err) { console.error(err); }
      if (TERMINAL.has(job.state)) { resolve(job); jobsChanged(); App.refresh().catch(() => {}); return; }
      timer = setTimeout(tick, interval);
    };
    tick();
  });
  return { promise, stop() { stopped = true; if (timer) clearTimeout(timer); } };
}

export async function cancelJob(jobId) {
  return api("POST", `/api/jobs/${P(jobId)}/cancel`);
}

const jobListeners = new Set();
export function onJobsChanged(fn) { jobListeners.add(fn); return () => jobListeners.delete(fn); }
export function jobsChanged() { for (const fn of jobListeners) { try { fn(); } catch (e) { console.error(e); } } }

// ---------------------------------------------------------------------------------------------
// app state
// ---------------------------------------------------------------------------------------------
export const App = {
  state: null,          // GET /api/state
  project: null,        // current project name
  lastRun: null,        // {hyp_id, summary, seconds} of the check just finished (shown once on the result page)
  listeners: new Set(),
  async refresh() {
    App.state = await api("GET", "/api/state");
    App.project = App.state.project;
    for (const fn of App.listeners) { try { fn(App.state); } catch (e) { console.error(e); } }
    return App.state;
  },
  onChange(fn) { App.listeners.add(fn); return () => App.listeners.delete(fn); },
  statusText(status) {
    const s = (App.state && App.state.statuses || []).find((x) => x.status === status);
    return s ? s.text : (status || "");
  },
  statusHelp(status) {
    const s = (App.state && App.state.statuses || []).find((x) => x.status === status);
    return s ? s.help : "";
  },
  statusNext(status) {
    const s = (App.state && App.state.statuses || []).find((x) => x.status === status);
    return s ? (s.next || "") : "";
  },
  settings() { return (App.state && App.state.settings) || {}; },
  // Where the text goes, from the settings: for the privacy indicator.
  privacy() {
    const s = App.settings();
    const b = s.backend || "auto";
    if (b === "anthropic") return { where: "cloud", label: "Cloud AI", plain: "Excerpts of your documents are sent to the Claude API (cloud)", detail: `Claude API · ${s.anthropic_model || ""}`, icon: "cloud" };
    if (b === "claude_code") return { where: "cloud", label: "Claude Code", plain: "Claude Code reads the excerpts on your own Claude plan: the passages it takes are sent to Anthropic", detail: "Claude Code (your subscription) · a helper and model per task", icon: "cloud" };
    if (b === "baseline") return { where: "none", label: "Demo mode", plain: "No AI model: a simple word-overlap stand-in. Results are not findings.", detail: "offline demo", icon: "cpu" };
    const labels = (App.state && App.state.backend_labels) || {};
    const model = b === "ollama" ? (s.ollama_model || "no model chosen") : b === "openai" ? (s.openai_model || "first model listed") : (s.ollama_model || s.openai_model || "first model found");
    return { where: "local", label: "Private", plain: "The AI runs on this computer. Your documents never leave it.", detail: `${labels[b] || b} · ${model}`, icon: "house" };
  },
  modelConfigured() {
    const s = App.settings();
    if (s.backend === "ollama") return !!s.ollama_model;
    if (s.backend === "anthropic") return !!(App.state && App.state.key && (App.state.key.session || App.state.key.env || App.state.key.stored));
    return true;
  },
};

export function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem("enlens." + key);
    if (value === null) localStorage.removeItem("enlens." + key);
    else localStorage.setItem("enlens." + key, String(value));
  } catch (_) { return null; }
  return value;
}

export function session(key, value) {
  try {
    if (value === undefined) { const v = sessionStorage.getItem("enlens." + key); return v === null ? null : JSON.parse(v); }
    if (value === null) sessionStorage.removeItem("enlens." + key);
    else sessionStorage.setItem("enlens." + key, JSON.stringify(value));
  } catch (_) { return null; }
  return value;
}

export function navigate(hash) { location.hash = hash; }

export function parseQuery(qs) {
  const out = {};
  for (const [k, v] of new URLSearchParams(qs || "")) out[k] = v;
  return out;
}

export function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// A random id for one upload batch: [A-Za-z0-9_-]
export function batchId() {
  const a = new Uint8Array(8);
  crypto.getRandomValues(a);
  return "u" + Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
}

// ---------------------------------------------------------------------------------------------
// small widgets
// ---------------------------------------------------------------------------------------------
export function field(label, control, opts = {}) {
  const id = control.id || ("f" + Math.random().toString(36).slice(2, 8));
  control.id = id;
  const wrap = h("div", { class: "field " + (opts.class || "") });
  const lab = h("label", { for: id, class: "field-label" }, label);
  if (opts.inline) {
    append(wrap, [h("div", { class: "field-inline" }, control, lab)]);
  } else {
    append(wrap, [lab, control]);
  }
  if (opts.help) {
    const help = h("div", { class: "field-help", id: id + "-help" }, opts.help);
    control.setAttribute("aria-describedby", id + "-help");
    wrap.appendChild(help);
  }
  return wrap;
}

export function switchControl(label, checked, opts = {}) {
  const input = h("input", { type: "checkbox", role: "switch", class: "switch-input", checked: !!checked, "aria-checked": checked ? "true" : "false" });
  input.addEventListener("change", () => input.setAttribute("aria-checked", input.checked ? "true" : "false"));
  const id = "sw" + Math.random().toString(36).slice(2, 8);
  input.id = id;
  const wrap = h("div", { class: "switch-field" },
    h("label", { class: "switch", for: id }, input, h("span", { class: "switch-track", "aria-hidden": "true" }), h("span", { class: "switch-label" }, label)),
    opts.help ? h("div", { class: "field-help" }, opts.help) : null);
  wrap.input = input;
  return wrap;
}

export function rangeControl(label, { min, max, step, value, format, help, ends }) {
  const input = h("input", { type: "range", min, max, step, value, class: "range" });
  const out = h("output", { class: "range-out" }, format ? format(value) : String(value));
  input.addEventListener("input", () => { out.textContent = format ? format(input.valueAsNumber) : input.value; });
  const id = "rg" + Math.random().toString(36).slice(2, 8);
  input.id = id;
  const wrap = h("div", { class: "field range-field" },
    h("div", { class: "range-head" }, h("label", { for: id, class: "field-label" }, label), out),
    input,
    ends ? h("div", { class: "range-ends", "aria-hidden": "true" }, h("span", {}, ends[0]), h("span", {}, ends[1])) : null,
    help ? h("div", { class: "field-help" }, help) : null);
  wrap.input = input;
  wrap.out = out;
  return wrap;
}

export function spinner(label) {
  return h("span", { class: "spinner", role: "img", "aria-label": label || "Working" }, icon("loader"));
}

export function emptyState(iconName, title, text, action) {
  return h("div", { class: "empty" }, icon(iconName, { size: 28 }), h("h3", {}, title), text ? h("p", {}, text) : null, action || null);
}

export function statusBadge(status, opts = {}) {
  const iconName = { supported: "circle-check", partially_supported: "circle-half", contested: "arrows-opposed", contradicted: "circle-x", uncertain: "help", unsupported: "circle-dashed", no_passages: "search-x", not_checked: "clock", failed: "alert-triangle", waiting: "inbox" }[status] || "circle";
  const text = opts.text || (opts.short ? STATUS_SHORT[status] : null) || App.statusText(status) || status;
  return h("span", { class: `badge status-${status} ${opts.size === "lg" ? "badge-lg" : ""} ${opts.class || ""}`, title: opts.title || (opts.short ? `${App.statusText(status)}. ` : "") + (App.statusHelp(status) || "") || null },
    icon(iconName, { size: opts.size === "lg" ? 20 : 14 }), opts.prefix ? h("span", { class: "badge-prefix" }, opts.prefix, " ") : null, h("span", {}, text));
}

export function gradeBadge(verdict, weak) {
  const names = { supports: "circle-check", partially_supports: "circle-half", refutes: "circle-x" };
  const v = verdict || "none";
  return h("span", { class: `badge grade-${v} ${weak ? "badge-weak" : ""}`, title: weak ? "Not counted: the AI was less sure than your strictness setting asks for" : null },
    icon(names[v] || "circle-dashed", { size: 14 }), h("span", {}, verdict ? GRADE_TEXT[verdict] || verdict : "Not about this hypothesis"));
}

export function codeChip(fw, code, description, label) {
  if (!code) return null;
  return h("span", { class: "chip chip-code", title: description || "" },
    h("strong", {}, `${label || fw || "code"} ${code}`),
    description ? h("span", { class: "chip-desc" }, " · " + (description.length > 80 ? description.slice(0, 80) + "…" : description)) : null);
}

export function kv(label, value, cls) {
  return h("div", { class: "kv " + (cls || "") }, h("dt", {}, label), h("dd", {}, value));
}

export function pageHead(title, opts = {}) {
  return h("header", { class: "page-head" },
    h("div", { class: "page-head-main" },
      opts.eyebrow ? h("p", { class: "eyebrow" }, opts.eyebrow) : null,
      h("h1", { id: "page-title", tabindex: "-1", class: opts.titleClass || "" }, title),
      opts.sub ? h("p", { class: "page-sub" }, opts.sub) : null),
    opts.actions ? h("div", { class: "page-head-actions" }, opts.actions) : null);
}

// ---------------------------------------------------------------------------------------------
// 0.8: the task queue (Claude Code)
// ---------------------------------------------------------------------------------------------
// A command to type, with a button that copies it.
export function copyLine(text, label = "Copy") {
  const btn = h("button", { class: "btn btn-sm btn-ghost copy-btn", type: "button", "aria-label": `${label}: ${text}` }, icon("copy", { size: 13 }), label);
  btn.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(text); toast("Copied. Paste it in Claude Code.", "ok", { ttl: 2000 }); }
    catch (_) { const r = document.createRange(); r.selectNodeContents(code); const s = getSelection(); s.removeAllRanges(); s.addRange(r); toast("Selected: copy it with Ctrl+C (or Cmd+C).", "info"); }
  });
  const code = h("code", { class: "copy-code" }, text);
  return h("div", { class: "copy-line" }, icon("terminal", { size: 13 }), code, btn);
}

// What waits for Claude Code, for a page that waits on it: the line, the estimate, the command, and a pause note.
export function queueNotice(q, opts = {}) {
  if (!q) return null;
  const est = q.estimate || "";
  return h("div", { class: `queue-notice ${q.paused ? "queue-paused" : ""}`, role: "status" },
    h("div", { class: "qn-head" }, icon(q.paused ? "pause" : "inbox", { size: 15 }), h("strong", {}, q.text || "Waiting for Claude Code"),
      q.being_answered ? h("span", { class: "muted small" }, ` · ${q.being_answered} being answered now`) : null),
    est && !q.paused ? h("div", { class: "muted small" }, est.charAt(0).toUpperCase() + est.slice(1) + ".") : null,
    q.paused && q.paused_text ? h("p", { class: "small", style: { margin: "4px 0" } }, q.paused_text) : null,
    h("div", { class: "small", style: { marginTop: "4px" } }, q.paused ? "Type this in Claude Code to go on:" : "Claude Code answers it when you type this in it (opened in any folder):"),
    copyLine(q.command || "/enlens-run"),
    opts.privacy === false ? null : h("div", { class: "muted small", style: { marginTop: "4px" } }, icon("cloud", { size: 12 }), " ", q.privacy || "Claude Code sends the passages inside the tasks it takes to Anthropic."));
}
