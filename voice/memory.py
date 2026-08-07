"""Vault-backed memory: USER.md + MEMORY.md context, fact write/remove.

All functions are no-ops (or return a clear error) when no vault is
configured — see voice.config.get_vault_dir().
"""
from __future__ import annotations
import voice  # noqa: F401
from voice import config as cfg


def load_context() -> str:
    vault = cfg.get_vault_dir()
    if vault is None:
        return ""
    parts = []
    for fname in ("USER.md", "MEMORY.md"):
        p = vault / fname
        if p.exists():
            text = p.read_text(encoding="utf-8").strip()
            if text:
                parts.append(text)
    return "\n\n---\n\n".join(parts)


_WRITE_MISMATCH = (
    "Vault writes disabled: your configured vault_path doesn't match the "
    "agent's actual write target. Leave vault_path unset to use the default vault."
)


def remember(key: str, value: str) -> str:
    if cfg.get_vault_dir() is None:
        return "No vault configured — set vault_path in settings to enable memory."
    if not cfg.vault_writes_safe():
        return _WRITE_MISMATCH
    from vault import actions  # type: ignore
    try:
        actions.append("MEMORY.md", f"\n- {key}: {value}")
        return f"Remembered: {key}: {value}"
    except Exception as exc:
        return f"Error saving fact: {exc}"


def forget(key: str) -> str:
    if cfg.get_vault_dir() is None:
        return "No vault configured — set vault_path in settings to enable memory."
    if not cfg.vault_writes_safe():
        return _WRITE_MISMATCH
    from vault import actions, paths  # type: ignore
    try:
        target = paths.validate("MEMORY.md")
        content = target.read_text(encoding="utf-8")
        line = next(
            (l for l in content.splitlines() if l.strip().startswith(f"- {key}:")),
            None,
        )
        if not line:
            return f"No fact with key: {key}"
        for needle in (line + "\n", line):
            if needle in content:
                actions.edit("MEMORY.md", find=needle, replace="")
                return f"Removed: {key}"
        return f"Could not remove: {key}"
    except Exception as exc:
        return f"Error: {exc}"
