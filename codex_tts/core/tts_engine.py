"""Fonctions de controle du moteur TTS (start/stop/pause/voix)."""
import threading

from ..core.state import STATE
from ..playback.control import restart_current_sentence
from ..text.sentences import split_sentences, split_sentences_with_positions


def _current_voice():
    if not STATE.voices:
        return None
    return STATE.voices[STATE.current_voice_index % len(STATE.voices)]


def _join_worker(timeout: float = 1.0):
    t = STATE.current_thread
    if not t or not t.is_alive():
        return
    # Eviter de se joindre soi-meme
    if t is threading.current_thread():
        return
    try:
        t.join(timeout=timeout)
    except Exception:
        pass
    if not t.is_alive():
        STATE.current_thread = None


def tts_stop():
    v = _current_voice()
    if v:
        eng = STATE.engine_for(v)
        if eng:
            try:
                eng.stop()
            except Exception:
                pass
    STATE.stop_requested = True
    STATE.pause_requested = False
    STATE.paused = False
    _join_worker()


def tts_pause():
    v = _current_voice()
    if not v:
        return
    eng = STATE.engine_for(v)
    if not eng:
        return
    STATE.pause_requested = True
    STATE.stop_requested = False
    STATE.paused = True
    try:
        # Coupe la phrase en cours; la reprise se fera au debut de la phrase
        eng.stop()
    except Exception:
        pass


def tts_resume():
    if not STATE.paused:
        return
    
    STATE.paused = False
    STATE.pause_requested = False
    STATE.stop_requested = False
    
    # La logique de reprise est maintenant plus fiable en relancant la lecture
    # sur la phrase courante, similaire a un changement de voix.
    restart_current_sentence(stop_existing=True, adjust_layout=False, debounce_ms=0)


def set_voice_by_index(index: int):
    if not STATE.voices:
        return
    index = index % len(STATE.voices)
    STATE.current_voice_index = index
    STATE.current_voice_desc = STATE.voices[index]["desc"]

    selector = getattr(STATE, "voice_selector", None)
    if selector is not None:
        try:
            selector.setCurrentText(STATE.current_voice_desc)
        except Exception:
            STATE.voice_selector = None


def get_speed_multiplier() -> float:
    try:
        val = float(getattr(STATE, "speed_value", 1.0))
    except Exception:
        val = 1.0
    return max(0.0, min(2.0, val))
