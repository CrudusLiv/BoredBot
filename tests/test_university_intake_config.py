"""University-intake config defaults land in voice.config.load()."""
from __future__ import annotations

from voice import config as cfg


def test_intake_defaults_present(monkeypatch, tmp_path):
    # Isolate from any installed %APPDATA%\Vesper\config.json.
    monkeypatch.setattr(cfg, "_DEV_CONFIG", tmp_path / "nope.json")
    monkeypatch.setattr(cfg, "_installed_config", lambda: tmp_path / "nope2.json")
    conf = cfg.load()
    assert conf["university_intake_enabled"] is False
    assert conf["university_intake_root"] == "D:/University"
    assert conf["university_intake_mode"] == "per-file"
    assert conf["university_intake_denylist"] == ["Visual Studio", "intern", "Uni General"]
    assert conf["university_intake_extensions"] == [".pdf", ".docx", ".pptx"]
    assert ".doc" not in conf["university_intake_extensions"]
    assert ".ppt" not in conf["university_intake_extensions"]
    assert ".txt" not in conf["university_intake_extensions"]
    assert ".md" not in conf["university_intake_extensions"]
    assert ".zip" not in conf["university_intake_extensions"]
    assert conf["university_intake_max_chars"] == 20000
    assert conf["university_intake_deadline_detection"] is True
    assert conf["university_intake_max_files_per_tick"] == 200
