#!/usr/bin/env python3
"""全量或按标准重建 Milvus（drop + create + 从 SQLite 重嵌入）。

用法（仓库根执行）:
    & "D:\\Ai software\\anaconda3\\envs\\archrag\\python.exe" project\\scripts\\rebuild_milvus.py
    ... rebuild_milvus.py --standard "GB 55031-2022" --batch-size 16
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from archrag.config import load_settings
from archrag.retrieval.embedder import BgeM3Embedder
from archrag.retrieval.reindex import reindex
from archrag.store.milvus import MilvusStore
from archrag.store.sqlite import SqliteStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="重建 Milvus 派生索引")
    parser.add_argument("--standard", action="append", help="只重建指定标准号，可重复")
    parser.add_argument("--sqlite-path", help="覆盖配置中的 SQLite 路径")
    parser.add_argument("--collection", help="覆盖 collection 名")
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args(argv)

    settings = load_settings()
    if settings.dev_mode:
        print("DEV_MODE=true：不建向量、不连接 Milvus（D8）")
        return 0
    store = SqliteStore(Path(args.sqlite_path) if args.sqlite_path else settings.sqlite_path)
    milvus = MilvusStore(
        settings.milvus_uri,
        args.collection or settings.milvus_collection,
    )
    report = reindex(
        store,
        milvus,
        BgeM3Embedder(settings.embed_model),
        standard_ids=args.standard,
        batch_size=args.batch_size,
    )
    for standard_id, total in report.counts.items():
        print(f"{standard_id}: {total} 个实体")
    print(f"合计 {report.embedded} 块，{report.batches} 批，collection={milvus.collection}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
