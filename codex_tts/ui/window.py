# window.py (Windows-like + 3 modes: normal / compact / masked)
from __future__ import annotations

import html
import re
from typing import Optional, Tuple, List, Callable

from PySide6.QtCore import Qt, QTimer, Slot, QSize
from PySide6.QtGui import QTextCursor, QTextCharFormat, QAction
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QLabel,
    QPushButton,
    QComboBox,
    QSlider,
    QSizePolicy,
    QStyle,
    QMenu,
)

from ..core.state import STATE
from ..core.tts_engine import tts_pause, tts_resume, set_voice_by_index
from ..services.fonctions import restart_current_sentence
from .prefs import load_window_prefs, save_window_prefs


class ControlWindow(QWidget):
    """
    UI Windows-like (Qt natif) + 3 modes d'affichage:

    Normal : _set_mode_normal()
      - Fenêtre actuelle (barre options + texte + status)
      - Boutons de droite: "<" => masked, "/\" => compact

    Compact : _set_mode_compact()
      - Seulement la barre d'options (sans zone texte) + boutons de droite
      - Boutons de droite: "<" => masked, "\/" => normal

    Masked : _set_mode_masked()
      - Seulement la barre d'options MAIS réduite: Pause + Phrases + 2 boutons de droite
      - Boutons de droite: ">" => compact, "\/" => normal

    Paramètres vitesse conformes au zip:
      - slider 0..20
      - 10 => 1.0
      - STATE.speed_value mis à jour + restart_current_sentence(debounce_ms=200)
    """

    MODE_NORMAL = "normal"
    MODE_COMPACT = "compact"
    MODE_MASKED = "masked"

    def __init__(
        self,
        text_len: int,
        highlight_callback: Callable[[int], None],
        cleanup_callback: Optional[Callable[[], None]] = None,
    ):
        super().__init__()
        self.setWindowTitle("SpeakToFR")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Window)

        self._highlight_callback = highlight_callback
        self._cleanup_callback = cleanup_callback

        self._mode: str = self.MODE_NORMAL

        # Support surbrillance (si utilisé par ui_main)
        self._last_highlight: Optional[Tuple[int, int]] = None
        self._highlight_timer = QTimer(self)
        self._highlight_timer.setSingleShot(True)
        self._highlight_timer.timeout.connect(self._apply_highlight_from_timer)

        # ---- Layout principal
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        style = self.style()
        icon_size = QSize(16, 16)
        sq_size = QSize(28, 28)

        self.pause_icon = style.standardIcon(QStyle.SP_MediaPause)
        self.play_icon = style.standardIcon(QStyle.SP_MediaPlay)

        # ---- Barre options (QWidget + HBox) => rendu Windows natif
        self.toolbar = QWidget(self)
        bar = QHBoxLayout(self.toolbar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(8)

        # Pause
        self.btn_pause = QPushButton("Pause", self.toolbar)
        self.btn_pause.setIcon(self.pause_icon)
        self.btn_pause.setIconSize(icon_size)
        self.btn_pause.clicked.connect(self.on_pause_clicked)
        bar.addWidget(self.btn_pause)

        # Voix
        bar.addSpacing(4)
        self.lbl_voice = QLabel("Voix", self.toolbar)
        bar.addWidget(self.lbl_voice)

        self.voice_combo = QComboBox(self.toolbar)
        self.voice_combo.setMinimumWidth(180)
        self.voice_combo.currentTextChanged.connect(self.on_voice_changed)
        bar.addWidget(self.voice_combo)

        # Spacer gauche -> centre
        self._sp_left = QWidget(self.toolbar)
        self._sp_left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(self._sp_left)

        # Vitesse au milieu
        self.speed_box = QWidget(self.toolbar)
        speed_lay = QHBoxLayout(self.speed_box)
        speed_lay.setContentsMargins(8, 2, 8, 2)
        speed_lay.setSpacing(6)

        self.speed_label = QLabel("Vitesse 1.0", self.speed_box)
        speed_lay.addWidget(self.speed_label)

        self.speed_slider = QSlider(Qt.Horizontal, self.speed_box)
        self.speed_slider.setRange(0, 20)   # 0.0 -> 2.0
        self.speed_slider.setSingleStep(1)
        self.speed_slider.setValue(10)     # 1.0
        self.speed_slider.setMinimumWidth(220)
        self.speed_slider.valueChanged.connect(self.on_speed_changed)
        speed_lay.addWidget(self.speed_slider, 1)

        bar.addWidget(self.speed_box)

        # Spacer centre -> droite
        self._sp_right = QWidget(self.toolbar)
        self._sp_right.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(self._sp_right)

        # Groupe phrases (4 boutons, style Windows)
        self.nav_container = QWidget(self.toolbar)
        nav = QHBoxLayout(self.nav_container)
        nav.setContentsMargins(6, 2, 6, 2)
        nav.setSpacing(1)

        def sq_btn(icon, tip):
            b = QPushButton(self.toolbar)
            b.setIcon(icon)
            b.setIconSize(icon_size)
            b.setToolTip(tip)
            b.setFixedSize(sq_size)
            return b

        self.btn_first = sq_btn(style.standardIcon(QStyle.SP_MediaSkipBackward), "Première phrase")
        self.btn_prev  = sq_btn(style.standardIcon(QStyle.SP_MediaSeekBackward), "Phrase précédente")
        self.btn_next  = sq_btn(style.standardIcon(QStyle.SP_MediaSeekForward), "Phrase suivante")
        self.btn_last  = sq_btn(style.standardIcon(QStyle.SP_MediaSkipForward), "Dernière phrase")

        nav.addWidget(self.btn_first)
        nav.addWidget(self.btn_prev)
        nav.addWidget(self.btn_next)
        nav.addWidget(self.btn_last)

        bar.addWidget(self.nav_container)

        # ---- Boutons de mode (tout à droite, même style que le groupe)
        self.mode_container = QWidget(self.toolbar)
        mode_lay = QHBoxLayout(self.mode_container)
        mode_lay.setContentsMargins(6, 2, 6, 2)
        mode_lay.setSpacing(1)

        self.btn_mode1 = QPushButton(self.toolbar)  # "<" ou ">"
        self.btn_mode1.setFixedSize(sq_size)
        self.btn_mode1.setToolTip("Masqué / Compact")

        self.btn_mode2 = QPushButton(self.toolbar)  # "/\" ou "\/"
        self.btn_mode2.setFixedSize(sq_size)
        self.btn_mode2.setToolTip("Compact / Normal")

        mode_lay.addWidget(self.btn_mode1)
        mode_lay.addWidget(self.btn_mode2)
        bar.addWidget(self.mode_container)

        # Menu attaché au mode2 (optionnel, mais demandé précédemment)
        self._menu = QMenu(self)
        act_prefs = QAction("Préférences…", self)
        act_about = QAction("À propos…", self)
        act_quit = QAction("Quitter", self)
        act_prefs.triggered.connect(self._show_prefs_placeholder)
        act_about.triggered.connect(self._show_about_placeholder)
        act_quit.triggered.connect(self.close)
        self._menu.addAction(act_prefs)
        self._menu.addAction(act_about)
        self._menu.addSeparator()
        self._menu.addAction(act_quit)
        # click-droit sur bouton2 ouvre menu (sans changer comportement principal)
        self.btn_mode2.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_mode2.customContextMenuRequested.connect(lambda pos: self._menu.exec(self.btn_mode2.mapToGlobal(pos)))

        # Connexions nav
        self.btn_first.clicked.connect(lambda: self._jump_to_sentence(0))
        self.btn_prev.clicked.connect(lambda: self._jump_to_sentence(STATE.sentence_index - 1))
        self.btn_next.clicked.connect(lambda: self._jump_to_sentence(STATE.sentence_index + 1))
        self.btn_last.clicked.connect(lambda: self._jump_to_sentence(len(STATE.sentence_parts) - 1 if STATE.sentence_parts else 0))

        # Connexions modes
        self.btn_mode1.clicked.connect(self._on_mode1_clicked)
        self.btn_mode2.clicked.connect(self._on_mode2_clicked)

        root.addWidget(self.toolbar)

        # Texte principal
        self.text_edit = QTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setAcceptRichText(True)
        self.text_edit.setMinimumHeight(220)
        root.addWidget(self.text_edit, 1)

        # Panneau <pre> (optionnel)
        self.pre_view = QTextEdit(self)
        self.pre_view.setReadOnly(True)
        self.pre_view.setAcceptRichText(False)
        self.pre_view.setVisible(False)
        self.pre_view.setMinimumHeight(120)
        root.addWidget(self.pre_view)

        # Ligne d'état en bas (sans cadre), alignée à droite
        self.status_label = QLabel("", self)
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status_label.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.status_label)

        # Appliquer prefs (position/vitesse)
        self._apply_saved_position()

        # Init mode normal (boutons corrects)
        self._set_mode_normal()

        # Affiche le statut demandé
        self.set_info(f"Lecture ({int(text_len)} caracteres)")

    # ---- Menu placeholders
    def _show_prefs_placeholder(self):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "SpeakToFR", "Préférences… (à implémenter)")

    def _show_about_placeholder(self):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "SpeakToFR", "SpeakToFR\nUI: PySide6 (style Windows)")

    # ---- Mode logic
    def _on_mode1_clicked(self):
        # Normal/Compact: "<" => masked ; Masked: ">" => compact
        if self._mode in (self.MODE_NORMAL, self.MODE_COMPACT):
            self._set_mode_masked()
        else:
            self._set_mode_compact()

    def _on_mode2_clicked(self):
        # Normal: "/\" => compact
        # Compact: "\/" => normal
        # Masked: "\/" => normal
        if self._mode == self.MODE_NORMAL:
            self._set_mode_compact()
        else:
            self._set_mode_normal()

    def _set_mode_normal(self):
        self._mode = self.MODE_NORMAL

        # Boutons de droite
        self.btn_mode1.setText("<")
        self.btn_mode2.setText("/\\")   # /\

        # Affichage: tout
        self._set_bar_reduced(False)
        self.text_edit.setVisible(True)
        self.status_label.setVisible(True)
        # pre_view seulement si contenu
        # (on laisse son état courant)

    def _set_mode_compact(self):
        self._mode = self.MODE_COMPACT

        self.btn_mode1.setText("<")
        self.btn_mode2.setText("\\/")   # \/

        # Affichage: barre complète, pas de texte ni status
        self._set_bar_reduced(False)
        self.text_edit.setVisible(False)
        self.pre_view.setVisible(False)
        self.status_label.setVisible(False)

    def _set_mode_masked(self):
        self._mode = self.MODE_MASKED

        self.btn_mode1.setText(">")
        self.btn_mode2.setText("\\/")   # \/

        # Affichage: barre réduite (Pause + Phrases + modes), pas de texte/status
        self._set_bar_reduced(True)
        self.text_edit.setVisible(False)
        self.pre_view.setVisible(False)
        self.status_label.setVisible(False)

    def _set_bar_reduced(self, reduced: bool):
        """Réduit la barre aux éléments demandés en mode masked."""
        self.lbl_voice.setVisible(not reduced)
        self.voice_combo.setVisible(not reduced)
        self.speed_box.setVisible(not reduced)
        self._sp_left.setVisible(not reduced)
        self._sp_right.setVisible(not reduced)

    # ---- Controls
    @Slot()
    def on_pause_clicked(self):
        try:
            if not getattr(STATE, "paused", False):
                self.btn_pause.setText("Reprendre")
                self.btn_pause.setIcon(self.play_icon)
                tts_pause()
                STATE.paused = True
            else:
                self.btn_pause.setText("Pause")
                self.btn_pause.setIcon(self.pause_icon)
                tts_resume()
                STATE.paused = False
        except Exception as e:
            print(f"[SpeakToFR] Pause/Resume error: {e}")

    def on_voice_changed(self, text: str):
        try:
            for i, v in enumerate(getattr(STATE, "voices", []) or []):
                if v.get("desc") == text:
                    set_voice_by_index(i)
                    restart_current_sentence(stop_existing=True, adjust_layout=False)
                    try:
                        save_window_prefs({"voice_desc": text})
                    except Exception:
                        pass
                    return
        except Exception:
            pass

    def on_speed_changed(self, value: int):
        val = float(value) / 10.0
        try:
            STATE.speed_value = val
        except Exception:
            pass
        self.speed_label.setText(f"Vitesse {val:.1f}")
        restart_current_sentence(debounce_ms=200, stop_existing=True, adjust_layout=False)
        try:
            save_window_prefs({"speed": val})
        except Exception:
            pass

    # ---- Navigation / Jump (zip-like + skip <pre>)
    def _jump_to_sentence(self, idx: int):
        if not getattr(STATE, "sentence_parts", None):
            return
        max_idx = len(STATE.sentence_parts) - 1
        idx = max(0, min(int(idx), max_idx))

        skip_flags = getattr(STATE, "sentence_skip", None) or []
        if skip_flags and 0 <= idx <= max_idx and idx < len(skip_flags):
            if skip_flags[idx]:
                if idx <= int(getattr(STATE, "sentence_index", 0)):
                    while idx > 0 and idx < len(skip_flags) and skip_flags[idx]:
                        idx -= 1
                else:
                    while idx < max_idx and idx < len(skip_flags) and skip_flags[idx]:
                        idx += 1

        STATE.sentence_index = idx
        restart_current_sentence(stop_existing=True, adjust_layout=False)

    # ---- API attendue par ui_main
    def set_voice_items(self, values: list[str], current: str):
        self.voice_combo.blockSignals(True)
        self.voice_combo.clear()
        self.voice_combo.addItems(values)
        try:
            if current in values:
                self.voice_combo.setCurrentText(current)
        except Exception:
            pass
        self.voice_combo.blockSignals(False)

    def set_info(self, text: str):
        # demandé: en bas, à droite, sans cadre
        self.status_label.setText(text or "")

    def set_content(self, text: str, html: Optional[str] = None, original_html: Optional[str] = None):
        if html and html.strip():
            h = html.strip()
            if "<html" in h.lower():
                self.text_edit.setHtml(h)
            else:
                self.text_edit.setHtml(f"<html><body>{h}</body></html>")
        else:
            self.text_edit.setPlainText(text or "")

        # Panneau <pre>
        try:
            if original_html:
                blocks = re.findall(r"<pre[^>]*>(.*?)</pre>", original_html, flags=re.IGNORECASE | re.DOTALL)
                if blocks:
                    cleaned = []
                    for b in blocks:
                        b_txt = re.sub(r"<[^>]+>", "", b)
                        b_txt = html.unescape(b_txt)
                        cleaned.append(b_txt.strip("\n"))
                    sep = "\n\n" + ("-" * 40) + "\n\n"
                    self.pre_view.setPlainText(sep.join(cleaned))
                    # visible seulement en mode normal
                    self.pre_view.setVisible(self._mode == self.MODE_NORMAL)
                else:
                    self.pre_view.setVisible(False)
            else:
                self.pre_view.setVisible(False)
        except Exception:
            self.pre_view.setVisible(False)

    def schedule_highlight(self, start: int, length: int, delay_ms: int = 0):
        self._last_highlight = (int(start), int(length))
        self._highlight_timer.start(max(0, int(delay_ms)))

    @Slot()
    def _apply_highlight_from_timer(self):
        if self._last_highlight is None:
            return
        start, length = self._last_highlight
        self.apply_highlight(start, length)

    def apply_highlight(self, start: int, length: int):
        if start < 0 or length <= 0:
            return
        try:
            cursor = self.text_edit.textCursor()
            cursor.setPosition(0)
            cursor.movePosition(QTextCursor.Right, QTextCursor.MoveAnchor, start)
            cursor.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, length)

            fmt = QTextCharFormat()
            fmt.setBackground(self.palette().highlight())
            fmt.setForeground(self.palette().highlightedText())
            cursor.mergeCharFormat(fmt)

            self.text_edit.setTextCursor(cursor)
            self._last_highlight = (start, length)
        except Exception:
            pass

    def clear_highlight(self):
        try:
            cursor = self.text_edit.textCursor()
            cursor.select(QTextCursor.Document)
            cursor.setCharFormat(QTextCharFormat())
        except Exception:
            pass
        self._last_highlight = None

    def shrink_text_area(self):
        # compat
        self.text_edit.setMinimumHeight(160)

    # ---- Prefs / geometry
    def closeEvent(self, event):
        try:
            prefs = load_window_prefs() or {}
            prefs["x"] = int(self.x())
            prefs["y"] = int(self.y())
            prefs["w"] = int(self.width())
            prefs["h"] = int(self.height())
            save_window_prefs(prefs)
        except Exception:
            pass

        try:
            if callable(self._cleanup_callback):
                self._cleanup_callback()
        except Exception:
            pass

        super().closeEvent(event)

    def _apply_saved_position(self):
        try:
            prefs = load_window_prefs() or {}
            x = prefs.get("x")
            y = prefs.get("y")
            w = prefs.get("w")
            h = prefs.get("h")
            speed = prefs.get("speed")
            if isinstance(speed, (int, float)):
                self.speed_slider.setValue(int(float(speed) * 10))
                self.speed_label.setText(f"Vitesse {float(speed):.1f}")

            if isinstance(w, int) and isinstance(h, int) and w > 200 and h > 150:
                self.resize(w, h)
            if isinstance(x, int) and isinstance(y, int):
                self.move(x, y)
        except Exception:
            pass
