"""应用配置：从环境变量与仓库根 `.env` 构建 `Settings`。

D7：相对路径一律相对仓库根解析，不受启动目录影响。
D8：`DEV_MODE=true` 时数据源加 `_dev` 后缀，避免污染正式数据。

本模块不提供全局单例：入口显式调用 `load_settings()`，再把结果传给各层。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from archrag.errors import ConfigError

# config.py 位于 <仓库根>/project/src/archrag/，上溯三级即仓库根。
REPO_ROOT = Path(__file__).resolve().parents[3]

# .env 与 .env.example 的全部键（不含密钥值）。
ENV_KEYS: tuple[str, ...] = (
    "DEEPSEEK_API_KEY",
    "BASE_URL",
    "MODEL",
    "REASONING_EFFORT",
    "EMBED_MODEL",
    "RERANK_ENABLED",
    "RERANK_MODEL",
    "RERANK_MAX_TOKENS",
    "CHUNK_MAX_TOKENS",
    "CONTEXT_MAX_TOKENS",
    "TOPK_DENSE",
    "TOPK_SPARSE",
    "RERANK_CANDIDATES",
    "TOP_N_DEFAULT",
    "RERANK_CANDIDATES_DEEP",
    "TOP_N_DEEP",
    "REF_EXPAND_LIMIT",
    "SCORE_THRESHOLD",
    "MILVUS_URI",
    "MILVUS_COLLECTION",
    "SQLITE_PATH",
    "STANDARD_MAP_PATH",
    "DEVICE",
    "DEV_MODE",
)

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True, slots=True)
class Settings:
    """一次加载得到的不可变配置快照。"""

    repo_root: Path
    dev_mode: bool
    deepseek_api_key: str
    base_url: str
    model: str
    reasoning_effort: str
    embed_model: str
    rerank_enabled: bool
    rerank_model: str
    rerank_max_tokens: int
    chunk_max_tokens: int
    context_max_tokens: int
    topk_dense: int
    topk_sparse: int
    rerank_candidates: int
    top_n_default: int
    rerank_candidates_deep: int
    top_n_deep: int
    ref_expand_limit: int
    score_threshold: float
    milvus_uri: str
    milvus_collection: str
    sqlite_path: Path
    standard_map_path: Path
    device: str

    def require_deepseek_api_key(self) -> str:
        """返回 DeepSeek 密钥；未配置时抛 `ConfigError`，异常消息不回显任何值。"""
        if not self.deepseek_api_key:
            raise ConfigError("DEEPSEEK_API_KEY 未配置：请写入仓库根 .env")
        return self.deepseek_api_key


def load_settings(
    env_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    """构建配置。

    - `env_file` 默认仓库根 `.env`，文件不存在时全部走默认值；
    - `environ` 默认 `os.environ`，便于测试注入；
    - 优先级：`environ` > `env_file` > 代码默认值；空字符串视为未设置。
    """
    file_path = REPO_ROOT / ".env" if env_file is None else Path(env_file)
    env: Mapping[str, str] = os.environ if environ is None else environ
    file_values: dict[str, str] = {}
    if file_path.is_file():
        raw_values = dotenv_values(file_path, encoding="utf-8")
        file_values = {key: value for key, value in raw_values.items() if value is not None}

    def get(key: str, default: str) -> str:
        value = env.get(key, "").strip()
        if not value:
            value = file_values.get(key, "").strip()
        return value or default

    dev_mode = _parse_bool(get("DEV_MODE", "false"), "DEV_MODE")
    collection = get("MILVUS_COLLECTION", "arch_regulations")
    sqlite_path = _resolve_path(get("SQLITE_PATH", "./data/arch_regulations.sqlite"))
    if dev_mode:
        collection = collection if collection.endswith("_dev") else f"{collection}_dev"
        sqlite_path = _with_dev_suffix(sqlite_path)

    return Settings(
        repo_root=REPO_ROOT,
        dev_mode=dev_mode,
        deepseek_api_key=get("DEEPSEEK_API_KEY", ""),
        base_url=get("BASE_URL", "https://api.deepseek.com"),
        model=get("MODEL", "deepseek-flash"),
        reasoning_effort=get("REASONING_EFFORT", "low"),
        embed_model=get("EMBED_MODEL", "BAAI/bge-m3"),
        rerank_enabled=_parse_bool(get("RERANK_ENABLED", "true"), "RERANK_ENABLED"),
        rerank_model=get("RERANK_MODEL", "BAAI/bge-reranker-v2-m3"),
        rerank_max_tokens=_parse_int(
            get("RERANK_MAX_TOKENS", "256"), "RERANK_MAX_TOKENS", minimum=1
        ),
        chunk_max_tokens=_parse_int(get("CHUNK_MAX_TOKENS", "256"), "CHUNK_MAX_TOKENS", minimum=1),
        context_max_tokens=_parse_int(
            get("CONTEXT_MAX_TOKENS", "12000"), "CONTEXT_MAX_TOKENS", minimum=1
        ),
        topk_dense=_parse_int(get("TOPK_DENSE", "30"), "TOPK_DENSE", minimum=1),
        topk_sparse=_parse_int(get("TOPK_SPARSE", "30"), "TOPK_SPARSE", minimum=1),
        rerank_candidates=_parse_int(
            get("RERANK_CANDIDATES", "25"), "RERANK_CANDIDATES", minimum=1
        ),
        top_n_default=_parse_int(get("TOP_N_DEFAULT", "10"), "TOP_N_DEFAULT", minimum=1),
        rerank_candidates_deep=_parse_int(
            get("RERANK_CANDIDATES_DEEP", "40"), "RERANK_CANDIDATES_DEEP", minimum=1
        ),
        top_n_deep=_parse_int(get("TOP_N_DEEP", "16"), "TOP_N_DEEP", minimum=1),
        ref_expand_limit=_parse_int(
            get("REF_EXPAND_LIMIT", "5"), "REF_EXPAND_LIMIT", minimum=1
        ),
        score_threshold=_parse_float(get("SCORE_THRESHOLD", "0.0"), "SCORE_THRESHOLD"),
        milvus_uri=get("MILVUS_URI", "http://localhost:19530"),
        milvus_collection=collection,
        sqlite_path=sqlite_path,
        standard_map_path=_resolve_path(
            get("STANDARD_MAP_PATH", "./数据库上传资料/规范标准号映射表.md")
        ),
        device=get("DEVICE", "cuda"),
    )


def _parse_bool(raw: str, key: str) -> bool:
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise ConfigError(f"{key} 取值非法：只接受 true/false（含 1/0、yes/no、on/off）")


def _parse_int(raw: str, key: str, *, minimum: int | None = None) -> int:
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{key} 必须是整数") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"{key} 必须不小于 {minimum}")
    return value


def _parse_float(raw: str, key: str) -> float:
    try:
        return float(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{key} 必须是数字") from exc


def _resolve_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


def _with_dev_suffix(path: Path) -> Path:
    if path.stem.endswith("_dev"):
        return path
    return path.with_name(f"{path.stem}_dev{path.suffix}")
