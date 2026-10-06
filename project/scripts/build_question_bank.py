#!/usr/bin/env python3
"""自动题库：每条约 1 条口语化问题 + 表格/符号/同义改写对抗子集。

用法（仓库根执行）:
    python project/scripts/build_question_bank.py --limit 20
    python project/scripts/build_question_bank.py --resume
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from deepseek_helper import chat, extract_json_array

from archrag.config import REPO_ROOT
from archrag.corpus.models import Clause
from archrag.corpus.parser import parse_file
from archrag.corpus.standard_map import load_standard_map

PROMPTS = {
    "base": (
        "你是建筑规范检索助手。下面给出若干条文，请为每一条生成一个设计人员日常会问的"
        "口语化问题。要求：只输出 JSON 数组，每项 {{\"clause_id\": \"...\", "
        "\"question\": \"...\"}}；问题必须能用该条文回答；不得照抄条文中任意连续 6 个"
        "及以上的字；问法自然，可以带场景；不要任何多余文字。\n条文：{payload}"
    ),
    "table": (
        "你是建筑规范检索助手。下面条文带表格，请为每一条生成一个针对表格数值或条件的"
        "口语化问题。要求：只输出 JSON 数组，每项 {{\"clause_id\": \"...\", "
        "\"question\": \"...\"}}；不得照抄条文中任意连续 6 个及以上的字；不要多余文字。"
        "\n条文（含表格）：{payload}"
    ),
    "symbol": (
        "你是建筑规范检索助手。下面条文含符号或公式，请生成一个用中文含义提问（不要直接"
        "使用符号）的口语化问题。要求：只输出 JSON 数组，每项 {{\"clause_id\": \"...\", "
        "\"question\": \"...\"}}；不得照抄条文中任意连续 6 个及以上的字；不要多余文字。"
        "\n条文：{payload}"
    ),
    "adversarial": (
        "你是建筑规范检索助手。请把下面每条条文改写成一种完全不同的日常问法（同义改写），"
        "用于检索对抗测试。要求：只输出 JSON 数组，每项 {{\"clause_id\": \"...\", "
        "\"question\": \"...\"}}；不得照抄条文中任意连续 6 个及以上的字；不要多余文字。"
        "\n条文：{payload}"
    ),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成自动题库（DeepSeek 批处理）")
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "data" / "question_bank" / "questions.jsonl"),
    )
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 条（调试用）")
    parser.add_argument(
        "--kinds",
        default="base,table,symbol,adversarial",
        help="要生成的子集，逗号分隔",
    )
    parser.add_argument("--adversarial-size", type=int, default=100)
    parser.add_argument("--resume", action="store_true", help="跳过已生成的 (clause_id, kind)")
    parser.add_argument("--workers", type=int, default=4, help="并发 API 请求数")
    args = parser.parse_args(argv)

    corpus_dir = REPO_ROOT / "数据库上传资料"
    standard_map = load_standard_map(corpus_dir / "规范标准号映射表.md")
    parsed_list = [
        parse_file(corpus_dir / name, standard) for name, standard in standard_map.items()
    ]
    raw_lines = {
        name: (corpus_dir / name).read_text(encoding="utf-8").splitlines()
        for name in standard_map
    }
    file_by_clause: dict[str, str] = {}
    for name, parsed in zip(standard_map, parsed_list, strict=True):
        for clause in parsed.clauses:
            file_by_clause[clause.clause_id] = name
    clauses = [clause for parsed in parsed_list for clause in parsed.clauses]

    def has_latex(clause: Clause) -> bool:
        lines = raw_lines[file_by_clause[clause.clause_id]]
        excerpt = "\n".join(lines[clause.source_line - 1 : clause.end_line])
        return "$" in excerpt

    kinds = [kind.strip() for kind in args.kinds.split(",") if kind.strip()]
    selected: list[tuple[str, Clause]] = []
    for kind in kinds:
        if kind not in PROMPTS:
            raise SystemExit(f"未知子集：{kind}")
        if kind == "base":
            selected.extend(("base", clause) for clause in clauses)
        elif kind == "table":
            selected.extend(("table", clause) for clause in clauses if clause.tables)
        elif kind == "symbol":
            selected.extend(("symbol", clause) for clause in clauses if has_latex(clause))
        else:
            picked = random.Random("adversarial").sample(
                clauses, min(args.adversarial_size, len(clauses))
            )
            selected.extend(("adversarial", clause) for clause in picked)
    if args.limit:
        selected = selected[: args.limit]

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    done: set[tuple[str, str]] = set()
    if args.resume and output.is_file():
        for line in output.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            done.add((record["clause_id"], record["kind"]))

    tasks: list[tuple[str, list[Clause]]] = []
    for kind in kinds:
        items = [clause for item_kind, clause in selected if item_kind == kind]
        pending = [item for item in items if (item.clause_id, kind) not in done]
        for start in range(0, len(pending), args.batch_size):
            tasks.append((kind, pending[start : start + args.batch_size]))

    generated = 0
    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(_generate_batch, kind, batch): (kind, batch)
            for kind, batch in tasks
        }
        for future in as_completed(futures):
            kind, batch = futures[future]
            completed += 1
            try:
                rows = future.result()
            except Exception as exc:  # 批处理：单批失败不阻断整体
                print(f"!! {kind} 批次失败：{exc}")
                continue
            with output.open("a", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            generated += len(rows)
            if completed % 5 == 0 or completed == len(tasks):
                print(f"批次 {completed}/{len(tasks)}，新增 {generated} 条")
    print(f"新增 {generated} 条，累计 {len(done) + generated} 条 → {output}")
    return 0


def _generate_batch(kind: str, batch: list[Clause]) -> list[dict]:
    payload = json.dumps(
        [
            {
                "clause_id": clause.clause_id,
                "clause_no": clause.clause_no,
                "text": _clip(clause.text, 400),
                "tables": [table.caption for table in clause.tables],
            }
            for clause in batch
        ],
        ensure_ascii=False,
    )
    response = chat(PROMPTS[kind].format(payload=payload), temperature=0.3)
    records = extract_json_array(response)
    by_id = {clause.clause_id: clause for clause in batch}
    rows: list[dict] = []
    for record in records:
        clause = by_id.get(record.get("clause_id"))
        question = str(record.get("question", "")).strip()
        if clause is None or not question:
            continue
        rows.append(
            {
                "clause_id": clause.clause_id,
                "standard_id": clause.clause_id.rsplit("_", 1)[0],
                "clause_no": clause.clause_no,
                "kind": kind,
                "question": question,
            }
        )
    return rows


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


if __name__ == "__main__":
    sys.exit(main())
