"""Fonctions utilitaires transverses."""
import threading

from PySide6.QtCore import QTimer

from ..core.state import STATE
from ..services.clipboard import set_clipboard_text


def restart_current_sentence(
    debounce_ms: int = 0,
    stop_existing: bool = True,
    adjust_layout: bool = False,
):
    """Relance la lecture sur la phrase courante (debut de phrase), en reutilisant l'UI."""
    text = (STATE.last_text or "").strip()
    if not text or STATE.root is None:
        return

    idx = max(0, STATE.sentence_index)

    def relaunch():
        def worker():
            # Stop immediat juste avant de relancer (evite les coupures multiples pendant un drag de slider)
            if stop_existing:
                try:
                    STATE.stop_requested = True
                    voice = STATE.voices[STATE.current_voice_index] if STATE.voices else None
                    eng = STATE.engine_for(voice) if voice else None
                    if eng:
                        eng.stop()
                except Exception:
                    pass
                # Attendre la fin du thread courant pour eviter les chevauchements audio (hors thread UI)
                try:
                    t = STATE.current_thread
                    if t and t.is_alive():
                        t.join(timeout=1.0)
                except Exception:
                    pass
            
            # Re-initialisation des flags pour la nouvelle lecture
            STATE.pause_requested = False
            STATE.paused = False
            STATE.stop_requested = False

            def launch_on_ui():
                from ..ui.ui import speak_with_ui  # import local pour eviter cycles

                speak_with_ui(
                    STATE.root,
                    text,
                    start_index=idx,
                    reuse_ui=True,
                    stop_existing=False,  # Le stop a deja ete fait ici
                    adjust_layout=adjust_layout,
                    translate_text=False,  # Ne retraduit pas un texte deja prepare
                    display_html_override=getattr(STATE, "last_display_html", None),
                )

            # Rebasculer sur le thread Qt
            try:
                QTimer.singleShot(0, STATE.root, launch_on_ui)
            except Exception:
                QTimer.singleShot(0, launch_on_ui)

        threading.Thread(target=worker, daemon=True).start()

    if debounce_ms > 0:
        # Debounce : annule la relance precedente si une nouvelle arrive
        try:
            t = getattr(STATE, "restart_timer", None)
            if t is not None:
                t.stop()
        except Exception:
            pass

        timer = QTimer()
        timer.setSingleShot(True)
        timer.setInterval(debounce_ms)
        timer.timeout.connect(lambda: (setattr(STATE, "restart_timer", None), relaunch()))
        setattr(STATE, "restart_timer", timer)
        timer.start()
    else:
        relaunch()


def stop_playback(clear_clipboard: bool = True):
    """Arrete proprement la lecture et nettoie les flags/UI basiques."""
    print("[CodexTTS] stop_playback: demande d'arret")
    try:
        STATE.stop_requested = True
        STATE.pause_requested = False
        STATE.paused = False
        voice = STATE.voices[STATE.current_voice_index] if STATE.voices else None
        eng = STATE.engine_for(voice) if voice else None
        if eng:
            print("[CodexTTS] stop_playback: stop moteur")
            eng.stop()
    except Exception:
        pass

    t = STATE.current_thread
    if t and t.is_alive():
        try:
            print("[CodexTTS] stop_playback: attente du thread courant")
            t.join(timeout=1.0)
        except Exception:
            pass
    STATE.current_thread = None

    if clear_clipboard:
        try:
            set_clipboard_text("")
        except Exception:
            pass
    print("[CodexTTS] stop_playback: termine")
