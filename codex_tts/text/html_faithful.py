"""HTML copie -> HTML pour la fenetre texte en rendu fidele (moteur Chromium).

Contrairement a html_clean (rendu simplifie pour QTextEdit), on garde tout ce qui fait l'aspect
de la page : images, fonds, degrades, coins arrondis, ombres, polices. On retire seulement :
- ce qui pourrait s'executer ou naviguer (scripts, iframes, attributs on*, liens javascript:) ;
- ce qui est invisible sur la page (display:none, texte reserve aux lecteurs d'ecran) ;
- les positions "fixed"/"sticky" qui couvriraient la fenetre.
Les images chargees a la demande (data-src...) recoivent leur vraie adresse.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Optional

from .html_clean import WHITE, _luminance, _page_background, _parse_style, parse_color

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
# Retirees avec tout leur contenu
_DROP_WITH_CONTENT = {
    "script", "style", "noscript", "template", "iframe", "frame", "frameset", "object", "applet", "head",
    "title", "canvas", "video", "audio", "foreignobject", "dialog",
}
# Retirees seules
_DROP_TAG = {"html", "body", "meta", "link", "base", "embed", "param"}
_URL_ATTRS = {"href", "src", "xlink:href", "action", "formaction", "poster", "background", "srcset", "data"}
_LAZY_SRC = ("data-src", "data-lazy-src", "data-original", "data-url", "data-lazy")
_LAZY_SRCSET = ("data-srcset", "data-lazy-srcset")
_DROP_ATTRS = {"srcdoc", "loading", "autofocus", "contenteditable", "target", "ping", "integrity", "nonce"}

DARK_PAGE = (32, 33, 36)
DARK_TEXT_CSS = "rgb(31, 31, 31)"
LIGHT_TEXT_CSS = "rgb(232, 234, 237)"


def _bad_url(value: str, allow_data_image: bool) -> bool:
    v = re.sub(r"[\x00-\x20]+", "", value or "").lower()
    if v.startswith(("javascript:", "vbscript:")):
        return True
    if v.startswith("data:"):
        return not (allow_data_image and v.startswith("data:image/"))
    return False


def _is_placeholder_src(src: Optional[str]) -> bool:
    if not src or not src.strip():
        return True
    s = src.strip().lower()
    return s.startswith(("data:image/gif", "data:image/svg+xml")) or "blank.gif" in s or "placeholder" in s


def _is_hidden(style: str, attrs: dict) -> bool:
    """Element invisible sur la page : pas affiche ni lu."""
    if "hidden" in attrs:
        return True
    decls = dict(_parse_style(style))
    if decls.get("display", "").startswith("none") or decls.get("visibility", "").startswith("hidden"):
        return True
    # Texte reserve aux lecteurs d'ecran (classe "sr-only" / "visually-hidden")
    if decls.get("position") == "absolute":
        clip = decls.get("clip", "").replace(" ", "")
        if clip.startswith(("rect(0", "rect(1px")) or decls.get("clip-path", "").startswith("inset(50%"):
            return True
        if decls.get("width") == "1px" and decls.get("height") == "1px":
            return True
    return False


def _fix_style(style: str) -> str:
    # Une position fixe/collante sortirait l'element du texte et couvrirait la fenetre
    style = re.sub(r"position\s*:\s*fixed", "position: absolute", style, flags=re.IGNORECASE)
    return re.sub(r"position\s*:\s*sticky", "position: relative", style, flags=re.IGNORECASE)


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.drop_tag: Optional[str] = None  # balise en cours de suppression (avec son contenu)
        self.drop_depth = 0
        self.svg_depth = 0

    def _start_drop(self, tag: str) -> None:
        self.drop_tag, self.drop_depth = tag, 1

    def handle_starttag(self, tag, attrs):
        self._start(tag.lower(), attrs, self_closing=False)

    def handle_startendtag(self, tag, attrs):
        self._start(tag.lower(), attrs, self_closing=True)

    def _start(self, t: str, attrs, self_closing: bool) -> None:
        if self.drop_tag:
            if t == self.drop_tag and not self_closing and t not in _VOID:
                self.drop_depth += 1
            return
        void = t in _VOID or self_closing
        if t in ("video", "audio"):
            poster = dict((k.lower(), v) for k, v in attrs).get("poster")
            if poster and not _bad_url(poster, True):
                self.out.append(f'<img src="{html.escape(poster, quote=True)}">')
        if t in _DROP_WITH_CONTENT:
            if not void:
                self._start_drop(t)
            return
        if t in _DROP_TAG:
            return
        amap = {}
        for k, v in attrs:
            amap[k.lower()] = v
        style = amap.get("style") or ""
        if _is_hidden(style, amap):
            if not void:
                self._start_drop(t)
            return
        if t == "img":
            if _is_placeholder_src(amap.get("src")):
                for key in _LAZY_SRC:
                    if amap.get(key):
                        amap["src"] = amap[key]
                        break
            if not amap.get("srcset"):
                for key in _LAZY_SRCSET:
                    if amap.get(key):
                        amap["srcset"] = amap[key]
                        break
        if t == "form":
            t = "div"
        kept = []
        allow_data = t in ("img", "source", "image", "picture")
        for k, v in amap.items():
            if k.startswith("on") or k in _DROP_ATTRS:
                continue
            if v is None:
                kept.append(k)
                continue
            if k in _URL_ATTRS and _bad_url(v, allow_data):
                continue
            if k == "style":
                v = _fix_style(v)
            kept.append(f'{k}="{html.escape(v, quote=True)}"')
        attr_txt = (" " + " ".join(kept)) if kept else ""
        if void and t not in _VOID:
            # <div/> n'existe pas en HTML : ouvert puis ferme
            self.out.append(f"<{t}{attr_txt}></{t}>")
            return
        self.out.append(f"<{t}{attr_txt}>")
        if t == "svg" and not void:
            self.svg_depth += 1

    def handle_endtag(self, tag):
        t = tag.lower()
        if self.drop_tag:
            if t == self.drop_tag:
                self.drop_depth -= 1
                if self.drop_depth <= 0:
                    self.drop_tag = None
            return
        if t in _VOID or t in _DROP_TAG or t in _DROP_WITH_CONTENT:
            return
        if t == "form":
            t = "div"
        if t == "svg" and self.svg_depth:
            self.svg_depth -= 1
        self.out.append(f"</{t}>")

    def handle_data(self, data):
        if self.drop_tag or not data:
            return
        if self.svg_depth:
            return  # texte des icones SVG : ni affiche par Qt ni lu
        self.out.append(html.escape(data, quote=False))


def _extract_fragment(fragment: str) -> str:
    m = re.search(r"<!--\s*StartFragment\s*-->(.*?)<!--\s*EndFragment\s*-->", fragment, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"<body[^>]*>(.*)</body>", fragment, flags=re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else fragment


def faithful_display_html(fragment: str) -> str:
    """HTML copie -> HTML sur (pas de script) et fidele a la page (voir le module)."""
    if not fragment or "<" not in fragment:
        return fragment
    fragment = _extract_fragment(fragment)
    fragment = re.sub(r"<!--.*?-->", "", fragment, flags=re.DOTALL)
    s = _Sanitizer()
    try:
        s.feed(fragment)
        s.close()
    except Exception:
        return html.escape(re.sub(r"<[^>]+>", " ", fragment), quote=False)
    return "".join(s.out)


def page_colors(body_html: str) -> tuple[str, str]:
    """(fond, texte) de la page : sombre si la selection vient d'une page sombre."""
    bg = _page_background(body_html or "")
    if bg == WHITE:
        # Texte clair sans fond (mode sombre dont le fond est porte par <body>) : fond sombre
        m = re.search(r"<[a-z][^>]*style\s*=\s*\"([^\"]*)\"", body_html or "", flags=re.IGNORECASE)
        if m:
            decls = dict(_parse_style(html.unescape(m.group(1))))
            c = parse_color(decls.get("color", ""))
            has_bg = any(parse_color(decls.get(p, "") or "") for p in ("background", "background-color"))
            if c is not None and c[3] > 0.5 and _luminance(c[:3]) > 0.55 and not has_bg:
                bg = DARK_PAGE
    dark = _luminance(bg) < 0.4
    return "rgb({}, {}, {})".format(*bg), (LIGHT_TEXT_CSS if dark else DARK_TEXT_CSS)


_BASE_CSS = """
html, body {{ margin: 0; background: {bg}; color: {fg}; }}
body {{ padding: 8px 10px; font: 14px "Segoe UI", Arial, sans-serif; line-height: 1.4; overflow-wrap: break-word; }}
img, video, svg, picture {{ max-width: 100%; }}
img {{ height: auto; }}
a {{ color: inherit; }}
::highlight(stfr) {{ background-color: #fff4b8; color: #000; }}
"""


def body_of(html_doc: str) -> str:
    m = re.search(r"<body[^>]*>(.*)</body>", html_doc or "", flags=re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else (html_doc or "")


def web_document(body_html: Optional[str], plain_text: str = "", base_url: Optional[str] = None) -> str:
    """Page complete pour Chromium : fond/texte de la page, styles de base, surlignage de lecture."""
    if body_html and body_html.strip():
        body = body_of(body_html)
    else:
        body = html.escape(plain_text or "", quote=False).replace("\n", "<br>")
    bg, fg = page_colors(body)
    base = f'<base href="{html.escape(base_url, quote=True)}">' if base_url else ""
    css = _BASE_CSS.format(bg=bg, fg=fg)
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f"{base}<style>{css}</style></head><body>{body}</body></html>"
    )
