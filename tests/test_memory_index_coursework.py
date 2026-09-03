"""coursework/ notes are discovered by the memory indexer."""
from __future__ import annotations

import sys
from pathlib import Path


def test_coursework_in_include_dirs():
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / ".claude" / "scripts" / "memory"))
    import memory_index
    assert "coursework" in memory_index.INCLUDE_DIRS
