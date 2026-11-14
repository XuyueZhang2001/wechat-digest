"""跨源汇总：把逐篇抽取出的判断合并成共识、分歧、独家与待核事项。"""

from __future__ import annotations

import json

from . import prompts
from .config import Event
from .llm import LLM

MAX_CLAIMS = 120


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _sources(value, known: set[str]) -> list[str]:
    out: list[str] = []
    for item in _as_list(value):
        name = str(item).strip()
        if name in known and name not in out:
            out.append(name)
    return out


def _text(value, limit: int = 400) -> str:
    return str(value or "").strip()[:limit]


def collect_claims(extracts: list[dict]) -> list[dict]:
    claims: list[dict] = []
    for item in extracts:
        if not item.get("relevant"):
            continue
        for claim in item.get("claims", []):
            claims.append(
                {
                    "i": len(claims),
                    "source": item["source"],
                    "title": item["title"],
                    "date": item.get("date", ""),
                    "claim": claim["text"],
                    "type": claim["type"],
                }
            )
            if len(claims) >= MAX_CLAIMS:
                return claims
    return claims


def normalize(data: dict, known: set[str]) -> dict:
    single_source = len(known) <= 1

    consensus = []
    for item in _as_list(data.get("consensus")):
        if not isinstance(item, dict) or not _text(item.get("point")):
            continue
        sources = _sources(item.get("sources"), known)
        if len(sources) < 2:
            # 共识必须是两个及以上独立信源，单源不算。
            continue
        consensus.append(
            {
                "point": _text(item.get("point"), 200),
                "sources": sources,
                "evidence": _text(item.get("evidence"), 300),
            }
        )

    disagreements = []
    for item in _as_list(data.get("disagreements")):
        if not isinstance(item, dict) or not _text(item.get("question")):
            continue
        positions = []
        for pos in _as_list(item.get("positions")):
            if not isinstance(pos, dict) or not _text(pos.get("view")):
                continue
            positions.append(
                {
                    "view": _text(pos.get("view"), 200),
                    "sources": _sources(pos.get("sources"), known),
                    "evidence": _text(pos.get("evidence"), 300),
                }
            )
        if len(positions) >= 2:
            disagreements.append(
                {"question": _text(item.get("question"), 200), "positions": positions}
            )

    unique = []
    for item in _as_list(data.get("unique")):
        if not isinstance(item, dict) or not _text(item.get("point")):
            continue
        unique.append(
            {
                "point": _text(item.get("point"), 200),
                "source": _text(item.get("source"), 60),
                "why": _text(item.get("why"), 200),
            }
        )
    if single_source:
        unique = unique[:5]

    forecasts = []
    for item in _as_list(data.get("forecasts")):
        if not isinstance(item, dict) or not _text(item.get("claim")):
            continue
        forecasts.append(
            {
                "claim": _text(item.get("claim"), 200),
                "source": _text(item.get("source"), 60),
                "basis": _text(item.get("basis"), 200),
            }
        )

    fact_checks = []
    for item in _as_list(data.get("fact_checks")):
        if not isinstance(item, dict) or not _text(item.get("issue")):
            continue
        fact_checks.append(
            {
                "issue": _text(item.get("issue"), 200),
                "sources": _sources(item.get("sources"), known),
                "detail": _text(item.get("detail"), 300),
            }
        )

    return {
        "tldr": [_text(x, 160) for x in _as_list(data.get("tldr")) if _text(x)][:5],
        "consensus": consensus,
        "disagreements": disagreements,
        "unique": unique,
        "forecasts": forecasts,
        "fact_checks": fact_checks,
        "gap_note": _text(data.get("gap_note"), 400),
        "single_source": single_source,
    }


def synthesize(llm: LLM, event: Event, extracts: list[dict], log=print) -> dict | None:
    claims = collect_claims(extracts)
    if not claims:
        return None

    known = {item["source"] for item in extracts if item.get("relevant")}
    log(f"  汇总 {len(claims)} 条判断，来自 {len(known)} 个信源")
    user = prompts.render(
        "synth.user",
        {
            "event_name": event.name,
            "event_desc": event.description or "（无）",
            "source_list": "、".join(sorted(known)),
            "claims": json.dumps(claims, ensure_ascii=False, indent=1),
        },
    )
    data = llm.json(prompts.load("synth.system"), user, max_tokens=4000)
    return normalize(data, known)
