### Changes that can alter your results

- **Reader 5 finds tables from their ruled lines, joins a table that runs over a page, and keeps figures as blocks of
  their own.** A table whose cells hold sentences, or whose numbers are aligned on the right, was read as paragraphs,
  because reader 2 found tables only where their columns have clear gaps. Reader 5 also uses the lines and boxes a PDF
  draws: a table ruled in a grid, or set with a rule above, under the header and below, is found with its rows and
  cells, left out of what searches, codes and checks read, and shown as a table in the reading view (and for Excel).
  A table at the foot of a page and the table at the head of the next, with the same number of columns and width, are
  one table (its header row once, if the next page repeats it). A chart drawn in lines and boxes, and an image, become
  one block each: its page, where it stands on the page, the words inside it (left out of passages, as before) and its
  caption (*Figure 3. …*), which stays a block of its own and still counts for checks. The picture itself is never
  stored and never sent to an AI: the reading view draws it from the original PDF when it is shown (`GET
  …/figures/<n>.png`), so a figure costs a page number, a box and its caption, and a large corpus does not grow. A
  Word file or web page keeps an image's alternative text as a block that is left out of passages, without the
  picture. **Can change results, for documents you move to it.** New documents are read by reader 5; documents already
  in a project keep their reading, and every result in them stays where it is, until you press *Read with the new
  reader*. A box round one paragraph is not a table, a logo repeated on every page, an icon and a scanned page are not
  figures, and a table or figure in a page that has no text layer (a scan, read by OCR) is not found.
- **Measured before it ships** (`enlens measure --reader 4 5`, four new documents of known text added to the reading
  test, the six of 0.15 unchanged). Reader 5 reads every old document as reader 4 does and the new ones better:

  | Document | Reader 4: words that belong · left-over table or figure text · tables (rows) · figures | Reader 5 |
  |---|---|---|
  | (g) table ruled in a grid, sentences in its cells | 84.2% · 0 of 5 · 1 (4) · 0 | 100% · 0 of 5 · 1 (4) · 0 |
  | (h) rules above, under the header, below | 100% · 0 of 6 · 1 (5) · 0 | 100% · 0 of 6 · 1 (5) · 0 |
  | (i) ruled table over two pages, header repeated | 97.3% · 1 of 42 · 1 (7 of 41) · 0 | 100% · 0 of 42 · 1 (41) · 0 |
  | (j) a chart with labels, and a picture, each with a caption | 93.0% · 5 of 6 · 0 · 0 | 100% · 0 of 6 · 0 · 2 |

  Average over the ten documents, reader 4 → reader 5: words kept 99.97% → 99.97%, words that belong 97.4% → 99.97%,
  reading order 99.97% → 99.97%, words run together 0.1 → 0.1, words broken apart 0 → 0, left-over running heads,
  notes and table or figure text 0.6 → 0. Reader 4 already finds table (h) and part of (g) by the gaps between its
  columns, so there reader 5 changes the words that belong (g) and the box (h: the rules' width), not the table.

### For developers

- `reader5.py` (new): `record` (pdfminer's lines, boxes and pictures per page, `reader._pdfminer_pages(path, shapes)`
  for version 5 only), `ruled_tables`, `figures`, `place`, `join_tables`, `link_captions`, `mark_text_figures`.
  `reader.Block` has an optional `box` that `bbox` uses when set (readers 2 to 4 never set it); a figure's `Block.caption`
  holds its caption. `READER` is 5 in `reader.py` and `ingest.py`; `RawDoc` has `before_5` (what readers 2 to 4 read of
  a Word file or web page) and `figures` (their images' alternative texts); `ingest._read_docx` returns six values.
  A figure without words is a block with `start == end` (no passage, a row in `blocks` with its box); the reading
  report has `figures` and `tables_joined`. `pdfmake.Page.rule/box/image` draw ruled lines, boxes and grey pictures for
  test PDFs. `measure.make_table_figure_texts` makes the four new documents; `measure.run` adds them when reader 5 is
  among the readers; `measure_case` gives `tables_found`, `table_rows` and `figures_found`.
  The fingerprints of readers 2 to 4 are unchanged (`tools/reader_fingerprints.py` on the demo corpus and the known
  texts: 0 differ). Tests: `tests/test_reader5_tables_figures.py`.

### Not yet done

- **Text inside figures is not read (no OCR of figures)** and **no picture is stored**: both would make a large corpus
  heavy, so the picture is drawn from the original PDF each time it is shown.
- **Tables in scanned pages stay unfound** without GROBID or Docling (roadmap A1).
- A table set with rules above and under its header but no rule below its last row, and a table that has no rules
  and no clear gaps between its columns, are not found from their rules. A table that runs over a page is joined only
  when it is the last block of one page and the first of the next (a *Table 1 (continued)* line in between stays a
  caption of its own).
- Merged cells are read as one cell of the first column they start in; a cell whose words run across a rule is
  read as its first column's.
- A chart whose labels are in the body's type size and stand far from it, or whose axes are far from its drawn
  area, may leave some of its words in the text. A drawing with more than 900 characters of text in it, or a page laid
  out with boxes (a slide), is not taken for a figure.
- Images in Word files and web pages: the alternative text of an image inside a table cell, and of an image in a
  header or footnote, is not kept. A picture's own caption is the text Word or the page already holds.
