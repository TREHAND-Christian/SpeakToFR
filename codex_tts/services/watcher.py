"""Watcher du presse-papiers qui declenche la lecture TTS (Qt)."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from codex_tts.services.clipboard import get_clipboard_text, set_clipboard_text
from codex_tts.core.config import TAG
from codex_tts.ui.ui import speak_with_ui
def clipboard_loop(app: QApplication):
    # Memorise le dernier presse-papiers tagge pour eviter les relances en boucle
    last_tagged = {"value": None}

    def check():
        try:
            raw = get_clipboard_text()
            if raw.startswith(TAG):
                if raw == last_tagged["value"]:
                    return
                last_tagged["value"] = raw
                payload = raw[len(TAG):].lstrip()
                text = payload if payload else "veuillez selectionner un texte"
                print("[CodexTTS] Watcher: texte detecte, lancement lecture.")
                QTimer.singleShot(0, lambda: speak_with_ui(app, text))
                try:
                    set_clipboard_text(payload)
                except Exception:
                    pass
            else:
                last_tagged["value"] = None
        except KeyboardInterrupt:
            QTimer.singleShot(0, app.quit)
            return
        except Exception:
            pass

    timer = QTimer()
    timer.setInterval(150)
    timer.timeout.connect(check)
    timer.start()
    # Evite GC
    setattr(app, "_codex_clipboard_timer", timer)
