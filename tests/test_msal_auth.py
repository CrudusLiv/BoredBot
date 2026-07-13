"""Tests for msal_auth — MSAL calls are mocked, no real device-code flow or network."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))
sys.path.insert(0, str(ROOT / ".claude" / "scripts" / "integrations"))

import integrations._env  # noqa: F401


def test_get_token_returns_none_without_client_id(monkeypatch):
    import importlib
    import integrations.msal_auth as ma
    importlib.reload(ma)
    monkeypatch.delenv("OUTLOOK_CLIENT_ID", raising=False)
    assert ma.get_token() is None


def test_get_token_uses_common_authority_when_no_tenant(monkeypatch):
    import importlib
    import integrations.msal_auth as ma
    importlib.reload(ma)
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "fake-client-id")
    monkeypatch.delenv("OUTLOOK_TENANT_ID", raising=False)

    mock_app = MagicMock()
    mock_app.get_accounts.return_value = []
    mock_app.initiate_device_flow.return_value = {
        "message": "Go to https://microsoft.com/devicelogin and enter CODE123",
        "device_code": "dc1",
    }
    mock_app.acquire_token_by_device_flow.return_value = {"access_token": "tok123"}

    with patch.object(ma.msal, "PublicClientApplication", return_value=mock_app) as ctor:
        token = ma.get_token(scopes=["Mail.Read"])

    assert token == "tok123"
    called_authority = ctor.call_args.kwargs["authority"]
    assert called_authority == "https://login.microsoftonline.com/common"


def test_get_token_uses_tenant_authority_when_set(monkeypatch):
    import importlib
    import integrations.msal_auth as ma
    importlib.reload(ma)
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("OUTLOOK_TENANT_ID", "tenant-abc")

    mock_app = MagicMock()
    mock_app.get_accounts.return_value = []
    mock_app.initiate_device_flow.return_value = {"message": "...", "device_code": "dc1"}
    mock_app.acquire_token_by_device_flow.return_value = {"access_token": "tok456"}

    with patch.object(ma.msal, "PublicClientApplication", return_value=mock_app) as ctor:
        token = ma.get_token(scopes=["Mail.Read"])

    assert token == "tok456"
    assert ctor.call_args.kwargs["authority"] == "https://login.microsoftonline.com/tenant-abc"


def test_get_token_silent_path_used_when_account_cached(monkeypatch):
    import importlib
    import integrations.msal_auth as ma
    importlib.reload(ma)
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "fake-client-id")

    mock_app = MagicMock()
    mock_app.get_accounts.return_value = [{"username": "b2300682@helplive.edu.my"}]
    mock_app.acquire_token_silent.return_value = {"access_token": "silent-tok"}

    with patch.object(ma.msal, "PublicClientApplication", return_value=mock_app):
        token = ma.get_token(scopes=["Mail.Read"])

    assert token == "silent-tok"
    mock_app.initiate_device_flow.assert_not_called()


def test_get_token_returns_none_on_device_flow_failure(monkeypatch):
    import importlib
    import integrations.msal_auth as ma
    importlib.reload(ma)
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "fake-client-id")

    mock_app = MagicMock()
    mock_app.get_accounts.return_value = []
    mock_app.initiate_device_flow.return_value = {"error": "bad_request"}

    with patch.object(ma.msal, "PublicClientApplication", return_value=mock_app):
        token = ma.get_token(scopes=["Mail.Read"])

    assert token is None


def test_get_token_returns_none_on_msal_exception(monkeypatch, capsys):
    import importlib
    import integrations.msal_auth as ma
    importlib.reload(ma)
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "fake-client-id")

    # Simulate PublicClientApplication raising an exception
    with patch.object(ma.msal, "PublicClientApplication", side_effect=RuntimeError("Network error")):
        token = ma.get_token(scopes=["Mail.Read"])

    assert token is None
    captured = capsys.readouterr()
    assert "msal_auth: unexpected error:" in captured.err
    assert "Network error" in captured.err


def test_get_token_handles_corrupted_cache(monkeypatch, capsys):
    import importlib
    import integrations.msal_auth as ma
    importlib.reload(ma)
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "fake-client-id")

    # Mock SerializableTokenCache to raise on deserialize if the cache file exists
    mock_cache = MagicMock()
    mock_cache.deserialize.side_effect = ValueError("Invalid cache format")
    mock_cache.has_state_changed = False

    mock_app = MagicMock()
    mock_app.get_accounts.return_value = [{"username": "test@example.com"}]
    mock_app.acquire_token_silent.return_value = {"access_token": "cached-tok"}

    with patch.object(ma, "TOKEN_CACHE_PATH") as mock_path:
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = "corrupted data"

        with patch.object(ma.msal, "SerializableTokenCache", return_value=mock_cache):
            with patch.object(ma.msal, "PublicClientApplication", return_value=mock_app):
                token = ma.get_token(scopes=["Mail.Read"])

    # Should succeed by treating corrupted cache as empty
    assert token == "cached-tok"
    captured = capsys.readouterr()
    assert "msal_auth: corrupted token cache, starting fresh:" in captured.err
