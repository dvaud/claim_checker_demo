// The result of one hypothesis, told as one consistent story from one fresh copy of the data: the answer, who says
// what (documents, from `balance`), then the evidence as verified quotes. Every count on the page is computed from
// the same `passages` the cards are drawn from, so sections and numbers always agree. A person's judgement
// replaces the AI's; it is protected (no silent overwrite) and every save can be undone.
import { App, api, h, icon, replace, clear, append, toast, showError, fmt, statusBadge, gradeBadge, codeChip, passageNode, popNote, gradeWords, navigate, watchJob, P, TOKEN, TERMINAL, confirmDialog, dialog, download, debounce, store, GRADE_TEXT, STATUS_SHORT, strictness, docsCountSentence, queueNotice, auditorName, strongerMark } from "../lib.js";
import { ProgressPanel, MiniJob } from "./progress.js";

const USER_VERDICTS = [["supports", "Supports"], ["partially_supports", "Partly supports"], ["refutes", "Contradicts"], ["not_relevant", "Not about this"]];
const about = (p) => p.verdict !== null && p.verdict !== undefined;   // the judgement that counts says it is about the hypothesis
// 0.11: who read an excerpt (its document's AI setting decides)
const READ_BY = { claude: ["cloud", "Read by Claude", "read-claude"], local: ["house", "Read by the local model", "read-local"], ai: ["cpu", "Read by the AI", "read-ai"],
  you: ["shield", "No AI read it", "read-you"], waiting: ["inbox", "Not read yet", "read-waiting"] };
const READ_BY_ROUND = { claude: (n) => `Claude read ${n}`, local: (n) => `the local model read ${n}`, ai: (n) => `the AI read ${n}`, you: (n) => `${n} for your judgement`, waiting: (n) => `${n} not read yet` };
function readByChip(p) {
  const [ic, text, cls] = READ_BY[p.read_by] || READ_BY.ai;
  const why = p.access === "none" ? "Its document is marked No AI." : p.access === "local" ? "Its document is marked Only a local AI." : "";
  return h("span", { class: `read-by ${cls}`, title: why || text }, icon(ic, { size: 12 }), text);
}
const SCOPE_HELP = "The AI thinks this excerpt is about another group, place, setting or period than your hypothesis names, so it counts it as partly supporting at most. Read the excerpt and judge for yourself whether it applies.";
const ONE_MODEL_NOTE = "Only one AI model is kept in memory at a time, so this takes a while: the main model is unloaded first, and the second one when it is done.";

// Whether a document's original file can still be opened (GET …/file?check=1), asked once per document per page.
const originalsCache = new Map();   // key -> promise of the answer
const originalsKnown = new Map();   // key -> the answer, once it arrived (so a re-draw fills the link at once, without a layout shift)
export function originalInfo(project, docId) {
  const key = `${project}/${docId}`;
  if (!originalsCache.has(key)) originalsCache.set(key, api("GET", `/api/projects/${P(project)}/documents/${P(docId)}/file?check=1`).then((r) => { originalsKnown.set(key, r); return r; }).catch(() => null));
  return originalsCache.get(key);
}
export function forgetOriginals() { originalsCache.clear(); originalsKnown.clear(); }
// The link to the original file, as a plain link the browser opens in a new tab, at the place of the quote when it
// can: a PDF at its page (#page=N), a text file as a page with the quote highlighted (?quote=…#quote), a web page
// with a text fragment (#:~:text=first words,last words) that browsers scroll to and highlight.
export function originalHref(project, docId, { kind, page, quote } = {}) {
  const base = `/api/projects/${P(project)}/documents/${P(docId)}/file?token=${encodeURIComponent(TOKEN)}`;
  const q = (quote || "").replace(/\s+/g, " ").trim();
  if (kind === "pdf") return base + (page ? `#page=${page}` : "");
  if (kind === "html" || kind === "htm") return base + (q ? `#:~:text=${textFragment(q)}` : "");
  if (q) return `${base}&quote=${encodeURIComponent(q)}#quote`;
  return base;
}
// The text-fragment form of a quote: the first and last few words, percent-encoded (also -, , and &).
export function textFragment(q) {
  const enc = (t) => encodeURIComponent(t).replace(/-/g, "%2D");
  const words = q.split(" ");
  if (words.length <= 10) return enc(q);
  return `${enc(words.slice(0, 5).join(" "))},${enc(words.slice(-5).join(" "))}`;
}
// "Open the original" (a new tab) when the file is still there, otherwise the plain reason. Filled in when known.
// opts: button, text, info (the ?check=1 answer when already known), reason (false: say nothing when missing),
// quote (opens at it), pdfHint (the title says where the quote is highlighted in the app).
export function originalLink(project, docId, page, kind, opts = {}) {
  const holder = h("span", { class: "orig-link" + (opts.class ? " " + opts.class : "") });
  const fill = (info) => {
    if (!info) return;
    const k = info.kind || kind;
    if (info.available) {
      const isPdf = k === "pdf";
      const where = isPdf ? (page ? `, at page ${page}` : "") : opts.quote ? ", at the quote" : "";
      const link = h("a", { class: opts.button ? "btn btn-sm btn-ghost" : "it", href: originalHref(project, docId, { kind: k, page, quote: opts.quote }), target: "_blank", rel: "noopener",
        title: `Opens ${info.name || "the original file"} in a new tab${where}${isPdf && opts.quote && opts.pdfHint ? ". The quote itself is highlighted here in the app, under “In context”." : ""}` },
        opts.noIcon ? null : icon("external-link", { size: 13 }), opts.text || (isPdf && page && !opts.pdfHint ? `Open the original (page ${page})` : "Open the original"));
      replace(holder, link);   // 0.12: where it opens is in its title, not in a line beside it
    } else if (opts.reason !== false) {
      replace(holder, h("span", { class: "muted small orig-missing" }, icon("alert-triangle", { size: 12 }), " ", info.reason || "The original file is no longer available; the text the app read is shown."));
    }
  };
  const known = originalsKnown.get(`${project}/${docId}`);
  if (opts.info) fill(opts.info); else if (known) fill(known); else originalInfo(project, docId).then(fill);
  return holder;
}

// Sentences of an excerpt, for "mark the sentence you mean": split after . ! ? but not after an initial ("M."),
// a number ("2.") or a common abbreviation (e.g., et al., Dr., p., Fig. …). Frontend only; the app's own splitter
// is not touched.
const ABBREVIATION = /(?:^|[\s(])(?:e\.g|i\.e|et al|etc|cf|vs|viz|ca|approx|resp|Dr|Prof|Mr|Mrs|Ms|Sr|Jr|St|Mt|No|no|Nr|nr|p|pp|Fig|fig|Figs|Eq|eq|Vol|vol|Ch|ch|chap|ed|eds|Ed|Eds|Univ|Dept|Inc|Ltd|Co|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|[A-Z])\.$/;
export function splitSentences(text) {
  const bits = String(text || "").split(/(?<=[.!?])\s+/);
  const out = [];
  for (const bit of bits) {
    const prev = out[out.length - 1];
    if (prev !== undefined && (ABBREVIATION.test(prev) || /^\d+\.$/.test(prev) || /^[a-z]/.test(bit))) out[out.length - 1] = `${prev} ${bit}`;
    else out.push(bit);
  }
  return out.map((x) => x.trim()).filter(Boolean);
}

// 0.12: the part of an excerpt a card shows at first: the sentences of the highlight with one sentence before and one
// after (no highlight: the first two sentences), as [start, end]; null when that would hide little (then the whole
// excerpt is shown). A sentence ends at . ! ? before a space, and at the excerpt's own paragraph breaks. opts.after: 0
// leaves out the sentence after the highlight (on a phone).
export function excerptWindow(text, start, end, breaks, opts = {}) {
  text = String(text || "");
  const cuts = new Set([0, text.length]);
  const re = /[.!?]["”’)\]]?\s+/g;
  let m;
  while ((m = re.exec(text))) cuts.add(m.index + m[0].length);
  for (const b of breaks || []) {
    if (b && Number.isInteger(b.at)) cuts.add(b.at);
    if (b && b.kind === "heading" && Number.isInteger(b.end)) cuts.add(b.end);
  }
  const pts = [...cuts].filter((x) => x >= 0 && x <= text.length).sort((x, y) => x - y);
  // a short last line after the highlight is the next section's heading ("4. Heterogeneity."): left out, even of a
  // short excerpt (the whole excerpt is one click away)
  let tail = null;
  if (Number.isInteger(end) && end > 0) {
    for (let k = pts.length - 2; k > 0 && pts[k] >= end && text.slice(pts[k]).trim().length < 30; k--) tail = pts[k];
  }
  if (text.length < 420) return tail ? [0, tail] : null;
  let a = 0, b;
  if (Number.isInteger(start) && Number.isInteger(end) && end > start) {
    let i = pts.findIndex((x, k) => k < pts.length - 1 && start >= x && start < pts[k + 1]);
    let j = pts.findIndex((x) => x >= end);
    if (i < 0) i = 0;
    if (j < 0) j = pts.length - 1;
    a = pts[Math.max(0, i - 1)];
    // a short line before the quote is a heading ("Recommendations."): one more sentence, for real context
    if (i - 1 > 0 && text.slice(a, pts[i]).trim().length < 30) a = pts[i - 2];
    b = opts.after === 0 ? pts[j] : pts[Math.min(pts.length - 1, j + 1)];
    // a short line after the quote is the next section's heading ("Method."): left out
    if (b > pts[j] && text.slice(pts[j], b).trim().length < 25) b = pts[j];
    if (tail !== null && b > tail) b = Math.max(tail, pts[j]);
  } else b = pts[Math.min(pts.length - 1, 2)];
  return text.length - (b - a) < 200 ? null : [a, b];
}

// The window of an excerpt as a passage, its highlight and breaks moved with it, an ellipsis where text is left out.
function windowNode(text, start, end, cls, breaks, [a, b]) {
  const t = text.slice(a, b).replace(/\s+$/, "");
  const shifted = (breaks || []).filter((x) => x && Number.isInteger(x.at) && x.at >= a && x.at < a + t.length)
    .map((x) => ({ ...x, at: x.at - a, end: Number.isInteger(x.end) ? Math.min(x.end - a, t.length) : x.end }));
  const ok = Number.isInteger(start) && Number.isInteger(end) && end > start;
  const el = passageNode(t, ok ? Math.max(0, start - a) : null, ok ? Math.min(t.length, end - a) : null, "p", `${cls} passage-window`, shifted.length ? shifted : null);
  const broken = el.classList.contains("passage-broken");
  if (broken) for (const line of [...el.children]) if (!line.textContent.trim()) line.remove();
  if (a > 0) (broken ? el.firstElementChild : el).prepend(h("span", { class: "ellip", "aria-hidden": "true" }, "…\u00a0"));
  if (a + t.length < text.length) (broken ? el.lastElementChild : el).append(h("span", { class: "ellip", "aria-hidden": "true" }, "\u00a0…"));
  return el;
}

export async function renderResult(view, [hypId], query) {
  const project = App.project;
  const setting = App.settings().threshold ?? 0.6;
  let threshold = query.threshold !== undefined ? Number(query.threshold) : setting;
  if (Number.isNaN(threshold)) threshold = setting;
  const box = h("div", { class: "result" });
  view.appendChild(box);
  const watchers = [];
  let lastRun = App.lastRun && App.lastRun.hyp_id === hypId ? App.lastRun : null;
  App.lastRun = null;
  const openFolds = new Set();     // data-fold keys of <details> that are open: kept across re-renders
  const newRound = new Map();      // claim_id -> round number whose excerpts are new since the page was opened
  let whatsNew = null;             // {n, about, claim_id, round} after "look for more" / "other words"
  const triedTerms = new Map();    // claim_id -> words searched for that found nothing new
  const termsOpen = new Set();     // claim_ids whose "search with other words" box is open (kept across re-renders)
  let focusAfter = null;           // {passage_id, top, was} to keep the person's place after a save
  let current = null;              // the result as last fetched
  let returnTo = query.card || null;   // passage to scroll to when coming back from the document view
  const termsText = new Map();     // claim_id -> words typed in "search with other words" (kept across re-draws)
  const termsResult = new Map();   // claim_id -> inline result of the last search with other words
  const running = new Map();       // job id -> {kind, mini} of a follow-up job of this result (read again, new documents, second model)
  let followNote = null;           // text shown in the follow-ups card after one of its jobs ended
  const secondShown = new Set();   // 0.11.2: "claim|passage" whose passage highlights the second opinion's quote
  const pendingQuote = new Map();  // "claim|passage" -> {text, start, end}: a sentence marked before a judgement was chosen (not saved yet)
  const visitedNext = new Set();   // cards "Next to review" went to in this session, so it moves on and wraps around
  const wholeShown = new Set();    // 0.12: "claim|passage" whose whole excerpt is shown (otherwise the quote in its context)
  let oneReader = null;            // 0.12: who read every excerpt, when it is the same for all (said once, above the cards)
  let changingSecond = false;      // the second-model select is open to change the choice
  let evidenceView = store("evidenceView") === "table" ? "table" : "cards";   // cards or a compact table, remembered per browser
  const pendingKey = (p, part) => `${part.claim_id}|${p.passage_id}`;
  const redraw = () => draw(current);   // re-draw from the data as last fetched (for places where `current` is shadowed)
  const splitResult = () => !!(current && current.decomposed);
  const statusNow = () => current && current.status;
  let waitTimer = null;            // 0.8: a check waiting for Claude Code is looked at again every few seconds
  const draftNotes = new Map();    // 0.12: "claim|passage" -> a comment typed but not saved yet (kept across re-draws)
  let serversOnce = null;          // 0.12: the model servers, asked once per page (the picker is drawn again on every save)

  async function load() {
    let r;
    try { r = await api("GET", `/api/projects/${P(project)}/hypotheses/${P(hypId)}?threshold=${threshold}`); }
    catch (e) {
      if (e.status === 404) { replace(box, h("div", { class: "empty" }, icon("search-x", { size: 28 }), h("h3", {}, "This result no longer exists"), h("p", {}, "It was deleted, or it belongs to another project."), h("a", { class: "btn", href: "#/history" }, "Back to results"))); return; }
      throw e;
    }
    current = r;
    draw(r);
  }

  function setThreshold(t) {
    threshold = t;
    history.replaceState(null, "", `#/h/${encodeURIComponent(hypId)}${Math.abs(t - setting) > 1e-9 ? `?threshold=${t}` : ""}`);
    openFolds.add("tech");
    load().catch(showError);
  }

  // 0.12: a button in a card's action row that opens a panel under the row (the row itself never moves); its open
  // state survives a re-render, like a fold's
  function panelToggle(key, label, panel, startOpen = false, chevron = true) {
    const open = openFolds.has(key) || startOpen;
    panel.hidden = !open;
    const btn = h("button", { class: "btn btn-sm btn-ghost panel-toggle", type: "button", "aria-expanded": open ? "true" : "false", onMousedown: (e) => e.preventDefault() }, chevron ? icon("chevron-right", { size: 13 }) : null, label);
    btn.addEventListener("click", () => {
      const on = panel.hidden;
      if (on) {   // one panel open per card: the other closes
        const card = btn.closest(".judge");
        for (const other of card ? card.querySelectorAll(".panel-toggle[aria-expanded='true']") : []) if (other !== btn) other.click();
      }
      panel.hidden = !on;
      btn.setAttribute("aria-expanded", on ? "true" : "false");
      if (on) openFolds.add(key); else openFolds.delete(key);
    });
    return btn;
  }

  // <details> whose open state survives a re-render
  function fold(key, attrs, ...children) {
    const d = h("details", { ...attrs, open: openFolds.has(key) }, ...children);
    d.dataset.fold = key;
    d.addEventListener("toggle", () => { if (d.open) openFolds.add(key); else openFolds.delete(key); });
    return d;
  }

  function draw(r) {
    const y = window.scrollY;
    document.title = `${STATUS_SHORT[r.status] || r.status} · ${(r.text || "").slice(0, 60)} · ENLENS`;
    clear(box);
    const parts = r.parts || [];
    const single = parts.length === 1 && !r.decomposed;
    const allPassages = parts.flatMap((p) => p.passages || []);
    const readers = new Set(allPassages.filter((p) => p.read_by && !p.waiting_for_you).map((p) => p.read_by));
    oneReader = readers.size === 1 && !allPassages.some((p) => p.waiting_for_you) ? [...readers][0] : null;

    // 0.12: one quiet line under the hypothesis: when it was checked and what was read
    box.appendChild(h("header", { class: "page-head result-head" },
      h("div", { class: "page-head-main" },
        h("p", { class: "eyebrow" }, h("a", { href: "#/history", class: "it" }, icon("arrow-left", { size: 12 }), "All results")),
        h("h1", { id: "page-title", tabindex: "-1", class: "result-hyp" }, r.text),
        r.code ? h("div", { style: { margin: "0 0 8px" } }, codeChip(r.framework, r.code, r.code_description, r.code_label)) : null,
        h("p", { class: "result-meta" },
          h("span", {}, `${r.status === "waiting" ? "Started" : "Checked"} ${fmt.date(r.created_at)}`),
          r.batch_id ? [h("span", { class: "sep" }, "·"), h("a", { href: `#/history?batch=${encodeURIComponent(r.batch_id)}` }, "part of a set")] : null))));

    const onlyLocal = r.waiting_local && !parts.some((p) => (p.rounds_info || []).some((x) => x.waiting) || ["terms", "rank", "judge"].includes(p.stage));
    if (r.status === "waiting" && onlyLocal) {
      // 0.11: only the excerpts of documents marked Only a local AI wait (their notice is on each part)
      box.appendChild(h("div", { class: "notice notice-info" }, icon("house"), h("p", {}, `${r.waiting_local} ${r.waiting_local === 1 ? "excerpt waits" : "excerpts wait"} for the local model; the answer counts the rest meanwhile. See “Read them now” below.`)));
    }
    if (r.status === "waiting" && !onlyLocal) {
      // 0.8: a check by queue: Claude Code has not read (all of) it yet; the page looks again every few seconds.
      // 0.12: the answer card is the queue notice, and only what already exists is shown below it
      box.appendChild(h("section", { class: "card answer answer-waiting", "aria-label": "Waiting for Claude Code" },
        queueNotice({ text: "Waiting for Claude Code to read the excerpts", command: r.queue_command }, { foldType: true })));
      clearTimeout(waitTimer);
      waitTimer = setTimeout(() => load().catch(() => {}), 5000);
      if (allPassages.length) {
        box.appendChild(evidenceHead(r, allPassages, single));
        for (const part of parts) box.appendChild(partView(part, r, single));
      }
      box.appendChild(noteCard(r));
      box.appendChild(h("div", { class: "result-foot" }, techCard(r, parts), h("button", { class: "link-btn danger-link", type: "button", onClick: () => deleteHyp(r) }, icon("trash", { size: 13 }), "Delete this result")));
    } else {
      // 0.12: the answer (with who says what, and documents added since), then the evidence, then the other AI models,
      // then notes and downloads: each section one purpose
      box.appendChild(answerCard(r, parts, single, allPassages));
      box.appendChild(evidenceHead(r, allPassages, single));
      if (evidenceView === "table" && allPassages.length) box.appendChild(excerptTable(parts, single));
      for (const part of parts) box.appendChild(partView(part, r, single));
      box.appendChild(modelsCard(r, allPassages));
      box.appendChild(noteCard(r));
      box.appendChild(downloadsCard(r, parts));
      box.appendChild(h("div", { class: "result-foot" }, techCard(r, parts), h("button", { class: "link-btn danger-link", type: "button", onClick: () => deleteHyp(r) }, icon("trash", { size: 13 }), "Delete this result")));
    }

    // keep the person's place after a save or a re-read: the card they acted on stays where it was on the screen,
    // even when it moved in the list (the list is sorted by judgement), gets a short highlight and says where it
    // went; a slim placeholder is left at its old place, so the next card slides into it
    window.scrollTo(0, y);
    if (focusAfter) {
      const f = focusAfter; focusAfter = null;
      const el = box.querySelector(`${f.claim_id ? `[data-claim="${CSS.escape(f.claim_id)}"] ` : ""}[data-passage="${CSS.escape(f.passage_id)}"]`);
      if (el) {
        const fl = el.closest("details"); if (fl && !fl.open) { fl.open = true; openFolds.add(fl.dataset.fold); }
        const nowIn = el.closest(".also-read") ? "rest" : "evidence";
        const newIndex = [...el.parentElement.children].filter((e) => e.classList.contains("ev")).indexOf(el);
        const movedList = f.was && f.was !== nowIn;
        const movedInList = !movedList && Number.isInteger(f.index) && newIndex !== f.index;
        const group = { supports: "Supports", partially_supports: "Partly supports", refutes: "Contradicts" }[(el.className.match(/ev-(supports|partially_supports|refutes)/) || [])[1]] || "Not about this hypothesis";
        if ((movedList || movedInList) && !f.noNote) {
          const part = el.closest(".part-card");
          const oldList = part ? (f.was === "rest" ? part.querySelector(".also-read .ev-list") : part.querySelector(":scope > .ev-list")) : null;
          const what = movedList ? (nowIn === "rest" ? "Moved to “not about this hypothesis”" : "Moved into the evidence list")
            : `Moved ${newIndex > f.index ? "down" : "up"} the list (sorted by judgement)`;
          const showIt = () => { el.scrollIntoView({ behavior: "smooth", block: "center" }); el.classList.add("ev-flash"); setTimeout(() => el.classList.remove("ev-flash"), 1800); };
          const ph = h("div", { class: "moved-ph", role: "status" }, icon("arrow-right", { size: 13 }),
            h("span", {}, what, " · "),
            h("button", { class: "link-btn", type: "button", onClick: showIt }, "Show it"),
            f.undo ? [" · ", h("button", { class: "link-btn", type: "button", onClick: f.undo }, "Undo")] : null);
          if (oldList) {
            const kids = [...oldList.children].filter((e) => e.classList.contains("ev") && e !== el);
            // insert before the card that now holds the old index (the card itself is skipped: it left that place)
            oldList.insertBefore(ph, kids[Math.min(f.index, kids.length)] || null);
          } else el.parentElement.insertBefore(ph, el);
          // and the card itself says where it went
          el.insertBefore(h("div", { class: "moved-note", role: "status" }, icon("arrow-right", { size: 13 }),
            h("span", {}, movedList ? (nowIn === "rest" ? "Moved here, to the excerpts that are not about this: " : "Moved here, into the evidence: ") : `Moved ${newIndex > f.index ? "down" : "up"} to here, among the excerpts judged “${group}”: `, f.reason || "the list is sorted by judgement, and this one's judgement changed."),
            f.undo ? h("button", { class: "link-btn", type: "button", onClick: f.undo }, "Undo") : null), el.firstChild);
        }
        // same place on the screen as before, when it was in view then; otherwise bring it into view. With an
        // anchor (the judgement row the person clicked), that row is what stays put, so no button moves under the pointer
        if (!f.noScroll) {
          const r0 = el.getBoundingClientRect();
          const wasInView = Number.isFinite(f.top) && (f.bottom === undefined || f.bottom > 0) && f.top < window.innerHeight;
          const anchorEl = f.anchor ? el.querySelector(f.anchor) : null;
          if (wasInView && anchorEl && Number.isFinite(f.anchorTop)) window.scrollBy(0, anchorEl.getBoundingClientRect().top - f.anchorTop);
          else if (wasInView) window.scrollBy(0, r0.top - f.top);
          else window.scrollBy(0, r0.top - Math.min(120, window.innerHeight / 4));
        }
        el.classList.add("ev-flash");
        setTimeout(() => el.classList.remove("ev-flash"), 1800);
      }
    }
    if (returnTo) {
      const id = returnTo; returnTo = null;
      const el = typeof id === "object" ? box.querySelector(`[data-claim="${CSS.escape(id.claim_id)}"] [data-passage="${CSS.escape(id.passage_id)}"]`) : box.querySelector(`[data-passage="${CSS.escape(id)}"]`);
      if (el) {
        const fl = el.closest("details"); if (fl && !fl.open) { fl.open = true; openFolds.add(fl.dataset.fold); }
        requestAnimationFrame(() => { el.scrollIntoView({ block: "center" }); el.classList.add("ev-flash"); setTimeout(() => el.classList.remove("ev-flash"), 2200); });
      }
      history.replaceState(null, "", `#/h/${encodeURIComponent(hypId)}${Math.abs(threshold - setting) > 1e-9 ? `?threshold=${threshold}` : ""}`);
    }
  }

  // ------------------------------------------------------------------------------------------
  // 0.12: the answer at a glance: the answer and who judged it, one sentence, who says what, then one caution when the
  // answer is fragile, and one button. Every count here is of the excerpts that are about the hypothesis (the ones
  // the AI found not about it come after, and do not make the answer less reviewed). Strictness is in the evidence's head.
  function answerCard(r, parts, single, allPassages) {
    const st = r.status;
    const next = App.statusNext(st);
    const bal = r.balance || {};
    const judged = allPassages.filter(about).length;
    const card = h("section", { class: `card card-verdict v-${st} answer`, "aria-label": "Answer" });
    let sentence = null;
    if (r.decomposed) {
      sentence = partsLine(parts);
    }
    else if (st === "uncertain") sentence = judged === 1 ? "1 excerpt is about it, but the AI was too unsure to count it."
      : `${judged} excerpts are about it, but the AI was too unsure to count any of them.`;
    else if (bal.docs_counted && ((parts[0] || {}).who || []).length) sentence = null;   // the columns below say it
    else if (bal.docs_counted) sentence = docsCountSentence(bal).replace(" No other document counts.", "");
    else sentence = App.statusHelp(st);

    const reviewed = allPassages.filter((p) => p.reviewed);
    const relevantLeft = allPassages.filter((p) => !p.reviewed && (p.ai_verdict || p.waiting_for_you)).length;
    const restLeft = Math.max(0, allPassages.filter((p) => !p.reviewed).length - relevantLeft);   // found not about it, not looked at
    const countedAll = allPassages.filter((p) => p.counted);
    const ownOnly = countedAll.length > 0 && countedAll.every((p) => p.user_verdict);
    const aiBelow = ownOnly && countedAll.every((p) => p.confidence === null || p.confidence === undefined || p.confidence < threshold);
    // AI judgements that decide the answer, not checked (0.12: of a split hypothesis, only in the parts that decide it)
    const unchecked = ownOnly ? 0 : r.decomposed ? decidingParts(parts).flatMap((x) => x.passages || []).filter((p) => p.counted && !p.reviewed).length
      : countedAll.filter((p) => !p.reviewed).length;
    // the same order "Next to review" uses, counted from the same excerpts the cards are drawn from
    const disagreeNew = allPassages.filter((p) => !p.reviewed && p.second && !p.second.agrees).length;
    const scopeNew = allPassages.filter((p) => !p.reviewed && p.scope_note).length;
    const order = unchecked ? "the ones that count first" : disagreeNew ? "where the second opinion differs first" : scopeNew ? "“about another group” first" : "";
    const allRead = parts.length && parts.every((p) => p.more_available === false);
    let advice = allRead && /more evidence|other words/i.test(next || "") ? "Every matching excerpt has been read; read the excerpts and judge them yourself." : next;
    const nextBtn = relevantLeft ? h("button", { class: "btn btn-primary next-review", type: "button", onClick: nextToReview,
      title: [advice, order ? `It goes to the excerpts you have not reviewed, ${order}.` : "It goes to the excerpts you have not reviewed."].filter(Boolean).join(" ") },
      "Next to review", icon("arrow-right", { size: 14 })) : null;
    const restBtn = !relevantLeft && restLeft ? h("button", { class: "link-btn", type: "button", onClick: () => nextToReview({ quiet: true }) }, `Review the ${restLeft} ${restLeft === 1 ? "excerpt" : "excerpts"} judged not about it`) : null;
    // who judged what the answer rests on: the AI (named), you for some, or you for all of it
    const basis = !reviewed.length ? (allPassages.some((p) => p.ai_verdict) ? "judged by the AI" : null) : relevantLeft === 0 ? "reviewed by you" : "partly reviewed by you";
    // at most one caution: what makes this answer fragile
    const singleDoc = bal.docs_counted === 1;
    const aiJ = (n) => (n === 1 ? "one excerpt" : n === 2 ? "two excerpts" : `${n} excerpts`);
    const forYou = allPassages.filter((p) => p.waiting_for_you && !p.reviewed).length;
    const caution = r.incomplete ? "One part of the check did not finish, so this answer is incomplete."
      : singleDoc && unchecked ? `It rests on a single document and on ${aiJ(unchecked)} you have not reviewed.`
      : singleDoc ? "It rests on a single document."
      : unchecked ? `It rests on ${aiJ(unchecked)} you have not reviewed.`
      : forYou ? `${forYou} ${forYou === 1 ? "excerpt waits" : "excerpts wait"} for your own judgement: no AI may read ${forYou === 1 ? "it" : "them"}.` : null;
    const done = !relevantLeft && reviewed.length ? "You have reviewed the evidence: the answer rests on your judgements. Download it for Excel, or add notes." : null;

    card.appendChild(h("div", { class: "answer-status" },
      statusBadge(st, { size: "lg", text: r.status_text || App.statusText(st), title: App.statusHelp(st) || null }),
      strongerMark(r.status_before_stronger, r.stronger),
      basis ? h("span", { class: "basis-text", title: `Who judged the excerpts this answer rests on${r.model ? `. The AI model: ${r.model} (more under Technical details)` : ""}` }, basis) : null));
    if (sentence) card.appendChild(h("p", { class: "answer-sentence" }, sentence));
    if (r.decomposed) {
      card.appendChild(h("ol", { class: "answer-part-list part-grid" }, parts.map((p) => h("li", {},
        h("a", { href: `#part-${p.part}`, class: "part-claim-link", onClick: jumpTo(`part-${p.part}`) }, `${p.part}. ${p.claim}`),
        h("span", { class: "part-answer" }, statusBadge(p.status, { short: true }), strongerMark(p.status_before_stronger, p.stronger, { compact: true, plain: true })),
        h("span", { class: "part-docs" }, p.balance && p.balance.docs_counted ? sidesText(p.balance) : "")))));

    } else {
      const who = whoSaysWhat(parts[0]);
      if (who) card.appendChild(who);
    }
    const added = addedSince(r);
    if (added) card.appendChild(added);
    for (const note of [whatsNew ? whatsNewText(whatsNew, single) : null, followNote].filter(Boolean)) {
      card.appendChild(h("p", { class: "whats-new", role: "status" }, icon("sparkles", { size: 13 }), h("span", {}, "Just now: ", note)));
    }
    if (lastRun) {
      card.appendChild(h("p", { class: "run-summary" }, icon("circle-check", { size: 14 }), h("span", {}, `Done in ${fmt.secs(lastRun.seconds)}`, lastRun.summary ? h("span", { class: "muted" }, ` · ${lastRun.summary}`) : null)));
      lastRun = null;
    }
    const own = ownOnly && relevantLeft ? `The answer rests on your own judgements only${aiBelow ? " (the AI's were below your strictness)" : ""}.` : null;
    const text = caution && done ? `${caution} You have reviewed the evidence; download it for Excel, or add notes.` : caution || done || own || (!nextBtn ? advice : null);
    if (text || nextBtn || restBtn) {
      card.appendChild(h("div", { class: "answer-next" + (card.querySelector(".who, .answer-part-list") ? "" : " answer-next-plain") },
        text ? h("p", { class: "answer-next-text" + (caution ? " answer-caution" : "") }, caution ? icon("alert-triangle", { size: 14 }) : null, text) : null,
        nextBtn || restBtn ? h("div", { class: "answer-next-actions" }, nextBtn, restBtn) : null));
    }
    return card;
  }

  // "2 documents for, 1 partly, 1 against"
  function sidesText(b) {
    const n = b.docs_counted || 0;
    const docsOf = (k) => `${k} ${k === 1 ? "document" : "documents"}`;
    const bits = [[b.docs_supporting, "for"], [b.docs_partly, "partly for"], [b.docs_refuting, "against"]].filter(([k]) => k);
    if (!bits.length) return docsOf(n);
    const plain = bits.map(([k, w], i) => (i ? `${k} ${w}` : `${docsOf(k)} ${w}`)).join(", ");
    if (bits.reduce((t, [k]) => t + k, 0) <= n) return plain;
    // 0.12: a document on two sides is one document: "3 documents for, 1 also against", "1 document for and partly
    // for", "2 documents for, 2 against (3 documents in all)"
    const [[k0, w0], ...rest] = bits;
    if (k0 === n) return n === 1 ? `${docsOf(1)} ${[w0, ...rest.map(([, w]) => w)].join(" and ")}` : `${docsOf(k0)} ${w0}, ${rest.map(([k, w]) => `${k} also ${w}`).join(", ")}`;
    return `${plain} (${docsOf(n)} in all)`;
  }



  // a split hypothesis in one line: which part decides the answer, and what the others are
  function decidingParts(parts) {
    const notOk = parts.filter((p) => p.status !== "supported");
    if (!notOk.length) return parts;
    const contra = notOk.filter((p) => p.status === "contradicted"), mixed = notOk.filter((p) => p.status === "contested");
    return contra.length ? contra : mixed.length ? mixed : notOk;
  }
  function partsLine(parts) {
    if (parts.every((p) => p.status === "supported")) return "Every part is supported, so the whole hypothesis is.";
    const bad = decidingParts(parts);
    const and = (xs) => (xs.length > 1 ? `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}` : xs[0]);
    return `${bad.length > 1 ? "Parts" : "Part"} ${and(bad.map((p) => p.part))} ${bad.length > 1 ? "decide" : "decides"} the answer: the hypothesis holds only if every part does.`;
  }

  function whatsNewText(w, single) {
    const what = single ? "this hypothesis" : "this part";
    if (!w.n) return w.terms && w.terms.length ? `nothing new was found for ${w.terms.join(", ")}: no unread excerpt contains these words.` : "nothing further matched, so no new excerpts were read.";
    const where = w.about === 0 ? ` (they are in the “not about ${what}” list, marked new)` : w.about === w.n ? " (marked new in the evidence list)" : ` (${w.about} in the evidence list, ${w.n - w.about} in the “not about” list, all marked new)`;
    return `${w.n} more ${w.n === 1 ? "excerpt" : "excerpts"} read${w.terms && w.terms.length ? ` for ${w.terms.join(", ")}` : ""}, ${w.about} of them about ${what}${where}.`;
  }

  // "Next to review": moves on from the card it went to last, in this order (0.12): the judgements that count in the
  // answer (those where the second opinion differs or the AI noted another group first), then the other flagged ones,
  // then the rest; cards with only a comment ("come back later") come last. It wraps around.
  function reviewOrder() {
    const all = [...box.querySelectorAll(".ev")].filter((e) => e.dataset.reviewed === "0");
    const key = (e) => `${e.dataset.claim}|${e.dataset.passage}`;
    const plain = all.filter((e) => e.dataset.comment === "0");
    const flagged = (e) => e.dataset.disagree === "1" || e.dataset.scope === "1";
    const groups = [plain.filter((e) => e.dataset.counted === "1" && flagged(e)), plain.filter((e) => e.dataset.counted === "1"),
      plain.filter(flagged), plain, all.filter((e) => e.dataset.comment === "1")];
    const seen = new Set(), out = [];
    for (const g of groups) for (const e of g) { if (!seen.has(key(e))) { seen.add(key(e)); out.push(e); } }
    return { list: out, key };
  }
  function goToCard(el) {
    const fl = el.closest("details");
    if (fl && !fl.open) { fl.open = true; openFolds.add(fl.dataset.fold); }
    el.scrollIntoView({ behavior: "smooth", block: "start" });
    el.classList.add("ev-flash"); setTimeout(() => el.classList.remove("ev-flash"), 1800);
    const first = el.querySelector(".judge button, .judge summary"); if (first) first.focus({ preventScroll: true });
  }
  function nextToReview(opts = {}) {
    if (evidenceView === "table") { evidenceView = "cards"; store("evidenceView", "cards"); draw(current); }   // the cards are what it goes to
    const { list, key } = reviewOrder();
    if (!list.length) { toast("Everything is reviewed.", "ok", { small: true, ttl: 2500 }); return; }
    let el = list.find((e) => !visitedNext.has(key(e)));
    if (!el) { visitedNext.clear(); el = list[0]; toast("Back to the first excerpt still to review: every one was shown once.", "info", { small: true, ttl: 3000 }); }
    visitedNext.add(key(el));
    // 0.12: past the evidence, it says that it now goes to the excerpts the AI found not about the hypothesis
    if (!opts.quiet && el.closest(".also-read") && !el.closest(".also-read").open) toast("The evidence is reviewed: next, the excerpts the AI found not about the hypothesis.", "info", { small: true, ttl: 4000 });
    goToCard(el);
  }

  const jumpTo = (id) => (e) => { e.preventDefault(); const t = document.getElementById(id); if (t) { t.scrollIntoView({ behavior: "smooth", block: "start" }); if (t.focus) t.focus({ preventScroll: true }); } };

  // ------------------------------------------------------------------------------------------
  // Documents added since the check (0.12: inside the answer card, as they can change the answer; nothing when none).
  function addedSince(r) {
    const added = r.docs_added_since || [];
    if (!added.length) return null;
    const n = added.length, m = added.filter((d) => d.matching).length;
    const busy = [...running.values()].filter((x) => x.kind === "read-new");
    const btn = h("button", { class: "btn btn-sm", type: "button", disabled: busy.length > 0,
      title: m ? `The AI reads only ${m === 1 ? "that document" : "those documents"}, as a further search for ${r.decomposed ? "every part" : "this hypothesis"}. The check is not run again, so your reviews are kept.${m === n ? "" : " The others are marked as looked at."}`
        : "Nothing in them shares a word with the hypothesis. Marking them as looked at stops this notice; the check is not run again." },
      icon(m ? "book-open" : "check", { size: 13 }), m ? (m === 1 ? "Read it" : "Read them") : "Mark as looked at");
    btn.addEventListener("click", () => runReadNew(btn));
    const list = fold("added", { class: "fold added-list-fold" }, h("summary", {}, n === 1 ? "Which one" : "Which ones"),
      h("ul", { class: "added-list" }, added.map((d) => h("li", {}, h("a", { href: `#/doc/${encodeURIComponent(d.doc_id)}?from=${encodeURIComponent(hypId)}` }, d.title || "untitled"),
        h("span", { class: "muted" }, d.matching ? " · has matching excerpts" : " · nothing in it matches")))));
    return h("div", { class: "answer-added", role: "status" }, icon("upload", { size: 14 }),
      h("div", { class: "grow" }, h("p", {}, `${n} ${n === 1 ? "document was" : "documents were"} added since this check; ${m === 0 ? "none has" : m === 1 ? "1 has" : `${m} have`} matching excerpts.`), list, busy.map((x) => x.mini.el)),
      btn);
  }

  // ------------------------------------------------------------------------------------------
  // Another AI model (0.11.2): two distinct choices, side by side. A stronger model *replaces* the first reading
  // (the answer can change); a second opinion is *only compared* with it (the answer never changes). 0.12: one line
  // each; the longer story is behind the (?) mark.
  function modelsCard(r, allPassages) {
    // 0.8: on Claude (Claude Code, or the Claude API with a model per task) the auditor gives the second opinion
    const st = App.settings();
    const name = auditorName(st);
    const auditor = name ? `${name} (the auditor)` : null;
    const secondSet = auditor || (st.second_model || "").trim();
    const mainModel = auditor ? "" : (st.ollama_model || st.openai_model || "").trim();
    const secondUsable = secondSet && secondSet !== mainModel;
    const secondRead = r.second_read || 0;
    const read = r.excerpts_read ?? allPassages.length;
    const disagree = r.disagreements || 0;
    const busy = [...running.values()];
    const card = h("section", { class: "card ask-card", "aria-label": "Ask another AI model" });
    // the model that gives second opinions, and where to change it: in the help, not in the flow
    const modelNote = secondUsable && !changingSecond ? h("span", { class: "ask-model" }, " Second opinions come from ", h("strong", { title: sizeHint(secondSet).trim() || null }, name || secondSet),
      name ? [", set in ", h("a", { href: "#/settings/routing" }, "Settings"), "."] : [" (", h("button", { class: "link-btn", type: "button", onClick: () => { changingSecond = true; draw(current); } }, "change"), ")."]) : null;
    const help = popNote(h("button", { class: "link-btn help-mark", type: "button", "aria-label": "What is the difference between the two?" }, icon("help", { size: 15 })),
      h("span", {}, "A stronger model judges the excerpts again, and its judgements take the place of the first AI's, so the answer can change: a small mark beside the answer then says what it was at first, and each changed excerpt shows both readings. A second opinion is another model's own reading, shown beside the first AI's on each excerpt: it never changes the answer, and points you to excerpts worth reading yourself.", modelNote), { wide: true });
    card.appendChild(h("div", { class: "card-head" }, h("h2", {}, "Ask another AI model", help)));
    // 0.12: what has happened first, one line each; then the buttons side by side, what each does in its tooltip
    // (the help mark says it at length)
    const facts = [], buttons = [];
    const STRONG_WHAT = "It replaces the AI's judgements; the answer can change.", SECOND_WHAT = "Shown only for comparison: it never changes the answer.";
    const row = (btn, ...what) => {
      const explains = what.length === 1 && (what[0] === STRONG_WHAT || what[0] === SECOND_WHAT);
      if (btn) { btn.title = [explains ? what[0] : null, btn.title].filter(Boolean).join(" "); buttons.push(btn); }
      if (!btn || !explains) facts.push(h("p", { class: "ask-fact" }, ...what));
    };

    // the stronger model: replaces (no row when the AI chosen has none: the help mark says so)
    const rds = (r.parts || []).flatMap((p) => p.rounds_info || []);
    const canStep = rds.filter((x) => x.can_step_up).length;
    const stepping = rds.filter((x) => x.stronger_waiting).length;
    const stepped = rds.filter((x) => x.stepped_up).length;
    const sInfo = r.stronger || {};
    let strongState = STRONG_WHAT;
    if (stepped) {
      const n = sInfo.changed || 0;
      strongState = `A stronger model read ${stepped === rds.length ? (stepped === 1 ? "the search" : `all ${stepped} searches`) : `${stepped} of the ${rds.length} searches`} again and ${n ? `changed ${n} ${n === 1 ? "judgement" : "judgements"}` : "kept every judgement"}${r.status_before_stronger ? `; the answer was ${(STATUS_SHORT[r.status_before_stronger] || "").toLowerCase()} before` : ""}.`;
    }
    if (stepping) strongState = `Reading ${stepping === 1 ? "a search" : `${stepping} searches`} again; until then the first reading counts.`;
    if (!current.stronger_model && !stepped && !stepping) {
      // none for this AI: said beside a button that cannot be pressed, so the choice is not hidden
      row(null, "No stronger model is set. ", h("a", { href: "#/settings/routing" }, "Set one in Settings"), ".");
    } else if ((current.stronger_model && canStep) || stepped || stepping) {
      let strongBtn = null;
      if (current.stronger_model && canStep) {
        strongBtn = h("button", { class: "btn btn-sm", type: "button", disabled: busy.some((x) => x.kind === "stronger") }, stepped ? `Ask it for the ${canStep === 1 ? "new search" : `${canStep} new searches`}` : "Ask a stronger model");
        strongBtn.title = `The stronger model: ${current.stronger_model}`;
        strongBtn.addEventListener("click", () => runStronger(strongBtn));
      }
      row(strongBtn, strongState);
    } else {
      row(null, "Stronger model: nothing here for it to read again yet.");
    }

    // the second opinion: compares
    const allSecond = secondRead >= read && read > 0;
    const secState = secondRead ? `The second model read ${secondRead === read ? `all ${read}` : `${secondRead} of the ${read}`} excerpts and ${disagree ? `judged ${disagree} differently` : "judged every one the same way"}.` : SECOND_WHAT;
    if (secondUsable && !changingSecond) {
      let secBtn = null;
      if (!allSecond) {
        secBtn = h("button", { class: "btn btn-sm", type: "button", disabled: busy.some((x) => x.kind === "second-opinion"), title: auditor ? null : ONE_MODEL_NOTE }, secondRead ? "Second opinion on the rest" : "Get a second opinion");
        secBtn.addEventListener("click", () => runSecondOpinion(secBtn));
      }
      row(secBtn, secState);
    } else if (secondRead) row(null, secState);
    if (facts.length) card.appendChild(h("div", { class: "ask-facts" }, facts));
    if (buttons.length) card.appendChild(h("div", { class: "btn-row ask-buttons" }, buttons));
    if (!auditor && !(secondUsable && !changingSecond)) card.appendChild(secondModelPicker(mainModel, secondUsable ? secondSet : "", busy.some((x) => x.kind === "second-opinion")));
    const jobs = busy.filter((x) => !x.passage_id && x.kind !== "read-new").map((x) => x.mini.el);
    if (jobs.length) card.appendChild(h("div", { class: "stack ask-jobs" }, jobs));
    return card;
  }

  // The model's size in plain words, from its name ("llama3.1:8b" -> 8 billion parameters).
  function sizeHint(name) {
    const m = /(\d+(?:\.\d+)?)\s*b\b/i.exec(name || "");
    return m ? ` (${m[1]}b: about ${m[1]} billion parameters; a larger model is usually better, but slower)` : "";
  }

  // No second model yet: choose one right here, from the other chat models the server has, and ask it, in one step.
  // The choice is saved in Settings (second_model) when the button is pressed.
  function secondModelPicker(mainModel, currentChoice, busy) {
    const sel = h("select", { class: "select input-sm", "aria-label": "Model for second opinions", disabled: true,
      title: "The number before “b” in a model's name is its size, in billions of parameters: a larger model is usually better, but slower." }, h("option", { value: "" }, "Looking for other models…"));
    const ask = h("button", { class: "btn btn-sm", type: "button", disabled: true, title: ONE_MODEL_NOTE }, icon("cpu", { size: 13 }), "Get a second opinion");
    const state = h("span", { class: "muted small", "aria-live": "polite" });
    const box = h("div", { class: "second-pick" },
      h("p", { class: "ask-state muted" }, h("span", {}, currentChoice ? "Choose another model on this computer " : "Choose a model on this computer ", "(", h("a", { href: "#/settings/second" }, "Settings"), "):")),
      h("div", { class: "row", style: { gap: "6px 8px" } }, sel, ask, currentChoice ? h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => { changingSecond = false; draw(current); } }, "Keep it") : null, state));
    (serversOnce = serversOnce || api("GET", "/api/servers")).then((r) => {
      const models = [...new Set((r.servers || []).flatMap((x) => x.chat_models || []))].filter((m) => m !== mainModel);
      replace(sel, models.length ? [h("option", { value: "" }, "Choose a model…"), models.map((m) => h("option", { value: m, selected: m === currentChoice }, m))] : h("option", { value: "" }, "No other model is installed"));
      sel.disabled = !models.length;
      ask.disabled = !sel.value || busy;
      if (!models.length) state.textContent = "Ask whoever installed the app to add a second model (for Ollama: ollama pull <model>).";
      sel.addEventListener("change", () => { ask.disabled = !sel.value || busy; });
    }).catch(() => { replace(sel, h("option", { value: "" }, "The model server did not answer")); });
    ask.addEventListener("click", async () => {
      if (!sel.value) return;
      ask.disabled = true; state.textContent = "Saving the choice…";
      try {
        const r = await api("PUT", "/api/settings", { second_model: sel.value });
        App.state.settings = r.settings;
        changingSecond = false;
        await runSecondOpinion(ask);
      } catch (e) { showError(e); ask.disabled = false; state.textContent = ""; }
    });
    return box;
  }

  // Watches a follow-up job of this result; `onDone(job, fresh)` runs when it finished well, with the result as
  // fetched once for the re-draw (one request, not two). The page redraws either way.
  function followJob(jobId, kind, title, onDone, extra = {}) {
    const mini = new MiniJob({ title });
    running.set(jobId, { kind, mini, ...extra });
    const w = watchJob(jobId, (job) => mini.update(job));
    watchers.push(w);
    w.promise.then(async (job) => {
      running.delete(jobId);
      let fresh = null;
      try { fresh = await api("GET", `/api/projects/${P(project)}/hypotheses/${P(hypId)}?threshold=${threshold}`); }
      catch (e) { if (e.status === 404) { await load(); return; } showError(e); }   // deleted meanwhile: load() says so
      if (job.state === "done") { try { await onDone(job, fresh || current); } catch (e) { showError(e); } }
      else if (job.state === "error") showError({ message: job.error, kind: job.error_kind });
      else if (job.state === "cancelled") toast("Stopped.", "info", { small: true, ttl: 2500 });
      if (fresh) { current = fresh; draw(fresh); }   // draw() keeps the scroll position, and the card the person acted on in place
    }).catch((e) => { running.delete(jobId); showError(e); });
    draw(current);
    return w;
  }

  async function runReadNew(btn) {
    btn.disabled = true;
    try {
      // no body: the endpoint takes none (and does not read one, so a body would spill into the next request)
      const res = await api("POST", `/api/projects/${P(project)}/hypotheses/${P(hypId)}/read-new`);
      const matching = (current.docs_added_since || []).filter((d) => d.matching).length;
      followJob(res.job.id, "read-new", matching ? "Reading the new documents" : "Marking the new documents as looked at", async (job, fresh) => {
        const me = ((job.result && job.result.hypotheses) || []).find((x) => x.hyp_id === hypId) || {};
        const n = me.passages || 0;
        let aboutN = 0;
        for (const rd of me.rounds || []) {
          const fp = (fresh.parts || []).find((x) => x.claim_id === rd.claim_id);
          if (!fp || !rd.passages) continue;
          newRound.set(rd.claim_id, rd.round);
          const newOnes = (fp.passages || []).filter((x) => x.round === rd.round);
          aboutN += newOnes.filter(about).length;
          if (newOnes.length && !newOnes.some(about)) openFolds.add(`rest:${rd.claim_id}`);
        }
        const docs = me.documents || 0, match = me.matching || 0;
        followNote = !match ? `${docs} ${docs === 1 ? "document" : "documents"} marked as looked at: nothing in ${docs === 1 ? "it" : "them"} matched this hypothesis.`
          : n ? `${match === 1 ? "The new document" : `The ${match} new documents`} with matching excerpts ${match === 1 ? "was" : "were"} read: ${n} more ${n === 1 ? "excerpt" : "excerpts"}, ${aboutN} of them about ${fresh.decomposed ? "a part of this hypothesis" : "this hypothesis"} (marked new below). Your reviews are kept${docs > match ? `; the ${docs - match === 1 ? "other document" : "other documents"} matched nothing and ${docs - match === 1 ? "is" : "are"} marked as looked at` : ""}.`
          : "The new documents were looked at, but none of their excerpts could be read for this hypothesis.";
        toast(n ? `${n} more ${n === 1 ? "excerpt" : "excerpts"} read from the new documents.` : "The new documents are marked as looked at.", "ok", { small: true, ttl: 4000 });
      });
    } catch (e) { showError(e); btn.disabled = false; }
  }

  async function runStronger(btn) {
    btn.disabled = true;
    try {
      const res = await api("POST", `/api/projects/${P(project)}/hypotheses/${P(hypId)}/stronger`, {});
      const before = current.status;
      followJob(res.job.id, "stronger", `A stronger model (${current.stronger_model}) reads the excerpts again`, async (job, fresh) => {
        const n = (fresh.stronger || {}).changed || 0;
        followNote = `A stronger model read the excerpts again and ${n ? `changed ${n} ${n === 1 ? "judgement" : "judgements"}` : "kept every judgement"}. Its reading counts${fresh.status !== before ? `: the answer is now ${(STATUS_SHORT[fresh.status] || "").toLowerCase()} (it was ${(STATUS_SHORT[before] || "").toLowerCase()})` : "; the answer stays the same"}.`;
        toast("The stronger model has read the excerpts again.", "ok", { small: true, ttl: 4000 });
      });
    } catch (e) { showError(e); btn.disabled = false; }
  }

  async function runSecondOpinion(btn) {
    btn.disabled = true;
    try {
      const res = await api("POST", `/api/projects/${P(project)}/second-opinion`, { hyp_ids: [hypId] });
      followJob(res.job.id, "second-opinion", "A second opinion: another model reads the excerpts", async (job, fresh) => {
        const d = fresh.disagreements || 0;
        followNote = `The second opinion is in for ${fresh.second_read || 0} ${fresh.second_read === 1 ? "excerpt" : "excerpts"}${d ? `; it differs from the first AI on ${d}: “Next to review” goes to ${d === 1 ? "it" : "those"} first. The answer is unchanged.` : " and matches the first AI on every one. The answer is unchanged."}`;
        toast("The second opinion is in.", "ok", { small: true, ttl: 4000 });
      });
    } catch (e) {
      if (e.status === 400) toast(e.message, "warn", { action: { href: "#/settings/second", text: "Choose a model for second opinions in Settings" } }); else showError(e);
      btn.disabled = false;
    }
  }

  // A follow-up job of this project started earlier (or on another page) and still running: show and follow it.
  async function adoptRunningJobs() {
    let jobs = [];
    try { jobs = (await api("GET", "/api/jobs")).jobs || []; } catch (_) { return; }
    const titles = { reread: "Reading one excerpt again", "read-new": "Reading the new documents", "second-opinion": "A second opinion: another model reads the excerpts", stronger: "A stronger model reads the excerpts again" };
    for (const j of jobs) {
      if (j.project !== project || !titles[j.kind] || TERMINAL.has(j.state) || running.has(j.id)) continue;
      if (j.kind === "stronger" && j.scope !== hypId) continue;   // a stronger model for another result
      followJob(j.id, j.kind, titles[j.kind], async () => { followNote = { reread: "The AI has read an excerpt again.", "read-new": "The new documents were read.", "second-opinion": "The second opinion is in.", stronger: "A stronger model has read the excerpts again; its reading counts." }[j.kind]; });
    }
  }

  // "8 excerpts read in 5 of 6 documents"; "5 of 6" opens a line naming the documents not read
  function readSentence(all, docsRead, total) {
    const n = all.length;
    if (!n) return h("span", { class: "result-read" }, "nothing read yet");
    let docsEl = h("span", {}, `${docsRead} of ${total ?? docsRead} documents`);
    let unreadLine = null;
    if (total && docsRead < total) {
      unreadLine = h("span", { class: "muted small unread-line", hidden: !openFolds.has("unread") }, "…");
      const fill = async () => {
        try {
          const docs = (await api("GET", `/api/projects/${P(project)}/documents`)).documents || [];
          const readIds = new Set(all.map((p) => p.doc_id));
          const unread = docs.filter((d) => !readIds.has(d.doc_id)).map((d) => d.title || d.file);
          replace(unreadLine, unread.length ? `Not read for this check: ${unread.join("; ")}.` : "Every document was read.");
        } catch (e) { showError(e); }
      };
      let pinned = openFolds.has("unread");
      const show = (on) => { unreadLine.hidden = !on; docsEl.setAttribute("aria-expanded", on ? "true" : "false"); if (on) fill(); };
      docsEl = h("button", { class: "link-btn defined", type: "button", "aria-expanded": pinned ? "true" : "false", "aria-label": `${docsRead} of ${total} documents; which were not read?`,
        onClick: () => { pinned = !pinned; if (pinned) openFolds.add("unread"); else openFolds.delete("unread"); show(pinned); },
        onMouseenter: () => show(true), onMouseleave: () => { if (!pinned) show(false); }, onFocus: () => show(true), onBlur: () => { if (!pinned) show(false); } }, `${docsRead} of ${total} documents`);
      if (pinned) fill();
    }
    return h("span", { class: "result-read" }, `${n} `, definedTerm(n === 1 ? "excerpt" : "excerpts", "An excerpt is a stretch of a document of up to about 180 words. Documents are read excerpt by excerpt, and each excerpt is judged on its own."), " read in ", docsEl, unreadLine);
  }

  // A term with an explanation that opens on hover or focus and stays open on click or tap (no native tooltip).
  const definedTerm = (term, explanation) => popNote(h("button", { class: "defined", type: "button" }, term), explanation);

  // ------------------------------------------------------------------------------------------
  // 0.12: who says what, one document per row: its title, then what it says and where, each side with its judgement
  // mark ("● supports it: paragraph 9 of 9 · ● contradicts it: paragraph 5 of 9"). Wraps the same way on a phone.
  function whoSaysWhat(part) {
    const bal = part.balance || {};
    const who = part.who || [];
    if (!bal.docs_counted || !who.length) return null;
    const verbOf = { supports: "supports it", partly: "partly supports it", refutes: "contradicts it" };
    const sideOf = { supports: "supports", partially_supports: "partly", refutes: "refutes" };
    const order = { supports: 0, partly: 1, refutes: 2 };
    const docs = new Map();   // doc_id -> {title, sides: Map(side -> locations)}
    for (const w of who) {
      const d = docs.get(w.doc_id) || { title: w.title, sides: new Map() };
      d.sides.set(w.side, [...(d.sides.get(w.side) || []), ...(w.locations || [])]);
      docs.set(w.doc_id, d);
    }
    // counted excerpts of a document on a side `who` does not list (a document with supporting and partly supporting ones)
    for (const p of (part.passages || []).filter((x) => x.counted && x.verdict)) {
      const d = docs.get(p.doc_id), sd = sideOf[p.verdict];
      if (d && !d.sides.has(sd)) d.sides.set(sd, [p.location]);
    }
    const first = (d) => Math.min(...[...d.sides.keys()].map((k) => order[k]));
    const rows = [...docs.values()].sort((x, y) => first(x) - first(y));
    return h("ul", { class: "who who-list", "aria-label": "Who says what: the documents whose excerpts count" },
      rows.map((d) => h("li", {},
        h("span", { class: "who-title" }, d.title || "untitled"),
        h("span", { class: "who-sides" }, [...d.sides.entries()].sort((x, y) => order[x[0]] - order[y[0]]).flatMap(([sd, locs], i) => [
          i ? h("span", { class: "sep" }, " · ") : null, h("span", { class: `who-dot who-${sd}`, "aria-hidden": "true" }),
          h("span", { class: "who-side" }, `${verbOf[sd] || "counts"}${locs.filter(Boolean).length ? `: ${placesText(locs).replace(/ of \d+/g, "")}` : ""}`)])))));
  }

  // "page 1, paragraph 5", "page 1, paragraph 4" -> "page 1, paragraphs 4 and 5"; "paragraph 9 of 9", "paragraph 5 of 9"
  // -> "paragraphs 5 and 9 of 9" (0.12)
  function placesText(locs) {
    const and = (xs) => (xs.length > 1 ? `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}` : String(xs[0]));
    const pages = new Map(), ofs = new Map(), other = [];
    for (const l of new Set(locs.filter(Boolean))) {
      let m = /^page (\d+), paragraph (\d+)$/i.exec(l);
      if (m) { if (!pages.has(m[1])) pages.set(m[1], []); pages.get(m[1]).push(+m[2]); continue; }
      m = /^paragraph (\d+) of (\d+)$/i.exec(l);
      if (m) { if (!ofs.has(m[2])) ofs.set(m[2], []); ofs.get(m[2]).push(+m[1]); continue; }
      other.push(l);
    }
    const out = [];
    for (const [pg, ps] of pages) { ps.sort((x, y) => x - y); out.push(ps.length > 1 ? `page ${pg}, paragraphs ${and(ps)}` : `page ${pg}, paragraph ${ps[0]}`); }
    for (const [of, ps] of ofs) { ps.sort((x, y) => x - y); out.push(ps.length > 1 ? `paragraphs ${and(ps)} of ${of}` : `paragraph ${ps[0]} of ${of}`); }
    return [...out, ...other].join("; ");
  }

  // ------------------------------------------------------------------------------------------
  function partView(part, r, single) {
    const passages = part.passages || [];
    const judged = passages.filter(about);
    // 0.11: excerpts no model read (documents marked No AI, or Only a local AI without a local model) wait for you
    const waitingYou = passages.filter((p) => !about(p) && (p.waiting_for_you || p.waiting_local));
    const rest = passages.filter((p) => !about(p) && !waitingYou.includes(p));
    const counted = passages.filter((p) => p.counted).length;
    const card = h("section", { class: "card part-card", "aria-label": single ? "Evidence" : `Part ${part.part}`, tabindex: "-1" });
    card.id = `part-${part.part}`;
    card.dataset.claim = part.claim_id;
    if (!single) {
      card.appendChild(h("div", { class: "part-head" },
        h("div", { class: "grow" }, h("p", { class: "part-claim" }, h("span", { class: "pn" }, `Part ${part.part}: `), part.claim),
          part.target ? h("div", { style: { marginTop: "6px" } }, codeChip(part.framework, part.target, part.target_description, r.code_label)) : null)));
      const who = whoSaysWhat(part);
      if (who) { who.classList.add("who-inline"); card.appendChild(who); }

      else card.appendChild(h("p", { class: "part-sentence" }, part.status === "uncertain" ? "Judged, but nothing was certain enough to count." : docsCountSentence(part.balance)));
    }
    if (part.status === "failed" && part.errors && part.errors.length) {
      card.appendChild(h("div", { class: "notice notice-error" }, icon("alert-circle"), h("div", {}, h("p", {}, "The AI's answers could not be used, even after three tries."), h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("ul", { class: "errors-list" }, part.errors.slice(0, 5).map((e) => h("li", {}, e)))))));
    }
    if (part.local_failed) {
      const n = part.local_failed.passages;
      card.appendChild(h("div", { class: "notice notice-warn" }, icon("house"), h("div", { class: "grow" }, h("p", {}, `The local model's answers for ${n} ${n === 1 ? "excerpt" : "excerpts"} from documents marked Only a local AI could not be used, even after three tries; ${n === 1 ? "it is" : "they are"} shown without a judgement. Try again (perhaps with another local model, Settings → AI), or judge ${n === 1 ? "it" : "them"} yourself.`),
        h("div", { class: "btn-row" }, readLocalButton("Read them again on this computer")),
        part.local_failed.errors.length ? h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("ul", { class: "errors-list" }, part.local_failed.errors.map((e) => h("li", {}, e)))) : null)));
    }
    if (part.status === "no_passages") {
      card.appendChild(h("div", { class: "notice notice-warn" }, icon("search-x"), h("p", {}, "No part of your documents uses words close to this. Try other words below, rephrase the hypothesis, or add documents.")));
    }
    const what = single ? "this hypothesis" : "this part";
    // 0.12: a split hypothesis says per part what its evidence is; a single one says it once, above the cards
    if (!judged.length && passages.length) {
      card.appendChild(h("p", { class: "part-sentence" }, `None of the ${passages.length} ${passages.length === 1 ? "excerpt" : "excerpts"} read is about ${what}.`));
    }
    if (part.waiting_local) card.appendChild(readLocalNotice(part));
    if (evidenceView === "table") {
      card.appendChild(h("p", { class: "muted small table-note" }, icon("list-checks", { size: 13 }), ` The ${passages.length} ${passages.length === 1 ? "excerpt" : "excerpts"} read for ${what} ${passages.length === 1 ? "is" : "are"} in the table above; click a row to open it as a card.`));
    } else {
      const byCount = [...judged.filter((x) => x.counted || x.user_verdict), ...judged.filter((x) => !(x.counted || x.user_verdict))];
      if (judged.length) card.appendChild(h("div", { class: "ev-list" }, byCount.map((p) => evidenceCard(p, part))));
      const forYou = waitingYou.filter((p) => p.waiting_for_you);
      if (forYou.length) {
        card.appendChild(h("div", { class: "evidence-head" }, h("h3", {}, `Waiting for your judgement: ${forYou.length} ${forYou.length === 1 ? "excerpt" : "excerpts"}`),
          h("span", { class: "muted small" }, "No AI may read these (their documents are marked No AI, or Only a local AI without a local model). Your judgement counts like any other.")));
        card.appendChild(h("div", { class: "ev-list" }, forYou.map((p) => evidenceCard(p, part))));
      }
      if (rest.length) {
        card.appendChild(fold(`rest:${part.claim_id}`, { class: "fold also-read" }, h("summary", { title: "Listed so you can check the search; you can judge them yourself" }, `${rest.length} ${rest.length === 1 ? "excerpt" : "excerpts"} read that ${rest.length === 1 ? "is" : "are"} not about ${what}`),

          h("div", { class: "ev-list" }, rest.map((p) => evidenceCard(p, part)))));
      }
    }
    card.appendChild(moreRow(part, r));
    return card;
  }

  // 0.12: the evidence section's head: the title with the switch between cards and a compact table (remembered in
  // this browser); what is about the hypothesis and what counts at your strictness (changed for this page in place);
  // that highlights are checked quotes and that your judgement replaces the AI's.
  function evidenceHead(r, allPassages, single) {
    const n = allPassages.length;
    const aboutN = allPassages.filter(about).length;
    const countedN = allPassages.filter((p) => p.counted).length;
    const below = allPassages.filter((p) => p.verdict && !p.counted).length;
    const set = (v) => { if (v === evidenceView) return; evidenceView = v; store("evidenceView", v); draw(current); };
    const btn = (v, label) => h("button", { class: "btn btn-sm seg-btn" + (evidenceView === v ? " seg-on" : ""), type: "button", "aria-pressed": evidenceView === v ? "true" : "false", onClick: () => set(v),
      title: v === "table" ? "One row per excerpt, with your decisions; click a row to open its card" : "The full text of each excerpt, with its quote, your judgement and the AI's" }, label);
    const temp = Math.abs(threshold - setting) > 1e-9;
    const help = popNote(h("button", { class: "link-btn help-mark", type: "button", "aria-label": "About strictness" }, icon("help", { size: 13 })),
      h("span", {}, `Your strictness decides which of the AI's judgements count in the answer: only those the AI was at least ${Math.round(threshold * 100)}% sure of${below ? ` (${below} ${below === 1 ? "was" : "were"} less sure here)` : ""}. Your own judgements always count. The AI's certainty is its own estimate, not a check of whether it is right. `,
        h("button", { class: "link-btn", type: "button", onClick: openStrictness }, "Try another strictness on this page"), "."), { wide: true });
    const strict = h("span", { class: "nowrap ev-strict", id: "strictness", tabindex: "-1" }, `at ${strictness(threshold)} strictness${temp ? " (this page only)" : ""}`, help);
    // 0.12: one line: what counts (said by the answer already when nothing does), and the two rules
    const count = single ? `${countedN} of ${aboutN} ${aboutN === 1 ? "excerpt counts" : countedN === 1 ? "excerpts counts" : "excerpts count"} `
      : `${countedN} of ${aboutN} ${countedN === 1 ? "judgements counts" : "judgements count"} across the parts `;
    return h("div", { class: "ev-section-head" },
      h("div", { class: "ev-title-row" }, h("h2", {}, "Evidence"),
        n ? h("div", { class: "view-toggle", role: "group", "aria-label": "How to show the excerpts" }, btn("cards", "Cards"), btn("table", "Table")) : null),
      n ? h("p", { class: "ev-section-sub" }, h("span", { class: "ev-count" }, count, strict,
        temp ? [" ", h("button", { class: "link-btn", type: "button", onClick: () => setThreshold(setting) }, "Back to my strictness")] : null),
        h("span", { class: "ev-rules" }, "Every quote is checked against its document; your judgement overrides the AI's.")) : null);
  }

  // "change" beside the strictness: the slider under Technical details, for this page only
  function openStrictness() {
    openFolds.add("tech");
    const d = box.querySelector('[data-fold="tech"]');
    if (d) d.open = true;
    const slider = box.querySelector("#thr");
    if (slider) { slider.scrollIntoView({ behavior: "smooth", block: "center" }); slider.focus({ preventScroll: true }); }
  }

  // One compact row per excerpt read, in the cards' order (part by part: evidence first, then the ones not about it).
  function excerptTable(parts, single) {
    const rows = [];
    for (const part of parts) {
      const ps = part.passages || [];
      for (const p of [...ps.filter(about), ...ps.filter((x) => !about(x))]) rows.push([part, p]);
    }
    const split = parts.length > 1;
    const open = (part, p) => { evidenceView = "cards"; store("evidenceView", "cards"); returnTo = { claim_id: part.claim_id, passage_id: p.passage_id }; draw(current); };
    const yours = (p) => p.user_verdict ? h("span", { class: `it ${p.changed ? "corrected" : ""}` }, icon(p.changed ? "note" : "check", { size: 12 }), p.user_verdict === "not_relevant" ? "Not about this" : GRADE_TEXT[p.user_verdict]) : p.user_note ? h("span", { class: "muted" }, "your comment") : h("span", { class: "faint" }, "—");
    const second = (p) => {
      if (!p.second) return h("span", { class: "faint" }, "—");
      const you = p.user_verdict ? (p.user_verdict === "not_relevant" ? null : p.user_verdict) : undefined;
      const agreesYou = you === undefined ? null : (p.second.verdict || null) === you;
      const ok = agreesYou === null ? !!p.second.agrees : agreesYou;
      return h("span", { class: `it ${ok ? "" : "tag-disagree"}` }, icon(ok ? "check" : "arrows-opposed", { size: 12 }), `${gradeWords(p.second.verdict, p.second.confidence)} · ${agreesYou === null ? (p.second.agrees ? "same as the AI" : "differs from the AI") : (agreesYou ? "same as you" : "differs from you")}`);
    };
    const table = h("table", { class: "table table-responsive ex-table" },
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "#"), split ? h("th", { scope: "col" }, "Part") : null, h("th", { scope: "col" }, "Document"), h("th", { scope: "col" }, "Where"), h("th", { scope: "col" }, "AI's judgement"), h("th", { scope: "col" }, "Your judgement"), h("th", { scope: "col" }, "Counts"), h("th", { scope: "col" }, "Second opinion"))),
      h("tbody", {}, rows.map(([part, p], i) => h("tr", { class: `row-link ex-row ex-${p.verdict || "none"}${p.reviewed ? " ex-reviewed" : ""}`, tabindex: "0", onClick: () => open(part, p), onKeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(part, p); } } },
        h("td", { class: "num muted" }, String(i + 1)),
        split ? h("td", { "data-label": "Part" }, `Part ${part.part}`) : null,
        h("td", { "data-label": "Document", class: "ex-doc" }, h("span", { class: "serif" }, p.title || "untitled"), p.scope_note ? h("div", { class: "small", style: { color: "var(--partly)" } }, `about another group: ${p.scope_note}`) : null),
        h("td", { "data-label": "Where", class: "small muted" }, p.location || p.span || ""),
        h("td", { "data-label": "AI's judgement" }, h("span", { class: "it" }, icon(p.ai_verdict ? { supports: "circle-check", partially_supports: "circle-half", refutes: "circle-x" }[p.ai_verdict] : "circle-dashed", { size: 12 }), gradeWords(p.ai_verdict, p.confidence)), p.reread ? h("div", { class: "small muted" }, "read again") : null),
        h("td", { "data-label": "Your judgement" }, yours(p)),
        h("td", { "data-label": "Counts" }, p.verdict ? (p.counted ? h("span", { class: "it", style: { color: "var(--ok)" } }, icon("check", { size: 12 }), "counts") : h("span", { class: "muted small" }, "too uncertain")) : h("span", { class: "muted small" }, "not about it")),
        h("td", { "data-label": "Second opinion", class: "small" }, second(p))))));
    return h("section", { class: "card ex-table-card", "aria-label": "All excerpts read" },
      h("div", { class: "card-head" }, h("h2", {}, `All ${rows.length} excerpts read`), h("span", { class: "muted small" }, "in the same order as the cards; your judgements count whatever the AI's certainty")),
      h("div", { class: "table-wrap" }, table));
  }

  // What was searched for in each round, and the AI's note on that round's excerpts: 0.12, one quiet line each (how
  // many excerpts a search reads is under Technical details).
  function roundsBlock(part, r) {
    const rounds = part.rounds_info || [];
    if (!rounds.length) return h("div");
    const own = new Set((r.text + " " + (part.claim || "")).toLowerCase().split(/[^a-z0-9]+/i).filter(Boolean));
    const box = h("div", { class: "rounds" });
    for (const rd of rounds) {
      const terms = (rd.terms || []).filter((t) => !own.has(String(t).toLowerCase()));
      const isNew = newRound.get(part.claim_id) === rd.round;
      const corrected = (part.passages || []).some((p) => p.round === rd.round && p.changed);
      box.appendChild(h("div", { class: "round-row" + (isNew ? " round-new" : "") },
        h("p", { class: "round-head" }, icon("search", { size: 13 }),
          h("span", {}, `${rounds.length > 1 ? `Search ${rd.round}` : "Searched"} for ${terms.length ? `the hypothesis's words and ${terms.join(", ")}` : "the hypothesis's words"} · ${rd.passages} ${rd.passages === 1 ? "excerpt" : "excerpts"} read`),
          isNew ? h("span", { class: "badge new-badge" }, "new") : null),
        (rd.parts || []).length > 1 ? h("p", { class: "round-readers" }, icon("shield", { size: 12 }), " ", rd.parts.map((x) => READ_BY_ROUND[x.read_by] ? READ_BY_ROUND[x.read_by](x.passages) : `${x.passages}`).join(" · ")) : null,
        rd.ai_note ? h("p", { class: "ai-note" }, icon("quote", { size: 13 }), h("span", {}, corrected ? "The AI's note, before your corrections: " : "The AI's note: ", rd.ai_note)) : null,
        strongerLine(rd)));
    }
    const tried = triedTerms.get(part.claim_id) || [];
    if (tried.length) box.appendChild(h("div", { class: "round-row round-tried" }, h("p", { class: "round-head" }, icon("search-x", { size: 13 }), h("span", {}, `You also tried ${tried.join(", ")}: nothing new was found.`))));
    return box;
  }

  // 0.11: excerpts that wait for the local model (a check made in a Claude chat, or while the app was closed)
  function readLocalButton(label) {
    const btn = h("button", { class: "btn btn-sm btn-primary", type: "button" }, icon("house", { size: 13 }), label);
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const r = await api("POST", `/api/projects/${P(project)}/hypotheses/${P(current.hyp_id)}/read-local`, {});
        const w = watchJob(r.job.id, () => {});
        watchers.push(w);
        const job = await w.promise;
        if (job.state === "error") showError({ message: job.error, kind: job.error_kind });
        load();
      } catch (e) { showError(e); btn.disabled = false; }
    });
    return btn;
  }

  function readLocalNotice(part) {
    const btn = readLocalButton("Read them now on this computer");
    return h("div", { class: "notice notice-info wait-local" }, icon("house"), h("div", { class: "grow" },
      h("p", {}, `${part.waiting_local} ${part.waiting_local === 1 ? "excerpt comes" : "excerpts come"} from documents marked Only a local AI and ${part.waiting_local === 1 ? "waits" : "wait"} for the local model.`),
      h("div", { class: "btn-row" }, btn, h("span", { class: "muted small" }, "Without a local model (Settings → AI) they wait for your judgement."))));
  }

  // What a stronger model did with one search (0.11.2: asking for one is in "Ask another AI model", for the whole result)
  function strongerLine(rd) {
    if (rd.waiting) return h("div", { class: "muted small" }, icon("inbox", { size: 12 }), " Waiting for Claude Code.");
    if (rd.stronger_waiting) return h("div", { class: "muted small" }, icon("inbox", { size: 12 }), " A stronger model reads these excerpts again; until then the first reading counts.");
    if (rd.stepped_up) return h("div", { class: "muted small" }, icon("layers", { size: 12 }), " A stronger model read these excerpts again; its reading counts (each changed excerpt shows the first one).");
    return null;
  }

  // 0.11.2: where the second opinion's quote is in the excerpt (it gives its own), or null
  function secondQuote(p) {
    const q = p.second && p.second.verdict ? p.second.quote : null;
    if (!q) return null;
    const i = String(p.text || "").indexOf(q);
    return i >= 0 ? { start: i, end: i + q.length } : null;
  }

  // 0.11.2: when the second opinion quoted another sentence, a switch for which of the two quotes the passage
  // highlights (0.12: on the card's note line; that the second opinion differs is a fact in the card's head)
  function secondQuoteSwitch(p, part) {
    const key = pendingKey(p, part);
    const sq = secondQuote(p);
    if (!sq || (sq.start === p.quote_start && sq.end === p.quote_end)) return null;
    const on = secondShown.has(key);
    const flip = (v) => () => { if (v === on) return; if (v) secondShown.add(key); else secondShown.delete(key); draw(current); };
    const seg = (v, label) => h("button", { class: "link-btn so-seg" + (on === v ? " so-seg-on" : ""), type: "button", "aria-pressed": on === v ? "true" : "false", onClick: flip(v) }, label);
    return h("span", { class: "so-flip", role: "group", "aria-label": "Which quote the excerpt highlights" },
      "Highlight the quote of: ", seg(false, p.quote_by === "you" ? "yours" : "the AI"), " / ", seg(true, "the second opinion"));
  }

  function evidenceCard(p, part) {
    const v = p.verdict || "none";
    const yours = !!p.user_verdict;
    const isNew = newRound.get(part.claim_id) === p.round;
    const pct = p.confidence !== null && p.confidence !== undefined ? ` (${Math.round(p.confidence * 100)}%)` : "";
    const card = h("article", { class: `ev ev-${v} ${p.counted ? "" : "ev-uncounted"} ${p.changed ? "ev-yours" : ""}`, "aria-label": `${p.verdict ? GRADE_TEXT[p.verdict] : "Not about this"}: ${p.title || "untitled"}` });
    card.dataset.passage = p.passage_id;
    card.dataset.reviewed = p.reviewed ? "1" : "0";
    card.dataset.counted = p.counted ? "1" : "0";
    card.dataset.disagree = p.second && !p.second.agrees ? "1" : "0";
    card.dataset.scope = p.scope_note ? "1" : "0";
    card.dataset.comment = !p.reviewed && p.user_note ? "1" : "0";   // "come back later": after everything else
    card.dataset.claim = part.claim_id;
    const pending = pendingQuote.get(pendingKey(p, part)) || null;
    // 0.12: the head: the judgement and at most two quiet facts (who judged it, or the AI's certainty and whether it
    // counts; a second opinion that differs); who read it, when that differs from card to card, at the far end.
    // Certainty in words; the percentage is in the tooltip and under More.
    const top = h("div", { class: "ev-top" });
    const fact = (text, extra = {}) => h("span", { class: "ev-fact", ...extra }, text);
    const aiSaid = p.ai_verdict ? GRADE_TEXT[p.ai_verdict].toLowerCase() : "not about this";
    const pctN = p.confidence !== null && p.confidence !== undefined ? Math.round(p.confidence * 100) : null;
    const word = p.certainty || (pctN !== null ? `${pctN}%` : "");
    if (yours && p.changed) {
      append(top, [gradeBadge(p.verdict, false), h("span", { class: "ev-fact ev-yours-fact" }, icon("check", { size: 12 }), p.read_by === "you" ? "Your judgement" : `Your judgement (the AI said ${aiSaid})`)]);
    } else if (yours) {
      append(top, [gradeBadge(p.verdict, false), h("span", { class: "ev-fact ev-yours-fact" }, icon("check", { size: 12 }), "You agreed with the AI")]);
    } else if (p.waiting_for_you) {
      append(top, [fact("Waiting for your judgement", { class: "ev-fact ev-yours-fact" }),
        fact(p.access === "none" ? "its document is marked No AI" : "its document is marked Only a local AI, and no local model is chosen")]);
    } else {
      append(top, [gradeBadge(p.verdict, false)]);
      if (p.verdict && !p.counted) append(top, [h("span", { class: "ev-fact ev-uncounted-fact", title: [certaintyHelp(p), "It is below your strictness: it counts once you judge it yourself (agreeing or otherwise)."].filter(Boolean).join(" ") }, word ? `Not counted · certainty: ${word}` : "Not counted")]);
      else if (p.verdict && word) append(top, [fact(`Certainty: ${word}`, { title: certaintyHelp(p) })]);
      else if (!p.verdict && p.waiting_local) append(top, [fact("Waiting for the local model")]);
      else if (p.user_note) append(top, [fact("Your comment", { title: "You wrote a comment on this excerpt but have not judged it: the AI's judgement still counts" })]);
    }
    if (p.second && !p.second.agrees) append(top, [h("span", { class: "ev-fact ev-second", title: `Another model${p.second.model ? ` (${p.second.model})` : ""} read this excerpt on its own and judged it differently. It is shown for comparison only and never changes the answer.` }, h("span", { class: `who-dot who-${{ supports: "supports", partially_supports: "partly", refutes: "refutes" }[p.second.verdict] || "none"}`, "aria-hidden": "true" }), `Second opinion: ${p.second.verdict ? GRADE_TEXT[p.second.verdict].toLowerCase() : "not about this"}`)]);
    if (isNew) append(top, [h("span", { class: "badge new-badge" }, "new")]);
    if (p.read_by && !p.waiting_for_you && !oneReader) append(top, [h("span", { class: "spacer" }), readByChip(p)]);
    card.appendChild(top);
    const hist = p.ai_history || [];
    if (p.reread && hist.length) {
      const first = hist[0];
      const info = p.reread_info || {};
      card.appendChild(h("div", { class: "reread-line" }, icon("refresh", { size: 13 }),
        h("div", {},
          h("div", {}, hist[hist.length - 1].why === "stepped up" ? `Read again by a stronger model (the first reading was by ${first.model || "the first model"}): ` : "Read again by the AI: ", `was ${gradeWords(first.verdict, first.confidence)}, now ${gradeWords(p.ai_verdict, p.confidence)}`, hist.length > 1 ? ` (read again ${hist.length} times; the list is under Technical details)` : "", ". ",
            p.user_verdict ? h("span", { class: "reread-yours" }, `Your own judgement (${p.user_verdict === "not_relevant" ? "Not about this" : GRADE_TEXT[p.user_verdict]}) still counts.`) : "The new judgement counts, unless you judge it yourself."),
          info.rationale ? h("div", { class: "reread-why" }, h("span", { class: "muted" }, "The AI's reason: "), info.rationale) : null,
          info.hint ? h("div", { class: "reread-why" }, h("span", { class: "muted" }, "Your note was given to the AI: "), h("q", {}, info.hint)) : null,
          h("div", { class: "reread-why muted" }, info.hint ? "The AI may simply follow your hint: judge the excerpt yourself." : "A re-read is still the AI's reading: judge the excerpt yourself."))));
    }
    const span = quoteSpan(p);
    card.appendChild(h("div", { class: "ev-src" },
      h("span", { class: "title" }, p.title || "untitled"),
      whereText(p),
      (() => {
        const o = (current && current.parts || []).map((x) => [x, (x.passages || []).find((y) => y.passage_id === p.passage_id && about(y))]).filter(([x, y]) => x.claim_id !== part.claim_id && y);
        if (!o.length) return null;
        const yours = (y) => (y.user_verdict ? `, where you judged it ${y.user_verdict === "not_relevant" ? "not about it" : GRADE_TEXT[y.user_verdict].toLowerCase()}` : "");
        return h("span", { class: "page also-in", title: "This excerpt was read for each of these parts; each part judges it on its own" }, ` ·\u00a0also in ${o.map(([x, y]) => `part ${x.part}${yours(y)}`).join(" and ")}`);
      })(),
      !p.in_corpus ? h("span", { class: "warn-chip", title: "This document was removed from the project after the check" }, icon("alert-triangle", { size: 12 }), "document removed since") : null));
    // a sentence marked before a judgement was chosen is shown, but not saved until the judgement comes
    const sq = secondQuote(p);
    const showSecond = sq && secondShown.has(pendingKey(p, part));
    const [hs, he, hcls] = pending && Number.isInteger(pending.start) ? [pending.start, pending.end, "passage passage-pending"]
      : showSecond ? [sq.start, sq.end, "passage passage-second"] : [p.quote_start, p.quote_end, "passage"];
    const wkey = pendingKey(p, part);
    const whole = wholeShown.has(wkey);
    const win = !whole && !p.waiting_for_you ? excerptWindow(p.text, hs, he, p.breaks, { after: matchMedia("(max-width: 600px)").matches ? 0 : 1 }) : null;
    const passageEl = win ? windowNode(p.text, hs, he, hcls, p.breaks, win) : passageNode(p.text, hs, he, "p", hcls, p.breaks);
    card.appendChild(passageEl);
    // the ways into the document: with the whole excerpt (In context), not in every card's row
    if (whole && p.in_corpus) card.appendChild(h("p", { class: "ev-doclink" }, h("a", { href: docHref(p, span) }, "Open the whole document at this place"), " · ",
      originalLink(project, p.doc_id, p.page, null, { text: "the original file", quote: p.quote || null, pdfHint: !!p.quote, noIcon: true }),
      p.verdict || p.user_verdict ? [" · ", h("button", { class: "link-btn", type: "button", title: "A copy of this document with the judgements of this hypothesis highlighted (green supports, amber partly, red contradicts), each with a note",
        onClick: () => download(`/api/projects/${P(project)}/documents/${P(p.doc_id)}/annotated.pdf?hyp=${encodeURIComponent(hypId)}&threshold=${threshold}`).catch(showError) }, "a highlighted copy")] : null));
    // 0.12: what to keep in mind about the quote, on one quiet line after it, each with its explanation behind a (?)
    const why = (text) => popNote(h("button", { class: "link-btn help-mark", type: "button", "aria-label": "Why?" }, icon("help", { size: 13 })), text, { wide: true });
    const notes = [];
    if (p.scope_note) notes.push(h("span", { class: "has-tip", title: SCOPE_HELP }, `About another group: ${p.scope_note.replace(/^about\s+/i, "")}`));
    if (p.refers_to) {  // check-v4: what the quote's "it" or "the plant" is
      const word = ((p.quote || "").match(/^\W*([\p{L}’']+(?:\s+(?:latter|former))?)/u) || [])[1] || "it";
      notes.push(h("span", { class: "refers", title: "The AI named what the quote refers to; the name was checked against the text" }, `“${word}” = ${p.refers_to}${p.refers_location ? ` (${p.refers_location})` : ""}`));
    } else if (p.reference_missing && !p.reviewed) {
      const first = ((p.quote || "").match(/^\W*([\p{L}’']+)/u) || [])[1] || "it";
      notes.push(h("span", {}, `The quote begins with “${first}”: check what it refers to`,
        why("The quote starts with a word like “it” or “this”, and the AI did not say what it refers to: read the text before it to be sure the excerpt is about what the hypothesis names.")));
    }
    const flipQuote = p.second && !p.second.agrees ? secondQuoteSwitch(p, part) : null;
    if (flipQuote) notes.push(flipQuote);
    if (notes.length) card.appendChild(h("p", { class: "ev-notes" }, notes.flatMap((n, i) => (i ? [h("span", { class: "sep" }, " · "), n] : [n]))));
    if (pending) {
      card.appendChild(h("div", { class: "pending-quote", role: "status" }, icon("highlighter", { size: 13 }),
        h("span", {}, "Sentence marked", Number.isInteger(pending.start) ? "" : [": ", h("q", {}, pending.text)], ". Choose your judgement below to save it. "),
        h("button", { class: "link-btn", type: "button", onClick: () => { pendingQuote.delete(pendingKey(p, part)); draw(current); } }, "Forget this sentence")));
    }
    const hasQuoteNow = Number.isInteger(p.quote_start) && Number.isInteger(p.quote_end) && p.quote_end > p.quote_start;
    if ((hasQuoteNow && p.quote_by === "you" || showSecond) && !pending) {
      const aiDiffers = p.quote_by === "you" && p.ai_quote && p.ai_quote !== p.quote;
      card.appendChild(h("div", { class: "quote-by muted small" }, icon("highlighter", { size: 12 }),
        h("span", {}, showSecond ? `Sentence highlighted by the second opinion${p.second.model ? ` (${p.second.model})` : ""}` : "Sentence highlighted by you",
          aiDiffers ? [" · The AI pointed to: ", h("q", {}, p.ai_quote)] : null)));
    }
    if (p.user_note) card.appendChild(h("div", { class: "user-note" }, h("span", {}, h("span", { class: "muted" }, "Your comment: "), p.user_note)));
    if (p.verdict && p.quote && !(Number.isInteger(p.quote_start) && Number.isInteger(p.quote_end))) {
      card.appendChild(h("div", { class: "ev-weak-note" }, icon("info", { size: 13 }), "Quote: ", h("q", {}, p.quote)));
    }
    // 0.12: one row of actions on every card: the three judging buttons, then two quiet ones: "In context" (the whole
    // excerpt, the document, the original file, a highlighted copy) and "Details" (how it was read, reading it again)
    const extras = { buttons: [], panels: [] };
    if (p.in_corpus || win || whole) {
      // 0.12: "In context" is the one way to see more of the text: the whole excerpt the AI read, with a way on into
      // the whole document at this place
      const ctxBtn = h("button", { class: "btn btn-sm btn-ghost ev-link ctx-toggle", type: "button", "aria-expanded": whole ? "true" : "false", onMousedown: (e) => e.preventDefault(),
        title: "The whole excerpt the AI read, and the way into the whole document at this place", onClick: () => {
          if (whole) wholeShown.delete(wkey); else wholeShown.add(wkey);
          const j = card.querySelector(".judge");
          if (j && j.saveDraft && j.saveDraft()) return;
          focusAfter = { passage_id: p.passage_id, claim_id: part.claim_id, ...placeOf(p.passage_id, part.claim_id), noNote: true };
          redraw();
        } }, whole ? "Less context" : "In context");
      extras.buttons.push(ctxBtn);
    }
    let rereadBtn = null;
    if (p.read_by !== "you") {   // 0.11: no model may read it
      // 0.12: under Details, with the facts about how this excerpt was read
      rereadBtn = h("button", { class: "btn btn-sm", type: "button", title: "The AI reads this excerpt again, on its own, with your comment as a hint", disabled: [...running.values()].some((x) => x.kind === "reread" && x.passage_id === p.passage_id) }, icon("refresh", { size: 13 }), "Ask the AI to read this again");
      rereadBtn.addEventListener("click", () => rereadDialog(p, part, rereadBtn));
    }
    const sec = p.second;
    const morePanel = h("div", { class: "ev-more-panel" },
      rereadBtn ? h("div", { class: "ev-more-actions" }, rereadBtn) : null,
      h("dl", { class: "ev-tech-list" },
        p.confidence !== null && p.confidence !== undefined ? h("div", {}, h("dt", {}, "AI certainty"), h("dd", {}, `${Math.round(p.confidence * 100)}%; your strictness counts from ${Math.round(threshold * 100)}%`)) : null,
        h("div", {}, h("dt", {}, "Found"), h("dd", {}, { keywords: "same words", meaning: "search by meaning", both: "same words and search by meaning" }[p.found_by] || p.found_by || "")),
        (p.matched || []).length ? h("div", {}, h("dt", {}, "Words that found it"), h("dd", {}, p.matched.join(", "))) : null,
        p.refers_to ? h("div", {}, h("dt", {}, "The quote refers to"), h("dd", {}, `${p.refers_to}${p.refers_location ? ` (${p.refers_location})` : ""}`)) : null,
        p.round ? h("div", {}, h("dt", {}, "Search round"), h("dd", {}, String(p.round))) : null,
        p.scope_note ? h("div", {}, h("dt", {}, "AI's scope note"), h("dd", {}, p.scope_note)) : null,
        p.span ? h("div", {}, h("dt", {}, "The excerpt covers"), h("dd", {}, p.span)) : null,
        h("div", {}, h("dt", {}, "Excerpt id"), h("dd", { class: "mono" }, p.passage_id))),
      hist.length ? h("div", { class: "tech-block" }, h("div", { class: "muted small" }, "The AI's earlier judgements of this excerpt (oldest first), before it was asked to read it again:"),
        h("ol", { class: "ai-history" }, hist.map((x) => h("li", {}, `${gradeWords(x.verdict, x.confidence)}${x.scope_note ? ` · scope note: ${x.scope_note}` : ""} · ${x.model || ""} · ${fmt.date(x.at)}${x.replaced_at ? ` → replaced ${fmt.date(x.replaced_at)}` : ""}`, x.quote ? h("div", { class: "muted small serif" }, `“${x.quote}”`) : null)),
          h("li", {}, `${gradeWords(p.ai_verdict, p.confidence)}${p.scope_note ? ` · scope note: ${p.scope_note}` : ""} · ${part.model || current.model || ""} · now`))) : null,
      sec ? h("div", { class: "tech-block" }, h("div", { class: "muted small" }, `Second model: ${sec.model || ""} · ${gradeWords(sec.verdict, sec.confidence)} · ${sec.agrees ? "agrees" : "disagrees"} with the main model's own judgement (${gradeWords(p.ai_verdict, p.confidence)}) · ${fmt.date(sec.at)}`),
        sec.scope_note ? h("div", { class: "muted small" }, `Its scope note: ${sec.scope_note}`) : null,
        sec.quote ? h("div", { class: "muted small serif" }, `Its quote: “${sec.quote}”`) : null) : null);
    const moreBtn = panelToggle(`tech:${p.passage_id}`, "Details", morePanel, false, false);
    moreBtn.title = "How this excerpt was found and judged, and asking the AI to read it again";
    moreBtn.classList.add("more-toggle");
    extras.buttons.push(moreBtn);
    extras.panels.push(morePanel);
    card.appendChild(judgeControl(p, part, passageEl, extras));
    for (const x of running.values()) if (x.kind === "reread" && x.passage_id === p.passage_id) card.appendChild(x.mini.el);
    return card;
  }

  // Where a card is on the screen now, and in which list: for keeping the person's place across a reload.
  function placeOf(passageId, claimId) {
    const el = box.querySelector(`${claimId ? `[data-claim="${CSS.escape(claimId)}"] ` : ""}[data-passage="${CSS.escape(passageId)}"]`);
    if (!el) return { top: 120, bottom: 400, was: null };
    const r0 = el.getBoundingClientRect();
    const list = [...el.parentElement.children].filter((e) => e.classList.contains("ev"));
    return { top: r0.top, bottom: r0.bottom, was: el.closest(".also-read") ? "rest" : "evidence", index: list.indexOf(el) };
  }

  // "Ask the AI to read this again": the AI reads this one excerpt alone, with the person's comment as a hint.
  async function rereadDialog(p, part, btn) {
    const note = h("textarea", { class: "textarea", rows: 2, id: "reread-note", placeholder: "e.g. “the next sentence says the opposite” — or leave it empty for a plain re-read", maxlength: 500 });
    note.value = p.user_note || "";
    const keep = h("input", { type: "checkbox", id: "reread-keep", checked: true });
    const keepRow = h("label", { class: "it small", for: "reread-keep", style: { marginTop: "6px" } }, keep, " Also save this as my comment on the excerpt");
    const syncKeep = () => { const has = !!note.value.trim(); keep.disabled = !has; keepRow.classList.toggle("muted", !has); };
    note.addEventListener("input", syncKeep);
    const ok = await dialog({
      title: "Ask the AI to read this excerpt again?",
      body: h("div", {},
        h("p", {}, "The AI reads only this excerpt again, on its own. Its new judgement replaces its earlier one on this card; the earlier one stays visible."),
        p.user_verdict ? h("p", {}, h("strong", {}, "Your own judgement is not changed and still counts."), " The AI's reading is for comparison.") : h("p", {}, "If you have judged it yourself, your judgement stays and still counts."),
        h("div", { class: "field" }, h("label", { class: "field-label", for: "reread-note" }, p.user_note ? "Your comment is given to the AI as a hint (change it here, or empty the box for a re-read without a hint)" : "A hint for the AI (optional: leave it empty for a re-read without a hint)"), note,
          h("div", { class: "field-help" }, "The hint is added to the AI's instructions as “A reader noted: …”. The AI may simply follow it, so judge the excerpt yourself afterwards."),
          keepRow)),
      actions: [{ text: "Cancel", value: false }, { text: "Read it again", value: true, primary: true, id: "dlg-confirm" }],
      onOpen() { syncKeep(); note.focus(); },
    });
    if (!ok) return;
    btn.disabled = true;
    const hint = note.value.trim();
    const body = hint ? { note: hint } : {};
    try {
      // the hint saved as the comment first (with the judgement the person has, or none), so it stays on the card
      if (hint && keep.checked && hint !== (p.user_note || "")) {
        await api("PUT", `/api/projects/${P(project)}/claims/${P(part.claim_id)}/judgements/${P(p.passage_id)}`, { verdict: p.user_verdict || null, note: hint });
      }
      const res = await api("POST", `/api/projects/${P(project)}/claims/${P(part.claim_id)}/reread/${P(p.passage_id)}`, body);
      followJob(res.job.id, "reread", "The AI is reading this excerpt again", async (job) => {
        const r = job.result || {};
        const b = r.before || {}, a = r.after;
        followNote = `The AI read an excerpt again: was ${gradeWords(b.verdict, b.confidence)}, now ${a ? gradeWords(a.verdict, a.confidence) : "not about this hypothesis"}${a && a.rationale ? ` — ${a.rationale}` : ""}${p.user_verdict ? ". Your own judgement still counts" : ""}.`;
        const place = placeOf(p.passage_id, part.claim_id);
        const inView = place.bottom > 0 && place.top < window.innerHeight;
        focusAfter = { passage_id: p.passage_id, claim_id: part.claim_id, ...place, noScroll: !inView, reason: "the AI's new judgement sorts it here." };
        const showIt = () => { const el = box.querySelector(`[data-claim="${CSS.escape(part.claim_id)}"] [data-passage="${CSS.escape(p.passage_id)}"]`); if (!el) return; const fl = el.closest("details"); if (fl && !fl.open) { fl.open = true; openFolds.add(fl.dataset.fold); } el.scrollIntoView({ behavior: "smooth", block: "center" }); el.classList.add("ev-flash"); setTimeout(() => el.classList.remove("ev-flash"), 1800); };
        toast(`The AI has read the excerpt again: now ${a ? gradeWords(a.verdict, a.confidence) : "not about this hypothesis"}.`, "ok", { small: true, ttl: 8000, button: inView ? undefined : { text: "Show the excerpt", onClick: showIt } });
      }, { passage_id: p.passage_id });
    } catch (e) { showError(e); btn.disabled = false; }
  }

  // "quote in paragraph 6 of 8 · the excerpt covers paragraphs 1–6"; with no quote only what the excerpt covers
  // "The quote is on page 1, paragraph 4", with what the whole excerpt covers on a lighter second line
  function whereText(p) {
    const hasQuote = Number.isInteger(p.quote_start) && Number.isInteger(p.quote_end) && p.quote_end > p.quote_start;
    const covers = (sp) => { const m = /^(pages?|paragraphs?) (\d+)[–-](\d+)(?: of (\d+))?$/i.exec(sp || ""); if (m) return `the excerpt shown runs from ${m[1].replace(/s$/, "")} ${m[2]} to ${m[3]}${m[4] ? ` of ${m[4]}` : ""}`; const m2 = /^(page \d+), paragraphs (\d+)[–-](\d+)$/i.exec(sp || ""); if (m2) return `the excerpt shown runs from paragraph ${m2[2]} to ${m2[3]} of ${m2[1]}`; return `the excerpt shown covers ${sp}`; };
    // 0.12: the quote's place, short; what the whole excerpt covers is in the title
    const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
    const nb = (t) => String(t).replace(/ /g, "\u00a0");
    if (hasQuote && p.location) return h("span", { class: "page", title: `The quote is ${/^page/i.test(p.location) ? "on" : "in"} ${p.location}${p.span && p.span !== p.location ? `; ${covers(p.span)}` : ""}.` }, ` ·\u00a0${nb(p.location)}`);
    if (p.span) return h("span", { class: "page", title: `${cap(covers(p.span))}.` }, ` ·\u00a0${nb(p.span)}`);
    return p.location ? h("span", { class: "page" }, ` ·\u00a0${nb(p.location)}`) : null;
  }

  // the quote's place in the whole document (character offsets), or the excerpt's start when there is no quote
  function quoteSpan(p) {
    const base = p.doc_start || 0;
    if (Number.isInteger(p.quote_start) && Number.isInteger(p.quote_end) && p.quote_end > p.quote_start) return { start: base + p.quote_start, end: base + p.quote_end };
    return { start: base, end: base + (p.text || "").length, whole: true };
  }
  function docHref(p, span) {
    return `#/doc/${encodeURIComponent(p.doc_id)}?from=${encodeURIComponent(hypId)}&card=${encodeURIComponent(p.passage_id)}&q=${span.start}-${span.end}${span.whole ? "&whole=1" : ""}`;
  }

  function certaintyHelp(p) {
    if (p.confidence === null || p.confidence === undefined) return "";
    const pct = Math.round(p.confidence * 100);
    return `The AI said it was ${pct}% sure of this judgement. Judgements count from ${Math.round(threshold * 100)}% (your strictness: ${strictness(threshold)}).`;
  }

  // Review: agree (saves the AI's own verdict), judge differently (saves on click), comment. Every save can be undone.
  function judgeControl(p, part, passageEl, extras = {}) {
    const wrap = h("div", { class: "judge" });
    const state = h("span", { class: "muted small", "aria-live": "polite" });
    const prev = { verdict: p.user_verdict || null, note: p.user_note || "", quote: p.quote_by === "you" ? p.quote : undefined };
    let noteField = null;
    let saving = false;
    const put = async (verdict, note, msg, opts = {}) => {
      saving = true;
      state.textContent = "Saving…";
      const el = wrap.closest(".ev");
      const list = el ? [...el.parentElement.children].filter((e) => e.classList.contains("ev")) : [];
      const rect = el ? el.getBoundingClientRect() : { top: 80, bottom: 400 };
      // the judgement row is what the person clicked: after the re-draw it stays where it is on the screen
      focusAfter = { passage_id: p.passage_id, claim_id: part.claim_id, top: rect.top, bottom: rect.bottom, anchor: ".judge", anchorTop: wrap.getBoundingClientRect().top, was: el && el.closest(".also-read") ? "rest" : "evidence", index: el ? list.indexOf(el) : 0,
        reason: verdict ? `your judgement is now ${verdict === "not_relevant" ? "“Not about this”" : `“${GRADE_TEXT[verdict]}”`}.` : "the AI's judgement counts again." };
      const fa = focusAfter;
      const noteNow = note ?? (noteField ? noteField.value.trim() : prev.note);   // a comment typed before picking is saved with the judgement
      const body = { verdict, note: noteNow };
      if (opts.quote !== undefined) body.quote = opts.quote;   // the sentence the person points to; left out = keep the earlier one
      const pend = pendingQuote.get(pendingKey(p, part));
      if (verdict && opts.quote === undefined && pend) { body.quote = pend.text; opts = { ...opts, quote: pend.text }; }   // a sentence marked before choosing: saved with the judgement
      if (verdict) pendingQuote.delete(pendingKey(p, part));
      try {
        await api("PUT", `/api/projects/${P(project)}/claims/${P(part.claim_id)}/judgements/${P(p.passage_id)}`, body);
        draftNotes.delete(pendingKey(p, part));   // the comment went with it
        const undo = async () => {
          focusAfter = { passage_id: p.passage_id, claim_id: part.claim_id, ...placeOf(p.passage_id, part.claim_id), reason: "your last change was undone." };
          const back = { verdict: prev.verdict, note: prev.note };
          if (opts.quote !== undefined) back.quote = prev.quote === undefined ? "" : prev.quote;
          try { await api("PUT", `/api/projects/${P(project)}/claims/${P(part.claim_id)}/judgements/${P(p.passage_id)}`, back); toast("Undone.", "ok", { ttl: 2500, small: true, group: "judge" }); await load(); }
          catch (e) { showError(e); }
        };
        fa.undo = undo;   // this save's own place note (a redraw meanwhile may have used and cleared focusAfter)
        const was = statusNow();
        await load();
        const now = statusNow();
        const change = was && now && was !== now ? ` The answer is now ${(STATUS_SHORT[now] || now).toLowerCase()}.` : "";
        if (!opts.silent) toast(msg + change, "ok", { ttl: 8000, small: true, group: "judge", button: { text: "Undo", onClick: undo } });
      } catch (e) { saving = false; if (opts.onError) opts.onError(e); else showError(e); state.textContent = ""; }
    };
    const aiVerdict = p.ai_verdict || "not_relevant";
    const current = p.user_verdict || "";
    const row = h("div", { class: "judge-row" });
    if (p.read_by === "you" && p.user_verdict) {
      row.appendChild(h("button", { class: "btn btn-sm agree-btn", type: "button", onMousedown: (e) => e.preventDefault(), onClick: () => put(null, p.user_note || "", "Your judgement was removed: the excerpt waits for it again.") }, "Take back"));
    } else if (p.changed) {
      // 0.12: the same as taking an agreement back: saved at once, with Undo (the comment is sent along, so it is kept)
      row.appendChild(h("button", { class: "btn btn-sm agree-btn", type: "button", onMousedown: (e) => e.preventDefault(), title: "Your judgement is removed and the AI's counts again, at your strictness",
        onClick: () => put(null, p.user_note || "", "Back to the AI's judgement.") }, "Take back"));
    } else if (p.read_by === "you") {
      // 0.11: no AI read it, so there is nothing to agree with: the person's own judgement is open at once
    } else {
      const agreed = p.reviewed && !p.changed;
      const pendHere = pendingQuote.get(pendingKey(p, part));
      // 0.12: the first slot of every card: agree (saying so when it makes an uncounted judgement count), or take the
      // agreement back; what agreeing does is in the button's title
      if (agreed) {
        row.appendChild(h("button", { class: "btn btn-sm agree-btn", type: "button", onMousedown: (e) => e.preventDefault(), title: "Your agreement is removed and the AI's judgement counts as the AI's again, at your strictness",
          onClick: () => put(null, p.user_note || "", "Your agreement is taken back.") }, "Take back"));
      } else {
        const makesCount = p.ai_verdict && p.verdict && !p.counted;
        row.appendChild(h("div", { class: "agree-box" },
          h("button", { class: "btn btn-sm agree-btn agree-main", type: "button", onMousedown: (e) => e.preventDefault(), onClick: () => put(aiVerdict, undefined, pendHere ? "Saved: you agree with the AI, with your sentence." : makesCount ? "Saved: you agree with the AI, so it now counts." : "Saved: you agree with the AI."),
            title: p.ai_verdict ? `Agree with the AI: it becomes your judgement and counts in the answer, whatever the AI's certainty${makesCount ? " (it does not count now)" : ""}.` : "Agree with the AI: you checked it, and it stays out of the answer." },
            "Agree"),
          pendHere ? h("span", { class: "muted small" }, "Agreeing saves your sentence with the AI's judgement as yours.") : null));
      }
    }
    // 0.12: dismiss an excerpt in one click: your judgement "Not about this" takes it out of the evidence and the
    // answer; it stays listed with the excerpts that are not about the hypothesis, and Undo is offered
    const canDismiss = p.read_by !== "you" && p.verdict && p.user_verdict !== "not_relevant";
    if (!canDismiss && !p.waiting_for_you) row.appendChild(h("span", { class: "slot-gap", "aria-hidden": "true" }));
    if (canDismiss) {
      row.appendChild(h("button", { class: "btn btn-sm btn-ghost dismiss-btn", type: "button", onMousedown: (e) => e.preventDefault(),
        title: "Dismiss it: your judgement “Not about this” takes it out of the evidence and the answer. It stays listed at the bottom, and you can undo it.",
        onClick: () => put("not_relevant", undefined, `Saved: not about this. It moved to the excerpts read that are not about ${splitResult() ? "this part" : "the hypothesis"}, under the cards.`) }, "Not about this"));
    }
    const judgePanel = h("div", { class: "judge-body judge-panel" });
    const needed = !!(pendingQuote.get(pendingKey(p, part)) || (p.read_by === "you" && !p.user_verdict));   // the options are needed now
    // the buttons above do "Not about this" and the AI's own judgement (Agree): the radios offer the others
    const opts = USER_VERDICTS.filter(([val]) => !(canDismiss && val === "not_relevant") && !(p.read_by !== "you" && !p.changed && val === (p.ai_verdict || "not_relevant"))).map(([val, label]) =>
      h("button", { class: "btn btn-sm judge-opt", type: "button", "aria-pressed": current === val ? "true" : "false", onMousedown: (e) => e.preventDefault(),
        onClick: () => { if (val !== current) put(val, undefined, `Saved: ${label}.`); } }, h("span", { class: `who-dot who-${{ supports: "supports", partially_supports: "partly", refutes: "refutes" }[val] || "none"}`, "aria-hidden": "true" }), label));
    const pendNow = pendingQuote.get(pendingKey(p, part));
    const hasQuote = Number.isInteger(p.quote_start) && Number.isInteger(p.quote_end) && p.quote_end > p.quote_start;
    const note = h("input", { class: "input input-sm", type: "text", placeholder: "Add a comment", value: draftNotes.has(pendingKey(p, part)) ? draftNotes.get(pendingKey(p, part)) : p.user_note || "", "aria-label": "Comment on this excerpt (saved on Enter, or when you leave the field)", title: "Saved on Enter, or when you leave the field" });
    noteField = note;
    // a comment alone is not a judgement: it is sent with verdict null and the AI's judgement keeps counting
    // 0.12: a comment is saved with Enter or when the field is left (a judgement picked meanwhile takes it along)
    const saveNote = () => { if (!saving && note.value.trim() !== (p.user_note || "").trim()) put(current || null, note.value.trim(), current ? "Comment saved." : "Comment saved. It is not a judgement: the AI's judgement still counts."); };
    note.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); saveNote(); } });
    note.addEventListener("blur", saveNote);
    note.addEventListener("input", () => draftNotes.set(pendingKey(p, part), note.value));
    // "In context" re-draws the card: a comment typed and not saved yet is saved first (the save re-draws it)
    wrap.saveDraft = () => { if (saving || note.value.trim() === (p.user_note || "").trim()) return false; saveNote(); return true; };
    const judgeBtn = panelToggle(`judge:${part.claim_id}:${p.passage_id}`, p.read_by === "you" && !p.user_verdict ? "Judge this excerpt…" : p.user_verdict ? "Edit judgement…" : "Judge differently…", judgePanel, needed, false);
    judgeBtn.title = "A comment, another judgement, or another sentence as the quote";
    judgeBtn.classList.add("judge-toggle");
    append(judgePanel, [
      pendNow ? h("p", { class: "pending-hint" }, icon("arrow-right", { size: 13 }), " Now choose your judgement for this sentence:") : null,
      h("p", { class: "judge-caption" }, current ? `Your judgement: ${current === "not_relevant" ? "not about this" : GRADE_TEXT[current].toLowerCase()}. Change it to:` : p.read_by === "you" ? "Your judgement:" : "Instead of the AI's judgement:"),
      h("div", { class: "judge-opts", role: "group", "aria-label": "Your judgement (saved when you pick one)" }, opts),
      h("div", { class: "row", style: { marginTop: "8px" } }, note),
      markSentence()]);
    judgePanel.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); judgeBtn.click(); judgeBtn.focus(); } });

    // "Mark the sentence you mean": select text in the excerpt (mouse or touch), or pick a sentence from the list
    // (keyboard). Saved with the current judgement and comment; the highlight then moves.
    function markSentence() {
      const msg = h("span", { class: "muted small mark-msg", "aria-live": "polite" });
      const saveQuote = (text) => {
        const q = (text || "").replace(/\s+/g, " ").trim();
        if (!q) { msg.textContent = "Select a sentence in the excerpt first."; return; }
        if (!(p.text || "").replace(/\s+/g, " ").includes(q)) { msg.textContent = "The selection must be text from this excerpt."; return; }
        msg.textContent = "";
        if (current) { put(current, undefined, "Saved: your sentence is highlighted.", { quote: q, onError: (e) => { msg.textContent = e.message || "Could not save the sentence."; } }); return; }
        // no judgement yet: the sentence is kept on the card (not saved) until a judgement is chosen for it
        const at = (p.text || "").indexOf(q);
        pendingQuote.set(pendingKey(p, part), { text: q, start: at >= 0 ? at : null, end: at >= 0 ? at + q.length : null });
        focusAfter = { passage_id: p.passage_id, claim_id: part.claim_id, ...placeOf(p.passage_id, part.claim_id), anchor: ".judge", anchorTop: wrap.getBoundingClientRect().top, noNote: true };
        redraw();
        const el = box.querySelector(`[data-claim="${CSS.escape(part.claim_id)}"] [data-passage="${CSS.escape(p.passage_id)}"] .judge-opts button`);
        if (el) el.focus({ preventScroll: true });
      };
      const useSel = h("button", { class: "btn btn-sm", type: "button", onMousedown: (e) => e.preventDefault(), onClick: () => {
        const sel = window.getSelection();
        const inside = sel && sel.rangeCount && !sel.isCollapsed && passageEl.contains(sel.anchorNode) && passageEl.contains(sel.focusNode);
        if (!inside) { msg.textContent = sel && !sel.isCollapsed ? "The selection must be inside this excerpt." : "Select a sentence in the excerpt first."; return; }
        saveQuote(sel.toString());
      } }, "Use selected text");
      const sentences = splitSentences(p.text).filter((x) => x.length > 12);
      const pick = h("select", { class: "input input-sm", "aria-label": "Or choose a sentence from the excerpt" },
        h("option", { value: "" }, "…or choose a sentence from the list"), sentences.map((x, i) => h("option", { value: String(i) }, x.length > 90 ? x.slice(0, 88) + "…" : x)));
      const usePick = h("button", { class: "btn btn-sm", type: "button", onClick: () => { if (pick.value === "") { msg.textContent = "Choose a sentence from the list first."; pick.focus(); return; } saveQuote(sentences[Number(pick.value)]); } }, "Use this sentence");
      const remove = p.quote_by === "you" && current ? h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => put(current, undefined, "Your sentence was removed.", { quote: "" }) }, "Remove my sentence") : null;
      // 0.12: one way at first (select, then the button); the list of sentences (for the keyboard) opens on demand
      const list = h("span", { class: "mark-list", hidden: true }, pick, usePick);
      const listBtn = h("button", { class: "link-btn judge-list", type: "button", "aria-expanded": "false", onMousedown: (e) => e.preventDefault(), onClick: () => { list.hidden = !list.hidden; listBtn.setAttribute("aria-expanded", list.hidden ? "false" : "true"); if (!list.hidden) pick.focus(); } }, "or pick from a list");
      useSel.title = `Another sentence than the one highlighted: select it in the excerpt, then press this.${current ? "" : " It is saved with the judgement you choose."}`;
      useSel.className = "btn btn-sm judge-tool";
      return h("div", { class: "mark-sentence" },
        h("div", { class: "row" }, h("span", { class: "judge-caption" }, "Quote another sentence:"), useSel, listBtn, list, remove),
        msg);
    }
    row.append(judgeBtn, state);
    if (extras.buttons && extras.buttons.length) row.append(h("span", { class: "spacer" }), ...extras.buttons);
    wrap.appendChild(row);
    wrap.append(judgePanel, ...(extras.panels || []));
    return wrap;
  }

  function moreRow(part, r) {
    const k = (r.options && r.options.k) || App.settings().k || 8;
    const row = h("div", { class: "more-row" });
    const status = h("div", { class: "grow", style: { flexBasis: "100%" } });
    const none = part.more_available === false;
    const readN = (part.passages || []).length;
    const moreBtn = h("button", { class: "btn btn-sm", type: "button", disabled: none }, "Read more excerpts");
    const open = termsOpen.has(part.claim_id);
    const termsBtn = h("button", { class: "btn btn-sm", type: "button", "aria-expanded": open ? "true" : "false" }, "Search with other words");
    const termsInput = h("input", { class: "input input-sm", type: "text", placeholder: "e.g. telework, home office, car use", "aria-label": "Words to search for, separated by commas", value: termsText.get(part.claim_id) || "" });
    termsInput.addEventListener("input", () => termsText.set(part.claim_id, termsInput.value));
    const termsGo = h("button", { class: "btn btn-sm", type: "button" }, "Search and read");
    const lastRes = termsResult.get(part.claim_id);
    const termsBox = h("div", { class: "more-terms", hidden: !open }, termsInput, termsGo, h("span", { class: "muted small" }, "Separate words with commas."),
      lastRes ? h("p", { class: `terms-result ${lastRes.n ? "ok" : "none"}`, role: "status" }, icon(lastRes.n ? "circle-check" : "search-x", { size: 13 }), lastRes.text) : null);
    termsBtn.addEventListener("click", () => { termsBox.hidden = !termsBox.hidden; termsBtn.setAttribute("aria-expanded", termsBox.hidden ? "false" : "true"); if (termsBox.hidden) termsOpen.delete(part.claim_id); else { termsOpen.add(part.claim_id); termsInput.focus(); } });
    const run = async (terms) => {
      moreBtn.disabled = termsGo.disabled = true;
      const before = Math.max(0, ...(part.rounds_info || []).map((x) => x.round));
      try {
        const body = { k };
        if (terms && terms.length) body.terms = terms;
        const res = await api("POST", `/api/projects/${P(project)}/claims/${P(part.claim_id)}/more`, body);
        const panel = new ProgressPanel({ title: "Looking for more evidence" });
        replace(status, panel.el);
        const w = watchJob(res.job.id, (job) => panel.update(job));
        watchers.push(w);
        const job = await w.promise;
        if (job.state === "done") {
          const n = (job.result && job.result.passages) || 0;
          const y = window.scrollY;
          const fresh = await api("GET", `/api/projects/${P(project)}/hypotheses/${P(hypId)}?threshold=${threshold}`);
          const fp = (fresh.parts || []).find((x) => x.claim_id === part.claim_id) || {};
          const round = before + 1;
          const newOnes = (fp.passages || []).filter((x) => x.round === round);
          const aboutN = newOnes.filter(about).length;
          whatsNew = { n, about: aboutN, claim_id: part.claim_id, round, terms };
          if (n) { newRound.set(part.claim_id, round); if (aboutN === 0) openFolds.add(`rest:${part.claim_id}`); }
          if (!n && terms && terms.length) triedTerms.set(part.claim_id, [...(triedTerms.get(part.claim_id) || []), ...terms]);
          if (terms && terms.length) termsResult.set(part.claim_id, { n, text: n ? `${n} more ${n === 1 ? "excerpt" : "excerpts"} read for ${terms.join(", ")}: ${aboutN} of them about ${r.decomposed ? "this part" : "this hypothesis"}. They are marked “new” below.`
            : `Nothing new was found for ${terms.join(", ")}: no unread excerpt contains these words. Try other words, or words that appear in your documents.` });
          if (n) termsOpen.delete(part.claim_id);
          toast(n ? `${n} more ${n === 1 ? "excerpt" : "excerpts"} read. See “Just now” in the answer box.` : "Nothing new was found for these words.", n ? "ok" : "warn", { small: true, ttl: 4000 });
          current = fresh; draw(fresh);
          window.scrollTo(0, y);
        } else if (job.state === "error") showError({ message: job.error, kind: job.error_kind });
        else replace(status);
      } catch (e) { showError(e); }
      moreBtn.disabled = termsGo.disabled = false;
    };
    moreBtn.addEventListener("click", () => run());
    termsGo.addEventListener("click", () => { const t = termsInput.value.split(",").map((x) => x.trim()).filter(Boolean); if (!t.length) { termsInput.focus(); return; } run(t); });
    termsInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); termsGo.click(); } });
    const totalEx = r.passages_in_project;
    // 0.12: the two buttons side by side, one line under them
    moreBtn.title = `The AI reads up to ${k} more excerpts that match the same words.`;   // 0.12: "Look for more evidence"
    termsBtn.title = "Type words your documents might use; the AI reads the excerpts that contain them.";
    row.append(...[
      none ? h("p", { class: "more-line more-first" }, totalEx && readN >= totalEx ? "Every excerpt in your documents has been read." : `All ${readN} excerpts that share a word with this ${r.decomposed ? "part" : "hypothesis"} have been read.`) : null,
      h("div", { class: "more-btns" }, none ? null : moreBtn, termsBtn),
      termsBox, status].filter(Boolean));   // Element.append(null) would write "null"
    return row;
  }

  function noteCard(r) {
    const ta = h("textarea", { class: "textarea", id: "note", placeholder: "What to check by hand, which document to trust…" });
    ta.value = r.note || "";
    const state = h("span", { class: "note-saved", "aria-live": "polite" }, r.note ? "Saved" : "");
    const save = debounce(async () => {
      try { await api("PUT", `/api/projects/${P(project)}/hypotheses/${P(hypId)}/note`, { note: ta.value }); state.textContent = "Saved"; if (current) current.note = ta.value; }
      catch (e) { state.textContent = "Not saved"; showError(e); }
    }, 600);
    ta.addEventListener("input", () => { state.textContent = "Saving…"; save(); });
    return h("section", { class: "card note-card", "aria-label": "Your notes" },
      h("div", { class: "note-head" }, h("label", { for: "note" }, h("strong", {}, "Your notes")), state), ta);
  }

  // ------------------------------------------------------------------------------------------
  // 0.12: the page's technical details (the strictness slider for this page, how the check was made, CSV and JSON),
  // in the last row with Delete, also while a check waits
  function techCard(r, parts) {
    const o = r.options || {};
    const qs = `?threshold=${threshold}`;
    const input = h("input", { type: "range", min: 0.3, max: 0.95, step: 0.05, value: threshold, id: "thr", "aria-describedby": "thr-help" });
    const out = h("output", { for: "thr", class: "nowrap" }, `${strictness(threshold)} (${Math.round(threshold * 100)}%)`);
    input.addEventListener("input", () => { out.textContent = `${strictness(input.valueAsNumber)} (${Math.round(input.valueAsNumber * 100)}%)`; });
    input.addEventListener("change", () => setThreshold(Number(input.value)));
    // how the excerpts were found, part by part: what was read (and by whom), each search and the AI's note on it
    const found = parts.filter((part) => (part.rounds_info || []).length || triedTerms.get(part.claim_id)).map((part) => {
      const ps = part.passages || [];
      return h("div", { class: "found-part" },
        parts.length > 1 ? h("p", { class: "found-claim" }, `Part ${part.part}: `, h("span", { class: "serif" }, part.claim)) : null,
        h("p", { class: "rounds-read" }, readSentence(ps, new Set(ps.map((x) => x.doc_id)).size, r.documents_in_project), oneReader && READ_BY[oneReader] ? `; ${READ_BY[oneReader][1].toLowerCase()}` : "", "."),
        roundsBlock(part, r));
    });
    return fold("tech", { class: "fold tech-card" }, h("summary", {}, "Technical details"),
      h("div", { class: "card card-plain details-body" },
        found.length ? h("div", { class: "found" }, h("h3", { class: "found-head" }, "How the excerpts were found"), found) : null,
        r.status === "waiting" ? null : h("div", { class: "threshold-ctl" },
          h("label", { for: "thr" }, "See this result at another strictness"), h("span", { class: "muted small" }, "relaxed"), input, h("span", { class: "muted small" }, "strict"), out,
          h("span", { class: "muted small", id: "thr-help" }, "Only this page changes. To change it for every result: ", h("a", { href: "#/settings/basics" }, "Settings"), ". A stricter setting counts fewer judgements, but can still count wrong ones.")),
        r.status_any && r.status_any !== r.status ? h("p", { class: "small", style: { marginTop: "8px" } }, icon("info", { size: 13 }), " If every judgement counted, whatever the AI's certainty, the answer would be: ", statusBadge(r.status_any, { short: true })) : null,
        h("dl", { class: "kv-grid", style: { marginTop: "14px" } },
          r.status === "waiting" && !(r.model || o.model) ? null : h("div", { class: "kv" }, h("dt", {}, "AI model"), h("dd", {}, `${r.model || o.model || "unknown"}${o.backend ? ` (${o.backend})` : ""}`)),
          h("div", { class: "kv" }, h("dt", {}, "Search"), h("dd", {}, o.search === "keywords+meaning" ? `same words + search by meaning (${o.embed_model || ""})` : "same words only")),
          h("div", { class: "kv" }, h("dt", {}, "Excerpts per claim"), h("dd", {}, `${o.k ?? "?"}, at most ${o.per_doc ?? "?"} per document`)),
          h("div", { class: "kv" }, h("dt", {}, "Other words"), h("dd", {}, o.expand ? "yes, suggested by the AI" : "no")),
          h("div", { class: "kv" }, h("dt", {}, "Checked in parts"), h("dd", {}, r.decomposed ? `yes, ${parts.length}` : "no")),
          o.prepared ? h("div", { class: "kv" }, h("dt", {}, "Looked at before checking"), h("dd", {}, [o.prepared.parts ? `parts ${o.prepared.edited_parts ? "changed by you" : "as the AI proposed"}` : null, o.prepared.terms ? `search words ${o.prepared.edited_terms ? "changed by you" : "as the AI proposed"}` : null].filter(Boolean).join(", ") || "yes")) : null,
          o.second_pass ? h("div", { class: "kv" }, h("dt", {}, "Sorted again by wording"), h("dd", {}, "yes")) : null,
          o.doc_ids && o.doc_ids.length ? h("div", { class: "kv" }, h("dt", {}, "Searched in"), h("dd", {}, `${o.doc_ids.length} chosen documents`)) : null,
          h("div", { class: "kv" }, h("dt", {}, "Result id"), h("dd", { class: "mono" }, r.hyp_id))),
        null));
  }

  function downloadsCard(r, parts) {
    const qs = `?threshold=${threshold}`;
    // 0.12: one row per download, the button first and one line on what it holds
    const row = (btn, what) => { if (!btn.title) btn.title = what; return h("div", { class: "dl-row" }, btn, h("span", { class: "dl-what" }, what)); };
    return h("section", { class: "card downloads", "aria-label": "Downloads" },
      h("div", { class: "card-head" }, h("h2", {}, "Download")),
      h("div", { class: "dl-rows" },
        row(h("button", { class: "link-btn dl-link", type: "button", onClick: () => download(`/api/projects/${P(project)}/hypotheses/${P(hypId)}/export.xlsx${qs}`).catch(showError) }, "Excel (.xlsx)"),
          "The answer, every excerpt and judgement, your notes."),
        row(h("button", { class: "link-btn dl-link", type: "button", title: "Readable in any PDF reader: green supports, amber partly, red contradicts, with a note on each",
          onClick: () => download(`/api/projects/${P(project)}/hypotheses/${P(hypId)}/annotated.zip${qs}`).catch(showError) }, "Highlighted documents (.zip)"),
          "Each document, its quotes highlighted."),
        row(projectZipLink(project, { text: "Whole project (.zip)", noIcon: true, cls: "link-btn dl-link" }),
          "Everything, to share or move."),
        h("div", { class: "dl-row" }, h("span", { class: "dl-what dl-wide" }, h("button", { class: "link-btn", type: "button", onClick: () => download(`/api/projects/${P(project)}/hypotheses/${P(hypId)}/export.csv${qs}`).catch(showError) }, "CSV"), " · ",
          h("button", { class: "link-btn", type: "button", onClick: () => download(`/api/projects/${P(project)}/hypotheses/${P(hypId)}/export.json${qs}`).catch(showError) }, "JSON"), " (for programmers)"))));
  }

  async function deleteHyp(r) {
    const ok = await confirmDialog({ title: "Delete this result?", message: h("div", {}, h("p", {}, "The hypothesis, the judgements and your notes are removed from the results. The documents stay."), h("p", { class: "serif" }, r.text)), confirmText: "Delete" });
    if (!ok) return;
    try { await api("DELETE", `/api/projects/${P(project)}/hypotheses/${P(hypId)}`); toast("Result deleted.", "ok"); navigate("#/history"); }
    catch (e) { showError(e); }
  }

  await load();
  adoptRunningJobs();
  return () => { clearTimeout(waitTimer); watchers.forEach((w) => w.stop()); };
}

// "Download the whole project (.zip)": a plain link (the browser saves it), with a note that the download started.
export function projectZipLink(project, opts = {}) {
  const a = h("a", { class: opts.cls || "btn btn-sm", href: `/api/projects/${P(project)}/export.zip?token=${encodeURIComponent(TOKEN)}`, download: "", title: "One zip with the database, the settings, the codebooks and the original files of this project" },
    opts.noIcon ? null : icon("download", { size: 13 }), opts.text || "Download the whole project (.zip)");
  a.addEventListener("click", () => toast(`Your download starts: “ENLENS project - ${project} - ${new Date().toISOString().slice(0, 10)}.zip”. It holds the documents, results, judgements and notes of this project; a large project takes a moment.`, "ok", { ttl: 7000 }));
  return a;
}

// A block (paragraph or page) of a document, with a global character span highlighted where it overlaps. The
// block's heading lines (0.6: `headings`, offsets in its text) are shown bold.
export function blockNode(b, span, tag = "p", cls = "") {
  const text = b.text || "";
  const breaks = (b.headings || []).map((x) => ({ at: x.at, end: x.end, kind: "heading" }));
  if (!span) return passageNode(text, null, null, tag, cls, breaks);
  const s = Math.max(0, span.start - b.start), e = Math.min(text.length, span.end - b.start);
  if (e <= 0 || s >= text.length || e <= s) return passageNode(text, null, null, tag, cls, breaks);
  return passageNode(text, s, e, tag, cls, breaks);
}

// What the blocks around one block are called: "paragraphs" (also within a page), "pages", or nothing to say.
export function blockUnit(b) {
  const label = (b && b.label) || "";
  if (/paragraph/i.test(label)) return "paragraphs";
  if (/^page/i.test(label)) return "pages";
  return "parts";
}
