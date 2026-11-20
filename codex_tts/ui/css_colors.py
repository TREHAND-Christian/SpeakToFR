"""Detection des couleurs de fond/texte d'un HTML pour choisir un fond lisible dans le QTextEdit."""
import re
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette, QTextCursor
from PySide6.QtWidgets import QTextEdit


def parse_css_color(value: str) -> Optional[QColor]:
    """Comprend #rgb, #rrggbb et rgb(r, g, b) ; None sinon."""
    if not value:
        return None
    s = value.strip().lower()
    if s.startswith("#"):
        hexv = s[1:]
        try:
            if len(hexv) == 3:
                return QColor(*(int(c * 2, 16) for c in hexv))
            if len(hexv) == 6:
                return QColor(int(hexv[0:2], 16), int(hexv[2:4], 16), int(hexv[4:6], 16))
        except ValueError:
            return None
        return None
    m = re.match(r"rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", s)
    if m:
        r, g, b = (int(m.group(i)) for i in (1, 2, 3))
        if max(r, g, b) <= 255:
            return QColor(r, g, b)
    return None


def detect_html_background_color(html_code: Optional[str]) -> Optional[QColor]:
    if not html_code:
        return None
    for pattern in (r"background-color\s*:\s*([^;\"']+)", r"bgcolor\s*=\s*[\"']?([^\"'>\s]+)"):
        m = re.search(pattern, html_code, flags=re.IGNORECASE)
        if m:
            color = parse_css_color(m.group(1))
            if color is not None:
                return color
    return None


def detect_html_text_color(html_code: Optional[str]) -> Optional[QColor]:
    if not html_code:
        return None
    for m in re.finditer(r"color\s*:\s*([^;\"']+)", html_code, flags=re.IGNORECASE):
        if "background-" in html_code[max(0, m.start() - 12):m.start()].lower():
            continue
        color = parse_css_color(m.group(1))
        if color is not None:
            return color
    m = re.search(r"color\s*=\s*[\"']?([^\"'>\s]+)", html_code, flags=re.IGNORECASE)
    if m:
        return parse_css_color(m.group(1))
    return None


def detect_default_text_color(text_edit: QTextEdit) -> QColor:
    """Couleur du premier caractere non blanc du document, sinon couleur de palette."""
    doc = text_edit.document()
    text = doc.toPlainText()
    idx = 0
    while idx < len(text) and text[idx].isspace():
        idx += 1
    cursor = QTextCursor(doc)
    if idx < len(text):
        cursor.setPosition(idx)
    brush = cursor.charFormat().foreground()
    if brush.style() != Qt.NoBrush and brush.color().isValid():
        return brush.color()
    return text_edit.palette().color(QPalette.Text)


def detect_rendered_text_color(text_edit: QTextEdit) -> Optional[QColor]:
    """Couleur dominante du texte reellement rendu (echantillonnage du viewport)."""
    try:
        img = text_edit.viewport().grab().toImage()
        w, h = img.width(), img.height()
        if w <= 0 or h <= 0:
            return None

        def color_at(x: int, y: int) -> QColor:
            return QColor(img.pixel(x, y))

        corners = [color_at(2, 2), color_at(w - 3, 2), color_at(2, h - 3), color_at(w - 3, h - 3)]
        bg = QColor(
            sum(c.red() for c in corners) // 4,
            sum(c.green() for c in corners) // 4,
            sum(c.blue() for c in corners) // 4,
        )

        def dist(a: QColor, b: QColor) -> int:
            return abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue())

        step = max(2, min(w, h) // 80)
        hist: dict[int, int] = {}
        for y in range(0, h, step):
            for x in range(0, w, step):
                c = color_at(x, y)
                if dist(c, bg) < 12:
                    continue
                key = ((c.red() // 8) << 10) | ((c.green() // 8) << 5) | (c.blue() // 8)
                hist[key] = hist.get(key, 0) + 1

        if not hist:
            return None
        best = max(hist, key=hist.get)
        return QColor(((best >> 10) & 0x1F) * 8 + 4, ((best >> 5) & 0x1F) * 8 + 4, (best & 0x1F) * 8 + 4)
    except Exception:
        return None


def contrast_background(text_edit: QTextEdit, last_html: Optional[str]) -> QColor:
    """Fond a appliquer : celui du HTML s'il en declare un, sinon l'oppose de la couleur du texte."""
    html_bg = detect_html_background_color(last_html)
    if html_bg is not None:
        return html_bg
    text_color = (
        detect_html_text_color(last_html)
        or detect_rendered_text_color(text_edit)
        or detect_default_text_color(text_edit)
    )
    luminance = 0.299 * text_color.red() + 0.587 * text_color.green() + 0.114 * text_color.blue()
    return QColor("#ffffff") if luminance < 128 else QColor("#000000")
