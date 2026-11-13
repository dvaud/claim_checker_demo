### New

- **Less scrolling sideways.** Wide grids, tables and lines now keep important information in view:
  - **Themes, documents by theme.** Documents are now the rows and themes the columns, so a project with many
    documents runs down the page instead of off to the right.
  - **Full screen for grids.** A grid wider than the page (the Evidence map, Codes by document, Themes) says which
    columns it shows ("Documents 1–6 of 23"), has arrows that move it one view at a time, and has a **Full screen**
    button. In full screen the grid fills the window and scrolls every way like a spreadsheet, and its header row
    and first column stay in place. Escape or *Exit full screen* returns to the page; following a link from the
    grid also closes it.
  - **Tables in the reading view.** A table taken from a document wraps its words to the reading column; only cells
    that are figures stay on one line.
  - **Smaller fixes.** Settings' table of models per task and a model test's results stack into labelled rows when
    space is short, like the other tables. In search results, a long phrase found is cut with "…". Long names no
    longer widen the tables that compare versions or pick groups. The drawer's tabs no longer run under its close
    button.
- **The Documents page is a list of one-line documents that open.** Each document is one line: its title, who may
  read it with AI, its role, a wait for the owner and anything that needs a look. The arrow at the end of a line, or a
  click on the line, opens a panel under it that names every fact and holds its controls: the file, who may read it
  with AI (three buttons, plus the note on why), how much Claude has read and *See what it read*, how it was read, its
  role, its place in the bibliography, *Open the document* and *Remove…*. The bare "text", "—" and "0%" of the old
  table are gone, and nothing hides in a column off to the side. Ticking documents shows a bar that stays in view, with
  one button per setting instead of a select and *Apply*.

Nothing here changes results.

### For developers

- `heatGrid(table, { label, unit })` (lib.js) draws every heat grid in its frame, with the bar, the arrows and Full
  screen (a native `<dialog class="grid-full">` the same frame moves into and back). `accessSelect` is gone: the
  Documents list sets a document's AI access with `choice()` in its panel. DESIGN.md 4.20, 4.24, 4.25 and 9 say how.

### Tests

- The design tests know `heatGrid` (it is on the reference page), the new soft-teal state of an open document, and the
  Documents list instead of its table; source tests follow the citation, the marked lines and the panel's actions.
- Checked in Chromium: a 30-column grid's bar, its arrows (no column stepped over), Full screen (header row held,
  scroll kept, closed by Escape and by a followed link); the Documents list at 1440 and 539 px, a setting changed,
  the question before loosening one and its Cancel, the bulk bar. The whole suite passes.

### Not yet done

- Themes, documents by theme, was not seen with a real theme run (the demo project has none).
- Tilted column heads would let narrow count columns fit, so a grid of a dozen themes would not scroll at all.
