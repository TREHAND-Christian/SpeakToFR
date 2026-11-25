"""Mode selection : hors Claude Desktop, du texte selectionne active la barre et Play le lit."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("win32clipboard")

from codex_tts.core.state import STATE  # noqa: E402
from codex_tts.services import selection as selmod  # noqa: E402


class FakeRange:
    def __init__(self, text):
        self.text = text

    def GetText(self, n=-1):
        return self.text


class FakePattern:
    def __init__(self, texts):
        self.texts = texts

    def GetSelection(self):
        return [FakeRange(t) for t in self.texts]


class FakeCtrl:
    def __init__(self, pattern=None, parent=None):
        self.pattern = pattern
        self.parent = parent

    def GetPattern(self, pid):
        return self.pattern

    def GetParentControl(self):
        return self.parent


def test_selected_text_walks_up_to_document():
    doc = FakeCtrl(FakePattern(["Bonjour ", "le monde"]))
    link = FakeCtrl(None, parent=doc)
    assert selmod.selected_text(link) == "Bonjour le monde"
    assert selmod.selected_text(FakeCtrl(FakePattern([""]))) == ""
    assert selmod.selected_text(FakeCtrl(None)) == ""


def test_check_once_ignores_claude_and_own_windows(monkeypatch):
    names = {11: "claude.exe", 22: "notepad.exe"}
    current = {"pid": 22}
    monkeypatch.setattr(selmod, "foreground_pid", lambda: current["pid"])
    monkeypatch.setattr(selmod, "exe_name", lambda pid: names.get(pid, ""))

    class FakeAuto:
        class PatternId:
            TextPattern = 1

        @staticmethod
        def GetFocusedControl():
            return FakeCtrl(FakePattern(["texte choisi"]))

    monkeypatch.setattr(selmod, "auto", FakeAuto)
    w = selmod.SelectionWatcher()
    assert w.check_once() is True  # Bloc-notes avec selection
    w.has_selection = True
    current["pid"] = os.getpid()
    assert w.check_once() is True  # clic sur la barre : etat garde
    current["pid"] = 11
    assert w.check_once() is False  # Claude Desktop : Play garde son role


def test_play_reads_selection_when_active(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from codex_tts.services import hotkeys
    from codex_tts.ui.app_actions import AppActions

    from codex_tts.services import foreground

    monkeypatch.setattr(foreground, "exe_name", lambda pid: "notepad.exe")  # pas Claude Desktop devant
    calls = []
    monkeypatch.setattr(hotkeys, "copy_selection_and_tag", lambda **kw: calls.append(kw))
    monkeypatch.setattr(STATE.playback, "busy", False)
    monkeypatch.setattr(STATE.playback, "paused", False)

    class FakeWatcher:
        enabled = True
        has_selection = True
        available = True

        def set_enabled(self, v):
            self.enabled = v

    acts = AppActions()
    acts.selection = FakeWatcher()
    assert acts.selection_active() is True
    acts.play_pause()
    for _ in range(50):
        if calls:
            break
        import time

        time.sleep(0.01)
    assert calls == [{"release_modifiers": False}]

    # Service en pause : plus de detection
    acts.set_service_paused(True)
    assert acts.selection.enabled is False and acts.selection_active() is False


def test_bar_not_dimmed_when_selection(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from codex_tts.services import foreground
    from codex_tts.ui.app_actions import AppActions
    from codex_tts.ui.minibar import MiniBar

    monkeypatch.setattr(foreground, "exe_name", lambda pid: "notepad.exe")  # pas Claude Desktop devant

    class FakeWatcher:
        enabled = True
        has_selection = False
        available = True

        def set_enabled(self, v):
            self.enabled = v

    acts = AppActions()
    acts.selection = FakeWatcher()
    bar = MiniBar(acts)
    bar._poll.stop()
    bar._focus.update = lambda: False  # Claude Desktop pas au premier plan
    bar.refresh_state()
    assert bar._dimmed is True
    acts.selection.has_selection = True
    bar.refresh_state()
    assert bar._dimmed is False
    assert bar.btn_play.toolTip() == "Lire le texte sélectionné"
    bar.close()


def test_back_in_claude_play_returns_to_claude_response(monkeypatch, tmp_path):
    """Apres la lecture d'une selection, Play dans Claude Desktop relit la reponse de Claude, pas la selection."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from codex_tts.ui import app_actions, ui_main
    from codex_tts.ui.app_actions import AppActions

    calls, restarts = [], []
    monkeypatch.setattr(ui_main, "speak_with_ui", lambda app_, text, **kw: calls.append((text, kw.get("origin"))))
    monkeypatch.setattr(app_actions, "restart_current_sentence", lambda **kw: restarts.append(kw))
    monkeypatch.setattr(STATE.ui, "root", app)
    pb = STATE.playback
    monkeypatch.setattr(pb, "busy", False)
    monkeypatch.setattr(pb, "paused", False)

    acts = AppActions()
    acts.set_loaded_text("Reponse de Claude.", fresh=False)  # deja lue automatiquement
    # Derniere lecture = une selection lue dans une autre appli
    monkeypatch.setattr(pb, "last_text", "Texte selectionne ailleurs.")
    monkeypatch.setattr(pb, "last_origin", "selection")
    acts.play_pause()
    assert calls == [("Reponse de Claude.", "claude")] and restarts == []

    # Derniere lecture = la reponse de Claude : on la relit sans retraduire
    pb.busy = False
    pb.last_origin = "claude"
    acts.play_pause()
    assert len(calls) == 1 and len(restarts) == 1
    pb.busy = False


def test_selection_ignored_when_claude_in_front(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from codex_tts.services import foreground
    from codex_tts.ui.app_actions import AppActions

    class FakeWatcher:
        enabled = True
        has_selection = True
        available = True

        def set_enabled(self, v):
            self.enabled = v

    acts = AppActions()
    acts.selection = FakeWatcher()
    monkeypatch.setattr(foreground, "foreground_pid", lambda: 11)
    monkeypatch.setattr(foreground, "exe_name", lambda pid: "notepad.exe")
    assert acts.selection_active() is True
    monkeypatch.setattr(foreground, "exe_name", lambda pid: "claude.exe")
    assert acts.selection_active() is False
    assert acts.selection.has_selection is False
