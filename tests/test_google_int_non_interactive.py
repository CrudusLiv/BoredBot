"""The background heartbeat must never trigger an interactive OAuth
consent flow. Each Google read path the heartbeat uses forwards an
`interactive` flag down to google_auth.get_credentials so the heartbeat
can pass interactive=False and get None (-> empty result) instead of a
blocked browser prompt when a token has gone bad."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))
sys.path.insert(0, str(ROOT / ".claude" / "scripts" / "integrations"))


@pytest.fixture
def spy_creds(monkeypatch):
    """Replace get_credentials in every integration module with a spy that
    records the `interactive` kwarg and returns None."""
    seen = {}

    def _spy(*args, account=None, interactive=True, **kw):
        seen["interactive"] = interactive
        return None

    import gcal_int  # type: ignore
    import gmail_int  # type: ignore
    import google_auth  # type: ignore

    # gcal_int / gmail_int bind get_credentials at import; gtasks_write does
    # `from google_auth import get_credentials` lazily inside _get_service,
    # so patch the origin too.
    monkeypatch.setattr(gcal_int, "get_credentials", _spy)
    monkeypatch.setattr(gmail_int, "get_credentials", _spy)
    monkeypatch.setattr(google_auth, "get_credentials", _spy)
    return seen


def test_gcal_upcoming_forwards_interactive_false(spy_creds):
    import gcal_int  # type: ignore
    assert gcal_int.upcoming(interactive=False) == []
    assert spy_creds["interactive"] is False


def test_gcal_upcoming_defaults_interactive_true(spy_creds):
    import gcal_int  # type: ignore
    gcal_int.upcoming()
    assert spy_creds["interactive"] is True


def test_gmail_list_recent_forwards_interactive_false(spy_creds):
    import gmail_int  # type: ignore
    assert gmail_int.list_recent(interactive=False) == []
    assert spy_creds["interactive"] is False


def test_gtasks_list_reminders_forwards_interactive_false(spy_creds):
    import gtasks_write  # type: ignore
    assert gtasks_write.list_reminders(interactive=False) == []
    assert spy_creds["interactive"] is False


def test_gtasks_due_reminders_forwards_interactive_false(spy_creds):
    import gtasks_write  # type: ignore
    assert gtasks_write.due_reminders(interactive=False) == []
    assert spy_creds["interactive"] is False
