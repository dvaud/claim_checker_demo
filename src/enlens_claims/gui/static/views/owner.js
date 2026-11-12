// 0.18 (roadmap L2): one owner, several collaborators. A shared project has one owner, who decides which documents it
// holds, how each is read and who may read each with AI; a collaborator's change to the documents is a proposal the
// owner accepts or declines (low: adding a document; medium: reading one again, Leave out / Restore; high: removing
// one, letting more AI read one).
//
// - The Team tab's section "Waiting for the owner" ("Waiting for you" in the owner's copy), before "People in the
//   folder": the proposals as cards with their severity, Accept / Decline with an optional reason, the proposer's
//   Take back, what was answered, a new reading still to make here, Become the owner / Take over, and the owner's
//   setting "Accept documents collaborators add, at once". team.js adds it (`OWNER_SECTION`) and reads its data with
//   the tab's refresh (`load`), its number for the tab (`count`).
// - The people list: the Owner mark and the owner's Make owner… on a colleague's row (`ownerMarks`, from team.js).
// - The Documents page (sources.js): the chip of a document that waits for the owner or stays in your copy only, the
//   words after a looser AI setting was proposed, and the line in the removal question of a collaborator.
// Built on GET/POST/PUT …/owner (gui/api_owner.py, docs/API.md); the words are worked out in owner-state.js.
// Built of 0.17.0's components (docs/DESIGN.md 5.5): a proposal is proposalCard() (what and its severity tag, who
// and when, Accept (main) and Decline… (quiet), or the wait and Take back); the owner is a role on the person mark;
// placed in views.css (the block "Working together").
import { App, api, h, toast, showError, P, confirmDialog, dialog, watchJob, TERMINAL, store, shortTitle, switchControl,
  button, link, input, select, field, notice, noticeList, fold, listRow, personMark, workState, proposalCard as proposalCardBox } from "../lib.js";
import { whenText } from "./team-state.js";
import { OWNER_API, ownerName, sectionShown, splitProposals, heading, nothingWaits, tabCount, proposer,
  whatParts, kindLine, conflictsText, answeredLine, declinedLine, applyText, docChip, proposedText,
  REMOVE_PROPOSAL, loosenConfirm, waitingFor } from "./owner-state.js";

const ACCEPT_ADDS = "Accept documents collaborators add, at once";
const ACCEPT_ADDS_HELP = "Off: each added document waits for your click. Removing a document and letting more AI read one always wait for you.";
const NO_OWNER = "This project has no owner yet. An owner decides which documents the project holds, how they are read and who may read them with AI. Until someone is, everything works as before.";

let following = null;        // the new-reader job this section follows: {id, w}
const gone = new Set();      // jobs that could not be followed (no such job any more): not followed again

// this person's own declined proposals marked as seen (in this browser)
const seenKey = (project) => `owner-seen:${project}`;
function seenSet(project) {
  try { return new Set(JSON.parse(store(seenKey(project)) || "[]")); } catch (_) { return new Set(); }
}
function markSeen(project, ids) {
  const s = seenSet(project);
  for (const id of ids) s.add(id);
  store(seenKey(project), JSON.stringify([...s].slice(-500)));
}

// the section's look is team.js's (`section`), with a heading the panel can focus
function sec(key, title, ...children) {
  const id = `team-h-${key}`;
  return h("section", { class: `team-section team-sec-${key}`, "aria-labelledby": id, dataset: { key } },
    h("h3", { class: "team-h", id, tabindex: "-1" }, title), ...children);   // focusable: the panel finds it again after a redraw
}

function teamSwitch(id, label, checked, help) {
  const sw = switchControl(label, checked, { help });
  sw.input.id = id;
  const lab = sw.querySelector("label");
  if (lab) lab.htmlFor = id;
  return sw;
}

// a dialog that asks for an optional reason: {why} or null
function reasonDialog({ title, message, confirmText, danger = false, help }) {
  const reason = input({ maxlength: 500, autocomplete: "off", id: "owner-dlg-reason" });
  const body = h("div", {}, ...(Array.isArray(message) ? message : [message]).map((m) => (typeof m === "string" ? h("p", {}, m) : m)),
    field("Reason (optional)", reason, { help, class: "owner-dlg-field" }));   // its help is the field's (owner-dlg-reason-help)
  reason.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); const b = document.getElementById("owner-dlg-ok"); if (b) b.click(); } });
  return dialog({ title, body, danger, actions: [{ text: "Cancel", value: null }, { text: confirmText, value: true, primary: true, id: "owner-dlg-ok" }],
    onOpen: () => reason.focus() }).then((ok) => (ok ? { why: reason.value.trim() } : null));
}

// ---------------------------------------------------------------------------------------------
// the Team tab's section
// ---------------------------------------------------------------------------------------------
export const OWNER_SECTION = {
  key: "owner",
  render: ownerSection,
  load: (project) => api("GET", OWNER_API.view(P(project))),
  count: (ctx) => tabCount(ctx.data && ctx.data.owner, seenSet(ctx.project)),
};

function ownerSection(ctx) {
  const v = ctx.data && ctx.data.owner;
  const hasFolder = !!(ctx.status && ctx.status.folder);
  if (!sectionShown(v, hasFolder)) return null;
  follow(ctx, v.job);
  if (v.can_claim) return sec("owner", heading(v), claimBox(ctx));
  const parts = splitProposals(v, seenSet(ctx.project));
  const body = [];
  // a team working with zips has no people list: the owner is named here
  if (!hasFolder && v.owner) {
    body.push(h("p", { class: "team-text owner-who" }, v.owner.me ? "You are the owner." : ["Owner: ", personMark([v.owner.name]), " ", v.owner.name, "."],
      v.owner.me ? handOverPicker(ctx, v) : null));
  }
  if (v.can_take_over) body.push(takeOverBox(ctx, v));
  if (parts.declined.length) body.push(declinedBox(ctx, v, parts.declined));
  if (v.job && !TERMINAL.has(v.job.state)) {
    body.push(h("p", { class: "owner-job", role: "status" }, workState("running", v.job.title || "Reading with the new reader, as the owner accepted…")));
  }
  for (const row of v.to_apply || []) body.push(applyRow(ctx, row));
  if (parts.cards.length) body.push(h("ul", { class: "owner-cards" }, parts.cards.map((p) => proposalCard(ctx, v, p))));
  else body.push(h("p", { class: "muted team-text owner-none" }, nothingWaits(v)));
  if (parts.answered.length) body.push(answeredFold(ctx, v, parts));
  if (v.is_owner) body.push(acceptAddsSwitch(ctx, v));
  return sec("owner", heading(v, parts.cards.length), ...body);
}

// no owner: say what an owner is, and offer to become it
function claimBox(ctx) {
  const b = button({ sm: true, icon: "shield", id: "owner-claim" }, "Become the owner");
  b.addEventListener("click", async () => {
    const ok = await confirmDialog({ title: "Become the owner of this project?", danger: false, confirmText: "Become the owner",
      message: h("div", {}, h("p", {}, "You then decide which documents the project holds, how they are read and who may read them with AI."),
        h("p", {}, "From then on, a colleague’s change to the documents is a proposal for you to accept or decline. Their copies learn it with your next round or file.")) });
    if (!ok) return;
    await act(ctx, b, () => api("POST", OWNER_API.claim(P(ctx.project)), {}), "You are the owner of this project now.");
  });
  return [notice({ kind: "info", role: "note", class: "owner-notice" }, h("p", {}, NO_OWNER)), h("div", { class: "btn-row" }, b)];
}

// the owner has left: a collaborator may take the project over
function takeOverBox(ctx, v) {
  const b = button({ sm: true, id: "owner-take-over" }, "Take over");
  b.addEventListener("click", async () => {
    const ok = await reasonDialog({ title: "Take the project over?", confirmText: "Take it over",
      message: [v.can_take_over, `You then decide about its documents; the proposals that wait become yours to answer. ${ownerName(v) === "the owner" ? "The owner" : ownerName(v)} can no longer accept or decline them.`],
      help: "Kept in the research log, for the team." });
    if (!ok) return;
    await act(ctx, b, () => api("POST", OWNER_API.takeOver(P(ctx.project)), ok.why ? { why: ok.why } : {}), "You are the owner of this project now.");
  });
  return notice({ kind: "attention", role: "note", class: "owner-notice" }, h("p", {}, `${v.can_take_over} You can take the project over.`), h("div", { class: "btn-row" }, b));
}

// the owner's Hand over… where there is no people list (a team working with zips)
function handOverPicker(ctx, v) {
  const others = (v.people || []).filter((x) => !x.me);
  if (!others.length) return null;
  const b = button({ kind: "quiet", sm: true, class: "owner-hand-over", id: "owner-hand-over" }, "Hand over…");
  b.addEventListener("click", async () => {
    const sel = select({ id: "owner-dlg-to" }, others.map((x) => h("option", { value: x.id }, x.name)));
    const ok = await reasonDialog({ title: "Hand this project over?", confirmText: "Hand it over",
      message: [field("To", sel),
        "They will decide about its documents from now on; proposals that wait become theirs to answer. You stay in the team."],
      help: "Kept in the research log, for the team." });
    if (!ok) return;
    const to = others.find((x) => x.id === sel.value) || others[0];
    await handOver(ctx, to, ok.why, b);
  });
  return [" ", b];
}

async function handOver(ctx, to, why, btn) {
  await act(ctx, btn, () => api("POST", OWNER_API.handOver(P(ctx.project)), why ? { to: to.id, why } : { to: to.id }),
    `${to.name} is the owner now. Their copy learns it with your next round or file.`);
}

// one request of the section; then the tab is read again and the focus goes to the section's heading
async function act(ctx, btn, call, said, kind = "ok") {
  if (btn) btn.disabled = true;
  try {
    const r = await call();
    if (said) toast(typeof said === "function" ? said(r) : said, kind, { ttl: 7000 });
    await ctx.refresh({ force: true });
    ctx.focusHeading("owner");
    return r;
  } catch (e) {
    showError(e);
    if (btn && btn.isConnected) btn.disabled = false;
    if (e && (e.status === 403 || e.status === 404 || e.status === 409)) { await ctx.refresh({ force: true }); ctx.focusHeading("owner"); }
    return null;
  }
}

// ---- a proposal that waits
function titleNode(p, v) {
  const { before, title, after } = whatParts(p.what);
  if (title === null) return [p.what];
  const t = p.here ? link({ kind: "title", serif: true, href: `#/doc/${encodeURIComponent(p.doc)}` }, title) : h("span", { class: "serif" }, title);
  return [before, "“", t, "”", after];
}

// who proposed it: the full name its tooltip. On a proposal's card the mark stands alone, so it shows the name ("Anna",
// "You"; docs/DESIGN.md 5.5); in a row whose words name the person, the initials (alone: false)
function byMark(ctx, p, alone = true) {
  const by = p.by || {};
  const opts = alone ? { name: "short" } : {};
  if (!by.me) return personMark([by.name || "a colleague"], opts);
  const mine = (ctx.status && ctx.status.me && ctx.status.me.name) || "";
  const m = personMark(["you"], opts);
  if (mine) m.title = `${mine} (you)`;
  return m;
}

// what is proposed, the card's head: "Removing “Annual report 2024” from the project" (the title a link where the
// document is in this copy)
function whatNode(p, v) {
  const parts = titleNode(p, v);
  if (typeof parts[0] === "string" && parts[0]) parts[0] = parts[0][0].toUpperCase() + parts[0].slice(1);
  return h("span", { class: "owner-what" }, ...parts);
}

// A proposal that waits: proposalCard() (lib.js, docs/DESIGN.md 5.5): what is proposed and its severity in the head,
// who proposed it (with the name) and when, what the change does (the kind's line) and a notice of another proposal
// for the same document; then the owner's Accept and Decline…, or the wait and the proposer's Take back.
function proposalCard(ctx, v, p) {
  const line = kindLine(p, v);
  const card = proposalCardBox({ id: `owner-card-${p.id}`, "aria-label": `A proposed change: ${p.what}`,
    what: whatNode(p, v), person: byMark(ctx, p), time: p.at ? whenText(p.at) : null, severity: p.severity,
    detail: [line ? h("p", { class: "owner-line" }, line) : null,
      (p.conflicts || []).length ? notice({ kind: "attention", class: "owner-conflicts" }, h("p", {}, conflictsText(p.conflicts.length))) : null],
    side: p.can_decide ? "owner" : "proposer", waiting: waitingFor(v),
    onAccept: (e) => accept(ctx, p, e.currentTarget), onDecline: (e) => decline(ctx, p, e.currentTarget),
    onTakeBack: p.can_take_back ? (e) => takeBack(ctx, p, e.currentTarget) : null });
  const time = card.querySelector(".proposal-by time");
  if (time && p.at) time.dateTime = new Date(p.at).toISOString();
  return card;
}

// the owner's Accept. Removing a document, or letting more AI read one, asks first, with an optional reason (kept in
// the research log; the proposer sees it); any other change is accepted at once.
async function accept(ctx, p, btn) {
  let why = "";
  if (p.kind === "remove" || p.kind === "loosen") {
    const inForce = !!(ctx.status && ctx.status.keep_out && ctx.status.keep_out.in_force);
    const ok = await reasonDialog(p.kind === "remove"
      ? { title: `Remove “${shortTitle(p.title, 70)}” from every copy of the project?`, confirmText: "Remove it", danger: true, help: reasonHelp(p),
        message: "Each copy removes it with its next round or file, after a backup. Checks keep what they read of it, as records. What the shared folder already holds of it stays there for now." }
      : { title: `Let more AI read “${shortTitle(p.title, 70)}”?`, confirmText: "Accept", help: reasonHelp(p),
        message: loosenConfirm(p, inForce) });
    if (!ok) return;
    why = ok.why;
  }
  await act(ctx, btn, () => api("POST", OWNER_API.accept(P(ctx.project), P(p.id)), why ? { reason: why } : {}), () => acceptedText(p));
}

// the owner's Decline…: a dialog asks for an optional reason (docs/DESIGN.md 5.5)
async function decline(ctx, p, btn) {
  const ok = await reasonDialog({ title: "Decline this proposal?", confirmText: "Decline", help: reasonHelp(p),
    message: [`${proposer(p).who} ${proposer(p).verb} ${p.what}.`, p.kind === "add" ? "Declined, the document leaves the other copies and stays in the proposer’s copy only." : "Declined, nothing changes in the project."] });
  if (!ok) return;
  const why = ok.why;
  await act(ctx, btn, () => api("POST", OWNER_API.decline(P(ctx.project), P(p.id)), why ? { reason: why } : {}), () => declinedText(p));
}

// what happens to the owner's reason
function reasonHelp(p) {
  const by = p.by && !p.by.me ? p.by.name : null;
  return by ? `${by} sees it with your answer, and it is kept in the research log.` : "It is kept in the research log.";
}

function acceptedText(p) {
  const tail = { add: "The document is one of the project’s now.", remove: "It leaves every copy with their next round or file.",
    reread: "Every copy reads it again with the new reader.", blocks: "Every copy reads it so from their next round or file.",
    loosen: "Every copy takes the setting with their next round or file." }[p.kind] || "";
  return `Accepted. ${tail}`.trim();
}

function declinedText(p) {
  const by = p.by && !p.by.me ? p.by.name : "the proposer";
  return p.kind === "add" ? `Declined. The document leaves the other copies; ${by} keeps it in their copy only.` : `Declined. Nothing changes in the project; ${by} sees your answer.`;
}

// the proposer's own: Take back
// the proposer's Take back: it asks first
async function takeBack(ctx, p, btn) {
  const ok = await confirmDialog({ title: "Take this proposal back?", confirmText: "Take it back", danger: false,
    message: h("div", {}, h("p", {}, `${proposer(p).who === "You" ? "Your proposal" : "The proposal"}: ${p.what}.`), h("p", {}, "Your copy stays as it is.")) });
  if (!ok) return;
  await act(ctx, btn, () => api("POST", OWNER_API.takeBack(P(ctx.project), P(p.id)), {}), "Taken back. Your copy stays as it is.");
}

// this person's own proposals the owner declined, shown first until marked as seen: notices one under the other
// (docs/DESIGN.md 5.5, noticeList)
function declinedBox(ctx, v, list) {
  const items = noticeList(list.map((p) => {
    const d = declinedLine(p, v);
    return { kind: "attention", text: [h("strong", {}, `${d.head}: `), ...titleNode(p, v), ". ", d.reason,
      p.decided_at ? h("span", { class: "muted small" }, ` · ${whenText(p.decided_at)}`) : null, h("br"), h("span", { class: "small" }, d.after)] };
  }));
  [...items.children].forEach((li, i) => { li.id = `owner-declined-${list[i].id}`; });
  const ok = button({ kind: "quiet", sm: true, icon: "check", id: "owner-seen" }, "Mark as seen");
  ok.addEventListener("click", async () => {
    markSeen(ctx.project, list.map((p) => p.id));
    await ctx.refresh({ force: true });
    ctx.focusHeading("owner");
  });
  return h("div", { class: "owner-declined-box" }, items, h("div", { class: "btn-row" }, ok));
}

// what was answered: the latest, in a fold that starts closed
function answeredFold(ctx, v, parts) {
  const rows = parts.answered.map((p) => {
    const who = proposer(p);
    const a = answeredLine(p);
    // a list row: who, what was proposed, the answer as its quiet second line, when
    return listRow({ person: byMark(ctx, p, false), title: h("span", { class: "owner-what" }, `${who.who} proposed `, titleNode(p, v), "."),
      sub: a.text, time: a.when || null });
  });
  const more = parts.answeredTotal > parts.answered.length ? h("p", { class: "muted small" }, `The latest ${parts.answered.length} of ${parts.answeredTotal}; the research log keeps every one.`) : null;
  const d = fold({ open: ctx.open.has("owner-answered"), class: "owner-fold" }, `Answered (${parts.answeredTotal})`, h("ul", { class: "owner-answered-list" }, rows), more);
  d.querySelector("summary").id = "owner-answered";   // h("summary", { id: "owner-answered" }) of 0.18: the focus finds it again
  d.addEventListener("toggle", () => { if (d.open) ctx.open.add("owner-answered"); else ctx.open.delete("owner-answered"); });
  return d;
}

// a new reading the owner accepted, not made in this copy yet
function applyRow(ctx, row) {
  const go = row.can_force ? button({ sm: true, icon: "layers", id: `owner-apply-${row.doc}` }, "Move it anyway") : null;
  if (go) {
    go.addEventListener("click", async () => {
      const ok = await confirmDialog({ title: `Read “${shortTitle(row.title, 60)}” with the new reader now?`, confirmText: "Move it anyway", danger: false,
        message: h("div", {}, h("p", {}, row.note || ""), h("p", {}, "Results that find no place are kept as records.")) });
      if (!ok) return;
      await act(ctx, go, () => api("POST", OWNER_API.apply(P(ctx.project)), { doc: row.doc, force: true }), "Reading it with the new reader…", "info");
    });
  }
  return notice({ kind: "attention", icon: "layers", role: "note", class: "owner-notice" }, h("p", {}, applyText(row)),
    h("div", { class: "btn-row" }, go, link({ href: `#/doc/${encodeURIComponent(row.doc)}?tab=reading` }, "Open the document")));
}

// the owner's setting
function acceptAddsSwitch(ctx, v) {
  const sw = teamSwitch("owner-accept-adds", ACCEPT_ADDS, !!v.accept_adds, ACCEPT_ADDS_HELP);
  sw.input.addEventListener("change", async () => {
    const want = sw.input.checked;
    sw.input.disabled = true;
    try {
      await api("PUT", OWNER_API.settings(P(ctx.project)), { accept_adds: want });
      toast(want ? "Documents collaborators add are accepted at once from now on (also those that waited)." : "Each document a collaborator adds now waits for your click.", "ok", { small: true, ttl: 6000 });
      await ctx.refresh({ force: true });
      const again = document.getElementById("owner-accept-adds");
      if (again) again.focus();
    } catch (e) {
      showError(e);
      sw.input.checked = !want;
      sw.input.setAttribute("aria-checked", sw.input.checked ? "true" : "false");
      sw.input.disabled = false;
    }
  });
  return h("div", { class: "owner-setting" }, sw);
}

// a new-reader job of the project (the owner accepted a new reading): read the tab again when it ends
function follow(ctx, job) {
  if (!job || !job.id || TERMINAL.has(job.state) || gone.has(job.id) || (following && following.id === job.id)) return;
  if (following) following.w.stop();
  const project = ctx.project;
  const w = watchJob(job.id, null, 1500);
  following = { id: job.id, w };
  const end = (j) => {
    if (following && following.w === w) following = null;
    if (j && j.state === "done" && j.result) {
      const kept = j.result.kept || [], moved = j.result.moved || [];
      if (moved.length) toast(`Read with the new reader, as the owner accepted: ${moved.map((m) => `“${shortTitle(m.title, 50)}”`).join(", ")}.`, "ok");
      else if (kept.length) toast(`${kept.length === 1 ? "A document" : `${kept.length} documents`} stayed as ${kept.length === 1 ? "it was" : "they were"}: see the Team tab.`, "warn", { ttl: 9000 });
    }
    if (ctx.project === project && App.project === project) ctx.refresh({ force: true });
  };
  w.promise.then(end).catch(() => { gone.add(job.id); end(null); });
}

// ---------------------------------------------------------------------------------------------
// the people list (team.js peopleSection): the Owner role on the person mark, and the owner's Make owner…
// ---------------------------------------------------------------------------------------------
const OWNER_TIP = "Decides which documents the project holds, how they are read and who may read them with AI.";
// a person's mark in the people list: "Owner" as its role (docs/DESIGN.md 4.10) for the owner
export function ownerPerson(ctx, person, name) {
  const v = ctx.data && ctx.data.owner;
  const owner = !!(v && v.owner && person && person.id && v.owner.id === person.id);
  const m = personMark([name || "a colleague"], { role: owner ? "Owner" : null });
  if (owner) m.title = `${m.title}. ${OWNER_TIP}`;
  return m;
}
// the owner's Make owner… on a colleague's row (null otherwise; the Owner role is on the person mark, ownerPerson)
export function ownerMarks(ctx, person) {
  const v = ctx.data && ctx.data.owner;
  if (!v || !v.owner || !person || !person.id) return null;
  const out = [];
  if (v.owner.id === person.id) return null;   // "Owner": the role on the person mark
  else if (v.is_owner && (v.people || []).some((x) => x.id === person.id)) {
    const name = person.name || "this colleague";
    const b = button({ kind: "quiet", sm: true, class: "owner-make", id: `owner-make-${person.id}`, "aria-label": `Make ${name} the owner…` }, "Make owner…");
    b.addEventListener("click", async () => {
      const ok = await reasonDialog({ title: `Hand this project over to ${name}?`, confirmText: "Hand it over",
        message: "They will decide about its documents from now on; proposals that wait become theirs to answer. You stay in the team.",
        help: "Kept in the research log, for the team." });
      if (!ok) return;
      await handOver(ctx, { id: person.id, name }, ok.why, b);
    });
    out.push(b);
  }
  return out.length ? out[0] : null;
}

// ---------------------------------------------------------------------------------------------
// the Documents page (sources.js)
// ---------------------------------------------------------------------------------------------
// a document that waits for the owner (the work state Waiting for the owner, a clock) or stays in your copy only (the
// owner declined it: settled, a grey dash; docs/DESIGN.md 4.21, 5.5): its text for a screen reader and the tip
export function proposalChip(proposal) {
  const c = docChip(proposal);
  if (!c) return null;
  const words = [h("span", { "aria-hidden": c.text ? "true" : null }, c.label), c.text ? h("span", { class: "visually-hidden" }, c.text) : null];
  const mark = workState(c.kind === "declined" ? "ended" : "waiting", words);
  if (c.text) mark.title = c.text;
  return h("div", { class: "owner-doc" }, mark);
}

// who the owner is, for the Documents page: read when needed, kept for half a minute
let known = { project: null, at: 0, view: null };
export async function ownerOf(project) {
  if (known.project === project && Date.now() - known.at < 30000) return known.view;
  try { known = { project, at: Date.now(), view: await api("GET", OWNER_API.view(P(project))) }; } catch (_) { return null; }
  return known.view;
}

// A collaborator's copy held a looser AI setting for the owner (`proposed` of PUT …/documents/ai-access): say so.
// Returns true when it did (the caller's own words about the change are then not said).
export async function proposedToast(res, project, ids = []) {
  const held = (res && res.proposed) || [];
  if (!held.length) return false;
  known.at = 0;
  const v = await ownerOf(project);
  const n = ownerName(v);
  const changed = ids.filter((id) => !held.includes(id)).length;
  toast(proposedText(held.length, n === "you" ? "the owner" : n, changed), "info", { ttl: 10000 });
  return true;
}

// The removal question's extra line, in a collaborator's copy (null in the owner's, with no owner, or for a document
// that is not one of the project's yet: an addition still proposed or declined goes from this copy only)
export async function removalNote(project, doc) {
  if (doc && doc.proposal && doc.proposal.state !== "waiting") return null;
  const v = await ownerOf(project);
  if (!v || !v.owner || v.is_owner) return null;
  return notice({ kind: "info", icon: "users", class: "owner-remove-note" }, h("p", {}, REMOVE_PROPOSAL));
}
