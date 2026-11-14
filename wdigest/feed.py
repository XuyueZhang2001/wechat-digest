"""RSS 2.0 / Atom 解析 + 简单正文清洗。

不依赖 feedparser：公众号 RSS 桥输出的格式很规矩，标准库足够。
"""

from __future__ import annotations

import email.utils
import html as html_lib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser

ATOM = "http://www.w3.org/2005/Atom"
CONTENT = "http://purl.org/rss/1.0/modules/content/"
DC = "http://purl.org/dc/elements/1.1/"


@dataclass
class FeedItem:
    title: str
    link: str
    guid: str
    published: datetime | None
    author: str
    content_html: str


class _TextExtractor(HTMLParser):
    """把 HTML 变成带段落换行的纯文本，丢掉脚本、样式和标签。"""

    _BLOCK = {
        "p", "div", "br", "li", "tr", "section", "article", "blockquote",
        "h1", "h2", "h3", "h4", "h5", "h6", "pre", "figure", "hr",
    }
    _SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BLOCK:
            self._out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self._BLOCK:
            self._out.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._out.append(data)

    def text(self) -> str:
        return "".join(self._out)


def html_to_text(raw: str) -> str:
    if not raw:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(raw)
        parser.close()
        text = parser.text()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw)
    text = html_lib.unescape(text).replace("\u00a0", " ").replace("\u3000", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    text = "\n".join(ln for ln in lines if ln)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _text(node: ET.Element, tag: str) -> str:
    found = node.find(tag)
    if found is None or found.text is None:
        return ""
    return found.text.strip()


def _parse_date(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        pass
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


def _parse_rss(root: ET.Element) -> list[FeedItem]:
    channel = root.find("channel")
    if channel is None:
        return []
    items: list[FeedItem] = []
    for node in channel.findall("item"):
        link = _text(node, "link") or _text(node, "guid")
        body = _text(node, f"{{{CONTENT}}}encoded") or _text(node, "description")
        items.append(
            FeedItem(
                title=_text(node, "title"),
                link=link,
                guid=_text(node, "guid") or link,
                published=_parse_date(_text(node, "pubDate")),
                author=_text(node, "author") or _text(node, f"{{{DC}}}creator"),
                content_html=body,
            )
        )
    return items


def _parse_atom(root: ET.Element) -> list[FeedItem]:
    items: list[FeedItem] = []
    for node in root.findall(f"{{{ATOM}}}entry"):
        link = ""
        for candidate in node.findall(f"{{{ATOM}}}link"):
            href = candidate.get("href", "")
            if candidate.get("rel", "alternate") == "alternate" and href:
                link = href
                break
            link = link or href
        author_node = node.find(f"{{{ATOM}}}author")
        author = ""
        if author_node is not None:
            author = _text(author_node, f"{{{ATOM}}}name")
        body = _text(node, f"{{{ATOM}}}content") or _text(node, f"{{{ATOM}}}summary")
        items.append(
            FeedItem(
                title=_text(node, f"{{{ATOM}}}title"),
                link=link,
                guid=_text(node, f"{{{ATOM}}}id") or link,
                published=_parse_date(
                    _text(node, f"{{{ATOM}}}published") or _text(node, f"{{{ATOM}}}updated")
                ),
                author=author,
                content_html=body,
            )
        )
    return items


def parse_feed(raw: bytes | str) -> list[FeedItem]:
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    root = ET.fromstring(raw)
    tag = root.tag.lower()
    if tag.endswith("rss") or root.find("channel") is not None:
        return _parse_rss(root)
    return _parse_atom(root)
