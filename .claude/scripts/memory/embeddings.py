"""FastEmbed wrapper. Lazy-loads the ONNX model once per process.

Model: sentence-transformers/all-MiniLM-L6-v2 (384-dim, ~80 MB).
Cached under .claude/data/fastembed-cache/ so repeated runs don't re-download.

Windows note: FastEmbed first tries the HuggingFace Hub cache, which uses
symlinks. On Windows without Developer Mode that fails with WinError 1314,
leaves a half-populated snapshot behind, and FastEmbed loses ~6 s before
falling back to its own tarball cache. The tarball cache works fine. Once
the tarball exists we wipe the HF cache and set HF_HUB_OFFLINE=1 so future
runs skip the Hub round trip entirely.
"""
from __future__ import annotations

import os
import shutil
import struct
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
CACHE_DIR = PROJECT_DIR / ".claude" / "data" / "fastembed-cache"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

_TARBALL_DIR = CACHE_DIR / "fast-all-MiniLM-L6-v2"
_TARBALL_MARKER = _TARBALL_DIR / "model.onnx"
_HF_DIR = CACHE_DIR / "models--qdrant--all-MiniLM-L6-v2-onnx"

_model = None


def get_model():
    global _model
    if _model is None:
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if _TARBALL_MARKER.exists():
            # Tarball cache is complete and known to work on Windows; the HF
            # Hub cache cannot be (symlinks fail). Wipe any HF cache state
            # unconditionally — completeness heuristics caught the wrong
            # missing files in practice.
            if _HF_DIR.exists():
                shutil.rmtree(_HF_DIR, ignore_errors=True)
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
        from fastembed import TextEmbedding
        _model = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(CACHE_DIR))
    return _model


def embed(texts: list[str]) -> list[list[float]]:
    """Batch-embed a list of strings into 384-dim float vectors."""
    if not texts:
        return []
    model = get_model()
    return [list(map(float, vec)) for vec in model.embed(texts)]


def embed_one(text: str) -> list[float]:
    return embed([text])[0]


def vec_to_blob(vec: list[float]) -> bytes:
    """Pack a float vector as little-endian f32 — the format vec0 stores natively."""
    return struct.pack(f"<{len(vec)}f", *vec)
