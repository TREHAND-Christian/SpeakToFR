from codex_tts.text import html_style, html_text, html_translate, tts_prep


# ---------- HTML -> texte ----------
def test_strip_html_basic_blocks():
    out = html_text.strip_html_to_text("<p>Un</p><p>Deux</p>")
    assert out.split() == ["Un", "Deux"]
    assert "\n" in out


def test_strip_html_ignores_script_style_and_pre_content():
    src = "<p>a</p><script>var x=1;</script><style>p{}</style><pre>code</pre><p>b</p>"
    out = html_text.strip_html_to_text(src)
    assert "var" not in out and "code" not in out and "p{}" not in out
    assert "a" in out and "b" in out


def test_strip_html_unescapes_entities():
    assert "a & b" in html_text.strip_html_to_text("<p>a &amp; b</p>")


def test_strip_with_pre_ranges_keeps_pre_text_and_reports_range():
    text, ranges = html_text.strip_html_to_text_with_pre_ranges("<p>avant</p><pre>CODE</pre><p>apres</p>")
    assert len(ranges) == 1
    a, b = ranges[0]
    assert text[a:b] == "CODE"


def test_strip_with_pre_ranges_masks_dots_in_code():
    text, _ = html_text.strip_html_to_text_with_pre_ranges("<p>voir <code>a.b</code></p>")
    assert "." not in text
    assert tts_prep.PLACEHOLDER_DOT in text


def test_comments_are_removed():
    assert "secret" not in html_text.strip_html_comments("a<!-- secret -->b")
    assert "secret" not in html_text.strip_html_comments("a<!-secret")


def test_looks_like_html():
    assert html_text.looks_like_html("<p>x</p>")
    assert html_text.looks_like_html("a <br> b")
    assert not html_text.looks_like_html("simple texte")
    assert not html_text.looks_like_html("")


def test_plain_to_html_escapes_and_breaks_lines():
    out = html_text.plain_to_html("a<b\nc")
    assert "a&lt;b<br>c" in out
    assert out.startswith("<html><body>")


# ---------- espaces autour de <code>/<a> ----------
def test_space_around_inline_code_and_links():
    out = html_text.space_around_inline_code_links("avant<code>x</code>apres<a href='u'>l</a>fin")
    assert "avant <code>" in out
    assert "</code> apres" in out
    assert "</a> fin" in out


def test_space_around_keeps_existing_spaces():
    src = "avant <code>x</code> apres"
    assert html_text.space_around_inline_code_links(src) == src


def test_code_pre_literal_is_escaped():
    out = html_text.space_around_inline_code_links("<code><pre></code>")
    assert "&lt;pre&gt;" in out


def test_strip_empty_tags():
    out = html_text.strip_empty_html_tags("<p>a</p><span></span><b>  </b><p>b</p>")
    assert "<span>" not in out and "<b>" not in out
    assert "<p>a</p>" in out and "<p>b</p>" in out


# ---------- preparation TTS ----------
def test_spell_letters_acronyms():
    assert tts_prep.spell_letters_tts("TTS") == "T T S"
    assert tts_prep.spell_letters_tts("API") == "API"  # contient une voyelle
    assert tts_prep.spell_letters_tts("TTS/PDF") == "T T S slash P D F"


def test_spell_tts_http_and_paths():
    assert "H T T P S" in tts_prep.spell_tts_http("https://x.fr")
    assert "slash" in tts_prep.spell_tts_http("a/b")
    assert tts_prep.spell_tts_paths(r"C:\Program Files\App") == "C: backslash Program Files backslash App"
    assert tts_prep.spell_tts_paths(r"a\b") == r"a\b"


def test_sentence_space_inserted_before_capital():
    assert tts_prep.add_sentence_space("Fin.Debut") == "Fin. Debut"
    assert tts_prep.add_sentence_space("Fin!Debut") == "Fin! Debut"
    assert tts_prep.add_sentence_space("3.5") == "3.5"


def test_sentence_space_with_ranges_shifts_ranges():
    text, ranges = tts_prep.add_sentence_space_with_ranges("A.B code", [(4, 8)])
    assert text == "A. B code"
    assert text[ranges[0][0]:ranges[0][1]] == "code"


def test_sentence_space_html_leaves_tags_untouched():
    out = tts_prep.add_sentence_space_html('<p class="a.B">Fin.Debut</p>')
    assert 'class="a.B"' in out
    assert "Fin. Debut" in out


def test_trim_space_before_punct():
    assert tts_prep.trim_space_before_punct("fin .") == "fin."
    assert tts_prep.trim_space_before_punct("quoi ?") == "quoi?"


def test_strip_tts_icons():
    assert tts_prep.strip_tts_icons("ok \U0001F600 \u2705 fin") == "ok   fin"


def test_mask_inline_dots_and_unmask():
    masked = tts_prep.mask_inline_dots("fichier.txt et mail@site.com. Fin")
    assert "fichier.txt" not in masked
    assert masked.endswith(". Fin")
    assert tts_prep.unmask_code_punct_tts(masked).count(".") >= 1
    assert tts_prep.unmask_code_punct_display(masked) == "fichier.txt et mail@site.com. Fin"


def test_inline_dot_before_capital_stays_a_real_dot():
    assert tts_prep.mask_inline_dots("Fin.Debut") == "Fin.Debut"


def test_code_punct_masking_round_trip():
    masked = tts_prep.mask_code_punct("a.b")
    assert tts_prep.unmask_code_punct_display(masked) == "a.b"
    assert "point" in tts_prep.unmask_code_punct_tts(masked)


def test_looks_like_french():
    assert tts_prep.looks_like_french("Le chat est dans la maison et il dort avec les autres")
    assert not tts_prep.looks_like_french("The quick brown fox jumps over the lazy dog")
    assert not tts_prep.looks_like_french("")


# ---------- style <pre>/<code> ----------
def test_style_pre_blocks_keeps_indentation_and_escapes():
    out = html_style.style_pre_blocks("<body><pre>  if a<b:\n\tx</pre></body>")
    assert "&nbsp;&nbsp;if a&lt;b:" in out
    assert "&nbsp;&nbsp;&nbsp;&nbsp;x" in out
    assert "background:#000" in out


def test_style_pre_blocks_styles_inline_code():
    out = html_style.style_pre_blocks("<p>x <code>y</code></p>")
    assert "font-family:monospace" in out


# ---------- traduction preservant le HTML ----------
def test_translate_preserve_markup_uses_translator(monkeypatch):
    monkeypatch.setattr(html_translate, "translate_to_fr", lambda t: t.upper())
    monkeypatch.setattr(html_translate, "translate_many", lambda ts: [t.upper() for t in ts])
    plain, html_out = html_translate.translate_html_preserve_markup("<p>hello <code>keep</code></p><pre>no</pre>")
    assert "HELLO" in html_out
    assert "<code>keep</code>" in html_out
    assert "<pre>no</pre>" in html_out
    assert "HELLO" in plain and "keep" in plain


def test_translate_preserve_markup_plain_text(monkeypatch):
    monkeypatch.setattr(html_translate, "translate_to_fr", lambda t: "bonjour")
    plain, html_out = html_translate.translate_html_preserve_markup("hello")
    assert plain == "bonjour" and "bonjour" in html_out


def test_translate_preserve_markup_headings_end_sentence(monkeypatch):
    monkeypatch.setattr(html_translate, "translate_to_fr", lambda t: t)
    monkeypatch.setattr(html_translate, "translate_many", lambda ts: list(ts))
    plain, _ = html_translate.translate_html_preserve_markup("<h1>Titre</h1><p>Texte</p>")
    assert plain.startswith("Titre. ")


def test_translate_preserve_markup_removes_images_and_comments(monkeypatch):
    monkeypatch.setattr(html_translate, "translate_to_fr", lambda t: t)
    monkeypatch.setattr(html_translate, "translate_many", lambda ts: list(ts))
    _, out = html_translate.translate_html_preserve_markup("<p>a<img src='x'><!-- c -->b</p>")
    assert "<img" not in out and "<!--" not in out


def test_translate_preserve_markup_empty():
    assert html_translate.translate_html_preserve_markup("") == ("", "")
