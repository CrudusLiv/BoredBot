"""Vesper's own workspace: drafts/active/ and scratch/ — writes that don't
require confirmation.

These are deliberately NOT routed through .claude/scripts/vault/actions.py's
create()/append() — those raise on existing-file conflicts and log an
undo/transactions entry, which is right for user-authored vault content but
wrong here: drafts/active/ and scratch/ are staging areas Vesper writes to
freely, so writes are upsert (overwrite-if-exists) and leave no undo-log
trail. Nothing here is ever auto-deleted or auto-moved; cleanup is manual,
by the user.

Gated the same way as read_note/append_note/create_note in voice/tools/
vault.py: cfg.get_vault_dir() must resolve and cfg.vault_writes_safe() must
be true (vault_path matches the agent layer's actual write target). Path
safety (relative, no `..`, stays under the vault, not a forbidden prefix)
is enforced by .claude/scripts/vault/paths.py:validate() — the same
validator every vault/actions.py verb uses.

No read tool here — voice/tools/vault.py's read_note already reads any path
under the vault, including drafts/... and scratch/....
"""
from __future__ import annotations
import voice  # noqa: F401 — sys.path setup for .claude/scripts
from voice import config as cfg

_NO_VAULT = "No vault configured — set vault_path in settings to enable notes."
_WRITE_MISMATCH = (
    "Vault writes disabled: your configured vault_path doesn't match the "
    "agent's actual write target. Leave vault_path unset to use the default vault."
)


def _safe_write(rel_path: str, text: str) -> str:
    if cfg.get_vault_dir() is None:
        return _NO_VAULT
    if not cfg.vault_writes_safe():
        return _WRITE_MISMATCH
    from vault import paths  # type: ignore
    try:
        target = paths.validate(rel_path)
    except ValueError as exc:
        return f"Error: {exc}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return f"Wrote {len(text.encode('utf-8'))} bytes to {rel_path}."


def write_draft(name: str, text: str) -> str:
    """Write (overwrite) drafts/active/<name>. No confirmation required."""
    return _safe_write(f"drafts/active/{name}", text)


def write_scratch(path: str, text: str) -> str:
    """Write (overwrite) scratch/<path>. No confirmation required."""
    return _safe_write(f"scratch/{path}", text)
