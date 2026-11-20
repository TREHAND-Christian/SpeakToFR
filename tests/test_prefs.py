import json

from codex_tts.core import prefs


def test_save_and_load_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(prefs, "_legacy_candidates", lambda: [])
    assert prefs.load_prefs() is None
    prefs.save_prefs({"speed": 1.5, "voice": "X"})
    prefs.save_prefs({"mode": "mini", "w": 10, "h": 20})
    data = prefs.load_prefs()
    assert data == {"speed": 1.5, "voice": "X", "mode": "mini"}  # w/h jamais persistes
    assert prefs.prefs_path().parent == tmp_path / "SpeakToFR"


def test_legacy_file_is_migrated_once(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    legacy = tmp_path / "window_prefs.json"
    legacy.write_text(json.dumps({"voice": "Microsoft Paul", "speed": 1.2}), encoding="utf-8")
    monkeypatch.setattr(prefs, "_legacy_candidates", lambda: [legacy])
    assert prefs.load_prefs() == {"voice": "Microsoft Paul", "speed": 1.2}
    legacy.write_text(json.dumps({"voice": "autre"}), encoding="utf-8")
    assert prefs.load_prefs()["voice"] == "Microsoft Paul"  # pas de nouvelle migration


def test_corrupted_file_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(prefs, "_legacy_candidates", lambda: [])
    prefs.prefs_path().write_text("{pas du json", encoding="utf-8")
    assert prefs.load_prefs() is None
    prefs.save_prefs({"a": 1})  # se remet d'un fichier corrompu
    assert prefs.load_prefs() == {"a": 1}
