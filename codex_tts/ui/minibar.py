"""Barre flottante de SpeakToFR, sur le modele de celle de CodexAudio.

Boutons : lecture/pause, stop, muet, fenetre texte, options.
Bordure verte = service actif, rouge = service en pause.
Barre normale seulement quand Claude Desktop est au premier plan, grisee dans toute
autre appli (VS Code compris : c'est alors la barre CodexAudio qui sert). Elle reprend ses
couleurs au survol de la souris et reste toujours cliquable.
La barre se deplace en glissant n'importe ou (boutons compris) ; sa position est memorisee.
"""
import ctypes
import logging

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPainterPath
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QPushButton, QWidget

from ..core import volume
from ..core.prefs import load_prefs, save_prefs
from ..services.foreground import FocusTracker
from .bus import BUS
from .icons import make_icon

log = logging.getLogger(__name__)

_MINIBAR_STYLE = """
QPushButton { border: none; border-radius: 6px; background: transparent; }
QPushButton:hover { background: rgba(0, 0, 0, 38); }
QPushButton:pressed { background: rgba(0, 0, 0, 70); }
QPushButton[active="true"] { background: rgba(0, 0, 0, 30); }
QPushButton[active="true"]:hover { background: rgba(0, 0, 0, 50); }
QToolTip { color: #f2f2f2; background-color: #2b2b2b; border: 1px solid #555; padding: 4px 6px; }
"""


class MiniBar(QWidget):
    def __init__(self, actions):
        super().__init__()
        self._actions = actions
        self._app_paused = False
        self._muted = False
        self._playing = False
        self._text_on = False
        self._active = False  # quelque chose a arreter (lecture, traduction, pause)
        self._selection = False  # texte selectionne hors Claude Desktop : Play le lit
        self._dimmed = False  # gris : Claude Desktop n'a pas le focus
        self._hover = False
        self._focus = FocusTracker()
        self._drag_active = False
        self._drag_offset = None
        self._drag_start_pos = None
        self._drag_pressed_button = None
        self._drag_moved = False

        self.setWindowTitle("SpeakToFR")
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setWindowFlag(Qt.Tool, True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        # Ne prend jamais le focus : l'appli au premier plan le garde, meme quand on clique la barre
        # (indispensable pour que Play copie la selection de cette appli)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowFlag(Qt.WindowDoesNotAcceptFocus, True)
        self.setFixedHeight(36)

        self.btn_play = QPushButton()
        self.btn_stop = QPushButton()
        self.btn_mute = QPushButton()
        self.btn_text = QPushButton()
        self.btn_opts = QPushButton()

        self.setStyleSheet(_MINIBAR_STYLE)
        for b in (self.btn_play, self.btn_stop, self.btn_mute, self.btn_text, self.btn_opts):
            b.setFixedSize(34, 28)
            b.setFlat(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setIconSize(QSize(20, 20))
            b.installEventFilter(self)

        kinds = ("play", "pause", "stop", "volume", "muted", "window", "gear")
        self._icons_on = {k: make_icon(k) for k in kinds}
        self._icons_dim = {k: make_icon(k, color=(165, 165, 165), accent=(205, 160, 160)) for k in kinds}
        self._icons = self._icons_on
        self.btn_opts.setToolTip("Ouvrir les options")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)
        for b in (self.btn_play, self.btn_stop, self.btn_mute, self.btn_text, self.btn_opts):
            layout.addWidget(b)

        self.btn_play.clicked.connect(self._actions.play_pause)
        self.btn_stop.clicked.connect(self._actions.stop)
        self.btn_mute.clicked.connect(self._actions.toggle_mute)
        self.btn_text.clicked.connect(self._actions.toggle_text_window)
        self.btn_opts.clicked.connect(self._actions.open_options)

        self._refresh_buttons()
        self._restore_position()

        # L'etat de lecture change dans des threads : on le relit regulierement
        self._poll = QTimer(self)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self.refresh_state)
        self._poll.start()
        BUS.settings_changed.connect(self.refresh_state)
        BUS.service_changed.connect(lambda *_: self.refresh_state())

    # ---------------------------------------------------------------- affichage
    def _set_no_activate(self) -> None:
        """WS_EX_NOACTIVATE : un clic sur la barre ne retire pas le focus a l'appli en cours."""
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            get_style = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_style = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            get_style.restype = ctypes.c_ssize_t
            get_style.argtypes = [ctypes.c_void_p, ctypes.c_int]
            set_style.restype = ctypes.c_ssize_t
            set_style.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
            GWL_EXSTYLE, WS_EX_NOACTIVATE = -20, 0x08000000
            style = get_style(hwnd, GWL_EXSTYLE)
            if not style & WS_EX_NOACTIVATE:
                set_style(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
        except Exception:
            log.exception("Style WS_EX_NOACTIVATE impossible")

    def showEvent(self, event):
        super().showEvent(event)
        self._set_no_activate()

    def ensure_on_top(self) -> None:
        try:
            self.show()
            self.raise_()
        except Exception:
            pass

    def refresh_state(self) -> None:
        focused = self._focus.update()
        selection = self._actions.selection_active()
        state = (
            bool(self._actions.service_paused),
            volume.is_muted(),
            self._actions.is_playing(),
            self._actions.show_text_window(),
            self._actions.dim_unfocused() and not (focused or selection) and not self._hover,
            self._actions.is_active(),
            selection,
        )
        current = (self._app_paused, self._muted, self._playing, self._text_on, self._dimmed, self._active,
                   self._selection)
        if state == current:
            return
        (self._app_paused, self._muted, self._playing, self._text_on, self._dimmed, self._active,
         self._selection) = state
        self._refresh_buttons()
        self.update()

    def _refresh_buttons(self) -> None:
        self._icons = self._icons_dim if self._dimmed else self._icons_on
        # Stop grise (et inactif) quand rien n'est en lecture
        self.btn_stop.setEnabled(self._active)
        self.btn_stop.setIcon((self._icons if self._active else self._icons_dim)["stop"])
        self.btn_stop.setToolTip("Arrêter la lecture" if self._active else "Rien en lecture")
        self.btn_text.setIcon(self._icons["window"])
        self.btn_opts.setIcon(self._icons["gear"])
        self.btn_play.setIcon(self._icons["pause" if self._playing else "play"])
        self.btn_mute.setIcon(self._icons["muted" if self._muted else "volume"])
        if self._playing:
            self.btn_play.setToolTip("Mettre en pause la lecture")
        elif self._selection and not self._actions.is_paused():
            self.btn_play.setToolTip("Lire le texte sélectionné")
        else:
            self.btn_play.setToolTip("Lire / reprendre la lecture")
        self.btn_mute.setToolTip("Réactiver le son" if self._muted else "Couper le son (muet)")
        self.btn_text.setToolTip("Masquer la fenêtre texte" if self._text_on else "Afficher la fenêtre texte")
        self.btn_text.setProperty("active", "true" if self._text_on else "false")
        self.btn_text.style().unpolish(self.btn_text)
        self.btn_text.style().polish(self.btn_text)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if self._dimmed:
            border_color = QColor(206, 160, 160) if self._app_paused else QColor(170, 170, 170)
            bg_color = QColor(214, 214, 214)
        else:
            border_color = QColor(196, 58, 58) if self._app_paused else QColor(47, 191, 58)
            bg_color = QColor(230, 230, 230)
        border_width = 3
        radius = 8
        rect = self.rect().adjusted(border_width // 2, border_width // 2, -border_width // 2, -border_width // 2)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, bg_color)
        pen = painter.pen()
        pen.setColor(border_color)
        pen.setWidth(border_width)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    # La barre grisee reprend ses couleurs au survol (elle reste toujours cliquable)
    def enterEvent(self, event):
        self._hover = True
        self.refresh_state()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.refresh_state()
        super().leaveEvent(event)

    # ---------------------------------------------------------------- deplacement
    def eventFilter(self, obj, event):
        if not isinstance(obj, QAbstractButton):
            return super().eventFilter(obj, event)

        etype = event.type()
        if etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._drag_active = True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._drag_start_pos = event.globalPosition().toPoint()
            self._drag_pressed_button = obj
            self._drag_moved = False
            obj.setDown(True)
            event.accept()
            return True

        if etype == QEvent.MouseMove and self._drag_active and self._drag_pressed_button is obj:
            current = event.globalPosition().toPoint()
            if self._drag_start_pos is not None and (current - self._drag_start_pos).manhattanLength() > 3:
                self._drag_moved = True
                obj.setDown(False)
            if self._drag_moved and self._drag_offset is not None:
                self.move(current - self._drag_offset)
            event.accept()
            return True

        if (
            etype == QEvent.MouseButtonRelease
            and self._drag_active
            and self._drag_pressed_button is obj
            and event.button() == Qt.LeftButton
        ):
            obj.setDown(False)
            moved = self._drag_moved
            self._drag_active = False
            self._drag_offset = None
            self._drag_start_pos = None
            self._drag_pressed_button = None
            if moved:
                self._save_position()
            else:
                obj.click()
            event.accept()
            return True

        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_active = True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_active and self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_active:
            self._drag_active = False
            self._drag_offset = None
            self._save_position()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ---------------------------------------------------------------- position
    def _save_position(self) -> None:
        try:
            save_prefs({"bar_x": int(self.x()), "bar_y": int(self.y())})
        except Exception:
            log.exception("Sauvegarde de la position de la barre impossible")

    def _restore_position(self) -> None:
        self.adjustSize()
        prefs = load_prefs() or {}
        try:
            x, y = int(prefs["bar_x"]), int(prefs["bar_y"])
            # Verifie que la barre reste sur un ecran branche
            if QGuiApplication.screenAt(QPoint(x + 10, y + 10)) is not None:
                self.move(x, y)
                return
        except (KeyError, TypeError, ValueError):
            pass
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        w = self.sizeHint().width()
        self.move(geo.x() + (geo.width() - w) // 2, geo.y() + 6)
