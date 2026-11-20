"""Preferences utilisateur (JSON dans %APPDATA%/SpeakToFR/prefs.json)."""
import json
import logging
import os
import shutil
import sys
import threading
from pathlib import Path
from typing import Optional

from .paths import app_data_dir

log = logging.getLogger(__name__)

_LOCK = threading.Lock()
_LEGACY_NAME = "window_prefs.json"


def prefs_path() -> Path:
    return app_data_dir() / "prefs.json"


def _legacy_candidates() -> list[Path]:
    """Anciens emplacements (a cote du code ou de l'executable)."""
    here = Path(__file__).resolve().parent.parent
    return [here / _LEGACY_NAME, Path(sys.executable).resolve().parent / _LEGACY_NAME]


def _migrate_legacy(path: Path) -> None:
    """Copie l'ancien window_prefs.json vers le nouvel emplacement (une seule fois)."""
    if path.exists():
        return
    for old in _legacy_candidates():
        try:
            if old.is_file():
                shutil.copyfile(old, path)
                log.info("Preferences migrees depuis %s", old)
                return
        except OSError:
            continue


def load_prefs() -> Optional[dict]:
    path = prefs_path()
    with _LOCK:
        try:
            _migrate_legacy(path)
            if not path.exists():
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, ValueError) as exc:
            log.warning("Lecture des preferences impossible: %s", exc)
            return None


def save_prefs(data: dict) -> None:
    path = prefs_path()
    with _LOCK:
        try:
            current: dict = {}
            if path.exists():
                try:
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        current = loaded
                except (OSError, ValueError):
                    current = {}
            current.update(data)
            # Ne jamais persister la taille de la fenetre.
            current.pop("w", None)
            current.pop("h", None)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(current), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            log.warning("Ecriture des preferences impossible: %s", exc)
