"""Preparation du texte pour la synthese vocale (epellation, masquage de ponctuation)."""
import re


PLACEHOLDER_DOT = "\ue001"


PLACEHOLDER_INLINE_DOT = "\ue002"


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


def spell_punct(text: str) -> str:
    """Epelle certains caracteres pour une lecture TTS plus claire."""
    if not text:
        return text
    out = text
    for k, v in TTS_PUNCT_MAP.items():
        out = out.replace(k, v)
    return out


def spell_tts_http(text: str) -> str:
    """Epelle http/https et ponctuation pour TTS (utiliser uniquement sur segments URLs/code)."""
    if not text:
        return text
    out = text
    # HTTP / HTTPS en lettres (insensible a la casse, avec limites de mots)
    out = re.sub(r"(?i)\bhttps\b", "H T T P S", out)
    out = re.sub(r"(?i)\bhttp\b", "H T T P", out)
    out = spell_punct(out)
    return out


def spell_tts_paths(text: str) -> str:
    """Epelle les backslashes dans les chemins Windows (ex: C:\\Program Files\\...)."""
    if not text:
        return text

    if re.search(r"\b[A-Za-z]:\\", text):
        return text.replace("\\", " backslash ")
    return text


def add_sentence_space(text: str) -> str:
    """Ajoute un espace après . ! ? quand une majuscule suit sans espace."""
    if not text:
        return text
    return re.sub(r"([.!?])(?=[A-ZÀ-ÖØ-Þ])", r"\1 ", text)


def add_sentence_space_with_ranges(
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


def add_sentence_space_html(fragment: str) -> str:
    """Ajoute un espace après . ! ? + majuscule dans le HTML sans toucher aux tags."""
    if not fragment:
        return fragment
    parts = re.split(r"(<[^>]+>)", fragment)
    for i in range(0, len(parts), 2):
        parts[i] = add_sentence_space(parts[i])
        parts[i] = trim_space_before_punct(parts[i])
    text_indices = [i for i in range(0, len(parts), 2)]
    for idx, i in enumerate(text_indices[:-1]):
        cur = parts[i]
        nxt = parts[text_indices[idx + 1]].lstrip()
        if cur and nxt and cur[-1] in '.!?' and not cur.endswith(' '):
            if nxt[:1].isupper():
                parts[i] = cur + ' '
    return ''.join(parts)


def trim_space_before_punct(text: str) -> str:
    """Supprime l'espace avant la ponctuation finale (., !, ?)."""
    if not text:
        return text
    return re.sub(r"\s+([.!?])", r"\1", text).replace(" .", ".").replace(" !", "!").replace(" ?", "?")


def strip_tts_icons(text: str) -> str:
    """Supprime les emojis/pictos pour eviter de les lire en TTS."""
    if not text:
        return text
    # Retire les pictos/emoji les plus courants (supplementary plane + dingbats/emoji).
    text = re.sub(r"[\U00010000-\U0010FFFF]", "", text)
    text = re.sub(r"[\u2600-\u27BF]", "", text)
    return text


def mask_code_punct(text: str) -> str:
    """Masque la ponctuation dans <code>/<a> pour éviter que les points ne coupent la phrase."""
    if not text:
        return text
    return text.replace(".", PLACEHOLDER_DOT)


def unmask_code_punct_tts(text: str) -> str:
    """Convertit les symboles masques en mots TTS (point)."""
    if not text:
        return text
    # Utilise la même liste de ponctuation TTS que le reste de l'app pour cohérence
    out = text.replace(PLACEHOLDER_DOT, TTS_PUNCT_MAP.get(".", " point "))
    return out.replace(PLACEHOLDER_INLINE_DOT, ".")


def unmask_code_punct_display(text: str) -> str:
    """Replace les symboles masqués par leur ponctuation originale pour l'affichage/surbrillance."""
    if not text:
        return text
    return text.replace(PLACEHOLDER_DOT, ".").replace(PLACEHOLDER_INLINE_DOT, ".")


def mask_inline_dots(text: str) -> str:
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


def spell_letters_tts(text: str) -> str:
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


def looks_like_french(text: str) -> bool:
    """Heuristique simple pour éviter de retraduire un texte déjà en français."""
    if not text:
        return False
    lowered = text.lower()
    words = re.findall(r"[a-zàâäéèêëîïôöùûüç]+", lowered)
    if not words:
        return False
    stop_hits = sum(1 for w in words if w in _COMMON_SMALL_FR)
    ratio = stop_hits / max(1, len(words))
    return stop_hits >= 5 or ratio >= 0.15


def prepare_tts_sentence(text: str, *, unmask: bool = True, spell_punct_if_masked: bool = False) -> str:
    """Chaine complete de preparation d'une phrase pour la voix.

    unmask: convertit les points masques (code/liens) en mots ("point").
    spell_punct_if_masked: epelle aussi toute la ponctuation si la phrase contenait un point masque.
    """
    out = unmask_code_punct_tts(text) if unmask else text
    if "http" in out.lower():
        out = spell_tts_http(out)
    out = spell_tts_paths(out)
    out = strip_tts_icons(out)
    if spell_punct_if_masked and PLACEHOLDER_DOT in text:
        out = spell_punct(out)
    out = add_sentence_space(out)
    return spell_letters_tts(out)
