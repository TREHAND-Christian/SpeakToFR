"""Traduction des noeuds texte d'un fragment HTML en preservant le balisage.

Les noeuds a traduire sont d'abord releves, puis envoyes ensemble (translate_many) :
quelques requetes au lieu d'une par noeud (un lien, un mot en gras, un element de liste...).
"""
import html
import re
from html.parser import HTMLParser

from ..services.translator import translate_many, translate_to_fr
from .html_text import plain_to_html, strip_html_comments, strip_html_to_text


class _HTMLTranslator(HTMLParser):
    """Traduit les text nodes d'un fragment HTML en preservant la structure."""

    SKIP_TAGS = {"script", "style", "head", "meta", "title", "link", "pre"}
    SPELL_TAGS = {"code"}

    def __init__(self, translate_fn=None):
        super().__init__(convert_charrefs=True)
        self.translate_fn = translate_fn  # garde pour compatibilite (plus utilise : traduction groupee)
        self.tokens = []
        self.pending = []  # (index du token, texte) : noeuds a traduire en fin d'analyse
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
        # Les titres (y compris leurs <a>) et le texte courant sont traduits ; l'interieur des <code> non.
        # Les noeuds sans lettres (puces, chiffres, ponctuation) ne partent pas a la traduction.
        if data.strip() and not inside_code and any(ch.isalpha() for ch in data):
            self.pending.append((len(self.tokens), data))
        self.tokens.append(("data", data, data, True))

    def translate_pending(self) -> None:
        """Traduit d'un coup tous les noeuds releves et remet chaque traduction a sa place."""
        if not self.pending:
            return
        try:
            translated = translate_many([text for _, text in self.pending])
        except Exception:
            return  # texte d'origine conserve
        for (idx, original), text_fr in zip(self.pending, translated):
            text_fr = _keep_edges(original, text_fr)
            self.tokens[idx] = ("data", text_fr, text_fr, True)

    def handle_comment(self, data):
        self.tokens.append(("comment", data))

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")


def _keep_edges(original: str, translated: str) -> str:
    """Remet les espaces de debut/fin du noeud d'origine (sinon "les <a>" devient "the<a>")."""
    if not translated:
        return original
    lead = original[: len(original) - len(original.lstrip())]
    trail = original[len(original.rstrip()):]
    return lead + translated.strip() + trail


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


def translate_html_preserve_markup(html_fragment: str, keep_images: bool = False):
    """Traduit les text nodes du fragment HTML et retourne (plain, html)."""
    if not html_fragment:
        return "", ""
    if not keep_images:
        # Rendu simplifie : pas d'images (Qt les affiche en icone cassee)
        html_fragment = re.sub(r"<img[^>]*>", " ", html_fragment, flags=re.IGNORECASE)
    html_fragment = strip_html_comments(html_fragment)

    # Fallback simple : si aucune balise, traduit comme du texte brut
    if "<" not in html_fragment:
        translated = translate_to_fr(html_fragment)
        return translated, plain_to_html(translated)

    translator = _HTMLTranslator()
    try:
        translator.feed(html_fragment)
        translator.close()
        translator.translate_pending()
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
