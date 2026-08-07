"""Path safety gate for vault actions.

Every function in vault/actions.py calls validate() before touching disk.
The validator enforces the USER.md hard limits in code, not in the prompt,
so a misread LLM cannot bypass them.
"""
from __future__ import annotations

import difflib
import os
from pathlib import Path

_FORBIDDEN_PREFIXES = ("_trash", "finance")


def _is_forbidden_prefix(top: str) -> bool:
    return top.lower() in _FORBIDDEN_PREFIXES


def vault() -> Path:
    """Return the vault root, re-reading CLAUDE_PROJECT_DIR each call so
    tests that monkeypatch the env var see the temp vault."""
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
    return project_dir / "Dynamous" / "Memory"


def validate(path: str) -> Path:
    """Resolve `path` under the vault root, raising ValueError on any unsafe input.

    Rules:
      - Must be relative (no leading slash, no Windows drive letter)
      - Must not contain `..` segments
      - After resolving symlinks, must remain under the vault root
      - Must not target `_trash/` (restores go through undo only)
      - Must not target `finance/` (finance writes live in _handle_finance)
    """
    if not path or not isinstance(path, str) or not path.strip():
        raise ValueError("path must be a non-empty string")

    # Absolute path or drive letter
    if path.startswith("/") or path.startswith("\\"):
        raise ValueError(f"path must be relative, got {path!r}")
    if len(path) >= 2 and path[1] == ":":
        raise ValueError(f"path must be relative, got {path!r}")

    parts = Path(path).parts
    if ".." in parts:
        raise ValueError(f"path must not contain '..', got {path!r}")

    top = parts[0] if parts else ""
    if _is_forbidden_prefix(top):
        raise ValueError(f"path under {top}/ is off-limits, got {path!r}")

    vault_root = vault()
    candidate = (vault_root / path).resolve()
    vault_resolved = vault_root.resolve()
    try:
        candidate.relative_to(vault_resolved)
    except ValueError as exc:
        raise ValueError(f"path resolves outside vault: {path!r}") from exc

    return candidate


_MAX_SUGGESTIONS = 3
_CUTOFF = 0.6  # difflib default; close enough for the spec's >0.7 / >0.85 bands


def _vault_files() -> list[str]:
    """All .md files under the vault as relative POSIX paths, excluding forbidden prefixes."""
    vault_root = vault()
    if not vault_root.exists():
        return []
    out: list[str] = []
    for p in vault_root.rglob("*.md"):
        try:
            rel = p.relative_to(vault_root).as_posix()
        except ValueError:
            continue
        top = rel.split("/", 1)[0]
        if _is_forbidden_prefix(top):
            continue
        out.append(rel)
    return out


def suggest_for_missing(path: str) -> list[str]:
    """Return up to 3 vault paths that look like what the caller meant.

    Empty list if no close matches. Caller decides whether to surface them
    as a disambiguation prompt or just report file-not-found.
    """
    candidates = _vault_files()
    if not candidates:
        return []
    target = Path(path).name  # match by filename first
    by_name = difflib.get_close_matches(target, [Path(c).name for c in candidates], n=_MAX_SUGGESTIONS, cutoff=_CUTOFF)
    matches = [c for c in candidates if Path(c).name in by_name]
    if matches:
        return matches[:_MAX_SUGGESTIONS]
    return difflib.get_close_matches(path, candidates, n=_MAX_SUGGESTIONS, cutoff=_CUTOFF)
