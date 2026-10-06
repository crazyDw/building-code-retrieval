"""标题归一化与源文件不可变测试。"""

from __future__ import annotations

import hashlib
import re

from archrag.corpus.parser import normalize_title

_CJK_SPACE_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]\s+[\u3400-\u4dbf\u4e00-\u9fff]")

_EXPECTED_SPACED_TITLES = {"总 则", "设 计", "场 地", "声 环 境", "燃 气"}


def test_normalize_title_removes_only_cjk_spaces() -> None:
    assert normalize_title("总 则") == "总则"
    assert normalize_title("声 环 境") == "声环境"
    assert normalize_title("GB 55031-2022") == "GB 55031-2022"


def test_real_titles_are_normalized(parsed_corpus) -> None:
    raw_titles = [
        item.raw_title
        for parsed in parsed_corpus.values()
        for item in (*parsed.chapters, *parsed.sections)
    ]
    normalized = [
        item.title
        for parsed in parsed_corpus.values()
        for item in (*parsed.chapters, *parsed.sections)
    ]
    assert all(_CJK_SPACE_RE.search(title) is None for title in normalized)
    spaced = {title for title in raw_titles if _CJK_SPACE_RE.search(title)}
    assert spaced == _EXPECTED_SPACED_TITLES
    assert sum(1 for title in raw_titles if _CJK_SPACE_RE.search(title)) == 10


def test_toc_title_spaces_are_normalized_in_memory(parsed_corpus) -> None:
    toc_texts = [
        item.text
        for parsed in parsed_corpus.values()
        for item in parsed.front_matter
        if item.kind == "目次"
    ]
    assert sum("目 次" in text for text in toc_texts) == 2
    assert normalize_title("目 次") == "目次"


def test_parse_does_not_modify_source(standard_map, corpus_dir) -> None:
    from archrag.corpus.parser import parse_file

    digests = {
        name: hashlib.sha256((corpus_dir / name).read_bytes()).hexdigest()
        for name in standard_map
    }
    for name, standard in standard_map.items():
        parse_file(corpus_dir / name, standard)
    for name, digest in digests.items():
        assert hashlib.sha256((corpus_dir / name).read_bytes()).hexdigest() == digest
