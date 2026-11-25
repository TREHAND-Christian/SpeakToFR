"""Correspondance entre le texte rendu par Qt et le texte de la page affichee par Chromium.

Les phrases sont decoupees sur le texte du document Qt (cache) ; Chromium affiche le meme HTML.
Les deux moteurs n'ont pas les memes espaces (retours ligne, puces, images...), mais les
caracteres visibles sont identiques : on repere donc une phrase par le nombre de caracteres
visibles qui la precedent. Les index sont comptes en unites UTF-16, comme les chaines JavaScript.
"""
from __future__ import annotations

# Caracteres ignores des deux cotes (espaces, objet image de Qt, caracteres invisibles).
# La meme liste sert a construire l'expression reguliere JavaScript (voir js_ignored_class).
IGNORED_CHARS = (
    "\t\n\x0b\x0c\r   "
    + "".join(chr(c) for c in range(0x2000, 0x200B))
    + "    　﻿"
    + "￼­​‌‍⁠"
)
_IGNORED = frozenset(IGNORED_CHARS)


def _units(ch: str) -> int:
    return 2 if ord(ch) > 0xFFFF else 1


def visible_prefix(text: str) -> list[int]:
    """prefix[i] = nombre d'unites visibles dans text[:i] (longueur len(text) + 1)."""
    out = [0] * (len(text) + 1)
    n = 0
    for i, ch in enumerate(text):
        if ch not in _IGNORED:
            n += _units(ch)
        out[i + 1] = n
    return out


def visible_text(text: str) -> str:
    """Texte sans les caracteres ignores."""
    return "".join(ch for ch in text if ch not in _IGNORED)


def visible_key(text: str, limit: int = 24) -> str:
    """Debut visible d'une phrase : sert a recaler la position si les deux textes divergent."""
    return visible_text(text)[:limit]


def segments_for_web(text: str, prefix: list[int], segments) -> list[list]:
    """[(debut, fin)] dans `text` -> [[debut_visible, fin_visible, cle]] pour la page web."""
    out = []
    n = len(text)
    for s, e in segments:
        s = max(0, min(int(s), n))
        e = max(s, min(int(e), n))
        vs, ve = prefix[s], prefix[e]
        if ve > vs:
            out.append([vs, ve, visible_key(text[s:e])])
    return out


def js_ignored_class() -> str:
    """Classe de caracteres JavaScript equivalente a IGNORED_CHARS (ex. "[\\t\\n...]")."""
    return "[" + "".join(f"\\u{ord(c):04x}" for c in IGNORED_CHARS) + "]"
