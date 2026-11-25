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



def stream(paragraphs, done):
    return {"name": "Message en cours de génération", "total": None, "claude": False, "complete": False,
            "text": "\n\n".join(paragraphs), "paragraphs": paragraphs, "done_count": done}


def final(n, paragraphs):
    return {"name": f"Message {n} sur {n}", "total": n, "claude": True, "complete": True,
            "text": "\n\n".join(paragraphs), "paragraphs": paragraphs, "done_count": len(paragraphs)}


def test_intermediate_texts_are_sent_once_then_only_the_rest():
    t = ResponseTracker()
    t.feed(final(10, ["Ancienne."]), "A - Claude")
    # Texte intermediaire en cours d'ecriture : pas encore termine
    assert t.feed(stream(["Je regarde le code"], 0), "A - Claude") == (None, "")
    # Un outil demarre apres : le texte est termine, mais il vient de changer -> on attend
    assert t.feed(stream(["Je regarde le code."], 1), "A - Claude") == (None, "")
    # Identique au passage suivant -> envoye une seule fois
    assert t.feed(stream(["Je regarde le code."], 1), "A - Claude") == ("partial", "Je regarde le code.")
    assert t.feed(stream(["Je regarde le code."], 1), "A - Claude") == (None, "")  # pas de repetition
    # Reponse finale qui s'ecrit : chaque paragraphe suivi d'un autre et stable est envoye
    assert t.feed(stream(["Je regarde le code.", "C'est fait.", "Dis-moi"], 2), "A - Claude") == (None, "")
    assert t.feed(stream(["Je regarde le code.", "C'est fait.", "Dis-moi si"], 2), "A - Claude") == (
        "partial", "C'est fait.")
    action, text = t.feed(final(12, ["Je regarde le code.", "C'est fait.", "Dis-moi si ça va."]), "A - Claude")
    assert action == "read" and text.startswith("Je regarde")
    assert t.remaining == "Dis-moi si ça va."  # seule la fin reste a lire


def test_response_without_intermediate_is_read_whole():
    t = ResponseTracker()
    t.feed(final(4, ["Ancienne."]), "A - Claude")
    t.feed(stream(["Une seule"], 0), "A - Claude")
    action, text = t.feed(final(6, ["Une seule réponse."]), "A - Claude")
    assert action == "read" and t.remaining == "Une seule réponse."



def test_step_lines_are_read_but_not_tool_lines():
    t = ResponseTracker()
    t.feed(final(2, ["Ancienne."]), "A - Claude")
    s = stream(["Je regarde."], 1)
    s["status"] = ["Designing a reading queue", "Utilisant Windows-MCP en cours d'exécution"]
    assert t.feed(s, "A - Claude") == (None, "")  # pas encore stable
    assert t.feed(dict(s), "A - Claude") == ("partial", "Designing a reading queue.\n\nJe regarde.")
    s2 = stream(["Je regarde."], 1)
    s2["status"] = ["Designing a reading queue", "Utilisant Windows-MCP"]
    assert t.feed(s2, "A - Claude") == (None, "")  # deja lu / ligne d'outil


def test_final_without_intermediate_texts_is_read_whole():
    """Les textes intermediaires sont replies dans la reponse finale : toute la reponse finale est lue."""
    t = ResponseTracker()
    t.feed(final(2, ["Ancienne."]), "A - Claude")
    t.feed(stream(["Intro de travail."], 1), "A - Claude")
    t.feed(final(4, ["Resultat un.", "Resultat deux."]), "A - Claude")
    assert t.remaining == "Resultat un.\n\nResultat deux."



def test_running_state_is_not_read():
    from codex_tts.services.claude_desktop import clean_status

    assert clean_status("Vérification du filtrage en cours d'exécution") == "Vérification du filtrage"
    assert clean_status("Vérification du filtrage en cours d’exécution") == "Vérification du filtrage"
    assert clean_status("Checking the logs running") == "Checking the logs"
    assert clean_status("Vérification du filtrage") == "Vérification du filtrage"


def test_visible_label_skips_hidden_text():
    from codex_tts.services.claude_desktop import _visible_label

    class C:
        def __init__(self, kind, name="", cls="", children=()):
            self.ControlTypeName, self.Name, self.ClassName, self.children = kind, name, cls, list(children)

        def GetChildren(self):
            return self.children

    button = C("ButtonControl", "Vérification du filtrage en cours d'exécution", children=[
        C("GroupControl", cls="group/morph", children=[C("TextControl", "Vérification du filtrage")]),
        C("GroupControl", cls="sr-only", children=[C("TextControl", "en cours d'exécution")]),
    ])
    assert _visible_label(button) == "Vérification du filtrage"



def test_text_still_appearing_is_not_cut():
    """Le texte s'affiche progressivement : on n'envoie pas un debut de phrase."""
    t = ResponseTracker()
    t.feed(final(2, ["Ancienne."]), "A - Claude")
    assert t.feed(stream(["Test de le"], 1), "A - Claude") == (None, "")
    assert t.feed(stream(["Test de lecture : ce premier texte."], 1), "A - Claude") == (None, "")
    assert t.feed(stream(["Test de lecture : ce premier texte."], 1), "A - Claude") == (
        "partial", "Test de lecture : ce premier texte.")


def test_animated_step_label_read_once_settled():
    t = ResponseTracker()
    t.feed(final(2, ["Ancienne."]), "A - Claude")
    for label in ("Plan", "Planning to", "Planning tool calls"):
        s = stream([], 0)
        s["status"] = [label]
        assert t.feed(s, "A - Claude") == (None, "")
    s = stream([], 0)
    s["status"] = ["Planning tool calls"]
    assert t.feed(s, "A - Claude") == ("partial", "Planning tool calls.")



def test_transitional_state_at_the_end_does_not_cancel_reading():
    """Fin de generation : 'Message 46 sur 46' apparait un instant sans 'Claude a repondu'."""
    t = ResponseTracker()
    t.feed(final(44, ["Ancienne."]), "A - Claude")
    t.feed(msg(45, 45, "Ma question", claude=False), "A - Claude")
    t.feed(stream(["Intro."], 1), "A - Claude")
    t.feed(stream(["Intro."], 1), "A - Claude")
    assert t.feed(msg(46, 46, "", claude=False, complete=False), "A - Claude") == (None, "")
    action, text = t.feed(final(46, ["Fin de la réponse."]), "A - Claude")
    assert action == "read" and t.remaining == "Fin de la réponse."
