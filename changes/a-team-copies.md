### Fixed

- **A colleague's removal is no longer undone without a word.** When a Member removed a document and the owner,
  not yet knowing of it, took the same document out and in again, the Member's removal was quietly undone in their
  copy. Now it is undone only when the project went on *knowing* of it (its card then says the document was removed
  and added again since); otherwise it stays out of the Member's copy and their proposal waits for the owner.
  Cannot change results.
- **A former owner's late answer no longer shows as *Accepted*.** After a take-over, an answer the former owner gave
  offline to a proposal the new owner had not answered showed as *Accepted* on its card, although it changed no
  document. It now waits for the new owner, as their late changes to the documents already did. Cannot change
  results.
- ***Not now* on a take-over holds in every browser.** It was kept only in the browser where you clicked it; it is
  now kept for you in the project. Cannot change results.
- **A project zip from a newer ENLENS is refused in words.** Opening such a zip as a new project now says to update
  ENLENS first and changes nothing, as bringing it into a project and the shared folder already did. (ENLENS 0.17.0
  to 0.18.0 still open such a zip without a warning: that cannot be changed after the fact.) Cannot change results.

- **Taking a project back never loosens an AI setting.** After *Take the project back*, a looser setting that your
  copy had gone on from (by your own stricter setting) could be put into force again without your click. It is now
  only offered, as every looser setting is. Cannot change results. (Found by the randomised roles test.)
- **A second take-over at the same point is refused in words.** Taking a project over twice at the same point of its
  history, after two different owners, left the copies disagreeing about the owner without a word (a copy keeps the
  first record it holds). ENLENS now refuses the second and says what to do: ask the owner to hand it over, or follow
  your earlier take-over. Cannot change results.
- **A removal is noted as the word of whoever keeps it.** A document a former owner removed, kept removed by the new
  owner's copy, was noted as removed "by" the former owner, who may be a Member in your copy by then; it is now the
  owner's word that is noted. Cannot change results.

### New

- ***Become the owner* says what becomes a proposal.** Its dialog now says that what colleagues removed or left out
  in their own copies before becomes their proposals, all at once; and each colleague's Team tab says so once when
  it happens ("2 documents you removed … are now your proposals to Anna"). Cannot change results.

### For developers

- `canon.hist_json` gains `seen`: the removals proposed for the document that its writer had seen when it last
  changed the document's state (`ownership.removal_spent`). A new owner writes, once, a mark in `decisions`
  (`proposal` `~restamped:<place>`, `knew_json` the former owners' answers it held); a former owner's answer not in
  it no longer counts. Both are ignored by ENLENS 0.18.0, so the sync format stays 4.

### Tests

- The randomised roles test now also takes the project over, answers the question (follow, keep, *Not now*), sends
  zips after a take-over, turns the documents switch on and off and opens the Team tab without a round, and checks
  that no document leaves a copy without its person's own removal or the word of its current Owner or a Co-owner.
