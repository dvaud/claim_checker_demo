### New

- **A concept map.** *Concepts* has a second tab, *Map*: the concepts mentioned in the most passages, joined by a line
  when the documents mention two together more often than by chance (pointwise mutual information, not a raw count),
  in groups, and with the links you accepted or added, the AI's confident ones and the abbreviations drawn in their
  types (*is part of*, *leads to*, *is used instead of*, *is related to*; two types between the same two concepts are
  both named). Groups 1 to 5 are filled shapes, each in its own colour; groups 6 to 10 the same shapes outlined; the
  smaller groups after them grey stars; a concept in no group a grey dashed circle, so no mark is told apart by colour
  alone. Choose a concept to open it, or a line to see the passages that join the two; the map is given as lists too.
  Filter it by document, theme, code or year of publication; theory and working documents are left out. A line says
  when the map is being counted, and the page says when it rests on fewer than 30 passages. Made on this computer
  without AI, the same map every time. Also `enlens concept-map`. Does not change results.

### For developers

- `conceptmap.py` (D1) builds on `conceptpaths._Graph`; routes `GET /api/projects/{p}/concept-map`, `…/options` and
  `…/edge` (docs/API.md); `views/concept-map.js`. New tokens `--group-1` to `--group-5` (docs/DESIGN.md 3.1), each at
  3:1 or more against `--surface` in both themes. The map's temporary tables are kept in memory
  (`PRAGMA temp_store=MEMORY` on the connection), so a request writes no temporary file.

### Not yet done

- The concept map has no "needs", "shapes" or "clashes with" links (ENLENS has no such link types yet), does not name
  its groups with the AI, and cannot be saved as a picture.
