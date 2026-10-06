# 常见故障处置

| 现象 | 判据 | 处置 |
|---|---|---|
| 检索变慢、`rerank_used=false` | `/api/health` 显示 GPU 不可用 | 属预期降级，**不回退 CPU 重排**（需 10–25 s）；排查显存占用后重启 |
| 启动失败，日志含 `Milvus 不可达` | 启动时 Milvus 未就绪 | 先 `docker compose up -d` 等 healthy 再启动后端（fail fast，不提供半可用检索） |
| 运行中 chat 返回 `error` 事件 | `health.milvus_connected=false`、`reason_code=milvus_unavailable` | 恢复 Milvus 后重试；SQLite 未受影响 |
| 启动失败，模型加载报错 | 日志含 `OSError` / `ModelLoadError` | 核对 `EMBED_MODEL` / `RERANK_MODEL` 路径与显存；模型加载失败不允许半可用启动 |
| 内存吃紧 | Milvus 在 WSL2 内占 1.5–2 GB | 已设 `C:\Users\<用户>\.wslconfig`：`memory=6GB`、`processors=8`、`swapFile` 移到 D 盘；改动后需 `wsl --shutdown` 生效（Docker 会跟着重启） |
| 首字超 3 s | 检索日志里的重排耗时 | 按既定回调：候选 25 → 20、返回 10 → 8，复测并记录 |
| 端口被占（19530/9091 起不来） | `docker compose up -d` 报 port already allocated | `docker ps` 找占用容器；确认归属后再停对方或临时改用备用端口，不要直接往别人的 Milvus 写数据 |
| 脚本输出中文乱码 | 控制台显示乱码 | 命令加 `-X utf8` |
| Milvus 与 SQLite 不一致 | 对比条文数量 | 以 SQLite 为准，`rebuild_milvus.py` 重建索引 |
| 移动或重命名 conda 环境后命令失效 | `pytest` / `mypy` 等静默失败（退出码非 0、无输出） | pip 装的命令行脚本把解释器路径写死在 shebang 里。用各包的 `RECORD` 找出所有 `../../Scripts/` 条目，按**锁定的版本**逐个 `pip install --force-reinstall --no-deps` 重装（不锁版本会被装成最新版，可能破坏依赖） |
| 多 worker 启动被拒绝 | 启动日志 `模型常驻进程必须 workers=1` | 单进程加载两个模型是刻意约束（显存与预热）；保持 `--workers 1` |
