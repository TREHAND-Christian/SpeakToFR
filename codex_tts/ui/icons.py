"""Icones vectorielles de la barre flottante (reprises de CodexAudio)."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF


def make_icon(kind: str, color: tuple = (55, 55, 55), accent: tuple = (196, 58, 58)) -> QIcon:
    """Dessine une icone 24x24 (rendue a 2x pour les ecrans HiDPI)."""
    ratio = 2
    pm = QPixmap(24 * ratio, 24 * ratio)
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    main = QColor(*color)
    pen = QPen(main, 1.8)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(Qt.NoPen)
    p.setBrush(main)

    def speaker():
        p.setPen(Qt.NoPen)
        p.setBrush(main)
        p.drawPolygon(
            QPolygonF(
                [QPointF(3.5, 9), QPointF(7.5, 9), QPointF(12.5, 4.5), QPointF(12.5, 19.5), QPointF(7.5, 15), QPointF(3.5, 15)]
            )
        )

    if kind == "play":
        p.drawPolygon(QPolygonF([QPointF(7, 4.5), QPointF(19.5, 12), QPointF(7, 19.5)]))
    elif kind == "pause":
        p.drawRoundedRect(QRectF(6, 5, 4, 14), 1.2, 1.2)
        p.drawRoundedRect(QRectF(14, 5, 4, 14), 1.2, 1.2)
    elif kind == "stop":
        p.drawRoundedRect(QRectF(6, 6, 12, 12), 2, 2)
    elif kind == "volume":
        speaker()
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(9, 8, 8, 8), -50 * 16, 100 * 16)
        p.drawArc(QRectF(7, 4.5, 14, 15), -50 * 16, 100 * 16)
    elif kind == "muted":
        speaker()
        xpen = QPen(QColor(*accent), 2.0)
        xpen.setCapStyle(Qt.RoundCap)
        p.setPen(xpen)
        p.drawLine(QPointF(15.5, 9), QPointF(21, 15))
        p.drawLine(QPointF(21, 9), QPointF(15.5, 15))
    elif kind == "window":
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(3.5, 4.5, 17, 15), 2.5, 2.5)
        p.drawLine(QPointF(3.5, 9), QPointF(20.5, 9))
        p.drawLine(QPointF(7, 12.5), QPointF(17, 12.5))
        p.drawLine(QPointF(7, 15.8), QPointF(14, 15.8))
    elif kind == "gear":
        p.translate(12, 12)
        for _ in range(8):
            p.drawRoundedRect(QRectF(-1.7, -10, 3.4, 5), 0.8, 0.8)
            p.rotate(45)
        p.drawEllipse(QPointF(0, 0), 6.8, 6.8)
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.drawEllipse(QPointF(0, 0), 2.8, 2.8)
    elif kind == "check":
        # Coche blanche pour les cases a cocher des options
        cpen = QPen(main, 2.6)
        cpen.setCapStyle(Qt.RoundCap)
        cpen.setJoinStyle(Qt.RoundJoin)
        p.setPen(cpen)
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF([QPointF(5, 12.5), QPointF(10, 17.5), QPointF(19, 7)]))
    elif kind == "chevron":
        # Fleche des listes deroulantes
        cpen = QPen(main, 2.2)
        cpen.setCapStyle(Qt.RoundCap)
        cpen.setJoinStyle(Qt.RoundJoin)
        p.setPen(cpen)
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF([QPointF(6, 9.5), QPointF(12, 15.5), QPointF(18, 9.5)]))
    p.end()
    return QIcon(pm)


def icon_png(kind: str, path, color: tuple, size: int = 24) -> str:
    """Enregistre une icone en PNG (pour les feuilles de style Qt) et renvoie le chemin avec des '/'."""
    pix = make_icon(kind, color=color).pixmap(size, size)
    pix.save(str(path), "PNG")
    return str(path).replace("\\", "/")
