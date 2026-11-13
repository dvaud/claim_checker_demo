[Manual](../MANUAL.md) › Notes, the research log and earlier versions

# Notes, the research log and earlier versions

> **In short**
> - Highlight and note the exact words of a document; a note can become evidence in a check. *Documents* › *Notes* lists them all.
> - ENLENS writes a dated *Research log* by itself, and you add entries of your own, from any page: what was decided, and why.
> - *History* keeps what you changed (themes, your judgements, codebooks) so you can compare it with now and go back.

## Highlights and notes

In a document, select words in its text. The bar that appears offers *Highlight* (yellow) and *Note*, where you write
your words and choose one of four colours. Click a highlight to see its note: *Edit* (or *Add a note*),
*Use as evidence* and *Remove*. The document's *Notes* panel lists the notes of that document; click one to find it in the text.

The *Notes* view of *Documents* (a tab under the page title) lists every note of the project by document. Search
the words of the notes and of the passages they mark, filter by document and by colour, and download them as Markdown
(.md) or Excel (.xlsx).

- **The words are checked.** A note holds words that are really in the document, as every quote is. A selection cut
  inside a word is widened to the whole word.
- **A document read again.** When a document is read with the new reader ([Read with the new reader](reading.md#read-with-the-new-reader)), each
  note follows its words. One whose words are no longer in the text says so, and is kept.
- **A removed document.** Its notes are kept, marked *removed from the project*.
- **Yours and a colleague's.** A note is yours alone until you share it (0.17.0). You can change only your own notes; a
  colleague's are shown with their name.

### Use a note as evidence

*Use as evidence* on a note, or *Add one of your notes* under a part of a check on the result page
([Read and review a result](review.md)), turns it into an excerpt you judged: the passage that holds the note's words
is the excerpt, your judgement and an optional comment come with it, and the note's words are the sentence you point to.

Two limits. The passage must be text that is read, not text left out of the reading. And the words must lie within
one passage; a note across two passages needs a shorter span. If the check already had the passage, your judgement of
it is set instead.

## The research log

The *Research log* is a dated record of what was decided in the project. It is a view of *Overview*, and a
*Research log* button at the top right of every page opens it as a panel on the right. It always opens the
*Research log*; the *Team* tab has its own row under the project's name. ENLENS writes an entry by itself when you:

| Group | What is written down |
| --- | --- |
| *Documents* | Documents added or removed, who may read documents with AI, a document read again with the new reader |
| *Checks* | A hypothesis checked, a check removed, a note used as evidence |
| *Themes* | Themes found; a set, or a theme, removed; a theme renamed, merged or restored |
| *Codebooks* | A codebook made, changed, moved, copied or removed |
| *Restored versions* | An earlier version put back |
| *Work together* | A colleague's work brought in, and what it brought |

*New entry* with *Add to the log* writes an entry of your own (a decision, a reason, a field note). In the panel you
write the entry in the box at the top: it is kept with the page you are on, and the panel lists that page's entries
(*This page*) or all of them (*All*). *Edit* and *Remove*
are for your own entries only: the entries ENLENS wrote are the record of what happened and cannot be removed or
reworded. Beside an entry that ENLENS wrote for something you did, *Say why* (later *Change why*) adds your reason.
Removing a document, a check, a set of themes or a theme, and saving a codebook, ask *Why? (optional, kept in the
research log)*, so the reason is written when it is fresh.

Filter the log by group, search it, and download it as Markdown (.md), oldest first with a heading per day, or as
Excel (.xlsx): for an appendix or an audit. An entry about a change has *Compare with before*, which opens the version
from before the change ([below](#earlier-versions)).

The log is part of the project. An entry you write is yours alone until you press *Share* on it (0.17.0;
[Work together](together.md#private-until-you-share-it)); a shared one reaches your colleagues under your name, and an
entry you removed does not come back. What ENLENS itself writes about the documents is shared with the project.

## Earlier versions

ENLENS keeps what you made before you change it:

| Where | The button | What is kept |
| --- | --- | --- |
| *Themes*, on a set of themes | *History* | Theme names, merges, moves of passages and removed themes |
| The foot of a result | *History of your judgements* | Your judgements, comments, the sentences you point to and the check's note |
| A codebook | *History* | The codebook as it was before each saved change |

The AI's answers and the themes themselves are not versioned: a new run makes them again from the same settings.

*History* lists the versions, newest first. *Compare with now* shows what changed in a table: *What*, *Then* and *Now*.
*Restore this version* puts it back, and keeps the state it replaces as a version too, so a restore can be undone the
same way. The research log notes every restore.

> [!NOTE]
> Versions belong to the copy that made them. Bringing in a colleague's work does not take over their versions or give
> them yours; a move to another computer ([Work together](together.md#moving-to-another-computer)) keeps yours.
