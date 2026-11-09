"""0.15: `enlens measure`, the figures that show whether a reader reads documents well.

ENLENS reads a PDF with a "reader" (reader 1: ENLENS 0.5 to 0.14; reader 2: 0.15). This module measures each reader
with no AI at all, so the figures can be repeated at every release:

- the reading test: a few small PDFs made here from text we know (columns, running heads, line numbers, front and
  back matter, a table, footnotes). What a reader made of each is compared with the truth;
- a folder of your own PDFs, each with a `.txt` beside it holding its true text (`tools/arxiv_truth.py` makes one);
- a project: do the quotes ENLENS recorded still find their place in the text a reader makes of the original file?
  (nothing in the project is changed: the work is done on a copy);
- timings (reading, searching, words nearby, the codebook's keyword pass and the Profile page, the glossary,
  themes by words) and the number of AI tasks waiting;
- determinism: reading a file twice gives the very same text.

`run()` gathers it all, `to_markdown()` writes the "Validation report: reading documents (no AI)".
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
import shutil
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from . import __version__, ingest, pdfmake, textutil

# =============================================================================================
# 1. the reading test: documents of known text
# =============================================================================================
# Plain academic prose on neutral topics. Every paragraph is used once, in one document only.
_P = {
    "bees": [
        "Cities are often described as hostile places for wild insects, yet surveys of parks, gardens and railway "
        "verges have repeatedly found a surprising variety of bees. In this study we ask which features of the "
        "urban landscape allow these insects to persist, and whether the answer differs between solitary species "
        "and the colonies of bumblebees.",
        "We counted bees along twelve fixed routes, each walked once a fortnight between April and September. "
        "Observers recorded every individual they could identify without capture, together with the plant it was "
        "visiting and the temperature at the start of the walk. Routes were chosen so that they crossed a wide range "
        "of building density, from leafy suburbs to the commercial centre.",
        "The long-term pattern is clear. Routes with more flowering plants supported more bees, and the effect was "
        "strongest in early summer, when few other sources of nectar are available. Bare ground mattered as well: "
        "species that nest in the soil were almost absent from routes where paving covered every open space.",
        "A well-known difficulty with counts of this kind is that they depend on the weather and on the skill of the "
        "observer. We reduced the first problem by walking only on dry mornings with light wind, and the second by "
        "training all observers together and comparing their lists on a test route before the season began.",
        "Several limits should be kept in mind. Our routes cover a single city, and a short-lived heatwave in July "
        "reduced counts on every route for about ten days. Species that are hard to tell apart in the field were "
        "grouped, so the figures describe the variety of kinds of bee rather than an exact number of species.",
        "Despite these limits, the results suggest practical steps. Leaving a strip of lawn uncut, planting "
        "different flowers so that something blooms in every month, and keeping small patches of bare soil are all "
        "inexpensive. Municipal managers who adopt such measures can expect gains within a single season, and "
        "monitoring of the kind described here would allow them to check whether the gains last.",
    ],
    "sleep": [
        "Sleep and learning have been linked for more than a century, but the strength of the link is still "
        "debated. Some experiments find that a night of sleep after study improves recall by a fifth, while others "
        "find no difference at all. We examine whether this disagreement comes from the kind of material that "
        "participants were asked to learn.",
        "Ninety students took part. Half studied a list of unrelated word pairs, and half practised a short "
        "sequence of finger movements on a keyboard. Within each half, participants were assigned at random to "
        "sleep normally at home or to stay awake under supervision until the morning. All were tested after a "
        "further recovery night so that tiredness itself could not explain the results.",
        "Recall of word pairs did not differ between the groups. The keyboard task showed a different picture: "
        "those who had slept typed the sequence faster and with fewer errors than those who stayed awake. The "
        "difference was modest, about eight per cent, but it was found in both the morning and the evening "
        "versions of the test.",
        "These findings fit a view in which sleep helps most where learning depends on practised movement, and "
        "less where it depends on arbitrary facts. Self-reported sleep diaries kept by the sleeping group "
        "agreed closely with wrist sensors, which gives us some confidence that the home condition was "
        "followed as intended.",
        "We cannot say from this design how long the benefit lasts, nor whether it holds for older adults, whose "
        "sleep is lighter and more broken. A follow-up that tests participants again after a week is planned. "
        "Until then, the safest conclusion is a narrow one: for motor skills, a normal night helps.",
        "Two practical points follow for teachers and coaches. Revision of facts need not be abandoned in favour "
        "of early nights, and practice of a physical skill is worth finishing before bedtime rather than after "
        "it. Neither point replaces the plain advice that tired students learn less on the day itself.",
        "The study was approved by the university ethics committee, and every participant gave written consent "
        "before the first session. Those who stayed awake were offered a meal and a quiet room, and all were "
        "paid for their time at the same hourly rate.",
    ],
    "soil": [
        "Farmland soil contains more living organisms than any other part of an agricultural system, and most of "
        "them are microbes that nobody sees. They break down straw, release nitrogen and compete with the "
        "organisms that cause disease in crops. How farming practice changes this hidden community remains "
        "poorly understood.",
        "We took soil cores from forty fields that had been managed in one of two ways for at least a decade. "
        "Twenty fields were ploughed every autumn; twenty were sown without ploughing, with the stubble of the "
        "previous crop left on the surface. Samples were frozen within three hours and the genetic material of "
        "bacteria and fungi was later extracted and sequenced.",
        "Fields that were not ploughed held a richer fungal community and a slightly poorer bacterial one. "
        "The difference was greatest in the top five centimetres and faded with depth, which is where "
        "ploughing mixes the layers together. Organic matter was higher in the same fields, and it rose with "
        "the number of years since ploughing had stopped.",
        "A large-scale comparison of this sort cannot prove cause. Farmers who stop ploughing may also change "
        "their crops, their use of fertiliser and the timing of their work, and we recorded only some of these "
        "choices. Soil texture varied too, and clay-rich fields behaved differently from sandy ones.",
        "Even so, the agreement between our fields is notable. If the pattern holds elsewhere, a farmer who "
        "wants more fungal activity in the soil has a simple option, and a researcher who wants to measure the "
        "result has a ready set of sampling methods.",
        "Further work should follow single fields through time rather than compare different fields on the "
        "same day, because only repeated sampling can separate the effect of management from the effect of place.",
    ],
    "coast": [
        "Coastal erosion is a slow process that becomes visible only in sudden events: a cliff path that ends in "
        "air, a car park that loses its edge after a winter storm. Because the events are rare, people who live "
        "on the coast tend to remember the last one and forget the long trend that lies behind it.",
        "This article reports a survey of residents in six villages along a soft-rock coastline. We asked how "
        "much they knew about local erosion rates, where they got their information, and what they thought "
        "should be done. Questionnaires were delivered by hand and returned by post, and the response rate "
        "was fifty-eight per cent.",
        "Most respondents overestimated how quickly the cliffs near their homes were retreating. The estimate "
        "was highest among those who had witnessed a recent collapse, and lowest among newcomers who had lived "
        "in the village for under five years. Trust in the local council was a stronger predictor of support "
        "for managed retreat than age, income or length of residence.",
        "Information came mainly from neighbours and local newspapers rather than from official maps. "
        "Respondents who had seen the maps usually found them hard to read, and several asked for photographs "
        "taken from the same spot in different decades.",
        "Interviews with ten officials add a second view. They described a shortage of money, conflicting "
        "guidance and the difficulty of explaining uncertainty to people who want a clear answer. One officer "
        "said that residents are rarely upset by bad news and often upset by news that changes.",
        "Our findings suggest that communication about erosion works better when it is local, visual and "
        "repeated. A single leaflet is quickly forgotten, whereas a yearly walk along the cliff with a "
        "surveyor leaves a lasting memory and builds the trust on which difficult decisions depend.",
    ],
    "library": [
        "Public libraries lend millions of books each year, yet the pattern behind those loans is seldom studied "
        "in detail. Knowing who borrows what, and when, would help libraries to plan opening hours, to buy "
        "stock and to explain their value to the councils that pay for them.",
        "We analysed anonymous loan records from four branches over three years. Each record gave the date, the "
        "branch, the broad subject of the item and the age band of the borrower. No names or addresses were "
        "held, and the branches agreed to the use of the data in writing.",
        "Loans differed markedly between branches, as Table 1 shows. The central branch lent most items, but "
        "the smallest branch lent the most per visitor, a result that surprised its own staff.",
        "Weekday patterns were stable. Children's books were borrowed most on Saturdays and during school holidays, "
        "while non-fiction loans by adults peaked on Tuesdays and Wednesdays. Audio books showed the steadiest "
        "demand, with little change from month to month.",
        "A semi-structured interview with each branch manager helped us to interpret the figures. Managers "
        "pointed to local events, such as a school project or a closed bus route, that moved the numbers in ways "
        "the records alone could not explain.",
    ],
    "archive": [
        "Before instruments were standardised, weather was recorded by anyone with the patience to look at the sky "
        "every day: clergymen, ships' officers, landowners and doctors. Their notebooks now fill the shelves "
        "of regional archives, and they hold information about past climate that no machine can replace.",
        "We transcribed the daily entries of one such diarist, a mid-century physician who noted wind, "
        "rain and temperature at his house for twenty-two years. The handwriting was clear, but the abbreviations "
        "changed over time and had to be learned from the pages themselves.",
        "The record shows a run of cold springs in the middle years and a warmer, wetter finish. Rain was "
        "noted on nearly half the days of the year, a figure close to that of the nearest modern station, "
        "which suggests that the diarist was a reliable observer.",
        "Checking such a record against other sources is essential. We compared the diary with harvest dates "
        "from a nearby estate and with the logbook of a ship that lay in the harbour each winter. Where the "
        "sources overlapped, they agreed on the main events of each year.",
        "The diary has limits. The thermometer hung on a north wall that may have been sheltered, and the "
        "entries stop abruptly when the physician moved house. Nevertheless, a year-round record of this length "
        "is rare, and it gives researchers a fixed point from which to judge more fragmentary sources.",
    ],
}

_COMPOUNDS = ("long-term", "well-known", "short-lived", "self-reported", "large-scale", "semi-structured",
              "soft-rock", "clay-rich", "year-round", "mid-century", "non-fiction", "low-income")


def _hyphenation(texts: list[str]) -> dict[str, int]:
    """Where a long word may be cut at the end of a line (after a vowel that is followed by a consonant, near the
    middle of the word): a fixed rule, so the same documents are made every time."""
    cuts: dict[str, int] = {}
    for t in texts:
        for w in t.split():
            core = w.strip(".,;:()")
            if w != core or not core.isalpha() or len(core) < 7 or core in cuts:
                continue
            mid = len(core) // 2
            for i in sorted(range(3, len(core) - 2), key=lambda i: (abs(i - mid), i)):
                if core[i - 1] in "aeiou" and core[i] not in "aeiou":
                    cuts[core] = i
                    break
    return cuts


@dataclass
class Case:
    """A document of known text: its file, its title, the words that belong in its body and the strings that must
    not be there."""
    name: str
    title: str
    path: Path
    body: str
    boilerplate: list[str] = field(default_factory=list)
    what: str = ""


def _full_width(fl: "pdfmake.Flow", text: str, x: float, width: float, font: str, size: float, leading: float) -> None:
    """Lines across both columns (a title, an abstract), written onto the page the flow is on."""
    for ln in pdfmake.wrap(text, width, font, size):
        fl.page.text(ln, x, fl._y, font, size)
        fl._y -= leading


class _TwoColumns(pdfmake.Flow):
    """A flow whose first page has its columns below a title and abstract; the later pages start at the top."""

    def _new_page(self) -> None:
        super()._new_page()
        if len(self.pages) > 1:
            self.top = self._y = 770


def _make_a(folder: Path) -> Case:
    """One column, a running head, page numbers, words cut at the end of a line and compounds broken at their own
    hyphen."""
    paras = _P["bees"]
    title = "Bees in the City: Where Wild Pollinators Persist"
    head = "Urban Pollinator Review - Volume 12 - Field Notes"
    cuts = _hyphenation(paras)
    fl = pdfmake.Flow(running_head=head, page_numbers=True)
    # a column narrow enough that lines end in cut words and broken compounds
    fl.columns = [(72, 350)]
    fl.heading(title, 14)
    for i, para in enumerate(paras):
        if i in (2, 4):
            fl.new_page()
        fl.paragraph(para, hyphenate=cuts)
    path = folder / "a_one_column.pdf"
    fl.write(path, title)
    return Case("a_one_column", title, path, " ".join([title] + paras), [head],
                "one column, running head, page numbers, words hyphenated across lines")


def _make_b(folder: Path) -> Case:
    """Two 230-point columns on A4, a title and an abstract across the full width above them."""
    title = "Does Sleep Help Us Learn? Evidence from Words and Movements"
    abstract_heading = "Abstract"
    abstract = ("We tested whether a night of sleep improves learning, and whether the answer depends on what is "
                "learned. Ninety students either slept or stayed awake after studying word pairs or a keyboard "
                "sequence. Sleep did not improve recall of words, but it improved the speed and accuracy of the "
                "movement task.")
    paras = _P["sleep"]
    head = "Journal of Learning and Memory - Short Reports"
    cuts = _hyphenation(paras)
    fl = _TwoColumns(columns=[(60, 230), (305, 230)], bottom=400, running_head=head, page_numbers=True)
    fl._y = 770
    _full_width(fl, title, 60, 475, "Helvetica-Bold", 15, 18)
    fl._y -= 6
    _full_width(fl, abstract_heading, 60, 475, "Helvetica-Bold", 10, 13)
    _full_width(fl, abstract, 60, 475, "Times-Roman", 10, 12.5)
    fl._y -= 10
    fl.top = fl._y   # the columns of the first page start below the abstract, those of later pages at the top
    for i, para in enumerate(paras):
        if i == 1:
            fl.heading("Methods")
        if i == 2:
            fl.heading("Results")
        if i == 4:
            fl.new_page()
            fl.heading("Discussion")
        fl.paragraph(para, hyphenate=cuts)
    path = folder / "b_two_columns.pdf"
    fl.write(path, title)
    return Case("b_two_columns", title, path,
                " ".join([title, abstract_heading, abstract, paras[0], "Methods", paras[1], "Results"] + paras[2:4]
                         + ["Discussion"] + paras[4:]),
                [head], "two columns with a full-width title and abstract")


def _make_c(folder: Path) -> Case:
    """Line numbers in the left margin, as in a manuscript sent for review."""
    paras = _P["soil"]
    title = "Soil Life under the Plough and without It"
    head = "Manuscript under review - please do not circulate"
    cuts = _hyphenation(paras)
    fl = pdfmake.Flow(columns=[(90, 350)], running_head=head, page_numbers=True, line_numbers=True)
    fl.heading(title, 14)
    for i, para in enumerate(paras):
        if i == 3:
            fl.new_page()
        fl.paragraph(para, hyphenate=cuts)
    path = folder / "c_line_numbers.pdf"
    fl.write(path, title)
    return Case("c_line_numbers", title, path, " ".join([title] + paras), [head],
                "line numbers in the margin and a running head")


def _make_d(folder: Path) -> Case:
    """Front matter on the first page (title, authors, affiliations, emails, dates, keywords), a last page of back
    matter and a short reference list."""
    paras = _P["coast"]
    title = "What Do Coastal Residents Know about Erosion?"
    authors = "Katalin Marsh and Owen Reddick"
    affiliations = ["1 Department of Geography, University of Northfield, Northfield NF1 2AB, United Kingdom",
                    "2 Centre for Coastal Communities, Harbourside Institute, Westport WP3 4CD, Ireland"]
    emails = ["Correspondence: k.marsh@northfield.example", "o.reddick@harbourside.example"]
    dates = "Received 12 March 2025; Accepted 2 June 2025; Published online 20 June 2025"
    keywords = "Keywords: coastal erosion; risk perception; managed retreat; local knowledge; trust"
    abstract = ("A survey of residents in six villages shows that people overestimate how fast their cliffs are "
                "retreating, and that trust in the council predicts support for managed retreat better than age or "
                "income does.")
    back = [("Acknowledgements", "We thank the residents and officials who gave their time, and the village halls "
             "that lent us rooms for the interviews."),
            ("Funding", "This work was supported by the Regional Coastal Futures Programme, grant number RCF-2231."),
            ("Conflicts of interest", "The authors declare that they have no conflicts of interest."),
            ("Data availability", "Anonymised survey responses are available from the corresponding author on "
             "reasonable request.")]
    licence = "This is an open access article distributed under the terms of the Creative Commons Attribution licence."
    refs = ["Okafor, T., and Lindqvist, M. (2019). Sediment movement along soft cliffs. Journal of Coastal "
            "Processes, 41, 112-130.",
            "Brandt, E. (2021). Hazard maps and public understanding. Risk and Society, 8, 55-71.",
            "Haddad, R., and Pell, S. (2018). Living with retreat. Coastal Management Review, 12, 201-219.",
            "Vance, L. (2022). Trust in local government. Public Policy Studies, 30, 14-33."]
    cuts = _hyphenation(paras)
    fl = pdfmake.Flow(columns=[(72, 300)], running_head="Coastal Communities Quarterly", page_numbers=True)
    fl.page.items = [it for it in fl.page.items if it[1] != 72 or it[2] != 806]   # no running head on page 1
    fl.line(title, "Helvetica-Bold", 16)
    fl.gap(4)
    fl.line(authors, "Helvetica", 11)
    fl.gap(4)
    for a in affiliations:
        fl.line(a, "Helvetica", 8.5)
    for e in emails:
        fl.line(e, "Helvetica", 8.5)
    fl.gap(2)
    fl.line(dates, "Helvetica", 8.5)
    fl.gap(8)
    fl.heading("Abstract")
    fl.paragraph(abstract, indent=0)
    fl.line(keywords, "Helvetica", 8.5)
    fl.gap(10)
    fl.heading("Introduction")
    fl.paragraph(paras[0], hyphenate=cuts)
    fl.new_page()
    fl.heading("Survey and findings")
    for para in paras[1:]:
        fl.paragraph(para, hyphenate=cuts)
    fl.new_page()
    for h, t in back:
        fl.heading(h)
        fl.paragraph(t, indent=0, hyphenate=cuts)
    fl.paragraph(licence, font="Helvetica", size=8, indent=0)
    fl.heading("References")
    for r in refs:
        fl.paragraph(r, size=9, indent=0, gap=False)
        fl.gap(3)
    path = folder / "d_front_and_back_matter.pdf"
    fl.write(path, title)
    body = " ".join([title, "Abstract", abstract, "Introduction", paras[0], "Survey and findings"] + paras[1:])
    boiler = [authors] + affiliations + [e.split(": ")[-1] for e in emails] + [dates, keywords] + \
             [t for _h, t in back] + [licence] + refs
    return Case("d_front_and_back_matter", title, path, body, boiler,
                "front matter, back matter (acknowledgements, funding, licence) and references")


def _make_e(folder: Path) -> Case:
    """A table (header row and five rows at aligned positions) with its caption between two body paragraphs."""
    paras = _P["library"]
    title = "Who Borrows What? Loans at Four Public Libraries"
    head = "Library Research Notes"
    caption = "Table 1. Loans per visitor and share of children's items, by branch, averaged over three years."
    header = ["Branch", "Loans per visit", "Children's share", "Open hours"]
    rows = [["Central", "1.9", "34 per cent", "68"], ["Riverside", "2.4", "41 per cent", "52"],
            ["Hillcrest", "2.1", "29 per cent", "44"], ["Tannery Lane", "3.2", "47 per cent", "30"],
            ["Orchard Road", "1.7", "38 per cent", "36"]]
    cuts = _hyphenation(paras)
    fl = pdfmake.Flow(columns=[(72, 270)], running_head=head, page_numbers=True)
    fl.heading(title, 14)
    fl.paragraph(paras[0], hyphenate=cuts)
    fl.paragraph(paras[1], hyphenate=cuts)
    fl.paragraph(paras[2], hyphenate=cuts)
    fl.gap(4)
    fl.line(caption, "Times-Roman", 9.5)
    fl.gap(4)
    xs = [72, 145, 230, 320]
    for k, row in enumerate([header] + rows):
        fl._advance(13)
        for x, cell in zip(xs, row):
            fl.page.text(cell, x, fl._y, "Helvetica-Bold" if k == 0 else "Helvetica", 9)
        fl._y -= 13
    fl.gap(10)
    fl.new_page()
    for para in paras[3:]:
        fl.paragraph(para, hyphenate=cuts)
    path = folder / "e_table.pdf"
    fl.write(path, title)
    boiler = [" ".join(r) for r in [header] + rows]
    return Case("e_table", title, path, " ".join([title] + paras[:3] + [caption] + paras[3:]), [head] + boiler,
                "a small table with its caption between body paragraphs")


def _make_f(folder: Path) -> Case:
    """Footnotes in a smaller font at the foot of two pages."""
    paras = _P["archive"]
    title = "A Physician's Weather Diary, Read Again"
    head = "Historical Climate Notes"
    notes = ["1 The diary is kept in the county record office; its shelf mark is given in the appendix.",
             "2 Abbreviations were expanded only where two or more entries made the meaning certain.",
             "3 The harbour logbook covers the winter months only, from November to March."]
    cuts = _hyphenation(paras)
    fl = pdfmake.Flow(columns=[(72, 260)], bottom=125, running_head=head, page_numbers=True)
    fl.heading(title, 14)
    fl.paragraph(paras[0], hyphenate=cuts)
    fl.paragraph(paras[1], hyphenate=cuts)
    for ln, y in zip(pdfmake.wrap(notes[0], 400, "Times-Roman", 8) + pdfmake.wrap(notes[1], 400, "Times-Roman", 8),
                     (100, 90, 80, 70)):
        fl.page.text(ln, 72, y, "Times-Roman", 8)
    fl.new_page()
    fl.paragraph(paras[2], hyphenate=cuts)
    fl.paragraph(paras[3], hyphenate=cuts)
    for ln, y in zip(pdfmake.wrap(notes[2], 400, "Times-Roman", 8), (100, 90)):
        fl.page.text(ln, 72, y, "Times-Roman", 8)
    fl.new_page()
    fl.paragraph(paras[4], hyphenate=cuts)
    path = folder / "f_footnotes.pdf"
    fl.write(path, title)
    return Case("f_footnotes", title, path, " ".join([title] + paras), [head] + notes,
                "footnotes in a smaller font at the foot of a page")


def make_known_texts(folder: str | Path) -> list[Case]:
    """Make the documents of the reading test in `folder` (created if need be) and return them with their truth.
    The same bytes every time."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    return [f(folder) for f in (_make_a, _make_b, _make_c, _make_d, _make_e, _make_f)]


# =============================================================================================
# 2. figures for one document read by one reader
# =============================================================================================
_WORD = re.compile(r"\w+(?:-\w+)*")


def words(text: str) -> list[str]:
    """The words of a text, lower case, typography unified (ligatures, quotes, dashes), a word with a hyphen of its
    own ("long-term") kept whole, a hyphen at the end of a line or a space dropped."""
    return _WORD.findall(textutil.normalise(text))


def body_text(doc) -> str:
    """The text of the passages features use (section 'body'), in reading order, one space between passages."""
    return " ".join(doc.text[p.start:p.end] for p in doc.passages if p.section == "body")


def _squash(s: str) -> str:
    return re.sub(r"\W+", "", textutil.normalise(s))


def figures(output: str, truth: str, boilerplate: list[str] | None = None) -> dict:
    """What a reader made of a document, in plain numbers. `output` is the text of the body passages, `truth` the
    words that belong in the body; `boilerplate` (when known) the strings that do not.

    - words_truth, words_read: how many words each has.
    - recall: of the words that belong in the body, the share the reader kept (1.0 = none lost). Words are counted
      without regard to their place, so a lost word lowers it and a word in the wrong place does not.
    - precision: of the words the reader kept, the share that belong (1.0 = nothing foreign: no running heads,
      page numbers, footnotes or table cells mixed in).
    - order: the share of the truth's words that the reader has in the right order (the longest run of words both
      share, in sequence, over the truth's words). Columns read in the wrong order lower this, not recall.
    - run_together: words in the output that are two true words stuck together ("ofthe" for "of the"); a word
      with no space where a space belongs. A true compound that lost its hyphen ("longterm" for "long-term") is
      counted here too. Counted per occurrence.
    - broken: true words that appear in the output as two pieces ("exam ple", "exam-ple", "long- term" for
      "long-term"); a space or hyphen where none belongs. Counted per occurrence.
    - boilerplate_left, boilerplate_total: how many of the strings that do not belong (running heads, emails,
      funding text, footnotes, table rows...) were still found in the body, and how many there were; the
      comparison ignores spaces and punctuation. Absent when no strings are known.
    """
    t, o = words(truth), words(output)
    ct, co = Counter(t), Counter(o)
    common = sum((ct & co).values())
    blocks = SequenceMatcher(None, t, o, autojunk=False).get_matching_blocks() if t and o else []
    in_order = sum(b.size for b in blocks)
    vocab = set(t)
    for w in list(vocab):
        vocab.update(w.split("-"))
    bigrams = set(zip(t, t[1:]))
    together = broken = 0
    for k, w in enumerate(o):
        if w not in vocab and "-" not in w and len(w) >= 4:
            if any(w[:i] in vocab and w[i:] in vocab for i in range(2, len(w) - 1)):
                together += 1
        elif "-" in w and w not in vocab and "".join(w.split("-")) in vocab:
            broken += 1
        if k + 1 < len(o):
            a, b = w, o[k + 1]
            if (a, b) not in bigrams and len(a + b) >= 4 and (a + b in vocab or a + "-" + b in vocab) \
                    and (a not in vocab or b not in vocab or a + "-" + b in vocab):
                broken += 1
    out = {"words_truth": len(t), "words_read": len(o),
           "recall": round(common / len(t), 4) if t else 1.0,
           "precision": round(common / len(o), 4) if o else (1.0 if not t else 0.0),
           "order": round(in_order / len(t), 4) if t else 1.0,
           "run_together": together, "broken": broken}
    if boilerplate is not None:
        sq = _squash(output)
        out["boilerplate_total"] = len(boilerplate)
        out["boilerplate_left"] = sum(1 for b in boilerplate if _squash(b) and _squash(b) in sq)
    return out


def _read(path: Path, reader: int):
    return ingest.read_document(Path(path), reader=reader)


def reader_available(reader: int, probe: Path) -> tuple[bool, str]:
    """Whether a reader can read at all (reader 2 is missing from a version that lacks it): (yes/no, why not)."""
    if reader < 1 or reader > max(ingest.READER, 2):
        return False, "there is no such reader"
    try:
        _read(probe, reader)
    except Exception as e:  # noqa: BLE001  a reader that is not there, or not finished, is "not available"
        return False, (str(e) or type(e).__name__)[:200]
    return True, ""


def reading_summary(doc) -> dict:
    """What a reader reports about its reading (reader 2's `reading` dict; empty for reader 1), as plain JSON."""
    r = getattr(doc, "reading", None)
    if not isinstance(r, dict):
        return {}
    try:
        return json.loads(json.dumps(r, default=str))
    except (TypeError, ValueError):
        return {}


def fingerprint(doc) -> str:
    """One hash of a reading: its text, its passages (place, page, section, block) and its page spans."""
    h = hashlib.sha1()
    h.update(doc.text.encode("utf-8", "replace"))
    for p in doc.passages:
        h.update(f"|{p.seq},{p.start},{p.end},{p.page},{p.section},{getattr(p, 'block', None)}".encode())
    h.update(repr(list(doc.page_spans)).encode())
    return h.hexdigest()


def measure_case(path: Path, reader: int, truth: str, boilerplate: list[str] | None = None) -> dict:
    """Figures for one file read by one reader."""
    doc = _read(path, reader)
    out = figures(body_text(doc), truth, boilerplate)
    out["passages"] = len(doc.passages)
    out["body_passages"] = sum(1 for p in doc.passages if p.section == "body")
    reading = reading_summary(doc)
    if reading:
        out["reading"] = reading
    return out


# =============================================================================================
# 3. a folder with truth files
# =============================================================================================
def measure_folder(folder: str | Path, readers: list[int]) -> dict:
    """Every `name.pdf` of the folder that has a `name.txt` beside it (its true body text), read by each reader."""
    folder = Path(folder)
    pairs = [(p, p.with_suffix(".txt")) for p in sorted(folder.glob("*.pdf")) if p.with_suffix(".txt").exists()]
    out: dict = {"folder": str(folder), "documents": [p.name for p, _t in pairs], "readers": {}}
    for r in readers:
        rows: dict[str, dict] = {}
        for pdf, txt in pairs:
            truth = txt.read_text(encoding="utf-8", errors="replace")
            try:
                rows[pdf.name] = measure_case(pdf, r, truth)
            except Exception as e:  # noqa: BLE001
                rows[pdf.name] = {"error": (str(e) or type(e).__name__)[:200]}
        out["readers"][str(r)] = {"documents": rows, "mean": _mean(rows.values())}
    return out


_MEAN_KEYS = ("recall", "precision", "order", "run_together", "broken", "boilerplate_left")


def _mean(rows) -> dict:
    rows = [r for r in rows if "error" not in r]
    if not rows:
        return {}
    return {k: round(sum(r[k] for r in rows) / len(rows), 4) for k in _MEAN_KEYS if all(k in r for r in rows)}


# =============================================================================================
# 4. quotes that still find their place; 5. timings
# =============================================================================================
_QUOTES = (
    "SELECT 'verifications' AS src, quote, doc_id FROM verifications WHERE quote IS NOT NULL AND doc_id IS NOT NULL",
    "SELECT 'labels', quote, doc_id FROM labels WHERE quote IS NOT NULL AND doc_id IS NOT NULL",
    "SELECT 'evidence', quote, doc_id FROM evidence WHERE quote IS NOT NULL AND doc_id IS NOT NULL",
    "SELECT 'judgements', j.quote, p.doc_id FROM judgements j JOIN passages p ON p.passage_id=j.passage_id "
    "WHERE j.quote IS NOT NULL",
    "SELECT 'second_opinions', s.quote, p.doc_id FROM second_opinions s JOIN passages p ON p.passage_id=s.passage_id "
    "WHERE s.quote IS NOT NULL",
)


def recorded_quotes(ws) -> dict[str, list[str]]:
    """The quotes the project recorded, per document: each different quote once per table."""
    seen: dict[str, set[tuple[str, str]]] = {}
    for sql in _QUOTES:
        try:
            rows = ws.query(sql)
        except Exception:  # noqa: BLE001  a table an older project lacks
            continue
        for r in rows:
            q = (r[1] or "").strip()
            if q:
                seen.setdefault(r[2], set()).add((r[0], q))
    return {d: [q for _s, q in sorted(v)] for d, v in seen.items()}


def copy_project(project: str | Path, into: Path) -> Path:
    """A copy of a project folder to work on (the project itself is never opened for writing)."""
    dest = Path(into) / "project"
    project = Path(project)
    shm = shutil.ignore_patterns("*.sqlite-shm")

    def ignore(folder, names):  # 0.16: without the glossary's kept readings (`cache/`), so its timing starts afresh
        return set(shm(folder, names)) | ({"cache"} if Path(folder) == project else set())

    shutil.copytree(project, dest, symlinks=True, ignore=ignore)
    return dest


def measure_quotes(ws, readers: list[int]) -> dict:
    """For each reader: how many of the quotes recorded for the project still find their place in the text that
    reader makes of the original files. Also the time each reader took to read them all."""
    from . import sources

    quotes = recorded_quotes(ws)
    docs, skipped = [], Counter()
    for r in ws.query("SELECT doc_id FROM documents ORDER BY doc_id"):
        info = sources.original_file(ws, r["doc_id"])
        if info.get("available") and info.get("path"):
            docs.append((r["doc_id"], Path(info["path"])))
        else:
            skipped[(info.get("reason") or "the original file is not available")[:80]] += 1
    out: dict = {"documents": ws.scalar("SELECT COUNT(*) FROM documents") or 0, "with_original": len(docs),
                 "skipped": dict(skipped), "quotes_recorded": sum(len(v) for v in quotes.values()),
                 "quotes_with_original": sum(len(quotes.get(d, ())) for d, _p in docs), "readers": {}}
    for rd in readers:
        t0 = time.perf_counter()
        total = placed = in_body = read = 0
        failed: list[str] = []
        for doc_id, path in docs:
            try:
                doc = _read(path, rd)
            except Exception as e:  # noqa: BLE001
                failed.append(f"{path.name}: {(str(e) or type(e).__name__)[:80]}")
                continue
            read += 1
            body = [(p.start, p.end) for p in doc.passages if p.section == "body"]
            for q in quotes.get(doc_id, ()):
                total += 1
                hit = textutil.find_quote(doc.text, q)
                if hit:
                    placed += 1
                    if any(a <= hit[0] < b for a, b in body):
                        in_body += 1
        out["readers"][str(rd)] = {"documents_read": read, "documents_failed": len(failed), "failures": failed[:5],
                                   "quotes_total": total, "placed": placed, "placed_in_body": in_body,
                                   "not_placed": total - placed, "seconds_reading": round(time.perf_counter() - t0, 2)}
    return out


def measure_timings(ws) -> dict:
    """On a copy of a project: how long a few searches, the glossary and a no-AI theme run take, and how many AI
    tasks wait. Every step that needs something missing is skipped, and says so."""
    from . import concordance, search, terms, themes

    out: dict = {"steps": {}, "skipped": {}}
    # AI tasks waiting: a count only, nothing is run
    try:
        rows = ws.query("SELECT kind, status, COUNT(*) AS n FROM tasks GROUP BY kind, status ORDER BY kind, status")
        out["ai_tasks"] = {f"{r['kind']} / {r['status']}": r["n"] for r in rows}
    except Exception as e:  # noqa: BLE001
        out["skipped"]["ai_tasks"] = str(e)[:100]
    body = ws.scalar("SELECT COUNT(*) FROM passages WHERE section='body'") or 0
    out["body_passages"] = body
    if not body:
        for s in ("search", "terms", "themes"):
            out["skipped"][s] = "the project has no readable passages"
        return out
    t0 = time.perf_counter()
    idx = search.passage_index(ws)
    out["steps"]["search_index_seconds"] = round(time.perf_counter() - t0, 3)
    freq: Counter = Counter()
    for r in idx.rows:
        for _a, _b, _stem, word in textutil.token_spans(r["text"]):
            freq[word] += 1
    top = [w for w, _n in sorted(freq.items(), key=lambda x: (-x[1], x[0]))[:5]]
    per = {}
    for w in top:
        t0 = time.perf_counter()
        res = concordance.search(ws, w, limit=50)
        per[w] = {"hits": res["total"], "seconds": round(time.perf_counter() - t0, 3)}
    out["steps"]["searches"] = per
    if top:  # 0.16: the words found near the most frequent word, as the Search page's Words nearby shows them
        t0 = time.perf_counter()
        res = concordance.collocates(ws, top[0])
        out["steps"]["collocates"] = {"word": top[0], "hits": res["hits"], "seconds": round(time.perf_counter() - t0, 3)}
    try:  # 0.16: the codebook's keyword pass over every passage, then the Profile page's grid and counts
        from . import profile

        t0 = time.perf_counter()
        kp = profile.keyword_pass(ws, "sdg")
        out["steps"]["keyword_pass_seconds"] = round(time.perf_counter() - t0, 2)
        out["steps"]["keyword_pass_candidates"] = kp.get("candidates")
        t0 = time.perf_counter()
        labs = profile.effective(ws, "sdg", light=True)
        profile.grid(ws, "sdg", None, "code", labs=labs)
        profile.stats(ws, "sdg", labs=labs)
        out["steps"]["profile_page_seconds"] = round(time.perf_counter() - t0, 3)
    except Exception as e:  # noqa: BLE001
        out["skipped"]["profile"] = (str(e) or type(e).__name__)[:120]
    t0 = time.perf_counter()
    try:
        st = terms.build(ws)
        out["steps"]["terms_seconds"] = round(time.perf_counter() - t0, 2)
        out["steps"]["terms"] = st.get("terms") if isinstance(st, dict) else None
    except Exception as e:  # noqa: BLE001
        out["skipped"]["terms"] = (str(e) or type(e).__name__)[:120]
    if "terms" not in out["skipped"]:
        t0 = time.perf_counter()
        try:  # themes by words: the term index only, no embeddings and no model server
            themes.run(ws, k=6, seed=0, mode="words")
            out["steps"]["themes_seconds"] = round(time.perf_counter() - t0, 2)
        except Exception as e:  # noqa: BLE001
            out["skipped"]["themes"] = (str(e) or type(e).__name__)[:120]
    else:
        out["skipped"]["themes"] = "needs the glossary, which could not be built"
    if "terms" not in out["skipped"]:
        try:
            out["steps"].update(_one_more_document(ws))
        except Exception as e:  # noqa: BLE001
            out["skipped"]["terms_one_more_document"] = (str(e) or type(e).__name__)[:120]
    return out


def _one_more_document(ws) -> dict:
    """0.16 (H3): the glossary after one more document, as after adding one: a document of middle size is taken out
    of the copy, the glossary built without it, and the time of the build once it is back is what is measured."""
    from . import terms

    docs = [r[0] for r in ws.query("SELECT doc_id FROM passages WHERE section='body' GROUP BY doc_id "
                                   "ORDER BY COUNT(*), doc_id")]
    if len(docs) < 2:
        return {}
    one = docs[len(docs) // 2]
    with ws.connect() as cx:
        cx.execute("UPDATE passages SET section='measure-held' WHERE doc_id=? AND section='body'", (one,))
        ws.bump_corpus(cx)
    terms.build(ws)
    with ws.connect() as cx:
        cx.execute("UPDATE passages SET section='body' WHERE doc_id=? AND section='measure-held'", (one,))
        ws.bump_corpus(cx)
    t0 = time.perf_counter()
    st = terms.build(ws)
    return {"terms_one_more_document_seconds": round(time.perf_counter() - t0, 2),
            "terms_one_more_document_read": st.get("documents_read")}


def measure_project(project: str | Path, readers: list[int], timings: bool = False) -> dict:
    """The project figures (quotes, and with `timings` the timings) from a copy of the project in a temporary folder."""
    from .store import Workspace

    project = Path(project)
    if not (project / "enlens.sqlite").exists():
        raise FileNotFoundError(f"No project at {project}.")
    with tempfile.TemporaryDirectory(prefix="enlens-measure-") as tmp:
        copy = Workspace.open(copy_project(project, Path(tmp)))
        try:
            out = {"project": str(project), **measure_quotes(copy, readers)}
            if timings:
                out["timings"] = measure_timings(copy)
            return out
        finally:
            copy.close_all()  # 0.15.7: Windows cannot remove the copy while its database is open


# =============================================================================================
# 6. determinism and the whole run
# =============================================================================================
def run(readers: list[int] | None = None, folder: str | Path | None = None, project: str | Path | None = None,
        timings: bool = False, work: str | Path | None = None) -> dict:
    """Everything: the reading test, determinism, and when given a folder with truth files, a project, timings."""
    readers = sorted(set(readers)) if readers else list(range(1, max(2, ingest.READER) + 1))
    result: dict = {"version": __version__, "date": datetime.date.today().isoformat(), "current_reader": ingest.READER,
                    "readers": {}, "known": {}, "determinism": {}}
    with tempfile.TemporaryDirectory(prefix="enlens-known-") as tmp:
        cases = make_known_texts(Path(work) if work else Path(tmp))
        for r in readers:
            ok, why = reader_available(r, cases[0].path)
            result["readers"][str(r)] = {"available": ok, "why_not": why}
        for c in cases:
            row = {"title": c.title, "what": c.what, "readers": {}}
            for r in readers:
                if not result["readers"][str(r)]["available"]:
                    continue
                row["readers"][str(r)] = measure_case(c.path, r, c.body, c.boilerplate)
            result["known"][c.name] = row
        for r in readers:
            if not result["readers"][str(r)]["available"]:
                continue
            same = {}
            for c in cases:
                same[c.name] = fingerprint(_read(c.path, r)) == fingerprint(_read(c.path, r))
            result["determinism"][str(r)] = same
    result["summary"] = {str(r): _mean(row["readers"][str(r)] for row in result["known"].values()
                                       if str(r) in row["readers"]) for r in readers
                         if result["readers"][str(r)]["available"]}
    if folder:
        result["folder"] = measure_folder(folder, [r for r in readers if result["readers"][str(r)]["available"]])
    if project:
        result["project"] = measure_project(project, [r for r in readers if result["readers"][str(r)]["available"]],
                                            timings)
    return result


# =============================================================================================
# 7. the report
# =============================================================================================
_FIGURES = (
    ("recall", "Words kept", "Of the words that belong in the text, the share the reader kept. 100% means none "
     "was lost. Higher is better."),
    ("precision", "Words that belong", "Of the words the reader kept, the share that really belong in the text: "
     "page numbers, running heads, footnotes and table cells that got mixed in lower it. Higher is better."),
    ("order", "Reading order", "How much of the text comes in the right order. Two columns read straight across "
     "the page, or a footnote in the middle of a sentence, lower it. Higher is better."),
    ("run_together", "Words run together", "Words stuck to the next one, such as \"ofthe\" for \"of the\", or a "
     "compound that lost its hyphen (\"longterm\" for \"long-term\"). Fewer is better; 0 is perfect."),
    ("broken", "Words broken apart", "Words split in two, such as \"exam ple\", or a compound that lost its "
     "joining hyphen (\"long- term\"). Fewer is better; 0 is perfect."),
    ("boilerplate_left", "Left-over running heads, notes and references", "Strings that should have been left out of the text that "
     "searches and AI read (running heads, emails, funding statements, footnotes, table rows, the reference list), "
     "but are still in it. Fewer is better; 0 is perfect."),
)
_PERCENT = {"recall", "precision", "order"}


def _fmt(key: str, v) -> str:
    if v is None:
        return "-"
    return f"{v * 100:.1f}%" if key in _PERCENT else (f"{v:.1f}" if isinstance(v, float) else str(v))


def _table(rows: list[tuple[str, dict]], readers: list[str], key: str, ok: dict, total_key: str | None = None) -> list[str]:
    out = ["| Document | " + " | ".join(f"Reader {r}" for r in readers) + " |",
           "|---|" + "---|" * len(readers)]
    for name, per in rows:
        cells = []
        for r in readers:
            if not ok.get(r):
                cells.append("not available")
            elif r not in per or key not in per[r]:
                cells.append("-")
            else:
                s = _fmt(key, per[r][key])
                if total_key and total_key in per[r]:
                    s += f" of {per[r][total_key]}"
                cells.append(s)
        out.append(f"| {name} | " + " | ".join(cells) + " |")
    return out


def to_markdown(result: dict) -> str:
    """The result of `run` as a plain-language report."""
    readers = sorted(result["readers"], key=int)
    ok = {r: result["readers"][r]["available"] for r in readers}
    L = ["# Validation report: reading documents (no AI)", "",
         f"ENLENS {result['version']}, measured on {result['date']}. Nothing in this report used an AI model: it "
         "measures how well ENLENS reads a document before any AI sees it. Reader 1 is the way ENLENS read PDFs up to "
         "version 0.14, and still reads the documents added before 0.15 until you move them to the new reader; reader "
         "2 is the new reader of version 0.15 (columns, reading order, hyphens, running heads and notes set aside).",
         "", "The same figures are made at every release with `enlens measure`, so a change in them shows that "
         "reading got better or worse.", ""]
    for r in readers:
        if not ok[r]:
            L.append(f"- Reader {r}: not available in this version ({result['readers'][r]['why_not']}).")
    if not all(ok.values()):
        L.append("")
    cases = [(f"{v['title']} ({k.split('_')[0]})", v["readers"]) for k, v in result["known"].items()]
    L += ["## 1. The reading test", "",
          "Six small documents were made from text we know, each with a layout that makes reading hard: " +
          "; ".join(f"({k.split('_')[0]}) {v['what']}" for k, v in result["known"].items()) + ". "
          "Each is read by each reader and compared, word by word, with the text we put in.", ""]
    for key, label, words_ in _FIGURES:
        L += [f"### {label}", "", words_, ""]
        L += _table(cases, readers, key, ok, "boilerplate_total" if key == "boilerplate_left" else None)
        L.append("")
    if result.get("summary"):
        L += ["### Average over the six documents", "", "| Figure | " + " | ".join(f"Reader {r}" for r in readers) + " |",
              "|---|" + "---|" * len(readers)]
        for key, label, _w in _FIGURES:
            L.append(f"| {label} | " + " | ".join(_fmt(key, result["summary"].get(r, {}).get(key)) if ok[r]
                                                 else "not available" for r in readers) + " |")
        L.append("")
    L += ["## 2. Same file, same reading", "",
          "A reading must not change from one run to the next. Each file was read twice by each reader and the two "
          "readings (text, passages, pages) compared.", ""]
    for r in readers:
        d = result["determinism"].get(r)
        L.append(f"- Reader {r}: " + ("not available." if d is None else
                 f"{sum(d.values())} of {len(d)} documents read identically both times."))
    L.append("")
    f = result.get("folder")
    if f:
        L += ["## 3. Documents with a known text on file", "",
              f"Folder {f['folder']}: {len(f['documents'])} PDF files with the true text beside them. The true text "
              "of papers made from their source is approximate (see tools/arxiv_truth.py), so differences of a "
              "point or two are noise; the comparison between readers is what counts.", ""]
        for key, label, words_ in _FIGURES[:5]:
            L += [f"### {label}", "", words_, ""]
            rows = [(n, {r: f["readers"][r]["documents"][n] for r in f["readers"]}) for n in f["documents"]]
            L += _table(rows, readers, key, ok)
            L.append("| Average | " + " | ".join(_fmt(key, f["readers"].get(r, {}).get("mean", {}).get(key))
                                                  for r in readers) + " |")
            L.append("")
    p = result.get("project")
    if p:
        L += ["## 4. Quotes that still find their place", "",
              f"Project {p['project']}: {p['documents']} documents, {p['with_original']} with their original file "
              f"still in place and unchanged, {p['quotes_recorded']} quotes recorded (verdicts, codebook labels, "
              "evidence, judgements, second opinions). Each reader read the original files again, nothing was "
              "stored, and ENLENS looked for every quote in the new text. A quote that is found keeps its place "
              "if results move to that reader; one that is not found would need checking.", "",
              "| Reader | Documents read | Quotes | Found | Not found | Found in the text features use |",
              "|---|---|---|---|---|---|"]
        for r in readers:
            q = p["readers"].get(r)
            L.append(f"| Reader {r} | " + (" | ".join(str(q[k]) for k in ("documents_read", "quotes_total", "placed",
                                                                          "not_placed", "placed_in_body"))
                                           if q and ok[r] else "not available | | | |") + " |")
        L.append("")
        if p["skipped"]:
            L.append("Documents left out: " + "; ".join(f"{n} ({why})" for why, n in p["skipped"].items()) + ".")
            L.append("")
        t = p.get("timings")
        if t:
            L += ["## 5. Timings and waiting AI tasks", "",
                  "Measured on a copy of the project, on this computer; they depend on the computer. No AI model was "
                  "used and nothing waiting in the queue was run.", "",
                  "| Step | Seconds |", "|---|---|"]
            for r in readers:
                q = p["readers"].get(r)
                if q and ok[r]:
                    L.append(f"| Reading every original file, reader {r} | {q['seconds_reading']} |")
            st = t["steps"]
            if "search_index_seconds" in st:
                L.append(f"| Building the search index | {st['search_index_seconds']} |")
            for w, v in st.get("searches", {}).items():
                L.append(f"| Searching for \"{w}\" ({v['hits']} places) | {v['seconds']} |")
            if "collocates" in st:
                c = st["collocates"]
                L.append(f"| Words nearby \"{c['word']}\" ({c['hits']} places) | {c['seconds']} |")
            if "keyword_pass_seconds" in st:
                L.append(f"| The SDG targets found by keywords in every passage ({st.get('keyword_pass_candidates')} "
                         f"candidates) | {st['keyword_pass_seconds']} |")
            if "profile_page_seconds" in st:
                L.append(f"| The Profile page's grid and counts | {st['profile_page_seconds']} |")
            if "terms_seconds" in st:
                L.append(f"| Building the glossary ({st.get('terms')} terms) | {st['terms_seconds']} |")
            if "terms_one_more_document_seconds" in st:
                L.append(f"| The glossary after one more document (documents read: "
                         f"{st.get('terms_one_more_document_read')}, the new one included) | "
                         f"{st['terms_one_more_document_seconds']} |")
            if "themes_seconds" in st:
                L.append(f"| Six themes, found by words | {st['themes_seconds']} |")
            L.append("")
            for s, why in t["skipped"].items():
                L.append(f"Skipped: {s} ({why}).")
            tasks_ = t.get("ai_tasks")
            if tasks_ is not None:
                L += ["", "AI tasks in the queue: " + ("; ".join(f"{k}: {n}" for k, n in tasks_.items())
                                                       if tasks_ else "none") + "."]
            L.append("")
    return "\n".join(L).rstrip() + "\n"
