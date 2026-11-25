"""Boucle de lecture phrase par phrase (thread) et nettoyage en fin de lecture."""
import logging
import threading
from typing import Callable

from PySide6.QtCore import Q_ARG, QCoreApplication, QMetaObject, Qt, QTimer

from ..core.state import STATE
from ..core.tts_engine import get_speed_multiplier

log = logging.getLogger(__name__)


def _speak_sentences(win, eng, voice) -> None:
    """Lit les phrases de STATE.playback a partir de sentence_index (thread de lecture)."""
    pb = STATE.playback
    log.debug("worker: demarrage, phrases=%d, start_idx=%d", len(pb.sentence_parts), pb.sentence_index)
    try:
        parts = pb.sentence_parts
        for idx in range(pb.sentence_index, len(parts)):
            if pb.stop_requested:
                log.debug("worker: stop_requested, sortie")
                break
            # Phrases dans un <pre> : ni lues ni surlignees
            if idx < len(pb.sentence_skip) and pb.sentence_skip[idx]:
                continue

            sentence = parts[idx].strip()
            if not sentence:
                continue
            pb.sentence_index = idx

            QMetaObject.invokeMethod(win, "apply_highlight_slot", Qt.QueuedConnection, Q_ARG(int, idx))

            try:
                sentence_tts = pb.sentence_parts_tts[idx]
            except IndexError:
                sentence_tts = sentence
            eng.speak_blocking(voice["token"], sentence_tts, rate=get_speed_multiplier())

            if pb.stop_requested:
                log.debug("worker: stop apres lecture phrase %d", idx)
                break
            if pb.pause_requested:
                log.debug("worker: pause apres phrase %d", idx)
                pb.sentence_index = idx
                break
        if not pb.pause_requested:
            pb.paused = False
    finally:
        log.debug("worker: fin")
        pb.current_thread = None


def start_playback_thread(win, eng, voice, playback_id: int, on_finished: Callable[[], None]) -> None:
    """Lance la lecture dans un thread ; en fin de lecture, appelle on_finished si rien ne l'a remplacee."""
    pb = STATE.playback

    def watcher():
        t = threading.Thread(target=_speak_sentences, args=(win, eng, voice), daemon=True)
        pb.current_thread = t
        t.start()
        t.join()

        def cleanup():
            if playback_id != pb.playback_token:
                return  # une autre lecture a pris le relais
            if pb.pause_requested or pb.paused:
                return
            pb.busy = False
            on_finished()

        # Retour dans le thread Qt. Sans objet contexte, un timer cree depuis un thread Python
        # ne se declenche jamais : la fin de lecture n'etait pas traitee.
        app = QCoreApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app, cleanup)

    QTimer.singleShot(50, lambda: threading.Thread(target=watcher, daemon=True).start())
