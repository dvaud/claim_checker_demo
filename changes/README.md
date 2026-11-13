# Changelog fragments

Since 0.18.1 (roadmap J1.4) a change does not edit `CHANGELOG.md`. It adds one small file here,
`changes/<topic>.md`, so two branches never edit the same lines of the changelog. At a release,
`python tools/release.py fragments <version> "<title>"` joins every fragment into the new entry at the top of
`CHANGELOG.md` and deletes them (`--dry-run` shows the entry first). A tag cannot be released while fragments are left.

A fragment is made of `### <Section>` headings, each followed by its text, written for the people who use ENLENS, in
the changelog's style: a bold headline, then what a person notices, and whether it can change results.

```markdown
### Changes that can alter your results

- **Reader 5 finds tables from their ruled lines.** … Can change results, for documents you move to it.

### Not yet done

- Figures in scanned pages are not found.
```

Sections of the same name in several fragments become one. *New* and *Changes that can alter your results* come
first; *Fixed*, *Privacy*, *For developers*, *Tests* and *Not yet done* come last, in that order; any other section
(*Reading*, *Safer*, …) comes between them, in the order the fragments (sorted by file name) first use it. Two lists
run on as one list. The entry's opening paragraph is written by hand at the release, after joining.
