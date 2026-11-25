"""Watcher du presse-papiers qui déclenche la lecture TTS (Qt)."""
from __future__ import annotations

import json
import logging

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from codex_tts.core.config import TAG
from codex_tts.services.clipboard import get_clipboard_text, set_clipboard_text
from codex_tts.ui.app_actions import ACTIONS
from codex_tts.ui.ui_main import speak_with_ui

log = logging.getLogger(__name__)


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
                except ValueError:
                    log.warning("Payload JSON du presse-papiers invalide, texte brut utilise")

            # Nettoie le clipboard pour éviter boucles
            try:
                set_clipboard_text("")
            except Exception:
                log.exception("Nettoyage du presse-papiers impossible")

            log.debug("watcher: lecture demandee")
            ACTIONS.clear_queue()
            QTimer.singleShot(
                0,
                lambda: speak_with_ui(
                    app,
                    text=text,
                    reuse_ui=True,
                    translate_text=True,
                    display_html_override=None,
                    source_url=source_url,
                    origin="selection",
                ),
            )
        except KeyboardInterrupt:
            QTimer.singleShot(0, app.quit)
        except Exception:
            # le watcher ne doit jamais faire planter l'app
            log.exception("Erreur dans la surveillance du presse-papiers")

    timer = QTimer()
    timer.setInterval(150)
    timer.timeout.connect(check)
    timer.start()
    setattr(app, "_codex_clipboard_timer", timer)
