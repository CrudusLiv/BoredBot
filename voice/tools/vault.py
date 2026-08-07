"""Vault tools: read notes (safe), append/create notes (require confirmation).

No-ops with a clear error when no vault is configured — see
voice.config.get_vault_dir().
"""
from __future__ import annotations
import voice  # noqa: F401
from voice import config as cfg

_NO_VAULT = "No vault configured — set vault_path in settings to enable notes."
_WRITE_MISMATCH = (
    "Vault writes disabled: your configured vault_path doesn't match the "
    "agent's actual write target. Leave vault_path unset to use the default vault."
)


def read_note(path: str) -> str:
    vault = cfg.get_vault_dir()
    if vault is None:
        return _NO_VAULT
    full = (vault / path).resolve()
    try:
        full.relative_to(vault.resolve())
    except ValueError:
        return f"Error: {path!r} is outside the vault."
    if not full.exists():
        return f"File not found: {path}"
    return full.read_text(encoding="utf-8")


def append_note(path: str, text: str) -> str:
    if cfg.get_vault_dir() is None:
        return _NO_VAULT
    if not cfg.vault_writes_safe():
        return _WRITE_MISMATCH
    from vault import actions  # type: ignore
    try:
        r = actions.append(path, text)
        return f"Appended {r['appended_chars']} chars to {path}."
    except Exception as exc:
        return f"Error: {exc}"


def create_note(path: str, text: str) -> str:
    if cfg.get_vault_dir() is None:
        return _NO_VAULT
    if not cfg.vault_writes_safe():
        return _WRITE_MISMATCH
    from vault import actions  # type: ignore
    try:
        r = actions.create(path, text)
        return f"Created {path} ({r['bytes']} bytes)."
    except Exception as exc:
        return f"Error: {exc}"
