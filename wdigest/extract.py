"""逐篇抽取：把一篇文章拆成若干条可独立理解、可回链的判断。"""

from __future__ import annotations

import json
import re

from . import prompts
from .config import Event
from .llm import LLM, LLMError

CLAIM_TYPES = {"事实", "解释", "预测", "观点", "亲历"}
MAX_CLAIMS = 8
BODY_LIMIT = 6000


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def build_prompt(event: Event, row) -> str:
    body = row["body"] or ""
    if len(body) > BODY_LIMIT:
        body = body[:BODY_LIMIT] + "\n……（后文已截断）"
    return prompts.render(
        "extract.user",
        {
            "event_name": event.name,
            "event_desc": event.description or "（无）",
            "source": row["source_name"],
            "title": row["title"],
            "date": (row["published_at"] or "")[:10],
            "body": body,
        },
    )


def normalize(data: dict, row) -> dict:
    body_norm = _squash(row["body"] or "")
    claims: list[dict] = []
    for item in data.get("claims") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        quote = str(item.get("quote", "")).strip()[:300]
        claim_type = str(item.get("type", "观点")).strip()
        claims.append(
            {
                "text": text[:300],
                "type": claim_type if claim_type in CLAIM_TYPES else "观点",
                "evidence": str(item.get("evidence", "")).strip()[:300],
                "quote": quote,
                "quote_verified": bool(quote) and _squash(quote) in body_norm,
            }
        )
        if len(claims) >= MAX_CLAIMS:
            break

    try:
        relevance = float(data.get("relevance", 0.0))
    except (TypeError, ValueError):
        relevance = 0.0

    return {
        "article_id": row["id"],
        "source": row["source_name"],
        "title": row["title"],
        "url": row["url"],
        "date": (row["published_at"] or "")[:10],
        "relevance": max(0.0, min(1.0, relevance)),
        "relevant": bool(data.get("relevant", relevance >= 0.3)),
        "summary": str(data.get("summary", "")).strip()[:400],
        "angle": str(data.get("angle", "")).strip()[:40],
        "claims": claims,
        "open_questions": [str(q).strip()[:200] for q in (data.get("open_questions") or [])][:5],
        "error": "",
    }


def extract_one(llm: LLM, event: Event, row) -> dict:
    system = prompts.load("extract.system")
    try:
        data = llm.json(system, build_prompt(event, row))
    except LLMError as exc:
        return {
            "article_id": row["id"],
            "source": row["source_name"],
            "title": row["title"],
            "url": row["url"],
            "date": (row["published_at"] or "")[:10],
            "relevance": 0.0,
            "relevant": False,
            "summary": "",
            "angle": "",
            "claims": [],
            "open_questions": [],
            "error": str(exc),
        }
    return normalize(data, row)


def extract_all(llm: LLM, event: Event, candidates, limit: int | None = None,
                log=print) -> list[dict]:
    results: list[dict] = []
    items = candidates[: limit or len(candidates)]
    for index, candidate in enumerate(items, 1):
        row = candidate.row
        log(f"  [{index}/{len(items)}] {row['source_name']} · {row['title'][:40]}")
        results.append(extract_one(llm, event, row))
    return results


def to_json(results: list[dict]) -> str:
    return json.dumps(results, ensure_ascii=False, indent=2)
