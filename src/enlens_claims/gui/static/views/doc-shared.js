// Documents, shared by the list (sources.js) and a document's page (doc-page.js and the panels beside its text): how a
// document was read and the offer of a move to the new reader, the reader's kinds of block in words, where the reader
// was before a repaint, and a job the page started earlier.
import { api, h, icon, fmt, P, TERMINAL, session, link, tag } from "../lib.js";

// 0.15: how a document was read, in the list: one that read badly or has something to check (0.15.7: until the
// person marks the reading as checked), or one read by an earlier reader (0.15.7: also 0.15.0's; its link opens the
// preview of the move)
export const reader = { latest: 5 };  // ingest.READER, as the list of documents says it
// 0.17.2: what reader 4 reads otherwise than reader 3 (only text files and Word files can change)
// 0.17.2: reader 4 reads only text and Word files otherwise than reader 3, so a reader-3 PDF or web page is not offered
// it (it would read the same); documents of earlier readers are offered it whatever their kind
// 0.18.1: from reader 5 a plain text file reads the same as by reader 4 (reader 5 changes tables, figures and pictures),
// so a reader-4 text file is not offered the move
export function newReaderFor(d, latest) {
  const r = d.reader || 1;
  return r < latest && !(r === 3 && latest === 4 && !["text", "docx"].includes(d.kind)) && !(r === 4 && latest === 5 && d.kind === "text");
}
export const READER_5_NEWS = "The new reader also finds tables from their ruled lines, joins a table that runs on to the next page, and shows figures and pictures with their captions (drawn from the original PDF, never stored). Other text reads the same.";
export const READER_4_NEWS = "The new reader takes each line of a text file without blank lines between its paragraphs as a paragraph of its own, and reads the text in a Word file's content controls and a table inside a table once. Other documents read the same.";
export function readingNote(d) {
  const href = `#/doc/${encodeURIComponent(d.doc_id)}?tab=reading`;
  if ((d.reading_quality === "poor" || d.reading_quality === "fair") && !d.reading_checked) {
    const title = `${(d.reading_warnings || []).join(" ")} Open it to see where to look, then mark the reading as checked.`.trim();
    // a tag is a fact and is never pressed: the way to the reading is a link of its own after it (DESIGN 4.10)
    if (d.reading_quality === "poor") return h("span", {}, tag({ kind: "attention" }, "read badly"), " ", link({ href, title }, "Look at its reading"));
    return link({ href, title, class: "it small" }, icon("info", { size: 12 }), "something to check in its reading");
  }
  if (newReaderFor(d, reader.latest)) return link({ class: "it small", href: `${href}&preview=1`, title: "Read by an earlier reader of ENLENS. Open it to see what the new reader would change, or read several at once with the button above the list." },
    icon("layers", { size: 12 }), (d.reader || 1) < 2 ? "read before 0.15" : "read by an earlier reader");
  return null;
}

// 0.15: what each kind of block is called in the reading view (reader.KIND_TEXT), in the plural for counts
const KIND_PLURAL = { title: ["title", "titles"], heading: ["heading", "headings"], abstract: ["abstract paragraph", "abstract paragraphs"], body: ["paragraph", "paragraphs"],
  caption: ["caption", "captions"], table: ["table", "tables"], footnote: ["footnote", "footnotes"], front: ["part of the front matter (authors, publishing details)", "parts of the front matter (authors, publishing details)"],
  back: ["end note (acknowledgements, funding, licence)", "end notes (acknowledgements, funding, licence)"], references: ["part of the reference list", "parts of the reference list"],
  figure: ["piece of text inside a figure", "pieces of text inside figures"], furniture: ["running head or page number", "running heads and page numbers"],
  // 0.15.1 (reader 3)
  contents: ["line of the table of contents", "lines of the table of contents"], index: ["part of the index", "parts of the index"] };
export const kindCount = (k, n) => `${fmt.num(n)} ${(KIND_PLURAL[k] || [k, k])[n === 1 ? 0 : 1]}`;

// where the reader was before a block was restored or left out (0.15), a move to the new reader (doc-reading.js), kept
// for the next drawing of the document page (doc-page.js): `keep.place` is {doc, y, tab, focus, open}
export const keep = { place: null };
// a job this page started earlier (kept for this tab), if it is still running
export async function stillRunning(key) {
  const j = session(key);
  if (!j || !j.id) return null;
  try { const job = await api("GET", `/api/jobs/${P(j.id)}`); if (!TERMINAL.has(job.state)) return j; } catch (_) { /* gone */ }
  session(key, null);
  return null;
}
export const norm = (s) => String(s || "").replace(/\s+/g, " ").trim().toLowerCase();
