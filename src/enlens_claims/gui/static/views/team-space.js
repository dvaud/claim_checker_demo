// 0.18.0rc2 (roadmap L6): a storage space of the team's own, on the Team page (team.js). Without a way of working
// together yet, the first section offers it (recommended: Backblaze for most research groups, Cloudflare for large
// teams that grow quickly) and takes an invite link; with a space, a section says where it is, the invites waiting and
// what was set aside (its members are the page's people list, with Remove…). The owner (the copy that keeps the
// space's keys) invites, removes and moves. Joining a team as a new project is also in the sidebar's project menu
// (Join a team…, app.js). Built on gui/api_space.py; the round itself is the shared folder's (*Sync now*, team.js).
// Placed in views.css ("Working together"); the set-up runs in a dialog.
import { App, api, h, toast, showError, P, plural, field, button, link, input, select, fold, noticeList, notice, dialog,
  confirmDialog, listRow, listGroup, watchJob, navigate, textarea, copyLine, helpMark } from "../lib.js";

const S = (project) => `/api/projects/${P(project)}/space`;
let LINKS = null;
const links = async () => (LINKS = LINKS || await api("GET", "/api/space/links").catch(() => ({})));
const when = (iso) => (iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "long" }) : "");
export const SERVICE_NAME = { b2: "Backblaze", r2: "Cloudflare" };
// a member's part of their row on the Team page: "keeps the space’s keys · since 12 November"
export const memberSub = (m) => (m ? [m.keeper ? "keeps the space’s keys" : null, m.since ? `since ${when(m.since)}` : null].filter(Boolean).join(" · ") : "");

function section(key, title, ...children) {
  const id = `team-h-${key}`;
  return h("section", { class: `team-section team-sec-${key}`, "aria-labelledby": id, dataset: { key } },
    h("h3", { class: "team-h", id }, title), ...children.filter((c) => c !== null && c !== undefined));
}

const outLink = (href, text, id) => link({ href, target: "_blank", rel: "noopener noreferrer", id }, text);
// A sign-up page's address to type or paste in a browser of the person's choosing, with a Copy button: a link would
// open the default browser, where Backblaze's robot check can loop for ever and Cloudflare's sign-up can fail.
const typeAddress = (href, id) => {
  const row = copyLine(String(href || "").replace(/^https?:\/\//, ""), "Copy", "your browser's address bar", "link");
  row.id = id;
  return row;
};

// ---------------------------------------------------------------------------------------------
// no way of working together yet: a storage space (recommended), or an invite link
// ---------------------------------------------------------------------------------------------
export const SPACE_SETUP_SECTION = { key: "space-setup", render: setupSection };

const SPACE_HELP = "Your team rents a private storage space online, free at a team’s size. ENLENS puts what you share there and brings in what your colleagues share, by itself: nobody installs anything or looks for a folder. You set it up once, in about five minutes; colleagues join from a link you send them. Everything is locked on this computer before it leaves it, with a key only your team holds: the storage service cannot read your work.";

function setupSection(ctx) {
  const st = ctx.status;
  if (st.folder || st.space) return null;
  const b2 = button({ kind: "main", sm: true, id: "team-space-b2", onClick: () => setupDialog(ctx, "b2") }, "Backblaze…");
  const r2 = button({ sm: true, id: "team-space-r2", onClick: () => setupDialog(ctx, "r2") }, "Cloudflare…");
  const join = button({ sm: true, icon: "link", id: "team-space-join", onClick: () => joinDialog(ctx) }, "Join with an invite link…");
  return section("space-setup", "A storage space (recommended)",
    h("p", { class: "muted team-lead" }, "Private and encrypted, free at a team’s size; colleagues join from a link.",
      helpMark("About storage spaces", SPACE_HELP)),
    h("ul", { class: "team-choices" },
      h("li", {}, b2, h("span", { class: "muted small" }, "Most research groups: no card, storage in the EU.")),
      h("li", {}, r2, h("span", { class: "muted small" }, "Large teams that grow quickly: asks for a card; nothing is charged within the free amount."))),
    h("div", { class: "btn-row" }, join));
}

// The owner's set-up (or a move to another space), in a dialog. `move`: the team moves there.
export async function setupDialog(ctx, service, { move = false } = {}) {
  const L = await links();
  const err = h("p", { class: "field-error", role: "alert" });
  const progress = h("p", { class: "muted small", role: "status", "aria-live": "polite" });
  let fields, read;
  if (service === "b2") {
    const keyId = input({ mono: true, id: "space-b2-key-id", autocomplete: "off", spellcheck: "false" });
    const appKey = input({ mono: true, id: "space-b2-app-key", type: "password", autocomplete: "off", spellcheck: "false" });
    fields = h("ol", { class: "team-steps" },
      h("li", {}, "Make a free Backblaze account: open this address in your browser.",
        typeAddress(L.b2_signup || "https://www.backblaze.com/sign-up/b2-cloud-storage-backup-archive", "space-b2-signup"),
        "On the form, choose ", h("strong", {}, "EU Central"), " as the region before Create Account: it cannot be changed afterwards. No card is needed.",
        h("p", { class: "muted small", id: "space-b2-robot" }, "If Backblaze keeps asking whether you are a robot, use another browser, such as Safari, Chrome or Edge.")),
      h("li", {}, "Signed in to Backblaze in that browser, open ", h("strong", {}, "Application Keys"), " in the menu and choose ", h("strong", {}, "Generate New Master Application Key"), "."),
      h("li", {}, "Paste the two parts it shows:",
        field("keyID", keyId), field("applicationKey", appKey, { help: "ENLENS uses it once, to make a key of its own, and then forgets it." })));
    read = () => ({ key_id: keyId.value.trim(), app_key: appKey.value.trim() });
  } else {
    const token = input({ mono: true, id: "space-r2-token", type: "password", autocomplete: "off", spellcheck: "false" });
    const signedIn = h("input", { type: "checkbox", id: "space-r2-signed-in" });
    const tokenStep = h("li", { hidden: true }, outLink(L.r2_token || L.r2_dashboard, "Make the token ENLENS needs", "space-r2-token-link"),
      ", then choose ", h("strong", {}, "Create Token"), " at the bottom of the page, and paste the token here:", field("Token", token));
    signedIn.addEventListener("change", () => { tokenStep.hidden = !signedIn.checked; });
    fields = h("ol", { class: "team-steps" },
      h("li", {}, "Make a Cloudflare account: open this address in your browser.",
        typeAddress(L.r2_signup || "https://dash.cloudflare.com/sign-up", "space-r2-signup")),
      h("li", {}, "In the dashboard, open ", h("strong", {}, "R2 Object Storage"), " and switch it on. Cloudflare asks for a card; nothing is charged within the free amount."),
      h("li", {}, h("label", { for: "space-r2-signed-in", class: "team-check" }, signedIn, " I am signed in to Cloudflare")),
      tokenStep);
    read = () => ({ token: token.value.trim() });
  }
  const lock = { on: false };
  const who = move ? { el: null, save: async () => {} } : nameField();
  const where = service === "b2" ? "Backblaze" : "Cloudflare";
  await dialog({
    title: move ? `Move the team to a storage space at ${where}` : `A storage space at ${where}`,
    wide: true, lock,
    body: h("div", { class: "team-space-setup" }, who.el, fields, err, progress,
      move ? h("p", { class: "muted small" }, "Your colleagues’ copies follow by themselves at their next round. What you share is written there once more.") : null,
      h("p", { class: "muted small" }, "If the service says it is down for maintenance, try again later: nothing is changed until the set-up has finished.")),
    actions: [{ text: "Cancel", value: null }, {
      text: move ? "Move the team" : "Set it up", primary: true, id: "dlg-confirm",
      async onClick(dlg) {
        err.textContent = "";
        const body = read();
        if (service === "b2" && (!body.key_id || !body.app_key)) { err.textContent = "Paste both the keyID and the applicationKey."; return false; }
        if (service === "r2" && !body.token) { err.textContent = "Paste the token Cloudflare showed."; return false; }
        const btn = dlg.querySelector("#dlg-confirm");
        btn.disabled = true; lock.on = true;
        try {
          await who.save();
          let job = (await api("POST", move ? `${S(ctx.project)}/move` : `${S(ctx.project)}/${service}`, move ? { service, ...body } : body)).job;
          job = await watchJob(job.id, (j) => { progress.textContent = (j.progress && j.progress.message) ? `${j.progress.message}…` : "Working…"; }).promise;
          if (job.state !== "done") { err.textContent = job.error || "The set-up did not finish."; return false; }
          const r = job.result || {};
          if (r.accounts && r.accounts.length) {   // a token that reaches several Cloudflare accounts: one is chosen
            const sel = select({ id: "space-r2-account" }, r.accounts.map((a) => h("option", { value: a.id }, a.name || a.id)));
            const chosen = await dialog({ title: "Which Cloudflare account?", body: field("Account", sel),
              actions: [{ text: "Cancel", value: null }, { text: "Use it", value: true, primary: true }] });
            if (!chosen) return false;
            job = (await api("POST", `${S(ctx.project)}/r2`, { ...body, account_id: sel.value })).job;
            job = await watchJob(job.id).promise;
            if (job.state !== "done") { err.textContent = job.error || "The set-up did not finish."; return false; }
          }
          for (const w of (job.result && job.result.warnings) || []) toast(w, "warn", { ttl: 15000 });
          if (service === "b2" && !((job.result && job.result.warnings) || []).some((w) => /master key/.test(w))) {
            toast("Ready. In Backblaze, generate a new master application key now: it makes the one you pasted useless, and ENLENS no longer needs it.", "ok", { ttl: 15000 });
          } else toast(move ? "The team moves to the new storage space." : "Ready. Invite your colleagues from this page.", "ok");
          if (move && job.result && job.result.moved && job.result.moved.not_told && job.result.moved.not_told.length) {
            toast(`The old storage space could not be reached: send ${job.result.moved.not_told.join(", ")} a new invite.`, "warn", { ttl: 15000 });
          }
          lock.on = false;
          await ctx.refresh({ force: true });
          ctx.startRound();
          return true;
        } catch (e) { err.textContent = e.message || String(e); return false; }
        finally { lock.on = false; const again = dlg.querySelector("#dlg-confirm"); if (again) again.disabled = false; }
      } }],
    onOpen(dlg) { const f = dlg.querySelector("input"); if (f) f.focus(); },
  });
}

// Join from an invite link, in this project (the Team tab or page) or as a new project (the project menu's Join a team…,
// Projects).
export async function joinDialog(ctx) {
  const text = textarea({ mono: true, id: "space-join-link", rows: 4, spellcheck: "false", placeholder: "enlens://join#…" });
  const err = h("p", { class: "field-error", role: "alert" });
  const newProject = !ctx;
  const who = nameField();
  await dialog({
    title: "Join a team",
    body: h("div", {}, who.el, field("The invite link your colleague sent", text, { help: "It starts with enlens://join#. Paste all of it." }),
      newProject ? h("p", { class: "muted small" }, "ENLENS makes a new project for it; its first round brings the team’s documents and shared work.") : h("p", { class: "muted small" }, "This project then works through the team’s storage space."),
      err),
    actions: [{ text: "Cancel", value: null }, {
      text: "Join", primary: true, id: "dlg-confirm",
      async onClick(dlg) {
        err.textContent = "";
        const l = text.value.trim();
        if (!l) { err.textContent = "Paste the invite link first."; return false; }
        dlg.querySelector("#dlg-confirm").disabled = true;
        try {
          await who.save();
          if (newProject) {
            const r = await api("POST", "/api/join-team", { link: l });
            await App.refresh();
            toast(`You joined the team. “${r.project}” fills in with the next rounds: the documents come first.`, "ok", { ttl: 9000 });
            navigate("#/overview");
          } else {
            await api("POST", `${S(ctx.project)}/join`, { link: l });
            toast("You joined the team’s storage space. The first round starts now.", "ok");
            await ctx.refresh({ force: true });
            ctx.startRound();
          }
          return true;
        } catch (e) { err.textContent = e.message || String(e); dlg.querySelector("#dlg-confirm").disabled = false; return false; }
      } }],
    onOpen() { text.focus(); },
  });
}

// ---------------------------------------------------------------------------------------------
// with a space: where it is, who is in it, invites, what was set aside
// ---------------------------------------------------------------------------------------------
export const SPACE_SECTION = { key: "space", render: spaceSection };

function spaceSection(ctx) {
  const sp = ctx.status && ctx.status.space;
  if (!sp) return null;
  const keeper = sp.members.find((m) => m.keeper);
  const waiting = !sp.joined ? notice({ kind: "info" }, h("p", {}, `Waiting for ${keeper && !keeper.me ? keeper.name : "the owner"} to let you in: their ENLENS does it by itself at its next round. Until then, your colleagues do not see what you share; you already see theirs.`)) : null;
  const invites = sp.invites.map((i) => listRow({
    title: i.label ? `Invite for ${i.label}` : "An invite", sub: `made ${when(i.made_at)}, not used yet`,
    actions: [button({ kind: "quiet", sm: true, id: `space-withdraw-${i.part}`, onClick: () => withdraw(ctx, i) }, "Withdraw")],
  }));
  const aside = sp.set_aside || [];
  const invite = sp.keeper ? button({ kind: "main", sm: true, icon: "plus", id: "space-invite", onClick: () => inviteDialog(ctx) }, "Invite a colleague…") : null;
  const moveFold = sp.keeper ? fold({ sm: true, id: "space-move" }, "Move to another storage space",
    h("p", { class: "muted small team-text" }, "When the storage is lost, unpaid or should change: set up a new one. Every copy writes what it shares there once more; your colleagues’ copies follow by themselves."),
    h("div", { class: "btn-row" }, button({ sm: true, onClick: () => setupDialog(ctx, "b2", { move: true }) }, "Backblaze…"),
      button({ sm: true, onClick: () => setupDialog(ctx, "r2", { move: true }) }, "Cloudflare…"))) : null;
  const tech = fold({ sm: true, id: "space-tech" }, "Technical details",
    h("p", { class: "muted small" }, `Bucket ${sp.where}. Files are encrypted with AES-256-GCM using the project’s key and signed with each member’s own key (Ed25519). Keys are kept in ${sp.keychain === "file" ? "a file in ENLENS’s folder, readable by you only" : "this computer’s keychain"}.`));
  return section("space", "The storage space",
    h("p", { class: "team-text team-space-where" }, sp.where, sp.in_eu === false ? " · not in the EU" : null),
    waiting,
    aside.length ? noticeList([{ kind: "attention", text: `${plural(aside.length, "file")} in the storage space ${aside.length === 1 ? "was" : "were"} set aside: ${aside[0].message}${aside.length > 1 ? " (and others)" : ""} Nothing of ${aside.length === 1 ? "it" : "them"} came into this project.` }]) : null,
    invites.length ? listGroup(`Invites not used yet (${invites.length})`, ...invites) : null,
    invite ? h("div", { class: "btn-row" }, invite) : (sp.joined ? h("p", { class: "muted small team-text" }, `To add a colleague, ask ${keeper && !keeper.me ? keeper.name : "the owner"} for an invite.`) : null),
    moveFold, tech);
}

async function inviteDialog(ctx) {
  const name = input({ id: "space-invite-name", maxlength: 80, placeholder: "e.g. Ben de Wit", autocomplete: "off" });
  const out = h("div", {});
  const err = h("p", { class: "field-error", role: "alert" });
  let made = null;
  await dialog({
    title: "Invite a colleague", wide: true,
    body: h("div", {}, field("Who is it for? (optional)", name, { help: "Only for you, to tell the invites apart." }), err, out),
    actions: [{ text: "Close", value: null }, {
      text: "Make the link", primary: true, id: "dlg-confirm",
      async onClick(dlg) {
        if (made) return true;
        err.textContent = "";
        const btn = dlg.querySelector("#dlg-confirm");
        btn.disabled = true;
        try {
          made = await api("POST", `${S(ctx.project)}/invites`, { label: name.value.trim() });
          const msg = textarea({ mono: true, id: "space-invite-message", rows: 9, readonly: true });
          msg.value = made.message;
          const copy = button({ sm: true, icon: "copy", id: "space-invite-copy" }, "Copy the message");
          copy.addEventListener("click", async () => {
            try { await navigator.clipboard.writeText(made.message); toast("Copied. Send it to your colleague privately.", "ok", { ttl: 3000 }); }
            catch (_) { msg.select(); toast("Selected: copy it with Ctrl+C (or Cmd+C).", "info"); }
          });
          out.append(h("p", {}, "Send this to your colleague, privately (it holds the keys to your storage space). The link works once."), msg, h("div", { class: "btn-row" }, copy));
          btn.textContent = "Done";
          btn.disabled = false;
          ctx.refresh({ force: true });
          copy.focus();
          return false;
        } catch (e) { err.textContent = e.message || String(e); btn.disabled = false; return false; }
      } }],
    onOpen() { name.focus(); },
  });
}

async function withdraw(ctx, inv) {
  try {
    await api("DELETE", `${S(ctx.project)}/invites/${P(inv.part)}`);
    toast("The invite was withdrawn: its link opens nothing now.", "ok");
    await ctx.refresh({ force: true });
  } catch (e) { showError(e); }
}

export async function removeMember(ctx, m) {
  const ok = await confirmDialog({ title: `Remove ${m.name} from the storage space?`, confirmText: "Remove",
    message: h("div", {}, h("p", {}, `${m.name}’s keys to the storage space stop working, and the project’s key is replaced for everyone else. What ${m.name} shared before stays in the project, and what they already have stays with them.`)) });
  if (!ok) return;
  try {
    await api("DELETE", `${S(ctx.project)}/members/${P(m.part)}`);
    toast(`${m.name} was removed from the storage space.`, "ok");
    await ctx.refresh({ force: true });
  } catch (e) { showError(e); }
}

// Projects page: "Join a team" (a new project from an invite link; also in the sidebar's project menu)
export function joinTeamButton() {
  return button({ id: "pj-join-team", icon: "users", onClick: () => joinDialog(null) }, "Join a team");
}

// "Your name", when ENLENS does not know it yet: colleagues see the person's shared work under it (saved on the way)
function nameField() {
  const s = (App.state && App.state.settings) || {};
  if ((s.your_name || "").trim()) return { el: null, save: async () => {} };
  const name = input({ id: "space-your-name", maxlength: 60, autocomplete: "name", placeholder: "e.g. Anna de Vries" });
  return { el: field("Your name", name, { help: "Your colleagues see you under this name." }),
    save: async () => { if (name.value.trim()) { await api("PUT", "/api/settings", { your_name: name.value.trim() }); App.refresh().catch(() => {}); } } };
}
