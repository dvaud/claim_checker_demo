[Manual](../MANUAL.md) › Make your own codebook

# Make your own codebook

> **In short**
> - A codebook is your list of codes: each with a definition, when to use it and when not, the words it is matched by
>   and examples from your documents. *Codes* › *Codebooks* makes, changes and removes them.
> - Start fresh, from the themes already found, from a copy of another codebook, or from a CSV file.
> - Changing a codebook changes no result by itself: labels follow renames and merges, and wait when a code is removed.

## What a codebook is for

*Codes* › *By document* and a document's *Codes* panel look for the codes of a codebook, and a hypothesis can be
tagged with one of its codes ([Explore your documents](explore.md#codes)). The 169 SDG targets ship with ENLENS; they cannot be changed, but
you can make a copy and change that. A codebook stays a CSV file, so it still opens in a spreadsheet.

The page lists *Your codebooks* and those that ship with ENLENS. Each card says how many codes it has, where it is
kept, how many labels and checks use it and whether *By document* uses it. A codebook file that cannot be used is listed
above them, with the reason.

## Make one

1. Press *New codebook*.
2. Give it a *Title* (the *Short name*, the file's name, follows it) and choose where it is *Kept*: *With this project*,
   or *With all my projects* (every project can use it, and a change shows in each).
3. Choose how it starts, then *Create* (*Next* for themes and theory). The editor opens.

| Start | What you get |
| --- | --- |
| *Start fresh* | An empty codebook: add codes and groups yourself. |
| *From the themes* | You tick themes found in the documents; each becomes a draft code (see below). |
| *From a theory document* (0.18.1) | You tick the concepts of a theory you read the documents through; each becomes a draft code with its definition quoted from the theory (see below). |
| *A copy of a codebook* | The SDG targets, or one of yours, to change. |
| *From a CSV file* | A spreadsheet saved as CSV (see below). |

**From the themes.** Each theme you tick becomes a draft code with a short name, its description where the AI named
the theme, its key terms as *Words it is matched by* and its best passages as examples. Removed themes are left out.
When the codebook is kept with all projects, the themes of every project are offered. Find the themes first (*Themes*
in the sidebar): it takes seconds and needs no AI.

**From a theory document (0.18.1).** Choose the document (those marked as theory come first: [Theory
documents](explore.md#theory-documents)). ENLENS offers its concepts, without AI: the terms it defines ("a stock is
…", "by a reinforcing loop we mean …", "X is defined as …", "X refers to …"), its headings, and the words and short
phrases it uses often. Each comes with its definition **quoted from the theory, with its page** (the quote, then the
document's title and the page), which becomes the code's description. Terms the text defines are ticked. Under each concept, sentences from the **evidence documents** that use
its words are offered as examples, unticked: an example is kept only when you tick it, and never comes from a theory
document. So the labeller learns what a reinforcing loop looks like in your field, not in the theory's own examples.
Words set in italics are not offered (the readers do not keep slant). An AI draft of the concepts is not offered yet.

**The short names (0.16.1).** A code's name is one or two words of the theme's name when your documents allow it, as
short as an SDG goal's: "National green hydrogen strategies and markets" becomes *Hydrogen strategies*. ENLENS tries
the shortest names first and takes a longer one only when the shorter ones are too generic: when most of the passages
that use them are in other themes ("Green hydrogen" is everywhere in a hydrogen corpus). No AI is asked. Beside each
name, − and + make it less or more specific (*Strategies*, *Hydrogen strategies*, *Green hydrogen strategies*, …), and
*Shorter* and *Longer* move every ticked theme at once; the theme's full name is shown beside it. Two themes never get
the same code, and a name you gave a theme yourself is kept when it fits in 40 characters. A name marked *check it*
had no evidence either way: its words are rare in the documents, or the documents are in another language than the
theme names. You can still rename every code in the editor.

**From a CSV file.** The columns are in this table; `code` and `description` are required. A semicolon or tab may separate
the columns, and a file saved in a Windows code page (a spreadsheet saved in Hungarian, say) is read correctly.

| Column | Holds |
| --- | --- |
| `code` | The code's name |
| `description` | Its definition |
| `group`, `group_name` | A short name for its group, and the group's full name |
| `when_to_use`, `when_not_to_use` | When the code applies, and when it does not |
| `keywords` | The words it is matched by, separated by `;` |
| `examples` | Quotes from the documents, one per line |

## Change it in the editor

Codes sit in groups. Click a code to open it:

| Field | What to write |
| --- | --- |
| *Name* | Short: it is how labels and checks name the code. |
| *Definition* | What the code is about, in a sentence or two. The AI reads it when it labels. |
| *When to use it*, *When not to use it* | The boundaries, in your own words. |
| *Words it is matched by* | Words besides the definition for the keyword pass, separated by commas. |
| *Examples from the documents* | Paste words of a document exactly as they are there. Each is checked against the documents, and one that is not found is refused. |

To move a code, drag it by its grip, or use *Up* and *Down*. *Split* makes a second code from one (the first keeps its
labels); *Merge into…* sends a code's labels to another and takes the code out; *Remove* takes a code out. *Add a code*
and *Add a group* are in each group and at the foot. *Codebook settings* holds the title, what one code is called
(*code*, *theme*, *category*) and whether its codes are aims that a text can help or hinder, like the SDG targets.

Changes are kept as drafts until you press *Save*, where you can write *Why?* for the research log
([Notes, the research log and earlier versions](notes-and-log.md#the-research-log)). *Discard* throws them away. A
draft stays while you look at another page.

## Try it before you use it

*Try it* shows, without any AI, which passages and documents each code would pick by its words, so you can sharpen a
code before the AI reads anything. It warns about a code that matches nothing, and about one that matches a large part
of the documents, which is probably too broad.

## What happens to labels

An edit changes no result by itself: labels are moved, never made or deleted.

| You do | The labels |
| --- | --- |
| Rename a code, or merge two | Follow it. This holds in every other project that uses a codebook kept with all projects, when it is opened. A merge can be undone by restoring the codebook from before. |
| Remove a code | Wait under *Removed codes*, are not counted, and come back with *Bring it back*. |
| Reword a code after the AI labelled with it | Stay as they are. The code shows *earlier wording* and *Label them again*, which has the AI label only those passages again. |

*By document* shows a notice when the codebook changed since the keyword pass (*Find the codes again* takes seconds), when
codes were reworded and when removed codes' labels wait, each with *Open the codebook*.

## Where it is kept

The ⋯ menu beside the codebook has *Keep it with all my projects* and *Keep it with this project only*; for a codebook
kept with all projects, *This project's own copy (change it here only)*; and *Remove the codebook*, which asks *Why?*.
Labels made with a codebook stay when it is removed: they are results. *CSV* downloads the codebook (a cell that starts with `=`, `@` or a sign gets an apostrophe in front, so a spreadsheet
shows it and does not run it as a formula; ENLENS takes the apostrophe off again when it reads the file), and *History*
lists its earlier versions, to compare and restore ([earlier versions](notes-and-log.md#earlier-versions)).
