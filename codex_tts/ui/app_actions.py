"""Actions communes a la barre flottante, a la fenetre Options et au menu de la zone de notification."""
import logging
import threading
from typing import Callable, Optional

from ..core import volume
from ..core.prefs import load_prefs, save_prefs
from ..core.state import STATE
from ..core.tts_engine import set_voice_by_index, tts_pause, tts_resume
from ..playback.control import restart_current_sentence, stop_playback
from .bus import BUS

log = logging.getLogger(__name__)

TEST_PHRASE = "Bonjour, ceci est un test de la voix."
SPEED_MIN = 0.5
SPEED_MAX = 2.0
NO_RESPONSE_TEXT = "Aucune réponse chargée : ouvre une conversation dans Claude Desktop."
INFO_LOADED = "Dernière réponse de Claude (Play pour la lire)"
INFO_LAST_READ = "Dernière lecture (Play pour la relire)"


def pref_bool(key: str, default: bool) -> bool:
    return bool((load_prefs() or {}).get(key, default))


class AppActions:
    """Point unique pour piloter la lecture et les reglages depuis n'importe quelle partie de l'UI."""

    def __init__(self) -> None:
        self.service_paused = False
        self.minibar = None
        self.claude_available = False
        self._show_text: Optional[bool] = None
        self._dim_unfocused: Optional[bool] = None
        self._selection_mode: Optional[bool] = None
        self.selection = None  # SelectionWatcher (texte selectionne hors Claude Desktop)
        self._read_partial: Optional[bool] = None
        self._queue: list = []  # morceaux a lire a la suite (reponses intermediaires)
        # Derniere reponse de la conversation affichee dans Claude Desktop
        self._loaded_text = ""
        self._loaded_fresh = False  # pas encore lue : le prochain Play la lit
        self._on_service_paused: Optional[Callable[[bool], None]] = None
        self._get_auto_read: Optional[Callable[[], bool]] = None
        self._set_auto_read: Optional[Callable[[bool], None]] = None
        self._get_autostart: Optional[Callable[[], bool]] = None
        self._set_autostart: Optional[Callable[[bool], None]] = None

    def configure(
        self,
        *,
        on_service_paused=None,
        get_auto_read=None,
        set_auto_read=None,
        get_autostart=None,
        set_autostart=None,
        claude_available: bool = False,
    ) -> None:
        """Branche les fonctions fournies par main.py (raccourci, lecteur Claude Desktop, demarrage Windows)."""
        self._on_service_paused = on_service_paused
        self._get_auto_read = get_auto_read
        self._set_auto_read = set_auto_read
        self._get_autostart = get_autostart
        self._set_autostart = set_autostart
        self.claude_available = bool(claude_available)

    # ---------------------------------------------------------------- etat
    def is_playing(self) -> bool:
        """Lecture demandee et en cours (traduction comprise), hors pause."""
        pb = STATE.playback
        return bool(pb.busy and not pb.paused)

    def is_paused(self) -> bool:
        return bool(STATE.playback.paused)

    def is_active(self) -> bool:
        """Il y a quelque chose a arreter : traduction, lecture ou pause."""
        pb = STATE.playback
        return bool(pb.busy or pb.paused)

    def has_last_text(self) -> bool:
        return bool((STATE.playback.last_text or "").strip())

    # ---------------------------------------------------------------- mode selection
    def selection_mode(self) -> bool:
        """Hors de Claude Desktop, du texte selectionne active la barre et Play le lit."""
        if self._selection_mode is None:
            self._selection_mode = pref_bool("bar_selection_mode", True)
        return self._selection_mode

    def set_selection_mode(self, enabled: bool) -> None:
        self._selection_mode = bool(enabled)
        save_prefs({"bar_selection_mode": bool(enabled)})
        self.update_selection_watcher()
        BUS.settings_changed.emit()

    def update_selection_watcher(self) -> None:
        if self.selection is not None:
            self.selection.set_enabled(self.selection_mode() and not self.service_paused)

    def selection_active(self) -> bool:
        """Du texte est selectionne dans l'appli au premier plan, et ce n'est pas Claude Desktop."""
        sel = self.selection
        if sel is None or not sel.enabled or not sel.has_selection:
            return False
        # Verification immediate : des le retour dans Claude Desktop, la selection ne compte plus
        # (sans attendre le prochain passage de la surveillance)
        from ..services.foreground import CLAUDE_DESKTOP_EXES, exe_name, foreground_pid

        try:
            if exe_name(foreground_pid()) in CLAUDE_DESKTOP_EXES:
                sel.has_selection = False
                return False
        except Exception:
            pass
        return True

    def _last_read_is_claude(self) -> bool:
        pb = STATE.playback
        return self.has_last_text() and pb.last_origin == "claude"

    def read_selection(self) -> None:
        """Lit la selection de l'appli au premier plan, comme Ctrl+Alt+Entree."""
        from ..services.hotkeys import copy_selection_and_tag  # import local (win32)

        self.clear_queue()
        threading.Thread(
            target=copy_selection_and_tag, kwargs={"release_modifiers": False}, daemon=True
        ).start()

    # ---------------------------------------------------------------- reponse chargee
    def loaded_text(self) -> str:
        return self._loaded_text

    def set_loaded_text(self, text: str, fresh: bool = True) -> None:
        """Derniere reponse de la conversation affichee dans Claude Desktop.

        fresh=True : pas encore lue, le prochain Play la lira (conversation ouverte ou changee).
        fresh=False : elle est lue tout de suite (lecture automatique).
        """
        text = (text or "").strip()
        if not text:
            return
        if text == self._loaded_text and not fresh:
            self._loaded_fresh = False
            return
        if text == self._loaded_text:
            return
        self._loaded_text = text
        self._loaded_fresh = bool(fresh)
        # Fenetre texte ouverte sans lecture : elle montre la nouvelle reponse
        if fresh and STATE.ui.ctrl_window is not None and not self.is_active() and self.show_text_window():
            self.open_idle_text_window()
        BUS.settings_changed.emit()

    # ---------------------------------------------------------------- file d'attente
    def read_partial(self) -> bool:
        """Lire aussi les reponses intermediaires de Claude Desktop, au fil de l'eau."""
        if self._read_partial is None:
            self._read_partial = pref_bool("claude_read_partial", True)
        return self._read_partial

    def set_read_partial(self, enabled: bool) -> None:
        self._read_partial = bool(enabled)
        save_prefs({"claude_read_partial": bool(enabled)})
        BUS.settings_changed.emit()

    def enqueue_reading(self, text: str, origin: str = "claude") -> None:
        """Lit le texte tout de suite, ou a la suite de la lecture en cours (sans la couper)."""
        text = (text or "").strip()
        if not text:
            return
        self._queue.append((text, origin))
        if not self.is_active():
            self.play_next_queued()

    def play_next_queued(self) -> bool:
        if not self._queue or STATE.ui.root is None:
            return False
        from .ui_main import speak_with_ui  # import local (evite les cycles)

        text, origin = self._queue.pop(0)
        speak_with_ui(STATE.ui.root, text=text, reuse_ui=True, translate_text=True, origin=origin)
        return True

    def clear_queue(self) -> None:
        self._queue.clear()

    # ---------------------------------------------------------------- lecture
    def play_pause(self) -> None:
        pb = STATE.playback
        try:
            if pb.paused:
                tts_resume()
            elif self.is_playing():
                tts_pause()
            elif self.selection_active():
                self.read_selection()
            else:
                self.play_last()
        except Exception:
            log.exception("Lecture/pause impossible")
        self._sync_ctrl_window()
        BUS.settings_changed.emit()

    def play_last(self) -> None:
        """Rien en cours : reponse de Claude Desktop (chargee, ou derniere lue), jamais une ancienne selection.

        - reponse chargee pas encore lue -> on la lit ;
        - derniere lecture = une reponse de Claude -> on la relit sans retraduire ;
        - derniere lecture = une selection -> on revient a la reponse chargee de Claude.
        """
        pb = STATE.playback
        root = STATE.ui.root
        self.clear_queue()
        if self._loaded_text and root is not None and (self._loaded_fresh or not self._last_read_is_claude()):
            from .ui_main import speak_with_ui  # import local (evite les cycles)

            self._loaded_fresh = False
            speak_with_ui(root, text=self._loaded_text, reuse_ui=True, translate_text=True, origin="claude")
        elif self.has_last_text():
            pb.sentence_index = 0
            pb.clear_flags()
            pb.busy = True  # la barre passe en "pause" sans attendre la relance
            restart_current_sentence(stop_existing=True, adjust_layout=False)

    def stop(self) -> None:
        self.clear_queue()
        win = STATE.ui.ctrl_window
        try:
            if win is not None:
                win.on_stop_clicked()
            else:
                threading.Thread(target=stop_playback, kwargs={"clear_clipboard": False}, daemon=True).start()
        except RuntimeError:  # fenetre Qt deja detruite
            threading.Thread(target=stop_playback, kwargs={"clear_clipboard": False}, daemon=True).start()
        except Exception:
            log.exception("Arret impossible")
        STATE.playback.busy = False
        BUS.settings_changed.emit()

    def test_voice(self) -> None:
        if self.is_playing():
            return
        from .alerts import speak_short_message  # import local (evite les cycles)

        speak_short_message(TEST_PHRASE)

    # ---------------------------------------------------------------- son
    def toggle_mute(self) -> None:
        self.set_muted(not volume.is_muted())

    def set_muted(self, muted: bool) -> None:
        volume.set_muted(muted)
        BUS.settings_changed.emit()

    def set_volume(self, pct: int) -> None:
        volume.set_volume(pct)
        BUS.settings_changed.emit()

    def set_speed(self, value: float) -> None:
        val = max(SPEED_MIN, min(SPEED_MAX, round(float(value), 2)))
        STATE.speed_value = val
        save_prefs({"speed": val})
        win = STATE.ui.ctrl_window
        if win is not None:
            try:
                win.sync_speed(val)
            except RuntimeError:
                pass
        if self.is_playing():
            restart_current_sentence(debounce_ms=250, stop_existing=True, adjust_layout=False)
        BUS.settings_changed.emit()

    def set_voice(self, index: int) -> None:
        if not STATE.voices:
            return
        index = index % len(STATE.voices)
        desc = STATE.voices[index]["desc"]
        if desc == STATE.current_voice_desc:
            return
        # Met aussi a jour la liste de la fenetre texte, qui relance la phrase en cours si besoin
        set_voice_by_index(index)
        save_prefs({"voice": desc})
        BUS.settings_changed.emit()

    # ---------------------------------------------------------------- fenetres
    def show_text_window(self) -> bool:
        if self._show_text is None:
            self._show_text = pref_bool("show_text", False)
        return self._show_text

    def set_show_text(self, show: bool) -> None:
        from .ctrl_window_factory import cleanup_ui, present_ctrl_window  # import local (evite les cycles)

        self._show_text = bool(show)
        save_prefs({"show_text": bool(show)})
        win = STATE.ui.ctrl_window
        try:
            if self.is_active():
                # Lecture en cours : on montre ou on cache simplement la fenetre
                if win is not None:
                    present_ctrl_window(win)
            elif show:
                # Rien en lecture : la fenetre montre la derniere reponse (Play la lira)
                self.open_idle_text_window()
            elif win is not None:
                cleanup_ui(clear_clipboard=False)
        except RuntimeError:  # fenetre Qt deja detruite
            pass
        BUS.settings_changed.emit()

    def toggle_text_window(self) -> None:
        self.set_show_text(not self.show_text_window())

    def _idle_content(self) -> tuple:
        pb = STATE.playback
        if self._loaded_text and (self._loaded_fresh or not self._last_read_is_claude()):
            return self._loaded_text, None, INFO_LOADED
        if self.has_last_text():
            return pb.last_text, pb.last_display_html, INFO_LAST_READ
        return NO_RESPONSE_TEXT, None, ""

    def open_idle_text_window(self) -> None:
        from .ui_main import show_idle_text_window  # import local (evite les cycles)

        text, html, info = self._idle_content()
        try:
            show_idle_text_window(text, html, info)
        except Exception:
            log.exception("Ouverture de la fenetre texte impossible")

    def dim_unfocused(self) -> bool:
        """Griser la barre quand Claude Desktop n'est pas au premier plan."""
        if self._dim_unfocused is None:
            self._dim_unfocused = pref_bool("bar_dim_unfocused", True)
        return self._dim_unfocused

    def set_dim_unfocused(self, enabled: bool) -> None:
        self._dim_unfocused = bool(enabled)
        save_prefs({"bar_dim_unfocused": bool(enabled)})
        BUS.settings_changed.emit()

    def bar_visible(self) -> bool:
        try:
            return bool(self.minibar is not None and self.minibar.isVisible())
        except RuntimeError:
            return False

    def set_bar_visible(self, visible: bool) -> None:
        if self.minibar is None:
            return
        if visible:
            self.minibar.ensure_on_top()
        else:
            self.minibar.hide()
        BUS.settings_changed.emit()

    def open_options(self) -> None:
        from .options_window import show_options_window  # import local (evite les cycles)

        show_options_window(self)

    # ---------------------------------------------------------------- service
    def set_service_paused(self, paused: bool) -> None:
        paused = bool(paused)
        if paused == self.service_paused:
            return
        self.service_paused = paused
        if self._on_service_paused is not None:
            try:
                self._on_service_paused(paused)
            except Exception:
                log.exception("Changement d'etat du service impossible")
        self.update_selection_watcher()
        BUS.service_changed.emit(paused)
        BUS.settings_changed.emit()

    def auto_read(self) -> bool:
        if self._get_auto_read is not None:
            try:
                return bool(self._get_auto_read())
            except Exception:
                pass
        return pref_bool("claude_auto_read", True)

    def set_auto_read(self, enabled: bool) -> None:
        if self._set_auto_read is not None:
            self._set_auto_read(bool(enabled))
        else:
            save_prefs({"claude_auto_read": bool(enabled)})
        BUS.settings_changed.emit()

    def autostart(self) -> bool:
        if self._get_autostart is None:
            return False
        try:
            return bool(self._get_autostart())
        except Exception:
            return False

    def set_autostart(self, enabled: bool) -> None:
        if self._set_autostart is not None:
            self._set_autostart(bool(enabled))
        BUS.settings_changed.emit()

    # ---------------------------------------------------------------- interne
    def _sync_ctrl_window(self) -> None:
        win = STATE.ui.ctrl_window
        if win is None:
            return
        try:
            win.sync_pause_button()
        except RuntimeError:
            pass


ACTIONS = AppActions()
