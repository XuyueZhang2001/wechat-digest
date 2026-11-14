"""读取信源清单与事件定义。

配置统一用 TOML，因为 Python 3.11+ 标准库自带 tomllib，项目可以零依赖运行。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass
class Source:
    id: str
    name: str
    feed: str = ""
    weight: float = 1.0
    angle: str = ""
    enabled: bool = True
    kind: str = "rss"          # rss | dataxapi
    account: str = ""          # 付费 API 用：公众号名称或 gh_ 编号


@dataclass
class Event:
    name: str
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    keyword_groups: list[list[str]] = field(default_factory=list)
    keyword_sets: list[list[list[str]]] = field(default_factory=list)
    window_days: int = 180
    date_from: str = ""
    date_to: str = ""
    notes: str = ""

    def groups(self) -> list[list[str]]:
        """每个内层列表都至少要命中一个词，才认为文章与该事件相关。"""
        groups = [g for g in self.keyword_groups if g]
        if not groups:
            groups = [[self.name, *self.aliases]]
        return groups

    def sets(self) -> list[list[list[str]]]:
        """多套条件之间是「或」：命中任意一套即可。

        每套内部仍是「每组至少命中一个词」。
        典型用法是给同一个事件的不同问题框架各写一套：
        黄仁勋+离职、黄仁勋+继任、英伟达+继任。
        """
        cleaned = [[g for g in group_set if g] for group_set in self.keyword_sets]
        cleaned = [group_set for group_set in cleaned if group_set]
        if cleaned:
            return cleaned
        return [self.groups()]

    def all_terms(self) -> list[str]:
        terms: list[str] = []
        for group in self.groups():
            terms.extend(group)
        return list(dict.fromkeys(t for t in terms if t))

    def range_iso(self) -> tuple[str, str]:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        start = self.date_from or (now - timedelta(days=self.window_days)).strftime("%Y-%m-%d")
        end = self.date_to or (now + timedelta(days=1)).strftime("%Y-%m-%d")
        return f"{start}T00:00:00", f"{end}T23:59:59"


def load_sources(path: str | Path) -> list[Source]:
    path = Path(path)
    data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    rows = data.get("sources", [])
    if not isinstance(rows, list):
        raise ValueError(f"{path}: [[sources]] 必须是数组表")

    sources: list[Source] = []
    seen: set[str] = set()
    for i, row in enumerate(rows, 1):
        sid = str(row.get("id", "")).strip()
        name = str(row.get("name", "")).strip()
        if not sid or not name:
            raise ValueError(f"{path}: 第 {i} 个信源缺少 id 或 name")
        if sid in seen:
            raise ValueError(f"{path}: 信源 id 重复：{sid}")
        seen.add(sid)
        kind = str(row.get("kind", "rss")).strip() or "rss"
        if kind not in {"rss", "dataxapi"}:
            raise ValueError(f"{path}: 信源 {sid} 的 kind 只能是 rss 或 dataxapi")
        sources.append(
            Source(
                id=sid,
                name=name,
                feed=str(row.get("feed", "")).strip(),
                weight=float(row.get("weight", 1.0)),
                angle=str(row.get("angle", "")).strip(),
                enabled=bool(row.get("enabled", True)),
                kind=kind,
                account=str(row.get("account", "")).strip(),
            )
        )
    return sources


def load_event(path: str | Path) -> Event:
    path = Path(path)
    data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    name = str(data.get("name", "")).strip()
    if not name:
        raise ValueError(f"{path}: 缺少 name")

    groups = data.get("keyword_groups", []) or []
    if groups and not all(isinstance(g, list) for g in groups):
        raise ValueError(f"{path}: keyword_groups 必须是二维数组")

    sets_raw = data.get("keyword_sets", []) or []
    if sets_raw and not all(
        isinstance(s, list) and all(isinstance(g, list) for g in s) for s in sets_raw
    ):
        raise ValueError(f"{path}: keyword_sets 必须是三维数组")

    return Event(
        name=name,
        description=str(data.get("description", "")).strip(),
        aliases=[str(a) for a in data.get("aliases", [])],
        keyword_groups=[[str(t) for t in g] for g in groups],
        keyword_sets=[[[str(t) for t in g] for g in s] for s in sets_raw],
        window_days=int(data.get("window_days", 180)),
        date_from=str(data.get("date_from", "")).strip(),
        date_to=str(data.get("date_to", "")).strip(),
        notes=str(data.get("notes", "")).strip(),
    )
