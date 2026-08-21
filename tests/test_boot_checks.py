# tests/test_boot_checks.py
"""Boot-check probes: shape, per-probe error isolation, no hard failures."""
from __future__ import annotations

import pytest

from voice import boot_checks


@pytest.fixture(autouse=True)
def _no_live_llm_probe(monkeypatch):
    """_llm() calls voice.llm.get_status(), which auto-detects the backend by
    opening a live socket to localhost (Ollama/LM Studio). In sandboxed or
    firewalled environments that connect can hang well past its own declared
    timeout, taking the whole test run down with it -- stub it so boot-check
    tests never touch the network."""
    from voice import llm

    monkeypatch.setattr(
        llm, "get_status",
        lambda: {"backend": "claude_cli", "model": "sonnet", "available": True},
    )


def test_run_all_returns_one_row_per_probe():
    rows = boot_checks.run_all()
    assert len(rows) == len(boot_checks.PROBES)
    assert {r["id"] for r in rows} == set(boot_checks.PROBES)


def test_every_row_has_the_full_shape():
    for row in boot_checks.run_all():
        assert set(row) == {"id", "label", "detail", "status", "error"}
        assert row["status"] in {"ok", "fail", "skip"}
        assert isinstance(row["label"], str) and row["label"]


def test_a_raising_probe_becomes_a_failed_row(monkeypatch):
    def boom():
        raise RuntimeError("disk on fire")

    monkeypatch.setitem(boot_checks.PROBES, "stt", ("STT", boom))
    rows = {r["id"]: r for r in boot_checks.run_all()}
    assert rows["stt"]["status"] == "fail"
    assert "disk on fire" in rows["stt"]["error"]


def test_a_raising_probe_does_not_stop_the_others(monkeypatch):
    def boom():
        raise RuntimeError("nope")

    monkeypatch.setitem(boot_checks.PROBES, "stt", ("STT", boom))
    rows = boot_checks.run_all()
    assert len(rows) == len(boot_checks.PROBES)
    assert any(r["status"] != "fail" for r in rows)
