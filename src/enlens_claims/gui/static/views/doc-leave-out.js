// A document's page, Restore and Leave out in place (0.16): the buttons beside a block and the change they make to the reading,
// which greys and folds away what leaves the text and brings back what returns, the rest of the page staying where it was.
// doc-page.js calls leaveOut() with the page's `ctx` and uses the buttons it makes.
import { api, h, icon, replace, toast, showError, fmt, download, plural, button } from "../lib.js";

export function leaveOut(ctx) {
  const { d, docBase, list, selBar, rows, loaded, panels, shownFigure, labelParts, place, paint } = ctx;
  function blockActions(b) {
    if (b.kind === "figure" && (d.reader || 1) >= 5) return null;   // 0.18.1: a reader-5 figure is never read: nothing to leave out or restore
    const wrap = h("div", { class: "dv-act" });
    const where = b.label || `${b.kind_text || "text"}${b.page ? `, page ${b.page}` : ""}`;
    const btn = b.included === false
      ? button({ kind: "quiet", sm: true, "aria-label": `Restore: ${where}`, title: "Count this in searches, codes, themes and checks again", onClick: (e) => setIncluded(b, true, e.currentTarget) }, icon("refresh", { size: 12 }), "Restore")
      : button({ kind: "quiet", sm: true, "aria-label": `Leave out: ${where}`, title: b.kind === "heading" || b.kind === "title" ? "Leave this heading and the text under it out of searches, codes, themes and checks" : "Leave this out of searches, codes, themes and checks (a heading above it goes with it)", onClick: (e) => setIncluded(b, false, e.currentTarget) }, icon("minus", { size: 12 }), "Leave out");
    wrap.appendChild(btn);
    // 0.15.1: the same for every block that looks like this one (running heads, page numbers, a repeated label)
    if (b.alike > 0) wrap.appendChild(button({ kind: "quiet", sm: true, "aria-label": `${b.included === false ? "Restore" : "Leave out"} all ${b.alike + 1} blocks like this: ${where}`,
      title: b.included === false ? `Restore this and the ${plural(b.alike, "other block")} that look the same (their numbers aside)` : `Leave out this and the ${plural(b.alike, "other block")} that look the same (their numbers aside), such as a running head on every page`,
      onClick: (e) => setIncluded(b, b.included === false, e.currentTarget, true) }, icon("copy", { size: 12 }), `All like this (${fmt.num(b.alike + 1)})`));
    // 0.15.1: where the document's own text starts and ends (a book's title pages before, its notes and index after)
    if (b.bound) wrap.appendChild(button({ kind: "quiet", sm: true, "aria-label": `Undo: the text ${b.bound === "start" ? "starts" : "ends"} here`, title: "What was left out by this mark counts again, unless it was left out for another reason", onClick: (e) => setBound(b.bound, null, e.currentTarget) }, icon("x", { size: 12 }), b.bound === "start" ? "Undo start" : "Undo end"));
    else if (b.included !== false && b.share != null) {
      if (b.share <= 0.34) wrap.appendChild(button({ kind: "quiet", sm: true, "aria-label": `The text starts here: ${where}`, title: "Leave out everything before this (title pages, publishing details, contents). Anything you restore there still counts.", onClick: (e) => setBound("start", b.n, e.currentTarget) }, icon("chevron-down", { size: 12 }), "Text starts here"));
      if (b.share >= 0.66) wrap.appendChild(button({ kind: "quiet", sm: true, "aria-label": `The text ends here: ${where}`, title: "Leave out everything after this (notes, bibliography, index, about the author). Anything you restore there still counts.", onClick: (e) => setBound("end", b.n, e.currentTarget) }, icon("chevron-up", { size: 12 }), "Text ends here"));
    }
    if (b.table) wrap.appendChild(button({ kind: "quiet", sm: true, "aria-label": `Download table ${b.table.n} for Excel`, title: "The table's rows and cells, for Excel", onClick: () => download(`${docBase}/tables/${b.table.n}.xlsx`).catch(showError) }, icon("download", { size: 12 }), "Excel"));
    return wrap;
  }
  // 0.16: Restore, Leave out and where the text starts or ends change the reading where it is. Before, the whole
  // document was drawn again: the page flashed and it was hard to tell what had happened. Now what leaves the text
  // greys and folds away into the line "Left out of the text", what comes back joins the text again, and the rest of
  // the page stays where it was.
  let turn = Promise.resolve();   // one change at a time, in the order clicked: a click during another waits for it
  const inTurn = (job) => { turn = turn.catch(() => {}).then(job); return turn; };
  function setIncluded(b, included, btn, alike = false) {
    btn.disabled = true;
    return inTurn(() => changeIncluded(b, included, btn, alike));
  }
  async function changeIncluded(b, included, btn, alike) {
    const hadFocus = list.contains(document.activeElement);
    const r0 = rows.get(b.n);
    const greyNow = !included && r0 && r0.row.parentElement === list && b.kind !== "table" && !shownFigure(b);
    if (greyNow) r0.row.classList.add("dv-leaving");  // at once: the answer from the app follows
    let r;
    try { r = await api("PUT", `${docBase}/blocks/${b.n}`, alike ? { included, alike: true } : { included }); }
    catch (e) { btn.disabled = false; if (greyNow) r0.row.classList.remove("dv-leaving"); showError(e); return; }
    const folded = await showChange(r, b, hadFocus);
    // where it went, when it folded away out of sight
    const away = (them) => (!included && folded ? ` ${them ? "They are" : "It is"} folded under “Left out of the text”, where Restore brings ${them ? "them" : "it"} back.` : "");
    if (alike) {
      toast(`${included ? "Restored" : "Left out"}: ${plural(r.alike || 1, "block")} like this${(r.together || 0) > (r.alike || 0) ? `, with ${plural(r.together - r.alike, "block")} read together with them` : ""}. Searches, codes, themes and checks ${included ? "read them again" : "will not read them"}.${away(true)}`, "ok");
      return;
    }
    // what went with it (its passage), and blocks elsewhere with the same words (the choice is kept by the words)
    const group = new Set(r.group || (r.blocks || []).map((x) => x.n));
    const others = (r.blocks || []).filter((x) => x.n !== b.n && group.has(x.n));
    const same = (r.blocks || []).filter((x) => !group.has(x.n) && (x.included !== false) === included).length;
    const elsewhere = same ? ` So ${same === 1 ? "is" : "are"} ${plural(same, "block")} elsewhere with the same words.` : "";
    const heads = others.filter((x) => x.kind === "heading" || x.kind === "title").map((x) => `“${x.text.length > 60 ? x.text.slice(0, 57) + "…" : x.text}”`);
    const rest = others.length - heads.length;
    const withWhat = [heads.length ? `${heads.length > 1 ? "its headings" : "its heading"} ${heads.join(" and ")}` : null,
      rest ? `${plural(rest, "paragraph")} next to it (they are read as one passage)` : null].filter(Boolean).join(" and ");
    toast(included ? `Restored${withWhat ? `, together with ${withWhat}` : ""}. Searches, codes, themes and checks read ${others.length ? "them" : "it"} again.${elsewhere}`
      : `Left out${withWhat ? `, together with ${withWhat}` : ""}. Searches, codes, themes and checks will not read ${others.length ? "them" : "it"}.${away(others.length > 0)}${elsewhere}`, "ok");
  }
  // 0.15.1: where the text starts or ends (block null: no longer)
  function setBound(side, n, btn) {
    btn.disabled = true;
    return inTurn(() => changeBound(side, n, btn));
  }
  async function changeBound(side, n, btn) {
    const hadFocus = list.contains(document.activeElement);
    const at = rows.get(Number(btn.closest(".passage-row").id.slice(6)));   // the block whose button was pressed
    let r;
    try { r = await api("PUT", `${docBase}/bounds`, { side, block: n }); }
    catch (e) { btn.disabled = false; showError(e); return; }
    await showChange(r, at ? at.b : null, hadFocus);
    const what = side === "start" ? "before it" : "after it";
    toast(n == null ? `Undone: ${r.restored ? `${plural(r.restored, "block")} ${what.replace("it", "that mark")} count${r.restored === 1 ? "s" : ""} again` : "nothing else changed"}.`
      : `The text ${side === "start" ? "starts" : "ends"} here: ${r.left_out ? `${plural(r.left_out, "block")} ${what} left out, folded under “Left out of the text”` : "nothing more to leave out"}. Searches, codes, themes and checks read only the text.`, "ok");
  }
  const calm = () => !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const pause = (ms) => new Promise((ok) => setTimeout(ok, calm() ? 0 : ms));
  // whether a row is shown (not in a closed fold), and where it is seen: the row itself or the line of its fold
  const isShown = (row) => { const f = row.closest("details.dv-fold"); return !f || f.open; };
  const shownBox = (row) => (!row.isConnected ? null : isShown(row) ? row : row.closest("details.dv-fold").querySelector(":scope > summary"));
  const onScreen = (el) => { const q = el && el.getBoundingClientRect(); return !!q && q.height > 0 && q.bottom > 0 && q.top < window.innerHeight; };
  // the height of a fold's line "Left out of the text" with its margins: what a row that folds away shrinks to
  function foldLineHeight() {
    const probe = h("details", { class: "dv-fold", style: { visibility: "hidden" } }, h("summary", {}, icon("chevron-right", { size: 13 }), h("span", {}, "Left out of the text")));
    list.insertBefore(probe, selBar);
    const cs = getComputedStyle(probe);
    const px = probe.getBoundingClientRect().height + (parseFloat(cs.marginTop) || 0) + (parseFloat(cs.marginBottom) || 0);
    probe.remove();
    return px;
  }
  // Show what the app changed (`res.blocks`: the blocks as they are now, `res.doc`: the reading's figures) in place.
  // `clicked`: the block whose button was pressed. Returns whether a block that was on the screen folded away.
  async function showChange(res, clicked, hadFocus) {
    const now = new Map((res.blocks || []).map((x) => [x.n, x]));
    const folds = (b) => b.included === false && b.kind !== "table" && !shownFigure(b);   // a left-out table (and a figure shown) stays in the text
    // which fold each left-out block will be in (named by its first block), laid out as place() will lay them out,
    // and which of those will be open: shown, or holding a block whose fold is open now
    const key = new Map();
    let k = null, page;
    for (const b of loaded) {
      if (b.page != null && b.page !== page) { page = b.page; k = null; }
      if (folds(now.get(b.n) || b)) { if (k == null) k = b.n; key.set(b.n, k); } else k = null;
    }
    const openNow = () => {
      const ns = new Set();
      for (const f of list.querySelectorAll("details.dv-fold[open]")) for (const x of f.querySelectorAll(":scope > .passage-row")) ns.add(Number(x.id.slice(6)));
      return ns;
    };
    const openNs = openNow();
    const openKeys = new Set([...key].filter(([n]) => openNs.has(n)).map(([, f]) => f));
    const foldedBefore = new Set();   // folds that hold a block folded already (their line is there now)
    for (const [n, f] of key) if (folds(rows.get(n).b)) foldedBefore.add(f);
    const going = [], coming = [];
    for (const [n, x] of now) {
      const r = rows.get(n);
      if (!r) continue;   // not drawn yet: it comes as it now is with the rest of the document
      if (!folds(r.b) && folds(x)) going.push(r);
      else if (folds(r.b) && !folds(x)) coming.push(r);
    }
    // 1. what leaves the text and is on the screen greys
    const seen = going.filter((r) => onScreen(r.row));
    for (const r of seen) r.row.classList.add("dv-leaving");
    if (seen.length) await pause(200);
    // 2. and folds away, into the line "Left out of the text" that takes its place (unless that fold is shown open):
    // a fold's first block shrinks to the line, the others to nothing; a block joining a fold already there, to nothing
    const folding = seen.filter((r) => !ctx.showLeftOut && !openKeys.has(key.get(r.b.n)));
    if (folding.length) {
      const line = foldLineHeight();
      for (const r of folding) r.row.style.height = `${r.row.getBoundingClientRect().height}px`;
      void list.offsetHeight;   // the heights above are where the shrinking starts
      for (const r of folding) {
        const f = key.get(r.b.n);
        r.row.classList.add("dv-folding");
        r.row.style.height = `${f === r.b.n && !foldedBefore.has(f) ? line : 0}px`;
      }
      await pause(280);
    }
    // 3. the rows as they are now, laid out again; the row just above the first change on the screen (or, when that
    // row is not on the screen, the first unchanged row that is) stays where it is, so a change above the screen
    // moves nothing
    const changed = (n) => now.has(n);
    const rowOf = (b) => rows.get(b.n).row;
    let anchor = null;
    const firstSeen = loaded.findIndex((b) => changed(b.n) && onScreen(shownBox(rowOf(b))));
    for (let i = firstSeen - 1; i >= 0 && !anchor; i--) if (!changed(loaded[i].n) && isShown(rowOf(loaded[i]))) anchor = rowOf(loaded[i]);
    if (anchor && anchor.getBoundingClientRect().bottom < 0) anchor = null;   // far above: changes in between would move the screen
    if (!anchor) { const b = loaded.find((x) => !changed(x.n) && isShown(rowOf(x)) && onScreen(rowOf(x))); if (b) anchor = rowOf(b); }
    const top0 = anchor ? anchor.getBoundingClientRect().top : 0;
    for (const [n, x] of now) {
      const r = rows.get(n);
      if (!r) continue;
      Object.assign(r.b, x);
      r.row.classList.toggle("dv-out", r.b.included === false);
      r.row.classList.toggle("dv-changed", !!r.b.changed);
      replace(r.label, labelParts(r.b));
    }
    const openThen = openNow();   // as they are now: a fold opened or closed during the animation stays so
    for (const el of [...list.children]) if (el !== selBar) el.remove();
    ctx.resetFold();
    for (const b of loaded) place(b, rows.get(b.n).row, openThen);
    for (const el of list.querySelectorAll(".dv-leaving, .dv-folding")) { el.classList.remove("dv-leaving", "dv-folding"); el.style.height = ""; }
    if (anchor) {
      const dy = anchor.getBoundingClientRect().top - top0;
      if (Math.abs(dy) >= 1) window.scrollBy(0, dy);
    }
    // 4. a short glow where it went: the fold's line, or the row itself when it is in view
    const glow = new Set();
    for (const r of [...seen, ...coming]) { const el = shownBox(r.row); if (el && onScreen(el)) glow.add(el); }
    for (const el of glow) { el.classList.remove("dv-glow"); void el.offsetWidth; el.classList.add("dv-glow"); setTimeout(() => el.classList.remove("dv-glow"), 1700); }
    // the keyboard stays where the change happened: on the block's first action, or the line of the fold it went into
    if (hadFocus && clicked && rows.get(clicked.n) && !list.contains(document.activeElement)) {
      const el = shownBox(rows.get(clicked.n).row);
      const to = el && (el.tagName === "SUMMARY" ? el : el.querySelector(".dv-act button"));
      if (to) to.focus({ preventScroll: true });
    }
    // the reading's figures, the page beside the text, and the panels that depend on what counts
    Object.assign(d, res.doc || {});
    for (const p of Object.values(panels)) if (p.live) Promise.resolve(p.live()).then(paint, () => {});
    const mine = clicked && rows.get(clicked.n);
    return !!mine && !isShown(mine.row);
  }
  return { blockActions };
}
