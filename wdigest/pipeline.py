"""串起采集、检索、抽取、汇总、出报告的流程。"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .config import Event, Source
from .dataxapi import DataXAPI, DataXAPIError
from .extract import extract_all
from .feed import html_to_text, parse_feed
from .llm import LLM
from .report import Bundle, render
from .retrieve import retrieve
from .store import Store
from .synth import synthesize

USER_AGENT = "Mozilla/5.0 (compatible; wechat-digest/0.1; personal research)"
DETAIL_PRICE = 0.02  # DataXAPI 每篇正文的价格，用于成本预估与封顶


def pick_for_enrichment(candidates, limit: int):
    """按信源轮转挑选，保证每个信源都能分到名额，而不是被高分的一家占满。"""
    buckets: dict[str, list] = {}
    for candidate in candidates:
        buckets.setdefault(candidate.row["source_name"], []).append(candidate)
    for items in buckets.values():
        items.sort(key=lambda c: c.score, reverse=True)

    picked: list = []
    rank = 0
    while len(picked) < limit:
        added = False
        for items in buckets.values():
            if rank < len(items):
                picked.append(items[rank])
                added = True
                if len(picked) >= limit:
                    break
        if not added:
            break
        rank += 1
    return picked


def _read_feed(feed: str, timeout: int = 30) -> bytes:
    if feed.lower().startswith(("http://", "https://")):
        request = urllib.request.Request(
            feed,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    return Path(feed).read_bytes()


def _iso_utc(value) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)[:19]
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")


def _resolve_account(source: Source, store: Store, client: DataXAPI, log=print) -> str:
    cached = store.get_account_id(source.id)
    if cached:
        return cached

    account = source.account or source.name
    if account.startswith("gh_") or account.isdigit():
        store.set_account_id(source.id, account)
        return account

    items = client.search_account(account)
    if not items:
        raise DataXAPIError("not_found", f"搜不到公众号：{account}")
    picked = next((item for item in items if item.get("name") == account), items[0])
    account_id = str(picked.get("id") or "")
    if not account_id:
        raise DataXAPIError("not_found", f"搜到「{account}」但没有编号")
    store.set_account_id(source.id, account_id)
    log(f"  「{source.name}」对应编号 {account_id}（{picked.get('name')}）")
    return account_id


def ingest_api(source: Source, store: Store, client: DataXAPI, pages: int = 1,
               log=print) -> dict:
    """列表只存摘要桩，正文等命中事件时再补，避免为每篇都付费。"""
    store.upsert_source(
        source.id, source.name, source.feed, source.weight, source.angle, True
    )
    account_id = _resolve_account(source, store, client, log=log)
    items = client.list_articles(account_id, pages=pages)

    counts = {"fetched": len(items), "inserted": 0, "duplicate": 0}
    for item in items:
        title = (item.get("title") or "（无标题）").strip()
        summary = (item.get("text") or "").strip()
        author = ((item.get("author") or {}).get("name") or "").strip()
        status = store.add_article(
            source_id=source.id,
            source_name=source.name,
            title=title,
            url=item.get("url") or "",
            author=author,
            published_at=_iso_utc(item.get("published_at")),
            body=summary,
            fulltext=False,
        )
        counts[status] = counts.get(status, 0) + 1

    log(f"  「{source.name}」列表 {len(items)} 条，新增 {counts['inserted']} 条")
    return counts


def ingest(sources: list[Source], store: Store, timeout: int = 30,
           api_client: DataXAPI | None = None, api_pages: int = 1,
           log=print) -> dict:
    summary = {
        "sources": 0,
        "inserted": 0,
        "duplicate": 0,
        "near_duplicate": 0,
        "empty": 0,
        "failed": [],
        "skipped": [],
        "api_calls": 0,
        "spent": 0.0,
    }

    removed = store.cleanup_duplicates()
    if removed:
        log(f"  清理重复摘要 {removed} 条")

    for source in sources:
        if not source.enabled:
            continue

        if source.kind == "dataxapi":
            if api_client is None or not api_client.enabled:
                log(f"  跳过「{source.name}」：未配置 DATAXAPI_API_KEY")
                summary["skipped"].append(
                    {"source": source.name, "reason": "未配置 DATAXAPI_API_KEY"}
                )
                continue
            try:
                counts = ingest_api(source, store, api_client, pages=api_pages, log=log)
            except DataXAPIError as exc:
                log(f"  失败「{source.name}」：{exc}")
                summary["failed"].append({"source": source.name, "error": str(exc)})
                continue
            summary["sources"] += 1
            summary["inserted"] += counts["inserted"]
            summary["duplicate"] += counts["duplicate"]
            continue

        if not source.feed:
            log(f"  跳过「{source.name}」：未配置 feed 地址")
            summary["skipped"].append({"source": source.name, "reason": "未配置 feed"})
            continue

        try:
            raw = _read_feed(source.feed, timeout=timeout)
            items = parse_feed(raw)
        except Exception as exc:  # noqa: BLE001 - 单个源失败不应中断整体
            log(f"  失败「{source.name}」：{exc}")
            summary["failed"].append({"source": source.name, "error": str(exc)})
            continue

        store.upsert_source(
            source.id, source.name, source.feed, source.weight, source.angle, source.enabled
        )
        summary["sources"] += 1
        for item in items:
            body = html_to_text(item.content_html)
            if not body:
                summary["empty"] += 1
                continue
            published = (
                item.published.strftime("%Y-%m-%dT%H:%M:%S") if item.published else ""
            )
            status = store.add_article(
                source_id=source.id,
                source_name=source.name,
                title=item.title or "（无标题）",
                url=item.link,
                author=item.author,
                published_at=published,
                body=body,
            )
            summary[status] = summary.get(status, 0) + 1

        log(f"  「{source.name}」解析 {len(items)} 条")

    if api_client is not None:
        summary["api_calls"] = api_client.calls
        summary["spent"] = round(api_client.spent, 4)
    return summary


def enrich_articles(store: Store, candidates, client: DataXAPI, limit: int = 10,
                    max_cost: float = 0.0, log=print) -> int:
    """给摘要桩补全文，只对进入候选的文章付费。"""
    done = 0
    for candidate in candidates[:limit]:
        row = candidate.row
        if row["fulltext"] or not row["url"]:
            continue
        if max_cost and client.spent + DETAIL_PRICE > max_cost + 1e-9:
            log(f"  达到成本上限 ${max_cost:.2f}，停止补全文")
            break
        try:
            item = client.get_article(row["url"])
        except DataXAPIError as exc:
            log(f"  补全文失败：{row['title'][:30]}（{exc.code}）")
            continue
        body = (item.get("text") or "").strip()
        if not body:
            continue
        store.update_content(
            row["id"],
            body,
            title=item.get("title"),
            published_at=_iso_utc(item.get("published_at")),
            author=((item.get("author") or {}).get("name") or None),
        )
        done += 1
        log(f"  补全文 {done} · {row['source_name']} · {(item.get('title') or row['title'])[:34]}")
    return done


def analyze(store: Store, event: Event, llm: LLM, top_n: int = 40,
            api_client: DataXAPI | None = None, enrich_top: int = 6,
            min_score: float = 0.6, max_cost: float = 0.0,
            log=print) -> Bundle:
    log(f"检索事件「{event.name}」……")
    candidates = retrieve(store, event, limit=top_n, min_score=min_score)
    log(f"命中 {len(candidates)} 篇")

    bundle = Bundle(event=event, candidates=candidates, llm_enabled=llm.enabled)
    since, until = event.range_iso()
    bundle.scanned = sum(1 for _ in store.iter_articles(since, until))

    if not candidates or not llm.enabled:
        return bundle

    if api_client is not None and api_client.enabled:
        pending = [item for item in candidates if not item.row["fulltext"]]
        if pending:
            picked = pick_for_enrichment(pending, enrich_top)
            estimate = len(picked) * DETAIL_PRICE
            log(f"补全全文 {len(picked)} 篇，预计 ${estimate:.2f}"
                + (f"（上限 ${max_cost:.2f}）" if max_cost else ""))
            enrich_articles(store, picked, api_client, limit=len(picked),
                            max_cost=max_cost, log=log)
            candidates = retrieve(store, event, limit=top_n, min_score=min_score)
            bundle.candidates = candidates

    log("逐篇抽取判断……")
    try:
        bundle.extracts = extract_all(llm, event, candidates, log=log)
        log("跨源汇总……")
        bundle.synthesis = synthesize(llm, event, bundle.extracts, log=log)
    except Exception as exc:  # noqa: BLE001 - 失败时仍输出检索结果
        bundle.llm_error = str(exc)
        log(f"  LLM 阶段出错：{exc}")

    return bundle


def write_report(bundle: Bundle, sources: list[Source], out_dir: str = "reports") -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r'[\\/:*?"<>|\s]+', "-", bundle.event.name).strip("-")[:60] or "report"
    path = out / f"{stamp}-{safe}.md"
    path.write_text(render(bundle, sources), encoding="utf-8")
    return path


def dump_json(bundle: Bundle, report_path: Path) -> Path:
    path = report_path.with_suffix(".json")
    payload = {
        "event": bundle.event.name,
        "candidates": [
            {
                "source": c.row["source_name"],
                "title": c.row["title"],
                "url": c.row["url"],
                "published_at": c.row["published_at"],
                "score": round(c.score, 2),
                "matched": c.matched,
                "fulltext": bool(c.row["fulltext"]),
            }
            for c in bundle.candidates
        ],
        "extracts": bundle.extracts,
        "synthesis": bundle.synthesis,
        "llm_error": bundle.llm_error,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
