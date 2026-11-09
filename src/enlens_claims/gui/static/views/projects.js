// Projects: create, link an existing workspace folder, switch, remove.
import { quickLookButton } from "./quicklook.js";
import { App, api, h, icon, replace, append, toast, showError, field, navigate, dialog, confirmDialog, pageHead, P, fmt, download } from "../lib.js";
import { projectZipLink } from "./result.js";
import { FEATURES } from "../features.js";

// Import a project from a zip made with "Download as a zip" (on this or another computer). 0.10: the same dialog takes
// the zip of "Move ENLENS to another computer" (every project and the settings); its projects keep their names.
const MOVE_NAME = /^ENLENS - all projects and settings - .*\.zip$/i;
export function importProjectDialog(opts = {}) {
  const file = h("input", { type: "file", accept: ".zip,application/zip", class: "input", id: "import-zip" });
  const name = h("input", { class: "input", type: "text", placeholder: "the name the project had", autocomplete: "off", maxlength: 60 });
  const nameField = field("Project name", name, { help: "Proposed from the file name. If a project of that name exists already, you are asked for another." });
  nameField.hidden = !!opts.move;  // a zip of everything keeps the names its projects had
  const err = h("div", { class: "field-error", role: "alert" });
  const status = h("div", { class: "muted small", "aria-live": "polite" });
  const moveNote = h("p", { class: "small", hidden: true }, "This file holds everything from another computer: each project comes in under its own name (with “(2)” when a project of that name is here already)", opts.move ? ", and the settings come with it when this computer has no project yet." : ".");
  let proposed = "";
  file.addEventListener("change", () => {
    const f = file.files && file.files[0];
    err.textContent = "";
    if (!f) return;
    const everything = MOVE_NAME.test(f.name);
    nameField.hidden = everything;
    moveNote.hidden = !everything;
    // "ENLENS project - Demo - 2026-10-28.zip" -> "Demo"
    const m = /^ENLENS project - (.+?) - \d{4}-\d{2}-\d{2}\.zip$/i.exec(f.name);
    proposed = (m ? m[1] : f.name.replace(/\.zip$/i, "")).trim();
    if (!everything && (!name.value.trim() || name.value === proposed)) name.value = proposed;
    status.textContent = `${f.name} · ${fmt.bytes(f.size)}`;
  });
  return dialog({
    title: opts.move ? "Bring ENLENS from another computer" : "Import a project (.zip)",
    body: h("div", {},
      opts.move ? h("p", { class: "muted" }, "On the other computer, open Projects and choose “Download everything (.zip)” under Move ENLENS to another computer. Bring that file here (a USB stick, a shared folder, an e-mail to yourself), then choose it below.")
        : h("p", { class: "muted" }, "A zip made with “Download as a zip”, from this or another computer: the documents, the results and the notes come with it, as a new project. A project folder zipped by hand works too, and so does a zip of everything (from “Move ENLENS to another computer”)."),
      field("Zip file", file), status, moveNote, nameField, err),
    actions: [{ text: "Cancel", value: null }, {
      text: "Import", value: true, primary: true, id: "dlg-confirm",
      async onClick(dlg) {
        err.textContent = "";
        const f = file.files && file.files[0];
        if (!f) { err.textContent = "Choose a zip file first."; file.focus(); return false; }
        const typed = nameField.hidden ? "" : name.value.trim();
        const btn = dlg.querySelector("#dlg-confirm");
        btn.disabled = true; status.textContent = `Importing ${f.name}… this can take a moment for a large project.`;
        try {
          const r = await api("POST", `/api/projects/import${typed ? `?name=${encodeURIComponent(typed)}` : ""}`, f);
          await App.refresh();
          if (r.moved) {
            const n = r.moved.projects.length;
            const renamed = r.moved.projects.filter((p) => p.name !== p.from);
            toast(`${n} ${n === 1 ? "project" : "projects"} brought in${r.moved.settings ? ", with the settings" : ""}.${renamed.length ? ` Renamed because the name was taken: ${renamed.map((p) => `${p.from} → ${p.name}`).join(", ")}.` : ""}`, "ok", { ttl: 9000 });
            navigate(n ? "#/projects" : "#/overview");
          } else {
            toast(`Project “${r.project.name}” imported: ${r.project.documents} ${r.project.documents === 1 ? "document" : "documents"}, ${r.project.hypotheses} ${r.project.hypotheses === 1 ? "result" : "results"}. It is now the current project.`, "ok", { ttl: 7000 });
            navigate("#/hypotheses");
          }
        } catch (e) {
          btn.disabled = false; status.textContent = "";
          err.textContent = e.status === 409 ? `${e.message} Type another name and try again.` : e.message;
          if (e.status === 409) { name.focus(); name.select(); }
          return false;
        }
        return true;
      },
    }],
    onOpen(dlg) {
      const btn = dlg.querySelector("#dlg-confirm");
      name.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); btn.click(); } });
      file.focus();
    },
  });
}

// 0.14: shared projects (sync.py). Each person keeps their own copy of a project; "Download as a zip" carries their
// work, and "Bring in a colleague's work" merges a colleague's zip into this copy.
const whose = (name) => (name === "you" ? "your" : `${name}’s`);

export function bringInDialog(project) {
  const file = h("input", { type: "file", accept: ".zip,application/zip", class: "input", id: "bring-in-zip" });
  const err = h("div", { class: "field-error", role: "alert" });
  const status = h("div", { class: "muted small", "aria-live": "polite" });
  let anyway = false, report = null;
  const lock = { on: false };   // 0.14.3: the dialog stays open while the merge runs, so its report is always seen
  file.addEventListener("change", () => {
    const f = file.files && file.files[0];
    anyway = false; err.textContent = "";
    status.textContent = f ? `${f.name} · ${fmt.bytes(f.size)}` : "";
  });
  return dialog({
    lock,
    title: "Bring in a colleague’s work",
    body: h("div", {},
      h("p", { class: "muted" }, `Choose the zip your colleague made with “Download as a zip” in their copy of “${project}”. What is new comes in. Where you both changed the same thing, their version comes in beside yours, marked “sync clash”. Nothing you decided is replaced.`),
      field("Zip file", file), status, err),
    actions: [{ text: "Cancel", value: null }, {
      text: "Bring in", value: true, primary: true, id: "dlg-confirm",
      async onClick(dlg) {
        err.textContent = "";
        const f = file.files && file.files[0];
        if (!f) { err.textContent = "Choose a zip file first."; file.focus(); return false; }
        const btn = dlg.querySelector("#dlg-confirm");
        btn.disabled = true; lock.on = true; status.textContent = `Bringing in ${f.name}… this can take a moment for a large project.`;
        try {
          const r = await api("POST", `/api/projects/${P(project)}/bring-in${anyway ? "?anyway=1" : ""}`, f);
          report = r.report;
        } catch (e) {
          lock.on = false; btn.disabled = false; status.textContent = "";
          err.textContent = e.message;
          if (e.status === 409 && e.data && e.data.not_this_project) { anyway = true; btn.textContent = "Bring it in anyway"; }
          return false;
        }
        lock.on = false;
        await App.refresh();
        return true;
      },
    }],
    onOpen() { file.focus(); },
  }).then((ok) => (ok && report ? reportDialog(report) : null));
}

// What a colleague's work changed, in a few sentences, with a link to each sync-clash copy.
function reportDialog(r) {
  const c = r.checks, d = r.documents, t = r.themes;
  const links = [
    ...c.clash.map((x) => h("li", {}, h("a", { href: `#/h/${encodeURIComponent(x.hyp_id)}` }, x.text), " (a result)")),
    ...d.clash.map((x) => h("li", {}, h("a", { href: `#/doc/${encodeURIComponent(x.doc_id)}` }, x.title), " (another reading of a document)")),
    ...t.clash.map((x) => h("li", {}, h("a", { href: `#/themes/${encodeURIComponent(x.run_id)}` }, "A set of themes"))),
    ...r.codebooks.clash.map((x) => h("li", {}, `The codebook “${x.of}” (kept as “${x.name}”)`)),
  ];
  return dialog({
    title: `${r.from.name || "Your colleague"}’s work is in`,
    body: h("div", { class: "bring-report" },
      h("ul", {}, (r.lines || []).map((line) => h("li", {}, line))),
      links.length ? h("div", { class: "br-clash" }, h("strong", {}, `${r.from.name ? `${r.from.name}’s` : "Their"} versions beside yours:`), h("ul", {}, links)) : null),
    actions: [{ text: "Close", value: null, primary: true }],
  });
}

function togetherCard() {
  const s = App.state.settings || {};
  const name = h("input", { class: "input", type: "text", value: s.your_name || "", placeholder: "e.g. Anna de Vries", maxlength: 60, autocomplete: "name", "aria-label": "Your name" });
  const save = h("button", { class: "btn btn-sm", type: "button", onClick: async () => {
    try { await api("PUT", "/api/settings", { your_name: name.value }); await App.refresh(); toast(name.value.trim() ? `Colleagues see your work as ${name.value.trim()}’s.` : "Your name is taken away.", "ok", { small: true, ttl: 3500 }); } catch (e) { showError(e); }
  } }, "Save");
  name.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); save.click(); } });
  const now = h("div", { class: "tg-now", hidden: true });
  const card = h("div", { class: "card card-plain together-card" },
    h("h2", { style: { fontSize: "1.05rem" } }, icon("users", { size: 16 }), ` ${FEATURES.together.title}`),
    h("p", { class: "muted small" }, FEATURES.together.what),
    h("div", { class: "tg-name" }, h("label", { class: "small", for: "tg-your-name" }, "Your name"), Object.assign(name, { id: "tg-your-name" }), save,
      h("span", { class: "muted small" }, "Colleagues see your judgements under this name.")),
    h("ol", { class: "small move-steps" },
      h("li", {}, "Choose “Download as a zip” on the project and send the file to your colleague (e-mail, a shared folder)."),
      h("li", {}, "The first time, they choose “Import a project (.zip)”. After that, “Bring in a colleague’s work” on the same project."),
      h("li", {}, "Do the same the other way round, as often as you like. A file brought in twice changes nothing.")),
    now);
  const project = App.project;
  // what this project has from colleagues; loaded again after a colleague's work is brought in
  card.reload = () => !project ? null : api("GET", `/api/projects/${P(project)}/together`).then((t) => {
      replace(now);
      now.hidden = true;
      const last = (t.history || [])[0];
      const open = (t.clashes || []).filter((x) => x.kind !== "codebook");
      const agree = t.agreement || [];
      if (!last && !open.length && !agree.length) return;
      const href = (x) => ({ check: `#/h/${encodeURIComponent(x.key)}`, document: `#/doc/${encodeURIComponent(x.key)}`, themes: `#/themes/${encodeURIComponent(x.key)}` })[x.kind];
      const what = { check: "a result", document: "a document", themes: "a set of themes" };
      append(now, [
        h("h3", {}, `In “${project}”`),
        last ? h("p", { class: "small" }, `Last brought in: ${last.from && last.from.name ? `${last.from.name}’s work` : "a colleague’s work"}, ${fmt.date(last.at)}. `, h("span", { class: "muted" }, (last.lines || [])[0] || "")) : null,
        open.length ? h("div", { class: "small" }, `Sync clashes (${open.length}): versions you both changed, kept side by side.`,
          h("ul", {}, open.slice(0, 5).map((x) => h("li", {}, h("a", { href: href(x) }, `${whose(x.name)[0].toUpperCase()}${whose(x.name).slice(1)} version of ${what[x.kind]}`), ` · ${fmt.dateShort(x.at)}`)))) : null,
        agree.length ? h("div", { class: "small" }, "How often you judged excerpts alike:",
          h("ul", {}, agree.map((a) => h("li", { title: "Cohen’s kappa corrects the agreement for what chance alone would give: 1 is perfect, 0 is chance." }, `You and ${a.name}: ${a.agreed} of ${a.both} ${a.both === 1 ? "excerpt" : "excerpts"} you both judged (${Math.round(a.rate * 100)}%)`, a.kappa !== null && a.kappa !== undefined ? `, Cohen’s kappa ${a.kappa.toFixed(2)}` : "")))) : null]);
      now.hidden = false;
    }).catch((e) => console.warn("Work together:", e.message));
  card.reload();
  return card;
}

// 0.10: every project and the settings in one zip, for another computer.
function moveCard() {
  const btn = h("button", { class: "btn btn-sm", type: "button", onClick: async () => {
    btn.disabled = true;
    toast("Packing every project… this can take a while for large projects.", "info", { small: true, ttl: 4000 });
    try { await download("/api/move.zip"); } catch (e) { showError(e); }
    btn.disabled = false;
  } }, icon("download", { size: 13 }), "Download everything (.zip)");
  return h("div", { class: "card card-plain move-card" },
    h("h2", { style: { fontSize: "1.05rem" } }, icon("monitor", { size: 16 }), " Move ENLENS to another computer"),
    h("p", { class: "muted small" }, "One file with every project (documents, results, your judgements and notes) and your settings. A saved Claude API key is left out: it stays on this computer. Projects used in place from another folder come along as copies."),
    h("ol", { class: "small move-steps" },
      h("li", {}, "Here: ", btn),
      h("li", {}, "On the new computer: install ENLENS, then on its first screen (or under Projects → Import) choose the file.")));
}

export function newProjectDialog() {
  const input = h("input", { class: "input", type: "text", placeholder: "e.g. Green hydrogen Morocco", autocomplete: "off", maxlength: 60 });
  const err = h("div", { class: "field-error", role: "alert" });
  return dialog({
    title: "New project",
    body: h("div", {}, h("p", { class: "muted" }, "A project is one set of documents and the hypotheses you check against them, for example one literature review."), field("Name", input), err),
    actions: [{ text: "Cancel", value: null }, {
      text: "Create", value: true, primary: true, id: "dlg-confirm",
      async onClick() {
        err.textContent = "";
        try {
          const typed = input.value.trim();
          const r = await api("POST", "/api/projects", { name: typed });
          await App.refresh();
          if (r.project.name !== typed) toast(`Saved as “${r.project.name}” (some characters can't be used in a project name). Now add your documents.`, "warn", { ttl: 9000 });
          else toast(`Project “${r.project.name}” created. Now add your documents.`, "ok");
          navigate("#/sources");
        } catch (e) { err.textContent = e.message; return false; }
        return true;
      },
    }],
    onOpen(dlg) {
      const btn = dlg.querySelector("#dlg-confirm");
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); btn.click(); } });
      input.focus();
    },
  });
}

export function linkProjectDialog() {
  const path = h("input", { class: "input input-mono", type: "text", placeholder: "/path/to/workspace (contains enlens.sqlite)", autocomplete: "off" });
  const name = h("input", { class: "input", type: "text", placeholder: "defaults to the folder's name", maxlength: 60 });
  const err = h("div", { class: "field-error", role: "alert" });
  return dialog({
    title: "Open an existing ENLENS project folder",
    body: h("div", {}, h("p", { class: "muted" }, "For technical users. This is not for a folder of documents (add those under Documents), but for a project folder that ENLENS itself made earlier, on the command line or in another copy of the app. It is used in place, not copied."), field("Folder path", path), field("Project name (optional)", name), err),
    actions: [{ text: "Cancel", value: null }, {
      text: "Link", value: true, primary: true, id: "dlg-confirm",
      async onClick() {
        err.textContent = "";
        try {
          const r = await api("POST", "/api/projects/link", { path: path.value.trim(), name: name.value.trim() || undefined });
          await App.refresh();
          toast(`Project “${r.project.name}” added.`, "ok");
          navigate("#/hypotheses");
        } catch (e) { err.textContent = e.message; return false; }
        return true;
      },
    }],
    onOpen(dlg) {
      const btn = dlg.querySelector("#dlg-confirm");
      for (const el of [path, name]) el.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); btn.click(); } });
      path.focus();
    },
  });
}

export async function renderProjects(view) {
  view.appendChild(pageHead("Projects", { sub: "Each project keeps its own documents, results and notes.", actions: [
    h("button", { class: "btn btn-primary", type: "button", onClick: () => newProjectDialog() }, icon("plus", { size: 14 }), "New project"),
    h("button", { class: "btn", type: "button", onClick: () => importProjectDialog() }, icon("upload", { size: 14 }), "Import a project (.zip)"),
    h("button", { class: "btn", type: "button", onClick: () => linkProjectDialog() }, icon("link", { size: 14 }), "Open an existing ENLENS project folder"),
    quickLookButton()] }));
  view.appendChild(h("p", { class: "muted small", style: { margin: "-10px 0 14px" } }, "“Download as a zip” gives a project to a colleague or moves it to another computer: one file with the documents, the results, your judgements and notes. “Import a project” brings such a zip in as a new project; “Bring in a colleague’s work” merges it into the copy you have."));
  const list = h("div", { class: "stack" });
  view.appendChild(list);
  const together = (App.state.projects || []).some((p) => !p.temporary) ? togetherCard() : null;
  if (together) view.appendChild(together);
  if ((App.state.projects || []).some((p) => !p.temporary)) view.appendChild(moveCard());
  const draw = () => {
    replace(list);
    const projects = App.state.projects || [];
    if (!projects.length) { list.appendChild(h("div", { class: "empty" }, icon("folder", { size: 28 }), h("h3", {}, "No projects yet"), h("p", {}, "Create one to get started."))); return; }
    for (const p of projects) {
      const current = p.name === App.project;
      list.appendChild(h("div", { class: "card card-plain", style: current ? { borderColor: "var(--accent)" } : null },
        h("div", { class: "row", style: { justifyContent: "space-between" } },
          h("div", { class: "grow" },
            h("div", { class: "it" }, icon(p.linked ? "link" : "folder", { size: 16 }), h("h2", { style: { fontSize: "1.05rem" } }, p.name), current ? h("span", { class: "chip chip-code" }, "current") : null, !p.ok ? h("span", { class: "warn-chip" }, icon("alert-triangle", { size: 12 }), "cannot be opened") : null),
            h("div", { class: "muted small", style: { marginTop: "4px" } }, `${p.documents} ${p.documents === 1 ? "document" : "documents"} · ${p.hypotheses} ${p.hypotheses === 1 ? "result" : "results"}${p.linked ? " · folder used in place" : ""}${p.temporary ? ` · a quick look, moved to the trash on ${fmt.dateShort(new Date(p.temporary.expires_at * 1000).toISOString())} unless kept` : ""}`),
            h("div", { class: "muted small mono", style: { marginTop: "2px", wordBreak: "break-all" } }, p.path)),
          h("div", { class: "btn-row" },
            !current ? h("button", { class: "btn btn-sm", type: "button", onClick: async () => { try { await api("PUT", "/api/settings", { project: p.name }); await App.refresh(); toast(`Project: ${p.name}`, "ok", { ttl: 2000 }); draw(); } catch (e) { showError(e); } } }, "Switch to") : null,
            p.ok ? projectZipLink(p.name, { text: "Download as a zip" }) : null,
            p.ok && !p.temporary ? h("button", { class: "btn btn-sm", type: "button", title: "Merge the zip of a colleague’s copy of this project into yours", onClick: () => bringInDialog(p.name).then(() => { draw(); if (together) together.reload(); }) }, icon("users", { size: 13 }), "Bring in a colleague’s work") : null,
            p.ok && p.documents ? h("button", { class: "btn btn-sm", type: "button", title: "One SQLite file in the FlexiConc layout of the Cross-Doc SDG Explorer: the documents, their sentences with codes, reference chains, themes and (if set up) embeddings",
              onClick: (e) => { const b = e.currentTarget; b.disabled = true; toast("Preparing the FlexiConc file…", "info", { small: true, ttl: 3000 }); download(`/api/projects/${P(p.name)}/flexiconc.sqlite`).catch(showError).finally(() => { b.disabled = false; }); } },
              icon("download", { size: 13 }), "For FlexiConc / Cross-Doc") : null,
            h("button", { class: "btn btn-sm btn-outline-danger", type: "button", onClick: async () => {
              const ok = await confirmDialog({ title: `Remove project “${p.name}”?`, message: p.linked ? "The folder is no longer used by the app and is left untouched on disk." : "The project (documents, results, notes) is moved to a trash folder inside the app's data folder.", confirmText: "Remove", typeToConfirm: p.name });
              if (!ok) return;
              try { const r = await api("DELETE", `/api/projects/${P(p.name)}`, { confirm: p.name }); await App.refresh(); toast(r.result === "unlinked" ? "Project removed: its folder is left as it was." : "Project removed: it is in the trash folder inside the data folder.", "ok"); if (!App.state.projects.length) navigate("#/setup"); else draw(); } catch (e) { showError(e); }
            } }, icon("trash", { size: 13 }), "Remove")))));
    }
  };
  draw();
  return App.onChange(draw);
}
