## 事件
名称：{{event_name}}
说明：{{event_desc}}

## 信源清单
{{source_list}}

## 判断条目
每条包含编号 i、来源 source、文章标题 title、日期 date、判断内容 claim、类型 type。

{{claims}}

## 输出格式

严格输出以下 JSON 对象：

{
  "tldr": ["3 到 5 条结论，每条不超过 40 字，概括信源们最值得知道的判断"],
  "consensus": [
    {"point": "被两个及以上信源支持的判断", "sources": ["来源名"], "evidence": "共同依据，没有就留空"}
  ],
  "disagreements": [
    {
      "question": "他们在哪个问题上不一致",
      "positions": [
        {"view": "一方的说法", "sources": ["来源名"], "evidence": "该方依据"}
      ]
    }
  ],
  "unique": [
    {"point": "只有一家提到的信息", "source": "来源名", "why": "为什么值得单独列出"}
  ],
  "forecasts": [
    {"claim": "谁预判接下来会发生什么", "source": "来源名", "basis": "依据"}
  ],
  "fact_checks": [
    {"issue": "互相矛盾的说法或存疑的数字", "sources": ["来源名"], "detail": "矛盾点在哪"}
  ],
  "gap_note": "关于信源覆盖盲区的一句话说明，没有就留空字符串"
}

## 注意

- disagreements 至少要有两方观点才输出。
- 如果所有条目高度一致，disagreements 返回空数组，不要制造对立。
- fact_checks 只在真的出现数字冲突、事实冲突或明显推测被当作事实时填写。
