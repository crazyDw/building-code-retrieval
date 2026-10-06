"""术语章、scope 段落与图片占位的合成夹具测试（真实语料计数为 0）。"""

from __future__ import annotations

import pytest

from archrag.corpus.models import Standard
from archrag.corpus.parser import parse_text

TEST_STANDARD = Standard(
    standard_id="GB 55000-2025",
    name="测试规范",
    file_name="test.md",
)

SYNTHETIC = """# 前言

测试前言。

# 目次

1 总则 1

## 1.1 术语 2

# 1 总 则

## 1.1 术语

1.1.1 建筑高度：自室外地面起算的建筑高度。

本规范适用于新建住宅项目。

## 1.2 其他

1.2.1 其他要求。

1 款内说明。

![](images/fig1.png)

1）项内容一

2）项内容二

<img src="images/fig2.png" alt="节点构造">
"""


@pytest.fixture()
def parsed():
    return parse_text(SYNTHETIC, TEST_STANDARD)


def test_real_corpus_has_no_term_scope_or_image(parsed_corpus) -> None:
    assert all(not parsed.terms for parsed in parsed_corpus.values())
    assert all(not parsed.scopes for parsed in parsed_corpus.values())
    assert all(not parsed.images for parsed in parsed_corpus.values())


def test_term_clause_becomes_term_entry(parsed) -> None:
    assert [(term.name, term.definition) for term in parsed.terms] == [
        ("建筑高度", "自室外地面起算的建筑高度。")
    ]
    assert parsed.sections[0].is_term is True


def test_scope_block_is_split_out_and_tagged(parsed) -> None:
    assert [scope.text for scope in parsed.scopes] == ["本规范适用于新建住宅项目。"]
    assert parsed.scopes[0].section_id == "1.1"
    term_clause = parsed.clause_by_no("1.1.1")
    assert "适用于" not in term_clause.text


def test_markdown_and_html_images_are_recorded(parsed) -> None:
    paths = {image.path for image in parsed.images}
    assert paths == {"images/fig1.png", "images/fig2.png"}
    clause = parsed.clause_by_no("1.2.1")
    assert len(clause.images) == 2
    assert "![" not in clause.text
    assert "images/fig1.png" not in clause.text
    assert clause.kuans[0].items[0].text == "项内容一"
    assert clause.kuans[0].items[1].text == "项内容二"
