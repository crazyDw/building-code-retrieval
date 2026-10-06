# 备份与恢复

三件套：`数据库上传资料/` 的 Markdown（源）+ SQLite 单文件（唯一真相源）+ Milvus 卷快照（派生，可重建）。

## 备份

```powershell
# 1) SQLite：先 checkpoint，再复制单文件
& "D:\Ai software\anaconda3\envs\archrag\python.exe" -X utf8 -c `
  "import sqlite3; c=sqlite3.connect(r'data/arch_regulations.sqlite'); print(c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone())"
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
New-Item -ItemType Directory -Force "data\backups\$stamp" | Out-Null
Copy-Item data\arch_regulations.sqlite "data\backups\$stamp\arch_regulations.sqlite"

# 2) 语料哈希清单（确认语料未变）
Get-ChildItem '数据库上传资料\*.md' | ForEach-Object { "$($_.Name)  $((Get-FileHash $_.FullName -Algorithm SHA256).Hash)" } |
  Set-Content "data\backups\$stamp\corpus-sha256.txt" -Encoding UTF8

# 3) Milvus 卷快照：先停容器再复制，避免半写状态
docker compose down
robocopy D:\milvus-data "data\backups\$stamp\milvus-data" /E
```

## 恢复

**首选：从 SQLite 重建 Milvus（不依赖卷快照）**

```powershell
docker compose up -d           # 等 healthy
& "D:\Ai software\anaconda3\envs\archrag\python.exe" -X utf8 project\scripts\rebuild_milvus.py
# 输出应分标准核对：110 / 125 / 135 / 147 / 184，合计 701
```

**卷快照恢复（需要保留旧索引时）**

```powershell
docker compose down
robocopy "data\backups\<stamp>\milvus-data" D:\milvus-data /E
docker compose up -d
```

## 演练记录（2026-10-06，M8）

- WAL checkpoint： `(0, 0, 0)`；`PRAGMA integrity_check` = `ok`；SQLite 554 条 / 701 块。
- 备份：`data/backups/20261006-031236/`（SQLite 1.4 MB + 语料 SHA256 + Milvus 卷快照 218.9 MB）。
- 恢复：drop collection 后从 SQLite 全量重建，实体数 110/125/135/147/184 = 701；检索「楼梯踏步最小宽度」Top1 命中 `GB 55031-2022_5.3.9`，`rerank_used=true`。
- 证据：`data/acceptance/backup_restore.md`。
