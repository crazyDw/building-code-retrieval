# AGENTS.md

建筑规范 RAG 智能检索助手 —— 本仓库 harness 工程的**唯一入口**。

先读本文件，再按索引进入具体文件。本文件只放**结论与约束**，细节一律外链。

## 当前状态

- 目录骨架已建，多数文件是空占位（`.codex/*`、`docs/*`、`project/*`、三个通用 skill）。
- 需求已定稿：`project-requirements/项目概况.md`，以它为准。
- 语料已就位：`数据库上传资料/` 下 5 份 `.md`，33 章 / 91 节 / 554 条 / 438 款 / 7 项，全部为全文强制性规范。
- **入库阻塞项**：5 部规范的标准号与全称需外部映射表提供——文件内与文件名均不含，无法自动推断。
- 另有 2 项待确认：条文说明与附录是否存在；外部转换工具的输出是否稳定。
- `.github/workflows/` 保留占位，但本项目**不配置 CI**，质量门在本地跑。

## 一、地图

```text
AGENTS.md                本文件：唯一入口（地图 · 铁律 · 能力清单 · 命令）
README.md                面向人的快速开始
pyproject.toml           工具链唯一事实来源：ruff / mypy / pytest
.env.example             环境变量与密钥清单（只放键名）；真实值放 .env，不入库
数据库上传资料/          输入数据：语料源，唯一；5 份规范 .md 平铺

.github/workflows/       CI 流水线占位；本项目不配 CI（见「当前状态」）
.codex/                  运行时层：Codex 专有配置（config.toml / rules / hooks / agents）
.agents/skills/          能力层：可移植 skill，与具体工具解耦
docs/                    规范层：工程约束与规范
  README.md              文档索引；文件级索引由各子目录自己的 README 负责
  python-rules/          Python 通用约束
  architecture/          架构图、模块边界、ADR
  domain/                领域术语与业务规则
  api/                   接口契约
  runbooks/              运维与排障手册
  framework/             框架 API 速查
project-requirements/    目标层：需求与目标
  项目概况.md            需求唯一事实来源：运行环境、技术选型、语料、检索链路、接口、验收标准
  关键决策记录.md        需求阶段关键决策及其理由
  规范文件修改记录.md    语料规范化方式、逐行改动清单与验收结果
project/                 隔离层：业务代码，src / tests / pyproject.toml
```

harness 与业务分离：根目录管工具链与环境，`project/` 只放业务代码与运行依赖。

## 二、铁律

以下为违反即返工的硬约束。**与实现便利冲突时，以本文件为准。**

**答案与输出**

1. **允许条件性推导，禁止下合规结论**。输出中不得出现「满足规范 / 合规 / 合格」这类结论性措辞。
2. 只依据检索到的条文作答，每条结论挂 `clause_id`；**禁止引入规范外知识**。未命中时明说「未检索到直接依据」并列出最接近的条款，不编造。
3. 失败即降级，不猜测：API 超时 60 s、重试 1 次，仍失败则退回纯检索模式，照常返回条文原文并明示「当前未提供归纳解读」。
4. 命中全文强制性规范必须明确标注；命中已被全文强制性规范替代的老标准，在答案末尾提示核对适用性。
5. 数值校验分层：原文层数值须**逐字出现在该条原文中**；推导层不设数值白名单，但**必须写明所用输入值**（如「按层数 6、层高 3.0 m 推算」）。
6. `scope` 块与表格「注：」可被检索，但**只能作条件限定，不得作为答案依据**；前言与目次入库留存但不参与检索；条文说明当前语料不含，规则待确认。
7. 输出分层且顺序固定：**推导在前，条文原文与适用范围在后**，两块视觉严格区分。用 Markdown + 自定义分隔标记（`<!--推导-->` / `<!--原文-->`），**不用 JSON**；条号引用由模型显式标记，不靠正则猜。

**语料与解析**

8. 解析**不依赖源文件的书写形式**，也不改写源文件。标题内的版式残留空格（实测 12 处 / 6 种：`总 则`×5、`设 计`×2、`目 次`×2、`场 地`、`声 环 境`、`燃 气`）**保留在源文件**，由解析器在内存中归一化——不要顺手清理。
9. 五级层级按**行首编号形态**判定，不按 `#` 数量；判定正则与四类已知缺陷见《项目概况》第三节。
10. 条号必须存**数值分量**排序键——字符串排序会把 `5.3.10` 排在 `5.3.9` 前面。
11. 长度口径：块长按**条文正文**计量，不含其引用的表格；硬上限 256 token（唯一例外是单个项自身超限）。**超限才按款切**，不改为总是按款切；切分取项边界，不跨款、不劈项。
12. 表格是内联 HTML 且可能含合并单元格，须按 `colspan` / `rowspan` 展开；表题与「注：」并入该表并可被检索。
13. 向 `数据库上传资料/` 新增或更新语料后，先跑 `normalize-regulation-md` 普查；标记异常报告但不阻断，**条号数量与连续性异常才阻断入库**。

**检索与存储**

14. **SQLite 是唯一真相源**（原文、元数据、引用图、词典），Milvus 是纯派生物。dense + sparse 双路召回，不用 FTS5 + jieba。
15. 同一标准号只允许一个现行版；解析、切分、写入整体事务化，任一步失败即回滚。
16. 重排默认开启，`RERANK_ENABLED` 是运维开关；GPU 不可用时自动跳过重排并置降级标记，**不回退 CPU 重排**。
17. 上下文上限 12000 token；超限时从重排分最低的条开始**整条丢弃**，不做单条截断。
18. 延迟红线：默认路径**首字 ≤ 3 s、完整回答 ≤ 20 s**；候选 25 条若顶到红线，回调候选至 20、返回条数至 8。

**工程与运行**

19. 依赖只走 pip，conda 只负责创建环境与 Python 版本。装 torch **必须显式指定 cu126 索引**，禁止 `conda install pytorch`；CPU 版会静默让 `torch.cuda.is_available()` 返回 `False`。
20. `DEV_MODE=true` 跳过模型加载与预热、使用 `_dev` 数据源；**其结果不得作为检索质量依据**。
21. 模型常驻的进程用「运行」而非「调试」——调试器挂起线程会破坏 CUDA context。
22. 两个 `pyproject.toml` 各管一摊：根目录管工具链，`project/` 管包元数据与运行依赖。PyCharm 以 `project/` 为项目根，源码根为 `project/src`。

## 三、能力清单

**项目技能**（`.agents/skills/`）

| 技能 | 状态 | 用途 |
|---|---|---|
| `normalize-regulation-md` | 已就位 | 规范语料标题规范化与结构校验；含普查/规范化两个脚本、层级规则参考与 `agents/openai.yaml`；新增语料后必用 |
| `create-module` / `create-test` / `code-review` | 空壳待写 | — |

**子代理**（`.codex/agents/`）

| 角色 | 状态 |
|---|---|
| `code-reviewer` / `test-runner` | 空壳待写 |

**运行时配置**：`.codex/config.toml`（模型、沙箱、审批、MCP、hooks、子代理上限）与 `.codex/rules/default.rules`（execpolicy）当前为空，按需填入。

## 四、命令

```powershell
# 环境（conda 只建环境与 Python 版本，其余依赖走 pip）
conda create -n archrag python=3.11
conda activate archrag
pip install torch --index-url https://download.pytorch.org/whl/cu126
pip install -e project          # 待 project/pyproject.toml 填好后生效

# GPU 自检：应为 True 且设备名为 RTX 4070 Laptop
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_name(0))"

# 质量门（本地，无 CI；配置在根目录 pyproject.toml）
ruff check .
mypy project/src
pytest
```

语料普查与规范化用 `normalize-regulation-md` 技能，命令与执行顺序见其 `SKILL.md`（新增语料后必跑）。此处只留指向，避免与技能内的命令各自漂移。
