# 上线后复盘预案

目标：部署两周后，从未经筛选的真实检索日志中抽查 20 条提问，确认答案形态与降级行为符合预期。

## 取样

日志在 `logs/archrag.log`（JSON Lines，`event=retrieval`）。随机抽 20 条：

```powershell
Get-Content logs\archrag.log | Where-Object { $_ -match '"event":"retrieval"' } |
  Get-Random -Count 20 | Set-Content data\acceptance\postlaunch-sample.jsonl -Encoding UTF8
```

## 逐条核对

对每条记录检查：

1. 提问与 `top_clauses` 是否相关；`not_found` 是否合理（不该把明确问题判成未命中）；
2. `rerank_used` / `degraded` 与当时健康状态是否一致；
3. `numbers` 是否被带入生成层；生成答案的推导是否写明输入值；
4. 是否存在禁止措辞（满足规范 / 合规 / 合格）或把表格「注：」当依据的情况。

结果写 `data/acceptance/postlaunch-review-<日期>.md`，逐条给出：
`问题 → 命中条款 → 结论（正常/降级/未命中）→ 是否需调整（阈值/词表/提示词）`。

## 后续动作

- 误判未命中集中出现 → 用新日志重跑阈值标定（`eval_retrieval.py` + `calibrate_threshold.py`）；
- 口语词命中差 → 走 `lexicon.md` 补充审核词表；
- 禁止措辞或注被当依据 → 检查 `validate.py` 规则并补测试。
