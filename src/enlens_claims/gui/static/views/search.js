// Search (F1): every place words occur in the project's documents, one line per hit with the words centred
// (a concordance). No hypothesis and no AI are needed. Clicking a word of a line adds it to the search; Shift-click
// makes a phrase. A line opens its document at the words, or starts a check about what it says.
import { featureEyebrow } from "../features.js";
import { App, api, h, icon, replace, clear, showError, download, pageHead, emptyState, fmt, P, navigate } from "../lib.js";

const MODES = [
  ["any", "any of the words"],
  ["all", "all the words, in one passage"],
  ["phrase", "the words as a phrase"],
  ["near", "the words near each other"],
];
const SORTS = [["doc", "by document"], ["left", "by the word before"], ["right", "by the word after"]];
const PAGE = 200;

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

// Clickable words: a click adds the word to the query, Shift-click extends the last phrase with it.
function wordSpans(text, onWord) {
  const out = [];
  const rx = /[\p{L}\p{N}][\p{L}\p{N}'’-]*/gu;
  let last = 0, m;
  while ((m = rx.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const w = m[0];
    out.push(h("span", { class: "kw-word", title: "Click: add to the search. Shift-click: make a phrase with the words before.", onClick: (e) => onWord(w, e.shiftKey) }, w));
    last = m.index + w.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export async function renderSearch(view, params, query) {
  const project = App.project;
  let info = {}, docs = [];
  try {
    const [p, d] = await Promise.all([api("GET", `/api/projects/${P(project)}`), api("GET", `/api/projects/${P(project)}/documents`)]);
    info = p; docs = d.documents || [];
  } catch (e) { showError(e); }
  const st = {
    q: query.q || "", mode: query.mode || "any", near: Number(query.near || 5), exact: query.exact === "1",
    all: query.all === "1", docs: query.docs || "", code: query.code || "", sort: query.sort || "doc",
    offset: Number(query.offset || 0), meaning: query.meaning === "1",
  };
  const semantic = !!(info.search && info.search.embedded);
  view.appendChild(pageHead("Search the documents", { eyebrow: featureEyebrow("search"),
    sub: `Every place words occur in the ${fmt.plural(docs.length, "document")} of project “${project}”, one line per place, with the words around it. No AI model is used (only search by meaning uses the embedding model).`,
  }));

  // ---------------------------------------------------------------- the form
  const input = h("input", { class: "input", type: "search", value: st.q, placeholder: "One or more words; put a phrase in \"quotes\"", "aria-label": "Words to search for", maxlength: 500 });
  const modeSel = h("select", { class: "select input-sm", "aria-label": "Find" }, MODES.map(([v, t]) => h("option", { value: v, selected: v === st.mode }, t)));
  const nearIn = h("input", { class: "input input-sm", type: "number", min: 1, max: 50, value: st.near, style: { width: "4.5em" }, "aria-label": "Within how many words" });
  const nearBox = h("label", { hidden: st.mode !== "near" }, "within", nearIn, "words");
  const exact = h("input", { type: "checkbox", checked: st.exact });
  const allSec = h("input", { type: "checkbox", checked: st.all });
  const meaning = h("input", { type: "checkbox", checked: st.meaning && semantic, disabled: !semantic });
  const docSel = h("select", { class: "select input-sm", "aria-label": "In which documents" }, h("option", { value: "" }, "in all documents"),
    docs.map((d) => h("option", { value: d.doc_id, selected: d.doc_id === st.docs }, (d.title || d.file || "").slice(0, 70))));
  const codeIn = h("input", { class: "input input-sm", type: "text", value: st.code, placeholder: "e.g. sdg:6.4", style: { width: "10em" }, "aria-label": "Only passages labelled with this code" });
  modeSel.addEventListener("change", () => { nearBox.hidden = modeSel.value !== "near"; });
  const go = h("button", { class: "btn btn-primary", type: "submit" }, icon("search", { size: 15 }), "Search");
  const form = h("form", { class: "card search-form", role: "search" },
    h("div", { class: "search-main" }, input, go),
    h("div", { class: "search-opts" },
      h("label", {}, "Find", modeSel), nearBox, docSel,
      h("label", { title: "Without this, “price” also finds “prices” and “priced”." }, exact, "exact words only"),
      h("label", { title: "Reference lists and title pages are left out of checks; include them here." }, allSec, "include reference lists"),
      h("label", { title: semantic ? "Whole passages that say the same thing in other words" : "Turn on search by meaning under Settings → Documents first." }, meaning, "search by meaning")),
    h("details", { class: "fold", open: !!st.code }, h("summary", {}, "Only passages with a code"),
      h("div", { class: "search-opts", style: { marginTop: "6px" } }, h("label", {}, "Code", codeIn),
        h("span", { class: "muted small" }, "A code of the Profile page, written as codebook:code (sdg:6.4). Only passages labelled with it are searched."))));
  view.appendChild(form);
  const out = h("section", { class: "section", "aria-live": "polite" });
  view.appendChild(out);

  const read = () => ({ q: input.value.trim(), mode: modeSel.value, near: Number(nearIn.value) || 5, exact: exact.checked, all: allSec.checked,
    docs: docSel.value, code: codeIn.value.trim(), sort: st.sort, offset: 0, meaning: meaning.checked });
  form.addEventListener("submit", (e) => { e.preventDefault(); Object.assign(st, read()); go_(); });

  function addWord(w, shift) {
    let q = input.value.trim();
    if (shift) {
      const m = /"([^"]*)"\s*$/.exec(q);
      q = m ? q.slice(0, m.index) + `"${m[1]} ${w}"` : (q ? q.replace(/(\S+)\s*$/, `"$1 ${w}"`) : `"${w}"`);
    } else if (!q.toLowerCase().split(/\s+/).includes(w.toLowerCase())) {
      q = (q + " " + w).trim();
    }
    input.value = q;
    input.focus();
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

  async function go_() {
    history.replaceState(null, "", hashWith({ q: st.q, mode: st.mode, near: st.mode === "near" ? st.near : "", exact: st.exact, all: st.all, docs: st.docs, code: st.code, sort: st.sort === "doc" ? "" : st.sort, offset: st.offset || "", meaning: st.meaning }));
    if (!st.q) { replace(out, emptyState("text-search", "Type a word to search for", "Every place it occurs in your documents is listed, one line per place. Click a word in a line to add it to the search; Shift-click to make a phrase.")); return; }
    replace(out, h("p", { class: "muted" }, "Searching…"));
    if (st.meaning) return meaningResults();
    let r;
    try { r = await api("GET", `/api/projects/${P(project)}/search?${apiQs({ offset: st.offset, limit: PAGE })}`); }
    catch (e) { replace(out, h("div", { class: "notice notice-error" }, icon("alert-circle"), h("p", {}, e.message))); return; }
    drawLines(r);
  }

  // forms of the words that the search does not find ("commuters" for "commuting"), to add with one click
  function otherForms(forms) {
    return h("div", { class: "other-forms" }, h("span", { class: "muted small" }, "Other forms in the documents, not included: "),
      forms.map((f) => h("button", { type: "button", class: "chip chip-btn", title: `Add “${f.word}” to the search (${f.count} times in the documents)`, onClick: () => { modeSel.value = "any"; nearBox.hidden = true; addWord(f.word, false); Object.assign(st, read()); go_(); } }, "+ ", f.word, " ", h("span", { class: "count" }, String(f.count)))));
  }

  function drawLines(r) {
    clear(out);
    if (!r.total) {
      out.appendChild(emptyState("search-x", "Not found", `No passage ${st.mode === "phrase" ? "has this phrase" : st.mode === "all" ? "has all these words" : st.mode === "near" ? "has these words near each other" : "has these words"}${st.exact ? " exactly" : ""}${st.docs ? " in this document" : ""}. Try other words${st.mode === "any" ? "" : ", fewer words, or “any of the words”"}.`));
      if (r.other_forms && r.other_forms.length) out.appendChild(otherForms(r.other_forms));
      return;
    }
    const sortSel = h("select", { class: "select input-sm", "aria-label": "Sort the lines" }, SORTS.map(([v, t]) => h("option", { value: v, selected: v === st.sort }, t)));
    sortSel.addEventListener("change", () => { st.sort = sortSel.value; st.offset = 0; go_(); });
    out.appendChild(h("div", { class: "section-title", style: { flexWrap: "wrap" } },
      h("h2", {}, `${fmt.plural(r.total, "place")} in ${fmt.plural(r.passages, "passage")} of ${fmt.plural(r.documents, "document")}`),
      h("span", { class: "muted" }, `searched for: ${r.words.join(", ")}`)));
    out.appendChild(h("p", { class: "muted small", style: { margin: "-4px 0 8px" } }, "A passage is the stretch of text the app reads as one unit, up to about 1,100 characters: a few paragraphs together, or part of a long one. “Where” gives the page and paragraph of the original."));
    if (r.rarest && r.words.length > 1) out.appendChild(h("p", { class: "muted small", style: { margin: "-4px 0 8px" } }, `One line for each place of “${r.rarest}”, the rarest of the words, in passages that have all of them; the other words may be further away in the same passage (open it to see them).`));
    if (r.other_forms && r.other_forms.length) out.appendChild(otherForms(r.other_forms));
    // counts per document first
    const perDoc = h("div", { class: "per-doc", role: "group", "aria-label": "Places per document (click to search only that document)" },
      r.per_doc.slice(0, 40).map((d) => h("button", { type: "button", class: "chip chip-btn", "aria-pressed": st.docs === d.doc_id ? "true" : "false", title: d.title,
        onClick: () => { st.docs = st.docs === d.doc_id ? "" : d.doc_id; docSel.value = st.docs; st.offset = 0; go_(); } },
        (d.title || "untitled").slice(0, 48), " ", h("span", { class: "count" }, String(d.hits)))),
      r.per_doc.length > 40 ? h("span", { class: "muted small" }, `and ${r.per_doc.length - 40} more documents`) : null);
    out.appendChild(perDoc);
    const tools = h("div", { class: "pager" },
      h("label", { class: "it" }, "Sort ", sortSel),
      h("div", { class: "btn-row" },
        h("button", { class: "btn btn-sm", type: "button", onClick: () => download(`/api/projects/${P(project)}/search.xlsx?${apiQs()}`).catch(showError) }, icon("download", { size: 13 }), "Excel (.xlsx)"),
        h("button", { class: "btn btn-sm", type: "button", onClick: () => download(`/api/projects/${P(project)}/search.csv?${apiQs()}`).catch(showError) }, icon("download", { size: 13 }), "CSV")));
    out.appendChild(tools);
    const rows = r.lines.map((x) => {
      const node = h("mark", {}, ...wordSpans(x.node, addWord));
      const docHref = `#/doc/${encodeURIComponent(x.doc_id)}?q=${x.start}-${x.end}`;
      const check = h("button", { class: "btn btn-sm btn-ghost", type: "button", title: "Check a hypothesis about what this line says",
        onClick: () => navigate(`#/check?text=${encodeURIComponent(starterSentence(x.left, x.node, x.right))}`) }, icon("flask", { size: 13 }), h("span", { class: "visually-hidden" }, "Check a hypothesis about this"));
      return h("tr", {},
        h("td", { class: "kw-where" }, h("a", { href: docHref, title: `${x.title} · ${x.location}` }, (x.title || "untitled").slice(0, 28)), h("div", {}, x.location)),
        h("td", { class: "kw-left" }, h("span", {}, ...wordSpans(x.left, addWord))),
        h("td", { class: "kw-node" }, node),
        h("td", { class: "kw-right" }, ...wordSpans(x.right, addWord)),
        h("td", { class: "kw-act" }, h("a", { class: "btn btn-sm btn-ghost", href: docHref, title: "Open the document at these words" }, icon("book-open", { size: 13 }), h("span", { class: "visually-hidden" }, "Open the document")), check));
    });
    out.appendChild(h("div", { class: "kwic-wrap" }, h("table", { class: "kwic" }, h("caption", { class: "visually-hidden" }, "Concordance: the words found, with the words before and after"), h("tbody", {}, rows))));
    const pages = h("div", { class: "pager" },
      h("button", { class: "btn btn-sm", type: "button", disabled: st.offset <= 0, onClick: () => { st.offset = Math.max(0, st.offset - PAGE); go_(); window.scrollTo(0, 0); } }, icon("chevron-left", { size: 13 }), "Previous"),
      h("span", { class: "muted small" }, `Lines ${fmt.num(st.offset + 1)}–${fmt.num(st.offset + r.lines.length)} of ${fmt.num(r.total)}`),
      h("button", { class: "btn btn-sm", type: "button", disabled: st.offset + PAGE >= r.total, onClick: () => { st.offset += PAGE; go_(); window.scrollTo(0, 0); } }, "Next", icon("chevron-right", { size: 13 })));
    out.appendChild(pages);
    out.appendChild(h("p", { class: "muted small" }, "Click a word in a line to add it to the search; Shift-click to make a phrase with the words you searched for. ", icon("flask", { size: 12 }), " starts a check of what the line says."));
    // the words around the hits
    const colBox = h("div", { class: "card card-plain", style: { marginTop: "12px" }, hidden: true });
    const colBtn = h("button", { class: "btn btn-sm", type: "button" }, icon("network", { size: 13 }), "Words that often appear nearby");
    const winSel = h("select", { class: "select input-sm", "aria-label": "How many words on each side" }, [2, 3, 5, 8, 10].map((n) => h("option", { value: n, selected: n === 5 }, `${n} words`)));
    const ordSel = h("select", { class: "select input-sm", "aria-label": "Order of the words" }, h("option", { value: "often" }, "most often first"), h("option", { value: "typical" }, "most typical first"));
    const colloc = async () => {
      colBtn.disabled = true;
      colBox.hidden = false;
      replace(colBox, h("p", { class: "muted small" }, "Counting…"));
      try {
        const c = await api("GET", `/api/projects/${P(project)}/collocates?${apiQs({ window: winSel.value, order: ordSel.value })}`);
        replace(colBox, h("h3", { style: { fontSize: "1rem", margin: "0 0 4px" } }, "Words that often appear nearby"),
          h("div", { class: "row", style: { gap: "8px", flexWrap: "wrap", margin: "0 0 6px" } }, h("label", { class: "it" }, "Within ", winSel), h("label", { class: "it" }, "Show ", ordSel)),
          h("p", { class: "muted small", style: { margin: "0 0 8px" } }, `Words within ${c.window} words of the ${fmt.plural(c.hits, "place")} found, seen there at least ${c.min_count} times. The number is how many times. ${ordSel.value === "typical" ? "Most typical first: words found here far more often than elsewhere in the documents." : "Most often first."} Click one to add it to the search.`),
          c.words.length ? h("div", { class: "colloc" }, c.words.map((w) => h("button", { type: "button", class: "chip chip-btn", title: `${w.count} times nearby; ${w.corpus} times in all documents; ${Math.max(1, Math.round(2 ** w.pmi))} times more often nearby than expected`, onClick: () => addWord(w.word, false) }, w.word, " ", h("span", { class: "count" }, `${w.count}`))))
            : h("p", { class: "muted" }, "No word stands out: there are too few places, or the words around them vary."),
          h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("p", { class: "muted small" }, "“Most typical” ranks by pointwise mutual information: how much more often the word appears near the places found than its frequency in all documents would lead you to expect. Point at a word to see both figures. The Excel download has the counts too.")));
      } catch (e) { replace(colBox, h("p", { class: "muted" }, e.message)); }
      colBtn.disabled = false;
    };
    colBtn.addEventListener("click", colloc);
    winSel.addEventListener("change", colloc);
    ordSel.addEventListener("change", colloc);
    out.appendChild(h("div", { class: "btn-row", style: { marginTop: "14px" } }, colBtn));
    out.appendChild(colBox);
  }

  async function meaningResults() {
    let r;
    try { r = await api("GET", `/api/projects/${P(project)}/search?${apiQs({ mode: "meaning", limit: 30 })}`); }
    catch (e) { replace(out, h("div", { class: "notice notice-error" }, icon("alert-circle"), h("p", {}, e.message))); return; }
    clear(out);
    out.appendChild(h("div", { class: "section-title" }, h("h2", {}, `The ${r.passages.length} passages closest in meaning`), h("span", { class: "muted" }, "whole passages, by keywords and meaning together")));
    if (!r.passages.length) { out.appendChild(emptyState("search-x", "Nothing found", "No passage is close to these words.")); return; }
    out.appendChild(h("div", { class: "meaning-list" }, r.passages.map((p) => h("article", { class: "card card-plain" },
      h("div", { class: "row", style: { justifyContent: "space-between" } },
        h("a", { href: `#/doc/${encodeURIComponent(p.doc_id)}?q=${p.start}-${(p.start || 0) + p.text.length}&whole=1` }, h("strong", { class: "serif" }, p.title || "untitled")),
        h("span", { class: "muted small" }, p.location)),
      h("p", { class: "passage serif" }, p.text),
      h("div", { class: "found-words" }, p.found_by === "meaning" ? "Found by meaning: it shares none of the words." : ["Found by the words: ", h("b", {}, (p.matched || []).join(", "))])))));
  }

  input.focus();
  if (st.q) go_(); else replace(out, emptyState("text-search", "Type a word to search for", "Every place it occurs in your documents is listed, one line per place, with the words before and after it. Nothing is sent to an AI."));
}
