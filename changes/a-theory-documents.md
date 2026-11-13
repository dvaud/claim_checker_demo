### New

- **Mark a document as theory: the lens, not the evidence.** A book or paper your research is read through (a theory
  of practice, a systems text) can be marked *Theory*, in the Documents list (each row's menu) or on the document's
  page. It is still read, searched, opened and noted as before, but it is left out of themes, labelling with
  codebooks, the excerpts a check reads, key terms and the glossary's counts (and so of the evidence map). You set
  it; ENLENS never guesses: a study that *uses* a theory is still evidence. Marking or unmarking changes no result by
  itself: the document's page lists the themes, codebook labels and checks made with it in, with links to make them
  again without it. In a shared project the mark travels like *Leave out*: the Owner's or a Co-owner's holds at once,
  a Member's is a proposal for the owner to accept. Cannot change results by itself; what you make afterwards
  leaves the theory out. (Roadmap K2, part 1.)

### For developers

- `documents.role` (`NULL` evidence, `"theory"`; room for N3's `"working"`) is read from the block choice
  `role:theory` (`docrole.py`), so the mark syncs, merges and is proposed as block choices are, with no new sync
  format. Every filter goes through `docrole.evidence_sql()` / `theory_docs()`. `search.rank_passages` gained
  `evidence_only` (default true; the Search page's search by meaning passes false; documents named in `doc_ids` are
  kept). Routes: `GET /api/projects/{p}/document-roles`, `GET`/`PUT /api/projects/{p}/documents/{d}/role`.
