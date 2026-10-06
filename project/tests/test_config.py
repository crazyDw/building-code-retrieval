"""Settings 工厂的行为测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from archrag.config import ENV_KEYS, REPO_ROOT, Settings, load_settings
from archrag.errors import ConfigError

# 与 .env.example 一一对应的示例值：每个键都必须能被 load_settings 读到。
ENV_EXAMPLE_VALUES: dict[str, str] = {
    "DEEPSEEK_API_KEY": "sk-test-only",
    "BASE_URL": "https://example.invalid",
    "MODEL": "test-model",
    "REASONING_EFFORT": "high",
    "EMBED_MODEL": "test-embed-model",
    "RERANK_ENABLED": "false",
    "RERANK_MODEL": "test-rerank-model",
    "RERANK_MAX_TOKENS": "128",
    "CHUNK_MAX_TOKENS": "129",
    "CONTEXT_MAX_TOKENS": "4096",
    "TOPK_DENSE": "11",
    "TOPK_SPARSE": "12",
    "RERANK_CANDIDATES": "13",
    "TOP_N_DEFAULT": "6",
    "RERANK_CANDIDATES_DEEP": "14",
    "TOP_N_DEEP": "7",
    "REF_EXPAND_LIMIT": "3",
    "SCORE_THRESHOLD": "0.25",
    "MILVUS_URI": "http://localhost:19530",
    "MILVUS_COLLECTION": "test_collection",
    "SQLITE_PATH": "./data/test.sqlite",
    "STANDARD_MAP_PATH": "./数据库上传资料/规范标准号映射表.md",
    "DEVICE": "cpu",
    "DEV_MODE": "false",
}

EXPECTED_FIELDS: dict[str, tuple[str, object]] = {
    "DEEPSEEK_API_KEY": ("deepseek_api_key", "sk-test-only"),
    "BASE_URL": ("base_url", "https://example.invalid"),
    "MODEL": ("model", "test-model"),
    "REASONING_EFFORT": ("reasoning_effort", "high"),
    "EMBED_MODEL": ("embed_model", "test-embed-model"),
    "RERANK_ENABLED": ("rerank_enabled", False),
    "RERANK_MODEL": ("rerank_model", "test-rerank-model"),
    "RERANK_MAX_TOKENS": ("rerank_max_tokens", 128),
    "CHUNK_MAX_TOKENS": ("chunk_max_tokens", 129),
    "CONTEXT_MAX_TOKENS": ("context_max_tokens", 4096),
    "TOPK_DENSE": ("topk_dense", 11),
    "TOPK_SPARSE": ("topk_sparse", 12),
    "RERANK_CANDIDATES": ("rerank_candidates", 13),
    "TOP_N_DEFAULT": ("top_n_default", 6),
    "RERANK_CANDIDATES_DEEP": ("rerank_candidates_deep", 14),
    "TOP_N_DEEP": ("top_n_deep", 7),
    "REF_EXPAND_LIMIT": ("ref_expand_limit", 3),
    "SCORE_THRESHOLD": ("score_threshold", 0.25),
    "MILVUS_URI": ("milvus_uri", "http://localhost:19530"),
    "MILVUS_COLLECTION": ("milvus_collection", "test_collection"),
    "SQLITE_PATH": ("sqlite_path", REPO_ROOT / "data" / "test.sqlite"),
    "STANDARD_MAP_PATH": (
        "standard_map_path",
        REPO_ROOT / "数据库上传资料" / "规范标准号映射表.md",
    ),
    "DEVICE": ("device", "cpu"),
    "DEV_MODE": ("dev_mode", False),
}


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """配置用例只依赖自己显式传入的值，不受外部环境变量影响。"""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _load(
    tmp_path: Path,
    *,
    env_text: str = "",
    environ: dict[str, str] | None = None,
) -> Settings:
    env_file = tmp_path / ".env"
    env_file.write_text(env_text, encoding="utf-8")
    return load_settings(env_file=env_file, environ=environ or {})


def _as_env_text(values: dict[str, str]) -> str:
    return "\n".join(f"{key}={value}" for key, value in values.items())


def _env_example_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        keys.add(stripped.split("=", 1)[0].strip())
    return keys


def test_env_example_file_matches_registered_keys(repo_root: Path) -> None:
    """新增 .env 键时必须同步 ENV_KEYS，否则用例失败。"""
    assert _env_example_keys(repo_root / ".env.example") == set(ENV_KEYS)


def test_every_key_is_read_into_settings(tmp_path: Path) -> None:
    assert set(ENV_EXAMPLE_VALUES) == set(ENV_KEYS)
    settings = _load(tmp_path, env_text=_as_env_text(ENV_EXAMPLE_VALUES))
    for key, (attribute, expected) in EXPECTED_FIELDS.items():
        assert getattr(settings, attribute) == expected, f"{key} 未被读入 {attribute}"


def test_defaults_resolve_paths_against_repo_root(tmp_path: Path) -> None:
    settings = _load(tmp_path)
    assert settings.dev_mode is False
    assert settings.milvus_collection == "arch_regulations"
    assert settings.sqlite_path == REPO_ROOT / "data" / "arch_regulations.sqlite"
    assert (
        settings.standard_map_path
        == REPO_ROOT / "数据库上传资料" / "规范标准号映射表.md"
    )


def test_default_standard_map_path_exists(tmp_path: Path) -> None:
    settings = _load(tmp_path)
    assert settings.standard_map_path.is_file()


def test_quoted_values_are_unquoted(tmp_path: Path) -> None:
    settings = _load(tmp_path, env_text='EMBED_MODEL="D:/Ai software/models/bge-m3"\n')
    assert settings.embed_model == "D:/Ai software/models/bge-m3"


def test_real_dotenv_model_paths_are_unquoted(repo_root: Path) -> None:
    env_path = repo_root / ".env"
    if not env_path.is_file():
        pytest.skip(".env 不存在")
    settings = load_settings(environ={})
    assert '"' not in settings.embed_model
    assert '"' not in settings.rerank_model


def test_relative_paths_do_not_depend_on_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = _load(tmp_path, env_text="SQLITE_PATH=./data/alt.sqlite\n")
    assert settings.sqlite_path == REPO_ROOT / "data" / "alt.sqlite"


@pytest.mark.parametrize(
    ("env_text", "expected_collection", "expected_sqlite_name"),
    [
        ("DEV_MODE=true\n", "arch_regulations_dev", "arch_regulations_dev.sqlite"),
        ("DEV_MODE=false\n", "arch_regulations", "arch_regulations.sqlite"),
        (
            "DEV_MODE=true\nMILVUS_COLLECTION=demo_dev\nSQLITE_PATH=./data/demo_dev.sqlite\n",
            "demo_dev",
            "demo_dev.sqlite",
        ),
    ],
)
def test_dev_mode_rewrites_data_source(
    tmp_path: Path, env_text: str, expected_collection: str, expected_sqlite_name: str
) -> None:
    settings = _load(tmp_path, env_text=env_text)
    assert settings.milvus_collection == expected_collection
    assert settings.sqlite_path.name == expected_sqlite_name


def test_environ_overrides_env_file(tmp_path: Path) -> None:
    settings = _load(tmp_path, env_text="MODEL=from-file\n", environ={"MODEL": "from-environ"})
    assert settings.model == "from-environ"


def test_empty_values_fall_back_to_defaults(tmp_path: Path) -> None:
    settings = _load(tmp_path, env_text="DEV_MODE=\nMODEL=\n")
    assert settings.dev_mode is False
    assert settings.model == "deepseek-flash"


@pytest.mark.parametrize(
    "env_text",
    [
        "RERANK_MAX_TOKENS=abc\n",
        "TOPK_DENSE=0\n",
        "SCORE_THRESHOLD=high\n",
        "DEV_MODE=maybe\n",
    ],
)
def test_invalid_values_raise_config_error(tmp_path: Path, env_text: str) -> None:
    key = env_text.split("=", 1)[0]
    with pytest.raises(ConfigError, match=key):
        _load(tmp_path, env_text=env_text)


def test_require_deepseek_api_key_raises_without_value(tmp_path: Path) -> None:
    settings = _load(tmp_path)
    with pytest.raises(ConfigError):
        settings.require_deepseek_api_key()


def test_require_deepseek_api_key_returns_configured_value(tmp_path: Path) -> None:
    settings = _load(tmp_path, env_text="DEEPSEEK_API_KEY=sk-test-only\n")
    assert settings.require_deepseek_api_key() == "sk-test-only"
