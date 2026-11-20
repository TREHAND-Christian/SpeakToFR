"""Test de fumee : fenetre de controle + lecture complete avec un faux moteur TTS (Qt hors ecran)."""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("win32clipboard")

from PySide6.QtWidgets import QApplication  # noqa: E402

from codex_tts.core.state import STATE  # noqa: E402


class FakeEngine:
    def __init__(self):
        self.spoken = []
        self.stop_flag = False

    def speak_blocking(self, token, text, rate=1.0):
        self.spoken.append(text)

    def stop(self):
        self.stop_flag = True

    def list_voices(self):
        return [{"kind": "OneCore", "token": "tok", "desc": "Voix Test"}]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fake_voice(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    eng = FakeEngine()
    monkeypatch.setattr(STATE, "onecore", eng)
    monkeypatch.setattr(STATE, "voices", eng.list_voices())
    monkeypatch.setattr(STATE, "current_voice_index", 0)
    monkeypatch.setattr(STATE, "current_voice_desc", "Voix Test")
    yield eng
    from codex_tts.ui.ctrl_window_factory import cleanup_ui

    cleanup_ui(clear_clipboard=False)


def _pump(app, seconds, until=lambda: False):
    end = time.time() + seconds
    while time.time() < end and not until():
        app.processEvents()
        time.sleep(0.01)


def test_control_window_content_modes_and_highlight(app, fake_voice):
    from codex_tts.ui.window import MODE_COMPLET, MODE_MINI, MODE_OPTIONS, ControlWindow

    win = ControlWindow(10, None)
    html = "<html><body><p>Bonjour le monde. Deuxieme phrase.</p><pre>x = 1</pre></body></html>"
    win.set_content("Bonjour le monde. Deuxieme phrase.", html=html, original_html=html)
    # Le panneau <pre> doit etre rempli (regression : html shadowing du module html)
    assert win.pre_view.toPlainText().strip() == "x = 1"

    for mode in (MODE_OPTIONS, MODE_MINI, MODE_COMPLET):
        win._set_mode(mode, persist=False)
        assert win._mode == mode

    win.apply_highlight(0, 7)
    assert len(win.text_edit.extraSelections()) == 1
    win.clear_highlight()
    assert win.text_edit.extraSelections() == []
    win.highlight_allowed = False
    win.apply_highlight(0, 7)
    assert win.text_edit.extraSelections() == []
    win.close()


def test_full_playback_reads_sentences_and_skips_pre(app, fake_voice):
    from codex_tts.ui.ui_main import _start_playback

    html = "<p>Premiere phrase. Seconde phrase.</p><pre>code_ligne_un\ncode_ligne_deux</pre><p>Derniere.</p>"
    _start_playback(app, "", html, True, False, 0)
    _pump(app, 5, until=lambda: len(fake_voice.spoken) >= 3 and STATE.playback.current_thread is None)

    spoken = " | ".join(fake_voice.spoken)
    assert "Premiere phrase." in spoken
    assert "Seconde phrase." in spoken
    assert "Derniere." in spoken
    assert "code_ligne" not in spoken and "code ligne" not in spoken.replace("_", " ")
    assert STATE.playback.sentence_skip  # phrases du <pre> marquees
    assert STATE.ui.ctrl_window is not None or STATE.playback.stop_requested is False


def test_plain_text_playback(app, fake_voice):
    from codex_tts.ui.ui_main import _start_playback

    _start_playback(app, "Un texte simple. Avec TTS dedans.", None, True, False, 0)
    _pump(app, 5, until=lambda: len(fake_voice.spoken) >= 2 and STATE.playback.current_thread is None)
    assert fake_voice.spoken[0] == "Un texte simple."
    assert fake_voice.spoken[1] == "Avec T T S dedans."


def test_no_voice_does_not_crash(app, monkeypatch, tmp_path):
    from codex_tts.ui import ui_main

    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(STATE, "voices", [])
    called = []
    monkeypatch.setattr(ui_main, "notify_no_voice", lambda a: called.append(1))
    ui_main._start_playback(app, "Bonjour.", None, True, False, 0)
    assert called == [1]
