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

## `/api/chat` 请求体（定稿）

```json
{
  "message": "6层住宅，层高3.0m，楼梯踏步宽度怎么定？",
  "deep_analysis": false,
  "project_conditions": [
    {"key": "层数", "label": "层数", "value": "6", "locked": false}
  ],
  "referenced_clause_ids": ["GB 55038-2025_4.2.2"]
}
```

`project_conditions` 中 `locked=true` 的条目在后续轮次优先，服务端不得覆盖；
`referenced_clause_ids` 只带用户显式引用过的历史条款，不累积会话。

## `/api/chat` SSE 事件（定稿）

| event | data 字段 | 说明 |
|---|---|---|
| `meta` | `mode` / `dev_mode` / `not_found` / `broad` / `rerank_used` / `degraded_flag` / `degraded_reason` / `numbers` / `project_conditions` | 首事件 |
| `reasoning` | `delta` | 深度模式推理增量（非规范内容） |
| `answer` | `block`（`derivation` / `original`）+ `delta` | 推导增量；原文块通过数值校验后整块下发 |
| `reset` | `reason`（违规清单） | 校验失败重生成，前端清空推导区后继续接收 |
| `error` | `code` / `message` | 检索或生成异常；随后仍会发送 `done` |
| `done` | `citations[]` / `tables[]` / `section_hint` / `fallback_flag` / `degraded_flag` / `degraded_reason` / `rerank_used` / `not_found` / `broad` / `superseded_notice` / `project_conditions` / `numbers` / `mode` / `dev_mode` / `attempts` / `timings` | 终止事件 |

`tables[]` 每项含 `table_id` / `caption` / `notes` / `rows` / `clause_id` / `highlight_rows`；
`section_hint` 含 `section_id` / `section_clause_count` / `listed_count`。

## 状态码

| 端点 | 状态码 | 语义 |
|---|---|---|
| `/api/chat` | 200 | SSE 流（含 error/done 事件） |
| | 422 | 请求体非法（缺 message 等） |
| | 503 | 预热未完成（`not_ready`） |
| `/api/ingest` | 200 | 入库完成（`created` 表示新建或幂等替换） |
| | 400 | `dev_mode_limited`（DEV_MODE 只允许《民用建筑通用规范》） |
| | 404 | `standard_not_found` |
| | 409 | `version_conflict`（同标准号不同内容，默认拒绝） |
| | 503 | `embedding_not_ready`（正式模式模型未就绪） |
| `/api/clause/{id}` | 404 | `clause_not_found` |
| `/api/clauses` | 400 | `missing_parameter`（需要 standard_id 与 section_no） |

## 约定

- 流式走 SSE。模型输出为 Markdown + `<!--推导-->` / `<!--原文-->` 分隔标记，**不用 JSON**：
  推导块在前、原文块在后；没有推导时只输出原文块。原文块通过数值校验后才下发。
- 引用标记定稿：`[[clause:{clause_id}]]`，例如 `[[clause:GB 55031-2022_5.3.9]]`；
  只允许引用本轮上下文中的条款，前端按标记渲染为可点击引用，不靠正则猜。
- 深度模式的 `reasoning_delta` 是模型推理增量（非规范内容），前端放折叠面板并标注。
- 降级文案：生成服务不可用或校验失败 → `当前未提供归纳解读` + 条文原文；
  检索未命中 → `未检索到直接依据` + 最接近的条款。
- 降级必须如实暴露：`fallback_flag` / `degraded_flag` / `rerank_used`。
- 环境变量清单见 `.env.example`。
- 检索日志每轮记录：提问、召回块及所属条款、融合分、重排耗时、阈值判定、兜底与降级、推导数值，落本地 JSON Lines。
