// Evidence map: hypotheses as rows, documents as columns, each cell the side a document takes on a hypothesis
// (judgements that count at the strictness; a person's always count), with symbols as well as colours. 0.17.0: a view
// of the Hypotheses page (its tab beside Answers), with the page's head. 0.18.8 (roadmap K3): a document marked
// Non-scientific is shown too, its cells with a mark of their own (the symbol with no fill and a dashed edge: read, not
// counted); they change no count or answer. Where a hypothesis counts them (its own setting), its cells are as any.
import { featureEyebrow, viewTabs } from "../features.js";
import { App, api, h, icon, showError, download, pageHead, statusBadge, emptyState, P, strictness, shortTitle, downloadLinks, link, iconButton, tag, notice, heatGrid, store, navigate } from "../lib.js";

const SIDE = {
  supports: { symbol: "+", word: "supports", cls: "m-sup" },
  partly: { symbol: "(+)", word: "partly supports", cls: "m-part" },
  refutes: { symbol: "−", word: "contradicts", cls: "m-ref" },
  both: { symbol: "±", word: "both supports and contradicts", cls: "m-both" },
};

export async function renderMap(view, params, query) {
  const project = App.project;
  const batch = query.batch || "";
  const threshold = App.settings().threshold ?? 0.6;
  const qs = new URLSearchParams({ threshold: String(threshold) });
  if (batch) qs.set("batch", batch);
  let m;
  try { m = await api("GET", `/api/projects/${P(project)}/map?${qs}`); } catch (e) { showError(e); m = { hypotheses: [], documents: [], cells: {} }; }
  const hyps = m.hypotheses || [], docs = m.documents || [], cells = m.cells || {};
  // 0.13.3: the download is a quiet link, as on the result page
  const xlsx = downloadLinks([{ text: "Excel (.xlsx)", title: "Three sheets: a summary, every excerpt read, and this map", onClick: () => download(`/api/projects/${P(project)}/export.xlsx?threshold=${threshold}`).catch(showError) }]);
  view.appendChild(pageHead("Hypotheses", {
    eyebrow: featureEyebrow("check"),
    sub: "Which documents are behind which answers: one row per hypothesis, one column per document with an excerpt that counts.",
    actions: xlsx,
  }));
  // the tabs of the place; the answers of one set stay one set when you go back to them
  const tabs = viewTabs("hypotheses", "map");
  if (tabs) {
    const answersTab = tabs.querySelector('a[href="#/hypotheses"]');
    if (answersTab && batch) answersTab.setAttribute("href", `#/hypotheses?batch=${encodeURIComponent(batch)}`);
    view.appendChild(tabs);
  }
  if (batch) view.appendChild(notice({ kind: "info", icon: "list-checks", class: "map-batch" }, h("p", {}, `Showing the ${hyps.length} ${hyps.length === 1 ? "hypothesis" : "hypotheses"} of one set checked together. `, link({ kind: "back", href: "#/map" }, "Show all hypotheses"))));

  if (!hyps.length) {
    view.appendChild(emptyState("layers", "Nothing to map yet", "Check a hypothesis and it appears here with the documents behind its answer.", link({ kind: "next", href: "#/hypotheses" }, "Check a hypothesis")));
    return;
  }

  const legend = h("div", { class: "map-legend", role: "list", "aria-label": "What the symbols mean" },
    Object.entries(SIDE).map(([k, s]) => h("span", { class: `map-key ${s.cls}`, role: "listitem" }, h("span", { class: "map-sym" }, s.symbol), ` ${s.word}`)),
    h("span", { class: "map-key", role: "listitem" }, h("span", { class: "map-sym" }, "·"), " no excerpt that counts"),
    docs.some((d) => d.nonscientific) ? h("span", { class: "map-key m-nonsci", role: "listitem" }, h("span", { class: "map-sym" }, "+"), " Non-scientific: read, not counted") : null,
    h("span", { class: "muted small", role: "listitem" }, `The number is how many excerpts count. Judgements the AI was at least ${Math.round(threshold * 100)}% sure of count (${strictness(threshold)}); your own always count.`));
  view.appendChild(legend);

  const single = hyps.filter((x) => x.single_document).length;
  const key = docs.filter((d) => d.key);
  const notes = [];
  if (single) notes.push(h("p", {}, icon("info", { size: 13 }), ` ${single === 1 ? "1 answer rests" : `${single} answers rest`} on one document only (marked “rests on one document”): a second source would make ${single === 1 ? "it" : "them"} more solid.`));
  if (key.length) notes.push(h("p", {}, icon("star", { size: 13 }), ` ${key.length === 1 ? "1 document is a key document" : `${key.length} documents are key documents`} (marked “decides N answers”): leaving it out would change those answers, so it deserves a careful read.`));
  if (m.nonscientific_shown) notes.push(h("p", {}, icon("newspaper", { size: 13 }), ` ${m.nonscientific_shown === 1 ? "1 document is" : `${m.nonscientific_shown} documents are`} marked non-scientific: what ${m.nonscientific_shown === 1 ? "it says is" : "they say is"} shown with a dashed edge, read and not counted, so ${m.nonscientific_shown === 1 ? "it changes" : "they change"} no answer here.`));
  if (m.documents_without_evidence) notes.push(h("p", { class: "muted" }, `${m.documents_without_evidence} ${m.documents_without_evidence === 1 ? "document has" : "documents have"} no excerpt that counts in any answer, so ${m.documents_without_evidence === 1 ? "it is" : "they are"} not shown as a column.`,
    // roadmap N5: the Documents list, grouped by the answers behind them, with those behind none open
    " ", link({ kind: "jump", onClick: () => {
      const fk = `docs-folded:${project}`;
      store(fk, (store(fk) || "").split(",").filter((x) => x && x !== "answers:unused").join(","));
      store(`docs-group:${project}`, "answers");
      navigate("#/sources");
    } }, "Show them in Documents")));
  if (notes.length) view.appendChild(h("div", { class: "map-notes" }, notes));

  // ---- the grid
  const short = (t) => shortTitle(t, 60);
  const table = h("table", { class: "map-table" });
  const thead = h("thead", {}, h("tr", {},
    h("th", { scope: "col", class: "map-hyp-head" }, "Hypothesis"),
    docs.map((d) => h("th", { scope: "col", class: "map-doc-head" },
      link({ kind: "title", serif: true, href: `#/doc/${encodeURIComponent(d.doc_id)}`, title: `${d.title || "untitled"} · ${d.answers} ${d.answers === 1 ? "answer rests" : "answers rest"} on it${d.decides ? ` · decides ${d.decides}` : ""}${d.nonscientific ? " · non-scientific: read, not counted (except where a hypothesis counts them)" : ""}${d.in_project === false ? " · removed from the project since" : ""}` },
        h("span", { class: "map-doc-title" }, short(d.title)),
        // a key document: a fact about it (a tag with the star), not something that needs you
        d.key ? tag({ icon: "star", class: "map-flag" }, `decides ${d.decides} ${d.decides === 1 ? "answer" : "answers"}`) : d.decides ? h("span", { class: "map-flag-text" }, `decides ${d.decides} ${d.decides === 1 ? "answer" : "answers"}`) : null,
        d.nonscientific ? h("span", { class: "map-flag-text" }, "non-scientific") : null,   // 0.18.8 (K3)
        d.in_project === false ? h("span", { class: "map-flag-text" }, "removed since") : null),
      d.in_project === false ? null : iconButton({ icon: "download", sm: true, size: 13, class: "map-doc-dl", label: `Download ${short(d.title)} as a PDF with the quotes highlighted`, title: "Download this PDF with the quotes highlighted",
        onClick: (e) => { e.stopPropagation(); download(`/api/projects/${P(project)}/documents/${P(d.doc_id)}/annotated.pdf?${new URLSearchParams({ hyp: hyps.map((x) => x.hyp_id).join(","), threshold: String(threshold) })}`).catch(showError); } })))));
  const tbody = h("tbody", {}, hyps.map((x) => {
    const href = `#/h/${encodeURIComponent(x.hyp_id)}`;
    const row = cells[x.hyp_id] || {};
    return h("tr", { class: "row-link", onClick: (e) => { if (e.target.closest("a")) return; location.hash = href; } },
      h("th", { scope: "row", class: "map-hyp" },
        link({ kind: "title", href, serif: true }, x.text),
        h("div", { class: "map-hyp-meta" }, statusBadge(x.status, { short: true, text: x.status_text }),
          x.single_document ? tag({ icon: "info" }, "rests on one document") : null,
          x.count_nonscientific ? tag({ icon: "newspaper", title: "This hypothesis counts non-scientific documents (set on its page): they are the material it is about" }, "counts non-scientific") : null,
          x.docs_counted ? h("span", { class: "muted small" }, `${x.docs_counted} ${x.docs_counted === 1 ? "document" : "documents"}`) : h("span", { class: "muted small" }, "no document counts"))),
      docs.map((d) => {
        const c = row[d.doc_id];
        if (!c) return h("td", { class: "map-cell m-none" }, h("span", { class: "visually-hidden" }, `${short(d.title)}: no excerpt that counts`), h("span", { "aria-hidden": "true" }, "·"));
        const s = SIDE[c.side] || SIDE.supports;
        // 0.18.8 (K3): a non-scientific document's cell: read, not counted (its own mark); or counted by the exception
        if (c.counted === false) return h("td", { class: `map-cell ${s.cls} m-nonsci`, title: `${d.title || "untitled"} ${s.word} “${x.text}”: ${c.excerpts} ${c.excerpts === 1 ? "excerpt" : "excerpts"}, not counted (a non-scientific document)` },
          h("span", { class: "visually-hidden" }, `${short(d.title)}: ${s.word}, ${c.excerpts} ${c.excerpts === 1 ? "excerpt" : "excerpts"}, non-scientific, not counted`),
          h("span", { class: "map-mark", "aria-hidden": "true" }, h("span", { class: "map-sym" }, s.symbol), h("span", { class: "map-n" }, String(c.excerpts))));
        return h("td", { class: `map-cell ${s.cls}`, title: `${d.title || "untitled"} ${s.word} “${x.text}”: ${c.excerpts} ${c.excerpts === 1 ? "excerpt" : "excerpts"} that ${c.excerpts === 1 ? "counts" : "count"}${c.nonscientific ? " (a non-scientific document, counted in this check as set on the hypothesis)" : ""}` },
          h("span", { class: "visually-hidden" }, `${short(d.title)}: ${s.word}, ${c.excerpts} ${c.excerpts === 1 ? "excerpt" : "excerpts"}`),
          h("span", { class: "map-mark", "aria-hidden": "true" }, h("span", { class: "map-sym" }, s.symbol), h("span", { class: "map-n" }, String(c.excerpts))));
      }));
  }));
  table.append(h("caption", { class: "visually-hidden" }, "Evidence map: hypotheses by documents"), thead, tbody);
  view.appendChild(heatGrid(table, { label: "Evidence map", unit: "documents" }));
  view.appendChild(h("p", { class: "muted small map-help" }, "Click a hypothesis to open its result, or a document title to open the document; the download arrow under a document title gives its PDF with the quotes marked. The Excel download of all answers has this map as a sheet called “Map”."));
}
