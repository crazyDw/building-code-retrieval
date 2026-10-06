"""随机核对清单：每部规范抽 50 条，写入 data/checklists/（不入库）。"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from archrag.corpus.models import ParsedStandard


@dataclass(frozen=True, slots=True)
class ChecklistItem:
    """一条待人工核对的条文。"""

    clause_id: str
    clause_no: str
    path: tuple[str, ...]
    text: str
    source_line: int


def build_checklist(
    parsed: ParsedStandard, *, size: int = 50, seed: str | int | None = None
) -> tuple[ChecklistItem, ...]:
    """抽样并输出清单条目；默认种子取标准号，保证可复现。"""
    clauses = list(parsed.clauses)
    randomizer = random.Random(parsed.standard.standard_id if seed is None else seed)
    picked = randomizer.sample(clauses, size) if len(clauses) > size else clauses
    picked.sort(key=lambda clause: clause.num_key)
    return tuple(
        ChecklistItem(
            clause_id=clause.clause_id,
            clause_no=clause.clause_no,
            path=clause.path,
            text=clause.text,
            source_line=clause.source_line,
        )
        for clause in picked
    )


def write_checklist(
    parsed: ParsedStandard,
    out_dir: Path,
    *,
    size: int = 50,
    seed: str | int | None = None,
) -> Path:
    """写出单部规范的 Markdown 清单，返回文件路径。"""
    items = build_checklist(parsed, size=size, seed=seed)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{parsed.standard.standard_id}.md"
    lines = [
        f"# {parsed.standard.name}（{parsed.standard.standard_id}）随机核对清单",
        "",
        f"- 抽样 {len(items)} 条 / 全部 {len(parsed.clauses)} 条",
        "",
    ]
    for index, item in enumerate(items, start=1):
        path_text = " › ".join(item.path)
        lines.extend(
            [
                f"## {index}. {item.clause_no}",
                "",
                f"- 章节：{path_text}",
                f"- 源文件行：{item.source_line}",
                "",
                item.text,
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
