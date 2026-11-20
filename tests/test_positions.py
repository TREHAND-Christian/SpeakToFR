from codex_tts.text import positions as p


def test_inserts_and_shift():
    text = "A.B fin.C"
    ins = p.sentence_space_inserts(text)
    assert ins == [2, 8]
    assert p.apply_inserts(text, ins) == "A. B fin. C"
    assert p.shift_ranges([(0, 1), (4, 7)], ins) == [(0, 1), (5, 8)]


def test_apply_inserts_empty():
    assert p.apply_inserts("abc", []) == "abc"


def test_mask_ranges_keeps_newlines_and_length():
    out = p.mask_ranges_keep_newlines("ab\ncd", [(1, 4)])
    assert out == "a \n d"
    assert len(out) == 5
    assert p.mask_ranges_keep_newlines("ab", []) == "ab"
    assert p.mask_ranges_keep_newlines("ab", [(-5, 99)]) == "  "


def test_subtract_ranges():
    assert p.subtract_ranges(0, 10, [(3, 5)]) == [(0, 3), (5, 10)]
    assert p.subtract_ranges(0, 10, [(0, 10)]) == []
    assert p.subtract_ranges(2, 4, [(8, 9)]) == [(2, 4)]
    assert p.subtract_ranges(0, 10, [(0, 2), (8, 10)]) == [(2, 8)]


def test_mostly_inside():
    assert p.mostly_inside(0, 10, [(0, 8)])
    assert not p.mostly_inside(0, 10, [(0, 5)])  # exactement 50% -> non
    assert not p.mostly_inside(0, 10, [])


def test_utf16_map_counts_surrogates():
    m = p.build_utf16_index_map("a\U0001F600b")
    assert m == [0, 1, 3, 4]


def test_ref_to_doc_map_identical_is_none():
    assert p.build_ref_to_doc_map("abc", "abc") is None
    assert p.build_ref_to_doc_map("", "abc") is None


def test_ref_to_doc_map_tracks_insertions():
    m = p.build_ref_to_doc_map("abcd", "abXcd")
    assert m[0] == 0 and m[1] == 1
    assert m[2] == 3 and m[3] == 4  # 'c' et 'd' decales d'un cran
    assert all(0 <= v <= 5 for v in m)
