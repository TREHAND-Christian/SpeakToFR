import threading
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTextEdit

_HTML_WINDOW = None

class TranslatedHtmlWindow(QWidget):
    """Fenetre affichant le code HTML du texte traduit."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("HTML traduit")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.resize(500, 700)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.text_edit = QTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setAcceptRichText(False)
        layout.addWidget(self.text_edit)

    def set_html(self, html_code: str):
        self.text_edit.setPlainText(html_code or "")

    def closeEvent(self, event):
        global _HTML_WINDOW
        _HTML_WINDOW = None
        super().closeEvent(event)




def show_translated_html_window(html_code: str):
    """Désactivé : on ne veut plus de fenêtre HTML."""
    return

    """Affiche ou met a jour la fenetre d'HTML traduit."""
    global _HTML_WINDOW
    if _HTML_WINDOW is None:
        _HTML_WINDOW = TranslatedHtmlWindow()
    _HTML_WINDOW.set_html(html_code)
    _HTML_WINDOW.show()
    _HTML_WINDOW.raise_()
    _HTML_WINDOW.activateWindow()


