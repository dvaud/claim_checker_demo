### New

- **Paths between two concepts.** A concept's page has a new card, *Paths to another concept*: type another concept
  and ENLENS lists the shortest chains between them, through the links you accepted and the concepts the documents
  mention together more often than by chance (by PMI). Each step shows the passages that join its two concepts, so
  you can follow an argument the corpus already makes. A list, not a drawn map. Cannot change results. (Roadmap D3.)
- **A concept over time and across groups.** A second card, *Over time and across groups*, shows how the concept is
  worded and what it is mentioned with, by publication year (from the works in your bibliography; documents without
  a year are counted apart), or in two sets of documents you pick on the page (policy against academic, one country
  against another; not kept). Cannot change results. (Roadmap D4.)
- Theory documents are left out of both.

### For developers

- `conceptpaths.py` (`paths`, `over_time`, `compare_groups`); routes `GET /api/projects/{p}/concept-paths?from&to`,
  `GET /api/projects/{p}/concept-time/{term}`, `POST /api/projects/{p}/concept-groups/{term}`.

### Not yet done

- The concept map (roadmap D1) that would draw these paths.
