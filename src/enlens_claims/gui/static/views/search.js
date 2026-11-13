// Search (F1): every place words occur in the project's documents, one line per hit with the words centred
// (a concordance). No hypothesis and no AI are needed. Clicking a word of a line adds it to the search; Shift-click
// makes a phrase. A line opens its document at the words, or starts a check about what it says.
import { featureEyebrow } from "../features.js";
import { simpleProgress } from "./progress.js";
import { App, api, h, icon, replace, clear, showError, toast, watchJob, TERMINAL, addDocumentsFirst, download, pageHead, emptyState, fmt, P, navigate, helpMark, downloadLinks, button, link, notice, card, input, select, fold, choice, shortTitle, textPositions, cpLength, latest, lazyList } from "../lib.js";

const MODES = [
  ["any", "any of the words"],
  ["all", "all the words, in one passage"],
  ["phrase", "the words as a phrase"],
  ["near", "the words near each other"],
];
const SORTS = [["doc", "by document"], ["left", "by the word before"], ["right", "by the word after"]];
const PAGE = 100;   // 0.18.1 (H5): the lines come a page at a time as the page scrolls (lazyList)

function hashWith(params) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "" && v !== false) qs.set(k, v === true ? "1" : String(v));
  const s = qs.toString();
  return "#/search" + (s ? "?" + s : "");
}

// A starter sentence for a check, from a concordance line: the sentence around the words found.
export function starterSentence(left, node, right) {
  const before = (left || "").split(/(?<=[.!?])\s+/).pop() || "";
  const after = ((right || "").match(/^[^.!?]*[.!?]?/) || [""])[0];
  return (before + node + after).replace(/\s+/g, " ").trim();
}

// 0.17: the words the search found, marked in a text. `marks` are [start, end] offsets the server gives (the same
// words and stemmer as the search, so exactly what it found is marked); this only draws them. `shift` is where
// `text` begins in the longer text the offsets refer to. Both are the app’s offsets (code points), turned into
// indices of `text` here.
export function markedText(text, marks, shift = 0) {
  const out = [];
  const pos = textPositions(text);
  const rel = (marks || []).map(([a, b]) => [pos.index(a - shift), pos.index(b - shift)]).filter(([a, b]) => b > 0 && a < text.length).sort((x, y) => x[0] - y[0]);
  let last = 0;
  for (const [a0, b0] of rel) {
    const a = Math.max(a0, last), b = Math.min(b0, text.length);
    if (b <= a) continue;
    if (a > last) out.push(text.slice(last, a));
    out.push(h("mark", { class: "kw-also" }, text.slice(a, b)));
    last = b;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// Clickable words: a click adds the word to the query, Shift-click extends the last phrase with it (one listener on
// the table, wordClick(): a page of results has thousands of words). A word on a mark (another searched word of the
// line, 0.17) is drawn marked and stays clickable. `marks` and `shift` are the app’s offsets (see markedText).
// The click on a word of the table: the word, and whether Shift was held (null: not on a word).
function wordClick(e, onWord) {
  const w = e.target instanceof Element ? e.target.closest(".kw-word") : null;
  if (w) onWord(w.textContent, e.shiftKey);
}

function wordSpans(text, marks = [], shift = 0) {
  const out = [];
  const rx = /[\p{L}\p{N}][\p{L}\p{N}'’-]*/gu;
  const pos = textPositions(text);
  let last = 0, m;
  while ((m = rx.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const w = m[0];
    const a = pos.point(m.index) + shift, b = pos.point(m.index + w.length) + shift;
    const span = h("span", { class: "kw-word" }, w);
    out.push((marks || []).some(([ma, mb]) => ma < b && a < mb) ? h("mark", { class: "kw-also" }, span) : span);
    last = m.index + w.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export async function renderSearch(view, params, query) {
  const project = App.project;
  // 0.14.3: a failure is the router's error on the page (it was a toast, then a heading "in the 0 documents")
  const [info, { documents: docs = [] }] = await Promise.all([api("GET", `/api/projects/${P(project)}`), api("GET", `/api/projects/${P(project)}/documents`)]);
  const st = {
    q: query.q || "", mode: query.mode || "any", near: Number(query.near || 5), exact: query.exact === "1",
    all: query.all === "1", docs: query.docs || "", code: query.code || "", sort: query.sort || "doc",
    offset: 0, meaning: query.meaning === "1",   // 0.18.1: the lines load as the page scrolls, so a link needs no offset
  };
  let semantic = !!(info.search && info.search.embedded);
  if (!docs.length) {
    view.appendChild(pageHead("Search the documents", { eyebrow: featureEyebrow("search"), sub: "Every place words occur in the documents, one line per place, with the words around it." }));
    view.appendChild(addDocumentsFirst("Search"));
    return;
  }
  view.appendChild(pageHead("Search the documents", { eyebrow: featureEyebrow("search"),
    sub: `Every place words occur in the ${fmt.plural(docs.length, "document")}, one line per place, with the words around it.`,
  }));

  // ---------------------------------------------------------------- the form
  const qIn = input({ type: "search", value: st.q, placeholder: "One or more words; put a phrase in \"quotes\"", "aria-label": "Words to search for", maxlength: 500 });
  const modeSel = select({ sm: true, "aria-label": "Find" }, MODES.map(([v, t]) => h("option", { value: v, selected: v === st.mode }, t)));
  const nearIn = input({ sm: true, type: "number", min: 1, max: 50, value: st.near, class: "sr-near", "aria-label": "Within how many words" });
  const nearBox = h("label", { hidden: st.mode !== "near" }, "within", nearIn, "words");
  const exact = h("input", { type: "checkbox", checked: st.exact });
  const allSec = h("input", { type: "checkbox", checked: st.all });
  const meaning = h("input", { type: "checkbox", checked: st.meaning && semantic, disabled: !semantic });
  const meaningLabel = h("label", {}, meaning, "search by meaning");
  const docSel = select({ sm: true, "aria-label": "In which documents" }, h("option", { value: "" }, "in all documents"),
    docs.map((d) => h("option", { value: d.doc_id, selected: d.doc_id === st.docs }, (d.title || d.file || "").slice(0, 70))));
  const codeIn = input({ sm: true, value: st.code, placeholder: "e.g. sdg:6.4", class: "sr-code", "aria-label": "Only passages labelled with this code" });
  modeSel.addEventListener("change", () => { nearBox.hidden = modeSel.value !== "near"; });
  const go = button({ kind: "main", type: "submit" }, icon("search", { size: 15 }), "Search");
  const form = card({ as: "form", class: "search-form", role: "search" },
    h("div", { class: "search-main" }, qIn, go),
    h("div", { class: "search-opts" },
      h("label", {}, "Find", modeSel), nearBox, docSel,
      h("label", { title: "Without this, “price” also finds “prices” and “priced”." }, exact, "exact words only"),
      h("label", { title: "Reference lists and title pages are left out of checks; include them here." }, allSec, "include reference lists"),
      meaningLabel),
    fold({ open: !!st.code }, "Only passages with a code",
      h("div", { class: "search-opts sr-code-opts" }, h("label", {}, "Code", codeIn),
        h("span", { class: "muted small" }, "A code of the Profile page, written as codebook:code (sdg:6.4). Only passages labelled with it are searched."))));
  view.appendChild(form);
  const meaningBox = h("div", { class: "search-meaning" });   // 0.18 (M3): setting up search by meaning, from here
  view.appendChild(meaningBox);
  setUpMeaning(info.search || {});
  const out = h("section", { class: "section", "aria-live": "polite" });
  view.appendChild(out);

  const read = () => ({ q: qIn.value.trim(), mode: modeSel.value, near: Number(nearIn.value) || 5, exact: exact.checked, all: allSec.checked,
    docs: docSel.value, code: codeIn.value.trim(), sort: st.sort, offset: 0, meaning: meaning.checked });
  form.addEventListener("submit", (e) => { e.preventDefault(); Object.assign(st, read()); go_(); });

  function addWord(w, shift) {
    let q = qIn.value.trim();
    if (shift) {
      const m = /"([^"]*)"\s*$/.exec(q);
      q = m ? q.slice(0, m.index) + `"${m[1]} ${w}"` : (q ? q.replace(/(\S+)\s*$/, `"$1 ${w}"`) : `"${w}"`);
    } else if (!q.toLowerCase().split(/\s+/).includes(w.toLowerCase())) {
      q = (q + " " + w).trim();
    }
    qIn.value = q;
    qIn.focus();
  }

  function apiQs(extra = {}) {
    const qs = new URLSearchParams({ q: st.q, mode: st.mode, sort: st.sort });
    if (st.mode === "near") qs.set("near", String(st.near));
    if (st.exact) qs.set("exact", "1");
    if (st.all) qs.set("all", "1");
    if (st.docs) qs.set("docs", st.docs);
    if (st.code) qs.set("code", st.code);
    for (const [k, v] of Object.entries(extra)) qs.set(k, String(v));
    return qs;
  }

  // 0.18 (M3): the three states of search by meaning. No model chosen: a line that leads to Settings. A model chosen but
  // the project not (fully) set up: a quiet prompt with the button of the Documents page (the same job, one per
  // project), and its progress here; a job already running (started anywhere) shows as progress, never a second button.
  // When the job ends the checkbox is usable at once, without a reload.
  function drawMeaningChoice(search) {
    semantic = !!(search && search.embedded);
    meaning.disabled = !semantic;
    if (!semantic) meaning.checked = false;
    meaningLabel.title = semantic
      ? "Whole passages that say the same thing in other words (uses the embedding model, on this computer; no AI model)"
      : "Not set up for this project yet: see the note below the search box.";
  }
  async function setUpMeaning(search, job = null) {
    drawMeaningChoice(search);
    clear(meaningBox);
    if (!search.model) {
      meaningBox.appendChild(h("p", { class: "muted small search-meaning-hint" }, icon("network", { size: 13 }), " Search by meaning finds passages that say the same thing in other words. It is off: ",
        link({ href: "#/settings/documents" }, "turn it on in Settings → Documents"), "."));
      return;
    }
    if (job) {
      meaningBox.appendChild(card({ class: "search-meaning-card", "aria-label": "Setting up search by meaning" },
        h("h2", {}, "Setting up search by meaning…"),
        h("p", { class: "muted small" }, "Searching by words works meanwhile. Search by meaning can be used when this is done."),
        simpleProgress(job, (p) => (p.total ? `Preparing ${fmt.num(p.done || 0)} of ${fmt.num(p.total)} excerpts` : "Starting…"))));
      return;
    }
    if (search.complete || !search.passages) return;
    const covered = search.embedded
      ? `${fmt.num(search.embedded)} of ${fmt.num(search.passages)} excerpts are covered so far; the rest are found by their words only.`
      : "Until it is set up, passages are found by their words only.";
    const btn = button({ kind: "main", sm: true }, icon("network", { size: 14 }), "Set up search by meaning");
    meaningBox.appendChild(card({ class: "search-meaning-card", "aria-label": "Set up search by meaning" },
      h("div", { class: "row" }, h("div", { class: "grow" }, h("strong", {}, "Set up search by meaning for this project"), h("p", { class: "muted small" }, covered)), btn)));
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const r = await api("POST", `/api/projects/${P(project)}/index`);   // a job already running comes back as it is
        followMeaning(r.job);
      } catch (e) { showError(e); btn.disabled = false; }
    });
  }
  function followMeaning(job) {
    setUpMeaning(info.search, job);
    const w = watchJob(job.id, (j) => { if (!TERMINAL.has(j.state)) setUpMeaning(info.search, j); });
    w.promise.then(async (j) => {
      if (!meaningBox.isConnected) return;
      try { info.search = (await api("GET", `/api/projects/${P(project)}`)).search || {}; } catch (_) { /* keep what it was */ }
      setUpMeaning(info.search);
      if (j.state === "done") toast("Search by meaning is ready.", "ok");
      else if (j.state === "error") showError({ message: j.error, kind: j.error_kind });
    }, () => { if (meaningBox.isConnected) setUpMeaning(info.search); });
  }
  // an index job that already runs for this project: shown as progress at once
  if (info.search && info.search.model) {
    api("GET", "/api/jobs").then((r) => {
      const running = (r.jobs || []).find((j) => j.project === project && j.kind === "index" && !TERMINAL.has(j.state));
      if (running && meaningBox.isConnected) followMeaning(running);
    }).catch(() => {});
  }

  const fresh = latest();   // a search answered after a newer one was asked (Next, Next) is not drawn
  async function go_() {
    const mine = fresh();
    history.replaceState(null, "", hashWith({ q: st.q, mode: st.mode, near: st.mode === "near" ? st.near : "", exact: st.exact, all: st.all, docs: st.docs, code: st.code, sort: st.sort === "doc" ? "" : st.sort, meaning: st.meaning }));
    if (!st.q) { replace(out, emptyState("text-search", "Type a word to search for", "Every place it occurs in your documents is listed, one line per place. Click a word in a line to add it to the search; Shift-click to make a phrase.")); return; }
    replace(out, h("p", { class: "muted" }, "Searching…"));
    if (st.meaning) return meaningResults(mine);
    let r;
    try { r = await api("GET", `/api/projects/${P(project)}/search?${apiQs({ offset: 0, limit: PAGE })}`); }
    catch (e) { if (mine()) replace(out, notice({ kind: "error", live: false }, h("p", {}, e.message))); return; }
    if (mine()) drawLines(r);
  }

  // forms of the words that the search does not find ("commuters" for "commuting"), to add with one click
  function otherForms(forms) {
    return h("div", { class: "other-forms" }, h("span", { class: "muted small" }, "Other forms in the documents, not included: "),
      forms.map((f) => button({ kind: "quiet", sm: true, title: `Add “${f.word}” to the search (${f.count} times in the documents)`, onClick: () => { modeSel.value = "any"; nearBox.hidden = true; addWord(f.word, false); Object.assign(st, read()); go_(); } }, "+ ", f.word, " ", h("span", { class: "count" }, String(f.count)))));
  }

  function drawLines(r) {
    clear(out);
    if (!r.total) {
      out.appendChild(emptyState("search-x", "Not found", `No passage ${st.mode === "phrase" ? "has this phrase" : st.mode === "all" ? "has all these words" : st.mode === "near" ? "has these words near each other" : "has these words"}${st.exact ? " exactly" : ""}${st.docs ? " in this document" : ""}. Try other words${st.mode === "any" ? "" : ", fewer words, or “any of the words”"}.`));
      if (r.other_forms && r.other_forms.length) out.appendChild(otherForms(r.other_forms));
      return;
    }
    const sortSel = select({ sm: true, "aria-label": "Sort the lines" }, SORTS.map(([v, t]) => h("option", { value: v, selected: v === st.sort }, t)));
    sortSel.addEventListener("change", () => { st.sort = sortSel.value; st.offset = 0; go_(); });
    out.appendChild(h("div", { class: "section-title sr-lines-head" },
      // 0.13.3: what a passage is sits in the heading's help mark, not in a paragraph under it
      h("h2", {}, `${fmt.plural(r.total, "place")} in ${fmt.plural(r.passages, "passage")} of ${fmt.plural(r.documents, "document")}`,
        helpMark("What is a passage?", "A passage is the stretch of text the app reads as one unit, up to about 1,100 characters: a few paragraphs together, or part of a long one. “Where” gives the page and paragraph of the original.")),
      h("span", { class: "muted" }, `searched for: ${r.words.join(", ")}`)));
    if (r.rarest && r.words.length > 1) out.appendChild(h("p", { class: "muted small sr-rarest-note" }, `One line for each place of “${r.rarest}”, the rarest of the words, in passages that have all of them; the other words may be further away in the same passage (open it to see them).`));
    if (r.other_forms && r.other_forms.length) out.appendChild(otherForms(r.other_forms));
    // counts per document first
    // 0.14.3: said in words above the buttons (they read as more word forms, right under "Other forms in the documents")
    out.appendChild(h("p", { class: "per-doc-label muted small", id: "per-doc-label" }, "Places per document (click one to search only that document):"));
    // a filter of the lines: a choice whose chosen document shows as chosen; picking it again shows every document
    const perDocChoice = choice({ filter: true, sm: true, "aria-labelledby": "per-doc-label", value: st.docs || null,
      options: r.per_doc.slice(0, 40).map((d) => [d.doc_id, shortTitle(d.title || "untitled", 48), d.hits, d.title]),
      onPick: (v) => { st.docs = st.docs === v ? "" : v; perDocChoice.set(st.docs || null); docSel.value = st.docs; st.offset = 0; go_(); } });
    const perDoc = h("div", { class: "per-doc" }, perDocChoice,
      r.per_doc.length > 40 ? h("span", { class: "muted small" }, `and ${r.per_doc.length - 40} more documents`) : null);
    out.appendChild(perDoc);
    const tools = h("div", { class: "pager" },
      h("label", { class: "it" }, "Sort ", sortSel),
      downloadLinks([
        { text: "Excel (.xlsx)", onClick: () => download(`/api/projects/${P(project)}/search.xlsx?${apiQs()}`).catch(showError) },
        { text: "CSV", onClick: () => download(`/api/projects/${P(project)}/search.csv?${apiQs()}`).catch(showError) },
      ]));
    out.appendChild(tools);
    const lineRow = (x) => {
      const node = h("mark", {}, ...wordSpans(x.node));
      const docHref = `#/doc/${encodeURIComponent(x.doc_id)}?q=${x.start}-${x.end}`;
      // it only takes the line to the Hypotheses page (nothing is checked yet): a place, so a link (DESIGN.md 6)
      const check = link({ href: `#/hypotheses?text=${encodeURIComponent(starterSentence(x.left, x.node, x.right))}`, class: "kw-check",
        title: "Write a hypothesis about what this line says, on the Hypotheses page", "aria-label": "Check a hypothesis about this line, on the Hypotheses page" }, "Check this");
      // 0.17: the title is what a person looks for; "paragraph N of M" sits in the tooltip and the accessible name
      // 0.17.0rc4: the title is the one way to open the document at these words, so it looks like a link
      const title = x.title || "untitled";
      const where = x.location ? `${title} · ${x.location}` : title;
      return h("tr", { title: where },
        h("td", { class: "kw-where kw-where-title" }, link({ kind: "title", serif: true, href: docHref, class: "kw-title", title: `Open the document at these words: ${where}`, "aria-label": `Open the document at these words: ${where}` }, title)),
        h("td", { class: "kw-left" }, h("span", {}, ...wordSpans(x.left, x.marks))),
        h("td", { class: "kw-node" }, node),
        h("td", { class: "kw-right" }, ...wordSpans(x.right, x.marks, cpLength(x.left) + cpLength(x.node))),
        h("td", { class: "kw-act" }, check));
    };
    // 0.18.1 (H5): the first page came with the heading's figures; the others are asked for as the end of the table
    // comes near. The query is fixed here, so a form edited but not searched yet does not change the later pages.
    const base = apiQs();
    const body_ = h("tbody");
    const lines = lazyList({ first: { items: r.lines, total: r.total }, list: body_, render: lineRow, pageSize: PAGE, noun: "line",
      fetchPage: async (offset, limit) => {
        const qs = new URLSearchParams(base); qs.set("offset", String(offset)); qs.set("limit", String(limit));
        const page = await api("GET", `/api/projects/${P(project)}/search?${qs}`);
        return { items: page.lines, total: page.total };
      } });
    out.appendChild(h("div", { class: "kwic-wrap" }, h("table", { class: "kwic", onClick: (e) => wordClick(e, addWord) }, h("caption", { class: "visually-hidden" }, "Concordance: the words found, with the words before and after"), body_)));
    out.appendChild(lines.footer);
    out.appendChild(h("p", { class: "muted small" }, "Click a word in a line to add it to the search; Shift-click to make a phrase with the words you searched for. Click the title to open the document at those words. “Check this” takes the line to the Hypotheses page, to check what it says."));
    // the words around the hits
    const colBox = card({ as: "div", class: "sr-colloc-card", hidden: true });
    const colBtn = button({ sm: true }, icon("network", { size: 13 }), "Words that often appear nearby");
    const winSel = select({ sm: true, "aria-label": "How many words on each side" }, [2, 3, 5, 8, 10].map((n) => h("option", { value: n, selected: n === 5 }, `${n} words`)));
    const ordSel = select({ sm: true, "aria-label": "Order of the words" }, h("option", { value: "often" }, "most often first"), h("option", { value: "typical" }, "most typical first"));
    const colloc = async () => {
      colBtn.disabled = true;
      colBox.hidden = false;
      replace(colBox, h("p", { class: "muted small" }, "Counting…"));
      try {
        const c = await api("GET", `/api/projects/${P(project)}/collocates?${apiQs({ window: winSel.value, order: ordSel.value })}`);
        replace(colBox, h("h3", { class: "sr-colloc-title" }, "Words that often appear nearby"),
          h("div", { class: "row sr-colloc-controls" }, h("label", { class: "it" }, "Within ", winSel), h("label", { class: "it" }, "Show ", ordSel)),
          h("p", { class: "muted small sr-colloc-note" }, `Words within ${c.window} words of the ${fmt.plural(c.hits, "place")} found, seen there at least ${c.min_count} times. The number is how many times. ${ordSel.value === "typical" ? "Most typical first: words found here far more often than elsewhere in the documents." : "Most often first."} Click one to add it to the search.`),
          c.words.length ? h("div", { class: "colloc" }, c.words.map((w) => button({ kind: "quiet", sm: true, title: `${w.count} times nearby; ${w.corpus} times in all documents; ${Math.max(1, Math.round(2 ** w.pmi))} times more often nearby than expected`, onClick: () => addWord(w.word, false) }, w.word, " ", h("span", { class: "count" }, `${w.count}`))))
            : h("p", { class: "muted" }, "No word stands out: there are too few places, or the words around them vary."),
          fold({}, "Technical details", h("p", { class: "muted small" }, "“Most typical” ranks by pointwise mutual information: how much more often the word appears near the places found than its frequency in all documents would lead you to expect. Point at a word to see both figures. The Excel download has the counts too.")));
      } catch (e) { replace(colBox, h("p", { class: "muted" }, e.message)); }
      colBtn.disabled = false;
    };
    colBtn.addEventListener("click", colloc);
    winSel.addEventListener("change", colloc);
    ordSel.addEventListener("change", colloc);
    out.appendChild(h("div", { class: "btn-row sr-colloc-actions" }, colBtn));
    out.appendChild(colBox);
  }

  async function meaningResults(mine = () => true) {
    let r;
    try { r = await api("GET", `/api/projects/${P(project)}/search?${apiQs({ mode: "meaning", limit: 30 })}`); }
    catch (e) { if (mine()) replace(out, notice({ kind: "error", live: false }, h("p", {}, e.message))); return; }
    if (!mine()) return;
    clear(out);
    out.appendChild(h("div", { class: "section-title" }, h("h2", {}, `The ${r.passages.length} passages closest in meaning`), h("span", { class: "muted" }, "whole passages, by keywords and meaning together")));
    if (!r.passages.length) { out.appendChild(emptyState("search-x", "Nothing found", "No passage is close to these words.")); return; }
    out.appendChild(h("div", { class: "meaning-list" }, r.passages.map((p) => card({ as: "article" },
      h("div", { class: "row sr-meaning-head" },
        link({ kind: "title", serif: true, title: `Open the document at this passage: ${p.title || "untitled"}`, "aria-label": `Open the document at this passage: ${p.title || "untitled"}${p.location ? " · " + p.location : ""}`, href: `#/doc/${encodeURIComponent(p.doc_id)}?q=${p.start}-${(p.start || 0) + cpLength(p.text)}&whole=1` }, h("strong", {}, p.title || "untitled")),
        h("span", { class: "muted small" }, p.location)),
      h("p", { class: "passage serif" }, ...markedText(p.text, p.marks)),
      h("div", { class: "found-words" }, p.found_by === "meaning" ? "Found by meaning: it shares none of the words." : ["Found by the words: ", h("b", {}, (p.matched || []).join(", "))])))));
  }

  qIn.focus();
  if (st.q) go_(); else replace(out, emptyState("text-search", "Type a word to search for", "Every place it occurs in your documents is listed, one line per place, with the words before and after it. Nothing is sent to an AI."));
}
