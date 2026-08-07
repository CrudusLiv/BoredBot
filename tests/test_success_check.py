"""Section 4: success_check + delete_after_success."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _import_vault_fs():
    """Locate the project's integrations/ module under the live repo, not tmp_vault.
    The function under test operates on caller-supplied paths, not env-derived ones."""
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / ".claude" / "scripts"))
    from integrations import vault_fs  # type: ignore
    return vault_fs


def test_success_check_accepts_valid_note(tmp_path):
    vault_fs = _import_vault_fs()
    note = tmp_path / "ok.md"
    note.write_text(
        "---\ntype: lecture\ncourse: CS101\n---\n\n# Title\n\nBody text here.\n",
        encoding="utf-8",
    )
    assert vault_fs.success_check(note) is True


def test_success_check_rejects_missing_file(tmp_path):
    vault_fs = _import_vault_fs()
    note = tmp_path / "missing.md"
    assert vault_fs.success_check(note) is False


def test_success_check_rejects_no_frontmatter(tmp_path):
    vault_fs = _import_vault_fs()
    note = tmp_path / "noframe.md"
    note.write_text("# Title\n\nJust prose.\n", encoding="utf-8")
    assert vault_fs.success_check(note) is False


def test_success_check_rejects_invalid_frontmatter(tmp_path):
    vault_fs = _import_vault_fs()
    note = tmp_path / "broken.md"
    note.write_text("---\nkey: : invalid\n---\n\n# T\n\nbody\n", encoding="utf-8")
    assert vault_fs.success_check(note) is False


def test_success_check_rejects_empty_body(tmp_path):
    vault_fs = _import_vault_fs()
    note = tmp_path / "empty_body.md"
    note.write_text("---\ntype: lecture\n---\n\n", encoding="utf-8")
    assert vault_fs.success_check(note) is False


def test_success_check_accepts_multiline_scalar(tmp_path):
    vault_fs = _import_vault_fs()
    note = tmp_path / "multiline.md"
    note.write_text(
        "---\ntype: lecture\nsummary: >-\n  Continuation line one.\n  Continuation line two.\n---\n\n# T\n\nbody\n",
        encoding="utf-8",
    )
    assert vault_fs.success_check(note) is True


def test_delete_after_success_deletes_source(tmp_path):
    vault_fs = _import_vault_fs()
    # Set up an inbox/_processed/ structure under tmp_path so the carve-out check passes.
    processed = tmp_path / "inbox" / "_processed"
    processed.mkdir(parents=True)
    src = processed / "source.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    note = tmp_path / "note.md"
    note.write_text("---\ntype: lecture\n---\n\n# T\n\nbody\n", encoding="utf-8")
    deleted = vault_fs.delete_after_success(src, note)
    assert deleted is True
    assert not src.exists()


def test_delete_after_success_keeps_source_on_failure(tmp_path):
    vault_fs = _import_vault_fs()
    processed = tmp_path / "inbox" / "_processed"
    processed.mkdir(parents=True)
    src = processed / "source.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    note = tmp_path / "broken.md"
    note.write_text("no frontmatter here", encoding="utf-8")
    deleted = vault_fs.delete_after_success(src, note)
    assert deleted is False
    assert src.exists()


def test_delete_after_success_refuses_outside_processed(tmp_path):
    """Carve-out enforcement: src must live inside inbox/_processed/."""
    vault_fs = _import_vault_fs()
    src = tmp_path / "some_other_dir" / "source.pdf"
    src.parent.mkdir()
    src.write_bytes(b"%PDF-1.4 fake")
    note = tmp_path / "note.md"
    note.write_text("---\ntype: lecture\n---\n\n# T\n\nbody\n", encoding="utf-8")
    with pytest.raises(ValueError):
        vault_fs.delete_after_success(src, note)
    assert src.exists()  # not deleted
