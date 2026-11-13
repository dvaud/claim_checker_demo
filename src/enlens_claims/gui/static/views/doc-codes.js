// A document's page, the Codes panel: which codes of a codebook the document addresses, with the labels, a way to add one
// and the keyword search. doc-page.js builds the panel and hands it the page's `ctx`.
import { api, h, icon, replace, clear, toast, showError, fmt, P, emptyState, certainty, textPositions, cpLength,
  session, plural, shortTitle, cap, runningJob, button, link, notice, card, tag, input, select, fold, inset } from "../lib.js";
import { jobCard } from "./progress.js";
import { aiLabelCard, startKeywordPass, keywordLabel, SOURCE_WORDS, RELEVANCE_WORDS, DIRECTION_WORDS } from "./profile.js";
import { stillRunning, norm } from "./doc-shared.js";

// ---- Codes (F2)
export function codesPanel(ctx) {
  const { query, docBase, keepUrl, project, watchers, docId, base, jumpTo, paint } = ctx;
  const el = h("section", { class: "dv-panel", "aria-labelledby": "dv-codes-h" });
  const head = h("div");
  const jobBox = h("div", { hidden: true });
  const aiBox = h("div");
  const addBox = h("div");
  const listBox = h("div", { "aria-live": "polite", "aria-busy": "false" });
  el.append(h("h2", { id: "dv-codes-h", class: "dv-panel-title" }, "Codes"), head, jobBox, addBox, listBox, aiBox);
  let prof = null, fws = null, codeItems = null, ai = null, aiFw = null, missingFw = null;
  const open = new Set(query.code ? [query.code] : []);
  const all = new Set();      // codes whose every passage is shown
  let marks = [];             // the passages of the open codes, marked in the text
  const passages = new Map(); // passage_id -> Promise of {start, text}

  async function load() {
    listBox.setAttribute("aria-busy", "true");
    try {
      try { prof = await api("GET", `${docBase}/profile?framework=${encodeURIComponent(ctx.framework)}`); }
      catch (e) {   // M2: a codebook kept in another project (or gone): the SDG targets, with a one-line note
        if (ctx.framework === "sdg" || !/^Unknown framework/.test(e.message || "")) throw e;
        missingFw = ctx.framework; ctx.framework = "sdg"; open.clear();
        prof = await api("GET", `${docBase}/profile?framework=sdg`);
      }
    }
    catch (e) { listBox.setAttribute("aria-busy", "false"); replace(listBox, notice({ kind: "error", live: false }, h("p", {}, e.message))); return; }
    listBox.setAttribute("aria-busy", "false");
    // a goal from the profile grid (?code=7): open its targets
    for (const c of [...open]) if (!prof.codes.some((x) => x.code === c)) { open.delete(c); for (const x of prof.codes) if (x.group === c) open.add(x.code); }
    draw();
    refreshMarks();
  }

  function draw() {
    const fwName = prof.framework_title || ctx.framework;
    const label = prof.code_label || "code";
    const sel = select({ sm: true, id: "dv-fw" }, (fws || [{ name: ctx.framework, title: fwName }]).map((f) => h("option", { value: f.name, selected: f.name === ctx.framework }, f.title || f.name)));
    sel.addEventListener("change", async () => { ctx.framework = sel.value; missingFw = null; open.clear(); keepUrl(); await load(); const again = document.getElementById("dv-fw"); if (again) again.focus(); });
    replace(head, h("div", { class: "dv-fw" }, h("label", { class: "field-label", for: "dv-fw" }, "Codebook"), sel));
    clear(listBox);
    if (missingFw) listBox.appendChild(notice({ kind: "attention", class: "dv-status-notice" },
      h("p", {}, `The codebook “${missingFw}” is kept in another project, so the SDG targets are shown. Codebooks › move it to all projects makes it available everywhere.`)));
    const p1 = prof.pass1 || {};
    if (!p1.done) {
      clear(aiBox); ai = null;
      if (jobBox.hidden) listBox.appendChild(emptyState("tag", "No codes found yet", `The app first finds the ${label}s of “${fwName}” in every passage of the project by their keywords. It takes seconds and runs on this computer.`,
        button({ kind: "main", sm: true, onClick: (e) => startKeywordPass(project, ctx.framework, jobBox, watchers, (job) => { if (job.state === "done") jobBox.hidden = true; load(); }, e.currentTarget) }, icon("tag", { size: 13 }), "Find the codes by keywords")));
      return;
    }
    if (p1.stale && jobBox.hidden) listBox.appendChild(notice({ kind: "attention", class: "dv-status-notice" },
      h("div", {}, h("p", {}, "Documents were added or removed since the codes were found, so this profile may be out of date."),
        button({ sm: true, class: "dv-find-again-btn", onClick: (e) => startKeywordPass(project, ctx.framework, jobBox, watchers, (job) => { if (job.state === "done") jobBox.hidden = true; load(); }, e.currentTarget) }, icon("refresh", { size: 13 }), "Find them again"))));
    const codes = prof.codes || [];
    const labelled = new Set(codes.flatMap((c) => c.items.map((it) => it.passage_id))).size;
    const provisional = codes.some((c) => c.items.some((it) => it.provisional));
    listBox.appendChild(h("p", { class: "dv-sum" }, codes.length
      ? [h("strong", {}, `${plural(codes.length, label)}`), ` in ${plural(labelled, "passage")} of ${fmt.num(prof.passages)} (${Math.round((labelled / Math.max(1, prof.passages)) * 100)}%).`]
      : `No ${label} counts in this document yet.`));
    listBox.appendChild(h("p", { class: "muted small dv-codes-help" },
      prof.read_by_model ? `The AI has read ${plural(prof.read_by_model, "passage")} of this document. ` : "The AI has not read this document yet. ",
      provisional ? [tag({ kind: "attention" }, "provisional"), " codes were found by keywords", p1.meaning_model ? " or meaning" : "", " and wait for the AI or you."] : ""));
    if (codes.length) {
      listBox.appendChild(h("ol", { class: "dv-codes" }, codes.map(codeNode)));
      listBox.appendChild(h("p", { class: "muted small" }, "Ranked by the number of passages. The strip shows where in the document each code occurs. Open a code to see its passages and why each was labelled."));
    }
    if (aiFw !== ctx.framework) {
      aiFw = ctx.framework;
      const key = `label-job:${project}:${docId}`;
      ai = aiLabelCard({ project, framework: ctx.framework, docIds: [docId], watchers, compact: true, onStart: (id) => session(key, { id }), onEnd: () => load() });
      replace(aiBox, ai.el);
      stillRunning(key).then((j) => { if (j && ai) ai.follow(j.id); });
    }
  }

  function pagesText(pages, n) {
    const out = [];
    for (let i = 0; i < pages.length; i++) {
      let j = i;
      while (j + 1 < pages.length && pages[j + 1] === pages[j] + 1) j++;
      out.push(j > i ? `${pages[i]}–${pages[j]}` : String(pages[i]));
      i = j;
    }
    return `${pages.length === 1 ? "page" : "pages"} ${out.join(", ")}${n ? ` of ${n}` : ""}`;
  }

  function codeNode(c) {
    const isOpen = open.has(c.code);
    const n = prof.n_pages;
    const share = c.share < 0.01 ? "under 1%" : `${Math.round(c.share * 100)}%`;
    const allProv = c.items.every((it) => it.provisional);
    const ticks = n && c.pages.length ? c.pages.map((pg) => ((pg - 0.5) / n) * 100) : c.positions;
    const whereText = n && c.pages.length ? pagesText(c.pages, n) : `at ${c.positions.map((x) => `${x}%`).join(", ")} of the text`;
    const strip = h("div", { class: "dv-strip", role: "img", "aria-label": `Where: ${whereText}`, title: `Where: ${whereText}. Click to go there.`,
      onClick: (e) => {
        const r = e.currentTarget.getBoundingClientRect();
        const x = ((e.clientX - r.left) / Math.max(1, r.width)) * 100;
        const pos = (it) => (n && it.page ? ((it.page - 0.5) / n) * 100 : it.position_pct || 0);
        const best = [...c.items].sort((a, b) => Math.abs(pos(a) - x) - Math.abs(pos(b) - x))[0];
        if (best) jumpItem(best);
      } }, ticks.map((t) => h("span", { class: "dv-tick", style: { left: `${Math.max(0, Math.min(100, t))}%` } })));
    const headBtn = h("button", { class: "dv-code-head", type: "button", "aria-expanded": isOpen ? "true" : "false", dataset: { code: c.code },
      onClick: () => { if (open.has(c.code)) open.delete(c.code); else open.add(c.code); draw(); refreshMarks(); const b = listBox.querySelector(`.dv-code-head[data-code="${CSS.escape(c.code)}"]`); if (b) b.focus(); } },
      h("span", { class: "dv-code-id" }, c.code),
      h("span", { class: "dv-code-main" }, h("span", { class: "dv-code-desc" }, c.description || c.code),
        h("span", { class: "dv-code-n" }, `${plural(c.passages, "passage")} · ${share} of the document`, c.main ? ` · main topic in ${c.main}` : "", allProv ? " · " : "", allProv ? tag({ kind: "attention" }, "provisional") : null)),
      icon(isOpen ? "chevron-up" : "chevron-down", { size: 14 }));
    const li = h("li", { class: "dv-code" + (isOpen ? " dv-open" : "") }, headBtn, strip);
    if (isOpen) {
      const items = all.has(c.code) ? c.items : c.items.slice(0, 12);
      li.appendChild(h("ul", { class: "dv-items" }, items.map((it) => itemNode(c, it))));
      if (c.items.length > items.length) li.appendChild(button({ kind: "quiet", sm: true, onClick: () => { all.add(c.code); draw(); } }, icon("chevron-down", { size: 13 }), `Show all ${c.items.length} passages`));
    }
    return li;
  }

  function itemNode(c, it) {
    const chips = [tag({ icon: it.source === "person" ? "user" : null }, SOURCE_WORDS[it.source] || it.source)];
    if (it.provisional) chips.push(tag({ kind: "attention", title: "Found without the AI. It counts until the AI has read this passage (or you decide)." }, "provisional"));
    if (it.source === "model" || it.source === "person" || it.decision === "change") {
      if (it.relevance) chips.push(tag({}, RELEVANCE_WORDS[it.relevance] || it.relevance));
      if (prof.directional && it.direction && it.direction !== "not_stated") chips.push(tag({}, DIRECTION_WORDS[it.direction] || it.direction));
    }
    if (it.source === "model" && it.confidence !== null && it.confidence !== undefined) { const ce = certainty(it.confidence); chips.push(h("span", { class: `cert cert-${ce.word}`, title: ce.long }, `AI certainty: ${ce.word} (${Math.round(it.confidence * 100)}%)`)); }
    if (it.decision === "accept") chips.push(tag({ icon: "user" }, "you agree"));
    else if (it.decision === "change") chips.push(tag({ icon: "user" }, "changed by you"));
    const why = [];
    if (it.quote) why.push(h("p", { class: "dv-quote serif" }, h("mark", { class: "dv-code-mark" }, it.quote)));
    if (it.source === "model" && it.reason) why.push(h("p", { class: "dv-why" }, h("span", { class: "muted" }, "The AI's reason: "), it.reason));
    else if (it.source === "person") why.push(h("p", { class: "dv-why" }, h("span", { class: "muted" }, "Your note: "), it.reason || "added by you"));
    else {
      const bits = [];
      if ((it.matched || []).length) bits.push(h("span", {}, h("span", { class: "muted" }, "Matched words: "), it.matched.map((w, i) => [i ? ", " : "", h("b", {}, w)])));
      else if (it.reason && !it.similarity) bits.push(h("span", {}, it.reason));
      if (it.similarity !== null && it.similarity !== undefined) bits.push(h("span", {}, h("span", { class: "muted" }, bits.length ? " · close in meaning" : "Close in meaning to the code's text"), ` (similarity ${Number(it.similarity).toFixed(2)})`));
      why.push(h("p", { class: "dv-why found-words" }, it.source === "both" ? h("strong", {}, "Keywords and meaning agree. ") : null, bits));
    }
    if (it.note && it.source !== "person") why.push(h("p", { class: "dv-note small" }, h("span", { class: "muted" }, "Your note: "), h("span", { class: "serif" }, it.note)));
    const where = link({ kind: "jump", class: "dv-loc", title: "Show it in the text", onClick: () => jumpItem(it) }, icon("eye", { size: 12 }), cap(it.location || (it.page ? `page ${it.page}` : "show in the text")));
    return inset({ as: "li", tentative: !!it.provisional, class: "dv-item" + (it.decision ? " ev-yours" : ""), dataset: { lid: it.label_id } },
      h("div", { class: "dv-item-top" }, where, h("span", { class: "chips" }, chips)), why, decideRow(c, it));
  }

  // agree / change relevance or direction / reject, every decision with Undo
  function decideRow(c, it) {
    const put = async (body, msg) => {
      try {
        await api("PUT", `${base}/labels/${P(it.label_id)}`, body);
        toast(msg, "ok", { small: true, ttl: 8000, group: "label", button: { text: "Undo", onClick: async () => {
          try { await api("PUT", `${base}/labels/${P(it.label_id)}`, it.decision ? { decision: it.decision === "change" ? "change" : it.decision, relevance: it.decision === "change" ? it.relevance : undefined, direction: it.decision === "change" ? it.direction : undefined } : { decision: "clear" }); toast("Undone.", "ok", { small: true, ttl: 2500, group: "label" }); await load(); } catch (e) { showError(e); }
        } } });
        await load();
        const again = listBox.querySelector(`[data-lid="${CSS.escape(it.label_id)}"] button`) || listBox.querySelector(`.dv-code-head[data-code="${CSS.escape(c.code)}"]`);
        if (again) again.focus({ preventScroll: true });
      } catch (e) { showError(e); }
    };
    const row = h("div", { class: "judge-row dv-decide" });
    if (it.source === "person") {
      row.appendChild(button({ kind: "quiet", sm: true, onClick: () => put({ decision: "reject" }, "Your label was removed.") }, icon("trash", { size: 13 }), "Remove my label"));
      return row;
    }
    const agreed = it.decision === "accept";
    row.appendChild(button({ kind: agreed ? "main" : "standard", sm: true, "aria-pressed": agreed ? "true" : "false",
      onClick: () => (agreed ? put({ decision: "clear" }, "Your decision was cleared.") : put({ decision: "accept" }, it.provisional ? "Saved: you agree. The label now counts as yours." : "Saved: you agree with this label.")) },
      icon("check", { size: 13 }), agreed ? "You agree" : "Agree"));
    row.appendChild(button({ kind: "quiet", sm: true, onClick: () => put({ decision: "reject" }, `Rejected: ${c.code} no longer counts for this passage.`) }, icon("x", { size: 13 }), "Reject"));
    // change: relevance and direction (where the codebook has one)
    const name = `dv-rel-${it.label_id}`;
    const radios = (nm, choices, current) => h("div", { class: "judge-opts", role: "radiogroup" }, choices.map(([v, t]) => {
      const radio = h("input", { type: "radio", name: nm, value: v });
      radio.checked = current === v;
      return h("label", { class: "judge-opt" }, radio, h("span", {}, t));
    }));
    const rel = radios(name, [["main", "main topic"], ["mentioned", "mentioned"]], it.relevance || "main");
    rel.setAttribute("aria-label", "How much the passage is about this code");
    const dir = prof.directional ? radios(`${name}-d`, [["helps", "helps"], ["hinders", "hinders"], ["mixed", "mixed"], ["not_stated", "not stated"]], it.direction || "not_stated") : null;
    if (dir) dir.setAttribute("aria-label", "Direction");
    const note = input({ sm: true, placeholder: "Optional note", value: it.decision === "change" ? (it.note || "") : "", "aria-label": "Your note on this label" });
    const save = button({ sm: true, onClick: () => {
      const r = rel.querySelector("input:checked"), dd = dir && dir.querySelector("input:checked");
      put({ decision: "change", relevance: r ? r.value : undefined, direction: dd ? dd.value : undefined, note: note.value.trim() || undefined }, "Saved: your change to this label.");
    } }, "Save the change");
    const instead = button({ kind: "quiet", sm: true, title: "Reject this code here and choose the right one",
      onClick: async () => { await put({ decision: "reject" }, "This code is rejected here: choose the right one."); addForm({ passage_id: it.passage_id, where: it.location }); } },
      icon("plus", { size: 13 }), "Wrong code? Choose another instead");
    row.appendChild(fold({ sm: true, class: "judge-diff" }, it.decision === "change" ? "Your change · edit" : "Change how it applies",
      h("div", { class: "judge-body" }, h("div", { class: "small muted" }, "How much is it about this code?"), rel,
        dir ? [h("div", { class: "small muted dv-decide-hint" }, "Does the passage say it helps or hinders the aim?"), dir] : null,
        h("div", { class: "row dv-decide-row" }, note, save),
        h("div", { class: "dv-decide-instead" }, instead))));
    row.appendChild(button({ kind: "quiet", sm: true, onClick: () => addForm({ passage_id: it.passage_id, where: it.location }) }, icon("plus", { size: 13 }), "Another code here"));
    return row;
  }

  async function passageOf(pid) {
    if (!passages.has(pid)) passages.set(pid, api("GET", `${base}/passages/${P(pid)}?around=0`).then((r) => (r.passages || []).find((x) => x.passage_id === pid) || null).catch(() => null));
    return passages.get(pid);
  }
  function wordMarks(text, startAt, words) {
    const out = [];
    const pos = textPositions(text);   // the matches are indices of the text; the marks, the app’s offsets
    for (const w of words || []) {
      const rx = new RegExp(`(?<![\\p{L}\\p{N}])${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![\\p{L}\\p{N}])`, "giu");
      let mm;
      while ((mm = rx.exec(text))) out.push({ start: startAt + pos.point(mm.index), end: startAt + pos.point(mm.index + mm[0].length), cls: "dv-code-mark", mark: true });
    }
    return out;
  }
  async function jumpItem(it) {
    if (Number.isInteger(it.start) && Number.isInteger(it.end)) return jumpTo({ start: it.start, end: it.end });
    const p = await passageOf(it.passage_id);
    if (!p || !Number.isInteger(p.start)) { toast("This passage could not be placed in the text.", "warn"); return; }
    jumpTo({ start: p.start, end: p.start + cpLength(p.text || "") }, { soft: true, extra: wordMarks(p.text || "", p.start, it.matched) });
  }

  // the passages of the open codes, marked in the text: quotes where the AI or you gave one, else the matched words
  let markSeq = 0;
  async function refreshMarks() {
    const my = ++markSeq;
    const out = [];
    for (const c of (prof && prof.codes) || []) {
      if (!open.has(c.code)) continue;
      const want = new Map();
      for (const it of c.items) {
        if (Number.isInteger(it.start) && Number.isInteger(it.end)) out.push({ start: it.start, end: it.end, cls: "dv-code-mark", mark: true });
        else if ((it.matched || []).length) want.set(it.passage_id, new Set(it.matched.map((w) => w.toLowerCase())));
      }
      if (!want.size) continue;
      const words = [...new Set([...want.values()].flatMap((s) => [...s]))].slice(0, 60);
      try {
        const r = await api("GET", `${base}/search?${new URLSearchParams({ q: words.join(" "), docs: docId, code: `${ctx.framework}:${c.code}`, limit: "1000", width: "20" })}`);
        for (const l of r.lines || []) { const w = want.get(l.passage_id); if (w && w.has(norm(l.node))) out.push({ start: l.start, end: l.end, cls: "dv-code-mark", mark: true }); }
      } catch (_) { /* the marks are a help, not essential */ }
    }
    if (my !== markSeq) return;
    marks = out;
    if (ctx.tab === "codes") paint();
  }

  // a label of one's own: for a passage (from a labelled passage) or for selected text
  let codeList = null;
  async function codesOf() {
    if (!codeList) codeList = api("GET", `${base}/frameworks/${P(ctx.framework)}`).then((r) => ((r.framework && r.framework.items) || [])).catch(() => []);
    return codeList;
  }
  async function addForm({ passage_id, quote, where }) {
    const label = (prof && prof.code_label) || "code";
    const items = await codesOf();
    const dl = h("datalist", { id: "dv-code-list" }, items.map((x) => h("option", { value: x.code }, `${x.code} · ${shortTitle(x.description, 90)}`)));
    const code = input({ sm: true, list: "dv-code-list", autocomplete: "off", id: "dv-add-code", placeholder: items[0] ? `e.g. ${items[0].code}` : "" });
    const desc = h("p", { class: "muted small dv-add-desc" });
    code.addEventListener("input", () => { const x = items.find((y) => y.code === code.value.trim()); desc.textContent = x ? x.description : ""; });
    const rel = select({ sm: true, "aria-label": "How much it is about the code" }, h("option", { value: "main" }, "main topic"), h("option", { value: "mentioned" }, "mentioned"));
    const dir = prof && prof.directional ? select({ sm: true, "aria-label": "Direction" }, ["not_stated", "helps", "hinders", "mixed"].map((v) => h("option", { value: v }, DIRECTION_WORDS[v]))) : null;
    const note = input({ sm: true, placeholder: "Why (optional)", "aria-label": "Why this code (optional)" });
    const msg = h("p", { class: "field-error", role: "alert", hidden: true });
    const save = button({ kind: "main", sm: true }, icon("plus", { size: 13 }), "Add my label");
    save.addEventListener("click", async () => {
      msg.hidden = true;
      if (!code.value.trim()) { code.focus(); return; }
      save.disabled = true;
      try {
        await api("POST", `${base}/labels`, { framework: ctx.framework, passage_id, code: code.value.trim(), quote: quote || undefined, relevance: rel.value, direction: dir ? dir.value : "not_stated", note: note.value.trim() || undefined });
        clear(addBox);
        toast("Your label was added. It always counts.", "ok", { small: true });
        await load();
      } catch (e) { msg.textContent = e.message; msg.hidden = false; save.disabled = false; }
    });
    replace(addBox, card({ as: "div", class: "dv-add" },
      h("h3", {}, `Add ${/^[aeiouAEIOU]|^SDG/.test(label) ? "an" : "a"} ${label} of your own`),
      h("p", { class: "muted small dv-add-intro" }, quote ? ["For the selected text: ", h("q", { class: "serif" }, shortTitle(quote, 160))] : `For the passage ${where ? `in ${where}` : ""}.`),
      h("label", { class: "field-label", for: "dv-add-code" }, cap(label)), code, dl, desc,
      h("div", { class: "row dv-add-fields" }, rel, dir, note),
      msg,
      h("div", { class: "btn-row dv-add-actions" }, save, button({ kind: "quiet", sm: true, onClick: () => clear(addBox) }, "Cancel"))));
    addBox.scrollIntoView({ block: "nearest" });
    code.focus();
  }
  // selected text -> its passage (found as a phrase in this document) -> the form
  async function labelSelection(s) {
    if (!prof) await load();
    let r;
    try { r = await api("GET", `${base}/search?${new URLSearchParams({ q: `"${s.text}"`, docs: docId, mode: "phrase", limit: "200", width: "20" })}`); }
    catch (e) { showError(e); return; }
    const line = (r.lines || []).filter((l) => Math.abs(l.start - s.start) <= 30).sort((a, b) => Math.abs(a.start - s.start) - Math.abs(b.start - s.start))[0];
    if (!line) { toast("The selection could not be matched to one passage: select words within one paragraph, not across a heading or page break.", "warn"); return; }
    addForm({ passage_id: line.passage_id, quote: s.text, where: line.location });
  }

  api("GET", `${base}/frameworks`).then((r) => { fws = r.frameworks || []; if (prof) draw(); }).catch(() => {});
  load();
  return {
    el, labelSelection,
    live: load,   // 0.16: what counts changed (Restore, Leave out): the codes read again, in place
    decos: () => marks,
    show() { runningJob(project, ["keywords"]).then((j) => { if (j) watchers.push(jobCard(jobBox, j.id, "Finding the codes by keywords and meaning", keywordLabel, () => { jobBox.hidden = true; load(); }, { small: true, plain: true })); }); },
    framework: () => ctx.framework,
    frameworkTitle: () => (prof && prof.framework_title) || ((fws || []).find((f) => f.name === ctx.framework) || {}).title || ctx.framework,
  };
}
