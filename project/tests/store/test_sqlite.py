"""SQLite schema、事务与版本规则测试。"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from archrag.corpus.chunker import build_chunks
from archrag.corpus.models import Standard
from archrag.corpus.parser import parse_text
from archrag.corpus.references import extract_references
from archrag.errors import CorpusError, StoreError
from archrag.store.sqlite import SCHEMA_VERSION, SqliteStore

EXPECTED_TABLES = {
    "standards",
    "chapters",
    "sections",
    "clauses",
    "clause_parts",
    "chunks",
    "tables",
    "table_rows",
    "references",
    "lexicon",
    "aliases",
    "query_expansion",
    "front_matter",
    "images",
    "ingest_runs",
}


@pytest.fixture()
def store(tmp_path: Path) -> SqliteStore:
    store = SqliteStore(tmp_path / "test.sqlite")
    store.initialize()
    return store


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ingest(store: SqliteStore, parsed, chunks, path: Path, *, sha: str | None = None):
    digest = sha if sha is not None else _sha256(path)
    return store.replace_standard(
        parsed,
        chunks,
        extract_references(parsed),
        source_sha256=digest,
        version=digest[:12],
    )


def test_initialize_creates_current_schema(store: SqliteStore) -> None:
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert names >= EXPECTED_TABLES


def test_ingest_real_standard(store, parsed_corpus, chunks_by_standard, corpus_dir) -> None:
    name = "民用建筑通用规范.md"
    parsed = parsed_corpus[name]
    chunks = chunks_by_standard[name]
    stats = _ingest(store, parsed, chunks, corpus_dir / name)
    assert (stats.clauses, stats.chunks, stats.tables, stats.created) == (142, 147, 2, True)
    counts = store.counts()
    assert counts["standards"] == 1
    assert counts["clauses"] == 142
    assert counts["chunks"] == 147
    assert counts["clause_parts"] == 220
    assert counts["tables"] == 2
    assert counts["front_matter"] == 2
    assert all(
        row["chunk_type"] in ("body", "table_row")
        for row in store.chunks_for("GB 55031-2022")
    )
    blocks = {row["kind"]: row for row in store.front_matter_for("GB 55031-2022")}
    assert set(blocks) == {"前言", "目次"}
    assert all(row["is_indexed"] == 0 for row in blocks.values())
    clause = store.clause_row("GB 55031-2022_1.0.1")
    assert clause is not None
    assert clause["text"] == parsed.clause_by_no("1.0.1").text


def test_same_version_replace_is_idempotent(
    store, parsed_corpus, chunks_by_standard, corpus_dir
) -> None:
    name = "民用建筑通用规范.md"
    parsed = parsed_corpus[name]
    chunks = chunks_by_standard[name]
    first = _ingest(store, parsed, chunks, corpus_dir / name)
    before = store.counts()
    second = _ingest(store, parsed, chunks, corpus_dir / name)
    assert first.created is True
    assert second.created is False
    after = store.counts()
    assert {key: value for key, value in after.items() if key != "ingest_runs"} == {
        key: value for key, value in before.items() if key != "ingest_runs"
    }
    assert after["ingest_runs"] == before["ingest_runs"] + 1


def test_different_version_is_rejected(
    store, parsed_corpus, chunks_by_standard, corpus_dir
) -> None:
    name = "民用建筑通用规范.md"
    parsed = parsed_corpus[name]
    chunks = chunks_by_standard[name]
    _ingest(store, parsed, chunks, corpus_dir / name, sha="a" * 64)
    with pytest.raises(CorpusError):
        _ingest(store, parsed, chunks, corpus_dir / name, sha="b" * 64)
    assert store.counts()["standards"] == 1


def test_write_failure_rolls_back(store, parsed_corpus, chunks_by_standard, corpus_dir) -> None:
    name = "民用建筑通用规范.md"
    parsed = parsed_corpus[name]
    chunks = chunks_by_standard[name]
    _ingest(store, parsed, chunks, corpus_dir / name)
    before = store.counts()
    duplicate = tuple(chunks) + (chunks[0],)
    with pytest.raises(StoreError):
        store.replace_standard(
            parsed,
            duplicate,
            extract_references(parsed),
            source_sha256=_sha256(corpus_dir / name),
            version="v1",
        )
    assert store.counts() == before
    assert store.clause_row("GB 55031-2022_1.0.1") is not None


def test_reference_edges_are_stored(
    store, parsed_corpus, chunks_by_standard, corpus_dir
) -> None:
    name = "住宅项目规范.md"
    _ingest(store, parsed_corpus[name], chunks_by_standard[name], corpus_dir / name)
    edges = store.reference_edges_for("GB 55038-2025")
    assert len(edges) == 10
    assert {edge["ref_type"] for edge in edges} == {"table"}


def test_scope_chunk_and_image_are_stored(store, token_counter) -> None:
    standard = Standard(standard_id="GB 55000-2025", name="测试规范", file_name="t.md")
    text = (
        "# 1 总 则\n\n1.0.1 甲。\n\n1 款内说明。\n\n"
        "![](images/x.png)\n\n本规范适用于新建住宅项目。\n"
    )
    parsed = parse_text(text, standard)
    chunks = build_chunks(parsed, version="v1", count_tokens=token_counter.count)
    store.replace_standard(parsed, chunks, (), source_sha256="c" * 64, version="v1")
    scope_rows = store.chunks_for("GB 55000-2025", "scope")
    assert len(scope_rows) == 1
    assert scope_rows[0]["clause_id"] is None
    with sqlite3.connect(store.path) as connection:
        image_rows = connection.execute(
            "SELECT clause_id, path FROM images ORDER BY image_id"
        ).fetchall()
    assert image_rows == [("GB 55000-2025_1.0.1", "images/x.png")]
