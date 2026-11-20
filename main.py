"""Point d'entree principal de SpeakToFR (PySide6)."""
import logging
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

from PySide6.QtCore import Qt, QUrl, QSharedMemory
from PySide6.QtGui import QIcon, QPainter, QColor, QPixmap, QDesktopServices
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from codex_tts.core.logging_setup import setup_logging
from codex_tts.core.state import STATE
from codex_tts.services.watcher import clipboard_loop
from codex_tts.services.hotkeys import hotkey_loop, stop_hotkey_loop
from codex_tts.playback.control import stop_playback

try:
    import winreg
except ImportError:
    winreg = None

log = logging.getLogger("codex_tts.main")


def main():
    setup_logging()
    log.info("SpeakToFR demarre")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    singleton = QSharedMemory("SpeakToFR.Singleton")
    if not singleton.create(1):
        return
    setattr(app, "_single_instance_guard", singleton)
    tray_icon = None
    hotkey_thread = None
    hotkey_enabled = True

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
            if tray_icon is not None:
                tray_icon.hide()
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
    STATE.ui.root = app

    clipboard_loop(app)

    def _make_status_icon(color: str) -> QIcon:
        size = 16
        pix = QPixmap(size, size)
        pix.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.setBrush(QColor("#000000"))
        painter.setPen(QColor("#000000"))
        painter.drawRect(0, 0, size - 1, size - 1)
        painter.setPen(QColor(color))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(0, 1, size, 7, Qt.AlignHCenter | Qt.AlignVCenter, "S2")
        painter.drawText(0, 8, size, 7, Qt.AlignHCenter | Qt.AlignVCenter, "FR")
        painter.end()
        return QIcon(pix)

    def _autostart_command() -> str:
        exe = Path(sys.executable)
        script = Path(__file__).resolve()
        return f"\"{exe}\" \"{script}\""

    def _get_autostart_enabled() -> bool:
        if winreg is None:
            return False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\\Microsoft\\Windows\\CurrentVersion\\Run") as key:
                winreg.QueryValueEx(key, "SpeakToFR")
                return True
        except Exception:
            return False

    def _set_autostart_enabled(enabled: bool) -> None:
        if winreg is None:
            return
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\\Microsoft\\Windows\\CurrentVersion\\Run",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                if enabled:
                    winreg.SetValueEx(key, "SpeakToFR", 0, winreg.REG_SZ, _autostart_command())
                else:
                    try:
                        winreg.DeleteValue(key, "SpeakToFR")
                    except FileNotFoundError:
                        pass
        except OSError:
            log.exception("Modification du demarrage automatique impossible")

    def _set_hotkey_enabled(enabled: bool) -> None:
        nonlocal hotkey_thread, hotkey_enabled
        if enabled and not hotkey_enabled:
            hotkey_thread = threading.Thread(target=hotkey_loop, daemon=True)
            hotkey_thread.start()
        elif not enabled and hotkey_enabled:
            stop_hotkey_loop()
        hotkey_enabled = enabled
        if tray_icon is not None:
            tray_icon.setIcon(_make_status_icon("#2ecc71" if hotkey_enabled else "#e74c3c"))
            tray_icon.setToolTip("SpeakToFR")

    def _open_help():
        try:
            help_path = Path(sys.argv[0]).resolve().parent / "help.html"
            if help_path.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(help_path)))
            else:
                log.warning("Aide introuvable: %s", help_path)
        except Exception:
            log.exception("Ouverture de l'aide impossible")

    def _init_tray():
        nonlocal tray_icon, hotkey_thread, hotkey_enabled
        hotkey_enabled = True
        tray_icon = QSystemTrayIcon()
        tray_icon.setIcon(_make_status_icon("#2ecc71"))
        tray_icon.setToolTip("SpeakToFR")

        menu = QMenu()
        toggle_action = menu.addAction("Marche/Arret Ctrl+Alt+Entree")
        toggle_action.setCheckable(True)
        toggle_action.setChecked(True)
        toggle_action.triggered.connect(lambda checked: _set_hotkey_enabled(checked))

        menu.addSeparator()
        autostart_action = menu.addAction("Demarrage automatique Windows")
        autostart_action.setCheckable(True)
        autostart_action.setChecked(_get_autostart_enabled())
        autostart_action.triggered.connect(lambda checked: _set_autostart_enabled(checked))

        menu.addSeparator()
        help_action = menu.addAction("Aide")
        help_action.triggered.connect(_open_help)

        menu.addSeparator()
        quit_action = menu.addAction("Quitter")
        quit_action.triggered.connect(shutdown)

        tray_icon.setContextMenu(menu)
        tray_icon.show()

        hotkey_thread = threading.Thread(target=hotkey_loop, daemon=True)
        hotkey_thread.start()

    _init_tray()

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
