"""入库编排与 CLI 测试。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from archrag.corpus.ingest import ingest_corpus, run_census
from archrag.corpus.models import Standard
from archrag.errors import CorpusError
from archrag.store.sqlite import SqliteStore

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_census_passes_on_real_corpus(corpus_dir, standard_map) -> None:
    report = run_census([corpus_dir / name for name in standard_map])
    assert report.returncode == 0
    assert report.number_gap_lines == ()
    assert report.marked_issue_lines == ()


def test_ingest_corpus_single_file(tmp_path, standard_map, corpus_dir, token_counter) -> None:
    store = SqliteStore(tmp_path / "ingest.sqlite")
    store.initialize()
    outcome = ingest_corpus(
        store,
        standard_map,
        corpus_dir=corpus_dir,
        count_tokens=token_counter.count,
        files=["民用建筑通用规范.md"],
    )
    assert outcome.census is not None
    assert len(outcome.stats) == 1
    stats = outcome.stats[0]
    assert (stats.standard_id, stats.clauses, stats.created) == ("GB 55031-2022", 142, True)
    counts = store.counts()
    assert counts["standards"] == 1
    assert counts["clauses"] == 142
    assert counts["aliases"] == 3
    assert counts["query_expansion"] > 0
    assert outcome.candidates.terms


def test_number_gap_blocks_ingest(tmp_path, token_counter) -> None:
    bad = tmp_path / "bad.md"
    bad.write_text("# 1 总 则\n\n1.0.1 甲。\n\n1.0.3 丙。\n", encoding="utf-8")
    standard = Standard(standard_id="GB 59999-2025", name="测试规范", file_name="bad.md")
    store = SqliteStore(tmp_path / "blocked.sqlite")
    store.initialize()
    with pytest.raises(CorpusError):
        ingest_corpus(
            store,
            {"bad.md": standard},
            corpus_dir=tmp_path,
            count_tokens=token_counter.count,
        )
    assert store.counts()["standards"] == 0


def test_cli_ingests_single_file(tmp_path) -> None:
    database = tmp_path / "cli.sqlite"
    completed = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(REPO_ROOT / "project" / "scripts" / "ingest_corpus.py"),
            "--file",
            "民用建筑通用规范.md",
            "--sqlite-path",
            str(database),
            "--skip-milvus",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    store = SqliteStore(database)
    assert store.counts()["clauses"] == 142
    assert store.counts()["standards"] == 1
