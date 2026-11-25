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

from codex_tts.core import volume
from codex_tts.core.logging_setup import setup_logging
from codex_tts.core.state import STATE
from codex_tts.services.watcher import clipboard_loop
from codex_tts.services.claude_desktop import ClaudeDesktopReader
from codex_tts.services.selection import SelectionWatcher
from codex_tts.core.prefs import load_prefs, save_prefs
from codex_tts.ui.app_actions import ACTIONS, pref_bool
from codex_tts.ui.bus import BUS
from codex_tts.ui.minibar import MiniBar
from codex_tts.ui.ui_main import speak_with_ui
from codex_tts.services.hotkeys import hotkey_loop, stop_hotkey_loop
from codex_tts.playback.control import stop_playback

from codex_tts.ui.web_text_view import init_web_engine

# Qt WebEngine (rendu fidele de la fenetre texte) doit etre initialise avant QApplication
init_web_engine()

try:
    import winreg
except ImportError:
    winreg = None

log = logging.getLogger("codex_tts.main")


def _selftest_web(out_path: str) -> int:
    """Diagnostic : affiche une page test dans la vue Chromium, ecrit le resultat dans out_path."""
    import json as _json
    from PySide6.QtCore import QTimer

    from codex_tts.text.html_faithful import web_document
    from codex_tts.ui.web_text_view import create_web_view, web_available

    app = QApplication(sys.argv)

    def write(msg: str) -> None:
        Path(out_path).write_text(msg, encoding="utf-8")

    if not web_available():
        write("ERREUR: Qt WebEngine indisponible")
        return 2
    view = create_web_view()
    view.resize(500, 200)
    view.move(-3000, -3000)
    view.show()
    state = {}

    def done(res):
        view.grab().save(str(Path(out_path).with_suffix(".png")))
        write(f"OK hauteur={state.get('h')} surligne={res!r}")
        app.quit()

    def on_size(h, _w):
        if "h" in state:
            return
        state["h"] = h
        view.highlight([[0, 4, "Test"]])
        QTimer.singleShot(
            500,
            lambda: view._run(
                "JSON.stringify(Array.from(CSS.highlights.get('stfr') || []).map(function(r){return r.toString();}))",
                done,
            ),
        )

    view.content_size_changed.connect(on_size)
    doc = web_document('<div style="background: linear-gradient(#c33, #33c); border-radius: 10px; color: white; '
                       'padding: 20px">Test <b>SpeakToFR</b> rendu fidèle</div>')
    view.show_html(doc, None, "rgb(255, 255, 255)")
    QTimer.singleShot(20000, lambda: (write("ERREUR: delai depasse"), app.quit()))
    app.exec()
    return 0


def main():
    if "--selftest-web" in sys.argv:
        idx = sys.argv.index("--selftest-web")
        out = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else str(Path.home() / "speaktofr_selftest.txt")
        return _selftest_web(out)
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
    minibar = None

    # Volume / muet memorises (s'appliquent a toute la session audio de SpeakToFR)
    volume.init_from_prefs()

    def shutdown():
        try:
            app._claude_desktop_reader.set_enabled(False)
        except Exception:
            pass
        try:
            stop_playback(clear_clipboard=True)
        except Exception:
            pass
        try:
            stop_hotkey_loop()
        except Exception:
            pass
        try:
            selection.set_enabled(False)
        except Exception:
            pass
        try:
            if minibar is not None:
                minibar.hide()
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

    claude_reader = ClaudeDesktopReader(app)
    setattr(app, "_claude_desktop_reader", claude_reader)
    auto_read = {"on": bool((load_prefs() or {}).get("claude_auto_read", True))}

    def _on_claude_partial(text: str) -> None:
        """Reponse intermediaire terminee (pendant que Claude travaille) : lue a la suite."""
        if auto_read["on"] and ACTIONS.read_partial():
            ACTIONS.enqueue_reading(text, origin="claude")

    def _on_claude_response(text: str, remaining: str = None) -> None:
        """Reponse terminee : lue (la partie pas encore lue) si la lecture auto est active, sinon gardee pour Play."""
        if remaining is None:
            remaining = text
        if auto_read["on"]:
            partial = ACTIONS.read_partial()
            ACTIONS.enqueue_reading(remaining if partial else text, origin="claude")
            # Lue en plusieurs morceaux : le prochain Play relira la reponse entiere
            chunked = partial and remaining.strip() != text.strip()
            ACTIONS.set_loaded_text(text, fresh=chunked)
        else:
            ACTIONS.set_loaded_text(text)

    claude_reader.callback = _on_claude_response
    claude_reader.on_partial = _on_claude_partial
    # Conversation ouverte ou changee : sa derniere reponse est chargee, le prochain Play la lit
    claude_reader.on_loaded = ACTIONS.set_loaded_text

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

    app.setWindowIcon(_make_status_icon("#2ecc71"))

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
            tray_icon.setToolTip("SpeakToFR" if hotkey_enabled else "SpeakToFR (en pause)")

    # Service en pause = plus de raccourci Ctrl+Alt+Entree ni de lecture auto Claude Desktop
    def _apply_service_paused(paused: bool) -> None:
        _set_hotkey_enabled(not paused)
        claude_reader.set_enabled(not paused)

    def _set_auto_read(enabled: bool) -> None:
        auto_read["on"] = bool(enabled)
        save_prefs({"claude_auto_read": auto_read["on"]})

    ACTIONS.configure(
        on_service_paused=_apply_service_paused,
        get_auto_read=lambda: auto_read["on"],
        set_auto_read=_set_auto_read,
        get_autostart=_get_autostart_enabled,
        set_autostart=_set_autostart_enabled,
        claude_available=claude_reader.available,
    )

    # Texte selectionne hors Claude Desktop : la barre redevient active et Play le lit
    selection = SelectionWatcher()
    ACTIONS.selection = selection
    ACTIONS.update_selection_watcher()

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
        service_action = menu.addAction("Service actif (Ctrl+Alt+Entrée)")
        service_action.setCheckable(True)
        service_action.setChecked(True)
        service_action.triggered.connect(lambda checked: ACTIONS.set_service_paused(not checked))

        claude_action = menu.addAction("Lecture auto Claude Desktop")
        claude_action.setCheckable(True)
        claude_action.setChecked(auto_read["on"])
        claude_action.setEnabled(claude_reader.available)
        claude_action.triggered.connect(lambda checked: ACTIONS.set_auto_read(checked))

        bar_action = menu.addAction("Barre flottante")
        bar_action.setCheckable(True)
        bar_action.triggered.connect(lambda checked: ACTIONS.set_bar_visible(checked))

        autostart_action = menu.addAction("Démarrage automatique Windows")
        autostart_action.setCheckable(True)
        autostart_action.setChecked(_get_autostart_enabled())
        autostart_action.triggered.connect(lambda checked: ACTIONS.set_autostart(checked))

        menu.addSeparator()
        options_action = menu.addAction("Options...")
        options_action.triggered.connect(ACTIONS.open_options)
        help_action = menu.addAction("Aide")
        help_action.triggered.connect(_open_help)

        menu.addSeparator()
        quit_action = menu.addAction("Quitter")
        quit_action.triggered.connect(shutdown)

        def _sync_menu(*_):
            # Les memes reglages sont modifiables depuis la barre et les options
            for action, value in (
                (service_action, not ACTIONS.service_paused),
                (claude_action, auto_read["on"]),
                (bar_action, ACTIONS.bar_visible()),
                (autostart_action, _get_autostart_enabled()),
            ):
                action.blockSignals(True)
                action.setChecked(value)
                action.blockSignals(False)

        menu.aboutToShow.connect(_sync_menu)
        BUS.settings_changed.connect(_sync_menu)

        def _on_tray_activated(reason):
            if reason in (QSystemTrayIcon.DoubleClick, QSystemTrayIcon.Trigger):
                ACTIONS.open_options()

        tray_icon.activated.connect(_on_tray_activated)
        tray_icon.setContextMenu(menu)
        tray_icon.show()
        setattr(app, "_tray_menu", menu)

        hotkey_thread = threading.Thread(target=hotkey_loop, daemon=True)
        hotkey_thread.start()
        # Toujours actif (sauf service en pause) : charge la derniere reponse meme sans lecture auto
        claude_reader.set_enabled(True)

    # Barre flottante (comme CodexAudio)
    minibar = MiniBar(ACTIONS)
    ACTIONS.minibar = minibar
    setattr(app, "_minibar", minibar)
    if pref_bool("bar_start", True):
        minibar.ensure_on_top()

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
