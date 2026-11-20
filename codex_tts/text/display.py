"""Construction des textes affiches / lus a partir du texte traduit et de son HTML."""
from dataclasses import dataclass
from typing import Optional

from .html_text import strip_html_to_text_with_pre_ranges
from .positions import (
    Range,
    apply_inserts,
    mask_ranges_keep_newlines,
    sentence_space_inserts,
    shift_ranges,
    subtract_ranges,
)
from .sentences import split_sentences_with_positions
from .tts_prep import (
    add_sentence_space_with_ranges,
    mask_inline_dots,
    prepare_tts_sentence,
    unmask_code_punct_display,
)


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


@dataclass
class DisplayText:
    masked: str  # points internes masques (decoupage en phrases), <pre> blanchis
    unmasked: str  # version affichable
    pre_ranges: list[Range]  # plages des <pre> dans `masked`


def build_display_text(display_html: Optional[str], fr_text: str) -> DisplayText:
    """Texte brut a partir du HTML affiche (ou du texte traduit si pas de HTML)."""
    if display_html:
        plain_with_pre, pre_ranges = strip_html_to_text_with_pre_ranges(display_html)
        # Version masquee : meme longueur, mais <pre> => espaces (les \n sont conserves)
        masked = mask_ranges_keep_newlines(plain_with_pre, pre_ranges)
        # Espace apres . ! ? quand une majuscule suit directement
        inserts = sentence_space_inserts(masked)
        masked = apply_inserts(masked, inserts)
        pre_ranges = shift_ranges(pre_ranges, inserts)
    else:
        masked = fr_text or ""
        pre_ranges = []

    # Masque les points internes (domaine, email, fichiers) pour ne pas couper les phrases
    masked = mask_inline_dots(masked)
    masked, pre_ranges = add_sentence_space_with_ranges(masked, pre_ranges)
    return DisplayText(masked=masked, unmasked=unmask_code_punct_display(masked), pre_ranges=pre_ranges)


def tts_parts_for_positions(masked: str, positions: list[Range], pre_ranges: list[Range]) -> list[str]:
    """Phrases a lire : le contenu des <pre> est retire, la ponctuation de code est epelee."""
    parts = []
    for start, end in positions:
        if pre_ranges:
            segs = subtract_ranges(start, end, pre_ranges)
            piece = "".join(masked[x:y] for x, y in segs)
        else:
            piece = masked[start:end]
        parts.append(prepare_tts_sentence(piece, spell_punct_if_masked=True))
    return parts


def sentences_from_document(doc_plain: str) -> tuple[list[str], list[Range], list[str]]:
    """Phrases, positions et textes TTS calcules sur le texte reellement rendu par Qt."""
    masked_doc = mask_inline_dots(doc_plain)
    masked_sentences, positions = split_sentences_with_positions(masked_doc)
    doc_sentences = [doc_plain[s:e] for s, e in positions]
    tts_parts = [prepare_tts_sentence(s) for s in masked_sentences]
    return doc_sentences, positions, tts_parts
