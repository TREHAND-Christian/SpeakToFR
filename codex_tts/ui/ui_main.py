import json
import difflib
import threading
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Slot, QMetaObject, Q_ARG
from PySide6.QtWidgets import QApplication, QMessageBox

from ..core.state import STATE
from ..playback.control import restart_current_sentence, stop_playback
from ..services.clipboard import set_clipboard_text
from ..services.translator import translate_to_fr
from ..core.tts_engine import (
    tts_stop,
    tts_pause,
    tts_resume,
    set_voice_by_index,
    get_speed_multiplier,
)
from ..text.sentences import split_sentences_with_positions

from .window import ControlWindow
from .html_window import show_translated_html_window
from .prefs import load_window_prefs, save_window_prefs

from ..text.html_utils import (
    _strip_html_to_text,
    _strip_html_to_text_with_pre_ranges,
    _looks_like_html,
    _plain_to_html,
    _space_around_inline_code_links,
    _strip_empty_html_tags,
    _strip_html_comments,
    _mask_code_punct,
    _unmask_code_punct_tts,
    _unmask_code_punct_display,
    _mask_inline_dots,
    _spell_letters_tts,
    _looks_like_french,
    _spell_tts_http,
    _spell_tts_paths,
    _strip_tts_icons,
    _add_sentence_space_tts,
    _add_sentence_space_text,
    _add_sentence_space_with_ranges,
    _add_sentence_space_html,
    _trim_space_before_punct,
    _style_pre_blocks,
    _prep_html_for_positions,
    translate_html_preserve_markup,
)

_VOICE_PREFS_APPLIED = False

_HTML_DEBUG_DIR = Path(__file__).resolve().parents[2] / "html"


def _write_html_debug(suffix: str, html_code: Optional[str]) -> None:
    if html_code is None:
        return
    try:
        prefs = load_window_prefs() or {}
        if not prefs.get("debug_html", False):
            return
        _HTML_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        path = _HTML_DEBUG_DIR / f"{ts}_{suffix}.html"
        path.write_text(html_code, encoding="utf-8")
    except Exception:
        pass


def _build_utf16_index_map(text: str) -> list[int]:
    """Mappe les indexes Python (codepoints) vers les indexes UTF-16 (Qt)."""
    m = [0] * (len(text) + 1)
    utf16_index = 0
    for i, ch in enumerate(text):
        m[i] = utf16_index
        utf16_index += 2 if ord(ch) > 0xFFFF else 1
    m[len(text)] = utf16_index
    return m


def _cleanup_ui(clear_clipboard: bool = True):
    """Nettoie l'UI de controle et (optionnel) vide le presse-papiers."""
    win = STATE.ctrl_window
    try:
        if win is not None:
            win.close()
    except Exception:
        pass
    STATE.ctrl_window = None
    STATE.voice_label = None
    STATE.trans_frame = None
    STATE.trans_label = None
    STATE.trans_info = None
    STATE.pause_button = None
    STATE.voice_selector = None

    if clear_clipboard:
        try:
            set_clipboard_text("")
        except Exception:
            pass

def create_ctrl_window(app: QApplication, text_len: int, highlight_callback) -> ControlWindow:
    if STATE.ctrl_window is not None:
        try:
            STATE.ctrl_window.close()
        except Exception:
            pass
        STATE.ctrl_window = None

    win = ControlWindow(text_len, highlight_callback, cleanup_callback=_cleanup_ui)
    win.voice_combo.blockSignals(True)
    win.speed_slider.blockSignals(True)
    win.set_voice_items([v["desc"] for v in STATE.voices], STATE.current_voice_desc)

    prefs = load_window_prefs() or {}

    # Vitesse : default 1.0 si absent
    speed_val = float(prefs.get("speed", getattr(STATE, "speed_value", 1.0) or 1.0))
    win.speed_slider.setValue(int(speed_val * 10))
    win.speed_label.setText(f"Vitesse {speed_val:.1f}")
    STATE.speed_value = speed_val

    # Voix : default "Microsoft Paul" si présente
    target_voice = prefs.get("voice") or "Microsoft Paul"
    desc_list = [v["desc"] for v in STATE.voices]
    if target_voice in desc_list:
        target_index = desc_list.index(target_voice)
    else:
        target_index = desc_list.index("Microsoft Paul") if "Microsoft Paul" in desc_list else 0 if desc_list else 0
    if desc_list:
        win.voice_combo.setCurrentIndex(target_index)
        try:
            set_voice_by_index(target_index)
            STATE.current_voice_desc = desc_list[target_index]
        except Exception:
            pass

    win.voice_combo.blockSignals(False)
    win.speed_slider.blockSignals(False)
    
    STATE.ctrl_window = win
    STATE.voice_selector = win.voice_combo
    STATE.pause_button = win.btn_pause
    STATE.trans_label = win.text_edit
    return win


def speak_with_ui(
    app: QApplication,
    text: str,
    start_index: int = 0,
    reuse_ui: bool = False,
    stop_existing: bool = True,
    adjust_layout: bool = True,
    translate_text: bool = True,
    display_html_override: Optional[str] = None,
):
    if not text or text.strip() == "":
        return
    print(f"[CodexTTS] speak_with_ui: texte recu ({len(text)} chars), reuse_ui={reuse_ui}")
    if stop_existing:
        # Stop immediat de toute lecture en cours pour que la nouvelle prenne la main
        try:
            print("[CodexTTS] speak_with_ui: stop_playback initial")
            from ..playback.control import stop_playback

            stop_playback(clear_clipboard=False)
        except Exception as e:
            print(f"[CodexTTS] speak_with_ui: erreur stop_playback initial {e}")

    text = _strip_html_comments(text)
    # Detecte si on dispose d'HTML et derive une version texte pour le TTS
    html_fragment = text if _looks_like_html(text) else None
    if html_fragment:
        html_fragment = _strip_html_comments(html_fragment)
        html_fragment = _space_around_inline_code_links(html_fragment)
        html_fragment = _strip_empty_html_tags(html_fragment)
    base_text = _strip_html_to_text(text) if html_fragment else text
    _write_html_debug("before_translation", html_fragment or _plain_to_html(base_text))

    prefs = load_window_prefs() or {}
    auto_detect_french = bool(prefs.get("auto_detect_french", True))
    force_translate = bool(prefs.get("force_translate", False))

    # Si le texte ressemble déjà à du français, ne le retraduis pas
    if translate_text and auto_detect_french and not force_translate and _looks_like_french(base_text or ""):
        print("[CodexTTS] Texte detecte comme deja en francais, traduction desactivee.")
        translate_text = False

    use_fast_translation = False
    if translate_text and len(base_text) > 20000:
        print("[CodexTTS] Texte long, traduction simplifiee (sans preservation HTML) pour accelerer.")
        use_fast_translation = True
    try:
        # Ouvre immediatement la fenetre HTML avec le contenu brut (en attendant la traduction)
        initial_html = display_html_override or (html_fragment if html_fragment else _plain_to_html(base_text))
        show_translated_html_window(initial_html)
    except Exception as e:
        print(f"[CodexTTS] show_translated_html_window initial error: {e}")

    def notify_no_voice():
        msg = "Aucune voix OneCore detectee. Verifiez que les voix Windows sont installees."
        print(f"[CodexTTS] {msg}")
        try:
            QMessageBox.warning(app.activeWindow() or None, "CodexTTS", msg)
        except Exception:
            pass

    def start_playback(fr_text: str, display_html: Optional[str] = None, allow_highlight: bool = True, reuse_ui: bool = False):
        # Texte pour positions/TTS :
        # - On conserve le contenu des <pre> (pour l'affichage),
        # - mais on enregistre ses ranges afin de l'ignorer en TTS/surlignage.
        pre_ranges = []
        if display_html:
            display_plain_masked, pre_ranges = _strip_html_to_text_with_pre_ranges(display_html)
        else:
            display_plain_masked = fr_text or ""
            pre_ranges = []

        # Masque les points internes (domaine, email, fichiers) pour ne pas couper les phrases
        display_plain_masked = _mask_inline_dots(display_plain_masked)
        display_plain_masked, pre_ranges = _add_sentence_space_with_ranges(display_plain_masked, pre_ranges)

        # Ranges des <pre> dans le texte affiché (pour ignorer la surbrillance à l'intérieur)
        STATE.pre_ranges = pre_ranges
        # Version affichable (ponctuation démasquée dans <code>/<a>)
        display_plain_unmasked = _unmask_code_punct_display(display_plain_masked)

        # HTML affiché (original), stylé pour <pre>
        html_for_display = _style_pre_blocks(_strip_html_comments(display_html)) if display_html else None
        _write_html_debug("display_in_app", html_for_display)

        # Normalisation newlines
        normalized_masked = display_plain_masked.replace("\r\n", "\n").replace("\r", "\n")
        normalized_unmasked = display_plain_unmasked.replace("\r\n", "\n").replace("\r", "\n")
        print(f"[CodexTTS] start_playback: texte normalise ({len(normalized_unmasked)} chars)")
        STATE.last_text = normalized_unmasked

        # Découpe sur la version masquée (les points à l'intérieur du code ne scindent pas)
        raw_sentences, positions = split_sentences_with_positions(normalized_masked)
        sentences_disp = [normalized_unmasked[st:en] for st, en in positions]
        if not sentences_disp:
            print("[CodexTTS] start_playback: aucune phrase detectee, abandon.")
            return

        # Version TTS : démasque ponctuation pour code/liens uniquement
        STATE.sentence_parts_tts = []
        for (start, end) in positions:
            masked_slice = display_plain_masked[start:end]
            # Retire le contenu appartenant à <pre> pour le TTS
            if pre_ranges:
                # calcule les sous-segments hors <pre>
                segs = [(start, end)]
                for a, b in pre_ranges:
                    new_segs = []
                    for x, y in segs:
                        if b <= x or a >= y:
                            new_segs.append((x, y))
                        else:
                            if x < a:
                                new_segs.append((x, a))
                            if b < y:
                                new_segs.append((b, y))
                    segs = new_segs
                masked_slice = ''.join(display_plain_masked[x:y] for x, y in segs)
            tts_s = _unmask_code_punct_tts(masked_slice)
            if "http" in tts_s.lower():
                tts_s = _spell_tts_http(tts_s)
            tts_s = _spell_tts_paths(tts_s)
            tts_s = _strip_tts_icons(tts_s)
            tts_s = _add_sentence_space_tts(tts_s)
            tts_s = _spell_letters_tts(tts_s)
            STATE.sentence_parts_tts.append(tts_s)

        STATE.sentence_parts = sentences_disp
        STATE.sentence_positions = positions
        STATE.sentence_index = min(max(0, start_index), len(sentences_disp) - 1)
        STATE.paused = False
        STATE.pause_requested = False
        STATE.stop_requested = False
        # La lecture en cours est deja arretee avant la traduction, inutile de stopper a nouveau

        # Appliquer les prefs (voix/vitesse) une seule fois au demarrage
        _apply_voice_speed_prefs_once()

        playback_id = getattr(STATE, "playback_token", 0) + 1
        STATE.playback_token = playback_id

        voice = STATE.voices[STATE.current_voice_index] if STATE.voices else None
        if not voice:
            return notify_no_voice()
        eng = STATE.engine_for(voice)
        if eng is None:
            return notify_no_voice()
        print(f"[CodexTTS] start_playback: voix active = {STATE.current_voice_desc}, playback_id={playback_id}")

        def highlight_sentence(idx: int):
            if STATE.ctrl_window is None:
                return
            if idx < 0 or idx >= len(STATE.sentence_positions):
                return
            try:
                if getattr(STATE, "sentence_skip", None) and idx < len(STATE.sentence_skip) and STATE.sentence_skip[idx]:
                    return
            except Exception:
                pass
            start, end = STATE.sentence_positions[idx]
            doc_display = STATE.ctrl_window.text_edit.document().toPlainText()
            doc_len = len(doc_display)
            start = max(0, min(start, doc_len))
            end = max(start, min(end, doc_len))
            # --- Skip visuel des <pre> : on ne touche ni au TTS, ni aux offsets, ni au split ---

            STATE.ctrl_window.apply_highlight(start, end)

        win: Optional[ControlWindow] = None
        if reuse_ui and STATE.ctrl_window is not None:
            win = STATE.ctrl_window
            win._highlight_callback = highlight_sentence # Re-assign callback
        
        if win is None:
            win = create_ctrl_window(app, len(fr_text), highlight_sentence)

        win.set_info(f"Lecture ({len(normalized_unmasked)} caracteres)")
        win.set_content(normalized_unmasked, html=html_for_display, original_html=display_html)

        # --- Alignement robuste des offsets ---
        # On mappe les index du texte de référence (normalisé) vers le texte réellement rendu par Qt.
        try:
            doc_plain = win.text_edit.document().toPlainText()
            doc_plain = doc_plain.replace("\r\n", "\n").replace("\r", "\n")
            ref_plain = normalized_unmasked
            if doc_plain and ref_plain and doc_plain != ref_plain:
                sm = difflib.SequenceMatcher(a=ref_plain, b=doc_plain, autojunk=False)
                m = [0] * (len(ref_plain) + 1)

                for tag, i1, i2, j1, j2 in sm.get_opcodes():
                    if tag == "equal":
                        # correspondance 1:1
                        for k in range(i1, i2 + 1):
                            m[k] = j1 + (k - i1)
                    else:
                        # zone différente: on mappe tout sur la position courante dans b
                        for k in range(i1, i2 + 1):
                            m[k] = j1

                # Clamp
                maxb = len(doc_plain)
                for k in range(len(m)):
                    if m[k] < 0:
                        m[k] = 0
                    elif m[k] > maxb:
                        m[k] = maxb

                STATE.ref_to_doc_map = m
                STATE.ref_to_doc_len = len(ref_plain)
                STATE.doc_plain_len = len(doc_plain)
            else:
                STATE.ref_to_doc_map = None
                STATE.ref_to_doc_len = 0
                STATE.doc_plain_len = 0
            STATE.doc_utf16_map = _build_utf16_index_map(doc_plain)
        except Exception:
            STATE.ref_to_doc_map = None
            STATE.ref_to_doc_len = 0
            STATE.doc_plain_len = 0
            STATE.doc_utf16_map = None

        # Ne pas surligner les zones <pre>
        try:
            win._pre_exclude_ranges = []
        except Exception:
            pass
        STATE.last_display_html = html_for_display
        win._highlight_allowed = bool(allow_highlight)
        win.show()
        win.raise_()
        win.activateWindow()
        try:
            html_for_window = html_for_display or _plain_to_html(normalized_unmasked)
            show_translated_html_window(html_for_window)
        except Exception as e:
            print(f"[CodexTTS] Impossible d'afficher la fenetre HTML: {e}")
        print("[CodexTTS] start_playback: fenetre affichee")

        # Recalcule les positions a partir du texte reel affiche par Qt pour garantir l'alignement du surlignage
        try:
            # Texte reel affiche par Qt
            doc_plain = win.text_edit.document().toPlainText().replace("\r\n", "\n").replace("\r", "\n")
            # Recalcule le TTS depuis un texte aligne sur l'affichage Qt
            prep_for_positions = _prep_html_for_positions(html_for_display or normalized_unmasked)
            doc_for_positions = _strip_html_to_text(prep_for_positions or (html_for_display or normalized_unmasked))
            doc_norm = doc_for_positions.replace("\r\n", "\n").replace("\r", "\n")
            if not doc_norm:
                doc_norm = doc_plain
            if len(doc_norm) != len(doc_plain) or doc_norm != doc_plain:
                doc_norm = doc_plain

            masked_doc = _mask_inline_dots(doc_norm)
            masked_sentences, masked_positions = split_sentences_with_positions(masked_doc)
            doc_positions = masked_positions
            doc_sentences = [doc_plain[s:e] for (s, e) in doc_positions]
            tts_parts = []
            if len(masked_sentences) == len(doc_sentences):
                for s in masked_sentences:
                    tts_s = _unmask_code_punct_tts(s)
                    if "http" in tts_s.lower():
                        tts_s = _spell_tts_http(tts_s)
                    tts_s = _spell_tts_paths(tts_s)
                    tts_s = _strip_tts_icons(tts_s)
                    tts_s = _add_sentence_space_tts(tts_s)
                    tts_s = _spell_letters_tts(tts_s)
                    tts_parts.append(tts_s)
            else:
                # Fallback : utiliser les phrases visibles sans masques
                for s in doc_sentences:
                    tts_s = s
                    if "http" in tts_s.lower():
                        tts_s = _spell_tts_http(tts_s)
                    tts_s = _spell_tts_paths(tts_s)
                    tts_s = _strip_tts_icons(tts_s)
                    tts_s = _add_sentence_space_tts(tts_s)
                    tts_s = _spell_letters_tts(tts_s)
                    tts_parts.append(tts_s)

            STATE.sentence_parts = doc_sentences
            STATE.sentence_positions = doc_positions
            STATE.sentence_parts_tts = tts_parts
            # Positions recalculées sur doc_plain: ne pas re-mapper via ref_to_doc_map.
            STATE.ref_to_doc_map = None
            STATE.ref_to_doc_len = 0
            STATE.doc_plain_len = 0

            # --- Skip <pre> for TTS + surbrillance ---
            # pre_ranges are (start,end) character ranges in the displayed plain text.
            def _overlaps_pre(a: int, b: int) -> bool:
                if not pre_ranges:
                    return False
                sentence_len = max(1, b - a)
                for p0, p1 in pre_ranges:
                    overlap_start = max(a, p0)
                    overlap_end = min(b, p1)
                    overlap_len = max(0, overlap_end - overlap_start)

                    # skip uniquement si la majorité de la phrase est dans <pre>
                    if overlap_len / sentence_len > 0.5:
                        return True
                return False

            try:
                skip_flags = [_overlaps_pre(s, e) for (s, e) in doc_positions]
            except Exception:
                skip_flags = [False] * len(doc_positions)

            STATE.sentence_skip = skip_flags
            # Ensure TTS never speaks <pre> content
            try:
                for i_sk, sk in enumerate(skip_flags):
                    if sk and i_sk < len(STATE.sentence_parts_tts):
                        STATE.sentence_parts_tts[i_sk] = ""
            except Exception:
                pass
            STATE.sentence_index = min(max(0, start_index), len(doc_sentences) - 1)
        except Exception as e:
            print(f"[CodexTTS] Recalc positions depuis Qt a echoue: {e}")

        # Assure que d'eventuelles fermetures de l'ancienne fenetre n'ont pas remis stop_requested
        STATE.stop_requested = False
        STATE.pause_requested = False
        STATE.paused = False
        print(f"[CodexTTS] start_playback: flags reset avant lecture (stop={STATE.stop_requested})")

        def clear_highlight():
            if STATE.ctrl_window is None:
                return
            STATE.ctrl_window.clear_highlight()

        def worker():
            try:
                print(f"[CodexTTS] worker: demarrage, phrases={len(STATE.sentence_parts)}, start_idx={STATE.sentence_index}")
                parts = STATE.sentence_parts
                for idx in range(STATE.sentence_index, len(parts)):
                    if STATE.stop_requested:
                        print("[CodexTTS] worker: stop_requested, sortie")
                        break
                    # Skip sentences that are inside/overlapping <pre>
                    try:
                        if getattr(STATE, "sentence_skip", None) and idx < len(STATE.sentence_skip) and STATE.sentence_skip[idx]:
                            continue
                    except Exception:
                        pass

                    sentence = parts[idx].strip()
                    if not sentence:
                        continue
                    STATE.sentence_index = idx

                    QMetaObject.invokeMethod(
                        win,
                        "apply_highlight_slot",
                        Qt.QueuedConnection,
                        Q_ARG(int, idx),
                    )

                    try:
                        speed = get_speed_multiplier()
                    except Exception:
                        speed = 1.0
                    try:
                        sentence_tts = STATE.sentence_parts_tts[idx]
                    except Exception:
                        sentence_tts = sentence
                    eng.speak_blocking(voice["token"], sentence_tts, rate=speed)
                    if STATE.stop_requested:
                        print(f"[CodexTTS] worker: stop apres lecture phrase {idx}")
                        break
                    if STATE.pause_requested:
                        print(f"[CodexTTS] worker: pause apres phrase {idx}")
                        STATE.sentence_index = idx
                        break
                if not STATE.pause_requested:
                    STATE.paused = False
            finally:
                print("[CodexTTS] worker: fin")
                STATE.current_thread = None

        def watcher():
            t = threading.Thread(target=worker, daemon=True)
            STATE.current_thread = t
            t.start()
            t.join()

            def cleanup():
                if playback_id != STATE.playback_token:
                    return
                if STATE.pause_requested or STATE.paused:
                    return
                _cleanup_ui(clear_clipboard=True)
                clear_highlight()

            QTimer.singleShot(0, cleanup)

        QTimer.singleShot(50, lambda: threading.Thread(target=watcher, daemon=True).start())

    def show_placeholder():
        try:
            # En reprise (reuse_ui=True) on conserve la fenêtre existante pour éviter de tout refermer
            if reuse_ui and STATE.ctrl_window is not None:
                return
            win = STATE.ctrl_window
            if win is not None:
                try:
                    win.close()
                except Exception:
                    pass
                STATE.ctrl_window = None
            win = create_ctrl_window(app, len(text), None)
            win.set_info("Traduction en cours...")
            win.set_content("Traduction en cours...")
            win.show()
            win.raise_()
            win.activateWindow()
            STATE.ctrl_window = win
        except Exception:
            pass

    # Affiche le placeholder immediatement pour eviter le delai si la traduction est longue
    try:
        QTimer.singleShot(0, app, show_placeholder)
    except Exception:
        try:
            QTimer.singleShot(0, show_placeholder)
        except Exception:
            pass

    def translate_and_dispatch():
        translated = base_text
        display_html = display_html_override
        allow_highlight = True

        if translate_text:
            QTimer.singleShot(0, app, show_placeholder)
            print("[CodexTTS] translate_and_dispatch: debut traduction")
            if display_html_override is None and html_fragment and not use_fast_translation:
                # Traduire les text nodes et conserver la structure HTML
                translated_plain, translated_html = translate_html_preserve_markup(html_fragment)
                translated = _add_sentence_space_text(translated_plain)
                translated = _trim_space_before_punct(translated)
                translated_html = _add_sentence_space_html(translated_html)
                translated_html = _space_around_inline_code_links(translated_html)
                display_html = _style_pre_blocks(translated_html)
                allow_highlight = True  # on laisse le highlight actif sur le texte traduit
                _write_html_debug("after_translation", translated_html)
            else:
                translated = translate_to_fr(base_text)
                translated = _add_sentence_space_text(translated)
                if display_html_override is None:
                    display_html = _plain_to_html(translated)
                display_html = _space_around_inline_code_links(display_html or "")
            print("[CodexTTS] translate_and_dispatch: traduction terminee")
            try:
                same = translated == base_text
                print(f"[CodexTTS] translate_and_dispatch: len(base)={len(base_text)}, len(translated)={len(translated)}, same={same}")
            except Exception:
                pass
        else:
            translated = base_text
            if display_html_override is None:
                if html_fragment:
                    display_html = _style_pre_blocks(html_fragment)
                else:
                    display_html = _plain_to_html(translated)

        try:
            # Post sur le thread Qt (receiver = app pour garantir la queue Qt)
            QTimer.singleShot(0, app, lambda: start_playback(translated, display_html, allow_highlight, True))
            print("[CodexTTS] translate_and_dispatch: start_playback poste sur le thread Qt")
        except Exception as e:
            print(f"[CodexTTS] translate_and_dispatch: fallback singleShot direct ({e})")
            QTimer.singleShot(0, lambda: start_playback(translated, display_html, allow_highlight, True))

    threading.Thread(target=translate_and_dispatch, daemon=True).start()

def _apply_voice_speed_prefs_once():
    global _VOICE_PREFS_APPLIED
    if _VOICE_PREFS_APPLIED:
        return
    prefs = load_window_prefs() or {}
    # Voix
    target_voice = prefs.get("voice")
    if target_voice and STATE.voices:
        for i, v in enumerate(STATE.voices):
            if v.get("desc") == target_voice:
                try:
                    set_voice_by_index(i)
                except Exception:
                    pass
                break
    # Vitesse
    if "speed" in prefs:
        try:
            STATE.speed_value = float(prefs.get("speed", 1.0))
        except Exception:
            STATE.speed_value = 1.0
    _VOICE_PREFS_APPLIED = True
