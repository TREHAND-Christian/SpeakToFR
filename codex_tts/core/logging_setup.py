"""Configuration du logging : fichier tournant dans %APPDATA%/SpeakToFR + console si disponible."""
import logging
import sys
from logging.handlers import RotatingFileHandler

from .paths import app_data_dir

_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger("codex_tts")
    root.setLevel(level)
    formatter = logging.Formatter(_FORMAT)

    try:
        fh = RotatingFileHandler(
            app_data_dir() / "speaktofr.log", maxBytes=512_000, backupCount=2, encoding="utf-8"
        )
        fh.setFormatter(formatter)
        root.addHandler(fh)
    except OSError:
        pass

    # En executable fenetre (console=False), sys.stderr vaut None
    if sys.stderr is not None:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(formatter)
        root.addHandler(sh)
