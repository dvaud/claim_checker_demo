// A document's page, the panels that look words up: Key terms, References and Search in this document. doc-page.js builds
// them and hands each the page's `ctx`.
import { withAI } from "../features.js";
import { App, api, h, icon, readsLine, replace, clear, toast, showError, fmt, emptyState, searchHref, session,
  plural, shortTitle, button, link, notice, input, select, fold } from "../lib.js";
import { jobCard } from "./progress.js";
import { stillRunning, norm } from "./doc-shared.js";

// ---- Key terms (F6)
export function termsPanel(ctx) {
  const { docBase, paint, base, watchers, list, jumpTo } = ctx;
  const el = h("section", { class: "dv-panel", "aria-labelledby": "dv-terms-h" });
  const jobBox = h("div", { hidden: true });
  const body = h("div", { "aria-busy": "true" }, h("p", { class: "muted small" }, "Loading…"));
  el.append(h("h2", { id: "dv-terms-h", class: "dv-panel-title" }, "Key terms"), jobBox, body);
  let data = null, n = 15, pinned = null;
  const cursor = {};
  async function load() {
    try { data = await api("GET", `${docBase}/terms?n=${n}`); } catch (e) { replace(body, notice({ kind: "error" }, h("p", {}, e.message))); return; }
    body.setAttribute("aria-busy", "false");
    draw();
    if (ctx.tab === "terms") paint();
  }
  function build(btn) {
    if (btn) btn.disabled = true;
    api("POST", `${base}/terms/build`, {}).then((r) => watchers.push(jobCard(jobBox, r.job.id, "Building the glossary", (p) => (p.total ? `Reading the documents: ${fmt.num(p.done || 0)} of ${fmt.num(p.total)}` : "Reading the documents…"), (job) => { if (job.state === "done") jobBox.hidden = true; load(); }, { small: true, plain: true })))
      .catch((e) => { showError(e); if (btn) btn.disabled = false; });
  }
  const hover = (tid, on) => { for (const x of list.querySelectorAll(`[data-terms~="${CSS.escape(tid)}"]`)) x.classList.toggle("kt-on", on); };
  function draw() {
    clear(body);
    const st = data.status || {};
    if (!st.built) {
      body.appendChild(emptyState("network", "No glossary yet", "Key terms come from the glossary of the project's terms. It is made on this computer in seconds to a minute; nothing is sent anywhere.",
        jobBox.hidden ? button({ kind: "main", sm: true, onClick: (e) => build(e.currentTarget) }, icon("network", { size: 13 }), "Make the glossary") : null));
      return;
    }
    if (st.stale && jobBox.hidden) body.appendChild(notice({ kind: "attention", class: "dv-status-notice" },
      h("div", {}, h("p", {}, "Documents were added or removed since the glossary was made, so the key terms may be out of date."),
        button({ sm: true, class: "dv-update-btn", onClick: (e) => build(e.currentTarget) }, icon("refresh", { size: 13 }), "Update the glossary"))));
    const terms = data.terms || [];
    if (!terms.length) { body.appendChild(emptyState("network", "No key terms", "No term of the glossary occurs in this document.")); return; }
    body.appendChild(h("p", { class: "muted small dv-terms-help" }, "The terms that set this document apart from the others in the project. Point at a term to underline it in the text; click it to keep it marked and go from one place to the next."));
    const max = Math.max(...terms.map((t) => t.score || 0), 1);
    const spans = data.spans || [];
    body.appendChild(h("ol", { class: "dv-terms" }, terms.map((t) => {
      const places = spans.filter((s) => s.term_id === t.term_id);
      const isPin = pinned === t.term_id;
      const pinBtn = h("button", { class: "dv-term-btn serif", type: "button", "aria-pressed": isPin ? "true" : "false", title: isPin ? "Click again for the next place" : "Mark it in the text and go to its first place",
        onClick: () => {
          if (pinned !== t.term_id) { pinned = t.term_id; cursor[t.term_id] = -1; }
          const i = cursor[t.term_id] = (cursor[t.term_id] + 1) % Math.max(1, places.length);
          draw();
          if (places[i]) jumpTo(places[i]);
          const again = body.querySelector(`[data-tid="${CSS.escape(t.term_id)}"] .dv-term-btn`); if (again) again.focus({ preventScroll: true });
        } }, t.label);
      const li = h("li", { class: "dv-term" + (isPin ? " dv-pinned" : ""), dataset: { tid: t.term_id },
        onMouseenter: () => hover(t.term_id, true), onMouseleave: () => hover(t.term_id, false), onFocusin: () => hover(t.term_id, true), onFocusout: () => hover(t.term_id, false) },
        h("div", { class: "dv-term-main" }, pinBtn,
          h("span", { class: "muted small" }, isPin && places.length ? `place ${cursor[t.term_id] + 1} of ${places.length}` : plural(t.mentions, "mention"))),
        h("span", { class: "dv-term-bar", "aria-hidden": "true" }, h("span", { style: { width: `${Math.max(4, Math.round(((t.score || 0) / max) * 100))}%` } })),
        h("span", { class: "dv-term-links" },
          link({ href: searchHref(t.label, { mode: "phrase" }), title: `Search the whole project for “${t.label}”` }, icon("text-search", { size: 13 }), h("span", { class: "visually-hidden" }, `Search the project for ${t.label}`)),
          link({ href: `#/concepts?name=${encodeURIComponent(t.label)}`, title: `The concept “${t.label}” across the documents` }, icon("network", { size: 13 }), h("span", { class: "visually-hidden" }, `Open the concept ${t.label}`))));
      return li;
    })));
    const btns = [];
    if (pinned) btns.push(button({ kind: "quiet", sm: true, onClick: () => { pinned = null; draw(); paint(); } }, icon("x", { size: 13 }), "Stop marking"));
    if (terms.length >= n && n < 50) btns.push(button({ kind: "quiet", sm: true, onClick: () => { n = 40; load(); } }, icon("chevron-down", { size: 13 }), "Show more key terms"));
    if (btns.length) body.appendChild(h("div", { class: "btn-row dv-terms-actions" }, btns));
    body.appendChild(fold({}, "Technical details", h("p", { class: "muted small" }, `Ranked by TF-IDF against the ${fmt.num(st.terms || 0)} terms of the project's glossary (made ${fmt.date(st.built_at)}); a term inside a longer key term with as many mentions is left out.`)));
  }
  load();
  return {
    el,
    live: load,   // 0.16: what counts changed (Restore, Leave out): the key terms read again, in place
    decos: () => (data ? (data.spans || []).map((s) => ({ start: s.start, end: s.end, cls: pinned === s.term_id ? "kt kt-pin" : "kt", term: s.term_id, mark: pinned === s.term_id })) : []),
  };
}

// ---- References (F5)
export function refsPanel(ctx) {
  const { docBase, paint, project, docId, watchers, jumpTo } = ctx;
  const el = h("section", { class: "dv-panel", "aria-labelledby": "dv-refs-h" });
  const jobBox = h("div", { hidden: true });
  const selBox = h("div", { "aria-live": "polite" });
  const body = h("div", {}, h("p", { class: "muted small" }, "Loading…"));
  el.append(h("h2", { id: "dv-refs-h", class: "dv-panel-title" }, "References"), selBox, jobBox, body);
  let data = null, selected = null, after = null, showAll = false, running = false;
  async function load() {
    try { data = await api("GET", `${docBase}/references`); } catch (e) { replace(body, notice({ kind: "error" }, h("p", {}, e.message))); return; }
    if (selected !== null && !(data.chains || []).some((c) => c.chain_id === selected)) selected = null;
    draw();
    if (ctx.tab === "refs") paint();
  }
  function start(name, btn) {
    if (btn) btn.disabled = true;
    api("POST", `${docBase}/references`, name ? { name } : {}).then((r) => { session(`refs-job:${project}:${docId}`, { id: r.job.id, name: name || null }); follow(r.job.id, name); }).catch((e) => { showError(e); if (btn) btn.disabled = false; });
  }
  function follow(jobId, name) {
    running = true;
    draw();
    watchers.push(jobCard(jobBox, jobId, name ? `Following the references to “${name}”` : "Following the references", (p) => (p.total ? `The AI has read ${fmt.num(Math.max(0, (p.done || 0) - 1))} of ${fmt.num(p.total)} stretches` : "The AI is getting ready…"), (job) => {
      running = false;
      if (job.state === "done") { jobBox.hidden = true; const r = job.result || {}; toast(name && !r.windows ? `“${name}” does not occur in this document, written this way. Try another spelling, or select the name in the text.`
        : !r.read && r.already_read ? `The AI had already read ${plural(r.already_read, "stretch", "stretches")} for this. ${plural(r.chains || 0, "name")} with references.`
        : `The AI read ${plural(r.read || 0, "stretch", "stretches")}${r.failed ? `; ${r.failed} could not be read` : ""}. ${r.chains ? `${plural(r.chains, "name")} with references.` : "It found no references to follow."}`, r.failed || (name && !r.windows) ? "warn" : "ok", { ttl: 9000 }); }
      load();
    }, { small: true, plain: true, stoppedText: "Stopped. What the AI read so far is kept; start again to go on where it stopped." }));
  }
  function draw() {
    clear(body);
    const st = data.status || {};
    const chains = data.chains || [];
    const where = App.privacy();
    body.appendChild(h("p", { class: "small dv-refs-lead" }, "The AI reads the document three passages at a time and links “it”, “they” or “the study” to the name they stand for. Every mention it reports is checked against the text. It is a reading aid: the AI misses some references."));
    const left = Math.max(0, (st.windows_total || 0) - (st.windows_read || 0));
    body.appendChild(h("p", { class: "muted small dv-refs-note" },
      st.windows_read ? `The AI has read ${fmt.num(st.windows_read)} of ${plural(st.windows_total || 0, "stretch", "stretches")} of this document` : `Not followed yet: ${plural(st.windows_total || 0, "stretch", "stretches")} of three passages to read`,
      st.windows_failed ? `; ${fmt.num(st.windows_failed)} could not be read` : "", "."));
    if (!running) {
      const name = input({ sm: true, placeholder: "a name used in the document", "aria-label": "Only for one name" });
      const nameBtn = button({ sm: true, onClick: (e) => { const v = name.value.trim(); if (!v) { name.focus(); return; } start(v, e.currentTarget); } }, "Follow this name");
      name.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); nameBtn.click(); } });
      body.appendChild(h("div", { class: "btn-row" },
        left ? withAI(button({ kind: chains.length ? "standard" : "main", sm: true, onClick: (e) => start(null, e.currentTarget) }, icon("link", { size: 13 }),
          st.windows_read ? `Go on where it stopped (${plural(left, "stretch", "stretches")} left)` : "Follow the references in this document")) : h("span", { class: "it small" }, icon("check", { size: 13 }), " The AI has read the whole document.")));
      body.appendChild(fold({}, "Only for one name", h("p", { class: "muted small dv-names-fast" }, "Faster: the AI reads only the passages where the name occurs."), h("div", { class: "row dv-name-row" }, name, withAI(nameBtn))));
      // where the passages go, once for the panel, at its foot (docs/DESIGN.md 4.4)
      if (where.where === "cloud" || where.where === "local") body.appendChild(readsLine("the passages it needs", { class: "dv-refs-reads" }));
    }
    if (!chains.length) {
      if (st.windows_read) body.appendChild(h("p", { class: "muted small" }, left ? "No references found yet in the stretches read." : "The AI found no references to follow in this document."));
      return;
    }
    body.appendChild(h("p", { class: "muted small dv-names-hint" }, "Select a name in the text to see every later mention of the same thing, or pick a name here."));
    const shown = showAll ? chains : chains.slice(0, 25);
    body.appendChild(h("ul", { class: "dv-chains" }, shown.map((ch) => {
      const on = selected === ch.chain_id;
      const li = h("li", { class: "dv-chain" + (on ? " dv-open" : "") },
        h("button", { class: "dv-chain-btn", type: "button", "aria-pressed": on ? "true" : "false", dataset: { chain: String(ch.chain_id) },
          onClick: () => { selected = on ? null : ch.chain_id; after = null; draw(); paint(); if (!on && ch.mentions[0]) jumpTo(ch.mentions[0]); const b = body.querySelector(`[data-chain="${ch.chain_id}"]`); if (b) b.focus({ preventScroll: true }); } },
          h("span", { class: "serif dv-chain-name" }, ch.name),
          h("span", { class: "muted small" }, `${plural(ch.size, "mention")}${ch.unnamed ? ` · ${ch.unnamed} without the name` : ""}`)));
      if (on) {
        const ms = after !== null ? ch.mentions.filter((x) => x.start >= after) : ch.mentions;
        li.appendChild(h("p", { class: "muted small dv-mentions-head" }, after !== null ? `${plural(ms.length, "later mention")} (of ${ch.size}):` : "Its mentions, in order:"));
        li.appendChild(h("ol", { class: "dv-mentions" }, ms.slice(0, 80).map((x) => h("li", {},
          link({ kind: "jump", onClick: () => jumpTo(x) }, x.is_named ? h("strong", {}, x.text) : x.text),
          h("span", { class: "muted small" }, ` · ${x.location || ""}`)))));
      }
      return li;
    })));
    if (chains.length > shown.length) body.appendChild(button({ kind: "quiet", sm: true, onClick: () => { showAll = true; draw(); } }, icon("chevron-down", { size: 13 }), `Show all ${chains.length} names`));
  }
  // a selection in the text: its chain (by offsets, or by the same words), else offer to follow that name
  async function lookup(s) {
    if (!data) await load();
    let ch = null;
    try { ch = (await api("GET", `${docBase}/references?start=${s.start}&end=${s.end}`)).chain; } catch (_) { /* try by text */ }
    if (!ch) ch = (data.chains || []).find((c) => norm(c.name) === norm(s.text) || c.mentions.some((x) => norm(x.text) === norm(s.text))) || null;
    clear(selBox);
    if (ch) {
      selected = ch.chain_id; after = s.end; showAll = showAll || !(data.chains || []).slice(0, 25).some((c) => c.chain_id === ch.chain_id);
      draw(); paint();
      const later = ch.mentions.filter((x) => x.start >= s.end);
      if (later[0]) jumpTo(later[0]);
      replace(selBox, h("p", { class: "dv-selnote" }, icon("link", { size: 13 }), ` “${shortTitle(s.text, 60)}” is part of `, h("strong", {}, ch.name), later.length ? `: ${plural(later.length, "later mention")}, marked in the text.` : ": no later mention."));
      return;
    }
    const btn = button({ sm: true, disabled: running, onClick: (e) => { clear(selBox); start(s.text, e.currentTarget); } }, icon("link", { size: 13 }), `Follow the references to “${shortTitle(s.text, 40)}”`);
    replace(selBox, notice({ kind: "info", class: "dv-selnote" }, h("div", {}, h("p", {}, `No reference found yet for “${shortTitle(s.text, 60)}”.`), h("div", { class: "btn-row dv-lookup-actions" }, withAI(btn)))));
  }
  load();
  return {
    el, lookup,
    show() { stillRunning(`refs-job:${project}:${docId}`).then((j) => { if (j && !running) follow(j.id, j.name); }); },
    decos: () => {
      const ch = data && selected !== null ? (data.chains || []).find((c) => c.chain_id === selected) : null;
      return ch ? ch.mentions.map((x) => ({ start: x.start, end: x.end, cls: x.is_named ? "dv-ref dv-ref-named" : "dv-ref", mark: true })) : [];
    },
  };
}

// ---- Search in this document (F1)
export function searchPanel(ctx) {
  const { query, keepUrl, paint, base, docId, jumpTo, docSlice } = ctx;
  const el = h("section", { class: "dv-panel", "aria-labelledby": "dv-search-h" });
  const qIn = input({ type: "search", id: "dv-q", placeholder: "Words to find in this document", value: query.find || "", autocomplete: "off" });
  const mode = select({ sm: true, "aria-label": "How to match the words" }, [["any", "any of the words"], ["all", "all the words, in one passage"], ["phrase", "the exact phrase"]].map(([v, t]) => h("option", { value: v }, t)));
  const form = h("form", { class: "dv-search", role: "search", onSubmit: (e) => { e.preventDefault(); run(); } },
    h("label", { class: "visually-hidden", for: "dv-q" }, "Search in this document"),
    h("div", { class: "row dv-search-row" }, qIn, button({ kind: "main", sm: true, type: "submit" }, icon("search", { size: 13 }), "Search")), mode);
  const results = h("div", { "aria-live": "polite" });
  el.append(h("h2", { id: "dv-search-h", class: "dv-panel-title" }, "Search in this document"), form,
    h("p", { class: "muted small dv-search-hint" }, "Or click a word in the text to add it; Shift-click a later word to make a phrase."), results);
  let res = null, cur = -1, lastPick = null, seq = 0;
  mode.addEventListener("change", () => { if (qIn.value.trim()) run(); });
  async function run(more) {
    const q = qIn.value.trim();
    keepUrl();
    if (!q) { res = null; cur = -1; clear(results); if (ctx.tab === "search") paint(); return; }
    const my = ++seq;
    const off = more && res ? res.lines.length : 0;
    let r;
    try { r = await api("GET", `${base}/search?${new URLSearchParams({ q, docs: docId, mode: mode.value, limit: "200", offset: String(off), width: "45" })}`); }
    catch (e) { if (my === seq) replace(results, h("p", { class: "field-error" }, e.message)); return; }
    if (my !== seq) return;
    if (more && res) { res.lines = res.lines.concat(r.lines || []); } else { res = r; cur = -1; }
    draw();
    paint();
  }
  // Previous, Next or a hit picked: the current row and the counter change in place (the table of up to hundreds of
  // hits is not drawn again), and the hit’s mark in the text through jumpTo’s paint
  let rowsNow = [], counter = null;
  function go(i) {
    if (!res || !res.lines[i]) return;
    if (rowsNow[cur]) rowsNow[cur].classList.remove("dv-cur");
    cur = i;
    if (rowsNow[cur]) rowsNow[cur].classList.add("dv-cur");
    if (counter) counter.textContent = `${cur + 1} of ${fmt.num(res.lines.length)}`;
    jumpTo(res.lines[i]);
  }
  function draw() {
    clear(results);
    rowsNow = []; counter = null;
    if (!res) return;
    const lines = res.lines || [];
    if (!res.total) { results.appendChild(h("p", { class: "muted" }, `No hit for “${res.query}” in this document.`, " ", h("a", { href: searchHref(res.query) }, "Search the whole project"))); return; }
    results.appendChild(h("div", { class: "row dv-hitnav" },
      h("strong", {}, `${plural(res.total, "hit")} in ${plural(res.passages, "passage")}`),
      h("span", { class: "grow" }),
      button({ sm: true, disabled: !lines.length, "aria-label": "Previous hit", onClick: () => go(cur <= 0 ? lines.length - 1 : cur - 1) }, icon("chevron-left", { size: 13 })),
      counter = h("span", { class: "small muted" }, cur >= 0 ? `${cur + 1} of ${fmt.num(lines.length)}` : ""),
      button({ sm: true, disabled: !lines.length, "aria-label": "Next hit", onClick: () => go(cur >= lines.length - 1 ? 0 : cur + 1) }, icon("chevron-right", { size: 13 }))));
    results.appendChild(h("div", { class: "kwic-wrap dv-kwic" }, h("table", { class: "kwic" },
      h("caption", { class: "visually-hidden" }, `Hits for ${res.query} in this document`),
      h("tbody", {}, rowsNow = lines.map((l, i) => h("tr", { class: i === cur ? "dv-cur" : "" },
        h("td", { class: "kw-left" }, h("span", {}, l.left)),
        h("td", { class: "kw-node" }, h("button", { class: "dv-node", type: "button", title: `Go to ${l.location || "it"}`, onClick: () => go(i) }, h("mark", {}, l.node))),
        h("td", { class: "kw-right" }, l.right),
        h("td", { class: "kw-where", title: l.location || null }, h("span", {}, l.location || ""))))))));
    if (lines.length < res.total) results.appendChild(button({ kind: "quiet", sm: true, class: "dv-more-hits-btn", onClick: () => run(true) }, icon("chevron-down", { size: 13 }), `Show more hits (${fmt.num(res.total - lines.length)} more)`));
    results.appendChild(h("p", { class: "small dv-search-note" }, h("a", { href: searchHref(res.query, { mode: mode.value !== "any" ? mode.value : null }) }, icon("text-search", { size: 12 }), " Search the whole project for it")));
  }
  function addWord(w, shift) {
    let v = qIn.value;
    if (shift && lastPick) {
      const s = Math.min(lastPick.start, w.start), e = Math.max(lastPick.end, w.end);
      const phrase = docSlice(s, e);
      if (phrase !== null && e - s <= 200) {
        const add = `"${phrase.replace(/\s+/g, " ").replace(/"/g, "").trim()}"`;
        v = v.trimEnd().endsWith(lastPick.inBox) ? v.trimEnd().slice(0, v.trimEnd().length - lastPick.inBox.length) + add : `${v.trim()} ${add}`;
        lastPick = { start: s, end: e, inBox: add };
        qIn.value = v.trim();
        run();
        return;
      }
    }
    if (!v.toLowerCase().split(/\s+/).includes(w.text.toLowerCase())) v = `${v.trim()} ${w.text}`;
    lastPick = { start: w.start, end: w.end, inBox: w.text };
    qIn.value = v.trim();
    run();
  }
  if (qIn.value.trim()) run();
  return {
    el, addWord,
    query: () => qIn.value.trim(),
    searchFor(text) { qIn.value = text; lastPick = null; run(); },
    show(fromUser) { if (fromUser) setTimeout(() => qIn.focus({ preventScroll: true }), 0); },
    decos: () => (res ? res.lines.map((l, i) => ({ start: l.start, end: l.end, cls: i === cur ? "dv-hit dv-hit-cur" : "dv-hit", mark: true })) : []),
  };
}
