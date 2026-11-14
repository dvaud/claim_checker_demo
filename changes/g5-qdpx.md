### New

- **Your project for NVivo, ATLAS.ti and MAXQDA (roadmap G5).** *NVivo, ATLAS.ti, MAXQDA (.qdpx)* on the Hypotheses
  page, the Codes page and a result's downloads saves the project in the REFI-QDA exchange format these programs open:
  every document as text (without the blocks you left out), your codebooks as codes with their definitions, each
  hypothesis as a code with *Supports*, *Partly supports* and *Contradicts*, the labels and judgements that count as
  codings on their quotes, and your notes, highlights and research log as memos. Each coding says whose decision it
  was: yours (your name from Settings), a colleague's, or "ENLENS AI" with the model's name. Two downloads of the same
  project give its items the same ids, so the other program can tell them apart. No AI; changes no result.
- **A codebook for NVivo, ATLAS.ti and MAXQDA.** *Download as .qdc* on a codebook's page saves it as a REFI-QDA
  codebook: its groups, and each code with its definition, when to use it and when not, keywords and examples. Its
  codes keep the same ids as in the project file. On the command line: `enlens export-qdpx` and `enlens export-qdc`.

### Tests

- `test_g5_qdpx.py`: the project file is read as a strict program would (namespace, the schema's order of elements,
  every code and memo a coding or a reference points at exists, every selection inside its text and on the exact words
  of its quote, whose decision each coding is); left-out text stays out, a note on left-out words sits on its
  document, a document no AI may read still goes, the ids are the same in two downloads, the codebook alone shares
  them; the two downloads through the app and the command line. After review: control characters from PDF text in a
  title or a note no longer make the file unreadable; a hypothesis's memo comes before its *Supports* … codes, as the
  schema asks; a judgement on an excerpt read before its document was read again is left out (counted as not placed)
  instead of landing on other words; two passages cut inside a long word join without a blank line.

### Not yet done

- The `.qdpx` has not yet been opened in NVivo, ATLAS.ti or MAXQDA themselves. An export of the test project, and its
  codebook, were checked once against the official REFI-QDA 1.0 schema files (`Project.xsd`, `Codebook.xsd`) with
  `xmllint`, and pass; the tests check the schema's order of elements without the schema file.
- Nothing comes back the other way yet: a project or codebook from those programs cannot be brought into ENLENS.
