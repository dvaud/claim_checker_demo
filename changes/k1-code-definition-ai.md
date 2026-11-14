### New

- **A code's definition drafted from its examples.** In the codebook editor, open a code with two examples or more and
  press *Draft from the examples*: the AI reads only the passages that hold those examples (with the code's name and
  group) and drafts a definition, *when to use it* and *when not to use it*. The definition and *when to use it* each
  come with a quote from those passages that shows them, checked like every quote. The draft waits under the examples
  until you take a part of it, all of it, or put it aside; what you take is marked *AI draft* until you rewrite it in
  your own words, and the research log says the wording came from the AI. The mark goes with the words when you copy
  the codebook, split the code, remove it and bring it back, or keep a colleague's version of it in a sync clash; a
  `.qdc` or CSV sent out and brought back holds the words alone. Each document's AI setting decides whether its
  passage is read and by whom (Claude, only the local model, or not at all); each example is read in the document it
  was added from, and asking again with the same examples reuses the answer. Several drafts may be asked at once, and
  stopping one leaves the others waiting. With Claude Code, its helpers answer these as *Code definitions from
  examples*. Changes no result by itself: a label changes only when a code you saved is used to label again. Roadmap
  K1, its optional AI part.

### Privacy

- A draft definition sends the passages that hold the code's examples, with the code's name and group; never a
  passage of a document marked *No AI*, and one marked *Only a local AI* only to the local model (`docs/PRIVACY.md`).
  A definition you keep goes with later label tasks, as every definition does: when the local model drafted it, the
  draft says so and asks you to rewrite it if it gives away what those documents say.
