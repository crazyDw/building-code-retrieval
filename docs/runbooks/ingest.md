# 语料入库与索引重建

## 1. 先普查（新增/更新语料后必跑）

普查脚本属于 `normalize-regulation-md` 技能，显式传入 5 份语料，**不要把映射表当语料**：

```powershell
& "D:\Ai software\anaconda3\envs\archrag\python.exe" -X utf8 `
  .agents\skills\normalize-regulation-md\scripts\scan_structure.py `
  数据库上传资料\民用建筑通用规范.md 数据库上传资料\住宅项目规范.md `
  数据库上传资料\钢结构通用规范.md 数据库上传资料\混凝土结构通用规范.md `
  数据库上传资料\砌体结构通用规范.md
```

标记异常只报告；**条号数量与连续性异常会阻断入库**（`ingest_corpus.py` 会自动调用同一脚本）。

## 2. 入库

```powershell
# 一次入库 5 份并重建 Milvus
& "D:\Ai software\anaconda3\envs\archrag\python.exe" -X utf8 project\scripts\ingest_corpus.py

# 只入库单份
... ingest_corpus.py --file 民用建筑通用规范.md

# 只写 SQLite（不重建 Milvus）
... ingest_corpus.py --skip-milvus

# 不入库，仅重建 Milvus
... ingest_corpus.py --reindex-only
```

也可以走 `POST /api/ingest`（单部、幂等；正式模式要求模型已预热，否则 503）。

## 3. 规则

- SQLite 是唯一真相源；Milvus 是纯派生，可随时用 `project/scripts/rebuild_milvus.py` 全量重建。
- 同一标准号只允许一个现行版：同版本重复入库是幂等替换；内容变化会被拒绝（HTTP 409 `version_conflict`）。
- 解析、切分、写入整体事务化，任一步失败全部回滚。
- 新增标准：先把文件放进 `数据库上传资料/`，在 `规范标准号映射表.md` 补一行，再按上面流程普查 + 入库。
