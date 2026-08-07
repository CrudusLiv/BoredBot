"""voice/test_runner.py — parses pytest's summary line."""
from __future__ import annotations

from unittest.mock import MagicMock

from voice.test_runner import _parse_summary, run_test_suite


def test_parse_summary_all_passed():
    assert _parse_summary("== 42 passed in 3.21s ==") == {"passed": 42, "failed": 0}


def test_parse_summary_with_failures():
    assert _parse_summary("== 2 failed, 40 passed in 3.21s ==") == {"passed": 40, "failed": 2}


def test_parse_summary_no_tests_collected():
    assert _parse_summary("== no tests ran in 0.01s ==") == {"passed": 0, "failed": 0}


def test_run_test_suite_ok_when_all_pass(monkeypatch, tmp_path):
    fake = MagicMock(returncode=0, stdout="== 5 passed in 1.0s ==\n", stderr="")
    monkeypatch.setattr("voice.test_runner.subprocess.run", lambda *a, **k: fake)
    result = run_test_suite(tmp_path)
    assert result == {"passed": 5, "failed": 0, "ok": True}


def test_run_test_suite_not_ok_when_failures(monkeypatch, tmp_path):
    fake = MagicMock(returncode=1, stdout="== 1 failed, 4 passed in 1.0s ==\n", stderr="")
    monkeypatch.setattr("voice.test_runner.subprocess.run", lambda *a, **k: fake)
    result = run_test_suite(tmp_path)
    assert result == {"passed": 4, "failed": 1, "ok": False}


def test_run_test_suite_handles_subprocess_error(monkeypatch, tmp_path):
    def _boom(*a, **k):
        raise OSError("py not found")
    monkeypatch.setattr("voice.test_runner.subprocess.run", _boom)
    result = run_test_suite(tmp_path)
    assert result["ok"] is False
