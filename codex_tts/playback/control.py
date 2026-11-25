"""Controle de la lecture : relance sur la phrase courante, arret propre."""
import logging
import threading

from PySide6.QtCore import QTimer

from ..core.state import STATE
from ..services.clipboard import set_clipboard_text

log = logging.getLogger(__name__)


def _stop_engine_and_join(timeout: float = 1.0) -> None:
    """Coupe le moteur et attend la fin du thread de lecture courant."""
    eng = STATE.current_engine()
    if eng:
        try:
            eng.stop()
        except Exception:
            log.exception("Arret du moteur TTS impossible")
    t = STATE.playback.current_thread
    if t and t.is_alive() and t is not threading.current_thread():
        t.join(timeout=timeout)


def restart_current_sentence(
    debounce_ms: int = 0,
    stop_existing: bool = True,
    adjust_layout: bool = False,
):
    """Relance la lecture sur la phrase courante (debut de phrase), en reutilisant l'UI."""
    pb = STATE.playback
    text = (pb.last_text or "").strip()
    if not text or STATE.ui.root is None:
        return

    idx = max(0, pb.sentence_index)

    def relaunch():
        def worker():
            # La fin de la lecture interrompue ne doit pas fermer l'interface ni remettre la barre a l'arret
            pb.playback_token += 1
            # Stop immediat juste avant de relancer (evite les coupures multiples pendant un drag de slider)
            if stop_existing:
                pb.stop_requested = True
                # Attendre la fin du thread courant pour eviter les chevauchements audio (hors thread UI)
                _stop_engine_and_join()

            # Re-initialisation des flags pour la nouvelle lecture
            pb.clear_flags()

            def launch_on_ui():
                from ..ui.ui_main import speak_with_ui  # import local pour eviter cycles

                speak_with_ui(
                    STATE.ui.root,
                    text,
                    start_index=idx,
                    reuse_ui=True,
                    stop_existing=False,  # Le stop a deja ete fait ici
                    adjust_layout=adjust_layout,
                    translate_text=False,  # Ne retraduit pas un texte deja prepare
                    display_html_override=pb.last_display_html,
                )

            # Rebasculer sur le thread Qt
            QTimer.singleShot(0, STATE.ui.root, launch_on_ui)

        threading.Thread(target=worker, daemon=True).start()

    if debounce_ms > 0:
        # Debounce : annule la relance precedente si une nouvelle arrive
        if pb.restart_timer is not None:
            pb.restart_timer.stop()

        timer = QTimer()
        timer.setSingleShot(True)
        timer.setInterval(debounce_ms)

        def fire():
            pb.restart_timer = None
            relaunch()

        timer.timeout.connect(fire)
        pb.restart_timer = timer
        timer.start()
    else:
        relaunch()


def stop_playback(clear_clipboard: bool = True):
    """Arrete proprement la lecture et nettoie les flags."""
    log.debug("stop_playback: demande d'arret")
    STATE.playback.request_stop()
    _stop_engine_and_join()
    STATE.playback.current_thread = None

    if clear_clipboard:
        try:
            set_clipboard_text("")
        except Exception:
            log.exception("Nettoyage du presse-papiers impossible")
    log.debug("stop_playback: termine")
