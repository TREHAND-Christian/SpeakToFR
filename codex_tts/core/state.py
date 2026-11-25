"""Etat partage de l'application, regroupe par responsabilite.

STATE reste un singleton (les threads TTS et l'UI Qt s'y retrouvent), mais ses
attributs sont tous declares ici :
- STATE.playback : etat de la lecture en cours (drapeaux, phrases, offsets) ;
- STATE.ui       : references vers les objets Qt utilises hors de l'UI ;
- STATE.voices / current_voice_* / speed_value : choix de voix et vitesse.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from .onecore import OneCoreEngine


@dataclass
class PlaybackState:
    """Etat de la lecture en cours."""

    paused: bool = False
    pause_requested: bool = False
    stop_requested: bool = False

    sentence_index: int = 0
    sentence_parts: list[str] = field(default_factory=list)  # phrases affichees
    sentence_parts_tts: list[str] = field(default_factory=list)  # phrases lues
    sentence_positions: list[tuple[int, int]] = field(default_factory=list)
    sentence_skip: list[bool] = field(default_factory=list)  # phrases dans un <pre>
    pre_ranges: list[tuple[int, int]] = field(default_factory=list)

    # Dernier texte lu (pour relire apres changement de voix/vitesse)
    last_text: str = ""
    last_display_html: Optional[str] = None
    last_source_url: Optional[str] = None  # page d'origine de la selection (liens/images relatifs)

    # Lecture demandee et pas terminee (traduction, lecture ou pause) : pilote la barre flottante
    busy: bool = False
    # Origine de la derniere lecture : "claude" (reponse de Claude Desktop) ou "selection"
    last_origin: str = ""

    current_thread: Optional[threading.Thread] = None
    # Identifiant de lecture courant (evite le clignotement lors des relances)
    playback_token: int = 0
    # Timer de relance (debounce) pour les changements de vitesse/voix
    restart_timer: Any = None

    # Correspondance des offsets texte de reference -> texte rendu par Qt
    ref_to_doc_map: Optional[list[int]] = None
    doc_utf16_map: Optional[list[int]] = None

    def clear_flags(self) -> None:
        self.paused = False
        self.pause_requested = False
        self.stop_requested = False

    def request_stop(self) -> None:
        self.stop_requested = True
        self.pause_requested = False
        self.paused = False
        self.busy = False


@dataclass
class UiRefs:
    """References vers des objets Qt partages."""

    root: Any = None  # QApplication
    ctrl_window: Any = None
    voice_selector: Any = None
    no_selection_box: Any = None

    def clear_window(self) -> None:
        self.ctrl_window = None
        self.voice_selector = None


class TTSState:
    def __init__(self):
        try:
            self.onecore: Optional[OneCoreEngine] = OneCoreEngine()
        except Exception:
            self.onecore = None

        self.voices: list[dict] = self.onecore.list_voices() if self.onecore else []

        # Voix par defaut : "Paul" si present, sinon la premiere voix disponible
        self.current_voice_index = 0
        for i, v in enumerate(self.voices):
            if "paul" in (v.get("desc") or "").lower():
                self.current_voice_index = i
                break
        self.current_voice_desc = self.voices[self.current_voice_index]["desc"] if self.voices else "?"

        # Vitesse de lecture (multiplicateur)
        self.speed_value: float = 1.0

        self.playback = PlaybackState()
        self.ui = UiRefs()

    def engine_for(self, voice_entry):
        if voice_entry.get("kind") == "OneCore":
            return self.onecore
        return None

    def current_voice(self) -> Optional[dict]:
        if not self.voices:
            return None
        return self.voices[self.current_voice_index % len(self.voices)]

    def current_engine(self):
        voice = self.current_voice()
        return self.engine_for(voice) if voice else None


STATE = TTSState()
