"""Traduction des noeuds texte d'un fragment HTML en preservant le balisage."""
import html
import re
from html.parser import HTMLParser

from ..services.translator import translate_to_fr
from .html_text import plain_to_html, strip_html_comments, strip_html_to_text


class _HTMLTranslator(HTMLParser):
    """Traduit les text nodes d'un fragment HTML en preservant la structure."""

    SKIP_TAGS = {"script", "style", "head", "meta", "title", "link", "pre"}
    SPELL_TAGS = {"code"}

    def __init__(self, translate_fn):
        super().__init__(convert_charrefs=True)
        self.translate_fn = translate_fn
        self.tokens = []
        self._skip = 0
        self._stack = []

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t in self.SKIP_TAGS:
            self._skip += 1
        self._stack.append(t)
        self.tokens.append(("start", tag, attrs))

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in self.SKIP_TAGS and self._skip > 0:
            self._skip -= 1
        self.tokens.append(("end", tag))
        if self._stack:
            try:
                self._stack.pop()
            except Exception:
                pass

    def handle_startendtag(self, tag, attrs):
        self.tokens.append(("startend", tag, attrs))

    def handle_data(self, data):
        if data is None:
            return
        if self._skip > 0:
            self.tokens.append(("data", data, data, False))
            return
        inside_code = any(t in self.SPELL_TAGS for t in self._stack)
        inside_heading = any(t in {"h1","h2","h3","h4","h5","h6"} for t in self._stack)
        display_text = data
        plain_text = data
        if data.strip():
            try:
                if inside_heading:
                    # Traduire tout le contenu des titres (y compris les <a> internes)
                    display_text = self.translate_fn(data)
                    plain_text = display_text
                elif inside_code:
                    # Ne pas traduire l'intérieur des <code>
                    display_text = data
                    plain_text = data
                else:
                    display_text = self.translate_fn(data)
                    plain_text = display_text
            except Exception:
                display_text = data
                plain_text = data
        self.tokens.append(("data", display_text, plain_text, True))

    def handle_comment(self, data):
        self.tokens.append(("comment", data))

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")


def render_attrs(attrs):
    if not attrs:
        return ""
    parts = []
    for k, v in attrs:
        if v is None:
            parts.append(k)
        else:
            parts.append(f'{k}="{html.escape(v, quote=True)}"')
    return " " + " ".join(parts)


def translate_html_preserve_markup(html_fragment: str):
    """Traduit les text nodes du fragment HTML et retourne (plain, html)."""
    if not html_fragment:
        return "", ""
    # Supprime les <img> du HTML (évite pollution visuelle dans l'app)
    html_fragment = re.sub(r"<img[^>]*>", " ", html_fragment, flags=re.IGNORECASE)
    html_fragment = strip_html_comments(html_fragment)

    # Fallback simple : si aucune balise, traduit comme du texte brut
    if "<" not in html_fragment:
        translated = translate_to_fr(html_fragment)
        return translated, plain_to_html(translated)

    translator = _HTMLTranslator(translate_to_fr)
    try:
        translator.feed(html_fragment)
        translator.close()
    except Exception:
        # Si parsing echoue, fallback brut
        translated = translate_to_fr(strip_html_to_text(html_fragment))
        return translated, plain_to_html(translated)

    out_html = []
    out_plain = []
    for tok in translator.tokens:
        kind = tok[0]
        if kind == "start":
            tag, attrs = tok[1], tok[2]
            out_html.append(f"<{tag}{render_attrs(attrs)}>")
        elif kind == "end":
            tag = tok[1]
            out_html.append(f"</{tag}>")
            # Traite h1..h6 comme fin de phrase pour le TTS
            if tag.lower() in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                out_plain.append(". ")
        elif kind == "startend":
            tag, attrs = tok[1], tok[2]
            out_html.append(f"<{tag}{render_attrs(attrs)}/>")
        elif kind == "data":
            display_text, plain_text, include_plain = tok[1], tok[2], tok[3]
            out_html.append(html.escape(display_text, quote=False))
            if include_plain:
                out_plain.append(plain_text)
        elif kind == "comment":
            pass
    translated_plain = "".join(out_plain)
    translated_html = "".join(out_html)
    return translated_plain, translated_html
