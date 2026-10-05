# AGENTS.md

建筑规范 RAG 智能检索助手 —— 本仓库 harness 工程的**唯一入口**。

先读本文件，再按索引进入具体文件。本文件只放**结论与约束**，细节一律外链。

顺序固定：**分层与地图**（怎么分层、东西在哪）→ **铁律**（什么不能做）。

## 当前状态

### 进度

- harness 层已就位（根级配置、`.codex/`、`.agents/skills/`、`docs/`）；`project/` 下的业务代码与 `project/pyproject.toml` 仍为空。
- 需求已定稿：`project-requirements/项目概况.md`，以它为准。
- 语料已就位：`数据库上传资料/` 下 5 份 `.md`，33 章 / 91 节 / 554 条 / 438 款 / 7 项，全部为全文强制性规范。
- 标准号映射表已就位：`数据库上传资料/规范标准号映射表.md`，含 5 部的标准号 / 全称 / 实施日期，入库时读取。
- 运行环境已就绪：conda 环境 `archrag`（Python 3.11.17）；torch 2.14.1+cu126 实测 `cuda.is_available()=True`；两个模型已用本地路径加载验证（合计显存约 2.1 GB）；Milvus 三镜像与 `docker-compose.yml` 就绪但**未启动**。

### 待办

- 2 项待确认：条文说明与附录是否存在；外部转换工具的输出是否稳定。
- `LICENSE` 的版权所有者仍是占位符 `<版权所有者>`，开源前替换。
- **隔离层动工时定** `project/pyproject.toml` 的依赖策略：不能把 torch 直接写进 `dependencies`（会从 PyPI 装成 CPU 版、覆盖 cu126 版），需在「requirements.txt 带 `--index-url`」与「保持手动安装」之间选一种。

## 一、分层与地图

harness = 业务代码之外的全部工作环境。下面五层是本仓库的组织骨架——前四层属于 harness，第五层是被隔离出去的业务。每层回答一个问题。

### 运行时层 —— `.codex/`

**这个工具被允许怎么跑。** 由机器强制执行，不靠读文档自觉遵守。

- `.codex/config.toml` —— 沙箱 `workspace-write`、审批 `on-request`、子代理并发 4
- `.codex/rules/default.rules` —— 沙箱外自动放行只读命令的白名单
- `.codex/agents/*.toml` —— 子代理身份（TOML，必填 `name` / `description` / `developer_instructions`）：`code_reviewer` 只读审查并找问题，`test_runner` 跑质量门与语料普查
- `.codex/hooks/` —— 未启用；若要启用，实际格式是 `.codex/hooks.json`，不是 hooks 目录

### 能力层 —— `.agents/skills/`

**我会做什么。** 随任务自动匹配，正文按需加载。

- `normalize-regulation-md` —— 新增或更新语料之后（必跑普查）
- `create-module` —— 在 `project/src` 下新增或改动业务模块
- `create-test` —— 在 `project/tests` 下新增或修改测试
- `code-review` —— 审查改动、要按铁律列问题

### 规范层 —— `docs/`

**按什么规矩做。** 读后自觉，与运行时层的机器强制相对。

- `docs/README.md` —— 六个子目录的索引，标明各自「什么时候读」；文件级索引由各子目录自己的 README 负责
- `docs/python-rules/` —— Python 通用约束
- `docs/architecture/` —— 架构与数据流、模块边界，含未决项
- `docs/domain/` —— 领域术语与业务规则
- `docs/api/` —— 接口契约
- `docs/runbooks/` —— 启动顺序、故障处置、入库与备份
- `docs/framework/` —— 用到哪些库、怎么用、有哪些坑

### 目标层 —— `project-requirements/`

**做成什么样。** 需求以《项目概况》为准；另两份是理由与变更的留档，按需查阅。

- `project-requirements/项目概况.md` —— 需求唯一事实来源，八节目录：
  摘要 / 运行环境与工程约定 / 语料 / 检索链路 / 生成与答案形态 / 界面、会话与接口 / 验收标准与测试 / 假设、默认值与不做范围
- `project-requirements/关键决策记录.md` —— 每个关键决策及其理由；只在追问「当初为什么这么定」时读
- `project-requirements/规范文件修改记录.md` —— 语料规范化的方式、逐行清单与验收；只在新增或更新语料、或追溯语料改动时读

### 隔离层 —— `project/`

**业务代码本身。** 只放业务代码与运行依赖，与 harness 隔离。

### 入口与支撑（不属于五层）

- `AGENTS.md` —— 面向 agent 的入口（本文件）
- `README.md` —— 面向人的快速开始
- `pyproject.toml` —— 工具链唯一事实来源（ruff / mypy / pytest）
- `.env.example` —— 环境变量与密钥清单（只放键名）；真实值放 `.env`，不入库
- `scripts/check_readme_index.py` —— 校验各目录 README 是否登记了同目录的所有 `.md`；新增或改名文档后跑
- `数据库上传资料/` —— 输入数据：5 份规范语料 + 标准号映射表（映射表不是语料）
- `.github/workflows/` —— CI 占位；本项目不配 CI（见铁律 24）
- `docker-compose.yml` —— Milvus standalone（etcd + minio + milvus v2.5.15），数据卷在 `D:\milvus-data`（仓库外）；做入库或检索前用 `docker compose up -d` 启动，常驻约 1.5–2 GB 内存

## 二、铁律

以下为违反即返工的硬约束。**与实现便利冲突时，以本文件为准。**

### A 答案与输出（1–7）

1. **允许条件性推导，禁止下合规结论**。输出中不得出现「满足规范 / 合规 / 合格」这类结论性措辞。
2. 只依据检索到的条文作答，每条结论挂 `clause_id`；**禁止引入规范外知识**。未命中时明说「未检索到直接依据」并列出最接近的条款，不编造。
3. 失败即降级，不猜测：API 超时 60 s、重试 1 次，仍失败则退回纯检索模式，照常返回条文原文并明示「当前未提供归纳解读」。
4. 命中全文强制性规范必须明确标注；命中已被全文强制性规范替代的老标准，在答案末尾提示核对适用性。
5. 数值校验分层：原文层数值须**逐字出现在该条原文中**；推导层不设数值白名单，但**必须写明所用输入值**（如「按层数 6、层高 3.0 m 推算」）。
6. `scope` 块与表格「注：」可被检索，但**只能作条件限定，不得作为答案依据**；前言与目次入库留存但不参与检索；条文说明当前语料不含，规则待确认。
7. 输出分层且顺序固定：**推导在前，条文原文与适用范围在后**，两块视觉严格区分。用 Markdown + 自定义分隔标记（`<!--推导-->` / `<!--原文-->`），**不用 JSON**；条号引用由模型显式标记，不靠正则猜。

### B 语料与解析（8–13）

8. 解析**不依赖源文件的书写形式**，也不改写源文件。标题内的版式残留空格（实测 12 处 / 6 种：`总 则`×5、`设 计`×2、`目 次`×2、`场 地`、`声 环 境`、`燃 气`）**保留在源文件**，由解析器在内存中归一化——不要顺手清理。
9. 五级层级按**行首编号形态**判定，不按 `#` 数量；判定正则与四类已知缺陷见《项目概况》第三节。
10. 条号必须存**数值分量**排序键——字符串排序会把 `5.3.10` 排在 `5.3.9` 前面。
11. 长度口径：块长按**条文正文**计量，不含其引用的表格；硬上限 256 token（唯一例外是单个项自身超限）。**超限才按款切**，不改为总是按款切；切分取项边界，不跨款、不劈项。
12. 表格是内联 HTML 且可能含合并单元格，须按 `colspan` / `rowspan` 展开；表题与「注：」并入该表并可被检索。
13. 向 `数据库上传资料/` 新增或更新语料后，先跑 `normalize-regulation-md` 普查；标记异常报告但不阻断，**条号数量与连续性异常才阻断入库**。该目录下的 `规范标准号映射表.md` 不是语料，普查要显式传入 5 份语料文件。

### C 检索与存储（14–18）

14. **SQLite 是唯一真相源**（原文、元数据、引用图、词典），Milvus 是纯派生物。dense + sparse 双路召回，不用 FTS5 + jieba。
15. 同一标准号只允许一个现行版；解析、切分、写入整体事务化，任一步失败即回滚。
16. 重排默认开启，`RERANK_ENABLED` 是运维开关；GPU 不可用时自动跳过重排并置降级标记，**不回退 CPU 重排**。
17. 上下文上限 12000 token；超限时从重排分最低的条开始**整条丢弃**，不做单条截断。
18. 延迟红线：默认路径**首字 ≤ 3 s、完整回答 ≤ 20 s**；候选 25 条若顶到红线，回调候选至 20、返回条数至 8。

### D 工程与运行（19–26）

19. 依赖只走 pip，conda 只负责创建环境与 Python 版本。装 torch **必须显式指定 cu126 索引**，禁止 `conda install pytorch`；CPU 版会静默让 `torch.cuda.is_available()` 返回 `False`。
20. `DEV_MODE=true` 跳过模型加载与预热、使用 `_dev` 数据源；**其结果不得作为检索质量依据**。
21. 模型常驻的进程用「运行」而非「调试」——调试器挂起线程会破坏 CUDA context。
22. 两个 `pyproject.toml` 各管一摊：根目录管工具链，`project/` 管包元数据与运行依赖。PyCharm 以 `project/` 为项目根，源码根为 `project/src`。
23. 查询 Codex 手册时，官方域名在本机不可达，改用 `https://www.codex-docs.com/docs/configuration`；该站是第三方镜像，结论须与本机实测（`~/.codex/config.toml`、`rules/`、项目 `hooks.json`）互相印证后再落盘。
24. 不配置 CI：质量门在本地跑——`ruff check .`、`mypy project/src`、`pytest`；`.github/workflows/` 只留占位。
25. FlagEmbedding 加载模型必须显式传 `devices=['cuda:0']`——不传时模型**静默落在 CPU**、不报错，推理慢 10–25 倍。加载后核对 `next(model.parameters()).device` 与 `torch.cuda.memory_allocated()`；两个模型 fp16 常驻约 2.1 GB。
26. 本项目的 Python 解释器是 `D:\Ai software\anaconda3\envs\archrag\python.exe`——PATH 上的 `python` / `pytest` 属于 base 环境，版本不同（pytest 7.4.4 vs 9.1.1）且没有 torch。跑质量门、脚本和任何 Python 命令都指定它：`& "<该路径>\python.exe" -m pytest`，或先 `conda activate archrag`。
