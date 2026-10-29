// The result of one hypothesis, told as one consistent story from one fresh copy of the data: the answer, who says
// what (documents, from `balance`), then the evidence as verified quotes. Every count on the page is computed from
// the same `passages` the cards are drawn from, so sections and numbers always agree. A person's judgement
// replaces the AI's; it is protected (no silent overwrite) and every save can be undone.
import { App, api, h, icon, replace, clear, append, toast, showError, fmt, statusBadge, gradeBadge, codeChip, passageNode, popNote, gradeWords, navigate, watchJob, P, TOKEN, TERMINAL, confirmDialog, dialog, download, debounce, store, GRADE_TEXT, STATUS_SHORT, strictness, docsCountSentence, partsSentence, queueNotice } from "../lib.js";
import { ProgressPanel, MiniJob } from "./progress.js";

const USER_VERDICTS = [["supports", "Supports"], ["partially_supports", "Partly supports"], ["refutes", "Contradicts"], ["not_relevant", "Not about this"]];
const about = (p) => p.verdict !== null && p.verdict !== undefined;   // the judgement that counts says it is about the hypothesis
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
// quote (opens at it), pdfHint (say where a PDF opens and where the quote is in the app).
export function originalLink(project, docId, page, kind, opts = {}) {
  const holder = h("span", { class: "orig-link" + (opts.class ? " " + opts.class : "") });
  const fill = (info) => {
    if (!info) return;
    const k = info.kind || kind;
    if (info.available) {
      const isPdf = k === "pdf";
      const where = isPdf ? (page ? `, at page ${page}` : "") : opts.quote ? ", at the quote" : "";
      const link = h("a", { class: opts.button ? "btn btn-sm btn-ghost" : "it", href: originalHref(project, docId, { kind: k, page, quote: opts.quote }), target: "_blank", rel: "noopener",
        title: `Opens ${info.name || "the original file"} in a new tab${where}${isPdf && opts.quote ? ". The quote itself is highlighted here in the app, under “Show more of the document”." : ""}` },
        icon("external-link", { size: 13 }), opts.text || (isPdf && page && !opts.pdfHint ? `Open the original (page ${page})` : "Open the original"));
      replace(holder, link, isPdf && opts.pdfHint ? h("span", { class: "muted small orig-hint" }, page ? `opens at page ${page}; the quote is highlighted under “Show more”` : "the quote is highlighted under “Show more”") : null);
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
  const blocksCache = new Map();   // doc_id -> blocks view of the document
  let current = null;              // the result as last fetched
  let returnTo = query.card || null;   // passage to scroll to when coming back from the document view
  const termsText = new Map();     // claim_id -> words typed in "search with other words" (kept across re-draws)
  const termsResult = new Map();   // claim_id -> inline result of the last search with other words
  const running = new Map();       // job id -> {kind, mini} of a follow-up job of this result (read again, new documents, second model)
  let followNote = null;           // text shown in the follow-ups card after one of its jobs ended
  const pendingQuote = new Map();  // "claim|passage" -> {text, start, end}: a sentence marked before a judgement was chosen (not saved yet)
  const visitedNext = new Set();   // cards "Next to review" went to in this session, so it moves on and wraps around
  let disagreeAt = -1;             // where "Next disagreement" is in its cycle
  let changingSecond = false;      // the second-model select is open to change the choice
  let evidenceView = store("evidenceView") === "table" ? "table" : "cards";   // cards or a compact table, remembered per browser
  const pendingKey = (p, part) => `${part.claim_id}|${p.passage_id}`;
  const redraw = () => draw(current);   // re-draw from the data as last fetched (for places where `current` is shadowed)
  let waitTimer = null;            // 0.8: a check waiting for Claude Code is looked at again every few seconds

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
    const docsRead = new Set(allPassages.map((p) => p.doc_id)).size;
    const total = r.documents_in_project;

    box.appendChild(h("header", { class: "page-head" },
      h("div", { class: "page-head-main" },
        h("p", { class: "eyebrow" }, h("a", { href: "#/history", class: "it" }, icon("arrow-left", { size: 12 }), "All results")),
        h("h1", { id: "page-title", tabindex: "-1", class: "result-hyp" }, r.text),
        r.code ? h("div", { style: { margin: "0 0 8px" } }, codeChip(r.framework, r.code, r.code_description, r.code_label)) : null,
        h("div", { class: "result-meta" },
          h("span", { class: "it" }, icon("clock", { size: 13 }), `Checked ${fmt.date(r.created_at)}`),
          r.batch_id ? [h("span", { class: "sep" }, "·"), h("a", { href: `#/history?batch=${encodeURIComponent(r.batch_id)}` }, "checked as part of a set")] : null),
        h("p", { class: "result-read" }, readSentence(allPassages, docsRead, total, single ? "this hypothesis" : "its parts")))));

    if (r.status === "waiting") {
      // 0.8: a check by queue: Claude Code has not read (all of) it yet; the page looks again every few seconds
      box.appendChild(h("section", { class: "card", "aria-label": "Waiting for Claude Code" },
        queueNotice({ text: "This check waits in the queue for Claude Code", command: r.queue_command,
          estimate: "The answer appears here as soon as Claude Code has read the excerpts" })));
      clearTimeout(waitTimer);
      waitTimer = setTimeout(() => load().catch(() => {}), 5000);
    }
    box.appendChild(answerCard(r, parts, single, allPassages));
    // documents added since the check, or a second model's disagreements, are worth seeing before the evidence;
    // otherwise the follow-ups sit below it
    // the follow-ups (documents added since, second model) always sit right under the answer, so they are easy to find
    box.appendChild(followUpsCard(r, allPassages));
    if (single) {
      const who = whoSaysWhat(parts[0]);
      if (who) box.appendChild(who);
    }
    if (allPassages.length) box.appendChild(viewToggle(allPassages.length));
    if (evidenceView === "table" && allPassages.length) box.appendChild(excerptTable(parts, single));
    for (const part of parts) box.appendChild(partView(part, r, single));
    box.appendChild(noteCard(r));
    box.appendChild(downloadsCard(r, parts));

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
  function answerCard(r, parts, single, allPassages) {
    const st = r.status;
    const next = App.statusNext(st);
    const bal = r.balance || {};
    const judged = allPassages.filter(about).length;
    const card = h("section", { class: `card card-verdict v-${st} answer`, "aria-label": "Answer" });
    const countedEx = allPassages.filter((p) => p.counted).length;
    let sentence = null;
    if (r.decomposed) sentence = partsSentence(parts, st);
    else if (st === "uncertain") sentence = judged === 1 ? `1 excerpt was judged, but the AI was not sure enough about it to count it at your strictness (${strictness(threshold)}).`
      : `${judged} excerpts were judged, but the AI was not sure enough about any of them to count them at your strictness (${strictness(threshold)}).`;
    else if (bal.docs_counted) sentence = oneDocSentence(bal, r.who) || docsCountSentence(bal);
    const titles = [...new Map((r.who || []).map((w) => [w.doc_id, w.title || "untitled"])).values()];
    const named = titles.length ? titles.slice(0, 3).join("; ") + (titles.length > 3 ? ` and ${titles.length - 3} more` : "") : "";
    const base = bal.docs_counted ? h("p", { class: "answer-base" }, icon("book-open", { size: 13 }), h("span", {}, `Rests on ${bal.docs_counted} ${bal.docs_counted === 1 ? "document" : "documents"}`, named ? [": ", h("span", { class: "serif" }, named)] : null, ` (${countedEx} ${countedEx === 1 ? "excerpt" : "excerpts"} that ${countedEx === 1 ? "counts" : "count"}).`,
      bal.docs_counted === 1 ? h("strong", {}, " This answer rests on a single document.") : null)) : null;

    // review figures, all from the same excerpts
    const read = r.excerpts_read ?? allPassages.length;
    const reviewed = allPassages.filter((p) => p.reviewed);
    const changed = reviewed.filter((p) => p.changed).length;
    const agreed = reviewed.length - changed;
    const toReview = r.to_review || 0;
    const countedAll = allPassages.filter((p) => p.counted);
    const countedUnchecked = countedAll.filter((p) => !p.reviewed).length;   // AI judgements that decide the answer and are not checked
    // the same order "Next to review" uses, counted from the same excerpts the cards are drawn from
    const disagreeNew = allPassages.filter((p) => !p.reviewed && p.second && !p.second.agrees).length;
    const scopeNew = allPassages.filter((p) => !p.reviewed && p.scope_note).length;
    const nextBtn = toReview ? h("button", { class: "btn btn-sm", type: "button", onClick: nextToReview }, icon("arrow-right", { size: 13 }), disagreeNew ? "Next to review (models disagree first)" : scopeNew ? "Next to review (“about another group” first)" : countedUnchecked ? "Next to review (counts first)" : "Next to review") : null;
    const disagreeAll = allPassages.filter((p) => p.second && !p.second.agrees).length;
    const disCounter = h("span", { class: "muted small", "aria-live": "polite" }, disagreeAt >= 0 ? `Disagreement ${Math.min(disagreeAt + 1, disagreeAll)} of ${disagreeAll}` : `${disagreeAll} ${disagreeAll === 1 ? "excerpt" : "excerpts"} where the AI models disagree`);
    const disBtn = disagreeAll ? h("span", { class: "it dis-nav" }, h("button", { class: "btn btn-sm", type: "button", onClick: () => nextDisagreement(disCounter) }, icon("arrows-opposed", { size: 13 }), "Next disagreement"), disCounter) : null;
    const review = h("div", { class: "answer-review" }, icon("note", { size: 13 }),
      h("div", {},
        h("span", {}, h("strong", {}, "Reviewed by you: "), `${reviewed.length} of the ${read} excerpts read`, changed ? ` (you changed ${changed})` : "", ". ",
          reviewed.length ? [`You agreed with the AI on ${agreed} of the ${reviewed.length} you reviewed `, h("a", { href: "#/settings/calibration", title: "How often you agreed with the AI, by its certainty, over the whole project, and what strictness that suggests" }, "(how often you agree, by the AI's certainty)"), ". "] : ""),
        toReview ? h("span", { class: "review-caution" }, `${toReview} ${toReview === 1 ? "excerpt is" : "excerpts are"} not reviewed by you yet${countedUnchecked ? ` (${countedUnchecked} of them ${countedUnchecked === 1 ? "counts" : "count"} in this answer)` : r.to_review_relevant ? ` (${r.to_review_relevant} of them ${r.to_review_relevant === 1 ? "carries" : "carry"} an AI judgement for or against)` : ""}. `, nextBtn) : null,
        disBtn ? h("span", { class: "review-dis" }, disBtn) : null));
    // provisional until a person has checked; solid once every counted excerpt (or everything) is reviewed
    const provisional = reviewed.length === 0;
    const complete = toReview === 0 || (reviewed.length > 0 && countedUnchecked === 0 && countedAll.length > 0);
    const basis = provisional ? ["AI only, not reviewed", "basis-ai"] : complete ? ["Reviewed by you", "basis-you"] : ["Partly reviewed by you", "basis-part"];
    const ownOnly = countedAll.length > 0 && countedAll.every((p) => p.user_verdict);
    const aiBelow = ownOnly && countedAll.every((p) => p.confidence === null || p.confidence === undefined || p.confidence < threshold);
    const decides = countedUnchecked > 0 && countedUnchecked <= 2 && !ownOnly ? (countedUnchecked === 1 ? "One unchecked AI judgement decides this answer." : "Two unchecked AI judgements decide this answer.") : null;
    let basisLine = null;
    if (decides) basisLine = provisional ? "" : "Check it first: it can change the answer.";
    else if (provisional) basisLine = countedAll.length ? `Based on ${countedAll.length} AI judgements you haven't checked.` : `Based on the AI's reading of ${read} ${read === 1 ? "excerpt" : "excerpts"}, none checked by you yet.`;
    else if (ownOnly && toReview > 0) basisLine = `The answer rests on your own judgements only${aiBelow ? " (the AI's were below your strictness)" : ""}.`;
    else if (countedUnchecked) basisLine = `${countedUnchecked} of the judgements that count ${countedUnchecked === 1 ? "is" : "are"} not checked by you yet.`;
    const allRead = parts.length && parts.every((p) => p.more_available === false);
    let nextText = allRead && /more evidence|other words/i.test(next || "") ? "Every matching excerpt has been read; read the excerpts and judge them yourself." : next;
    if (toReview === 0 && allPassages.length) nextText = "You have reviewed every excerpt read. The answer now rests on your judgements. Download it for Excel, or add notes.";

    card.appendChild(h("div", { class: "answer-main" },
      h("div", { class: "answer-status" },
        h("div", { class: "answer-status-main" },
          provisional ? h("span", { class: "status-prefix" }, "The AI's first reading:") : null,
          statusBadge(st, { size: "lg", text: r.status_text || App.statusText(st), class: provisional ? "badge-provisional" : "" })),
        h("span", { class: `basis ${basis[1]}`, title: "Who judged the excerpts this answer rests on" }, icon(basis[1] === "basis-you" ? "circle-check" : basis[1] === "basis-part" ? "circle-half" : "cpu", { size: 13 }), basis[0])),
      basisLine || decides ? h("p", { class: "answer-basis-line" + (decides ? " answer-decides" : "") }, decides ? [h("strong", {}, decides), " "] : null, basisLine || null) : null,
      sentence ? h("p", { class: "answer-sentence" }, sentence) : null,
      r.decomposed ? h("ol", { class: "answer-part-list" }, parts.map((p) => h("li", { class: p.status === "supported" ? "ok" : "notok" },
        h("a", { href: `#part-${p.part}`, class: "serif", onClick: jumpTo(`part-${p.part}`) }, p.claim), " ", statusBadge(p.status, { short: true })))) : null,
      r.decomposed ? null : h("p", { class: sentence ? "answer-help" : "answer-sentence" }, App.statusHelp(st)),
      base,
      bal.excerpts_uncounted && st !== "uncertain" ? h("p", { class: "answer-help" }, `${bal.excerpts_uncounted} more ${bal.excerpts_uncounted === 1 ? "judgement was" : "judgements were"} too uncertain to count; ${bal.excerpts_uncounted === 1 ? "it is" : "they are"} shown below, marked as not counted.`) : null,
      review,
      whatsNew ? h("p", { class: "whats-new" }, icon("sparkles", { size: 13 }), h("span", {}, h("strong", {}, "Just now: "), whatsNewText(whatsNew, single))) : null,
      nextText ? h("p", { class: "answer-next" }, icon("arrow-right", { size: 14 }), h("span", {}, h("strong", {}, "What to do next: "), nextText)) : null,
      r.incomplete ? h("div", { class: "notice notice-warn", style: { marginTop: "10px" } }, icon("alert-triangle"), h("p", {}, "One part of the check did not finish, so this answer is incomplete.")) : null,
      strictnessLine()));
    if (lastRun) {
      card.appendChild(h("div", { class: "run-summary" }, icon("circle-check", { size: 15 }), h("div", {}, h("strong", {}, `Done in ${fmt.secs(lastRun.seconds)}`), lastRun.summary ? h("span", { class: "muted" }, ` · ${lastRun.summary}`) : null)));
      lastRun = null;
    }
    return card;
  }

  function whatsNewText(w, single) {
    const what = single ? "this hypothesis" : "this part";
    if (!w.n) return w.terms && w.terms.length ? `nothing new was found for ${w.terms.join(", ")}: no unread excerpt contains these words.` : "nothing further matched, so no new excerpts were read.";
    const where = w.about === 0 ? ` (they are in the “not about ${what}” list, marked new)` : w.about === w.n ? " (marked new in the evidence list)" : ` (${w.about} in the evidence list, ${w.n - w.about} in the “not about” list, all marked new)`;
    return `${w.n} more ${w.n === 1 ? "excerpt" : "excerpts"} read${w.terms && w.terms.length ? ` for ${w.terms.join(", ")}` : ""}, ${w.about} of them about ${what}${where}.`;
  }

  function oneDocSentence(bal, who) {
    if (!(bal.docs_counted === 1 && bal.docs_both)) return null;
    const w = (who || [])[0];
    if (!w) return null;
    const kinds = [bal.docs_supporting && "supporting", bal.docs_partly && "partly supporting", bal.docs_refuting && "contradicting"].filter(Boolean);
    const list = kinds.length > 1 ? kinds.slice(0, -1).join(", ") + " and " + kinds[kinds.length - 1] : kinds[0] || "";
    return h("span", {}, "One document, ", h("span", { class: "serif" }, `“${w.title || "untitled"}”`), `, has excerpts on both sides: ${list} ones. No other document counts.`);
  }

  // "Next to review": moves on from the card it went to last, in this order: excerpts where the two AI models
  // disagree, then those the AI flagged as about another group, then the ones that count in the answer, then the
  // rest; cards with only a comment ("come back later") come last. It wraps around.
  function reviewOrder() {
    const all = [...box.querySelectorAll(".ev")].filter((e) => e.dataset.reviewed === "0");
    const key = (e) => `${e.dataset.claim}|${e.dataset.passage}`;
    const groups = [all.filter((e) => e.dataset.comment === "0" && e.dataset.disagree === "1"), all.filter((e) => e.dataset.comment === "0" && e.dataset.scope === "1"),
      all.filter((e) => e.dataset.comment === "0" && e.dataset.counted === "1"), all.filter((e) => e.dataset.comment === "0"), all.filter((e) => e.dataset.comment === "1")];
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
  function nextToReview() {
    const { list, key } = reviewOrder();
    if (!list.length) { toast("Everything is reviewed.", "ok", { small: true, ttl: 2500 }); return; }
    let el = list.find((e) => !visitedNext.has(key(e)));
    if (!el) { visitedNext.clear(); el = list[0]; toast("Back to the first excerpt still to review: every one was shown once.", "info", { small: true, ttl: 3000 }); }
    visitedNext.add(key(el));
    goToCard(el);
  }
  // "Next disagreement": every excerpt where the two AI models disagree, reviewed or not, round and round.
  function nextDisagreement(counter) {
    const all = [...box.querySelectorAll(".ev")].filter((e) => e.dataset.disagree === "1");
    if (!all.length) return;
    disagreeAt = (disagreeAt + 1) % all.length;
    if (counter) counter.textContent = `Disagreement ${disagreeAt + 1} of ${all.length}`;
    goToCard(all[disagreeAt]);
  }

  const jumpTo = (id) => (e) => { e.preventDefault(); const t = document.getElementById(id); if (t) { t.scrollIntoView({ behavior: "smooth", block: "start" }); if (t.focus) t.focus({ preventScroll: true }); } };

  // ------------------------------------------------------------------------------------------
  // Keeping the result up to date: documents added since the check, and a second AI model's reading.
  function followUpsCard(r, allPassages) {
    const added = r.docs_added_since || [];
    const matching = added.filter((d) => d.matching);
    // 0.8: on Claude (Claude Code, or the Claude API with a model per task) the auditor gives the second opinion
    const st = App.settings();
    const auditor = ["claude_code", "anthropic"].includes(st.backend) && st.routing !== false ? `${st.use_fable ? "fable" : "opus"} (the auditor)` : null;
    const secondSet = auditor || (st.second_model || "").trim();
    const mainModel = auditor ? "" : (st.ollama_model || st.openai_model || "").trim();
    const secondUsable = secondSet && secondSet !== mainModel;
    const secondRead = r.second_read || 0;
    const read = r.excerpts_read ?? allPassages.length;
    const disagree = r.disagreements || 0;
    const disagreeNew = r.disagreements_to_review || 0;
    const card = h("section", { class: "card followups", "aria-label": "Keep this result up to date" });
    card.appendChild(h("div", { class: "card-head" }, h("h2", {}, "Keep this result up to date"), h("span", { class: "muted small" }, "Both keep your reviews and notes.")));
    const rows = h("div", { class: "followup-rows" });
    card.appendChild(rows);
    const busy = [...running.values()];
    const jobsBox = h("div", { class: "stack", style: { gap: "6px" } }, busy.filter((x) => !x.passage_id).map((x) => x.mini.el));
    const noteEl = followNote ? h("p", { class: "whats-new", role: "status" }, icon("sparkles", { size: 13 }), h("span", {}, h("strong", {}, "Just now: "), followNote)) : null;

    // --- documents added since
    const docsRow = h("div", { class: "followup-row" });
    const titles = (xs) => xs.map((d) => d.title || "untitled");
    if (added.length) {
      const n = added.length, m = matching.length;
      const sentence = `${n} ${n === 1 ? "document was" : "documents were"} added since this check; ${m === 0 ? "none has" : m === 1 ? "1 has" : `${m} have`} matching excerpts.`;
      const list = h("ul", { class: "added-list" }, added.map((d) => h("li", {}, h("a", { href: `#/doc/${encodeURIComponent(d.doc_id)}?from=${encodeURIComponent(hypId)}`, class: "serif" }, d.title || "untitled"), h("span", { class: "muted small" }, d.matching ? " · has matching excerpts" : " · nothing in it matches"))));
      const btn = h("button", { class: "btn btn-sm " + (m ? "btn-primary" : ""), type: "button", disabled: busy.some((x) => x.kind === "read-new") }, icon(m ? "book-open" : "check", { size: 13 }), m ? (m === 1 ? "Read it" : "Read them") : "Mark as looked at");
      btn.addEventListener("click", () => runReadNew(btn));
      append(docsRow, [h("div", { class: "followup-text" }, icon("upload", { size: 15 }),
        h("div", {}, h("p", { class: "followup-lead" }, h("strong", {}, sentence)), list,
          h("p", { class: "muted small" }, m ? `The AI reads only ${m === 1 ? "that document" : "those documents"}, as a further search for ${r.decomposed ? "every part" : "this hypothesis"}; the check is not run again, so your reviews are kept. ${m === n ? "" : "The others are marked as looked at."}` : "Nothing in them shares a word with the hypothesis. Marking them as looked at stops this notice; the check is not run again."))),
        h("div", { class: "followup-action" }, btn)]);
    } else {
      append(docsRow, [h("div", { class: "followup-text muted" }, icon("upload", { size: 15 }), h("div", {}, h("p", { class: "followup-lead" }, "No documents were added since this check."), h("p", { class: "muted small" }, "When you add documents later, you can have the AI read them for this result without running the check again.")))]);
    }
    rows.appendChild(docsRow);

    // --- second AI model
    const secRow = h("div", { class: "followup-row" });
    let secLead, secHelp = null, secBtn = null;
    const allRead = secondRead >= read && read > 0;
    if (secondRead) {
      secLead = `A second AI model read ${secondRead === read ? `all ${read}` : `${secondRead} of the ${read}`} excerpts${disagree ? ` and disagrees with the main model on ${disagree}${disagreeNew ? ` (${disagreeNew} not reviewed by you yet)` : ""}.` : " and agrees with the main model on every one."}`;
      secHelp = disagree ? "“Next to review” in the answer goes to the excerpts where the models disagree first. The second model's judgements never change the answer; yours do." : "Its judgements are shown on each excerpt and never change the answer.";
    } else {
      secLead = "Ask a second AI model to read the same excerpts.";
      secHelp = "A second opinion from another model: where the two disagree, it is worth reading the excerpt yourself. Its judgements are shown beside the main model's and never change the answer.";
    }
    if (secondUsable && !changingSecond) {
      secBtn = h("button", { class: "btn btn-sm", type: "button", disabled: allRead || busy.some((x) => x.kind === "second-opinion") }, icon("cpu", { size: 13 }), secondRead ? (allRead ? "Every excerpt has a second reading" : "Let it read the rest") : "Ask a second AI model");
      secBtn.addEventListener("click", () => runSecondOpinion(secBtn));
    }
    const chosenLine = secondUsable && !changingSecond ? h("p", { class: "small second-chosen" }, h("span", { class: "muted" }, "Second AI model: "), h("strong", {}, secondSet),
      auditor ? h("span", { class: "muted" }, " · it can be another model than the one that judged first when Fable is switched on (Settings)") : [" · ",
        h("button", { class: "link-btn", type: "button", onClick: () => { changingSecond = true; draw(current); } }, "change"), h("span", { class: "muted" }, sizeHint(secondSet))]) : null;
    append(secRow, [h("div", { class: "followup-text" }, icon("cpu", { size: 15 }),
      h("div", {}, h("p", { class: "followup-lead" }, h("strong", {}, secLead)), h("p", { class: "muted small" }, secHelp),
        chosenLine,
        auditor ? null : secondUsable && !changingSecond ? h("p", { class: "muted small" }, ONE_MODEL_NOTE) : secondModelPicker(mainModel, secondUsable ? secondSet : "", busy.some((x) => x.kind === "second-opinion")))),
      secBtn ? h("div", { class: "followup-action" }, secBtn) : null]);
    rows.appendChild(secRow);
    if (noteEl) card.appendChild(noteEl);
    card.appendChild(jobsBox);
    return card;
  }

  // No second model yet: choose one right here, from the other chat models the server has (saved in Settings).
  // The model's size in plain words, from its name ("llama3.1:8b" -> 8 billion parameters).
  function sizeHint(name) {
    const m = /(\d+(?:\.\d+)?)\s*b\b/i.exec(name || "");
    return m ? ` (${m[1]}b: about ${m[1]} billion parameters; a larger model is usually better, but slower)` : "";
  }

  // Choose the second model and ask it, in one step: a select of the other chat models on the server and a button.
  // The choice is saved in Settings (second_model) when the button is pressed.
  function secondModelPicker(mainModel, currentChoice, busy) {
    const sel = h("select", { class: "select input-sm", "aria-label": "Second AI model", disabled: true }, h("option", { value: "" }, "Looking for other models…"));
    const ask = h("button", { class: "btn btn-sm btn-primary", type: "button", disabled: true }, icon("cpu", { size: 13 }), "Ask this model for a second opinion");
    const state = h("span", { class: "muted small", "aria-live": "polite" });
    const hint = h("p", { class: "muted small", style: { margin: "4px 0 0" } }, "The number before “b” in a model's name is its size, in billions of parameters: a larger model is usually better, but slower. ", ONE_MODEL_NOTE, " ", h("a", { href: "#/settings/second" }, "More in Settings"), ".");
    const box = h("div", { class: "second-pick" },
      h("p", { class: "muted small", style: { margin: "0 0 4px" } }, currentChoice ? "Choose another of the models on this computer:" : "No second AI model is chosen yet. Pick one of the other models on this computer:"),
      h("div", { class: "row", style: { gap: "6px 8px" } }, sel, ask, currentChoice ? h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => { changingSecond = false; draw(current); } }, "Keep it") : null, state),
      hint);
    api("GET", "/api/servers").then((r) => {
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

  // Watches a follow-up job of this result; `onDone(job)` runs when it finished well. The page reloads either way.
  function followJob(jobId, kind, title, onDone, extra = {}) {
    const mini = new MiniJob({ title });
    running.set(jobId, { kind, mini, ...extra });
    const w = watchJob(jobId, (job) => mini.update(job));
    watchers.push(w);
    w.promise.then(async (job) => {
      running.delete(jobId);
      if (job.state === "done") { try { await onDone(job); } catch (e) { showError(e); } }
      else if (job.state === "error") showError({ message: job.error, kind: job.error_kind });
      else if (job.state === "cancelled") toast("Stopped.", "info", { small: true, ttl: 2500 });
      await load();   // draw() keeps the scroll position, and the card the person acted on in place
    }).catch((e) => { running.delete(jobId); showError(e); });
    draw(current);
    return w;
  }

  async function runReadNew(btn) {
    btn.disabled = true;
    try {
      // no body: the endpoint takes none (and does not read one, so a body would spill into the next request)
      const res = await api("POST", `/api/projects/${P(project)}/hypotheses/${P(hypId)}/read-new`);
      const before = new Map((current.parts || []).map((p) => [p.claim_id, Math.max(0, ...(p.rounds_info || []).map((x) => x.round))]));
      const matching = (current.docs_added_since || []).filter((d) => d.matching).length;
      followJob(res.job.id, "read-new", matching ? "Reading the new documents" : "Marking the new documents as looked at", async (job) => {
        const me = ((job.result && job.result.hypotheses) || []).find((x) => x.hyp_id === hypId) || {};
        const n = me.passages || 0;
        const fresh = await api("GET", `/api/projects/${P(project)}/hypotheses/${P(hypId)}?threshold=${threshold}`);
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

  async function runSecondOpinion(btn) {
    btn.disabled = true;
    try {
      const res = await api("POST", `/api/projects/${P(project)}/second-opinion`, { hyp_ids: [hypId] });
      followJob(res.job.id, "second-opinion", "The second AI model is reading the excerpts", async (job) => {
        const fresh = await api("GET", `/api/projects/${P(project)}/hypotheses/${P(hypId)}?threshold=${threshold}`);
        const d = fresh.disagreements || 0;
        followNote = `The second AI model read ${fresh.second_read || 0} ${fresh.second_read === 1 ? "excerpt" : "excerpts"}${d ? ` and disagrees with the main model on ${d}: “Next to review” goes to ${d === 1 ? "it" : "those"} first.` : " and agrees with the main model on every one."}`;
        toast("The second AI model has read the excerpts.", "ok", { small: true, ttl: 4000 });
      });
    } catch (e) {
      if (e.status === 400) toast(e.message, "warn", { action: { href: "#/settings/second", text: "Choose a second model in Settings" } }); else showError(e);
      btn.disabled = false;
    }
  }

  // A follow-up job of this project started earlier (or on another page) and still running: show and follow it.
  async function adoptRunningJobs() {
    let jobs = [];
    try { jobs = (await api("GET", "/api/jobs")).jobs || []; } catch (_) { return; }
    const titles = { reread: "Reading one excerpt again", "read-new": "Reading the new documents", "second-opinion": "The second AI model is reading the excerpts" };
    for (const j of jobs) {
      if (j.project !== project || !titles[j.kind] || TERMINAL.has(j.state) || running.has(j.id)) continue;
      followJob(j.id, j.kind, titles[j.kind], async () => { followNote = j.kind === "reread" ? "The AI has read an excerpt again." : j.kind === "read-new" ? "The new documents were read." : "The second AI model has read the excerpts."; });
    }
  }

  function strictnessLine() {
    const pct = Math.round(threshold * 100);
    const temp = Math.abs(threshold - setting) > 1e-9;
    return h("p", { class: "strict-line", id: "strictness", tabindex: "-1" }, icon("sliders", { size: 13 }),
      h("span", {}, h("strong", {}, "Your strictness: "), `counting judgements the AI was at least ${pct}% sure of (${strictness(threshold)})`, temp ? h("strong", {}, " — temporarily; your setting stays at " + Math.round(setting * 100) + "%") : null, ". Your own judgements always count. The AI's certainty is its own estimate, not a check of whether it is right. "),
      temp ? h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => setThreshold(setting) }, "Back to my setting") : h("a", { href: "#/settings/basics" }, "Change in Settings"));
  }

  // "8 excerpts read from 5 of 6 documents: …"; "5 of 6" opens a line naming the documents not read
  function readSentence(all, docsRead, total, what) {
    const judged = all.filter(about).length;
    const rest = all.length - judged;
    const n = all.length;
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
    return h("span", {}, `${n} `, definedTerm(n === 1 ? "excerpt" : "excerpts", "An excerpt is a stretch of a document of up to about 180 words. Documents are read excerpt by excerpt, and each excerpt is judged on its own."), " read from ", docsEl, `: ${judged} ${judged === 1 ? "is" : "are"} about ${what} (below), ${rest} ${rest === 1 ? "was" : "were"} not (listed at the bottom).`, unreadLine);
  }

  // A term with an explanation that opens on hover or focus and stays open on click or tap (no native tooltip).
  function definedTerm(term, explanation) {
    const pop = h("span", { class: "pop", role: "note", hidden: true }, explanation);
    let pinned = false;
    const btn = h("button", { class: "defined", type: "button", "aria-expanded": "false" }, term);
    const show = (on) => { pop.hidden = !on; btn.setAttribute("aria-expanded", on ? "true" : "false"); };
    btn.addEventListener("click", () => { pinned = !pinned; show(pinned); });
    btn.addEventListener("mouseenter", () => show(true)); btn.addEventListener("mouseleave", () => { if (!pinned) show(false); });
    btn.addEventListener("focus", () => show(true)); btn.addEventListener("blur", () => { if (!pinned) show(false); });
    btn.addEventListener("keydown", (e) => { if (e.key === "Escape") { pinned = false; show(false); } });
    return h("span", { class: "defined-wrap" }, btn, pop);
  }

  // ------------------------------------------------------------------------------------------
  function whoSaysWhat(part) {
    const bal = part.balance || {};
    const who = part.who || [];
    if (!bal.docs_counted || !who.length) return null;
    const sideWord = { supports: "supports it", partly: "partly supports it", refutes: "contradicts it" };
    const sideWordPl = { supports: "support it", partly: "partly support it", refutes: "contradict it" };
    const sideOf = { supports: "supports", partially_supports: "partly", refutes: "refutes" };
    const counted = (part.passages || []).filter((p) => p.counted && p.verdict);
    const col = (side, cls, ic) => {
      const docs = who.filter((w) => w.side === side);
      const one = docs.length === 1;
      const verb = { supports: one ? "supports it" : "support it", partly: one ? "partly supports it" : "partly support it", refutes: one ? "contradicts it" : "contradict it" }[side];
      return h("div", { class: `who-col ${cls}` },
        h("h3", { class: "it" }, icon(ic, { size: 15 }), `${docs.length} ${one ? "document" : "documents"} ${verb}`),
        docs.length ? h("ul", {}, docs.map((w) => {
          const other = w.both_sides ? who.find((x) => x.doc_id === w.doc_id && x.side !== w.side) : null;
          // counted excerpts of this document on a side `who` does not list (a document with supporting and partly supporting ones)
          const listed = new Set(who.filter((x) => x.doc_id === w.doc_id).map((x) => x.side));
          const extra = counted.filter((p) => p.doc_id === w.doc_id && !listed.has(sideOf[p.verdict]));
          const extraBy = {};
          for (const p of extra) (extraBy[sideOf[p.verdict]] = extraBy[sideOf[p.verdict]] || []).push(p.location);
          return h("li", {}, h("span", { class: "serif" }, w.title),
            h("span", { class: "muted small" }, w.locations && w.locations.length ? ` · ${w.locations.join(", ")}` : "", w.excerpts > 1 ? ` · ${w.excerpts} excerpts` : ""),
            other ? h("span", { class: "both-note" }, ` · also ${sideWord[other.side]}`) : null,
            Object.entries(extraBy).map(([sd, locs]) => h("span", { class: "more-note" }, ` · ${locs.length === 1 ? "1 more excerpt" : `${locs.length} more excerpts`} ${locs.length === 1 ? sideWord[sd] : sideWordPl[sd]}${locs.filter(Boolean).length ? ` (${locs.filter(Boolean).join(", ")})` : ""}`)));
        })) : h("p", { class: "muted small" }, "none"));
    };
    let sub;
    if (bal.docs_counted === 1 && bal.docs_both) sub = "One document has excerpts that count, and it is listed on both sides.";
    else sub = `${bal.docs_counted} ${bal.docs_counted === 1 ? "document has" : "documents have"} excerpts that count` + (bal.docs_both ? `; ${bal.docs_both} ${bal.docs_both === 1 ? "of them is" : "of them are"} on both sides.` : ".");
    return h("section", { class: "card who", "aria-label": "Who says what" },
      h("div", { class: "card-head" }, h("h2", {}, "Who says what"), h("span", { class: "muted small" }, sub)),
      h("div", { class: "who-grid" }, col("supports", "who-sup", "circle-check"), col("partly", "who-part", "circle-half"), col("refutes", "who-ref", "circle-x")));
  }

  // ------------------------------------------------------------------------------------------
  function partView(part, r, single) {
    const passages = part.passages || [];
    const judged = passages.filter(about);
    const rest = passages.filter((p) => !about(p));
    const counted = passages.filter((p) => p.counted).length;
    const card = h("section", { class: "card part-card", "aria-label": single ? "Evidence" : `Part ${part.part}` });
    card.id = `part-${part.part}`;
    card.dataset.claim = part.claim_id;
    if (!single) {
      card.appendChild(h("div", { class: "part-head" },
        h("div", { class: "grow" }, h("span", { class: "pn" }, `Part ${part.part} of ${r.parts.length}`), h("p", { class: "part-claim" }, part.claim),
          part.target ? h("div", { style: { marginTop: "6px" } }, codeChip(part.framework, part.target, part.target_description, r.code_label)) : null),
        h("div", { class: "part-status" }, statusBadge(part.status, { short: true }), h("span", { class: "muted small", style: { maxWidth: "28em", textAlign: "right" } }, part.status === "uncertain" ? "judged, but nothing certain enough to count" : docsCountSentence(part.balance),
          part.balance && part.balance.docs_counted ? ` Rests on ${part.balance.docs_counted} ${part.balance.docs_counted === 1 ? "document" : "documents"} (${counted} ${counted === 1 ? "excerpt" : "excerpts"}).` : ""))));
      if (App.statusHelp(part.status)) card.appendChild(h("p", { class: "part-help muted small" }, `This part: ${App.statusHelp(part.status)}`));
      const who = whoSaysWhat(part);
      if (who) { who.classList.add("who-inline"); card.appendChild(who); }
    }
    if (part.status === "failed" && part.errors && part.errors.length) {
      card.appendChild(h("div", { class: "notice notice-error" }, icon("alert-circle"), h("div", {}, h("p", {}, "The AI's answers could not be used, even after three tries."), h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("ul", { class: "errors-list" }, part.errors.slice(0, 5).map((e) => h("li", {}, e)))))));
    }
    if (part.status === "no_passages") {
      card.appendChild(h("div", { class: "notice notice-warn" }, icon("search-x"), h("p", {}, "No part of your documents uses words close to this. Try other words below, rephrase the hypothesis, or add documents.")));
    }
    const title = single ? "Evidence" : "Evidence for this part";
    const what = single ? "this hypothesis" : "this part";
    card.appendChild(h("div", { class: "evidence-head" },
      h("h3", {}, judged.length ? `${title}: ${judged.length} ${judged.length === 1 ? "excerpt is" : "excerpts are"} about ${what}` : `${title}: none of the ${passages.length} ${passages.length === 1 ? "excerpt" : "excerpts"} read is about ${what}`),
      h("span", { class: "muted small" }, judged.length ? [`${counted} ${counted === 1 ? "counts" : "count"} at `, h("a", { href: "#strictness", onClick: jumpTo("strictness") }, "your strictness"), rest.length ? `; ${rest.length} ${rest.length === 1 ? "excerpt was" : "excerpts were"} not about ${what} (listed at the bottom)` : "", ". The highlighted words are the exact quote, verified against the document."] : "")));
    card.appendChild(roundsBlock(part, r));
    if (evidenceView === "table") {
      card.appendChild(h("p", { class: "muted small table-note" }, icon("list-checks", { size: 13 }), ` The ${passages.length} ${passages.length === 1 ? "excerpt" : "excerpts"} read for ${what} ${passages.length === 1 ? "is" : "are"} in the table above; click a row to open it as a card.`));
    } else {
      if (judged.length) card.appendChild(h("div", { class: "ev-list" }, judged.map((p) => evidenceCard(p, part))));
      if (rest.length) {
        card.appendChild(fold(`rest:${part.claim_id}`, { class: "fold also-read" }, h("summary", {}, `Excerpts read that were not about ${what} (${rest.length})`),
          h("p", { class: "muted small", style: { margin: "4px 0 0" } }, "Judged as not about it, by the AI or by you. They are listed so you can check the search, and you can judge them yourself."),
          h("div", { class: "ev-list" }, rest.map((p) => evidenceCard(p, part)))));
      }
    }
    card.appendChild(moreRow(part, r));
    return card;
  }

  // "Cards" or "Table": how the excerpts are shown; remembered in this browser.
  function viewToggle(n) {
    const set = (v) => { if (v === evidenceView) return; evidenceView = v; store("evidenceView", v); draw(current); };
    const btn = (v, label, ic) => h("button", { class: "btn btn-sm seg-btn" + (evidenceView === v ? " seg-on" : ""), type: "button", "aria-pressed": evidenceView === v ? "true" : "false", onClick: () => set(v) }, icon(ic, { size: 13 }), label);
    return h("div", { class: "view-toggle", role: "group", "aria-label": "How to show the excerpts" },
      h("span", { class: "muted small" }, `Show the ${n} excerpts read as:`), btn("cards", "Cards", "file-text"), btn("table", "Table", "list-checks"),
      h("span", { class: "muted small" }, evidenceView === "table" ? "one row per excerpt, with your decisions; click a row to open its card" : "the full text with its quote, your judgement and the AI's"));
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
      return h("span", { class: `it ${ok ? "" : "tag-disagree"}` }, icon(ok ? "check" : "arrows-opposed", { size: 12 }), `${gradeWords(p.second.verdict, p.second.confidence)} · ${agreesYou === null ? (p.second.agrees ? "agrees" : "disagrees") : (agreesYou ? "agrees with you" : "disagrees with you")}`);
    };
    const table = h("table", { class: "table table-responsive ex-table" },
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "#"), split ? h("th", { scope: "col" }, "Part") : null, h("th", { scope: "col" }, "Document"), h("th", { scope: "col" }, "Where"), h("th", { scope: "col" }, "AI's judgement"), h("th", { scope: "col" }, "Your judgement"), h("th", { scope: "col" }, "Counts"), h("th", { scope: "col" }, "Second AI model"))),
      h("tbody", {}, rows.map(([part, p], i) => h("tr", { class: `row-link ex-row ex-${p.verdict || "none"}${p.reviewed ? " ex-reviewed" : ""}`, tabindex: "0", onClick: () => open(part, p), onKeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(part, p); } } },
        h("td", { class: "num muted" }, String(i + 1)),
        split ? h("td", { "data-label": "Part" }, `Part ${part.part}`) : null,
        h("td", { "data-label": "Document", class: "ex-doc" }, h("span", { class: "serif" }, p.title || "untitled"), p.scope_note ? h("div", { class: "small", style: { color: "var(--partly)" } }, `about another group: ${p.scope_note}`) : null),
        h("td", { "data-label": "Where", class: "small muted" }, p.location || p.span || ""),
        h("td", { "data-label": "AI's judgement" }, h("span", { class: "it" }, icon(p.ai_verdict ? { supports: "circle-check", partially_supports: "circle-half", refutes: "circle-x" }[p.ai_verdict] : "circle-dashed", { size: 12 }), gradeWords(p.ai_verdict, p.confidence)), p.reread ? h("div", { class: "small muted" }, "read again") : null),
        h("td", { "data-label": "Your judgement" }, yours(p)),
        h("td", { "data-label": "Counts" }, p.verdict ? (p.counted ? h("span", { class: "it", style: { color: "var(--ok)" } }, icon("check", { size: 12 }), "counts") : h("span", { class: "muted small" }, "too uncertain")) : h("span", { class: "muted small" }, "not about it")),
        h("td", { "data-label": "Second AI model", class: "small" }, second(p))))));
    return h("section", { class: "card ex-table-card", "aria-label": "All excerpts read" },
      h("div", { class: "card-head" }, h("h2", {}, `All ${rows.length} excerpts read`), h("span", { class: "muted small" }, "in the same order as the cards; your judgements count whatever the AI's certainty")),
      h("div", { class: "table-wrap" }, table));
  }

  // What was searched for in each round, and the AI's note on that round's excerpts.
  function roundsBlock(part, r) {
    const rounds = part.rounds_info || [];
    if (!rounds.length) return h("div");
    const own = new Set((r.text + " " + (part.claim || "")).toLowerCase().split(/[^a-z0-9]+/i).filter(Boolean));
    const box = h("div", { class: "rounds" });
    const o = r.options || {};
    box.appendChild(h("div", { class: "muted small limits" }, `Each search reads up to ${o.k ?? App.settings().k ?? 8} excerpts, at most ${o.per_doc ?? App.settings().per_doc ?? 2} per document (`, h("a", { href: "#/settings/basics" }, "Settings"), ")."));
    for (const rd of rounds) {
      const terms = (rd.terms || []).filter((t) => !own.has(String(t).toLowerCase()));
      const isNew = newRound.get(part.claim_id) === rd.round;
      const corrected = (part.passages || []).some((p) => p.round === rd.round && p.changed);
      box.appendChild(h("div", { class: "round-row" + (isNew ? " round-new" : "") },
        h("div", { class: "round-head" }, h("strong", {}, rounds.length > 1 ? `Search ${rd.round}` : "Search"), isNew ? h("span", { class: "badge status-supported new-badge" }, "new") : null,
          h("span", { class: "muted" }, ` · ${rd.passages} ${rd.passages === 1 ? "excerpt" : "excerpts"} read`),
          terms.length ? h("span", { class: "muted" }, " · also searched for: ", terms.map((t) => h("span", { class: "term" }, t))) : h("span", { class: "muted" }, " · searched with the words of the hypothesis")),
        rd.ai_note ? h("div", { class: "ai-note" }, icon("quote", { size: 13 }), h("span", {}, h("span", { class: "muted" }, corrected ? `The AI's note when it read these ${rd.passages} excerpts (before your corrections): ` : `The AI's own note on these ${rd.passages} excerpts: `), rd.ai_note)) : null,
        strongerLine(rd)));
    }
    const tried = triedTerms.get(part.claim_id) || [];
    if (tried.length) box.appendChild(h("div", { class: "round-row round-tried" }, h("div", { class: "round-head" }, h("strong", {}, "You also tried"), h("span", { class: "muted" }, ": ", tried.map((t) => h("span", { class: "term" }, t)), ". Nothing new was found."))));
    return box;
  }

  // 0.8: "Ask a stronger model" on one search round (the excerpts the AI read together), once
  function strongerLine(rd) {
    if (rd.waiting) return h("div", { class: "muted small" }, icon("inbox", { size: 12 }), " Waiting for Claude Code.");
    if (rd.stronger_waiting) return h("div", { class: "muted small" }, icon("inbox", { size: 12 }), " A stronger model reads these excerpts again; until then the first reading counts.");
    if (rd.stepped_up) return h("div", { class: "muted small" }, icon("layers", { size: 12 }), " A stronger model read these excerpts again; its reading counts (the first one is under Technical details on each excerpt).");
    if (!current.stronger_model || rd.status !== "done") return null;
    return h("div", {}, h("button", { class: "btn btn-sm btn-ghost stronger-btn", type: "button", title: "The excerpts of this search are read once more by a stronger model; its judgements replace the AI's first ones (yours stay and still count)", onClick: async (e) => {
      e.currentTarget.disabled = true;
      try {
        const r = await api("POST", `/api/projects/${P(project)}/tasks/${P(rd.task_id)}/stronger`, {});
        toast(`A stronger model (${current.stronger_model}) reads these ${rd.passages} excerpts again.`, "ok");
        const w = watchJob(r.job.id, () => {});
        watchers.push(w);
        w.promise.then(() => load()).catch(() => load());
        load();
      } catch (err) { showError(err); }
    } }, icon("layers", { size: 13 }), `Ask a stronger model (${current.stronger_model})`));
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
    const top = h("div", { class: "ev-top" });
    if (yours && p.changed) {
      append(top, [gradeBadge(p.verdict, false), h("span", { class: "chip chip-yours" }, icon("note", { size: 12 }), "your judgement"),
        h("span", { class: "muted small" }, p.ai_verdict ? `AI said: ${GRADE_TEXT[p.ai_verdict]}${p.certainty ? ` (certainty ${p.certainty}${pct ? `, ${Math.round(p.confidence * 100)}%` : ""})` : ""}` : "AI said: not about this")]);
    } else if (yours) {
      append(top, [gradeBadge(p.verdict, false), h("span", { class: "chip chip-yours" }, icon("check", { size: 12 }), "you agreed with the AI"),
        p.certainty ? h("span", { class: "muted small" }, `AI certainty: ${p.certainty}${pct}`) : null]);
    } else {
      append(top, [gradeBadge(p.verdict, false)]);
      if (p.verdict && p.certainty) append(top, [h("span", { class: `cert cert-${p.certainty}`, title: certaintyHelp(p) }, icon(p.certainty === "high" ? "circle-check" : p.certainty === "medium" ? "circle-half" : "circle-dashed", { size: 12 }), `AI certainty: ${p.certainty}${pct}`)]);
      else if (!p.verdict) append(top, [h("span", { class: "muted small" }, "AI: not about this hypothesis (it gives no certainty for this)")]);
      if (p.user_note) append(top, [h("span", { class: "chip chip-yours", title: "You wrote a comment on this excerpt but have not judged it: the AI's judgement still counts" }, icon("note", { size: 12 }), "your comment (not a judgement)")]);
    }
    if (p.verdict && p.counted) append(top, [h("span", { class: "chip chip-counted", title: "This judgement is counted in the answer" }, icon("check", { size: 12 }), "counts")]);
    else if (p.verdict && !p.counted) append(top, [h("span", { class: "chip chip-weak", title: certaintyHelp(p) }, icon("alert-triangle", { size: 12 }), "not counted: the AI was less sure than your strictness")]);
    if (p.scope_note) {
      const chip = h("button", { class: "chip chip-scope", type: "button" }, icon("help", { size: 12 }), h("span", {}, "About another group: ", h("em", {}, p.scope_note)));
      append(top, [popNote(chip, SCOPE_HELP, { wide: true })]);
    }
    if (p.second) {
      const s = p.second;
      const agrees = !!s.agrees;   // with the first AI's own judgement
      // when the person has judged it, compare with them first (their "not about this" is the model's null)
      const youSaid = p.user_verdict ? (p.user_verdict === "not_relevant" ? null : p.user_verdict) : undefined;
      const agreesYou = youSaid === undefined ? null : (s.verdict || null) === youSaid;
      const text = agreesYou === null ? `Second AI model: ${gradeWords(s.verdict, s.confidence)} — ${agrees ? "agrees" : "disagrees"} with the first AI`
        : `Second AI model: ${gradeWords(s.verdict, s.confidence)} — ${agreesYou ? "agrees" : "disagrees"} with your judgement (the first AI said ${p.ai_verdict ? GRADE_TEXT[p.ai_verdict] : "not about this"})`;
      const good = agreesYou === null ? agrees : agreesYou;
      const chip = h("button", { class: `chip chip-second ${good ? "chip-agrees" : "chip-disagrees"}${!agrees ? " chip-models-differ" : ""}`, type: "button" },
        icon(good ? "check" : "arrows-opposed", { size: 12 }), h("span", {}, text));
      append(top, [popNote(chip, (agreesYou === null
        ? (agrees ? "A second AI model read this excerpt and came to the same judgement as the first AI. " : "A second AI model read this excerpt and judged it differently from the first AI. Where two models disagree, it is worth reading the excerpt yourself: your judgement decides. ")
        : (agreesYou ? "A second AI model read this excerpt and came to the same judgement as you. " : "A second AI model read this excerpt and judged it differently from you. ") + (agrees ? "It agrees with the first AI. " : "The two AI models disagree with each other. "))
        + "Second judgements never change the answer.", { wide: true })]);
    }
    if (isNew) append(top, [h("span", { class: "badge status-supported new-badge" }, "new")]);
    card.appendChild(top);
    if (current && (current.parts || []).length > 1) {
      card.appendChild(h("div", { class: "ev-part muted small" }, icon("split", { size: 12 }), h("span", {}, h("strong", {}, `Part ${part.part} of ${current.parts.length}: `), h("span", { class: "serif" }, part.claim))));
    }
    const hist = p.ai_history || [];
    if (p.reread && hist.length) {
      const first = hist[0];
      const info = p.reread_info || {};
      card.appendChild(h("div", { class: "reread-line" }, icon("refresh", { size: 13 }),
        h("div", {},
          h("div", {}, h("strong", {}, hist[hist.length - 1].why === "stepped up" ? `Read again by a stronger model (the first reading was by ${first.model || "the first model"}): ` : "Read again by the AI: "), `was ${gradeWords(first.verdict, first.confidence)}, now ${gradeWords(p.ai_verdict, p.confidence)}`, hist.length > 1 ? ` (read again ${hist.length} times; the list is under Technical details)` : "", ". ",
            p.user_verdict ? h("span", { class: "reread-yours" }, `Your own judgement (${p.user_verdict === "not_relevant" ? "Not about this" : GRADE_TEXT[p.user_verdict]}) still counts.`) : "The new judgement counts, unless you judge it yourself."),
          info.rationale ? h("div", { class: "reread-why" }, h("span", { class: "muted" }, "The AI's reason: "), info.rationale) : null,
          info.hint ? h("div", { class: "reread-why" }, h("span", { class: "muted" }, "Your note was given to the AI: "), h("q", {}, info.hint)) : null,
          h("div", { class: "reread-why muted" }, info.hint ? "The AI may simply follow your hint: judge the excerpt yourself." : "A re-read is still the AI's reading: judge the excerpt yourself."))));
    }
    const span = quoteSpan(p);
    card.appendChild(h("div", { class: "ev-src" }, icon("file-text", { size: 14 }),
      p.in_corpus ? h("a", { href: docHref(p, span), class: "title", title: "Open the whole document at this place" }, p.title || "untitled") : h("span", { class: "title" }, p.title || "untitled"),
      whereText(p),
      !p.in_corpus ? h("span", { class: "warn-chip", title: "This document was removed from the project after the check" }, icon("alert-triangle", { size: 12 }), "document removed since") : null));
    // a sentence marked before a judgement was chosen is shown, but not saved until the judgement comes
    const passageEl = pending && Number.isInteger(pending.start) ? passageNode(p.text, pending.start, pending.end, "p", "passage passage-pending", p.breaks) : passageNode(p.text, p.quote_start, p.quote_end, "p", "passage", p.breaks);
    card.appendChild(passageEl);
    if (pending) {
      card.appendChild(h("div", { class: "pending-quote", role: "status" }, icon("highlighter", { size: 13 }),
        h("span", {}, h("strong", {}, "The sentence you mean "), Number.isInteger(pending.start) ? "(highlighted above)" : h("q", {}, pending.text), " — not saved yet: ", h("strong", {}, "now choose your judgement for this sentence"), " below. If you leave the page first, nothing is saved. "),
        h("button", { class: "link-btn", type: "button", onClick: () => { pendingQuote.delete(pendingKey(p, part)); draw(current); } }, "Forget this sentence")));
    }
    const hasQuoteNow = Number.isInteger(p.quote_start) && Number.isInteger(p.quote_end) && p.quote_end > p.quote_start;
    if (hasQuoteNow && p.quote_by && !pending) {
      const aiDiffers = p.quote_by === "you" && p.ai_quote && p.ai_quote !== p.quote;
      card.appendChild(h("div", { class: "quote-by muted small" }, icon("highlighter", { size: 12 }),
        h("span", {}, p.quote_by === "you" ? "Sentence highlighted by you" : "Sentence highlighted by the AI",
          aiDiffers ? [" · The AI pointed to: ", h("q", {}, p.ai_quote)] : null)));
    }
    if (p.refers_to) {  // check-v4: what the quote's "it" or "the plant" is
      const word = ((p.quote || "").match(/^\W*([\p{L}’']+(?:\s+(?:latter|former))?)/u) || [])[1] || "it";
      card.appendChild(h("div", { class: "ev-refers" }, h("span", { class: "refers", title: "The AI named what the quote refers to; the name was checked against the text" },
        icon("link", { size: 12 }), h("span", {}, `“${word}” = `), h("strong", {}, p.refers_to), p.refers_location ? h("span", { class: "muted" }, `(${p.refers_location})`) : null)));
    } else if (p.reference_missing && !p.reviewed) {
      card.appendChild(h("div", { class: "ev-refers" }, h("span", { class: "chip chip-flag", title: "The quote starts with a word like “it” or “this”, and the AI did not say what it refers to: read the text before it to be sure the excerpt is about what the hypothesis names." },
        icon("help", { size: 12 }), "Check what the quote's first word refers to")));
    }
    if (p.user_note) card.appendChild(h("div", { class: "user-note" }, icon("note", { size: 13 }), h("span", {}, h("span", { class: "muted" }, "Your comment: "), p.user_note)));
    if (p.verdict && p.quote && !(Number.isInteger(p.quote_start) && Number.isInteger(p.quote_end))) {
      card.appendChild(h("div", { class: "ev-weak-note" }, icon("info", { size: 13 }), "Quote: ", h("q", {}, p.quote)));
    }
    card.appendChild(judgeControl(p, part, passageEl));
    const foot = h("div", { class: "ev-foot" });
    if (p.in_corpus) {
      const ctxBtn = h("button", { class: "btn btn-sm btn-ghost", type: "button", "aria-expanded": "false" }, icon("eye", { size: 13 }), "Show more of the document");
      let ctx = null;
      ctxBtn.addEventListener("click", async () => {
        if (ctx) { ctx.hidden = !ctx.hidden; ctxBtn.setAttribute("aria-expanded", ctx.hidden ? "false" : "true"); replace(ctxBtn, icon("eye", { size: 13 }), ctx.hidden ? "Show more of the document" : "Hide the surroundings"); return; }
        ctxBtn.disabled = true;
        try {
          ctx = await contextView(p, span);
          card.appendChild(ctx);
          ctxBtn.setAttribute("aria-expanded", "true");
          replace(ctxBtn, icon("eye", { size: 13 }), "Hide the surroundings");
        } catch (e) { showError(e); }
        ctxBtn.disabled = false;
      });
      foot.appendChild(ctxBtn);
      foot.appendChild(originalLink(project, p.doc_id, p.page, null, { button: true, quote: p.quote || null, pdfHint: !!p.quote }));
      if (p.verdict || p.user_verdict) foot.appendChild(h("button", { class: "btn btn-sm btn-ghost", type: "button", title: "A copy of this document with the judgements of this hypothesis highlighted (green supports, amber partly, red contradicts), each with a note",
        onClick: () => download(`/api/projects/${P(project)}/documents/${P(p.doc_id)}/annotated.pdf?hyp=${encodeURIComponent(hypId)}&threshold=${threshold}`).catch(showError) },
        icon("highlighter", { size: 13 }), "Highlighted copy"));
    }
    const rereadBtn = h("button", { class: "btn btn-sm btn-ghost", type: "button", disabled: [...running.values()].some((x) => x.kind === "reread" && x.passage_id === p.passage_id) }, icon("refresh", { size: 13 }), "Ask the AI to read this again");
    rereadBtn.addEventListener("click", () => rereadDialog(p, part, rereadBtn));
    foot.appendChild(rereadBtn);
    foot.appendChild(h("span", { class: "spacer" }));
    const sec = p.second;
    foot.appendChild(fold(`tech:${p.passage_id}`, { class: "fold ev-tech" }, h("summary", {}, "Technical details"),
      h("dl", { class: "ev-tech-list" },
        p.confidence !== null && p.confidence !== undefined ? h("div", {}, h("dt", {}, "AI certainty"), h("dd", {}, `${Math.round(p.confidence * 100)}% (counts from ${Math.round(threshold * 100)}%)`)) : null,
        h("div", {}, h("dt", {}, "Found"), h("dd", {}, { keywords: "same words", meaning: "search by meaning", both: "same words and search by meaning" }[p.found_by] || p.found_by || "")),
        (p.matched || []).length ? h("div", {}, h("dt", {}, "Words that found it"), h("dd", {}, p.matched.join(", "))) : null,
        p.refers_to ? h("div", {}, h("dt", {}, "The quote refers to"), h("dd", {}, `${p.refers_to}${p.refers_location ? ` (${p.refers_location})` : ""}`)) : null,
        p.round ? h("div", {}, h("dt", {}, "Search round"), h("dd", {}, String(p.round))) : null,
        p.scope_note ? h("div", {}, h("dt", {}, "AI's scope note"), h("dd", {}, p.scope_note)) : null,
        h("div", {}, h("dt", {}, "Excerpt id"), h("dd", { class: "mono" }, p.passage_id))),
      hist.length ? h("div", { class: "tech-block" }, h("div", { class: "muted small" }, "The AI's earlier judgements of this excerpt (oldest first), before it was asked to read it again:"),
        h("ol", { class: "ai-history" }, hist.map((x) => h("li", {}, `${gradeWords(x.verdict, x.confidence)}${x.scope_note ? ` · scope note: ${x.scope_note}` : ""} · ${x.model || ""} · ${fmt.date(x.at)}${x.replaced_at ? ` → replaced ${fmt.date(x.replaced_at)}` : ""}`, x.quote ? h("div", { class: "muted small serif" }, `“${x.quote}”`) : null)),
          h("li", {}, `${gradeWords(p.ai_verdict, p.confidence)}${p.scope_note ? ` · scope note: ${p.scope_note}` : ""} · ${part.model || current.model || ""} · now`))) : null,
      sec ? h("div", { class: "tech-block" }, h("div", { class: "muted small" }, `Second model: ${sec.model || ""} · ${gradeWords(sec.verdict, sec.confidence)} · ${sec.agrees ? "agrees" : "disagrees"} with the main model's own judgement (${gradeWords(p.ai_verdict, p.confidence)}) · ${fmt.date(sec.at)}`),
        sec.scope_note ? h("div", { class: "muted small" }, `Its scope note: ${sec.scope_note}`) : null,
        sec.quote ? h("div", { class: "muted small serif" }, `Its quote: “${sec.quote}”`) : null) : null));
    card.appendChild(foot);
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
    if (hasQuote && p.location) return h("span", { class: "page" }, h("span", { class: "where-quote" }, `The quote is ${/^page/i.test(p.location) ? "on" : "in"} ${p.location}`), p.span && p.span !== p.location ? h("span", { class: "where-span" }, ` (${covers(p.span)})`) : "");
    if (p.span) return h("span", { class: "page" }, h("span", { class: "where-span" }, covers(p.span).replace(/^the excerpt shown/, "The excerpt shown")));
    return p.location ? h("span", { class: "page" }, p.location) : null;
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

  async function blocksOf(docId) {
    if (!blocksCache.has(docId)) blocksCache.set(docId, api("GET", `/api/projects/${P(project)}/documents/${P(docId)}?view=blocks&offset=0&limit=500`));
    return blocksCache.get(docId);
  }

  // The paragraph or page the quote is in, with one before and one after, labelled as the locations are.
  async function contextView(p, span) {
    const d = await blocksOf(p.doc_id);
    const blocks = d.blocks || [];
    let i = blocks.findIndex((b) => span.start >= b.start && span.start < b.end);
    if (i < 0) i = 0;
    const shown = blocks.slice(Math.max(0, i - 1), Math.min(blocks.length, i + 2));
    return h("div", { class: "context" },
      h("div", { class: "muted small", style: { marginBottom: "6px" } }, `In “${d.title || p.title || "untitled"}”: ${blocks[i] ? blocks[i].label : "the place"}, with the quote, and the ${blockUnit(blocks[i])} around it.`),
      h("ul", { class: "context-list" }, shown.map((b) => h("li", { class: b.n === blocks[i].n ? "current" : "" },
        h("span", { class: "cp" }, b.label),
        blockNode(b, span, "span", "")))),
      h("div", { class: "btn-row", style: { marginTop: "6px" } },
        h("a", { href: docHref(p, span), class: "btn btn-sm btn-ghost" }, icon("book-open", { size: 13 }), "Open the whole document here"),
        originalLink(project, p.doc_id, (blocks[i] && blocks[i].page) || p.page, d.kind, { button: true, info: d.original, reason: false, quote: p.quote || null })));
  }

  function certaintyHelp(p) {
    if (p.confidence === null || p.confidence === undefined) return "";
    const pct = Math.round(p.confidence * 100);
    return `The AI said it was ${pct}% sure of this judgement. Judgements count from ${Math.round(threshold * 100)}% (your strictness: ${strictness(threshold)}).`;
  }

  // Review: agree (saves the AI's own verdict), judge differently (saves on click), comment. Every save can be undone.
  function judgeControl(p, part, passageEl) {
    const wrap = h("div", { class: "judge" });
    const state = h("span", { class: "muted small", "aria-live": "polite" });
    const prev = { verdict: p.user_verdict || null, note: p.user_note || "", quote: p.quote_by === "you" ? p.quote : undefined };
    let noteField = null;
    const put = async (verdict, note, msg, opts = {}) => {
      state.textContent = "Saving…";
      const el = wrap.closest(".ev");
      const list = el ? [...el.parentElement.children].filter((e) => e.classList.contains("ev")) : [];
      const rect = el ? el.getBoundingClientRect() : { top: 80, bottom: 400 };
      // the judgement row is what the person clicked: after the re-draw it stays where it is on the screen
      focusAfter = { passage_id: p.passage_id, claim_id: part.claim_id, top: rect.top, bottom: rect.bottom, anchor: ".judge", anchorTop: wrap.getBoundingClientRect().top, was: el && el.closest(".also-read") ? "rest" : "evidence", index: el ? list.indexOf(el) : 0,
        reason: verdict ? `your judgement is now ${verdict === "not_relevant" ? "“Not about this”" : `“${GRADE_TEXT[verdict]}”`}.` : "the AI's judgement counts again." };
      const noteNow = note ?? (noteField ? noteField.value.trim() : prev.note);   // a comment typed before picking is saved with the judgement
      const body = { verdict, note: noteNow };
      if (opts.quote !== undefined) body.quote = opts.quote;   // the sentence the person points to; left out = keep the earlier one
      const pend = pendingQuote.get(pendingKey(p, part));
      if (verdict && opts.quote === undefined && pend) { body.quote = pend.text; opts = { ...opts, quote: pend.text }; }   // a sentence marked before choosing: saved with the judgement
      if (verdict) pendingQuote.delete(pendingKey(p, part));
      try {
        await api("PUT", `/api/projects/${P(project)}/claims/${P(part.claim_id)}/judgements/${P(p.passage_id)}`, body);
        const undo = async () => {
          focusAfter = { passage_id: p.passage_id, claim_id: part.claim_id, ...placeOf(p.passage_id, part.claim_id), reason: "your last change was undone." };
          const back = { verdict: prev.verdict, note: prev.note };
          if (opts.quote !== undefined) back.quote = prev.quote === undefined ? "" : prev.quote;
          try { await api("PUT", `/api/projects/${P(project)}/claims/${P(part.claim_id)}/judgements/${P(p.passage_id)}`, back); toast("Undone.", "ok", { ttl: 2500, small: true, group: "judge" }); await load(); }
          catch (e) { showError(e); }
        };
        focusAfter.undo = undo;
        if (!opts.silent) toast(msg, "ok", { ttl: 8000, small: true, group: "judge", button: { text: "Undo", onClick: undo } });
        await load();
      } catch (e) { if (opts.onError) opts.onError(e); else showError(e); state.textContent = ""; }
    };
    const aiVerdict = p.ai_verdict || "not_relevant";
    const current = p.user_verdict || "";
    const row = h("div", { class: "judge-row" });
    if (p.changed) {
      row.appendChild(h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: async () => {
        const ok = await confirmDialog({ title: "Go back to the AI's judgement?", message: `Your judgement (${current === "not_relevant" ? "Not about this" : GRADE_TEXT[current]}) is replaced by the AI's (${p.ai_verdict ? GRADE_TEXT[p.ai_verdict] : "not about this"}).${p.user_note ? " Your comment stays." : ""}`, confirmText: "Go back to the AI's", danger: false });
        if (ok) put(null, p.user_note || "", "Back to the AI's judgement.");   // the comment is sent along, so it is kept
      } }, icon("refresh", { size: 13 }), "Go back to the AI's judgement"));
    } else {
      const agreed = p.reviewed && !p.changed;
      const pendHere = pendingQuote.get(pendingKey(p, part));
      row.appendChild(h("div", { class: "agree-box" },
        h("button", { class: "btn btn-sm agree-btn " + (agreed ? "btn-primary" : ""), type: "button", "aria-pressed": agreed ? "true" : "false", onClick: () => put(aiVerdict, undefined, pendHere ? "Saved: you agree with the AI, with your sentence." : "Saved: you agree with the AI.") }, icon("check", { size: 13 }), agreed ? "You agree with the AI" : "Agree with the AI"),
        h("span", { class: "muted small" }, agreed ? "" : pendHere ? "Agreeing saves your sentence with the AI's judgement as yours." : p.ai_verdict ? "Agreeing makes it your judgement: it then counts in the answer, whatever the AI's certainty." : "Agreeing records that you checked it: it stays out of the answer.")));
    }
    const det = fold(`judge:${part.claim_id}:${p.passage_id}`, { class: "fold judge-diff" });
    if (pendingQuote.get(pendingKey(p, part))) det.open = true;   // the options are needed now
    const name = `jv-${part.claim_id}-${p.passage_id}`.replace(/[^a-z0-9_-]/gi, "_");   // one group per card: the same excerpt can sit in two parts
    const opts = USER_VERDICTS.map(([val, label]) => {
      const input = h("input", { type: "radio", name, value: val });
      input.checked = current === val;
      input.addEventListener("change", () => { if (input.checked && val !== current) put(val, undefined, `Saved: ${label}.`); });
      return h("label", { class: "judge-opt" }, input, h("span", {}, label));
    });
    const pendNow = pendingQuote.get(pendingKey(p, part));
    const hasQuote = Number.isInteger(p.quote_start) && Number.isInteger(p.quote_end) && p.quote_end > p.quote_start;
    const note = h("input", { class: "input input-sm", type: "text", placeholder: hasQuote ? "Optional comment, e.g. “about home desks, not commuting”" : "Which sentence do you mean, and why?", value: p.user_note || "", "aria-label": "Comment on this excerpt (saved with your judgement)" });
    noteField = note;
    // a comment alone is not a judgement: it is sent with verdict null and the AI's judgement keeps counting
    const saveNote = h("button", { class: "btn btn-sm", type: "button", onClick: () => put(current || null, note.value.trim(), current ? "Comment saved." : "Comment saved. It is not a judgement: the AI's judgement still counts.") }, "Save comment");
    note.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); saveNote.click(); } });
    det.append(h("summary", {}, icon("note", { size: 13 }), p.changed ? `Your judgement: ${current === "not_relevant" ? "Not about this" : GRADE_TEXT[current]} · change` : "Judge it differently"),
      h("div", { class: "judge-body" },
        pendNow ? h("p", { class: "pending-hint" }, icon("arrow-right", { size: 13 }), " Now choose your judgement for this sentence:") : null,
        h("div", { class: "judge-opts", role: "radiogroup", "aria-label": "Your judgement (saved when you pick one)" }, opts),
        h("div", { class: "row", style: { marginTop: "8px" } }, note, saveNote, current ? null : h("span", { class: "muted small" }, "A comment on its own is not a judgement.")),
        markSentence(),
        h("p", { class: "muted small", style: { margin: "6px 0 0" } }, "Picking one saves it at once (with an Undo). Your judgement replaces the AI's in the answer and the counts, always counts whatever the strictness, and is recorded in downloads.")));

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
        const el = box.querySelector(`[data-claim="${CSS.escape(part.claim_id)}"] [data-passage="${CSS.escape(p.passage_id)}"] .judge-opts input`);
        if (el) el.focus({ preventScroll: true });
      };
      const useSel = h("button", { class: "btn btn-sm", type: "button", onMousedown: (e) => e.preventDefault(), onClick: () => {
        const sel = window.getSelection();
        const inside = sel && sel.rangeCount && !sel.isCollapsed && passageEl.contains(sel.anchorNode) && passageEl.contains(sel.focusNode);
        if (!inside) { msg.textContent = sel && !sel.isCollapsed ? "The selection must be inside this excerpt." : "Select a sentence in the excerpt first."; return; }
        saveQuote(sel.toString());
      } }, icon("highlighter", { size: 13 }), "Use the selected text");
      const sentences = splitSentences(p.text).filter((x) => x.length > 12);
      const pick = h("select", { class: "input input-sm", "aria-label": "Or choose a sentence from the excerpt" },
        h("option", { value: "" }, "…or choose a sentence from the list"), sentences.map((x, i) => h("option", { value: String(i) }, x.length > 90 ? x.slice(0, 88) + "…" : x)));
      const usePick = h("button", { class: "btn btn-sm", type: "button", onClick: () => { if (pick.value === "") { msg.textContent = "Choose a sentence from the list first."; pick.focus(); return; } saveQuote(sentences[Number(pick.value)]); } }, "Use this sentence");
      const remove = p.quote_by === "you" && current ? h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => put(current, undefined, "Your sentence was removed.", { quote: "" }) }, "Remove my sentence") : null;
      return h("div", { class: "mark-sentence" },
        h("div", { class: "mark-head" }, h("strong", {}, "Mark the sentence you mean"), h("span", { class: "muted small" }, current ? " — select text in the excerpt above, then:" : " — select text in the excerpt above, then: (it is saved together with the judgement you choose)")),
        h("div", { class: "row" }, useSel, pick, usePick, remove),
        msg);
    }
    row.append(det, state);
    wrap.appendChild(row);
    return wrap;
  }

  function moreRow(part, r) {
    const k = (r.options && r.options.k) || App.settings().k || 8;
    const row = h("div", { class: "more-row" });
    const status = h("div", { class: "grow", style: { flexBasis: "100%" } });
    const none = part.more_available === false;
    const readN = (part.passages || []).length;
    const moreBtn = h("button", { class: "btn btn-sm", type: "button", disabled: none }, icon("book-open", { size: 13 }), "Look for more evidence");
    const open = termsOpen.has(part.claim_id);
    const termsBtn = h("button", { class: "btn btn-sm", type: "button", "aria-expanded": open ? "true" : "false" }, icon("search", { size: 13 }), "Search with other words");
    const termsInput = h("input", { class: "input input-sm", type: "text", placeholder: "e.g. telework, home office, car use", "aria-label": "Words to search for, separated by commas", value: termsText.get(part.claim_id) || "" });
    termsInput.addEventListener("input", () => termsText.set(part.claim_id, termsInput.value));
    const termsGo = h("button", { class: "btn btn-sm btn-primary", type: "button" }, "Search and read");
    const lastRes = termsResult.get(part.claim_id);
    const termsBox = h("div", { class: "more-terms", hidden: !open }, termsInput, termsGo, h("span", { class: "muted small" }, "Words your documents might use instead, separated by commas. The AI then reads the excerpts that match them."),
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
    row.append(
      h("div", { class: "more-opt" }, moreBtn, h("span", { class: "muted small" }, none
        ? (totalEx && readN >= totalEx ? "Every excerpt in your documents has been read." : `All ${readN} excerpts that share a word with this ${r.decomposed ? "part" : "hypothesis"} have been read${totalEx ? ` (${readN} of ${totalEx} excerpts in your documents)` : ""}. Other words may still find more.`)
        : `The AI reads the next ${k} excerpts that match the same words.`)),
      h("div", { class: "more-opt" }, termsBtn, h("span", { class: "muted small" }, "Type words your documents might use; the AI reads excerpts that contain them.")),
      termsBox, status);
    return row;
  }

  function noteCard(r) {
    const ta = h("textarea", { class: "textarea", id: "note", placeholder: "Your own notes on this result: what to check by hand, which document to trust, what to do next…" });
    ta.value = r.note || "";
    const state = h("span", { class: "note-saved", "aria-live": "polite" }, r.note ? "Saved" : "");
    const save = debounce(async () => {
      try { await api("PUT", `/api/projects/${P(project)}/hypotheses/${P(hypId)}/note`, { note: ta.value }); state.textContent = "Saved"; if (current) current.note = ta.value; }
      catch (e) { state.textContent = "Not saved"; showError(e); }
    }, 600);
    ta.addEventListener("input", () => { state.textContent = "Saving…"; save(); });
    return h("section", { class: "card note-card", "aria-label": "Your notes" },
      h("div", { class: "note-head" }, h("label", { for: "note", class: "it" }, icon("note", { size: 15 }), h("strong", {}, "Your notes")), state), ta,
      h("div", { class: "muted small" }, "Saved automatically with this result and included in the Excel download."));
  }

  // ------------------------------------------------------------------------------------------
  function downloadsCard(r, parts) {
    const o = r.options || {};
    const qs = `?threshold=${threshold}`;
    const input = h("input", { type: "range", min: 0.3, max: 0.95, step: 0.05, value: threshold, id: "thr", "aria-describedby": "thr-help" });
    const out = h("output", { for: "thr", class: "nowrap" }, `${strictness(threshold)} (${Math.round(threshold * 100)}%)`);
    input.addEventListener("input", () => { out.textContent = `${strictness(input.valueAsNumber)} (${Math.round(input.valueAsNumber * 100)}%)`; });
    input.addEventListener("change", () => setThreshold(Number(input.value)));
    const tech = fold("tech", { class: "fold tech-card" }, h("summary", {}, "Technical details"),
      h("div", { class: "card card-plain details-body" },
        h("div", { class: "threshold-ctl" },
          h("label", { for: "thr" }, "See this result at another strictness"), h("span", { class: "muted small" }, "relaxed"), input, h("span", { class: "muted small" }, "strict"), out,
          h("span", { class: "muted small", id: "thr-help" }, "Temporary: only this page changes. Your setting is changed in Settings, and applies to every result. A stricter setting counts fewer judgements, but can still count wrong ones.")),
        r.status_any && r.status_any !== r.status ? h("p", { class: "small", style: { marginTop: "8px" } }, icon("info", { size: 13 }), " If every judgement counted, whatever the AI's certainty, the answer would be: ", statusBadge(r.status_any, { short: true })) : null,
        h("dl", { class: "kv-grid", style: { marginTop: "14px" } },
          h("div", { class: "kv" }, h("dt", {}, "AI model"), h("dd", {}, `${r.model || o.model || "unknown"}${o.backend ? ` (${o.backend})` : ""}`)),
          h("div", { class: "kv" }, h("dt", {}, "Search"), h("dd", {}, o.search === "keywords+meaning" ? `same words + search by meaning (${o.embed_model || ""})` : "same words only")),
          h("div", { class: "kv" }, h("dt", {}, "Excerpts per claim"), h("dd", {}, `${o.k ?? "?"}, at most ${o.per_doc ?? "?"} per document`)),
          h("div", { class: "kv" }, h("dt", {}, "Other words"), h("dd", {}, o.expand ? "yes, suggested by the AI" : "no")),
          h("div", { class: "kv" }, h("dt", {}, "Checked in parts"), h("dd", {}, r.decomposed ? `yes, ${parts.length}` : "no")),
          o.prepared ? h("div", { class: "kv" }, h("dt", {}, "Looked at before checking"), h("dd", {}, [o.prepared.parts ? `parts ${o.prepared.edited_parts ? "changed by you" : "as the AI proposed"}` : null, o.prepared.terms ? `search words ${o.prepared.edited_terms ? "changed by you" : "as the AI proposed"}` : null].filter(Boolean).join(", ") || "yes")) : null,
          o.second_pass ? h("div", { class: "kv" }, h("dt", {}, "Sorted again by wording"), h("dd", {}, "yes")) : null,
          o.doc_ids && o.doc_ids.length ? h("div", { class: "kv" }, h("dt", {}, "Searched in"), h("dd", {}, `${o.doc_ids.length} chosen documents`)) : null,
          h("div", { class: "kv" }, h("dt", {}, "Result id"), h("dd", { class: "mono" }, r.hyp_id))),
        h("div", { class: "btn-row", style: { marginTop: "14px" } },
          h("span", { class: "muted small" }, "For programmers / data analysis:"),
          h("button", { class: "btn btn-sm", type: "button", onClick: () => download(`/api/projects/${P(project)}/hypotheses/${P(hypId)}/export.csv${qs}`).catch(showError) }, icon("download", { size: 14 }), "CSV"),
          h("button", { class: "btn btn-sm", type: "button", onClick: () => download(`/api/projects/${P(project)}/hypotheses/${P(hypId)}/export.json${qs}`).catch(showError) }, icon("download", { size: 14 }), "JSON"),
          h("span", { class: "spacer", style: { flex: 1 } }),
          h("button", { class: "btn btn-sm btn-outline-danger", type: "button", onClick: () => deleteHyp(r) }, icon("trash", { size: 14 }), "Delete this result"))));
    return h("section", { class: "card downloads", "aria-label": "Downloads" },
      h("div", { class: "row", style: { justifyContent: "space-between" } },
        h("div", {}, h("h2", { style: { fontSize: "1.05rem" } }, "Download"), h("p", { class: "muted small", style: { margin: "2px 0 0" } }, "An Excel file with two sheets: a summary (one row per hypothesis) and every excerpt read with its judgement, who judged it, where it is, and your comments and notes.")),
        h("div", { class: "btn-row" },
          h("button", { class: "btn", type: "button", title: "A zip with a copy of every document behind this answer, its quotes highlighted (green supports, amber partly, red contradicts) with a note on each: readable in any PDF reader",
            onClick: () => download(`/api/projects/${P(project)}/hypotheses/${P(hypId)}/annotated.zip${qs}`).catch(showError) }, icon("highlighter", { size: 14 }), "Highlighted documents (.zip)"),
          h("button", { class: "btn btn-primary", type: "button", onClick: () => download(`/api/projects/${P(project)}/hypotheses/${P(hypId)}/export.xlsx${qs}`).catch(showError) }, icon("download", { size: 14 }), "Download for Excel (.xlsx)"))),
      h("div", { class: "row", style: { justifyContent: "space-between", marginTop: "10px", paddingTop: "10px", borderTop: "1px dashed var(--border)" } },
        h("p", { class: "muted small", style: { margin: 0 } }, "The whole project (every document, result, judgement and note) as one zip file: to give to a colleague, or to move to another computer, where “Import a project” under Manage projects brings it back."),
        projectZipLink(project)),
      tech);
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
  const a = h("a", { class: "btn btn-sm", href: `/api/projects/${P(project)}/export.zip?token=${encodeURIComponent(TOKEN)}`, download: "", title: "One zip with the database, the settings, the codebooks and the original files of this project" },
    icon("download", { size: 13 }), opts.text || "Download the whole project (.zip)");
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

export function plainSection(section) {
  return { references: "reference list", reference_like: "looks like a reference list", unreadable: "unreadable text", body: "" }[section] || section;
}
