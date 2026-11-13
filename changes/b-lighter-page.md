### New

- **Long lists open at once and fill in as you scroll.** The Search page shows the first 100 lines of a search and
  loads the next ones when you come near the end, instead of Previous and Next. A line under the list says how many
  are shown (*100 of 1,400 lines*), and *Show more* does the same from the keyboard. If a page cannot be loaded, the
  line says so and *Try again* asks for it again. The answers on the Hypotheses page and the excerpt cards of a long
  check (more than 40 in a list) are drawn the same way. *Next to review*, the *Show* buttons of the answer's
  sentences and the jumps back from a document draw the card they go to first, and printing draws every card. Cannot
  change results.
- **Judging an excerpt no longer draws the whole result again.** Only its card (or its row in the table), the answer,
  the counts and the part's own summary change; the scroll position, the open folds and the cards already drawn stay
  as they are. A judgement that changed the answer says so once under the answer (*Just now: Your judgement on …
  turned this from Supported to Mixed evidence*). An excerpt that moves to another list, such as *Not about this*,
  still draws the page again, with its note where the card went. Cannot change results.

### For developers

- `lazyList()` in `lib.js` (documented there): the first page, the next ones from an `IntersectionObserver` on a
  footer or from *Show more*, `reveal()` for a card that is not drawn yet, `reset()`, one request per page. It takes
  the whole list (`items`) or pages from the API (`fetchPage`, with `first` when the first page is known).
- `GET …/hypotheses` takes `offset` and `limit` (100 when not given) and answers `total`, `offset` and `limit`; without
  `offset` it answers as before.
- The result page's `applyJudgement()` fetches the result again and `patchInPlace()` makes only the changed parts
  again; `inPlacePlan()` says when it cannot and the page is drawn whole.

### Not yet done

- The Documents page's passage list still draws all passages at once; it moves to `lazyList()` in the release.
- The Hypotheses page pages its answers in the browser, not by the server's `offset`: the buttons above the list act on
  every answer shown, so the page needs all rows. The server paging is there for other callers.
- The table view of a check's evidence is not drawn in pages.
