"""vault_fs.list_inbox_new — now also picks up screenshot images."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "scripts"))
from integrations import vault_fs  # noqa: E402


def test_supported_suffixes_include_screenshot_formats():
    assert {".png", ".jpg", ".jpeg"} <= vault_fs.SUPPORTED_SUFFIXES


def test_supported_suffixes_still_include_lecture_formats():
    assert {".pptx", ".pdf", ".ppt"} <= vault_fs.SUPPORTED_SUFFIXES
