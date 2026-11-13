### New

- **A codebook from a theory document: the AI can draft the concepts.** In *New codebook*, *From a theory document*,
  the list of concepts found without AI now has a **Draft with AI** button. The AI reads the passages of the theory
  where those concepts are defined or used most, and drafts the theory's own concepts: each with a short name, its
  definition quoted exactly from the theory with its page, and one line on why it is a concept of the theory. Every
  quote is checked against the document, and a quote that is not there goes back to the AI to be fixed. The AI's
  concepts join the end of the list **unticked and marked *AI draft***; a concept already on the list is not offered
  twice. Their examples still come only from your evidence documents, never from the theory and never from the AI,
  and only when you tick them. The document's own AI setting decides who reads it: Claude, only a local AI on this
  computer, or none (then the button is not offered, and the dialog says why). The draft waits its turn like any AI
  job, goes to Claude Code's queue when Claude Code is your AI, is written in the research log, and asking again for
  the same document reuses the answer. Nothing changes until you tick a concept and make the codebook, so nothing here
  changes results.

### For developers

- A new kind of AI task, `theory_codes` (prompt `theory-codes-v1`; Sonnet stepping up to Opus, the large local model;
  the `enlens-namer` helper, whose instructions now cover it): one task per draft, its payload the document's Level-0
  candidates and up to 12 of its passages (24,000 characters). `theorycodes.ai_offer`, `make_ai_task`, `draft_with_ai`
  and `ai_drafts`; the answer stays with the task (`results`), and the drafts are read from it. Routes:
  `GET` and `POST /api/projects/<p>/codebook-theory/<doc>/ai` (the second starts a `theory-codes` job). Settings'
  table of models per task has a new row, *Codes from a theory document*. The research log's new kind is
  `codebook-drafted` (group Codebooks).

### Not yet done

- The AI drafts concepts from at most 12 passages of the theory: in a long book, concepts defined only in passages it
  is not given are left to the list found without AI, or to you.
