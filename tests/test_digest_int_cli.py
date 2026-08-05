"""query.py digest git-todo / digest build-watch -- new integration module."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "scripts"))
from integrations import digest_int  # noqa: E402
from voice import git_digest, todo_tracker, test_runner  # noqa: E402


def test_git_todo_combines_commits_and_todos(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(git_digest, "recent_commits", lambda repo, since_hours=24: [{"sha": "abc", "message": "fix"}])
    monkeypatch.setattr(todo_tracker, "unchecked_todos", lambda vault: ["write tests"])
    monkeypatch.setattr(digest_int.voice_config, "get_vault_dir", lambda: tmp_path)

    rc = digest_int.handle_query(["git-todo", "--json"])

    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {
        "commits": [{"sha": "abc", "message": "fix"}], "todos": ["write tests"]
    }


def test_git_todo_empty_vault_gives_empty_todos(monkeypatch, capsys):
    monkeypatch.setattr(git_digest, "recent_commits", lambda repo, since_hours=24: [])
    monkeypatch.setattr(digest_int.voice_config, "get_vault_dir", lambda: None)

    digest_int.handle_query(["git-todo", "--json"])

    assert json.loads(capsys.readouterr().out) == {"commits": [], "todos": []}


def test_build_watch_runs_tests_and_skips_workflow_without_repo(monkeypatch, capsys):
    monkeypatch.setattr(test_runner, "run_test_suite", lambda root: {"passed": 5, "failed": 0, "ok": True})

    rc = digest_int.handle_query(["build-watch", "--json"])

    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {
        "test": {"passed": 5, "failed": 0, "ok": True}, "workflow": None
    }


def test_build_watch_checks_workflow_when_repo_given(monkeypatch, capsys):
    monkeypatch.setattr(test_runner, "run_test_suite", lambda root: {"passed": 1, "failed": 1, "ok": False})
    monkeypatch.setattr(digest_int.github_int, "latest_workflow_run", lambda repo: {"conclusion": "failure"})

    digest_int.handle_query(["build-watch", "--repo", "me/repo", "--json"])

    assert json.loads(capsys.readouterr().out) == {
        "test": {"passed": 1, "failed": 1, "ok": False}, "workflow": {"conclusion": "failure"}
    }
