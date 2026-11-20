"""Controle du moteur TTS (stop/pause/reprise, voix, vitesse)."""
import logging
import threading

from ..core.state import STATE
from ..playback.control import restart_current_sentence

log = logging.getLogger(__name__)


def join_worker(timeout: float = 1.0) -> None:
    """Attend la fin du thread de lecture (sauf si on est dedans)."""
    t = STATE.playback.current_thread
    if not t or not t.is_alive() or t is threading.current_thread():
        return
    try:
        t.join(timeout=timeout)
    except RuntimeError:
        pass
    if not t.is_alive():
        STATE.playback.current_thread = None


def tts_pause():
    eng = STATE.current_engine()
    if not eng:
        return
    pb = STATE.playback
    pb.pause_requested = True
    pb.stop_requested = False
    pb.paused = True
    # Coupe la phrase en cours; la reprise se fera au debut de la phrase
    eng.stop()


def tts_resume():
    pb = STATE.playback
    if not pb.paused:
        return
    pb.clear_flags()
    # Reprise = relance sur la phrase courante, comme un changement de voix.
    restart_current_sentence(stop_existing=True, adjust_layout=False, debounce_ms=0)


def set_voice_by_index(index: int):
    if not STATE.voices:
        return
    index = index % len(STATE.voices)
    STATE.current_voice_index = index
    STATE.current_voice_desc = STATE.voices[index]["desc"]

    selector = STATE.ui.voice_selector
    if selector is not None:
        try:
            selector.setCurrentText(STATE.current_voice_desc)
        except RuntimeError:  # widget Qt deja detruit
            STATE.ui.voice_selector = None


def get_speed_multiplier() -> float:
    try:
        val = float(STATE.speed_value)
    except (TypeError, ValueError):
        val = 1.0
    return max(0.0, min(2.0, val))
