"""bge-m3 与 bge-reranker 的设备、精度与输出测试。"""

from __future__ import annotations

import pytest
import torch

pytestmark = pytest.mark.gpu


def test_cuda_runtime_version() -> None:
    assert torch.cuda.is_available()
    assert torch.version.cuda == "12.6"


def test_embedder_output_shape_and_device(embedder) -> None:
    batch = embedder.encode(["楼梯踏步的最小宽度", "住宅建筑层高不应低于2.40m"])
    assert len(batch.dense) == 2
    assert all(len(vector) == 1024 for vector in batch.dense)
    assert all(weights for weights in batch.sparse)
    assert embedder.memory_bytes >= 900 * 1024**2


def test_reranker_scores_relevant_pair_higher(reranker) -> None:
    scores = reranker.compute_score(
        [
            ("楼梯踏步宽度", "楼梯踏步的最小宽度不应小于0.26m"),
            ("楼梯踏步宽度", "住宅建筑层高不应低于2.40m"),
        ]
    )
    assert len(scores) == 2
    assert scores[0] > scores[1]


def test_reranker_truncates_long_input(reranker) -> None:
    scores = reranker.compute_score([("楼梯", "踏步" * 5000)])
    assert len(scores) == 1
    assert isinstance(scores[0], float)


def test_two_models_fit_expected_memory(embedder, reranker) -> None:
    assert embedder.memory_bytes >= 900 * 1024**2
    assert reranker.memory_bytes - embedder.memory_bytes >= 800 * 1024**2
    assert reranker.memory_bytes <= 3 * 1024**3
