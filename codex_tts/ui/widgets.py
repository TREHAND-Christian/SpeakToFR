"""Petits composants graphiques de la fenetre de controle (poignee, icones de mode)."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QWidget


class DragHandleLabel(QLabel):
    """Petite poignee permettant de deplacer la fenetre via drag."""

    def __init__(self, window: QWidget, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._win = window
        self._drag_offset = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._win is not None:
            self._drag_offset = event.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton and self._win is not None:
            self._win.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = None
        super().mouseReleaseEvent(event)


def make_drag_handle(window: QWidget, parent: QWidget) -> DragHandleLabel:
    """Poignee en points, placee en debut de barre."""
    pix = QPixmap(12, 28)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#7a7a7a"))
    painter.setPen(Qt.NoPen)
    spacing_x = 4
    spacing_y = 2
    for row in range(5):
        y = spacing_y + row * (4 + spacing_y)
        for col in range(3):
            painter.drawEllipse(1 + col * spacing_x, y, 4, 4)
    painter.end()

    handle = DragHandleLabel(window, parent)
    handle.setPixmap(pix)
    handle.setFixedSize(QSize(28, 28))
    handle.setAlignment(Qt.AlignCenter)
    handle.setCursor(Qt.OpenHandCursor)
    return handle


def make_options_icon(size: QSize) -> QIcon:
    """Icone mode options: fenetre basse (30%) avec barre superieure fine."""
    w = max(8, size.width())
    h = max(8, size.height())
    pix = QPixmap(w, h)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = painter.pen()
    pen.setColor(QColor("#000000"))
    pen.setWidth(1)
    painter.setPen(pen)
    body_h = max(3, int(h * 0.3))
    painter.drawRect(0, 0, w - 1, body_h - 1)
    painter.fillRect(0, 0, w, 2, QColor("#000000"))
    painter.end()
    return QIcon(pix)


def make_mini_icon(size: QSize) -> QIcon:
    """Icone mode mini: petite barre en haut, 50% largeur, alignee a gauche."""
    w = max(8, size.width())
    h = max(8, size.height())
    pix = QPixmap(w, h)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.fillRect(0, 0, max(3, int(w * 0.5)), 2, QColor("#000000"))
    painter.end()
    return QIcon(pix)
