# Python 通用约束

适用于 `project/src` 与 `project/tests`。工具配置在根目录 `pyproject.toml`（ruff / mypy / pytest 的唯一事实来源）。

## 环境与依赖

- Python 3.11。conda 只负责建环境与 Python 版本，所有包走 pip。
- 运行依赖声明在 `project/pyproject.toml`；harness 工具配置在根目录 `pyproject.toml`，两者不要混。
- `torch` 必须显式指定 cu126 索引安装，否则会静默装成 CPU 版。

## 编码

- 缩进 4 空格；行宽 100；格式化与静态检查都交给 `ruff`。
- 命名：模块/函数/变量 `snake_case`，常量 `UPPER_SNAKE`，类 `PascalCase`，内部实现加 `_` 前缀。
- 导入：绝对导入；标准库 / 三方库 / 本项目 三组，组间空行，排序交给 ruff 的 isort 规则。
- 类型：公共函数与方法的参数、返回值必须注解；mypy 已开 `disallow_untyped_defs`。
- 路径：统一用 `pathlib.Path`，不做字符串拼接。
- 数据结构：优先 `dataclass`；容器元素类型写清楚，不用裸 `dict`。

## 错误与日志

- 不写裸 `except`；捕获后要么补偿、要么带上上下文重新抛出。
- 自定义异常集中在项目内的异常基类之下，便于上层按类型降级。
- 日志用标准库 `logging`，输出 **JSON Lines**；不要用 `print`。
- 日志正文用参数化写法（`logger.info("hit %s", clause_id)`），不要 f-string 拼。

## 配置与副作用

- 配置一律读环境变量，键名见 `.env.example`；代码里不硬编码路径、密钥、阈值。
- 不在导入期做重活（加载模型、连库、起线程）——预热由启动流程负责，便于测试与 DEV_MODE。
- 资源成对：文件、连接、事务都要有对应的关闭与回滚路径。

## 领域相关的硬约束

- 条号比较必须用**数值分量**，字符串排序会把 `5.3.10` 排到 `5.3.9` 前面。
- 解析器不改写语料源文件；标题内的版式空格在内存中归一化。
- 块长按条文**正文**计量，不含其引用的表格。
