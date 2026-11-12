// 0.17.0: the feature finder's index and its scoring. Pure: no imports and no DOM, so the tests load it in Node.
// Not an AI feature: a list of the places, views, features and actions with the words people might type for them,
// matched by plain loops (exact, prefix, keyword, a near-miss spelling, substring) on every keystroke.

// Words a researcher might type for a place or view, by its normalised title.
const KEYWORDS = {
  "bibliography": "zotero references reference citations citation literature bibtex library sources works papers",
  "codes": "tag tags category categories coding code nvivo atlas maxqda codebook profile",
  "codebooks": "codebook codes tag category categories coding nvivo atlas scheme framework own custom",
  "by document": "profile codes coding compare sdg targets topics",
  "concepts": "glossary terms term abbreviations abbreviation acronyms acronym vocabulary words meaning synonyms",
  "themes": "topics topic clusters cluster categories overview grouped subjects",
  "hypotheses": "claim claims statement test verify check evidence results result answers answer supported contradicted several batch spreadsheet excel",
  "answers": "results result answer hypotheses checked evidence quotes review excel download",
  "evidence map": "map heatmap grid matrix evidence overview",
  "notes": "highlight highlights highlighter annotate annotation annotations memo memos comment comments marginalia",
  "research log": "diary journal decision decisions audit trail history record changes versions undo",
  "documents": "upload import add pdf word docx files reports papers web pages sources read corpus",
  "search": "find word phrase keyword lookup passage quote text occurs",
  "overview": "home start dashboard summary",
};

// Other names for the same thing, scored like a word of its title: "zotero" is the Bibliography, however many
// actions mention it.
const NAMES = {
  "bibliography": "zotero", "codebooks": "codebook", "concepts": "glossary", "notes": "highlights annotations",
  "research log": "diary", "answers": "results", "documents": "upload",
};

// Names the app used before 0.17.0 and where they went: [title, place and view now, href, icon].
const OLD_NAMES = {
  "#/history": ["Results", "now Hypotheses › Answers", "#/hypotheses", "history"],
  "#/check": ["Check a hypothesis", "now in Hypotheses", "#/hypotheses", "flask"],
  "#/batch": ["Check several", "now in Hypotheses", "#/hypotheses", "list-checks"],
  "#/profile": ["Profile", "now Codes › By document", "#/profile", "tag"],
};

// [title, where, href, icon, keywords]
export const ACTIONS = [
  ["Add documents", "in Documents", "#/sources", "upload", "upload import pdf word docx files folder zip reports papers"],
  ["Check a hypothesis", "in Hypotheses", "#/hypotheses", "flask", "claim statement test verify evidence support contradict one"],
  ["Check several hypotheses, a list or a spreadsheet", "in Hypotheses", "#/hypotheses", "list-checks", "batch many multiple paste csv excel xlsx claims several"],
  ["Download the results to Excel", "in Hypotheses", "#/hypotheses", "download", "xlsx export spreadsheet save answers table"],
  ["See the evidence map", "in Hypotheses", "#/map", "layers", "map heatmap grid matrix"],
  ["Make a new codebook", "in Codes", "#/codebooks", "plus", "codebook make my own codes categories tags coding scheme create new"],
  ["Profile the documents with a codebook", "in Codes", "#/profile", "tag", "profile codes coding compare sdg targets by document"],
  ["Find themes", "in Themes", "#/themes", "shapes", "topics clusters what the documents are about overview categories"],
  ["Build the glossary of terms", "in Concepts", "#/concepts", "network", "glossary terms abbreviations acronyms concepts vocabulary synonyms"],
  ["Bring in my Zotero library", "in Documents", "#/bibliography", "library", "zotero references citations literature bibtex import collection"],
  ["See my notes and highlights", "in Documents", "#/notes", "highlighter", "highlight annotate annotation memo notes comments"],
  ["Write in the research log", "in Overview", "#/log", "notebook", "diary journal decision audit trail entry record"],
  ["Choose the AI or set up Claude", "in Settings", "#/settings/model", "cloud", "ai model claude anthropic api key local ollama plan subscription backend"],
  ["Work together or share a project", "in Projects", "#/projects", "users", "share colleague team collaborate export import send file together"],
  ["Start a new project", "in Projects", "#/projects", "folder-open", "create project new open switch"],
  ["Open the settings", "in Settings", "#/settings", "sliders", "settings preferences options appearance dark light"],
  ["Copy my link", "in Settings › Technical", "#/settings/link", "link", "bookmark link address url open browser"],
];

const PLACE_WHERE = { explore: "in Explore", check: "in Check hypotheses", record: "in Your notes" };
const STOP = new Set(["the", "a", "an", "to", "of", "my", "me", "i", "and", "or", "for", "in", "on", "at", "is", "it", "do", "does", "how", "can", "want", "what", "with", "you", "your", "this", "that", "some", "all", "from", "by", "be", "we", "us", "our"]);
const KIND_RANK = { place: 0, view: 1, action: 2 };

export function normalise(s) {
  return String(s == null ? "" : s).toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, " ").trim();
}

function tokens(s, minLen = 1) {
  const out = [];
  for (const w of normalise(s).split(" ")) if (w.length >= minLen && out.indexOf(w) < 0) out.push(w);
  return out;
}

function addTokens(into, words) { for (const w of words) if (into.indexOf(w) < 0) into.push(w); }

export function buildIndex({ FEATURES = {}, PLACES = {}, SECTIONS = {} } = {}) {
  const entries = [];
  const byKey = new Map();
  // `desc` holds the words of a feature's text: found, but ranked below title and keyword matches
  const put = (kind, title, where, href, icon, kw, text) => {
    const norm = normalise(title);
    const key = norm + "|" + href;
    let e = byKey.get(key);
    if (e) {
      if (KIND_RANK[kind] < KIND_RANK[e.kind]) { e.kind = kind; e.where = where; e.icon = icon; }
    } else {
      e = { title, where, href, kind, icon, norm, titleWords: tokens(title), words: [], desc: [] };
      byKey.set(key, e);
      entries.push(e);
    }
    if (NAMES[norm] && kind !== "action") addTokens(e.titleWords, tokens(NAMES[norm]));
    addTokens(e.words, tokens(kw || "").concat(tokens(KEYWORDS[norm] || "")));
    if (text) addTokens(e.desc, tokens(text, 4).filter((w) => !STOP.has(w) && e.words.indexOf(w) < 0 && e.titleWords.indexOf(w) < 0));
    return e;
  };

  for (const [pk, p] of Object.entries(PLACES)) {
    put("place", p.title, PLACE_WHERE[p.section] || "in your project", p.href, p.icon, pk, p.what);
    for (const [vk, label, href, ic] of p.views || []) {
      put("view", label, `in ${p.title}`, href, ic, vk, "");
    }
  }
  for (const [fk, f] of Object.entries(FEATURES)) {
    if (f.href == null) continue;
    const old = OLD_NAMES[f.href];
    const text = (f.what || "") + " " + (f.use || "");
    if (old) {
      put("view", old[0], old[1], old[2], old[3] || f.icon, fk, text);
    } else {
      const sec = SECTIONS[f.section];
      put("view", f.title, sec ? `in ${sec.short || sec.title}` : "", f.href, f.icon, fk, text);
    }
  }
  for (const [title, where, href, ic, kw] of ACTIONS) put("action", title, where, href, ic, kw, "");
  for (const e of entries) e.words = e.titleWords.concat(e.words.filter((w) => e.titleWords.indexOf(w) < 0));
  return entries;
}

// Damerau-Levenshtein distance (adjacent swaps count one), giving up above `max`.
export function distance(a, b, max) {
  const la = a.length, lb = b.length;
  if (Math.abs(la - lb) > max) return max + 1;
  let prev2 = new Array(lb + 1), prev = new Array(lb + 1), cur = new Array(lb + 1);
  for (let j = 0; j <= lb; j++) prev[j] = j;
  for (let i = 1; i <= la; i++) {
    cur[0] = i;
    let rowMin = i;
    for (let j = 1; j <= lb; j++) {
      const cost = a.charCodeAt(i - 1) === b.charCodeAt(j - 1) ? 0 : 1;
      let v = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
      if (i > 1 && j > 1 && cost && a.charCodeAt(i - 1) === b.charCodeAt(j - 2) && a.charCodeAt(i - 2) === b.charCodeAt(j - 1)) v = Math.min(v, prev2[j - 2] + 1);
      cur[j] = v;
      if (v < rowMin) rowMin = v;
    }
    if (rowMin > max) return max + 1;
    const t = prev2; prev2 = prev; prev = cur; cur = t;
  }
  return prev[lb];
}

// How well one query word fits an entry: title word 60 (exact) or 50 (prefix), keyword 40 or 34, a near spelling 28
// (title) or 24 (keyword), a substring 12, a word of the description 8 or 5.
function scoreWord(q, e) {
  let best = 0;
  const tw = e.titleWords;
  for (let i = 0; i < tw.length; i++) {
    if (tw[i] === q) return 60;
    if (tw[i].startsWith(q) && best < 50) best = 50;
  }
  const kw = e.words;
  for (let i = 0; i < kw.length; i++) {
    if (kw[i] === q) { if (best < 40) best = 40; }
    else if (kw[i].startsWith(q) && best < 34) best = 34;
  }
  if (best) return best;
  if (q.length >= 4) {
    const max = q.length >= 7 ? 2 : 1;
    for (let i = 0; i < kw.length; i++) {
      if (kw[i].length < 4) continue;
      if (distance(q, kw[i], max) <= max) { const s = i < tw.length ? 28 : 24; if (s > best) best = s; }
    }
    if (best) return best;
  }
  if (q.length >= 3) {
    for (let i = 0; i < kw.length; i++) if (kw[i].indexOf(q) >= 0) return 12;
  }
  const d = e.desc;
  for (let i = 0; i < d.length; i++) {
    if (d[i] === q) return 8;
    if (q.length >= 3 && d[i].startsWith(q)) best = 5;
  }
  return best;
}

export function findFeatures(query, index, { limit = 8 } = {}) {
  const norm = normalise(query);
  if (!norm) return index.filter((e) => e.kind === "place").slice(0, limit);
  let qw = norm.split(" ");
  const kept = qw.filter((w) => !STOP.has(w));
  if (kept.length) qw = kept;
  const scored = [];
  for (let i = 0; i < index.length; i++) {
    const e = index[i];
    let s = 0, hit = 0;
    for (let k = 0; k < qw.length; k++) {
      const w = scoreWord(qw[k], e);
      if (w) { s += w; hit++; }
    }
    if (!hit) continue;
    if (hit === qw.length && qw.length > 1) s += 10;
    if (e.norm === norm) s += 1000;
    else if (e.norm.startsWith(norm)) s += 300;
    scored.push({ e, s, i });
  }
  scored.sort((a, b) => b.s - a.s || KIND_RANK[a.e.kind] - KIND_RANK[b.e.kind] || a.i - b.i);
  const out = [];
  for (let i = 0; i < scored.length && out.length < limit; i++) out.push(scored[i].e);
  return out;
}
