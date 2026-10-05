# 建筑规范 RAG 智能检索助手

面向工程设计人员的规范检索助手：用自然语言描述设计场景，定位到具体规范条款，输出**分层答案**——条件性推导在前，条文原文与适用范围在后，二者视觉严格区分。

**允许条件性推导，禁止下合规结论。**

> 当前处于骨架阶段：harness 层（目录、文档、技能、配置）已就位，`project/` 下的业务代码尚未实现。

## 语料

`数据库上传资料/` 下 5 份全文强制性规范 Markdown，共 **33 章 / 91 节 / 554 条 / 438 款 / 7 项**。新增或更新语料后，先跑 `normalize-regulation-md` 技能普查结构。

## 快速开始

本机环境**已就绪**——conda 环境 `archrag`（Python 3.11.17），torch / FlagEmbedding / FastAPI / LangChain 等均已安装。日常只需激活：

```powershell
conda activate archrag
```

换机器从零搭建时（conda 只建环境与 Python 版本，其余依赖走 pip）：

```powershell
conda create -n archrag python=3.11
conda activate archrag

# torch 必须显式指定 cu126 索引，否则会静默装成 CPU 版
pip install torch --index-url https://download.pytorch.org/whl/cu126

# 用量库功能前先起 Milvus（数据卷在 D:\milvus-data）
docker compose up -d

# 业务代码实现后生效
pip install -e project

# GPU 自检：应为 True 且设备名为 RTX 4070 Laptop
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

本地质量门的命令见 `AGENTS.md` 铁律（「工程与运行」组）。

## 开发模式

`DEV_MODE=true` 跳过模型加载与预热，改用 `_dev` 后缀的 SQLite 文件与 Milvus collection，语料仅入库《民用建筑通用规范》。**开发模式的结果不得作为检索质量依据。**

## 文档入口

| 想知道什么 | 读哪里 |
|---|---|
| 怎么在这个仓库里工作（规则、能力、命令） | `AGENTS.md` |
| 需求本身 | `project-requirements/项目概况.md` |
| 为什么这样设计 | `project-requirements/关键决策记录.md` |
| 语料改过什么 | `project-requirements/规范文件修改记录.md` |
| 约束、架构、术语、接口、运维 | `docs/` |

## 许可

MIT，见 `LICENSE`。
