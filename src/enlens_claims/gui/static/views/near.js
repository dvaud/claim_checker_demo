// Near-duplicate hypotheses (0.18, roadmap N1), under the Hypotheses page's box. The server compares the lines by
// their key words, without AI (nearduplicates.py, POST …/hypotheses/similar); this draws what it found, as offers that
// never block a check:
// - lines of a list that say nearly the same: "Lines 1 and 2 are very close: check them as one?", with a menu that
//   keeps the line you pick and drops the others (dropLines), or keeps them all;
// - lines that are close but claim something different (one says "indicates", the other "predicts"; one is negated):
//   one quiet line says so, and no merge is offered: both are checked;
// - a hypothesis checked before in the project, yours or a colleague's that came in through sync: "You checked a very
//   similar one on 3 Nov: “…”", or "Anna checked…", with a link to its answer. Check then checks anyway.
import { h, icon, notice, menu, link, fmt, shortTitle, norm } from "../lib.js";

const SHOWN = 3;   // offers of each kind drawn; the rest are counted

// "Line 2", "Lines 1 and 2", "Lines 1, 2 and 4" (n: 0-based)
export function linesWords(ns) {
  const w = ns.map((i) => String(i + 1));
  if (w.length === 1) return `Line ${w[0]}`;
  return `Lines ${w.slice(0, -1).join(", ")} and ${w[w.length - 1]}`;
}

// The groups of lines that say nearly the same and claim the same (pairs whose `differ` is empty, joined when they
// share a line): [[0, 1], [3, 5, 6]], each in the list's order. apart: the groups of lines that are close but claim
// different things instead.
export function clusters(pairs, apart = false) {
  const up = new Map();
  const top = (i) => { while (up.has(i) && up.get(i) !== i) i = up.get(i); return i; };
  for (const p of pairs || []) {
    if (!!(p.differ && p.differ.length) !== apart) continue;
    for (const i of [p.a, p.b]) if (!up.has(i)) up.set(i, i);
    const a = top(p.a), b = top(p.b);
    if (a !== b) up.set(Math.max(a, b), Math.min(a, b));
  }
  const groups = new Map();
  for (const i of [...up.keys()].sort((x, y) => x - y)) {
    const t = top(i);
    if (!groups.has(t)) groups.set(t, []);
    groups.get(t).push(i);
  }
  return [...groups.values()];
}

// Whether the server's answer has anything to say about these lines.
export function saysSomething(res) {
  return !!res && (clusters(res.pairs).length > 0 || (res.before || []).some((b) => b && b.length));
}

// The box's text without the lines of `drop` (indexes of `items`, the list as the server read it), or null when a
// line cannot be told for sure. A plain list: the items are its lines that are not empty and do not start with #, in
// order (claimcheck.parse_batch). A CSV: the one row whose text holds the item's.
export function dropLines(text, items, drop) {
  const lines = String(text || "").split(/\r?\n/);
  const plain = [];
  lines.forEach((l, i) => { const t = norm(l); if (t && !t.startsWith("#")) plain.push(i); });
  const isPlain = plain.length === items.length && plain.every((li, k) => norm(lines[li]) === items[k].text);
  const at = (k) => {
    if (isPlain) return plain[k];
    const hits = [];
    lines.forEach((l, i) => { if (i > 0 && items[k] && norm(l).includes(items[k].text)) hits.push(i); });
    return hits.length === 1 ? hits[0] : -1;
  };
  const gone = new Set();
  for (const k of drop) {
    const i = at(k);
    if (i < 0) return null;
    gone.add(i);
  }
  return lines.filter((_, i) => !gone.has(i)).join("\n");
}

// Who checked a hypothesis before, as the sentence begins: "You checked a very similar one on 3 Nov", "Anna checked
// this one on 3 Nov", "A very similar one was checked…" (nobody known); in a list's line (many), not capitalised.
function checkedBy(b, line, many) {
  const when = b.created_at ? ` on ${fmt.dateShort(b.created_at)}` : "";
  const same = norm(b.text).toLowerCase() === norm(line).toLowerCase();
  const what = same ? "this one" : "a very similar one";
  const who = b.who ? (b.who.mine ? "you" : b.who.name) : null;
  const s = who ? `${who} checked ${what}${when}` : `${what} was checked${when}`;
  return many ? s : s[0].toUpperCase() + s.slice(1);
}

// The offers, as elements to put under the box. res: the server's answer; lines: the texts it was about; list: a list
// (lines are named by number); onKeep(keep, group): keep line `keep` of `group` and drop the others.
export function nearNotices(res, { lines = [], list = false, onKeep = null } = {}) {
  if (!res) return [];
  const out = [];
  const groups = list ? clusters(res.pairs) : [];
  for (const g of groups.slice(0, SHOWN)) {
    const items = g.map((i) => ({ text: `Keep line ${i + 1}`, meta: shortTitle(lines[i], 60), title: lines[i], onClick: () => onKeep && onKeep(i, g) }));
    out.push(notice({ kind: "info", icon: "merge", class: "hyp-near-notice" },
      h("p", {}, `${linesWords(g)} are very close: check them as one?`),
      onKeep ? menu({ text: "Check as one", label: `Check ${linesWords(g).toLowerCase()} as one`, items: [...items, "sep", { text: g.length === 2 ? "Check both" : "Check them all" }] }) : null));
  }
  if (groups.length > SHOWN) out.push(h("p", { class: "muted small hyp-near-more" }, `${groups.length - SHOWN} more groups of lines are very close.`));
  // close but claiming different things: one quiet line a group ("Lines 1, 2 and 3 are close but say “observable”,
  // “indicate” and “predicted”: each is checked"); a line already offered as one with another is left out
  const offered = new Set(groups.flat());
  const apartPairs = list ? (res.pairs || []).filter((p) => p.differ && p.differ.length && !(offered.has(p.a) && offered.has(p.b))) : [];
  for (const g of clusters(apartPairs, true).slice(0, SHOWN)) {
    const said = new Map();   // line -> its word, as the pairs name them (a negation names one word for the pair)
    for (const p of apartPairs) {
      if (!g.includes(p.a)) continue;
      if (p.differ.length === 2) { if (!said.has(p.a)) said.set(p.a, p.differ[0]); if (!said.has(p.b)) said.set(p.b, p.differ[1]); }
    }
    const words = [...new Set(g.filter((i) => said.has(i)).map((i) => said.get(i)))].map((w) => `“${w}”`);
    const negation = apartPairs.find((p) => g.includes(p.a) && p.differ.length === 1);
    const says = words.length >= 2 ? `say ${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}` : `one says “${negation ? negation.differ[0] : "not"}”`;
    out.push(h("p", { class: "muted small hyp-near-apart" }, icon("info", { size: 12 }), ` ${linesWords(g)} are close but ${says}: ${g.length === 2 ? "both are" : "each is"} checked.`));
  }
  const before = (res.before || []).map((b, i) => [i, (b || [])[0]]).filter(([, b]) => b);
  for (const [i, b] of before.slice(0, SHOWN)) {
    const lead = list ? `${linesWords([i])} — ${checkedBy(b, lines[i], true)}` : checkedBy(b, lines[i], false);
    out.push(notice({ kind: "info", icon: "history", class: "hyp-near-notice" },
      h("p", {}, `${lead}: `, h("span", { class: "serif" }, `“${shortTitle(b.text, 140)}”`)),
      link({ href: `#/h/${encodeURIComponent(b.hyp_id)}` }, "Open its answer")));
  }
  if (before.length > SHOWN) out.push(h("p", { class: "muted small hyp-near-more" }, `${before.length - SHOWN} more lines were checked before in a very similar form.`));
  return out;
}
