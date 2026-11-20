from codex_tts.text.sentences import split_sentences, split_sentences_with_positions


def test_split_keeps_final_punctuation():
    assert split_sentences("Bonjour. Comment ca va ? Tres bien !") == [
        "Bonjour.",
        "Comment ca va ?",
        "Tres bien !",
    ]


def test_positions_point_to_source_text():
    text = "Une phrase. Une autre."
    sents, pos = split_sentences_with_positions(text)
    assert [text[a:b] for a, b in pos] == sents


def test_newline_ends_a_sentence():
    sents, _ = split_sentences_with_positions("ligne un\nligne deux")
    assert sents == ["ligne un", "ligne deux"]


def test_crlf_is_normalized():
    sents, pos = split_sentences_with_positions("a.\r\nb.")
    assert sents == ["a.", "b."]
    assert pos == [(0, 2), (3, 5)]


def test_empty_text():
    assert split_sentences_with_positions("") == ([], [])
    assert split_sentences("") == [""]


def test_text_without_punctuation_is_one_sentence():
    assert split_sentences("pas de ponctuation") == ["pas de ponctuation"]
