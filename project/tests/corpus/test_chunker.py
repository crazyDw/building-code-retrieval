"""切块行为测试：长度上限、按款/项切、元数据与四类块。"""

from __future__ import annotations

from archrag.corpus.chunker import build_chunks, render_clause
from archrag.corpus.models import ChunkType, Standard
from archrag.corpus.parser import parse_text

TEST_STANDARD = Standard(standard_id="GB 55000-2025", name="测试规范", file_name="test.md")


def _chunks(text: str, counter, *, max_tokens: int = 256):
    parsed = parse_text(text, TEST_STANDARD)
    return parsed, build_chunks(
        parsed, version="v1", count_tokens=counter.count, max_tokens=max_tokens
    )


def _body(chunks, clause_no: str):
    return [
        chunk
        for chunk in chunks
        if chunk.clause_no == clause_no and chunk.chunk_type in (ChunkType.BODY, ChunkType.TERM)
    ]


def test_all_real_chunks_within_limit(chunks_by_standard) -> None:
    for name, chunks in chunks_by_standard.items():
        over = [chunk for chunk in chunks if chunk.token_count > 256]
        assert over == [], f"{name} 存在超限块：{[c.chunk_id for c in over][:3]}"


def test_chunk_metadata_is_complete(chunks_by_standard) -> None:
    for name, chunks in chunks_by_standard.items():
        identifiers = [chunk.chunk_id for chunk in chunks]
        assert len(identifiers) == len(set(identifiers))
        for chunk in chunks:
            assert chunk.standard_name
            assert chunk.source_file == name
            assert chunk.level == "全文强制"
            assert chunk.token_count > 0
            assert chunk.embed_text.startswith(chunk.standard_name)
            if chunk.chunk_type in (ChunkType.BODY, ChunkType.TERM):
                assert chunk.clause_id and chunk.clause_no and chunk.section_id
                assert chunk.num_key is not None
                assert chunk.path
            if chunk.chunk_type is ChunkType.TABLE_ROW:
                assert chunk.table_id and chunk.row_no
                assert chunk.clause_no


def test_overlong_clause_splits_by_kuan(chunks_by_standard) -> None:
    chunks = _body(chunks_by_standard["住宅项目规范.md"], "4.2.2")
    assert [chunk.kuan_no for chunk in chunks] == [None, 1, 2, 3, 4]
    assert chunks[0].chunk_id.endswith(":intro")
    assert all(chunk.token_count <= 256 for chunk in chunks)


def test_overlong_clause_with_small_kuan_keeps_items_together(chunks_by_standard) -> None:
    chunks = _body(chunks_by_standard["混凝土结构通用规范.md"], "4.4.9")
    assert [chunk.kuan_no for chunk in chunks] == [None, 1, 2]
    kuan2 = chunks[-1]
    assert kuan2.item_nos == (1, 2, 3)
    assert "箍筋加密区" in kuan2.text and "剪跨比" in kuan2.text


def test_kuan_that_fits_stays_whole(chunks_by_standard) -> None:
    kuan2 = _body(chunks_by_standard["混凝土结构通用规范.md"], "4.4.9")[-1]
    assert kuan2.token_count <= 256
    assert kuan2.chunk_id.endswith(":k2")


def test_clause_with_tables_is_measured_without_tables(chunks_by_standard) -> None:
    chunks = _body(chunks_by_standard["住宅项目规范.md"], "3.1.1")
    assert len(chunks) == 1
    assert chunks[0].token_count <= 256
    assert "<table" not in chunks[0].text
    assert chunks[0].has_table is True


def test_chunk_build_is_deterministic(parsed_corpus, token_counter) -> None:
    parsed = parsed_corpus["民用建筑通用规范.md"]
    first = build_chunks(parsed, version="v1", count_tokens=token_counter.count)
    second = build_chunks(parsed, version="v1", count_tokens=token_counter.count)
    assert [(c.chunk_id, c.text, c.token_count) for c in first] == [
        (c.chunk_id, c.text, c.token_count) for c in second
    ]


def test_item_boundary_split_for_synthetic_overlong_kuan(token_counter) -> None:
    long_a = "甲" * 120
    long_b = "乙" * 120
    long_c = "丙" * 120
    text = (
        "# 1 总 则\n\n1.0.1 示例条应符合下列规定：\n\n"
        f"1 示例款：\n\n1）{long_a}。\n\n2）{long_b}。\n\n3）{long_c}。\n"
    )
    _, chunks = _chunks(text, token_counter)
    kuan_chunks = [chunk for chunk in chunks if chunk.kuan_no == 1]
    assert len(kuan_chunks) >= 2
    assert all(chunk.token_count <= 256 for chunk in kuan_chunks)
    assert all("1 示例款" in chunk.text for chunk in kuan_chunks)
    for marker, expected_item in ((long_a, 1), (long_b, 2), (long_c, 3)):
        owners = [chunk for chunk in kuan_chunks if marker in chunk.text]
        assert len(owners) == 1
        assert expected_item in owners[0].item_nos


def test_single_item_over_limit_is_kept_and_flagged(token_counter) -> None:
    huge = "丁" * 400
    text = f"# 1 总 则\n\n1.0.1 示例条：\n\n1 示例款：\n\n1）{huge}。\n"
    _, chunks = _chunks(text, token_counter)
    kuan_chunks = [chunk for chunk in chunks if chunk.kuan_no == 1]
    assert len(kuan_chunks) == 1
    assert kuan_chunks[0].over_limit_reason == "单个项自身超限"
    assert huge in kuan_chunks[0].text


def test_sentence_fallback_for_clause_without_kuan(token_counter) -> None:
    sentence = "这是一句用于测试切分的较长描述文字" * 12 + "。"
    text = f"# 1 总 则\n\n1.0.1 {sentence}{sentence}{sentence}\n"
    _, chunks = _chunks(text, token_counter)
    assert len(chunks) >= 2
    assert all(chunk.token_count <= 256 for chunk in chunks)
    assert all(chunk.kuan_no is None for chunk in chunks)
    assert all(chunk.text.endswith("。") for chunk in chunks)


def test_scope_becomes_separate_chunk(token_counter) -> None:
    text = (
        "# 1 总 则\n\n1.0.1 甲。\n\n"
        "本规范适用于新建住宅项目。\n\n"
        "1.0.2 乙。\n"
    )
    parsed, chunks = _chunks(text, token_counter)
    assert len(parsed.scopes) == 1
    scope_chunks = [chunk for chunk in chunks if chunk.chunk_type is ChunkType.SCOPE]
    assert len(scope_chunks) == 1
    assert scope_chunks[0].clause_id is None
    assert scope_chunks[0].text == "本规范适用于新建住宅项目。"


def test_term_clause_becomes_term_chunk(token_counter) -> None:
    text = "# 1 总 则\n\n## 1.1 术语\n\n1.1.1 建筑高度：自室外地面起算。\n"
    _, chunks = _chunks(text, token_counter)
    assert [chunk.chunk_type for chunk in chunks] == [ChunkType.TERM]


def test_table_row_chunk_uses_header_dimensions(chunks_by_standard) -> None:
    chunks = chunks_by_standard["砌体结构通用规范.md"]
    row = next(
        chunk
        for chunk in chunks
        if chunk.chunk_type is ChunkType.TABLE_ROW and "微冻地区" in chunk.text
    )
    assert "抗冻指标" in row.embed_text
    assert "质量损失" in row.embed_text
    assert "≤5" in row.text


def test_table_row_chunk_includes_caption_and_notes(chunks_by_standard) -> None:
    chunks = chunks_by_standard["住宅项目规范.md"]
    row = next(
        chunk
        for chunk in chunks
        if chunk.chunk_type is ChunkType.TABLE_ROW and "建筑物面向道路无公共出入口" in chunk.text
    )
    assert "表 3.2.6" in row.embed_text
    assert "城镇道路的边缘是指道路红线" in row.embed_text


def test_embed_text_prefix_follows_spec(chunks_by_standard) -> None:
    kuan = next(
        chunk
        for chunk in chunks_by_standard["住宅项目规范.md"]
        if chunk.clause_no == "4.2.2" and chunk.kuan_no == 1
    )
    assert kuan.embed_text.startswith("住宅项目规范")
    assert "4.2.2" in kuan.embed_text
    assert "款1" in kuan.embed_text
    assert kuan.text in kuan.embed_text
    row = next(
        chunk
        for chunk in chunks_by_standard["住宅项目规范.md"]
        if chunk.chunk_type is ChunkType.TABLE_ROW and chunk.table_id == "表 3.2.6"
    )
    assert row.embed_text.startswith("住宅项目规范 表 3.2.6 住宅建筑外墙面至道路边缘的最小距离")


def test_rendered_clause_keeps_kuan_and_item_numbers(chunks_by_standard, parsed_corpus) -> None:
    clause = parsed_corpus["混凝土结构通用规范.md"].clause_by_no("4.4.9")
    rendered = render_clause(clause)
    assert "1 柱全部纵向普通钢筋" in rendered
    assert "2 柱箍筋在规定的范围内应加密" in rendered
    assert "1）" in rendered and "3）" in rendered
