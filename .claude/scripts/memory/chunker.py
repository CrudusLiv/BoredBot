"""Markdown-aware chunker.

Strategy: split first by markdown headings (each heading section is a unit),
then size-cap each section to ~400 tokens with paragraph-aware breaks and a
~50-token sliding overlap so chunks straddling a boundary don't lose context.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

CHARS_PER_TOKEN = 4
TARGET_TOKENS = 400
TARGET_CHARS = TARGET_TOKENS * CHARS_PER_TOKEN
OVERLAP_CHARS = 200

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class Chunk:
    heading: str
    content: str


def split_by_headings(text: str) -> list[tuple[str, str]]:
    """Return (heading, body) pairs. Heading is the most recent ATX heading text."""
    sections: list[tuple[str, str]] = []
    cur_heading = ""
    cur_body: list[str] = []
    for line in text.split("\n"):
        m = HEADING_RE.match(line)
        if m:
            body = "\n".join(cur_body).strip()
            if body:
                sections.append((cur_heading, body))
            cur_heading = m.group(2).strip()
            cur_body = []
        else:
            cur_body.append(line)
    body = "\n".join(cur_body).strip()
    if body:
        sections.append((cur_heading, body))
    return sections


def split_by_size(text: str, target: int = TARGET_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """Sliding-window split. Prefers paragraph boundaries for break points."""
    if len(text) <= target:
        return [text] if text.strip() else []
    out: list[str] = []
    pos = 0
    n = len(text)
    while pos < n:
        end = min(pos + target, n)
        if end < n:
            para = text.rfind("\n\n", pos + target // 2, end)
            if para > 0:
                end = para
        chunk = text[pos:end].strip()
        if chunk:
            out.append(chunk)
        if end >= n:
            break
        pos = max(end - overlap, pos + 1)
    return out


def chunk_markdown(text: str) -> list[Chunk]:
    sections = split_by_headings(text) or [("", text)]
    chunks: list[Chunk] = []
    for heading, body in sections:
        for piece in split_by_size(body):
            chunks.append(Chunk(heading=heading, content=piece))
    return chunks
