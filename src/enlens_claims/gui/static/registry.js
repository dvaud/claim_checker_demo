// 0.13.6: the page's extension points (docs/EXTENDING.md). An add-on's page module (static/extensions.js in a fork,
// static/addons/<add-on>/extensions.js in a package) adds to these lists with applyExtensions(); ENLENS's own entries
// are here too, so the sidebar's jobs, the Overview and the result page read one list each.
// No imports: the tests load this file in Node.

// Jobs in the sidebar: where a job's row links to, its icon and its name. `withJob`: the link carries ?job=<id>, so
// the page follows that job. `label(j, text)`: the row's words when they are more than the kind's name; `tooltip`:
// the row's tooltip adds the job's own title when the row's words leave it out.
// 0.15.6: every row has a tooltip, its whole name: the sidebar cuts a long name short ("Reading an ex…").
// 0.17.0: checks, sets of checks and the answers' own jobs link to Hypotheses (their old pages are part of it).
export const JOB_KINDS = {
  check: { icon: "flask", text: "Check", link: "#/hypotheses", withJob: true, tooltip: true, label: (j) => j.title || "Check" },
  prepare: { icon: "eye", text: "Look before checking", link: "#/hypotheses", tooltip: true, label: (j, t) => `${t}${j.title ? ` (${j.title})` : ""}` },
  batch: { icon: "list-checks", text: "Several hypotheses", link: "#/hypotheses", withJob: true, tooltip: true, label: (j, t) => `${t}${j.title ? ` (${j.title})` : ""}` },
  more: { icon: "search", text: "More evidence", link: "#/hypotheses", withJob: true },
  reread: { icon: "refresh", text: "Reading an excerpt again", link: "#/hypotheses" },
  "read-new": { icon: "book-open", text: "Reading the new documents", link: "#/hypotheses", withJob: true, label: (j, t) => j.title || t },
  "second-opinion": { icon: "cpu", text: "Second opinion", link: "#/hypotheses", withJob: true,
    label: (j, t) => `${t}${/ on (\d+ hypothes\w+)$/.test(j.title || "") ? ` (${/ on (\d+ hypothes\w+)$/.exec(j.title)[1]})` : ""}` },
  ingest: { icon: "upload", text: "Adding documents", link: "#/sources" },
  index: { icon: "network", text: "Search by meaning set-up", link: "#/sources" },
  benchmark: { icon: "cpu", text: "Model test", link: "#/settings/test" },
  keywords: { icon: "tag", text: "Codes by keywords", link: "#/profile" },
  label: { icon: "tag", text: "The AI labels passages", link: "#/profile" },
  "label-compare": { icon: "scale", text: "Comparing labels", link: "#/profile" },
  terms: { icon: "network", text: "Building the glossary", link: "#/concepts" },
  link: { icon: "network", text: "The AI relates concepts", link: "#/concepts" },
  wordings: { icon: "network", text: "Other wordings", link: "#/concepts" },
  themes: { icon: "shapes", text: "Finding themes", link: "#/themes" },
  "theme-names": { icon: "shapes", text: "Naming themes", link: "#/themes" },
  // a new theme in place of a removed one; its scope is the set of themes
  "theme-new": { icon: "shapes", text: "Finding a new theme", link: (j) => (j.scope ? `#/themes/${encodeURIComponent(j.scope)}` : "#/themes") },
  resolve: { icon: "link", text: "Following references", link: "#/sources" },
  quicklook: { icon: "eye", text: "Quick look", link: "#/sources" },
  "claude-install": { icon: "download", text: "Installing Claude Code", link: "#/settings/model" },
  "model-pull": { icon: "download", text: "Downloading a model", link: "#/settings/model" },   // 0.13.7
  "ollama-install": { icon: "download", text: "Installing Ollama", link: "#/settings/model" },   // 0.15.6
  bibliography: { icon: "library", text: "Bringing in the bibliography", link: "#/bibliography" },
};

// A job's row: {href, icon, text, tooltip}. A kind no one registered shows its own title (an add-on's job).
export function jobRow(j) {
  const k = JOB_KINDS[j.kind];
  if (!k) return { href: "#/overview", icon: "circle", text: j.title || j.kind, tooltip: j.title || j.kind };
  const text = k.label ? k.label(j, k.text) : k.text;
  const link = typeof k.link === "function" ? k.link(j) : k.link;  // a link may depend on the job (its scope)
  return { href: link + (k.withJob ? `?job=${encodeURIComponent(j.id)}` : ""), icon: k.icon, text,
    tooltip: k.tooltip && j.title && !text.includes(j.title) ? `${text}: ${j.title}` : text };
}

// Pages an add-on adds: [pattern, the sidebar entry it lights up, render(view, groups, query)], after ENLENS's own.
export const PAGE_ROUTES = [];

// Cards on the welcome screen (first run): {icon, title, text}.
export const WELCOME_CARDS = [];

// Where a hypothesis comes from (its `origin`): the result page links back to it. `eyebrow`: the link above the
// hypothesis (in place of "All results"); `meta`: the words in the line under it; `href(id)`.
export const ORIGINS = {
  batch: { meta: "part of a set", href: (id) => `#/hypotheses?batch=${encodeURIComponent(id)}` },   // 0.17.0: the answers are on Hypotheses
};

// The back-link of a result: {eyebrow, meta, href} or null. A batch from before 0.13.6 has a batch id and no origin.
export function originLink(r) {
  const key = r.origin && ORIGINS[r.origin] ? r.origin : (r.batch_id ? "batch" : null);
  if (!key) return null;
  const o = ORIGINS[key];
  const id = key === r.origin ? (r.origin_id || r.batch_id || "") : r.batch_id;
  return { eyebrow: o.eyebrow || null, meta: o.meta || null, href: o.href(id) };
}

// The Overview's sections, in SECTIONS' order: each with the features that show a card there, in FEATURES' order
// (a feature's `overview.order` moves it). A feature shows in its own section, or in `overview.section`;
// `overview: false` keeps it off the Overview. Sections without a card are left out.
export function overviewSections(FEATURES, SECTIONS) {
  const keys = Object.keys(FEATURES);
  return Object.keys(SECTIONS).map((s) => ({
    key: s, title: SECTIONS[s].title, sub: SECTIONS[s].sub || "", compact: !!SECTIONS[s].compact,
    features: keys.filter((k) => FEATURES[k].overview !== false && ((FEATURES[k].overview || {}).section || FEATURES[k].section) === s)
      .map((k, i) => [k, (FEATURES[k].overview || {}).order ?? keys.indexOf(k)])
      .sort((a, b) => a[1] - b[1]).map(([k]) => k),
  })).filter((s) => s.features.length);
}

// What a page module adds. `ext` is its default export: an object, or a function returning one. Every part is
// optional:
//   sections: {key: {title, short, sub, compact}}            new parts of the app (sidebar group, Overview section)
//   features: {key: {section, title, icon, href, ai, what, use, nav, overview, state(o)}}
//   routes:   [[RegExp, featureKey, render(view, groups, query)]]
//   jobKinds: {kind: {icon, text, link (a hash, or link(j) from the job), withJob, tooltip, label(j, text)}}
//   welcome:  [{icon, title, text}]
//   origins:  {origin: {eyebrow, meta, href(id)}}
// It never replaces one of ENLENS's entries; returns the keys it added, by list.
export function applyExtensions(ext, { FEATURES, SECTIONS }) {
  const e = typeof ext === "function" ? ext() : ext;
  const added = { sections: [], features: [], routes: 0, jobKinds: [], welcome: 0, origins: [] };
  if (!e || typeof e !== "object") return added;
  const merge = (into, from, name) => {
    for (const [k, v] of Object.entries(from || {})) {
      if (!(k in into) && v && typeof v === "object") { into[k] = v; added[name].push(k); }
    }
  };
  merge(SECTIONS, e.sections, "sections");
  merge(FEATURES, e.features, "features");
  merge(JOB_KINDS, e.jobKinds, "jobKinds");
  merge(ORIGINS, e.origins, "origins");
  for (const r of e.routes || []) {
    if (Array.isArray(r) && r[0] instanceof RegExp && typeof r[2] === "function") { PAGE_ROUTES.push(r); added.routes++; }
  }
  for (const c of e.welcome || []) {
    if (c && c.title) { WELCOME_CARDS.push(c); added.welcome++; }
  }
  return added;
}
