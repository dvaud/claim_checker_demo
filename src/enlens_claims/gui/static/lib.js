// Shared plumbing: API client, DOM helpers, formatting, toasts, dialogs, job polling and app state.
import { icon, STATUS_ICON } from "./icons.js";

// ---------------------------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------------------------
// 0.17.2: the page never carries the access token (any account on this computer could fetch it). It comes in the link
// the app opens (or the terminal shows), after # so it never reaches a server: #token=…, kept for this tab only and
// taken out of the address bar. A tab opened without it (a new tab, a bookmark) asks this browser's other ENLENS tabs
// (ensureToken); when none has it, the page says how to open ENLENS (app.js).
const TOKEN_KEY = "enlens-token";
const TOKEN_RX = /^[A-Za-z0-9_-]{16,}$/;
function keepToken(t) { try { sessionStorage.setItem(TOKEN_KEY, t); } catch (_) { /* this tab only, then */ } }
let fromStore = false;   // the token came from this tab's storage (a reload): it may be from before a restart
function readToken() {
  const m = /(?:^#|&)token=([A-Za-z0-9_-]+)/.exec(location.hash || "");
  if (m) {
    keepToken(m[1]);
    try { history.replaceState(null, "", location.pathname + "#/"); } catch (_) { /* the address keeps it */ }
    return m[1];
  }
  try { const t = sessionStorage.getItem(TOKEN_KEY) || ""; fromStore = !!t; return t; } catch (_) { return ""; }
}
export let TOKEN = readToken();

// The app's other tabs in this browser: a BroadcastChannel reaches only pages of the same address (this app, in this
// browser, so this account), never another web site or another account's browser. Each tab that has the token
// answers; the asking tab takes the first answer the app accepts (a tab left open from before a restart holds an old
// one).
const CHANNEL = "enlens-token";
function channel() {
  try { return typeof BroadcastChannel === "function" ? new BroadcastChannel(CHANNEL) : null; } catch (_) { return null; }
}
async function askOtherTabs(wait = 400) {
  const ch = channel();
  if (!ch) return [];
  const got = [];
  ch.onmessage = (e) => { const t = e.data && e.data.token; if (typeof t === "string" && TOKEN_RX.test(t) && !got.includes(t)) got.push(t); };
  ch.postMessage({ ask: true });
  await new Promise((r) => setTimeout(r, wait));
  ch.close();
  return got;
}
// true: the app takes it; false: it refuses it (401); null: no answer (the app is not running: say that, not "old key")
async function verdict(t) {
  try { const r = await fetch("/api/jobs", { headers: { "X-Enlens-Token": t } }); return r.status === 401 ? false : r.ok ? true : null; }
  catch (_) { return null; }
}
let answering = null, stale = false;
export const keyWasStale = () => stale;
export async function ensureToken() {
  // a token this tab kept from before ENLENS started again: drop it, and ask the other tabs as a tab without one would
  if (TOKEN && fromStore && (await verdict(TOKEN)) === false) {
    stale = true; TOKEN = "";
    try { sessionStorage.removeItem(TOKEN_KEY); } catch (_) { /* gone with the tab */ }
  }
  if (!TOKEN) {
    for (const t of await askOtherTabs()) if ((await verdict(t)) === true) { TOKEN = t; keepToken(t); stale = false; break; }
  }
  if (TOKEN && !answering && (answering = channel())) {
    answering.onmessage = (e) => { if (e.data && e.data.ask && TOKEN) answering.postMessage({ token: TOKEN }); };
  }
  return TOKEN;
}
// 0.17.2: the link that opens ENLENS with this tab's token (Settings › Technical › Your link to ENLENS)
export function myLink() { return TOKEN ? `${location.origin}/#token=${TOKEN}` : ""; }
export const OPEN_FROM_ICON = "Open ENLENS from its icon (or run enlens-gui).";
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
    const err = new ApiError(res.status, res.status === 401 ? (TOKEN ? `This tab's key to ENLENS no longer works: ENLENS has started again since it was opened. ${OPEN_FROM_ICON}` : `This tab was opened without ENLENS's key. ${OPEN_FROM_ICON}`) : msg,
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
// Words the program found by matching (a search, a code's words, the words that name a work): soft teal, never the
// quote's yellow (docs/DESIGN.md 4.23)
export function foundWords(text) { return h("mark", { class: "found" }, text); }

// ---------------------------------------------------------------------------------------------
// Text positions. The app counts the characters of a text as Python does, one per code point; a JavaScript string
// counts UTF-16 units, so a character outside the Basic Multilingual Plane (an emoji, a mathematical letter such as
// 𝑥 that PDFs of papers are full of, a rare CJK character) is one position there and two here. Every offset the app
// sends (a quote’s quote_start/quote_end, a block’s start/end, the marks of a search, a note’s place, breaks) is
// turned into a string index with these before a slice, and every position the page sends back (a selection, a word
// clicked) is turned into the app’s count first. Offsets inside one string that never leave the page need neither.
// ---------------------------------------------------------------------------------------------
const SURROGATE = /[\uD800-\uDFFF]/;
const PLAIN_POSITIONS = { index: (cp) => cp, point: (i) => i, length: 0, plain: true };
const POSITIONS = new Map();   // the tables of the texts used last (a block’s text is looked at once per decoration)
// The table of one text: index(cp) gives the string index of the app’s offset cp, point(i) the app’s offset of the
// string index i (an index inside a pair of surrogates counts as the pair’s start), length the text’s length as the
// app counts it. A text without such characters (nearly all) is tested once and its offsets are its indices.
export function textPositions(text) {
  text = String(text ?? "");
  const known = POSITIONS.get(text);
  if (known) return known;
  let table;
  if (!SURROGATE.test(text)) table = { ...PLAIN_POSITIONS, length: text.length };
  else {
    const astral = [];   // the string index of each such character’s first half, in order
    for (let i = 0; i + 1 < text.length; i++) {
      const c = text.charCodeAt(i);
      if (c >= 0xD800 && c <= 0xDBFF && (text.charCodeAt(i + 1) & 0xFC00) === 0xDC00) { astral.push(i); i++; }
    }
    // how many of the first `n` such characters satisfy `test` (it holds for a prefix of them): a bisection
    const count = (test) => { let lo = 0, hi = astral.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (test(mid)) lo = mid + 1; else hi = mid; } return lo; };
    table = {
      plain: !astral.length,
      length: text.length - astral.length,
      // the k-th such character is at the app’s offset astral[k] - k; each one before cp adds a unit
      index: (cp) => cp + count((k) => astral[k] - k < cp),
      point: (i) => {
        const k = count((j) => astral[j] < i);   // characters starting before i
        if (k && astral[k - 1] + 1 === i) return astral[k - 1] - (k - 1);   // inside a pair: its start
        return i - k;
      },
    };
  }
  if (POSITIONS.size >= 256) POSITIONS.delete(POSITIONS.keys().next().value);
  POSITIONS.set(text, table);
  return table;
}
// The string index of the app’s offset `cp` in `text`, and back; the length of `text` as the app counts it.
export function cpToIndex(text, cp) { return Number.isInteger(cp) ? textPositions(text).index(cp) : cp; }
export function indexToCp(text, i) { return Number.isInteger(i) ? textPositions(text).point(i) : i; }
export function cpLength(text) { return textPositions(text).length; }
// The word around the string index `i` of `text`: [start, end) as string indices, or null when `i` is not in or right
// after a word. A letter outside the BMP (𝑥, 𐍈, 𠀀) is two UTF-16 units: it is looked at whole, so it is a word's letter
// like any other (looked at as halves, neither half is a letter and a click on it picked nothing).
const WORD_CHAR = /[\p{L}\p{N}_'’-]/u;
export function wordSpan(text, i) {
  const t = String(text ?? "");
  const at = (j) => (j >= 0 && j < t.length ? String.fromCodePoint(t.codePointAt(j)) : "");
  const back = (j) => (j >= 2 && (t.charCodeAt(j - 1) & 0xFC00) === 0xDC00 && (t.charCodeAt(j - 2) & 0xFC00) === 0xD800 ? j - 2 : j - 1);
  const fwd = (j) => j + (t.codePointAt(j) > 0xFFFF ? 2 : 1);
  if ((t.charCodeAt(i) & 0xFC00) === 0xDC00 && i > 0 && (t.charCodeAt(i - 1) & 0xFC00) === 0xD800) i--;   // inside a pair: its start
  if (!WORD_CHAR.test(at(i))) { if (i > 0 && WORD_CHAR.test(at(back(i)))) i = back(i); else return null; }
  let s = i, e = fwd(i);
  while (s > 0 && WORD_CHAR.test(at(back(s)))) s = back(s);
  while (e < t.length && WORD_CHAR.test(at(e))) e = fwd(e);
  while (s < e && /['’-]/.test(t[s])) s++;
  while (e > s && /['’-]/.test(t[e - 1])) e--;
  return e > s ? [s, e] : null;
}
// A list of breaks ({at, end, …}, the app’s offsets in `text`) as string indices.
export function breaksToIndex(text, breaks) {
  if (!Array.isArray(breaks)) return breaks;
  const pos = textPositions(text);
  if (pos.plain) return breaks;
  return breaks.map((b) => (b && typeof b === "object" ? { ...b, at: Number.isInteger(b.at) ? pos.index(b.at) : b.at, end: Number.isInteger(b.end) ? pos.index(b.end) : b.end } : b));
}

// `start`, `end` and the breaks are string indices of `text`: the app’s offsets (a quote’s quote_start, a block’s
// headings) go through cpToIndex() and breaksToIndex() first.
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
// Offsets here are string indices: the app’s go through breaksToIndex() first.
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
  // "Today 17:26", "Yesterday 17:26", "4 Nov 17:26", "4 Nov 2025 17:26" (the research log’s way, and the shared
  // folder’s): `t` an ISO time, or a number of seconds or milliseconds since 1970; "" when there is none
  whenText(t, now = new Date()) {
    if (t === null || t === undefined || t === "") return "";
    const m = typeof t === "number" ? (t < 1e12 ? t * 1000 : t) : Date.parse(t);
    if (Number.isNaN(m)) return String(t);
    const d = new Date(m);
    const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
    const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const diff = Math.round((day(now) - day(d)) / 86400000);
    if (diff === 0) return `Today ${time}`;
    if (diff === 1) return `Yesterday ${time}`;
    const sameYear = d.getFullYear() === now.getFullYear();
    return `${d.toLocaleDateString("en-GB", sameYear ? { day: "numeric", month: "short" } : { day: "numeric", month: "short", year: "numeric" })} ${time}`;
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
// A text with each run of white space as one space and none at the ends: two texts that differ only in line breaks or
// spacing then compare alike (a hypothesis, and the title of the job that checks it).
export const norm = (t) => String(t || "").split(/\s+/).filter(Boolean).join(" ");

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

// A link’s address only when it uses one of `schemes` (by default the web’s own: http and https; the Zotero links
// also "zotero"); otherwise null, so h() leaves the href out. An address from a file or a library (a bibliography
// entry’s link) is never trusted to be a web page: "javascript:" and the like never reach a link.
export function safeHref(url, schemes = ["http", "https"]) {
  const m = /^\s*([a-z][a-z0-9+.-]*):/i.exec(String(url ?? ""));
  return m && schemes.includes(m[1].toLowerCase()) ? String(url).trim() : null;
}

// The Search page for some words: `#/search?q=…`; opts.mode ("phrase": the words as one phrase) and any other
// option of the page (docs, exact…) are added as given.
export function searchHref(words, opts = {}) {
  const qs = new URLSearchParams({ q: String(words ?? "") });
  for (const [k, v] of Object.entries(opts)) if (v !== undefined && v !== null && v !== "" && v !== false) qs.set(k, v === true ? "1" : String(v));
  return `#/search?${qs.toString().replace(/\+/g, "%20")}`;
}

// The newest of several requests of one kind: `const fresh = latest();` then, for each request, `const mine =
// fresh();` before it and `if (!mine()) return;` after it. An older answer that arrives after a newer request was
// made is dropped, so it never draws over the newer one (paging Next, Next; a poll answered after a save).
// fresh.quiet() is for a request that looks again on its own (every few seconds): it is dropped like the others when
// a request was made after it, but makes no other request old.
export function latest() {
  let seq = 0;
  const fresh = () => { const my = ++seq; return () => my === seq; };
  fresh.quiet = () => { const my = seq; return () => my === seq; };
  return fresh;
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
  replace(el, notice({ kind: "error" }, h("p", {}, (e && e.message) || "This could not be loaded.")));
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
  saveBlob(blob, filename || dispositionName(res.headers.get("Content-Disposition")) || fallback || "download");
  return res;
}

// The name of the file from a Content-Disposition header: the real one in filename*=UTF-8''… first (the app puts a name
// with accents there, "Ábel Gergő"), else the plain filename="…", which holds only an ASCII stand-in for it ("_bel
// Gerg_"). "" when it names none.
export function dispositionName(cd) {
  cd = String(cd || "");
  const star = /filename\*\s*=\s*([^']*)'[^']*'([^;]+)/i.exec(cd);
  if (star) {
    try { return decodeURIComponent(star[2].trim().replace(/^"|"$/g, "")); } catch (_) { /* a broken name: the plain one */ }
  }
  const m = /filename\s*=\s*(?:"([^"]*)"|([^;]+))/i.exec(cd);
  return m ? (m[1] !== undefined ? m[1] : m[2].trim()) : "";
}

// A file made in the page (or fetched) saved under `name`: the browser’s own download.
export function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: name || "download" });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

// An uploaded text file (a CSV, a list) as text: UTF-8, else the Windows code page of a spreadsheet saved in Europe
// (f.text() read every file as UTF-8 and garbled the others: ő and ű mark the Central European page).
export async function readTextFile(f) {
  const bytes = new Uint8Array(await f.arrayBuffer());
  try { return new TextDecoder("utf-8", { fatal: true }).decode(bytes).replace(/^﻿/, ""); }
  catch (_) { return new TextDecoder(bytes.some((b) => b === 0xF5 || b === 0xD5) ? "windows-1250" : "windows-1252").decode(bytes); }
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
      if (job.waiting_for) queuedToast(job);   // 0.18 queued jobs
      else if (queuedToasts.has(job.id)) document.querySelectorAll(`.toast[data-group="queued-${job.id}"]`).forEach((t) => t.remove());
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

// 0.18 queued jobs: a job that waits for another job of its project says so once, in a toast with Cancel
const queuedToasts = new Set();
function queuedToast(job) {
  if (queuedToasts.has(job.id)) return;
  queuedToasts.add(job.id);
  toast(`${job.waiting_for.message}.`, "info", { group: `queued-${job.id}`, button: { text: "Cancel", onClick: async () => {
    try {   // only while it still waits: once it has started, Stop on its card stops it
      const now = await api("GET", `/api/jobs/${P(job.id)}`);
      if (now.waiting_for) await cancelJob(job.id);
      else if (!TERMINAL.has(now.state)) toast("It has started already: stop it from its card if you want to.", "info");
    } catch (e) { showError(e); }
  } } });
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

// What is new in this version (gui/static/whats-new.md), its points read only when asked. After an update a small note
// in the corner says the version and its title, with Read what's new (app.js whatsNewInit), until it is read or closed;
// Settings (beside the version) and Find (which goes to Settings › Technical) offer it always. One look (GET /api/whats-new) for them all:
// it also brings, once, the note of an update on Windows that did not finish (`note`, which app.js shows by itself).
export const WhatsNew = { changes: null, unread: false, pending: null };
export function loadWhatsNew() {
  if (!WhatsNew.pending) {
    WhatsNew.pending = api("GET", "/api/whats-new").then((r) => {
      WhatsNew.changes = r.changes && Array.isArray(r.changes.points) && r.changes.points.length ? r.changes : null;
      WhatsNew.unread = !!(WhatsNew.changes && r.unread);
      return r;
    }, () => ({ note: null }));
  }
  return WhatsNew.pending;
}
export function markWhatsNewRead() {
  if (!WhatsNew.unread) return;
  WhatsNew.unread = false;
  api("POST", "/api/whats-new/read").catch(() => {});
  window.dispatchEvent(new CustomEvent("enlens-whats-new-read"));
}
export function showWhatsNew() {
  const n = WhatsNew.changes;
  if (!n) return Promise.resolve(null);
  markWhatsNewRead();
  return dialog({ title: `What's new in ${n.version}`, body: h("div", { class: "news-note" },
    h("p", { class: "news-title" }, n.title),
    n.subtitle ? h("p", { class: "news-sub" }, n.subtitle) : null,
    h("ul", { class: "news-list" }, ...n.points.map((t) => h("li", {}, t))),
    n.url ? h("p", { class: "small" }, link({ kind: "external", href: n.url }, `Every change in ${n.version}, on GitHub`)) : null) });
}
// The words that open it, where it is offered always (Settings): a link drawn as a button (`jump`), since it opens a
// dialog and changes nothing; nothing when this version has no note.
export function whatsNewLink() {
  const slot = h("span", {});
  loadWhatsNew().then(() => {
    if (WhatsNew.changes) replace(slot, " · ", link({ kind: "jump", onClick: () => showWhatsNew(), "aria-haspopup": "dialog" }, "What's new"));
  });
  return slot;
}

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
  cardHead: "card-head", pageHead: "page-head", tabs: "settings-tabs",
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

// A button's kind, changed in place: a button that becomes the main one when its step comes (the sidebar's Update,
// set-up's Next once Claude is ready). Only its kind's classes change.
export function setButtonKind(b, kind) {
  b.classList.remove(...new Set(Object.values(UI.button).join(" ").split(" ")));
  b.classList.add(...UI.button[kind || "standard"].split(" "));
}

// A button at work: the loader turns in place of its icon, the words stay, it is disabled and keeps its width.
const BUSY_ICON = new WeakMap();   // a busy button's own icon, put back when the work ends
export function setBusy(b, busy) {
  b.disabled = !!busy;
  const first = b.firstElementChild;
  if (busy) {
    b.setAttribute("aria-busy", "true");
    if (first && first.classList.contains("icon") && !BUSY_ICON.has(b)) {
      BUSY_ICON.set(b, first);
      first.replaceWith(icon("loader", { size: Number(first.getAttribute("width")) || 15 }));
    }
  } else {
    b.removeAttribute("aria-busy");
    if (BUSY_ICON.has(b)) { if (first) first.replaceWith(BUSY_ICON.get(b)); BUSY_ICON.delete(b); }
  }
}

// A job's Stop: a small quiet button with the stop icon. It ends work under way and removes nothing (what is done is
// kept), so it is never a danger button. opts.text: "Stop Claude Code" where the job beside it has its own Stop.
export function stopButton(opts = {}) {
  const [o, attrs] = split(opts, ["text"]);
  return button({ ...attrs, kind: "quiet", sm: true, icon: "stop" }, o.text || "Stop");
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
// words. live: how a screen reader hears it (docs/DESIGN.md 4.12, 8). A notice drawn with the page is read with the
// page: no live role. One that appears because of what you just did says so: "status" (read when the reader is free:
// a test's outcome, what came of adding documents) or "alert" (read at once). An error is an alert unless live says
// otherwise.
export function notice(opts = {}, ...children) {
  const [o, attrs] = split(opts, ["kind", "icon", "live"]);
  const kind = o.kind || "info";
  const ic = o.icon === false ? null : (o.icon || UI.noticeIcon[kind]);
  const role = o.live === undefined ? (kind === "error" ? "alert" : null) : (o.live || null);
  return h("div", withClass(UI.notice[kind], { role, ...attrs }), ic ? icon(ic, { size: 16 }) : null, h("div", { class: "notice-body" }, children));
}

// The one box a card may hold (docs/DESIGN.md 4.11): --surface-2, no edge, the control's corners. One of a list inside
// a card (a label in a document's Codes panel, a concept's link, a codebook's Try it) or one aside (a calibration, a
// comparison). as: the element (default "div"; "li" in a list). tentative: not in force yet (a reading the AI proposed
// and nobody confirmed, a proposed link): a dashed edge. A box where a dragged item may land says so with
// data-drop="true".
export function inset(opts = {}, ...children) {
  const [o, attrs] = split(opts, ["as", "tentative"]);
  return h(o.as || "div", withClass(o.tentative ? "inset inset-tentative" : "inset", attrs), ...children);
}

// A card: one thing, or one task, held together. opts.as: the element (default "section"); title, help (a helpMark)
// and action (one button) make its head; level: the title's element (default "h2"); titleId: the title's id, which
// also names the card (aria-labelledby). A page never spells the head itself.
// sm: the small card, one of many in a list (a note). as: "details" makes a card that folds: its first child is the
// <summary>, drawn as its title line with the fold's chevron.
export function card(opts = {}, ...children) {
  const [o, attrs] = split(opts, ["as", "title", "titleId", "help", "action", "level", "sm"]);
  if (o.titleId && o.title && !attrs["aria-label"] && !attrs["aria-labelledby"]) attrs["aria-labelledby"] = o.titleId;
  const head = o.title || o.action ? h("div", { class: UI.cardHead },
    o.title ? h(o.level || "h2", { class: "card-title-h", id: o.titleId || null }, o.title, o.help || null) : null, o.action || null) : null;
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

// A menu: more actions for one thing, or a list to pick from, under its button. items: [{ text, icon, onClick, href,
// meta, title, danger, current, disabled }] or "sep" (href: a row that goes somewhere; meta: quiet words after the
// row's own). The button is a small quiet button: the words (default "More") and the more icon; or, with trigger, the
// summary holds those children and takes its look from where it is placed (the project switch, docs/DESIGN.md 5.1).
// listClass: the list's own class for placement. Escape and a click outside close it.
export function menu(opts = {}) {
  const [o, attrs] = split(opts, ["items", "text", "label", "title", "trigger", "listClass"]);
  const list = h("div", { class: o.listClass ? `${UI.menu} ${o.listClass}` : UI.menu, role: "menu" });
  const trigger = o.trigger
    ? h("summary", { "aria-haspopup": "menu", "aria-label": o.label || null, title: o.title || null }, o.trigger)
    : h("summary", { class: `${UI.button.quiet} ${UI.sm}`, "aria-haspopup": "menu", "aria-label": o.label || null, title: o.title || null },
      icon("more-horizontal", { size: 14 }), o.text || "More");
  const det = h("details", withClass("menu", attrs), trigger, list);
  const close = () => { det.open = false; };
  for (const it of o.items || []) {
    if (it === "sep") { list.appendChild(h("div", { class: UI.menuSep, role: "separator" })); continue; }
    const inner = [it.icon ? icon(it.icon, { size: 14 }) : null,
      it.meta ? h("span", { class: "menu-text" }, it.text, h("span", { class: "menu-meta" }, it.meta)) : it.text];
    const cls = UI.menuItem + (it.danger ? " menu-item-danger" : "");
    list.appendChild(it.href
      ? h("a", { class: cls, href: it.href, role: "menuitem", title: it.title || null, onClick: close }, inner)
      : h("button", { class: cls, type: "button", role: "menuitem", title: it.title || null,
        "aria-current": it.current ? "true" : null, disabled: !!it.disabled,
        onClick: (e) => { close(); if (it.onClick) it.onClick(e); } }, inner));
  }
  det.addEventListener("keydown", (e) => { if (e.key === "Escape" && det.open) { close(); trigger.focus(); e.stopPropagation(); } });
  // Where a frame would cut the open list (a table that scrolls, its last row), the list floats over the page instead,
  // under its button, toward the side with room; a scroll of the page or a resize closes it, as it would leave its
  // button behind. Where the list fits inside every frame around it (the project switch in the sidebar, a menu in the
  // drawer), it hangs from its button as always.
  const cutBy = () => {
    const l = list.getBoundingClientRect();
    for (let el = det.parentElement; el && el !== document.body; el = el.parentElement) {
      const cs = getComputedStyle(el);
      if (cs.overflowX === "visible" && cs.overflowY === "visible") continue;
      const f = el.getBoundingClientRect();
      if (l.left < f.left - 1 || l.right > f.right + 1 || l.top < f.top - 1 || l.bottom > f.bottom + 1) return el;
    }
    return null;
  };
  const unfloat = () => { delete list.dataset.float; list.style.left = ""; list.style.top = ""; };
  // the list's own scrolling (a long project list) is not a scroll that leaves the button behind
  const away = (e) => { if (e && e.type === "scroll" && e.target instanceof Node && list.contains(e.target)) return; if (det.open) close(); };
  det.addEventListener("toggle", () => {
    if (!det.open) { unfloat(); MENUS_OPEN.delete(det); unfloatMenu(det); return; }
    MENUS_OPEN.add(det);
    unfloat();   // measured where it hangs from its button
    const frame = cutBy();
    if (!frame) return;
    list.dataset.float = "true";
    const r = trigger.getBoundingClientRect(), f = frame.getBoundingClientRect(), w = list.offsetWidth, hgt = list.offsetHeight;
    // its end under the button's end when that keeps it over the frame, else its start under the button's start
    const x = r.right - w >= Math.max(8, f.left) ? r.right - w : Math.min(r.left, window.innerWidth - w - 8);
    list.style.left = `${Math.round(Math.max(8, x))}px`;
    list.style.top = `${Math.round(r.bottom + 4 + hgt <= window.innerHeight - 8 ? r.bottom + 4 : Math.max(8, r.top - 4 - hgt))}px`;
    floatMenu(det, away);
  });
  if (!MENU_CLICKS.on) { document.addEventListener("click", menuClick); MENU_CLICKS.on = true; }
  return det;
}
// Every menu shares the same listeners, so a list with a menu per row (the Documents page) adds none of its own: one
// click listener on the document closes an open menu the click was not in, and, only while a floating list is open,
// one scroll and one resize listener on the window close it. A menu removed from the page while open is forgotten.
const MENU_CLICKS = { on: false };
const MENUS_OPEN = new Set();    // the menus open now
const MENUS_FLOAT = new Map();   // a menu whose list floats -> what a scroll or resize does to it
function menuClick(e) {
  for (const det of [...MENUS_OPEN]) {
    if (det.isConnected === false || !det.open) { MENUS_OPEN.delete(det); unfloatMenu(det); continue; }
    if (!det.contains(e.target)) det.open = false;
  }
}
function menuAway(e) {
  for (const [det, away] of [...MENUS_FLOAT]) {
    if (det.isConnected === false) { MENUS_OPEN.delete(det); unfloatMenu(det); } else away(e);
  }
}
function floatMenu(det, away) {
  if (!MENUS_FLOAT.size) { window.addEventListener("scroll", menuAway, true); window.addEventListener("resize", menuAway); }
  MENUS_FLOAT.set(det, away);
}
function unfloatMenu(det) {
  if (!MENUS_FLOAT.delete(det) || MENUS_FLOAT.size) return;
  window.removeEventListener("scroll", menuAway, true); window.removeEventListener("resize", menuAway);
}

// A colleague's initials: the first letters of the first and the last word of the name, so particles (de, van, von,
// da) never count: "Anna de Vries" is AV. One word gives one letter. Letters and figures of any script count; a name
// that is not known ("a colleague", "you") gives none.
export function initials(name) {
  const n = String(name || "").trim();
  if (!n || /^(a colleague|you|maker not known)$/i.test(n)) return "";
  const words = n.split(/[\s.]+/).filter((w) => /\p{L}|\p{N}/u.test(w));
  if (!words.length) return "";
  const first = (w) => [...w.replace(/^[^\p{L}\p{N}]+/u, "")][0] || "";
  const a = first(words[0]), b = words.length > 1 ? first(words[words.length - 1]) : "";
  return (a + b).toUpperCase();
}
// A person mark: who did something, beside an item, a judgement, a log entry or a review. The person icon, then "You"
// or a colleague's initials (several people: each, "You" first), and a role when it matters (Owner, Co-owner).
// The full names and the role are its tooltip and its accessible name. note: a word after the role's dot instead of a
// role ("partly", while only part is reviewed). prefix: what they did, for the tooltip ("Reviewed by").
// Initials are enough only where the row already names the person (a person row). A mark that stands alone (a shared
// item's "by Anna", a "changed by" line, a proposal's proposer) shows the name in their place: name "short" (the
// first word: "Anna") or "full" ("Anna de Vries"); there the prefix is shown too ("By Anna", "Changed by Anna"). A
// name that is not known stays whole: "A colleague", "By a colleague".
export function personMark(people, opts = {}) {
  const list = (people || []).filter(Boolean);
  if (!list.length) return null;
  const and = (xs) => (xs.length > 1 ? `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}` : xs[0]);
  const words = `${opts.prefix ? `${opts.prefix} ` : ""}${and(list)}${opts.role ? ` (${opts.role})` : ""}`;
  const shown = opts.name
    ? (opts.prefix ? `${opts.prefix} ` : "") + and(list.map((p, i) => (p === "you" ? (i || opts.prefix ? "you" : "You")
      : !initials(p) ? "a colleague" : opts.name === "full" ? p : String(p).trim().split(/\s+/)[0])))
    : list.map((p) => (p === "you" ? "You" : initials(p))).filter(Boolean).join(" · ");   // not known: the icon only
  const after = opts.role || opts.note;
  return h("span", { class: `${UI.tag.neutral} person-mark`, title: cap(words), "aria-label": cap(words), role: "img" },
    icon(list.length > 1 ? "users" : "user", { size: 12 }), shown ? h("span", { "aria-hidden": "true" }, opts.name ? cap(shown) : shown) : null,
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
  const said = [h("span", { class: "visually-hidden" }, "Severity: "), words];   // heard as "Severity: Low"
  return level === "high" ? tag({ kind: "attention", title: "Severity: high" }, said)
    : tag({ class: `severity-${level}`, title: `Severity: ${words.toLowerCase()}` }, said);
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
// listGroup(heading, …rows), by person or by day (null: no heading); heading may be { text, action }: the group's one action at the
// head's end (What came in · Mark as seen). serif: the name is the research's own (a document, a hypothesis, a concept,
// a theme), in the serif (docs/DESIGN.md 3.2); a person's name or a sentence about what happened stays sans.
export function listRow({ person, title, href, time, sub, warn, serif, actions = [] }) {
  return h("li", { class: "list-row" }, person || null,
    h("div", { class: "list-row-main" }, href ? link({ kind: "title", serif, href }, title) : h("span", { class: serif ? "serif" : null }, title),
      sub ? (warn ? tag({ kind: "attention" }, sub) : h("span", { class: "list-row-sub" }, sub)) : null),
    time ? h("time", { class: "list-row-time" }, time) : null,
    actions.length ? h("span", { class: "list-row-actions" }, ...actions) : null);
}
// heading null: the rows alone, where the place around them already names them (a section of the drawer)
export function listGroup(heading, ...rows) {
  if (heading === null || heading === undefined) return h("div", { class: "list-group" }, h("ul", { class: "list-rows" }, ...rows));
  const hd = heading.text !== undefined ? heading : { text: heading };
  const title = h("h3", { class: "list-head" }, hd.text);
  return h("section", { class: "list-group" }, hd.action ? h("div", { class: "list-group-head" }, title, hd.action) : title,
    h("ul", { class: "list-rows" }, ...rows));
}

// A proposed change (working together), one card in a list of them (listGroup(): waiting, decided, taken back). Its
// head: what is proposed and the severity tag; under it who proposed it and when, and the proposer's reason in their
// words; detail: what else the card must say (what the change does, a notice of another proposal for the same item).
// side "owner": Accept (main) and Decline… (quiet; it asks for an optional reason). side "proposer": the state in words
// (waiting: "Waiting for Anna.", by default "Waiting for the owner"; or Declined: the reason) and Take back (quiet)
// while it waits, when onTakeBack is given (a colleague who neither decides nor proposed sees the wait only). An owner
// who still has a proposal of their own waiting (after a hand-over) keeps its Take back beside Accept and Decline…. state: "waiting" | "accepted" | "declined" |
// "taken-back". even: neither answer is the main one (a proposal two people answered both ways: both small standard
// buttons, so the look favours no answer). Other options (id, aria-label) go to the card.
export function proposalCard(opts = {}) {
  const [o, attrs] = split(opts, ["what", "person", "time", "severity", "reason", "detail", "side", "state", "declined", "waiting", "onAccept", "onDecline", "onTakeBack", "even"]);
  const side = o.side || "owner", state = o.state || "waiting";
  const words = { accepted: workState("done", "Accepted"), declined: workState("ended", o.declined ? `Declined: ${o.declined}` : "Declined"),
    "taken-back": workState("ended", "Taken back") }[state]
    || (side === "proposer" ? workState("waiting", o.waiting || "Waiting for the owner") : null);
  const takeBack = o.onTakeBack ? [button({ kind: "quiet", sm: true, onClick: o.onTakeBack }, "Take back")] : [];
  const actions = state !== "waiting" ? [] : side === "owner"
    ? [o.even ? button({ sm: true, onClick: o.onAccept }, "Accept") : button({ kind: "main", sm: true, onClick: o.onAccept }, "Accept"),
      button({ kind: o.even ? "standard" : "quiet", sm: true, onClick: o.onDecline }, "Decline…"), ...takeBack]
    : takeBack;
  return card({ ...attrs, as: "li", sm: true, class: ["proposal", attrs.class].filter(Boolean).join(" "), title: o.what, level: "h3", action: o.severity ? severityTag(o.severity) : null },
    h("p", { class: "proposal-by" }, o.person || null, o.time ? h("time", {}, o.time) : null),
    o.reason ? h("p", { class: "proposal-why" }, "“", o.reason, "”") : null,
    o.detail || null,
    words || actions.length ? h("div", { class: "btn-row proposal-foot" }, words, ...actions) : null);
}

// A decision that is not a proposal (working together: a question about the owner, a change refused in your name, a
// looser AI setting offered), in a proposal card's shape: what it is about in the head, with one tag (flag: "A
// take-over", "More AI"); who and when; their words (said); what the card must say (body); its buttons (actions: at
// most one main, the rest small); and the AI line at its foot (ai), where an answer lets an AI read more. A question
// with two answers is such a card, never a notice with two buttons (docs/DESIGN.md 5.5). Other options (id,
// aria-label) go to the card.
export function decisionCard(opts = {}) {
  const [o, attrs] = split(opts, ["what", "flag", "person", "time", "said", "body", "actions", "ai"]);
  return card({ ...attrs, as: "li", sm: true, class: ["proposal", attrs.class].filter(Boolean).join(" "), title: o.what, level: "h3",
    action: o.flag ? tag({ kind: "attention" }, o.flag) : null },
    o.person || o.time ? h("p", { class: "proposal-by" }, o.person || null, o.time ? h("time", {}, o.time) : null) : null,
    o.said ? h("p", { class: "proposal-why" }, "“", o.said, "”") : null,
    o.body || null,
    (o.actions || []).filter(Boolean).length ? h("div", { class: "btn-row proposal-foot" }, ...o.actions.filter(Boolean)) : null,
    o.ai || null);
}

// A list of problems, one notice each (the shared folder: one per colleague or per kind): items [{ kind, person, text,
// action, live }]; kind as notice()'s (attention: needs you, error: did not work, info: wait and it passes). The list
// stands in its place and is read with it, so no row is an alert unless its live says so.
export function noticeList(items) {
  return h("ul", { class: "notice-list" }, items.filter(Boolean).map((it) =>
    h("li", {}, notice({ kind: it.kind || "attention", live: it.live ?? false }, h("p", {}, it.person || null, it.person ? " " : null, it.text), it.action || null))));
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
// | "failed" | "attention" (needs you: a folder not reachable, a newer ENLENS needed) | "paused" (you paused it: grey)
// | "ended" (settled and not done: declined, taken back; grey); time: seconds for a running state.
export function workState(state, words, time) {
  const ic = { waiting: "clock", stopped: "pause", paused: "pause", done: "check", failed: "alert-circle", attention: "alert-triangle", ended: "minus" }[state];
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
export function drawer({ id, title, icon: ic, tabs: tabItems, current, onTab, control, sections = [], foot, onClose, closeLabel }) {
  const close = iconButton({ icon: "x", label: closeLabel || `Close ${title.toLowerCase()}`, onClick: () => onClose && onClose() });
  const body = h("div", { class: "drawer-body" });
  // with tabs, the body is their panel (role tabpanel, named by the chosen tab)
  const tabList = tabItems && tabItems.length > 1 ? tabs({ class: "drawer-tabs", label: title, items: tabItems, current, panel: body, onTab: (key) => onTab && onTab(key) }) : null;
  const aside = h("aside", { class: "drawer", id, "aria-label": title, hidden: true },
    h("div", { class: "drawer-head" }, tabList || [ic ? icon(ic, { size: 16 }) : null, h("h2", { class: "drawer-title" }, title)], control || null, close),
    body,
    foot ? h("div", { class: "drawer-foot" }, foot) : null);
  aside.setSections = (parts) => replace(body, ...parts.filter(Boolean).map((el) => { el.classList.add("drawer-section"); return el; }));
  aside.setSections(sections);
  aside.closeButton = close;
  aside.tabs = tabList;   // its tabs (or null): aside.tabs.choose(key) opens one from code
  return aside;
}
// The drawer's button: a small button that stays in the same spot on every page, soft teal while its drawer is open.
export function drawerButton({ id, controls, label, icon: ic, onClick, title }) {
  return h("button", { class: `${UI.button.standard} ${UI.sm} btn-opens drawer-btn`, id, type: "button", "aria-expanded": "false",
    "aria-controls": controls, title: title || null, onClick }, icon(ic, { size: 15 }), h("span", { class: "drawer-btn-text" }, label));
}
// The team line: the project switch's second row in a project that has a team. A button of the "opens beside" kind:
// it opens the drawer at its Team tab and is soft teal while that tab shows. Its end says the team's state in fixed
// words. set({ kind, words, count }): kind "ok" | "running" | "attention"; count: what is new, in words ("3 new").
export function teamLine({ id, controls, onClick }) {
  const name = h("span", { class: "team-line-name" }, "Team");
  const state = h("span", { class: "team-line-state" });
  const el = h("button", { class: "btn-opens team-line", id, type: "button", "aria-expanded": "false", "aria-controls": controls, onClick });
  el.set = ({ kind = "ok", words = "", count = null } = {}) => {
    el.setAttribute("data-kind", kind);
    replace(el, icon(kind === "attention" ? "alert-triangle" : "users", { size: 15 }), name, state);
    replace(state, kind === "running" ? h("span", { class: "running-dot", "aria-hidden": "true" }) : null,
      count ? tag({ kind: "count", class: "tab-count" }, count) : words);
    const said = `Team${count || words ? `: ${count || words}` : ""}. Opens the Team tab beside the page`;
    el.setAttribute("title", said);
    el.setAttribute("aria-label", said);
  };
  el.set();
  return el;
}
export function setDrawerOpen(open, btn) {
  if (open) document.body.dataset.drawer = "open"; else delete document.body.dataset.drawer;
  if (btn) btn.setAttribute("aria-expanded", open ? "true" : "false");
}

// The one AI mark (docs/DESIGN.md 4.4): the chip icon says whether something uses the AI, everywhere in the same words (the
// sidebar's groups, a page's top line, beside an action). The cloud icon is kept for where text goes (which AI reads
// it): the AI line at the foot of the sidebar and "Claude, on your plan, reads…" beside a check.
const AI_TEXT = {
  none: ["No AI", "Never uses the AI: it runs on this computer."],
  optional: ["AI on request", "Works without the AI; the AI adds to it only when you ask."],
  uses: ["Uses the AI", "The AI does this work: it reads the passages it needs."],
};

export function aiTag(ai) {
  const [text, plain] = AI_TEXT[ai] || AI_TEXT.none;
  return h("span", { class: `ai-tag ai-${ai}`, title: plain }, icon("cpu", { size: 12 }), text);
}

// Buttons that send text to an AI, with their one AI mark (docs/DESIGN.md 4.4): the buttons and the mark after them
// are one wrapping group (.with-ai), so a row of such buttons has one mark. Put the result in the row: h("div", { class:
// "btn-row" }, withAI(check, look)).
export function withAI(...buttons) {
  const all = buttons.flat().filter(Boolean);
  if (!all.length) return null;
  // one wrapping group: on a narrow screen the buttons stay in one row and the mark goes under them, never beside
  // the last button only
  return [h("span", { class: "with-ai" }, ...all, aiTag("uses"))];
}

// Where text goes, and which AI reads it (the AI line): the cloud (Claude), the house (this computer) or the folder (a
// folder shared with colleagues) and one sentence. One per card that holds such actions, under them; never in the
// row of a button. "attention": no AI can run yet.
export function aiWhere(text, where = "cloud", attrs = {}) {
  const ic = { local: "house", attention: "alert-triangle", folder: "folder" }[where] || "cloud";
  return h("p", withClass(where === "attention" ? "ai-where ai-where-attention" : "ai-where", attrs), icon(ic, { size: 13 }), h("span", {}, text));
}

// The AI line of the AI chosen in Settings: who reads `what`, and where the text goes. opts.model: the model that reads
// when it is not the main one (a second local model); opts.class: the page's own class for placement.
export function readsLine(what = "the excerpts it needs", opts = {}) {
  const p = App.privacy(), s = App.settings();
  const attrs = opts.class ? { class: opts.class } : {};
  if (s.backend === "claude_code") return aiWhere(`${p.label}, reads ${what}.`, "cloud", attrs);   // "Claude, on your plan, reads…"
  if (p.where === "cloud") return aiWhere(`Claude, through the Claude API${s.anthropic_model ? ` (${s.anthropic_model})` : ""}, reads ${what}: the text is sent to Anthropic.`, "cloud", attrs);
  if (p.where === "local") return aiWhere(`The AI on this computer (${opts.model || p.detail}) reads ${what}: your documents never leave it.`, "local", attrs);
  return aiWhere("Demo mode: no AI reads the excerpts. A simple word-overlap stand-in answers, so the answers are not findings.", "attention", attrs);
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
  // disabled: a setting you cannot change here; its help says why ("On because of Ben: …")
  const input = h("input", { type: "checkbox", role: "switch", class: "switch-input", checked: !!checked, disabled: !!opts.disabled, "aria-checked": checked ? "true" : "false" });
  input.addEventListener("change", () => input.setAttribute("aria-checked", input.checked ? "true" : "false"));
  const id = "sw" + Math.random().toString(36).slice(2, 8);
  input.id = id;
  if (opts.help) input.setAttribute("aria-describedby", id + "-help");
  const wrap = h("div", { class: "switch-field" },
    h("label", { class: "switch", for: id }, input, h("span", { class: "switch-track", "aria-hidden": "true" }), h("span", { class: "switch-label" }, label)),
    opts.help ? h("div", { class: "field-help", id: id + "-help" }, opts.help) : null);
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

// The judgement's own icon (the circle family, docs/DESIGN.md 3.3): an answer (STATUS_ICON, icons.js) or the grade of an
// excerpt. Only a judgement carries one: a badge, or a grade said in a dense place (a table of excerpts).
const GRADE_ICON = { supports: "circle-check", partially_supports: "circle-half", refutes: "circle-x", none: "circle-dashed" };
export function judgementIcon(key, size = 12) {
  return icon(GRADE_ICON[key || "none"] || STATUS_ICON[key] || GRADE_ICON.none, { size });
}

export function gradeBadge(verdict, weak) {
  const v = verdict || "none";
  return h("span", { class: `badge grade-${v} ${weak ? "badge-weak" : ""}`, title: weak ? "Not counted: the AI was less sure than your strictness setting asks for" : null },
    judgementIcon(v, 14), h("span", {}, verdict ? GRADE_TEXT[verdict] || verdict : "Not about this hypothesis"));
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

// 0.18.2: a heat grid in its frame (components.css, 4.25 The heat grid). Both of its axes are data, so a grid wider
// than the page still scrolls sideways, but never silently: while columns are out of sight, a bar above it says which
// show ("Documents 1–6 of 23"), with arrows that move it a frame at a time, and Full screen, which lays the grid over
// the whole window. There it scrolls every way, like a spreadsheet, with its header row and first column held in place.
// The grid itself moves into the full-screen layer and back (never a copy), so rows drawn in steps and the cells'
// buttons keep working; following a link from there (a cell, a title) closes the layer, as the page changes under it.
// `label` names the grid (its region, the layer's title); `unit` is what its columns are, in the plural.
export function heatGrid(table, { label, unit = "columns" } = {}) {
  const wrap = h("div", { class: "map-wrap", role: "region", "aria-label": label }, table);
  const frame = h("div", { class: "heat-frame" }, wrap);
  const where = h("span", { class: "heat-where" });
  // the part of the frame the columns scroll through: right of the first column (it stays), up to the frame's edge
  const view = () => {
    const row = table.tHead && table.tHead.rows[0];
    const w = wrap.getBoundingClientRect();
    return { row, heads: row ? [...row.cells].slice(1) : [], left: w.left + (row ? row.cells[0].offsetWidth : 0), right: w.left + wrap.clientWidth };
  };
  // a step on: the first column not wholly in sight comes to the left; a step back: the last one hidden on the left
  // comes to the right edge. So no column is ever stepped over.
  const step = (dir) => {
    const { heads, left, right } = view();
    let by = dir * Math.max(80, (right - left) * 0.9);
    const rects = heads.map((c) => c.getBoundingClientRect());
    const next = dir > 0 ? rects.find((r) => r.right > right + 1) : rects.filter((r) => r.left < left - 1).pop();
    if (next) by = dir > 0 ? next.left - left : next.right - right;
    const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    wrap.scrollBy({ left: by, behavior: smooth ? "smooth" : "auto" });
  };
  const back = iconButton({ icon: "chevron-left", sm: true, label: `Earlier ${unit}`, onClick: () => step(-1) });
  const on = iconButton({ icon: "chevron-right", sm: true, label: `More ${unit}`, onClick: () => step(1) });
  const fullBtn = button({ sm: true, class: "heat-full-btn", onClick: () => openFull() }, icon("maximize", { size: 13 }), "Full screen");
  const box = h("div", { class: "heat-grid" }, h("div", { class: "heat-bar" }, where, h("span", { class: "heat-nav" }, back, on), fullBtn), frame);

  // which columns show: those whose head lies whole between the first column (it stays) and the frame's right edge
  const measure = () => {
    const over = wrap.scrollWidth > wrap.clientWidth + 1;
    box.toggleAttribute("data-over", over);
    if (over) wrap.setAttribute("tabindex", "0"); else wrap.removeAttribute("tabindex");
    const { heads, left, right } = view();
    if (!over || !heads.length) { delete frame.dataset.more; return; }
    let a = -1, b = -1;
    heads.forEach((c, i) => { const r = c.getBoundingClientRect(); if (r.left >= left - 2 && r.right <= right + 2) { if (a < 0) a = i; b = i; } });
    const name = unit.charAt(0).toUpperCase() + unit.slice(1);
    where.textContent = a < 0 ? `${heads.length} ${unit}` : `${name} ${a + 1}${b > a ? `–${b + 1}` : ""} of ${heads.length}`;
    back.disabled = wrap.scrollLeft <= 1;
    on.disabled = wrap.scrollLeft + wrap.clientWidth >= wrap.scrollWidth - 1;
    frame.dataset.more = on.disabled ? "" : "end";
  };
  let queued = false;
  const later = () => { if (queued) return; queued = true; requestAnimationFrame(() => { queued = false; measure(); }); };
  wrap.addEventListener("scroll", later, { passive: true });
  if ("ResizeObserver" in window) { const ro = new ResizeObserver(later); ro.observe(wrap); ro.observe(table); }
  else window.addEventListener("resize", later);

  let layer = null, stand = null;
  // a frame taken out of the page and put back forgets how far it was scrolled: it is carried over by hand
  const move = (fn) => { const x = wrap.scrollLeft, y = wrap.scrollTop; fn(); wrap.scrollLeft = x; wrap.scrollTop = y; };
  const closeFull = () => {
    if (!layer) return;
    const dlg = layer;
    layer = null;
    window.removeEventListener("hashchange", closeFull);
    move(() => { if (stand && stand.isConnected) stand.replaceWith(box); });
    stand = null;
    dlg.close();
    dlg.remove();
    if (fullBtn.isConnected) fullBtn.focus({ preventScroll: true });
    later();
  };
  function openFull() {
    if (layer) return;
    // the grid's place in the page keeps its height while it is away, so the page does not move under the layer
    stand = h("div", { class: "heat-stand", style: { height: `${box.offsetHeight}px` } });
    layer = h("dialog", { class: "grid-full", "aria-label": label },
      h("div", { class: "grid-full-head" }, h("h2", {}, label),
        button({ sm: true, onClick: closeFull }, icon("minimize", { size: 13 }), "Exit full screen")));
    layer.addEventListener("cancel", (e) => { e.preventDefault(); closeFull(); });
    // a link followed from the layer (a title) leads to another place, even to the page under it: the layer goes
    layer.addEventListener("click", (e) => { if (e.target.closest("a[href]")) setTimeout(closeFull, 0); });
    window.addEventListener("hashchange", closeFull);
    (document.getElementById("dialogs") || document.body).appendChild(layer);
    move(() => { box.replaceWith(stand); layer.appendChild(box); layer.showModal(); });
    later();
  }
  return box;
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

// 0.18.1 (H5): a long list drawn page by page, so a page of thousands of lines opens at once. Two sources:
//   lazyList({ items, render })              the whole list is here already (a result's excerpts, the answers): drawing
//                                            more is synchronous, so reveal() can draw up to a card a jump needs;
//   lazyList({ fetchPage, render, first })   the pages come from the API: fetchPage(offset, limit) answers
//                                            { items, total }. `first` is the first page, when it was fetched already
//                                            (the page needed its total for its heading): it is not asked for again.
// render(item, index) gives a Node (null leaves the item out). Options: pageSize (100), firstSize (the first page's
// size for `items`, pageSize), list (the element the items go into, e.g. a <tbody>; else a <div>), noun ("line" or
// ["line", "lines"]), empty (a Node said instead of the list when there is nothing).
// The result: el (the items' parent), footer (put it right after `el`, outside a table: "120 of 1,400 lines", a "Show
// more" button, and the sentinel the IntersectionObserver watches), more(), reveal(i or test) and revealAll() (`items`
// only; reveal answers false when nothing matches), shown(), total(), reset(items | first), ready (the first page).
// The next page is asked for when the footer comes within about a screen of the window, or when "Show more" is used
// (from the keyboard or where IntersectionObserver is missing). A page is never asked for twice; a failure says so
// (showError), stops the automatic loading and turns the button into "Try again". An answer that arrives after reset()
// is dropped. For print, an `items` list draws everything first.
export function lazyList({ items = null, fetchPage = null, first = null, render, pageSize = 100, firstSize = 0, list = null, noun = "item", empty = null } = {}) {
  let local = Array.isArray(items);
  const [one, many] = Array.isArray(noun) ? noun : [noun, noun + "s"];
  const el = list || h("div", { class: "lazy-list" });
  const status = h("span", { class: "muted small lazy-status", "aria-live": "polite" });
  const moreLabel = h("span", {}, "Show more");
  const moreBtn = button({ kind: "quiet", sm: true, class: "lazy-more", onClick: () => { more(true); } }, icon("chevron-down", { size: 13 }), moreLabel);
  const footer = h("div", { class: "draw-more lazy-foot", hidden: true }, status, " ", moreBtn);
  let shown = 0, total = null, gen = 0, busy = null, failed = false, firstN = 0, observer = null;
  const requested = new Set();   // offsets asked for: a page is never asked for twice
  let ready = Promise.resolve();

  const put = (batch, byHand) => {
    const nodes = batch.map((it, i) => render(it, shown + i)).filter((x) => x != null);
    shown += batch.length;
    el.append(...nodes);
    // "Show more" from the keyboard: the focus goes on to the first new item, not back to the top of the page
    if (byHand && nodes.length) {
      const f = nodes[0].querySelector("a[href], button, input, select, [tabindex]") || nodes[0];
      if (f === nodes[0] && !f.hasAttribute("tabindex")) f.setAttribute("tabindex", "-1");
      f.focus();
    }
  };
  function paint() {
    const all = total !== null && shown >= total;
    footer.classList.toggle("lazy-failed", failed);
    if (total === 0 && empty) { clear(footer); footer.append(empty); footer.hidden = false; return; }
    if (!failed && (total === null ? !busy : all && total <= firstN)) { footer.hidden = true; return; }   // all on the first page: nothing to say
    footer.hidden = false;
    status.textContent = failed ? `Could not load more ${many}.` : total === null && !shown ? "Loading…" : all ? `All ${fmt.plural(total, one, many)} shown` : total === null ? `${fmt.num(shown)} ${many} shown` : `${fmt.num(shown)} of ${fmt.plural(total, one, many)}`;
    moreBtn.hidden = all && !failed;
    moreBtn.disabled = !!busy;
    moreLabel.textContent = failed ? "Try again" : "Show more";
    if (busy) footer.setAttribute("aria-busy", "true"); else footer.removeAttribute("aria-busy");
    if (observer) { observer.unobserve(footer); if (!all && !failed && !busy) observer.observe(footer); }   // observe() again asks at once: a short page may leave the end in view
  }
  function more(byHand = false) {
    if (local) {
      if (shown >= items.length) return Promise.resolve();
      put(items.slice(shown, shown + pageSize), byHand);
      paint();
      return Promise.resolve();
    }
    if (busy) return busy;
    if ((total !== null && shown >= total) || requested.has(shown)) return Promise.resolve();
    const mine = gen, offset = shown;
    requested.add(offset);
    failed = false;
    busy = Promise.resolve().then(() => fetchPage(offset, pageSize)).then((r) => {
      if (mine !== gen) return;
      const got = (r && r.items) || [];
      if (r && r.total !== undefined && r.total !== null) total = r.total;
      put(got, byHand);
      if (!got.length) total = shown;   // an empty page ends the list, whatever the total said
    }).catch((e) => {
      if (mine !== gen) return;
      failed = true;
      requested.delete(offset);
      try { showError(e); } catch (_) { /* the footer says it too */ }
    }).finally(() => { if (mine === gen) { busy = null; paint(); } });
    paint();
    return busy;
  }
  function seed(src) {
    clear(el);
    shown = 0; gen++; busy = null; failed = false; requested.clear();
    if (Array.isArray(src)) { local = true; items = src; total = src.length; firstN = firstSize || pageSize; put(src.slice(0, firstN)); ready = Promise.resolve(); }
    else if (src) { local = false; total = src.total ?? null; firstN = src.items.length; requested.add(0); put(src.items); ready = Promise.resolve(); }
    else { local = false; total = null; firstN = pageSize; ready = more(); }
    paint();
  }
  if ("IntersectionObserver" in window) {
    observer = new IntersectionObserver((entries) => {
      if (!footer.isConnected) { observer.disconnect(); observer = null; return; }   // the list was drawn again
      if (entries.some((e) => e.isIntersecting) && !failed) more();
    }, { rootMargin: "900px 0px" });
  }
  const api_ = {
    el, footer, more, ready: null,
    shown: () => shown, total: () => total,
    reset: (src) => seed(src),
    // draws up to the item `which` (an index, or a test on the item): a jump to a card that is not drawn yet
    reveal(which) {
      if (!local) return false;
      const i = typeof which === "number" ? which : items.findIndex(which);
      if (i < 0 || i >= items.length) return false;
      while (shown <= i) more();
      return true;
    },
    revealAll() { if (local && shown < items.length) { put(items.slice(shown)); paint(); } },
  };
  if (local) {
    const onPrint = () => { if (!el.isConnected) window.removeEventListener("beforeprint", onPrint); else api_.revealAll(); };
    window.addEventListener("beforeprint", onPrint);
  }
  seed(local ? items : first || null);
  api_.ready = ready;
  return api_;
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
    const b = downloadButton({ title: it.title || null, onClick: it.onClick }, it.text);
    // a note stays with its button when the line wraps: "CSV (for programmers)" never leaves the note alone
    parts.push(it.note ? h("span", { class: "dl-pair" }, b, h("span", { class: "muted small" }, it.note)) : b);
  });
  // the files are one group: when the line is too narrow, they go under the word together, never one by one
  return h("span", { class: "dl-links" }, h("span", { class: "dl-label" }, opts.label || "Download"), h("span", { class: "dl-files" }, parts));
}

// A page head (docs/DESIGN.md 4.14): where you are and what the page is for.
//   eyebrow: the section and the AI mark (featureEyebrow(key));
//   back: { href, text } (or a list of them): a back link in the eyebrow's place, on a page that is one item;
//   display: the title in the Display serif (the research's own words: a hypothesis, a document, a concept, a theme);
//   facts: short facts about the item, in a line under the title, "·" between them;
//   sub: the one line under the title (and its facts): what the page is for, a code, its ways to other pages as links;
//   meta: further lines (a bibliography line, a row of links), as given;
//   actions: the page's actions at the right, never a link;
//   class, titleClass: the page's own classes, for placement.
// 0.18.1 (roadmap J4.2): on a result's own page, which earlier ENLENS made it, as one of the head's facts; nothing when
// this version made it. `m` is one result's {app_version, label, version, older} (runs.made_with_one), or a list of
// them with their counts `n` (a codebook's labels, runs.labels_made_with).
export function madeWithFact(m) {
  const older = [m || []].flat().filter((x) => x && x.older);
  if (!older.length) return null;
  const by = (x) => (x.app_version ? `ENLENS ${x.label}` : `an ENLENS ${x.label}`);
  const text = Array.isArray(m)
    ? `${older.map((x) => `${plural(x.n, "label")} made with ${by(x)}`).join(", ")}`
    : `Made with ${by(older[0])}`;
  return h("span", { class: "made-with", title: `You have ENLENS ${older[0].version}. A result stays as it was made; each Excel download names the version behind every answer.` },
    icon("history", { size: 12 }), h("span", {}, text));
}

export function pageHead(title, opts = {}) {
  const backs = [opts.back || []].flat().filter(Boolean);
  const top = backs.length ? backs.map((b, i) => [i ? " " : null, link({ kind: "back", href: b.href }, b.text)]) : opts.eyebrow;
  const facts = (opts.facts || []).filter(Boolean);
  return h("header", withClass(UI.pageHead, opts.class ? { class: opts.class } : {}),
    h("div", { class: "page-head-main" },
      top ? h("p", { class: "eyebrow" }, top) : null,
      h("h1", { id: "page-title", tabindex: "-1", class: [opts.display ? "title-display" : "", opts.titleClass || ""].filter(Boolean).join(" ") || null }, title),
      facts.length ? h("p", { class: "page-facts" }, facts.map((f, i) => [i ? h("span", { class: "sep", "aria-hidden": "true" }, "·") : null, f instanceof Node ? f : h("span", {}, f)])) : null,
      opts.sub ? h("p", { class: "page-sub" }, opts.sub) : null,
      opts.meta || null),
    opts.actions ? h("div", { class: "page-head-actions" }, opts.actions) : null,
    // the AI line of the head's AI action (docs/DESIGN.md 4.4): the head's last line, under its actions
    opts.ai || null);
}

// View tabs (docs/DESIGN.md 4.5): other views of one place, on a rule; the current one has the accent line. items:
// [{ key, label, href, icon, count }] (or [key, label, href, icon]); count: what is new behind it, in words ("3 new"). With href, each tab is a link (aria-current="page");
// without (a drawer's tabs, which have no address), onTab(key) is called and the tabs are buttons with the same look,
// with the whole tab pattern: role tablist/tab, aria-selected, only the chosen tab in the Tab order, Left and Right
// move to the previous and next tab (and choose it), Home and End to the first and last. panel: the element the tabs
// show (role tabpanel, labelled by the chosen tab; each tab's aria-controls). row.choose(key) chooses a tab from code,
// as pressing it does; row.setCount(key, words) changes what is new behind a tab ("3 new"; none hides it).
let TABS_SEQ = 0;  // each row of tabs' own ids
export function tabs(opts = {}) {
  const [o, attrs] = split(opts, ["label", "items", "current", "onTab", "panel"]);
  const items = (o.items || []).map((t) => (Array.isArray(t) ? { key: t[0], label: t[1], href: t[2], icon: t[3] } : t));
  const asButtons = !!o.onTab;
  const row = h(asButtons ? "div" : "nav", withClass(UI.tabs, { role: asButtons ? "tablist" : null, "aria-label": o.label, ...attrs }));
  // count: what is new behind the tab, in words ("3 new"): a count tag after its label (row.setCount changes it)
  const countTag = (t) => tag({ kind: "count", class: "tab-count", hidden: !t.count }, t.count || "");
  const inner = (t) => [t.icon ? icon(t.icon, { size: 14 }) : null, t.label, asButtons || t.count ? countTag(t) : null];
  if (!asButtons) {
    append(row, items.map((t) => h("a", { href: t.href, "aria-current": t.key === o.current ? "page" : null, "data-key": t.key }, inner(t))));
    return row;
  }
  const seq = ++TABS_SEQ;
  const panel = o.panel || null;
  if (panel) { panel.id = panel.id || `tabpanel-${seq}`; panel.setAttribute("role", "tabpanel"); }
  const idOf = (key) => `tab-${seq}-${String(key).replace(/[^\w-]/g, "_")}`;
  const buttons = items.map((t) => h("button", { type: "button", role: "tab", id: idOf(t.key), "data-key": t.key,
    "aria-controls": panel ? panel.id : null, onClick: () => row.choose(t.key) }, inner(t)));
  // the chosen tab shows itself current and is the one in the Tab order; the panel is named by it
  const mark = (key) => {
    for (const b of buttons) {
      const on = b.dataset.key === key;
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
    }
    if (panel) panel.setAttribute("aria-labelledby", idOf(key));
  };
  // a tab without an address shows itself current when it is chosen, then onTab draws what it holds
  row.choose = (key) => { mark(key); o.onTab(key); };
  // what is new behind a tab changed (words, "3 new"; none hides the count)
  row.setCount = (key, words) => {
    const c = buttons.find((b) => b.dataset.key === key)?.querySelector(".tab-count");
    if (c) { c.textContent = words || ""; c.hidden = !words; }
  };
  row.addEventListener("keydown", (e) => {
    const at = buttons.indexOf(e.target);
    if (at < 0 || e.altKey || e.ctrlKey || e.metaKey) return;
    const to = { ArrowLeft: at - 1, ArrowRight: at + 1, Home: 0, End: buttons.length - 1 }[e.key];
    if (to === undefined) return;
    e.preventDefault();
    const b = buttons[(to + buttons.length) % buttons.length];
    b.focus();
    if (b.getAttribute("aria-selected") !== "true") row.choose(b.dataset.key);
  });
  append(row, buttons);
  mark(items.some((t) => t.key === o.current) ? o.current : (items[0] || {}).key);
  return row;
}

// ---------------------------------------------------------------------------------------------
// 0.8: the task queue (Claude Code)
// ---------------------------------------------------------------------------------------------
// A command to type, with a button that copies it.
// `where`: where it is pasted, for the confirmation ("Claude Code", or "a terminal" for a command line).
// `lead`: the icon before it ("link" for a web address to type in a browser).
export function copyLine(text, label = "Copy", where = "Claude Code", lead = "terminal") {
  const btn = button({ kind: "quiet", sm: true, class: "copy-btn", "aria-label": `${label}: ${text}` }, icon("copy", { size: 13 }), label);
  btn.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(text); toast(`Copied. Paste it in ${where}.`, "ok", { ttl: 2000 }); }
    catch (_) { const r = document.createRange(); r.selectNodeContents(code); const s = getSelection(); s.removeAllRanges(); s.addRange(r); toast("Selected: copy it with Ctrl+C (or Cmd+C).", "info"); }
  });
  const code = h("code", { class: "copy-code" }, text);
  return h("div", { class: "copy-line" }, icon(lead, { size: 13 }), code, btn);
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
      aiWhere(q.privacy || "Claude Code sends the passages inside the tasks it takes to Anthropic.")) : typeIt;
    const r = q.runner || {};
    const parts = [];
    const idle = idleQueue(q);
    if (!idle) WAIT_SINCE.delete(project);
    if (q.route !== "claude_code") { replace(box, typeIt); return; }
    if (r.running) {
      parts.push(h("div", { class: "sc-running" }, h("span", { class: "running-dot", "aria-hidden": "true" }),
        h("span", {}, h("strong", {}, "Claude Code is working on it"), h("span", { class: "muted small" }, ` · started ${ago(r.seconds || 0)} from ${appName()}${planText(r) ? ` · ${planText(r)}` : ""}`)),
        stopButton({ text: "Stop Claude Code", onClick: async () => {
          try { await api("POST", `/api/projects/${P(project)}/queue/claude-code/stop`, {}); toast("Claude Code stopped. What it had not answered waits again.", "ok"); QUEUE_CACHE.delete(project); draw(false); } catch (e) { showError(e); }
        } })));  // 0.11.3: not just "Stop": the job beside it has its own
    } else if (q.can_start && (q.waiting || q.being_answered || opts.always)) {
      const b = button({ kind: "main", sm: true, onClick: async () => {
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
      parts.push(h("div", { class: "sc-start" }, withAI(b), hint));
      if (idle) watchIdle(b, hint);
      // 0.18.1 (N2): how much thought Claude gives the tasks, chosen here and kept (Settings' claude_thought); how many
      // helpers run at once is said, and chosen under Settings › AI only. The helpers for this run stay folded away.
      if (q.thought) parts.push(thoughtPicker(q.thought.chosen, saveThought, { onSaved: () => { QUEUE_CACHE.delete(project); choiceChanged(project, box); } }));
      if (q.speed) {
        const custom = customRun(RUN_CHOICE.get(project));
        const chosen = q.speed.chosen || "normal";
        const speed = h("p", { class: "sc-speed small" }, h("span", { class: "sc-speed-line muted" },
          `${helpersText((q.speed.options || {})[chosen] || 2)} at a time. `),
          link({ href: "#/settings/speed" }, "Change in Settings"));
        if (custom) speed.classList.add("sc-speed-off");
        parts.push(speed, helpersFold(project, q, () => {
          speed.classList.toggle("sc-speed-off", customRun(RUN_CHOICE.get(project)));
          choiceChanged(project, box);
        }));
      }
      if (r.exit_code !== undefined && r.exit_code !== null && r.exit_code !== 0 && !r.stopped) {
        parts.push(fold({ sm: true }, workState("failed", "The last run stopped with a problem"), inset({ as: "pre", class: "mono small sc-report" }, r.report || "(no report)")));
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
  const show = (v) => { line.textContent = `${helpersText(options[v] || 2)} at a time${SPEED_NOTE[v] || ""}.`; };
  // a choice (radio form): one Tab stop, the arrows move and pick, each pick saved at once
  const group = choice({ sm: true, label: "Speed of Claude Code", class: "sc-speed-btns", value: current, options: SPEED_CHOICES,
    onPick: async (v) => {
      if (v === current && !(opts.custom && opts.custom())) return;  // the speed shown, picked again, undoes a choice of helpers
      const before = current;
      current = v; show(v);
      try { await onPick(v); } catch (e) { current = before; group.set(before); show(before); showError(e); }
    } });
  show(current);
  const label = opts.label === undefined ? "Speed" : opts.label;
  return h("div", { class: "sc-speed" }, label ? h("span", { class: "sc-speed-label small" }, label) : null, group, line);
}

// 0.18.1 (N2): how much thought Claude gives each kind of task: which models (and, where a helper takes one, how much
// effort) answer it. Balanced is the recommended table; Energy efficient a lighter model per kind, Intelligence a
// stronger one. Kept (Settings' claude_thought); for Claude only (a local model keeps its own choice). Fable for the
// auditor stays its own switch in Settings.
export const THOUGHT_CHOICES = [["efficient", "Energy efficient"], ["balanced", "Balanced"], ["intelligence", "Intelligence"]];
const THOUGHT_NOTE = { efficient: "A lighter model for each kind of task: easiest on your plan's limits and on energy. Unsure answers still go to a stronger model.",
  balanced: "The recommended model for each kind of task.",
  intelligence: "A stronger model for each kind of task, thinking harder: uses your plan's limits sooner." };

export async function saveThought(thought) {
  const r = await api("PUT", "/api/settings", { claude_thought: thought });
  App.state.settings = r.settings;
  QUEUE_CACHE.clear();  // the models and estimates follow it
  return r;
}

// The three choices as one row of buttons with a line saying what the chosen one does; `onPick(v)` saves it (a failure
// puts the choice back); `opts.onSaved()` after a save; `opts.label`: null for none.
export function thoughtPicker(chosen, onPick = saveThought, opts = {}) {
  let current = chosen || "balanced";
  const line = h("span", { class: "muted small sc-speed-line" });
  const show = (v) => { line.textContent = THOUGHT_NOTE[v] || ""; };
  const group = choice({ sm: true, label: "How much thought Claude gives the tasks", class: "sc-speed-btns", value: current, options: THOUGHT_CHOICES,
    onPick: async (v) => {
      if (v === current) return;
      const before = current;
      current = v; show(v);
      try { await onPick(v); if (opts.onSaved) opts.onSaved(v); } catch (e) { current = before; group.set(before); show(before); showError(e); }
    } });
  show(current);
  const label = opts.label === undefined ? "Thought" : opts.label;
  return h("div", { class: "sc-speed sc-thought" }, label ? h("span", { class: "sc-speed-label small" }, label) : null, group, line);
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
    const back = customRun(C()) ? button({ kind: "quiet", sm: true, onClick: () => { const c = C(); c.total = null; c.counts = {}; draw(); onChange(); } },
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
