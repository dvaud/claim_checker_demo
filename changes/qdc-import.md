### New

- **Bring in a codebook from NVivo, ATLAS.ti or MAXQDA.** *Codes* › *Codebooks* › *New codebook* › *From NVivo,
  ATLAS.ti or MAXQDA* takes a REFI-QDA codebook (`.qdc`), or the codebook of a REFI-QDA project (`.qdpx`), and makes
  it a codebook of your own, still a CSV file. Top codes with codes under them become groups; deeper levels fold into
  their top group, each code keeping its place in the tree at the end of its definition; a code without a description
  gets its place in the tree as a stand-in definition. A summary says what came in and what was folded or left out
  (colours, sets, codes that cannot be coded). A codebook ENLENS exported comes back with its definitions, when to use and when not, keywords, examples (their words) and groups. No AI. On the
  command line: `enlens import-qdc FILE [NAME]`. Changes no result by itself: it is a new codebook.

### Safer

- A REFI-QDA file that declares a DOCTYPE or an ENTITY is refused before it is read, and a `.qdpx` is read no further
  than its `project.qde` (at most 64 MB unpacked, 5,000 files).

### For developers

- *Download as .qdc* writes a code's keywords separated by `; ` (was `, `), as the CSV does, so a keyword holding a
  comma comes back whole.
