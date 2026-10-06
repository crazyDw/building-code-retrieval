#!/usr/bin/env python3
"""自动题库评测：Recall@5、分路径耗时与重排正负样本存档。"""

from __future__ import annotations

import argparse
import dataclasses
import json
import statistics
import sys
import time
from pathlib import Path

from deepseek_helper import rewriter as build_rewriter

from archrag.config import REPO_ROOT, load_settings
from archrag.retrieval.embedder import BgeM3Embedder
from archrag.retrieval.pipeline import PipelineConfig, retrieve
from archrag.retrieval.reranker import BgeReranker
from archrag.store.milvus import MilvusStore
from archrag.store.sqlite import SqliteStore
from archrag.tokenizer import BgeM3TokenCounter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检索评测（Recall@5 与耗时）")
    parser.add_argument(
        "--questions",
        default=str(REPO_ROOT / "data" / "question_bank" / "questions.jsonl"),
    )
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "data" / "eval"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--deep", action="store_true")
    parser.add_argument(
        "--rewrite-sample",
        type=int,
        default=0,
        help="额外测 N 条改写路径耗时（会调用 DeepSeek）",
    )
    parser.add_argument("--tag", default="default")
    parser.add_argument(
        "--negative-questions",
        default="",
        help="超范围问题文件（每行一个问题），用于阈值标定的真负样本",
    )
    parser.add_argument("--only-negatives", action="store_true")
    args = parser.parse_args(argv)

    settings = load_settings()
    store = SqliteStore(settings.sqlite_path)
    milvus = MilvusStore(settings.milvus_uri, settings.milvus_collection)
    embedder = BgeM3Embedder(settings.embed_model)
    reranker = BgeReranker(settings.rerank_model)
    counter = BgeM3TokenCounter(settings.embed_model)
    config = PipelineConfig.from_settings(settings)
    if args.no_rerank:
        config = dataclasses.replace(config, rerank_enabled=False)

    records = [
        json.loads(line)
        for line in Path(args.questions).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.limit:
        records = records[: args.limit]
    if not records:
        print(f"题库为空：{args.questions}")
        return 2

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if args.only_negatives:
        if not args.negative_questions:
            print("缺少 --negative-questions")
            return 2
        _measure_negatives(
            args, store, milvus, embedder, reranker, config, counter, output_dir, stamp
        )
        return 0

    results: list[dict] = []
    started = time.monotonic()
    for index, record in enumerate(records, start=1):
        result = retrieve(
            record["question"],
            store=store,
            milvus=milvus,
            embedder=embedder,
            reranker=None if args.no_rerank else reranker,
            config=config,
            deep=args.deep,
            count_tokens=counter.count,
        )
        top5 = [hit.clause_id for hit in result.hits[:5]]
        positives, negatives = _candidate_scores(result, store, record["clause_id"])
        results.append(
            {
                "question": record["question"],
                "kind": record.get("kind", "base"),
                "gold": record["clause_id"],
                "top5": top5,
                "hit": record["clause_id"] in top5,
                "rerank_used": result.rerank_used,
                "degraded": result.degraded,
                "not_found": result.not_found,
                "rewrite_needed": result.plan.rewrite_needed,
                "broad": result.plan.is_broad,
                "timings": result.timings,
                "positives": positives,
                "negatives": negatives,
            }
        )
        if index % 50 == 0:
            hit_rate = sum(item["hit"] for item in results) / len(results)
            print(f"{index}/{len(records)} Recall@5={hit_rate:.3f}")

    summary = _summarize(results, args.tag, elapsed=time.monotonic() - started)
    detail_path = output_dir / f"eval_{args.tag}_{stamp}.json"
    summary_path = output_dir / f"summary_{args.tag}_{stamp}.json"
    detail_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / f"report_{args.tag}_{stamp}.md").write_text(
        _report(summary), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"明细：{detail_path}\n汇总：{summary_path}")

    if args.negative_questions:
        _measure_negatives(
            args, store, milvus, embedder, reranker, config, counter, output_dir, stamp
        )
    if args.rewrite_sample:
        _measure_rewrite(results, args.rewrite_sample, output_dir, stamp)
    return 0


def _candidate_scores(result, store: SqliteStore, gold: str) -> tuple[list[float], list[float]]:
    candidates = result.log_fields.get("candidates", [])
    chunk_ids = [item["chunk_id"] for item in candidates if item.get("rerank_score") is not None]
    rows = {row["chunk_id"]: row for row in store.chunks_by_ids(chunk_ids)}
    positives: list[float] = []
    negatives: list[float] = []
    for item in candidates:
        score = item.get("rerank_score")
        if score is None:
            continue
        row = rows.get(item["chunk_id"])
        clause_id = row["clause_id"] if row is not None else None
        if clause_id == gold:
            positives.append(float(score))
        else:
            negatives.append(float(score))
    return positives, negatives


def _summarize(results: list[dict], tag: str, *, elapsed: float) -> dict:
    by_kind: dict[str, dict[str, float]] = {}
    for item in results:
        kind = item["kind"]
        bucket = by_kind.setdefault(kind, {"count": 0, "hits": 0})
        bucket["count"] += 1
        bucket["hits"] += int(item["hit"])
    for bucket in by_kind.values():
        bucket["recall_at_5"] = round(bucket["hits"] / bucket["count"], 4)
    timings = {
        key: _percentiles([item["timings"].get(key, 0.0) for item in results])
        for key in ("embed_ms", "search_ms", "fusion_ms", "rerank_ms", "context_ms", "total_ms")
    }
    return {
        "tag": tag,
        "count": len(results),
        "recall_at_5": round(sum(item["hit"] for item in results) / len(results), 4),
        "by_kind": by_kind,
        "rewrite_needed_rate": round(
            sum(item["rewrite_needed"] for item in results) / len(results), 4
        ),
        "broad_rate": round(sum(item["broad"] for item in results) / len(results), 4),
        "degraded_count": sum(item["degraded"] for item in results),
        "not_found_count": sum(item["not_found"] for item in results),
        "timings": timings,
        "wall_seconds": round(elapsed, 1),
    }


def _percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0}
    ordered = sorted(values)
    return {
        "mean": round(statistics.fmean(ordered), 2),
        "p50": round(ordered[int(len(ordered) * 0.5)], 2),
        "p95": round(ordered[min(int(len(ordered) * 0.95), len(ordered) - 1)], 2),
    }


def _report(summary: dict) -> str:
    lines = [
        f"# 检索评测（{summary['tag']}）",
        "",
        f"- 题目数：{summary['count']}",
        f"- Recall@5：**{summary['recall_at_5']:.2%}**",
        f"- 改写触发率：{summary['rewrite_needed_rate']:.2%}；"
        f"宽泛问题率：{summary['broad_rate']:.2%}",
        f"- 降级 {summary['degraded_count']} 条；未命中 {summary['not_found_count']} 条",
        "",
        "| 子集 | 题数 | Recall@5 |",
        "|---|---|---|",
    ]
    for kind, bucket in sorted(summary["by_kind"].items()):
        lines.append(f"| {kind} | {bucket['count']} | {bucket['recall_at_5']:.2%} |")
    lines.extend(["", "| 阶段 | 均值 ms | P50 | P95 |", "|---|---|---|---|"])
    for key, value in summary["timings"].items():
        lines.append(f"| {key} | {value['mean']} | {value['p50']} | {value['p95']} |")
    return "\n".join(lines) + "\n"


def _measure_rewrite(results: list[dict], sample: int, output_dir: Path, stamp: str) -> None:
    candidates = [item for item in results if item["rewrite_needed"] and "这个" in item["question"]]
    if not candidates:
        candidates = [item for item in results if item["rewrite_needed"]]
    if not candidates:
        print("没有需要改写的样例，跳过改写耗时测量")
        return
    rewrite = build_rewriter()
    measurements = []
    for item in candidates[:sample]:
        started = time.monotonic()
        try:
            rewritten = rewrite(item["question"])
        except Exception as exc:
            rewritten = f"<失败：{exc}>"
        elapsed = round((time.monotonic() - started) * 1000, 1)
        measurements.append(
            {"question": item["question"], "rewritten": rewritten, "rewrite_ms": elapsed}
        )
    path = output_dir / f"rewrite_latency_{stamp}.json"
    path.write_text(
        json.dumps(measurements, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for item in measurements:
        print(f"改写 {item['rewrite_ms']} ms：{item['question']} → {item['rewritten']}")
    print(f"改写耗时：{path}")


def _measure_negatives(
    args, store, milvus, embedder, reranker, config, counter, output_dir: Path, stamp: str
) -> None:
    questions = [
        line.strip()
        for line in Path(args.negative_questions).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    records = []
    for question in questions:
        result = retrieve(
            question,
            store=store,
            milvus=milvus,
            embedder=embedder,
            reranker=None if args.no_rerank else reranker,
            config=config,
            count_tokens=counter.count,
        )
        scores = [
            item["rerank_score"]
            for item in result.log_fields.get("candidates", [])
            if item.get("rerank_score") is not None
        ]
        records.append(
            {
                "question": question,
                "top_score": max(scores) if scores else None,
                "rerank_used": result.rerank_used,
            }
        )
    path = output_dir / f"negatives_{stamp}.json"
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    usable = [record["top_score"] for record in records if record["top_score"] is not None]
    if usable:
        print(
            f"超范围负样本 {len(usable)} 条：top 分均值 "
            f"{statistics.fmean(usable):.3f}，最大 {max(usable):.3f}"
        )
    print(f"负样本明细：{path}")


if __name__ == "__main__":
    sys.exit(main())
