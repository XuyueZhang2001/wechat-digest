"""把信源与事件写回 TOML。只覆盖本项目用到的结构。

注意：整文件重写，手工注释不会保留。
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import Event, Source


def _s(value) -> str:
    """JSON 字符串转义与 TOML 基本字符串兼容。"""
    return json.dumps(str(value), ensure_ascii=False)


def dump_sources(sources: list[Source], path: str | Path) -> None:
    lines = [
        "# 由界面写入。手工修改可以，但界面保存时会整体重写，注释不保留。",
        "",
    ]
    for source in sources:
        lines.extend(
            [
                "[[sources]]",
                f"id = {_s(source.id)}",
                f"name = {_s(source.name)}",
                f"kind = {_s(source.kind)}",
                f"feed = {_s(source.feed)}",
                f"account = {_s(source.account)}",
                f"weight = {source.weight:.2f}",
                f"angle = {_s(source.angle)}",
                f"enabled = {'true' if source.enabled else 'false'}",
                "",
            ]
        )
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def dump_event(event: Event, path: str | Path) -> None:
    lines = [
        "# 由界面写入。",
        "",
        f"name = {_s(event.name)}",
        f"description = {_s(event.description)}",
    ]
    if event.aliases:
        lines.append("aliases = [" + ", ".join(_s(a) for a in event.aliases) + "]")
    lines.append(f"window_days = {event.window_days}")
    if event.date_from:
        lines.append(f"date_from = {_s(event.date_from)}")
    if event.date_to:
        lines.append(f"date_to = {_s(event.date_to)}")
    lines.append("")
    lines.append("keyword_sets = [")
    for group_set in event.sets():
        lines.append("  [")
        for group in group_set:
            lines.append("    [" + ", ".join(_s(term) for term in group) + "],")
        lines.append("  ],")
    lines.append("]")
    if event.notes:
        note = event.notes.replace('"""', "'''")
        lines.extend(["", f'notes = """', note, '"""'])
    lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")
