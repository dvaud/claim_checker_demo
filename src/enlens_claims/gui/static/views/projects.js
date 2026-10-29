// Projects: create, link an existing workspace folder, switch, remove.
import { quickLookButton } from "./quicklook.js";
import { App, api, h, icon, replace, toast, showError, field, navigate, dialog, confirmDialog, pageHead, P, fmt, download } from "../lib.js";
import { projectZipLink } from "./result.js";

// Import a project from a zip made with "Download as a zip" (on this or another computer).
export function importProjectDialog() {
  const file = h("input", { type: "file", accept: ".zip,application/zip", class: "input", id: "import-zip" });
  const name = h("input", { class: "input", type: "text", placeholder: "the name the project had", autocomplete: "off", maxlength: 60 });
  const err = h("div", { class: "field-error", role: "alert" });
  const status = h("div", { class: "muted small", "aria-live": "polite" });
  let proposed = "";
  file.addEventListener("change", () => {
    const f = file.files && file.files[0];
    err.textContent = "";
    if (!f) return;
    // "ENLENS project - Demo - 2026-10-28.zip" -> "Demo"
    const m = /^ENLENS project - (.+?) - \d{4}-\d{2}-\d{2}\.zip$/i.exec(f.name);
    proposed = (m ? m[1] : f.name.replace(/\.zip$/i, "")).trim();
    if (!name.value.trim() || name.value === proposed) name.value = proposed;
    status.textContent = `${f.name} · ${fmt.bytes(f.size)}`;
  });
  return dialog({
    title: "Import a project (.zip)",
    body: h("div", {},
      h("p", { class: "muted" }, "A zip made with “Download as a zip”, from this or another computer: the documents, the results and the notes come with it, as a new project."),
      field("Zip file", file), status,
      field("Project name", name, { help: "Proposed from the file name. If a project of that name exists already, you are asked for another." }), err),
    actions: [{ text: "Cancel", value: null }, {
      text: "Import", value: true, primary: true, id: "dlg-confirm",
      async onClick(dlg) {
        err.textContent = "";
        const f = file.files && file.files[0];
        if (!f) { err.textContent = "Choose a zip file first."; file.focus(); return false; }
        const typed = name.value.trim();
        const btn = dlg.querySelector("#dlg-confirm");
        btn.disabled = true; status.textContent = `Importing ${f.name}… this can take a moment for a large project.`;
        try {
          const r = await api("POST", `/api/projects/import${typed ? `?name=${encodeURIComponent(typed)}` : ""}`, f);
          await App.refresh();
          toast(`Project “${r.project.name}” imported: ${r.project.documents} ${r.project.documents === 1 ? "document" : "documents"}, ${r.project.hypotheses} ${r.project.hypotheses === 1 ? "result" : "results"}. It is now the current project.`, "ok", { ttl: 7000 });
          navigate("#/history");
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
          navigate("#/check");
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
  view.appendChild(h("p", { class: "muted small", style: { margin: "-10px 0 14px" } }, "“Download as a zip” gives a project to a colleague or moves it to another computer: one file with the documents, the results, your judgements and notes. “Import a project” brings such a zip in as a new project."));
  const list = h("div", { class: "stack" });
  view.appendChild(list);
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
