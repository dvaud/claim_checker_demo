// D1: the concept map, a view of Concepts (Glossary | Map). The concepts mentioned in the most passages, joined when
// the documents mention two together more often than by chance (PMI, not raw counts), in groups found from those
// joins, with the links you and the AI accepted drawn in their type. Filters (documents, a theme, a code, years) narrow
// the passages counted. A concept opens its page; a line shows the passages that join its two concepts. The same map
// is given as lists under it (docs/DESIGN.md 8). Rules and layout: conceptmap.py; routes: gui/api_corpus.py.
import { featureEyebrow, viewTabs } from "../features.js";
import { App, api, h, P, replace, clear, showError, failedLoad, noDocuments, addDocumentsFirst, fmt, pageHead, emptyState, plural, shortTitle, button, link, notice, card, select, field, fold } from "../lib.js";

const NS = "http://www.w3.org/2000/svg";
const ASPECT = 1.6;                        // conceptmap.ASPECT: the layout's width over its height
const GROUPS_COLOURED = 5;                 // groups 1 to 5 have a colour and a shape; the others are grey circles
const SHAPES = ["circle", "circle", "square", "diamond", "triangle", "hexagon"];   // by group (0: none or past 5)
const SHAPE_WORDS = { circle: "circle", square: "square", diamond: "diamond", triangle: "triangle", hexagon: "hexagon" };
// a link as drawn: its kind, and whether it runs from a to b (false: from b to a)
const REL = { narrower: ["part", true], broader: ["part", false], effect: ["leads", true], effect_of: ["leads", false],
  replaces: ["replaces", true], replaced_by: ["replaces", false], related: ["related", true] };
const REL_WORDS = { part: "is part of", leads: "leads to", replaces: "is used instead of", related: "is related to" };
const SOURCE_WORDS = { person: "added or accepted by you", meaning: "accepted by you", model: "judged by the AI",
  abbreviation: "an abbreviation in the documents", pattern: "found in the text, accepted" };
const SIZES = [30, 60, 100, 150];
const FILTER_KEYS = ["doc", "theme", "framework", "code", "year_from", "year_to", "n"];

const conceptHref = (id) => `#/concepts/${encodeURIComponent(id)}`;
const docHref = (b) => `#/doc/${encodeURIComponent(b.doc_id)}?q=${b.start}-${b.start + 1}`;
const times = (pmi) => (2 ** pmi).toFixed(pmi < 3.33 ? 1 : 0);   // PMI in base 2 as "times as often as by chance"

// an SVG element (h() makes HTML ones)
function s(tag, attrs = {}, ...kids) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else el.setAttribute(k, String(v));
  }
  for (const c of kids.flat()) if (c !== null && c !== undefined && c !== false) el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
}

const groupOf = (g) => (g && g <= GROUPS_COLOURED ? g : 0);

// a group's mark: its colour (a class of views.css, from the --group-* tokens) and its shape
function mark(g, x, y, r) {
  const k = groupOf(g);
  const cls = `cm-mark cm-g${k}`;
  const shape = SHAPES[k];
  if (shape === "square") { const a = r * 0.9; return s("rect", { class: cls, x: x - a, y: y - a, width: 2 * a, height: 2 * a, rx: 1.5 }); }
  const poly = (pts) => s("polygon", { class: cls, points: pts.map(([px, py]) => `${(x + px).toFixed(1)},${(y + py).toFixed(1)}`).join(" ") });
  if (shape === "diamond") return poly([[0, -r * 1.25], [r * 1.25, 0], [0, r * 1.25], [-r * 1.25, 0]]);
  if (shape === "triangle") return poly([[0, -r * 1.3], [r * 1.15, r * 0.75], [-r * 1.15, r * 0.75]]);
  if (shape === "hexagon") return poly([0, 1, 2, 3, 4, 5].map((i) => [r * 1.1 * Math.cos(Math.PI / 3 * i), r * 1.1 * Math.sin(Math.PI / 3 * i)]));
  return s("circle", { class: cls, cx: x, cy: y, r });
}
const swatch = (g) => s("svg", { class: "cm-swatch", viewBox: "0 0 16 16", width: 16, height: 16, "aria-hidden": "true" }, mark(g, 8, 8, 5.5));

function passageItem(b) {
  return h("li", {}, h("span", { class: "serif" }, "“", shortTitle(b.text || b.quote || "", 260), "” "),
    b.doc_id ? link({ href: docHref(b), class: "small" }, `${b.title || "a document"}${b.location ? `, ${b.location}` : b.page ? `, p. ${b.page}` : ""}`) : null);
}

// Where each concept's name goes: beside its mark, else on its left, above or below it, wherever it overlaps no other
// name and no mark; the concepts in the most passages first. A name with no room is hidden until its concept is
// pointed at or focused. (Widths are guessed from the number of letters: no text is measured.)
const LABEL_LETTERS = 28;
function placeLabels(marks, W, H) {
  const taken = marks.map((A) => [A.x - A.r - 1, A.y - A.r - 1, A.x + A.r + 1, A.y + A.r + 1]);
  const free = (b, own) => b[0] >= 2 && b[2] <= W - 2 && b[1] >= 2 && b[3] <= H - 2 &&
    taken.every((t, k) => k === own || b[2] <= t[0] || b[0] >= t[2] || b[3] <= t[1] || b[1] >= t[3]);
  const out = [];
  for (const A of marks) {
    const text = shortTitle(A.n.label, LABEL_LETTERS);
    const w = text.length * 6.6 + 2, hh = 13;
    const ways = [
      { x: A.x + A.r + 4, y: A.y + 4, anchor: "start", box: [A.x + A.r + 3, A.y - hh / 2 - 1, A.x + A.r + 4 + w, A.y + hh / 2 + 1] },
      { x: A.x - A.r - 4, y: A.y + 4, anchor: "end", box: [A.x - A.r - 4 - w, A.y - hh / 2 - 1, A.x - A.r - 3, A.y + hh / 2 + 1] },
      { x: A.x, y: A.y - A.r - 5, anchor: "middle", box: [A.x - w / 2, A.y - A.r - 4 - hh, A.x + w / 2, A.y - A.r - 2] },
      { x: A.x, y: A.y + A.r + 13, anchor: "middle", box: [A.x - w / 2, A.y + A.r + 2, A.x + w / 2, A.y + A.r + 4 + hh] },
    ];
    const way = ways.find((c) => free(c.box, A.i));
    if (way) taken.push(way.box);
    out[A.i] = { ...(way || ways[0]), text, shown: !!way };
  }
  // room(box): whether a link's words fit there too (then they take it)
  const room = (b) => { if (!free(b, -1)) return false; taken.push(b); return true; };
  return { labels: out, room };
}

export async function renderConceptMap(view, params, query) {
  const project = App.project;
  const base = `/api/projects/${P(project)}`;
  view.appendChild(pageHead("Concepts", { eyebrow: featureEyebrow("concepts"), sub: "The concepts the documents mention together more often than by chance, in groups, with the links you accepted." }));
  view.appendChild(viewTabs("concepts", "conceptmap"));
  if (noDocuments()) { view.appendChild(addDocumentsFirst("The concept map")); return; }

  const f = {};
  for (const k of FILTER_KEYS) if (query[k]) f[k] = String(query[k]);
  const filtersBox = h("div", { class: "cm-filters", role: "group", "aria-label": "What the map counts" });
  const factsBox = h("div");
  const mapBox = h("div", { "aria-busy": "false" });
  const detailBox = h("div", { "aria-live": "polite" });
  const listBox = h("div");
  view.append(filtersBox, factsBox, mapBox, detailBox, listBox);

  let opts;
  try { opts = await api("GET", `${base}/concept-map/options`); } catch (e) { failedLoad(mapBox, e); return; }

  // a filter whose value is not in this project (a link from another project) is dropped
  const docIds = new Set(opts.documents.map((d) => d.doc_id));
  if (f.doc && !f.doc.split(",").every((d) => docIds.has(d))) delete f.doc;
  const themeIds = new Set((opts.themes.themes || []).map((t) => `${opts.themes.run_id}:${t.theme_id}`));
  if (f.theme && !themeIds.has(f.theme)) delete f.theme;
  const fws = new Map(opts.codebooks.map((c) => [c.name, c]));
  if (f.framework && !fws.has(f.framework)) { delete f.framework; delete f.code; }

  function keepUrl() {
    const q = new URLSearchParams();
    for (const k of FILTER_KEYS) if (f[k]) q.set(k, f[k]);
    const qs = q.toString();
    history.replaceState(null, "", "#/concept-map" + (qs ? "?" + qs : ""));
  }
  const qs = () => { const q = new URLSearchParams(); for (const k of FILTER_KEYS) if (f[k]) q.set(k, f[k]); return q.toString(); };

  // ---- the filters ----
  function opt(value, words, chosen) { return h("option", { value, selected: chosen }, words); }
  function drawFilters() {
    clear(filtersBox);
    const onPick = (key, extra) => (e) => { const v = e.currentTarget.value; if (v) f[key] = v; else delete f[key]; if (extra) extra(v); keepUrl(); drawFilters(); load(); };
    const docSel = select({}, opt("", "All documents", !f.doc), opts.documents.map((d) => opt(d.doc_id, shortTitle(d.title || d.doc_id, 60), f.doc === d.doc_id)));
    docSel.addEventListener("change", onPick("doc"));
    filtersBox.appendChild(field("Documents", docSel));
    if (opts.themes.themes.length) {
      const thSel = select({}, opt("", "Every passage", !f.theme), opts.themes.themes.map((t) => opt(`${opts.themes.run_id}:${t.theme_id}`, shortTitle(t.name, 50), f.theme === `${opts.themes.run_id}:${t.theme_id}`)));
      thSel.addEventListener("change", onPick("theme"));
      filtersBox.appendChild(field("Theme", thSel));
    }
    if (opts.codebooks.length) {
      const cbSel = select({}, opt("", "No code", !f.framework), opts.codebooks.map((c) => opt(c.name, shortTitle(c.title, 40), f.framework === c.name)));
      cbSel.addEventListener("change", onPick("framework", () => { delete f.code; }));
      filtersBox.appendChild(field("Codebook", cbSel));
      const cb = fws.get(f.framework);
      if (cb) {
        const codeSel = select({}, opt("", "Choose a code", !f.code), cb.codes.map((c) => opt(c.code, shortTitle(c.description ? `${c.code} ${c.description}` : c.code, 60), f.code === c.code)));
        codeSel.addEventListener("change", onPick("code"));
        filtersBox.appendChild(field("Code", codeSel));
      }
    }
    if (opts.years.length) {
      const yFrom = select({}, opt("", "Any year", !f.year_from), opts.years.map((y) => opt(String(y), String(y), f.year_from === String(y))));
      yFrom.addEventListener("change", onPick("year_from"));
      const yTo = select({}, opt("", "Any year", !f.year_to), opts.years.map((y) => opt(String(y), String(y), f.year_to === String(y))));
      yTo.addEventListener("change", onPick("year_to"));
      filtersBox.append(field("Published from", yFrom), field("Published until", yTo));
    }
    const nSel = select({}, SIZES.map((n) => opt(String(n), `${n} concepts`, (Number(f.n) || 60) === n)));
    nSel.addEventListener("change", (e) => { f.n = e.currentTarget.value === "60" ? "" : e.currentTarget.value; if (!f.n) delete f.n; keepUrl(); load(); });
    filtersBox.appendChild(field("Concepts on the map", nSel));
  }

  // ---- the map ----
  let m = null;
  let seq = 0;
  let lastWidth = 0;
  async function load() {
    const my = ++seq;
    mapBox.setAttribute("aria-busy", "true");
    let r;
    try { r = await api("GET", `${base}/concept-map?${qs()}`); }
    catch (e) { if (my === seq) { failedLoad(mapBox, e); mapBox.setAttribute("aria-busy", "false"); } return; }
    if (my !== seq) return;
    mapBox.setAttribute("aria-busy", "false");
    m = r;
    clear(detailBox);
    draw();
  }

  const filtered = () => ["doc", "theme", "code", "year_from", "year_to"].some((k) => f[k]);
  function draw() {
    clear(factsBox); clear(mapBox); clear(listBox);
    if (!m.built) {
      filtersBox.hidden = true;
      mapBox.appendChild(emptyState("network", "No glossary yet", "The map is drawn from the glossary: the terms your documents use, grouped into concepts. Make the glossary first; it is made on this computer and nothing is sent anywhere.",
        link({ kind: "next", href: "#/concepts" }, "Make the glossary on the Glossary tab")));
      return;
    }
    filtersBox.hidden = false;
    if (!m.nodes.length) {
      mapBox.appendChild(emptyState("search-x", "Nothing to draw", filtered()
        ? "No concept is mentioned in two passages or more within these filters. Choose fewer filters."
        : "No concept of the glossary is mentioned in two passages or more."));
      return;
    }
    factsBox.appendChild(h("p", { class: "muted small cm-facts" },
      `${m.nodes.length < m.concepts_in_scope ? `The ${m.nodes.length} of ${fmt.num(m.concepts_in_scope)} concepts mentioned in the most passages` : plural(m.nodes.length, "concept")}, counted in ${plural(m.passages, "passage")}${filtered() ? " within these filters" : ""}. Theory and working documents are left out.`,
      m.links_off_map ? ` ${plural(m.links_off_map, "link")} you accepted ${m.links_off_map === 1 ? "joins" : "join"} a concept not on the map.` : ""));
    if (!m.edges.length && !m.links.length) {
      factsBox.appendChild(notice({ kind: "info", class: "cm-note" }, h("p", {}, "No two of these concepts are mentioned together often enough to be joined (in two passages or more, more often than by chance).")));
    }
    mapBox.appendChild(card({ class: "section cm-card", "aria-label": "The concept map" }, legend(), h("div", { class: "cm-svg-wrap" }, svgMap())));
    drawLists();
  }

  function legend() {
    const kinds = [...new Set(m.links.map((lk) => (REL[lk.relation] || ["related"])[0]))];
    return h("div", { class: "cm-legend" },
      h("ul", { class: "cm-keys", "aria-label": "Groups" },
        m.groups.map((g) => h("li", { class: "cm-key" }, swatch(g.group),
          h("span", {}, h("strong", {}, `Group ${g.group}`), ` ${g.names.join(", ")}${g.size > g.names.length ? "…" : ""}`))),
        m.nodes.some((n) => !n.group) ? h("li", { class: "cm-key" }, swatch(0), h("span", { class: "muted" }, "In no group")) : null,
        m.groups.length > GROUPS_COLOURED ? h("li", { class: "cm-key muted" }, `Groups ${GROUPS_COLOURED + 1} and on are grey circles too: the lists below say which.`) : null),
      h("p", { class: "muted small cm-how" }, "A line: the two are mentioned together more often than by chance (the thicker, the more). ",
        kinds.length ? `An arrow or a darker line with words: a link you accepted (${kinds.map((k) => REL_WORDS[k]).join(", ")}). ` : "",
        "Choose a concept to open it; choose a line to see the passages that join the two."));
  }

  function svgMap() {
    const wrapW = Math.max(320, Math.min(1200, mapBox.clientWidth || view.clientWidth || 900));
    lastWidth = wrapW;
    // the map is laid out ASPECT times as wide as high; a narrow page turns it a quarter round when that makes it taller,
    // and its height follows what it holds, so the groups stay round and no band is left empty
    const narrow = wrapW < 600;
    const W = wrapW;
    const padX = narrow ? 24 : 56, padY = 28;
    const span = (k) => Math.max(...m.nodes.map((n) => n[k])) - Math.min(...m.nodes.map((n) => n[k]));
    const turn = narrow && span("x") * ASPECT > span("y");   // only when turning makes it taller
    const pts = m.nodes.map((n) => (turn ? [n.y, n.x * ASPECT] : [n.x * ASPECT, n.y]));
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const x0 = Math.min(...xs), y0 = Math.min(...ys);
    const xr = Math.max(...xs) - x0 || 1, yr = Math.max(...ys) - y0 || 1;
    let scale = (W - 2 * padX) / xr;
    const H = Math.round(Math.min(yr * scale + 2 * padY, W * (narrow ? 2.2 : 0.9)));
    scale = Math.min(scale, (H - 2 * padY) / yr);
    const offX = (W - xr * scale) / 2;
    const maxP = Math.max(...m.nodes.map((n) => n.passages));
    const maxPmi = Math.max(1, ...m.edges.map((e) => e.pmi));
    const at = {};
    m.nodes.forEach((n, i) => {
      at[n.id] = { x: offX + (pts[i][0] - x0) * scale, y: padY + (pts[i][1] - y0) * scale, r: 4 + 8 * Math.sqrt(n.passages / maxP), i, n };
    });
    const { labels, room } = placeLabels(m.nodes.map((n) => at[n.id]), W, H);
    const near = {};   // node id -> set of ids joined to it
    const join = (a, b) => { (near[a] = near[a] || new Set()).add(b); (near[b] = near[b] || new Set()).add(a); };
    m.edges.forEach((e) => join(e.a, e.b));
    m.links.forEach((lk) => join(lk.a, lk.b));

    const svg = s("svg", { class: "cm-svg", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "group",
      "aria-label": `A map of ${plural(m.nodes.length, "concept")} in ${plural(m.groups.length, "group")}. The same map is given as lists below it.` });
    svg.appendChild(s("defs", {}, s("marker", { id: "cm-arrow", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" },
      s("path", { class: "cm-arrow", d: "M0,0 L10,5 L0,10 z" }))));
    const edgesG = s("g", { class: "cm-edges" });
    const linksG = s("g", { class: "cm-links" });
    const nodesG = s("g", { class: "cm-nodes" });
    svg.append(edgesG, linksG, nodesG);

    // a line from the edge of one mark to the edge of the other
    const ends = (a, b, gapA = 2, gapB = 2) => {
      const A = at[a], B = at[b];
      const dx = B.x - A.x, dy = B.y - A.y, d = Math.hypot(dx, dy) || 1;
      return { x1: A.x + dx / d * (A.r + gapA), y1: A.y + dy / d * (A.r + gapA), x2: B.x - dx / d * (B.r + gapB), y2: B.y - dy / d * (B.r + gapB) };
    };
    const linked = new Set(m.links.map((lk) => [lk.a, lk.b].sort().join("|")));
    for (const e of m.edges) {
      if (linked.has([e.a, e.b].sort().join("|"))) continue;   // the link is drawn instead, and says both
      const p = ends(e.a, e.b);
      const title = `${at[e.a].n.label} and ${at[e.b].n.label}: mentioned together in ${plural(e.together, "passage")}, ${times(e.pmi)} times as often as by chance`;
      edgesG.appendChild(s("g", { class: "cm-pair", "data-a": e.a, "data-b": e.b },
        s("line", { class: "cm-edge", ...p, "stroke-width": (0.8 + 2.7 * e.pmi / maxPmi).toFixed(2) }),
        s("line", { class: "cm-hit", ...p, onClick: () => showEdge(e.a, e.b) }, s("title", {}, title))));
    }
    for (const lk of m.links) {
      const [kind, forward] = REL[lk.relation] || ["related", true];
      const [from, to] = forward ? [lk.a, lk.b] : [lk.b, lk.a];
      const p = ends(from, to, 2, kind === "related" ? 2 : 4);
      const words = REL_WORDS[kind];
      const title = `${at[from].n.label} ${words} ${at[to].n.label} (${SOURCE_WORDS[lk.source] || lk.source})`;
      const mx = (p.x1 + p.x2) / 2, my = (p.y1 + p.y2) / 2;
      linksG.appendChild(s("g", { class: "cm-pair", "data-a": lk.a, "data-b": lk.b },
        s("line", { class: "cm-link", ...p, "marker-end": kind === "related" ? null : "url(#cm-arrow)" }),
        s("text", { class: "cm-rel", x: mx.toFixed(1), y: (my - 4).toFixed(1), "text-anchor": "middle",
          "data-hidden": room([mx - words.length * 3.1, my - 15, mx + words.length * 3.1, my - 1]) ? null : "true" }, words),
        s("line", { class: "cm-hit", ...p, onClick: () => showEdge(lk.a, lk.b) }, s("title", {}, title))));
    }
    const focus = (id) => {
      if (!id) { delete svg.dataset.focus; svg.querySelectorAll("[data-near]").forEach((el) => el.removeAttribute("data-near")); return; }
      svg.dataset.focus = "true";
      const ns = near[id] || new Set();
      nodesG.querySelectorAll(".cm-node").forEach((el) => { if (el.dataset.id === id || ns.has(el.dataset.id)) el.dataset.near = "true"; else el.removeAttribute("data-near"); });
      svg.querySelectorAll(".cm-pair").forEach((el) => { if (el.dataset.a === id || el.dataset.b === id) el.dataset.near = "true"; else el.removeAttribute("data-near"); });
    };
    // the larger marks last, so they lie on top; their labels too
    for (const n of [...m.nodes].reverse()) {
      const A = at[n.id];
      const g = n.group ? `group ${n.group}` : "in no group";
      const a = s("a", { class: "cm-node", href: conceptHref(n.id), "data-id": n.id,
        "aria-label": `${n.label}: ${plural(n.passages, "passage")}, ${g}${(near[n.id] || new Set()).size ? `, joined to ${plural(near[n.id].size, "concept")}` : ""}` },
        s("title", {}, `${n.label} · ${plural(n.passages, "passage")} · ${g}`),
        mark(n.group, A.x, A.y, A.r),
        s("text", { class: "cm-label", x: labels[A.i].x.toFixed(1), y: labels[A.i].y.toFixed(1),
          "text-anchor": labels[A.i].anchor, "data-hidden": labels[A.i].shown ? null : "true" }, labels[A.i].text));
      a.addEventListener("mouseenter", () => focus(n.id));
      a.addEventListener("mouseleave", () => focus(null));
      a.addEventListener("focus", () => focus(n.id));
      a.addEventListener("blur", () => focus(null));
      nodesG.appendChild(a);
    }
    return svg;
  }

  // ---- one line of the map: its link, how often together, the passages ----
  async function showEdge(a, b) {
    const q = new URLSearchParams(qs());
    q.set("a", a); q.set("b", b);
    let r;
    try { r = await api("GET", `${base}/concept-map/edge?${q}`); } catch (e) { showError(e); return; }
    const A = link({ kind: "title", serif: true, href: conceptHref(r.a.node) }, r.a.label);
    const B = link({ kind: "title", serif: true, href: conceptHref(r.b.node) }, r.b.label);
    let linkLine = null;
    if (r.link) {
      const [kind, forward] = REL[r.link.relation] || ["related", true];
      const [x, y] = forward ? [r.a.label, r.b.label] : [r.b.label, r.a.label];
      linkLine = h("div", { class: "cm-detail-part" }, h("p", {}, h("strong", {}, `${x} ${REL_WORDS[kind]} ${y}`), h("span", { class: "muted" }, ` · ${SOURCE_WORDS[r.link.source] || r.link.source}`)),
        (r.link.sentences || []).length ? h("ul", { class: "ct-quotes" }, r.link.sentences.map(passageItem)) : null);
    }
    const together = r.together
      ? h("p", {}, `Mentioned together in ${plural(r.together, "passage")}${filtered() ? " within these filters" : ""}`, r.pmi !== null && r.pmi > 0 ? `, ${times(r.pmi)} times as often as by chance` : r.pmi !== null ? ", no more often than by chance" : "", ".")
      : h("p", { class: "muted" }, `No passage${filtered() ? " within these filters" : ""} mentions both.`);
    replace(detailBox, card({ class: "section cm-detail", title: h("span", {}, A, " and ", B), titleId: "cm-detail-h", level: "h2" },
      linkLine, together,
      r.passages.length ? h("ul", { class: "ct-quotes" }, r.passages.map(passageItem)) : null,
      r.together > r.passages.length ? h("p", { class: "muted small" }, `The first ${r.passages.length} of ${r.together}, by document.`) : null));
    detailBox.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  // ---- the same map as lists (docs/DESIGN.md 8) ----
  function drawLists() {
    const lab = Object.fromEntries(m.nodes.map((n) => [n.id, n.label]));
    const nameLink = (id) => link({ kind: "title", serif: true, href: conceptHref(id) }, lab[id]);
    const groupRows = [...m.groups.map((g) => [`Group ${g.group}`, g.group, m.nodes.filter((n) => n.group === g.group)]),
      ["In no group", 0, m.nodes.filter((n) => !n.group)]].filter((x) => x[2].length);
    const groupsTable = h("div", { class: "table-wrap" }, h("table", { class: "table table-responsive cm-groups" },
      h("caption", { class: "visually-hidden" }, "The groups of concepts"),
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Group"), h("th", { scope: "col" }, "Concepts, with their passages"))),
      h("tbody", {}, groupRows.map(([name, g, ns]) => h("tr", {},
        h("td", { "data-label": "Group" }, h("span", { class: "cm-group-name" }, swatch(g), name),
          g && g > GROUPS_COLOURED ? null : h("span", { class: "visually-hidden" }, ` (${SHAPE_WORDS[SHAPES[groupOf(g)]]})`)),
        h("td", { "data-label": "Concepts" }, ns.map((n, i) => [i ? ", " : null, nameLink(n.id), h("span", { class: "muted small" }, ` ${fmt.num(n.passages)}`)])))))));
    const pairButton = (a, b) => button({ sm: true, kind: "quiet", onClick: () => showEdge(a, b) }, "Show the passages");
    const pairsTable = m.edges.length ? h("div", { class: "table-wrap" }, h("table", { class: "table table-responsive cm-pairs" },
      h("caption", { class: "visually-hidden" }, "Concepts mentioned together more often than by chance"),
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Concepts"), h("th", { scope: "col", class: "num" }, "Passages together"), h("th", { scope: "col", class: "num" }, "Times as often as by chance"), h("th", { scope: "col" }, h("span", { class: "visually-hidden" }, "Passages")))),
      h("tbody", {}, m.edges.map((e) => h("tr", {},
        h("td", { "data-label": "Concepts" }, nameLink(e.a), " and ", nameLink(e.b)),
        h("td", { class: "num", "data-label": "Passages together" }, fmt.num(e.together)),
        h("td", { class: "num", "data-label": "Times as often as by chance" }, times(e.pmi)),
        h("td", {}, pairButton(e.a, e.b))))))) : h("p", { class: "muted" }, "No two concepts are mentioned together often enough to be joined.");
    const linksList = m.links.length ? h("ul", { class: "cm-link-list" }, m.links.map((lk) => {
      const [kind, forward] = REL[lk.relation] || ["related", true];
      const [x, y] = forward ? [lk.a, lk.b] : [lk.b, lk.a];
      return h("li", {}, nameLink(x), ` ${REL_WORDS[kind]} `, nameLink(y), h("span", { class: "muted small" }, ` · ${SOURCE_WORDS[lk.source] || lk.source} `), pairButton(lk.a, lk.b));
    })) : h("p", { class: "muted" }, "No link you accepted joins two concepts on the map. Accept or add links on a concept’s page.");
    listBox.appendChild(fold({ class: "section", open: false }, "The map as lists",
      h("h3", { class: "cm-list-h" }, "Groups"), groupsTable,
      h("h3", { class: "cm-list-h" }, "Mentioned together"), pairsTable,
      h("h3", { class: "cm-list-h" }, "Your links"), linksList));
  }

  drawFilters();
  await load();
  // a new width draws the map again (the marks keep their size, so a narrow window gets a taller map)
  let timer = null;
  const ro = new ResizeObserver(() => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (!m || !m.nodes || !m.nodes.length) return;
      const w = mapBox.clientWidth;
      if (Math.abs(w - lastWidth) < 40) return;
      const wrap = mapBox.querySelector(".cm-svg-wrap");
      if (wrap) replace(wrap, svgMap());
    }, 200);
  });
  ro.observe(mapBox);
  return () => { ro.disconnect(); clearTimeout(timer); };
}
