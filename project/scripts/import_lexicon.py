#!/usr/bin/env python3
"""导入人工审核后的词表：approved_terms.txt 一行一词；approved_expansions.txt 一行 from=to。"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from archrag.config import REPO_ROOT, load_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导入审核后的词表")
    parser.add_argument(
        "--terms", default=str(REPO_ROOT / "data" / "lexicon" / "approved_terms.txt")
    )
    parser.add_argument(
        "--expansions",
        default=str(REPO_ROOT / "data" / "lexicon" / "approved_expansions.txt"),
    )
    parser.add_argument("--sqlite-path")
    args = parser.parse_args(argv)

    settings = load_settings()
    sqlite_path = Path(args.sqlite_path) if args.sqlite_path else settings.sqlite_path
    candidates_path = REPO_ROOT / "data" / "lexicon" / "candidates.json"
    scores: dict[str, tuple[int, float, str]] = {}
    if candidates_path.is_file():
        payload = json.loads(candidates_path.read_text(encoding="utf-8"))
        scores = {
            item["term"]: (item["freq"], item["score"], item["source"])
            for item in payload.get("terms", [])
        }
    terms = _read_lines(Path(args.terms))
    expansions = []
    for line in _read_lines(Path(args.expansions)):
        if "=" in line:
            source, target = line.split("=", 1)
            expansions.append((source.strip(), target.strip()))
    if not terms and not expansions:
        print("没有可导入的内容（文件为空或不存在）")
        return 2
    with sqlite3.connect(sqlite_path) as connection:
        connection.executemany(
            "INSERT OR REPLACE INTO lexicon (term, freq, score, source, status) "
            "VALUES (?, ?, ?, ?, 'approved')",
            [
                (term, *scores.get(term, (0, 0.0, "manual")))
                for term in terms
            ],
        )
        connection.executemany(
            "INSERT OR IGNORE INTO query_expansion (from_text, to_text, kind) "
            "VALUES (?, ?, 'manual')",
            expansions,
        )
    print(f"导入术语 {len(terms)} 条、扩展 {len(expansions)} 条 → {sqlite_path}")
    return 0


def _read_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


if __name__ == "__main__":
    sys.exit(main())
