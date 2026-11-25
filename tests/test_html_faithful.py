"""Rendu fidele : HTML sur et fidele, reperage des phrases, presse-papiers, traduction avec images."""
import re

from codex_tts.text import html_translate
from codex_tts.text.html_faithful import faithful_display_html, page_colors, web_document
from codex_tts.text.html_style import style_pre_blocks
from codex_tts.text.web_align import (
    IGNORED_CHARS,
    js_ignored_class,
    segments_for_web,
    visible_prefix,
    visible_text,
)


# ----------------------------------------------------------------- HTML fidele
def test_scripts_events_and_javascript_links_removed():
    html = ('<div onclick="evil()">Texte<script>alert(1)</script>'
            '<a href="javascript:alert(2)">lien</a><a href="https://ok.fr/">bon</a>'
            '<iframe src="https://x.fr"></iframe><noscript>sans js</noscript></div>')
    out = faithful_display_html(html)
    assert "script" not in out and "onclick" not in out and "iframe" not in out
    assert "javascript:" not in out and "sans js" not in out
    assert 'href="https://ok.fr/"' in out and "Texte" in out and "lien" in out


def test_images_backgrounds_and_styles_kept():
    html = ('<div class="card" style="background: linear-gradient(transparent, rgba(0, 0, 0, 0.8)); '
            'border-radius: 10px; box-shadow: rgba(0,0,0,.15) 0px 2px 6px">'
            '<img src="https://cdn.site.fr/photo.jpg" style="width: 260px"><img src="data:image/png;base64,AAAA">'
            '<span style="color: rgba(255, 255, 255, 0.9)">Titre</span></div>')
    out = faithful_display_html(html)
    assert out.count("<img") == 2
    assert "linear-gradient" in out and "border-radius" in out and "rgba(255, 255, 255, 0.9)" in out
    assert 'class="card"' in out


def test_lazy_images_get_their_real_source():
    html = '<img src="data:image/gif;base64,R0lGOD" data-src="https://cdn.fr/vraie.jpg" loading="lazy">'
    out = faithful_display_html(html)
    assert 'src="https://cdn.fr/vraie.jpg"' in out and "loading" not in out


def test_hidden_and_screen_reader_text_dropped():
    html = ('<div>Visible<span style="display: none">cache</span>'
            '<span style="position: absolute; width: 1px; height: 1px; overflow: hidden">lecteur</span>'
            '<div hidden><div>imbrique</div></div> fin</div>')
    out = faithful_display_html(html)
    assert "Visible" in out and "fin" in out
    assert "cache" not in out and "lecteur" not in out and "imbrique" not in out


def test_fixed_position_and_svg_text_neutralised():
    html = ('<div style="position: fixed; top: 0">bandeau</div>'
            '<svg width="16"><title>icone</title><text>ABC</text><path d="M0 0"/></svg>')
    out = faithful_display_html(html)
    assert "position: absolute" in out and "fixed" not in out
    assert "icone" not in out and "ABC" not in out and "<path" in out


def test_fragment_markers_and_comments():
    html = "<html><body><!--StartFragment--><p>Bonjour</p><!--EndFragment--></body></html>"
    assert faithful_display_html(html) == "<p>Bonjour</p>"


def test_page_colors_dark_when_text_is_light():
    assert page_colors('<div style="color: rgb(240, 240, 240)">x</div>')[0] == "rgb(32, 33, 36)"
    assert page_colors('<div style="color: rgb(20, 20, 20)">x</div>')[0] == "rgb(255, 255, 255)"
    assert page_colors('<div style="background-color: rgb(20, 20, 20)">x</div>')[0] == "rgb(20, 20, 20)"


def test_web_document_has_highlight_style_and_base():
    doc = web_document("<html><body><p>Salut</p></body></html>", base_url="https://site.fr/page")
    assert "::highlight(stfr)" in doc and '<base href="https://site.fr/page">' in doc
    assert "<p>Salut</p>" in doc
    plain = web_document(None, "ligne 1\nligne <2>")
    assert "ligne 1<br>ligne &lt;2&gt;" in plain


# ------------------------------------------------------------- reperage phrases
def test_visible_prefix_ignores_spaces_images_and_counts_utf16():
    text = "Ab ￼ c\U0001F642d"
    prefix = visible_prefix(text)
    assert prefix[-1] == 6  # A b c (2 unites pour l'emoji) d
    assert visible_text(text) == "Abc\U0001F642d"


def test_segments_for_web():
    text = "Un deux.\n\nTrois quatre."
    prefix = visible_prefix(text)
    start = text.index("Trois")
    segs = segments_for_web(text, prefix, [(start, len(text))])
    assert segs == [[len("Undeux."), len("Undeux.Troisquatre."), "Troisquatre."]]
    assert segments_for_web(text, prefix, [(3, 3)]) == []


def test_js_class_lists_every_ignored_char():
    cls = js_ignored_class()
    for ch in IGNORED_CHARS:
        assert f"\\u{ord(ch):04x}" in cls
    assert re.fullmatch(r"\[(\\u[0-9a-f]{4})+\]", cls)


# --------------------------------------------------------------- presse-papiers
def test_cf_html_offsets_are_bytes():
    from codex_tts.services.clipboard import _html_fragment_from_cf_html

    frag = "<p>États-Unis : le beau-père · inculpé</p>"
    prefix = "<html><body>"
    header_tpl = "Version:0.9\r\nStartHTML:{:08d}\r\nEndHTML:{:08d}\r\nStartFragment:{:08d}\r\nEndFragment:{:08d}\r\n"
    header_len = len(header_tpl.format(0, 0, 0, 0).encode())
    start = header_len + len(prefix.encode())
    end = start + len(frag.encode("utf-8"))
    data = header_tpl.format(header_len, end + 14, start, end) + prefix + frag + "</body></html>"
    assert _html_fragment_from_cf_html(data) == frag
    marked = data.replace(frag, "<!--StartFragment-->" + frag + "<!--EndFragment-->")
    assert _html_fragment_from_cf_html(marked) == frag


# -------------------------------------------------------------------- traduction
def test_translation_keeps_images_and_spaces_around_links(monkeypatch):
    monkeypatch.setattr(html_translate, "translate_many", lambda ts: [t.strip().upper() for t in ts])
    plain, out = html_translate.translate_html_preserve_markup(
        '<p>les <a href="/x">liens</a> ici<img src="https://a.fr/i.jpg"></p>', keep_images=True)
    assert '<img src="https://a.fr/i.jpg"/>' in out or '<img src="https://a.fr/i.jpg">' in out
    assert "LES <a" in out and "</a> ICI" in out
    _, simple = html_translate.translate_html_preserve_markup('<p>a<img src="x.jpg"></p>')
    assert "<img" not in simple


def test_code_with_existing_style_stays_valid():
    out = style_pre_blocks('<p><code style="color: red">x</code></p>')
    m = re.search(r'<code style="([^"]*)">', out)
    assert m and "font-family:monospace" in m.group(1) and "color: red" in m.group(1)
