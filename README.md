# Atlas PKM

> 本地优先的个人知识管理 Agent：把资讯采集、中文翻译/摘要、画像匹配、Markdown 知识库、带引用问答和 LLM Wiki 串成一条可长期维护的本地工作流。

Atlas PKM 是一个面向个人使用者的桌面应用。资讯、索引、模型配置和知识库都保存在本机；外部模型只负责推理和生成，Markdown 始终是知识库的事实层。

```text
资讯来源 → 本地落盘 → 翻译/摘要/匹配度 → 收藏 / 忽略 / 入库
        → Markdown Vault → 检索 → 带引用问答 → Patch → LLM Wiki
```

当前版本：`0.1.0`  
桌面端：Windows 10/11（WebView2）  
测试：86 项自动化测试通过

---

## 目录

- [项目概述](#项目概述)
- [核心功能](#核心功能)
- [系统架构](#系统架构)
- [部署方式](#部署方式)
- [首次使用](#首次使用)
- [使用流程](#使用流程)
- [资讯系统](#资讯系统)
- [知识库与 Wiki](#知识库与-wiki)
- [模型配置](#模型配置)
- [数据与备份](#数据与备份)
- [开发与测试](#开发与测试)
- [项目结构](#项目结构)
- [安全与隐私](#安全与隐私)
- [已知限制](#已知限制)
- [路线图](#路线图)
- [License](#license)

---

## 项目概述

大多数资讯工具解决的是“今天有什么新闻”，Atlas PKM 解决的是：

```text
今天这条内容，对我有什么用？
它应该进入我的长期知识库吗？
它和我已经掌握的内容、正在学习的目标是什么关系？
```

Atlas PKM 的定位：

- **本地优先**：SQLite、Markdown、Wiki 构建产物都在本地。
- **个人长期使用**：不是多人协作平台，不依赖云端账号。
- **被动服务**：按计划采集，不做消息推送和社交提醒。
- **Obsidian 兼容**：Vault 是普通 Markdown 目录，可以直接用 Obsidian 打开。
- **可替换模型**：OpenAI、Anthropic、Gemini、DeepSeek，以及 OpenAI/Anthropic-compatible 第三方服务。
- **可扩展来源**：RSS/Atom、CSDN、Qt Blog、博主主页、GitHub 搜索/仓库订阅、HTML 列表和推荐来源目录。

它适合：

- 需要持续跟踪 C++、系统、分布式、AI 工程等技术方向的开发者
- 已经在使用 Obsidian，希望资讯能进入知识库的人
- 希望把“阅读”变成“可检索、可问答、可复盘”的长期积累的人

---

## 核心功能

### 1. 资讯采集

- GitHub 与“其他来源”两套独立管理。
- GitHub 支持搜索订阅、仓库订阅和热门仓库。
- 其他来源支持 RSS/Atom、CSDN 博主、Qt Blog、博主主页、通用 HTML。
- 内置 50 个推荐来源，覆盖重点技术博客、科技公司 Engineering Blog、学术出版、国内技术社区。
- 支持最近 24 小时 / 3 天 / 7 天抓取窗口，默认 3 天。
- 支持每天固定时间或固定间隔采集。
- 左侧来源列表按来源查看资讯；第一项为“全部”。
- 失败来源显示最近错误，单个来源可独立抓取。

### 2. 内容处理

每条新资讯进入本地后，可执行：

```text
中文翻译
中文摘要
匹配度分析
知识缺口
标签
```

- 默认按匹配度分页显示，也可以切换“最新”。
- 新资讯优先处理，历史缺失内容会增量补全。
- 内容发生变化时，会清理旧摘要/翻译并重新分析。

### 3. 资讯操作

- **收藏**：保留在收藏页，不复制正文到知识库。
- **忽略**：默认不再显示，后续重新抓取时不会更新该条。
- **入库**：生成 SourceNote，写入 Markdown Vault，并更新 Wiki。
- **重新翻译+摘要**：单条重新生成。
- 收藏页区分 **RSS / 其他** 与 **GitHub** 两个 Tab。
- GitHub 榜单卡片支持收藏，收藏后可在 GitHub Tab 查看。

### 4. 个人画像与匹配

个人画像分三部分：

```text
岗位信息
├─ 工作岗位
├─ 当前水平
├─ 是否技术岗位
└─ 编程语言（多选）

技能信息
└─ 已有技能

学习目标
└─ 后续想学习的技能 / 方向（原“兴趣方向”已合并）
```

画像用于摘要、匹配度、知识缺口、学习内容和复盘。匹配度排序会综合岗位、语言、技能和学习目标。

### 5. 知识库

- Markdown Vault 固定存放在 exe 同级目录。
- 支持 Obsidian 直接打开。
- 目录包括：

```text
00-Inbox
01-Drafts
02-Knowledge
03-Maps
08-Collections
90-Attachments
_system
```

- 资讯入库生成 `02-Knowledge/Sources/` 下的 SourceNote。
- 应用 Patch、保存学习文档后，内容进入 Markdown。
- 支持 wikilink 与标签知识图谱。

### 6. 问答、Patch 与 Wiki

- 带引用问答：优先检索本地知识库和资讯摘要。
- 可选生成 Patch，写入 Patch Queue，手动应用后才修改知识库。
- LLM Wiki：从 Markdown 自动生成可浏览的 HTML Wiki。
- Obsidian 修改 Markdown 后，Wiki 会自动重建。

### 7. 学习与复盘

- 按主题生成结构化知识文档。
- 按难度和数量生成面试题。
- 周期复盘：最近 7/30/90 天的资讯、收藏、笔记、匹配度。
- 自动复盘可保存到 `03-Maps/Reviews/`。

### 8. 检索

- SQLite FTS5 trigram 本地全文检索。
- 本地字符 n-gram 向量，无需 Key。
- 可选外部 Embedding：OpenAI / Gemini / Ollama。
- 混合检索用于搜索和问答上下文。

### 9. 多平台模型用量

- 新增“用量”页面。
- 支持 DeepSeek API Key 查询余额。
- 支持 DeepSeek Platform Token 查询详细 Token 用量。
- 支持米醋、CCTQ 等 New API 中转站：
  - `Access Token + 用户 ID` 读取账户级用量
  - 剩余/累计额度
  - 今日 Token 和请求数
  - 近 30 天 Token（DeepSeek 使用官方 last30Days 口径）
  - 按模型统计
  - 按 API Key 展开：Key 名称、状态、今日/区间 Token、请求数、累计已用、剩余额度
- 按 API Key 明细采用**展开时懒加载**，账号级刷新不会翻日志，避免触发 New API 429。
- DeepSeek 使用 Platform `userToken` 查询按 API Key 用量；API Key 仍只用于余额。
- 按 Key 明细读取失败不会影响账号级用量显示，会单独提示。
- 用量账户令牌使用 Windows DPAPI 加密保存，API 响应只返回是否已配置。
- 外部用量结果缓存 5 分钟；按 Key 遇到 429 会暂停 60 秒，避免继续放大限流。

> 绑定方式：New API 使用平台个人资料中的 **Access Token + 数字用户 ID**；DeepSeek 使用 **API Key**（余额）和可选的 **Platform userToken**（详细 Token）。

### 10. 桌面体验

- 便携 exe，不要求目标机器安装 Python。
- WebView2 原生窗口；不可用时回退 Edge/Chrome 应用窗口。
- 系统托盘：打开、重建 Wiki、退出。
- 支持登录自启和后台运行。
- 多实例安全：如果端口被另一个 vault 实例占用，会自动选择新端口，不会错误打开其他知识库。

---

## 系统架构

```text
┌─────────────────────────────────────────────────────┐
│                    AtlasPKM.exe                     │
│  WebView2 / Edge 窗口  ←→  本地 FastAPI 服务         │
└───────────────────────┬─────────────────────────────┘
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
   data/pkm.db     data/config.json   vault/
   SQLite/FTS      模型与设置         Markdown
        │
        ├─ 资讯条目 / 来源 / 收藏 / 忽略
        ├─ GitHub 榜单与 Star 快照
        ├─ Patch Queue
        ├─ Embedding / 搜索索引
        └─ 运行记录

   data/wiki/  ← 从 vault 生成的 HTML Wiki（可重建）
```

关键原则：

- **vault**：人类可读、可版本管理、可被 Obsidian 打开的知识内容。
- **data**：数据库、索引、缓存、运行状态和模型配置。
- **data/wiki**：生成产物，可删除后重建，不属于知识事实层。

---

## 平台支持

| 平台 | 源码/后端 | 桌面窗口 | 托盘 | 安装包 |
|---|---|---|---|---|
| Windows 10/11 | ✅ | ✅ WebView2 | ✅ | ✅ 便携 exe / 安装脚本 |
| Linux | ⚠️ 核心服务预计可用，未在 Linux 实测 | ⚠️ 需浏览器打开，未提供原生打包 | ❌ | ❌ |
| macOS | 未验证 | 未验证 | ❌ | ❌ |

Linux 当前属于“源码运行、尚未实测”的范围。核心 FastAPI 服务不依赖 Windows API，但依赖 Linux 上的 Python、WebKit/浏览器和 SQLite FTS5 环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run.py
```

然后打开 `http://127.0.0.1:8787`。`desktop.py` 在 Linux 上会回退到系统默认浏览器；`pywebview`、系统托盘和 PowerShell 安装脚本仅面向 Windows。

## 部署方式

### 方式一：便携 exe（推荐给普通用户）

构建：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_portable.ps1
```

产物：

```text
dist\AtlasPKM.exe
```

使用：

1. 把 exe 放到一个**可写目录**。
2. 双击启动。
3. 首次启动自动创建：

```text
AtlasPKM.exe
data\
vault\
```

4. 浏览器/原生窗口打开本地服务。

后台模式：

```powershell
dist\AtlasPKM.exe --background --port 8787
```

说明：

- exe 已包含 Python 运行时和依赖。
- Windows 10/11 需要 WebView2；一般 Edge 自带。
- 不可写目录（例如 Program Files）不适合直接放便携版。
- 窗口化 exe 的异常日志在 `data\atlas.log`。

### 方式二：安装到当前用户

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_app.ps1
```

安装并设置登录自启：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_app.ps1 -StartWithWindows
```

卸载（默认保留 `data` / `vault`）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\uninstall_app.ps1
```

彻底删除数据：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\uninstall_app.ps1 -RemoveData
```

### 方式三：源码运行

要求：

- Windows 10/11
- Python 3.11+
- 可访问模型 API 的网络环境（使用外部模型时）

```powershell
cd pkm-app
python -m pip install -r requirements.txt
python run.py
```

打开：

```text
http://127.0.0.1:8787
```

或使用桌面窗口：

```powershell
python desktop.py
```

---

## 首次使用

### 1. 启动应用

首次启动会自动创建：

```text
data\
├─ config.json
├─ pkm.db
└─ wiki\
vault\
```

知识库路径固定为 exe 同级 `vault`，设置页只显示路径，不提供修改入口，避免数据目录和知识库分离。

### 2. 配置模型

进入：

```text
设置 → 模型
```

支持：

| Provider | 默认模型 | 说明 |
|---|---|---|
| OpenAI | `gpt-4o-mini` | 官方接口 |
| Anthropic | `claude-3-5-haiku-latest` | 官方接口 |
| Gemini | `gemini-1.5-flash` | 官方接口 |
| DeepSeek | `deepseek-chat` | 当前主要验证模型 |
| 第三方 | 自定义 | OpenAI-compatible / Anthropic-compatible |

填写 Key 后点击 **测试当前模型**。

顶部状态会显示：

```text
未配置模型 → 模型待验证 → 模型已就绪
                     ↘ 模型连接失败
```

未配置模型时：

- 应用仍可打开
- 本地知识库仍可浏览
- AI 翻译、摘要、匹配度、问答不可用
- 定时采集会等待模型配置

页面顶部会显示全局引导条，直接提供“配置模型”和“知识库设置”入口。

### 3. 添加来源

进入：

```text
设置 → 采集 → 资讯来源
```

#### GitHub

```text
GitHub 搜索订阅
GitHub 仓库订阅
GitHub 热门
```

搜索订阅可填写：

```text
查询词：C++
语言：C++
最低 Star：50
```

#### 其他来源

```text
RSS / Atom
CSDN 博主
Qt Blog
博主主页
通用 HTML
arXiv
Dev.to
```

也可以展开：

```text
推荐来源：重点博客 / 科技公司 / 学术出版 / 国内社区
```

重点博客默认勾选，一键导入。

### 4. 抓取

资讯页点击：

```text
抓取最新资讯
```

会按设置的时间窗口抓取所有已启用来源。

也可以在来源列表单独抓取。

---

## 使用流程

### 日常资讯流

```text
抓取最新资讯
  ↓
翻译 / 摘要 / 匹配度
  ↓
默认按匹配度排序
  ↓
左侧按来源查看
  ↓
收藏 / 忽略 / 入库
```

### 将资讯转成知识

```text
资讯卡片 → 入库
  ↓
生成 SourceNote
  ↓
写入 vault/02-Knowledge/Sources/
  ↓
重建 Wiki
```

### 问答与知识维护

```text
提问
  ↓
FTS + 向量混合检索
  ↓
带引用回答
  ↓
可选生成 Patch
  ↓
手动应用
  ↓
Markdown 更新 + Wiki 重建
```

### 学习与复盘

```text
选择主题 / 难度
  ↓
生成知识文档或面试题
  ↓
保存前检查
  ↓
新建草稿 / 追加到已有笔记
```

周期复盘：

```text
03-Maps/Reviews/
```

---

## 资讯系统

### 来源分组

```text
GitHub 订阅
└─ 搜索 / 仓库 / 热门

其他来源
├─ RSS / Atom
├─ CSDN 博主
├─ Qt Blog
├─ 博主主页
├─ 通用 HTML
├─ arXiv
└─ Dev.to
```

### 推荐来源

内置 50 个来源，分为：

- 重点技术博客
- 科技公司 Engineering Blog
- 技术博主
- 论坛与专业出版
- 学术与专业出版
- 国内平台与社区

重点来源包括 C++ Stories、Fluent C++、The Old New Thing、Arthur O'Dwyer、Brendan Gregg、Julia Evans、LWN.net、Dan Luu、Martin Kleppmann、Jepsen、High Scalability、All Things Distributed 等。

CSDN 由用户手动添加博主地址；优先使用作者 RSS，失败时回退作者页 HTML。

### 时间窗口

```text
最近 24 小时
最近 3 天（默认）
最近 7 天
```

只抓取窗口内文章；GitHub 仓库订阅按自身查询条件执行。

### 本地落盘

- 资讯先写入 `data/pkm.db`。
- 重复 URL 更新本地记录。
- 内容变化时重新生成摘要、翻译、匹配度。
- “入库”才会写入 vault。

### 单条操作

```text
重新翻译+摘要
收藏
忽略 / 恢复未读
入库
打开原文
```

- 收藏：进入收藏页。
- 忽略：默认隐藏，后续不更新。
- 入库：生成 SourceNote 并更新 Wiki。

---

## 知识库与 Wiki

### Vault 目录

```text
vault/
├─ 00-Inbox/
├─ 01-Drafts/
├─ 02-Knowledge/
│  ├─ Sources/
│  ├─ Concepts/
│  ├─ Technologies/
│  ├─ Practices/
│  └─ Github-Repositories/
├─ 03-Maps/
├─ 08-Collections/
├─ 90-Attachments/
└─ _system/
```

### Wiki

- 页面路径：`data/wiki/`
- 入口：`/wiki/`
- 来源：`vault` 中的 Markdown
- Obsidian 修改 Markdown 后自动重建
- 删除笔记后清理旧页面

Wiki 是派生视图，不是事实源；Markdown 才是。

---

## 模型配置

### 配置位置

```text
data/config.json
```

包含：

- Provider
- API Key
- 模型名
- Base URL
- Embedding 配置
- Vault 路径（固定）
- 采集与画像配置

### 连接状态

- **未配置模型**：没有可用 Key
- **模型待验证**：已保存 Key，但没有测试结果
- **模型已就绪**：最近测试成功
- **模型连接失败**：最近测试失败，显示错误

修改 Provider、Key 或模型后，会回到“待验证”。

### Provider 兼容性

- 官方 OpenAI、Anthropic、Gemini、DeepSeek
- 第三方 OpenAI-compatible
- 第三方 Anthropic-compatible
- 模型列表发现：填写 Key/Base URL 后可获取厂商模型列表
- 第三方协议支持三种：OpenAI Chat Completions、OpenAI Responses、Anthropic Messages
- 第三方网关的协议和 Base URL 必须匹配；不同中转站的路径规则可能不同
- 模型请求会自动使用 `HTTPS_PROXY` / `HTTP_PROXY` 或 Windows 系统代理；本地 Base URL 会跳过代理

当前实测主要使用 DeepSeek；其他适配器保留但需要对应 Key 验证。

### Embedding

默认：

```text
local-ngram 2048 维
```

可选：

| Provider | 模型 | 说明 |
|---|---|---|
| OpenAI | `text-embedding-3-small` | 需要 Key |
| Gemini | `text-embedding-004` | 需要 Key |
| Ollama | `bge-m3` | 本地服务 |

切换后重建索引；未完成重建时仍可使用 FTS + 本地 n-gram。

---

## 数据与备份

### 数据分布

| 路径 | 内容 |
|---|---|
| `data/pkm.db` | 资讯、来源、收藏、忽略、索引、Patch、运行记录 |
| `data/config.json` | 模型、API Key、路径、采集设置 |
| `data/wiki/` | 生成的 Wiki HTML，可重建 |
| `vault/` | Markdown 知识内容、SourceNote、复盘、附件 |

### 备份建议

完整备份至少包含：

```text
vault/
data/pkm.db
data/config.json
```

`data/wiki/` 可以删除后重建。

### 迁移

- 整个应用目录（exe + data + vault）可以整体复制到另一台 Windows 机器。
- 目标目录必须可写。
- 不要只复制 vault，否则会丢失资讯、来源和模型配置。

---

## 开发与测试

### 技术栈

- Python 3.11
- FastAPI + uvicorn
- SQLite + FTS5
- 原生 HTML / CSS / JavaScript
- pywebview 6 + WebView2
- PyInstaller onefile
- pytest

### 测试

```powershell
cd pkm-app
python -m pytest -q
```

当前结果：

```text
80 passed
```

覆盖：

- API 与配置
- RSS / GitHub / arXiv / Dev.to
- 来源分组与推荐目录
- CSDN / Qt / 博主适配器
- 抓取时间窗口
- FTS 与本地向量
- 画像匹配
- Patch Queue
- Wiki
- SourceNote / 收藏 / 入库

### 构建

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_portable.ps1
```

---

## 项目结构

```text
pkm-app/
├─ app/
│  ├─ main.py                 # FastAPI 路由
│  ├─ config.py               # 配置、固定路径
│  ├─ db.py                   # SQLite / FTS5 / 迁移
│  ├─ vault.py                # Markdown Vault
│  ├─ providers/              # 模型适配器
│  ├─ services/
│  │  ├─ feeds.py             # 抓取、去重、时间窗口
│  │  ├─ source_adapters.py   # RSS / CSDN / Qt / 博主 / GitHub
│  │  ├─ source_catalog.py    # 50 个推荐来源
│  │  ├─ targeted.py          # 定向查询
│  │  ├─ agent.py             # 摘要、翻译、评分、问答
│  │  ├─ scheduler.py         # 定时采集
│  │  ├─ search.py            # FTS + 向量
│  │  ├─ notes.py             # SourceNote
│  │  ├─ patches.py           # Patch Queue
│  │  ├─ wiki.py              # HTML Wiki
│  │  └─ ...
│  ├─ static/                 # 前端
│  └─ templates/              # Wiki 模板
├─ tests/
├─ docs/
├─ data/                     # 运行时生成
├─ vault/                    # 运行时生成
├─ desktop.py                # 桌面启动器
├─ run.py                    # 源码启动
├─ build_portable.ps1
├─ install_app.ps1
└─ uninstall_app.ps1
```

---

## 安全与隐私

### 本地保存

- SQLite 数据库
- Markdown 文件
- Wiki 构建产物
- 模型配置
- 搜索索引

### 会离开设备的内容

使用外部模型时：

- 资讯标题、摘要、正文
- 问答上下文
- 生成请求中的画像与提示词

会发送给所配置的模型服务商。

### 不会做的事情

- 不提供云端账号
- 不内置遥测
- 不自动上传知识库
- 不绕过登录、验证码或付费墙

### 用户需要知道

- API Key 存在 `data/config.json`，当前为本地明文；共享或备份时要保护该文件。
- 外部模型的隐私政策由对应服务商决定。
- 资讯来源抓取公开内容；站点反爬或页面改版会导致失败。

---

## 已知限制

- 目前主要面向 Windows；macOS/Linux 桌面打包未完成。
- 外部模型适配器已实现，但当前主要验证 DeepSeek。
- CSDN、知乎等平台可能反爬；CSDN 采用作者 RSS/页面回退，不做全站搜索。
- HTML 适配器依赖站点结构，站点改版可能失效。
- 资讯、Wiki、问答和 Patch 是单用户本地模型，不提供多人协作。
- 没有成本预算、提示注入防护、数据脱敏和外发审计。
- 没有自动模型降级或质量评估。
- 当前仓库尚未添加正式 `LICENSE` 文件，开源发布前需要确定许可证。

---

## 路线图

- 更多平台专用适配器（掘金、V2EX、InfoQ、Medium、Reddit 等）
- 备份/恢复与存储管理界面
- 更完善的来源健康检查与失败重试
- 语义重排与可配置相关度阈值
- macOS / Linux 桌面打包
- 可选的 Wiki 输出到 Vault
- 更细的问答引用与知识页发布流程

---

## License

当前仓库尚未包含 `LICENSE` 文件。正式开源发布前需要选择并添加许可证；在添加之前，不应默认视为 MIT 或其他开源许可。








