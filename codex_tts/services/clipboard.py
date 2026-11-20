"""Utilitaires d'accès au presse-papiers Windows.

Renvoie le fragment HTML brut s'il existe (CF_HTML), sinon le texte Unicode.
"""
import time
import win32clipboard
import win32con
from html.parser import HTMLParser


class _HTMLStripper(HTMLParser):
    """Convertit un fragment HTML en texte lisible (sauts de ligne simples)."""

    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"p", "div", "br", "li", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)

    def get_text(self) -> str:
        text = "".join(self.parts)
        lines = [line.strip() for line in text.splitlines()]
        return "\n".join(l for l in lines if l)


def _decode_html_bytes(raw) -> str:
    """Decode CF_HTML bytes robustly (tries utf-8-sig, utf-16, cp1252)."""
    if not isinstance(raw, (bytes, bytearray)):
        return str(raw)
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(enc, errors="ignore")
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")



def _source_url_from_cf_html(data: str) -> str | None:
    """Extrait SourceURL:... depuis le header CF_HTML si présent."""
    try:
        data = data.replace("\x00", "")
        for line in data.splitlines():
            if line.startswith("SourceURL:"):
                url = line.split(":", 1)[1].strip()
                return url or None
    except Exception:
        pass
    return None

def _html_fragment_from_cf_html(data: str) -> str:
    """Extrait le fragment HTML (CF_HTML Windows) de manière robuste."""
    data = data.replace("\x00", "")
    start_fragment = end_fragment = start_html = -1
    # Lecture des offsets ligne par ligne
    for line in data.splitlines():
        if line.startswith("StartFragment:"):
            try:
                start_fragment = int(line.split(":", 1)[1].strip() or -1)
            except Exception:
                pass
        elif line.startswith("EndFragment:"):
            try:
                end_fragment = int(line.split(":", 1)[1].strip() or -1)
            except Exception:
                pass
        elif line.startswith("StartHTML:"):
            try:
                start_html = int(line.split(":", 1)[1].strip() or -1)
            except Exception:
                pass
    # 1) Priorité : offsets fragment
    if start_fragment >= 0 and end_fragment > start_fragment:
        return data[start_fragment:end_fragment]
    # 2) Fallback : offsets HTML complets
    if start_html >= 0:
        return data[start_html:]
    # 3) Fallback ultimate : commentaires Start/EndFragment
    try:
        import re

        m = re.search(r"<!--StartFragment-->(.*)<!--EndFragment-->", data, re.S | re.I)
        if m:
            return m.group(1)
    except Exception:
        pass
    return data



def get_clipboard_payload(retries: int = 3, delay: float = 0.05) -> dict:
    """Retourne un dict:
    - type: 'html' si CF_HTML dispo, sinon 'text'
    - html: fragment HTML (si type html)
    - url: SourceURL (si dispo)
    - text: texte unicode (si dispo)
    """
    payload = {"type": "text", "text": "", "html": None, "url": None}
    for _ in range(max(1, retries)):
        try:
            win32clipboard.OpenClipboard()
            try:
                cf_html = win32clipboard.RegisterClipboardFormat("HTML Format")
                if win32clipboard.IsClipboardFormatAvailable(cf_html):
                    raw = win32clipboard.GetClipboardData(cf_html)
                    raw_str = _decode_html_bytes(raw)
                    fragment = _html_fragment_from_cf_html(raw_str)
                    url = _source_url_from_cf_html(raw_str)
                    if fragment and fragment.strip():
                        payload["type"] = "html"
                        payload["html"] = fragment
                        payload["url"] = url
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    payload["text"] = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT) or ""
            finally:
                win32clipboard.CloseClipboard()
            break
        except Exception:
            time.sleep(delay)
    return payload

def get_clipboard_text(retries: int = 3, delay: float = 0.05) -> str:
    """Retourne du HTML brut si disponible, sinon du texte Unicode."""
    txt = ""
    for _ in range(max(1, retries)):
        try:
            win32clipboard.OpenClipboard()
            try:
                cf_html = win32clipboard.RegisterClipboardFormat("HTML Format")
                if win32clipboard.IsClipboardFormatAvailable(cf_html):
                    raw = win32clipboard.GetClipboardData(cf_html)
                    raw_str = _decode_html_bytes(raw)
                    fragment = _html_fragment_from_cf_html(raw_str)
                    if fragment.strip():
                        txt = fragment
                if not txt and win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    txt = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()
            break
        except Exception:
            time.sleep(delay)
    return txt or ""


def set_clipboard_text(text: str, retries: int = 3, delay: float = 0.05) -> bool:
    for _ in range(max(1, retries)):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            finally:
                win32clipboard.CloseClipboard()
            return True
        except Exception:
            time.sleep(delay)
    return False
