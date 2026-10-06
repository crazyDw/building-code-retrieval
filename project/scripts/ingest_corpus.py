#!/usr/bin/env python3
"""入库 CLI：默认一次入库 5 份语料并重建 Milvus，`--file` 指定单份。

用法（仓库根执行）:
    & "D:\\Ai software\\anaconda3\\envs\\archrag\\python.exe" project\\scripts\\ingest_corpus.py
    ... ingest_corpus.py --file 民用建筑通用规范.md --sqlite-path data/dev.sqlite --skip-milvus
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from archrag.config import load_settings
from archrag.corpus.ingest import ingest_corpus
from archrag.corpus.standard_map import load_standard_map
from archrag.retrieval.embedder import BgeM3Embedder
from archrag.retrieval.reindex import reindex
from archrag.store.milvus import MilvusStore
from archrag.store.sqlite import SqliteStore
from archrag.tokenizer import BgeM3TokenCounter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="语料入库（解析 → 切块 → SQLite）")
    parser.add_argument("--file", action="append", help="只入库指定文件名，可重复")
    parser.add_argument("--sqlite-path", help="覆盖配置中的 SQLite 路径")
    parser.add_argument("--skip-census", action="store_true", help="跳过前置普查（仅调试用）")
    parser.add_argument("--max-tokens", type=int, default=256, help="块长硬上限")
    parser.add_argument("--skip-milvus", action="store_true", help="只写 SQLite，不重建 Milvus")
    parser.add_argument("--reindex-only", action="store_true", help="跳过入库，仅重建 Milvus")
    parser.add_argument("--batch-size", type=int, default=32, help="嵌入批大小")
    args = parser.parse_args(argv)

    settings = load_settings()
    standard_map = load_standard_map(settings.standard_map_path)
    store = SqliteStore(Path(args.sqlite_path) if args.sqlite_path else settings.sqlite_path)
    store.initialize()
    if not args.reindex_only:
        files = args.file
        if files is None and settings.dev_mode:
            files = ["民用建筑通用规范.md"]
        outcome = ingest_corpus(
            store,
            standard_map,
            corpus_dir=settings.repo_root / "数据库上传资料",
            count_tokens=BgeM3TokenCounter(settings.embed_model).count,
            files=files,
            max_tokens=args.max_tokens,
            run_census_first=not args.skip_census,
        )
        for stats in outcome.stats:
            state = "新建" if stats.created else "幂等替换"
            print(
                f"{stats.standard_id}: {state} | 条 {stats.clauses} 块 {stats.chunks} "
                f"表 {stats.tables} 引用 {stats.references}"
            )
        if outcome.census is not None:
            print(
                f"普查：标记异常 {len(outcome.census.marked_issue_lines)} 处，"
                f"条号缺口 {len(outcome.census.number_gap_lines)} 处"
            )
    if not args.skip_milvus:
        if settings.dev_mode:
            print("DEV_MODE=true：跳过 Milvus 重建（D8）")
        else:
            report = reindex(
                store,
                MilvusStore(settings.milvus_uri, settings.milvus_collection),
                BgeM3Embedder(settings.embed_model),
                batch_size=args.batch_size,
            )
            for standard_id, total in report.counts.items():
                print(f"Milvus {standard_id}: {total} 个实体")
            print(f"Milvus 合计 {sum(report.counts.values())} 个实体")
    print(f"SQLite：{store.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
