from enlens_claims.taxonomy import normalise_target, targets, targets_reference_text
from enlens_claims.textutil import clean_doi, find_dois, find_quote, split_sentences


def test_169_targets_including_lettered():
    t = targets()
    assert len(t) == 169
    assert "7.b" in t and "17.19" in t
    assert sum(1 for c in t if not c.split(".")[1].isdigit()) == 43
    assert "7.b" in targets_reference_text()


def test_normalise_target_spellings():
    assert normalise_target("SDG 6.4") == "6.4"
    assert normalise_target("Target 7.B") == "7.b"
    assert normalise_target(" 12.a ") == "12.a"
    assert normalise_target("18.1") is None
    assert normalise_target("water") is None


def test_quote_exact_and_typography():
    hay = "The “heavy” dependence on im-  ported\nequipment poses a risk."
    s, e, kind = find_quote(hay, 'the "heavy" dependence on im- ported equipment')
    assert kind == "exact" and hay[s:e].startswith("The “heavy”")


def test_quote_tolerates_pdf_spacing_but_not_paraphrase():
    hay = "In this briefing, we examine w hy Africa is wellplaced for hydrogen."
    hit = find_quote(hay, "we examine why Africa is well placed")
    assert hit and hit[2] == "spacing"
    assert find_quote(hay, "we examine why Africa is ideally placed") is None
    assert find_quote(hay, "Africa is wellplaced for hydrogen by 30%") is None


def test_sentence_split_respects_abbreviations():
    t = "Water use rises, e.g. in Morocco. Smith et al. agree with this. Next sentence here!"
    sents = [t[a:b] for a, b in split_sentences(t)]
    assert sents == ["Water use rises, e.g. in Morocco.", "Smith et al. agree with this.", "Next sentence here!"]


def test_doi_helpers():
    assert clean_doi("https://doi.org/10.1016/J.IJHYDENE.2022.11.024.") == "10.1016/j.ijhydene.2022.11.024"
    assert find_dois("see doi:10.1000/xyz123, and 10.1000/xyz123") == ["10.1000/xyz123"]
