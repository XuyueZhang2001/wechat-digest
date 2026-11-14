"""用模型把一句话题描述变成可检索的关键词组。"""

from __future__ import annotations

from . import prompts
from .llm import LLM

MAX_SETS = 4
MAX_GROUPS = 3
MAX_TERMS = 10


def _clean_terms(values) -> list[str]:
    terms: list[str] = []
    for value in values or []:
        term = str(value).strip()
        if not (2 <= len(term) <= 20):
            continue
        if term in terms:
            continue
        terms.append(term)
        if len(terms) >= MAX_TERMS:
            break
    return terms


def _dedupe(items, limit: int = 12) -> list[str]:
    out: list[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
        if len(out) >= limit:
            break
    return out


def normalize(data: dict) -> dict:
    sets: list[list[list[str]]] = []
    for raw_set in data.get("sets") or []:
        # 模型可能返回 [[...]] 或 [{"groups": [...]}]，两种都接受。
        if isinstance(raw_set, dict):
            raw_groups = raw_set.get("groups")
        else:
            raw_groups = raw_set
        if not isinstance(raw_groups, list):
            continue
        groups: list[list[str]] = []
        for raw_group in raw_groups:
            terms = _clean_terms(raw_group if isinstance(raw_group, list) else [])
            if terms:
                groups.append(terms)
        if len(groups) >= 2:
            sets.append(groups[:MAX_GROUPS])
        if len(sets) >= MAX_SETS:
            break
    if not sets:
        raise ValueError("模型没有生成有效的关键词组，请补一句更具体的话题说明")

    # 简单框只展示第一套（最核心的）条件，完整多套仍写进高级框。
    subjects = _dedupe(list(sets[0][0]))
    angles = _dedupe([term for group in sets[0][1:] for term in group])
    return {"sets": sets, "subject": subjects, "angle": angles}


def suggest_keywords(llm: LLM, name: str, description: str) -> dict:
    system = prompts.load("keywords.system")
    user = f"话题：{name}\n说明：{description or '（无）'}"
    data = llm.json(system, user, max_tokens=1200)
    return normalize(data)
