"""把分析结果渲染成 Markdown 报告。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from .config import Event, Source


@dataclass
class Bundle:
    event: Event
    candidates: list
    extracts: list[dict] = field(default_factory=list)
    synthesis: dict | None = None
    llm_enabled: bool = False
    llm_error: str = ""
    demo: bool = False
    scanned: int = 0


def _cell(value, limit: int = 60) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().replace("|", "\\|")
    return text if len(text) <= limit else text[:limit] + "…"


def _plain(value, limit: int = 60) -> str:
    """非表格位置用，不转义竖线。"""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _src(names: list[str]) -> str:
    return "、".join(names) if names else "—"


def _is_configured(source: Source) -> bool:
    if source.kind == "dataxapi":
        return bool(source.account)
    return bool(source.feed)


def _bullets(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items] if items else ["- （无）"]


def render(bundle: Bundle, sources: list[Source]) -> str:
    event = bundle.event
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: list[str] = []

    lines.append(f"# 事件：{event.name}")
    lines.append("")
    if bundle.demo:
        lines.append("> **演示数据**：报告中包含由 `seed-demo` 生成的虚构信源文章，"
                     "仅用于验证流程，不是真实报道，也不代表任何真实媒体的观点。")
        lines.append("")
    enabled = [source for source in sources if source.enabled]
    missing = [source for source in enabled if not _is_configured(source)]
    header = (
        f"> 生成时间 {now} ｜ 命中文章 {len(bundle.candidates)} 篇 ｜ "
        f"已分析 {len(bundle.extracts)} 篇 ｜ 配置信源 {len(sources)} 个，启用 {len(enabled)} 个"
    )
    if missing:
        header += f"（{len(missing)} 个未配置）"
    lines.append(header)
    if not bundle.llm_enabled:
        lines.append("")
        lines.append("> ⚠️ 未检测到 LLM API Key，本次仅输出检索结果，未做判断抽取与汇总。")
    if bundle.llm_error:
        lines.append("")
        lines.append(f"> ⚠️ LLM 调用出错：{bundle.llm_error}")
    lines.append("")

    synthesis = bundle.synthesis

    # 一、结论摘要
    lines.append("## 一、结论摘要")
    lines.append("")
    if synthesis and synthesis.get("tldr"):
        lines.extend(_bullets(synthesis["tldr"]))
    elif synthesis:
        lines.append("- 信源之间未形成可归纳的共识，详见下节分歧与逐篇摘要。")
    elif bundle.candidates:
        lines.append(f"- 在指定时间窗内，信源中共命中 {len(bundle.candidates)} 篇文章。")
        lines.append("- 尚未启用汇总（需要 LLM），当前只完成检索。")
    else:
        lines.append(f"- 时间窗内共检索 {bundle.scanned} 篇文章，没有一篇同时命中两组关键词。")
        lines.append("- 这不等于信源没有观点：可能是该事件不在它们的选题范围内，"
                     "也可能 feed 只保留最近 20 篇、事件发生在窗口之外。")
        lines.append("- 建议先核对「覆盖情况」和文章日期，再决定是放宽时间窗、补信源，还是调整关键词。")

    if len(bundle.candidates) >= 2:
        lines.append("")
        lines.append("### 时间线")
        lines.append("")
        ordered = sorted(bundle.candidates, key=lambda c: c.row["published_at"] or "")
        for candidate in ordered:
            row = candidate.row
            lines.append(
                f"- {(row['published_at'] or '')[:10]} · "
                f"{_plain(row['title'], 56)}（{_plain(row['source_name'], 12)}）"
            )
    lines.append("")

    # 二、共识
    lines.append("## 二、共识")
    lines.append("")
    consensus = synthesis.get("consensus", []) if synthesis else []
    if synthesis and synthesis.get("single_source"):
        lines.append("_本次只有一个信源覆盖该事件，因此不存在跨源共识。该信源的完整判断见第九节。_")
        lines.append("")
    elif not consensus:
        lines.append("_没有多个信源共同支持的判断。_")
        lines.append("")
    else:
        for i, item in enumerate(consensus, 1):
            lines.append(f"### {i}. {item['point']}")
            lines.append("")
            lines.append(f"来源：{_src(item['sources'])}")
            if item.get("evidence"):
                lines.append("")
                lines.append(f"依据：{item['evidence']}")
            lines.append("")

    # 三、分歧
    lines.append("## 三、分歧")
    lines.append("")
    disagreements = synthesis.get("disagreements", []) if synthesis else []
    if not disagreements:
        lines.append("_未识别出信源之间的实质性分歧。_")
        lines.append("")
    else:
        for i, item in enumerate(disagreements, 1):
            lines.append(f"### {i}. {item['question']}")
            lines.append("")
            for pos in item["positions"]:
                lines.append(f"- **{pos['view']}**（来源：{_src(pos['sources'])}）")
                if pos.get("evidence"):
                    lines.append(f"  - 依据：{pos['evidence']}")
            lines.append("")

    # 四、独家信息
    lines.append("## 四、独家信息与独特视角")
    lines.append("")
    unique = synthesis.get("unique", []) if synthesis else []
    if synthesis and synthesis.get("single_source") and unique:
        lines.append("> 单源覆盖，以下信息无法交叉验证。")
        lines.append("")
    if not unique:
        lines.append("_无。_")
    else:
        for item in unique:
            suffix = f"—— {item['why']}" if item.get("why") else ""
            lines.append(f"- **{item['point']}**（{item['source']}）{suffix}")
    lines.append("")

    # 五、预判
    lines.append("## 五、预判")
    lines.append("")
    forecasts = synthesis.get("forecasts", []) if synthesis else []
    if not forecasts:
        lines.append("_无。_")
        lines.append("")
    else:
        lines.append("| 预判 | 信源 | 依据 |")
        lines.append("| --- | --- | --- |")
        for item in forecasts:
            lines.append(
                f"| {_cell(item['claim'], 80)} | {_cell(item['source'], 20)} | {_cell(item['basis'], 60)} |"
            )
        lines.append("")

    # 六、待核实
    lines.append("## 六、待核实")
    lines.append("")
    checks = synthesis.get("fact_checks", []) if synthesis else []
    if not checks:
        lines.append("_未发现互相矛盾、需要回查原始来源的说法。_")
        lines.append("")
    else:
        for item in checks:
            lines.append(f"- **{item['issue']}**（{_src(item['sources'])}）")
            if item.get("detail"):
                lines.append(f"  - {item['detail']}")
        lines.append("")

    # 七、覆盖情况
    lines.append("## 七、覆盖情况")
    lines.append("")
    counts: dict[str, int] = {}
    if bundle.extracts:
        for item in bundle.extracts:
            if item.get("relevant"):
                counts[item["source"]] = counts.get(item["source"], 0) + 1
    else:
        for candidate in bundle.candidates:
            name = candidate.row["source_name"]
            counts[name] = counts.get(name, 0) + 1
    lines.append("| 信源 | 命中篇数 | 状态 |")
    lines.append("| --- | --- | --- |")
    enabled_map = {source.name: source.enabled for source in sources}
    configured_map = {source.name: _is_configured(source) for source in sources}
    names = [source.name for source in sources]
    if bundle.demo:
        names = [name for name in names if counts.get(name)]
    for item in bundle.extracts:
        if item["source"] not in names:
            names.append(item["source"])
    for candidate in bundle.candidates:
        if candidate.row["source_name"] not in names:
            names.append(candidate.row["source_name"])
    for name in names:
        n = counts.get(name, 0)
        if not configured_map.get(name, True):
            status = "未配置"
        elif enabled_map.get(name) is False:
            status = "未启用"
        elif n:
            status = "已覆盖"
        else:
            status = "未命中"
        lines.append(f"| {_cell(name, 20)} | {n} | {status} |")
    lines.append("")
    if synthesis and synthesis.get("gap_note"):
        lines.append(f"> {synthesis['gap_note']}")
        lines.append("")

    # 八、文章清单
    lines.append("## 八、文章清单")
    lines.append("")
    if not bundle.candidates:
        lines.append("_没有命中任何文章。_")
        lines.append("")
    else:
        lines.append("| # | 信源 | 标题 | 日期 | 得分 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for i, cand in enumerate(bundle.candidates, 1):
            row = cand.row
            title = _cell(row["title"], 44)
            if row["url"]:
                title = f"[{title}]({row['url']})"
            lines.append(
                f"| {i} | {_cell(row['source_name'], 16)} | {title} | "
                f"{(row['published_at'] or '')[:10]} | {cand.score:.1f} |"
            )
        lines.append("")

    # 九、逐篇摘要
    lines.append("## 九、逐篇摘要")
    lines.append("")
    if not bundle.extracts:
        lines.append("_尚未抽取（需要 LLM）。_")
        lines.append("")
    else:
        for item in bundle.extracts:
            lines.append("<details>")
            summary = f"<summary>{_plain(item['source'], 20)} · {_plain(item['title'], 50)}"
            if not item.get("relevant"):
                summary += "（判定为不相关）"
            summary += "</summary>"
            lines.append(summary)
            lines.append("")
            if item.get("error"):
                lines.append(f"抽取失败：{item['error']}")
            else:
                lines.append(f"- 角度：{item.get('angle') or '—'}")
                lines.append(f"- 摘要：{item.get('summary') or '—'}")
                if item.get("claims"):
                    lines.append("- 判断：")
                    for claim in item["claims"]:
                        mark = "" if claim["quote_verified"] else " ⚠️"
                        line = f"  - [{claim['type']}] {claim['text']}{mark}"
                        if claim.get("evidence"):
                            line += f"（依据：{claim['evidence']}）"
                        lines.append(line)
                        if claim.get("quote"):
                            lines.append(f"    > {claim['quote']}")
                if item.get("open_questions"):
                    lines.append(f"- 留下的问题：{'；'.join(item['open_questions'])}")
            lines.append("")
            lines.append("</details>")
            lines.append("")

    # 方法与边界
    lines.append("---")
    lines.append("")
    lines.append("**方法与边界**")
    lines.append("")
    lines.append("- 本报告只汇总信源明确表达的内容，不含程序自身的判断。")
    lines.append("- 每条判断附原文引文；标 ⚠️ 表示引文未能在正文中逐字匹配，需人工核对。")
    lines.append("- 未被任何信源提及的角度不会出现在报告中，请结合「覆盖情况」判断盲区。")
    lines.append("- 「未命中」不等于该信源没有观点，也可能是 RSS 未抓到、或文章超出时间窗。")
    lines.append("")

    return "\n".join(lines)
