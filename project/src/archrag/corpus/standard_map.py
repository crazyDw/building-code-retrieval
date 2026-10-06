"""解析《规范标准号映射表.md》：文件名 → 标准号/全称/实施日期。"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from archrag.corpus.models import Standard
from archrag.errors import CorpusError

_SEPARATOR_RE = re.compile(r"^\|[\s:|-]+\|$")


def load_standard_map(path: Path) -> dict[str, Standard]:
    """读取映射表文件；文件缺失或内容非法时抛 CorpusError。"""
    if not path.is_file():
        raise CorpusError(f"标准号映射表不存在：{path}")
    return parse_standard_map(path.read_text(encoding="utf-8"))


def parse_standard_map(text: str) -> dict[str, Standard]:
    """解析映射表 Markdown，返回「文件名 → Standard」。"""
    standards: dict[str, Standard] = {}
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("|") or _SEPARATOR_RE.match(stripped):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 4 or cells[0] == "文件名":
            continue
        file_name, name, standard_id, effective = cells[:4]
        if not file_name or not name or not standard_id:
            raise CorpusError(f"映射表第 {line_no} 行缺少必填字段")
        if file_name in standards:
            raise CorpusError(f"映射表第 {line_no} 行文件名重复：{file_name}")
        standards[file_name] = Standard(
            standard_id=standard_id,
            name=name,
            file_name=file_name,
            effective_date=_parse_date(effective, line_no),
        )
    if not standards:
        raise CorpusError("映射表未解析出任何标准")
    return standards


def _parse_date(raw: str, line_no: int) -> date | None:
    if not raw or raw == "—":
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise CorpusError(f"映射表第 {line_no} 行实施日期格式非法：{raw}") from exc
