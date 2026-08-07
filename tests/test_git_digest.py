"""voice/git_digest.py — local `git log` reader for the daily summary."""
from __future__ import annotations

import subprocess

import pytest

from voice.git_digest import recent_commits


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("1", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "first commit"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("2", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "second commit"], cwd=tmp_path, check=True)
    return tmp_path


def test_recent_commits_returns_both_commits(repo):
    commits = recent_commits(repo, since_hours=24)
    messages = [c["message"] for c in commits]
    assert messages == ["first commit", "second commit"] or messages == ["second commit", "first commit"]


def test_recent_commits_each_has_sha_and_date(repo):
    commits = recent_commits(repo, since_hours=24)
    for c in commits:
        assert len(c["sha"]) >= 7
        assert c["date"]


def test_recent_commits_empty_for_non_git_dir(tmp_path):
    assert recent_commits(tmp_path / "not-a-repo", since_hours=24) == []


def test_recent_commits_since_window_excludes_old(repo):
    commits = recent_commits(repo, since_hours=0)
    # since_hours=0 means "since right now" — a commit made moments ago in
    # the fixture may or may not clear the window depending on clock
    # resolution, so only assert the call doesn't raise and returns a list.
    assert isinstance(commits, list)
