# 运维与排障

开发与部署同机：Windows 11 + Docker standalone Milvus + conda 环境 `archrag`（Python 3.11.17，路径 `D:\Ai software\anaconda3\envs\archrag`）。

## 手册索引

| 场景 | 读哪里 |
|---|---|
| 启动/停止服务、torch 安装、健康自检 | `startup.md` |
| Windows 开机自启（任务计划） | `windows-autostart.md` |
| 语料入库、普查、Milvus 重建 | `ingest.md` |
| 词表候选 → 人工审核 → 入库 | `lexicon.md` |
| 备份与恢复演练 | `backup-restore.md` |
| 常见故障处置 | `troubleshooting.md` |
| 上线两周后的复盘抽查 | `postlaunch-review.md` |

## 一分钟速查

1. `docker compose up -d`（等 `milvus-standalone` healthy）。
2. `cd project/frontend; npm run build`（dist 变动时）。
3. `& "D:\Ai software\anaconda3\envs\archrag\python.exe" -m uvicorn archrag.api.app:app --host 127.0.0.1 --port 8000 --workers 1`
4. `GET /api/health` 直到 `ready=true`，浏览器打开 `http://127.0.0.1:8000`。
5. 停止：后端 Ctrl+C；`docker compose down` 释放 Milvus 内存。

**两条硬约束**：模型常驻进程必须 `workers=1`（多 worker 会被拒绝启动）；用「运行」而不是「调试」，调试器挂起线程会破坏 CUDA context。
