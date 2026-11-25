"""Nettoyage du HTML copie (navigateur) pour un rendu lisible dans la fenetre texte (QTextEdit).

Le moteur HTML de Qt ne gere qu'une partie du CSS. Constate sur une copie Chrome :
- un fond semi-transparent (voile sombre sur une photo) devient une barre noire opaque ;
- un texte blanc pose sur une photo devient invisible (blanc sur blanc) ;
- une image distante s'affiche en icone d'image cassee ;
- un emplacement d'image vide avec un fond laisse une barre grise.

On reconstruit donc le HTML : medias retires, styles limites a ce que Qt rend bien, fonds
transparents retires, couleurs avec transparence melangees au fond, contraste texte/fond garanti,
blocs vides supprimes.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Optional

# Balises retirees avec tout leur contenu
_DROP_WITH_CONTENT = {
    "script", "style", "head", "svg", "picture", "video", "audio", "iframe", "canvas",
    "object", "noscript", "template", "map", "select", "textarea",
}
# Balises retirees seules (pas de contenu)
_DROP_TAG = {"img", "source", "embed", "input", "link", "meta", "track", "wbr", "html", "body", "button"}
_VOID = {"br", "hr", "img", "source", "embed", "input", "link", "meta", "track", "wbr", "area", "col"}

# Proprietes CSS conservees (Qt les rend correctement)
_KEEP_PROPS = {
    "color", "background-color", "font-weight", "font-style", "font-size", "font-family",
    "text-decoration", "text-decoration-line", "text-align", "vertical-align", "white-space",
    "margin", "margin-top", "margin-bottom", "margin-left", "margin-right",
    "padding", "padding-top", "padding-bottom", "padding-left", "padding-right",
}
_KEEP_ATTRS = {"a": {"href"}, "td": {"colspan", "rowspan"}, "th": {"colspan", "rowspan"}, "ol": {"start"}}
# Balises HTML5 que Qt ne connait pas : rendues comme des blocs
_AS_DIV = {"article", "section", "header", "footer", "aside", "nav", "main", "figure", "figcaption"}
_BLOCKS = {"div", "p", "ul", "ol", "li", "table", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre"} | _AS_DIV
CARD_GAP = "margin-bottom: 10px"

_COLOR_RE = re.compile(
    r"rgba?\(\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*(?:,\s*([\d.]+%?)\s*)?\)"
    r"|#([0-9a-f]{3,8})\b"
    r"|\b(transparent|white|black)\b",
    re.IGNORECASE,
)
_NAMED = {"white": (255, 255, 255, 1.0), "black": (0, 0, 0, 1.0), "transparent": (0, 0, 0, 0.0)}

WHITE = (255, 255, 255)
DARK_TEXT = (31, 31, 31)
LIGHT_TEXT = (245, 245, 245)
_MIN_CONTRAST = 3.0
_OPAQUE_ENOUGH = 0.9


def parse_color(value: str) -> Optional[tuple]:
    """(r, g, b, alpha) d'une valeur CSS (rgb, rgba, #hex, transparent, white, black), sinon None."""
    m = _COLOR_RE.search(value or "")
    if not m:
        return None
    if m.group(6):
        return _NAMED[m.group(6).lower()]
    if m.group(5):
        h = m.group(5)
        if len(h) in (3, 4):
            r, g, b = (int(c * 2, 16) for c in h[:3])
            a = int(h[3] * 2, 16) / 255 if len(h) == 4 else 1.0
            return r, g, b, a
        if len(h) in (6, 8):
            r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
            a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
            return r, g, b, a
        return None
    r, g, b = (min(255, int(float(m.group(i)))) for i in (1, 2, 3))
    a_raw = m.group(4)
    if a_raw is None:
        a = 1.0
    elif a_raw.endswith("%"):
        a = float(a_raw[:-1]) / 100
    else:
        a = float(a_raw)
    return r, g, b, max(0.0, min(1.0, a))


def _blend(color: tuple, under: tuple) -> tuple:
    r, g, b, a = color
    return tuple(int(round(a * c + (1 - a) * u)) for c, u in zip((r, g, b), under))


def _luminance(rgb: tuple) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: tuple, b: tuple) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _css(rgb: tuple) -> str:
    return "rgb({}, {}, {})".format(*rgb)


def _parse_style(style: str) -> list[tuple[str, str]]:
    out = []
    for decl in (style or "").split(";"):
        if ":" not in decl:
            continue
        prop, value = decl.split(":", 1)
        prop, value = prop.strip().lower(), value.strip()
        if prop and value:
            out.append((prop, value.replace("!important", "").strip()))
    return out


def _clamp_size(value: str) -> Optional[str]:
    m = re.fullmatch(r"([\d.]+)px", value.strip())
    if m:
        return f"{max(10, min(28, round(float(m.group(1)))))}px"
    if re.fullmatch(r"[\d.]+(em|rem|%|pt)|small|medium|large|x-large|smaller|larger", value.strip()):
        return value.strip()
    return None


def _clamp_box(value: str) -> Optional[str]:
    """Marges/espacements : valeurs en px limitees (evite les grands vides), le reste est ignore."""
    parts = value.split()
    out = []
    for p in parts:
        m = re.fullmatch(r"(-?[\d.]+)px", p)
        if m:
            out.append(f"{max(0, min(16, round(float(m.group(1)))))}px")
        elif p == "0":
            out.append("0")
        else:
            return None
    return " ".join(out) if out else None


class _Cleaner(HTMLParser):
    def __init__(self, page_bg: tuple):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0  # profondeur dans une balise retiree avec son contenu
        self.skip_tag: list[str] = []
        # Pile des elements ouverts : [balise, fond effectif, couleur effective, index de la balise ouvrante, style]
        self.stack: list[list] = [["#root", page_bg, DARK_TEXT if _luminance(page_bg) > 0.4 else LIGHT_TEXT, -1, ""]]
        self.cards: set[int] = set()  # index des <a> qui contiennent des blocs (cartes d'un fil d'actualites)

    # -------------------------------------------------------------- balises
    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if self.skip:
            if t in _DROP_WITH_CONTENT:
                self.skip += 1
            return
        if t in _DROP_WITH_CONTENT:
            self.skip = 1
            return
        if t in _DROP_TAG:
            return
        if t in _AS_DIV:
            t = "div"
        if t in _BLOCKS:
            # Un lien qui contient des blocs est une carte : affichee en bloc, separee de la suivante
            for opened in reversed(self.stack[1:]):
                if opened[0] == "a":
                    self.cards.add(opened[3])
                    break
        parent_bg, parent_fg = self.stack[-1][1], self.stack[-1][2]
        style = ""
        kept = []
        for k, v in attrs:
            k = k.lower()
            if k == "style":
                style = v or ""
            elif k in _KEEP_ATTRS.get(t, ()) and v is not None:
                kept.append((k, v))
        decls, bg, fg = self._clean_style(style, parent_bg, parent_fg)
        if t == "a" and not any(d.startswith("text-decoration") for d in decls):
            decls.append("text-decoration: none")  # comme sur la page (Qt souligne les liens par defaut)
        style_txt = "; ".join(decls)
        attr_txt = "".join(f' {k}="{html.escape(v, quote=True)}"' for k, v in kept)
        if decls:
            attr_txt += ' style="' + html.escape(style_txt, quote=True) + '"'
        self.out.append(f"<{t}{attr_txt}>")
        if t not in _VOID:
            self.stack.append([t, bg, fg, len(self.out) - 1, style_txt])

    def handle_startendtag(self, tag, attrs):
        t = tag.lower()
        if self.skip or t in _DROP_TAG or t in _DROP_WITH_CONTENT:
            return
        if t in ("br", "hr"):
            self.out.append(f"<{t}/>")

    def handle_endtag(self, tag):
        t = tag.lower()
        if self.skip:
            if t in _DROP_WITH_CONTENT:
                self.skip -= 1
            return
        if t in _DROP_TAG or t in _VOID:
            return
        # Ferme jusqu'a la balise correspondante (HTML copie parfois mal equilibre)
        if t in _AS_DIV:
            t = "div"
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i][0] == t:
                for opened in reversed(self.stack[i:]):
                    self._close(opened)
                del self.stack[i:]
                return

    def _close(self, opened) -> None:
        tag, idx, style_txt = opened[0], opened[3], opened[4]
        if tag == "a" and idx in self.cards:
            # Carte : le lien devient un bloc espace (Qt n'affiche pas un lien comme un bloc)
            style = "; ".join(s for s in (style_txt, CARD_GAP) if s)
            self.out[idx] = f'<div style="{html.escape(style, quote=True)}">'
            self.out.append("</div>")
        else:
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if self.skip or not data:
            return
        self.out.append(html.escape(data, quote=False))

    # -------------------------------------------------------------- styles
    def _clean_style(self, style: str, parent_bg: tuple, parent_fg: tuple):
        decls: list[str] = []
        bg = parent_bg
        color_value = None
        for prop, value in _parse_style(style):
            if prop == "background":
                # Seule une couleur unie est gardee (pas de degrade ni d'image)
                if "gradient" in value or "url(" in value:
                    continue
                prop = "background-color"
            if prop == "background-color":
                c = parse_color(value)
                if c is None or c[3] < _OPAQUE_ENOUGH:
                    continue  # transparent ou voile : Qt le rendrait opaque (barre noire)
                bg = c[:3]
                decls.append(f"background-color: {_css(bg)}")
                continue
            if prop == "color":
                color_value = value
                continue
            if prop not in _KEEP_PROPS:
                continue
            if prop == "font-size":
                v = _clamp_size(value)
            elif prop.startswith(("margin", "padding")):
                v = _clamp_box(value)
            elif prop == "font-family":
                v = value if len(value) < 120 else None
            else:
                v = value
            if v:
                decls.append(f"{prop}: {v}")
        # Couleur du texte : transparence melangee au fond, puis contraste garanti
        fg = parent_fg
        declared = False
        if color_value is not None:
            c = parse_color(color_value)
            if c is not None:
                fg = _blend(c, bg) if c[3] < 1 else c[:3]
                declared = True
        if contrast(fg, bg) < _MIN_CONTRAST:
            fg = DARK_TEXT if contrast(DARK_TEXT, bg) >= contrast(LIGHT_TEXT, bg) else LIGHT_TEXT
            declared = True
        if declared:
            decls.append(f"color: {_css(fg)}")
        return decls, bg, fg


_EMPTY_BLOCK = re.compile(
    r"<(div|span|a|p|section|article|figure|figcaption|li|ul|ol|header|footer|aside|nav|main|"
    r"strong|b|em|i|small|time|h[1-6])\b[^>]*>(?:\s|&nbsp;| )*</\1>",
    re.IGNORECASE,
)


def _page_background(fragment: str) -> tuple:
    """Fond de la page : celui du premier element s'il est sombre (mode sombre), sinon blanc."""
    m = re.search(r"<[a-z][^>]*style\s*=\s*\"([^\"]*)\"", fragment or "", flags=re.IGNORECASE)
    if m:
        for prop, value in _parse_style(html.unescape(m.group(1))):
            if prop in ("background-color", "background"):
                c = parse_color(value)
                # Seulement un fond sombre (page en mode sombre) : un gris clair est souvent un emplacement
                if c is not None and c[3] >= _OPAQUE_ENOUGH and "gradient" not in value and _luminance(c[:3]) < 0.2:
                    return c[:3]
    return WHITE


def clean_display_html(fragment: str) -> str:
    """HTML copie -> HTML simple et lisible pour QTextEdit (voir le module)."""
    if not fragment or "<" not in fragment:
        return fragment
    m = re.search(r"<!--\s*StartFragment\s*-->(.*?)<!--\s*EndFragment\s*-->", fragment, flags=re.DOTALL | re.IGNORECASE)
    if m:
        fragment = m.group(1)
    page_bg = _page_background(fragment)
    cleaner = _Cleaner(page_bg)
    try:
        cleaner.feed(fragment)
        cleaner.close()
    except Exception:
        return fragment
    # Ferme ce qui est reste ouvert
    for opened in reversed(cleaner.stack[1:]):
        cleaner._close(opened)
    body = "".join(cleaner.out)
    # Blocs vides (emplacements d'images, voiles...) : supprimes, plusieurs passes pour les imbriques
    for _ in range(10):
        new = _EMPTY_BLOCK.sub("", body)
        if new == body:
            break
        body = new
    body = re.sub(r"(?:\s*<br/>\s*){3,}", "<br/><br/>", body)
    bg_css = _css(page_bg)
    fg_css = _css(DARK_TEXT if _luminance(page_bg) > 0.4 else LIGHT_TEXT)
    return f'<div style="background-color: {bg_css}; color: {fg_css}">{body}</div>'
