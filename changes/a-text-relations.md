### New

- **Relations found from the text.** When the glossary is made, ENLENS now proposes links between concepts from the
  sentences themselves, without AI: "X such as Y" and "Y and other X" (broader and narrower), "X, also called Y" and
  "X (also known as Y)" (the same), "X leads to / causes / reduces Y" (*leads to*, a new kind of link) and "X instead
  of Y" (*replaces*, also new). Only between terms the glossary knows, and only when the connecting words alone stand
  between them; words inside quotation marks are passed by. Each proposal shows the sentences it was found in, each
  with its document and page, and waits for you to accept or reject it, as links from search by meaning do. English
  sentences only, for now. Cannot change results until you accept a link. (Roadmap D2.)

### For developers

- `concept_links` rows with source `pattern` (`textrelations.py`), their sentences in the new table
  `concept_link_sentences`; `terms.LINK_RELATIONS` gains `effect`, `effect_of`, `replaces`, `replaced_by`.

### Not yet done

- Relations in other languages than English.
