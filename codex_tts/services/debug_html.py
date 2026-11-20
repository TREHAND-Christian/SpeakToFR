"""Ecriture optionnelle de fichiers HTML de debug (preference debug_html)."""
import logging
import time
from typing import Optional

from ..core.paths import app_data_dir
from ..core.prefs import load_prefs

log = logging.getLogger(__name__)


def write_html_debug(suffix: str, html_code: Optional[str]) -> None:
    if html_code is None:
        return
    try:
        if not (load_prefs() or {}).get("debug_html", False):
            return
        folder = app_data_dir() / "html"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{int(time.time() * 1000)}_{suffix}.html").write_text(html_code, encoding="utf-8")
    except OSError as exc:
        log.warning("Ecriture du HTML de debug impossible: %s", exc)
