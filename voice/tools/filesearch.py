"""Read-only machine-wide file search: find files by name, grep file
contents. No confirmation gate (like list_windows) — nothing is written.

Scope is limited to filesearch_roots in voice/config.py; filesearch_denylist
keeps secrets (.env, ssh keys, credential stores) out of both the walk and
the results. search_files shells out to ripgrep when it's on PATH and falls
back to a bounded pure-Python scan otherwise.
"""
from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
from pathlib import Path

import voice  # noqa: F401

_MAX_FILE_BYTES = 2_000_000
_MAX_OUTPUT_CHARS = 6000
_MAX_RESULTS = 50
_LINE_CLIP = 200
_RG_TIMEOUT_S = 20


def _roots() -> list[Path]:
    """Resolved, existing directories the search may descend into. An empty
    filesearch_roots falls back to a default set; a non-empty list replaces
    it entirely."""
    from voice import config as cfg
    configured = cfg.load().get("filesearch_roots", []) or []
    if configured:
        raw = [Path(p) for p in configured]
    else:
        home = Path.home()
        raw = [home / "Desktop", home / "Documents", home / "Downloads",
               Path("D:/GitHub"), Path("D:/University")]
    out: list[Path] = []
    for p in raw:
        try:
            rp = p.expanduser().resolve()
        except OSError:
            continue
        if rp.is_dir() and rp not in out:
            out.append(rp)
    return out


def _denylist() -> list[str]:
    """Filename / path-segment globs that are never scanned or returned."""
    from voice import config as cfg
    return cfg.load().get("filesearch_denylist", []) or []


def _denied(rel: Path, patterns: list[str]) -> bool:
    """True if the filename or any segment of `rel` (a path *relative to its
    search root*) matches a denylist glob, case-insensitively."""
    name = rel.name.lower()
    segs = [s.lower() for s in rel.parts]
    for pat in patterns:
        p = pat.lower()
        if fnmatch.fnmatch(name, p) or any(fnmatch.fnmatch(s, p) for s in segs):
            return True
    return False


def _cap(text: str) -> str:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    return text[:_MAX_OUTPUT_CHARS].rstrip() + "\n… (truncated)"


def _walk(roots, patterns):
    """Yield (absolute_path, filename) for every non-denylisted file under the
    roots, pruning denylisted directories as it descends."""
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = Path(dirpath).relative_to(root)
            dirnames[:] = [d for d in dirnames if not _denied(rel_dir / d, patterns)]
            for fn in filenames:
                if not _denied(rel_dir / fn, patterns):
                    yield root / rel_dir / fn, fn


def find_files(name_glob: str, limit: int = _MAX_RESULTS) -> str:
    """Find files whose name matches `name_glob` (case-insensitive) across the
    configured search roots. Args: name_glob(str, e.g. "*.pdf", "resume*"),
    limit(int)."""
    roots = _roots()
    if not roots:
        return "no search roots configured or none exist"
    patterns = _denylist()
    limit = max(1, min(int(limit), _MAX_RESULTS))
    needle = name_glob.lower()
    hits: list[str] = []
    for fp, fn in _walk(roots, patterns):
        if fnmatch.fnmatch(fn.lower(), needle):
            hits.append(str(fp))
            if len(hits) >= limit:
                return "\n".join(hits)
    return "\n".join(hits) if hits else f"no files matching {name_glob!r}"


def search_files(query: str, path_glob: str = "*", limit: int = _MAX_RESULTS) -> str:
    """Search file *contents* for `query` across the configured search roots,
    restricted to files whose name matches `path_glob`. Returns
    "path:line: text" lines. Args: query(str), path_glob(str), limit(int)."""
    roots = _roots()
    if not roots:
        return "no search roots configured or none exist"
    patterns = _denylist()
    limit = max(1, min(int(limit), _MAX_RESULTS))
    rg = shutil.which("rg")
    lines = (
        _rg_search(rg, roots, query, path_glob, limit, patterns) if rg
        else _py_search(roots, query, path_glob, limit, patterns)
    )
    if not lines:
        return f"no matches for {query!r}"
    return _cap("\n".join(lines[:limit]))


def _rg_search(rg, roots, query, path_glob, limit, patterns) -> list[str]:
    # Run once per root with cwd=root so rg prints root-relative paths — no
    # Windows drive-letter colon to confuse "path:line:text" parsing, and the
    # denylist check sees only segments below the root.
    out: list[str] = []
    for root in roots:
        cmd = [
            rg, "--line-number", "--no-heading", "--color=never",
            "--max-filesize", str(_MAX_FILE_BYTES),
            "--glob", path_glob, "--fixed-strings", "-e", query, ".",
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=_RG_TIMEOUT_S,
                encoding="utf-8", errors="replace", cwd=str(root),
            )
        except (OSError, subprocess.SubprocessError):
            return _py_search(roots, query, path_glob, limit, patterns)
        for raw in proc.stdout.splitlines():
            parts = raw.split(":", 2)
            if len(parts) < 3:
                continue
            rel_str, lineno, text = parts
            rel = Path(rel_str)
            if _denied(rel, patterns):
                continue
            out.append(f"{root / rel}:{lineno}: {text.strip()[:_LINE_CLIP]}")
            if len(out) >= limit:
                return out
    return out


def _py_search(roots, query, path_glob, limit, patterns) -> list[str]:
    needle = query.lower()
    glob = path_glob.lower()
    out: list[str] = []
    for fp, fn in _walk(roots, patterns):
        if not fnmatch.fnmatch(fn.lower(), glob):
            continue
        try:
            if fp.stat().st_size > _MAX_FILE_BYTES:
                continue
            data = fp.read_bytes()
        except OSError:
            continue
        if b"\x00" in data[:1024]:
            continue
        text = data.decode("utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), start=1):
            if needle in line.lower():
                out.append(f"{fp}:{i}: {line.strip()[:_LINE_CLIP]}")
                if len(out) >= limit:
                    return out
    return out
