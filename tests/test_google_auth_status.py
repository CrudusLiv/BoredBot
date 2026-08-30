"""google_auth.py -- non-interactive status inspection + forced re-auth,
used by the heartbeat's expiry notice and the orb Calendar tab's reconnect
card. Like tests/test_google_auth.py, these run the REAL
google.oauth2.credentials.Credentials against synthetic token files on
disk; only Credentials.refresh and the InstalledAppFlow consent flow --
the parts that hit the network -- are mocked."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _import_module():
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / ".claude" / "scripts"))
    sys.path.insert(0, str(repo_root / ".claude" / "scripts" / "integrations"))
    import google_auth  # type: ignore
    return google_auth


def _write_token(path: Path, *, scopes=None, token="access-token", expiry: str | None = None):
    m = _import_module()
    path.write_text(json.dumps({
        "token": token,
        "refresh_token": "test-refresh-token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
        "scopes": scopes if scopes is not None else list(m.SCOPES),
        "expiry": expiry or (datetime.now(timezone.utc) + timedelta(hours=1))
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
    }), encoding="utf-8")


_PAST = "2020-01-01T00:00:00Z"


@pytest.fixture
def token_dir(tmp_path, monkeypatch):
    """Redirect TOKEN_PATH (and thus every _token_path(label)) at a tmp dir."""
    m = _import_module()
    monkeypatch.setattr(m, "TOKEN_PATH", tmp_path / "google_token.json")
    return tmp_path


# ── list_accounts ──────────────────────────────────────────────────────────

def test_list_accounts_primary_only_when_no_label_files(token_dir):
    m = _import_module()
    _write_token(token_dir / "google_token.json")
    assert m.list_accounts() == [None]


def test_list_accounts_includes_each_labelled_token_file(token_dir):
    m = _import_module()
    _write_token(token_dir / "google_token.json")
    _write_token(token_dir / "google_token_jobs.json")
    assert m.list_accounts() == [None, "jobs"]


def test_list_accounts_primary_present_even_with_no_files(token_dir):
    m = _import_module()
    assert m.list_accounts() == [None]


# ── account_status ─────────────────────────────────────────────────────────

def test_account_status_missing_token_reports_never_connected(token_dir):
    m = _import_module()
    st = m.account_status()
    assert st["account"] == "primary"
    assert st["connected"] is False
    assert st["needs_reconnect"] is True
    assert st["detail"] == "never connected"


def test_account_status_valid_token_is_connected_without_refresh(token_dir, monkeypatch):
    m = _import_module()
    _write_token(token_dir / "google_token.json")  # expiry 1h out -> valid

    def _no_refresh(self, request):
        raise AssertionError("refresh() must not run for a still-valid token")

    monkeypatch.setattr("google.oauth2.credentials.Credentials.refresh", _no_refresh)
    st = m.account_status()
    assert st["connected"] is True
    assert st["needs_reconnect"] is False


def test_account_status_expired_but_refreshable_reconnects_and_saves(token_dir, monkeypatch):
    m = _import_module()
    tok = token_dir / "google_token.json"
    _write_token(tok, expiry=_PAST)

    def _ok_refresh(self, request):
        self.token = "fresh-access-token"
        self.expiry = datetime(2099, 1, 1)

    monkeypatch.setattr("google.oauth2.credentials.Credentials.refresh", _ok_refresh)
    st = m.account_status()
    assert st["connected"] is True
    assert st["needs_reconnect"] is False
    assert "fresh-access-token" in tok.read_text(encoding="utf-8")


def test_account_status_dead_refresh_token_needs_reconnect(token_dir, monkeypatch):
    m = _import_module()
    _write_token(token_dir / "google_token.json", expiry=_PAST)
    from google.auth.exceptions import RefreshError

    def _dead_refresh(self, request):
        raise RefreshError("Token has been expired or revoked.")

    monkeypatch.setattr("google.oauth2.credentials.Credentials.refresh", _dead_refresh)
    st = m.account_status()
    assert st["connected"] is False
    assert st["needs_reconnect"] is True
    assert st["detail"] == "sign-in expired"


def test_account_status_never_opens_a_browser(token_dir, monkeypatch):
    m = _import_module()
    _write_token(token_dir / "google_token.json", expiry=_PAST)
    from google.auth.exceptions import RefreshError

    monkeypatch.setattr(
        "google.oauth2.credentials.Credentials.refresh",
        lambda self, request: (_ for _ in ()).throw(RefreshError("revoked")),
    )
    boom = MagicMock(side_effect=AssertionError("consent flow must not run"))
    monkeypatch.setattr(
        "google_auth_oauthlib.flow.InstalledAppFlow.from_client_config", boom
    )
    m.account_status()          # expired + dead refresh
    m.account_status("absent")  # no token file at all


def test_account_status_reads_the_labelled_token_file(token_dir, monkeypatch):
    m = _import_module()
    _write_token(token_dir / "google_token_jobs.json")

    monkeypatch.setattr(
        "google.oauth2.credentials.Credentials.refresh",
        lambda self, request: None,
    )
    st = m.account_status("jobs")
    assert st["account"] == "jobs"
    assert st["connected"] is True


# ── get_credentials(interactive=False) ─────────────────────────────────────

def test_get_credentials_non_interactive_returns_none_instead_of_browser(token_dir, monkeypatch):
    m = _import_module()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(
        "google_auth_oauthlib.flow.InstalledAppFlow.from_client_config",
        MagicMock(side_effect=AssertionError("must not open a browser")),
    )
    assert m.get_credentials(interactive=False) is None


# ── reauth ────────────────────────────────────────────────────────────────

def test_reauth_runs_consent_flow_and_writes_token(token_dir, monkeypatch):
    m = _import_module()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csecret")
    fresh = MagicMock()
    fresh.to_json.return_value = '{"refresh_token": "brand-new"}'
    flow = MagicMock()
    flow.run_local_server.return_value = fresh
    monkeypatch.setattr(
        "google_auth_oauthlib.flow.InstalledAppFlow.from_client_config",
        classmethod(lambda cls, config, scopes: flow),
    )
    result = m.reauth()
    assert result["ok"] is True
    assert result["account"] == "primary"
    flow.run_local_server.assert_called_once()
    assert "brand-new" in (token_dir / "google_token.json").read_text(encoding="utf-8")


def test_reauth_labelled_account_writes_its_own_file(token_dir, monkeypatch):
    m = _import_module()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csecret")
    fresh = MagicMock()
    fresh.to_json.return_value = '{"refresh_token": "jobs-new"}'
    flow = MagicMock()
    flow.run_local_server.return_value = fresh
    monkeypatch.setattr(
        "google_auth_oauthlib.flow.InstalledAppFlow.from_client_config",
        classmethod(lambda cls, config, scopes: flow),
    )
    result = m.reauth("jobs")
    assert result["ok"] is True
    assert (token_dir / "google_token_jobs.json").exists()
    assert not (token_dir / "google_token.json").exists()


def test_reauth_without_client_env_returns_error(token_dir, monkeypatch):
    m = _import_module()
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(
        "google_auth_oauthlib.flow.InstalledAppFlow.from_client_config",
        MagicMock(side_effect=AssertionError("no env -> no flow")),
    )
    result = m.reauth()
    assert result["ok"] is False
    assert result["error"]
