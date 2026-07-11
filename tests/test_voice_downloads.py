from voice import config as cfg


def test_config_has_downloads_defaults():
    conf = cfg.load()
    assert conf["downloads_triage_enabled"] is False
    assert conf["downloads_watch_folders"] == []
    assert ".pdf" in conf["downloads_watch_exts"]
    assert ".pptx" in conf["downloads_watch_exts"]
