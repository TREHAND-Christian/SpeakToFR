from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from ..core.prefs import load_prefs, save_prefs


class PreferencesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Préférences SpeakToFR")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setMinimumWidth(420)

        prefs = load_prefs() or {}

        self.auto_detect_french = QCheckBox("Ne pas retraduire un texte déjà en français")
        self.auto_detect_french.setChecked(bool(prefs.get("auto_detect_french", True)))

        self.force_translate = QCheckBox("Forcer la traduction")
        self.force_translate.setChecked(bool(prefs.get("force_translate", False)))

        self.debug_html = QCheckBox("Enregistrer les fichiers HTML de debug")
        self.debug_html.setChecked(bool(prefs.get("debug_html", False)))

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)
        form.addRow(self.auto_detect_french)
        form.addRow(self.force_translate)
        form.addRow(self.debug_html)

        note = QLabel(
            "Les changements sont appliqués à la prochaine lecture. "
            "La voix, la vitesse, la position et le mode restent réglés depuis la fenêtre de lecture."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #555;")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def accept(self):
        save_prefs(
            {
                "auto_detect_french": self.auto_detect_french.isChecked(),
                "force_translate": self.force_translate.isChecked(),
                "debug_html": self.debug_html.isChecked(),
            }
        )
        super().accept()


_PREFERENCES_DIALOG = None


def show_preferences_dialog(parent=None):
    global _PREFERENCES_DIALOG
    if _PREFERENCES_DIALOG is not None:
        try:
            _PREFERENCES_DIALOG.raise_()
            _PREFERENCES_DIALOG.activateWindow()
            return
        except Exception:
            _PREFERENCES_DIALOG = None

    dialog = PreferencesDialog(parent)
    _PREFERENCES_DIALOG = dialog
    dialog.finished.connect(lambda *_: _clear_preferences_dialog(dialog))
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()


def _clear_preferences_dialog(dialog):
    global _PREFERENCES_DIALOG
    if _PREFERENCES_DIALOG is dialog:
        _PREFERENCES_DIALOG = None
