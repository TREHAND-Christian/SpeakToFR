"""Traduction vers le francais pour la lecture TTS (googletrans).

- translate_to_fr(texte) : un texte, decoupe en blocs d'environ 4 500 caracteres.
- translate_many(textes) : plusieurs morceaux (noeuds texte d'un HTML) envoyes ensemble,
  numerotes, en une requete par bloc au lieu d'une requete par morceau.
- Les traductions reussies sont gardees en cache : relire un texte deja traduit est instantane.
"""
from __future__ import annotations

import functools
import logging
import re
import threading
from collections import OrderedDict

try:
    from langdetect import detect
except Exception:  # pragma: no cover
    detect = None

try:
    from googletrans import Translator  # type: ignore
except Exception:  # pragma: no cover
    Translator = None

log = logging.getLogger(__name__)

MAX_CHUNK = 4500  # Google accepte environ 5 000 caracteres par requete
_CACHE_SIZE = 2000
_cache: "OrderedDict[str, str]" = OrderedDict()
_cache_lock = threading.Lock()
_MARKER = re.compile(r"\[\[\s*(\d+)\s*\]\]")


@functools.lru_cache(maxsize=1)
def _translator():
    if Translator is None:
        return None
    try:
        return Translator()
    except Exception:
        return None


# ---------------------------------------------------------------- cache
def _cache_get(text: str):
    with _cache_lock:
        val = _cache.get(text)
        if val is not None:
            _cache.move_to_end(text)
        return val


def _cache_put(text: str, translated: str) -> None:
    with _cache_lock:
        _cache[text] = translated
        _cache.move_to_end(text)
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# ---------------------------------------------------------------- appel Google
def _request(text: str):
    """Une requete de traduction ; renvoie le texte traduit, ou None en cas d'echec."""
    tr = _translator()
    if tr is None:
        return None
    res = tr.translate(text, dest="fr")
    # googletrans peut renvoyer une liste ou un objet
    if isinstance(res, list):
        res = res[0] if res else None
    return getattr(res, "text", None) or None


def _has_letters(text: str) -> bool:
    return any(ch.isalpha() for ch in text)


def _split_keep_space(text: str) -> tuple[str, str, str]:
    """(espaces de debut, coeur, espaces de fin) : les espaces autour comptent dans le HTML."""
    core = text.strip()
    if not core:
        return text, "", ""
    start = text.index(core[0])
    end = start + len(core)
    return text[:start], core, text[end:]


def _split_long_line(line: str, max_len: int) -> list[str]:
    """Coupe une ligne trop longue aux fins de phrase (sinon aux espaces)."""
    pieces = re.split(r"(?<=[.!?;:])\s+", line)
    out: list[str] = []
    buf = ""
    for p in pieces:
        while len(p) > max_len:  # phrase geante : coupe aux espaces
            cut = p.rfind(" ", 0, max_len)
            cut = cut if cut > 0 else max_len
            if buf:
                out.append(buf)
                buf = ""
            out.append(p[:cut])
            p = p[cut:].lstrip()
        if buf and len(buf) + 1 + len(p) > max_len:
            out.append(buf)
            buf = p
        else:
            buf = f"{buf} {p}" if buf else p
    if buf:
        out.append(buf)
    return out


def _chunk(text: str, max_len: int = MAX_CHUNK) -> list[str]:
    """Decoupe le texte en morceaux <= max_len en coupant de preference sur les retours ligne."""
    if len(text) <= max_len:
        return [text]
    out: list[str] = []
    buf: list[str] = []
    cur = 0
    for ln in text.splitlines(keepends=True):
        if len(ln) > max_len:
            if buf:
                out.append("".join(buf))
                buf, cur = [], 0
            end = ln[len(ln.rstrip("\r\n")):]
            pieces = _split_long_line(ln.rstrip("\r\n"), max_len)
            out.extend(p + " " for p in pieces[:-1])
            out.append(pieces[-1] + end)
            continue
        if cur + len(ln) > max_len and buf:
            out.append("".join(buf))
            buf, cur = [], 0
        buf.append(ln)
        cur += len(ln)
    if buf:
        out.append("".join(buf))
    return out


# ---------------------------------------------------------------- API
def translate_to_fr(text: str) -> str:
    """Retourne le texte traduit en francais (essaie toujours), sinon le texte d'origine."""
    if not text or text.strip() == "":
        return text
    cached = _cache_get(text)
    if cached is not None:
        return cached
    if _translator() is None:
        log.warning("translate_to_fr: aucun backend de traduction disponible")
        return text
    out: list[str] = []
    failed = False
    err_count = 0
    for chunk in _chunk(text):
        lead, core, trail = _split_keep_space(chunk)
        if not core or not _has_letters(core):
            out.append(chunk)
            continue
        done = _cache_get(core)
        if done is None:
            try:
                done = _request(core)
            except Exception as e:
                done = None
                err_count += 1
                if err_count <= 3:
                    log.warning("translate_to_fr: erreur sur un bloc, texte brut conserve (%s)", e)
            if done is None:
                failed = True
                done = core
            else:
                _cache_put(core, done)
        out.append(lead + done + trail)
    result = "".join(out)
    if not failed:
        _cache_put(text, result)
    return result


def translate_many(texts: list[str]) -> list[str]:
    """Traduit plusieurs morceaux en peu de requetes, dans l'ordre ; espaces autour conserves.

    Les morceaux sans lettres (puces, chiffres, ponctuation) ne sont pas envoyes. Chaque morceau
    est numerote "[[i]]" sur sa ligne ; si Google perd un numero, ce morceau est traduit seul.
    """
    results = list(texts)
    todo: dict[str, list[int]] = {}  # coeur -> positions (un meme texte n'est envoye qu'une fois)
    parts = []
    for i, t in enumerate(texts):
        lead, core, trail = _split_keep_space(t or "")
        parts.append((lead, core, trail))
        if not core or not _has_letters(core):
            continue
        cached = _cache_get(core)
        if cached is not None:
            results[i] = lead + cached + trail
            continue
        todo.setdefault(core, []).append(i)
    if not todo:
        return results
    if _translator() is None:
        log.warning("translate_many: aucun backend de traduction disponible")
        return results

    cores = list(todo)
    translated: dict[str, str] = {}

    # Blocs de lignes "[[n]] texte" ne depassant pas MAX_CHUNK
    batches: list[list[int]] = []
    cur: list[int] = []
    size = 0
    for n, core in enumerate(cores):
        line_len = len(core) + 8
        if cur and size + line_len > MAX_CHUNK:
            batches.append(cur)
            cur, size = [], 0
        cur.append(n)
        size += line_len
    if cur:
        batches.append(cur)

    for batch in batches:
        # Un morceau trop long pour un bloc partira seul (translate_to_fr le decoupe)
        if len(batch) == 1 and len(cores[batch[0]]) + 8 > MAX_CHUNK:
            continue
        joined = "\n".join(f"[[{n}]] {re.sub(r'\s+', ' ', cores[n])}" for n in batch)
        try:
            out = _request(joined)
        except Exception as e:
            log.warning("translate_many: erreur sur un bloc (%s), traduction morceau par morceau", e)
            out = None
        if not out:
            continue
        pieces = _MARKER.split(out)  # [avant, n1, texte1, n2, texte2, ...]
        for k in range(1, len(pieces) - 1, 2):
            try:
                n = int(pieces[k])
            except ValueError:
                continue
            # Une seule ligne par morceau : une ligne en plus vient d'un numero perdu (repli pour celui-la)
            text_fr = pieces[k + 1].strip().splitlines()[0].strip() if pieces[k + 1].strip() else ""
            if n in batch and text_fr and cores[n] not in translated:
                translated[cores[n]] = text_fr
        missing = sum(1 for n in batch if cores[n] not in translated)
        if missing:
            log.info("translate_many: %d morceau(x) sur %d sans numero, traduits seuls", missing, len(batch))

    for core in cores:
        if core in translated:
            _cache_put(core, translated[core])
            fr = translated[core]
        else:
            fr = translate_to_fr(core)  # repli : seul (avec cache)
        for i in todo[core]:
            lead, _, trail = parts[i]
            results[i] = lead + fr + trail
    return results
