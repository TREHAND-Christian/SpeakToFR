"""Point d'entree de la lecture : prepare le texte, le traduit, affiche la fenetre et lance la voix."""
import logging
import threading
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from ..core.prefs import load_prefs
from ..core.state import STATE
from ..playback.control import stop_playback
from ..playback.worker import start_playback_thread
from ..services.debug_html import write_html_debug
from ..services.html_inliner import inline_html_with_computed_styles
from ..services.translator import translate_to_fr
from ..text.display import (
    build_display_text,
    normalize_newlines,
    sentences_from_document,
    tts_parts_for_positions,
)
from ..text.html_style import style_pre_blocks
from ..text.html_text import (
    looks_like_html,
    plain_to_html,
    space_around_inline_code_links,
    strip_empty_html_tags,
    strip_html_comments,
    strip_html_to_text,
)
from ..text.html_translate import translate_html_preserve_markup
from ..text.positions import build_ref_to_doc_map, build_utf16_index_map, mostly_inside
from ..text.sentences import split_sentences_with_positions
from ..text.tts_prep import (
    add_sentence_space,
    add_sentence_space_html,
    looks_like_french,
    trim_space_before_punct,
)
from .alerts import NO_SELECTION_TEXT, notify_no_voice, show_no_selection_alert, speak_short_message
from .ctrl_window_factory import (
    apply_voice_speed_prefs_once,
    cleanup_ui,
    create_ctrl_window,
    finish_playback_ui,
    present_ctrl_window,
)

log = logging.getLogger(__name__)

# Au-dela, on traduit le texte brut sans preserver le HTML (plus rapide)
_FAST_TRANSLATION_THRESHOLD = 20000


def _highlight_sentence(idx: int) -> None:
    """Surligne la phrase `idx` dans la fenetre de controle (sauf phrases dans un <pre>)."""
    win = STATE.ui.ctrl_window
    pb = STATE.playback
    if win is None or idx < 0 or idx >= len(pb.sentence_positions):
        return
    if idx < len(pb.sentence_skip) and pb.sentence_skip[idx]:
        return
    start, end = pb.sentence_positions[idx]
    doc_len = len(win.text_edit.document().toPlainText())
    start = max(0, min(start, doc_len))
    end = max(start, min(end, doc_len))
    win.apply_highlight(start, end)


def _show_placeholder(app: QApplication, text_len: int, reuse_ui: bool) -> None:
    """Fenetre "Traduction en cours..." affichee tout de suite, avant la fin de la traduction."""
    try:
        # En reprise (reuse_ui=True) on conserve la fenetre existante
        if reuse_ui and STATE.ui.ctrl_window is not None:
            return
        win = create_ctrl_window(text_len, None)
        win.set_info("Traduction en cours...")
        win.set_content("Traduction en cours...")
        present_ctrl_window(win)
    except Exception:
        log.exception("Affichage de la fenetre d'attente impossible")


def _align_with_qt_document(win, normalized_unmasked: str, pre_ranges, start_index: int) -> None:
    """Calcule les offsets du surlignage a partir du texte reellement rendu par Qt."""
    pb = STATE.playback
    doc_plain = normalize_newlines(win.text_edit.document().toPlainText())
    pb.ref_to_doc_map = build_ref_to_doc_map(normalized_unmasked, doc_plain)
    pb.doc_utf16_map = build_utf16_index_map(doc_plain)

    # Les positions sont recalculees sur doc_plain : plus besoin de re-mapper via ref_to_doc_map.
    sentences, positions, tts_parts = sentences_from_document(doc_plain)
    pb.sentence_parts = sentences
    pb.sentence_positions = positions
    pb.sentence_parts_tts = tts_parts
    pb.ref_to_doc_map = None

    # Phrases majoritairement dans un <pre> : ni lues ni surlignees
    pb.sentence_skip = [mostly_inside(s, e, pre_ranges) for s, e in positions]
    for i, skip in enumerate(pb.sentence_skip):
        if skip:
            pb.sentence_parts_tts[i] = ""
    pb.sentence_index = min(max(0, start_index), max(0, len(sentences) - 1))


def _start_playback(
    app: QApplication,
    fr_text: str,
    display_html: Optional[str],
    allow_highlight: bool,
    reuse_ui: bool,
    start_index: int,
) -> None:
    pb = STATE.playback

    # Texte pour positions/TTS : le contenu des <pre> reste affiche, mais est masque pour la voix
    dt = build_display_text(display_html, fr_text)
    pb.pre_ranges = dt.pre_ranges

    # HTML affiche (original), style pour <pre>
    html_for_display = style_pre_blocks(strip_html_comments(display_html)) if display_html else None
    write_html_debug("display_in_app", html_for_display)

    normalized_masked = normalize_newlines(dt.masked)
    normalized_unmasked = normalize_newlines(dt.unmasked)
    log.debug("start_playback: texte normalise (%d chars)", len(normalized_unmasked))
    pb.last_text = normalized_unmasked

    # Decoupe sur la version masquee (les points a l'interieur du code ne scindent pas)
    _, positions = split_sentences_with_positions(normalized_masked)
    sentences_disp = [normalized_unmasked[st:en] for st, en in positions]
    if not sentences_disp:
        log.debug("start_playback: aucune phrase detectee, abandon")
        pb.busy = False
        return

    pb.sentence_parts_tts = tts_parts_for_positions(dt.masked, positions, dt.pre_ranges)
    pb.sentence_parts = sentences_disp
    pb.sentence_positions = positions
    pb.sentence_skip = []
    pb.sentence_index = min(max(0, start_index), len(sentences_disp) - 1)
    pb.clear_flags()

    apply_voice_speed_prefs_once()

    pb.playback_token += 1
    playback_id = pb.playback_token

    voice = STATE.current_voice()
    eng = STATE.current_engine()
    if not voice or eng is None:
        pb.busy = False
        return notify_no_voice(app)
    log.debug("start_playback: voix=%s, playback_id=%d", STATE.current_voice_desc, playback_id)

    win = STATE.ui.ctrl_window if reuse_ui else None
    if win is not None:
        win.set_highlight_callback(_highlight_sentence)
    else:
        win = create_ctrl_window(len(fr_text), _highlight_sentence)

    win.set_info(f"Lecture ({len(normalized_unmasked)} caracteres)")
    win.set_content(normalized_unmasked, html=html_for_display, original_html=display_html)
    pb.last_display_html = html_for_display
    win.highlight_allowed = bool(allow_highlight)
    # Fenetre texte visible seulement si l'option est cochee (barre flottante sinon)
    present_ctrl_window(win)

    try:
        _align_with_qt_document(win, normalized_unmasked, dt.pre_ranges, start_index)
    except Exception:
        log.exception("Recalcul des positions depuis Qt echoue, offsets du texte source conserves")
        pb.ref_to_doc_map = None
        pb.doc_utf16_map = None

    # Une fermeture de l'ancienne fenetre a pu remettre stop_requested
    pb.clear_flags()
    pb.busy = True
    start_playback_thread(win, eng, voice, playback_id, finish_playback_ui)


def show_idle_text_window(text: str, html: Optional[str] = None, info: str = "") -> None:
    """Fenetre texte sans lecture : montre la derniere reponse (le prochain Play la lira)."""
    win = STATE.ui.ctrl_window
    if win is None:
        win = create_ctrl_window(len(text), _highlight_sentence)
    win.clear_highlight()
    win.set_info(info)
    win.set_content(text, html=html, original_html=html)
    present_ctrl_window(win)


def _translate(
    base_text: str,
    html_fragment: Optional[str],
    display_html_override: Optional[str],
    source_url: Optional[str],
    use_fast_translation: bool,
) -> tuple[str, Optional[str], bool]:
    """Traduit le texte ; renvoie (texte_traduit, html_affiche, surlignage_autorise)."""
    allow_highlight = True
    display_html = display_html_override

    if display_html_override is None and html_fragment and not use_fast_translation:
        # Traduit les text nodes et conserve la structure HTML
        translated_plain, translated_html = translate_html_preserve_markup(html_fragment)
        translated = trim_space_before_punct(add_sentence_space(translated_plain))
        translated_html = add_sentence_space_html(translated_html)
        translated_html = space_around_inline_code_links(translated_html)
        display_html = style_pre_blocks(translated_html)
        # Optionnel : inline des styles calcules (Chromium headless) pour un rendu fidele
        if source_url:
            try:
                res = inline_html_with_computed_styles(source_url, display_html, remove_images=True)
                if res.ok and res.html:
                    display_html = res.html
                    allow_highlight = False  # pas de surlignage dans un HTML ultra-riche
                else:
                    log.warning("inline_styles: fallback (%s)", res.error)
            except Exception:
                log.exception("inline_styles: erreur")
        write_html_debug("after_translation", translated_html)
    else:
        translated = add_sentence_space(translate_to_fr(base_text))
        if display_html_override is None:
            display_html = space_around_inline_code_links(plain_to_html(translated))

    log.debug("traduction terminee: len(base)=%d, len(traduit)=%d", len(base_text), len(translated))
    return translated, display_html, allow_highlight


def speak_with_ui(
    app: QApplication,
    text: str,
    start_index: int = 0,
    reuse_ui: bool = False,
    stop_existing: bool = True,
    adjust_layout: bool = True,  # conserve pour compatibilite avec les appelants
    translate_text: bool = True,
    display_html_override: Optional[str] = None,
    source_url: Optional[str] = None,
):
    if not text or text.strip() == "":
        return
    if text.strip().lower() == NO_SELECTION_TEXT:
        speak_short_message(NO_SELECTION_TEXT)
        show_no_selection_alert(app)
        return
    log.info("speak_with_ui: texte recu (%d chars), reuse_ui=%s", len(text), reuse_ui)

    if stop_existing:
        # Stop immediat de toute lecture en cours pour que la nouvelle prenne la main
        try:
            stop_playback(clear_clipboard=False)
        except Exception:
            log.exception("stop_playback initial impossible")

    pb = STATE.playback
    pb.playback_token += 1  # la fin de la lecture precedente ne doit pas remettre la barre a l'arret
    pb.busy = True  # la barre passe tout de suite en "pause" (traduction comprise)

    text = strip_html_comments(text)
    # Detecte si on dispose d'HTML et derive une version texte pour le TTS
    html_fragment = None
    if looks_like_html(text):
        html_fragment = strip_empty_html_tags(space_around_inline_code_links(text))
    base_text = strip_html_to_text(text) if html_fragment else text
    write_html_debug("before_translation", html_fragment or plain_to_html(base_text))

    prefs = load_prefs() or {}
    auto_detect_french = bool(prefs.get("auto_detect_french", True))
    force_translate = bool(prefs.get("force_translate", False))

    # Si le texte ressemble deja a du francais, ne le retraduis pas
    if translate_text and auto_detect_french and not force_translate and looks_like_french(base_text or ""):
        log.info("Texte detecte comme deja en francais, traduction desactivee")
        translate_text = False

    use_fast_translation = translate_text and len(base_text) > _FAST_TRANSLATION_THRESHOLD
    if use_fast_translation:
        log.info("Texte long, traduction simplifiee (sans preservation HTML)")

    # Placeholder immediat pour eviter le delai si la traduction est longue
    QTimer.singleShot(0, app, lambda: _show_placeholder(app, len(text), reuse_ui))

    def translate_and_dispatch():
        allow_highlight = True
        display_html = display_html_override
        try:
            if translate_text:
                log.debug("translate_and_dispatch: debut traduction")
                translated, display_html, allow_highlight = _translate(
                    base_text, html_fragment, display_html_override, source_url, use_fast_translation
                )
            else:
                translated = base_text
                if display_html_override is None:
                    display_html = style_pre_blocks(html_fragment) if html_fragment else plain_to_html(translated)
        except Exception:
            log.exception("Preparation du texte impossible")
            pb.busy = False
            return

        # Post sur le thread Qt (receiver = app pour garantir la queue Qt)
        QTimer.singleShot(
            0,
            app,
            lambda: _start_playback(app, translated, display_html, allow_highlight, True, start_index),
        )

    threading.Thread(target=translate_and_dispatch, daemon=True).start()
