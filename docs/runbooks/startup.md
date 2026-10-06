# 启动与停止

## 换机器从零搭建

```powershell
conda create -n archrag python=3.11
conda activate archrag

# torch 必须显式指定 cu126 索引；装成 CPU 版不会报错，只会让 cuda.is_available()=False
pip install torch --index-url https://download.pytorch.org/whl/cu126

pip install -e project

cd project/frontend
npm install
npm run build
```

GPU 自检（应为 `True` 且设备名为 RTX 4070 Laptop）：

```powershell
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

## 每次启动

1. 启动 Milvus：`docker compose up -d`；等到健康：
   `docker inspect --format '{{.State.Health.Status}}' milvus-standalone` 输出 `healthy`。
2. 构建前端（`project/frontend/dist` 不存在或前端有改动时）：
   `cd project/frontend; npm run build; cd ../..`
3. 启动后端（**必须 `--workers 1`**；应用会拒绝多 worker 启动）：

```powershell
& "D:\Ai software\anaconda3\envs\archrag\python.exe" -m uvicorn archrag.api.app:app --host 127.0.0.1 --port 8000 --workers 1
```

启动时加载 bge-m3 与 bge-reranker-v2-m3 并各跑一次空推理预热（约 30–60 s，显存约 2.1 GB）。
**预热完成前 `/api/chat` 返回 503**；`GET /api/health` 的 `ready=true` 才对外可用。

4. 浏览器打开 `http://127.0.0.1:8000`。

## 停止

- 后端：终端 `Ctrl+C`；若在后台运行，用 `Stop-Process -Id <pid>`。
- Milvus：`docker compose down`（释放约 1.5–2 GB 内存；SQLite 是真相源，可随时重建）。

## 自检清单

```powershell
(Invoke-RestMethod http://127.0.0.1:8000/api/health) | ConvertTo-Json
```

- `ready=true`、`milvus_connected=true`、`device=cuda:0`；
- 提一个已知问题（如「公共楼梯踏步的最小宽度和最大高度是多少？」）能看到推导块 + 原文块 + 引用；
- `logs/archrag.log` 有 JSON Lines 检索日志，且不含密钥。

## 开发模式

`DEV_MODE=true` 跳过模型加载与预热、只用 `_dev` SQLite 与 LIKE 检索，界面/health 会显式标注 DEV。**其结果不得作为检索质量依据。**
