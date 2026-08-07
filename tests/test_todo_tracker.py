"""voice/todo_tracker.py — Dynamous/Memory/TODO.md checkbox parser."""
from __future__ import annotations

from voice.todo_tracker import todo_count, unchecked_todos


def test_unchecked_todos_returns_open_items(tmp_path):
    (tmp_path / "TODO.md").write_text(
        "- [ ] Write plan\n- [x] Read spec\n- [ ] Ship it\n", encoding="utf-8"
    )
    assert unchecked_todos(tmp_path) == ["Write plan", "Ship it"]


def test_todo_count_counts_done_and_total(tmp_path):
    (tmp_path / "TODO.md").write_text(
        "- [ ] Write plan\n- [x] Read spec\n- [ ] Ship it\n", encoding="utf-8"
    )
    assert todo_count(tmp_path) == (1, 3)


def test_missing_file_returns_empty(tmp_path):
    assert unchecked_todos(tmp_path) == []
    assert todo_count(tmp_path) == (0, 0)


def test_ignores_non_checkbox_lines(tmp_path):
    (tmp_path / "TODO.md").write_text(
        "# Todos\n\n- [ ] Real task\nSome prose line\n", encoding="utf-8"
    )
    assert unchecked_todos(tmp_path) == ["Real task"]
