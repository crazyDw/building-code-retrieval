# 运维与排障

开发与部署同机：Windows 11 + Docker standalone Milvus + conda 环境 `archrag`（Python 3.11.17，路径 `D:\Ai software\anaconda3\envs\archrag`）。

## 启动顺序

1. 启动 Milvus：`docker compose up -d`（数据卷在 `D:\milvus-data`，仓库外）。
2. 启动后端：加载 bge-m3 与 bge-reranker-v2-m3，各跑一次空推理完成预热。
3. **预热完成前不接受请求**；就绪状态由 `/api/health` 暴露。
4. 启动前端。

## 常见处置

| 现象 | 判据 | 处置 |
|---|---|---|
| 检索变慢、`rerank_used=false` | `/api/health` 显示 GPU 不可用 | 属预期降级，**不回退 CPU 重排**（需 10–25 s）；排查显存占用后重启 |
| 内存吃紧 | Milvus 在 WSL2 内占 1.5–2 GB | 已设 `C:\Users\<用户>\.wslconfig`：`memory=6GB`、`processors=8`、`swapFile` 移到 D 盘；改动后需 `wsl --shutdown` 生效（Docker 会跟着重启） |
| 首字超 3 s | 检索日志里的重排耗时 | 按既定回调：候选 25 → 20、返回 10 → 8 |
| 脚本输出中文乱码 | 控制台显示乱码 | 命令加 `-X utf8` |
| Milvus 与 SQLite 不一致 | 对比条文数量 | 以 SQLite 为准，重建 Milvus 索引 |
| 移动或重命名 conda 环境后命令失效 | `pytest` / `mypy` 等静默失败（退出码非 0、无输出） | pip 装的命令行脚本把解释器路径写死在 shebang 里。用各包的 `RECORD` 找出所有 `../../Scripts/` 条目，按**锁定的版本**逐个 `pip install --force-reinstall --no-deps` 重装（不锁版本会被装成最新版，可能破坏依赖） |
| 显存不足 / 模型加载失败 | 启动日志 | 走降级路径并置 `degraded_flag`；就绪状态如实反映 |

## 入库

`POST /api/ingest` 单部规范入库，幂等。入库前先跑语料普查；**条号数量与连续性异常时阻断入库**。解析、切分、写入整体事务化，任一步失败全部回滚。

## 备份与恢复

三件套：`数据库上传资料/` 的 Markdown + SQLite 单文件 + Milvus 卷快照。SQLite 开启 WAL。

## 开发模式

`DEV_MODE=true` 跳过模型加载与预热，使用 `_dev` 后缀的 SQLite 与 Milvus collection，仅入库《民用建筑通用规范》。**其结果不得作为检索质量依据。**

模型常驻的进程用「运行」而非「调试」——调试器挂起线程会破坏 CUDA context。

## 上线后复盘

部署两周后，从未经筛选的检索日志中抽查 20 条真实提问。
