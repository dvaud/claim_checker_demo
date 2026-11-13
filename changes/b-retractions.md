### New

- **Check the bibliography for retractions and corrections.** *Check for retractions* on the Bibliography page
  asks Crossref, which carries Retraction Watch's list, whether the works of your bibliography and your documents
  have been retracted, corrected or flagged with an expression of concern. A warning stands under the title of each
  affected work (a retraction is the serious one), and an excerpt from a document whose work has a notice shows a small
  warning in a check's results. The page keeps the date of the last check. It runs only when you press the button
  (or `enlens retractions <project> --check`), sends only DOIs (no name, no email address, no project name), leaves
  out works whose document is marked No AI, and sends nothing under local-only. Cannot change results.

### For developers

- `retractions.lookup`, `status`, `for_docs`, `for_items`; the table `retractions`; `GET …/retractions` and
  `POST …/retractions/check`; `notices` on each work of `GET …/bibliography`; `ENLENS_CROSSREF_URL` sets another
  address. Tests: `tests/test_retractions.py`.

### Not yet done

- Works without a DOI are not looked up (matching by title would send titles).
- A lookup is not repeated by itself: press the button again to see new notices.
