"""Make src/enlens_claims/data/stopwords.json (0.17): the common words of 58 languages for the glossary.

    python tools/make_stopwords.py stopwords-iso.json /usr/share/dict/words

- `stopwords-iso.json`: stopwords-iso 1.1.0 (https://github.com/stopwords-iso/stopwords-iso, MIT licence; its
  licence is data/stopwords-iso-LICENSE.txt), e.g. https://cdn.jsdelivr.net/npm/stopwords-iso@1.1.0/stopwords-iso.json
- `/usr/share/dict/words`: Webster's Second International (1934, public domain), on macOS and most Unix systems.

The file keeps every list as it is, and `english_too`: the words of the lists other than English that are also English
words (in Webster's or in stopwords-iso's English list: "care", "global", "door", "net"). They tell nothing of a
passage's language, so `stopwords.detect` does not count them (a heading "Net zero care homes" is not Romanian); in a
passage of their language they are still common words.
"""
from __future__ import annotations

import json
import sys


def main(iso_path: str, dict_path: str, out_path: str = "src/enlens_claims/data/stopwords.json") -> None:
    with open(iso_path, encoding="utf-8") as f:
        iso = json.load(f)
    with open(dict_path, encoding="utf-8", errors="ignore") as f:
        english = {w.strip().lower() for w in f if w.strip()} | {w.lower() for w in iso["en"]}
    foreign = {w.lower() for code, words in iso.items() if code != "en" for w in words}
    out = {"source": "stopwords-iso 1.1.0 (https://github.com/stopwords-iso/stopwords-iso), MIT licence: see "
                     "stopwords-iso-LICENSE.txt; english_too: words of the other lists in Webster's Second "
                     "International (1934, public domain) or in stopwords-iso's English list (tools/make_stopwords.py)",
           "languages": {k: sorted(set(v)) for k, v in sorted(iso.items())},
           "english_too": sorted(w for w in foreign if w in english and len(w) > 1 and w.isalpha())}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    print(f"{len(out['languages'])} languages, {len(out['english_too'])} words also English -> {out_path}")


if __name__ == "__main__":
    main(*sys.argv[1:])
