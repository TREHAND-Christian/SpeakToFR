"""Nettoyage du HTML copie pour la fenetre texte (voiles, couleurs, medias, cartes)."""
from codex_tts.text.html_clean import clean_display_html, contrast, parse_color


def test_semi_transparent_overlay_removed_and_white_text_darkened():
    html = ('<div style="background-color: rgba(0, 0, 0, 0.55)">'
            '<span style="color: rgba(255, 255, 255, 0.95)">Titre sur photo</span></div>')
    out = clean_display_html(html)
    assert "rgba" not in out and "0.55" not in out  # plus de barre noire
    assert "color: rgb(31, 31, 31)" in out  # texte blanc -> sombre (fond blanc)
    assert "Titre sur photo" in out


def test_media_removed_and_empty_placeholders_dropped():
    html = ('<div style="height: 180px; background-color: rgb(229, 229, 229)">'
            '<img src="https://x/a.jpg"></div><p><img src="fav.png"> Le Monde · 4h</p>'
            '<svg><path d="M0"/></svg><script>alert(1)</script>')
    out = clean_display_html(html)
    assert "<img" not in out and "<svg" not in out and "alert" not in out
    assert "229" not in out  # emplacement d'image vide supprime (barre grise)
    assert "Le Monde · 4h" in out


def test_card_link_becomes_spaced_block_without_underline():
    html = '<a href="https://x" style="color: rgb(0,0,0)"><div>Source</div><div>Titre</div></a> <a href="#">lien</a>'
    out = clean_display_html(html)
    assert out.count("margin-bottom: 10px") == 1
    assert '<a href="#" style="text-decoration: none">lien</a>' in out
    assert "</div></div>" in out or "</div> " in out


def test_gradient_and_layout_properties_dropped():
    html = ('<div style="background: linear-gradient(red, blue); position: absolute; width: 300px; '
            'font-size: 64px; padding: 40px; -webkit-line-clamp: 3">Texte</div>')
    out = clean_display_html(html)
    assert "gradient" not in out and "position" not in out and "width" not in out
    assert "font-size: 28px" in out and "padding: 16px" in out


def test_dark_page_keeps_light_text():
    html = '<div style="background-color: rgb(30, 30, 30); color: rgb(230, 230, 230)">Mode sombre</div>'
    out = clean_display_html(html)
    assert out.startswith('<div style="background-color: rgb(30, 30, 30)')
    assert "color: rgb(230, 230, 230)" in out


def test_color_parsing_and_contrast():
    assert parse_color("rgba(0, 0, 0, 0)") == (0, 0, 0, 0.0)
    assert parse_color("#fff") == (255, 255, 255, 1.0)
    assert parse_color("transparent")[3] == 0
    assert contrast((0, 0, 0), (255, 255, 255)) > 20
