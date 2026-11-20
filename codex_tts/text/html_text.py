"""Conversion HTML -> texte brut, nettoyage de fragments HTML."""
import html
import re
from html.parser import HTMLParser

from .tts_prep import mask_code_punct


class _SimpleHTMLStripper(HTMLParser):
    """Convertit rapidement du HTML en texte brut pour TTS/positions."""

    def __init__(self):
        super().__init__()
        self.parts = []
        self.stack = []
        self.skip = 0
        self.SPELL_TAGS = {"code", "a"}
        self.SKIP_TAGS = {"pre", "script", "style"}

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t in self.SKIP_TAGS:
            self.skip += 1
        self.stack.append(t)
        if tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in self.SKIP_TAGS and self.skip > 0:
            self.skip -= 1
        if t in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            # Ajoute un saut de ligne une seule fois, et jamais en tête
            if self.parts:
                last = self.parts[-1]
                if not last.endswith("\n"):
                    self.parts.append("\n")
        if self.stack:
            try:
                self.stack.pop()
            except Exception:
                pass

    def handle_data(self, data):
        if self.skip > 0:
            # Preserve length with spaces pour garder les offsets stables
            self.parts.append(" " * len(data))
            return
        if data is None:
            return
        data = html.unescape(data)
        self.parts.append(data)

    def handle_comment(self, data):
        if data:
            self.parts.append(" " * len(data))

    def get_text(self) -> str:
        return "".join(self.parts)


def strip_html_to_text(html_str: str) -> str:
    try:
        stripper = _SimpleHTMLStripper()
        stripper.feed(html_str)
        # Decode entities pour un texte lisible
        return html.unescape(stripper.get_text())
    except Exception:
        return html_str


class _HTMLTextWithPreRanges(HTMLParser):
    """Convertit HTML en texte en conservant le contenu des <pre>, et renvoie les ranges correspondant aux <pre>.
    - Masque la ponctuation dans <code>/<a> (même longueur) via mask_code_punct (pour éviter la coupure des phrases).
    - Ne saute PAS <pre> ici (car on veut l'afficher), mais on marque ses offsets pour pouvoir l'ignorer (TTS/surlignage).
    """

    def __init__(self):
        super().__init__()
        self.parts = []
        self.stack = []
        self.pre_depth = 0
        self.pre_ranges = []
        self._pre_start = None
        self.SPELL_TAGS = {"code", "a"}

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        self.stack.append(t)
        if t == "pre":
            self.pre_depth += 1
            if self.pre_depth == 1:
                self._pre_start = len("".join(self.parts))
        if t in {"br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            # Ajoute un saut de ligne une seule fois, et jamais en tête
            if self.parts:
                last = self.parts[-1]
                if not last.endswith("\n"):
                    self.parts.append("\n")
        if t == "pre" and self.pre_depth > 0:
            self.pre_depth -= 1
            if self.pre_depth == 0 and self._pre_start is not None:
                end = len("".join(self.parts))
                if end > self._pre_start:
                    self.pre_ranges.append((self._pre_start, end))
                self._pre_start = None
        if self.stack:
            try:
                self.stack.pop()
            except Exception:
                pass

    def handle_data(self, data):
        if data is None:
            return
        inside_spell = any(t in self.SPELL_TAGS for t in self.stack)
        if inside_spell:
            self.parts.append(mask_code_punct(data))
        else:
            self.parts.append(data)

    def handle_comment(self, data):
        if data:
            self.parts.append(" " * len(data))

    def get_text_and_pre_ranges(self):
        txt = "".join(self.parts)
        return txt, self.pre_ranges


def strip_html_to_text_with_pre_ranges(html_str: str):
    """Retourne (texte, pre_ranges) à partir d'un fragment HTML, en conservant <pre>."""
    try:
        parser = _HTMLTextWithPreRanges()
        parser.feed(html_str)
        return parser.get_text_and_pre_ranges()
    except Exception:
        return strip_html_to_text(html_str), []


def looks_like_html(text: str) -> bool:
    if not text:
        return False

    lowered = text.lower()
    return (
        ("</" in lowered)
        or ("<p" in lowered)
        or ("<div" in lowered)
        or ("<span" in lowered)
        or ("<br" in lowered)
        or ("<code" in lowered)
        or ("<a" in lowered)
    )


def plain_to_html(text: str) -> str:
    safe = html.escape(text or "")
    safe = safe.replace("\n", "<br>")
    return f"<html><body>{safe}</body></html>"


def space_around_inline_code_links(fragment: str) -> str:
    """Ajoute un espace avant/apres <code>/<a> si absent."""
    if not fragment:
        return fragment
    out = fragment
    # Cas courant: "<code><pre></code>" doit afficher le texte "<pre>".
    out = re.sub(
        r"(?is)<code([^>]*)>\s*<pre[^>]*>\s*</code>",
        r"<code\1>&lt;pre&gt;</code>",
        out,
    )
    # Espace avant <code> si collé
    out = re.sub(r"(?i)(?<!\s)(<\s*(?:code|a)\b)", r" \1", out)
    # Espace apres </code> si collé
    out = re.sub(r"(?i)(</\s*(?:code|a)\s*>)(?=\w)", r"\1 ", out)
    # Espace apres </code> avant un tag collé
    out = re.sub(r"(?i)(</\s*(?:code|a)\s*>)(?=<)", r"\1 ", out)
    # Normalise doubles espaces autour des balises
    out = re.sub(r"\s{2,}", " ", out)
    return out


def strip_empty_html_tags(fragment: str) -> str:
    """Supprime les balises vides ou ne contenant que des espaces."""
    if not fragment:
        return fragment

    pattern = re.compile(r"<([A-Za-z0-9]+)(?:\s[^>]*)?>\s*</\1>", re.MULTILINE)
    out = fragment
    for _ in range(5):  # boucle pour eliminer les imbrications vides simples
        # On remplace par un espace pour conserver les séparations éventuelles
        new_out = pattern.sub(" ", out)
        if new_out == out:
            break
        out = new_out
    return out


def strip_html_comments(fragment: str) -> str:
    """Supprime les commentaires HTML (<!-- ... -->)."""
    if not fragment:
        return fragment
    fragment = re.sub(r"<!--.*?-->", " ", fragment, flags=re.DOTALL)
    # Garde-fou pour commentaires mal formes du type "<!-Finfrag"
    return re.sub(r"<!-(?:.|\n)*?(?:-->|$)", " ", fragment)
