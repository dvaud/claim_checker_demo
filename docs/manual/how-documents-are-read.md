[Manual](../MANUAL.md) › How documents are read

# How documents are read

> **In short**
> - Before anything else, ENLENS turns each file into text and cuts it into passages. Search, codes, themes,
>   concepts and checks all read those passages.
> - What is not the document's own text (running heads, page numbers, author details, reference lists…) is set
>   aside, and tables and figures are kept apart from the passages.
> - The part that does this is the *reader*. Every document records which reader read it, and keeps that reading until
>   you move it.

This page explains how a file becomes text. To see how a document was read, and to put it right, use
[Look at how a document was read](reading.md); the method for a methods section is in
[METHODS.md](../METHODS.md#reading-documents).

The part of ENLENS that does this is the **reader**. Every document records the reader that read it, and a document
keeps that reading until you move it ([how](reading.md#read-with-the-new-reader)), so every quote and judgement in it stays
where it is.

| Reader | Since | Reads |
| --- | --- | --- |
| 1 | before 0.15 | Every document added before 0.15. |
| 2 | 0.15.0 | PDFs by their layout: columns, tables, what to set aside. |
| 3 | 0.15.1 | Reader 2, plus text files and books: running heads, page numbers, paragraphs and headings found from the text alone. |
| 4 | 0.17.2 | Reader 3, plus: a text file with one paragraph per line, and a Word file's content controls and tables inside tables (see *What reader 4 changed* below). PDFs and web pages read as with reader 3. |
| 5 | 0.18.1 | Reader 4, plus: tables found from their ruled lines and joined across pages, figures as blocks of their own with their captions, and a Word file's or web page's pictures by their alternative text (see *What reader 5 changed* below). Plain text files read as with reader 4. |


## What the reader does

**With a PDF**, it looks at where each line stands on the page (with the PDF layout reader, which the one-line install
has; without it, it reads the PDF's text layer, without columns or tables):

- **Columns** are read one after the other, not across, and a title or abstract set across the page comes first.
- **What is not the document's own text is set aside**: running heads and footers, page numbers, line numbers in the
  margin, the words inside charts and diagrams, author names, affiliations, e-mail addresses and dates on the first
  page (*author and article details*), acknowledgements, funding, conflicts of interest, data availability and
  licence notes (*end notes*), footnotes, and the reference list. They stay in the document and in a search of all
  its text, but searches, codes, themes and checks do not read them. So themes no longer form around journal names,
  and checks no longer read a funding note.
- **Tables are kept as tables**, with their caption, rows and cells: found from the gaps between their columns, and
  (reader 5) from the lines a PDF draws, a grid or rules above, under the header and below. A table that runs on to
  the next page is one table, its header row once. Tables are left out of the passages (a table read as prose garbles
  a passage), and each can be downloaded for Excel.
- **Figures are blocks of their own** (reader 5): a chart drawn in lines and boxes, or a picture, with its page, where
  it stands on the page and the words inside it. Those words stay out of the passages. Its caption (*Figure 3. …*)
  stays a block of its own and counts for checks like any paragraph.
- **Words are repaired**: a word cut at a line end is joined ("exam-ple" → "example"), a compound keeps its hyphen
  ("long-term"), words that ran together are split only where the document itself writes them apart ("ofthe" → "of
  the"), and ligatures (ﬁ, ﬂ), odd spaces and accents set apart from their letter are put right.
- **A passage is a paragraph.** Long ones are cut into parts of about equal size, short ones are put together, and a
  heading starts a new passage with the text under it. Paragraphs are numbered as quotes are cited: per page in a PDF
  (a heading with the text under it counts as one), every block between blank lines in a text file.

**Word files, web pages and text files** are read with the same repairs, their headings and reference list set aside
in the same way. A Word file's tables are read row by row, a table inside a table's cell after the row that holds it;
text in its content controls (a cover page, a contents box, form fields) is read like any other text, and Word's own
table of contents is set aside as a book's is. Footnotes, comments and text boxes are not read. A picture in a Word
file or web page (reader 5) is kept by its alternative text, as a block left out of the passages, without the
picture itself.

**Text files and books.** Many `.txt` and `.md` files are text copied out of a PDF by a converter: every running
head and page number is still in the text, while the pages, the headings and often the spaces between words are
gone. Reader 3 reads such files by rules on the text alone (no AI):

| It finds | How |
| --- | --- |
| Running heads and footers | They come back about once a page, next to a page break or at regular intervals ("Frontiers in Neurology 04 frontiersin.org"); a short one in capitals with its page number ("2 INTRODUCTION") from two pages, or from the contents. Answers that recur in an interview ("[P] Ja.") recur irregularly, mid-text: they stay. |
| Page numbers | Lines that are only a number, counting up a page apart. |
| Paragraphs and headings | A short line that ends a sentence ends its paragraph; a short line on its own is a heading. A Markdown file, web page or Word file that marks fewer than three headings gets headings this way too. |
| A book's parts | The table of contents (lines ending in page numbers that go up) is set aside, and its entries find the chapter headings. Front matter before the first chapter (half title, other books by the author, copyright page, dedication, lists of figures) is set aside, but an abstract, summary or preface stays. Notes, bibliography, index, *About the author* and acknowledgements at the end are set aside; an index is also known by its lines ("archetypes, 112–116, 191"). |
| Damaged text | Text printed twice ("TTIISS ffiinnaall" → "TIS final"), ligatures broken by a space ("fi nd" → "find"), and, only in a file that lost many of its spaces, words run together ("peoplelivingwithdementia" → "people living with dementia", using words the document itself writes apart; never into word endings). |

**What reader 4 changed.** Reader 4 reads three things otherwise than reader 3; everything else reads exactly as before:

- **A text file with one paragraph per line**, as Word saves "plain text": no blank line between paragraphs, each
  paragraph one long line. Reader 3 read such a file as a single paragraph, so every quote in it was cited as
  paragraph 1. Reader 4 takes each line as a paragraph. A file whose lines are wrapped to one width, or whose
  paragraphs have a blank line between them, reads as before.
- **A table inside a table's cell** in a Word file was read three times; it is now read once.
- **Text in a Word file's content controls** (and in custom XML) was left out without a word; it is now read.

**What reader 5 changed.** Reader 5 reads every document as reader 4 does, except:

- **Tables from their rules.** A table whose cells hold sentences, or whose numbers are aligned on the right, was read
  as paragraphs, because it has no clear gaps between its columns. Reader 5 also uses the lines and boxes the PDF
  draws, so such a table is found with its rows and cells, and left out of the passages.
- **A table over two pages** is one table: the table at the foot of a page and the one at the head of the next, with
  the same columns and width, are joined, and a header row the next page repeats is kept once.
- **Figures.** A chart or a picture is one block, with its caption beside it. Its words no longer slip into the text
  around it.
- **Pictures in Word files and web pages** are kept by their alternative text.

The picture itself is never stored and never sent to an AI: the reading view draws it from the original PDF when it
is shown, so a large corpus does not grow. Kept out on purpose: reading the text inside pictures (OCR of figures),
storing pictures, and tables or figures on scanned pages (a page with no text layer).


## Measuring how well ENLENS reads

`enlens measure` shows in figures how well ENLENS reads, with no AI. It makes small PDFs whose text it knows (one and
two columns, running heads, line numbers, front and back matter, a table, footnotes), reads them with each reader,
and reports the share of the words kept, the share that belong, whether they come in order, words run together or
broken apart, and leftover boilerplate.

From 0.18.1, when reader 5 is measured, four more documents of known text are added: a table ruled in a grid with
sentences in its cells (g), a table with rules above, under the header and below (h), a ruled table over two pages
with its header repeated (i), and a chart with labels and a picture, each with a caption (j). It then also counts the
tables, their rows and the figures found. Reader 5 read the six earlier documents as reader 4 does, and the new ones
better:

| Document | Words that belong, reader 4 → 5 | Table or figure text left in passages | Found by reader 5 |
| --- | --- | --- | --- |
| (g) table ruled in a grid | 84.2% → 100% | 0 of 5 → 0 of 5 | 1 table (4 rows) |
| (h) rules above, under the header, below | 100% → 100% | 0 of 6 → 0 of 6 | 1 table (5 rows) |
| (i) ruled table over two pages | 97.3% → 100% | 1 of 42 → 0 of 42 | 1 table (41 rows; reader 4: 7) |
| (j) a chart and a picture, with captions | 93.0% → 100% | 5 of 6 → 0 of 6 | 2 figures |

Over the ten documents, the words that belong rose from 97.4% to 99.97%, and leftover running heads, notes and
table or figure text fell from 0.6 to 0; the words kept, their order and words run together or broken apart stayed
the same.

| Option | Adds |
| --- | --- |
| `--folder DIR` | Measures PDFs that have a `.txt` of their true text beside them. |
| `--ws PROJECT` | How many of a project's quotes still find their place in each reader's text (on a copy: the project never changes). |
| `--timings` | How long reading, search, *Words nearby*, the keyword pass, the *Codes* page, key terms and themes take. |
| `--report FILE.md` | Writes it all as a report. |

Each release carries this report as `validation-report.md`.

---

Next: [How two copies of a project come together →](how-two-copies-come-together.md)
