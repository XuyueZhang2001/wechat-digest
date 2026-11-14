"""在本地语料里检索与事件相关的文章。

刻意不用 FTS5：中文分词在 SQLite 里是个坑，而个人使用的数据量（几万篇以内）
直接扫描 + 打分完全够，且行为可解释、可调试。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import Event
from .store import Store


@dataclass
class Candidate:
    row: sqlite3.Row
    score: float
    matched: list[str]


def _age_days(ts: str, now: datetime) -> float:
    try:
        dt = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return 999.0
    return max(0.0, (now - dt).total_seconds() / 86400.0)


def retrieve(store: Store, event: Event, limit: int = 40,
             min_score: float = 0.6) -> list[Candidate]:
    since, until = event.range_iso()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    keyword_sets = event.sets()
    weights = store.source_weights()

    hits: list[Candidate] = []
    for row in store.iter_articles(since, until):
        if row["dup_of"]:
            continue
        title = row["title"] or ""
        body = row["body"] or ""
        text_cf = f"{title}\n{body}".casefold()
        title_cf = title.casefold()

        # 多套条件之间取「或」：任意一套完整命中即可，取分最高的一套。
        best_score: float | None = None
        best_matched: list[str] = []
        for groups in keyword_sets:
            matched_local: list[str] = []
            score_local = 0.0
            ok = True
            for group in groups:
                group_hits = [term for term in group if term and term.casefold() in text_cf]
                if not group_hits:
                    ok = False
                    break
                matched_local.extend(group_hits)
                for term in group_hits:
                    term_cf = term.casefold()
                    if term_cf in title_cf:
                        score_local += 3.0
                    score_local += min(text_cf.count(term_cf), 5) * 0.4
            if ok and (best_score is None or score_local > best_score):
                best_score = score_local
                best_matched = matched_local

        if best_score is None:
            continue
        score = best_score
        matched = best_matched

        age = _age_days(row["published_at"], now)
        score += max(0.0, 1.0 - age / max(event.window_days, 1)) * 0.8
        score *= weights.get(row["source_id"], 1.0)

        hits.append(Candidate(row=row, score=score, matched=sorted(set(matched))))

    hits.sort(key=lambda h: h.score, reverse=True)
    return [h for h in hits if h.score >= min_score][:limit]
