"""项目异常基类与分层异常。

上层按类型决定降级方式；配置类错误没有降级路径，直接启动失败并明确报错。
"""

from __future__ import annotations


class ArchRagError(Exception):
    """本项目全部异常的基类。"""


class ConfigError(ArchRagError):
    """配置缺失或取值非法。消息中不得包含密钥值。"""


class CorpusError(ArchRagError):
    """语料读取、解析或结构校验失败。"""


class ChunkError(ArchRagError):
    """切块结果违反长度或归属约束。"""


class StoreError(ArchRagError):
    """SQLite schema、事务或版本规则失败。"""


class ModelLoadError(ArchRagError):
    """模型加载后未落在预期设备/精度，或加载失败。"""


class ReindexError(ArchRagError):
    """向量索引重建或校验失败。"""


class GenerationError(ArchRagError):
    """生成模型调用失败（超时、断网、无 key 等）。"""
