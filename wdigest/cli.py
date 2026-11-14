"""命令行入口。"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .config import load_event, load_sources
from .dataxapi import DataXAPI
from .demo import purge, seed
from .env import load_dotenv
from .llm import LLM
from .pipeline import analyze, dump_json, ingest, write_report
from .store import Store


def _safe_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - 老终端不支持就算了
        pass


def cmd_ingest(args) -> int:
    sources = load_sources(args.sources)
    store = Store(args.db)
    enabled = [source for source in sources if source.enabled]
    print(f"开始抓取 {len(enabled)} 个信源（配置共 {len(sources)} 个）……")
    client = DataXAPI()
    summary = ingest(sources, store, timeout=args.timeout,
                     api_client=client, api_pages=args.pages)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["api_calls"]:
        print(f"付费接口调用 {summary['api_calls']} 次，花费 ${summary['spent']:.4f}")
    if summary["skipped"]:
        print(f"\n{len(summary['skipped'])} 个信源未配置，已跳过。")
    if summary["failed"]:
        print("\n有信源失败，检查 feed 地址、账号编号或网络。")
    store.close()
    return 0


def cmd_seed(args) -> int:
    store = Store(args.db)
    counts = seed(store, reset=args.reset)
    store.close()
    print("演示数据写入结果：" + json.dumps(counts, ensure_ascii=False))
    print("下一步：python run.py run --event events/huang-renxun-lizhi.toml")
    return 0


def cmd_purge(args) -> int:
    store = Store(args.db)
    removed = purge(store)
    store.close()
    print(f"已删除 {removed} 篇演示文章。")
    return 0


def cmd_run(args) -> int:
    event = load_event(args.event)
    store = Store(args.db)
    sources = load_sources(args.sources) if Path(args.sources).exists() else []
    if not sources:
        print(f"提示：未找到 {args.sources}，报告中的覆盖表将只包含实际命中的信源。")

    llm = LLM()
    if args.no_llm:
        llm.api_key = ""

    client = DataXAPI()
    bundle = analyze(store, event, llm, top_n=args.top,
                     api_client=client, enrich_top=args.enrich_top,
                     min_score=args.min_score, max_cost=args.max_cost)
    path = write_report(bundle, sources, out_dir=args.out)
    if args.dump_json:
        dump_json(bundle, path)

    print(f"\n报告：{path.resolve()}")
    print(f"命中 {len(bundle.candidates)} 篇，分析 {len(bundle.extracts)} 篇。")
    if client.calls:
        print(f"付费接口调用 {client.calls} 次，花费 ${client.spent:.4f}")
    store.close()
    return 0


def cmd_sources(args) -> int:
    store = Store(args.db)
    stats = store.stats()
    print(f"文章总数：{stats['total']}，近重复：{stats['near_duplicate']}")
    if stats["by_source"]:
        print("\n| 信源 | 篇数 | 最近一篇 |")
        print("| --- | --- | --- |")
        for row in stats["by_source"]:
            print(f"| {row['source_name']} | {row['n']} | {(row['latest'] or '')[:10]} |")
    store.close()
    return 0


def cmd_init(args) -> int:
    root = Path(__file__).resolve().parent.parent
    pairs = [
        ("sources.example.toml", "sources.toml"),
        (".env.example", ".env"),
    ]
    for example, target in pairs:
        source = root / example
        dest = root / target
        if dest.exists():
            print(f"{target} 已存在，跳过")
            continue
        shutil.copyfile(source, dest)
        print(f"已生成 {target}")
    print("\n下一步：编辑 .env 填模型 Key，编辑 sources.toml 填 feed 或公众号，然后 python run.py serve")
    return 0


def cmd_serve(args) -> int:
    from .server import serve

    serve(port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wechat-digest",
        description="汇总固定信源对某个事件的看法。",
    )
    parser.add_argument("--db", default="data/wdigest.db", help="SQLite 路径")
    parser.add_argument("--sources", default="sources.toml", help="信源配置")

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser("ingest", help="抓取所有已配置的信源")
    p_ingest.add_argument("--timeout", type=int, default=30)
    p_ingest.add_argument("--pages", type=int, default=1, help="付费 API 每个号翻几页列表")
    p_ingest.set_defaults(func=cmd_ingest)

    p_seed = sub.add_parser("seed-demo", help="写入合成演示数据")
    p_seed.add_argument("--reset", action="store_true", help="先清空旧的演示数据")
    p_seed.set_defaults(func=cmd_seed)

    p_purge = sub.add_parser("purge-demo", help="删除所有演示数据")
    p_purge.set_defaults(func=cmd_purge)

    p_run = sub.add_parser("run", help="检索、抽取、汇总并生成报告")
    p_run.add_argument("--event", required=True, help="事件 TOML 路径")
    p_run.add_argument("--top", type=int, default=40, help="最多分析多少篇")
    p_run.add_argument("--enrich-top", type=int, default=6,
                       help="最多为多少篇候选补全文（付费接口按篇计费）")
    p_run.add_argument("--min-score", type=float, default=0.6,
                       help="低于这个检索得分的文章不进入分析，默认 0.6")
    p_run.add_argument("--max-cost", type=float, default=0.0,
                       help="本次补全文的美元上限，0 表示不封顶")
    p_run.add_argument("--no-llm", action="store_true", help="只检索，不调用模型")
    p_run.add_argument("--out", default="reports", help="报告输出目录")
    p_run.add_argument("--dump-json", action="store_true", help="同时输出结构化 JSON")
    p_run.set_defaults(func=cmd_run)

    p_sources = sub.add_parser("sources", help="查看库里的信源与文章量")
    p_sources.set_defaults(func=cmd_sources)

    p_serve = sub.add_parser("serve", help="启动本地网页界面")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.set_defaults(func=cmd_serve)

    p_init = sub.add_parser("init", help="从示例生成 sources.toml 和 .env")
    p_init.set_defaults(func=cmd_init)

    return parser


def main(argv: list[str] | None = None) -> int:
    _safe_stdout()
    load_dotenv()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
