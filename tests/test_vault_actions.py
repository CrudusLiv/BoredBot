"""Tests for vault/actions.py — one per verb. Builds out incrementally."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))

from vault import actions  # noqa: E402


@pytest.fixture
def isolated_log(tmp_vault, tmp_data) -> Path:
    """tmp_vault sets CLAUDE_PROJECT_DIR, so transactions._log_path() resolves
    into tmp_data automatically. Just return the path tests should read from."""
    return tmp_data / "vault_transactions.jsonl"


def _read_log(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------- append ----------

def test_append_adds_text_to_existing_file(tmp_vault, isolated_log):
    target = tmp_vault / "notes" / "x.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("hello\n", encoding="utf-8")
    original_size = target.stat().st_size  # byte count, may differ from len("hello\n") on Windows

    result = actions.append("notes/x.md", "world")
    assert target.read_text(encoding="utf-8") == "hello\nworld"
    assert result["path"] == "notes/x.md"

    log = _read_log(isolated_log)
    assert len(log) == 1
    assert log[0]["action"] == "append"
    assert log[0]["undo_state"]["original_length"] == original_size


def test_append_errors_when_file_missing(tmp_vault, isolated_log):
    with pytest.raises(FileNotFoundError):
        actions.append("notes/missing.md", "world")
    assert _read_log(isolated_log) == []  # no log entry on failure


# ---------- create ----------

def test_create_writes_new_file(tmp_vault, isolated_log):
    result = actions.create("notes/new.md", "fresh content")
    target = tmp_vault / "notes" / "new.md"
    assert target.read_text(encoding="utf-8") == "fresh content"
    assert result["path"] == "notes/new.md"

    log = _read_log(isolated_log)
    assert len(log) == 1
    assert log[0]["action"] == "create"


def test_create_errors_when_path_exists(tmp_vault, isolated_log):
    target = tmp_vault / "notes" / "x.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("already here", encoding="utf-8")
    with pytest.raises(FileExistsError):
        actions.create("notes/x.md", "would overwrite")
    assert _read_log(isolated_log) == []


def test_create_creates_parent_directories(tmp_vault, isolated_log):
    actions.create("research/new-area/note.md", "content")
    target = tmp_vault / "research" / "new-area" / "note.md"
    assert target.read_text(encoding="utf-8") == "content"


# ---------- edit ----------

def test_edit_replaces_single_occurrence(tmp_vault, isolated_log):
    target = tmp_vault / "notes" / "x.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("alpha beta gamma\n", encoding="utf-8")

    actions.edit("notes/x.md", find="beta", replace="BETA")
    assert target.read_text(encoding="utf-8") == "alpha BETA gamma\n"
    log = _read_log(isolated_log)
    assert log[0]["action"] == "edit"
    assert log[0]["undo_state"] == {"find_was": "beta", "replace_was": "BETA"}


def test_edit_errors_when_find_missing(tmp_vault, isolated_log):
    target = tmp_vault / "notes" / "x.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("alpha\n", encoding="utf-8")
    with pytest.raises(ValueError, match="0 matches"):
        actions.edit("notes/x.md", find="beta", replace="BETA")


def test_edit_errors_when_find_ambiguous(tmp_vault, isolated_log):
    target = tmp_vault / "notes" / "x.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("beta beta\n", encoding="utf-8")
    with pytest.raises(ValueError, match="2 matches"):
        actions.edit("notes/x.md", find="beta", replace="BETA")


# ---------- rename ----------

def test_rename_moves_file_within_same_dir(tmp_vault, isolated_log):
    src = tmp_vault / "notes" / "old.md"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("hi", encoding="utf-8")

    actions.rename("notes/old.md", "new.md")
    assert not src.exists()
    assert (tmp_vault / "notes" / "new.md").read_text(encoding="utf-8") == "hi"
    log = _read_log(isolated_log)
    assert log[0]["action"] == "rename"
    assert log[0]["undo_state"]["old_path"] == "notes/old.md"
    assert log[0]["undo_state"]["new_path"] == "notes/new.md"


def test_rename_errors_when_target_exists(tmp_vault, isolated_log):
    src = tmp_vault / "notes" / "old.md"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("hi", encoding="utf-8")
    (tmp_vault / "notes" / "new.md").write_text("taken", encoding="utf-8")
    with pytest.raises(FileExistsError):
        actions.rename("notes/old.md", "new.md")


# ---------- move ----------

def test_move_relocates_file_to_other_dir(tmp_vault, isolated_log):
    src = tmp_vault / "notes" / "x.md"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("hi", encoding="utf-8")

    actions.move("notes/x.md", "research")
    assert not src.exists()
    assert (tmp_vault / "research" / "x.md").read_text(encoding="utf-8") == "hi"
    log = _read_log(isolated_log)
    assert log[0]["action"] == "move"
    assert log[0]["undo_state"] == {"from": "notes/x.md", "to": "research/x.md"}


# ---------- delete (soft) ----------

def test_delete_moves_file_to_trash(tmp_vault, isolated_log):
    src = tmp_vault / "notes" / "x.md"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("bye", encoding="utf-8")

    result = actions.delete("notes/x.md")
    assert not src.exists()

    trash_rel = result["trash_path"]
    assert trash_rel.startswith("_trash/")
    assert (tmp_vault / trash_rel).read_text(encoding="utf-8") == "bye"

    log = _read_log(isolated_log)
    assert log[0]["action"] == "delete"
    assert log[0]["undo_state"]["trash_path"] == trash_rel


def test_delete_does_not_call_unlink(tmp_vault, isolated_log, monkeypatch):
    """Hard guarantee: soft-delete never reaches Path.unlink."""
    src = tmp_vault / "notes" / "x.md"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("bye", encoding="utf-8")

    real_unlink = Path.unlink
    def boom(self, *a, **kw):
        raise AssertionError(f"unlink called on {self}")
    monkeypatch.setattr(Path, "unlink", boom)
    try:
        actions.delete("notes/x.md")
    finally:
        monkeypatch.setattr(Path, "unlink", real_unlink)


def test_delete_handles_name_collision_in_trash(tmp_vault, isolated_log):
    """Two deletes in the same day of files with the same name must both succeed."""
    for first in (True, False):
        src = tmp_vault / "notes" / "x.md"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text("v1" if first else "v2", encoding="utf-8")
        actions.delete("notes/x.md")

    # Trash should contain two distinct entries under today's date dir
    trash_today = list((tmp_vault / "_trash").rglob("x*.md"))
    assert len(trash_today) == 2


# ---------- list ----------

def test_list_returns_filenames_in_dir(tmp_vault, isolated_log):
    d = tmp_vault / "notes"
    d.mkdir(exist_ok=True)
    (d / "a.md").write_text("", encoding="utf-8")
    (d / "b.md").write_text("", encoding="utf-8")

    result = actions.list_dir("notes")
    assert set(result["entries"]) == {"a.md", "b.md"}


def test_list_is_not_recursive(tmp_vault, isolated_log):
    d = tmp_vault / "notes"
    (d / "sub").mkdir(parents=True, exist_ok=True)
    (d / "a.md").write_text("", encoding="utf-8")
    (d / "sub" / "b.md").write_text("", encoding="utf-8")

    result = actions.list_dir("notes")
    assert "a.md" in result["entries"]
    assert "b.md" not in result["entries"]
    assert "sub" in result["entries"]  # dir name shown, no descent


def test_list_logs_nothing(tmp_vault, isolated_log):
    (tmp_vault / "notes").mkdir(exist_ok=True)
    actions.list_dir("notes")
    assert _read_log(isolated_log) == []  # read-only verb, no log entry


# ---------- undo ----------

def test_undo_returns_message_when_log_empty(tmp_vault, isolated_log):
    result = actions.undo()
    assert "nothing to undo" in result["message"].lower()


def test_undo_reverses_append(tmp_vault, isolated_log):
    target = tmp_vault / "notes" / "x.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("hello\n", encoding="utf-8")
    actions.append("notes/x.md", "world")
    assert target.read_text(encoding="utf-8") == "hello\nworld"

    actions.undo()
    assert target.read_text(encoding="utf-8") == "hello\n"

    # Two log entries now: the append and its inverse
    log = _read_log(isolated_log)
    assert len(log) == 2
    assert log[1]["action"] == "undo_of_append"


def test_undo_reverses_create_via_soft_delete(tmp_vault, isolated_log):
    actions.create("notes/new.md", "hi")
    assert (tmp_vault / "notes" / "new.md").exists()
    actions.undo()
    assert not (tmp_vault / "notes" / "new.md").exists()
    # The file landed in trash via the soft-delete inverse
    trash = list((tmp_vault / "_trash").rglob("new.md"))
    assert len(trash) == 1


def test_undo_reverses_delete_by_restoring_from_trash(tmp_vault, isolated_log):
    target = tmp_vault / "notes" / "x.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("alive", encoding="utf-8")
    actions.delete("notes/x.md")
    assert not target.exists()

    actions.undo()
    assert target.read_text(encoding="utf-8") == "alive"


def test_undo_reverses_rename(tmp_vault, isolated_log):
    src = tmp_vault / "notes" / "old.md"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("hi", encoding="utf-8")
    actions.rename("notes/old.md", "new.md")
    actions.undo()
    assert src.read_text(encoding="utf-8") == "hi"
    assert not (tmp_vault / "notes" / "new.md").exists()


def test_undo_reverses_move(tmp_vault, isolated_log):
    src = tmp_vault / "notes" / "x.md"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("hi", encoding="utf-8")
    actions.move("notes/x.md", "research")
    actions.undo()
    assert src.read_text(encoding="utf-8") == "hi"
    assert not (tmp_vault / "research" / "x.md").exists()


def test_undo_reverses_edit(tmp_vault, isolated_log):
    target = tmp_vault / "notes" / "x.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("alpha BETA gamma\n", encoding="utf-8")
    actions.edit("notes/x.md", find="BETA", replace="beta")
    actions.undo()
    assert target.read_text(encoding="utf-8") == "alpha BETA gamma\n"


def test_undo_undo_redoes_the_action(tmp_vault, isolated_log):
    target = tmp_vault / "notes" / "x.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("hello\n", encoding="utf-8")
    actions.append("notes/x.md", "world")
    actions.undo()  # back to "hello\n"
    actions.undo()  # redo the append → "hello\nworld"
    assert target.read_text(encoding="utf-8") == "hello\nworld"
