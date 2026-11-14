// 0.18 (roadmap L2): what the Team tab and the Documents page say about the project's owner and the proposals that
// wait for the owner, worked out from GET …/owner (gui/api_owner.py, ownership.view) without touching the page. Its
// only import is team-state.js, which has none, so it also runs in Node for the tests. owner.js draws it.
//
// The view: {owner: {id, name, me} | null, me, is_owner, since, how, can_claim, can_take_over: words | null,
// accept_adds, people: [{id, name, me, owner}], proposals: [{id, kind, severity, doc, title, what, by: {id, name, me},
// at, state, note, reason, decided_by, decided_at, auto, mine, can_decide, can_take_back, here, conflicts, detail}]
// (newest first), waiting, to_apply: [{doc, title, kind, note, can_force}], documents: {doc id: {state, text}}, job}.
// Roles (DESIGN-roles §7 P1, the fields this page reads; each may be missing in an older answer, read as empty):
// role ("owner" | "co" | "member"), can_write, can_set_roles; people[] + role, same_as, needs_update; questions:
// [{id, seq, kind: "founder" | "takeover" | "other", owner, by, why, now}]; offers: [{doc, title, from, to, by}];
// removed: [{doc, title, at, by, why, cause, until}]; clashes: [{id, kind: "part" | "answer", doc, title, part,
// events, counts, people, …}]; refused: [{kind, key, via, title, owner, at}]; notices: [{kind, text}];
// proposals[] + clash: {accepted: [people], declined: [people]} | null. A person is {id, name, me} or a bare id.
import { whenText } from "./team-state.js";

export const OWNER_API = {
  view: (p) => `/api/projects/${p}/owner`,                                   // GET
  claim: (p) => `/api/projects/${p}/owner/claim`,                            // POST {}
  handOver: (p) => `/api/projects/${p}/owner/hand-over`,                     // POST {to, why?}
  takeOver: (p) => `/api/projects/${p}/owner/take-over`,                     // POST {why?}
  settings: (p) => `/api/projects/${p}/owner/settings`,                      // PUT {accept_adds}
  apply: (p) => `/api/projects/${p}/owner/apply`,                            // POST {doc, force?}
  accept: (p, id) => `/api/projects/${p}/owner/proposals/${id}/accept`,      // POST {reason?}
  decline: (p, id) => `/api/projects/${p}/owner/proposals/${id}/decline`,    // POST {reason?}
  takeBack: (p, id) => `/api/projects/${p}/owner/proposals/${id}/take-back`, // POST {}
  // roles (DESIGN-roles §7 P4)
  role: (p, person) => `/api/projects/${p}/owner/roles/${person}`,           // PUT {role} | {same_as}
  question: (p, id) => `/api/projects/${p}/owner/questions/${id}`,           // POST {answer: "follow" | "keep" | "later"}
  loosening: (p) => `/api/projects/${p}/owner/loosening`,                    // POST {docs, allow}
  restore: (p, doc) => `/api/projects/${p}/owner/removed/${doc}/restore`,    // POST {}
  clash: (p, id) => `/api/projects/${p}/owner/clashes/${id}`,                // POST {} (Leave it so)
  takeProjectBack: (p) => `/api/projects/${p}/owner/take-back`,              // POST {}
  dismiss: (p, kind, key) => `/api/projects/${p}/owner/refused/${kind}/${key}/dismiss`,   // POST {}
  codebookOffer: (p, cb) => `/api/projects/${p}/codebooks/${cb}/offer`,      // GET
  codebookFollow: (p, cb) => `/api/projects/${p}/codebooks/${cb}/follow`,    // POST {follow}
};

// who may read a document with AI (the titles of views/ai-access.js LEVEL)
export const LEVEL_WORDS = { cloud: "Claude may read it", local: "Only a local AI", none: "No AI" };
export const ANSWERED_SHOWN = 10;

const nameOf = (person, fallback = "a colleague") => (person && (person.me ? "you" : person.name)) || fallback;
const plural = (n, one, many) => `${n} ${n === 1 ? one : many || one + "s"}`;

// The owner in a sentence: "you", "Anna de Vries", or "the owner" (not known)
export function ownerName(v) {
  return v && v.owner ? nameOf(v.owner, "the owner") : "the owner";
}

// Whether the Team tab shows the section: with a shared folder always; without one (a team working with zips), once
// the project has an owner on record, has none and could have one, or something waits. A project never exchanged has
// nothing to say there.
export function sectionShown(v, hasFolder) {
  if (!v) return false;
  return !!(hasFolder || v.since || v.can_claim || (v.proposals || []).length || (v.to_apply || []).length || v.job);
}

// The proposals in their places: `cards` wait (newest first); `declined` are this person's own declined ones not
// marked as seen (shown first, open, so "Declined: …" is read once); `answered` the latest others, for the fold.
export function splitProposals(v, seen = new Set()) {
  const all = (v && v.proposals) || [];
  const cards = all.filter((p) => p.state === "waiting");
  const declined = all.filter((p) => p.state === "declined" && p.mine && !seen.has(p.id));
  const rest = all.filter((p) => p.state !== "waiting" && !declined.includes(p));
  return { cards, declined, answered: rest.slice(0, ANSWERED_SHOWN), answeredTotal: rest.length };
}

// The section's heading: "Waiting for your word (3)": what waits for this person, whatever their role (DESIGN-roles §5.2)
export function heading(v, n = 0) {
  if (v && v.can_claim) return "No owner yet";
  return n ? `Waiting for your word (${n})` : "Waiting for your word";
}

// A Member's own proposals that wait (and, for anyone who cannot answer them, a colleague's): their own section
export function mineHeading(list) {
  const n = list.length;
  return list.every((p) => p.mine) ? `Your proposals (${n})` : `Proposals that wait (${n})`;
}

// The number on the Team tab: the cards that wait for this person's word (a question put off with Not now in this
// browser no longer counts), and their own proposals declined and not seen yet.
export function tabCount(v, seen = new Set()) {
  if (!v) return 0;
  return inbox(v, seen).count + splitProposals(v, seen).declined.length;
}

// "Ben Okafor proposes" / "You propose"
export function proposer(p) {
  const by = p.by || {};
  return by.me ? { who: "You", verb: "propose" } : { who: by.name || "A colleague", verb: "proposes" };
}

// `what` in three parts around the document's title in quotes, so the title can be a link:
// "removing “Annual report 2024” from the project" -> {before: "removing ", title: "Annual report 2024", after: " from the project"}
export function whatParts(what) {
  const s = String(what || "");
  const a = s.indexOf("“"), z = s.lastIndexOf("”");
  if (a < 0 || z <= a) return { before: s, title: null, after: "" };
  return { before: s.slice(0, a), title: s.slice(a + 1, z), after: s.slice(z + 1) };
}

// "2 passages left out, 1 restored." (+ where the text starts or ends)
export function blocksLine(d) {
  const bits = [];
  if (d.left_out) bits.push(`${plural(d.left_out, "passage")} left out`);
  if (d.restored) bits.push(bits.length ? `${d.restored} restored` : `${plural(d.restored, "passage")} restored`);
  if (d.undone) bits.push(`${bits.length ? d.undone : plural(d.undone, "passage")} back as the reader reads ${d.undone === 1 ? "it" : "them"}`);
  const out = bits.length ? [`${bits.join(", ")}.`] : [];
  if (d.bounds) out.push("Where the text starts or ends was changed.");
  // 0.18.1 (K2): a document marked as theory (the lens the research is read through), or as evidence again
  // 0.19.0 (N3): or as a working document (the researcher's own draft or notes, never a source)
  if (d.role) out.push(d.role === "evidence" ? "Marked as evidence again." : d.role === "working" ? "Marked as a working document: never a source, left out of themes, check excerpts, key terms and the corpus’s code counts." : "Marked as theory: left out of themes, codebook labels, check excerpts and key terms.");
  // 0.18.6: a document marked Non-scientific (its judgements no longer count in answers), or counted again
  if (d.nonscientific !== undefined) out.push(d.nonscientific ? "Marked as non-scientific: no judgement of its excerpts counts in an answer." : "Counted as scientific again.");
  return out.join(" ") || "Which passages are read was changed.";
}

// The line under a waiting proposal's card, by kind
export function kindLine(p, v) {
  const d = p.detail || {};
  switch (p.kind) {
    case "add":
      return `It is in every copy for now. Declined, it stays in ${p.by && p.by.me ? "your" : p.by && p.by.name ? `${p.by.name}’s` : "their"} copy only.`;
    case "reread":
      return `Reader ${d.from_reader ?? "?"} to ${d.to_reader ?? "?"}. Accepted, every copy reads it again and moves its results with it.`;
    case "blocks":
      return blocksLine(d);
    case "remove":
      return "Accepted, it leaves every copy; checks keep what they read of it.";
    case "loosen":
      return `Now: ${LEVEL_WORDS[d.from] || d.from || "?"}. Proposed: ${LEVEL_WORDS[d.to] || d.to || "?"}. Until ${v && v.is_owner ? "you accept" : "the owner accepts"}, nothing changes anywhere.`;
    default:
      return "";
  }
}

// Accepting a looser setting: the confirmation's words. `keepOutInForce`: the shared folder keeps documents marked
// Only a local AI or No AI out (the Team tab's switch); one let out to Claude then has its text and file written there.
export function loosenConfirm(p, keepOutInForce) {
  const d = (p && p.detail) || {};
  const to = LEVEL_WORDS[d.to] || d.to || "?";
  const kept = new Set(["local", "none"]);
  const out = `Every copy then has it as “${to}”.`;
  if (keepOutInForce && kept.has(d.from) && !kept.has(d.to)) {
    return `${out} The shared folder keeps out only documents marked Only a local AI or No AI, so its text and file will then go into the shared folder too.`;
  }
  return out;
}

export function conflictsText(n) {
  return n === 1 ? "1 other proposal for this document waits too." : `${n} other proposals for this document wait too.`;
}

// Under a proposal that waits, for whoever cannot answer it
export function waitingFor(v) {
  const n = ownerName(v);
  if (n === "you") return "Waiting for you.";
  return coOwners(v).length ? `Waiting for ${n} or a Co-owner.` : `Waiting for ${n}.`;
}

// An answered proposal in words: {text, when}
export function answeredLine(p, now = new Date()) {
  switch (p.state) {
    case "accepted":
      if (p.decided_by) return { text: `Accepted by ${nameOf(p.decided_by)}${p.auto ? " at once" : ""}`, when: whenText(p.decided_at, now) };
      return { text: p.note ? `No longer needed: ${p.note}` : "Accepted.", when: "" };
    case "declined":
      return { text: p.reason ? `Declined: ${p.reason}` : "Declined.", when: whenText(p.decided_at, now) };
    case "taken_back":
      return { text: "Taken back.", when: "" };
    case "replaced":
      return { text: "Replaced by a later proposal.", when: "" };
    case "moot":
      return { text: p.note ? `No longer needed: ${p.note}` : "No longer needed.", when: "" };
    default:
      return { text: "", when: "" };
  }
}

// What the person sees after their own proposal was declined (shown first, until marked as seen)
export function declinedLine(p, v) {
  const who = p.decided_by ? nameOf(p.decided_by, ownerName(v)) : ownerName(v);
  const first = `${who === "you" ? "You" : who[0].toUpperCase() + who.slice(1)} declined your proposal`;
  const after = p.kind === "add" ? " The document stays in your copy only." : p.kind === "loosen" ? " Nothing changed anywhere." : " Your copy keeps your change.";
  return { head: first, reason: p.reason ? `Declined: ${p.reason}` : "Declined.", after: after.trim() };
}

// A new reading the owner accepted that this copy has not made yet
export function applyText(row) {
  return `The project now reads “${row.title || "a document"}” with the new reader. ${row.note || ""}`.trim();
}

// The Documents page: a document only proposed to the owner, or declined (`documents[].proposal`)
export function docChip(proposal) {
  if (!proposal || !proposal.state) return null;
  return { label: proposal.state === "declined" ? "In your copy only" : "Waiting for the owner", text: proposal.text || "",
    kind: proposal.state === "declined" ? "declined" : "waiting" };
}

// After PUT …/documents/ai-access answered `proposed`: a looser setting held for the owner's word
export function proposedText(n, owner, changed = 0) {
  const lead = changed ? `${plural(changed, "document")} changed. ` : "";
  const who = !owner || owner === "the owner" ? "the owner" : owner;
  return `${lead}${n === 1 ? "1 document" : `${n} documents`}: a looser setting is the owner’s to decide. Proposed to ${who}; until then nothing changes.`;
}

// Removing a document in a collaborator's copy
export const REMOVE_PROPOSAL = "In your copy it goes now; for the project it is a proposal to the owner.";

// ---------------------------------------------------------------------------------------------
// roles (DESIGN-roles §5; the picked mock-up B, "one inbox, first", with the blind review's changes)
// ---------------------------------------------------------------------------------------------
export const ROLE_WORD = { owner: "Owner", co: "Co-owner", member: null };
export const NEEDS_UPDATE = "needs a newer ENLENS to act as Co-owner";
export const CLASH_WAITING = "Waiting: answered both ways, to be decided again";
export const TICK_FIRST = "Tick the documents first";

// this person's role; a view of before the roles reads as before: the owner, or a Member
export const roleOf = (v) => (v && v.role) || (v && v.is_owner ? "owner" : "member");
export const canWrite = (v) => !!v && (v.can_write ?? roleOf(v) !== "member");
export const canSetRoles = (v) => !!v && (v.can_set_roles ?? !!v.is_owner);
export const coOwners = (v) => ((v && v.people) || []).filter((x) => x.role === "co");

// A person of the view: {id, name, me}, from a person or a bare id (looked up in people)
export function personOf(x, v) {
  if (!x) return null;
  if (typeof x === "object") return x;
  const p = ((v && v.people) || []).find((y) => y.id === x);
  return p || { id: x, name: "a colleague", me: !!(v && v.me === x) };
}
// "Ben" (Ben Okafor), "Anna (laptop)" (Anna de Vries (laptop)), "you"; the first word and any words in brackets
export function shortName(x, v) {
  const p = personOf(x, v);
  if (!p) return "a colleague";
  if (p.me) return "you";
  const n = String(p.name || "").trim();
  if (!n || n === "a colleague") return "a colleague";
  const tail = /\s(\([^)]*\))$/.exec(n);
  return n.split(/\s+/)[0] + (tail ? ` ${tail[1]}` : "");
}
const cap1 = (t) => (t ? t[0].toUpperCase() + t.slice(1) : t);
const and = (xs) => (xs.length > 1 ? `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}` : xs[0] || "");
// "you and Ben": this person first
function names(list, v) {
  const ps = (list || []).map((x) => personOf(x, v)).filter(Boolean);
  ps.sort((a, b) => (b.me ? 1 : 0) - (a.me ? 1 : 0));
  return and(ps.map((p) => shortName(p, v)));
}
// "Ben (Co-owner)", "Anna (owner)": who did something, with the role that let them
export function withRole(x, v) {
  const p = personOf(x, v);
  if (!p) return "a colleague";
  if (p.me) return "you";
  const person = ((v && v.people) || []).find((y) => y.id === p.id) || p;
  const owner = v && v.owner && v.owner.id === p.id;
  const role = owner ? "owner" : person.role === "co" ? "Co-owner" : null;
  return role ? `${shortName(p, v)} (${role})` : shortName(p, v);
}

// Under the people list's head: what this person's role means (nothing for the Owner, or with no owner)
export function roleSentence(v) {
  if (!v || !v.owner || v.can_claim) return null;
  const r = roleOf(v);
  if (r === "co") return "You are a Co-owner: your changes to the documents hold for everyone, and you answer proposals.";
  if (r === "member") {
    const to = coOwners(v).length ? `${shortName(v.owner, v)} and the Co-owners` : shortName(v.owner, v);
    return `You are a Member: your changes to the documents are proposals to ${to}.`;
  }
  return null;
}

// The people of the list in order: rows of one person stand together (a second computer right under its person)
export function peopleInOrder(list) {
  const out = [], placed = new Set();
  const byId = new Map(list.map((x) => [x.id, x]));
  const under = (x) => list.filter((y) => y.same_as === x.id && !placed.has(y.id));
  const put = (x) => { if (placed.has(x.id)) return; placed.add(x.id); out.push(x); under(x).forEach(put); };
  for (const x of list) { if (!x.same_as || !byId.has(x.same_as)) put(x); }
  for (const x of list) put(x);
  return out;
}
// "Also Anna de Vries: the same person" (or "Also you: …"): on the row of a second computer
export function samePersonLine(x, v) {
  if (!x || !x.same_as) return null;
  const other = personOf(x.same_as, v);
  return `Also ${other && other.me ? "you" : (other && other.name) || "a colleague"}: the same person`;
}

// What waits for this person's word, as cards in the order of the tab, most serious first (DESIGN-roles §5.2):
// proposals answered both ways, questions about the owner, changes refused in this person's name, looser AI settings
// offered (one card per person), then the proposals this person answers. `settled`: what was changed at the same time
// and settled by the rules (rows under the cards, for the Owner and Co-owners). `mine`: proposals that wait for
// someone else's word (a Member's own). `later`: questions put off with Not now (in this browser).
export function inbox(v, later = new Set()) {
  const props = ((v && v.proposals) || []).filter((p) => p.state === "waiting");
  const bothWays = props.filter((p) => p.clash && p.can_decide);
  const deciding = props.filter((p) => !p.clash && p.can_decide);
  const mine = props.filter((p) => !p.can_decide);
  const questions = questionCards(v);
  const refused = ((v && v.refused) || []).slice();
  const offers = offerGroups(v);
  const settled = canWrite(v) ? ((v && v.clashes) || []).filter((c) => c.kind === "part") : [];
  const count = bothWays.length + questions.filter((q) => !q.ids.every((id) => later.has(id))).length + refused.length
    + offers.length + deciding.length;
  return { bothWays, questions, refused, offers, deciding, mine, settled, count,
    cards: bothWays.length + questions.length + refused.length + offers.length + deciding.length };
}

// The questions about the owner, as cards: two first owners and none followed yet are one card with a button each
export function questionCards(v) {
  const qs = ((v && v.questions) || []).slice();
  const founders = qs.filter((q) => q.kind === "founder" && Number(q.seq) === 1);
  const out = [];
  if (!(v && v.owner) && founders.length > 1) {
    out.push({ kind: "founders", ids: founders.map((q) => q.id), list: founders });
  }
  for (const q of qs) if (!out.length || !out[0].ids.includes(q.id)) out.push({ kind: q.kind, ids: [q.id], list: [q] });
  const rank = { takeover: 0, founders: 1, founder: 2, other: 3 };
  return out.sort((a, b) => (rank[a.kind] ?? 9) - (rank[b.kind] ?? 9));
}

// A question card's words: {title, tag, said, text, answers: [{label, id, answer, quiet}]}
export function questionWords(card, v) {
  const q = card.list[0];
  const who = (x) => shortName(x, v);
  const named = personOf(q.owner || q.by, v);
  const now = q.now ? who(q.now) : (v && v.owner ? who(v.owner) : null);
  const iAmOwner = !!(v && v.is_owner);
  if (card.kind === "founders") {
    return { title: "Two first owners", tag: null, said: null,
      text: "Two people say they are this project’s first owner. Which do you follow?",
      answers: card.list.map((x) => ({ label: `Follow ${cap1(who(x.owner || x.by))}`, id: x.id, answer: "follow" })) };
  }
  if (card.kind === "takeover") {
    const n = cap1(who(named));
    return { title: `${n} took the project over`, tag: "A take-over", said: q.why || null,
      text: `${iAmOwner ? "Here you are still the owner." : now ? `You follow ${cap1(now)}.` : ""} If you follow ${n}, ${n} decides about the documents from now on.`.trim(),
      answers: [{ label: `Follow ${n}`, id: q.id, answer: "follow" }, { label: "Not now", id: q.id, answer: null, quiet: true }] };
  }
  const first = card.kind === "founder";
  const n = cap1(who(named));
  const self = now === "you";   // this copy follows its own person: "Here you are the owner"
  const kept = now && !self ? cap1(now) : null;
  return { title: first ? "Another first owner" : "Another owner", tag: null, said: q.why || null,
    text: `This file names another ${first ? "first " : ""}owner: ${n}.${self ? " Here you are the owner." : kept ? ` You follow ${kept}.` : ""}`,
    answers: [{ label: `Follow ${n}`, id: q.id, answer: "follow" },
      { label: self ? "Stay the owner" : kept ? `Keep ${kept}` : "Keep as it is", id: q.id, answer: "keep", quiet: true }] };
}

// A change a file brought in this person's name, refused (DESIGN-roles §4.10): {title, text, takeBack}
export function refusedWords(r, v) {
  const via = cap1(shortName(r.via, v));
  const viaFile = via === "You" ? "A file" : `${via}’s file`;
  if (r.kind === "ownership") {
    const to = r.owner ? shortName(r.owner, v) : null;
    return { title: "A change in your name was refused",
      text: `${viaFile} says you handed the project ${to && to !== "you" ? `to ${cap1(to)}` : "over"}. You did not: nothing was changed here.`, takeBack: true };
  }
  const what = r.kind === "canon" ? (r.title ? `a change to “${r.title}”` : "a change to a document")
    : r.kind === "roles" ? "a change of a role" : r.kind === "decisions" ? "an answer to a proposal" : r.kind === "proposals" ? "a proposal" : "a change";
  return { title: "A change in your name was refused",
    text: `${viaFile} held ${what} in your name. It was not taken, and your own word was sent again.`, takeBack: false };
}

// Looser AI settings offered here, one group per person who loosened them: [{by, list}] (the order of the view)
export function offerGroups(v) {
  const groups = new Map();
  for (const o of (v && v.offers) || []) {
    const p = personOf(o.by, v) || { id: "?", name: "a colleague" };
    if (!groups.has(p.id)) groups.set(p.id, { by: p, list: [] });
    groups.get(p.id).list.push(o);
  }
  return [...groups.values()];
}
const READS = { cloud: "Claude", local: "a local AI" };
// An offer card's words; `ticked`: how many of its documents are ticked (a card of one document has no box)
export function offerWords(g, v, ticked = 0) {
  const n = g.list.length, by = cap1(shortName(g.by, v)), o = g.list[0];
  const levels = new Set(g.list.map((x) => x.to));
  const its = n === 1 ? "its" : "their";
  const ai = levels.has("cloud") && levels.has("local")
    ? `Once allowed, Claude may read the excerpts of those ${by} lets Claude read, and only the AI on this computer the others.`
    : levels.has("cloud") ? `Once allowed, Claude may read ${its} excerpts.` : `Once allowed, only the AI on this computer may read ${its} excerpts.`;
  if (n === 1) {
    return { title: `${by} lets more AI read a document`, tag: "More AI", one: true,
      text: `${withRole(g.by, v).replace(/^./, (c) => c.toUpperCase())} lets ${READS[o.to] || "an AI"} read “${o.title || "a document"}”. Here it stays ${LEVEL_WORDS[o.from] || o.from} until you say.`,
      allow: "Allow here", keep: "Keep it stricter here", ready: true, ai, where: levels.has("cloud") ? "cloud" : "local" };
  }
  return { title: `${by} lets more AI read ${n} documents`, tag: "More AI", one: false,
    text: "Here they stay as they are until you say.",
    allow: ticked ? `Allow here for ${plural(ticked, "document")}` : "Allow here",
    keep: ticked ? `Keep ${ticked} stricter here` : "Keep stricter here",
    ready: ticked > 0, ai, where: levels.has("cloud") ? "cloud" : "local", here: "Here:", theirs: `${by}’s:` };
}
export function allowedText(n, allow) {
  return allow ? `Allowed here for ${plural(n, "document")}.` : `${n === 1 ? "It stays" : "They stay"} stricter here.`;
}

// A proposal answered both ways (DESIGN-roles §5.4): {who, result}
const STAYS = { add: "it is not one of the project’s documents yet", remove: "the document stays in the project",
  loosen: "who may read it with AI stays as it was", reread: "the project reads it as before", blocks: "the passages read stay as they were" };
export function bothWaysWords(p, v) {
  const c = p.clash || {};
  const acc = cap1(names(c.accepted, v) || "Someone"), dec = names(c.declined, v) || "someone else";
  return { who: `${acc} accepted it and ${dec} declined it, neither knowing the other’s answer.`,
    result: STAYS[p.kind] || "nothing changes" };
}

// Something two people changed at the same time, settled by the rules: the row's words (DESIGN-roles §5.4)
const ev = (e) => (Array.isArray(e) ? { n: e[0], by: e[1], value: e[2] } : e || {});
export function settledWords(c, v) {
  const evs = (c.events || []).map(ev);
  const people = c.people && c.people.length ? c.people : [...new Set(evs.map((e) => e.by))];
  const who = cap1(names(people, v));
  const held = Array.isArray(c.counts) ? evs.find((e) => e.n === c.counts[0] && e.by === c.counts[1]) : null;
  switch (c.part) {
    case "ai": {
      const level = held ? held.value : evs.map((e) => e.value).sort((a, b) => STRICT[b] - STRICT[a])[0];
      return { text: `${who} changed who may read it with AI at the same time. The stricter holds: ${LEVEL_WORDS[level] || level || "?"}.` };
    }
    case "state": {
      const rm = evs.filter((e) => e.value === "removed").map((e) => e.by), kept = evs.filter((e) => e.value !== "removed").map((e) => e.by);
      return { text: `${cap1(names(rm, v) || "Someone")} removed it while ${names(kept, v) || "someone else"} kept it. It stays in the project.`,
        remove: "To remove it, use its menu on ", where: "Documents" };
    }
    case "read":
      return { text: `${who} each read it again at the same time. The newer reader’s reading holds.` };
    case "blocks": {
      const holder = held ? personOf(held.by, v) : null;
      const others = people.map((x) => personOf(x, v)).filter((p) => p && (!holder || p.id !== holder.id));
      const top = others.some((p) => p.me) ? "yours" : others.length ? `${names(others, v)}’s` : "the others’";
      return { text: `${who} each changed which passages are read at the same time. ${holder ? (holder.me ? "Your" : `${cap1(shortName(holder, v))}’s`) : "One"} choices hold, with ${top} on top where they differ.` };
    }
    default:
      return { text: `${who} changed it at the same time.` };
  }
}
const STRICT = { none: 2, local: 1, cloud: 0 };

// "12 November"
export function dayMonth(t) {
  const m = Date.parse(t || "");
  return Number.isFinite(m) ? new Date(m).toLocaleDateString("en-GB", { day: "numeric", month: "long" }) : "";
}
// A row of "Removed in the last 30 days": its second line
export function removedLine(r, v) {
  const by = r.by ? withRole(r.by, v) : null;
  const when = dayMonth(r.at);
  const head = r.cause === "declined" ? `Declined${by ? ` by ${by}` : ""}` : `Removed${by ? ` by ${by}` : ""}`;
  return [`${head}${when ? ` on ${when}` : ""}${r.why ? `: “${r.why}”` : "."}`, r.until ? `Can be restored until ${dayMonth(r.until)}.` : ""].filter(Boolean).join(" ");
}
// The toast after Restore (`proposed`: a Member's copy, where it goes to the owner again)
export function restoredText(title, proposed) {
  const t = `“${title || "The document"}”`;
  return proposed ? `${t} is back in your copy, and proposed to the owner.` : `${t} is back in the project.`;
}

// The role dialogs' words (DESIGN-roles §5.1): {title, body: [..], ok}
export function roleDialogWords(name, to) {
  const n = shortName({ name }, null);
  if (to === "co") {
    return { title: `Make ${n} a Co-owner?`, ok: "Make Co-owner",
      body: [`${n}’s changes to the documents will hold for everyone at once, and ${n} can accept or decline proposals. Only you set roles and hand the project over.`] };
  }
  return { title: `Make ${n} a Member again?`, ok: "Make Member",
    body: [`What ${n} changed and the project has taken stays. What ${n} changes from now on is a proposal.`,
      `Changes of ${n}’s that have not reached you yet come as proposals too.`] };
}
export function roleToast(name, to) {
  const n = shortName({ name }, null);
  return to === "co" ? `${n} is a Co-owner now. Their copy learns it with your next round or file.` : `${n} is a Member again. Their copy learns it with your next round or file.`;
}
export const SAME_PERSON_BODY = "One person on two computers stands together in the list, and a judgement of theirs counts once.";
export const samePersonTitle = (name) => `Is ${name} the same person as someone here?`;

// The codebook page: a colleague's renames and merges of a codebook they did not make (DESIGN-roles §5.7, H8)
export function codebookOfferText(o) {
  const by = cap1((o && o.from && (typeof o.from === "object" ? String(o.from.name || "").split(/\s+/)[0] : o.from)) || "A colleague");
  const ev2 = ((o && o.events) || []).map((e) => (e.op === "merge" ? `merged ${e.from} into ${e.to}` : `renamed ${e.from} to ${e.to}`));
  const what = and(ev2) || "changed codes";
  const n = (o && o.labels) || 0;
  return `${by} ${what}. Follow for your ${plural(n, "label")}?`;
}
