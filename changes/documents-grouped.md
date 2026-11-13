### New

- **Documents, grouped as you choose, with a filter.** The Documents page now groups its list: by who may read the
  documents with AI (the first time), by their role (evidence or theory), by what needs a look, or not at all, and
  sorts it by title or newest first. Each group has a head that stays in view while it scrolls, with a count and
  *Select these N*, which becomes *Clear these N* once they are all ticked, and one sentence under it on what the
  group means. A box above the list keeps the documents whose title or file name holds the words you type. A long
  title ends in "…" on its line and shows whole when the line is opened. A closed line shows its marks as small
  icons (a warning, something to check in its reading, read by an earlier reader, theory, a wait for the owner),
  each named when you point at it and said in words in the panel the line opens; it shows its file name only when
  another document has the same title. When a document's setting changes it moves to its new group without the
  page jumping, and glows where it lands. *3 documents need a look* now has *Show them*.
- **Made for long lists.** Under the filter, each group's count takes you to it ("Claude: 266 documents · Local AI:
  27 documents · No AI: 14 documents"); a group's head stays under the page's top while its documents scroll, and
  folds away (remembered per project). The bar for the ticked documents stays at the bottom of the window and says
  how many of them the filter or a fold hides; a line above the list leads to it; after a change the ticks are
  cleared and the message has *Undo*, which asks first when it would let Claude read documents again. Once a
  project has documents, *Add documents* is one line that opens.

Nothing here changes results.

### Tests

- The design tests know the Documents list's own tick (DESIGN 9.5) and its title room; source tests follow the
  owner's word in the panel. Checked in Chromium on a project of 307 documents: grouping, folding, the jumps, the
  filter, moves that open a folded group and keep the focus, the bar's change and its Undo (with the question before
  Claude may read again), phone, dark and the drawer open.
