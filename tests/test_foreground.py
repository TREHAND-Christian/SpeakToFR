"""FocusTracker : barre active seulement dans Claude Desktop, grisee partout ailleurs."""
import os

import pytest

pytest.importorskip("win32clipboard")

from codex_tts.services import foreground  # noqa: E402


def test_focus_tracker_active_only_in_claude_desktop(monkeypatch):
    names = {11: "claude.exe", 22: "code.exe", 33: "explorer.exe"}
    current = {"pid": 11}
    monkeypatch.setattr(foreground, "foreground_pid", lambda: current["pid"])
    monkeypatch.setattr(foreground, "exe_name", lambda pid: names.get(pid, ""))

    t = foreground.FocusTracker()
    assert t.update() is True  # Claude Desktop
    current["pid"] = 22
    assert t.update() is False  # VS Code -> grisee
    current["pid"] = 11
    assert t.update() is True
    current["pid"] = 33
    assert t.update() is False  # autre appli -> grisee
    current["pid"] = 11
    assert t.update() is True
    current["pid"] = os.getpid()
    assert t.update() is True  # clic sur nos propres fenetres -> etat garde
    current["pid"] = 0
    assert t.update() is True  # pas de fenetre au premier plan -> etat garde


def test_real_foreground_does_not_crash():
    t = foreground.FocusTracker()
    assert t.update() in (True, False)
