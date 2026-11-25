"""ResponseTracker : lire les nouvelles reponses, charger (sans lire) celle d'une conversation ouverte."""
import pytest

pytest.importorskip("PySide6")

from codex_tts.services.claude_desktop import ResponseTracker  # noqa: E402


def msg(n, total, text="Bonjour.", claude=True, complete=True):
    return {"name": f"Message {n} sur {total}", "total": total, "claude": claude, "complete": complete, "text": text}


STREAM = {"name": "Message en cours de génération", "total": None, "claude": False, "complete": False, "text": ""}


def test_startup_loads_last_response():
    t = ResponseTracker()
    assert t.feed(msg(12, 12, "Ancienne reponse."), "Conv A - Claude") == ("load", "Ancienne reponse.")
    assert t.feed(msg(12, 12, "Ancienne reponse."), "Conv A - Claude") == (None, "")  # deja chargee


def test_new_response_after_streaming_is_read():
    t = ResponseTracker()
    t.feed(msg(12, 12, "Ancienne."), "A - Claude")
    assert t.feed(msg(13, 13, "Ma question", claude=False), "A - Claude") == (None, "")
    assert t.feed(STREAM, "A - Claude") == (None, "")
    assert t.feed(msg(14, 14, "Nouvelle.", complete=False), "A - Claude") == (None, "")
    assert t.feed(msg(14, 14, "Nouvelle reponse."), "A - Claude") == ("read", "Nouvelle reponse.")


def test_switching_conversation_loads_without_reading():
    t = ResponseTracker()
    t.feed(msg(10, 10, "Reponse A."), "A - Claude")
    # Conversation B avec 2 messages de plus : ne doit pas etre prise pour une nouvelle reponse
    assert t.feed(msg(12, 12, "Reponse B."), "B - Claude") == ("load", "Reponse B.")
    assert t.feed(msg(10, 10, "Reponse A."), "A - Claude") == ("load", "Reponse A.")


def test_new_chat_title_change_still_reads_first_response():
    t = ResponseTracker()
    t.feed(msg(1, 1, "Salut", claude=False), "Claude")
    t.feed(STREAM, "Claude")
    # Le titre du chat est genere pendant/apres la 1re reponse
    assert t.feed(msg(2, 2, "Premiere reponse."), "Mon sujet - Claude") == ("read", "Premiere reponse.")


def test_switch_while_streaming_elsewhere_does_not_read():
    t = ResponseTracker()
    t.feed(msg(8, 8, "Reponse A."), "A - Claude")
    t.feed(STREAM, "A - Claude")
    assert t.feed(msg(20, 20, "Reponse B."), "B - Claude") == ("load", "Reponse B.")
