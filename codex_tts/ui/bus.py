"""Signaux Qt partages : previent la barre flottante, les options et le menu quand un reglage change."""
from PySide6.QtCore import QObject, Signal


class _UiBus(QObject):
    # Voix, vitesse, volume, muet, fenetre texte, barre... (tout ce qui s'affiche dans les options)
    settings_changed = Signal()
    # True = service en pause
    service_changed = Signal(bool)


BUS = _UiBus()
