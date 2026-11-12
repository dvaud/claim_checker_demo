// 0.18 (roadmap L2): what the Team tab and the Documents page say about the project's owner and the proposals that
// wait for the owner, worked out from GET …/owner (gui/api_owner.py, ownership.view) without touching the page. Its
// only import is team-state.js, which has none, so it also runs in Node for the tests. owner.js draws it.
//
// The view: {owner: {id, name, me} | null, me, is_owner, since, how, can_claim, can_take_over: words | null,
// accept_adds, people: [{id, name, me, owner}], proposals: [{id, kind, severity, doc, title, what, by: {id, name, me},
// at, state, note, reason, decided_by, decided_at, auto, mine, can_decide, can_take_back, here, conflicts, detail}]
// (newest first), waiting, to_apply: [{doc, title, kind, note, can_force}], documents: {doc id: {state, text}}, job}.
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
};

// how much a change matters: the word, never only a colour
export const SEVERITY_WORDS = { low: "Low", medium: "Medium", high: "High" };
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

// The section's heading: "Waiting for you (2)" for the owner, "Waiting for the owner (1)" otherwise
export function heading(v, n = 0) {
  if (v && v.can_claim) return "No owner yet";
  const base = v && v.is_owner ? "Waiting for you" : "Waiting for the owner";
  return n ? `${base} (${n})` : base;
}

export function nothingWaits(v) {
  return v && v.is_owner ? "Nothing waits for you." : "Nothing waits for the owner.";
}

// The number on the Team tab: for the owner, what waits for their answer; for a collaborator, their own proposals the
// owner declined that they have not seen yet (what waits on the owner is no news to them).
export function tabCount(v, seen = new Set()) {
  if (!v) return 0;
  if (v.is_owner) return Number(v.waiting) || 0;
  return splitProposals(v, seen).declined.length;
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
  return n === "you" ? "Waiting for you." : `Waiting for ${n}.`;
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
