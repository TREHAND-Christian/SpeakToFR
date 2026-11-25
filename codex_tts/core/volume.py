"""Volume et mode muet de SpeakToFR.

La voix est jouee par winsound (waveOut). Depuis Windows Vista, waveOutSetVolume
regle le volume de la session audio de l'application : seul SpeakToFR est
concerne, le volume general de Windows ne bouge pas, et le changement
s'applique meme au milieu d'une phrase.
"""
import ctypes
import logging

from .prefs import load_prefs, save_prefs

log = logging.getLogger(__name__)

_state = {"volume": 100, "muted": False}


def _apply() -> None:
    pct = 0 if _state["muted"] else max(0, min(100, int(_state["volume"])))
    level = int(round(pct * 0xFFFF / 100)) & 0xFFFF
    value = level | (level << 16)  # canal gauche (mot bas) + canal droit (mot haut)
    try:
        winmm = ctypes.windll.winmm
        winmm.waveOutSetVolume.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        res = winmm.waveOutSetVolume(None, value)
        if res != 0:
            log.warning("waveOutSetVolume a renvoye %s", res)
    except Exception:
        log.exception("Reglage du volume impossible")


def init_from_prefs() -> None:
    prefs = load_prefs() or {}
    try:
        _state["volume"] = max(0, min(100, int(prefs.get("volume", 100))))
    except (TypeError, ValueError):
        _state["volume"] = 100
    _state["muted"] = bool(prefs.get("muted", False))
    _apply()


def get_volume() -> int:
    return int(_state["volume"])


def is_muted() -> bool:
    return bool(_state["muted"])


def set_volume(pct: int, persist: bool = True) -> None:
    _state["volume"] = max(0, min(100, int(pct)))
    _apply()
    if persist:
        save_prefs({"volume": _state["volume"]})


def set_muted(muted: bool, persist: bool = True) -> None:
    _state["muted"] = bool(muted)
    _apply()
    if persist:
        save_prefs({"muted": _state["muted"]})
