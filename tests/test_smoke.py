"""冒烟测试：不联网、不需要 API key。

运行：python tests/test_smoke.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wdigest.config import Event, Source, load_event, load_sources  # noqa: E402
from wdigest.demo import seed  # noqa: E402
from wdigest.feed import html_to_text, parse_feed  # noqa: E402
from wdigest.pipeline import analyze, enrich_articles, ingest_api  # noqa: E402
from wdigest.report import render  # noqa: E402
from wdigest.retrieve import retrieve  # noqa: E402
from wdigest.store import Store, hamming, simhash  # noqa: E402


class FakeLLM:
    """模拟模型，返回固定结构，用来验证整条链路。"""

    enabled = True

    def json(self, system: str, user: str, max_tokens: int = 3000) -> dict:
        if "研究综述编辑" in system:
            return {
                "tldr": ["交接早有准备", "短期路线不变"],
                "consensus": [
                    {
                        "point": "短期产品与技术路线不会改变",
                        "sources": ["示例信源·技术观察"],
                        "evidence": "测试依据",
                    }
                ],
                "disagreements": [
                    {
                        "question": "是否需要重估估值",
                        "positions": [
                            {"view": "会明显折价", "sources": ["示例信源·商业分析"], "evidence": "测试"},
                            {"view": "基本面不依赖个人", "sources": ["示例信源·商业分析"], "evidence": "测试"},
                        ],
                    }
                ],
                "unique": [
                    {"point": "客户要求改由新管理层签约", "source": "示例信源·供应链", "why": "独家信号"}
                ],
                "forecasts": [
                    {"claim": "明年一季度见分晓", "source": "示例信源·供应链", "basis": "客户框架协议"}
                ],
                "fact_checks": [
                    {"issue": "估值缩水幅度不一致", "sources": ["示例信源·商业分析"], "detail": "三成"}
                ],
                "gap_note": "",
            }

        body = user.split("正文：", 1)[-1].strip()
        snippet = body.splitlines()[0][:30]
        return {
            "relevant": True,
            "relevance": 0.9,
            "summary": "这是一条测试摘要。",
            "angle": "技术",
            "claims": [
                {
                    "text": "这是一条测试判断",
                    "type": "解释",
                    "evidence": "测试依据",
                    "quote": snippet,
                },
                {
                    "text": "引文不存在时应被标记",
                    "type": "观点",
                    "evidence": "",
                    "quote": "这句话肯定不在正文里",
                },
            ],
            "open_questions": ["测试问题"],
        }


def test_feed_parser() -> None:
    raw = (ROOT / "tests/fixtures/sample_feed.xml").read_bytes()
    items = parse_feed(raw)
    assert len(items) == 2, items
    assert items[0].title == "测试文章一"
    assert items[0].author == "作者甲"
    assert items[0].published is not None and items[0].published.year == 2026
    text = html_to_text(items[0].content_html)
    assert "黄仁勋卸任" in text
    assert "should be dropped" not in text
    assert "<p>" not in text
    assert items[1].published is not None


def test_simhash() -> None:
    a = simhash("英伟达宣布黄仁勋卸任，董事会已完成交接安排。")
    b = simhash("英伟达宣布黄仁勋卸任，董事会已完成交接安排。")
    c = simhash("今天天气不错，适合出门散步和晒太阳。")
    assert hamming(a, b) == 0
    assert hamming(a, c) > 3


def test_dedup(store: Store) -> None:
    payload = dict(
        source_id="t",
        source_name="测试源",
        title="标题",
        url="https://example.com/x",
        author="",
        published_at="2026-11-12T10:00:00",
        body="完全相同的正文内容，用于测试去重逻辑。" * 5,
    )
    assert store.add_article(**payload) == "inserted"
    assert store.add_article(**payload) == "duplicate"


def test_retrieval(store: Store, event: Event) -> None:
    candidates = retrieve(store, event, limit=40)
    titles = [c.row["title"] for c in candidates]
    assert len(candidates) == 5, titles
    assert not any("GTC" in t for t in titles), titles
    assert not any("加速卡" in t for t in titles), titles


def test_end_to_end(store: Store, event: Event, sources) -> None:
    bundle = analyze(store, event, FakeLLM(), top_n=40, log=lambda *_: None)
    assert len(bundle.extracts) == 5
    verdicts = [
        claim["quote_verified"]
        for item in bundle.extracts
        for claim in item["claims"]
        if claim["text"] == "这是一条测试判断"
    ]
    assert verdicts and all(verdicts), verdicts
    flagged = [
        claim["quote_verified"]
        for item in bundle.extracts
        for claim in item["claims"]
        if claim["text"] == "引文不存在时应被标记"
    ]
    assert flagged and not any(flagged), flagged

    assert bundle.synthesis is not None
    report = render(bundle, sources)
    for section in ["## 一、结论摘要", "## 二、共识", "## 三、分歧", "## 七、覆盖情况"]:
        assert section in report, section
    assert "测试摘要" in report
    assert "⚠️" in report


def test_coverage_without_llm(store: Store, event: Event, sources) -> None:
    from wdigest.report import Bundle

    candidates = retrieve(store, event, limit=40)
    bundle = Bundle(event=event, candidates=candidates, llm_enabled=False)
    markdown = render(bundle, sources)
    assert "| 示例信源·技术观察 | 2 | 已覆盖 |" in markdown, markdown
    assert "未检测到 LLM API Key" in markdown


class FakeDataXAPI:
    """模拟付费接口：列表给摘要，详情给全文。"""

    enabled = True

    def __init__(self) -> None:
        self.calls = 0
        self.spent = 0.0

    def _charge(self) -> None:
        self.calls += 1
        self.spent += 0.02

    def search_account(self, query: str) -> list[dict]:
        self._charge()
        return [{"id": "gh_test", "name": query}]

    def list_articles(self, account_id: str, pages: int = 1) -> list[dict]:
        self._charge()
        return [
            {
                "id": "1",
                "url": "https://mp.weixin.qq.com/s/a",
                "title": "黄仁勋卸任后，英伟达的接班人问题",
                "text": "这是摘要，不是全文。",
                "published_at": "2026-11-12T10:00:00.000Z",
                "author": {"name": "晚点LatePost"},
            },
            {
                "id": "2",
                "url": "https://mp.weixin.qq.com/s/b",
                "title": "与事件无关的文章",
                "text": "无关摘要。",
                "published_at": "2026-11-11T10:00:00.000Z",
                "author": {"name": "晚点LatePost"},
            },
        ]

    def get_article(self, url: str) -> dict:
        self._charge()
        return {
            "title": "黄仁勋卸任后，英伟达的接班人问题",
            "text": "正文第一段。" * 20 + "黄仁勋卸任，英伟达进入新阶段。",
            "published_at": "2026-11-12T10:00:00.000Z",
            "author": {"name": "晚点LatePost"},
        }


def test_paid_api(store: Store, event: Event) -> None:
    client = FakeDataXAPI()
    source = Source(
        id="latepost",
        name="晚点LatePost",
        kind="dataxapi",
        account="晚点LatePost",
        enabled=True,
    )
    counts = ingest_api(source, store, client, pages=1, log=lambda *_: None)
    assert counts["inserted"] == 2, counts
    assert client.calls == 2, client.calls  # 搜号 + 列表

    stub = store.conn.execute(
        "SELECT id, fulltext, body FROM articles WHERE source_id = 'latepost' AND title LIKE '黄仁勋%'"
    ).fetchone()
    assert stub is not None
    assert stub["fulltext"] == 0
    assert "这是摘要" in stub["body"]

    candidates = retrieve(store, event, limit=20)
    candidate = next(c for c in candidates if c.row["id"] == stub["id"])
    assert enrich_articles(store, [candidate], client, limit=5, log=lambda *_: None) == 1
    assert client.calls == 3

    updated = store.conn.execute(
        "SELECT body, fulltext FROM articles WHERE id = ?", (stub["id"],)
    ).fetchone()
    assert updated["fulltext"] == 1
    assert "黄仁勋卸任，英伟达进入新阶段" in updated["body"]


def test_pick_for_enrichment() -> None:
    from wdigest.pipeline import pick_for_enrichment

    class Candidate:
        def __init__(self, source: str, score: float) -> None:
            self.row = {"source_name": source}
            self.score = score

    candidates = [
        Candidate("36氪", 9.0),
        Candidate("36氪", 8.0),
        Candidate("36氪", 7.0),
        Candidate("虎嗅", 6.0),
        Candidate("虎嗅", 5.0),
    ]
    picked = pick_for_enrichment(candidates, 4)
    assert [c.row["source_name"] for c in picked] == ["36氪", "虎嗅", "36氪", "虎嗅"]
    assert len(pick_for_enrichment(candidates, 10)) == 5


def test_markdown_render() -> None:
    from wdigest.markdown import render

    html = render(
        "# 标题\n\n- 一\n- 二\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n"
        "**粗** [链](https://example.com)"
    )
    for needle in [
        "<h1>标题</h1>",
        "<li>一</li>",
        "<table>",
        "<td>1</td>",
        "<strong>粗</strong>",
        'href="https://example.com"',
    ]:
        assert needle in html, (needle, html)


def test_toml_roundtrip(tmp: Path) -> None:
    from wdigest.tomlwrite import dump_event, dump_sources

    sources = [
        Source(id="a", name="甲", kind="rss", feed="https://example.com/f",
               weight=1.2, angle="测试", enabled=True)
    ]
    path = tmp / "sources.toml"
    dump_sources(sources, path)
    loaded = load_sources(path)
    assert loaded[0].name == "甲"
    assert loaded[0].weight == 1.2
    assert loaded[0].feed == "https://example.com/f"

    event = Event(
        name="测试事件",
        description="说明",
        window_days=30,
        keyword_sets=[[["甲"], ["乙", "丙"]]],
    )
    epath = tmp / "event.toml"
    dump_event(event, epath)
    loaded_event = load_event(epath)
    assert loaded_event.name == "测试事件"
    assert loaded_event.sets() == [[["甲"], ["乙", "丙"]]]


class FakeKeywordLLM:
    enabled = True

    def json(self, system: str, user: str, max_tokens: int = 3000) -> dict:
        return {
            "sets": [
                [["Fable 5.2", "Fable5.2", "Fable 5.2"], ["具身", "机器人"]],
                [["Fable"], ["影响"]],
            ]
        }


def test_suggest_keywords() -> None:
    from wdigest.suggest import normalize, suggest_keywords

    result = suggest_keywords(FakeKeywordLLM(), "Fable 5.2 对具身智能的影响", "说明")
    assert len(result["sets"]) == 2
    assert result["sets"][0][0] == ["Fable 5.2", "Fable5.2"]

    object_shape = normalize(
        {"sets": [{"name": "事件", "groups": [["甲方"], ["乙方"]]}]}
    )
    assert object_shape["sets"] == [[["甲方"], ["乙方"]]]


def test_dotenv_tolerates_non_utf8(tmp: Path) -> None:
    import os

    from wdigest.env import load_dotenv

    path = tmp / "env_gbk"
    path.write_bytes("TEST_GBK_KEY=abc123\n# 中文注释\n".encode("gbk"))
    load_dotenv(path)
    assert os.environ.get("TEST_GBK_KEY") == "abc123"


def test_config_loaders() -> None:
    sources = load_sources(ROOT / "sources.example.toml")
    assert len(sources) >= 6
    assert any(s.name == "新智元" for s in sources)
    assert any(s.kind == "dataxapi" for s in sources)
    assert any(s.enabled for s in sources), "示例里至少要有一个开箱可用的源"
    event = load_event(ROOT / "events/huang-renxun-lizhi.toml")
    assert event.name == "黄仁勋从英伟达离职"
    assert len(event.sets()) == 3, event.sets()


def main() -> int:
    test_config_loaders()
    test_feed_parser()
    test_simhash()
    test_pick_for_enrichment()

    tmp_root = ROOT / ".test-tmp"
    tmp_root.mkdir(exist_ok=True)
    test_markdown_render()
    test_toml_roundtrip(tmp_root)
    test_suggest_keywords()
    test_dotenv_tolerates_non_utf8(tmp_root)
    store = Store(tmp_root / "test.db")
    try:
        seed(store)
        event = load_event(ROOT / "events/huang-renxun-lizhi.toml")
        sources = load_sources(ROOT / "sources.example.toml")

        test_dedup(store)
        test_retrieval(store, event)
        test_end_to_end(store, event, sources)
        test_coverage_without_llm(store, event, sources)
        test_paid_api(store, event)
    finally:
        store.close()
        shutil.rmtree(tmp_root, ignore_errors=True)

    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
