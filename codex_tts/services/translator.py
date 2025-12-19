"""Traduction simple vers le francais pour la lecture TTS."""
from __future__ import annotations

import functools

try:
    from langdetect import detect
except Exception:  # pragma: no cover
    detect = None

try:
    from googletrans import Translator  # type: ignore
except Exception:  # pragma: no cover
    Translator = None


@functools.lru_cache(maxsize=1)
def _translator():
    if Translator is None:
        return None
    try:
        return Translator()
    except Exception:
        return None


def _chunk(text: str, max_len: int = 4000) -> list[str]:
    """Decoupe le texte en morceaux <= max_len en essayant de couper sur les retours ligne."""
    if len(text) <= max_len:
        return [text]
    out: list[str] = []
    buf: list[str] = []
    cur = 0
    for ln in text.splitlines(keepends=True):
        if cur + len(ln) > max_len and buf:
            out.append("".join(buf))
            buf = []
            cur = 0
        buf.append(ln)
        cur += len(ln)
    if buf:
        out.append("".join(buf))
    return out


def translate_to_fr(text: str) -> str:
    """Retourne le texte traduit en francais (essaie toujours), sinon le texte d'origine."""
    if not text or text.strip() == "":
        return text
    tr = _translator()
    if tr is None:
        print("[CodexTTS] translate_to_fr: aucun backend de traduction disponible (Translator None)")
        return text
    try:
        parts = _chunk(text, max_len=2000)
        out: list[str] = []
        err_count = 0
        for chunk in parts:
            try:
                res = tr.translate(chunk, dest="fr")
                # googletrans peut renvoyer une liste ou un objet
                if isinstance(res, list):
                    res = res[0] if res else None
                out.append(getattr(res, "text", None) or chunk)
            except Exception as e:
                err_count += 1
                if err_count <= 3:
                    print(f"[CodexTTS] translate_to_fr: erreur sur un chunk, fallback chunk brut ({e})")
                out.append(chunk)
        return "".join(out)
    except Exception as e:
        print(f"[CodexTTS] translate_to_fr: erreur globale, retour texte original ({e})")
        return text
