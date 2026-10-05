# 接口契约

契约以《项目概况》第六节为准；实现改动接口时同步更新本文档。

## 端点

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/chat` | 问答主入口，SSE 流式；请求含 `deep_analysis` 开关 |
| GET | `/api/health` | 就绪状态、预热状态、GPU 可用性 |
| GET | `/api/clause/{clause_id}` | 条文原文与元数据 |
| GET | `/api/clauses?standard_id=&section_no=` | 该节全部条文（支撑「查看该节全部」） |
| GET | `/api/standards` | 已入库规范清单与章节树 |
| GET | `/api/search?clause_no=5.3.9` | 条款号直查 |
| POST | `/api/ingest` | 单部规范入库，幂等，触发 Milvus 全量重建 |

## `/api/chat` 返回字段

```
{answer_delta, reasoning_delta, citations[], tables[], section_hint,
 fallback_flag, degraded_flag, rerank_used, superseded_notice, project_conditions}
```

| 字段 | 含义 |
|---|---|
| `answer_delta` | 答案正文增量 |
| `reasoning_delta` | 思考模式下的推理过程增量 |
| `citations[]` | 引用列表，含完整章节路径 |
| `tables[]` | 命中的整表，前端高亮命中行 |
| `section_hint` | 节内条数与「查看该节全部」提示 |
| `fallback_flag` | 未命中或退回纯检索 |
| `degraded_flag` | 降级状态（如 GPU 不可用） |
| `rerank_used` | 本轮是否实际用了重排 |
| `superseded_notice` | 命中被替代老标准时的提示 |
| `project_conditions` | 本轮项目条件（含用户锁定项） |

## 约定

- 流式走 SSE。模型输出为 Markdown + `<!--推导-->` / `<!--原文-->` 分隔标记，**不用 JSON**。
- 条号引用由模型显式标记，前端按标记渲染，不靠正则猜。
- 降级必须如实暴露：`fallback_flag` / `degraded_flag` / `rerank_used`。
- 环境变量清单见 `.env.example`。
- 检索日志每轮记录：提问、召回块及所属条款、融合分、重排耗时、阈值判定、兜底与降级、推导数值，落本地 JSON Lines。
