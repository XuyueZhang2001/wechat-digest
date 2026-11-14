"""把报告用的 Markdown 子集渲染成 HTML。

只处理本项目自己生成的语法：标题、列表、表格、引用、details、粗体、链接。
"""

from __future__ import annotations

import html
import re

_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BULLET = re.compile(r"^[-*]\s+")
_ORDERED = re.compile(r"^\d+\.\s+")


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = _LINK.sub(
        r'<a href="\2" target="_blank" rel="noopener">\1</a>', text
    )
    return text


def _table(rows: list[str]) -> str:
    if len(rows) < 2:
        return ""
    header = [cell.strip() for cell in rows[0].strip().strip("|").split("|")]
    body_rows = rows[2:]
    out = ["<table><thead><tr>"]
    out.extend(f"<th>{_inline(cell)}</th>" for cell in header)
    out.append("</tr></thead><tbody>")
    for row in body_rows:
        cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
        out.append("<tr>")
        out.extend(f"<td>{_inline(cell)}</td>" for cell in cells)
        out.append("</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def render(markdown: str) -> str:
    lines = markdown.splitlines()
    out: list[str] = []
    i = 0
    list_tag: str | None = None

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            close_list()
            i += 1
            continue

        if stripped.startswith("<details") or stripped.startswith("</details") or stripped.startswith("<summary"):
            close_list()
            out.append(stripped)
            i += 1
            continue

        if stripped.startswith("|"):
            close_list()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_table(rows))
            continue

        if stripped.startswith("#"):
            close_list()
            level = len(stripped) - len(stripped.lstrip("#"))
            out.append(f"<h{level}>{_inline(stripped[level:].strip())}</h{level}>")
            i += 1
            continue

        if stripped == "---":
            close_list()
            out.append("<hr/>")
            i += 1
            continue

        if stripped.startswith(">"):
            close_list()
            out.append(f"<blockquote>{_inline(stripped[1:].strip())}</blockquote>")
            i += 1
            continue

        if _BULLET.match(stripped):
            if list_tag != "ul":
                close_list()
                out.append("<ul>")
                list_tag = "ul"
            out.append(f"<li>{_inline(_BULLET.sub('', stripped))}</li>")
            i += 1
            continue

        if _ORDERED.match(stripped):
            if list_tag != "ol":
                close_list()
                out.append("<ol>")
                list_tag = "ol"
            out.append(f"<li>{_inline(_ORDERED.sub('', stripped))}</li>")
            i += 1
            continue

        close_list()
        out.append(f"<p>{_inline(stripped)}</p>")
        i += 1

    close_list()
    return "\n".join(out)
