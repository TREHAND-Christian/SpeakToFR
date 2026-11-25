"""Creation et nettoyage de la fenetre de controle, application des preferences voix/vitesse."""
import logging

from ..core.prefs import load_prefs
from ..core.state import STATE
from ..core.tts_engine import set_voice_by_index
from ..services.clipboard import set_clipboard_text
from .app_actions import ACTIONS
from .window import MODE_COMPLET, ControlWindow

log = logging.getLogger(__name__)

_DEFAULT_VOICE = "Microsoft Paul"
_voice_prefs_applied = False


def cleanup_ui(clear_clipboard: bool = True) -> None:
    """Ferme la fenetre de controle et (optionnel) vide le presse-papiers."""
    win = STATE.ui.ctrl_window
    if win is not None:
        try:
            win.close()
        except RuntimeError:  # objet Qt deja detruit
            pass
    STATE.ui.clear_window()

    if clear_clipboard:
        try:
            set_clipboard_text("")
        except Exception:
            log.exception("Nettoyage du presse-papiers impossible")


def create_ctrl_window(text_len: int, highlight_callback) -> ControlWindow:
    if STATE.ui.ctrl_window is not None:
        try:
            STATE.ui.ctrl_window.close()
        except RuntimeError:
            pass
        STATE.ui.ctrl_window = None

    win = ControlWindow(text_len, highlight_callback, cleanup_callback=cleanup_ui)
    # Les modes reglage/discret sont remplaces par la barre flottante
    win.mode_container.setVisible(False)
    win.voice_combo.blockSignals(True)
    win.speed_slider.blockSignals(True)
    win.set_voice_items([v["desc"] for v in STATE.voices], STATE.current_voice_desc)

    prefs = load_prefs() or {}

    # Vitesse : 1.0 si absente
    speed_val = float(prefs.get("speed", STATE.speed_value or 1.0))
    win.speed_slider.setValue(int(speed_val * 10))
    win.speed_label.setText(f"Vitesse {speed_val:.1f}")
    STATE.speed_value = speed_val

    # Voix : celle des preferences, sinon Microsoft Paul si presente, sinon la premiere
    desc_list = [v["desc"] for v in STATE.voices]
    if desc_list:
        target = prefs.get("voice") or _DEFAULT_VOICE
        if target not in desc_list:
            target = _DEFAULT_VOICE if _DEFAULT_VOICE in desc_list else desc_list[0]
        index = desc_list.index(target)
        win.voice_combo.setCurrentIndex(index)
        set_voice_by_index(index)

    win.voice_combo.blockSignals(False)
    win.speed_slider.blockSignals(False)

    STATE.ui.ctrl_window = win
    STATE.ui.voice_selector = win.voice_combo
    return win


def present_ctrl_window(win: ControlWindow) -> None:
    """Affiche la fenetre texte si l'option est cochee ; sinon elle reste cachee (la lecture continue)."""
    if ACTIONS.show_text_window():
        if getattr(win, "_mode", MODE_COMPLET) != MODE_COMPLET:
            win.set_display_mode(MODE_COMPLET)
        win.show()
        win.raise_()
    else:
        win.hide()


def finish_playback_ui() -> None:
    """Fin de lecture : garde la fenetre texte si elle est affichee (Play relira), sinon la ferme.

    Le presse-papiers n'est plus vide ici : il pouvait effacer ce que l'utilisateur avait copie.
    """
    win = STATE.ui.ctrl_window
    if win is not None and ACTIONS.show_text_window():
        try:
            if win.isVisible():
                win.clear_highlight()
                win.set_info("Lecture terminée (Play pour relire)")
                win.sync_pause_button()
                return
        except RuntimeError:  # fenetre Qt deja detruite
            pass
    cleanup_ui(clear_clipboard=False)


def apply_voice_speed_prefs_once() -> None:
    """Applique voix/vitesse des preferences au premier demarrage de lecture seulement."""
    global _voice_prefs_applied
    if _voice_prefs_applied:
        return
    prefs = load_prefs() or {}
    target_voice = prefs.get("voice")
    if target_voice and STATE.voices:
        for i, v in enumerate(STATE.voices):
            if v.get("desc") == target_voice:
                set_voice_by_index(i)
                break
    if "speed" in prefs:
        try:
            STATE.speed_value = float(prefs["speed"])
        except (TypeError, ValueError):
            STATE.speed_value = 1.0
    _voice_prefs_applied = True
