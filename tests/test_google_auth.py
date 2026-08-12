"""google_auth.py -- SCOPES includes Tasks, and a cached token that predates
a scope in SCOPES is discarded rather than silently reused (which would
otherwise surface as an opaque 403 from the API, not from auth).

These tests exercise the REAL google.oauth2.credentials.Credentials class
against a synthetic token file on disk -- not a mock of that class. An
earlier version of this test mocked Credentials.from_authorized_user_file
directly, which hid a real bug: passing scopes=SCOPES to that classmethod
makes it echo SCOPES back as creds.scopes instead of reading the file's
actual granted scopes (see google.oauth2.credentials.Credentials.
from_authorized_user_info: `if scopes is None and "scopes" in info: ...`),
so the mismatch check was always trivially true. Only Credentials.refresh
and the InstalledAppFlow consent flow are mocked here -- the parts that
would hit the network."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock


def _import_module():
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / ".claude" / "scripts"))
    sys.path.insert(0, str(repo_root / ".claude" / "scripts" / "integrations"))
    import google_auth  # type: ignore
    return google_auth


def _write_token(path, scopes):
    path.write_text(json.dumps({
        "refresh_token": "test-refresh-token",
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
        "scopes": scopes,
    }), encoding="utf-8")


def test_tasks_scope_is_requested():
    m = _import_module()
    assert "https://www.googleapis.com/auth/tasks" in m.SCOPES


def test_stale_token_missing_new_scope_triggers_fresh_consent(monkeypatch, tmp_path):
    m = _import_module()
    token_path = tmp_path / "google_token.json"
    _write_token(token_path, [
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/gmail.readonly",
    ])  # missing tasks
    monkeypatch.setattr(m, "TOKEN_PATH", token_path)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csecret")

    def _refresh_should_not_be_called(self, request):
        raise AssertionError("refresh() must not be called on a scope-mismatched token")

    monkeypatch.setattr(
        "google.oauth2.credentials.Credentials.refresh",
        _refresh_should_not_be_called,
    )

    fresh_creds = MagicMock()
    fresh_creds.to_json.return_value = "{}"
    flow = MagicMock()
    flow.run_local_server.return_value = fresh_creds
    monkeypatch.setattr(
        "google_auth_oauthlib.flow.InstalledAppFlow.from_client_config",
        classmethod(lambda cls, config, scopes: flow),
    )

    result = m.get_credentials()
    assert result is fresh_creds
    flow.run_local_server.assert_called_once()


def test_token_covering_all_scopes_is_reused(monkeypatch, tmp_path):
    m = _import_module()
    token_path = tmp_path / "google_token.json"
    _write_token(token_path, list(m.SCOPES))
    monkeypatch.setattr(m, "TOKEN_PATH", token_path)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csecret")

    def _fake_refresh(self, request):
        # Simulate a successful token refresh in place, matching the real
        # Credentials.refresh(request) signature (mutates self, no return).
        self.token = "refreshed-access-token"

    monkeypatch.setattr(
        "google.oauth2.credentials.Credentials.refresh",
        _fake_refresh,
    )
    flow_from_config = MagicMock()
    monkeypatch.setattr(
        "google_auth_oauthlib.flow.InstalledAppFlow.from_client_config",
        flow_from_config,
    )

    result = m.get_credentials()
    assert result.token == "refreshed-access-token"
    flow_from_config.assert_not_called()
