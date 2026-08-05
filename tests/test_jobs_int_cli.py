"""query.py jobs scan -- new CLI subcommand over voice.jobs.scan_alerts()."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "scripts"))
from integrations import jobs_int  # noqa: E402
from voice import jobs as voice_jobs  # noqa: E402


def test_scan_prints_added_count(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(voice_jobs, "scan_alerts", lambda data_dir, conf: 2)
    monkeypatch.setattr(jobs_int.voice_config, "load", lambda: {"job_alerts_enabled": True})
    monkeypatch.setattr(jobs_int.voice_config, "get_data_dir", lambda: tmp_path)

    rc = jobs_int.handle_query(["scan", "--json"])

    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"added": 2}


def test_scan_passes_data_dir_and_config_through(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(voice_jobs, "scan_alerts", lambda data_dir, conf: captured.update(data_dir=data_dir, conf=conf) or 0)
    monkeypatch.setattr(jobs_int.voice_config, "load", lambda: {"job_alert_senders": ["x.com"]})
    monkeypatch.setattr(jobs_int.voice_config, "get_data_dir", lambda: tmp_path)

    jobs_int.handle_query(["scan", "--json"])

    assert captured["data_dir"] == tmp_path
    assert captured["conf"] == {"job_alert_senders": ["x.com"]}
