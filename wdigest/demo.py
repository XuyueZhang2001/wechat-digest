"""合成演示数据：只用于验证流程，全部标注为「示例」。

刻意不使用真实媒体名，避免把编造的内容挂到真实信源头上。
"""

from __future__ import annotations

from .store import Store

DEMO_SOURCES = [
    ("demo-tech", "示例信源·技术观察", "技术"),
    ("demo-biz", "示例信源·商业分析", "商业"),
    ("demo-chain", "示例信源·供应链", "供应链"),
]

_PREFIX = "（示例数据，仅用于测试，非真实报道）"

DEMO_ARTICLES = [
    {
        "source_id": "demo-tech",
        "source_name": "示例信源·技术观察",
        "title": "【示例】黄仁勋卸任的时点，比人选更值得关注",
        "published_at": "2026-11-10T09:00:00",
        "body": _PREFIX + "英伟达在 GTC 前一周宣布黄仁勋卸任，时点耐人寻味。"
        "从公司治理角度看，选择在产品路线图发布前完成交接，说明董事会希望把后黄仁勋时代的叙事"
        "和下一代平台绑定，而不是让交接本身成为一条独立的负面事件。"
        "多位接近公司的人士表示，交接方案至少准备了六个月，继任者来自运营体系而非技术体系。"
        "这意味着未来两年英伟达的重心会从架构激进转向交付稳定。"
        "文章判断，短期产品路线不会改变，但中长期看，CUDA 生态的维护者角色会被稀释。"
        "作者还提出一个疑问：如果新管理层不再亲自站台，开发者关系由谁承接。",
    },
    {
        "source_id": "demo-biz",
        "source_name": "示例信源·商业分析",
        "title": "【示例】换帅之后，英伟达的估值逻辑要重估吗",
        "published_at": "2026-11-11T08:30:00",
        "body": _PREFIX + "资本市场对黄仁勋卸任的第一反应是估值折价。"
        "有分析师测算，若创始人溢价消失，英伟达的合理估值可能缩水近三成。"
        "但本文给出相反判断：黄仁勋过去三年的主要贡献，是把公司从芯片供应商变成 AI 基础设施的标准制定者，"
        "这套位置一旦形成，并不依赖某一个人。"
        "真正的风险不在继任者能力，而在组织是否还允许长期投入。"
        "文章提醒，未来两个季度的资本开支指引，比人事公告更能说明问题。"
        "结论是短期估值会波动，但基本面取决于订单而不是头衔。",
    },
    {
        "source_id": "demo-chain",
        "source_name": "示例信源·供应链",
        "title": "【示例】中国团队与供应链：交接当周的三个信号",
        "published_at": "2026-11-12T10:15:00",
        "body": _PREFIX + "交接消息公布后，英伟达中国区员工在内部信中被告知业务照常。"
        "供应链侧，台积电的 CoWoS 订单排期没有变化，至少说明短期交付节奏未被打乱。"
        "但文章指出一个被忽略的信号：原本由黄仁勋亲自对接的几家云厂商，"
        "正在要求把年度框架协议改由新管理层签署，这说明客户在重新评估长期承诺。"
        "文章判断，真正的考验在明年一季度。"
        "如果新管理层无法延续亲自下场的客户关系模式，订单集中度会上升，议价能力会下降。",
    },
    {
        "source_id": "demo-tech",
        "source_name": "示例信源·技术观察",
        "title": "【示例】别把英伟达的成功写成个人传记",
        "published_at": "2026-11-12T18:40:00",
        "body": _PREFIX + "把黄仁勋的离开解读为一个时代的结束，是一种懒惰的叙事。"
        "英伟达的护城河是 CUDA 加上十五年积累的开发者习惯，这套东西不会因为 CEO 更换而消失。"
        "反过来看，过度绑定创始人的公司，往往在交接后暴露出组织能力短板。"
        "文章认为，这次交接真正的观察点不是谁接班，而是董事会是否愿意继续为十年期的研发下注。"
        "如果研发投入开始向短期财报妥协，那才是真正的转折点。",
    },
    {
        "source_id": "demo-biz",
        "source_name": "示例信源·商业分析",
        "title": "【示例】接班人是谁，比卸任本身更重要",
        "published_at": "2026-11-13T07:50:00",
        "body": _PREFIX + "目前公开信息指向两位候选人，一位来自运营体系，一位来自财务体系。"
        "运营背景意味着公司会继续押注交付和生态，财务背景则可能带来更严格的资本配置。"
        "文章倾向于前者，理由是董事会此时最不需要的是降本信号。"
        "文章还提到，黄仁勋保留董事长职务的可能性很高，这会让交接变成分权而不是退出。"
        "若属实，短期内战略连续性会好于市场预期。",
    },
    {
        "source_id": "demo-tech",
        "source_name": "示例信源·技术观察",
        "title": "【示例】黄仁勋在 GTC 上谈推理成本",
        "published_at": "2026-11-09T12:00:00",
        "body": _PREFIX + "本文记录黄仁勋在 GTC 演讲中关于推理成本的三点判断，"
        "涉及单位 token 成本、集群利用率和模型蒸馏。全文没有涉及人事变动。",
    },
    {
        "source_id": "demo-tech",
        "source_name": "示例信源·技术观察",
        "title": "【示例】新一代加速卡的三个技术细节",
        "published_at": "2026-11-08T09:20:00",
        "body": _PREFIX + "本文讨论新发布加速卡的封装、互联和功耗，与人事变动无关。",
    },
]


def purge(store: Store) -> int:
    """删掉所有演示数据，返回删除的文章数。"""
    cursor = store.conn.execute("DELETE FROM articles WHERE source_id LIKE 'demo-%'")
    store.conn.execute("DELETE FROM sources WHERE id LIKE 'demo-%'")
    store.conn.commit()
    return cursor.rowcount


def seed(store: Store, reset: bool = False) -> dict:
    if reset:
        store.conn.execute("DELETE FROM articles WHERE source_id LIKE 'demo-%'")
        store.conn.commit()

    for sid, name, angle in DEMO_SOURCES:
        store.upsert_source(sid, name, feed="", weight=1.0, angle=angle, enabled=True)

    counts: dict[str, int] = {}
    for article in DEMO_ARTICLES:
        status = store.add_article(
            source_id=article["source_id"],
            source_name=article["source_name"],
            title=article["title"],
            url="",
            author="",
            published_at=article["published_at"],
            body=article["body"],
        )
        counts[status] = counts.get(status, 0) + 1

    return counts
