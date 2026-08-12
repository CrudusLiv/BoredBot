"""voice/tools/icons.py::extract_icon_png, _render_icon_png -- GDI icon
extraction. All win32gui/win32ui calls are mocked; no real exe is ever
loaded and no real window/DC is created."""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

from PIL import Image

from voice.tools import icons


def test_extract_icon_png_returns_none_when_no_icon_resource(monkeypatch):
    mock_render = MagicMock()
    monkeypatch.setattr(icons, "_render_icon_png", mock_render)
    with patch("win32gui.ExtractIconEx", return_value=([], [])), \
         patch("win32gui.DestroyIcon") as mock_destroy:
        result = icons.extract_icon_png("C:\\fake.exe")
    assert result is None
    mock_render.assert_not_called()
    mock_destroy.assert_not_called()


def test_extract_icon_png_uses_first_large_handle(monkeypatch):
    captured = {}

    def fake_render(hicon, size=32):
        captured["hicon"] = hicon
        return b"PNGBYTES"

    monkeypatch.setattr(icons, "_render_icon_png", fake_render)
    with patch("win32gui.ExtractIconEx", return_value=([111], [222])), \
         patch("win32gui.DestroyIcon"):
        result = icons.extract_icon_png("C:\\fake.exe")
    assert result == b"PNGBYTES"
    assert captured["hicon"] == 111


def test_extract_icon_png_destroys_all_extracted_handles(monkeypatch):
    monkeypatch.setattr(icons, "_render_icon_png", lambda h, size=32: b"PNGBYTES")
    with patch("win32gui.ExtractIconEx", return_value=([111], [222])), \
         patch("win32gui.DestroyIcon") as mock_destroy:
        icons.extract_icon_png("C:\\fake.exe")
    assert mock_destroy.call_count == 2
    mock_destroy.assert_any_call(111)
    mock_destroy.assert_any_call(222)


def test_extract_icon_png_returns_none_on_render_failure(monkeypatch):
    def fake_render(hicon, size=32):
        raise RuntimeError("GDI failure")

    monkeypatch.setattr(icons, "_render_icon_png", fake_render)
    with patch("win32gui.ExtractIconEx", return_value=([111], [])), \
         patch("win32gui.DestroyIcon") as mock_destroy:
        result = icons.extract_icon_png("C:\\fake.exe")
    assert result is None
    mock_destroy.assert_called_once_with(111)  # cleanup still happens


def test_render_icon_png_produces_valid_png_from_fake_bitmap():
    fake_bits = bytes(4 * 4 * 4)  # 4x4 BGRA, all zero
    mock_hbmp = MagicMock()
    mock_hbmp.GetInfo.return_value = {"bmWidth": 4, "bmHeight": 4}
    mock_hbmp.GetBitmapBits.return_value = fake_bits
    mock_hbmp.GetHandle.return_value = 999
    mock_hdc_mem = MagicMock()
    mock_hdc_mem.GetHandleOutput.return_value = 1
    mock_hdc = MagicMock()
    mock_hdc.CreateCompatibleDC.return_value = mock_hdc_mem

    with patch("win32gui.GetDC", return_value=0), \
         patch("win32ui.CreateDCFromHandle", return_value=mock_hdc), \
         patch("win32ui.CreateBitmap", return_value=mock_hbmp), \
         patch("win32gui.DrawIconEx") as mock_draw, \
         patch("win32gui.DeleteObject") as mock_delete_obj:
        result = icons._render_icon_png(hicon=42, size=4)

    mock_draw.assert_called_once()
    mock_delete_obj.assert_called_once_with(999)
    assert result[:8] == b"\x89PNG\r\n\x1a\n"
    img = Image.open(io.BytesIO(result))
    assert img.size == (4, 4)
