# The ENLENS interface: design guide

What every kind of element on ENLENS's screens means, how it looks, when to use it, which helper makes it and the one
place its look is defined. It is for anyone who changes the interface (a person or a Claude Code session), and for the
owner or a reviewer who points at a piece of a screen and asks "does this fit?".

**How to use it.** Come with one question. Find the meaning in [the language on one page](#1-the-language-on-one-page)
or the element in the contents, read its entry, compare it with the [live reference](#10-the-live-reference-and-the-checks)
(`#/design` in the running app), stop. Every element's entry has the same parts: **Means**, **Use**, **Not for**,
**Looks** (with its variants and states), **Make it** (the helper), **Lives in** (one file and section).

**The identity.** Warm paper greys, one teal accent, a sans-serif for the interface and a serif for the documents' own
words, plain UK English, light and dark as equals: a quiet instrument for reading evidence. This guide makes that
identity consistent; it does not replace it. Four invariants carry it, and a newcomer picks them up from the first
screens:

- **An edge means you can press it.** Every button has a visible edge at rest; nothing else that looks pressable does.
- **Teal words take you somewhere.** A link is teal (underlined in running text); the name of an item in a list is teal
  and opens it. Teal on a ground means *here* or *chosen*.
- **A coloured pill is a judgement of the evidence.** Green, amber, purple, red and slate pills say what the documents
  say, and nothing else is a pill or wears those colours with a circle icon.
- **The chip answers "does this use the AI?"**, and the cloud or the house says where the text goes.

Contents: [1 The language](#1-the-language-on-one-page) · [2 Checking a screen](#2-checking-a-screen) ·
[3 The identity](#3-the-identity) · [4 Elements](#4-elements) · [5 The navigation's pieces](#5-the-navigations-pieces) ·
[6 Action or place](#6-action-or-place-the-cases-the-app-meets) · [7 Writing](#7-writing-on-the-interface) ·
[8 Accessibility](#8-accessibility) · [9 Where the look lives](#9-where-the-look-lives) ·
[10 The live reference and the checks](#10-the-live-reference-and-the-checks)

---

## 1 The language on one page

One meaning, one look. If a piece of the interface means one of these things it looks like this, and nothing else
looks like this. **A piece that cannot be named from this table is a misfit.**

| The researcher should read… | It looks like… | Element |
| --- | --- | --- |
| Press me to do something | Words (often with an icon) in a box with an edge | [Button](#41-buttons) |
| The main thing to do here | The one solid teal box of the page, card or dialog | [Main button](#41-buttons) |
| This removes or deletes | Red words in a red-edged box; solid red only in the dialog that confirms it | [Danger button](#41-buttons) |
| Show or hide a panel right here | A button whose chevron turns | [Toggle](#41-buttons) |
| An action shown by its icon (close, copy, help) | An icon with no box, a tooltip with its name | [Icon button](#42-icon-buttons) |
| This takes me somewhere | Teal underlined words | [Link](#43-links) |
| The name of a thing; it opens it | Teal words, underlined when pointed at | [Title link](#43-links) |
| The one way on, done on another page | Teal underlined words in 600, an arrow after them | [Next-step link](#43-links) |
| A place in the app | An icon and a noun in the sidebar | [Sidebar entry](#51-the-sidebar) |
| I am here | Soft teal ground, teal words in 600 (in the sidebar); a teal line under the tab (in tabs) | [Sidebar entry](#51-the-sidebar), [view tab](#45-view-tabs) |
| Another view of this place | A tab on a line under the page title | [View tab](#45-view-tabs) |
| One of a few values, shown in place | Small separate boxes; the chosen one soft teal with a teal edge | [Choice](#46-choices) |
| A choice whose options need a sentence | Cards with an icon, a title and a line; the chosen one soft teal | [Option card](#47-option-cards) |
| Type or pick here | A white box with a strong edge, its label above it | [Form field](#48-form-fields) |
| Does this use the AI? | The chip icon and *Uses the AI*, *AI on request* or *No AI*, in grey | [AI mark](#44-the-ai-mark-and-the-ai-line) |
| Where my text goes, who reads it | The cloud (Claude) or the house (this computer) and one sentence | [AI line](#44-the-ai-mark-and-the-ai-line) |
| What the evidence says | A coloured pill with a circle icon: green, amber, purple, red, slate | [Judgement badge](#49-judgement-badges) |
| A fact about this item | A small grey rectangle | [Tag](#410-tags-and-counts) |
| A judgement that does not count | Its pill with no fill and a dashed edge (the one dashed edge on a pill) | [Judgement badge](#49-judgement-badges) |
| Who did it | The person icon and *You* or initials, in a tag | [Person mark](#410-tags-and-counts) |
| Two versions of one thing | Two grey boxes side by side, *Keep mine* / *Keep theirs* under them | [Comparison](#427-comparisons) |
| This needs me | Amber with the warning triangle | [Attention tag](#410-tags-and-counts), [notice](#412-notices), [status area](#52-the-status-area-and-the-last-row) |
| Something went wrong | Red with the alert circle | [Error notice](#412-notices), [toast](#415-toasts) |
| Something to know before going on | A grey box with an icon | [Notice](#412-notices) |
| Nothing here yet, and how to fill it | A dashed frame, a large icon, one step | [Empty state](#413-empty-states) |
| Just happened (saved, copied) | A short card at the bottom right with a tick | [Toast](#415-toasts) |
| Decide this now | A box over a dimmed page | [Dialog](#416-dialogs) |
| More actions for this one thing | *More* and a list in a floating box | [Menu](#417-menus) |
| More about this | A small (?) | [Help mark](#418-help-notes-and-defined-terms) |
| This word has a definition | A dotted underline | [Defined term](#418-help-notes-and-defined-terms) |
| My own working space beside the page | A panel on the right, opened by one button in the same spot on every page | [Drawer](#419-the-drawer) |
| Work under way, waiting, not running | A pulsing teal dot and a time; a clock; a pause mark in amber, always with words | [Work state](#421-progress-and-work-states) |
| More here, folded away | A grey line with a chevron before it | [Fold](#422-folds) |
| The research's own words (documents, hypotheses, concepts, themes) | The serif face | [Type](#32-type) |
| The quote the AI found | Yellow with a line under it; in an excerpt card, its grade's tint and line | [Quote](#423-quotes-and-highlights) |
| My highlight | My colour as a ground, no line | [Highlight](#423-quotes-and-highlights) |
| Words found by a search or a code | Soft teal, no line | [Search hit](#423-quotes-and-highlights) |

**Why five minutes is enough.** The whole language rests on the four invariants at the top of this guide. The AI has one
icon (the chip), where text goes has two (the cloud, the house), "needs you" has one (the triangle), "went wrong" one
(the alert circle). Nothing else carries those icons or those colours.

**A five-minute test.** Give a new user five minutes in the dev server's Demo project, then ask them to point at: the
main action of this page; something that would send text to the AI; where they are; something that needs them; what
the documents say about a hypothesis; a place to type; on an empty page, where to go next. Any hesitation is a finding,
filed against the element.

---

## 2 Checking a screen

A procedure for the owner or a reviewer; a few minutes per screen. Open the screen in the light and the dark theme and
at 390 px wide (`docs/DEVELOPING.md`, *Trying the app*), and open `#/design` beside it.

1. **Name everything.** Point at each element and name it from [section 1](#1-the-language-on-one-page). Anything
   unnamed is a misfit.
2. **Compare it with the reference.** Find the element's section on `#/design`: it has this guide's numbers and
   titles. A different corner, edge, weight, size, colour or icon is a misfit.
3. **Does it do, or go?** Pressing it changes something: it must look like a button. It moves you to another page,
   view or place on the page: it must look like a link, a tab or a sidebar entry ([section 6](#6-action-or-place-the-cases-the-app-meets)).
4. **Every colour has its meaning.** For each hue on screen, find it in [3.1](#31-colour). Green, amber, purple, red or
   slate on anything that is not a judgement (amber and red: or a needs-you or went-wrong state in its own form) is a
   misfit. Yellow anywhere but the AI's quote is a misfit.
5. **The AI is said once per thing.** The page's eyebrow carries one AI mark; a button that sends text to an AI has
   *Uses the AI* beside it (one mark for a row of such buttons); no button carries an AI-looking icon; a card that
   sends text has one AI line, at its foot ([4.4](#44-the-ai-mark-and-the-ai-line)).
6. **The words.** Buttons are verbs, places nouns, numbers say what they count, UK spelling ([section 7](#7-writing-on-the-interface)).
7. **The keyboard.** Tab through: every action is reached, the focus ring always shows, Escape closes what opened.
8. **Find the source** (two minutes in the browser's inspector). Select the piece and read its *Styles*: every rule
   that draws it comes from its component's section of `components.css` (or from `site.css`, an installation's own
   look). A rule from `views.css` that sets more than its place, or an `element.style` entry, is the misfit even when
   the piece looks right today: it is the rule that makes it look wrong after the next change to the component.

Write a finding as: *"<element> on <page> is <what it is>; the guide has <what it should be> (DESIGN.md §n)."*

---

## 3 The identity

### 3.1 Colour

Every colour is a token in `tokens.css`, set for light and dark; nothing else names a colour (`#design` shows them
all). **Who may use which colour:**

| Colour (tokens) | Means | Used by | Never for |
| --- | --- | --- | --- |
| Teal, solid (`--accent`, `--on-accent`, `--focus`) | The main action; the app at work; focus | Main button, running dot, progress bar, focus ring, the heat grid's cells | Decoration, a fact, a heading |
| Teal words (`--accent-text`, `--accent-strong`) | Takes you somewhere; chosen | Links, title links, the current entry, tab and option | A state, a fact |
| Soft teal ground (`--accent-soft`) | Here; chosen; found by words | Current sidebar entry, chosen choice and option card, the drawer's open button, search hits and a code's words | Notices, tags |
| Green (`--ok*`) | The evidence supports | Judgement badges; the quote's tint in an excerpt card that supports | Success, "set up", "local", "high certainty" |
| Amber (`--partly*`) | Partly supports | Judgement badges; the quote's tint | Warnings (those are `--attention`) |
| Purple (`--mixed*`) | Mixed evidence: some documents for, some against | Judgement badges; "some for, some against" in an answer | The AI, a second model, a disagreement |
| Red (`--bad*`) | Contradicts | Judgement badges; the quote's tint | — |
| Slate (`--none*`) | No evidence; not about the hypothesis | Judgement badges; the quote's tint | — |
| Amber with the triangle (`--attention*`) | Needs you | Attention tags and notices, the stalled work box, the AI line when no AI can run | A judgement; anything without the triangle |
| Red, through `--danger*` | Removes, deletes; went wrong | Danger buttons, error notices and toasts, field errors, a menu's delete row | A judgement |
| Greys (`--text`, `--text-2`, `--muted`, `--faint`, `--surface*`, `--border*`, `--bg*`) | Everything else | Text, facts, tags, AI marks, the AI line, work states, done notices | — |
| Yellow (`--mark`, `--mark-line`) | The quote the AI found | `mark.quote` | A search hit, a highlight, anything else |
| Highlight colours (`--hl-*`) | Your own highlights | `mark.hl-*`, their swatches, a quoted highlight's edge | Anything the app says |

Amber and red each serve a judgement and a state. They are told apart by form, always: **a judgement is a pill with a
circle-family icon; a state is never a pill and carries the triangle (needs you) or the alert circle (went wrong).**
`--attention*` and `--danger*` start as the values of `--warn*` and `--bad*`, so an installation can colour the states
apart from the judgements in its `site.css` without touching a component.

### 3.2 Type

| Style | Face, size, weight (tokens) | For |
| --- | --- | --- |
| Display | Serif, `--fs-display` (1.65rem), 400 | A page whose title is the research's own words: a hypothesis, a document, a concept (`.title-display`) |
| Title | Sans, `--fs-title` (1.55rem), 600 | A page's `h1`, the first screen's title, a big figure (the Bibliography's tiles) |
| Lead | Serif or sans, `--fs-lead` (1.2rem) | The box a hypothesis is written in, a part's claim, a theme's name, the Overview's group heads |
| Section | Sans, `--fs-section` (1.05rem), 600 | Section and card titles (`h2`, `h3`) |
| Body | Sans, `--fs-body` (15px), 400 | Interface text |
| Document text | Serif, `--fs-doc` (1rem), 400 | The documents' own words, excerpts, hypotheses in lists, the names of documents, concepts and themes |
| Small | Sans, `--fs-small` (.875rem), 400 | Small buttons, tags, AI marks, help, meta lines, tables |
| Fine | Sans, `--fs-xs` (.8rem), 400 | Times, a table's header row, key hints, a log entry's meta line |
| Group label | Sans, `--fs-label` (.72rem), 600, capitals, .04em | The sidebar's and the finder's group labels only |

Under 861 px a page's Title and Display take `--fs-title-sm` (1.35rem). **Every size is one of these tokens**: no
stylesheet writes a size in rem or px; only code and keys inside running text take a size relative to it (`.86em`).
**Two weights: 400 and 600** (`--fw-regular`, `--fw-strong`), and nothing else. **The serif is for the research's own words**: the
documents' text and titles, hypotheses, concepts and themes, your own entries in the research log; the interface never
sets its own words in serif. **Three faces from the system** (`--font-ui`, `--font-serif`, `--font-mono` for codes,
commands and times); no web fonts.

### 3.3 Space, corners, shadows, icons

| | Values (tokens) | Rule |
| --- | --- | --- |
| Space | 4, 8, 12, 16, 24, 32 px (`--space-1` … `--space-6`) | 4 between an icon and its words; 6 between small things on a line; 8 between controls in a row; 12 inside a stack; 16 card padding and between cards; 24 after a page head and between sections; 32 the page's top |
| Corners | `--radius-xs` 4 (code, keys) · `--radius-sm` 6 (tags, menu rows) · `--radius-ctl` 8 (every control, at every size) · `--radius` 10 (cards, panels) · `--radius-lg` 14 (dialogs, the drawer as a sheet) · `--radius-pill` (judgement badges, switches) | A pill is a judgement; the only other round shapes are a switch's track and a bar's (progress, a theme's size) |
| Shadows | none · `--shadow` · `--shadow-lg` | Nothing in the page's flow has a shadow: cards are flat. `--shadow`: what hangs from a trigger (help notes, the AI line's card). `--shadow-lg`: what lies over everything (menus, dialogs, toasts, the drawer over the page) |
| Icons | 12–13 px with small text · 15–16 px with body text and on buttons · 18 px sidebar entries · 20 px the large badge · 28 px empty states | Stroke icons from `icons.js` only, in `currentColor`. An icon never carries meaning alone: words beside it, or a name and a tooltip on an icon button |

**A dashed edge has one meaning: not in force, or not there yet.** A judgement that does not count (its badge), an
empty state's frame and the drop zone that waits for files, a proposed link not yet accepted (Concepts). A box that is
done or reviewed is never dashed; lines between the parts of a card are solid.

**Icons with a reserved meaning.** The circle family (`circle-check`, `circle-half`, `arrows-opposed`, `circle-x`,
`circle-dot`, `circle-dashed`, `search-x`: `STATUS_ICON` in `icons.js`) is for answers and grades only. `cpu` (the
chip) means "does this use the AI" and nothing else. `cloud` means "goes to Claude", `house` "stays on this computer".
`alert-triangle` means "needs you", `alert-circle` "went wrong", `check` "done". `user` is "reviewed by you".

### 3.4 Light and dark

Both themes are equal: every element is looked at in both before it ships. A theme differs only in token values; **no
rule outside `tokens.css` names a theme** (no `prefers-color-scheme`, no `data-theme`).

### 3.5 The tokens

`tokens.css` holds every token, light and dark. Releases add tokens and never rename or remove one; a changed value is
named in `CHANGELOG.md`. Besides the colours above: the faces (`--font-ui`, `--font-serif`, `--font-mono`), the type
scale (`--fs-*`, `--fw-*`), the spacing scale (`--space-*`), the corners (`--radius-*`), `--shadow`, `--shadow-lg`,
`--sidebar-w`, `--content-w`, `--drawer-w` (300 px, 340 px from 1,200 px wide; `--logdrawer-w` is its older name),
`--heat-4` (the darkest heat cell), `--paper` (behind a picture of a document's page), and the quote's tint in an
excerpt card by its grade (`--quote-ok`, `--quote-partly`, `--quote-bad`, `--quote-none`).

---

## 4 Elements

Each entry: **Means** · **Use** · **Not for** · **Looks** (variants and states) · **Make it** · **Lives in**. The
helpers are in `lib.js` (and `features.js` for the AI mark and the view tabs); every one is drawn on `#/design`.
Every helper takes `h()`'s attributes besides its own options (ids, `aria-*`, `on*` handlers, and a page's own class
for placement) and its children after them.

### 4.1 Buttons

**Means:** pressing it does something. **Use:** every action. **Not for:** going somewhere (a [link](#43-links)),
choosing a value shown in place (a [choice](#46-choices)).

| Kind | `button({ kind })` | Looks | Use |
| --- | --- | --- | --- |
| Main | `"main"` (`.btn-primary`) | Solid teal, white words, 600 | The one main action of a page, a card or a dialog (*Check*; *Next to review* on a result page, an arrow after its words). At most one in each |
| Standard | default (`.btn`) | The card's white, a strong edge, the text colour | Every other action |
| Quiet | `"quiet"` (`.btn-ghost`) | The same edge, no fill, secondary words | Lesser actions in rows: *Not about this*, *Say why*, *Cancel*, downloads |
| Danger | `"danger"` (`.btn-outline-danger`) | Red words, a red edge, no fill | *Remove*, *Delete*: it opens the dialog that confirms |
| Confirm | `"confirm"` (`.btn-danger`) | Solid red | Only the confirming button of a dangerous dialog (`confirmDialog()`) |

**Every button has an edge at rest** (`--border-strong`, the edge of every field), so a button never reads as words
or as a link. On a card, quiet and standard differ by their words (`--text-2` against `--text`); where a dense row needs
one action read first (*Agree*), it is standard and takes the row's first place. **One size step:** `sm: true`
(`.btn-sm`, .875rem) in rows, card feet, toolbars and the sidebar. There is no large size.

**As wide as its words.** A button takes the width its words and padding need. Where a row keeps its buttons in the
same place on every card (an excerpt's judging row), each has a `min-width` for its longest label, never a `width`: a
fixed width clips a longer label. A button that shows free text (your note on a document's AI setting, a chosen work's
title) cuts it with "…" inside its padding and says it whole in its tooltip.

**States.** Hover: a step darker, the edge stronger. Focus: the 2 px teal ring. Disabled: half opacity, and the reason
in its `title` or the line beside it. Busy (`busy: true`, `setBusy()`): disabled, `aria-busy`, the label stays and its
first icon turns. A toggle (`toggle: true`): a chevron after the words that turns with `aria-expanded`. Opens beside
(`opens: true`, the drawer's button): soft teal while what it opens is open. A button that waits for you (*Start Claude
Code* with work waiting) pulses (`.sc-nudge`), and stands still with a ring under reduced motion.

**Two actions that are not `<button>`s:** a download makes a file, so it is a small quiet button even when it is an
`<a download>` (`downloadButton()`; a row of them: `downloadLinks()`); choosing a file is an action, so the label that
holds the hidden file input is a button (`fileButton()`).

**Make it:** `button({ kind, sm, icon, busy, toggle, opens, wrap, …attrs }, …children)`, `downloadButton()`,
`fileButton()`, `setBusy()`. `dialog()` and `confirmDialog()` draw their own (*Cancel* quiet, then main or confirm).
**Lives in:** `components.css` § 4.1.

### 4.2 Icon buttons

**Means:** an action shown by its icon alone. **Use:** close, copy, the theme, a help mark, removing a word from a
search. **Not for:** an action that needs words to be understood (a button).

**Looks:** the icon (16 px) in a 32 px square, no edge, secondary colour; hover a grey ground. `sm: true`: 24 px, muted,
teal on hover, for dense rows and the help mark only (32 px on a touch screen). Its name is its `aria-label` and its
tooltip. **Make it:** `iconButton({ icon, label, sm, size, onClick })`. **Lives in:** `components.css` § 4.2.

### 4.3 Links

**Means:** takes you somewhere: another page, a view, a place on this page, a page outside the app. **Use:** every
move. **Not for:** an action, even a small one inside a sentence ([section 6](#6-action-or-place-the-cases-the-app-meets)).

| Kind | `link({ kind })` | Looks | Use |
| --- | --- | --- | --- |
| Link | default (the base `a`) | Teal words, underlined | In a sentence, a foot, a toast |
| Title link | `"title"` (`.link-title`), `serif: true` for the research's own words | Teal words in the row's face, underlined when pointed at or focused | The name of an item in a list, table, card or grid: a hypothesis, a document, a concept, a theme, a codebook. The name **is** the link: no separate *Open* |
| Back link | `"back"` (`.link-back`) | ← and the place's name, small | Above a page title (*All hypotheses*); the way out of a page whose item is gone |
| Next step | `"next"` (`.link-next`) | Teal underlined words in 600, an arrow after them | The one way on from an empty state or a notice to the page where the work is done (*Add documents on the Documents page*); it always has an address. Never beside a main button: a notice or an empty state has one step, a main button (done here) or a next-step link (done there) |
| Outside | `"external"` (`.link-external`) | Words and the outside-link icon; opens a new tab | The original file, GitHub |
| On this page | `"jump"` (`.link-jump`) | Like a link; it is a `<button>` because the place has no address | *Show it*, *Show in the text*, a place in the reading view. It only moves the view: what changes the page as it goes (*Next to review*) is a button |

**States:** hover a darker teal; the focus ring; visited looks the same. A link in a notice takes the notice's text
colour and keeps its underline. **Make it:** `link({ kind, serif, href, … }, …children)`. **Lives in:** the base `a` in
`app.css` (*Base elements*), the kinds in `components.css` § 4.3.

### 4.4 The AI mark and the AI line

**The AI mark** answers "does this use the AI?" with three values, the same words everywhere (`aiTag()`,
`features.js`):

| Value | Words | Tooltip |
| --- | --- | --- |
| `uses` | *Uses the AI* | The AI does this work: it reads the passages it needs. |
| `optional` | *AI on request* | Works without the AI; the AI adds to it only when you ask. |
| `none` | *No AI* | Never uses the AI: it runs on this computer. |

**Where it goes:** a page's eyebrow (*Check · Uses the AI*, `featureEyebrow()`); the sidebar's group labels; an
Overview card's foot; right after a button that sends text to an AI, kept with it (`.with-ai`), one mark for a row of
such buttons (*Check* and *Look before checking* · *Uses the AI*). **Looks:** the chip (12 px) and the words, grey,
.875rem, 400; no box, no colour of its own (never teal, never a judgement colour, never a pill). In a sidebar group
label it takes the label's size. **Not for:** where text goes (the AI line). A button never carries an AI-looking icon.

**The AI line** says where text goes and who reads it: the cloud (Claude) or the house (a model on this computer) and
one sentence (*Claude, on your plan, reads the excerpts it needs*). **Where it goes:** the sidebar's
[status area](#52-the-status-area-and-the-last-row), always; **once per card or section that holds AI actions, at its
foot**, never in a button's row. **Looks:** the icon (13 px) and the sentence, small, `--text-2`. When no AI can run
(no model downloaded, no key) or in Demo mode it takes the attention look: the triangle, amber, *No AI model set up
yet*. A document's AI setting is a [tag](#410-tags-and-counts) with the same icons: *Claude may read it* (cloud),
*Only a local AI* (house), *No AI* (chip).

**Make it:** `aiTag(value)`, `featureEyebrow(key)`, `aiWhere(sentence, "cloud" | "local" | "attention")`; a button
with its mark: `h("span", { class: "with-ai" }, button(…), aiTag("uses"))`. **Lives in:** `components.css` § 4.4.

### 4.5 View tabs

**Means:** other views of this place; each has its address. **Use:** a place's views (*Overview* | *Research log*,
*Documents* | *Notes* | *Bibliography*, *By document* | *Codebooks*, *Answers* | *Evidence map*), Settings' tabs, the
drawer's tabs. A place's views are reached through these tabs only, never through entries under a sidebar entry.
**Not for:** switching how the same content is shown (a [choice](#46-choices)).

**Looks:** words with a 14 px icon, secondary text, on a 1 px line; the current tab teal in 600 with a 2 px teal line on
the rule (`aria-current="page"`); hover a grey ground. No counts in tabs. **Make it:** `viewTabs(place, current)`
(`features.js`). **Lives in:** `components.css` § 4.5 (`.settings-tabs`; `.view-tabs` places them under a page head). A
tab is a link; a drawer's tabs, which have no address, are buttons with the same look.

### 4.6 Choices

**Means:** one of a few values, shown in place; the content below follows it. **Use:** *Cards* | *Table*, a filter of
a list (*All 3* | *Supported 1*), *This page* | *All* in the drawer, the speed of Claude Code, which panel a document's
side shows. **Not for:** views with an address (tabs), options that need a sentence each (option cards), on and off
(a switch).

**Looks:** separate small boxes (8 px corners, 6 px apart, a strong edge, small type); the chosen one soft teal with a
teal edge and teal words in 600. A filter shows after its words the number of rows it would show. The chosen state is an
attribute, never a class: `aria-checked` in a radio group, `aria-pressed` for a filter. Arrow keys move between the
options; in a radio group they also pick, so a choice whose pick saves or loads something at once (your judgement of an
excerpt, one document of a search, a document's side panel) is a filter: the arrows only move. `sm: true` for a tight
place (24 px high at least). A set of buttons that each mark themselves pressed is a choice, never quiet buttons with
`aria-pressed`: nothing else draws the chosen state. **Make it:** `choice({ label, options: [[value, words, count]], value, onPick,
filter, sm })`; its `.set(value)` changes the chosen one. **Lives in:** `components.css` § 4.6 (`.seg`, `.seg-btn`).

### 4.7 Option cards

**Means:** a choice whose options each need a sentence. **Use:** which AI reads the documents, who may read a
document, how to start a codebook, which note to use. **Looks:** cards in a grid: an icon, a title in 600, one line,
optionally a tag at the head's right (*Recommended*) and a quiet foot line (where text goes); the chosen card soft teal
with a 2 px teal edge. **Make it:** `optionCards({ label, options: [{ value, icon, title, text, tag, foot }], value,
onPick })`; with `name`, the cards are labels holding real radio inputs of that name (a form's question). Its `.set(value)`
chooses one without calling `onPick`. **Lives in:** `components.css` § 4.7.

### 4.8 Form fields

**Means:** type or pick here. **Looks:** the card's white, a strong edge, 8 px corners; the label above (600), help
under it (muted, small); the placeholder muted and never the label's only copy.

| Field | Make it | Note |
| --- | --- | --- |
| Text | `field(label, input({ … }), { help })` | `mono: true` for a code or a command |
| Multi-line | `textarea({ … })` | |
| A hypothesis | `textarea({ hyp: true })` | Serif, 1.25rem: the researcher writes a claim about the documents; smaller when it holds a list |
| Select | `select({ … }, …options)` | The system's own list |
| Search | `searchField({ placeholder })` | The magnifier inside the field |
| Check box | the system's check box, its label after it | |
| Switch | `switchControl(label, on, { help })` | On or off, applied at once |
| Range | `rangeControl(label, { min, max, step, value, format, ends })` | Strictness |

`sm: true` on `input()` or `select()` is a small field in a row of controls (*Find* · *any of the words*): as wide as
its content, never wider than its place, so a long option cannot push a page sideways.

**States.** Focus: the edge and a 2 px ring turn teal. Disabled: a grey ground, muted words, the lighter edge, and the
reason in the help line. Error: `aria-invalid="true"` (a red edge) and a red line under it (`.field-error`).
**Lives in:** `components.css` § 4.8.

### 4.9 Judgement badges

**Means:** what the evidence says: an answer (*Supported*, *Partly supported*, *Mixed evidence*, *Contradicted*, *Only
uncertain evidence*, *No evidence found*, *Nothing matched*) or the grade of one excerpt (*Supports*, *Partly
supports*, *Contradicts*, *Not about this hypothesis*). **Use:** answers and grades only. **Not for:** facts, states of
work, settings, AI use.

**Looks:** a pill (the only pills in the app) in the judgement's soft colour, its words in the strong colour, 600, a
circle-family icon (`STATUS_ICON`). *Only uncertain evidence* is grey, so amber keeps one meaning. The large size for
the answer of a result page. Not counted: no fill, a dashed edge in its colour. *Not finished*, *Did not work* and
*Waiting for Claude Code* are states of work and are drawn as [work states](#421-progress-and-work-states).
**Make it:** `statusBadge(status, { size, short, text })`, `gradeBadge(verdict, weak)`. **Lives in:**
`components.css` § 4.9.

### 4.10 Tags and counts

**Means:** a fact about an item: a code, a kind, *new*, who reviewed it, how certain, a document's AI setting.
**Looks:** a small grey rectangle (6 px corners, `--surface-3`, secondary words, .875rem, 400), an optional 12 px icon.
Kinds: a code (its code in 600, `codeChip()`); a count (tabular figures); **attention** (amber ground, amber words, the
triangle): a fact that needs you (*very short: is this the whole text?*, *the second model differs*). **A person mark** says who did something: the
person icon and *You* or a colleague's initials (the users icon and each, for several people), and a role when it
matters (*Owner*, *Collaborator*); the full names are its tooltip and its name. Its first use is *Reviewed* beside an
answer (`reviewedMark()`): *You*, and *You · partly* while only part is reviewed. **A sharing state** is a tag with its
icon: *Private* (the house), *Shared* (the users icon), *Withdrawn* (undo), `shareState()`. **A document not on this
computer** (a colleague's work names it): its title as plain serif words (there is nothing to open), the tag *not on this
computer* (`file-x`) and the small quiet button *Add its file*, `absentDocument(title, { onAdd })`. A tag that explains itself on hover or click is a tag
on a button (*at first: partly supported*, `strongerMark()`). **Not for:** judgements (badges), actions (buttons), AI
use (the AI mark), links. A tag is never pressed to do something.

**Counts.** A number always says what it counts: *3 documents*, *2 of 6 excerpts read*, a count tag beside a name
(*Mostly from* · a document · *4 passages*). A bare number is allowed only as a filter's count in a
[choice](#46-choices), in a table cell under a header that names the unit, and on a main button that counts what you
just typed (*Check 3*, under three lines). Never beside a sidebar entry.

**Make it:** `tag({ kind: "neutral" | "code" | "attention" | "count", icon }, …)`, `codeChip()`, `personMark(people,
{ role, note })`, `reviewedMark(people, partly)`, `severityTag(level)`, `shareState(state)`, `absentDocument(title, {
onAdd })`, `strongerMark()`. **Lives in:** `components.css` § 4.10.

### 4.11 Cards

**Means:** one thing, or one task, held together. **Looks:** the card's white, a 1 px edge, 10 px corners, 18 × 20 px
padding, flat. Its head: a Section title and at most a help mark and one action. **At most two levels of boxes:** a card
may hold one box (`--surface-2`, no edge, or an edge and no fill), never a card. A card that holds AI actions ends with
its AI line. Two variants: **the small card** (`sm: true`, 10 × 12 px padding, 8 px corners), one of many in a list
(a note); **the card that folds** (`as: "details"`, its first child the `<summary>`): its summary is the title line in
600 with the fold's chevron (*Codebook settings*, *3 removed codes*). Where a page's content lies on the page (a result's
evidence, whose excerpt cards are the cards), it is not put in a card. A page's link card (the Overview's) is a page's
own piece built on the same look: the whole card is its link, the edge teal when pointed at. **Make it:** `card({ as,
title, help, action, sm, class }, …body)`. **Lives in:**
`components.css` § 4.11.

### 4.12 Notices

**Means:** something to know before going on; it stays while it is true. **Use:** above what it concerns, at most one
per card.

| Kind | `notice({ kind })` | Looks | Use |
| --- | --- | --- | --- |
| Info | `"info"` | A grey box, the info icon | A fact to keep in mind; a step on another page |
| Done | `"done"` | The same, with a tick | A state the page is about that stays true: *Ollama is installed and running* |
| Attention | `"attention"` | Amber ground and edge, the triangle | Needs you before you go on |
| Error | `"error"` | Red ground and edge, the alert circle | Did not work |

None is green: green is *supported*; none is teal: teal is *here*. A notice may hold one action (a small button) or one
link (a next-step link to the page where the work is done) after its words. Another icon may replace the kind's own
(the cloud, the inbox, the pause) when it says more. A list of problems (one per colleague, or one per kind) is notices
one under the other, each with its own plain message: `noticeList([{ kind, person, text, action }])`. **Make it:**
`notice({ kind, icon }, …children)`, `noticeList(items)`; `addDocumentsFirst(what)` is the notice of a project with no
documents. **Lives in:** `components.css` § 4.12.

### 4.13 Empty states

**Means:** nothing here yet, and the one step that fills it. **Looks:** a dashed frame, a 28 px icon, a title, one or
two sentences, then the step: one main button when the work is done here, or one next-step link when it is done on
another page (*Check a hypothesis*). **Make it:** `emptyState(icon, title, text, step)`. **Lives in:**
`components.css` § 4.13.

### 4.14 Page heads

**Means:** where you are and what the page is for. **Looks:** the eyebrow (the section and the AI mark, small, muted),
the Title, one line under it (at most 46em), then the view tabs. At the right, only actions, never a link: the page's
main action (at most one, often none), and on a page that is one thing (a codebook) its few lesser actions as small
buttons, the rest in a *More* [menu](#417-menus); downloads as small quiet buttons (*Download all:* · *Excel (.xlsx)* ·
*CSV*). A way to another page is a link in the line under the title (*Add more on the Documents page*). A result page's title is its hypothesis in the Display serif,
with a back link in place of the eyebrow. **Make it:** `pageHead(title, { eyebrow: featureEyebrow(key), sub, actions
})`. **Lives in:** `components.css` § 4.14.

### 4.15 Toasts

**Means:** something just happened: saved, copied, could not be done. **Looks:** bottom right, the card's white, the
large shadow, an icon in its meaning's colour (a teal tick for done, the triangle, the red alert circle), a close icon
button; at most one link or one small button. An error toast stays 15 s and keeps the technical message behind
*Technical details*. The note of what is new after an update is a quieter toast that waits to be closed. **Not for:**
anything to act on later (a notice) or not to miss (a dialog). **Make it:** `toast(message, kind, { action, button,
detail })`, `showError(e)`. **Lives in:** `components.css` § 4.15.

### 4.16 Dialogs

**Means:** decide this now, before anything else. **Use:** confirming a removal, a short form, a choice that needs a
moment. **Looks:** the native `<dialog>`, 14 px corners, the large shadow, a dimmed page; the title and a close icon
button, the body, the actions at the bottom right: *Cancel* quiet, then the main button (the confirm kind when it
removes). Escape and a click outside close it, except while its work runs (`lock`). **Make it:** `dialog({ title, body,
actions, danger, lock })`, `confirmDialog({ title, message, confirmText, typeToConfirm })`. **Lives in:**
`components.css` § 4.16.

### 4.17 Menus

**Means:** more actions for one thing, or a list to pick from (the projects). **Looks:** a floating box under its button
(the card's white, an edge, 8 px corners, the large shadow); rows of a 14 px icon and a verb; the current row soft teal;
a dangerous row in red, last, after a line. Its button is a small quiet button: *More* with the more icon, or the current
value and a chevron (the project switch). Escape, a choice or a click outside closes it. **Make it:** `menu({ items:
[{ text, icon, onClick, danger, current }, "sep"], text })`. **Lives in:** `components.css` § 4.17.

**No popover panels for running work.** Work shows in the fixed [status area](#52-the-status-area-and-the-last-row);
the queue's controls live in Settings (*Work waiting for Claude Code*). Popovers hold explanations and short menus only.

### 4.18 Help notes and defined terms

**Means:** "more about this" (a help mark) and "this word has a definition" (a defined term). **Looks:** the help mark
is a 24 px icon button with the (?) (muted, teal when pointed at); a defined term has a dotted underline and the help
cursor. Both open the same note on hover, focus or click: a small card under the trigger (8 px corners, a strong edge,
`--shadow`, at most 34em). **Make it:** `helpMark(label, text)`; `popNote(trigger, text)` on an
`h("button", { class: "defined" }, word)`. **Lives in:** `components.css` § 4.18.

### 4.19 The drawer

**Means:** your own working space beside any page: the research log now, and in 0.18 working together. **Looks:** a
panel on the right, `--drawer-w` wide, the card's white, an edge on its left. From 1,000 px wide (at any zoom) it is a
column of its own, flush right, and the page keeps its margin beside it; from 861 to 999 px it lies over the page's
right side with the large shadow; under 861 px it rises from the bottom as a sheet, 72 % of the window high. Head: an
icon and the title (or the tabs, when there are two or more), at most one control (a [choice](#46-choices)), the close
icon button. Body: sections divided by a line, each drawn by its content's own components; the last one scrolls. Foot:
one link to the whole view. **Its button** is a small standard button with the *opens* state, always at the top right of
every page (in the top bar under 861 px, its words then its name only); open, the body carries
`data-drawer="open"`.

**The research log in it is the Research log page's own write box and entries** (`.log-new`, `.log-entries`): one
entry looks the same on the page and in the drawer.

**Adding a tab or a section.** A section is one more element in `sections` (or in the drawer's own
`.setSections([…])` when it redraws). A second tab (0.18's *Team*) is a `tabs` list: `drawer({ tabs: [{ key: "log", label: "Research log", icon:
"notebook" }, { key: "team", label: "Team", icon: "users" }], current, onTab })`; the head then shows the tabs in the
view tabs' look, and `onTab(key)` draws that tab's sections with `.setSections([…])`. Nothing else changes: the button,
the widths and the open state are the drawer's.

**Make it:** `drawer({ id, title, icon, tabs, current, onTab, control, sections, foot, onClose })`,
`drawerButton({ id, controls, label, icon, onClick })`, `setDrawerOpen(open, button)`; `views/logdrawer.js` is its
first content. **Lives in:** `components.css` § 4.19.

### 4.20 Tables, lists and dense places

**Looks:** a table in its frame (`.table-wrap`: the card's white, an edge, 10 px corners); the header row small, muted,
600; rows divided by lines; numbers right-aligned in tabular figures; under 861 px the rows of `.table-responsive` stack
with their labels (`data-label`). Lists of entries (the research log, notes, answers) keep the same rhythm.

**Dense places** (the answers, excerpt cards, the codebook editor, the reading view, tables) keep their actions
recognisable this way:

1. The item's name is its [title link](#43-links); no *Open*.
2. Row actions are small quiet buttons at the row's end, in the same place on every row; more than two go into a menu.
3. The one action that matters most in a row (*Agree*) is small standard in the first place.
4. A panel opens under the row that opened it, by a toggle; the row does not move.
5. The smallest control is 24 × 24 px (the small icon button), 32 px on a touch screen.
6. Running and waiting items sit at the top of a list of answers, with their work state instead of a badge.
7. An AI action in a row keeps its mark beside it; the card says its AI line once, at its foot.

**Lists of rows** (in the drawer and on pages): who (a person mark), the item's name as its title link, under it at most
one quiet second line (a colleague's ENLENS version; it becomes an attention tag only when it needs you), when, and one
or two small actions at the row's end; grouped under a small heading by person or by day. The research log's entries
are such rows: an entry ENLENS wrote is itself the title link to its item; your own entry keeps your words in serif and
names its item after *About:*.

**Make it:** `h("div", { class: "table-wrap" }, h("table", { class: "table table-responsive" }, …))`;
`listGroup(heading, …listRow({ person, title, href, time, sub, warn, actions }))`; `drawInSteps()` for a long list.
**Lives in:** `components.css` § 4.20.

### 4.21 Progress and work states

| State | Looks | Words |
| --- | --- | --- |
| Running | the pulsing teal dot, a time in tabular figures | *Checking · 41 s* |
| Waiting its turn | a clock, grey | *Waiting its turn* |
| Queued | a clock, grey, and a small quiet *Cancel* after it | *Queued: starts when Read the documents has finished* |
| Not running (nothing answers it) | a pause mark, amber | *Not running*, *Not finished*, *Offline* |
| Needs you | the triangle, amber | *The shared folder cannot be reached* |
| Done | a tick | *Done*, *Synced 3 minutes ago* |
| Did not work | the alert circle, red | *Did not work* |
| A button at work | its loader turns, its words stay ([4.1](#41-buttons)) | the verb stays |
| A long step-by-step job | the progress panel: steps with icons and times, a bar | step names |
| Loading a part of a page | the turning loader and a sentence | *Loading the works…* |

A work state is words and an icon, never a pill. The running dot stands still under reduced motion. **Make it:**
`workState(state, words, seconds)`, `spinner(label)`, the progress panel (`views/progress.js`). **Lives in:**
`components.css` § 4.21.

### 4.22 Folds

**Means:** more here, folded away (*More options*, *What happens when you check*, *Technical details*). **Looks:** a line
in secondary text with a chevron before it that turns when open; the small kind (`sm: true`, small type) in dense places:
a card's foot, a list's tail, a toast, a notice. **Not for:** a step the researcher needs (it would be missed), or a
panel tied to one item in a dense row (a toggle button). **Make it:** `fold({ open, sm, class }, summary, …body)`. **Lives in:** `components.css` § 4.22.

### 4.23 Quotes and highlights

Three meanings in the documents' own words, three looks that never swap:

| Mark | Means | Looks |
| --- | --- | --- |
| `mark.quote` | The exact quote the AI found | Yellow with a 2 px line under it. **In an excerpt card** it takes its grade's tint and its line the grade's colour (`--quote-*`), so the badge and the quote say the same; still a ground with a line |
| `mark.hl.hl-*` | Your own highlight, in the colour you chose | Its colour as a ground only, no line; a highlight with a note has a small ✎ after it |
| `mark.dv-hit`, `mark.dv-code-mark`, the concordance's hit | Where your search words, or a code's words, are | Soft teal, no line; the current one ringed in the focus colour |
| `mark.dv-ref` | The places that name the same thing (*it*, *the plant*) | A plain grey ground; the named mention in 600 |

**Make it:** `passageNode(text, start, end)` marks the quote; the reading view (`views/sources.js`) draws highlights and
hits. **Lives in:** `components.css` § 4.23.

### 4.24 Concordance lines

**Means:** every place some words occur, one line each, the words centred (Search, a concept's lines, a document's
Search panel). **Looks:** a table in a frame; the words before and after in grey serif, cut with "…"; the words found in
600 on soft teal (other words searched for in a lighter tint); the line's document as a title link (two lines at most);
a line's own action a small quiet button at its end. **Lives in:** `components.css` § 4.24.

### 4.25 The heat grid

**Means:** how much each document addresses each code (Codes by document), theme (Themes) or hypothesis (the Evidence
map). **Looks:** a grid in a frame whose first column (the row's name, a title link) stays while it scrolls sideways; a
cell is shaded in the teal by its level (`heat-l1` … `heat-l4`, on a log scale) and is a button when it has passages; an
evidence-map cell holds the judgements as small symbols in their own colours. **Make it:** `heatCell(n, max, label,
prefix, onClick)`. **Lives in:** `components.css` § 4.25.

### 4.26 Excerpt cards

**Means:** one excerpt the AI read for a hypothesis (the result page). **Looks:** a card (8 px corners): its grade
badge and facts at the top, the document and the place in small text, the passage in serif grey with the AI's quote in
its grade's tint and line; then the row of actions: *Agree* (small standard) first, then small quiet buttons, the
toggles *Judge differently…*, *In context* and *Details* last (their panels open under the row, which never moves). A
judgement that does not count shows its badge without fill and with a dashed edge, then *Not counted*. A reviewed card sits
back (no fill: the page's ground shows through its solid edge), and says who judged it with the person icon, so the ones
still to review stand out. The other judgements, in *Judge differently…*, are a [choice](#46-choices) (filter form). **Lives in:** `components.css` § 4.26.

### 4.27 Comparisons

**Means:** two versions of one thing side by side (yours and a colleague's; before and after), to choose between.
**Looks:** two columns of the same width, each a grey box headed by who and when (a person mark and a time), the
content in its own face; the actions under both: *Keep mine*, *Keep theirs* (small standard buttons), *Keep both*
(small quiet). Under 861 px one above the other. **Not for:** a list of what changed in one version (a table, as on
*Earlier versions*). **Make it:** `compare({ left: { title, meta, body }, right: { … }, actions })`. **Lives in:**
`components.css` § 4.27.

---

## 5 The navigation's pieces

The map of places (seven, and what each holds) is the navigation's own decision; these are the pieces it is built from.

### 5.1 The sidebar

| Piece | Means | Looks |
| --- | --- | --- |
| Brand | Home | The logo and *ENLENS* |
| Project switch | Which project | A field-like box with *Project* and its name, a chevron; a [menu](#417-menus) of projects |
| Find button | Find a page, view or setting | [5.3](#53-find) |
| Entry | A place | An 18 px icon and the place's name, secondary text; hover a grey ground; **current**: soft teal ground, teal words in 600 |
| Group label | A section of places, and its AI use | Small capitals (`--fs-label`) and the AI mark in the same size; not a link |

**No counts beside entries, no AI marks on entries, no entries under an entry.** When the window is short only the list
of places scrolls; the brand, the project, Find and the foot stay. **Lives in:** `components.css` § 5.1.

### 5.2 The status area and the last row

**The status area has one fixed size** (66 px; 58 px in a window under 760 px high): normally the AI line's card;
while work runs or waits, the work box in exactly that space. Never a popover.

| State | Looks |
| --- | --- |
| The AI line | the cloud or the house, the AI's name (*Claude, on your plan*), what leaves the computer; on hover or focus a card of details opens upwards (the account, the model, where to change it) |
| Set-up not finished, no AI model yet, Demo mode | the same card in the attention look: the triangle, amber |
| Work running | a teal edge; the running dot, what runs, the time; under it how many more, and the AI's name with its icon |
| Work not running or waiting | amber: a pause mark, *Not running*, *N tasks wait for Claude*; one action, *Start* (a small main button) |

The box's words are the link to where the work shows; its one button is always an action. **The last row:**
*Settings* (an entry), then *Quit* (a small quiet button) or, when an update waits, *Update* in its place (a small main
button), then the theme's icon button. **Lives in:** `components.css` § 5.2.

### 5.3 Find

**Means:** find a page, a view or a setting by its words, never with the AI. **The Find button** sits under the project
switch and looks like the search field it opens: an edge, the search icon, muted *Find a feature or page*, the key hint
(*⌘K* or *Ctrl K*). **The finder** is a dialog near the top: the field, then rows grouped under small capitals, each an
icon, the name and where it lives; the chosen row soft teal (`aria-selected`); arrows and Enter; last, *Search the
documents for "…"*. On the Overview the same field sits under the tabs. **Make it:** `finder.js`. **Lives in:**
`components.css` § 5.3.

### 5.4 The Hypotheses composer and answers

One box (`textarea({ hyp: true })`, one hypothesis per line); under it, the hint and *Load a spreadsheet (CSV) or text
file* (a file button); then *Check* (main, counting the lines: *Check 3*) and *Look before checking* (standard) with one
*Uses the AI* after them; one AI line under them. Then the answers: running and waiting checks first with their work
state, then each hypothesis as a title link with its judgement badge; the *Evidence map* is a view tab. The page's
arrangement is the Hypotheses block of `views.css`.

### 5.5 The pieces of working together

Working together (0.18) is built from the elements above; none needs a look of its own.

| Piece | Is | Make it |
| --- | --- | --- |
| Who did it, a role | a [person mark](#410-tags-and-counts) | `personMark(people, { role })` |
| An item's sharing state: *Private*, *Shared*, *Withdrawn* | a [tag](#410-tags-and-counts) (the house, the users icon, the undo icon) | `shareState(state)` |
| A document this copy does not hold | its title in plain serif, the tag *not on this computer*, the small quiet button *Add its file*, wherever a document title shows | `absentDocument(title, { onAdd })` |
| *Share*, *Unshare* | small buttons (*Unshare* quiet); for many rows, check boxes and a row of small buttons above the list | `button()` |
| The sync state: synced, syncing, offline, the folder not reachable, a copy that needs a newer ENLENS | a [work state](#421-progress-and-work-states) (done, running, not running, needs you), in the drawer's head and, small, in the status area | `workState()` |
| Setting up the shared folder | a [card](#411-cards): a field with a mono path and *Browse…* (a small button), a done or attention notice for the check, who else is there (list rows), a switch with its two or three sentences, the main action, and one line of where text goes with the folder icon | `card()`, `field()`, `notice()`, `switchControl()`, `aiWhere(sentence, "folder")` |
| A switch with a long explanation (*Keep documents marked Only a local AI or No AI out of the shared folder*) | a [switch](#48-form-fields) whose help line holds the two or three sentences of what it does and does not do; the same in the set-up card and in Settings | `switchControl(label, on, { help })` |
| Rows in the drawer, a person row | [list rows](#420-tables-lists-and-dense-places): a person mark, the item as a title link, a time, one or two small quiet buttons; a quiet second line (a colleague's ENLENS version) that becomes an attention tag only when it matters; grouped by person or day | `listGroup()`, `listRow({ sub, warn })` |
| Problems with the shared folder | [notices](#412-notices) one under the other, one per colleague or per kind, each in plain words: *The shared folder cannot be reached* (attention), *Still arriving: try again in a few minutes* (info), *The last round did not finish* (error, *Try again*), *Anna's copy needs a newer ENLENS* (attention). The single sync state stays a work state in the drawer's head | `noticeList()` |
| A proposed change | a [card](#411-cards) with a severity tag in its head (*Low*, *Medium*: neutral; *High*: attention; never a judgement colour), *Accept* (main) and *Decline* (quiet); for the other person a work state (*Waiting for the owner*) or the reason (*Declined: …*) | `card()`, `severityTag()`, `workState("waiting", …)` |
| Two versions of one item | a [comparison](#427-comparisons) | `compare()` |
| Queued work | a work state, *Queued: starts when … has finished*, with a small quiet *Cancel*; in a toast, the same words and the button | `workState("waiting", …)`, `toast(…, { button })` |
| A report, a warning before an action, a refusal | [notices](#412-notices): done with a small fold of details; attention; error | `notice()`, `fold({ sm: true })` |
| Two downloads for two audiences | two small quiet download buttons whose words say who each is for (*For your colleagues*, *To move to another computer*) | `downloadLinks()` |

A second tab in the drawer (*Team*) is added as [4.19](#419-the-drawer) says.

---

## 6 Action or place: the cases the app meets

The rule: **does it change something, or move you?** Changing is a button; moving is a link, a tab or a sidebar entry.

| Case | It… | Is |
| --- | --- | --- |
| *In context*, *Details*, *Judge differently…* on an excerpt card | opens a panel here | small quiet toggle buttons (a chevron after the words) |
| *Next to review* on a result page, *Review the 3 excerpts judged not about it* | steps through the excerpts still to judge: each press goes to another, switches the evidence to cards and opens a fold when it must | buttons: the page's main button, an arrow after its words; the second a small standard button |
| *Say why*, *Edit*, *Undo*, *Forget this sentence* | act | small quiet buttons after their sentence |
| *Remove*, *Delete this result* | remove | small danger buttons (a dialog confirms) |
| *Show it*, *Show in the text* | move the view to a place on this page | links (`kind: "jump"`) |
| A document's, hypothesis', concept's or theme's name in a list | opens it | its title link; no separate *Open* |
| A download (*Excel (.xlsx)*, *Download a highlighted copy*) | makes a file | small quiet buttons with the download icon |
| *Load a spreadsheet* | opens the file chooser | a file button |
| An empty state or notice whose work is on another page (*Add documents*, *Check a hypothesis*) | moves | a next-step link that names the place |
| Setup's last step | moves to Documents | a next-step link (*Add documents on the Documents page*), with *Skip for now* as a plain link |
| The way back to a list (*All hypotheses*, *All codebooks*) | moves | a back link |
| *Report a problem (on GitHub)*, *Open the original* | opens outside the app | an outside link |
| The (?) beside a phrase | opens a note | a help mark (a small icon button) |
| A heat cell with passages | opens the passages | a button the size of the cell |
| The work box in the sidebar | goes to where the work shows | its words are the link; its one button (*Start*) acts |

**Small actions inside text.** An action never sits inside a running sentence: the sentence ends, and the action follows
as a small quiet button. A link may sit inside a sentence.

---

## 7 Writing on the interface

| Rule | Example | Not |
| --- | --- | --- |
| A button says what happens, as a verb | *Check*, *Add to the log*, *Remove* | *OK*, *Submit*, *Go* |
| A place is a noun | *Hypotheses*, *Research log* | *Check a hypothesis* as a place |
| A link says where it goes | *Change it in Settings › AI*, *The whole research log* | *here*, *more* |
| Numbers say what they count | *3 documents*, *2 of 6 excerpts read* | a bare *3* ([4.10](#410-tags-and-counts)) |
| Plain words, UK spelling, sentence case | *colour*, *organise*, *Find a feature or page* | jargon outside Settings › Technical |
| One word for one thing | *excerpt* for what the AI reads; *document*; *hypothesis* | *passage* and *snippet* for the same |
| States in fixed words | *Not running*, *Waiting its turn*, *AI on request* | other words per page |
| Times in the app's own helpers | a duration as `fmt.secs()` writes it (*4.0 s*, *41 s*, *1 min 05 s*); a date as `fmt.date()` (*4 Nov 2026, 19:36*) | *0:41*, *41s* |

**A label is part of the design.** The manual quotes labels exactly, in italics, so a changed label is a changed manual
page: search `docs/manual` for the old words in the same commit.

---

## 8 Accessibility

Part of every element above; these are the rules that cut across them.

| Rule | Value |
| --- | --- |
| Text contrast | 4.5:1 for all text, in both themes (`--muted` on every ground included) |
| Focus | a 2 px teal ring, offset 2, on every control; never removed from a control (page titles take focus without a ring: they are not controls) |
| Hit areas | 24 × 24 px at least; 32 px for small icon buttons on a touch screen |
| Keyboard | every action by Tab; choices and finder rows by arrows; Escape closes dialogs, notes, menus and the drawer; Ctrl/⌘ K opens Find |
| Never colour alone | every judgement has its icon and words; every state its icon and words |
| Names | an icon button has an `aria-label`; the AI mark's tooltip says the long form; toasts and the status area are live regions |
| Disabled | a disabled control looks disabled and says why nearby |
| Reduced motion | animations shortened; the running dot and the nudge stand still; the drawer appears without sliding |
| Narrow and zoomed | every page at 390 px wide; the drawer a column from 1,000 px at 80–125 % zoom |
| Dark | each element looked at in dark as in light |

---

## 9 Where the look lives

### 9.1 The stylesheets

| File | Holds |
| --- | --- |
| `tokens.css` | Every token, light and dark; the only file that names a theme |
| `app.css` | Base elements (`body`, headings, `a`, `code`), the shell (the sidebar's column, the page, the top bar), layout utilities (`.stack`, `.row`, `.grow`, `.btn-row`, `.muted`, `.small`, `.serif`…), motion and print |
| `components.css` | Every component, one section each, numbered and named as in this guide (`/* ==== 4.1 Buttons */`) |
| `views.css` | Each page's own pieces and their arrangement, one block per page (`/* ==== A result */`) |
| `site.css` | An installation's or a fork's own look: loaded last, after `<!-- release stylesheets end -->`; ENLENS never edits it |

### 9.2 The rules

1. **A component's look is defined in one section of `components.css`.** Every variant, size and state is there; a new
   variant is added to its component's section and named in this guide in the same commit, never beside it.
2. **Pages place, components look.** In `views.css` a component's class may get only where it sits (display, position,
   margins, sizes, grid and flex placement, order, overflow), never its colour, face, edge, padding, corners or shadow.
   A page's own pieces (the concordance's columns, a result's answer) are styled in the page's block under the page's
   own class names; a piece that a second page needs moves into `components.css` as a component.
3. **No inline styles but computed ones.** `style: {…}` in JavaScript only for values computed at run time (a bar's
   width, a note's shift); a page's spacing is a class of its block in `views.css`; never a colour, face, edge, padding
   or corner.
4. **Pages use the helpers.** A page names what it wants (`button(…)`, `tag(…)`, `notice(…)`) and never spells a
   component's classes; the helpers take their classes from one table, `UI` in `lib.js`.
5. **Colours are tokens**, and only `tokens.css` sets a token or names a theme.
6. **A class names one thing.** A state is an attribute (`aria-current`, `aria-checked`, `aria-pressed`,
   `aria-expanded`, `aria-selected`, `aria-busy`, or a `data-` attribute such as `body[data-drawer="open"]`), never a
   class that is also a component's name.

Then "change button type A once and every type-A button changes" holds: type A is one selector in § 4.1, and nothing
else may reach it.

### 9.3 The helpers

| Element | Helper (`lib.js` unless named) |
| --- | --- |
| Button, download, file chooser, icon button | `button()`, `setBusy()`, `downloadButton()`, `downloadLinks()`, `fileButton()`, `iconButton()` |
| Link (all kinds) | `link()` |
| AI mark, eyebrow, AI line | `aiTag()`, `featureEyebrow()` (`features.js`), `aiWhere()` |
| View tabs, choice, option cards | `viewTabs()` (`features.js`), `choice()`, `optionCards()` |
| Judgement badge, tag, person mark | `statusBadge()`, `gradeBadge()`, `tag()`, `codeChip()`, `personMark()`, `reviewedMark()`, `severityTag()`, `shareState()`, `absentDocument()`, `strongerMark()` |
| Comparison | `compare()` |
| Card, notice, empty state, page head | `card()`, `notice()`, `noticeList()`, `addDocumentsFirst()`, `emptyState()`, `pageHead()` |
| Toast, dialog, menu, help | `toast()`, `showError()`, `dialog()`, `confirmDialog()`, `menu()`, `helpMark()`, `popNote()` |
| Fields | `field()`, `input()`, `select()`, `textarea()`, `searchField()`, `switchControl()`, `rangeControl()` |
| Drawer | `drawer()`, `drawerButton()`, `setDrawerOpen()` |
| Lists, grids, work | `listRow()`, `listGroup()`, `drawInSteps()`, `heatCell()`, `workState()`, `spinner()`, `fold()` |

### 9.4 The promise to forks and add-ons

- **Tokens:** never renamed or removed; additions only; a changed value is named in `CHANGELOG.md`. A fork re-colours
  the app in its `site.css` by setting tokens, light and dark (`docs/EXTENDING.md`).
- **`site.css`** is loaded last and never edited by ENLENS.
- **Add-ons build with the same helpers** (`import { button, card, notice } from "/static/lib.js"`), so their pages look
  native and follow every change of a component.
- **Classes:** a component keeps its class name; a class goes only when looks merge, and every removed class is named in
  `CHANGELOG.md`.

---

## 10 The live reference and the checks

**The live reference** is the page `#/design` of the running app (`views/design.js`): every element drawn by the helper
the pages use, with its kinds and states, the colour tokens and the type scale. It cannot show a look the app does not
have: change a component or its helper and the page changes. It loads `site.css` like every page, so an installation
sees its own look. It is not in the sidebar or in Find: type the address. Look at it in both themes (the theme button
at the sidebar's foot) and at 390 px.

**It is laid out as this guide is:** one section per section here, under the same number and title and in the same
order (3.1 to 3.3, 4.1 to 4.27, 5.1 to 5.5), with the list of them at its top. With the guide open at 4.12, look at 4.12
there. The navigation's pieces (5.1 to 5.3) have no helper: they are drawn there with their own classes, in each
state, and the live ones are beside the page. No sample leads away from the page: its links point at the page itself.
A new element gets its section there in the commit that gives it its section here.

**The checks** (`tests/test_0_17_0_design.py`, part of the suite) keep the rules of [9.2](#92-the-rules) true:

- the stylesheets are `tokens.css`, `app.css`, `components.css`, `views.css`, then `site.css` last, and no other;
- every section of `components.css` is a section of this guide, in its order; a component's class is styled in one
  section only, and never in `app.css`;
- in `views.css` a component's class, or a page's class given to a component through its helper (`button({ class })`,
  found through import aliases too), gets only its place, and so does a component's own part reached through it (a
  fold's `summary`, a card's title);
- every size and weight is a token of the type scale;
- the classes 0.17.0 removed stay gone;
- no colour outside `tokens.css`, no theme rule outside it, no token set elsewhere; every token of the last release is
  still defined;
- no inline visual style in the JavaScript; no component class spelled by hand in `views/` (buttons, tags, notices,
  cards, choices, option cards, empty states, folds, badges, work states and the rest come from their helpers);
- a helper's name stays the helper's: no script uses a helper it imports as an object (`fold.kinds`) where no local of
  that name holds, so a local renamed when a helper came in leaves no use behind;
- no action drawn as a link, no link drawn as a button (a download is the one `<a>` with a button's look, made by
  `downloadButton()`); a next-step link always has an address; states are attributes;
- no button is fixed to a width: a slot is a `min-width` (icon buttons and colour swatches hold no words and have
  their size);
- every helper is drawn on `#/design`, and every helper, file and class this guide names exists;
- `#/design` has a section for every section of 4 and 5 here, numbered and named as here and in this order, and none
  of its samples leads away from it.

Before a change to the interface is committed, look at the screens it touches and at `#/design` in both themes, run
[section 2](#2-checking-a-screen) on them, and run the suite.
