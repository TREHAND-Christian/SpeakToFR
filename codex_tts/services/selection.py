"""Texte selectionne dans l'appli au premier plan (accessibilite Windows / UI Automation).

Hors de Claude Desktop, quand du texte est selectionne, la barre flottante redevient active
et son bouton Play lit la selection (comme Ctrl+Alt+Entree). Rien n'est copie pour le savoir :
on lit seulement la selection exposee par l'appli (TextPattern), toutes les 0,4 s.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Optional

from .foreground import CLAUDE_DESKTOP_EXES, exe_name, foreground_pid

try:
    import uiautomation as auto
except ImportError:  # module optionnel : la detection reste simplement inactive
    auto = None

log = logging.getLogger(__name__)

POLL_SECONDS = 0.4
_MAX_PARENTS = 6  # l'element actif (un lien...) peut etre dans le document qui porte la selection


def selected_text(ctrl, max_len: int = 2000) -> str:
    """Selection de l'element actif, ou du premier parent qui gere le texte ("" si aucune)."""
    for _ in range(_MAX_PARENTS):
        if ctrl is None:
            break
        try:
            pattern = ctrl.GetPattern(auto.PatternId.TextPattern)
        except Exception:
            pattern = None
        if pattern:
            try:
                return "".join(r.GetText(max_len) for r in (pattern.GetSelection() or []))
            except Exception:
                return ""
        try:
            ctrl = ctrl.GetParentControl()
        except Exception:
            break
    return ""


class SelectionWatcher:
    """Thread qui tient a jour `has_selection` : du texte est selectionne hors de Claude Desktop."""

    def __init__(self) -> None:
        self.has_selection = False
        self.enabled = False
        self._own_pid = os.getpid()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def available(self) -> bool:
        return auto is not None

    def set_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled) and auto is not None
        if enabled == self.enabled:
            return
        self.enabled = enabled
        if enabled:
            self._stop.clear()
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="SelectionWatcher", daemon=True)
                self._thread.start()
        else:
            self._stop.set()
            self.has_selection = False

    def check_once(self) -> bool:
        pid = foreground_pid()
        if not pid or pid == self._own_pid:
            return self.has_selection  # nos propres fenetres : on garde l'etat
        if exe_name(pid) in CLAUDE_DESKTOP_EXES:
            return False  # dans Claude Desktop, Play garde son role habituel
        return bool(selected_text(auto.GetFocusedControl()).strip())

    def _run(self) -> None:
        with auto.UIAutomationInitializerInThread():
            while not self._stop.wait(POLL_SECONDS):
                try:
                    self.has_selection = self.check_once()
                except Exception:
                    self.has_selection = False
        self.has_selection = False
