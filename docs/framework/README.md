# 框架与库：本项目怎么用

只记录本项目实际用到的部分与踩坑点。API 细节查官方文档，不在这里抄。

| 组件 | 本项目怎么用 | 官方文档 |
|---|---|---|
| FastAPI | 提供 `/api/*`；问答走 SSE 流式 | https://fastapi.tiangolo.com/ |
| Milvus | Docker standalone；FLAT 索引 + COSINE 度量；标量字段 `standard_id` / `level` / `chunk_type` / `clause_id` / `section_id`；纯派生，可整体重建 | https://milvus.io/docs |
| FlagEmbedding | `bge-m3` 一次前向同时产出 dense（1024 维）与 sparse 向量；`bge-reranker-v2-m3` 截断 256 token | https://github.com/FlagOpen/FlagEmbedding |
| PyTorch | 用 cu126 wheel 自带的 CUDA runtime，不引用系统 Toolkit 库文件 | https://pytorch.org/docs/stable/index.html |
| SQLite | 唯一真相源；开 WAL；单文件便于备份 | https://docs.python.org/3/library/sqlite3.html |
| DeepSeek API | 生成与批量题库/词表；默认 `deepseek-flash` + 关闭 thinking | https://api-docs.deepseek.com/ |
| LangChain（`langchain-deepseek`） | **只用于生成侧**：连 DeepSeek 做 chat 与流式；检索链路不套它的抽象 | https://python.langchain.com/docs/integrations/chat/deepseek/ |
| React + Vite + TypeScript | 前端 | https://vite.dev/ |

## 已知的坑

- `pip install torch` 不带 `--index-url` 会静默装成 CPU 版：`torch.cuda.is_available()` 返回 `False` 且不报错。
- 禁止 `conda install pytorch`：conda 渠道的 `cudatoolkit` 与 pip 轮子自带 runtime 冲突。
- `nvidia-smi` 显示的 CUDA 版本是**驱动支持的最高版本**，不是已安装版本。
- Windows 上 torch 从自身 `lib/` 目录加载 DLL，不查 PATH。
- **FlagEmbedding 默认把模型加载到 CPU**：`BGEM3FlagModel(...)` / `FlagReranker(...)` 不传 `devices` 时，参数落在 CPU 且**不报任何错**，推理慢 10–25 倍。必须显式传 `devices=['cuda:0']`，并在加载后核对 `next(model.parameters()).device` 与 `torch.cuda.memory_allocated()`。实测两个模型 fp16 常驻约 2.1 GB。
