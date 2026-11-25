"""Ancien dialogue de preferences, remplace par la fenetre Options (options_window.py).

Garde pour compatibilite : show_preferences_dialog() ouvre simplement les Options.
"""
from .app_actions import ACTIONS


def show_preferences_dialog(parent=None):
    ACTIONS.open_options()
