// 0.18 (roadmap L3, L4): what the Team tab says about the shared folder, worked out from the app's answers without
// touching the page (no imports, so it also runs in Node for the tests). team.js draws it.
//
// The poller (L3, branch feature/0.18-poller) looks at the shared folder by itself every couple of minutes. Its state
// per project is `GET /api/projects/<p>/sync-poller` (the contract 3-poller fixed in the coordination log, 09:46): state
// off | paused | waiting | due | busy | running | offline, next_round_at, offline.retry_seconds, busy, round,
// last_round, every_seconds, paused, paused_all, came_in {count, seen_through, rounds: [{id, at, from, lines, count}]}.
// `PUT …/sync-poller {"paused"}` pauses one project, `POST …/sync-poller/seen {"through"}` marks what came in as seen,
// `PUT /api/sync-poller {"paused"?, "every_minutes"?}` the whole app. Everything the Team tab reads of it goes through
// `pollerState` below.
//
// STAND-IN until the parent merges feature/0.18-poller: GET …/sync-poller answers 404 and team.js passes `poller`
// null. There are then no rounds by themselves (`auto` false, no pause), "offline" is a problem of kind `unreachable`,
// the last round is the `last_round` job of GET …/shared-folder (or the last time work was read or written), what came
// in is the work brought in that the project keeps (`history` of GET …/together, from `sync_log`: every round and zip,
// newest first; else the last round's `result.read[].report.lines`), and "seen" is remembered in this browser
// (`seenAt`, kept by team.js). Nothing needs switching when the poller lands: its answer is used as soon as it exists.

export const POLLER_API = {
  state: (p) => `/api/projects/${p}/sync-poller`,          // GET; PUT {"paused": bool}
  seen: (p) => `/api/projects/${p}/sync-poller/seen`,      // POST {"through"?: round id}
  app: "/api/sync-poller",                                 // PUT {"paused"?: bool, "every_minutes"?: 1–60}
};
export const EVERY_CHOICES = [1, 2, 5, 10, 15, 30, 60];   // minutes between rounds (the poller takes 1–60; 2 by default)

const num = (x) => (x === null || x === undefined || x === "" || Number.isNaN(Number(x)) ? null : Number(x));
// an ISO string or unix seconds -> milliseconds (null when neither)
export function ms(t) {
  if (t === null || t === undefined || t === "") return null;
  if (typeof t === "number") return t < 1e12 ? t * 1000 : t;
  const d = Date.parse(t);
  return Number.isNaN(d) ? null : d;
}

// The lines of a bring-in report that say something came in (sync/report.py writes one line "Nothing new: …" when
// nothing did).
export function newsLines(lines) {
  return (lines || []).filter((l) => typeof l === "string" && l.trim() && !/^Nothing new\b/.test(l));
}

// What came in from colleagues in a finished round (a job view of kind folder-sync, with its result): one entry per
// colleague whose work came in, with the bring-in report's lines.
export function roundCameIn(round) {
  const res = round && round.result;
  if (!res || !Array.isArray(res.read)) return [];
  const at = ms(round.finished_at) || ms(res.at);
  return res.read.filter((r) => r && r.report && newsLines(r.report.lines).length)
    .map((r) => ({ at, from: r.name || (r.report.from && r.report.from.name) || "a colleague", person: r.id || null, id: null, lines: newsLines(r.report.lines) }));
}

// What came in, from the project's record of work brought in (GET …/together `history`: [{at, from: {id, name},
// lines}], newest first).
export function historyCameIn(history) {
  return (Array.isArray(history) ? history : []).map((x) => ({ at: ms(x.at), from: (x.from && x.from.name) || "a colleague",
    person: (x.from && x.from.id) || null, id: null, lines: newsLines(x.lines) })).filter((c) => c.lines.length);
}

// The last time work was read from or written to the folder (the last round, when the app does not know it: the
// poller and this page keep the last round only while the app runs)
function folderTimes(st) {
  const times = [...(st.people || []).map((x) => ms(x.last_read_at)), ms((st.me || {}).last_written_at)].filter((x) => x);
  return times.length ? Math.max(...times) : null;
}

// The poller's state for the Team tab, in one shape: {live, auto, paused, paused_here, paused_all, offline, next_at,
// last_at, backoff, busy, every, round, came_in: [{at, from, person, id, lines, seen}] (newest first), unseen,
// newest_id}. `poller`: GET …/sync-poller's answer (null: the stand-in); `seenAt` (ms) and `history` (GET …/together's)
// serve the stand-in, and give the live state the rounds seen before.
export function pollerState(status, seenAt = null, history = null, poller = null) {
  const st = status || {};
  const p = poller;
  const offlineProblem = (st.problems || []).some((x) => x.kind === "unreachable") || st.reachable === false;
  if (p && typeof p === "object" && typeof p.state === "string") {
    const ci = p.came_in || {};
    const fresh = (Array.isArray(ci.rounds) ? ci.rounds : []).map((r) => ({ at: ms(r.at), from: (r.from && r.from.name) || "a colleague",
      person: (r.from && r.from.id) || null, id: r.id ?? null, lines: newsLines(r.lines), seen: false })).filter((c) => c.lines.length)
      .sort((a, b) => (b.at || 0) - (a.at || 0));
    // what was seen before: the project's record of work brought in (rounds and zips), less the rounds not seen yet.
    // The same round is in both, with the same person and lines, at times a few seconds apart; each round not seen
    // takes away one entry only, the nearest in time (two rounds of a colleague often read alike)
    const rest = historyCameIn(history);
    for (const f of fresh) {
      let best = -1;
      rest.forEach((c, i) => {
        if (c.person !== f.person || c.lines.join("\n") !== f.lines.join("\n")) return;
        if (best < 0 || Math.abs((c.at || 0) - (f.at || 0)) < Math.abs((rest[best].at || 0) - (f.at || 0))) best = i;
      });
      if (best >= 0) rest.splice(best, 1);
    }
    const earlier = rest.map((c) => ({ ...c, seen: true }));
    const last = p.last_round || null;
    return { live: true, auto: p.state !== "off" && p.folder !== false, paused: !!p.paused || !!p.paused_all, paused_here: !!p.paused,
      paused_all: !!p.paused_all, offline: p.state === "offline" || !!p.offline || offlineProblem, next_at: ms(p.next_round_at),
      last_at: last ? ms(last.finished_at) : folderTimes(st), last_state: last ? last.state : null, backoff: p.offline ? num(p.offline.retry_seconds) : null, busy: p.state === "busy" ? p.busy : null,
      every: num(p.every_seconds), round: p.round || null, due: p.state === "due",
      came_in: [...fresh, ...earlier], unseen: num(ci.count) ?? fresh.length, newest_id: fresh.length ? fresh[0].id : null };
  }
  const last = st.last_round || null;
  const came = (history ? historyCameIn(history) : roundCameIn(last)).map((c) => ({ ...c, seen: !!seenAt && (c.at || 0) <= seenAt }));
  const lastAt = last ? ms(last.finished_at) : folderTimes(st);
  return { live: false, auto: false, paused: false, paused_here: false, paused_all: false, offline: offlineProblem, next_at: null,
    last_at: lastAt, last_state: last ? last.state : null, backoff: null, busy: null, every: null, round: null, due: false,
    came_in: came, unseen: came.filter((c) => !c.seen).length, newest_id: null };
}

// "Today 17:26", "Yesterday 17:26", "4 Nov 17:26" (the research log's way)
export function whenText(t, now = new Date()) {
  const m = ms(t);
  if (m === null) return "";
  const d = new Date(m);
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 86400000);
  if (diff === 0) return `Today ${time}`;
  if (diff === 1) return `Yesterday ${time}`;
  const sameYear = d.getFullYear() === now.getFullYear();
  return `${d.toLocaleDateString("en-GB", sameYear ? { day: "numeric", month: "short" } : { day: "numeric", month: "short", year: "numeric" })} ${time}`;
}

// "today at 17:26", "yesterday at 17:26", "on 4 Nov at 17:26" (inside a sentence)
export function whenPhrase(t, now = new Date()) {
  const w = whenText(t, now);
  if (!w) return "";
  const [day, time] = [w.slice(0, w.lastIndexOf(" ")), w.slice(w.lastIndexOf(" ") + 1)];
  return day === "Today" || day === "Yesterday" ? `${day.toLowerCase()} at ${time}` : `on ${day} at ${time}`;
}

// "in about 2 min", "in less than a minute"
export function inText(t, now = Date.now()) {
  const m = ms(t);
  if (m === null) return "";
  const s = Math.round((m - now) / 1000);
  if (s <= 45) return "in less than a minute";
  const min = Math.round(s / 60);
  return min < 60 ? `in about ${min} min` : `in about ${Math.round(min / 60)} h`;
}

// The sync state in words: {kind: "running" | "offline" | "paused" | "busy" | "failed" | "ok" | "never", text, sub}
export function syncLine(status, poll, now = Date.now()) {
  const st = status || {};
  const p = poll || pollerState(st);
  const job = (st.job && !["done", "error", "cancelled"].includes(st.job.state) && st.job) || p.round;
  if (job && ["running", "queued"].includes(job.state)) {
    const msg = (job.waiting_for && job.waiting_for.message) || (job.progress && job.progress.message) || (job.state === "queued" ? "Waiting for its turn…" : "");
    return { kind: "running", text: job.state === "queued" ? "A round waits its turn" : "Syncing now…", sub: msg };
  }
  if (p.due) return { kind: "running", text: "Starting a round…", sub: "" };
  if (p.offline) {
    const again = p.next_at ? ` ${inText(p.next_at, now)}` : p.backoff ? ` in about ${Math.max(1, Math.round(p.backoff / 60))} min` : "";
    return { kind: "offline", text: "Offline: the shared folder cannot be reached",
      sub: p.auto && !p.paused ? `Connect the drive or the cloud folder. ENLENS tries again by itself${again}.` : "Connect the drive or the cloud folder, then press Sync now." };
  }
  if (p.paused) {
    return { kind: "paused", text: p.paused_all && !p.paused_here ? "Paused for every project" : "Paused",
      sub: "No round runs by itself until you resume; Sync now still works." };
  }
  if (p.busy) return { kind: "busy", text: "The next round waits", sub: p.busy.message || `It starts when “${p.busy.title || "the work under way"}” has finished.` };
  const last = st.last_round;
  if (last && last.state === "error") {
    return { kind: "failed", text: `The last round did not work${p.last_at ? ` (${whenText(p.last_at, new Date(now))})` : ""}`, sub: last.error || "" };
  }
  const next = p.auto && p.next_at ? `next round ${inText(p.next_at, now)}` : "";
  if (p.last_at && p.last_state === "cancelled") {   // 0.18 real poller: a round stopped (a queued Sync now cancelled)
    return { kind: "ok", text: `Last round stopped: ${whenText(p.last_at, new Date(now))}`, sub: next ? `${next[0].toUpperCase()}${next.slice(1)}.` : "Sync now starts one." };
  }
  if (p.last_at) {
    return { kind: "ok", text: `Last round: ${whenText(p.last_at, new Date(now))}`,
      sub: next ? `Up to date; ${next}.` : p.auto ? "Up to date." : "Sync now sends your shared work and brings in your colleagues’." };
  }
  return { kind: "never", text: "No round yet", sub: p.auto ? (next ? `The first round runs by itself, ${next.replace("next round ", "")}.` : "The first round runs by itself in a moment.") : "Press Sync now for the first round." };
}

// What this person shared, by kind, from GET …/sharing: {kind: [items]} (items here, yours or nobody's known, shared),
// and how many they took back.
export function myShared(listing) {
  const out = {};
  let withdrawn = 0;
  for (const it of (listing && listing.items) || []) {
    if (!it.mine && it.owner) continue;   // a colleague's
    if (it.state === "withdrawn" && it.mine) withdrawn++;
    if (it.state !== "shared" || it.here === false) continue;
    (out[it.kind] = out[it.kind] || []).push(it);
  }
  for (const k of Object.keys(out)) out[k].sort((a, b) => String(b.at || "").localeCompare(String(a.at || "")));
  return { byKind: out, withdrawn, total: Object.values(out).reduce((n, l) => n + l.length, 0) };
}

// A colleague's line in "People in the folder": {text, warn}
export function personLine(person, problems = []) {
  const bits = [];
  if (person.app_version) bits.push(`ENLENS ${person.app_version}`);
  const own = problems.filter((x) => x.person && x.person.id === person.id);
  if (own.some((x) => x.kind === "newer_format")) return { text: [...bits, "made with a newer ENLENS: update to bring in their work"].join(" · "), warn: true };
  if (own.length) return { text: [...bits, "their work waits: see the problem above"].join(" · "), warn: true };
  if (person.waiting) bits.push(person.waiting === 1 ? "new work waiting: it comes in with the next round" : `new work waiting (${person.waiting} rounds): it comes in with the next round`);
  else bits.push("up to date");
  return { text: bits.join(" · "), warn: false };
}

// "Ben Okafor’s work came in.", "Ben’s and Chloé’s work came in." (a round's toast)
export function whoseWork(names) {
  const s = `${names.map((n) => `${n || "a colleague"}’s`).join(" and ")} work came in.`;
  return s[0].toUpperCase() + s.slice(1);
}

// A path pasted from Windows' "Copy as path" comes in quotes; a Mac's "Copy as Pathname" may end in a slash.
export function cleanPath(raw) {
  let p = String(raw || "").trim();
  if (p.length > 1 && ((p[0] === '"' && p.endsWith('"')) || (p[0] === "'" && p.endsWith("'")))) p = p.slice(1, -1).trim();
  if (p.length > 1 && /[\\/]$/.test(p) && !/^[A-Za-z]:[\\/]$/.test(p)) p = p.slice(0, -1);
  return p;
}

// 0.18.0rc2 (L7): a folder as a colleague sees it: the cloud folder it is in, by name, then the folders below it
// ("OneDrive – University of Amsterdam › Team › Project"). `clouds` is GET /api/cloud-folders' list; a folder in none of
// them is named by its last two folders. Returns {cloud: name | null, below: [names], text}.
export function folderAsSeen(path, clouds) {
  const windows = /^[A-Za-z]:[\\/]/.test(String(path || ""));
  const norm = (x) => { const t = String(x || "").replace(/\\/g, "/").replace(/\/+$/, ""); return windows ? t.toLowerCase() : t; };
  const keep = (x) => String(x || "").replace(/\\/g, "/").split("/").filter(Boolean);
  const p = norm(path);
  let best = null;
  for (const c of clouds || []) {
    const r = norm(c.path);
    if (r && (p === r || p.startsWith(`${r}/`)) && (!best || r.length > norm(best.path).length)) best = c;
  }
  if (best) {
    const below = keep(path).slice(keep(best.path).length);
    return { cloud: best.name, below, text: [best.name, ...below].join(" \u203a ") };
  }
  const last = keep(path).slice(-2);
  return { cloud: null, below: last, text: last.join(" \u203a ") };
}

// 0.18 stage 5: a round the poller started (a job marked `background`) stays out of the sidebar's work box for its
// first QUIET_SECONDS, then shows like any job (app.js drawStatus). The page learns that a round runs from GET /api/jobs
// (drawStatus) and from the poller's state (app.js syncNewsInit); these say when to look again, so that a long round
// shows once it has run that long, without looking every few seconds while nothing runs.
export const QUIET_SECONDS = 20;
const ENDED = ["done", "error", "cancelled"];
export function quietRound(j) {
  return !!j && !!j.background && !ENDED.includes(j.state) && (Number(j.seconds) || 0) < QUIET_SECONDS;
}
// Milliseconds until the longest-running quiet round reaches QUIET_SECONDS (null when none runs): the work box looks
// again then (a round still waiting to start counts from 0).
export function quietRoundAgainIn(jobs) {
  const quiet = (jobs || []).filter(quietRound);
  if (!quiet.length) return null;
  const oldest = Math.max(...quiet.map((j) => (j.state === "running" ? Number(j.seconds) || 0 : 0)));
  return Math.max(500, Math.ceil((QUIET_SECONDS - oldest) * 1000) + 250);
}
// Milliseconds until the next look at the poller's state (`every` unless a round is due sooner): just after the next
// round is due (the poller starts it within 5 s), so a long one is seen while it runs. Never sooner than 5 s, and not
// while the round waits for another job (busy), is paused, or the folder is offline (its next try is minutes away).
export function nextSyncLook(poller, every = 30000) {
  const p = poller || {};
  const due = num(p.next_round_in);
  if (!p.folder || due === null || p.state === "busy" || p.state === "offline" || p.state === "paused") return every;
  const at = (due + 5) * 1000;
  return at < every ? Math.max(5000, at) : every;
}

// An item's sharing line (share.js shareWhere): who gets a shared item, and when. From GET …/shared-folder (`status`)
// and GET …/sync-poller (`poller`), either null when it could not be read: {team, names, nextAt, sentAt}. team: the
// project has a shared folder or a storage space; names: the colleagues' first names ("Ben", "Ben and Chloé", "your 4
// colleagues", "your team" when none is known yet); nextAt: the next round, unless paused; sentAt: when your work
// last went out (the poller's last round that worked, else the last time this copy wrote to the folder).
export function briefOf(status, poller) {
  const st = status || {};
  const team = !!(status && (st.folder || st.space));
  const members = ((st.space && st.space.members) || []).filter((m) => m && !m.me && !m.removed);
  const people = members.length ? members : (st.people || []);
  const first = people.map((x) => String((x && x.name) || "").trim().split(/\s+/)[0]).filter(Boolean);
  const names = first.length === 0 ? "your team" : first.length === 1 ? first[0] : first.length === 2 ? `${first[0]} and ${first[1]}`
    : `your ${first.length} colleagues`;
  const p = poller && typeof poller === "object" ? poller : null;
  const nextAt = p && !p.paused && !p.paused_all && p.next_round_at ? p.next_round_at : null;
  const last = p && p.last_round;
  const sentAt = (last && last.state === "done" && last.finished_at) || (st.me && st.me.last_written_at) || null;
  return { team, names, nextAt, sentAt };
}

// The same, read for a project (kept 15 s per project, so a page drawn again does not ask again; forgetBrief() after a
// share or unshare, which moves the next round closer). `get(path)`: GET a
// path of the app (by default lib.js api(), loaded when first needed: this file has no imports, so it runs in Node).
const BRIEF_TTL = 15000;
const briefs = new Map();
export async function teamBrief(project, get = null) {
  const kept = briefs.get(project);
  if (kept && Date.now() - kept.at < BRIEF_TTL) return kept.brief;
  let read = get;
  let p = encodeURIComponent;
  if (!read) {
    const lib = await import("../lib.js");
    read = (path) => lib.api("GET", path);
    p = lib.P;
  }
  const or = (x) => Promise.resolve().then(() => read(x)).catch(() => null);
  const [status, poller] = await Promise.all([or(`/api/projects/${p(project)}/shared-folder`), or(POLLER_API.state(p(project)))]);
  const brief = briefOf(status, poller);
  briefs.set(project, { at: Date.now(), brief });
  return brief;
}
export function forgetBrief(project) { briefs.delete(project); }
