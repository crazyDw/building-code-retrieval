---
name: create-module
description: 在 project/src 下新增或改动业务模块时使用。约束模块边界、命名、类型注解与配套测试；只改文档、语料或 harness 配置时不适用。
---

# 新增业务模块

`project/src` 是业务代码根目录（PyCharm 以 `project/` 为项目根）。动手前先确认模块属于哪一层，不要把 harness 层的职责（语料规范化、工具链配置）搬进业务代码。

## 动手前

1. 读 `AGENTS.md` 的「二、铁律」——解析、检索、答案相关的约束违反即返工。
2. 读 `docs/python-rules/` 的编码规范。
3. 在 `docs/architecture/` 确认模块边界；归属不清楚就先问，不要新建一个职责模糊的模块。

## 约定

- 一个模块一件事；不要建 `utils` 这类无归属的收容模块。
- 对外函数写类型注解；公共接口用 docstring 说明入参、返回值与可能抛出的异常。
- 配置一律从环境变量读取（键名见 `.env.example`），代码里不硬编码路径、密钥与阈值。
- 日志用标准库 `logging` 输出 JSON Lines，不用 `print`。
- 依赖单向：上层可调下层，下层不得反向导入。

## 验证

- `ruff check .` 与 `mypy project/src` 干净。
- 新增行为配对应测试，按 `create-test` 技能写。
- 若改动了对外接口，同步更新 `docs/api/`。
