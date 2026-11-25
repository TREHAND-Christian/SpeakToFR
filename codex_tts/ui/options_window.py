"""Fenetre Options de SpeakToFR, sur le modele du panneau Options de CodexAudio (theme sombre)."""
import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..core import volume
from ..core.paths import app_data_dir
from ..core.prefs import load_prefs, save_prefs
from ..core.state import STATE
from .bus import BUS
from .icons import icon_png
from .web_text_view import web_available

log = logging.getLogger(__name__)

ACCENT = "#0078d4"
ACCENT_HOVER = "#026ec1"
ACCENT_PRESSED = "#005a9e"

_STYLE = """
QWidget#optionsRoot {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1a1a1a, stop:1 #202020);
}
QWidget { color: #cccccc; font-family: "Segoe UI"; font-size: 13px; }
QLabel { background: transparent; }
QLabel#title { font-size: 16px; font-weight: 700; color: #e7e7e7; }
QLabel#status {
    border: 1px solid #3c3c3c; border-radius: 11px; background: #252526;
    color: #9d9d9d; font-size: 12px; padding: 3px 10px;
}
QFrame#group { border: 1px solid #353535; border-radius: 12px; background: #232323; }
QLabel#groupTitle { color: #9d9d9d; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
QCheckBox { spacing: 10px; background: transparent; }
QCheckBox::indicator {
    width: 16px; height: 16px; border: 1px solid #6b6b6b; border-radius: 3px; background: #2b2b2b;
}
QCheckBox::indicator:hover { border-color: #9a9a9a; }
QCheckBox::indicator:checked { background: %(accent)s; border-color: %(accent)s; image: url(%(check)s); }
QCheckBox:disabled { color: #6b6b6b; }
QComboBox {
    background: #313131; color: #cccccc; border: 1px solid #3c3c3c; border-radius: 8px;
    padding: 5px 10px; min-height: 20px;
}
QComboBox:hover { border-color: #5a5a5a; }
QComboBox:focus { border-color: %(accent)s; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: url(%(chevron)s); width: 14px; height: 14px; }
QComboBox[muted="true"] { color: #f14c4c; border-color: #a33a3a; }
QComboBox QAbstractItemView {
    background: #252526; color: #cccccc; border: 1px solid #3c3c3c;
    selection-background-color: #04395e; selection-color: #ffffff; outline: 0; padding: 4px;
}
QSlider { background: transparent; min-height: 22px; }
QSlider::groove:horizontal { height: 10px; border-radius: 5px; background: #24425a; }
QSlider::sub-page:horizontal { height: 10px; border-radius: 5px; background: #24425a; }
QSlider::handle:horizontal {
    width: 14px; height: 14px; margin: -4px 0; border-radius: 9px;
    background: %(accent)s; border: 2px solid #4da3e6;
}
QPushButton#rangeBtn {
    background: %(accent)s; color: #ffffff; border: none; border-radius: 8px; font-weight: 700;
    font-size: 14px; min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; padding: 0;
}
QPushButton#rangeBtn:hover { background: %(accent_hover)s; }
QPushButton#rangeBtn:pressed { background: %(accent_pressed)s; }
QPushButton#secondary {
    background: #313131; color: #cccccc; border: 1px solid #3c3c3c; border-radius: 8px; padding: 7px 12px;
}
QPushButton#secondary:hover { background: #3c3c3c; }
QPushButton#secondary:disabled { color: #6b6b6b; }
QLabel#mono { font-family: Consolas, monospace; font-size: 12px; color: #bbbbbb; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #424242; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { color: #f2f2f2; background-color: #2b2b2b; border: 1px solid #555; padding: 4px 6px; }
"""


def _style_sheet() -> str:
    icons_dir = app_data_dir() / "ui"
    try:
        icons_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    check = icon_png("check", icons_dir / "check.png", color=(255, 255, 255))
    chevron = icon_png("chevron", icons_dir / "chevron.png", color=(204, 204, 204))
    return _STYLE % {
        "accent": ACCENT,
        "accent_hover": ACCENT_HOVER,
        "accent_pressed": ACCENT_PRESSED,
        "check": check,
        "chevron": chevron,
    }


def _voice_label(desc: str) -> str:
    """'Microsoft Paul' -> 'Paul' (comme dans CodexAudio)."""
    return desc[len("Microsoft "):] if desc.startswith("Microsoft ") else desc


class _Group(QFrame):
    """Carte arrondie avec un titre en petites capitales."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("group")
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(14, 12, 14, 12)
        self.layout_.setSpacing(10)
        lbl = QLabel(title.upper(), self)
        lbl.setObjectName("groupTitle")
        self.layout_.addWidget(lbl)

    def add(self, widget) -> None:
        self.layout_.addWidget(widget)

    def add_layout(self, layout) -> None:
        self.layout_.addLayout(layout)


class OptionsWindow(QWidget):
    def __init__(self, actions, parent=None):
        super().__init__(parent)
        self._actions = actions
        self.setWindowTitle("SpeakToFR - Options")
        self.setWindowFlag(Qt.Window, True)
        self.setObjectName("optionsRoot")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_style_sheet())
        self.setFixedWidth(400)

        # Petits delais pour ne pas ecrire les preferences a chaque cran du curseur
        self._speed_timer = QTimer(self)
        self._speed_timer.setSingleShot(True)
        self._speed_timer.setInterval(200)
        self._speed_timer.timeout.connect(lambda: self._actions.set_speed(self.speed_slider.value() / 100.0))
        self._volume_timer = QTimer(self)
        self._volume_timer.setSingleShot(True)
        self._volume_timer.setInterval(200)
        self._volume_timer.timeout.connect(lambda: self._actions.set_volume(self.volume_slider.value()))

        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # En-tete
        header = QHBoxLayout()
        title = QLabel("SpeakToFR")
        title.setObjectName("title")
        self.status_label = QLabel()
        self.status_label.setObjectName("status")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.status_label)
        root.addLayout(header)

        # --- Principal
        main = _Group("Principal")
        self.chk_pause = QCheckBox("Mettre le service en pause")
        self.chk_pause.setToolTip("Coupe le raccourci Ctrl+Alt+Entrée et la lecture auto de Claude Desktop")
        self.chk_mute = QCheckBox("Muet")
        self.chk_auto = QCheckBox("Lecture automatique des réponses de Claude Desktop")
        if not self._actions.claude_available:
            self.chk_auto.setEnabled(False)
            self.chk_auto.setToolTip("Lecture de Claude Desktop indisponible sur ce PC")
        self.chk_partial = QCheckBox("Lire aussi les réponses intermédiaires")
        self.chk_partial.setToolTip("Pendant que Claude travaille, chaque texte terminé est lu sans attendre la fin")
        if not self._actions.claude_available:
            self.chk_partial.setEnabled(False)
        for w in (self.chk_pause, self.chk_mute, self.chk_auto, self.chk_partial):
            main.add(w)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.setColumnMinimumWidth(0, 70)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(2, 40)

        self.voice_combo = QComboBox()
        self.voice_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        grid.addWidget(QLabel("Voix :"), 0, 0)
        grid.addWidget(self.voice_combo, 0, 1, 1, 2)

        self.speed_slider, speed_row, self.speed_value = self._range_row(50, 200, 5, 5)
        grid.addWidget(QLabel("Vitesse :"), 1, 0)
        grid.addLayout(speed_row, 1, 1)
        grid.addWidget(self.speed_value, 1, 2)

        self.volume_slider, volume_row, self.volume_value = self._range_row(0, 100, 1, 5)
        grid.addWidget(QLabel("Volume :"), 2, 0)
        grid.addLayout(volume_row, 2, 1)
        grid.addWidget(self.volume_value, 2, 2)
        main.add_layout(grid)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.btn_test = QPushButton("Tester la voix")
        self.btn_test.setObjectName("secondary")
        self.btn_test.setCursor(Qt.PointingHandCursor)
        footer.addWidget(self.btn_test)
        main.add_layout(footer)
        root.addWidget(main)

        # --- Interface
        ui = _Group("Interface")
        self.chk_bar = QCheckBox("Afficher la barre flottante")
        self.chk_bar_start = QCheckBox("Afficher la barre flottante au démarrage")
        self.chk_bar_dim = QCheckBox("Griser la barre quand Claude Desktop n'a pas le focus")
        self.chk_bar_dim.setToolTip("Normale seulement quand Claude Desktop est au premier plan, grisée ailleurs")
        self.chk_selection = QCheckBox("Ailleurs, activer la barre si du texte est sélectionné")
        self.chk_selection.setToolTip("Hors de Claude Desktop : Play lit la sélection, comme Ctrl+Alt+Entrée")
        self.chk_autostart = QCheckBox("Lancer SpeakToFR au démarrage de Windows")
        for w in (self.chk_bar, self.chk_bar_start, self.chk_bar_dim, self.chk_selection, self.chk_autostart):
            ui.add(w)
        root.addWidget(ui)

        # --- Fenetre texte
        txt = _Group("Fenêtre texte")
        self.chk_show_text = QCheckBox("Afficher la fenêtre texte")
        self.chk_faithful = QCheckBox("Rendu fidèle à la page (images, fonds, couleurs)")
        self.chk_faithful.setToolTip(
            "Coché : la sélection est affichée comme sur la page (moteur Chromium).\n"
            "Décoché : rendu simplifié, texte seul. S'applique à la prochaine lecture."
        )
        self.chk_no_retranslate = QCheckBox("Ne pas retraduire un texte déjà en français")
        self.chk_force = QCheckBox("Toujours traduire (forcer googletrans)")
        self.chk_debug = QCheckBox("Enregistrer les fichiers HTML de debug")
        for w in (self.chk_show_text, self.chk_faithful, self.chk_no_retranslate, self.chk_force, self.chk_debug):
            txt.add(w)
        root.addWidget(txt)
        root.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self._content = content

        self._connect()
        self.refresh()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(500)
        self._status_timer.timeout.connect(self._refresh_status)
        BUS.settings_changed.connect(self.refresh)
        BUS.service_changed.connect(lambda *_: self.refresh())

    # ---------------------------------------------------------------- construction
    def _range_row(self, lo: int, hi: int, step: int, btn_step: int):
        slider = QSlider(Qt.Horizontal)
        slider.setRange(lo, hi)
        slider.setSingleStep(step)
        slider.setPageStep(btn_step * 2)
        slider.setCursor(Qt.PointingHandCursor)
        dec = QPushButton("-")
        inc = QPushButton("+")
        for b in (dec, inc):
            b.setObjectName("rangeBtn")
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setAutoRepeat(True)
        dec.clicked.connect(lambda: slider.setValue(slider.value() - btn_step))
        inc.clicked.connect(lambda: slider.setValue(slider.value() + btn_step))
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(dec)
        row.addWidget(slider, 1)
        row.addWidget(inc)
        value = QLabel()
        value.setObjectName("mono")
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return slider, row, value

    def _connect(self) -> None:
        a = self._actions
        self.chk_pause.toggled.connect(a.set_service_paused)
        self.chk_mute.toggled.connect(a.set_muted)
        self.chk_auto.toggled.connect(a.set_auto_read)
        self.chk_partial.toggled.connect(a.set_read_partial)
        self.voice_combo.currentIndexChanged.connect(self._on_voice)
        self.speed_slider.valueChanged.connect(self._on_speed)
        self.volume_slider.valueChanged.connect(self._on_volume)
        self.btn_test.clicked.connect(a.test_voice)
        self.chk_bar.toggled.connect(a.set_bar_visible)
        self.chk_bar_start.toggled.connect(lambda v: save_prefs({"bar_start": bool(v)}))
        self.chk_bar_dim.toggled.connect(a.set_dim_unfocused)
        self.chk_selection.toggled.connect(a.set_selection_mode)
        self.chk_autostart.toggled.connect(a.set_autostart)
        self.chk_show_text.toggled.connect(a.set_show_text)
        self.chk_no_retranslate.toggled.connect(lambda v: save_prefs({"auto_detect_french": bool(v)}))
        self.chk_force.toggled.connect(lambda v: save_prefs({"force_translate": bool(v)}))
        self.chk_debug.toggled.connect(lambda v: save_prefs({"debug_html": bool(v)}))
        self.chk_faithful.toggled.connect(lambda v: save_prefs({"text_render_faithful": bool(v)}))

    # ---------------------------------------------------------------- evenements
    def _on_voice(self, row: int) -> None:
        idx = self.voice_combo.itemData(row)
        if idx is not None:
            self._actions.set_voice(int(idx))

    def _on_speed(self, value: int) -> None:
        self.speed_value.setText(f"{value}%")
        self._speed_timer.start()

    def _on_volume(self, value: int) -> None:
        self.volume_value.setText(f"{value}%")
        volume.set_volume(value, persist=False)  # immediat, meme en cours de phrase
        self._volume_timer.start()

    # ---------------------------------------------------------------- etat
    def refresh(self) -> None:
        """Relit l'etat courant (prefs, voix, volume...) sans declencher les actions."""
        a = self._actions
        prefs = load_prefs() or {}
        widgets = (
            self.chk_pause, self.chk_mute, self.chk_auto, self.chk_partial, self.voice_combo, self.speed_slider,
            self.volume_slider, self.chk_bar, self.chk_bar_start, self.chk_bar_dim, self.chk_selection,
            self.chk_autostart,
            self.chk_show_text, self.chk_faithful, self.chk_no_retranslate, self.chk_force, self.chk_debug,
        )
        for w in widgets:
            w.blockSignals(True)
        try:
            self.chk_pause.setChecked(bool(a.service_paused))
            self.chk_mute.setChecked(volume.is_muted())
            self.chk_auto.setChecked(a.auto_read())
            self.chk_partial.setChecked(a.read_partial())

            descs = [v.get("desc", "?") for v in STATE.voices]
            current = [self.voice_combo.itemData(i) for i in range(self.voice_combo.count())]
            if current != list(range(len(descs))):
                self.voice_combo.clear()
                for i, d in enumerate(descs):
                    self.voice_combo.addItem(_voice_label(d), i)
            if descs:
                self.voice_combo.setCurrentIndex(STATE.current_voice_index % len(descs))
            self.voice_combo.setEnabled(bool(descs))
            self.voice_combo.setProperty("muted", "true" if volume.is_muted() else "false")
            self.voice_combo.style().unpolish(self.voice_combo)
            self.voice_combo.style().polish(self.voice_combo)

            if not self.speed_slider.isSliderDown() and not self._speed_timer.isActive():
                try:
                    speed = float(prefs.get("speed", STATE.speed_value or 1.0))
                except (TypeError, ValueError):
                    speed = 1.0
                self.speed_slider.setValue(int(round(speed * 100)))
            self.speed_value.setText(f"{self.speed_slider.value()}%")

            if not self.volume_slider.isSliderDown() and not self._volume_timer.isActive():
                self.volume_slider.setValue(volume.get_volume())
            self.volume_value.setText(f"{self.volume_slider.value()}%")

            self.chk_bar.setChecked(a.bar_visible())
            self.chk_bar.setEnabled(a.minibar is not None)
            self.chk_bar_start.setChecked(bool(prefs.get("bar_start", True)))
            self.chk_bar_dim.setChecked(a.dim_unfocused())
            self.chk_selection.setChecked(a.selection_mode())
            self.chk_selection.setEnabled(a.selection is not None and a.selection.available)
            self.chk_autostart.setChecked(a.autostart())
            self.chk_show_text.setChecked(a.show_text_window())
            self.chk_no_retranslate.setChecked(bool(prefs.get("auto_detect_french", True)))
            self.chk_force.setChecked(bool(prefs.get("force_translate", False)))
            self.chk_debug.setChecked(bool(prefs.get("debug_html", False)))
            self.chk_faithful.setChecked(web_available() and bool(prefs.get("text_render_faithful", True)))
            self.chk_faithful.setEnabled(web_available())
        finally:
            for w in widgets:
                w.blockSignals(False)
        self._refresh_status()

    def _refresh_status(self) -> None:
        a = self._actions
        if a.service_paused:
            text, color = "● En pause", "#f14c4c"
        elif a.is_playing():
            text, color = "▶ Lecture en cours", "#3794ff"
        elif a.is_paused():
            text, color = "❚❚ Lecture en pause", "#cca700"
        else:
            text, color = "● Actif", "#89d185"
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color};")
        self.btn_test.setEnabled(not a.is_playing())

    def showEvent(self, event):
        self.refresh()
        self._status_timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self._status_timer.stop()
        super().hideEvent(event)

    def place_and_show(self) -> None:
        self._content.adjustSize()
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        wanted_h = self._content.sizeHint().height() + 2
        if avail is not None:
            wanted_h = min(wanted_h, int(avail.height() * 0.9))
        self.resize(self.width(), wanted_h)
        if not self.isVisible() and avail is not None:
            geo = avail
            x = avail.x() + (avail.width() - self.width()) // 2
            y = avail.y() + (avail.height() - wanted_h) // 2
            bar = self._actions.minibar
            try:
                if bar is not None and bar.isVisible():
                    # Sous la barre flottante, sans sortir de son ecran
                    x = bar.x() + bar.width() // 2 - self.width() // 2
                    y = bar.y() + bar.height() + 8
                    bar_screen = QGuiApplication.screenAt(bar.geometry().center())
                    if bar_screen is not None:
                        geo = bar_screen.availableGeometry()
            except RuntimeError:
                pass
            x = max(geo.x(), min(x, geo.right() - self.width()))
            y = max(geo.y(), min(y, geo.bottom() - wanted_h))
            self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()


_WINDOW = None


def show_options_window(actions) -> OptionsWindow:
    global _WINDOW
    if _WINDOW is None:
        _WINDOW = OptionsWindow(actions)
    _WINDOW.place_and_show()
    return _WINDOW
