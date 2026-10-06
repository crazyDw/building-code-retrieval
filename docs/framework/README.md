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
- **pymilvus 与 Milvus 版本**：pymilvus 3.0.2 连 Milvus v2.5.15 已实测兼容（2026-10-05 M0 冒烟）：连接、`list_collections`、创建/删除 dense `FLAT+COSINE` 与 sparse `SPARSE_INVERTED_INDEX+IP` 的 collection 均通过。M3 若遇接口差异再按计划降到 pymilvus 2.5.x。
- **FlagEmbedding 惰性搬家**：`BGEM3FlagModel` / `FlagReranker` 即便传了 `devices=['cuda:0']`，**构造完成时权重仍在 CPU、显存占用为 0**；要等第一次前向（空推理）后才整体搬到 `cuda:0`。校验必须在预热之后做（见 `retrieval/device.py`）。实测 embedder 1093 MB、reranker 再 +1083 MB，合计约 2.1 GB。
- **MilvusClient 写入后要 flush 才可见**：批量 `insert` 后统一调用一次 `flush()`，不要每批都 flush（22 批逐批 flush 会让一次重建从 ~30 s 涨到数分钟）。`query(output_fields=["count(*)"])` 可用于按标量统计；sparse 检索的 `data` 直接传 `{token_id: weight}` 字典即可。
- **重排阈值标定要用超范围问题做负样本**：若拿同域近似条款当负样本，相邻条文得分天然很高，会把阈值抬到误拦大量正常提问；M4 用 40 条域外问题做负样本，最高分 −3.6，与正样本（均值 4.6）分离清晰，最终运营阈值取 −2.0。
- **DeepSeek `deepseek-flash` 默认会输出 thinking**：不传参数时流里就带 `reasoning_content`。默认路径必须显式 `extra_body={"thinking": {"type": "disabled"}}`；深度模式 `enabled` 时传 `reasoning_effort=low` 且**不传 temperature**、`top_p=1.0`。实测短问题默认首字 688 ms/总 735 ms，深度总 8.7 s。
- **分隔标记与 clause_id 都要喂给模型**：模型可能把章节路径当成 `[[clause:...]]` 的内容，必须把 `clause_id：GB 55031-2022_5.3.9` 写在每个条文块标题里；模型偶尔漏写标记结尾的 `-->`，解析器按 `<!--推导` / `<!--原文` 前缀容错。
- **前端联调**：Node 24 + Vite 7 + React 19；`npm run build` 后由 FastAPI 挂载 `dist/`。DEV_MODE 下用 `uvicorn archrag.api.app:app --workers 1` 起服务即可无 GPU 全流程验证；界面截图存 `data/acceptance/`。
