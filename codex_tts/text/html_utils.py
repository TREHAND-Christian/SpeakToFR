import html
import re
from html.parser import HTMLParser
from typing import Optional

from ..services.translator import translate_to_fr

# Placeholder unique pour masquer les points internes (code, noms de fichiers, emails, domaines)
PLACEHOLDER_DOT = "\ue001"
PLACEHOLDER_INLINE_DOT = "\ue002"
_INLINE_DOT_RE = re.compile(r"(?<=\w)\.(?=\w)")
TTS_PUNCT_MAP = {
    ".": " point ",
    ":": " deux points ",
    "/": " slash ",
    "-": " tiret ",
    "_": " underscore ",
    "\\": " backslash ",
}
_COMMON_SMALL_FR = {
    "le",
    "la",
    "les",
    "un",
    "une",
    "des",
    "du",
    "de",
    "en",
    "et",
    "ou",
    "mais",
    "donc",
    "or",
    "ni",
    "car",
    "que",
    "qui",
    "quoi",
    "dont",
    "ou",
    "où",
    "aux",
    "au",
    "avec",
    "pour",
    "sur",
    "pas",
    "plus",
    "tres",
    "très",
    "sans",
    "encore",
    "cela",
    "ceci",
    "il",
    "elle",
    "ils",
    "elles",
    "nous",
    "vous",
    "tu",
    "je",
    "te",
    "moi",
    "toi",
    "leur",
    "leurs",
    "cette",
    "ce",
    "cet",
    "ces",
    "dans",
    "par",
    "comme",
    "si",
    "quand",
    "est",
    "etait",
    "était",
    "etaient",
    "étaient",
    "ete",
    "été",
    "etre",
    "être",
    "avoir",
    "fait",
    "faire",
    "son",
    "sa",
    "ses",
    "nos",
    "vos",
    "leurs",
}


class _SimpleHTMLStripper(HTMLParser):
    """Convertit rapidement du HTML en texte brut pour TTS/positions."""

    def __init__(self):
        super().__init__()
        self.parts = []
        self.stack = []
        self.skip = 0
        self.SPELL_TAGS = {"code"}
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


def _strip_html_to_text(html_str: str) -> str:
    try:
        stripper = _SimpleHTMLStripper()
        stripper.feed(html_str)
        # Decode entities pour un texte lisible
        return html.unescape(stripper.get_text())
    except Exception:
        return html_str

class _HTMLTextWithPreRanges(HTMLParser):
    """Convertit HTML en texte en conservant le contenu des <pre>, et renvoie les ranges correspondant aux <pre>.
    - Masque la ponctuation dans <code>/<a> (même longueur) via _mask_code_punct (pour éviter la coupure des phrases).
    - Ne saute PAS <pre> ici (car on veut l'afficher), mais on marque ses offsets pour pouvoir l'ignorer (TTS/surlignage).
    """

    def __init__(self):
        super().__init__()
        self.parts = []
        self.stack = []
        self.pre_depth = 0
        self.pre_ranges = []
        self._pre_start = None
        self.SPELL_TAGS = {"code"}

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
            self.parts.append(_mask_code_punct(data))
        else:
            self.parts.append(data)

    def handle_comment(self, data):
        if data:
            self.parts.append(" " * len(data))

    def get_text_and_pre_ranges(self):
        txt = "".join(self.parts)
        return txt, self.pre_ranges


def _strip_html_to_text_with_pre_ranges(html_str: str):
    """Retourne (texte, pre_ranges) à partir d'un fragment HTML, en conservant <pre>."""
    try:
        parser = _HTMLTextWithPreRanges()
        parser.feed(html_str)
        return parser.get_text_and_pre_ranges()
    except Exception:
        return _strip_html_to_text(html_str), []


def _looks_like_html(text: str) -> bool:
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


def _plain_to_html(text: str) -> str:
    safe = html.escape(text or "")
    safe = safe.replace("\n", "<br>")
    return f"<html><body>{safe}</body></html>"


def _space_around_inline_code_links(fragment: str) -> str:
    """Ajoute un espace avant/apres <code>/<a> si absent."""
    if not fragment:
        return fragment
    import re
    out = fragment
    # Espace avant <code> si collé
    out = re.sub(r"(?i)(?<!\s)(<\s*(?:code|a)\b)", r" \1", out)
    # Espace apres </code> si collé
    out = re.sub(r"(?i)(</\s*(?:code|a)\s*>)(?=\w)", r"\1 ", out)
    # Normalise doubles espaces autour des balises
    out = re.sub(r"\s{2,}", " ", out)
    return out


def _strip_empty_html_tags(fragment: str) -> str:
    """Supprime les balises vides ou ne contenant que des espaces."""
    if not fragment:
        return fragment
    import re

    pattern = re.compile(r"<([A-Za-z0-9]+)(?:\s[^>]*)?>\s*</\1>", re.MULTILINE)
    out = fragment
    for _ in range(5):  # boucle pour eliminer les imbrications vides simples
        # On remplace par un espace pour conserver les séparations éventuelles
        new_out = pattern.sub(" ", out)
        if new_out == out:
            break
        out = new_out
    return out


def _strip_html_comments(fragment: str) -> str:
    """Supprime les commentaires HTML (<!-- ... -->)."""
    if not fragment:
        return fragment
    fragment = re.sub(r"<!--.*?-->", " ", fragment, flags=re.DOTALL)
    # Garde-fou pour commentaires mal formes du type "<!-Finfrag"
    return re.sub(r"<!-(?:.|\n)*?(?:-->|$)", " ", fragment)


def _spell_punct(text: str) -> str:
    """Epelle certains caracteres pour une lecture TTS plus claire."""
    if not text:
        return text
    out = text
    for k, v in TTS_PUNCT_MAP.items():
        out = out.replace(k, v)
    return out


def _spell_tts_http(text: str) -> str:
    """Epelle http/https et ponctuation pour TTS (utiliser uniquement sur segments URLs/code)."""
    if not text:
        return text
    out = text
    # HTTP / HTTPS en lettres (insensible a la casse, avec limites de mots)
    out = re.sub(r"(?i)\bhttps\b", "H T T P S", out)
    out = re.sub(r"(?i)\bhttp\b", "H T T P", out)
    out = _spell_punct(out)
    return out


def _spell_tts_paths(text: str) -> str:
    """Epelle les backslashes dans les chemins Windows (ex: C:\\Program Files\\...)."""
    if not text:
        return text

    if re.search(r"\b[A-Za-z]:\\", text):
        return text.replace("\\", " backslash ")
    return text


def _add_sentence_space_tts(text: str) -> str:
    """Ajoute un espace après . ! ? quand une majuscule suit sans espace (TTS uniquement)."""
    if not text:
        return text
    return re.sub(r"([.!?])(?=[A-ZÀ-ÖØ-Þ])", r"\1 ", text)


def _add_sentence_space_text(text: str) -> str:
    """Ajoute un espace après . ! ? quand une majuscule suit sans espace (texte affiché)."""
    if not text:
        return text
    return re.sub(r"([.!?])(?=[A-ZÀ-ÖØ-Þ])", r"\1 ", text)



def _add_sentence_space_html(fragment: str) -> str:
    """Ajoute un espace après . ! ? + majuscule dans le HTML sans toucher aux tags."""
    if not fragment:
        return fragment
    parts = re.split(r"(<[^>]+>)", fragment)
    for i in range(0, len(parts), 2):
        parts[i] = _add_sentence_space_text(parts[i])
        parts[i] = _trim_space_before_punct(parts[i])
    text_indices = [i for i in range(0, len(parts), 2)]
    for idx, i in enumerate(text_indices[:-1]):
        cur = parts[i]
        nxt = parts[text_indices[idx + 1]].lstrip()
        if cur and nxt and cur[-1] in '.!?' and not cur.endswith(' '):
            if nxt[:1].isupper():
                parts[i] = cur + ' '
    return ''.join(parts)

def _trim_space_before_punct(text: str) -> str:
    """Supprime l'espace avant la ponctuation finale (., !, ?)."""
    if not text:
        return text
    return re.sub(r"\s+([.!?])", r"\1", text).replace(" .", ".").replace(" !", "!").replace(" ?", "?")


def _add_sentence_space_with_ranges(
    text: str, ranges: list[tuple[int, int]]
) -> tuple[str, list[tuple[int, int]]]:
    """Ajoute un espace après . ! ? + majuscule et ajuste les ranges."""
    if not text:
        return text, ranges
    inserts = [m.end() for m in re.finditer(r"([.!?])(?=[A-ZÀ-ÖØ-Þ])", text)]
    if not inserts:
        return text, ranges

    chars = list(text)
    offset = 0
    for idx in inserts:
        chars.insert(idx + offset, " ")
        offset += 1

    if not ranges:
        return "".join(chars), ranges

    new_ranges = []
    for a, b in ranges:
        shift_a = sum(1 for ins in inserts if ins <= a)
        shift_b = sum(1 for ins in inserts if ins <= b)
        new_ranges.append((a + shift_a, b + shift_b))

    return "".join(chars), new_ranges



def _strip_tts_icons(text: str) -> str:
    """Supprime les emojis/pictos pour eviter de les lire en TTS."""
    if not text:
        return text
    # Retire les pictos/emoji les plus courants (supplementary plane + dingbats/emoji).
    text = re.sub(r"[\U00010000-\U0010FFFF]", "", text)
    text = re.sub(r"[\u2600-\u27BF]", "", text)
    return text


def _mask_code_punct(text: str) -> str:
    """Masque la ponctuation dans <code>/<a> pour éviter que les points ne coupent la phrase."""
    if not text:
        return text
    return text.replace(".", PLACEHOLDER_DOT)


def _unmask_code_punct_tts(text: str) -> str:
    """Convertit les symboles masques en mots TTS (point)."""
    if not text:
        return text
    # Utilise la même liste de ponctuation TTS que le reste de l'app pour cohérence
    out = text.replace(PLACEHOLDER_DOT, TTS_PUNCT_MAP.get(".", " point "))
    return out.replace(PLACEHOLDER_INLINE_DOT, ".")


def _unmask_code_punct_display(text: str) -> str:
    """Replace les symboles masqués par leur ponctuation originale pour l'affichage/surbrillance."""
    if not text:
        return text
    return text.replace(PLACEHOLDER_DOT, ".").replace(PLACEHOLDER_INLINE_DOT, ".")


def _mask_inline_dots(text: str) -> str:
    """Masque les points inseres au milieu des mots (fichiers, emails, domaines) pour ne pas couper les phrases."""
    if not text:
        return text

    def _mask_inline(m):
        nxt = text[m.end()]
        if nxt.isupper():
            return "."
        return PLACEHOLDER_INLINE_DOT

    def _mask_leading(m):
        nxt = text[m.end()]
        if nxt.isupper():
            return "."
        return PLACEHOLDER_INLINE_DOT

    out = re.sub(r"(?<=\w)\.(?=\w)", _mask_inline, text)
    # Masque aussi un point qui demarre un bloc de mot (ex: .platform.site)
    out = re.sub(r"(?:(?<=\s)|^)\.(?=\w)", _mask_leading, out)
    return out


def _spell_letters_tts(text: str) -> str:
    """
    Epelle lettre par lettre certains tokens courts (acronymes, raccourcis, segments avec '/').
    Ex: TTS -> T T S, ntm -> n t m, ac/ad -> a c slash a d.
    """
    if not text:
        return text

    vowels = set("AEIOUY")

    def _is_acronym(tok: str) -> bool:
        return tok.isupper() and len(tok) >= 3 and not any(ch in vowels for ch in tok)

    def _spell_token(tok: str) -> str:
        token = tok
        if "/" in token:
            parts = token.split("/")
            if all(p.isalpha() and _is_acronym(p) for p in parts):
                spelled_parts = [" ".join(list(p)) for p in parts]
                return " slash ".join(spelled_parts)
        if token.isalpha():
            if _is_acronym(token):
                return " ".join(list(token))
        return tok

    return re.sub(r"[A-Za-z/]{2,}", lambda m: _spell_token(m.group(0)), text)


def _looks_like_french(text: str) -> bool:
    """Heuristique simple pour éviter de retraduire un texte déjà en français."""
    if not text:
        return False
    lowered = text.lower()
    words = re.findall(r"[a-zàâäéèêëîïôöùûüç]+", lowered)
    if not words:
        return False
    accents = any(ch in "àâäéèêëîïôöùûüç" for ch in lowered)
    stop_hits = sum(1 for w in words if w in _COMMON_SMALL_FR)
    ratio = stop_hits / max(1, len(words))
    return accents or stop_hits >= 3 or ratio >= 0.12


def _style_pre_blocks(html_fragment: str) -> str:
    """
    Force un rendu lisible des blocs <pre> dans QTextEdit (Qt) :
    - fond noir
    - texte blanc
    - padding + police monospace
    IMPORTANT : Qt applique beaucoup mieux le style INLINE que <style>...</style>.
    """
    if not html_fragment:
        return html_fragment

    import re

    # Extrait head/body s'ils existent (sans toucher au contenu head)
    body = html_fragment
    head_content = ""
    m_body = re.search(r"<body[^>]*>(.*)</body>", html_fragment, flags=re.IGNORECASE | re.DOTALL)
    if m_body:
        body = m_body.group(1)
    m_head = re.search(r"<head[^>]*>(.*)</head>", html_fragment, flags=re.IGNORECASE | re.DOTALL)
    if m_head:
        head_content = m_head.group(1)

    def _strip_attrs(tag_match):
        tag = tag_match.group(1)
        # Conserve les balises sans attributs (on ne garde pas les attrs)
        return f"<{tag}>"

    def _process_pre(match):
        inner = match.group(1)

        # Nettoyage des tags internes (comme avant)
        inner_clean = re.sub(r"<(\w+)(?:\s[^>/]*?)?>", _strip_attrs, inner)

        # Style INLINE (fiable dans Qt)
        pre_style = (
            "background:#000 !important;"
            "color:#fff !important;"
            "padding:6px 8px !important;"
            "display:block !important;"
            "border-radius:4px !important;"
            "font-family:monospace !important;"
            "white-space:pre-wrap !important;"
        )

        # Force la couleur à l'intérieur (héritage parfois foireux dans Qt)
        inner_clean = f'<span style="color:#fff !important;">{inner_clean}</span>'

        return f'<pre style="{pre_style}">{inner_clean}</pre>'

    # Remplace tous les <pre ...>...</pre> par des <pre style="...">...</pre>
    pre_blocks = []

    def _replace_pre(match):
        processed = _process_pre(match)
        pre_blocks.append(processed)
        return f"__PRE_BLOCK_{len(pre_blocks) - 1}__"

    body = re.sub(r"<pre[^>]*>(.*?)</pre>", _replace_pre, body, flags=re.IGNORECASE | re.DOTALL)

    # Ajoute un style lisible aux balises <code> (hors <pre>)
    code_style = "background:#f2f2f2 !important;padding:1px 4px !important;border-radius:3px !important;font-family:monospace !important;"

    def _style_code(match):
        attrs = match.group(1) or ""
        if "style=" in attrs.lower():
            return match.group(0).replace("style=", f'style="{code_style}', 1)
        sep = "" if attrs.strip().endswith("/") or not attrs.strip() else " "
        return f"<code{attrs}{sep}style=\"{code_style}\">"

    body = re.sub(r"<code([^>]*)>", _style_code, body, flags=re.IGNORECASE)

    # Restaure les blocs <pre> deja stylises
    for idx, pre_html in enumerate(pre_blocks):
        body = body.replace(f"__PRE_BLOCK_{idx}__", pre_html)

    return f"<html><head>{head_content}</head><body>{body}</body></html>"


def _prep_html_for_positions(html_fragment: Optional[str]) -> Optional[str]:
    """Ajoute des espaces placeholder pour les balises sans texte (ex: img) avant strip."""
    if not html_fragment:
        return html_fragment
    import re
    frag = html_fragment
    # Ne garder que le contenu du body pour eviter que le head/style ne decale les offsets
    m = re.search(r"<body[^>]*>(.*)</body>", frag, flags=re.IGNORECASE | re.DOTALL)
    if m:
        frag = m.group(1)
    # Masque le contenu des <pre> par des espaces (en conservant les sauts de ligne) pour les ignorer en TTS/surbrillance
    def _mask_pre(match):
        inner = match.group(1)
        inner_plain = _strip_html_to_text(inner)
        masked = "".join("\n" if c == "\n" else " " for c in inner_plain)
        return f"<pre>{masked}</pre>"
    frag = re.sub(r"<pre[^>]*>(.*?)</pre>", _mask_pre, frag, flags=re.IGNORECASE | re.DOTALL)
    # Ici on retire completement les img pour eviter tout decalage de positions
    frag = re.sub(r"<img[^>]*>", "", frag, flags=re.IGNORECASE)
    return frag


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


def _render_attrs(attrs):
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
    html_fragment = _strip_html_comments(html_fragment)

    # Fallback simple : si aucune balise, traduit comme du texte brut
    if "<" not in html_fragment:
        translated = translate_to_fr(html_fragment)
        return translated, _plain_to_html(translated)

    translator = _HTMLTranslator(translate_to_fr)
    try:
        translator.feed(html_fragment)
        translator.close()
    except Exception:
        # Si parsing echoue, fallback brut
        translated = translate_to_fr(_strip_html_to_text(html_fragment))
        return translated, _plain_to_html(translated)

    out_html = []
    out_plain = []
    for tok in translator.tokens:
        kind = tok[0]
        if kind == "start":
            tag, attrs = tok[1], tok[2]
            out_html.append(f"<{tag}{_render_attrs(attrs)}>")
        elif kind == "end":
            tag = tok[1]
            out_html.append(f"</{tag}>")
            # Traite h1..h6 comme fin de phrase pour le TTS
            if tag.lower() in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                out_plain.append(". ")
        elif kind == "startend":
            tag, attrs = tok[1], tok[2]
            out_html.append(f"<{tag}{_render_attrs(attrs)}/>")
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
