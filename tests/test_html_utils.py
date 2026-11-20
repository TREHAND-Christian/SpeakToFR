from codex_tts.text import html_utils as h


# ---------- HTML -> texte ----------
def test_strip_html_basic_blocks():
    out = h._strip_html_to_text("<p>Un</p><p>Deux</p>")
    assert out.split() == ["Un", "Deux"]
    assert "\n" in out


def test_strip_html_ignores_script_style_and_pre_content():
    src = "<p>a</p><script>var x=1;</script><style>p{}</style><pre>code</pre><p>b</p>"
    out = h._strip_html_to_text(src)
    assert "var" not in out and "code" not in out and "p{}" not in out
    assert "a" in out and "b" in out


def test_strip_html_unescapes_entities():
    assert "a & b" in h._strip_html_to_text("<p>a &amp; b</p>")


def test_strip_with_pre_ranges_keeps_pre_text_and_reports_range():
    text, ranges = h._strip_html_to_text_with_pre_ranges("<p>avant</p><pre>CODE</pre><p>apres</p>")
    assert len(ranges) == 1
    a, b = ranges[0]
    assert text[a:b] == "CODE"


def test_strip_with_pre_ranges_masks_dots_in_code():
    text, _ = h._strip_html_to_text_with_pre_ranges("<p>voir <code>a.b</code></p>")
    assert "." not in text
    assert h.PLACEHOLDER_DOT in text


def test_comments_are_removed():
    assert "secret" not in h._strip_html_comments("a<!-- secret -->b")
    assert "secret" not in h._strip_html_comments("a<!-secret")


def test_looks_like_html():
    assert h._looks_like_html("<p>x</p>")
    assert h._looks_like_html("a <br> b")
    assert not h._looks_like_html("simple texte")
    assert not h._looks_like_html("")


def test_plain_to_html_escapes_and_breaks_lines():
    out = h._plain_to_html("a<b\nc")
    assert "a&lt;b<br>c" in out
    assert out.startswith("<html><body>")


# ---------- espaces autour de <code>/<a> ----------
def test_space_around_inline_code_and_links():
    out = h._space_around_inline_code_links("avant<code>x</code>apres<a href='u'>l</a>fin")
    assert "avant <code>" in out
    assert "</code> apres" in out
    assert "</a> fin" in out


def test_space_around_keeps_existing_spaces():
    src = "avant <code>x</code> apres"
    assert h._space_around_inline_code_links(src) == src


def test_code_pre_literal_is_escaped():
    out = h._space_around_inline_code_links("<code><pre></code>")
    assert "&lt;pre&gt;" in out


def test_strip_empty_tags():
    out = h._strip_empty_html_tags("<p>a</p><span></span><b>  </b><p>b</p>")
    assert "<span>" not in out and "<b>" not in out
    assert "<p>a</p>" in out and "<p>b</p>" in out


# ---------- preparation TTS ----------
def test_spell_letters_acronyms():
    assert h._spell_letters_tts("TTS") == "T T S"
    assert h._spell_letters_tts("API") == "API"  # contient une voyelle
    assert h._spell_letters_tts("TTS/XYZ") == "T T S slash X Y Z"


def test_spell_tts_http_and_paths():
    assert "H T T P S" in h._spell_tts_http("https://x.fr")
    assert "slash" in h._spell_tts_http("a/b")
    assert h._spell_tts_paths(r"C:\Program Files\App") == "C: backslash Program Files backslash App"
    assert h._spell_tts_paths("a\b") == "a\b"


def test_sentence_space_inserted_before_capital():
    assert h._add_sentence_space_tts("Fin.Debut") == "Fin. Debut"
    assert h._add_sentence_space_text("Fin!Debut") == "Fin! Debut"
    assert h._add_sentence_space_tts("3.5") == "3.5"


def test_sentence_space_with_ranges_shifts_ranges():
    text, ranges = h._add_sentence_space_with_ranges("A.B code", [(4, 8)])
    assert text == "A. B code"
    assert text[ranges[0][0]:ranges[0][1]] == "code"


def test_sentence_space_html_leaves_tags_untouched():
    out = h._add_sentence_space_html('<p class="a.B">Fin.Debut</p>')
    assert 'class="a.B"' in out
    assert "Fin. Debut" in out


def test_trim_space_before_punct():
    assert h._trim_space_before_punct("fin .") == "fin."
    assert h._trim_space_before_punct("quoi ?") == "quoi?"


def test_strip_tts_icons():
    assert h._strip_tts_icons("ok \U0001F600 \u2705 fin") == "ok   fin"


def test_mask_inline_dots_and_unmask():
    masked = h._mask_inline_dots("fichier.txt et mail@site.com. Fin")
    assert "fichier.txt" not in masked
    assert masked.endswith(". Fin")
    assert h._unmask_code_punct_tts(masked).count(".") >= 1
    assert h._unmask_code_punct_display(masked) == "fichier.txt et mail@site.com. Fin"


def test_inline_dot_before_capital_stays_a_real_dot():
    assert h._mask_inline_dots("Fin.Debut") == "Fin.Debut"


def test_code_punct_masking_round_trip():
    masked = h._mask_code_punct("a.b")
    assert h._unmask_code_punct_display(masked) == "a.b"
    assert "point" in h._unmask_code_punct_tts(masked)


def test_looks_like_french():
    assert h._looks_like_french("Le chat est dans la maison et il dort avec les autres")
    assert not h._looks_like_french("The quick brown fox jumps over the lazy dog")
    assert not h._looks_like_french("")


# ---------- style <pre>/<code> ----------
def test_style_pre_blocks_keeps_indentation_and_escapes():
    out = h._style_pre_blocks("<body><pre>  if a<b:\n\tx</pre></body>")
    assert "&nbsp;&nbsp;if a&lt;b:" in out
    assert "&nbsp;&nbsp;&nbsp;&nbsp;x" in out
    assert "background:#000" in out


def test_style_pre_blocks_styles_inline_code():
    out = h._style_pre_blocks("<p>x <code>y</code></p>")
    assert "font-family:monospace" in out


def test_prep_html_for_positions_masks_pre_and_drops_img():
    out = h._prep_html_for_positions("<body><p>a</p><pre>xy</pre><img src='i'></body>")
    assert "<img" not in out
    assert "xy" not in out


# ---------- traduction preservant le HTML ----------
def test_translate_preserve_markup_uses_translator(monkeypatch):
    monkeypatch.setattr(h, "translate_to_fr", lambda t: t.upper())
    plain, html_out = h.translate_html_preserve_markup("<p>hello <code>keep</code></p><pre>no</pre>")
    assert "HELLO" in html_out
    assert "<code>keep</code>" in html_out
    assert "<pre>no</pre>" in html_out
    assert "HELLO" in plain and "keep" in plain


def test_translate_preserve_markup_plain_text(monkeypatch):
    monkeypatch.setattr(h, "translate_to_fr", lambda t: "bonjour")
    plain, html_out = h.translate_html_preserve_markup("hello")
    assert plain == "bonjour" and "bonjour" in html_out


def test_translate_preserve_markup_headings_end_sentence(monkeypatch):
    monkeypatch.setattr(h, "translate_to_fr", lambda t: t)
    plain, _ = h.translate_html_preserve_markup("<h1>Titre</h1><p>Texte</p>")
    assert plain.startswith("Titre. ")


def test_translate_preserve_markup_removes_images_and_comments(monkeypatch):
    monkeypatch.setattr(h, "translate_to_fr", lambda t: t)
    _, out = h.translate_html_preserve_markup("<p>a<img src='x'><!-- c -->b</p>")
    assert "<img" not in out and "<!--" not in out


def test_translate_preserve_markup_empty():
    assert h.translate_html_preserve_markup("") == ("", "")
