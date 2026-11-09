[Manual](../MANUAL.md) › Explore your documents

# Explore your documents

> **In short**
> - Before or beside checking, the pages under **Explore the documents** show what your documents say and where.
> - Search, key terms, the keyword profile, the glossary and themes by words need **no AI**. The AI only adds
>   readings on top, and each one quotes the text and is checked against it.
> - Every line, code and theme opens the document at its place.

| Page | What it gives | AI? |
| --- | --- | --- |
| [Search](#search) | Every place words occur, with the words around them; phrases, near, other forms, words nearby; Excel/CSV | no |
| [Profile](#profile) | The codes each document addresses, how much and where, with the words or quote and reason behind each | keywords first; the AI confirms |
| [Concepts](#concepts) | A glossary of terms grouped into concepts (abbreviations, wordings, your links), and where each appears | optional |
| [Themes](#themes) | Themes across the documents, by document and by code; rename, merge, move, remove | optional (names) |
| [A document](#in-a-document) | Its codes, key terms, references ("it", "they"), search, a highlighted copy, how it was read | references only |

## Search

<img src="../images/manual/search.png" alt="Search: the count per document, then one line per place with the words around it" width="800">

Every place words occur, one line per place with the words before and after (a concordance), with the count per
document first.

| You want | Do |
| --- | --- |
| Any of the words, all of them in one passage, a phrase, or words near each other | Choose it under *Find* (*near*: within N words). In a phrase search, words typed next to a "quoted phrase" must also be in the passage. |
| Other endings too ("price" finds "prices") | The default. *Exact words only* turns it off. Forms the search did not include are listed under the count (*Other forms in the documents: commuters*), to add with one click. |
| To grow the search from what you see | Click a word in a line to add it; <kbd>Shift</kbd>-click to make a phrase. |
| To see patterns | Sort by document, by the words before or by the words after. |
| The words around your search | *Words that often appear nearby*: the words within 2 to 10 words of the places found, most often or most typical first (point at one for both figures; within one document or code, "typical" is measured against that document's or code's own passages). |
| To test what a line says | Its flask button starts a check of it. |
| A list for later | Download every line for Excel or as CSV. |

Every line opens the document at its words. A *passage* is the stretch of text the app reads as one unit: a
paragraph, up to about 1,100 characters ([How documents are read](reading.md)). The place shown (page, paragraph) is
that of the original.

## Profile

<img src="../images/manual/profile.png" alt="Profile: codes by document" width="800">

Which codes of a codebook each document addresses, how much and where. The codebook is the 169 SDG targets by
default, the 17 goals, or your own CSV ([Settings → Exploring](settings.md#the-five-tabs)).

1. **Keywords first.** When documents are added, the app finds candidate codes in seconds by their keywords (and by
   meaning, with an embedding model): a *provisional* profile.
2. **The AI confirms.** *Let the AI label the passages* has the AI read each passage with a candidate code and say
   which codes really apply (main topic or mentioned; for the SDGs, whether the passage says it helps or hinders the
   aim), with a quote and a reason. Afterwards it says how many keyword codes it confirmed, did not confirm, and
   added.
3. **You decide.** In a document, the **Codes** panel shows every code with its passages, quotes, reasons or the
   words that found it (highlighted in the text). Agree, change how it applies, reject (with *Undo*), or add a code
   of your own. Your labels always count: a keyword label you agreed with or changed stays even after the AI has
   read the passage.

Count by code or by group (the SDG goals). The grid opens the passages behind each cell. *Technical details* shows
the model, its exact version (digest), the prompt and the seed, and warns when they differ from the last run.

## Concepts

A **glossary** of the terms the documents use (one or more words, found by the C-value method; running heads and page
furniture are left out), grouped into **concepts**:

- abbreviations and their long forms ("proton exchange membrane (PEM)");
- wordings close in meaning (with an embedding model);
- links the AI proposes and you accept, and links of your own.

A concept card shows how the documents write it (*Not the same* splits a wording off), which documents discuss it and
where it first appears, every line where it occurs, and related concepts (the same, broader, narrower, related,
often together). *Ask the AI for other wordings* lists wordings the documents use: add them, or say *Not the same*
and they are not proposed again.

## Themes

<img src="../images/manual/themes.png" alt="Themes: each with key terms, size and documents" width="800">

What the documents are about, grouped into themes. Each theme has key terms, a size, the documents it comes from and
the passages that represent it best; grids show themes by document and by code. The same documents and settings
always give the same themes (spherical k-means on the passages' embeddings, or on their terms without an embedding
model). A small project gets fewer themes than asked: about three passages a theme.

- **Rename, merge, move passages.** Your edits are kept, and carried to a new set with the same settings after
  documents were added: an edit follows its theme by the passages they share, and stays behind when no theme of the
  new set has them.
- *Let the AI name the themes* gives names and short descriptions, with checked quotes.
- **Remove** a theme that is not relevant to you (running headers, reference lists, a topic outside your question):
  its passages are left out of the themes, the grids and the downloads. It waits under *Removed themes* at the foot
  of the list, where *Bring it back* undoes it.
- **Remove and find a new theme** also looks for a new theme in its place, on this computer and without AI.

<details>
<summary>How <i>Remove and find a new theme</i> chooses</summary>

Among the passages that fit their own theme least well, it finds the group that sits closer to a new centre than to
the theme it is in, and moves it into a new theme named by its key terms (the themes it takes passages from keep their
names). It never takes passages that are closer to a theme you removed, so the removed theme does not come back under
another name. A new theme says which theme it replaces and where its passages come from; remove it too to find
another. Removals and new themes belong to that set of themes only.

</details>

## In a document

A document's page shows its text as the reader found it ([How documents are read](reading.md)), with panels beside
it:

| Panel | What it does |
| --- | --- |
| **Codes** | Every code with its passages ([Profile](#profile)). |
| **Key terms** | The terms that set the document apart; point at one to underline it in the text. |
| **References** | *Follow the references*: the AI reads the document three passages at a time and links "it", "they" or "the study" to the name they stand for. Select a name in the text to see every later mention. |
| **Search** | Search within the document. |
| **Reading**, **Page** | How well it was read, and the original page beside the text ([How documents are read](reading.md)). |

*Download a highlighted copy* gives the PDF with highlights for the judgements, codes, concepts or references you
choose (exact boxes with the PDF layout reader, whole lines otherwise, text recognition for scanned pages), and a note
listing any quote it could not place. Other documents come as an HTML copy.

## Quick look

*Quick look at one document* (on the Overview, *Check a hypothesis* and *Manage projects*) reads one file into a
temporary project and opens it at its key terms: search it, see its codes and references at once. A banner offers
*Keep as a project* or *Discard now*; otherwise it goes to the trash after 7 days.

## For FlexiConc and the Cross-Doc SDG Explorer

*For FlexiConc / Cross-Doc* (on the Projects page; `enlens export-flexiconc` on the command line) downloads the project
as one SQLite file in the FlexiConc layout of the Cross-Doc SDG Explorer: documents, sentences with their code,
reference chains, theme clusters and, with an embedding model, embeddings.

<details>
<summary>Where the parts of the Cross-Doc SDG Explorer went</summary>

The explore pages replace the Cross-Doc SDG Explorer, one of the two tools ENLENS grew out of.

| Cross-Doc | ENLENS |
| --- | --- |
| Single-document concordance (AND / OR), token strip | Search (any / all / phrase / near), across all documents or one |
| SDG classifier, dual consensus | Profile: keywords and meaning first, the AI confirms with a quote and a reason |
| Explainability (integrated gradients, span masking, keyphrases) | Key terms per document and passage; the words and reason behind every label |
| Coreference (fastcoref, LingMess) | References in a document (the AI follows "it" and "they"); checks say what a quote's "it" is |
| Global coreference (trie) across documents | Concepts: one concept followed across every document, with its wordings |
| SciCo clusters, communities and summaries | Themes, named by the AI with checked quotes |
| `pdf_highlight_post.py` | Highlighted copies of a document, an answer, a column of the evidence map |
| FlexiConc SQLite | *For FlexiConc / Cross-Doc* on the Projects page, `enlens export-flexiconc` |

</details>

---

Next: [How documents are read →](reading.md)
