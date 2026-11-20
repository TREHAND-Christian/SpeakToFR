import logging
import re
import threading
from html import unescape
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Slot, QSize
from PySide6.QtGui import QColor, QGuiApplication, QPalette, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.prefs import load_prefs, save_prefs
from ..core.state import STATE
from ..core.tts_engine import set_voice_by_index, tts_pause, tts_resume
from ..playback.control import restart_current_sentence, stop_playback
from ..text.positions import subtract_ranges
from .css_colors import contrast_background
from .widgets import make_drag_handle, make_mini_icon, make_options_icon

log = logging.getLogger(__name__)

MODE_COMPLET = "complet"
MODE_OPTIONS = "options"
MODE_MINI = "mini"


class ControlWindow(QWidget):
    def __init__(self, text_len: int, highlight_callback, cleanup_callback=None):
        super().__init__()
        self.setWindowTitle("SpeakToFR")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self._highlight_callback = highlight_callback
        self._cleanup_callback = cleanup_callback
        self._pos_from_prefs = False
        self._last_saved_pos = None
        self._mode = MODE_COMPLET
        self._pre_view_has_content = False
        self._last_html = None
        self.highlight_allowed = True
        self.pre_exclude_ranges: list[tuple[int, int]] = []

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(12, 2, 12, 4)
        self._main_layout.setSpacing(2)

        # Barre boutons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(1)
        style = self.style()
        self.pause_icon = style.standardIcon(QStyle.SP_MediaPause)
        self.play_icon = style.standardIcon(QStyle.SP_MediaPlay)
        self.stop_icon = style.standardIcon(QStyle.SP_BrowserStop)
        self.open_icon = style.standardIcon(QStyle.SP_ArrowUp)
        self.close_icon = style.standardIcon(QStyle.SP_ArrowDown)
        self.up_icon = style.standardIcon(QStyle.SP_ArrowUp)
        self.down_icon = style.standardIcon(QStyle.SP_ArrowDown)
        # Icônes mode (actions cibles)
        self.mode_to_full_icon = style.standardIcon(QStyle.SP_TitleBarMaxButton)
        self.mode_to_options_icon = make_options_icon(QSize(16, 16))
        self.mode_to_mini_icon = make_mini_icon(QSize(16, 16))

        btn_row.addWidget(make_drag_handle(self, self))

        self.btn_pause = QPushButton("Pause", self)
        self.btn_pause.setIcon(self.pause_icon)

        self.btn_stop = QPushButton("Fermer", self)
        self.btn_stop.setIcon(self.stop_icon)

        btn_row.addWidget(self.btn_pause)
        btn_row.addWidget(self.btn_stop)
        # Ligne reglage directement dans la barre boutons
        self.voice_combo = QComboBox(self)
        self.voice_combo.setMinimumWidth(260)
        btn_row.addWidget(self.voice_combo)

        self.speed_box = QWidget(self)
        self.speed_box.setObjectName("speed_box")
        speed_layout = QHBoxLayout(self.speed_box)
        speed_layout.setContentsMargins(8, 4, 8, 4)
        speed_layout.setSpacing(4)

        self.speed_label = QLabel("Vitesse 1.0", self.speed_box)
        speed_layout.addWidget(self.speed_label)

        self.speed_slider = QSlider(Qt.Horizontal, self.speed_box)
        self.speed_slider.setRange(0, 20)  # 0.0 -> 2.0
        self.speed_slider.setSingleStep(1)
        self.speed_slider.setValue(10)
        self.speed_slider.setMinimumWidth(200)
        speed_layout.addWidget(self.speed_slider, 1)

        btn_row.addWidget(self.speed_box, 1)

        btn_row.addStretch(1)
        # Navigation phrases (unique ligne)
        icon_skip_back = style.standardIcon(QStyle.SP_MediaSkipBackward)
        icon_skip_fwd = style.standardIcon(QStyle.SP_MediaSkipForward)
        icon_seek_back = style.standardIcon(QStyle.SP_MediaSeekBackward)
        icon_seek_fwd = style.standardIcon(QStyle.SP_MediaSeekForward)
        nav_icon_size = QSize(16, 16)
        nav_btn_size = QSize(28, 28)

        self.nav_container = QWidget(self)
        self.nav_container.setObjectName("nav_container")
        nav_layout = QHBoxLayout(self.nav_container)
        nav_layout.setContentsMargins(6, 2, 6, 2)
        nav_layout.setSpacing(1)

        self.btn_first = QPushButton(self)
        self.btn_first.setIcon(icon_skip_back)
        self.btn_first.setIconSize(nav_icon_size)
        self.btn_first.setToolTip("Premiere phrase")
        self.btn_first.setFixedSize(nav_btn_size)
        nav_layout.addWidget(self.btn_first)

        self.btn_prev = QPushButton(self)
        self.btn_prev.setIcon(icon_seek_back)
        self.btn_prev.setIconSize(nav_icon_size)
        self.btn_prev.setToolTip("Phrase precedente")
        self.btn_prev.setFixedSize(nav_btn_size)
        nav_layout.addWidget(self.btn_prev)

        self.btn_next = QPushButton(self)
        self.btn_next.setIcon(icon_seek_fwd)
        self.btn_next.setIconSize(nav_icon_size)
        self.btn_next.setToolTip("Phrase suivante")
        self.btn_next.setFixedSize(nav_btn_size)
        nav_layout.addWidget(self.btn_next)

        self.btn_last = QPushButton(self)
        self.btn_last.setIcon(icon_skip_fwd)
        self.btn_last.setIconSize(nav_icon_size)
        self.btn_last.setToolTip("Derniere phrase")
        self.btn_last.setFixedSize(nav_btn_size)
        nav_layout.addWidget(self.btn_last)
        nav_layout.addStretch(1)

        btn_row.addWidget(self.nav_container)

        self.btn_close_ui = QPushButton(self)
        self.btn_close_ui.setIcon(self.mode_to_options_icon)
        self.btn_close_ui.setIconSize(nav_icon_size)
        self.btn_close_ui.setFixedSize(nav_btn_size)
        self.btn_close_ui.setToolTip("Passer en mode options")

        self.btn_expand_options = QPushButton(self)
        self.btn_expand_options.setIcon(self.mode_to_mini_icon)
        self.btn_expand_options.setIconSize(nav_icon_size)
        self.btn_expand_options.setFixedSize(nav_btn_size)
        self.btn_expand_options.setToolTip("Passer en mode mini")
        self.btn_expand_options.setVisible(True)

        self.mode_container = QWidget(self)
        self.mode_container.setObjectName("mode_container")
        mode_layout = QHBoxLayout(self.mode_container)
        mode_layout.setContentsMargins(6, 2, 6, 2)
        mode_layout.setSpacing(1)
        mode_layout.addWidget(self.btn_close_ui)
        mode_layout.addWidget(self.btn_expand_options)
        btn_row.addWidget(self.mode_container)

        # Navigation phrases (ligne unique en fin de barre)
        self.top_bar = QWidget(self)
        self.top_bar.setLayout(btn_row)
        self._main_layout.addWidget(self.top_bar)
        # Style du cadre vitesse
        self.setStyleSheet(
            """
            QWidget#speed_box {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                background: #f8f8f8;
            }
            QWidget#nav_container {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                background: #f8f8f8;
            }
            QWidget#mode_container {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                background: #f8f8f8;
            }
            """
        )

        # Ligne navigation phrases

        # Zone texte
        self.text_edit = QTextEdit(self)
        # Panneau "Code" pour afficher le contenu réel des <pre> (visuel uniquement)
        self.pre_view = QTextEdit()
        self.pre_view.setReadOnly(True)
        self.pre_view.setVisible(False)
        self.pre_view.setStyleSheet(
            "QTextEdit { background: #000000; color: #ffffff; font-family: Consolas, monospace; border: 2px solid #ffffff; }"
        )

        self.text_edit.setReadOnly(True)
        self.text_edit.setAcceptRichText(True)
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.text_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._apply_text_background_contrast()
        self._main_layout.addWidget(self.text_edit)
        self._main_layout.addWidget(self.pre_view)

        self.info_widget = QWidget(self)
        info_row = QHBoxLayout(self.info_widget)
        info_row.setContentsMargins(0, 0, 0, 0)
        info_row.addStretch(1)
        self.info_label = QLabel(f"Lecture ({text_len} caracteres)", self)
        info_row.addWidget(self.info_label)
        self.info_widget.setLayout(info_row)
        self._main_layout.addWidget(self.info_widget)

        # Handlers
        self.btn_pause.clicked.connect(self.on_pause_clicked)
        self.btn_stop.clicked.connect(self.on_stop_clicked)
        self.voice_combo.currentTextChanged.connect(self.on_voice_changed)
        self.speed_slider.valueChanged.connect(self.on_speed_changed)
        self.btn_first.clicked.connect(lambda: self._jump_to_sentence(0))
        self.btn_prev.clicked.connect(lambda: self._jump_to_sentence(STATE.playback.sentence_index - 1))
        self.btn_next.clicked.connect(lambda: self._jump_to_sentence(STATE.playback.sentence_index + 1))
        self.btn_last.clicked.connect(lambda: self._jump_to_sentence(len(STATE.playback.sentence_parts) - 1))
        self.btn_close_ui.clicked.connect(self._handle_collapse_button)
        self.btn_expand_options.clicked.connect(self._handle_option_button)

        # Position sauvegardee
        self._apply_saved_position()
        # Etat mode sauvegarde
        self._apply_saved_mode()

    def set_highlight_callback(self, callback):
        self._highlight_callback = callback

    @Slot(int)
    def apply_highlight_slot(self, index: int):
        if self._highlight_callback:
            self._highlight_callback(index)

    def on_pause_clicked(self):
        try:
            if not STATE.playback.paused:
                self.btn_pause.setText("Reprendre")
                self.btn_pause.setIcon(self.play_icon)
                tts_pause()
            else:
                self.btn_pause.setText("Pause")
                self.btn_pause.setIcon(self.pause_icon)
                tts_resume()
            if self._mode == MODE_MINI:
                self.btn_pause.setText("")
        except Exception:
            log.exception("Pause/reprise impossible")

    def on_stop_clicked(self):
        threading.Thread(target=stop_playback, daemon=True).start()
        if self._cleanup_callback:
            try:
                self._cleanup_callback(clear_clipboard=True)
            except Exception:
                pass

    def on_voice_changed(self, text: str):
        try:
            for i, v in enumerate(STATE.voices):
                if v["desc"] == text:
                    set_voice_by_index(i)
                    restart_current_sentence(stop_existing=True, adjust_layout=False)
                    save_prefs({"voice": text})
                    break
        except Exception:
            pass

    def on_speed_changed(self, value: int):
        val = float(value) / 10.0
        STATE.speed_value = val
        self.speed_label.setText(f"Vitesse {val:.1f}")
        restart_current_sentence(debounce_ms=200, stop_existing=True, adjust_layout=False)
        save_prefs({"speed": val})

    def schedule_adjust(self):
        QTimer.singleShot(0, self._adjust_height_to_text)

    def _adjust_height_to_text(self):
        """Hauteur auto : fenetre clamp 90% ecran, QTextEdit = min(texte, espace dispo)."""
        screen = QGuiApplication.primaryScreen()
        max_h = int(screen.availableGeometry().height()) if screen else 1000
        max_win_h = int(max_h * 0.9)

        # Hauteur du texte rendu
        doc = self.text_edit.document()
        layout = doc.documentLayout()
        doc_h = layout.documentSize().height() if layout else doc.size().height()
        if doc_h <= 0:
            doc_h = 80

        m = self.text_edit.contentsMargins()
        frame = self.text_edit.frameWidth() * 2
        text_needed_h = int(doc_h + m.top() + m.bottom() + frame)

        # Hauteur fixe des barres + marges layout
        lm, tm, rm, bm = self._main_layout.getContentsMargins()
        spacing = self._main_layout.spacing()
        top_h = self.top_bar.sizeHint().height()
        info_h = self.info_widget.sizeHint().height()
        fixed_parts_h = top_h + info_h + tm + bm + spacing * 2

        compact_mode = self._mode in (MODE_OPTIONS, MODE_MINI)
        if compact_mode:
            # Mode compact : seulement la barre du haut
            final_win_h = min(max_win_h, top_h + tm + bm)
        else:
            ideal_win_h = fixed_parts_h + text_needed_h
            final_win_h = min(ideal_win_h, max_win_h)

            avail_text_h = max(0, final_win_h - fixed_parts_h)
            text_final_h = min(text_needed_h, avail_text_h if avail_text_h > 0 else text_needed_h)
            self.text_edit.setMinimumHeight(text_final_h)
            self.text_edit.setMaximumHeight(avail_text_h if avail_text_h > 0 else text_final_h)
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.setMaximumHeight(max_h)
        # Centre/replace la fenetre uniquement si aucune position sauvegardee
        target_w = self.width() or self.sizeHint().width()
        if compact_mode:
            target_w = self.top_bar.sizeHint().width() + 20
        self.resize(target_w, final_win_h)
        try:
            if self._pos_from_prefs and self._last_saved_pos:
                self.move(*self._last_saved_pos)
            else:
                screen_geom = screen.availableGeometry()
                x = screen_geom.x() + (screen_geom.width() - target_w) // 2
                if compact_mode:
                    y = screen_geom.y()
                else:
                    y = screen_geom.y() + (screen_geom.height() - final_win_h) // 2
                self.move(x, y)
        except Exception:
            pass

    def _normalize_mode(self, mode: str) -> str:
        val = str(mode or "").strip().lower()
        if val in ("complet", "complete", "full"):
            return MODE_COMPLET
        if val in ("options", "option"):
            return MODE_OPTIONS
        if val in ("mini", "minimal", "compact"):
            return MODE_MINI
        return MODE_COMPLET

    def _set_layout_density(self, compact: bool) -> None:
        if compact:
            self._main_layout.setContentsMargins(4, 2, 4, 2)
            self._main_layout.setSpacing(0)
            self.top_bar.layout().setContentsMargins(0, 0, 0, 0)
            self.top_bar.layout().setSpacing(0)
        else:
            self._main_layout.setContentsMargins(12, 2, 12, 4)
            self._main_layout.setSpacing(2)
            self.top_bar.layout().setContentsMargins(0, 0, 0, 0)
            self.top_bar.layout().setSpacing(1)

    def _apply_text_background_contrast(self) -> None:
        palette = self.text_edit.palette()
        palette.setColor(QPalette.Base, contrast_background(self.text_edit, self._last_html))
        self.text_edit.setPalette(palette)

    def _handle_collapse_button(self):
        mode = self._mode
        if mode == MODE_COMPLET:
            self._set_mode(MODE_OPTIONS)
        else:
            self._set_mode(MODE_COMPLET)

    def _handle_option_button(self):
        mode = self._mode
        if mode in (MODE_COMPLET, MODE_OPTIONS):
            self._set_mode(MODE_MINI)
        else:
            self._set_mode(MODE_OPTIONS)

    def _set_mode(self, mode: str, persist: bool = True):
        normalized = self._normalize_mode(mode)
        self._mode = normalized

        is_complet = normalized == MODE_COMPLET
        is_options = normalized == MODE_OPTIONS
        is_mini = normalized == MODE_MINI

        # Icon toggle
        if is_complet:
            self.btn_close_ui.setIcon(self.mode_to_options_icon)
            self.btn_close_ui.setToolTip("Passer en mode réglage")
            self.btn_expand_options.setIcon(self.mode_to_mini_icon)
            self.btn_expand_options.setToolTip("Passer en mode discret")
        elif is_options:
            self.btn_close_ui.setIcon(self.mode_to_full_icon)
            self.btn_close_ui.setToolTip("Passer en mode lecture")
            self.btn_expand_options.setIcon(self.mode_to_mini_icon)
            self.btn_expand_options.setToolTip("Passer en mode discret")
        else:
            self.btn_close_ui.setIcon(self.mode_to_full_icon)
            self.btn_close_ui.setToolTip("Passer en mode lecture")
            self.btn_expand_options.setIcon(self.mode_to_options_icon)
            self.btn_expand_options.setToolTip("Passer en mode réglage")

        show_options = is_complet or is_options
        show_text = is_complet

        for w in (self.voice_combo, self.speed_box, self.nav_container):
            w.setVisible(show_options)

        self.text_edit.setVisible(show_text)
        self.pre_view.setVisible(show_text and self._pre_view_has_content)
        self.info_widget.setVisible(show_text)

        self._set_layout_density(compact=not is_complet)

        if is_mini:
            self.btn_pause.setText("")
            self.btn_stop.setText("")
        else:
            self.btn_pause.setText("Pause" if not STATE.playback.paused else "Reprendre")
            self.btn_stop.setText("Fermer")

        if persist:
            try:
                save_prefs({"mode": normalized})
            except Exception:
                pass

        self.schedule_adjust()

    def _jump_to_sentence(self, idx: int):
        if not STATE.playback.sentence_parts:
            return
        max_idx = len(STATE.playback.sentence_parts) - 1
        idx = max(0, min(idx, max_idx))

        # Saute les phrases marquees <pre> dans les deux sens.
        skip_flags = STATE.playback.sentence_skip
        if skip_flags and 0 <= idx <= max_idx and idx < len(skip_flags):
            if skip_flags[idx]:
                if idx <= STATE.playback.sentence_index:
                    # Remonter
                    while idx > 0 and idx < len(skip_flags) and skip_flags[idx]:
                        idx -= 1
                else:
                    # Descendre
                    while idx < max_idx and idx < len(skip_flags) and skip_flags[idx]:
                        idx += 1

        STATE.playback.sentence_index = idx
        restart_current_sentence(stop_existing=True, adjust_layout=False)

    def set_voice_items(self, values: list[str], current: str):
        self.voice_combo.clear()
        self.voice_combo.addItems(values)
        try:
            longest = max(values, key=len) if values else ""
            metrics = self.voice_combo.fontMetrics()
            pad = 40
            width_px = metrics.horizontalAdvance(longest) + pad
            self.voice_combo.setMinimumWidth(width_px)
            self.voice_combo.setMaximumWidth(width_px)
        except Exception:
            pass
        self.voice_combo.setCurrentText(current)

    def set_info(self, text: str):
        self.info_label.setText(text)

    def set_content(self, text: str, html: Optional[str] = None, original_html: Optional[str] = None):
        if html and html.strip():
            h = html.strip()
            # IMPORTANT: si le HTML contient déjà <html>, on NE re-wrappe PAS
            if "<html" in h.lower():
                self.text_edit.setHtml(h)
            else:
                self.text_edit.setHtml(f"<html><body>{h}</body></html>")
            self._last_html = h
        else:
            self.text_edit.setPlainText(text)
            self._last_html = None

        # Affichage des blocs <pre> dans un panneau séparé (visuel uniquement)
        try:
            if original_html:
                blocks = re.findall(r"<pre[^>]*>(.*?)</pre>", original_html, flags=re.IGNORECASE | re.DOTALL)
                if blocks:
                    cleaned = []
                    for b in blocks:
                        b_txt = re.sub(r"<[^>]+>", "", b)   # retire tags internes si besoin
                        b_txt = unescape(b_txt)
                        cleaned.append(b_txt.strip("\n"))

                    sep = "\n\n" + ("-" * 40) + "\n\n"
                    self.pre_view.setPlainText(sep.join(cleaned) + "\n")
                    self.pre_view.setVisible(True)
                    self._pre_view_has_content = True
                else:
                    self.pre_view.clear()
                    self.pre_view.setVisible(False)
                    self._pre_view_has_content = False
            else:
                self.pre_view.clear()
                self.pre_view.setVisible(False)
                self._pre_view_has_content = False
        except Exception:
            self.pre_view.clear()
            self.pre_view.setVisible(False)
            self._pre_view_has_content = False

        if self._mode != MODE_COMPLET:
            self.pre_view.setVisible(False)

        QTimer.singleShot(0, self._apply_text_background_contrast)
        self.schedule_adjust()

    def apply_highlight(self, start: int, end: int):
        """Surligne la phrase en cours sans la sélectionner. Les blocs <pre> ne sont pas surlignés."""
        if not self.highlight_allowed:
            return
        extra_selections = []
        if start < end:
            # Convertit les index "référence" -> index du texte réellement rendu par Qt
            mp = STATE.playback.ref_to_doc_map
            if isinstance(mp, list) and end < len(mp):
                start = mp[start] if 0 <= start < len(mp) else start
                end = mp[end] if 0 <= end < len(mp) else end

            # Clamp sur le texte réellement affiché
            doc_display = self.text_edit.document().toPlainText()
            doc_len = len(doc_display)
            start = max(0, min(start, doc_len))
            end = max(start, min(end, doc_len))

            excludes = self.pre_exclude_ranges

            segments = subtract_ranges(start, end, excludes)

            utf16_map = STATE.playback.doc_utf16_map

            for s, e in segments:
                if isinstance(utf16_map, list) and e < len(utf16_map):
                    s = utf16_map[s] if 0 <= s < len(utf16_map) else s
                    e = utf16_map[e] if 0 <= e < len(utf16_map) else e
                selection = QTextEdit.ExtraSelection()
                selection.format.setBackground(QColor("#fff4b8"))
                selection.format.setForeground(QColor("#000000"))
                cursor = self.text_edit.textCursor()
                cursor.setPosition(s)
                cursor.setPosition(e, QTextCursor.KeepAnchor)
                selection.cursor = cursor
                extra_selections.append(selection)

            # Centre la vue sur le début (hors <pre> si possible)
            if segments:
                visible_pos = segments[0][0]
                if isinstance(utf16_map, list) and visible_pos < len(utf16_map):
                    visible_pos = utf16_map[visible_pos]
                visible_cursor = self.text_edit.textCursor()
                visible_cursor.clearSelection()
                visible_cursor.setPosition(visible_pos)
                self.text_edit.setTextCursor(visible_cursor)
                self.text_edit.ensureCursorVisible()

        self.text_edit.setExtraSelections(extra_selections)

    def clear_highlight(self):
        self.text_edit.setExtraSelections([])

    def shrink_text_area(self):
        """Reduit la zone texte."""
        self.text_edit.setMinimumHeight(120)
        self._main_layout.invalidate()

    def closeEvent(self, event):
        threading.Thread(target=stop_playback, daemon=True).start()
        super().closeEvent(event)

    def moveEvent(self, event):
        super().moveEvent(event)
        try:
            pos = (self.x(), self.y())
            self._last_saved_pos = pos
            save_prefs({"x": pos[0], "y": pos[1]})
        except Exception:
            pass

    def _apply_saved_position(self):
        data = load_prefs()
        if data and "x" in data and "y" in data:
            self._pos_from_prefs = True
            self._last_saved_pos = (int(data["x"]), int(data["y"]))
            try:
                self.move(*self._last_saved_pos)
            except Exception:
                pass
        else:
            self._pos_from_prefs = False

    def _apply_saved_mode(self):
        data = load_prefs()
        if not data:
            self._set_mode(MODE_COMPLET, persist=False)
            return
        if "mode" in data:
            self._set_mode(data.get("mode"), persist=False)
            return
        self._set_mode(MODE_COMPLET, persist=False)
