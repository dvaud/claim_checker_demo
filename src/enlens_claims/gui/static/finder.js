// 0.17.0: the feature finder ("Find": Ctrl+K or ⌘K, the sidebar's button, and a box on the Overview). Type what you
// want to do; it suggests the place, view or action you probably meant, misspellings included. Not an AI feature:
// finder-index.js matches the words with plain loops.
import { h, icon, input as fieldInput, navigate } from "./lib.js";
import { FEATURES, PLACES, SECTIONS } from "./features.js";
import { buildIndex, findFeatures } from "./finder-index.js";

let uid = 0;

const searchHref = (q) => `#/search?q=${encodeURIComponent(q)}`;

// The rows for a query: "Go to" (places and views), then "Do" (actions), then, for a query, a Search row.
function rowsFor(query, index) {
  const found = findFeatures(query, index, { limit: 8 });
  const groups = [
    { label: "Go to", items: found.filter((e) => e.kind !== "action") },
    { label: "Do", items: found.filter((e) => e.kind === "action") },
  ].filter((g) => g.items.length);
  const q = query.trim();
  if (q) groups.push({ label: "", items: [{ title: `Search the documents for “${q}”`, where: "in Search", href: searchHref(q), icon: "text-search", kind: "search" }] });
  return groups;
}

// The input, the listbox and the keys, shared by the dialog and the Overview box. `onPick(href)` follows a row.
function finderParts({ placeholder, onPick, onEscape, label }) {
  const n = ++uid;
  const listId = `finder-list-${n}`;
  let index = buildIndex({ FEATURES, PLACES, SECTIONS });   // built when it opens, so an add-on's features are in
  let rows = [];
  let active = -1;

  const input = fieldInput({
    class: "finder-input", autocomplete: "off", spellcheck: "false", autocapitalize: "off",
    placeholder, "aria-label": label, role: "combobox", "aria-expanded": "true", "aria-controls": listId, "aria-autocomplete": "list",
  });
  const list = h("div", { class: "finder-list", id: listId, role: "listbox", "aria-label": "Suggestions" });
  const live = h("span", { class: "visually-hidden", role: "status", "aria-live": "polite" });

  function setActive(i, scroll = true) {
    if (!rows.length) { active = -1; input.removeAttribute("aria-activedescendant"); return; }
    active = (i + rows.length) % rows.length;
    rows.forEach((r, k) => { r.el.setAttribute("aria-selected", k === active ? "true" : "false"); });
    input.setAttribute("aria-activedescendant", rows[active].el.id);
    if (scroll && rows[active].el.scrollIntoView) rows[active].el.scrollIntoView({ block: "nearest" });
  }

  function render() {
    const groups = rowsFor(input.value, index);
    rows = [];
    list.replaceChildren();
    for (const g of groups) {
      const box = h("div", { class: "finder-group", role: "group", "aria-label": g.label || "Search" });
      if (g.label) box.appendChild(h("div", { class: "finder-group-label", "aria-hidden": "true" }, g.label));
      for (const item of g.items) {
        const el = h("div", { class: "finder-row" + (item.kind === "search" ? " finder-row-search" : ""), role: "option", id: `finder-${n}-${rows.length}`, "aria-selected": "false" },
          h("span", { class: "finder-icon", "aria-hidden": "true" }, icon(item.icon || "arrow-right", { size: 16 })),
          h("span", { class: "finder-title" }, item.title),
          item.where ? h("span", { class: "finder-where" }, item.where) : null);
        const k = rows.length;
        el.addEventListener("mousedown", (e) => e.preventDefault());   // the input keeps its focus
        el.addEventListener("mousemove", () => { if (active !== k) setActive(k, false); });
        el.addEventListener("click", () => onPick(item.href));
        rows.push({ el, item });
        box.appendChild(el);
      }
      list.appendChild(box);
    }
    live.textContent = rows.length ? `${rows.length} suggestions` : "";
    setActive(rows.length ? 0 : -1, false);
  }

  input.addEventListener("input", render);
  input.addEventListener("keydown", (e) => {
    if (e.isComposing) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive(active + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); }
    else if (e.key === "Enter") { e.preventDefault(); if (rows[active]) onPick(rows[active].item.href); }
    else if (e.key === "Escape" && onEscape) { e.preventDefault(); onEscape(); }
  });
  return { input, list, live, render, refresh() { index = buildIndex({ FEATURES, PLACES, SECTIONS }); render(); } };
}

export function openFinder(initial = "") {
  const existing = document.querySelector("dialog.finder-dialog");
  if (existing) { const i = existing.querySelector(".finder-input"); if (i) { i.focus(); i.select(); } return; }
  const returnTo = document.activeElement;
  const dlg = h("dialog", { class: "dialog finder-dialog", "aria-modal": "true", "aria-label": "Find a feature" });
  const close = () => {
    if (dlg.open) dlg.close();
    dlg.remove();
    if (returnTo && returnTo.focus && document.contains(returnTo)) returnTo.focus();
  };
  const parts = finderParts({
    placeholder: "What do you want to do? e.g. find themes, add documents", label: "What do you want to do?",
    onPick(href) { close(); navigate(href); }, onEscape: close,
  });
  dlg.append(parts.input, parts.list, parts.live,
    h("p", { class: "finder-hint" }, h("kbd", {}, "↑"), h("kbd", {}, "↓"), " to move, ", h("kbd", {}, "Enter"), " to open, ", h("kbd", {}, "Esc"), " to close"));
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
  dlg.addEventListener("click", (e) => { if (e.target === dlg) close(); });
  (document.getElementById("dialogs") || document.body).appendChild(dlg);
  dlg.showModal();
  parts.input.value = initial;
  parts.render();
  parts.input.focus();
  if (initial) parts.input.select();
}

export function finderBox({ placeholder = "What do you want to do? e.g. find themes, add documents" } = {}) {
  const parts = finderParts({
    placeholder, label: "What do you want to do?",
    onPick(href) { navigate(href); parts.input.value = ""; parts.render(); },
    onEscape() { parts.input.value = ""; parts.render(); },
  });
  const box = h("div", { class: "finder-box" }, h("span", { class: "finder-box-icon", "aria-hidden": "true" }, icon("search", { size: 16 })), parts.input, parts.list, parts.live);
  parts.render();
  // 0.17.0: on the Overview the suggestions show only while the box is in use, so the page below stays in view
  const shown = () => { parts.list.hidden = !(box.contains(document.activeElement) || parts.input.value.trim()); };
  box.addEventListener("focusin", shown);
  box.addEventListener("focusout", () => setTimeout(shown, 120));   // after a click on a suggestion has landed
  parts.input.addEventListener("input", shown);
  parts.list.hidden = true;
  return box;
}
