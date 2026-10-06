# 建筑规范 RAG 智能检索助手

> **v1.0 已交付**（2026-10-06 完成端到端验收）。

面向工程设计人员的规范检索助手，部署在内网单机、Web 界面访问：用自然语言描述设计场景，助手定位到具体规范条款，输出**分层答案**——基于条文的条件性推导在前，条文原文与适用范围在后，二者视觉严格区分。

**允许条件性推导，禁止下合规结论。**

## 核心特性

- **分层答案**：推导在前、原文与适用范围在后，两块视觉严格区分；推导层必须写明所用输入值（如「按层数 6、层高 3.0 m 推算」）。
- **条文级引用**：每条结论挂 `clause_id`，引用卡片显示完整章节路径（如「第5章 建筑通用空间 › 5.3 楼梯、走廊 › 5.3.9」）。
- **只依据检索到的条文作答**：命中全文强制性规范明确标注；未命中时明说「未检索到直接依据」并列出最接近的条款，不编造。
- **表格整表返回**：命中表格时展示整张表并高亮命中行——表格各行互斥，只看一行容易套错条件。
- **章节完整性提示**：多条命中来自同一节时标注「该节共 N 条，当前列出 M 条」，并提供「查看该节全部」。
- **条款号直查**：输入 `5.3.9` 直接返回原文，不走检索与生成。
- **深度分析（按需）**：先判定建筑分类与适用前提再作答，推理过程放折叠面板并标注「非规范内容」。
- **项目条件条**：自动抽取层数、建筑高度、耐火等级、是否设自动灭火系统等条件；用户手改即锁定，后续轮次不被覆盖。
- **多轮且不累积**：只带本轮召回条款，加上被用户显式引用过的历史条款。
- **降级如实暴露**：生成超时或校验失败退回纯检索并提示「当前未提供归纳解读」；GPU 不可用时跳过重排（不回退 CPU）并置降级标记。

## v1 验收数据

| 指标 | 实测 | 证据 |
|---|---|---|
| 语料 | 5 份全文强制性规范，33 章 / 91 节 / 554 条 / 436 款 / 7 项 | — |
| 入库 | 701 检索块（body 601 / table_row 100），0 未标记超限 | — |
| 检索质量 | 703 题 **Recall@5 = 99.86%**（base 99.82 / table 100 / symbol 100 / adversarial 100） | `data/eval/` |
| 未命中阈值 | `SCORE_THRESHOLD = -2.0`（域内误判 0.85%，超范围 40/40 拦下） | `data/eval/threshold_curve.json` |
| 延迟（默认路径） | 首字 P50 727 ms / 完整 P50 3.85 s | `data/acceptance/latency.md` |
| 延迟（深度分析） | 首字 P50 531 ms / 完整 P50 14.4 s | 同上 |
| 模型常驻显存 | bge-m3 1093 MB + reranker 1083 MB ≈ 2.1 GB | `tests/retrieval/test_models.py` |
| 质量门 | ruff 通过；mypy 无问题；pytest 221 通过 / 6 跳过；前端 build 通过 | `data/acceptance/acceptance-report.md` |

端到端验收、降级演练、重启恢复与备份恢复演练的证据均在 `data/acceptance/`；逐项对照见 `data/acceptance/acceptance-report.md`。

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11 + FastAPI + SSE（单 uvicorn 进程，强制 `workers=1`） |
| 前端 | React 19 + Vite 7 + TypeScript（build 产物由 FastAPI 静态挂载到 `/`） |
| 向量库 | Milvus v2.5.15（Docker standalone；FLAT + COSINE；纯派生物，可整体重建） |
| 关系库 | SQLite（**唯一真相源**：原文、元数据、引用图、词典） |
| 嵌入 | bge-m3（一次前向同时产出 dense 1024 维 + sparse 向量） |
| 重排 | bge-reranker-v2-m3（GPU，默认开启，256 token 截断） |
| 生成 | DeepSeek API（`deepseek-flash`），经 `langchain-deepseek` 调用 |

## 架构与数据流

```
检索：提问 → 查询理解（条款号短路 / 别名 / 数值剥离 / 按需改写 / 同义词追加）
      → dense + sparse 双路召回 → RRF 融合 → GPU 重排 → 按 clause_id 聚合
      → 上下文组装（整条还原 + 章节路径 + scope + 表格）→ DeepSeek 生成 → SSE

入库：语料 Markdown → 解析五级层级与表格 → 256 token 切块 → 校验
      → 写 SQLite（真相源）→ 重建 Milvus 索引（派生）
```

改动时必须保持的不变量：

- **SQLite 能独立重建 Milvus，反向不成立**。
- 一条对多块；无论命中哪一块，送入模型的都是**整条**条文。
- `scope` 块与表格「注：」可被检索，但**只能作条件限定，不得作为答案依据**。
- 未命中用重排阈值判定；GPU 不可用时跳过重排，**不回退 CPU 重排**。

## 目录结构

```
.
├── AGENTS.md                 # 面向 agent 的仓库入口（分层地图 + 26 条铁律）
├── README.md                 # 本文件
├── pyproject.toml            # 工具链（ruff / mypy / pytest）唯一事实来源
├── docker-compose.yml        # Milvus standalone（数据卷在仓库外 D:\milvus-data）
├── .env.example              # 环境变量清单（只放键名与示例值）
├── 数据库上传资料/            # 语料源：5 份规范 Markdown + 标准号映射表
├── project/                  # 业务代码（隔离层）
│   ├── pyproject.toml        # 包元数据与运行依赖
│   ├── src/archrag/
│   │   ├── config.py / logging_setup.py / errors.py / tokenizer.py
│   │   ├── corpus/           # 解析入库：parser / tables / latex / chunker / references / lexicon / ingest
│   │   ├── store/            # sqlite（真相源）/ milvus（派生）
│   │   ├── retrieval/        # query / embedder / reranker / fusion / pipeline / context / reindex
│   │   ├── generation/       # prompts / client / validate / service
│   │   └── api/              # app / chat / catalog / ingest / health / schemas
│   ├── frontend/             # React + Vite + TypeScript
│   ├── scripts/              # 入库、重建、题库、评测、词表等批处理
│   └── tests/                # pytest 用例（corpus / store / retrieval / generation / api）
├── docs/                     # 工程约束：架构 / 领域 / 接口 / 运维 / 框架 / Python 规范
├── project-requirements/     # 需求与留档：项目概况 / 开发计划 / 关键决策记录 / 规范文件修改记录
├── data/                     # 运行数据（已 gitignore）：SQLite、评测、词表、验收证据、备份
└── logs/                     # JSON Lines 日志（已 gitignore）
```

依赖方向：`api → generation → retrieval → store → corpus.models`；`corpus.ingest → store`。

## 环境要求

- **操作系统**：Windows 11（含 WSL2 + Docker Desktop）。
- **GPU**：NVIDIA 显卡（本机 RTX 4070 Laptop 8 GB）；两个模型 fp16 常驻约 2.1 GB。
- **内存**：建议 ≥ 16 GB（Milvus 三件套另需 1.5–2 GB）。
- **Python**：3.11（本机 conda 环境 `archrag`，Python 3.11.17）。
- **Node.js**：构建前端用（Vite 7 / TypeScript 5.9）。
- **生成服务**：可用的 DeepSeek API Key。

> `torch` 不进 `project/pyproject.toml`，必须按下文命令显式安装 cu126 版；本机解释器为 `D:\Ai software\anaconda3\envs\archrag\python.exe`（PATH 上的 `python` 属 base 环境，不可用）。

## 快速开始

**从零搭建（换机器时）**

```powershell
conda create -n archrag python=3.11
conda activate archrag

# torch 必须显式指定 cu126 索引；装成 CPU 版不会报错，只会让 cuda.is_available()=False
pip install torch --index-url https://download.pytorch.org/whl/cu126

pip install -e project

cd project/frontend
npm install
npm run build
```

GPU 自检（应输出 `True` 与设备名）：

```powershell
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

**每次启动**

```powershell
# 1. 启动 Milvus（等 milvus-standalone 变为 healthy）
docker compose up -d

# 2. 构建前端（dist 不存在或前端有改动时）
cd project/frontend; npm run build; cd ../..

# 3. 启动后端（必须 workers=1；应用会拒绝多 worker 启动）
& "D:\Ai software\anaconda3\envs\archrag\python.exe" -m uvicorn archrag.api.app:app --host 127.0.0.1 --port 8000 --workers 1
```

启动时加载 bge-m3 与 bge-reranker-v2-m3 并各跑一次空推理预热（约 30–60 s）；**预热完成前 `/api/chat` 返回 503**。浏览器打开 `http://127.0.0.1:8000`。

健康自检：

```powershell
(Invoke-RestMethod http://127.0.0.1:8000/api/health) | ConvertTo-Json
# 期望：ready=true、milvus_connected=true、device=cuda:0
```

停止：后端 `Ctrl+C`；Milvus `docker compose down`（释放 1.5–2 GB 内存；SQLite 是真相源，可随时重建）。

> 两条硬约束：模型常驻进程必须 `workers=1`；用「运行」而非「调试」，调试器挂起线程会破坏 CUDA context。
>
> 完整的启动 / 停止 / 自启 / 入库 / 排障步骤见 `docs/runbooks/`。

## 开发模式

`DEV_MODE=true` 跳过模型加载与预热，使用 `_dev` 后缀的 SQLite 与 Milvus collection，语料仅入库《民用建筑通用规范》，检索退化为 SQLite 关键词（LIKE）模拟；界面、`/api/health` 与 SSE `meta`/`done` 均标注 DEV。

**开发模式的结果不得作为检索质量依据。**

开发期前端热更新：`cd project/frontend; npm run dev`（Vite 把 `/api` 代理到 8000）。

## 配置

配置走环境变量 + 根目录 `.env` 文件（键名与示例值见 `.env.example`）。分组如下：

| 组 | 变量 |
|---|---|
| 生成 | `DEEPSEEK_API_KEY` / `BASE_URL` / `MODEL` / `REASONING_EFFORT` |
| 嵌入与重排 | `EMBED_MODEL` / `RERANK_ENABLED` / `RERANK_MODEL` / `RERANK_MAX_TOKENS` |
| 检索 | `CHUNK_MAX_TOKENS` / `CONTEXT_MAX_TOKENS` / `TOPK_DENSE` / `TOPK_SPARSE` / `RERANK_CANDIDATES` / `TOP_N_DEFAULT` / `RERANK_CANDIDATES_DEEP` / `TOP_N_DEEP` / `REF_EXPAND_LIMIT` / `SCORE_THRESHOLD` |
| 存储 | `MILVUS_URI` / `MILVUS_COLLECTION` / `SQLITE_PATH` / `STANDARD_MAP_PATH` |
| 运行 | `DEVICE` / `DEV_MODE` |

## 接口概览

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/chat` | 问答主入口，SSE 流式；请求含 `deep_analysis` 开关 |
| GET | `/api/health` | 就绪状态、预热状态、GPU 可用性 |
| GET | `/api/clause/{clause_id}` | 条文原文与元数据 |
| GET | `/api/clauses?standard_id=&section_no=` | 该节全部条文（支撑「查看该节全部」） |
| GET | `/api/standards` | 已入库规范清单与章节树 |
| GET | `/api/search?clause_no=5.3.9` | 条款号直查 |
| POST | `/api/ingest` | 单部规范入库，幂等，触发 Milvus 全量重建 |

`/api/chat` 走 SSE，事件为 `meta` / `reasoning` / `answer`（`block=derivation|original`）/ `reset` / `error` / `done`；答案用 Markdown + `<!--推导-->` / `<!--原文-->` 分隔标记（**不用 JSON**），引用标记为 `[[clause:{clause_id}]]`。请求体、响应字段与状态码详见 `docs/api/`。

## 质量门与测试

本项目不配置 CI，质量门在本地跑（解释器用绝对路径的 `archrag` 环境）：

```powershell
& "D:\Ai software\anaconda3\envs\archrag\python.exe" -m ruff check .
& "D:\Ai software\anaconda3\envs\archrag\python.exe" -m mypy project/src
& "D:\Ai software\anaconda3\envs\archrag\python.exe" -m pytest

# 含 Milvus + GPU 集成用例
$env:ARCHRAG_MILVUS_TESTS = "1"
& "D:\Ai software\anaconda3\envs\archrag\python.exe" -m pytest

# 前端构建
cd project/frontend; npm run build; cd ../..

# 文档索引校验（各目录 README 是否登记全部 .md）
& "D:\Ai software\anaconda3\envs\archrag\python.exe" -X utf8 scripts\check_readme_index.py
```

当前结果：ruff 全绿；mypy 42 个源文件无问题；pytest 221 通过 / 6 跳过（含 Milvus + GPU 集成 227 通过）；前端 build 通过（JS 236 KB / gzip 75 KB）。

## 语料与词表

语料为 5 份全文强制性工程建设规范（GB 550xx 系列），**整部收录**，不做专业拆分：

| 文件 | 标准号 | 章 | 节 | 条 | 款 | 项 |
|---|---|---|---|---|---|---|
| 民用建筑通用规范.md | GB 55031-2022 | 6 | 26 | 142 | 78 | 0 |
| 住宅项目规范.md | GB 55038-2025 | 7 | 16 | 122 | 90 | 0 |
| 钢结构通用规范.md | GB 55006-2021 | 8 | 21 | 107 | 70 | 0 |
| 混凝土结构通用规范.md | GB 55008-2021 | 6 | 16 | 99 | 126 | 7 |
| 砌体结构通用规范.md | GB 55007-2021 | 6 | 12 | 84 | 72 | 0 |
| **合计** | — | **33** | **91** | **554** | **436** | **7** |

标准号取自 `数据库上传资料/规范标准号映射表.md`（源文件与文件名均不含标准号）。新增或更新语料后，先跑 `normalize-regulation-md` 技能普查结构；异常报告但不阻断，**仅条号数量与连续性异常才阻断入库**。

**领域词表**：`data/lexicon/` 下 500 条候选经人工筛出 **281 条**完整领域词并导入 `lexicon`（`status=approved`）；生成层系统提示词取分数前 50 条。维护流程见 `docs/runbooks/lexicon.md`。

## 文档导航

| 想知道什么 | 读哪里 |
|---|---|
| 怎么在这个仓库里工作（规则、能力、命令、26 条铁律） | `AGENTS.md` |
| 需求本身（唯一事实来源） | `project-requirements/项目概况.md` |
| 为什么这样设计 | `project-requirements/关键决策记录.md` |
| 落地路线图与里程碑进度 | `project-requirements/开发计划.md` |
| 语料改过什么 | `project-requirements/规范文件修改记录.md` |
| 架构、数据流、模块边界、M0 冻结决策 | `docs/architecture/` |
| 领域术语与业务规则 | `docs/domain/` |
| 接口契约（端点 / SSE / 状态码） | `docs/api/` |
| 启动、自启、入库、词表、备份、排障、复盘 | `docs/runbooks/` |
| 框架与库的落地要点与踩坑 | `docs/framework/` |
| 验收与演练证据 | `data/acceptance/` |

## v1 范围之外

PDF → Markdown 转换本身；按专业拆分章节；地名 → 建筑气候区划的查询扩展；合规判定与参数化规则引擎；跨规范新旧体系并列对比；条文级失效映射表；地方标准与图集；节级检索块；会话历史持久化；用户反馈纠错闭环；模型微调；账号与权限；Milvus GPU 索引；本地大模型生成；CI 流水线。完整清单见《项目概况》第八节。

## 许可

MIT，见 `LICENSE`（Copyright (c) 2026 github.com/crazyDw）。
