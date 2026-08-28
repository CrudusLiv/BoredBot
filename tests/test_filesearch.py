"""voice/tools/filesearch.py — read-only machine-wide file search.

find_files matches by filename glob; search_files greps file contents. Both
are confined to filesearch_roots and must never scan or return a path that
hits filesearch_denylist (.env, ssh keys, credential stores). search_files
uses ripgrep when it's on PATH and a pure-Python walk otherwise; the two
paths must behave the same.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from voice.tools import filesearch


@pytest.fixture
def tree(tmp_path: Path, monkeypatch) -> Path:
    """A small file tree wired in as the only search root, with a
    predictable denylist."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "report.pdf").write_text("annual report")
    (tmp_path / "docs" / "notes.txt").write_text("meeting notes\nplan the sprint\n")
    (tmp_path / "code").mkdir()
    (tmp_path / "code" / "main.py").write_text("print('hello sprint')\n")
    (tmp_path / ".env").write_text("API_KEY=sprint-secret\n")
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "id_rsa").write_text("PRIVATE KEY sprint\n")
    monkeypatch.setattr(filesearch, "_roots", lambda: [tmp_path])
    monkeypatch.setattr(
        filesearch, "_denylist",
        lambda: [".env", ".ssh", "*.key", "*.pem", "id_rsa", "AppData"],
    )
    return tmp_path


# ── find_files ────────────────────────────────────────────────────────────────

def test_find_files_matches_by_name_glob(tree):
    result = filesearch.find_files("*.pdf")
    assert "report.pdf" in result
    assert "notes.txt" not in result


def test_find_files_is_case_insensitive(tree):
    assert "report.pdf" in filesearch.find_files("REPORT*")


def test_find_files_skips_denylisted_files(tree):
    result = filesearch.find_files("*")
    assert ".env" not in result
    assert "id_rsa" not in result


def test_find_files_no_match_reports_it(tree):
    assert "no files" in filesearch.find_files("*.xyz").lower()


def test_find_files_caps_results(tree, tmp_path):
    for i in range(20):
        (tmp_path / f"f{i}.log").write_text("x")
    result = filesearch.find_files("*.log", limit=5)
    assert len(result.splitlines()) == 5


def test_find_files_no_roots_reports_it(monkeypatch):
    monkeypatch.setattr(filesearch, "_roots", lambda: [])
    assert "no search roots" in filesearch.find_files("*").lower()


# ── search_files ─────────────────────────────────────────────────────────────

def test_search_files_finds_content(tree):
    result = filesearch.search_files("plan the sprint")
    assert "notes.txt" in result
    assert ":2:" in result  # line number


def test_search_files_skips_denylisted_files(tree):
    # The query string also lives in .env and .ssh/id_rsa — must not surface.
    result = filesearch.search_files("sprint")
    assert ".env" not in result
    assert "id_rsa" not in result


def test_search_files_no_match_reports_it(tree):
    assert "no matches" in filesearch.search_files("nonexistent-token-zzz").lower()


def test_search_files_path_glob_filters(tree):
    result = filesearch.search_files("sprint", path_glob="*.py")
    assert "main.py" in result
    assert "notes.txt" not in result


def test_search_files_python_fallback_matches_ripgrep(tree, monkeypatch):
    monkeypatch.setattr(filesearch.shutil, "which", lambda _name: None)
    result = filesearch.search_files("plan the sprint")
    assert "notes.txt" in result


def test_search_files_python_fallback_skips_binary(tree, tmp_path, monkeypatch):
    monkeypatch.setattr(filesearch.shutil, "which", lambda _name: None)
    (tmp_path / "blob.dat").write_bytes(b"before\x00sprint after")
    result = filesearch.search_files("sprint")
    assert "blob.dat" not in result


def test_search_files_python_fallback_skips_large_files(tree, tmp_path, monkeypatch):
    monkeypatch.setattr(filesearch.shutil, "which", lambda _name: None)
    monkeypatch.setattr(filesearch, "_MAX_FILE_BYTES", 100)
    (tmp_path / "big.txt").write_text("sprint " * 200)
    result = filesearch.search_files("sprint")
    assert "big.txt" not in result


def test_search_files_output_is_capped(tree, tmp_path, monkeypatch):
    monkeypatch.setattr(filesearch, "_MAX_OUTPUT_CHARS", 200)
    big = "\n".join(f"line {i} sprint" for i in range(500))
    (tmp_path / "many.txt").write_text(big)
    result = filesearch.search_files("sprint", limit=500)
    assert len(result) <= 400  # cap + a short truncation marker
    assert "truncated" in result.lower()


# ── helpers reading real config ──────────────────────────────────────────────

def test_roots_default_set_when_config_empty(monkeypatch):
    from voice import config as cfg
    monkeypatch.setattr(cfg, "load", lambda: {"filesearch_roots": []})
    # Default roots resolve against the home dir; some may not exist on this
    # machine — just assert the call returns a list and does not raise.
    assert isinstance(filesearch._roots(), list)


def test_roots_config_list_replaces_default(tmp_path, monkeypatch):
    from voice import config as cfg
    monkeypatch.setattr(cfg, "load", lambda: {"filesearch_roots": [str(tmp_path)]})
    assert filesearch._roots() == [tmp_path.resolve()]


def test_denylist_comes_from_config(monkeypatch):
    from voice import config as cfg
    monkeypatch.setattr(cfg, "load", lambda: {"filesearch_denylist": ["*.foo"]})
    assert filesearch._denylist() == ["*.foo"]


# ── registration ─────────────────────────────────────────────────────────────

def test_filesearch_tools_in_registry():
    from voice import tools
    names = {t["name"] for t in tools.REGISTRY}
    assert {"find_files", "search_files"} <= names


def test_config_defaults_present():
    from voice import config as cfg
    assert "filesearch_roots" in cfg.DEFAULTS
    assert "filesearch_denylist" in cfg.DEFAULTS
    assert ".env" in cfg.DEFAULTS["filesearch_denylist"]
