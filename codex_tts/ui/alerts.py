"""Petits messages a l'utilisateur : alerte "aucune selection", voix absente, lecture courte."""
import logging
import threading

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from ..core.state import STATE
from ..core.tts_engine import get_speed_multiplier

log = logging.getLogger(__name__)

NO_SELECTION_TEXT = "veuillez selectionner un texte"


def notify_no_voice(app: QApplication) -> None:
    msg = "Aucune voix OneCore detectee. Verifiez que les voix Windows sont installees."
    log.error(msg)
    try:
        QMessageBox.warning(app.activeWindow() or None, "SpeakToFR", msg)
    except Exception:
        log.exception("Affichage de l'alerte voix impossible")


def speak_short_message(message: str) -> None:
    """Lit un message court sans ouvrir la fenetre UI."""
    voice = STATE.current_voice()
    eng = STATE.current_engine()
    if not voice or eng is None:
        return
    speed = get_speed_multiplier()

    def worker():
        try:
            eng.speak_blocking(voice["token"], message, rate=speed)
        except Exception:
            log.exception("Lecture du message court impossible")

    threading.Thread(target=worker, daemon=True).start()


def show_no_selection_alert(app: QApplication) -> None:
    existing = STATE.ui.no_selection_box
    if existing is not None:
        try:
            existing.raise_()
            existing.activateWindow()
            return
        except RuntimeError:  # objet Qt deja detruit
            STATE.ui.no_selection_box = None
    try:
        parent = app.activeWindow() if app is not None else None
        box = QMessageBox(parent)
        box.setWindowTitle("SpeakToFR")
        box.setText(NO_SELECTION_TEXT)
        box.setIcon(QMessageBox.Warning)
        box.setStandardButtons(QMessageBox.Ok)
        box.setWindowModality(Qt.ApplicationModal)
        box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        box.setAttribute(Qt.WA_DeleteOnClose, True)
        box.finished.connect(lambda *_: setattr(STATE.ui, "no_selection_box", None))
        STATE.ui.no_selection_box = box
        box.show()
        box.raise_()
        box.activateWindow()
    except Exception:
        log.exception("Affichage de l'alerte 'aucune selection' impossible")
