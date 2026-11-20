"""Calculs d'offsets sur le texte affiche : plages <pre>, insertions d'espaces, mappings Qt."""
import difflib
import re
from typing import Optional

Range = tuple[int, int]

_SENTENCE_END_BEFORE_CAPITAL = re.compile(r"([.!?])(?=[A-ZÀ-ÖØ-Þ])")


def sentence_space_inserts(text: str) -> list[int]:
    """Positions ou inserer un espace (apres . ! ? suivi directement d'une majuscule)."""
    return [m.end() for m in _SENTENCE_END_BEFORE_CAPITAL.finditer(text)]


def apply_inserts(text: str, inserts: list[int]) -> str:
    """Insere un espace a chaque position de `inserts` (positions croissantes, dans `text`)."""
    if not inserts:
        return text
    chars = list(text)
    for offset, pos in enumerate(inserts):
        chars.insert(pos + offset, " ")
    return "".join(chars)


def shift_ranges(ranges: list[Range], inserts: list[int]) -> list[Range]:
    """Decale des plages pour tenir compte des insertions faites avant leurs bornes."""
    return [
        (a + sum(1 for i in inserts if i <= a), b + sum(1 for i in inserts if i <= b))
        for a, b in ranges
    ]


def mask_ranges_keep_newlines(text: str, ranges: list[Range]) -> str:
    """Remplace les plages par des espaces (meme longueur), en gardant les retours ligne."""
    if not ranges:
        return text
    chars = list(text)
    for a, b in ranges:
        for k in range(max(0, a), min(len(chars), b)):
            if chars[k] != "\n":
                chars[k] = " "
    return "".join(chars)


def subtract_ranges(start: int, end: int, ranges: list[Range]) -> list[Range]:
    """Retire de [start, end[ les plages `ranges` ; renvoie les segments restants non vides."""
    parts = [(start, end)]
    for a, b in ranges:
        new_parts = []
        for x, y in parts:
            if b <= x or a >= y:
                new_parts.append((x, y))
            else:
                if x < a:
                    new_parts.append((x, a))
                if b < y:
                    new_parts.append((b, y))
        parts = new_parts
    return [(x, y) for x, y in parts if x < y]


def mostly_inside(start: int, end: int, ranges: list[Range], threshold: float = 0.5) -> bool:
    """Vrai si une plage recouvre plus de `threshold` de [start, end[ (ex: phrase dans un <pre>)."""
    length = max(1, end - start)
    for a, b in ranges:
        overlap = max(0, min(end, b) - max(start, a))
        if overlap / length > threshold:
            return True
    return False


def build_utf16_index_map(text: str) -> list[int]:
    """Mappe les indexes Python (codepoints) vers les indexes UTF-16 (Qt)."""
    m = [0] * (len(text) + 1)
    utf16_index = 0
    for i, ch in enumerate(text):
        m[i] = utf16_index
        utf16_index += 2 if ord(ch) > 0xFFFF else 1
    m[len(text)] = utf16_index
    return m


def build_ref_to_doc_map(ref: str, doc: str) -> Optional[list[int]]:
    """Mappe les index de `ref` vers ceux de `doc` (texte rendu par Qt). None si identiques."""
    if not doc or not ref or doc == ref:
        return None
    sm = difflib.SequenceMatcher(a=ref, b=doc, autojunk=False)
    m = [0] * (len(ref) + 1)
    for tag, i1, i2, j1, _j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i1, i2 + 1):
                m[k] = j1 + (k - i1)
        else:
            for k in range(i1, i2 + 1):
                m[k] = j1
    maxb = len(doc)
    return [min(max(v, 0), maxb) for v in m]
