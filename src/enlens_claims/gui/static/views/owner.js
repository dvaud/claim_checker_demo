// 0.18 (roadmap L2): one owner, several collaborators. A shared project has one owner, who decides which documents it
// holds, how each is read and who may read each with AI; a collaborator's change to the documents is a proposal the
// owner accepts or declines (low: adding a document; medium: reading one again, Leave out / Restore; high: removing
// one, letting more AI read one).
//
// - The Team tab's section "Waiting for the owner" ("Waiting for you" in the owner's copy), before "People in the
//   folder": the proposals as cards with their severity, Accept / Decline with an optional reason, the proposer's
//   Take back, what was answered, a new reading still to make here, Take over. team.js adds it (`OWNER_SECTION`) and
//   reads its data with the tab's refresh (`load`), its number for the tab (`count`); it shows only when something
//   waits. The Team page (team.js) has the owner's own section (`ROLES_SECTION`): Become the owner, who the owner is,
//   and the owner's setting "Accept documents collaborators add, at once".
// - The people list: the Owner mark and the owner's Make owner… on a colleague's row (`ownerMarks`, from team.js).
// - The Documents page (sources.js): the chip of a document that waits for the owner or stays in your copy only, the
//   words after a looser AI setting was proposed, and the line in the removal question of a collaborator.
// Roles (DESIGN-roles §5; the picked mock-up B, "one inbox, first", with the blind review's changes): the section is
// "Waiting for your word", the first of the tab: one card per decision, most serious first (a proposal answered both
// ways, a question about the owner, a change refused in your name, a colleague's looser AI settings, the proposals
// this person answers), then the quiet rows "Settled at the same time". A Member's own proposals have their section
// ("Your proposals"), the removals of the last 30 days theirs, and the people list the role on each person mark and,
// in the Owner's copy, the role in each row's More menu.
// Built on GET/POST/PUT …/owner (gui/api_owner.py, docs/API.md); the words are worked out in owner-state.js.
// Built of 0.17.0's components (docs/DESIGN.md 5.5): a proposal is proposalCard() (what and its severity tag, who
// and when, Accept (main) and Decline… (quiet), or the wait and Take back); the owner is a role on the person mark;
// placed in views.css (the block "Working together").
import { App, api, h, toast, showError, P, confirmDialog, dialog, watchJob, TERMINAL, store, shortTitle, switchControl,
  button, link, input, select, field, notice, noticeList, fold, listRow, listGroup, personMark, workState, tag, menu, aiWhere, helpMark,
  proposalCard as proposalCardBox, decisionCard } from "../lib.js";
import { whenText } from "./team-state.js";
import { OWNER_API, ownerName, sectionShown, splitProposals, heading, tabCount, proposer,
  whatParts, kindLine, conflictsText, answeredLine, declinedLine, applyText, docChip, proposedText,
  REMOVE_PROPOSAL, loosenConfirm, waitingFor,
  // roles (DESIGN-roles §5)
  LEVEL_WORDS, ROLE_WORD, NEEDS_UPDATE, CLASH_WAITING, TICK_FIRST, inbox, mineHeading, questionWords, refusedWords,
  offerWords, allowedText, bothWaysWords, settledWords, removedLine, restoredText, roleDialogWords, roleToast,
  SAME_PERSON_BODY, samePersonTitle, samePersonLine, peopleInOrder, roleSentence, canSetRoles, shortName,
  personOf } from "./owner-state.js";

const ACCEPT_ADDS = "Accept documents collaborators add, at once";
const ACCEPT_ADDS_HELP = "Off: each added document waits for your click. Removing a document and letting more AI read one always wait for you.";
const OWNER_HELP = "The owner decides which documents the project holds, how they are read and who may read them with AI. A colleague’s change to the documents is a proposal for the owner (or a Co-owner) to accept or decline.";
const NO_OWNER = "No owner yet: everything works as before. An owner decides which documents the project holds, how they are read and who may read them with AI.";

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

// questions about the owner put off with Not now: they stay in the list, but no longer count. 0.18.1: kept for the
// person in the project (the view's `later`), so in every browser; what an earlier version kept in this browser counts too
const laterKey = (project) => `owner-later:${project}`;
function laterSet(project, v) {
  let old = [];
  try { old = JSON.parse(store(laterKey(project)) || "[]"); } catch (_) { old = []; }
  return new Set([...(Array.isArray(old) ? old : []), ...((v && v.later) || [])]);
}
async function putOff(project, ids) {
  for (const id of ids) await api("POST", OWNER_API.question(P(project), P(id)), { answer: "later" });
}
// the documents ticked on an offer card, kept across the tab's redraws: project -> Set of doc ids
const ticked = new Map();
const tickedFor = (project) => { if (!ticked.has(project)) ticked.set(project, new Set()); return ticked.get(project); };

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
  count: (ctx) => tabCount(ctx.data && ctx.data.owner, new Set([...seenSet(ctx.project), ...laterSet(ctx.project, ctx.data && ctx.data.owner)])),
};
// a Member's own proposals that wait (a colleague's too, for whoever cannot answer them)
export const MINE_SECTION = { key: "mine", render: mineSection };
// "Removed in the last 30 days"
export const REMOVED_SECTION = { key: "removed", render: removedSection };
// The Team page: the owner. Become the owner (no owner yet), who it is and Hand over… (a team working with files, which
// has no people list), and the owner's setting. Its key is the tab section's: it reads the same answer (ctx.data.owner).
export const ROLES_SECTION = { key: "owner", render: rolesSection, load: OWNER_SECTION.load };

// The tab's section: only when something waits for this person's word (or a new reading runs). Becoming the owner,
// who the owner is and the owner's setting are the Team page's (rolesSection).
function ownerSection(ctx) {
  const v = ctx.data && ctx.data.owner;
  const hasFolder = !!(ctx.status && ctx.status.folder);
  if (!sectionShown(v, hasFolder)) return null;
  follow(ctx, v.job);
  if (v.can_claim) return null;
  const parts = splitProposals(v, seenSet(ctx.project));
  const box = inbox(v, laterSet(ctx.project, v));
  const running = !!(v.job && !TERMINAL.has(v.job.state));
  if (!box.cards && !parts.declined.length && !running && !(v.to_apply || []).length && !v.can_take_over
    && !(v.notices || []).length && !box.settled.length) return null;   // nothing waits: no section
  const body = [];
  if (v.can_take_over) body.push(takeOverBox(ctx, v));
  if (parts.declined.length) body.push(declinedBox(ctx, v, parts.declined));
  if (v.job && !TERMINAL.has(v.job.state)) {
    body.push(h("p", { class: "owner-job", role: "status" }, workState("running", v.job.title || "Reading with the new reader, as the owner accepted…")));
  }
  for (const row of v.to_apply || []) body.push(applyRow(ctx, row));
  // one card per decision, most serious first (DESIGN-roles §5.2)
  const cards = [...box.bothWays.map((p) => proposalCard(ctx, v, p)), ...box.questions.map((c) => questionCard(ctx, v, c)),
    ...box.refused.map((r) => refusedCard(ctx, v, r)), ...box.offers.map((g) => offerCard(ctx, v, g)),
    ...box.deciding.map((p) => proposalCard(ctx, v, p))];
  if (cards.length) body.push(h("ul", { class: "owner-cards" }, cards));
  // role changes and hand-overs made elsewhere, said once (ownership.view)
  if ((v.notices || []).length) body.push(noticeList(v.notices.map((n) => ({ kind: "info", text: n.text }))));
  if (box.settled.length) body.push(settledGroup(ctx, v, box.settled));
  if (parts.answered.length) body.push(answeredFold(ctx, v, parts));
  return sec("owner", heading(v, box.cards), ...body);
}

// The Team page's section: the owner
function rolesSection(ctx) {
  const v = ctx.data && ctx.data.owner;
  const hasFolder = !!(ctx.status && ctx.status.folder);
  if (!v || !sectionShown(v, hasFolder)) return null;
  if (v.can_claim) return sec("owner", heading(v), claimBox(ctx));
  if (!v.owner) return null;
  const body = [h("p", { class: "team-text owner-who" }, v.owner.me ? "You are the owner." : ["Owner: ", personMark([v.owner.name]), " ", v.owner.name, "."],
    // a team working with files has no people list: Hand over… is here
    v.owner.me && !hasFolder ? handOverPicker(ctx, v) : null, helpMark("About the owner", OWNER_HELP))];
  const said = !hasFolder ? roleSentence(v) : null;   // (with a folder, it is said under the people list)
  if (said) body.push(h("p", { class: "team-text" }, said));
  if (v.is_owner) body.push(acceptAddsSwitch(ctx, v));
  return sec("owner", "Owner", ...body);
}

// proposals that wait for someone else's word: a Member's own (with Take back), and a colleague's they cannot answer
function mineSection(ctx) {
  const v = ctx.data && ctx.data.owner;
  if (!v || v.can_claim) return null;
  const list = inbox(v).mine;
  if (!list.length) return null;
  return sec("mine", mineHeading(list), h("ul", { class: "owner-cards" }, list.map((p) => proposalCard(ctx, v, p))));
}

// no owner: say what an owner is, and offer to become it
function claimBox(ctx) {
  const b = button({ sm: true, icon: "shield", id: "owner-claim" }, "Become the owner");
  b.addEventListener("click", async () => {
    const ok = await confirmDialog({ title: "Become the owner of this project?", danger: false, confirmText: "Become the owner",
      message: h("div", {}, h("p", {}, "You then decide which documents the project holds, how they are read and who may read them with AI."),
        h("p", {}, "From then on, a colleague’s change to the documents is a proposal for you to accept or decline. Their copies learn it with your next round or file."),
        h("p", {}, "What a colleague removed or left out in their own copy before now becomes their proposal to you, all at once; what you changed in yours becomes the project’s.")) });
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
        "They will decide about its documents from now on; proposals that wait become theirs to answer. You stay in the team.",
        driveHandOverNote(ctx)].filter(Boolean),
      help: "Kept in the research log, for the team." });
    if (!ok) return;
    const to = others.find((x) => x.id === sel.value) || others[0];
    await handOver(ctx, to, ok.why, b);
  });
  return [" ", b];
}

// a team whose storage space is a folder in this person's drive (WebDAV): the folder stays there after a hand-over
function driveHandOverNote(ctx) {
  const dav = ctx.status && ctx.status.space && ctx.status.space.drive;
  if (!dav || !dav.mine) return null;
  return `The project’s folder “${dav.folder}” stays in your drive at ${dav.host}: after the hand-over, only you can share it with colleagues or stop sharing it. The new owner can take full control by moving the team to a folder in their own drive (Move to another storage space, on the Team page).`;
}

async function handOver(ctx, to, why, btn) {
  await act(ctx, btn, () => api("POST", OWNER_API.handOver(P(ctx.project)), why ? { to: to.id, why } : { to: to.id }),
    `${to.name} is the owner now. Their copy learns it with your next round or file.`);
}

// one request of the section; then the tab is read again and the focus goes to the section's heading
async function act(ctx, btn, call, said, kind = "ok", focus = "owner") {
  if (btn) btn.disabled = true;
  try {
    const r = await call();
    if (said) toast(typeof said === "function" ? said(r) : said, kind, { ttl: 7000 });
    await ctx.refresh({ force: true });
    ctx.focusHeading(document.getElementById(`team-h-${focus}`) ? focus : "owner");
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
  // answered both ways (DESIGN-roles §5.4): said once, as an error notice inside the card, for whoever decides it
  // again; the proposer and the Members read it in the card's state. Neither answer is the main button (even).
  const both = p.clash && p.can_decide ? bothWaysNotice(p, v) : null;
  const card = proposalCardBox({ id: `owner-card-${p.id}`, "aria-label": `A proposed change: ${p.what}`,
    what: whatNode(p, v), person: byMark(ctx, p), time: p.at ? whenText(p.at) : null, severity: p.severity,
    detail: [both, line ? h("p", { class: "owner-line" }, line) : null,
      (p.conflicts || []).length ? notice({ kind: "attention", class: "owner-conflicts" }, h("p", {}, conflictsText(p.conflicts.length))) : null],
    side: p.can_decide ? "owner" : "proposer", waiting: p.clash ? CLASH_WAITING : waitingFor(v), even: !!both,
    onAccept: (e) => accept(ctx, p, e.currentTarget), onDecline: (e) => decline(ctx, p, e.currentTarget),
    onTakeBack: p.can_take_back ? (e) => takeBack(ctx, p, e.currentTarget) : null });
  const time = card.querySelector(".proposal-by time");
  if (time && p.at) time.dateTime = new Date(p.at).toISOString();
  return card;
}

function bothWaysNotice(p, v) {
  const w = bothWaysWords(p, v);
  return notice({ kind: "error", live: false, class: "owner-line owner-both" },
    h("p", {}, h("strong", {}, "Answered both ways."), " ", w.who),
    h("p", {}, "Neither answer counts: ", h("em", {}, w.result), ". Decide it again."));
}

// ---- the decisions that are not proposals (decisionCard(), lib.js)
// a person of the view as a mark that stands alone ("Ben", "In the file of Eszter")
function markOf(v, x, opts = {}) {
  const p = personOf(x, v);
  if (!p) return null;
  return personMark([p.me ? "you" : p.name || "a colleague"], { name: "short", ...opts });
}

// a question about the owner: Follow …, and Keep … or Not now (a take-over stays in the list, no longer counted)
function questionCard(ctx, v, c) {
  const w = questionWords(c, v);
  const q = c.list[0];
  const actions = w.answers.map((a, i) => button({ kind: a.quiet ? "quiet" : "standard", sm: true, id: `owner-q-${a.id}-${a.answer || "later"}`,
    onClick: (e) => answerQuestion(ctx, a, w, e.currentTarget, c) }, a.label));
  return decisionCard({ id: `owner-q-${c.ids.join("-")}`, what: w.title, flag: w.tag, person: c.kind === "founders" ? null : markOf(v, q.by),
    time: q.at ? whenText(q.at) : null, said: w.said, body: h("p", { class: "owner-line" }, w.text), actions });
}

async function answerQuestion(ctx, a, w, btn, c) {
  if (!a.answer) {   // Not now
    try { await putOff(ctx.project, c.ids); } catch (e) { toast(e.message || String(e), "error"); return; }
    toast("Put off: it stays in the list until you answer it.", "info", { small: true, ttl: 5000 });
    await ctx.refresh({ force: true });
    ctx.focusHeading("owner");
    return;
  }
  if (a.answer === "follow") {
    const who = a.label.replace(/^Follow /, "");
    const ok = await confirmDialog({ title: `Follow ${who} as the owner?`, confirmText: a.label, danger: false,
      message: h("div", {}, h("p", {}, `${who} then decides about the documents in your copy, and the proposals that wait become ${who}’s to answer.`),
        h("p", {}, "Your own work stays as it is.")) });
    if (!ok) return;
  }
  await act(ctx, btn, () => api("POST", OWNER_API.question(P(ctx.project), P(a.id)), { answer: a.answer }),
    a.answer === "follow" ? `You follow ${a.label.replace(/^Follow /, "")} as the owner now.` : "Kept as it is. You are not asked about it again.");
}

// a change a file brought in this person's name, refused (DESIGN-roles §4.10)
function refusedCard(ctx, v, r) {
  const w = refusedWords(r, v);
  const id = `${r.kind}-${r.key}`;
  const back = w.takeBack ? button({ sm: true, id: `owner-take-back-${id}`, onClick: (e) => takeProjectBack(ctx, e.currentTarget) }, "Take the project back") : null;
  const dismiss = button({ kind: "quiet", sm: true, id: `owner-dismiss-${id}`,
    onClick: (e) => act(ctx, e.currentTarget, () => api("POST", OWNER_API.dismiss(P(ctx.project), P(r.kind), P(r.key)), {}), null) }, "Dismiss");
  return decisionCard({ id: `owner-refused-${id}`, what: w.title, person: markOf(v, r.via, { prefix: "In the file of" }),
    time: r.at ? whenText(r.at) : null, body: h("p", { class: "owner-line" }, w.text), actions: [back, dismiss] });
}

async function takeProjectBack(ctx, btn) {
  const ok = await confirmDialog({ title: "Take the project back?", confirmText: "Take the project back", danger: false,
    message: h("div", {}, h("p", {}, "You are the owner in your copy again. Every other copy is asked whom to follow, as for any take-over."),
      h("p", {}, "Nothing of the project was changed here.")) });
  if (!ok) return;
  await act(ctx, btn, () => api("POST", OWNER_API.takeProjectBack(P(ctx.project)), {}), "You took the project back. The other copies are asked with your next round or file.");
}

// a colleague's looser AI settings, one card per person (DESIGN-roles §5.2; the review's change 1): each document a
// tick box that starts unticked, both settings in its AI tags; the buttons wait for a tick and count what they do. A
// card of one document has no box: one sentence and two buttons.
const LEVEL_ICON = { cloud: "cloud", local: "house", none: "eye-off" };
const levelTag = (lv) => tag({ icon: LEVEL_ICON[lv] || "eye-off" }, LEVEL_WORDS[lv] || lv || "?");
function offerCard(ctx, v, g) {
  const sel = tickedFor(ctx.project);
  const docs = g.list.map((o) => o.doc);
  for (const d of [...sel]) if (!docs.includes(d) && !(v.offers || []).some((o) => o.doc === d)) sel.delete(d);
  const chosen = () => (g.list.length === 1 ? docs : docs.filter((d) => sel.has(d)));
  const w0 = offerWords(g, v, chosen().length);
  const allow = button({ sm: true, id: `owner-allow-${g.by.id}` }, w0.allow);
  const keep = button({ kind: "quiet", sm: true, id: `owner-keep-${g.by.id}` }, w0.keep);
  const why = h("span", { class: "muted small owner-tick-first", id: `owner-tick-${g.by.id}` }, TICK_FIRST);
  const paint = () => {
    const w = offerWords(g, v, chosen().length);
    allow.textContent = w.allow; keep.textContent = w.keep;
    allow.disabled = keep.disabled = !w.ready;
    why.hidden = w.ready;
    for (const b of [allow, keep]) { if (w.ready) b.removeAttribute("aria-describedby"); else b.setAttribute("aria-describedby", why.id); }
  };
  const answer = (yes, btn) => {
    const list = chosen();
    if (!list.length) return;
    act(ctx, btn, () => api("POST", OWNER_API.loosening(P(ctx.project)), { docs: list, allow: yes }), allowedText(list.length, yes))
      .then((r) => { if (r) for (const d of list) sel.delete(d); });
  };
  allow.addEventListener("click", () => answer(true, allow));
  keep.addEventListener("click", () => answer(false, keep));
  let body;
  if (w0.one) {
    body = h("p", { class: "owner-line" }, w0.text);
  } else {
    const rows = g.list.map((o) => {
      const box = h("input", { type: "checkbox", id: `owner-tick-doc-${o.doc}`, checked: sel.has(o.doc) });
      box.addEventListener("change", () => { if (box.checked) sel.add(o.doc); else sel.delete(o.doc); paint(); });
      return h("li", {}, h("label", { class: "owner-check", for: box.id }, box,
        h("span", { class: "owner-check-text" }, h("span", { class: "serif" }, o.title || "a document"),
          h("span", { class: "owner-levels" }, h("span", { class: "muted small" }, w0.here), levelTag(o.from),
            h("span", { class: "muted small" }, w0.theirs), levelTag(o.to)))));
    });
    body = [h("p", { class: "owner-line" }, w0.text), h("ul", { class: "owner-ticks" }, rows)];
  }
  paint();
  return decisionCard({ id: `owner-offer-${g.by.id}`, what: w0.title, flag: w0.tag,
    person: markOf(v, g.by, { role: ROLE_WORD[(v.people || []).find((x) => x.id === g.by.id)?.role] || (v.owner && v.owner.id === g.by.id ? "Owner" : null) }),
    body, actions: w0.one ? [allow, keep] : [allow, keep, why], ai: aiWhere(w0.ai, w0.where) });
}

// changed at the same time and settled by the rules (DESIGN-roles §5.4): quiet rows, the document's title opens it,
// Leave it so writes it again as it is (the row then goes in every copy)
function settledGroup(ctx, v, list) {
  const rows = list.map((c) => {
    const w = settledWords(c, v);
    const people = (c.people && c.people.length ? c.people : []).map((x) => personOf(x, v)).filter(Boolean);
    const leave = button({ kind: "quiet", sm: true, id: `owner-leave-${c.id}`,
      onClick: (e) => act(ctx, e.currentTarget, () => api("POST", OWNER_API.clash(P(ctx.project), P(c.id)), {}), "Left so. It goes from this list in every copy with your next round or file.") }, "Leave it so");
    return listRow({ person: people.length ? personMark(people.map((p) => (p.me ? "you" : p.name))) : null,
      title: c.title || "a document", href: c.doc ? `#/doc/${encodeURIComponent(c.doc)}` : null, serif: true,
      sub: w.remove ? [w.text, " ", w.remove, link({ href: "#/sources" }, w.where), "."] : w.text, actions: [leave] });
  });
  return h("div", { class: "owner-settled" }, listGroup(`Settled at the same time (${list.length})`, ...rows));
}

// "Removed in the last 30 days": each its title, who removed it and why, until when, Restore
function removedSection(ctx) {
  const v = ctx.data && ctx.data.owner;
  const list = (v && v.removed) || [];
  if (!list.length) return null;
  const rows = list.map((r) => listRow({ title: r.title || "a document", serif: true, sub: removedLine(r, v),
    actions: [button({ kind: "quiet", sm: true, icon: "undo", id: `owner-restore-${r.doc}`, "aria-label": `Restore “${shortTitle(r.title || "a document", 60)}”`,
      onClick: (e) => act(ctx, e.currentTarget, () => api("POST", OWNER_API.restore(P(ctx.project), P(r.doc)), {}),
        (res) => restoredText(r.title, !!(res && res.restored && res.restored.proposed)), "ok", "removed") }, "Restore")] }));
  return sec("removed", `Removed in the last 30 days (${list.length})`, listGroup(null, ...rows));
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
  const sw = teamSwitch("owner-accept-adds", ACCEPT_ADDS, !!v.accept_adds, null);
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
  return h("div", { class: "owner-setting team-switch" }, sw, helpMark("About accepting documents at once", ACCEPT_ADDS_HELP));
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
// the people list (team.js peopleSection): the role on the person mark, and in the Owner's copy each other person's
// More menu (Make a Co-owner… / Make a Member again…, Same person as…, and last Make owner…)
// ---------------------------------------------------------------------------------------------
const OWNER_TIP = "Decides which documents the project holds, how they are read and who may read them with AI.";
const CO_TIP = "Their changes to the documents hold for everyone, and they answer proposals.";
// the view's own row of a person (role, same_as, needs_update), or null
function viewPerson(ctx, person) {
  const v = ctx.data && ctx.data.owner;
  return v && person && person.id ? (v.people || []).find((x) => x.id === person.id) || null : null;
}
function roleWord(ctx, person) {
  const v = ctx.data && ctx.data.owner;
  if (!v || !person || !person.id) return null;
  if (v.owner && v.owner.id === person.id) return "Owner";
  const x = viewPerson(ctx, person);
  return x ? ROLE_WORD[x.role] || null : null;
}
// a person's mark in the people list: the role (docs/DESIGN.md 4.10) for the Owner and a Co-owner; a Member has none
export function ownerPerson(ctx, person, name) {
  const role = roleWord(ctx, person);
  const m = personMark([name || "a colleague"], { role });
  if (role) m.title = `${m.title}. ${role === "Owner" ? OWNER_TIP : CO_TIP}`;
  return m;
}
// the people in the order of the list: rows of one person stand together (a second computer under its person)
export function peopleRows(ctx, list) {
  const v = ctx.data && ctx.data.owner;
  if (!v || !(v.people || []).some((x) => x.same_as)) return list;
  const withSame = list.map((x) => ({ ...x, same_as: (viewPerson(ctx, x) || {}).same_as || null }));
  return peopleInOrder(withSame);
}
// the second line of a person's row: who else they are; or, for a Co-owner on an old ENLENS, an attention tag
export function personSub(ctx, person, line) {
  const v = ctx.data && ctx.data.owner;
  const x = viewPerson(ctx, person);
  if (x && x.needs_update && x.role === "co") return { text: NEEDS_UPDATE, warn: true };
  const same = x ? samePersonLine(x, v) : null;
  if (!same) return line;
  return { text: line && line.text ? [same, " · ", line.text] : same, warn: false };
}
// what the role of this copy's person means, under the people list's head (a Co-owner, a Member)
export function peopleNote(ctx) {
  const said = roleSentence(ctx.data && ctx.data.owner);
  return said ? h("p", { class: "team-text owner-role-note" }, said) : null;
}

// the Owner's More menu on another person's row (null otherwise). `more`: items after Make owner… (the Team page's
// Remove from the team…, for the copy that keeps the storage space's keys)
export function ownerMarks(ctx, person, more = []) {
  const v = ctx.data && ctx.data.owner;
  if (!v || !v.owner || !person || !person.id) return null;
  if (v.owner.id === person.id || person.me || !canSetRoles(v)) return null;
  const known = (v.people || []).find((x) => x.id === person.id);
  if (!known) return null;
  const name = person.name || known.name || "this colleague";
  const co = known.role === "co";
  const items = [
    co ? { text: "Make a Member again…", icon: "user", onClick: () => roleChange(ctx, person.id, name, "member") }
      : { text: "Make a Co-owner…", icon: "users", onClick: () => roleChange(ctx, person.id, name, "co") },
    { text: "Same person as…", icon: "users", onClick: () => samePerson(ctx, v, person.id, name, known.same_as || "") },
    "sep",
    { text: "Make owner…", icon: "shield", onClick: () => makeOwner(ctx, person.id, name) },
    ...more,
  ];
  const m = menu({ label: `More for ${name}`, items, id: `owner-more-${person.id}` });
  m.querySelector("summary").id = `owner-more-${person.id}-btn`;   // the focus finds it again after a redraw
  return m;
}

async function roleChange(ctx, id, name, to) {
  const w = roleDialogWords(name, to);
  const ok = await dialog({ title: w.title, body: h("div", {}, w.body.map((t) => h("p", {}, t))),
    actions: [{ text: "Cancel", value: null }, { text: w.ok, value: true, primary: true, id: "owner-dlg-ok" }] });
  if (!ok) return;
  await act(ctx, null, () => api("PUT", OWNER_API.role(P(ctx.project), P(id)), { role: to }), roleToast(name, to), "ok", "people");
}

async function samePerson(ctx, v, id, name, current) {
  const others = (v.people || []).filter((x) => x.id !== id);
  const sel = select({ id: "owner-dlg-same" }, h("option", { value: "" }, "Nobody"),
    others.map((x) => h("option", { value: x.id, selected: x.id === current }, x.me ? `${x.name} (you)` : x.name)));
  const ok = await dialog({ title: samePersonTitle(name), body: h("div", {}, h("p", {}, SAME_PERSON_BODY),
    field("The same person as", sel, { help: "Use it for a second computer of one person." })),
  actions: [{ text: "Cancel", value: null }, { text: "Save", value: true, primary: true, id: "owner-dlg-ok" }] });
  if (!ok) return;
  const to = sel.value || null;
  const other = others.find((x) => x.id === to);
  await act(ctx, null, () => api("PUT", OWNER_API.role(P(ctx.project), P(id)), { same_as: to }),
    to ? `${shortName({ name }, v)} and ${other && other.me ? "you" : shortName(other, v)} stand together now, as one person.` : `${shortName({ name }, v)} stands alone again.`, "ok", "people");
}

async function makeOwner(ctx, id, name) {
  const ok = await reasonDialog({ title: `Hand this project over to ${name}?`, confirmText: "Hand it over",
    message: ["They will decide about its documents from now on; proposals that wait become theirs to answer. You stay in the team.",
      driveHandOverNote(ctx)].filter(Boolean),
    help: "Kept in the research log, for the team." });
  if (!ok) return;
  await handOver(ctx, { id, name }, ok.why, null);
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
