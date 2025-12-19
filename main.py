"""Point d'entree principal de CodexTTS (Fluent / PySide6)."""
import os
import sys
import threading
import signal
from pathlib import Path

# Assure le chargement des DLL Qt (Qt6Core/Gui/Widgets) avant l'import PySide6
_pyside_dir = Path(sys.prefix) / "Lib" / "site-packages" / "PySide6"
if not _pyside_dir.exists():
    _pyside_dir = Path(__file__).resolve().parent / ".venv" / "Lib" / "site-packages" / "PySide6"
for _d in (_pyside_dir, _pyside_dir / "lib"):
    if _d.exists():
        try:
            os.add_dll_directory(str(_d))
        except Exception:
            pass
        os.environ["PATH"] = str(_d) + os.pathsep + os.environ.get("PATH", "")

from PySide6.QtWidgets import QApplication

from codex_tts.core.state import STATE
from codex_tts.services.watcher import clipboard_loop
from codex_tts.services.hotkeys import hotkey_loop, stop_hotkey_loop
from codex_tts.playback.control import stop_playback


def main():
    print("[CodexTTS] Demarre. Surveille le presse-papiers (Fluent/PySide6).")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    def shutdown():
        try:
            stop_playback(clear_clipboard=True)
        except Exception:
            pass
        try:
            stop_hotkey_loop()
        except Exception:
            pass
        try:
            app.quit()
        except Exception:
            pass

    try:
        signal.signal(signal.SIGINT, lambda *_: shutdown())
    except Exception:
        pass
    STATE.root = app

    clipboard_loop(app)

    t = threading.Thread(target=hotkey_loop, daemon=True)
    t.start()

    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        shutdown()
    finally:
        try:
            stop_hotkey_loop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
