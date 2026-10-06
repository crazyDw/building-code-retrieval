#!/usr/bin/env python3
"""生成层真实 API 冒烟：默认与深度各 1 次，记录首字与推理增量。"""

from __future__ import annotations

import argparse
import json
import sys
import time

from archrag.config import REPO_ROOT, load_settings
from archrag.generation.client import DeepSeekClient
from archrag.generation.service import stream_answer
from archrag.retrieval.embedder import BgeM3Embedder
from archrag.retrieval.pipeline import PipelineConfig, retrieve
from archrag.retrieval.reranker import BgeReranker
from archrag.store.milvus import MilvusStore
from archrag.store.sqlite import SqliteStore
from archrag.tokenizer import BgeM3TokenCounter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成层冒烟（真实 DeepSeek API）")
    parser.add_argument("--question", default="公共楼梯踏步的最小宽度和最大高度是多少？")
    args = parser.parse_args(argv)

    settings = load_settings()
    store = SqliteStore(settings.sqlite_path)
    milvus = MilvusStore(settings.milvus_uri, settings.milvus_collection)
    embedder = BgeM3Embedder(settings.embed_model)
    reranker = BgeReranker(settings.rerank_model)
    counter = BgeM3TokenCounter(settings.embed_model)
    client = DeepSeekClient(settings)
    config = PipelineConfig.from_settings(settings)

    results = {}
    for label, deep in (("default", False), ("deep", True)):
        retrieval = retrieve(
            args.question,
            store=store,
            milvus=milvus,
            embedder=embedder,
            reranker=reranker,
            config=config,
            deep=deep,
            count_tokens=counter.count,
        )
        started = time.monotonic()
        first_token_ms = None
        reasoning_pieces = 0
        derivation_pieces = 0
        done = None
        for event in stream_answer(
            args.question,
            retrieval=retrieval,
            client=client,
            store=store,
            count_tokens=counter.count,
            deep=deep,
        ):
            if event.kind == "reasoning":
                reasoning_pieces += 1
                if first_token_ms is None:
                    first_token_ms = round((time.monotonic() - started) * 1000, 1)
            elif event.kind == "derivation":
                derivation_pieces += 1
                if first_token_ms is None:
                    first_token_ms = round((time.monotonic() - started) * 1000, 1)
            elif event.kind == "done":
                done = event.data
        results[label] = {
            "question": args.question,
            "first_token_ms": first_token_ms,
            "total_ms": round((time.monotonic() - started) * 1000, 1),
            "reasoning_pieces": reasoning_pieces,
            "derivation_pieces": derivation_pieces,
            "fallback_flag": done.fallback_flag if done else None,
            "citations": list(done.citations) if done else [],
            "text_head": (done.text[:200] if done else ""),
        }
        print(
            f"{label}: first_token={first_token_ms}ms total={results[label]['total_ms']}ms "
            f"reasoning={reasoning_pieces} fallback={results[label]['fallback_flag']} "
            f"citations={results[label]['citations'][:2]}"
        )

    output_dir = REPO_ROOT / "data" / "eval"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"generation_smoke_{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"存档：{path}")
    ok = all(
        item["fallback_flag"] is False and item["citations"] for item in results.values()
    )
    if results["deep"]["reasoning_pieces"] == 0:
        print("!! 深度模式没有收到推理增量")
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
