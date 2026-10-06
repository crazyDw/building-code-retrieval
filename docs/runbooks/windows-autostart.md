# Windows 开机自启（任务计划）

目标：开机后自动启动 Milvus 与后端服务（前端由后端静态挂载，不需要单独进程）。

## 前置

- Docker Desktop 设置为「登录时启动」；
- 服务账号能读取仓库与 `D:\milvus-data`。

## 任务计划配置

1. 任务计划程序 → 创建任务（不是「基本任务」）。
2. **常规**：勾选「不管用户是否登录都要运行」需要保存密码；或选择「只在用户登录时运行」。
3. **触发器**：登录时（或启动时），延迟 2 分钟，给 Docker Desktop 留启动时间。
4. **操作 1（Milvus）**：
   - 程序：`C:\Program Files\Docker\Docker\resources\bin\docker.exe`（或 PATH 中的 `docker`）
   - 参数：`compose up -d`
   - 起始于：`D:\AiProject\CodexProject\建筑规范智能问答系统`
5. **操作 2（后端）**：
   - 程序：`D:\Ai software\anaconda3\envs\archrag\python.exe`
   - 参数：`-X utf8 -m uvicorn archrag.api.app:app --host 127.0.0.1 --port 8000 --workers 1`
   - 起始于：`D:\AiProject\CodexProject\建筑规范智能问答系统`
6. **设置**：取消「如果任务运行时间超过以下时间，停止任务」；勾选「如果任务失败，按以下频率重新启动」。

## 验证

```powershell
schtasks /Run /TN "ArchRag"
Start-Sleep -Seconds 90
(Invoke-RestMethod http://127.0.0.1:8000/api/health) | ConvertTo-Json -Compress
```

`ready=true` 即成功。日志：`logs/archrag.log` 与任务计划历史记录。

## 停止

- 临时：任务计划程序 → 结束任务；并 `docker compose down`。
- 交付建议：任务名统一为 `ArchRag`，参数变化时同步本文档。
