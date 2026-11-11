// Shared plumbing: API client, DOM helpers, formatting, toasts, dialogs, job polling and app state.
import { icon, STATUS_ICON } from "./icons.js";

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

// 0.14.3: whether the app answers. A request that cannot reach it (the browser's fetch fails) sets the flag; the
// next answer of any kind clears it. The shell (app.js) shows one banner across the app while it is set.
export const Connection = { down: false };
function connection(down) {
  if (Connection.down === down) return;
  Connection.down = down;
  window.dispatchEvent(new CustomEvent("enlens-connection", { detail: { down } }));
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
    connection(true);
    throw new ApiError(0, "The app is not answering. Is it still running in the terminal?", "internal");
  }
  connection(false);
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
    const err = new ApiError(res.status, res.status === 401 ? (TOKEN ? "The page's token is no longer valid. Reload the page." : "Open the link that enlens-gui printed in its terminal: it carries the access token.") : msg,
      (data && data.kind) || (res.status === 502 ? "backend" : "request"));
    err.data = data;   // 0.14: what else the app said (a file of another project: who sent it)
    throw err;
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

export { icon };

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
  const show = (on) => {
    pop.hidden = !on; trigger.setAttribute("aria-expanded", on ? "true" : "false");
    // 0.13.3: a note opened near the right edge (a help mark at the end of a long line) is moved left to stay in the
    // window, instead of running off it
    pop.style.transform = "";
    if (on) {
      const r = pop.getBoundingClientRect(), room = document.documentElement.clientWidth - 8;
      const shift = r.right > room ? Math.min(r.right - room, r.left - 8) : 0;
      if (shift > 0) pop.style.transform = `translateX(${-Math.round(shift)}px)`;
    }
  };
  trigger.addEventListener("click", () => { pinned = !pinned; show(pinned); });
  trigger.addEventListener("mouseenter", () => show(true)); trigger.addEventListener("mouseleave", () => { if (!pinned) show(false); });
  // 0.14.3: Tab from the mark into a button inside the note keeps the note open (it closed, and focus fell to the page)
  trigger.addEventListener("focus", () => show(true));
  trigger.addEventListener("blur", (e) => { if (!pinned && !(e.relatedTarget && pop.contains(e.relatedTarget))) show(false); });
  pop.addEventListener("focusout", (e) => { if (!pinned && !(e.relatedTarget && (pop.contains(e.relatedTarget) || e.relatedTarget === trigger))) show(false); });
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
    // 0.12: in English like the rest of the page ("4 Nov 2026, 19:36"), not in the computer's own language
    return d.toLocaleString("en-GB", { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  },
  dateShort(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10);
    const now = new Date();
    const sameYear = d.getFullYear() === now.getFullYear();
    return d.toLocaleDateString("en-GB", sameYear ? { month: "short", day: "numeric" } : { year: "numeric", month: "short", day: "numeric" });
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
    return plural(n, one, many);
  },
  bytes(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} kB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
  },
};

// "3 documents", "1 passage": the count and the word, the plural by adding s unless given.
export function plural(n, one, many) {
  return `${fmt.num(n)} ${n === 1 ? one : (many || one + "s")}`;
}
// A title cut to n characters, with an ellipsis; "untitled" when empty.
export function shortTitle(t, n = 70) {
  t = (t || "untitled").replace(/\s+/g, " ").trim();
  return t.length > n ? t.slice(0, n - 2).trimEnd() + "…" : t;
}
// "page 3" -> "Page 3"
export const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

// Plain vocabulary, used consistently on every screen. Technical names stay available in "details" places.
export const GRADE_TEXT = { supports: "Supports", partially_supports: "Partly supports", refutes: "Contradicts" };
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
// 0.8: the auditor gives second opinions and reads the hard cases again on a Claude route (Claude Code, the Claude
// API with a model per task): Opus, or Fable when switched on in Settings. null on a local route, or with the model
// per task switched off. `opts.claude` / `opts.fable` override the settings (the Settings page has them from
// /api/routing).
export function auditorName(s = App.settings(), opts = {}) {
  const claude = opts.claude !== undefined ? opts.claude : (["claude_code", "anthropic"].includes(s.backend) && s.routing !== false);
  if (!claude) return null;
  if (s.backend === "claude_code" && planTier(s) === "free") return "sonnet";  // 0.13.10: no Opus or Fable on Free
  return (opts.fable !== undefined ? opts.fable : s.use_fable) ? "fable" : "opus";
}
// 0.13.10: the Claude plan the recommended models follow (free | pro | max; "" not known): set by hand, else the one
// Claude Code names (found in the background)
export function planTier(s = App.settings()) {
  return s.claude_plan && s.claude_plan !== "auto" ? s.claude_plan : (s.claude_plan_detected || "");
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

// ---------------------------------------------------------------------------------------------
// toasts
// ---------------------------------------------------------------------------------------------
export function toast(message, kind = "info", opts = {}) {
  const box = document.getElementById("toasts");
  if (!box) return;
  const names = { info: "info", ok: "check", warn: "alert-triangle", error: "alert-circle" };   // a tick for done: the circle-tick is "Supported"
  if (opts.group) for (const old of box.querySelectorAll(`.toast[data-group="${opts.group}"]`)) old.remove();
  const t = h("div", { class: `toast toast-${kind}${opts.small ? " toast-small" : ""}`, role: kind === "error" ? "alert" : "status", dataset: opts.group ? { group: opts.group } : null },
    icon(names[kind] || "info"),
    h("div", { class: "toast-body" }, h("div", {}, message),
      opts.detail ? fold({ sm: true, class: "toast-detail" }, "Technical details", h("div", { class: "mono small" }, opts.detail)) : null,
      opts.action ? h("a", { href: opts.action.href, class: "toast-link" }, opts.action.text) : null,
      opts.button ? button({ sm: true, class: "toast-btn", onClick: () => { t.remove(); opts.button.onClick(); } }, opts.button.text) : null),
    iconButton({ icon: "x", label: "Dismiss", onClick: () => t.remove() }));
  box.appendChild(t);
  const ttl = opts.ttl || (kind === "error" ? 15000 : opts.button ? 9000 : 5000);
  setTimeout(() => { t.classList.add("toast-out"); setTimeout(() => t.remove(), 300); }, ttl);
  return t;
}

// Errors in plain words; the technical message is kept behind "Technical details".
// 0.14.3: a failed load drawn in the page itself (a toast fades, and a heading over nothing looks like "nothing here")
export function failedLoad(el, e) {
  replace(el, h("div", { class: "notice notice-error", role: "alert" }, icon("alert-circle"), h("p", {}, (e && e.message) || "This could not be loaded.")));
}

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
// `lock` (0.14.3): { on: true } while a request of the dialog runs: Escape, a click outside, the X and Cancel then do
// nothing, so the dialog cannot be closed on work that goes on without it (its report would never be seen)
export function dialog({ title, body, actions, danger, onOpen, wide, lock }) {
  return new Promise((resolve) => {
    const dlg = h("dialog", { class: "dialog" + (wide ? " dialog-wide" : ""), "aria-labelledby": "dlg-title" });
    const close = (value) => { if (lock && lock.on) return; dlg.close(); dlg.remove(); resolve(value); };
    const btns = (actions || [{ text: "Close", value: null }]).map((a) =>
      button({
        kind: a.primary ? (danger ? "confirm" : "main") : "quiet",
        id: a.id,
        disabled: a.disabled,
        onClick: async () => {
          if (a.onClick) { const r = await a.onClick(dlg); if (r === false) return; }
          close(a.value);
        },
      }, a.text));
    append(dlg, [
      h("div", { class: "dialog-head" }, h("h2", { id: "dlg-title" }, title),
        iconButton({ icon: "x", label: "Close", onClick: () => close(null) })),
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
    input = h("input", withClass(UI.input, { type: "text", autocomplete: "off", "aria-label": `Type ${typeToConfirm} to confirm` }));
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
// `filename` is used as given; otherwise the server's name, then `fallback`. Returns the response (its headers).
export async function download(path, filename, fallback) {
  const res = await api("GET", path, undefined, { raw: true });
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const m = /filename="?([^";]+)"?/.exec(cd);
  const name = filename || (m && m[1]) || fallback || "download";
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: name });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  return res;
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

// A running job of one of these kinds for this project, if any (`test(job)`: a further condition).
export async function runningJob(project, kinds, test) {
  try {
    const jobs = (await api("GET", "/api/jobs")).jobs || [];
    return jobs.find((j) => j.project === project && kinds.includes(j.kind) && !TERMINAL.has(j.state) && (!test || test(j))) || null;
  } catch (_) { return null; }
}

const jobListeners = new Set();
export function onJobsChanged(fn) { jobListeners.add(fn); return () => jobListeners.delete(fn); }
export function jobsChanged() { for (const fn of jobListeners) { try { fn(); } catch (e) { console.error(e); } } }

// ---------------------------------------------------------------------------------------------
// app state
// ---------------------------------------------------------------------------------------------
// 0.13.5: the app's name and words, from static/brand.json and add-ons (GET /api/state "brand"). Page code names the
// app with appName(), never with a fixed "ENLENS", so an app built on ENLENS is named right everywhere it shows.
export const DEFAULT_BRAND = {
  name: "ENLENS", tagline: "explore and check your documents", logo: "/static/logo.svg",
  welcome_title: "Explore your documents, and check what they say",
  welcome_text: "ENLENS reads your reports, papers and interview notes. Search them, see which topics and codes each one addresses, follow concepts and themes across them, and check a hypothesis against them, with the exact quotes so you can judge for yourself.",
  description: "Explore your documents and check hypotheses against them, with verified quotes.",
};
export function brand() { return { ...DEFAULT_BRAND, ...((App.state && App.state.brand) || {}) }; }
export function appName() { return brand().name; }

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
    if (b === "anthropic") return { where: "cloud", label: "Claude, through an API key", plain: "Excerpts of your documents are sent to the Claude API (cloud)", detail: `Claude API · ${s.anthropic_model || ""}`, icon: "cloud" };
    if (b === "claude_code") return { where: "cloud", label: "Claude, on your plan", sent: "Claude Code reads the passages on your Claude plan (sent to Anthropic).", short: "Only the passages of AI tasks leave this computer", plain: "Your documents stay here; only the passages inside the AI's tasks go to Anthropic.", detail: "Claude Code (your subscription) · a helper and model per task", icon: "cloud" };
    if (b === "baseline") return { where: "none", label: "Demo mode", short: "A stand-in, not an AI: results are not findings", plain: "No AI model: a simple word-overlap stand-in. Results are not findings.", detail: "offline demo", icon: "alert-triangle" };
    const labels = (App.state && App.state.backend_labels) || {};
    const model = b === "ollama" ? (s.ollama_model || "no model chosen") : b === "openai" ? (s.openai_model || "first model listed") : (s.ollama_model || s.openai_model || "first model found");
    return { where: "local", label: "A model on this computer", short: "The AI runs on this computer", plain: "The AI runs on this computer. Your documents never leave it.", detail: `${labels[b] || b} · ${model}`, icon: "house" };
  },
  modelConfigured() {
    const s = App.settings();
    if (s.backend === "ollama") return !!s.ollama_model;
    if (s.backend === "anthropic") return !!(App.state && App.state.key && (App.state.key.session || App.state.key.env || App.state.key.stored));
    return true;
  },
};

// 0.13.4: what Claude Code says about itself (found, signed in, which account), shared by the sidebar and Settings:
// asked again after a minute at most (the server asks Claude Code itself, and keeps the answer half a minute).
const claudeSeen = { at: 0, status: null, pending: null };
export function claudeStatus(maxAge = 60000) {
  if (claudeSeen.status && Date.now() - claudeSeen.at < maxAge) return Promise.resolve(claudeSeen.status);
  if (!claudeSeen.pending) {
    claudeSeen.pending = api("GET", "/api/claude-setup").then((r) => rememberClaude(r.status || {}))
      .finally(() => { claudeSeen.pending = null; });
  }
  return claudeSeen.pending;
}
// The answer last seen (or null), and a fresher one from Settings (Check again, a sign-in), so the sidebar has it too.
export function claudeSeenNow() { return claudeSeen.status; }
export function rememberClaude(st) { claudeSeen.status = st || {}; claudeSeen.at = Date.now(); return claudeSeen.status; }

// 0.13.6: whether a newer version waits (GET /api/update), shared by the sidebar's Update button, its pop-up and
// Settings → Check for updates. The page asks when it opens and every UPDATE_EVERY; the server keeps its answer a
// little less than that, so several tabs share one look. `fresh` looks again now. `install` is set by app.js (the
// confirmation, the update and the restart).
export const UPDATE_EVERY = 120000;
export const Updates = { info: null, error: null, at: 0, pending: null, listeners: new Set(), install: () => {}, quit: null };  // 0.17.0: quit (app.js) for Settings, while Update takes Quit's place
export function checkUpdate(fresh = false) {
  if (Updates.pending && !fresh) return Updates.pending;
  const ask = api("GET", fresh ? "/api/update?fresh=1" : "/api/update")
    .then((info) => { Updates.info = info; Updates.error = null; return info; },
      (e) => { Updates.error = e; throw e; })
    .finally(() => {
      Updates.at = Date.now();
      if (Updates.pending === ask) Updates.pending = null;
      for (const fn of Updates.listeners) { try { fn(Updates.info, Updates.error); } catch (e) { console.error(e); } }
    });
  Updates.pending = ask;
  return ask;
}
export function onUpdateSeen(fn) { Updates.listeners.add(fn); return () => Updates.listeners.delete(fn); }

// Which account Claude Code is signed in to, in words: { email, plan: "Team plan", org } or null when it is not
// signed in (or does not say). The organisation only on a Team or Enterprise plan: on Pro and Max it is usually Claude's
// own "…'s Organization".
export function claudeAccount(st) {
  if (!st || st.signed_in !== true) return null;
  const plan = st.plan ? `${st.plan[0].toUpperCase()}${st.plan.slice(1)} plan`
    : /^(api_key|console)$/i.test(st.auth_method || "") ? "Claude Console account" : "";
  return { email: st.email || "", plan, org: ["team", "enterprise"].includes(st.plan) ? (st.org_name || "") : "" };
}

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
  const run = (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  run.cancel = () => clearTimeout(t);   // 0.14.3
  return run;
}

// A random id for one upload batch: [A-Za-z0-9_-]
export function batchId() {
  const a = new Uint8Array(8);
  crypto.getRandomValues(a);
  return "u" + Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
}

// ---------------------------------------------------------------------------------------------
// The components (docs/DESIGN.md, section 4): one helper per kind of element, so a page names what it wants and never
// spells a component's classes. `UI` is the one table of those classes: a variant is named once, here and in its
// section of components.css. Every helper takes the attributes of h() besides its own options (a page's own class for
// placement, ids, aria-*, on*), and its children after them, like h().
// ---------------------------------------------------------------------------------------------
export const UI = {
  button: { main: "btn btn-primary", standard: "btn", quiet: "btn btn-ghost", danger: "btn btn-outline-danger", confirm: "btn btn-danger" },
  sm: "btn-sm",
  iconButton: "icon-btn", iconButtonSm: "icon-btn icon-btn-sm",
  link: { plain: "", title: "link-title", back: "link-back", next: "link-next", external: "link-external", jump: "link-jump" },
  tag: { neutral: "chip", code: "chip chip-code", attention: "warn-chip", count: "chip chip-count" },
  notice: { info: "notice notice-info", done: "notice notice-ok", attention: "notice notice-warn", error: "notice notice-error" },
  noticeIcon: { info: "info", done: "check", attention: "alert-triangle", error: "alert-circle" },
  card: "card", cardSm: "card-sm", fold: "fold", foldSm: "fold-sm", choice: "seg", choiceButton: "seg-btn", option: "option-card",
  input: "input", select: "select", textarea: "textarea", search: "search-field",
  menu: "menu-list", menuItem: "menu-item", menuSep: "menu-sep",
  workState: "work-state",
};

// h()'s attributes with the component's classes in front of the page's own
function withClass(cls, attrs = {}) {
  const own = attrs.class ? ` ${attrs.class}` : "";
  return { ...attrs, class: `${cls}${own}`.trim() };
}
function split(opts, keys) {
  const own = {}, rest = {};
  for (const [k, v] of Object.entries(opts || {})) (keys.includes(k) ? own : rest)[k] = v;
  return [own, rest];
}

// A button: something that does. kind: "standard" (default) | "main" (the one main action of a page, card or dialog)
// | "quiet" (lesser actions in rows) | "danger" (removes; opens the dialog that confirms) | "confirm" (only the confirming
// button of a dangerous dialog). sm: the small size. icon: an icon name before the words. busy: the loader turns and
// the button waits. toggle: a chevron that turns with aria-expanded (shows or hides a panel right under it).
export function button(opts = {}, ...children) {
  const [o, attrs] = split(opts, ["kind", "sm", "icon", "busy", "toggle", "opens", "wrap"]);
  const cls = [UI.button[o.kind || "standard"], o.sm ? UI.sm : "", o.toggle ? "btn-toggle" : "", o.opens ? "btn-opens" : "", o.wrap ? "btn-wrap" : ""].filter(Boolean).join(" ");
  const b = h("button", withClass(cls, { type: "button", ...attrs }),
    o.icon ? icon(o.icon, { size: o.sm ? 13 : 15 }) : null, children,
    o.toggle ? icon("chevron-down", { size: 13, class: "btn-chevron" }) : null);
  if (o.toggle && !b.hasAttribute("aria-expanded")) b.setAttribute("aria-expanded", "false");
  if (o.busy) setBusy(b, true);
  return b;
}

// A button at work: the loader turns in place of its icon, the words stay, it is disabled and keeps its width.
export function setBusy(b, busy) {
  b.disabled = !!busy;
  if (busy) b.setAttribute("aria-busy", "true"); else b.removeAttribute("aria-busy");
}

// A download: it makes a file, so it looks like a (quiet, small) button, though it may be an <a download>.
// opts.href: a file the browser fetches itself; otherwise onClick makes it.
export function downloadButton(opts = {}, ...children) {
  const [o, attrs] = split(opts, ["href", "kind"]);
  const cls = `${UI.button[o.kind || "quiet"]} ${UI.sm}`;
  if (o.href) return h("a", withClass(cls, { href: o.href, download: "", ...attrs }), icon("download", { size: 13 }), children);
  return h("button", withClass(cls, { type: "button", ...attrs }), icon("download", { size: 13 }), children);
}

// A file chooser drawn as a button (a <label> that holds the hidden input): choosing a file is an action.
export function fileButton(opts = {}, input, ...children) {
  const [o, attrs] = split(opts, ["kind", "sm", "icon"]);
  const cls = [UI.button[o.kind || "quiet"], o.sm === false ? "" : UI.sm].filter(Boolean).join(" ");
  input.classList.add("visually-hidden");
  return h("label", withClass(cls, attrs), o.icon ? icon(o.icon, { size: 13 }) : null, children, input);
}

// An icon button: an action shown by its icon alone (close, copy, theme, remove a word). label is its accessible name
// and tooltip. sm: 24 px, for dense rows and the help mark only.
export function iconButton(opts = {}) {
  const [o, attrs] = split(opts, ["icon", "label", "sm", "size"]);
  return h("button", withClass(o.sm ? UI.iconButtonSm : UI.iconButton, { type: "button", "aria-label": o.label, title: o.label, ...attrs }),
    icon(o.icon, { size: o.size || (o.sm ? 14 : 16) }));
}

// A link: it takes you somewhere. kind: "plain" (default; underlined accent words) | "title" (the name of an item in a
// list: accent words, underlined on hover; serif when serif: true, for the research's own words) | "back" (← and the
// place's name, above a page title) | "next" (the one way on from an empty state or a notice, to the page where the
// work is done: an arrow after) | "external" (opens outside the app: an icon after) | "jump" (a move to another place
// on this page that has no address of its own: a <button> drawn as a link, because it moves and changes nothing).
export function link(opts = {}, ...children) {
  const [o, attrs] = split(opts, ["kind", "serif"]);
  const kind = o.kind || "plain";
  const cls = [UI.link[kind], o.serif ? "serif" : ""].filter(Boolean).join(" ");
  if (kind === "jump") return h("button", withClass(cls, { type: "button", ...attrs }), children);
  const a = h("a", withClass(cls, attrs),
    kind === "back" ? icon("arrow-left", { size: 13 }) : null,
    children,
    kind === "next" ? icon("arrow-right", { size: 14 }) : null,
    kind === "external" ? icon("external-link", { size: 13 }) : null);
  if (kind === "external" && !a.target) { a.target = "_blank"; a.rel = "noopener"; }
  return a;
}

// A tag: a fact about an item, never pressed. kind: "neutral" (default) | "code" (a code, its code in 600) |
// "attention" (a fact that needs you: amber, with the triangle) | "count" (a small count beside a name).
export function tag(opts = {}, ...children) {
  const [o, attrs] = split(opts, ["kind", "icon"]);
  const kind = o.kind || "neutral";
  const ic = o.icon || (kind === "attention" ? "alert-triangle" : null);
  return h("span", withClass(UI.tag[kind], attrs), ic ? icon(ic, { size: 12 }) : null, children);
}

// A notice: something to know before going on, that stays while it is true. kind: "info" (default) | "done" (a state
// the page is about that stays true: set up, passed) | "attention" (needs you) | "error" (did not work). Its icon comes
// with its kind; icon: another icon name (the cloud, the house) or false. At most one action or one link after its
// words.
export function notice(opts = {}, ...children) {
  const [o, attrs] = split(opts, ["kind", "icon"]);
  const kind = o.kind || "info";
  const ic = o.icon === false ? null : (o.icon || UI.noticeIcon[kind]);
  const role = kind === "error" || kind === "attention" ? "alert" : null;
  return h("div", withClass(UI.notice[kind], { role, ...attrs }), ic ? icon(ic, { size: 16 }) : null, h("div", { class: "notice-body" }, children));
}

// A card: one thing, or one task, held together. opts.as: the element (default "section"); title, help (a helpMark)
// and action (one button) make its head.
// sm: the small card, one of many in a list (a note). as: "details" makes a card that folds: its first child is the
// <summary>, drawn as its title line with the fold's chevron.
export function card(opts = {}, ...children) {
  const [o, attrs] = split(opts, ["as", "title", "help", "action", "level", "sm"]);
  const head = o.title || o.action ? h("div", { class: "card-head" },
    o.title ? h(o.level || "h2", { class: "card-title-h" }, o.title, o.help || null) : null, o.action || null) : null;
  return h(o.as || "section", withClass(o.sm ? `${UI.card} ${UI.cardSm}` : UI.card, attrs), head, children);
}

// A fold: more here, folded away (More options, Technical details). open: open at first. sm: the small kind, for
// dense places (a card's foot, an excerpt's list, a toast).
export function fold(opts = {}, summary, ...children) {
  const [o, attrs] = split(opts, ["open", "sm"]);
  return h("details", withClass(o.sm ? `${UI.fold} ${UI.foldSm}` : UI.fold, { open: !!o.open, ...attrs }), h("summary", {}, summary), children);
}

// A choice: one of a few values, shown in place; the content follows it. options: [[value, words, count?]];
// filter: true for a filter of a list (each option shows the rows it would show, aria-pressed); otherwise a radio group.
// onPick(value) after the chosen value changes. Arrow keys move between the options.
export function choice(opts = {}) {
  const [o, attrs] = split(opts, ["label", "options", "value", "onPick", "filter", "sm"]);
  let value = o.value;
  const btns = [];
  const group = h("div", withClass(UI.choice + (o.sm ? " seg-sm" : ""), { role: o.filter ? "group" : "radiogroup", "aria-label": o.label, ...attrs }));
  const paint = () => btns.forEach((b) => {
    const on = b.dataset.value === String(value);
    if (o.filter) b.setAttribute("aria-pressed", on ? "true" : "false");
    else { b.setAttribute("aria-checked", on ? "true" : "false"); b.tabIndex = on ? 0 : -1; }
  });
  for (const [v, words, count, title] of o.options || []) {
    const b = h("button", { class: UI.choiceButton, type: "button", role: o.filter ? null : "radio", "data-value": String(v), title: title || null,
      onClick: () => { value = v; paint(); if (o.onPick) o.onPick(v); } },
      words, count !== undefined && count !== null ? h("span", { class: "count" }, String(count)) : null);
    btns.push(b);
  }
  group.addEventListener("keydown", (e) => {
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) return;
    const i = btns.indexOf(document.activeElement);
    if (i < 0) return;
    const j = (i + (e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 1) + btns.length) % btns.length;
    btns[j].focus();
    if (!o.filter) btns[j].click();
    e.preventDefault();
  });
  append(group, btns);
  paint();
  group.set = (v) => { value = v; paint(); };
  return group;
}

// Option cards: a choice whose options each need a sentence (which AI reads the documents, how to start a codebook).
// options: [{ value, title, text, icon, tag, foot, disabled }]: tag a few words at the head's right (Recommended), foot
// a line under the text (where text goes). A radio group whose chosen card is marked by aria-checked; with `name`, the
// cards are labels holding real radio inputs of that name (a form's question, changed with the arrow keys). onPick(value)
// after a pick; .set(value) chooses one without calling it.
export function optionCards(opts = {}) {
  const [o, attrs] = split(opts, ["label", "options", "value", "onPick", "name"]);
  const cards = [];
  const group = h("div", withClass("option-cards", { role: "radiogroup", "aria-label": o.label, ...attrs }));
  const paint = (v) => cards.forEach((c) => {
    const on = c.dataset.value === String(v);
    if (o.name) c.querySelector("input").checked = on;
    else { c.setAttribute("aria-checked", on ? "true" : "false"); c.tabIndex = on ? 0 : -1; }
  });
  for (const op of o.options || []) {
    const inner = [h("span", { class: "option-card-head" }, op.icon ? icon(op.icon, { size: 16 }) : null, h("span", { class: "option-card-title" }, op.title),
      op.tag ? tag({}, op.tag) : null),
      op.text ? h("span", { class: "option-card-sub" }, op.text) : null,
      op.foot ? h("span", { class: "option-card-foot" }, op.foot) : null];
    let c;
    if (o.name) {
      const radio = h("input", { type: "radio", name: o.name, value: String(op.value), checked: String(op.value) === String(o.value), disabled: !!op.disabled });
      radio.addEventListener("change", () => { if (radio.checked && o.onPick) o.onPick(op.value); });
      c = h("label", { class: UI.option, "data-value": String(op.value), "aria-disabled": op.disabled ? "true" : null }, radio, inner);
    } else {
      c = h("button", { class: UI.option, type: "button", role: "radio", "data-value": String(op.value), disabled: !!op.disabled,
        onClick: () => { paint(op.value); if (o.onPick) o.onPick(op.value); } }, inner);
    }
    cards.push(c);
  }
  append(group, cards);
  paint(o.value);
  group.set = paint;
  return group;
}

// Form controls (put them in field()): a text input, a select (children: its <option>s), a multi-line box. mono: for
// codes and commands. hyp: the box a hypothesis is written in (serif).
export function input(opts = {}) {
  const [o, attrs] = split(opts, ["mono", "sm"]);
  return h("input", withClass([UI.input, o.mono ? "input-mono" : "", o.sm ? "input-sm" : ""].filter(Boolean).join(" "), { type: "text", ...attrs }));
}
export function select(opts = {}, ...options) {
  const [o, attrs] = split(opts, ["sm"]);
  return h("select", withClass(UI.select + (o.sm ? " input-sm" : ""), attrs), options);
}
export function textarea(opts = {}) {
  const [o, attrs] = split(opts, ["hyp", "mono"]);
  return h("textarea", withClass([UI.textarea, o.hyp ? "textarea-hyp" : "", o.mono ? "input-mono" : ""].filter(Boolean).join(" "), attrs));
}
// A search box: the magnifier inside the field. Returns the <label>; its .input is the <input>.
export function searchField(opts = {}) {
  const inp = h("input", withClass(UI.input, { type: "search", ...opts, class: opts.class || null }));
  const lab = h("label", { class: UI.search }, icon("search", { size: 15 }), inp);
  lab.input = inp;
  return lab;
}

// A menu: more actions for one thing, under its button. items: [{ text, icon, onClick, danger, current }] or "sep".
// The button is a small quiet button: the words (default "More") and the more icon; Escape and a click outside close.
export function menu(opts = {}) {
  const [o, attrs] = split(opts, ["items", "text", "label"]);
  const list = h("div", { class: UI.menu, role: "menu" });
  const trigger = h("summary", { class: `${UI.button.quiet} ${UI.sm}`, "aria-haspopup": "menu", "aria-label": o.label || null },
    icon("more-horizontal", { size: 14 }), o.text || "More");
  const det = h("details", withClass("menu", attrs), trigger, list);
  const close = () => { det.open = false; };
  for (const it of o.items || []) {
    if (it === "sep") { list.appendChild(h("div", { class: UI.menuSep, role: "separator" })); continue; }
    list.appendChild(h("button", { class: UI.menuItem + (it.danger ? " menu-item-danger" : ""), type: "button", role: "menuitem",
      "aria-current": it.current ? "true" : null, disabled: !!it.disabled,
      onClick: (e) => { close(); if (it.onClick) it.onClick(e); } }, it.icon ? icon(it.icon, { size: 14 }) : null, it.text));
  }
  det.addEventListener("keydown", (e) => { if (e.key === "Escape" && det.open) { close(); trigger.focus(); e.stopPropagation(); } });
  document.addEventListener("click", (e) => { if (det.open && !det.contains(e.target)) close(); });
  return det;
}

// A person mark: who did something, beside an item, a judgement, a log entry or a review. The person icon, then "You"
// or a colleague's initials (several people: each, "You" first), and a role when it matters (Owner, Collaborator).
// The full names and the role are its tooltip and its accessible name. note: a word after the role's dot instead of a
// role ("partly", while only part is reviewed).
export function personMark(people, opts = {}) {
  const list = (people || []).filter(Boolean);
  if (!list.length) return null;
  const names = list.length > 1 ? `${list.slice(0, -1).join(", ")} and ${list[list.length - 1]}` : list[0];
  const words = `${opts.prefix ? `${opts.prefix} ` : ""}${names}${opts.role ? ` (${opts.role})` : ""}`;
  const short = list.map((p) => (p === "you" ? "You" : p.split(/\s+/).map((w) => w[0] || "").join("").slice(0, 2).toUpperCase()));
  const after = opts.role || opts.note;
  return h("span", { class: `${UI.tag.neutral} person-mark`, title: cap(words), "aria-label": cap(words), role: "img" },
    icon(list.length > 1 ? "users" : "user", { size: 12 }), h("span", { "aria-hidden": "true" }, short.join(" · ")),
    after ? h("span", { class: "person-mark-role", "aria-hidden": "true" }, after) : null);
}
// Reviewed: who judged the excerpts an answer rests on (the person mark's first use); "You · partly" while only part is.
export function reviewedMark(people, partly) {
  return personMark(people, { prefix: partly ? "Partly reviewed by" : "Reviewed by", note: partly ? "partly" : null });
}

// A severity (of a proposed change): low, medium or high, as a tag; never a judgement colour. High needs you: the
// attention tag.
export function severityTag(level) {
  const words = { low: "Low", medium: "Medium", high: "High" }[level] || level;
  return level === "high" ? tag({ kind: "attention", title: "Severity: high" }, words)
    : tag({ class: `severity-${level}`, title: `Severity: ${words.toLowerCase()}` }, words);
}

// An item's sharing state (working together): Private (only on this computer), Shared (in the shared folder),
// Withdrawn (no longer shared). A tag with its icon; its tooltip says what it means.
export function shareState(state) {
  const [ic, words, title] = { private: ["house", "Private", "Only on this computer"], shared: ["users", "Shared", "In the shared folder: colleagues see it"],
    withdrawn: ["undo", "Withdrawn", "No longer shared; colleagues keep what they had"] }[state] || ["house", state, null];
  return tag({ icon: ic, title, class: "share-state" }, words);
}

// A document this copy does not hold (a colleague's check or note names it): its title as plain words (nothing to
// open), the tag "not on this computer" and, when it can be added, the small quiet button "Add its file".
export function absentDocument(title, opts = {}) {
  return h("span", { class: "doc-absent" }, h("span", { class: "doc-absent-title" }, title),
    tag({ icon: "file-x", title: "A colleague's work names this document; its file is not in this copy of the project" }, "not on this computer"),
    opts.onAdd ? button({ kind: "quiet", sm: true, icon: "upload", onClick: opts.onAdd }, "Add its file") : null);
}

// A row of a list (in the drawer or on a page): who (a person mark), the item's name as its title link, when, and one
// or two small actions at the row's end. sub: a quiet second line under the name (a colleague's ENLENS version);
// warn: true when that line needs you (it becomes an attention tag). Rows are grouped under a small heading by
// listGroup(heading, …rows), by person or by day.
export function listRow({ person, title, href, time, sub, warn, actions = [] }) {
  return h("li", { class: "list-row" }, person || null,
    h("div", { class: "list-row-main" }, href ? link({ kind: "title", href }, title) : h("span", {}, title),
      sub ? (warn ? tag({ kind: "attention" }, sub) : h("span", { class: "list-row-sub" }, sub)) : null),
    time ? h("time", { class: "list-row-time" }, time) : null,
    actions.length ? h("span", { class: "list-row-actions" }, ...actions) : null);
}
export function listGroup(heading, ...rows) {
  return h("section", { class: "list-group" }, h("h3", { class: "list-head" }, heading), h("ul", { class: "list-rows" }, ...rows));
}

// A list of problems, one notice each (the shared folder: one per colleague or per kind): items [{ kind, person, text,
// action }]; kind as notice()'s (attention: needs you, error: did not work, info: wait and it passes).
export function noticeList(items) {
  return h("ul", { class: "notice-list" }, items.filter(Boolean).map((it) =>
    h("li", {}, notice({ kind: it.kind || "attention" }, h("p", {}, it.person || null, it.person ? " " : null, it.text), it.action || null))));
}

// A side-by-side comparison of two versions of one thing (yours and a colleague's, before and after): two columns,
// each with its heading (a person mark, a time), the actions under them (Keep mine, Keep theirs, Keep both).
export function compare({ left, right, actions, label }) {
  const side = (s) => h("div", { class: "compare-side" }, h("div", { class: "compare-head" }, s.title, s.meta || null), h("div", { class: "compare-body" }, s.body));
  return h("div", { class: "compare", role: "group", "aria-label": label || "Two versions side by side" },
    h("div", { class: "compare-sides" }, side(left), side(right)), actions ? h("div", { class: "compare-actions btn-row" }, actions) : null);
}

// A work state: work under way, waiting, not running, done or did not work, in words and an icon (never a pill).
// state: "running" | "waiting" (queued: starts when … has finished) | "stopped" (not running) | "done" (synced, finished)
// | "failed" | "attention" (needs you: a folder not reachable, a newer ENLENS needed); time: seconds for a running state.
export function workState(state, words, time) {
  const ic = { waiting: "clock", stopped: "pause", done: "check", failed: "alert-circle", attention: "alert-triangle" }[state];
  return h("span", { class: `${UI.workState} work-${state}` },
    state === "running" ? h("span", { class: "running-dot", "aria-hidden": "true" }) : icon(ic || "circle", { size: 13 }),
    h("span", {}, words), time !== undefined && time !== null ? h("span", { class: "work-state-time" }, fmt.secs(time)) : null);
}

// The drawer: your own working space beside any page (the research log; in 0.18 also working together). One panel on
// the right, opened by one button in the same place on every page (drawerButton()). Its head shows the title, or, when
// it holds two or more tabs, the tabs (tabs: [{ key, label, icon }], current, onTab(key): the head's view tabs); then at
// most one control (a choice) and the close button. `sections` are its body's parts, top to bottom, each drawn by its
// content's own components (a write box, a list); the last may grow and scroll. `foot`: one link to the whole view.
// A new tab is a new entry in `tabs` whose onTab draws its own sections (setSections()); a new section is one more
// element in `sections`. Opening and closing: body[data-drawer="open"], set by setDrawerOpen().
export function drawer({ id, title, icon: ic, tabs, current, onTab, control, sections = [], foot, onClose, closeLabel }) {
  const close = iconButton({ icon: "x", label: closeLabel || `Close ${title.toLowerCase()}`, onClick: () => onClose && onClose() });
  const tabList = tabs && tabs.length > 1 ? h("div", { class: "drawer-tabs settings-tabs", role: "tablist", "aria-label": title },
    tabs.map((t) => h("button", { type: "button", role: "tab", "aria-selected": t.key === current ? "true" : "false",
      "aria-current": t.key === current ? "page" : null, onClick: () => onTab && onTab(t.key) }, t.icon ? icon(t.icon, { size: 14 }) : null, t.label))) : null;
  const body = h("div", { class: "drawer-body" });
  const aside = h("aside", { class: "drawer", id, "aria-label": title, hidden: true },
    h("div", { class: "drawer-head" }, tabList || [ic ? icon(ic, { size: 16 }) : null, h("h2", { class: "drawer-title" }, title)], control || null, close),
    body,
    foot ? h("div", { class: "drawer-foot" }, foot) : null);
  aside.setSections = (parts) => replace(body, ...parts.filter(Boolean).map((el) => { el.classList.add("drawer-section"); return el; }));
  aside.setSections(sections);
  aside.closeButton = close;
  return aside;
}
// The drawer's button: a small button that stays in the same spot on every page, soft teal while its drawer is open.
export function drawerButton({ id, controls, label, icon: ic, onClick, title }) {
  return h("button", { class: `${UI.button.standard} ${UI.sm} btn-opens drawer-btn`, id, type: "button", "aria-expanded": "false",
    "aria-controls": controls, title: title || null, onClick }, icon(ic, { size: 15 }), h("span", { class: "drawer-btn-text" }, label));
}
export function setDrawerOpen(open, btn) {
  if (open) document.body.dataset.drawer = "open"; else delete document.body.dataset.drawer;
  if (btn) btn.setAttribute("aria-expanded", open ? "true" : "false");
}

// Where text goes, and which AI reads it (the AI line): the cloud (Claude), the house (this computer) or the folder (a
// folder shared with colleagues) and one sentence. One per card that holds such actions, at its foot; never in the
// row of a button. "attention": no AI can run yet.
export function aiWhere(text, where = "cloud") {
  const ic = { local: "house", attention: "alert-triangle", folder: "folder" }[where] || "cloud";
  return h("p", { class: where === "attention" ? "ai-where ai-where-attention" : "ai-where" }, icon(ic, { size: 13 }), h("span", {}, text));
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

// 0.14.3: the pages that work on the documents (Search, Profile, Concepts) say "Add documents first" in a project
// with none, as Check and Overview do, instead of offering a button that answers "0 documents"
export function noDocuments() {
  const p = ((App.state && App.state.projects) || []).find((x) => x.name === App.project);
  return !!p && p.ok !== false && p.documents === 0;
}
export function addDocumentsFirst(what) {
  // a step done on another page: the one way on is a next-step link, not a button (docs/DESIGN.md, Links)
  return notice({ kind: "info" }, h("p", {}, h("strong", {}, "Add documents first. "), `${what} works on the documents of this project, and there are none yet.`),
    h("p", {}, link({ kind: "next", href: "#/sources" }, "Add documents on the Documents page")));
}

// The answer of a check as a judgement badge (a pill: the only pills in the app). "Not finished", "Did not work" and
// "Waiting for Claude Code" are states of work, not judgements: they are drawn as a work state (words and an icon).
const WORK_STATUS = { not_checked: "stopped", failed: "failed", waiting: "waiting" };
export function statusBadge(status, opts = {}) {
  const iconName = STATUS_ICON[status] || "circle";
  const text = opts.text || (opts.short ? STATUS_SHORT[status] : null) || App.statusText(status) || status;
  const title = opts.title || (opts.short ? `${App.statusText(status)}. ` : "") + (App.statusHelp(status) || "") || null;
  if (WORK_STATUS[status]) {
    const w = workState(WORK_STATUS[status], text);
    w.classList.add(`status-${status}`);
    if (opts.class) w.classList.add(...opts.class.split(" ").filter(Boolean));
    if (title) w.title = title;
    return w;
  }
  return h("span", { class: `badge status-${status} ${opts.size === "lg" ? "badge-lg" : ""} ${opts.class || ""}`, title: opts.title || (opts.short ? `${App.statusText(status)}. ` : "") + (App.statusHelp(status) || "") || null },
    icon(iconName, { size: opts.size === "lg" ? 20 : 14 }), opts.prefix ? h("span", { class: "badge-prefix" }, opts.prefix, " ") : null, h("span", {}, text));
}

// 0.11.2: a small mark beside an answer a stronger model changed: "at first: Partly supported". The stronger model's
// reading is the answer; the mark keeps the first one in sight (hover or click for the whole story).
export function strongerMark(before, info = {}, opts = {}) {
  if (!before) return null;
  const was = STATUS_SHORT[before] || before;
  const first = (info.first_models || []).join(", ") || "the first AI model";
  const strong = (info.models || []).join(", ") || "a stronger model";
  const n = info.changed || 0;
  const story = `The first AI model (${first}) found this ${was.toLowerCase()}. A stronger model (${strong}) read the excerpts again${n ? ` and changed ${n} ${n === 1 ? "judgement" : "judgements"}` : ""}; its reading counts, so this is the answer now. Each excerpt it changed shows both readings.`;
  const label = opts.compact ? `was ${was.toLowerCase()}` : `at first: ${was.toLowerCase()}`;
  if (opts.plain) return tag({ class: "was-mark", title: story, icon: "layers" }, h("span", {}, label));
  const btn = h("button", { class: `${UI.tag.neutral} was-mark`, type: "button", "aria-label": `Changed by a stronger model; at first ${was.toLowerCase()}` }, icon("layers", { size: 12 }), h("span", {}, label));
  const wrap = popNote(btn, story, { wide: true });
  wrap.classList.add("was-wrap");
  return wrap;
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

// A heat cell of a documents × codes (or themes × documents) grid, on a log scale so one very large cell does not
// leave the others pale: classes `<prefix>-cell <prefix>-l0..4` (components.css, 4.25 The heat grid).
export function heatCell(n, max, label, prefix, onClick) {
  const level = n ? Math.max(1, Math.min(4, Math.ceil((4 * Math.log1p(n)) / Math.log1p(max)))) : 0;
  // 0.14.3: a cell with passages holds a button (Tab and Enter reach it); the cell's own click still works for the mouse
  return h("td", { class: `map-cell heat-l${level} ${prefix}-cell ${prefix}-l${level}`, title: `${label}: ${plural(n, "passage")}`, onClick: n ? onClick : null },
    n && onClick ? h("button", { class: "heat-btn", type: "button", "aria-label": `${label}: ${plural(n, "passage")}` }, String(n))
      : [h("span", { class: "visually-hidden" }, `${label}: `), n ? String(n) : h("span", { "aria-label": "none" }, "·")]);
}

// 0.16 (H5): a long list drawn in steps, so a project of hundreds of documents opens its page at once: the first
// `first` items now, then `step` more whenever the end of what is drawn comes within about a screen of the window
// (or "Show more" is used, from the keyboard or where the page cannot tell). `more(left, onClick)` makes the element
// that stands at the end (a table row for a table body); `render` may return null for an item to leave out.
export function drawInSteps(parent, items, render, { first = 60, step = 120, more } = {}) {
  let done = 0, observer = null;
  const button = (left, onClick) => h("button", { class: `${UI.button.quiet} ${UI.sm}`, type: "button", onClick }, icon("chevron-down", { size: 13 }), `Show more (${left} more)`);
  const tail = more || ((left, onClick) => h("div", { class: "draw-more" }, button(left, onClick)));
  let end = null;
  const next = (n, byHand) => {
    const slice = items.slice(done, done + n);
    done += slice.length;
    const nodes = slice.map(render).filter((x) => x != null);
    if (end) end.remove();
    parent.append(...nodes);
    // "Show more" used from the keyboard: the focus goes on to the first new row, not back to the top of the page
    if (byHand && nodes.length) {
      const first = nodes[0].querySelector("a[href], button, input, select, [tabindex]") || nodes[0];
      if (first === nodes[0] && !first.hasAttribute("tabindex")) first.setAttribute("tabindex", "-1");
      first.focus({ preventScroll: false });
    }
    end = null;
    if (done < items.length) {
      end = tail(items.length - done, () => next(step, true));
      parent.append(end);
      if (observer) observer.observe(end);
    } else if (observer) { observer.disconnect(); observer = null; }
  };
  if ("IntersectionObserver" in window && items.length > first) {
    observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting) && end && end.isConnected) next(step);
      else if (end && !end.isConnected) { observer.disconnect(); observer = null; }  // the list was drawn again
    }, { rootMargin: "900px 0px" });
  }
  next(first);
  return { drawn: () => done, button };
}

// 0.13.3: the result page's help mark, for every page: a small (?) whose explanation opens on hover, focus or click,
// so a page says one short line and keeps the longer explanation one step away.
export function helpMark(label, text, opts = {}) {
  return popNote(iconButton({ icon: "help", label, sm: true, size: opts.size || 13, class: "help-mark", title: null }),
    text, { wide: opts.wide !== false });
}

// Downloads, quiet: "Download" and one small quiet button per file (a download makes a file: an action, so a
// button, never a link), so they never compete with the page's main action. items: [{ text, title, onClick, note }]
export function downloadLinks(items, opts = {}) {
  const parts = [];
  items.filter(Boolean).forEach((it) => {
    parts.push(downloadButton({ title: it.title || null, onClick: it.onClick }, it.text));
    if (it.note) parts.push(h("span", { class: "muted small" }, it.note));
  });
  return h("span", { class: "dl-links" }, h("span", { class: "dl-label" }, opts.label || "Download"), parts);
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
// `where`: where it is pasted, for the confirmation ("Claude Code", or "a terminal" for a command line).
export function copyLine(text, label = "Copy", where = "Claude Code") {
  const btn = button({ kind: "quiet", sm: true, class: "copy-btn", "aria-label": `${label}: ${text}` }, icon("copy", { size: 13 }), label);
  btn.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(text); toast(`Copied. Paste it in ${where}.`, "ok", { ttl: 2000 }); }
    catch (_) { const r = document.createRange(); r.selectNodeContents(code); const s = getSelection(); s.removeAllRanges(); s.addRange(r); toast("Selected: copy it with Ctrl+C (or Cmd+C).", "info"); }
  });
  const code = h("code", { class: "copy-code" }, text);
  return h("div", { class: "copy-line" }, icon("terminal", { size: 13 }), code, btn);
}

// What waits for Claude Code, for a page that waits on it: the line, the estimate, a button that starts Claude Code
// (0.9), the command to type instead (opts.foldType: in a fold, 0.12), and the privacy note.
export function queueNotice(q, opts = {}) {
  if (!q) return null;
  const est = q.estimate || "";
  // a notice (attention while nothing answers it), its one action Start Claude Code, and the AI line once, at its foot
  return notice({ kind: q.paused ? "attention" : "info", icon: q.paused ? "pause" : "inbox", class: `queue-notice${q.paused ? " queue-paused" : ""}`, role: "status" },
    h("p", { class: "qn-head" }, h("strong", {}, q.text || "Waiting for Claude Code"),
      q.being_answered ? h("span", { class: "muted small qn-answered" }, ` · ${q.being_answered} being answered now`) : null),
    est && !q.paused ? h("p", { class: "muted small" }, est.charAt(0).toUpperCase() + est.slice(1) + ".") : null,
    q.paused && q.paused_text ? h("p", { class: "small" }, q.paused_text) : null,
    App.project ? startClaude(App.project, { command: q.command, foldType: opts.foldType }) : null,
    opts.privacy === false || opts.foldType ? null : aiWhere(q.privacy || "Claude Code sends the passages inside the tasks it takes to Anthropic."));
}

// 0.9: "Start Claude Code": ENLENS starts Claude Code (signed in with its own login, on the researcher's plan) for
// the project's queue, and shows while it works. The command to type in Claude Code yourself stays one line below.
// The element keeps itself current while it is on the page.
export function startClaude(project, opts = {}) {
  const box = h("div", { class: "start-claude", dataset: { project } });
  let timer = null;
  let busy = false;
  const ago = (s) => (s < 60 ? "just now" : `${Math.round(s / 60)} min ago`);
  // 0.11.3: an unpressed button asks for attention: the step above it spins, which reads as if work were under way.
  // A few seconds after work starts waiting with nothing answering it, the button pulses and its line says that
  // nothing runs until it is pressed. Changed in place, so the button never moves under the pointer.
  function nudge(b, hint) {
    if (b.classList.contains("sc-nudge")) return;
    b.classList.add("sc-nudge");
    b.style.animationDelay = `-${Date.now() % NUDGE_PULSE}ms`;  // in step with the other buttons, and across redraws
    hint.classList.add("sc-wake");
    if (!opts.foldType) replace(hint, h("strong", {}, "Nothing runs until you press it."), " Then it works on your Claude plan, in the background, and stops by itself when nothing waits.");
  }
  function watchIdle(b, hint) {
    if (!WAIT_SINCE.has(project)) WAIT_SINCE.set(project, Date.now());
    const left = NUDGE_AFTER - (Date.now() - WAIT_SINCE.get(project));
    if (left <= 0) nudge(b, hint);
    // look again when the nudge is due, then every 5 s: once something answers, draw the new state
    timer = setTimeout(async () => {
      if (!b.isConnected || busy) return;
      let q;
      const c = QUEUE_CACHE.get(project);
      try { q = c && c.q && Date.now() - c.at < 3000 ? c.q : await queueFetch(project); } catch (_) { return; }
      if (!b.isConnected || busy) return;
      if (idleQueue(q)) watchIdle(b, hint); else draw(true);
    }, Math.max(left, 0) || 5000);
  }
  async function draw(useCache) {
    clearTimeout(timer);
    if (!box.isConnected && box.dataset.drawn) return;  // the page moved on
    let q;
    const cached = QUEUE_CACHE.get(project);
    if (useCache && cached && cached.q) {
      q = cached.q;  // draw at once from the last answer (a page that redraws often never waits)
      if (Date.now() - cached.at > 3000) queueFetch(project).then(() => { if (box.isConnected) draw(true); }).catch(() => {});
    } else {
      try { q = await queueFetch(project); } catch (_) { return; }
    }
    box.dataset.drawn = "1";
    const cmd = opts.command || q.command || `/enlens-run ${project}`;
    const typeIt = h("div", { class: "sc-type" }, h("span", { class: "muted small" }, q.can_start ? "Or type this in Claude Code yourself:" : "In Claude Code (opened in any folder), type:"), copyLine(cmd));
    // 0.12, opts.foldType (the result page's waiting card): one line under the button; how it works, the command to
    // type and what is sent sit in a fold
    const typeBlock = opts.foldType && q.can_start ? fold({ sm: true, class: "sc-type-fold" }, "How it works",
      h("p", { class: "small" }, "It works on your Claude plan, in the background, and stops by itself when nothing waits."),
      h("div", { class: "sc-type" }, h("span", { class: "muted small" }, "Or type this in Claude Code yourself:"), copyLine(cmd)),
      h("p", { class: "muted small" }, icon("cloud", { size: 12 }), " ", q.privacy || "Claude Code sends the passages inside the tasks it takes to Anthropic.")) : typeIt;
    const r = q.runner || {};
    const parts = [];
    const idle = idleQueue(q);
    if (!idle) WAIT_SINCE.delete(project);
    if (q.route !== "claude_code") { replace(box, typeIt); return; }
    if (r.running) {
      parts.push(h("div", { class: "sc-running" }, h("span", { class: "running-dot", "aria-hidden": "true" }),
        h("span", {}, h("strong", {}, "Claude Code is working on it"), h("span", { class: "muted small" }, ` · started ${ago(r.seconds || 0)} from ${appName()}${planText(r) ? ` · ${planText(r)}` : ""}`)),
        h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: async () => {
          try { await api("POST", `/api/projects/${P(project)}/queue/claude-code/stop`, {}); toast("Claude Code stopped. What it had not answered waits again.", "ok"); QUEUE_CACHE.delete(project); draw(false); } catch (e) { showError(e); }
        } }, icon("stop", { size: 12 }), "Stop Claude Code")));  // 0.11.3: not just "Stop": the job beside it has its own
    } else if (q.can_start && (q.waiting || q.being_answered || opts.always)) {
      const b = h("button", { class: "btn btn-primary btn-sm", type: "button", onClick: async () => {
        if (busy) return;
        busy = true; b.disabled = true; b.classList.remove("sc-nudge");
        const body = runBody(project, q);
        const listed = (q.speed && q.speed.helpers) || [];
        if (body.helpers && listed.length && !listed.some((r) => body.helpers[r.helper] > 0)) {
          busy = false; b.disabled = false;
          showError(new Error("Every helper is set to 0 under “Choose the helpers for this run”: give at least one helper 1 or more."));
          return;
        }
        try {
          await api("POST", `/api/projects/${P(project)}/queue/claude-code`, body);
          RUN_CHOICE.delete(project);  // the helpers chosen were for this run only
          toast("Claude Code started. You can keep working; the results appear as they come in.", "ok");
        } catch (e) { showError(e); }
        busy = false; QUEUE_CACHE.delete(project); await draw(false);
        choiceChanged(project, box);
      } }, icon("play", { size: 13 }), "Start Claude Code");
      const hint = h("span", { class: "muted small" }, opts.foldType ? "Nothing runs until you press it." : "Runs on your Claude plan, in the background. It stops by itself when nothing waits.");
      parts.push(h("div", { class: "sc-start" }, b, hint));
      if (idle) watchIdle(b, hint);
      // 0.13.10: the speed (kept), and the helpers for this run (folded away)
      if (q.speed) {
        const custom = customRun(RUN_CHOICE.get(project));
        const speed = speedPicker(q.speed.chosen, q.speed.options, async (v) => {
          await saveSpeed(v);
          RUN_CHOICE.delete(project);  // a speed picked (even the one shown) replaces the helpers chosen for this run
          await draw(false);
          const again = box.querySelector(`.sc-speed [data-speed="${v}"]`);
          if (again) again.focus();
          choiceChanged(project, box);
        }, { custom: () => customRun(RUN_CHOICE.get(project)) });
        if (custom) speed.classList.add("sc-speed-off");
        parts.push(speed, helpersFold(project, q, () => {
          speed.classList.toggle("sc-speed-off", customRun(RUN_CHOICE.get(project)));
          choiceChanged(project, box);
        }));
      }
      if (r.exit_code !== undefined && r.exit_code !== null && r.exit_code !== 0 && !r.stopped) {
        parts.push(fold({ sm: true }, [icon("alert-circle", { size: 12 }), " The last run stopped with a problem"], h("pre", { class: "mono small sc-report" }, r.report || "(no report)")));
      }
    } else if (!q.can_start && q.claude && !q.claude.found) {
      parts.push(h("p", { class: "small sc-missing" }, icon("info", { size: 12 }), " Claude Code was not found on this computer. ", h("a", { href: "#/settings/model" }, "Set it up"), " to start it from here."));
    }
    if (q.claude && q.claude.signed_in === false) parts.push(h("p", { class: "small" }, icon("info", { size: 12 }), " Sign in to Claude Code once: open a terminal, type ", h("code", {}, "claude"), " and sign in with your Claude plan."));
    replace(box, ...parts, r.running ? null : typeBlock);
    // the page may have moved on (or re-drawn its panel) by then: a detached box fetches nothing
    if (r.running) timer = setTimeout(() => { if (box.isConnected) queueFetch(project).then(() => draw(true)).catch(() => {}); }, 4000);
    else if (r.seconds !== undefined && opts.onDone && box.dataset.wasRunning === "1") opts.onDone();
    box.dataset.wasRunning = r.running ? "1" : "0";
  }
  // 0.13.10: two of these for one project can be on the page at once (the sidebar's job and queue panels): a choice
  // made in one shows in the other
  for (const e of [...SC_LIVE]) if (e.box.dataset.drawn && !e.box.isConnected) SC_LIVE.delete(e);
  SC_LIVE.add({ project, box, redraw: () => draw(true) });
  draw(true);
  return box;
}
const QUEUE_CACHE = new Map();
const SC_LIVE = new Set();  // the Start Claude Code elements made, until they have left the page
function choiceChanged(project, from) {
  for (const e of [...SC_LIVE]) {
    if (e.box === from || e.project !== project) continue;
    if (e.box.isConnected) e.redraw(); else if (e.box.dataset.drawn) SC_LIVE.delete(e);
  }
}

// 0.13.10: how fast Claude Code works: how many helpers it starts at once (one, two or four). Faster is done sooner
// and uses the plan's limits faster. The choice is kept (Settings' claude_speed) and shows beside every Start Claude
// Code and under Settings → AI. "Choose the helpers for this run", folded away, names the helpers one by one.
const SPEED_CHOICES = [["slower", "Slower"], ["normal", "Normal"], ["faster", "Faster"]];
const SPEED_NOTE = { slower: ": slowest, and easiest on your plan's limits", faster: ": done sooner, but uses your plan's limits faster" };
const helpersText = (n) => `${n} helper${n === 1 ? "" : "s"}`;

export async function saveSpeed(speed) {
  const r = await api("PUT", "/api/settings", { claude_speed: speed });
  App.state.settings = r.settings;
  QUEUE_CACHE.clear();  // the estimates follow the speed
  return r;
}

// The three speeds as one row of buttons, with a line saying what the chosen one does. `options`: {speed: helpers at
// once}; `onPick(speed)` saves it (a failure puts the choice back). `opts.custom()`: whether helpers were chosen for
// the run, so that the speed shown can be picked again; `opts.label`: null for none.
export function speedPicker(chosen, options = { slower: 1, normal: 2, faster: 4 }, onPick = saveSpeed, opts = {}) {
  let current = chosen || "normal";
  const line = h("span", { class: "muted small sc-speed-line" });
  const group = h("div", { class: `${UI.choice} seg-sm sc-speed-btns`, role: "group", "aria-label": "Speed of Claude Code" });
  const show = (v) => {
    for (const b of group.children) { const on = b.dataset.speed === v; b.setAttribute("aria-pressed", on ? "true" : "false"); }
    line.textContent = `${helpersText(options[v] || 2)} at a time${SPEED_NOTE[v] || ""}.`;
  };
  for (const [v, label] of SPEED_CHOICES) {
    group.appendChild(h("button", { class: UI.choiceButton, type: "button", dataset: { speed: v }, onClick: async () => {
      if (v === current && !(opts.custom && opts.custom())) return;  // the speed shown, picked again, undoes a choice of helpers
      const before = current;
      current = v; show(v);
      try { await onPick(v); } catch (e) { current = before; show(before); showError(e); }
    } }, label));
  }
  show(current);
  const label = opts.label === undefined ? "Speed" : opts.label;
  return h("div", { class: "sc-speed" }, label ? h("span", { class: "sc-speed-label small" }, label) : null, group, line);
}

// "For this run": the choices made in the fold, per project, until the run starts (kept in memory only, so a panel
// that draws itself again keeps them).
const RUN_CHOICE = new Map();
function runChoice(project) {
  if (!RUN_CHOICE.has(project)) RUN_CHOICE.set(project, { open: false, total: null, counts: {} });
  return RUN_CHOICE.get(project);
}
const customRun = (c) => !!c && (c.total !== null || Object.keys(c.counts).length > 0);
// what Start Claude Code sends: nothing (the speed of Settings), or {parallel, helpers}
function runBody(project, q) {
  const c = RUN_CHOICE.get(project);
  if (!customRun(c)) return {};
  const sp = q.speed || {};
  const total = c.total ?? ((sp.options || {})[sp.chosen] || 2);
  const body = { parallel: total };
  if (Object.keys(c.counts).length) {
    // the helpers listed as chosen; one each for the others, whose work may come in during the run (a check's
    // search words lead to excerpts to judge, an unsure answer goes to the auditor)
    const dflt = (r) => Math.min(total, sp.max_per_helper || 4, Math.max(1, r.batches || 1));
    body.helpers = Object.fromEntries((sp.all_helpers || []).map((hp) => [hp, 1]));
    for (const r of sp.helpers || []) body.helpers[r.helper] = c.counts[r.helper] ?? dflt(r);
  }
  return body;
}
const planText = (r) => (r.parallel ? `${helpersText(r.parallel)} at once${r.helpers ? ", chosen for this run" : ""}` : "");

let FOLD_SEQ = 0;  // each fold's own ids (two folds for one project can be on the page)
function helpersFold(project, q, onChange) {
  const sp = q.speed || {};
  const rows = sp.helpers || [];
  const uid = `sc${++FOLD_SEQ}`;
  const C = () => runChoice(project);  // looked up each time: a start or a speed picked elsewhere starts it afresh
  const speedN = (sp.options || {})[sp.chosen] || 2;
  const maxAll = sp.max_parallel || 8, maxOne = sp.max_per_helper || 4;
  const total = () => C().total ?? speedN;
  const dflt = (r) => Math.min(total(), maxOne, Math.max(1, r.batches || 1));
  const value = (r) => C().counts[r.helper] ?? dflt(r);
  const range = (from, to) => Array.from({ length: to - from + 1 }, (_, i) => from + i);
  const helpers = fold({ sm: true, class: "sc-helpers", open: C().open }, null);
  const refocus = (id) => { const el = helpers.querySelector(`[id="${id}"]`); if (el) el.focus(); };  // the list drawn again
  const summary = helpers.firstElementChild;
  const body = h("div", { class: "sc-helpers-body" });
  helpers.append(body);
  helpers.addEventListener("toggle", () => { C().open = helpers.open; });
  function draw() {
    replace(summary, "Choose the helpers for this run", customRun(C()) ? h("span", { class: "chip" }, "changed") : null);
    const totalSel = h("select", { class: "select select-sm", id: `${uid}-total` },
      range(1, maxAll).map((n) => h("option", { value: n, selected: n === total() }, n)));
    totalSel.addEventListener("change", () => { const n = Number(totalSel.value); C().total = n === speedN ? null : n; draw(); onChange(); refocus(totalSel.id); });
    const list = rows.map((r, i) => {
      const id = `${uid}-h${i}`;
      const sel = h("select", { class: "select select-sm", id, "aria-describedby": `${id}-what` },
        range(0, maxOne).map((n) => h("option", { value: n, selected: n === value(r) }, n)));
      sel.addEventListener("change", () => { C().counts[r.helper] = Number(sel.value); draw(); onChange(); refocus(id); });
      return h("div", { class: "sc-helper" + (value(r) === 0 ? " sc-helper-off" : "") },
        h("label", { class: "sc-helper-name", for: id }, cap(r.name), h("span", { class: "muted mono" }, ` ${r.models.join(", ")}`)),
        h("span", { class: "sc-helper-what muted", id: `${id}-what` }, `${r.kinds.join(", ")} · ${r.waiting.toLocaleString()} waiting`), sel);
    });
    const named = rows.reduce((s, r) => s + value(r), 0);
    const n = Object.keys(C().counts).length ? Math.min(total(), named) : total();
    const back = customRun(C()) ? h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => { const c = C(); c.total = null; c.counts = {}; draw(); onChange(); } },
      icon("refresh", { size: 12 }), "Use the speed again") : null;
    replace(body,
      h("div", { class: "sc-total" }, h("label", { for: totalSel.id }, "Helpers at once, in all"), totalSel),
      rows.length ? h("div", { class: "sc-helper-list", role: "group", "aria-label": "How many of each helper at once" }, list) : h("p", { class: "muted" }, "No work waits for a helper just now."),
      h("p", { class: "muted" }, named === 0 ? h("strong", {}, "Nothing would run: give at least one helper 1 or more. ")
        : `Up to ${helpersText(n)} at once, `, "for this run only. 0 leaves that work waiting. Work that comes in during the run for a helper not listed here (an unsure answer for the auditor, for example) gets one. ",
        "Which model each helper uses is set under ", h("a", { href: "#/settings/routing" }, "AI model per task"), "."),
      back);
  }
  draw();
  return helpers;
}
// 0.11.3, the Start Claude Code nudge: when a project's work first waited with nothing answering it (kept per project, as
// the sidebar draws its button again every 5 s and the progress panel whenever the queue's line changes).
const NUDGE_AFTER = 5000;
const NUDGE_PULSE = 1600;  // the length of one pulse of .btn.sc-nudge (components.css, 4.1)
const WAIT_SINCE = new Map();
const idleQueue = (q) => !!(q && q.route === "claude_code" && q.can_start && !(q.runner || {}).running && q.waiting && !q.being_answered);
// one request at a time per project; the answer is kept for the next element that draws
function queueFetch(project) {
  const c = QUEUE_CACHE.get(project) || {};
  if (c.inflight) return c.inflight;
  const p = api("GET", `/api/projects/${P(project)}/queue`).then((q) => { QUEUE_CACHE.set(project, { q, at: Date.now() }); return q; })
    .finally(() => { const now = QUEUE_CACHE.get(project); if (now && now.inflight === p) delete now.inflight; });
  QUEUE_CACHE.set(project, { ...c, inflight: p });
  return p;
}

// 0.17.0: start Claude Code for a project's queue from a single button (the status area at the foot of the sidebar),
// with the speed of Settings or the helpers chosen for this run. Settings › AI has the whole choice.
export async function startClaudeNow(project) {
  const q = await queueFetch(project);
  await api("POST", `/api/projects/${P(project)}/queue/claude-code`, runBody(project, q));
  RUN_CHOICE.delete(project);
  QUEUE_CACHE.delete(project);
}

// 0.10: how to get Tesseract (text recognition for scanned PDFs) on this computer's system, as the server says
// (ocr.install: {text, command, link, link_text}); the Python parts are a technical detail.
export function tesseractHelp(ocr) {
  const how = (ocr && ocr.install) || null;
  if (!how) return null;
  const py = ((ocr && ocr.missing) || []).filter((m) => m !== "tesseract");
  return h("div", { class: "tess-help" },
    h("p", { class: "small" }, "Scanned pages need Tesseract, a free text-recognition program. ", how.text),
    how.command ? copyLine(how.command, "Copy", "a terminal") : null,
    h("p", { class: "small" }, how.link ? h("a", { href: how.link, target: "_blank", rel: "noopener" }, how.link_text || "How to install it") : null,
      how.link ? " · " : null, `${appName()} notices it within a minute; then add the document again.`),
    py.length ? fold({}, "Technical details", h("p", { class: "small" }, `Also missing in ENLENS's Python: ${py.join(", ")}. Install them with `, h("code", {}, "pip install 'enlens-claims[ocr]'"), " (the one-line install brings them).")) : null);
}
