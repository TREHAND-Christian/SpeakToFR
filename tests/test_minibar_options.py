"""Test de fumee : barre flottante + fenetre Options (Qt hors ecran)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("win32clipboard")

from PySide6.QtWidgets import QApplication  # noqa: E402

from codex_tts.core.state import STATE  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def actions(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(
        STATE,
        "voices",
        [{"kind": "OneCore", "token": "a", "desc": "Microsoft Paul"}, {"kind": "OneCore", "token": "b", "desc": "Microsoft Julie"}],
    )
    monkeypatch.setattr(STATE, "current_voice_index", 0)
    monkeypatch.setattr(STATE, "current_voice_desc", "Microsoft Paul")
    from codex_tts.ui.app_actions import AppActions

    acts = AppActions()
    paused_calls = []
    acts.configure(on_service_paused=paused_calls.append, claude_available=True)
    acts.paused_calls = paused_calls
    return acts


def test_minibar_buttons_and_state(app, actions):
    from codex_tts.ui.minibar import MiniBar

    bar = MiniBar(actions)
    actions.minibar = bar
    bar.show()
    assert bar.height() == 36

    # Muet
    bar.btn_mute.click()
    bar.refresh_state()
    assert bar._muted is True
    bar.btn_mute.click()
    bar.refresh_state()
    assert bar._muted is False

    # Fenetre texte (option memorisee)
    assert actions.show_text_window() is False
    bar.btn_text.click()
    assert actions.show_text_window() is True
    bar.btn_text.click()
    assert actions.show_text_window() is False

    # Service en pause -> bordure rouge
    actions.set_service_paused(True)
    bar.refresh_state()
    assert bar._app_paused is True and actions.paused_calls == [True]
    actions.set_service_paused(False)
    bar.close()


def test_options_window_reflects_and_applies(app, actions):
    from codex_tts.core.prefs import load_prefs
    from codex_tts.ui.options_window import OptionsWindow

    win = OptionsWindow(actions)
    win.refresh()
    assert win.voice_combo.count() == 2
    assert win.voice_combo.itemText(0) == "Paul"

    win.voice_combo.setCurrentIndex(1)
    assert STATE.current_voice_desc == "Microsoft Julie"
    assert (load_prefs() or {}).get("voice") == "Microsoft Julie"

    win.chk_show_text.setChecked(True)
    assert actions.show_text_window() is True

    win.chk_pause.setChecked(True)
    assert actions.service_paused is True

    win.speed_slider.setValue(150)
    win._speed_timer.timeout.emit()
    assert abs(STATE.speed_value - 1.5) < 1e-6
    assert win.speed_value.text() == "150%"
    win.close()


def test_text_window_follows_option(app, actions, monkeypatch):
    """Fenetre texte cachee par defaut (barre seule), affichee si l'option est cochee."""
    from codex_tts.ui import app_actions, ctrl_window_factory, ui_main

    class FakeEngine:
        def speak_blocking(self, token, text, rate=1.0):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(STATE, "onecore", FakeEngine())
    monkeypatch.setattr(app_actions, "ACTIONS", actions)
    monkeypatch.setattr(ctrl_window_factory, "ACTIONS", actions)

    ui_main._start_playback(app, "Bonjour. Au revoir.", None, True, False, 0)
    win = STATE.ui.ctrl_window
    assert win is not None and not win.isVisible()
    assert not win.mode_container.isVisible()

    actions.set_show_text(True)
    assert win.isVisible()
    actions.set_show_text(False)
    assert not win.isVisible()

    # Laisse la lecture (instantanee avec le faux moteur) se terminer pour ne pas polluer les autres tests
    import time

    end = time.time() + 3
    while time.time() < end and (STATE.ui.ctrl_window is not None or STATE.playback.current_thread is not None):
        app.processEvents()
        time.sleep(0.01)
    ctrl_window_factory.cleanup_ui(clear_clipboard=False)


def test_play_reads_loaded_response_then_rereads(app, actions, monkeypatch):
    """Conversation chargee : Play lit sa derniere reponse ; ensuite Play relit la derniere lecture."""
    from codex_tts.ui import ui_main

    calls = []
    monkeypatch.setattr(ui_main, "speak_with_ui", lambda app_, text, **kw: calls.append(text))
    monkeypatch.setattr(STATE.ui, "root", app)
    monkeypatch.setattr(STATE.playback, "busy", False)
    monkeypatch.setattr(STATE.playback, "paused", False)
    monkeypatch.setattr(STATE.playback, "last_text", "")

    assert actions.is_active() is False
    actions.set_loaded_text("Derniere reponse de Claude.")
    actions.play_pause()
    assert calls == ["Derniere reponse de Claude."]

    # Deja lue : Play relit la derniere lecture preparee (sans retraduire)
    restarts = []
    from codex_tts.ui import app_actions

    monkeypatch.setattr(app_actions, "restart_current_sentence", lambda **kw: restarts.append(kw))
    monkeypatch.setattr(STATE.playback, "last_text", "Derniere reponse traduite.")
    actions.play_pause()
    assert calls == ["Derniere reponse de Claude."] and len(restarts) == 1
    assert actions.is_playing() is True  # la barre passe tout de suite en "pause"
    STATE.playback.busy = False


def test_stop_disabled_when_idle(app, actions, monkeypatch):
    from codex_tts.ui.minibar import MiniBar

    monkeypatch.setattr(STATE.playback, "busy", False)
    monkeypatch.setattr(STATE.playback, "paused", False)
    bar = MiniBar(actions)
    bar.refresh_state()
    assert not bar.btn_stop.isEnabled()
    STATE.playback.busy = True
    bar.refresh_state()
    assert bar.btn_stop.isEnabled() and bar._playing is True
    STATE.playback.paused = True
    bar.refresh_state()
    assert bar.btn_stop.isEnabled() and bar._playing is False
    STATE.playback.busy = False
    STATE.playback.paused = False
    bar.close()


def test_text_window_button_shows_loaded_response_when_idle(app, actions, monkeypatch):
    from codex_tts.ui import ctrl_window_factory

    monkeypatch.setattr(ctrl_window_factory, "ACTIONS", actions)
    monkeypatch.setattr(STATE.playback, "busy", False)
    monkeypatch.setattr(STATE.playback, "paused", False)
    actions.set_loaded_text("Reponse chargee pour la fenetre.")
    actions.set_show_text(True)
    win = STATE.ui.ctrl_window
    assert win is not None and win.isVisible()
    assert "Reponse chargee pour la fenetre." in win.text_edit.toPlainText()
    actions.set_show_text(False)
    assert STATE.ui.ctrl_window is None
