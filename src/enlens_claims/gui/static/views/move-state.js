// Roles (DESIGN-roles §5.5, §5.7): the words of the move-zip question and of linking a folder made by someone else,
// worked out without touching the page (no imports, so it also runs in Node for the tests). projects.js draws them.
//
// peek (POST /api/projects/import, a move zip): {made, version, projects: [{name, documents}], person: {id, name},
// settings: {key: value shown}, servers: [{key, url, here}], fresh}.
const plural = (n, one, many) => `${n} ${n === 1 ? one : many || one + "s"}`;

export const MOVE_TITLE = "This file moves ENLENS from another computer";
export const MOVING = { title: "I am moving to this computer.", text: "The other computer stops. You stay the same person here." };
export const BOTH = { title: "I will use both computers.", text: "This computer becomes a second person in your projects. The owner can mark both as you." };
export const NOT_FRESH = "This computer already has projects, so it keeps its own name and settings.";

// "3 projects, made on 12 November with ENLENS 0.17.1, by Dávid."
export function moveSummary(peek) {
  const p = peek || {};
  const n = (p.projects || []).length;
  const m = Date.parse(p.made || "");
  const when = Number.isFinite(m) ? ` on ${new Date(m).toLocaleDateString("en-GB", { day: "numeric", month: "long" })}` : "";
  const made = when || p.version ? `, made${when}${p.version ? ` with ENLENS ${p.version}` : ""}` : "";
  const by = p.person && p.person.name ? `, by ${p.person.name}` : "";
  return `${plural(n, "project")}${made}${by}.`;
}
// the name proposed for this computer when both are used: "Dávid (2)"
export const secondName = (peek) => (peek && peek.person && peek.person.name ? `${peek.person.name} (2)` : "");
// the addresses of the other computer's servers that are not on this computer: each asks its own tick
export const foreignServers = (peek) => ((peek && peek.servers) || []).filter((s) => !s.here);
export const serverLine = (url) => [`Send what ENLENS reads to `, url, ` as the other computer did.`];
// what the move did, for the toast
export function movedText(r) {
  const moved = (r && r.moved) || r || {};
  const list = moved.projects || [];
  const renamed = list.filter((p) => p.from && p.name !== p.from);
  return `${plural(list.length, "project")} brought in${moved.settings ? ", with the settings" : ""}.${renamed.length ? ` Renamed because the name was taken: ${renamed.map((p) => `${p.from} → ${p.name}`).join(", ")}.` : ""}`;
}

// Linking a folder made by someone else (409 with the report of bundle.check_linked)
export function linkCleanTitle(report) {
  const who = report && report.other && report.other.name;
  return who ? `This folder is ${who}’s project.` : "This folder is another person’s project.";
}
export const LINK_CLEAN = "ENLENS will clean it like a project brought in from a file: its record of a shared folder, file paths on the other computer, and what was stored for speed go. The documents and the work stay.";
