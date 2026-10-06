#!/usr/bin/env python3
"""生成词表候选与人工审核清单（不直接入库）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from archrag.config import REPO_ROOT
from archrag.corpus.lexicon import build_candidates, write_candidates
from archrag.corpus.parser import parse_file
from archrag.corpus.standard_map import load_standard_map


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="词表候选生成")
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "data" / "lexicon"),
    )
    parser.add_argument("--top-n", type=int, default=500)
    args = parser.parse_args(argv)

    corpus_dir = REPO_ROOT / "数据库上传资料"
    standard_map = load_standard_map(corpus_dir / "规范标准号映射表.md")
    parsed_list = [
        parse_file(corpus_dir / name, standard) for name, standard in standard_map.items()
    ]
    candidates = build_candidates(parsed_list, top_n=args.top_n)
    output_dir = Path(args.output_dir)
    write_candidates(candidates, output_dir / "candidates.json")
    review = output_dir / "review.md"
    lines = [
        "# 词表人工审核清单",
        "",
        "在要保留的词前把 `[ ]` 改成 `[x]`，完成后运行 "
        "`project/scripts/import_lexicon.py --terms data/lexicon/approved_terms.txt`。",
        "",
        f"## 术语候选（{len(candidates.terms)}）",
        "",
    ]
    for item in candidates.terms:
        lines.append(
            f"- [ ] {item.term}  "
            f"<!-- freq={item.freq} score={item.score} source={item.source} -->"
        )
    lines.extend(["", "## 别名（自动入库）", ""])
    lines.extend(
        f"- {item.standard_id} → {item.alias}（{item.alias_type}）"
        for item in candidates.aliases
    )
    lines.extend(["", "## 符号/条件映射（自动入库）", ""])
    lines.extend(
        f"- {item.from_text} → {item.to_text}（{item.kind}）"
        for item in candidates.expansions
    )
    review.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"术语 {len(candidates.terms)} / 别名 {len(candidates.aliases)} / "
        f"映射 {len(candidates.expansions)}"
    )
    print(f"候选：{output_dir / 'candidates.json'}\n审核清单：{review}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
