"""标准号映射表解析测试。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from archrag.corpus.standard_map import load_standard_map, parse_standard_map
from archrag.errors import CorpusError

EXPECTED = {
    "民用建筑通用规范.md": ("民用建筑通用规范", "GB 55031-2022", date(2023, 3, 1)),
    "住宅项目规范.md": ("住宅项目规范", "GB 55038-2025", date(2025, 5, 1)),
    "钢结构通用规范.md": ("钢结构通用规范", "GB 55006-2021", date(2022, 1, 1)),
    "混凝土结构通用规范.md": ("混凝土结构通用规范", "GB 55008-2021", date(2022, 4, 1)),
    "砌体结构通用规范.md": ("砌体结构通用规范", "GB 55007-2021", date(2022, 1, 1)),
}


def test_real_mapping_file_has_all_five_standards(standard_map) -> None:
    assert set(standard_map) == set(EXPECTED)
    for file_name, (name, standard_id, effective) in EXPECTED.items():
        standard = standard_map[file_name]
        assert (standard.name, standard.standard_id, standard.effective_date) == (
            name,
            standard_id,
            effective,
        )
        assert standard.mandatory is True


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(CorpusError):
        load_standard_map(tmp_path / "missing.md")


def test_malformed_row_raises() -> None:
    text = "| 文件 | 全称 | 标准号 | 实施日期 |\n|---|---|---|---|\n| a.md | A | | 2022-01-01 |\n"
    with pytest.raises(CorpusError):
        parse_standard_map(text)


def test_invalid_date_raises() -> None:
    text = "| a.md | A规范 | GB 55000-2022 | 2022年1月 |\n"
    with pytest.raises(CorpusError):
        parse_standard_map(text)
