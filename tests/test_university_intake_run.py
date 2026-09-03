# tests/test_university_intake_run.py
"""run_intake: walk, manifest diff, note writes, MOC, orphans."""
from __future__ import annotations

from pathlib import Path

from voice import university_intake as ui

CONFIG = {
    "university_intake_extensions": [".txt", ".md", ".pdf"],
    "university_intake_denylist": ["Visual Studio", "intern", "Uni General"],
    "university_intake_mode": "per-file",
    "university_intake_max_chars": 20000,
    "university_intake_deadline_detection": True,
}


def _tree(root: Path):
    base = root / "University" / "Uni Assignments" / "Degree" / "Sem 2" / "BIT216"
    base.mkdir(parents=True)
    (base / "brief.txt").write_text("Assignment brief. Submission due 15/10/2026.", encoding="utf-8")
    tut = root / "University" / "Uni Tutorial" / "Degree" / "Sem 1" / "FEC100"
    tut.mkdir(parents=True)
    (tut / "lab1.txt").write_text("Tutorial one body.", encoding="utf-8")
    denied = root / "Visual Studio" / "Calorie Counter"
    denied.mkdir(parents=True)
    (denied / "Program.txt").write_text("code", encoding="utf-8")
    (root / "loose.txt").write_text("directly under root", encoding="utf-8")


def test_fresh_ingest(tmp_path):
    root, vault = tmp_path / "U", tmp_path / "V"
    _tree(root)
    vault.mkdir()
    manifest = {"version": 1, "files": {}}
    res = ui.run_intake(root, vault, manifest=manifest, config=CONFIG)
    assert sorted(res.added) == [
        "coursework/bit216/brief.md", "coursework/fec100/lab1.md",
    ]
    assert res.skipped >= 1           # denied Program.txt
    assert res.unparsed >= 1          # loose.txt under root
    assert ("2026-10-15", "BIT216 — brief") in res.deadlines
    note = vault / "coursework" / "bit216" / "brief.md"
    assert note.exists()
    assert "[[bit216]]" in note.read_text(encoding="utf-8")
    assert "University/Uni Assignments/Degree/Sem 2/BIT216/brief.txt" in manifest["files"]


def test_second_run_no_changes_no_rewrite(tmp_path):
    root, vault = tmp_path / "U", tmp_path / "V"
    _tree(root); vault.mkdir()
    manifest = {"version": 1, "files": {}}
    ui.run_intake(root, vault, manifest=manifest, config=CONFIG)
    note = vault / "coursework" / "bit216" / "brief.md"
    mtime = note.stat().st_mtime_ns
    res2 = ui.run_intake(root, vault, manifest=manifest, config=CONFIG)
    assert res2.added == [] and res2.updated == []
    assert note.stat().st_mtime_ns == mtime


def test_changed_source_updates_note(tmp_path):
    root, vault = tmp_path / "U", tmp_path / "V"
    _tree(root); vault.mkdir()
    manifest = {"version": 1, "files": {}}
    ui.run_intake(root, vault, manifest=manifest, config=CONFIG)
    brief = root / "University" / "Uni Assignments" / "Degree" / "Sem 2" / "BIT216" / "brief.txt"
    brief.write_text("Rewritten brief body.", encoding="utf-8")
    res = ui.run_intake(root, vault, manifest=manifest, config=CONFIG)
    assert res.updated == ["coursework/bit216/brief.md"]
    assert "Rewritten brief body." in (vault / "coursework" / "bit216" / "brief.md").read_text(encoding="utf-8")


def test_orphan_shows_in_moc_and_drops_from_manifest(tmp_path):
    root, vault = tmp_path / "U", tmp_path / "V"
    _tree(root); vault.mkdir()
    manifest = {"version": 1, "files": {}}
    ui.run_intake(root, vault, manifest=manifest, config=CONFIG)
    (root / "University" / "Uni Tutorial" / "Degree" / "Sem 1" / "FEC100" / "lab1.txt").unlink()
    ui.run_intake(root, vault, manifest=manifest, config=CONFIG)
    moc = (vault / "coursework" / "_moc.md").read_text(encoding="utf-8")
    assert "## Orphaned" in moc and "coursework/fec100/lab1.md" in moc
    assert not any("lab1.txt" in k for k in manifest["files"])
    assert (vault / "coursework" / "fec100" / "lab1.md").exists()   # never deleted


def test_corrupt_extractor_writes_stub_and_continues(tmp_path, monkeypatch):
    root, vault = tmp_path / "U", tmp_path / "V"
    _tree(root); vault.mkdir()
    pdf_dir = root / "University" / "Uni Assignments" / "Degree" / "Sem 2" / "BIT216"
    (pdf_dir / "slides.pdf").write_bytes(b"%PDF-1.4 broken")
    def boom(p): raise RuntimeError("bang")
    monkeypatch.setattr(ui, "_extract_pdf", boom)
    manifest = {"version": 1, "files": {}}
    res = ui.run_intake(root, vault, manifest=manifest, config=CONFIG)
    assert "coursework/bit216/slides.md" in res.added
    assert "No extractable text" in (vault / "coursework" / "bit216" / "slides.md").read_text(encoding="utf-8")


def test_rollup_mode_one_note_per_course(tmp_path):
    root, vault = tmp_path / "U", tmp_path / "V"
    _tree(root); vault.mkdir()
    cfg = dict(CONFIG, university_intake_mode="rollup")
    manifest = {"version": 1, "files": {}}
    res = ui.run_intake(root, vault, manifest=manifest, config=cfg)
    assert "coursework/bit216.md" in res.added
    assert (vault / "coursework" / "bit216.md").read_text(encoding="utf-8").count("## ") >= 1


def test_per_file_exception_is_recorded_and_walk_continues(tmp_path, monkeypatch):
    root, vault = tmp_path / "U", tmp_path / "V"
    _tree(root); vault.mkdir()
    real_note_for = ui.note_for

    def flaky(parsed, text, truncated, mode):
        if parsed.course == "BIT216":
            raise ValueError("kaboom")
        return real_note_for(parsed, text, truncated, mode)

    monkeypatch.setattr(ui, "note_for", flaky)
    manifest = {"version": 1, "files": {}}
    res = ui.run_intake(root, vault, manifest=manifest, config=CONFIG)
    bad = "University/Uni Assignments/Degree/Sem 2/BIT216/brief.txt"
    assert res.errors == [f"{bad}: kaboom"]
    assert "coursework/fec100/lab1.md" in res.added
    assert not (vault / "coursework" / "bit216" / "brief.md").exists()


def test_errors_capped_at_20(tmp_path, monkeypatch):
    root, vault = tmp_path / "U", tmp_path / "V"
    base = root / "University" / "Uni Assignments" / "Degree" / "Sem 2" / "BIT216"
    base.mkdir(parents=True); vault.mkdir()
    for i in range(30):
        (base / f"f{i:02d}.txt").write_text(f"body {i}", encoding="utf-8")

    def boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(ui, "note_for", boom)
    manifest = {"version": 1, "files": {}}
    res = ui.run_intake(root, vault, manifest=manifest, config=CONFIG)
    assert len(res.errors) == 20


def test_max_chars_truncates_body(tmp_path):
    root, vault = tmp_path / "U", tmp_path / "V"
    base = root / "University" / "Uni Assignments" / "Degree" / "Sem 2" / "BIT216"
    base.mkdir(parents=True); vault.mkdir()
    (base / "big.txt").write_text("x " * 20000, encoding="utf-8")
    cfg = dict(CONFIG, university_intake_max_chars=100)
    manifest = {"version": 1, "files": {}}
    ui.run_intake(root, vault, manifest=manifest, config=cfg)
    md = (vault / "coursework" / "bit216" / "big.md").read_text(encoding="utf-8")
    assert "truncated: true" in md


def _course(root: Path) -> Path:
    base = root / "University" / "Uni Assignments" / "Degree" / "Sem 2" / "BIT216"
    base.mkdir(parents=True)
    return base


def test_slug_collision_dedupes_and_is_stable(tmp_path, monkeypatch):
    # brief.pdf + brief.txt in one course both slugify to coursework/bit216/brief.md
    root, vault = tmp_path / "U", tmp_path / "V"
    base = _course(root); vault.mkdir()
    (base / "brief.txt").write_text("txt body", encoding="utf-8")
    (base / "brief.pdf").write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(ui, "_extract_pdf", lambda p: "pdf body")
    manifest = {"version": 1, "files": {}}
    res = ui.run_intake(root, vault, manifest=manifest, config=CONFIG)

    notes = sorted(res.added)
    assert notes == ["coursework/bit216/brief-2.md", "coursework/bit216/brief.md"]
    assert (vault / "coursework" / "bit216" / "brief.md").exists()
    assert (vault / "coursework" / "bit216" / "brief-2.md").exists()
    man_notes = {v["note"] for v in manifest["files"].values()}
    assert man_notes == {"coursework/bit216/brief.md", "coursework/bit216/brief-2.md"}

    # Second run: same source -> same note path, no renumbering, no rewrites.
    before = {k: v["note"] for k, v in manifest["files"].items()}
    res2 = ui.run_intake(root, vault, manifest=manifest, config=CONFIG)
    assert res2.added == [] and res2.updated == []
    assert {k: v["note"] for k, v in manifest["files"].items()} == before


def test_second_run_does_not_rehash(tmp_path, monkeypatch):
    root, vault = tmp_path / "U", tmp_path / "V"
    _tree(root); vault.mkdir()
    manifest = {"version": 1, "files": {}}
    ui.run_intake(root, vault, manifest=manifest, config=CONFIG)
    # Every manifest entry now carries a stat cache.
    assert all("size" in v and "mtime" in v for v in manifest["files"].values())

    def boom(p):
        raise AssertionError("file_hash must not run for an untouched tree")

    monkeypatch.setattr(ui, "file_hash", boom)
    res = ui.run_intake(root, vault, manifest=manifest, config=CONFIG)
    assert res.added == [] and res.updated == [] and res.errors == []
    assert res.skipped >= 2


def test_empty_walk_with_history_keeps_manifest(tmp_path):
    root, vault = tmp_path / "U", tmp_path / "V"
    root.mkdir(); vault.mkdir()          # exists, but nothing parseable inside
    note = vault / "coursework" / "bit216" / "gone.md"
    note.parent.mkdir(parents=True); note.write_text("kept", encoding="utf-8")
    manifest = {"version": 1, "files": {
        "University/Uni Assignments/Degree/Sem 2/BIT216/gone.txt": {
            "hash": "x", "mtime": 1.0, "size": 4, "note": "coursework/bit216/gone.md"},
    }}
    res = ui.run_intake(root, vault, manifest=manifest, config=CONFIG)
    assert "University/Uni Assignments/Degree/Sem 2/BIT216/gone.txt" in manifest["files"]
    moc = (vault / "coursework" / "_moc.md").read_text(encoding="utf-8")
    assert "## Orphaned" not in moc
    assert res.added == [] and res.updated == []


def test_corrupt_pdf_records_one_error_and_continues(tmp_path, monkeypatch):
    root, vault = tmp_path / "U", tmp_path / "V"
    base = _course(root); vault.mkdir()
    (base / "slides.pdf").write_bytes(b"%PDF-1.4 broken")
    (base / "brief.txt").write_text("Assignment brief body.", encoding="utf-8")

    def boom(p):
        raise RuntimeError("bang")

    monkeypatch.setattr(ui, "_extract_pdf", boom)
    manifest = {"version": 1, "files": {}}
    res = ui.run_intake(root, vault, manifest=manifest, config=CONFIG)
    assert len(res.errors) == 1
    assert "slides.pdf" in res.errors[0] and "extract failed" in res.errors[0]
    assert (vault / "coursework" / "bit216" / "slides.md").exists()
    assert "coursework/bit216/brief.md" in res.added   # walk continued


def test_per_tick_cap_splits_backfill_across_runs(tmp_path):
    root, vault = tmp_path / "U", tmp_path / "V"
    base = _course(root); vault.mkdir()
    for i in range(5):
        (base / f"a{i:02d}.txt").write_text(f"body {i}", encoding="utf-8")
    cfg = dict(CONFIG, university_intake_max_files_per_tick=3)
    manifest = {"version": 1, "files": {}}
    res = ui.run_intake(root, vault, manifest=manifest, config=cfg)
    assert len(res.added) == 3 and res.partial is True
    res2 = ui.run_intake(root, vault, manifest=manifest, config=cfg)
    assert len(res2.added) == 2 and res2.partial is False
    assert len(manifest["files"]) == 5


def test_slug_collision_earlier_sorting_sibling_does_not_clobber(tmp_path, monkeypatch):
    # brief.pdf sorts before brief.txt: the pre-seeded claim map must protect
    # the already-ingested brief.txt note from the later-added PDF.
    root, vault = tmp_path / "U", tmp_path / "V"
    base = _course(root); vault.mkdir()
    (base / "brief.txt").write_text("TXT DERIVED NOTE BODY", encoding="utf-8")
    monkeypatch.setattr(ui, "_extract_pdf", lambda p: "PDF DERIVED NOTE BODY")
    manifest = {"version": 1, "files": {}}
    ui.run_intake(root, vault, manifest=manifest, config=CONFIG)
    brief_md = vault / "coursework" / "bit216" / "brief.md"
    assert "TXT DERIVED NOTE BODY" in brief_md.read_text(encoding="utf-8")

    (base / "brief.pdf").write_bytes(b"%PDF-1.4")
    res = ui.run_intake(root, vault, manifest=manifest, config=CONFIG)
    assert res.added == ["coursework/bit216/brief-2.md"]
    assert "TXT DERIVED NOTE BODY" in brief_md.read_text(encoding="utf-8")   # untouched
    assert "PDF DERIVED NOTE BODY" in (
        vault / "coursework" / "bit216" / "brief-2.md").read_text(encoding="utf-8")
    man_notes = sorted(v["note"] for v in manifest["files"].values())
    assert man_notes == ["coursework/bit216/brief-2.md", "coursework/bit216/brief.md"]
    moc = (vault / "coursework" / "_moc.md").read_text(encoding="utf-8")
    assert "[[bit216]] — 2 note(s)" in moc

    res3 = ui.run_intake(root, vault, manifest=manifest, config=CONFIG)
    assert res3.added == [] and res3.updated == []


def test_per_file_mode_writes_course_hub_note_that_resolves_links(tmp_path):
    # Every per-file note carries a bare [[bit216]] link; without a real
    # coursework/bit216.md note that link resolves to nothing and the vault
    # graph shows the note as an orphan.
    root, vault = tmp_path / "U", tmp_path / "V"
    _tree(root); vault.mkdir()
    ui.run_intake(root, vault, manifest={"version": 1, "files": {}}, config=CONFIG)
    hub = vault / "coursework" / "bit216.md"
    assert hub.exists()
    body = hub.read_text(encoding="utf-8")
    assert "type: coursework-hub" in body
    assert "course: BIT216" in body
    assert "[[coursework/bit216/brief]]" in body
    # The other course gets its own hub too.
    assert "[[coursework/fec100/lab1]]" in (vault / "coursework" / "fec100.md").read_text(encoding="utf-8")


def test_course_hub_note_regenerates_as_notes_come_and_go(tmp_path):
    root, vault = tmp_path / "U", tmp_path / "V"
    base = _course(root); vault.mkdir()
    (base / "a.txt").write_text("body a", encoding="utf-8")
    manifest = {"version": 1, "files": {}}
    ui.run_intake(root, vault, manifest=manifest, config=CONFIG)
    hub = vault / "coursework" / "bit216.md"
    assert "[[coursework/bit216/a]]" in hub.read_text(encoding="utf-8")

    (base / "b.txt").write_text("body b", encoding="utf-8")
    ui.run_intake(root, vault, manifest=manifest, config=CONFIG)
    body = hub.read_text(encoding="utf-8")
    assert "[[coursework/bit216/a]]" in body
    assert "[[coursework/bit216/b]]" in body


def test_rollup_mode_does_not_clobber_course_note_with_a_hub(tmp_path):
    root, vault = tmp_path / "U", tmp_path / "V"
    _tree(root); vault.mkdir()
    cfg = dict(CONFIG, university_intake_mode="rollup")
    ui.run_intake(root, vault, manifest={"version": 1, "files": {}}, config=cfg)
    body = (vault / "coursework" / "bit216.md").read_text(encoding="utf-8")
    assert "type: coursework-hub" not in body   # real rollup content, not a hub stub
    assert body.lstrip().startswith("## ")


def test_deadlines_capped_at_20_per_run(tmp_path):
    root, vault = tmp_path / "U", tmp_path / "V"
    base = _course(root); vault.mkdir()
    for i in range(25):
        (base / f"asg{i:02d}.txt").write_text(
            "Submission due 15/10/2026 via Turnitin.", encoding="utf-8")
    manifest = {"version": 1, "files": {}}
    res = ui.run_intake(root, vault, manifest=manifest, config=CONFIG)
    assert len(res.deadlines) == 20
