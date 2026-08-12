"""voice/static/orb.html's :root color tokens must meet WCAG AA contrast
(>=4.5:1) against --bg -- regression pin for the low-contrast text colors
(#4a4d58, #404068, #3d3d6a, etc.) this redesign replaces. Parses the raw
CSS text; no browser involved."""
from __future__ import annotations

import re
from pathlib import Path

ORB_HTML = Path(__file__).resolve().parents[1] / "voice" / "static" / "orb.html"


def _read_root_tokens() -> dict[str, str]:
    css = ORB_HTML.read_text(encoding="utf-8")
    root_block = re.search(r":root\s*\{(.*?)\n  \}", css, re.S)
    assert root_block, "could not find :root block in orb.html"
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6});", root_block.group(1)))


def _relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def linearize(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = linearize(r), linearize(g), linearize(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(hex_a: str, hex_b: str) -> float:
    l1, l2 = _relative_luminance(hex_a), _relative_luminance(hex_b)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def test_text_tiers_meet_wcag_aa_against_background():
    tokens = _read_root_tokens()
    bg = tokens["bg"]
    for tier in ("text", "text-dim", "text-faint"):
        ratio = _contrast_ratio(tokens[tier], bg)
        assert ratio >= 4.5, f"--{tier} ({tokens[tier]}) is only {ratio:.2f}:1 against --bg ({bg})"
