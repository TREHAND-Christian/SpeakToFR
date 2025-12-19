import json
from pathlib import Path
from typing import Optional

def _prefs_path() -> Path:
    # codex_tts/ui/prefs.py -> codex_tts/window_prefs.json (same as before)
    return Path(__file__).resolve().parent.parent / "window_prefs.json"

def load_window_prefs() -> Optional[dict]:
    path = _prefs_path()
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def save_window_prefs(data: dict) -> None:
    path = _prefs_path()
    try:
        current = load_window_prefs() or {}
        current.update(data)
        path.write_text(json.dumps(current), encoding="utf-8")
    except Exception:
        pass
