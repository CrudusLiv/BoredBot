from voice.config import DEFAULTS


def test_wakeword_engine_defaults_to_openwakeword():
    assert DEFAULTS["wakeword_engine"] == "openwakeword"
