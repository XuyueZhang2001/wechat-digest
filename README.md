# wechat-digest

把一组固定信源对某个话题的看法，汇总成一份**可追溯**的报告。

输入：信源清单 + 一个话题。  
输出：共识、分歧、独家信息、预判、待核实、覆盖缺口。每条判断都带原文引文和链接。

## 它和「让 AI 搜一下」有什么不同

- **信源是你定的**，不是搜索引擎临时给的。名单固定，结果可复现。
- **按论点汇总，不是按文章摘要**。一篇文章拆成若干条判断，跨源合并同类项。
- **可追溯**。每条结论能点回原文；引文对不上正文会自动标 ⚠️。
- **不替你做判断**。报告只记录信源说了什么，模型自己的观点不混进来。

## 特点

- 零依赖，Python 3.11+，只用标准库
- 先检索后付费：只有命中话题的文章才去取正文
- 支持多套关键词（同一话题的不同问法）
- 本地网页界面，不用手改配置文件
- 数据全部落在本地 SQLite，不上传

## 快速开始

```bash
git clone <your-repo> wechat-digest
cd wechat-digest
python run.py init          # 生成 sources.toml 和 .env
```

编辑 `.env`，填入模型 Key（下一节有获取步骤）：

```
WDIGEST_API_KEY=sk-...
WDIGEST_BASE_URL=https://api.deepseek.com/v1
WDIGEST_MODEL=deepseek-chat
```

然后启动界面：

```bash
python run.py serve
```

打开 `http://127.0.0.1:8765`。

不想用界面也可以走命令行：

```bash
# 合成演示数据，不需要任何 Key
python run.py seed-demo
python run.py run --event events/huang-renxun-lizhi.toml --no-llm

# 配置 Key 后跑完整流程
python run.py run --event events/huang-renxun-lizhi.toml
```

## 配置模型 Key（以 DeepSeek 为例）

抽取和汇总都走 OpenAI 兼容接口，默认接 DeepSeek。

**1. 注册并充值**

打开 https://platform.deepseek.com ，注册登录。DeepSeek 是预付费，余额为 0 时调用会失败，先在「充值」里充一点。

**2. 创建 API Key**

左侧「API Keys」→「创建 API key」→ 起个名字（比如 `wechat-digest`）→ 复制。

Key 只在创建时显示一次，格式是 `sk-` 开头。关了窗口就只能重建。

**3. 写进 `.env`**

`python run.py init` 已经生成了 `.env`，打开填：

```
WDIGEST_API_KEY=sk-你复制的key
WDIGEST_BASE_URL=https://api.deepseek.com/v1
WDIGEST_MODEL=deepseek-chat
```

等号后面直接粘贴，不要加引号。`.env` 已被 `.gitignore` 忽略，不会提交。

**4. 验证**

```bash
python run.py run --event events/huang-renxun-lizhi.toml
```

- 报 `HTTP 401`：Key 错了或已失效
- 提示「未配置 API key」：`.env` 没被读到，确认文件名是 `.env` 而不是 `.env.txt`

**换别家模型**：只要是 OpenAI 兼容接口，改 `WDIGEST_BASE_URL` 和 `WDIGEST_MODEL` 两行即可，代码不用动。

## 配置信源

信源在 `sources.toml`（`init` 生成，已在 `.gitignore` 里）。两种类型：

```toml
# 免费：RSS
[[sources]]
id = "jiqizhixin"
name = "机器之心"
kind = "rss"
feed = "https://wechat2rss.xlab.app/feed/51e92aad2728acdd1fda7314be32b16639353001.xml"
weight = 1.2
angle = "AI 技术与产业"
enabled = true

# 付费：按篇计费
[[sources]]
id = "kr36"
name = "36氪"
kind = "dataxapi"
account = "36氪"
weight = 1.1
angle = "商业与科技新闻"
enabled = true
```

`account` 写公众号名称即可，首次会自动搜索并缓存编号；也可以直接填 `gh_` 或 `wxid_` 编号。

**公众号没有公开 RSS。** 按有没有被免费列表收录，分两条路。

### 找 Wechat2RSS 的 feed（免费）

1. 打开完整列表：https://wechat2rss.xlab.app/list/all.html
2. `Ctrl+F` 搜公众号名，比如「机器之心」
3. 点名字后面的链接，浏览器地址栏就是 feed，形如 `https://wechat2rss.xlab.app/feed/51e92aad...xml`
4. 复制进 `sources.toml`：`kind = "rss"`，`feed = "上面那串"`，`enabled = true`
5. 验证：浏览器打开该地址应看到 XML；或在项目里跑 `python run.py ingest`

列表只覆盖 300+ 个号，且只保留最近的文章。没收录的号往下看。

### 付费信源（DataXAPI）

适合没被免费列表收录的号，比如 36氪、虎嗅、晚点。

**1. 注册并充值**

打开 https://dataxapi.com ，注册后充值。按次计费：列表 $0.02/次，正文 $0.02/篇。

**2. 创建 Key**

控制台「API Keys」新建，格式是 `dx_` 开头。

**3. 写进 `.env`**

```
DATAXAPI_API_KEY=dx_你复制的key
```

**4. 加信源**

```toml
[[sources]]
id = "kr36"
name = "36氪"
kind = "dataxapi"
account = "36氪"
weight = 1.1
angle = "商业与科技新闻"
enabled = true
```

**5. 抓取**

```bash
python run.py ingest
```

`account` 写名称时，第一次会自动搜索并打印「对应编号 gh_xxx / wxid_xxx」并缓存。搜不到就换更精确的名称，或直接把编号填进去。

成本控制：`ingest` 只拉列表，`run` 时才按 `--enrich-top` 补正文，`--max-cost` 可以设硬上限，补过的正文永久缓存。详见「成本」一节。

没配 Key 时，这类信源会被跳过，不影响 RSS 源。

### 不建议再用的方案

- **wewe-rss** 已于 2026-05 归档，依赖的闭源中继已 502，新部署连扫码都走不通。
- **we-mp-rss** 仍在维护，但容器出现过挖矿报告（issue #485），不建议跑在本机。

## 定义话题

话题是 `events/` 下的一个 TOML 文件。核心是 `keyword_sets`：

```toml
name = "黄仁勋从英伟达离职"
description = "黄仁勋不再担任 CEO 或从公司去职的相关事实、原因与影响。"
window_days = 120

keyword_sets = [
  [["黄仁勋", "Jensen Huang"], ["离职", "辞职", "卸任", "走", "失去"]],
  [["黄仁勋", "Jensen Huang"], ["继任", "接班", "接替", "后黄仁勋"]],
  [["英伟达", "NVIDIA"], ["失去创始人", "后创始人时代", "新任CEO"]],
]
```

规则：

- 每套内部是「组间 AND、组内 OR」
- 套与套之间是 OR，命中任意一套即可
- 三套分别对应「事件本身」「继任」「公司层面」，避免只写一种框架漏掉另一种

写完先跑一次 `--no-llm` 看命中列表，确认没有大量误召回，再花钱分析。

## 网页界面

```bash
python run.py serve
```

三个页签：

- **信源**：增删、启停、看每个源抓了多少篇
- **话题**：新建、编辑、删除；可以只写一句说明，点「自动生成关键词」让模型生成多套条件
- **运行**：选话题、限制补全文篇数、设费用上限，实时看日志，完成后直接读报告

服务只绑定 `127.0.0.1`。界面保存会重写 `sources.toml` / `events/*.toml`，手工注释不保留。

## 工作流

```bash
python run.py ingest                    # 抓取所有启用的信源
python run.py sources                   # 看每个源抓到多少篇
python run.py run --event events/x.toml --no-llm        # 免费预演
python run.py run --event events/x.toml --enrich-top 6 --max-cost 0.12
```

## 成本

数据费几乎全在「补全文」上：

| 用法 | 单次数据成本 |
| --- | --- |
| 默认 `--enrich-top 6` | ≈ $0.12 |
| `--enrich-top 4 --top 8` | ≈ $0.08 |
| `--max-cost 0.06` | ≤ $0.06 |
| 只用免费 RSS 源 | $0 |

- 补过全文的文章永久缓存，重跑或换话题命中同一篇都不再收费
- 先检索后付费：只有通过关键词组的文章才补正文
- 名额按信源轮转，不会被高分的一家占满
- 模型费另计，用 deepseek-chat 一场话题通常几分钱

## 目录结构

```
wechat-digest/
├── run.py                  # 入口
├── sources.toml            # 本地信源（gitignore）
├── sources.example.toml    # 信源模板
├── events/                 # 话题定义
├── prompts/                # 提示词，可直接改
├── web/index.html          # 本地界面
├── wdigest/
│   ├── feed.py             # RSS/Atom 解析
│   ├── dataxapi.py         # 付费接口客户端
│   ├── store.py            # SQLite、去重
│   ├── retrieve.py         # 关键词检索与打分
│   ├── extract.py          # 逐篇判断抽取
│   ├── synth.py            # 跨源汇总
│   ├── report.py           # Markdown 渲染
│   ├── server.py           # 本地 Web 服务
│   └── pipeline.py         # 串流程
└── tests/
```

## 已知限制

- **检索是关键词式的**，没有向量或语义召回。没有固定措辞的主题（比如「英伟达的未来」）会漏。
- **RSS 只保留最近 N 篇**，做不了长期历史回溯。
- **付费接口的列表只有摘要**，检索阶段靠标题和摘要打分，召回略弱于全文。
- **引文校验是字符串匹配**，模型改写过的引文会被标 ⚠️。
- **单源不构成共识**：只有一个信源覆盖时，报告会明确说「不存在跨源共识」。

## 合规与免责

- 本项目**不自带任何公众号抓取实现**，只消费你配置的 RSS 或付费接口。
- 抓到的正文只存在本地 SQLite，用于检索和分析，请勿二次分发。
- 请遵守目标站点的服务条款与版权要求，仅用于个人学习和研究。
- 使用付费接口、模型服务产生的费用和账号风险由使用者自行承担。

## 参与

欢迎 issue 和 PR。改完代码跑一下：

```bash
python tests/test_smoke.py
```

CI 会在 Python 3.11 / 3.12 / 3.13 上跑同一套测试。

## 致谢

本项目在 DeepSeek 模型辅助下完成：代码、测试、文档和网页界面由 AI 协作生成，作者负责需求定义、信源与话题设计、审阅和验证。详见 [CONTRIBUTORS.md](CONTRIBUTORS.md)。

## License

MIT
