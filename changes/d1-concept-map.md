### New

- **A concept map.** *Concepts* has a second tab, *Map*: the concepts mentioned in the most passages, joined by a line
  when the documents mention two together more often than by chance (pointwise mutual information, not a raw count),
  in groups, each with a colour and a shape, and with the links you accepted drawn in their types (*is part of*,
  *leads to*, *is used instead of*, *is related to*). Choose a concept to open it, or a line to see the passages that
  join the two; the map is given as lists too. Filter it by document, theme, code or year of publication; theory and
  working documents are left out. Made on this computer without AI, the same map every time. Also
  `enlens concept-map`. Does not change results.

### For developers

- `conceptmap.py` (D1) builds on `conceptpaths._Graph`; routes `GET /api/projects/{p}/concept-map`, `…/options` and
  `…/edge` (docs/API.md); `views/concept-map.js`. New tokens `--group-1` to `--group-5` (docs/DESIGN.md 3.1).

### Not yet done

- The concept map has no "needs", "shapes" or "clashes with" links (ENLENS has no such link types yet), does not name
  its groups with the AI, and cannot be saved as a picture.
