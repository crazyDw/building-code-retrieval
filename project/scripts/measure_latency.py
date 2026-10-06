#!/usr/bin/env python3
"""延迟实测：默认 / 深度 / 改写路径分开记录首字与完整耗时，存档 data/acceptance/。"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from deepseek_helper import rewriter as build_rewriter

from archrag.config import REPO_ROOT, load_settings
from archrag.generation.client import DeepSeekClient
from archrag.generation.service import stream_answer
from archrag.retrieval.embedder import BgeM3Embedder
from archrag.retrieval.pipeline import PipelineConfig, retrieve
from archrag.retrieval.reranker import BgeReranker
from archrag.store.milvus import MilvusStore
from archrag.store.sqlite import SqliteStore
from archrag.tokenizer import BgeM3TokenCounter

TARGETS = {
    "default": {"first_token_ms": 3000, "total_ms": 20000},
    "deep": {"first_token_ms": 5000, "total_ms": 90000},
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="端到端延迟实测")
    parser.add_argument("--count", type=int, default=10, help="默认路径题数")
    parser.add_argument("--deep-count", type=int, default=3)
    parser.add_argument("--rewrite-count", type=int, default=3)
    parser.add_argument("--no-warmup", action="store_true", help="跳过预热（冷启动口径）")
    parser.add_argument(
        "--output", default=str(REPO_ROOT / "data" / "acceptance" / "latency.json")
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    store = SqliteStore(settings.sqlite_path)
    milvus = MilvusStore(settings.milvus_uri, settings.milvus_collection)
    embedder = BgeM3Embedder(settings.embed_model)
    reranker = BgeReranker(settings.rerank_model)
    counter = BgeM3TokenCounter(settings.embed_model)
    client = DeepSeekClient(settings)
    config = PipelineConfig.from_settings(settings)

    records = [
        json.loads(line)
        for line in (REPO_ROOT / "data" / "question_bank" / "questions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    base_questions = [item["question"] for item in records if item.get("kind") == "base"][
        : args.count
    ]
    deep_questions = base_questions[: args.deep_count]
    rewrite_questions = ["楼梯宽度", "那个要求", "踏步高度"]

    payload: dict[str, object] = {"settings": {"model": settings.model}}
    if not args.no_warmup:
        _warm_up(
            store=store, milvus=milvus, embedder=embedder, reranker=reranker,
            client=client, counter=counter, config=config,
        )
    payload["default"] = _measure(
        base_questions, deep=False, store=store, milvus=milvus, embedder=embedder,
        reranker=reranker, client=client, counter=counter, config=config,
    )
    payload["deep"] = _measure(
        deep_questions, deep=True, store=store, milvus=milvus, embedder=embedder,
        reranker=reranker, client=client, counter=counter, config=config,
    )

    rewrite_times: list[float] = []
    base_rewriter = build_rewriter()

    def timed_rewriter(text: str) -> str:
        started = time.monotonic()
        rewritten = base_rewriter(text)
        rewrite_times.append(round((time.monotonic() - started) * 1000, 1))
        return rewritten

    payload["rewrite"] = _measure(
        rewrite_questions[: args.rewrite_count],
        deep=False,
        store=store,
        milvus=milvus,
        embedder=embedder,
        reranker=reranker,
        client=client,
        counter=counter,
        config=config,
        rewriter=timed_rewriter,
    )
    payload["rewrite"]["rewrite_ms"] = rewrite_times

    for name, target in TARGETS.items():
        summary = payload[name]["summary"]
        summary["pass"] = (
            summary["first_token_ms"]["p50"] <= target["first_token_ms"]
            and summary["total_ms"]["p50"] <= target["total_ms"]
        )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = output.with_suffix(".md")
    report.write_text(_render(payload), encoding="utf-8")
    print(_render(payload))
    print(f"存档：{output} / {report}")
    ok = all(payload[name]["summary"].get("pass", False) for name in TARGETS)
    return 0 if ok else 1


def _measure(
    questions,
    *,
    deep: bool,
    store,
    milvus,
    embedder,
    reranker,
    client,
    counter,
    config,
    rewriter=None,
) -> dict:
    rows = []
    for question in questions:
        retrieval_started = time.monotonic()
        retrieval = retrieve(
            question,
            store=store,
            milvus=milvus,
            embedder=embedder,
            reranker=reranker,
            config=config,
            deep=deep,
            count_tokens=counter.count,
            rewriter=rewriter,
        )
        retrieval_ms = round((time.monotonic() - retrieval_started) * 1000, 1)
        started = time.monotonic()
        first_token_ms = None
        done = None
        try:
            for event in stream_answer(
                question,
                retrieval=retrieval,
                client=client,
                store=store,
                count_tokens=counter.count,
                deep=deep,
            ):
                if event.kind in ("derivation", "reasoning", "original") and first_token_ms is None:
                    first_token_ms = round((time.monotonic() - started) * 1000, 1)
                elif event.kind == "done":
                    done = event.data
        except Exception as exc:  # 单题失败不阻断整体
            rows.append({"question": question, "error": type(exc).__name__})
            continue
        rows.append(
            {
                "question": question,
                "first_token_ms": first_token_ms,
                "generation_total_ms": round((time.monotonic() - started) * 1000, 1),
                "retrieval_ms": retrieval_ms,
                "fallback_flag": done.fallback_flag if done else None,
                "rerank_used": retrieval.rerank_used,
                "degraded_flag": retrieval.degraded,
            }
        )
    return {"runs": rows, "summary": _summarize(rows)}


def _warm_up(
    *, store, milvus, embedder, reranker, client, counter, config
) -> None:
    """预热：模型加载 + 一次完整问答，不计入延迟样本（服务启动时同样预热）。"""
    retrieval = retrieve(
        "楼梯踏步宽度",
        store=store,
        milvus=milvus,
        embedder=embedder,
        reranker=reranker,
        config=config,
        count_tokens=counter.count,
    )
    for _ in stream_answer(
        "楼梯踏步宽度",
        retrieval=retrieval,
        client=client,
        store=store,
        count_tokens=counter.count,
    ):
        pass


def _summarize(rows) -> dict:
    first = [row["first_token_ms"] for row in rows if row.get("first_token_ms")]
    total = [
        (row.get("retrieval_ms", 0.0) + row.get("generation_total_ms", 0.0))
        for row in rows
        if row.get("generation_total_ms")
    ]
    return {
        "count": len(rows),
        "errored": sum(1 for row in rows if row.get("error")),
        "fallback": sum(1 for row in rows if row.get("fallback_flag")),
        "first_token_ms": _percentiles(first),
        "total_ms": _percentiles(total),
    }


def _percentiles(values) -> dict:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(values)
    return {
        "p50": round(statistics.median(ordered), 1),
        "p95": round(ordered[min(int(len(ordered) * 0.95), len(ordered) - 1)], 1),
        "max": round(ordered[-1], 1),
    }


def _render(payload) -> str:
    lines = ["# 端到端延迟实测", ""]
    for name in ("default", "deep", "rewrite"):
        summary = payload[name]["summary"]
        lines.append(f"## {name}")
        lines.append(
            f"- 样本 {summary['count']}，失败 {summary['errored']}，兜底 {summary['fallback']}"
        )
        lines.append(
            f"- 首字 P50/P95/max：{summary['first_token_ms']['p50']} / "
            f"{summary['first_token_ms']['p95']} / {summary['first_token_ms']['max']} ms"
        )
        lines.append(
            f"- 完整 P50/P95/max：{summary['total_ms']['p50']} / "
            f"{summary['total_ms']['p95']} / {summary['total_ms']['max']} ms"
        )
        if name == "rewrite":
            lines.append(f"- 改写本身耗时：{payload['rewrite']['rewrite_ms']}")
        if "pass" in summary:
            lines.append(f"- 达标：{summary['pass']}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
