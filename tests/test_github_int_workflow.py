"""integrations.github_int.latest_workflow_run — release-build status check."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "scripts"))
from integrations import github_int  # noqa: E402


def _stub_client(monkeypatch, runs):
    g = MagicMock()
    repo = MagicMock()
    workflow = MagicMock()
    workflow.get_runs.return_value = runs
    repo.get_workflow.return_value = workflow
    g.get_repo.return_value = repo
    monkeypatch.setattr(github_int, "_get_client", lambda: g)
    return g


def _run(status="completed", conclusion="success", url="https://x/1", created="2026-07-07T09:00:00Z"):
    r = MagicMock()
    r.status = status
    r.conclusion = conclusion
    r.html_url = url
    r.created_at.isoformat.return_value = created
    return r


def test_returns_latest_run_fields(monkeypatch):
    _stub_client(monkeypatch, [_run(conclusion="failure")])
    result = github_int.latest_workflow_run("me/repo", "build.yml")
    assert result == {
        "status": "completed", "conclusion": "failure",
        "html_url": "https://x/1", "created_at": "2026-07-07T09:00:00Z",
    }


def test_returns_none_when_no_runs(monkeypatch):
    _stub_client(monkeypatch, [])
    assert github_int.latest_workflow_run("me/repo", "build.yml") is None


def test_returns_none_when_no_client(monkeypatch):
    monkeypatch.setattr(github_int, "_get_client", lambda: None)
    assert github_int.latest_workflow_run("me/repo", "build.yml") is None


def test_returns_none_on_api_error(monkeypatch):
    g = MagicMock()
    g.get_repo.side_effect = RuntimeError("rate limited")
    monkeypatch.setattr(github_int, "_get_client", lambda: g)
    assert github_int.latest_workflow_run("me/repo", "build.yml") is None
