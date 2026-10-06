"""pytest 全局夹具：仓库路径、语料路径与配置环境隔离。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from archrag.corpus.chunker import build_chunks
from archrag.corpus.models import ParsedStandard, Standard
from archrag.corpus.parser import parse_file
from archrag.corpus.standard_map import load_standard_map
from archrag.tokenizer import BgeM3TokenCounter

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = REPO_ROOT / "数据库上传资料"
BACKUP_MARKDOWN_DIR = REPO_ROOT.parent / "建筑规范" / "markdown"


@pytest.fixture()
def repo_root() -> Path:
    """仓库根目录。"""
    return REPO_ROOT


@pytest.fixture()
def corpus_dir(repo_root: Path) -> Path:
    """语料源目录；语料相关用例直接读这里的真实文件。"""
    return CORPUS_DIR


@pytest.fixture(scope="session")
def standard_map() -> dict[str, Standard]:
    """文件名 → 标准号/全称/实施日期。"""
    return load_standard_map(CORPUS_DIR / "规范标准号映射表.md")


@pytest.fixture(scope="session")
def parsed_corpus(standard_map: dict[str, Standard]) -> dict[str, ParsedStandard]:
    """5 份真实语料的解析结果，按文件名索引。"""
    return {
        name: parse_file(CORPUS_DIR / name, standard)
        for name, standard in standard_map.items()
    }


@pytest.fixture(scope="session")
def backup_markdown_dir() -> Path:
    """工作区外未规范化备份目录；不可用时跳过相关用例。"""
    if not BACKUP_MARKDOWN_DIR.is_dir():
        pytest.skip(f"工作区外备份不存在：{BACKUP_MARKDOWN_DIR}")
    return BACKUP_MARKDOWN_DIR


@pytest.fixture(scope="session")
def token_counter() -> BgeM3TokenCounter:
    """真实 bge-m3 tokenizer；模型不可用时跳过依赖它的用例。"""
    from archrag.config import load_settings

    counter = BgeM3TokenCounter(load_settings().embed_model)
    try:
        counter.count("测试")
    except Exception as exc:  # tokenizer 缺失或损坏时给出明确跳过原因
        pytest.skip(f"bge-m3 tokenizer 不可用：{exc}")
    return counter


@pytest.fixture(scope="session")
def chunks_by_standard(parsed_corpus, token_counter) -> dict[str, tuple]:
    """5 份真实语料的切块结果，按文件名索引。"""
    return {
        name: build_chunks(parsed, version="test-version", count_tokens=token_counter.count)
        for name, parsed in parsed_corpus.items()
    }


@pytest.fixture(scope="session")
def embedder():
    """真实 bge-m3 嵌入模型（GPU 不可用时跳过）。"""
    import torch

    if not torch.cuda.is_available():
        pytest.skip("CUDA 不可用")
    from archrag.config import load_settings
    from archrag.retrieval.embedder import BgeM3Embedder

    instance = BgeM3Embedder(load_settings().embed_model)
    instance.load()
    return instance


@pytest.fixture(scope="session")
def reranker():
    """真实 bge-reranker（GPU 不可用时跳过）。"""
    import torch

    if not torch.cuda.is_available():
        pytest.skip("CUDA 不可用")
    from archrag.config import load_settings
    from archrag.retrieval.reranker import BgeReranker

    instance = BgeReranker(load_settings().rerank_model)
    instance.load()
    return instance


@pytest.fixture()
def milvus_factory():
    """创建受保护的测试 collection；默认跳过，需显式开启。

    运行方式：`$env:ARCHRAG_MILVUS_TESTS='1'; $env:MILVUS_URI='http://localhost:19531'; pytest`
    这样避免误连到共用端口上别的项目实例。服务不可达或实例含非本项目
    collection 时也会跳过。
    """
    from archrag.config import load_settings
    from archrag.store.milvus import MilvusStore

    def create(collection: str = "archrag_test") -> MilvusStore:
        if os.environ.get("ARCHRAG_MILVUS_TESTS") != "1":
            pytest.skip("未设置 ARCHRAG_MILVUS_TESTS=1，跳过 Milvus 集成测试")
        settings = load_settings()
        store = MilvusStore(settings.milvus_uri, collection)
        if not store.is_available():
            pytest.skip(f"Milvus 不可达：{settings.milvus_uri}")
        existing = set(store._get_client().list_collections())
        foreign = {
            name
            for name in existing
            if not (name.startswith("archrag_") or name.startswith("arch_regulations"))
        }
        if foreign:
            pytest.skip(
                f"Milvus 实例含非本项目 collection {sorted(foreign)[:3]}，"
                "疑似共用实例，跳过以免污染"
            )
        store.drop()
        store.ensure_collection()
        return store

    return create


@pytest.fixture()
def milvus_store(milvus_factory):
    """测试用 Milvus collection，用后销毁。"""
    store = milvus_factory("archrag_test")
    yield store
    store.drop()
