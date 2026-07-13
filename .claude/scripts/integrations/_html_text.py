"""Shared HTML -> plain-text conversion for mail-body rendering.

Block tags become newlines, <a href> URLs are kept inline as
`anchor text <url>` so digest parsers (e.g. job-alert scanning) can
find links."""
from __future__ import annotations

from html.parser import HTMLParser

_BLOCK_TAGS = {"p", "div", "br", "tr", "li", "td", "h1", "h2", "h3", "h4", "table"}


class _HtmlText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out: list[str] = []
        self._skip = 0
        self._href = ""

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag in _BLOCK_TAGS:
            self.out.append('\n')
        if tag == "a":
            self._href = dict(attrs).get("href") or ""

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag == "a" and self._href:
            self.out.append(f" <{self._href}>")
            self._href = ""
        if tag in _BLOCK_TAGS:
            self.out.append('\n')

    def handle_data(self, data):
        if not self._skip:
            self.out.append(data)


def html_to_text(html: str) -> str:
    p = _HtmlText()
    try:
        p.feed(html)
        p.close()
    except Exception:
        return html
    lines = (ln.strip() for ln in "".join(p.out).splitlines())
    return '\n'.join(ln for ln in lines if ln)