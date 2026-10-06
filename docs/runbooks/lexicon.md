# 词表审核流程

> 当前状态（2026-10-06）：500 条候选已人工筛出 **281 条**完整领域词，导入 `lexicon`（`status=approved`）；
> 生成层系统提示词的术语表取分数前 50 条。检索侧未变（`query_expansion` 仍为 15 条别名 + 58 条符号映射）。
> 若要让词表影响召回，需按第 2 步补 `approved_expansions.txt` 后重跑 `import_lexicon.py`。

## 1. 生成候选

```powershell
& "D:\Ai software\anaconda3\envs\archrag\python.exe" -X utf8 project\scripts\extract_lexicon.py
```

产物（`data/lexicon/`）：

- `candidates.json`：统计共现 + 表格词 + 符号映射候选（默认 500 条）；
- `review.md`：人工勾选清单；别名与符号映射已自动入库，无需勾选。

## 2. 人工勾选

打开 `data/lexicon/review.md`，把要保留的条目 `- [ ]` 改成 `- [x]`，
把勾选结果整理成 `data/lexicon/approved_terms.txt`（一行一个词）；
需要补充的条件词写入 `data/lexicon/approved_expansions.txt`（一行 `原词=目标词`，如 `喷淋=自动灭火系统`）。

## 3. 入库

```powershell
& "D:\Ai software\anaconda3\envs\archrag\python.exe" -X utf8 project\scripts\import_lexicon.py
```

术语写入 `lexicon`（`status=approved`），扩展写入 `query_expansion`，
下一轮检索的「同义词追加」会自动使用（系统提示词的术语表取 approved 前 50 条）。

## 4. 复核

- `sqlite3 data/arch_regulations.sqlite "SELECT COUNT(*) FROM lexicon WHERE status='approved';"`
- `approved_terms`：`store.approved_terms(50)` 应返回 50 条并按分数排序，会进入系统提示词 `<术语表>`；
- 问一个口语化问题，检索日志里看 `expanded_terms` 是否包含新增词。
