"""Sentence splitting helpers shared by UI and TTS."""
import re

_SENTENCE_REGEX = re.compile(r"[^.!?\r\n]+(?:[.!?]+|(?=$|[\r\n]))")


def split_sentences(text: str) -> list[str]:
    """Decoupe le texte en phrases en conservant la ponctuation finale."""
    sents, _ = split_sentences_with_positions(text)
    return sents if sents else [text.strip()]


def split_sentences_with_positions(text: str) -> tuple[list[str], list[tuple[int, int]]]:
    """Retourne les phrases et leurs positions (start, end) dans le texte source."""
    # Normalise les fins de ligne pour aligner les positions avec QTextEdit
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    sentences: list[str] = []
    positions: list[tuple[int, int]] = []

    for match in _SENTENCE_REGEX.finditer(normalized):
        raw = match.group()
        start, end = match.span()
        stripped = raw.strip()
        if not stripped:
            continue

        lead = len(raw) - len(raw.lstrip())
        trail = len(raw) - len(raw.rstrip())
        adj_start = start + lead
        adj_end = end - trail

        sentences.append(stripped)
        positions.append((adj_start, adj_end))

    if not sentences:
        cleaned = normalized.strip()
        if cleaned:
            sentences.append(cleaned)
            positions.append((0, len(cleaned)))

    return sentences, positions
