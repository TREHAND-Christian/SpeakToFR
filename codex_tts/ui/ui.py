"""Facade module kept for backward-compatible imports.

Watcher and other modules import: from codex_tts.ui.ui import speak_with_ui
We keep this file tiny to avoid indentation issues and to make maintenance easier.
"""

from .ui_main import speak_with_ui

__all__ = ["speak_with_ui"]
