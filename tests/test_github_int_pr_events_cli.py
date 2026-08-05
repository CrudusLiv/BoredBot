"""query.py github pr-events -- new CLI subcommand over recent_pr_events()."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "scripts"))
from integrations import github_int  # noqa: E402


def test_pr_events_prints_json_array(monkeypatch, capsys):
    events = [{"id": "open:me/repo:1", "kind": "pr_opened", "repo": "me/repo",
               "pr_number": 1, "pr_title": "x", "pr_url": "https://x", "actor": "a", "ts": 123.0}]
    monkeypatch.setattr(github_int, "recent_pr_events", lambda repos=None, since=None: events)

    rc = github_int.handle_query(["pr-events", "--json"])

    assert rc == 0
    assert json.loads(capsys.readouterr().out) == events


def test_pr_events_passes_since_and_repos_through(monkeypatch):
    captured = {}

    def fake(repos=None, since=None):
        captured["repos"] = repos
        captured["since"] = since
        return []

    monkeypatch.setattr(github_int, "recent_pr_events", fake)
    github_int.handle_query(["pr-events", "--repos", "a/b,c/d", "--since", "1000.5", "--json"])

    assert captured["repos"] == ["a/b", "c/d"]
    assert captured["since"] == 1000.5


def test_pr_events_defaults_repos_and_since_to_none(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        github_int, "recent_pr_events",
        lambda repos=None, since=None: captured.update(repos=repos, since=since) or []
    )
    github_int.handle_query(["pr-events", "--json"])

    assert captured == {"repos": None, "since": None}
