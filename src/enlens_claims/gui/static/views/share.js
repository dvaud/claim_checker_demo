// 0.18 (roadmap L1): private until shared, on each item's own page and in the Team tab (team.js). An item is a check, a
// set of themes, a codebook, a note or highlight, an entry you wrote in the research log, or a link between terms.
// A small tag says whether it is private, shared or withdrawn (shared once, taken back) and whose it is; Share and
// Unshare stand beside it in a list, for its owner only. On an item's own page its maker has a choice instead (Private |
// Shared with your team), and while it is shared a line says where it goes (shareWhere). Built on GET/POST …/sharing
// (gui/api_sharing.py, docs/API.md).
// 0.17.0's components (docs/DESIGN.md 5.5): the state is shareState(), whose it is a person mark (lib.js personMark(),
// the initials and the name as its tooltip), Share and Unshare small buttons, the two zips download buttons. Placed in
// views.css (the block "Working together").
import { App, api, h, replace, toast, showError, P, shortTitle, helpMark, download, dialog, button, downloadButton, notice, tag,
  personMark, shareState, choice, icon, link } from "../lib.js";
import { askWhy } from "./versions.js";
import { teamBrief, forgetBrief, whenPhrase, inText, ms } from "./team-state.js";

// the words for one item of each kind, in a sentence ("Shared the check …")
export const KIND_WORDS = { check: "check", themes: "set of themes", codebook: "codebook", note: "note", log: "entry", link: "link between terms" };
export const KIND_MANY = { check: "Checks", themes: "Sets of themes", codebook: "Codebooks", note: "Notes and highlights", log: "Research log entries", link: "Links between terms" };

const STATE_TEXT = { private: "Private", shared: "Shared", withdrawn: "Withdrawn" };   // the words of shareState()
export const SHARING_HELP = "Private: only you see it. Shared: your colleagues get it with your work, through the team's storage space or shared folder, or in the file “Send what you shared (.zip)”. Withdrawn: shared once and taken back; it is no longer sent, and colleagues keep what they had, marked as withdrawn. Only the person who made an item can share it or take it back.";

// Where an item is shown ("#/h/…"), or null when it has no page of its own.
export function itemHref(item) {
  const k = encodeURIComponent(item.key || "");
  if (item.here === false) return null;
  switch (item.kind) {
    case "check": return `#/h/${k}`;
    case "themes": return `#/themes/${k}`;
    case "codebook": return `#/codebooks/${k}`;
    case "note": return "#/notes";
    case "log": return "#/log";
    case "link": return `#/concepts/${encodeURIComponent(String(item.key || "").split("|")[0])}`;
    default: return null;
  }
}

// The tag: Private / Shared / Withdrawn by … (shareState(), its tooltip saying what it means for this item)
export function shareTag(item) {
  const st = STATE_TEXT[item.state] ? item.state : "private";
  const text = st === "withdrawn" && item.by ? `Withdrawn by ${item.by}` : STATE_TEXT[st];
  const why = { private: item.mine ? "Only you see it, until you share it." : "It reached you in a whole project from its maker, who has not shared it: you see it, and it is never passed on.",
    shared: item.mine ? "Your colleagues get it with your work." : "Its maker shared it with the team.",
    withdrawn: "Shared once and taken back: it is no longer sent. Colleagues keep what they had." }[st];
  const t = shareState(st);
  t.title = why;
  if (text !== STATE_TEXT[st]) t.lastChild.textContent = text;
  return t;
}

// Whose the item is, when it is not yours: a person mark that stands alone, so with the name ("By Anna"; docs/DESIGN.md
// 5.5), or "maker not known" (made by an ENLENS that
// did not yet keep its maker: before 0.16 for checks, themes and codebooks, before 0.18 for links between terms)
export function ownerMark(item) {
  if (item.mine) return null;
  if (!item.owner) return tag({ title: "Made with an older ENLENS that did not keep who made it, so anyone in the team may share it or take it back." }, "maker not known");
  const m = personMark([item.owner.name], { name: "short", prefix: "By" });
  m.title = `${item.owner.name} made it: only they can share it or take it back.`;
  return m;
}

// Share an item (and what it needs: a check's codebook), with a toast saying what happened. Returns the answer or null.
export async function shareItem(item, opts = {}) {
  try {
    const r = await api("POST", `/api/projects/${P(App.project)}/sharing/share`, { items: [{ kind: item.kind, key: item.key }] });
    const name = shortTitle(item.title || item.key, 60);
    const parts = [];
    if ((r.shared || []).length) parts.push(`Shared “${name}”: your colleagues get it with your work from now on.`);
    else if ((r.already || []).some((x) => x.kind === item.kind && x.key === item.key)) parts.push(`“${name}” was shared already.`);
    for (const x of r.also || []) parts.push(`Its ${KIND_WORDS[x.kind]} “${shortTitle(x.title || x.key, 50)}” is shared with it, so colleagues can read its codes.`);
    for (const x of r.cannot || []) parts.push(`Its ${KIND_WORDS[x.kind]} “${shortTitle(x.title || x.key, 50)}” is a colleague’s and not shared by them: colleagues without it see the ${KIND_WORDS[item.kind]} without its codes’ descriptions.`);
    toast(parts.join(" ") || "Shared.", (r.cannot || []).length ? "warn" : "ok", { ttl: (r.also || []).length || (r.cannot || []).length ? 9000 : 5000, group: "share" });
    if (opts.onDone) opts.onDone(r);
    return r;
  } catch (e) { showError(e); return null; }
}

// Take a shared item back, after saying what that does (with an optional why, kept in the research log).
export async function unshareItem(item, opts = {}) {
  const name = shortTitle(item.title || item.key, 80);
  const ok = await askWhy({ title: `Unshare “${shortTitle(item.title || item.key, 50)}”?`, confirmText: "Unshare", danger: false,
    placeholder: "For example: not ready yet, shared by mistake",
    message: h("div", {}, h("p", {}, `It stops going to your colleagues from now on. What they already have of it stays with them, marked as withdrawn by you: nothing is taken from anyone's copy.`),
      h("p", { class: "muted small" }, "You can share it again later.")) });
  if (!ok) return null;
  try {
    const r = await api("POST", `/api/projects/${P(App.project)}/sharing/unshare`, { items: [{ kind: item.kind, key: item.key }], why: ok.why || undefined });
    toast((r.withdrawn || []).length ? `Unshared “${name}”: it is no longer sent. Colleagues keep what they had, marked as withdrawn.` : `“${name}” was not shared.`, "ok", { group: "share" });
    if (opts.onDone) opts.onDone(r);
    return r;
  } catch (e) { showError(e); return null; }
}

// An id for an item's button that stays the same when the page is drawn again (`prefix`: where it is, so the same item
// in the Team tab and on its page has two)
export function shareId(item, prefix = "share") {
  return `${prefix}-${item.kind}-${String(item.key).replace(/[^A-Za-z0-9_-]/g, "_")}`;
}

// The button that changes an item's state (only for its owner, or anyone when its maker is not known); null otherwise.
// A small button, Unshare quiet (docs/DESIGN.md 5.5); `opts.link`: in a list, without its icon. `onChanged(r)` may
// return a promise (the page drawn again): the focus then goes back to the item's new button.
export function shareButton(item, onChanged, opts = {}) {
  if (!item.can_change) return null;
  const name = shortTitle(item.title || item.key, 60);
  const shared = item.state === "shared";
  const label = shared ? "Unshare" : item.state === "withdrawn" ? "Share again" : "Share";
  const id = shareId(item, opts.idPrefix);
  const b = button({ kind: shared ? "quiet" : "standard", sm: true, icon: opts.link ? null : shared ? "undo" : "users", class: "share-act", id,
    "aria-label": `${label}: ${KIND_WORDS[item.kind] || "item"} “${name}”`,
    title: shared ? "Stop sending it to your colleagues (what they have stays with them)" : "Give it to your colleagues with your work" }, label);
  b.addEventListener("click", async () => {
    b.disabled = true;
    const r = shared ? await unshareItem(item) : await shareItem(item);
    b.disabled = false;
    if (!r) { b.focus(); return; }
    if (onChanged) await onChanged(r);
    const again = document.getElementById(id);
    if (again && again !== b) again.focus();
  });
  return b;
}

// Tag, whose it is, and the button, in one quiet row (for a card in a list: notes, log entries, links).
// `opts.owner` false: the card says whose it is already.
export function shareInline(item, onChanged, opts = {}) {
  if (!item) return null;
  return h("span", { class: "share-inline" }, shareTag(item), opts.owner === false ? null : ownerMark(item), shareButton(item, onChanged, { link: true }));
}

// The sharing choice on an item's own page, for its maker (or anyone, when its maker is not known): Private | Shared
// with your team (Shared, while the project has no team), the chosen one soft teal (docs/DESIGN.md 4.6, 5.5). A group
// of two pressed-state buttons (choice()'s filter kind): in its radio kind an arrow key would pick, and so share an
// item by itself. Taking it back asks first (unshareItem): the choice stays where it was until the answer.
// `onChanged(r)` may return a promise (the page drawn again): the focus then goes to the chosen value of the new choice.
export function shareChoice(item, onChanged, opts = {}) {
  const id = shareId(item, opts.idPrefix);
  const now = item.state === "shared" ? "shared" : "private";
  let busy = false;
  const c = choice({ label: `Who sees this ${KIND_WORDS[item.kind] || "item"}`, value: now, id, class: "share-choice", filter: true,
    options: [["private", [icon("house", { size: 13 }), "Private"], null, "Only you see it"],
      ["shared", [icon("users", { size: 13 }), opts.team ? "Shared with your team" : "Shared"], null,
        opts.team ? "Your team gets it with your work" : "Colleagues get it with your work"]],
    onPick: async (v) => {
      if (v === now || busy) { c.set(now); return; }
      busy = true;
      if (v === "private") c.set(now);   // the dialog asks first: nothing has changed yet
      const btns = [...c.querySelectorAll("button")];
      btns.forEach((b) => { b.disabled = true; });
      const r = v === "shared" ? await shareItem(item) : await unshareItem(item);
      busy = false;
      if (!r) {
        c.set(now);
        btns.forEach((b) => { b.disabled = false; });
        const back = c.querySelector(`[data-value="${now}"]`);
        if (back) back.focus();
        return;
      }
      if (onChanged) await onChanged(r);
      const again = document.getElementById(id);
      const chosen = again && again.querySelector('[aria-pressed="true"]');
      if (chosen) chosen.focus();
    } });
  return c;
}

// The quiet line under a shared item's choice: who gets it and when, and where to see it (the Team tab, at What you
// shared); a withdrawn item says what that means. `brief`: teamBrief()'s answer, or null. Null when there is nothing
// to say (a private item).
export function shareWhere(item, brief) {
  if (item.state === "withdrawn") return h("p", { class: "share-where" }, "Taken back: colleagues keep what they had, marked as withdrawn.");
  if (item.state !== "shared") return null;
  if (!brief || !brief.team) {
    return h("p", { class: "share-where" }, "No team yet: it goes to colleagues in the file “Send what you shared (.zip)”. ",
      link({ href: "#/team" }, "Set up a team"));
  }
  const sent = brief.sentAt && ms(brief.sentAt) !== null && ms(brief.sentAt) > (ms(item.at) || 0);
  const words = sent ? `Sent to your team ${whenPhrase(brief.sentAt)}.`
    : `Goes to ${brief.names} at the next round${brief.nextAt ? ", " + inText(brief.nextAt) : ""}.`;
  return h("p", { class: "share-where" }, words, " ",
    link({ kind: "jump", class: "share-see", onClick: () => window.dispatchEvent(new CustomEvent("enlens-drawer", { detail: { tab: "team", section: "shared" } })) },
      "See what you shared"));
}

// The row on an item's own page: it reads the item's state itself and draws it again after a change. For its maker,
// the choice and the line under it; for anyone else, the tag, whose it is and that only they can change it. Stays
// hidden for something that is not an item of the project (a codebook that comes with ENLENS, a removed check).
// The same element can be put back into a page that draws its head again.
export function shareBar(kind, key, opts = {}) {
  const box = h("div", { class: "share-bar", role: "group", "aria-label": "Sharing with your team", hidden: true });
  let item = null;
  let brief = null;
  const load = async () => {
    const project = App.project;
    try {
      const [r, b] = await Promise.all([api("GET", `/api/projects/${P(project)}/sharing/${kind}/${P(key)}`),
        teamBrief(project).catch(() => null)]);
      if (project !== App.project) return;
      item = r.item;
      brief = b;
      draw();
    } catch (e) {
      box.hidden = true;
      if (e.status !== 404) console.warn("Sharing:", e.message);
    }
  };
  const draw = () => {
    if (!item) { box.hidden = true; return; }
    const help = helpMark("About sharing", SHARING_HELP);
    if (!item.can_change) {
      const colleague = item.owner && !item.mine;
      replace(box, shareTag(item), ownerMark(item),
        colleague ? h("span", { class: "muted small" }, `only ${item.owner.name} can share it or take it back`) : null, help);
    } else {
      const pick = shareChoice(item, async () => { forgetBrief(App.project); await load(); if (opts.onChange) opts.onChange(); },
        { team: !!(brief && brief.team) });
      replace(box, pick, item.state === "withdrawn" ? shareTag(item) : null,
        !item.mine && !item.owner ? ownerMark(item) : null, help, shareWhere(item, brief));
    }
    box.hidden = false;
  };
  box.reload = load;
  load();
  return box;
}

// Every item of one kind, by key: Map key -> item (for a list page). An empty map when it cannot be read.
export async function sharingOf(kind) {
  try {
    const r = await api("GET", `/api/projects/${P(App.project)}/sharing?kind=${encodeURIComponent(kind)}`);
    return new Map((r.items || []).map((i) => [i.key, i]));
  } catch (e) { console.warn("Sharing:", e.message); return new Map(); }
}

// ---------------------------------------------------------------------------------------------
// the two downloads of a project: what you shared (for a colleague), or the whole project (to move it)
// ---------------------------------------------------------------------------------------------
const today = () => new Date().toISOString().slice(0, 10);
export const ZIP_WORDS = {
  shared: { text: "Send what you shared (.zip)", what: "For a colleague: the documents and the work you shared, nothing private." },
  all: { text: "Download the whole project (.zip)", what: "To move the project to another computer of yours: everything, your private work too." },
};

// Before the whole project leaves: it holds private work, and a colleague on ENLENS 0.17 would see it all.
export async function confirmWholeProject(project) {
  return dialog({
    title: "Download the whole project?",
    body: h("div", {},
      h("p", {}, "This file holds everything in the project, your private checks, notes and entries too. It is for moving the project to another computer of yours."),
      notice({ kind: "attention", role: "note" },
        h("p", {}, h("strong", {}, "Not for a colleague. "), "A colleague who opens it with ENLENS 0.17.0rc5 or earlier sees all your private work, and that version cannot keep it private. To give your work to a colleague, send what you shared.")),
      h("p", { class: "muted small" }, `Project: ${project}`)),
    actions: [{ text: "Cancel", value: null }, { text: "Send what you shared instead", value: "shared" }, { text: "Download the whole project", value: "all", primary: true }],
  });
}

export async function downloadProject(project, scope) {
  const shared = scope === "shared";
  download(`/api/projects/${P(project)}/export.zip${shared ? "?scope=shared" : ""}`).catch(showError);
  toast(shared ? `Your download starts: “ENLENS shared work - ${project} - ${today()}.zip”. It holds the documents and what you shared; nothing private.`
    : `Your download starts: “ENLENS project - ${project} - ${today()}.zip”. It holds everything in this project; a large project takes a moment.`, "ok", { ttl: 7000 });
}

// A download button for one of the two zips (a small quiet button: it makes a file, docs/DESIGN.md 4.1). `opts`: text,
// title, id. The whole project asks first.
export function zipButton(project, scope, opts = {}) {
  const w = ZIP_WORDS[scope === "shared" ? "shared" : "all"];
  const b = downloadButton({ title: opts.title || w.what, id: opts.id || null }, opts.text || w.text);
  b.addEventListener("click", async () => {
    if (scope === "shared") { downloadProject(project, "shared"); return; }
    const pick = await confirmWholeProject(project);
    if (pick) downloadProject(project, pick);
  });
  return b;
}
