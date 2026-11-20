"""Chemins de donnees utilisateur (hors dossier d'installation)."""
import os
from pathlib import Path

APP_NAME = "SpeakToFR"


def app_data_dir() -> Path:
    """Dossier %APPDATA%/SpeakToFR (cree si besoin)."""
    base = os.environ.get("APPDATA") or str(Path.home())
    path = Path(base) / APP_NAME
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path
