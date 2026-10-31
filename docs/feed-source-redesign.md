# 资讯来源与抓取重构设计

> 目标：把“资讯获取”从单一 RSS 列表，升级为 **GitHub / 其他来源** 两套独立管理体系；支持论坛、博客、CSDN、Qt Blog、指定博主；让勾选的画像词真正参与“搜索候选 + 精确过滤”，而不是只做事后过滤。

## 1. 当前问题

1. `sources` 只有 `kind/name/url`，RSS、GitHub、arXiv、Dev.to 共用一张表，管理界面混在一起。
2. “其他来源”实际上只能填 RSS/Atom；CSDN、Qt Blog、博主主页没有专门入口。
3. 抓取主要依赖固定 RSS 和 GitHub 全局热门；勾选 C++ 不会去 CSDN/Qt/GitHub 搜索 C++。
4. 定向查询只在 GitHub/arXiv/Dev.to 做，且是临时逻辑，没有来源级配置、预览和独立调度。
5. 来源级别没有“包含词/排除词/语言/最低匹配度/每次上限”等精确规则。
6. HTML 站点、作者主页、平台搜索没有适配器抽象；遇到 CSDN 这类页面无法扩展。

## 2. 目标结构

```text
资讯
├─ GitHub
│  ├─ 仓库订阅（owner/repo，含 Releases）
│  ├─ 搜索订阅（关键词 + language/topic/stars/updated）
│  ├─ 用户/组织订阅（某人的仓库）
│  └─ 榜单（保留现有榜单，不直接进资讯流）
└─ 其他来源
   ├─ RSS / Atom（自动发现）
   ├─ 平台适配器（CSDN、Qt Blog、博客园、掘金、V2EX、InfoQ、Reddit、HN、Medium、Dev.to、arXiv…）
   ├─ 博主订阅（作者主页 / 作者 RSS）
   └─ 通用 HTML 列表（CSS 选择器，作为兜底）
```

两类来源使用同一套 `feed_items`，但**管理、调度、抓取适配器、状态统计完全分开**。

## 3. 来源模型

### 3.1 `sources`

```text
id
group            github | other
adapter          github_search | github_repo | github_user |
                 rss | atom | platform | author | html
name
homepage_url
feed_url
enabled
schedule_minutes
config_json      adapter 专属配置
last_fetch_at
last_status
last_error
created_at
```

`config_json` 示例：

```json
// GitHub 搜索
{
  "query": "C++",
  "language": "C++",
  "topic": "",
  "min_stars": 50,
  "updated_within_days": 30,
  "sort": "stars",
  "limit": 20
}

// CSDN 作者
{
  "author": "用户名",
  "mode": "rss",
  "rss_url": "https://blog.csdn.net/用户名/rss/list",
  "include_any": [],
  "exclude_any": []
}

// 通用 HTML 列表
{
  "list_url": "https://example.com/blog",
  "item_selector": "article",
  "link_selector": "h2 a",
  "summary_selector": ".summary",
  "date_selector": "time"
}
```

### 3.2 `source_queries`（可选，多查询订阅）

一个来源可以有多组查询，例如同一个 GitHub 搜索订阅同时关注：

```text
C++ + Qt
C++ + 并发
C++ + 编译器
```

```text
id, source_id, label, query_json, enabled, last_run_at
```

### 3.3 `source_rules`

```text
source_id
include_any      必含其一（为空表示不限）
exclude_any      命中即丢弃
languages        限定语言
min_relevance    0-1，可选
max_items        每次最多入库
```

### 3.4 `fetch_runs`

记录每次抓取的：

```text
source_id, started_at, status, fetched, kept, filtered, error
```

用于来源详情页显示“抓了多少、筛掉多少、为什么失败”。

## 4. 抓取流水线

```text
1. 读取启用的来源 + 当前画像勾选
2. 为每个来源生成查询计划
3. 适配器抓取候选
4. 标准化（标题/作者/时间/正文/标签）
5. canonical URL + 内容哈希去重
6. 来源规则 + 画像规则过滤
7. 可选语义重排（LLM）
8. 入库、翻译/摘要/评分
9. 记录 fetch_run
```

### 4.1 查询生成

画像词分为三组：

```text
已有技能 / 兴趣方向 / 学习目标
```

生成规则：

- 每个来源只使用与自身相关的词
- 中文技术词先映射英文别名：
  - 数据库 → database / db / sql
  - 编译器 → compiler / llvm / clang
  - 分布式系统 → distributed systems
  - 系统设计 → system design
  - C++ → C++ / cpp / c plus plus
- 支持排除词，例如：
  - `C++` 排除 `招聘`、`课程广告`
- 每个来源限制查询词数量，避免 GitHub/站点限流。

### 4.2 精确过滤

分两层：

**来源查询层**

- GitHub：`q`、`language`、`topic`、`stars`、`pushed`
- CSDN/平台搜索：站点搜索 URL 或作者页
- arXiv：`all:"C++"`
- Dev.to：tag
- RSS：无法搜索，只能在条目层过滤

**条目过滤层**

必须命中 `include_any` 或当前勾选的画像词之一；命中 `exclude_any` 直接丢弃。检查：

```text
标题、摘要、正文、标签、作者、仓库语言、仓库 topics
```

默认是硬过滤；可选“低分保留但隐藏”模式。

### 4.3 语义重排（第二阶段）

关键词过滤后，可选：

```text
批量把标题+摘要交给模型
输出 0-1 相关度 + 原因
低于阈值不进入主列表，或标记为“低相关”
```

只对候选条目做，不对全量文章逐篇调用，控制成本。

## 5. 平台适配器

### 5.1 适配器接口

```python
class SourceAdapter:
    name: str
    async def discover(url: str) -> SourceDraft
    async def fetch(source: dict) -> list[Item]
    async def extract(item: dict) -> str
```

注册表按 `adapter` 分发，新增平台只加适配器，不改调度器。

### 5.2 CSDN

优先顺序：

1. 作者 RSS：`blog.csdn.net/{user}/rss/list`（若可用）
2. 作者主页 HTML：抓文章列表
3. CSDN 站内搜索：`so.csdn.net/so/search?q=...&t=blog`

注意：

- 不绕过登录、验证码、付费墙
- 搜索页若被反爬拦截，来源状态显示“需要 RSS/作者订阅”
- 正文提取优先 `#content_views`，保留代码块
- 失败时降级使用摘要，不阻塞其他来源

### 5.3 Qt Blog

1. 官方 RSS：`https://www.qt.io/blog/rss.xml`
2. HTML 列表兜底
3. 正文提取保留代码块和标题层级

### 5.4 其他优先平台

```text
国内：CSDN、博客园、掘金、V2EX、InfoQ 中文、OSChina
国外：Qt Blog、Hacker News、Reddit、Medium、Dev.to、arXiv、GitHub
```

每个平台优先官方 RSS/API；没有稳定 Feed 的用 HTML 适配器或作者订阅。

### 5.5 博主订阅

输入博主主页后：

1. 自动发现 `<link rel="alternate" type="application/rss+xml">`
2. 找不到则尝试平台作者适配器
3. 再找不到则让用户配置列表选择器

支持：

```text
单博主 / 多博主 / 平台作者 / 个人独立博客
```

## 6. UI 设计

### 6.1 资讯页

```text
资讯
[全部] [GitHub] [其他]

[重新抓取全部] [抓取筛选：C++ ×] [Python ×] ...

[全部] [未读] [已收藏] [已忽略]   搜索框
```

筛选区：

```text
已有技能   [C++] [Python] [网络编程]
兴趣方向   [数据库] [编译器]
学习目标   [系统设计] [分布式系统] [AI 工程化]
```

勾选后：

- 显示“将查询 GitHub / CSDN / Qt / arXiv…”
- 显示每个来源预计查询词
- 可预览前 10 条候选

### 6.2 来源管理

独立页面，两个 Tab：

```text
来源管理
[GitHub 订阅] [其他来源]

GitHub：
+ 新建搜索订阅
+ 订阅仓库
+ 订阅用户/组织

其他：
+ 添加 RSS
+ 添加博主
+ 添加平台（CSDN / Qt / 博客园 / 掘金 / V2EX…）
+ 高级：HTML 列表
```

每个来源卡片：

```text
名称 / 类型 / 查询词
最近抓取 / 抓取数 / 筛选数 / 失败原因
[抓取] [编辑] [停用] [删除]
```

### 6.3 添加向导

```text
粘贴 URL
  ↓
自动发现 RSS / Atom / 平台适配器
  ↓
预览最近 5 条
  ↓
选择画像过滤规则
  ↓
保存并抓取
```

避免让用户直接面对 CSS 选择器；高级选项折叠。

## 7. 调度设计

- GitHub 和 Other 两套队列，互不阻塞。
- 每个来源独立 `schedule_minutes`。
- GitHub 遵守 Token 配额；无 Token 时降低并发和查询数。
- 平台站点串行 + 延迟，避免被封。
- 失败指数退避：1h → 6h → 24h。
- 支持“只抓某个来源”“只抓 GitHub / 只抓其他”。
- “重新抓取全部”仍是替换模式；单来源抓取是增量。

## 8. API 设计

```text
GET    /api/sources?group=github|other
POST   /api/sources                 创建
PATCH  /api/sources/{id}            修改
DELETE /api/sources/{id}
POST   /api/sources/discover        根据 URL 自动发现
POST   /api/sources/{id}/test       预览抓取结果
POST   /api/sources/{id}/fetch      单来源抓取
GET    /api/sources/{id}/runs       抓取历史
POST   /api/scheduler/run?group=...&replace=...
GET    /api/feed?group=github|other
```

## 9. 兼容与迁移

- 现有 `kind=rss` → `group=other, adapter=rss`
- `kind=github` → `group=github, adapter=github_search`
- arXiv/Dev.to → `group=other, adapter=platform`
- 保留旧字段，新增字段用迁移脚本填充，避免破坏现有 feed_items。
- 现有来源 URL 和已抓资讯不删除。

## 10. 实施阶段

### P0：结构与管理

- sources 增加 group/adapter/config
- 来源管理拆 GitHub / 其他
- RSS 自动发现、添加向导、测试抓取
- 来源详情统计

### P1：精确查询

- 画像词 → GitHub/arXiv/Dev.to 查询
- CSDN、Qt Blog 适配器
- 博主主页 / 作者 RSS
- 查询预览 + 来源规则

### P2：精准与稳定

- 语义重排与阈值
- 失败退避、限流、抓取历史
- 更多平台适配器（博客园、掘金、V2EX、InfoQ、Medium、Reddit）

### P3：体验完善

- 来源模板市场（内置常用源）
- 导入/导出 OPML
- 按来源分组、标签、优先级

## 11. 验收标准

1. 来源管理能分别查看 GitHub 和其他来源。
2. 添加 CSDN 博主主页能自动选择 RSS 或 HTML 适配器。
3. 添加 Qt Blog 能抓到最新文章。
4. 添加 GitHub `C++` 搜索订阅能抓到 C++ 仓库。
5. 勾选 C++ 后，“重新抓取全部”会向 GitHub/CSDN/Qt/arXiv 发起 C++ 查询，而不只是过滤。
6. 每个来源能显示抓取数、筛选数、失败原因。
7. 单来源抓取不清空旧资讯；“重新抓取全部”仍是替换模式。

## 12. 风险与边界

- CSDN/知乎等平台可能反爬；不绕过登录、验证码、付费墙。
- HTML 选择器会随站点改版失效，需要适配器维护。
- 平台搜索和 GitHub API 有限流，需要 Token、并发限制和退避。
- 只抓公开内容；个人使用为主。
- “各大论坛全部支持”不现实，采用“通用 RSS/HTML + 优先平台适配器”的可持续方案。
