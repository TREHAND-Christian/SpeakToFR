"""Watcher du presse-papiers qui déclenche la lecture TTS (Qt)."""
from __future__ import annotations

import json

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from codex_tts.core.config import TAG
from codex_tts.services.clipboard import get_clipboard_text, set_clipboard_text
from codex_tts.ui.ui import speak_with_ui


def clipboard_loop(app: QApplication) -> None:
    # Mémorise le dernier presse-papiers taggé pour éviter les relances en boucle
    last_tagged = {"value": None}

    def check() -> None:
        try:
            raw = get_clipboard_text()
            if not raw.startswith(TAG):
                last_tagged["value"] = None
                return

            if raw == last_tagged["value"]:
                return
            last_tagged["value"] = raw

            payload_str = raw.split("\n", 1)[1] if "\n" in raw else ""
            payload_str = payload_str or ""

            text = payload_str
            source_url = None

            # Support JSON payload (HTML + SourceURL)
            if payload_str.strip().startswith("{"):
                try:
                    obj = json.loads(payload_str)
                    if isinstance(obj, dict) and obj.get("type") == "html" and obj.get("html"):
                        text = obj.get("html") or ""
                        source_url = obj.get("url")
                except Exception:
                    pass

            # Nettoie le clipboard pour éviter boucles
            try:
                set_clipboard_text("")
            except Exception:
                pass

            print("[CodexTTS] watcher: start_playback poste sur le thread Qt")
            QTimer.singleShot(
                0,
                lambda: speak_with_ui(
                    app,
                    text=text,
                    reuse_ui=True,
                    translate_text=True,
                    display_html_override=None,
                    source_url=source_url,
                ),
            )
        except KeyboardInterrupt:
            QTimer.singleShot(0, app.quit)
        except Exception:
            # silencieux: le watcher ne doit jamais faire planter l'app
            pass

    timer = QTimer()
    timer.setInterval(150)
    timer.timeout.connect(check)
    timer.start()
    setattr(app, "_codex_clipboard_timer", timer)
