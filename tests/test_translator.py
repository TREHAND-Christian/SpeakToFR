"""Traduction : morceaux groupes (peu de requetes), espaces conserves, repli, cache, decoupage."""
import re

import pytest

from codex_tts.services import translator as tr
from codex_tts.text import html_translate


class FakeResult:
    def __init__(self, text):
        self.text = text


class FakeGoogle:
    """Simule Google : 'fr:' devant chaque ligne ; peut perdre un numero."""

    def __init__(self, drop_marker=None):
        self.calls = []
        self.drop_marker = drop_marker

    def translate(self, text, dest="fr"):
        self.calls.append(text)
        lines = []
        for line in text.split("\n"):
            m = re.match(r"\[\[(\d+)\]\] (.*)", line)
            if m:
                n, body = m.groups()
                if self.drop_marker is not None and int(n) == self.drop_marker:
                    lines.append(f"fr:{body}")
                else:
                    lines.append(f"[[{n}]] fr:{body}")
            else:
                lines.append(f"fr:{line}")
        return FakeResult("\n".join(lines))


@pytest.fixture
def google(monkeypatch):
    fake = FakeGoogle()
    tr.clear_cache()
    monkeypatch.setattr(tr, "_translator", lambda: fake)
    yield fake
    tr.clear_cache()


def test_translate_many_one_request_keeps_order_and_spaces(google):
    texts = ["Use ", "setting 1", " to configure the ", "option", " in the panel.", "•", " 1. "]
    out = tr.translate_many(texts)
    assert len(google.calls) == 1
    assert out == ["fr:Use ", "fr:setting 1", " fr:to configure the ", "fr:option", " fr:in the panel.", "•", " 1. "]


def test_translate_many_lost_marker_falls_back_alone(monkeypatch):
    fake = FakeGoogle(drop_marker=1)
    tr.clear_cache()
    monkeypatch.setattr(tr, "_translator", lambda: fake)
    out = tr.translate_many(["one", "two", "three"])
    assert out[0] == "fr:one" and out[2] == "fr:three"
    assert out[1] == "fr:two"  # traduit seul en repli
    assert len(fake.calls) == 2
    tr.clear_cache()


def test_cache_avoids_new_requests(google):
    tr.translate_many(["Hello world", "Good morning"])
    tr.translate_to_fr("A full sentence.")
    n = len(google.calls)
    assert tr.translate_many(["Hello world", "Good morning"]) == ["fr:Hello world", "fr:Good morning"]
    assert tr.translate_to_fr("A full sentence.") == "fr:A full sentence."
    assert len(google.calls) == n


def test_many_nodes_are_grouped_in_few_requests(google):
    texts = [f"item number {i} with some words" for i in range(400)]  # ~14 000 caracteres
    out = tr.translate_many(texts)
    assert out[123] == "fr:item number 123 with some words"
    assert 2 <= len(google.calls) <= 5


def test_chunk_size_and_long_line_split():
    text = ("Une phrase assez longue pour le test. " * 300).strip()  # ~11 000 car. sur une ligne
    parts = tr._chunk(text)
    assert all(len(p) <= tr.MAX_CHUNK + 1 for p in parts)
    assert len(parts) == 3
    assert "".join(parts).replace("  ", " ").strip() == text


def test_html_translation_uses_grouped_requests(google):
    items = "".join(f"<li>Use <b>setting {i}</b> to set the <a href='#'>option {i}</a>.</li>" for i in range(15))
    plain, html_out = html_translate.translate_html_preserve_markup(f"<ul>{items}</ul><p><code>keep()</code></p>")
    assert len(google.calls) == 1  # 75 noeuds -> une seule requete
    assert "fr:setting 3" in html_out and "<b>" in html_out and "keep()" in html_out
    assert "fr:keep" not in html_out
