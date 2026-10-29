// Evidence map: hypotheses as rows, documents as columns, each cell the side a document takes on a hypothesis
// (judgements that count at the strictness; a person's always count), with symbols as well as colours.
import { App, api, h, icon, replace, clear, showError, download, pageHead, statusBadge, emptyState, P, strictness } from "../lib.js";

const SIDE = {
  supports: { symbol: "+", word: "supports", cls: "m-sup", icon: "circle-check" },
  partly: { symbol: "(+)", word: "partly supports", cls: "m-part", icon: "circle-half" },
  refutes: { symbol: "−", word: "contradicts", cls: "m-ref", icon: "circle-x" },
  both: { symbol: "±", word: "both supports and contradicts", cls: "m-both", icon: "arrows-opposed" },
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
  const xlsx = h("button", { class: "btn btn-sm", type: "button", onClick: () => download(`/api/projects/${P(project)}/export.xlsx?threshold=${threshold}`).catch(showError) }, icon("download", { size: 13 }), "Download for Excel (.xlsx)");
  view.appendChild(pageHead("Evidence map", {
    sub: `Which documents are behind which answers in project “${project}”: one row per hypothesis, one column per document that has an excerpt that counts.`,
    actions: [h("a", { class: "btn btn-sm", href: batch ? `#/history?batch=${encodeURIComponent(batch)}` : "#/history" }, icon("history", { size: 13 }), batch ? "Back to the set" : "All results"), xlsx],
  }));
  if (batch) view.appendChild(h("div", { class: "batch-banner", style: { marginBottom: "12px" } }, icon("list-checks", { size: 14 }), h("span", {}, `Showing the ${hyps.length} ${hyps.length === 1 ? "hypothesis" : "hypotheses"} of one set checked together.`), h("a", { class: "btn btn-sm btn-ghost", href: "#/map" }, "Show all results")));

  if (!hyps.length) {
    view.appendChild(emptyState("layers", "Nothing to map yet", "Check a hypothesis and it appears here with the documents behind its answer.", h("a", { class: "btn btn-primary", href: "#/check" }, "Check a hypothesis")));
    return;
  }

  const legend = h("div", { class: "map-legend", role: "list", "aria-label": "What the symbols mean" },
    Object.entries(SIDE).map(([k, s]) => h("span", { class: `map-key ${s.cls}`, role: "listitem" }, h("span", { class: "map-sym" }, s.symbol), ` ${s.word}`)),
    h("span", { class: "map-key", role: "listitem" }, h("span", { class: "map-sym" }, "·"), " no excerpt that counts"),
    h("span", { class: "muted small", role: "listitem" }, `The number is how many excerpts count. Judgements the AI was at least ${Math.round(threshold * 100)}% sure of count (${strictness(threshold)}); your own always count.`));
  view.appendChild(legend);

  const single = hyps.filter((x) => x.single_document).length;
  const key = docs.filter((d) => d.key);
  const notes = [];
  if (single) notes.push(h("p", {}, icon("alert-triangle", { size: 13 }), ` ${single === 1 ? "1 answer rests" : `${single} answers rest`} on one document only (marked “rests on one document”): a second source would make ${single === 1 ? "it" : "them"} more solid.`));
  if (key.length) notes.push(h("p", {}, icon("star", { size: 13 }), ` ${key.length === 1 ? "1 document is a key document" : `${key.length} documents are key documents`} (marked “decides N answers”): leaving it out would change those answers, so it deserves a careful read.`));
  if (m.documents_without_evidence) notes.push(h("p", { class: "muted" }, `${m.documents_without_evidence} ${m.documents_without_evidence === 1 ? "document has" : "documents have"} no excerpt that counts in any answer, so ${m.documents_without_evidence === 1 ? "it is" : "they are"} not shown as a column.`));
  if (notes.length) view.appendChild(h("div", { class: "map-notes" }, notes));

  // ---- the grid
  const short = (t) => { t = (t || "untitled").replace(/\s+/g, " ").trim(); return t.length > 60 ? t.slice(0, 58).trimEnd() + "…" : t; };
  const table = h("table", { class: "map-table" });
  const thead = h("thead", {}, h("tr", {},
    h("th", { scope: "col", class: "map-hyp-head" }, "Hypothesis"),
    docs.map((d) => h("th", { scope: "col", class: "map-doc-head" + (d.key ? " map-key-doc" : "") },
      h("a", { href: `#/doc/${encodeURIComponent(d.doc_id)}`, title: `${d.title || "untitled"} · ${d.answers} ${d.answers === 1 ? "answer rests" : "answers rest"} on it${d.decides ? ` · decides ${d.decides}` : ""}${d.in_project === false ? " · removed from the project since" : ""}` },
        h("span", { class: "map-doc-title" }, short(d.title)),
        d.key ? h("span", { class: "map-flag" }, icon("star", { size: 11 }), ` decides ${d.decides} ${d.decides === 1 ? "answer" : "answers"}`) : d.decides ? h("span", { class: "map-flag muted" }, `decides ${d.decides}`) : null,
        d.in_project === false ? h("span", { class: "map-flag muted" }, "removed since") : null),
      d.in_project === false ? null : h("button", { class: "btn btn-sm btn-ghost map-doc-dl", type: "button", title: `Download ${d.title || "the document"} with the quotes of these answers highlighted`, "aria-label": `Highlighted copy of ${short(d.title)}`,
        onClick: (e) => { e.stopPropagation(); download(`/api/projects/${P(project)}/documents/${P(d.doc_id)}/annotated.pdf?${new URLSearchParams({ hyp: hyps.map((x) => x.hyp_id).join(","), threshold: String(threshold) })}`).catch(showError); } },
        icon("download", { size: 11 }), "highlighted")))));
  const tbody = h("tbody", {}, hyps.map((x) => {
    const href = `#/h/${encodeURIComponent(x.hyp_id)}`;
    const row = cells[x.hyp_id] || {};
    return h("tr", { class: "row-link", onClick: (e) => { if (e.target.closest("a")) return; location.hash = href; } },
      h("th", { scope: "row", class: "map-hyp" },
        h("a", { href, class: "serif" }, x.text),
        h("div", { class: "map-hyp-meta" }, statusBadge(x.status, { short: true, text: x.status_text }),
          x.single_document ? h("span", { class: "warn-chip" }, icon("alert-triangle", { size: 11 }), "rests on one document") : null,
          x.docs_counted ? h("span", { class: "muted small" }, `${x.docs_counted} ${x.docs_counted === 1 ? "document" : "documents"}`) : h("span", { class: "muted small" }, "no document counts"))),
      docs.map((d) => {
        const c = row[d.doc_id];
        if (!c) return h("td", { class: "map-cell m-none" }, h("span", { class: "visually-hidden" }, `${short(d.title)}: no excerpt that counts`), h("span", { "aria-hidden": "true" }, "·"));
        const s = SIDE[c.side] || SIDE.supports;
        return h("td", { class: `map-cell ${s.cls}`, title: `${d.title || "untitled"} ${s.word} “${x.text}”: ${c.excerpts} ${c.excerpts === 1 ? "excerpt" : "excerpts"} that ${c.excerpts === 1 ? "counts" : "count"}` },
          h("span", { class: "visually-hidden" }, `${short(d.title)}: ${s.word}, ${c.excerpts} ${c.excerpts === 1 ? "excerpt" : "excerpts"}`),
          h("span", { class: "map-mark", "aria-hidden": "true" }, h("span", { class: "map-sym" }, s.symbol), h("span", { class: "map-n" }, String(c.excerpts))));
      }));
  }));
  table.append(h("caption", { class: "visually-hidden" }, "Evidence map: hypotheses by documents"), thead, tbody);
  view.appendChild(h("p", { class: "muted small map-scroll-hint", style: { margin: "0 0 6px" } }, icon("arrow-right", { size: 12 }), " The grid scrolls sideways: drag or swipe it to see every document."));
  view.appendChild(h("div", { class: "map-wrap", tabindex: "0", role: "region", "aria-label": "Evidence map grid (scrolls sideways)" }, table));
  view.appendChild(h("p", { class: "muted small", style: { marginTop: "10px" } }, "Click a hypothesis to open its result, or a document title to open the document; “highlighted” downloads it with the quotes marked. The Excel download of all results has this map as a sheet called “Map”."));
}
