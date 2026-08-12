"""Tests for voice/ui_window.py's testable surface -- the show()/is_available()
state and the closing-handler/init-failure/success branches of start(), all
exercised via monkeypatched _create_window() so no real WebView2 runtime is
needed. Actual webview.start()/window creation is excluded from CI, same
posture as voice/screen_overlay.py's real Tk window."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from voice import ui_window


@pytest.fixture(autouse=True)
def _reset_module_state():
    ui_window._window = None
    ui_window._available = False
    yield
    ui_window._window = None
    ui_window._available = False


def test_is_available_false_initially():
    assert ui_window.is_available() is False


def test_show_noop_when_no_window():
    ui_window.show()  # must not raise


def test_show_calls_window_show():
    calls = []
    ui_window._window = SimpleNamespace(show=lambda: calls.append(True))
    ui_window.show()
    assert calls == [True]


def test_on_closing_hides_and_cancels_close():
    calls = []
    fake_window = SimpleNamespace(hide=lambda: calls.append(True))
    result = ui_window._on_closing(fake_window)
    assert calls == [True]
    assert result is False


def test_start_marks_unavailable_on_create_failure(monkeypatch):
    def _raise(port, token):
        raise RuntimeError("no WebView2 runtime")

    monkeypatch.setattr(ui_window, "_create_window", _raise)
    ui_window.start(7070, "tok")
    assert ui_window.is_available() is False
    assert ui_window._window is None


def test_start_marks_available_and_starts_webview_on_success(monkeypatch):
    # window.show() must NOT be called here -- pywebview's real Window API
    # blocks on a readiness event that's only set once webview.start() has
    # initialized the GUI loop; calling show() before start() times out
    # with WebViewException('Main window failed to start') (see start()'s
    # docstring). The window is shown automatically by start() instead,
    # since _create_window() no longer passes hidden=True.
    start_calls = []
    fake_window = SimpleNamespace()
    fake_webview = SimpleNamespace(start=lambda: start_calls.append(True))

    monkeypatch.setattr(
        ui_window, "_create_window", lambda port, token: (fake_window, fake_webview)
    )
    ui_window.start(7070, "tok")
    assert ui_window.is_available() is True
    assert ui_window._window is fake_window
    assert start_calls == [True]
