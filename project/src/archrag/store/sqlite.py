"""SQLite 存储：SQLite 是唯一真相源，Milvus 只是派生。

手写 DDL + `PRAGMA user_version` 管版本；每次写入单事务，失败整体回滚。
注意：`references` 是 SQL 关键字，所有语句中都必须写成 `"references"`。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from archrag.corpus.models import (
    Alias,
    Chunk,
    Expansion,
    LexiconTerm,
    ParsedStandard,
    Reference,
)
from archrag.errors import CorpusError, StoreError

SCHEMA_VERSION = 1

_DDL = """
CREATE TABLE IF NOT EXISTS standards (
    standard_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    level TEXT NOT NULL,
    effective_date TEXT,
    version TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    superseded_by TEXT,
    is_current INTEGER NOT NULL DEFAULT 1,
    parsed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chapters (
    standard_id TEXT NOT NULL REFERENCES standards(standard_id) ON DELETE CASCADE,
    chapter_no INTEGER NOT NULL,
    title TEXT NOT NULL,
    raw_title TEXT NOT NULL,
    marks TEXT NOT NULL,
    source_line INTEGER NOT NULL,
    PRIMARY KEY (standard_id, chapter_no)
);

CREATE TABLE IF NOT EXISTS sections (
    standard_id TEXT NOT NULL REFERENCES standards(standard_id) ON DELETE CASCADE,
    section_id TEXT NOT NULL,
    chapter_no INTEGER NOT NULL,
    title TEXT NOT NULL,
    raw_title TEXT NOT NULL,
    marks TEXT NOT NULL,
    is_term INTEGER NOT NULL DEFAULT 0,
    clause_count INTEGER NOT NULL DEFAULT 0,
    source_line INTEGER NOT NULL,
    PRIMARY KEY (standard_id, section_id)
);

CREATE TABLE IF NOT EXISTS clauses (
    clause_id TEXT PRIMARY KEY,
    standard_id TEXT NOT NULL REFERENCES standards(standard_id) ON DELETE CASCADE,
    clause_no TEXT NOT NULL,
    num_a INTEGER NOT NULL,
    num_b INTEGER NOT NULL,
    num_c INTEGER NOT NULL,
    chapter_no INTEGER NOT NULL,
    section_id TEXT NOT NULL,
    path_json TEXT NOT NULL,
    text TEXT NOT NULL,
    intro TEXT NOT NULL,
    source_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    has_table INTEGER NOT NULL DEFAULT 0,
    ordinal INTEGER NOT NULL,
    UNIQUE (standard_id, clause_no)
);
CREATE INDEX IF NOT EXISTS idx_clauses_section
    ON clauses(standard_id, section_id, num_a, num_b, num_c);

CREATE TABLE IF NOT EXISTS clause_parts (
    clause_id TEXT NOT NULL REFERENCES clauses(clause_id) ON DELETE CASCADE,
    part_type TEXT NOT NULL,
    part_no INTEGER NOT NULL,
    kuan_no INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    source_line INTEGER NOT NULL,
    PRIMARY KEY (clause_id, part_type, kuan_no, part_no)
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    standard_id TEXT NOT NULL REFERENCES standards(standard_id) ON DELETE CASCADE,
    clause_id TEXT REFERENCES clauses(clause_id) ON DELETE CASCADE,
    section_id TEXT,
    chunk_type TEXT NOT NULL,
    clause_no TEXT,
    chapter_no INTEGER,
    section_a INTEGER,
    section_b INTEGER,
    num_a INTEGER,
    num_b INTEGER,
    num_c INTEGER,
    path_json TEXT NOT NULL DEFAULT '[]',
    kuan_no INTEGER,
    item_nos_json TEXT NOT NULL DEFAULT '[]',
    section_clause_count INTEGER NOT NULL DEFAULT 0,
    table_id TEXT,
    row_no INTEGER,
    has_table INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    embed_text TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    level TEXT NOT NULL,
    version TEXT NOT NULL,
    source_file TEXT NOT NULL,
    over_limit_reason TEXT,
    ordinal INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_standard_type ON chunks(standard_id, chunk_type);
CREATE INDEX IF NOT EXISTS idx_chunks_clause ON chunks(clause_id);

CREATE TABLE IF NOT EXISTS tables (
    standard_id TEXT NOT NULL REFERENCES standards(standard_id) ON DELETE CASCADE,
    table_seq INTEGER NOT NULL,
    table_id TEXT NOT NULL,
    caption TEXT NOT NULL,
    is_continuation INTEGER NOT NULL DEFAULT 0,
    clause_no TEXT,
    source_line INTEGER NOT NULL,
    notes_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (standard_id, table_seq)
);

CREATE TABLE IF NOT EXISTS table_rows (
    standard_id TEXT NOT NULL,
    table_seq INTEGER NOT NULL,
    row_no INTEGER NOT NULL,
    cells_json TEXT NOT NULL,
    PRIMARY KEY (standard_id, table_seq, row_no),
    FOREIGN KEY (standard_id, table_seq)
        REFERENCES tables(standard_id, table_seq) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS "references" (
    src_clause_id TEXT NOT NULL REFERENCES clauses(clause_id) ON DELETE CASCADE,
    ref_type TEXT NOT NULL,
    dst_id TEXT NOT NULL,
    dst_standard_id TEXT,
    source_line INTEGER,
    PRIMARY KEY (src_clause_id, ref_type, dst_id)
);

CREATE TABLE IF NOT EXISTS lexicon (
    term TEXT PRIMARY KEY,
    freq INTEGER NOT NULL,
    score REAL NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate'
);

CREATE TABLE IF NOT EXISTS aliases (
    standard_id TEXT NOT NULL,
    alias TEXT NOT NULL,
    alias_type TEXT NOT NULL,
    PRIMARY KEY (standard_id, alias)
);

CREATE TABLE IF NOT EXISTS query_expansion (
    from_text TEXT NOT NULL,
    to_text TEXT NOT NULL,
    kind TEXT NOT NULL,
    PRIMARY KEY (from_text, to_text, kind)
);

CREATE TABLE IF NOT EXISTS front_matter (
    standard_id TEXT NOT NULL REFERENCES standards(standard_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    source_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    is_indexed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (standard_id, kind)
);

CREATE TABLE IF NOT EXISTS images (
    image_id INTEGER PRIMARY KEY AUTOINCREMENT,
    standard_id TEXT NOT NULL REFERENCES standards(standard_id) ON DELETE CASCADE,
    clause_id TEXT,
    alt TEXT NOT NULL,
    path TEXT NOT NULL,
    source_line INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    standard_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    clause_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    source_sha256 TEXT,
    message TEXT
);
"""


@dataclass(frozen=True, slots=True)
class IngestStats:
    """一次入库的结果；created=False 表示同版本幂等替换。"""

    standard_id: str
    source_sha256: str
    clauses: int
    chunks: int
    tables: int
    references: int
    created: bool


class SqliteStore:
    """单文件 SQLite 的 schema 与写入/查询入口。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        """建表并设置 user_version；版本不符时拒绝打开。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                connection.executescript(_DDL)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                connection.commit()
            elif version != SCHEMA_VERSION:
                raise StoreError(
                    f"SQLite schema 版本不符：期望 {SCHEMA_VERSION}，实际 {version}"
                )

    def replace_standard(
        self,
        parsed: ParsedStandard,
        chunks: Sequence[Chunk],
        references: Sequence[Reference] = (),
        *,
        source_sha256: str,
        version: str,
        aliases: Sequence[Alias] = (),
        expansions: Sequence[Expansion] = (),
        lexicon: Sequence[LexiconTerm] = (),
        now: datetime | None = None,
    ) -> IngestStats:
        """单事务写入一部规范；同内容幂等替换，不同内容拒绝。"""
        standard_id = parsed.standard.standard_id
        timestamp = (now or datetime.now(UTC)).isoformat(timespec="seconds")
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT source_sha256 FROM standards WHERE standard_id = ?",
                    (standard_id,),
                ).fetchone()
                if existing is not None and existing["source_sha256"] != source_sha256:
                    raise CorpusError(
                        f"标准 {standard_id} 已入库且内容不同（不同版本默认拒绝）；"
                        "如需替换请先人工确认"
                    )
                created = existing is None
                if existing is not None:
                    connection.execute(
                        "DELETE FROM standards WHERE standard_id = ?", (standard_id,)
                    )
                self._insert_standard(connection, parsed, source_sha256, version, timestamp)
                self._insert_structure(connection, parsed)
                self._insert_chunks(connection, chunks)
                self._insert_tables(connection, parsed)
                self._insert_references(connection, references)
                self._insert_front_matter(connection, parsed)
                self._insert_images(connection, parsed)
                self._insert_lexicon(connection, aliases, expansions, lexicon)
                connection.execute(
                    "INSERT INTO ingest_runs "
                    "(standard_id, started_at, finished_at, status, clause_count, "
                    " chunk_count, source_sha256, message) "
                    "VALUES (?, ?, ?, 'success', ?, ?, ?, ?)",
                    (
                        standard_id,
                        timestamp,
                        timestamp,
                        len(parsed.clauses),
                        len(chunks),
                        source_sha256,
                        "created" if created else "replaced",
                    ),
                )
                connection.commit()
            except sqlite3.Error as exc:
                connection.rollback()
                raise StoreError(f"写入失败已整体回滚：{exc}") from exc
            except BaseException:
                connection.rollback()
                raise
        return IngestStats(
            standard_id=standard_id,
            source_sha256=source_sha256,
            clauses=len(parsed.clauses),
            chunks=len(chunks),
            tables=len(parsed.tables),
            references=len(references),
            created=created,
        )

    def _insert_standard(
        self,
        connection: sqlite3.Connection,
        parsed: ParsedStandard,
        source_sha256: str,
        version: str,
        timestamp: str,
    ) -> None:
        connection.execute(
            "INSERT INTO standards (standard_id, name, level, effective_date, version, "
            " source_file, source_sha256, superseded_by, is_current, parsed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 1, ?)",
            (
                parsed.standard.standard_id,
                parsed.standard.name,
                "全文强制" if parsed.standard.mandatory else "非全文强制",
                parsed.standard.effective_date.isoformat()
                if parsed.standard.effective_date
                else None,
                version,
                parsed.source_name,
                source_sha256,
                timestamp,
            ),
        )

    def _insert_structure(self, connection: sqlite3.Connection, parsed: ParsedStandard) -> None:
        standard_id = parsed.standard.standard_id
        connection.executemany(
            "INSERT INTO chapters (standard_id, chapter_no, title, raw_title, marks, "
            " source_line) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    standard_id,
                    chapter.chapter_no,
                    chapter.title,
                    chapter.raw_title,
                    chapter.marks,
                    chapter.source_line,
                )
                for chapter in parsed.chapters
            ],
        )
        clause_counts: dict[str, int] = {}
        for clause in parsed.clauses:
            clause_counts[clause.section_id] = clause_counts.get(clause.section_id, 0) + 1
        connection.executemany(
            "INSERT INTO sections (standard_id, section_id, chapter_no, title, raw_title, "
            " marks, is_term, clause_count, source_line) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    standard_id,
                    section.section_id,
                    section.chapter_no,
                    section.title,
                    section.raw_title,
                    section.marks,
                    int(section.is_term),
                    clause_counts.get(section.section_id, 0),
                    section.source_line,
                )
                for section in parsed.sections
            ],
        )
        connection.executemany(
            "INSERT INTO clauses (clause_id, standard_id, clause_no, num_a, num_b, num_c, "
            " chapter_no, section_id, path_json, text, intro, source_line, end_line, "
            " has_table, ordinal) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    clause.clause_id,
                    standard_id,
                    clause.clause_no,
                    clause.num_key[0],
                    clause.num_key[1],
                    clause.num_key[2],
                    clause.chapter_no,
                    clause.section_id,
                    json.dumps(list(clause.path), ensure_ascii=False),
                    clause.text,
                    clause.intro,
                    clause.source_line,
                    clause.end_line,
                    int(bool(clause.tables)),
                    ordinal,
                )
                for ordinal, clause in enumerate(parsed.clauses, start=1)
            ],
        )
        parts: list[tuple] = []
        for clause in parsed.clauses:
            if clause.intro:
                parts.append((clause.clause_id, "intro", 1, 0, clause.intro, clause.source_line))
            for kuan in clause.kuans:
                parts.append(
                    (
                        clause.clause_id,
                        "kuan",
                        kuan.kuan_no,
                        kuan.kuan_no,
                        kuan.text,
                        kuan.source_line,
                    )
                )
                for item in kuan.items:
                    parts.append(
                        (
                            clause.clause_id,
                            "item",
                            item.item_no,
                            kuan.kuan_no,
                            item.text,
                            item.source_line,
                        )
                    )
        connection.executemany(
            "INSERT INTO clause_parts (clause_id, part_type, part_no, kuan_no, text, "
            " source_line) VALUES (?, ?, ?, ?, ?, ?)",
            parts,
        )

    def _insert_chunks(self, connection: sqlite3.Connection, chunks: Sequence[Chunk]) -> None:
        connection.executemany(
            "INSERT INTO chunks (chunk_id, standard_id, clause_id, section_id, chunk_type, "
            " clause_no, chapter_no, section_a, section_b, num_a, num_b, num_c, path_json, "
            " kuan_no, item_nos_json, section_clause_count, table_id, row_no, has_table, "
            " text, embed_text, token_count, level, version, source_file, over_limit_reason, "
            " ordinal) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            " ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    chunk.chunk_id,
                    chunk.standard_id,
                    chunk.clause_id,
                    chunk.section_id,
                    chunk.chunk_type.value,
                    chunk.clause_no,
                    chunk.chapter_no,
                    chunk.section_num[0] if chunk.section_num else None,
                    chunk.section_num[1] if chunk.section_num else None,
                    chunk.num_key[0] if chunk.num_key else None,
                    chunk.num_key[1] if chunk.num_key else None,
                    chunk.num_key[2] if chunk.num_key else None,
                    json.dumps(list(chunk.path), ensure_ascii=False),
                    chunk.kuan_no,
                    json.dumps(list(chunk.item_nos)),
                    chunk.section_clause_count,
                    chunk.table_id,
                    chunk.row_no,
                    int(chunk.has_table),
                    chunk.text,
                    chunk.embed_text,
                    chunk.token_count,
                    chunk.level,
                    chunk.version,
                    chunk.source_file,
                    chunk.over_limit_reason,
                    ordinal,
                )
                for ordinal, chunk in enumerate(chunks, start=1)
            ],
        )

    def _insert_tables(self, connection: sqlite3.Connection, parsed: ParsedStandard) -> None:
        standard_id = parsed.standard.standard_id
        connection.executemany(
            "INSERT INTO tables (standard_id, table_seq, table_id, caption, is_continuation, "
            " clause_no, source_line, notes_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    standard_id,
                    sequence,
                    table.table_id,
                    table.caption,
                    int(table.is_continuation),
                    table.clause_no,
                    table.source_line,
                    json.dumps(list(table.notes), ensure_ascii=False),
                )
                for sequence, table in enumerate(parsed.tables, start=1)
            ],
        )
        rows: list[tuple] = []
        for sequence, table in enumerate(parsed.tables, start=1):
            for row_no, row in enumerate(table.rows, start=1):
                rows.append(
                    (
                        standard_id,
                        sequence,
                        row_no,
                        json.dumps(list(row), ensure_ascii=False),
                    )
                )
        connection.executemany(
            "INSERT INTO table_rows (standard_id, table_seq, row_no, cells_json) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )

    def _insert_references(
        self, connection: sqlite3.Connection, references: Sequence[Reference]
    ) -> None:
        connection.executemany(
            'INSERT OR IGNORE INTO "references" (src_clause_id, ref_type, dst_id, '
            " dst_standard_id, source_line) VALUES (?, ?, ?, ?, ?)",
            [
                (
                    reference.src_clause_id,
                    reference.ref_type.value,
                    reference.dst_id,
                    reference.dst_standard_id,
                    reference.source_line,
                )
                for reference in references
            ],
        )

    def _insert_front_matter(
        self, connection: sqlite3.Connection, parsed: ParsedStandard
    ) -> None:
        connection.executemany(
            "INSERT INTO front_matter (standard_id, kind, text, source_line, end_line, "
            " is_indexed) VALUES (?, ?, ?, ?, ?, 0)",
            [
                (
                    parsed.standard.standard_id,
                    block.kind,
                    block.text,
                    block.source_line,
                    block.end_line,
                )
                for block in parsed.front_matter
            ],
        )

    def _insert_images(self, connection: sqlite3.Connection, parsed: ParsedStandard) -> None:
        owners: dict[tuple[int, str], str] = {}
        for clause in parsed.clauses:
            for image in clause.images:
                owners[(image.source_line, image.path)] = clause.clause_id
        rows = [
            (
                parsed.standard.standard_id,
                owners.get((image.source_line, image.path)),
                image.alt,
                image.path,
                image.source_line,
            )
            for image in parsed.images
        ]
        if rows:
            connection.executemany(
                "INSERT INTO images (standard_id, clause_id, alt, path, source_line) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )

    def _insert_lexicon(
        self,
        connection: sqlite3.Connection,
        aliases: Sequence[Alias],
        expansions: Sequence[Expansion],
        lexicon: Sequence[LexiconTerm],
    ) -> None:
        if aliases:
            connection.executemany(
                "INSERT OR IGNORE INTO aliases (standard_id, alias, alias_type) "
                "VALUES (?, ?, ?)",
                [(item.standard_id, item.alias, item.alias_type) for item in aliases],
            )
        if expansions:
            connection.executemany(
                "INSERT OR IGNORE INTO query_expansion (from_text, to_text, kind) "
                "VALUES (?, ?, ?)",
                [(item.from_text, item.to_text, item.kind) for item in expansions],
            )
        if lexicon:
            connection.executemany(
                "INSERT OR REPLACE INTO lexicon (term, freq, score, source, status) "
                "VALUES (?, ?, ?, ?, 'candidate')",
                [(item.term, item.freq, item.score, item.source) for item in lexicon],
            )

    def counts(self) -> dict[str, int]:
        """各表行数，便于测试与运维核对。"""
        tables = (
            "standards",
            "chapters",
            "sections",
            "clauses",
            "clause_parts",
            "chunks",
            "tables",
            "table_rows",
            '"references"',
            "lexicon",
            "aliases",
            "query_expansion",
            "front_matter",
            "images",
            "ingest_runs",
        )
        with self._connect() as connection:
            return {
                name.strip('"'): connection.execute(
                    f"SELECT COUNT(*) FROM {name}"
                ).fetchone()[0]
                for name in tables
            }

    def chunks_for(
        self, standard_id: str, chunk_type: str | None = None
    ) -> list[sqlite3.Row]:
        query = "SELECT * FROM chunks WHERE standard_id = ?"
        parameters: list[object] = [standard_id]
        if chunk_type is not None:
            query += " AND chunk_type = ?"
            parameters.append(chunk_type)
        query += " ORDER BY ordinal"
        with self._connect() as connection:
            return list(connection.execute(query, parameters))

    def front_matter_for(self, standard_id: str) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return list(
                connection.execute(
                    "SELECT * FROM front_matter WHERE standard_id = ? ORDER BY source_line",
                    (standard_id,),
                )
            )

    def reference_edges_for(self, standard_id: str) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return list(
                connection.execute(
                    'SELECT r.* FROM "references" r JOIN clauses c ON c.clause_id = '
                    " r.src_clause_id WHERE c.standard_id = ? ORDER BY r.src_clause_id",
                    (standard_id,),
                )
            )

    def clause_row(self, clause_id: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM clauses WHERE clause_id = ?", (clause_id,)
            ).fetchone()

    def clause_ids(self, standard_id: str) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT clause_id FROM clauses WHERE standard_id = ? "
                "ORDER BY num_a, num_b, num_c",
                (standard_id,),
            ).fetchall()
        return [row["clause_id"] for row in rows]

    def chunks_for_reindex(
        self, standard_ids: Sequence[str] | None = None
    ) -> list[sqlite3.Row]:
        """读取重建 Milvus 所需的块与嵌入文本（不读原文以外的内容）。"""
        query = (
            "SELECT chunk_id, standard_id, chunk_type, level, clause_id, section_id, "
            " clause_no, kuan_no, table_id, row_no, embed_text FROM chunks"
        )
        parameters: list[object] = []
        if standard_ids:
            placeholders = ", ".join("?" for _ in standard_ids)
            query += f" WHERE standard_id IN ({placeholders})"
            parameters.extend(standard_ids)
        query += " ORDER BY standard_id, ordinal"
        with self._connect() as connection:
            return list(connection.execute(query, parameters))

    def chunk_counts_by_standard(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT standard_id, COUNT(*) AS total FROM chunks GROUP BY standard_id"
            ).fetchall()
        return {row["standard_id"]: int(row["total"]) for row in rows}

    def chunks_by_ids(self, chunk_ids: Sequence[str]) -> list[sqlite3.Row]:
        if not chunk_ids:
            return []
        placeholders = ", ".join("?" for _ in chunk_ids)
        with self._connect() as connection:
            return list(
                connection.execute(
                    f"SELECT * FROM chunks WHERE chunk_id IN ({placeholders})",
                    list(chunk_ids),
                )
            )

    def clauses_by_ids(self, clause_ids: Sequence[str]) -> list[sqlite3.Row]:
        if not clause_ids:
            return []
        placeholders = ", ".join("?" for _ in clause_ids)
        with self._connect() as connection:
            return list(
                connection.execute(
                    f"SELECT * FROM clauses WHERE clause_id IN ({placeholders})",
                    list(clause_ids),
                )
            )

    def clause_ids_by_no(
        self, clause_no: str, standard_id: str | None = None
    ) -> list[str]:
        query = "SELECT clause_id FROM clauses WHERE clause_no = ?"
        parameters: list[str] = [clause_no]
        if standard_id is not None:
            query += " AND standard_id = ?"
            parameters.append(standard_id)
        query += " ORDER BY standard_id"
        with self._connect() as connection:
            return [
                row["clause_id"]
                for row in connection.execute(query, parameters).fetchall()
            ]

    def clause_parts_for(self, clause_ids: Sequence[str]) -> list[sqlite3.Row]:
        if not clause_ids:
            return []
        placeholders = ", ".join("?" for _ in clause_ids)
        with self._connect() as connection:
            return list(
                connection.execute(
                    "SELECT * FROM clause_parts WHERE clause_id IN "
                    f"({placeholders}) ORDER BY part_type, kuan_no, part_no",
                    list(clause_ids),
                )
            )

    def tables_for_clause(self, standard_id: str, clause_no: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            tables = connection.execute(
                "SELECT * FROM tables WHERE standard_id = ? AND clause_no = ? "
                "ORDER BY table_seq",
                (standard_id, clause_no),
            ).fetchall()
            result: list[dict[str, Any]] = []
            for table in tables:
                rows = connection.execute(
                    "SELECT row_no, cells_json FROM table_rows WHERE standard_id = ? "
                    "AND table_seq = ? ORDER BY row_no",
                    (standard_id, table["table_seq"]),
                ).fetchall()
                result.append({"table": table, "rows": [dict(row) for row in rows]})
        return result

    def standard_names(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT standard_id, name FROM standards").fetchall()
        return {row["standard_id"]: row["name"] for row in rows}

    def standard_levels(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT standard_id, level FROM standards").fetchall()
        return {row["standard_id"]: str(row["level"]) for row in rows}

    def section_clause_counts(self, standard_id: str) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT section_id, clause_count FROM sections WHERE standard_id = ?",
                (standard_id,),
            ).fetchall()
        return {row["section_id"]: int(row["clause_count"]) for row in rows}

    def scope_chunks_for_sections(
        self, standard_id: str, section_ids: Sequence[str]
    ) -> list[sqlite3.Row]:
        if not section_ids:
            return []
        placeholders = ", ".join("?" for _ in section_ids)
        with self._connect() as connection:
            return list(
                connection.execute(
                    "SELECT chunk_id, section_id, text FROM chunks WHERE standard_id = ? "
                    f"AND chunk_type = 'scope' AND section_id IN ({placeholders})",
                    [standard_id, *section_ids],
                )
            )

    def alias_index(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT standard_id, alias FROM aliases ORDER BY alias"
            ).fetchall()
        return {row["alias"]: row["standard_id"] for row in rows}

    def query_expansions(self) -> list[tuple[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT from_text, to_text FROM query_expansion ORDER BY from_text"
            ).fetchall()
        return [(row["from_text"], row["to_text"]) for row in rows]

    def clause_reference_targets(self, clause_ids: Sequence[str]) -> list[sqlite3.Row]:
        if not clause_ids:
            return []
        placeholders = ", ".join("?" for _ in clause_ids)
        with self._connect() as connection:
            return list(
                connection.execute(
                    'SELECT src_clause_id, dst_id FROM "references" WHERE ref_type = '
                    f"'clause' AND src_clause_id IN ({placeholders}) ORDER BY src_clause_id",
                    list(clause_ids),
                )
            )

    def approved_terms(self, limit: int = 100) -> list[str]:
        """人工审核通过的术语，按分数排序，用于系统提示词里的术语表。"""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT term FROM lexicon WHERE status = 'approved' "
                "ORDER BY score DESC, term LIMIT ?",
                (limit,),
            ).fetchall()
        return [row["term"] for row in rows]

    def superseded_by_map(self, standard_ids: Sequence[str]) -> dict[str, str]:
        if not standard_ids:
            return {}
        placeholders = ", ".join("?" for _ in standard_ids)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT standard_id, superseded_by FROM standards "
                f"WHERE standard_id IN ({placeholders}) AND superseded_by IS NOT NULL",
                list(standard_ids),
            ).fetchall()
        return {row["standard_id"]: str(row["superseded_by"]) for row in rows}

    def search_chunks_like(self, terms: Sequence[str], limit: int = 30) -> list[sqlite3.Row]:
        """DEV_MODE 用的关键词退化检索（LIKE），结果不得作为质量依据。"""
        cleaned = [term.strip() for term in terms if term.strip()]
        if not cleaned:
            return []
        clauses = " OR ".join("(text LIKE ? OR embed_text LIKE ?)" for _ in cleaned)
        parameters: list[object] = []
        for term in cleaned:
            pattern = f"%{term}%"
            parameters.extend([pattern, pattern])
        query = (
            "SELECT * FROM chunks "
            f"WHERE ({clauses}) AND chunk_type != 'scope' "
            "ORDER BY ordinal LIMIT ?"
        )
        parameters.append(limit)
        with self._connect() as connection:
            return list(connection.execute(query, parameters))

    def clauses_in_section(self, standard_id: str, section_no: str) -> list[sqlite3.Row]:
        """节内全部条文；section_no 为章号（无点）时按章取。"""
        with self._connect() as connection:
            if "." in section_no:
                return list(
                    connection.execute(
                        "SELECT * FROM clauses WHERE standard_id = ? AND section_id = ? "
                        "ORDER BY num_a, num_b, num_c",
                        (standard_id, section_no),
                    )
                )
            return list(
                connection.execute(
                    "SELECT * FROM clauses WHERE standard_id = ? AND chapter_no = ? "
                    "ORDER BY num_a, num_b, num_c",
                    (standard_id, int(section_no)),
                )
            )

    def list_standards(self) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return list(
                connection.execute(
                    "SELECT * FROM standards ORDER BY standard_id"
                )
            )

    def chapters_for(self, standard_id: str) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return list(
                connection.execute(
                    "SELECT * FROM chapters WHERE standard_id = ? ORDER BY chapter_no",
                    (standard_id,),
                )
            )

    def sections_for(self, standard_id: str) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return list(
                connection.execute(
                    "SELECT * FROM sections WHERE standard_id = ? "
                    "ORDER BY chapter_no, section_id",
                    (standard_id,),
                )
            )
