"""Etat global du moteur TTS et des fenetres (OneCore uniquement)."""
import asyncio
import html
import os
import tempfile
import threading
import time
import wave
import winsound
from array import array
from typing import Any, Optional

try:
    from winsdk.windows.media.speechsynthesis import SpeechSynthesizer
    from winsdk.windows.storage.streams import DataReader, InputStreamOptions

    HAS_ONECORE = True
except Exception:
    HAS_ONECORE = False


class OneCoreEngine:
    def __init__(self):
        if not HAS_ONECORE:
            raise RuntimeError("OneCore not available")
        self.synth = SpeechSynthesizer()
        try:
            self.default_rate = float(self.synth.options.speaking_rate)
        except Exception:
            self.default_rate = None
        self.voices = list(SpeechSynthesizer.all_voices)
        self.stop_flag = False

    def list_voices(self):
        return [{"kind": "OneCore", "token": v, "desc": v.display_name} for v in self.voices]

    def _scale_rate(self, rate: float) -> float:
        """Mappe directement le slider 0.0-2.0 vers OneCore, avec clamp de securite."""
        try:
            r = float(rate)
        except Exception:
            r = 1.0
        return max(0.1, min(2.0, r))

    def _ssml(self, text: str, rate: float) -> str:
        safe_text = html.escape(text)
        pct = max(10, min(int(rate * 100), 300))
        return (
            "<speak version='1.0' xml:lang='fr-FR'>"
            f"<prosody rate='{pct}%'>{safe_text}</prosody>"
            "</speak>"
        )

    async def _synth_to_wav(self, token, text: str, rate: float) -> str:
        self.synth.voice = token
        scaled = self._scale_rate(rate)
        base = self.default_rate if self.default_rate is not None else 1.0
        try:
            if abs(scaled - 1.0) < 1e-3:
                self.synth.options.speaking_rate = base
            else:
                self.synth.options.speaking_rate = base * scaled
        except Exception:
            pass
        # Utilise la synthese texte standard (evite le double effet SSML + speaking_rate)
        stream = await self.synth.synthesize_text_to_stream_async(text)
        size = stream.size
        reader = DataReader(stream)
        reader.input_stream_options = InputStreamOptions.READ_AHEAD
        await reader.load_async(size)
        buf = array("B", [0]) * size
        reader.read_bytes(buf)
        data = buf.tobytes()
        f = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        f.write(data)
        f.close()
        return f.name

    def speak_blocking(self, token, text: str, rate: float = 1.0):
        self.stop_flag = False
        loop = asyncio.new_event_loop()
        wav = None
        try:
            wav = loop.run_until_complete(self._synth_to_wav(token, text, rate))
        finally:
            try:
                loop.close()
            except Exception:
                pass
        if not wav:
            return

        # Lecture asynchrone pour pouvoir interrompre
        duration = 0.0
        try:
            with wave.open(wav, "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate() or 1
                duration = frames / float(rate)
        except Exception:
            duration = 0.0

        try:
            winsound.PlaySound(wav, winsound.SND_FILENAME | winsound.SND_ASYNC)
            waited = 0.0
            step = 0.05
            max_wait = duration + 0.5 if duration > 0 else 5.0
            while waited < max_wait and not self.stop_flag:
                time.sleep(step)
                waited += step
        finally:
            try:
                winsound.PlaySound(None, 0)
            except Exception:
                pass
            try:
                os.remove(wav)
            except Exception:
                pass

    def stop(self):
        self.stop_flag = True
        try:
            winsound.PlaySound(None, 0)
        except Exception:
            pass

    def pause(self):
        self.stop()

    def resume(self):
        pass


class TTSState:
    def __init__(self):
        self.sapi = None
        try:
            self.onecore = OneCoreEngine()
        except Exception:
            self.onecore = None

        self.voices = self.onecore.list_voices() if self.onecore else []

        # Voix par defaut : on choisit "Paul" si present, sinon la premiere voix disponible
        self.current_voice_index = 0
        for i, v in enumerate(self.voices):
            if "paul" in (v.get("desc") or "").lower():
                self.current_voice_index = i
                break
        self.current_voice_desc = self.voices[self.current_voice_index]["desc"] if self.voices else "?"

        # UI references (Qt widgets)
        self.ctrl_window: Any = None
        self.voice_label: Any = None
        self.trans_frame: Any = None
        self.trans_label: Any = None
        self.trans_info: Any = None
        self.pause_button: Any = None
        self.voice_selector: Any = None
        self.root: Any = None

        # Etat lecture
        self.paused: bool = False
        self.pause_requested: bool = False
        self.stop_requested: bool = False
        self.sentence_index: int = 0
        self.sentence_parts: list[str] = []
        self.sentence_positions: list[tuple[int, int]] = []

        # Fenetre de choix de voix
        self.voice_win: Any = None

        # Dernier texte lu (pour relire apres changement de voix)
        self.last_text: str = ""
        self.last_display_html: Any = None

        # Thread courant
        self.current_thread: Optional[threading.Thread] = None

        # Vitesse de lecture (multiplicateur)
        self.speed_value: float = 1.0

        # Identifiant de lecture courant (evite le clignotement lors des relances)
        self.playback_token: int = 0

        # Timer de relance (debounce) pour les changements de vitesse/voix
        self.restart_timer = None

    def engine_for(self, voice_entry):
        if voice_entry.get("kind") == "OneCore":
            return self.onecore
        return None


STATE = TTSState()
