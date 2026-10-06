# 架构与数据流

## 数据流

**检索**：提问 → 查询理解（条款号短路 / 别名匹配 / 数值剥离 / 按需改写 / 同义词追加）→ dense + sparse 双路召回 → RRF 融合 → 重排 → 按 `clause_id` 聚合 → 上下文组装 → 生成 → 分层答案

**入库**：语料 Markdown → 解析五级层级与表格 → 切块 → 校验 → 写 SQLite（真相源）→ 建 Milvus 索引（派生）

## 分层与职责

| 层 | 职责 | 关键约束 |
|---|---|---|
| 解析入库 | 读 `数据库上传资料/`，解析层级、表格、公式，切块写库 | 不改写源文件；解析、切分、写入整体事务化 |
| 存储 | SQLite 存原文、元数据、引用图、词典；Milvus 存向量 | **SQLite 是唯一真相源**，Milvus 纯派生 |
| 检索 | 查询理解、双路召回、RRF、重排、按条聚合 | 块长上限 256 token；上下文上限 12000 token |
| 生成 | 组装上下文、调用生成模型、分层输出、数值校验 | 只依据检索到的条文；禁止合规结论 |
| 接口 | FastAPI + SSE 流式 | 契约见 `docs/api/` |
| 前端 | React + Vite + TypeScript | 推导与原文视觉严格区分 |

## 不变量（改动时必须保持）

- SQLite 能独立重建 Milvus；反向不成立。
- 一条对多块时，无论命中哪一块，送入模型的都是**整条**条文。
- `scope` 块不占 top10 名额，命中时作为限定条件附加。
- 未命中用重排阈值判定；GPU 不可用时降级为纯 RRF，不回退 CPU 重排。
- 块长按实际块文本（标准名 + 章节路径 + 条号 +（款号）+ 正文）计 token，表格内容不计入；单个项自身超限时保留整项并记录例外（铁律 11）。

## 技术决策（M0 冻结）

> 来源：`project-requirements/开发计划.md` 第三节，2026-10-05 冻结。实现需要偏离时先改本节再动代码。

| 编号 | 决策 | 理由 | 回退 |
|---|---|---|---|
| D1 | 包划分按下文「包划分」，分 `config/logging_setup/errors/tokenizer` 与 `corpus/store/retrieval/generation/api` 六块 | 与数据流分层一一对应，依赖单向 | 实现中发现职责重叠时先改文档再动代码 |
| D2 | 依赖策略：`project/pyproject.toml` 用 setuptools + src 布局（`package-dir = {"" = "src"}`），声明除 torch 外的运行依赖；torch 按 README 固定命令手动安装，不写进 `dependencies` | 避免任何路径把 cu126 版覆盖成 CPU 版 | 若 FlagEmbedding 触发 torch 重装，改用带 `--index-url` 的 `requirements-torch.txt` 单独先行安装 |
| D3 | 进程模型：单个 uvicorn 进程（**强制 `workers=1`**）内加载 bge-m3 与重排模型，lifespan 里预热完成后才置就绪；模型推理用单把互斥锁串行化；`DEV_MODE=true` 跳过；模型常驻进程禁用调试器 | 单机单用户，延迟最优、部署最简；多 worker 会让显存与实际模型数翻倍 | 显存冲突时拆成模型服务（v1 不做，只记录） |
| D4 | 前后端同源：Vite build 产物由 FastAPI 静态挂载 `/`；开发期 Vite proxy 到 8000 | SSE 同源、无 CORS、少一个常驻进程 | 部署问题出现时再拆端口 |
| D5 | 存储实现：stdlib `sqlite3` + 手写 DDL（`PRAGMA user_version` 管版本），不引 ORM/Alembic；pymilvus 同步客户端；Milvus 重建 = drop + create + 从 SQLite 全量重嵌入 | 规模只有 554 条条文，简单可靠优先 | 结构变更频繁时再引迁移工具 |
| D6 | 检索链路同步实现；SSE 用 `StreamingResponse`，阻塞调用放线程池；生成侧用 `langchain-deepseek` | 与《关键决策记录》一致：LangChain 只管生成 | 流式问题无法解决时改用官方 HTTP SDK |
| D7 | 配置用 `python-dotenv` 读 `.env`；相对路径一律相对仓库根解析（从 `config.py` 的位置推），不依赖 cwd | 从任何目录启动行为一致 | 无 |
| D8 | `DEV_MODE=true`：SQLite 文件与 Milvus collection 名加 `_dev` 后缀（不建向量、不写正式库），仅入库《民用建筑通用规范》，跳过模型加载与预热；检索退化为 SQLite 关键词（LIKE）模拟 | 界面与接口开发不占 GPU，也不污染正式数据 | 无；其结果不得作为检索质量依据 |
| D9 | 标准号映射表直接解析 `数据库上传资料/规范标准号映射表.md`（唯一来源，不派生 CSV）；`.env` / `.env.example` 的 `STANDARD_MAP_PATH` 同步指向该文件 | 避免两份数据不同步 | 无 |
| D10 | 降级与就绪行为：CUDA 可用 + `RERANK_ENABLED=true` 为完整路径；开关为 false 属主动配置，只置 `rerank_used=false`、不置 degraded；CUDA 不可用时 embedder 回退 CPU 加载并置 degraded（原因码 `gpu_unavailable`）、重排跳过（不回退 CPU 重排）；embedder 也加载失败则启动失败并明确报错（不提供半可用检索）；Milvus 启动时不可达则 fail fast，运行中断开则 chat 返回错误事件、health 置不健康 | 与铁律 16 和需求一致，避免含糊的「半可用」状态 | 无 |
| D11 | 会话上下文：服务端不持久化会话；`/api/chat` 请求带 `referenced_clause_ids[]`，由前端在用户消息出现条号或点击引用链接时收集；服务端只组装「本轮召回 + 这些历史条款」 | 满足「不累积」的上下文要求，又不引入会话存储（v1 明确不做） | 若后续要历史，改为服务端会话表 |
| D12 | Milvus 度量：dense 用 FLAT + COSINE；sparse 用 SPARSE_INVERTED_INDEX + IP（Milvus 稀疏向量不支持 COSINE）；与《项目概况》「FLAT + COSINE」的字面差异以本节为准 | 按库的实际能力落地，避免 M3 卡在不可行的索引定义上 | 无 |

### 包划分

```
project/src/archrag/
├── __init__.py
├── config.py                   # Settings 工厂：读 .env/环境变量，派生 DEV_MODE 路径与 collection
├── logging_setup.py            # JSON Lines（UTF-8、按天轮转、不记录密钥）
├── errors.py                   # 异常基类与分层异常（解析/入库/检索/生成）
├── tokenizer.py                # bge-m3 tokenizer 懒加载，块长与上下文计量
├── corpus/                     # 解析入库层（只读语料，不改写源文件）
│   ├── models.py               # Standard/Section/Clause/Table/Chunk 等 dataclass
│   ├── standard_map.py         # 解析映射表 Markdown
│   ├── parser.py               # 五级层级、目次区间、标题空格归一化、scope/term/图片识别
│   ├── references.py           # 引用图：条→表 / 条→条 / 条→标准
│   ├── tables.py               # HTML 表格 + colspan/rowspan 展开 + 表题/注关联
│   ├── latex.py                # LaTeX 符号还原 + 符号→中文术语候选
│   ├── chunker.py              # 256 token 切块：body/term/scope/table_row
│   ├── lexicon.py              # 术语候选（统计+API）+ 别名表/查询扩展表种子
│   ├── checklist.py            # 每部规范 50 条随机核对清单
│   └── ingest.py               # 编排（含语料普查前置校验）：解析 → 切块 → 事务写 SQLite → 重建 Milvus
├── store/
│   ├── sqlite.py               # schema/事务/CRUD/引用图/词典/统计/失效与版本字段
│   └── milvus.py               # collection 管理：只存向量与定位标量，不存原文
├── retrieval/
│   ├── query.py                # 条款号短路/别名/数值剥离/按需改写/同义词
│   ├── device.py               # 模型设备/精度校验与显存计量（预热后调用）
│   ├── embedder.py             # bge-m3：dense+sparse，显式 devices=['cuda:0'] + 校验
│   ├── reranker.py             # bge-reranker-v2-m3，256 token 截断
│   ├── reindex.py              # 从 SQLite 全量/按标准重建 Milvus
│   ├── fusion.py               # RRF（默认等权，k=60）
│   ├── pipeline.py             # 召回→融合→重排→按条聚合→scope→引用扩展
│   └── context.py              # 整条还原 + 表格/章节路径/scope 带入 + 12000 token 预算
├── generation/
│   ├── prompts.py              # 固定前缀系统提示词 + 术语表
│   ├── client.py               # langchain-deepseek：流式、60 s 超时、重试 1 次、thinking 开关
│   ├── validate.py             # 分隔标记/引用标记、数值分层校验、禁止措辞扫描
│   └── service.py              # 默认/深度/降级编排
└── api/
    ├── app.py                  # FastAPI 实例、lifespan 预热、静态挂载
    ├── deps.py                 # 应用状态、就绪门、共享服务句柄
    ├── schemas.py              # 请求/响应模型（与 docs/api 对齐）
    ├── chat.py                 # POST /api/chat（SSE）
    ├── catalog.py              # clause/clauses/standards/search
    ├── ingest.py               # POST /api/ingest
    └── health.py               # GET /api/health
```

依赖方向：`api → generation → retrieval → store → corpus.models`；`corpus.ingest → store`。`store` 不得反向导入 `parser/ingest`，`corpus.models` 是共享数据契约（叶子模块）。

### 前端（`project/frontend/`）

Vite + React + TypeScript：`npm run build` 产物 `dist/` 由 FastAPI 静态挂载为 `/`，开发期用 Vite proxy 把 `/api` 转发到 8000（D4）。SSE 解析在 `src/api.ts`，分层答案渲染在 `src/components/AnswerBlocks.tsx`，引用侧栏在 `src/components/CitationSidebar.tsx`，表格高亮与条件条分别在 `TableView.tsx` / `ConditionBar.tsx`。

### 进程与部署

- 单 uvicorn 进程、强制 `workers=1`，预热完成前不接受请求（D3、D10）。
- 前后端同源：Vite build 产物由 FastAPI 挂载，开发期用 Vite proxy（D4）。
- Windows 开机自启用**任务计划**；具体步骤在 M8 写入 `docs/runbooks/`。
