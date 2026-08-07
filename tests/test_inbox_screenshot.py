"""core.inbox._process_screenshot — OCR a dropped image into a vault note."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "scripts"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    from core import inbox
    monkeypatch.setattr(inbox, "VAULT", tmp_path)
    monkeypatch.setattr(inbox, "SCREENSHOTS", tmp_path / "screenshots")
    (tmp_path / "inbox").mkdir()
    return inbox


def test_process_screenshot_writes_note_with_ocr_text(env, tmp_path, monkeypatch):
    src = tmp_path / "inbox" / "shot.png"
    src.write_bytes(b"fake-png-bytes")

    monkeypatch.setattr(env, "run_ocr_on_image", lambda image: ("Assignment due Friday", 0.92, None))
    monkeypatch.setattr(env, "_open_image", lambda p: object())

    summary = env._process_screenshot(src)

    assert summary["type"] == "screenshot"
    assert summary["roadmap_notice"] is None
    note_path = summary["path"]
    assert note_path.exists()
    assert "Assignment due Friday" in note_path.read_text(encoding="utf-8")


def test_process_screenshot_moves_source_to_processed(env, tmp_path, monkeypatch):
    src = tmp_path / "inbox" / "shot.png"
    src.write_bytes(b"fake-png-bytes")
    monkeypatch.setattr(env, "run_ocr_on_image", lambda image: ("text", 0.9, None))
    monkeypatch.setattr(env, "_open_image", lambda p: object())

    env._process_screenshot(src)

    assert not src.exists()
    assert (tmp_path / "inbox" / "_processed" / "shot.png").exists()


def test_process_screenshot_returns_none_on_ocr_error(env, tmp_path, monkeypatch):
    src = tmp_path / "inbox" / "shot.png"
    src.write_bytes(b"fake-png-bytes")
    monkeypatch.setattr(env, "run_ocr_on_image", lambda image: ("", 0.0, "decode error"))
    monkeypatch.setattr(env, "_open_image", lambda p: object())

    assert env._process_screenshot(src) is None
    assert src.exists()  # left in place for retry / manual inspection
