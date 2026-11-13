# Validation gold set: authoring notes

Invented literature on remote work: six demo documents (`tools/demo_corpus/`, unchanged) plus seven new ones in
`documents/` (77 paragraphs, each 325 to 438 characters). Every anchor and every evidence quote was checked to occur
character for character in its file.

## Counts

- `labels.csv`: 110 rows (33 demo passages marked `section body`, 77 new paragraphs). 16 rows have no code.
- Rows per code (main label): WELLBEING 23, COMMUTE 22, MANAGEMENT 13, PRODUCTIVITY 10, EMISSIONS 8, LONELINESS 8,
  WORKING_HOURS 7, TEAMWORK 7, LEARNING 5, RECRUITMENT 4.
- `hypotheses.csv`: 30 hypotheses. supported 7, partially_supported 6, contradicted 6, contested 5, unsupported 6.
  Compound: 6 (H16, H19, H25, H26, H28, H30).

## Calls I was unsure of

- Anchors for demo passages are the first 10 words of the passage as dumped. The news article's first passage starts
  with the title, which appears twice in the HTML (`<title>` and `<h1>`); the anchor is still unique among labels.
- Sick leave, sleep, burnout, back and neck complaints and recovery are all labelled WELLBEING (no separate health
  code); retention (resignations) is labelled RECRUITMENT.
- Municipal brief 0003 (office building closed, service quality) has no code; the managers' study "Performance"
  paragraph is labelled PRODUCTIVITY although it only reports managers' beliefs.
- H10 (equipment reduces sickness absence): the health report gives fewer consultations, so partially_supports.
- H15 (resignations): the evaluation itself says the job market weakened, so partially_supports.
- H26 (life satisfaction by cutting travel time): larger gains for long commutes fit the cause but do not test it, so
  the cause part is partial and the verdict is partially_supported. A strict grader could call it supported.
- H06 (loneliness among older people who live alone): relies on "another group" being counted as partial.
- H18 (stress): the panel's stress fall is for women with young children only (partial); the union survey is
  refuting. Both are single-passage calls.
- 16 unlabelled rows is above "around 10" because background, method and limitations paragraphs of the new
  documents carry no code.
