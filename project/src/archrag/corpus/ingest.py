"""入库编排：普查前置 → 解析 → 切块 → 引用图 → 单事务写 SQLite。

前置普查复用 `normalize-regulation-md` 技能的只读脚本：条号数量与连续性异常
时阻断入库；其余标记异常只报告（铁律 13）。
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from archrag.config import REPO_ROOT
from archrag.corpus.chunker import DEFAULT_MAX_TOKENS, build_chunks
from archrag.corpus.lexicon import LexiconCandidates, build_candidates
from archrag.corpus.models import Standard
from archrag.corpus.parser import parse_file
from archrag.corpus.references import extract_references
from archrag.errors import CorpusError
from archrag.store.sqlite import IngestStats, SqliteStore

CENSUS_SCRIPT = (
    REPO_ROOT / ".agents" / "skills" / "normalize-regulation-md" / "scripts" / "scan_structure.py"
)


@dataclass(frozen=True, slots=True)
class CensusReport:
    """普查脚本的只读结果。"""

    files: tuple[str, ...]
    returncode: int
    number_gap_lines: tuple[str, ...]
    marked_issue_lines: tuple[str, ...]
    output: str


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    """一次入库的统计与普查结果。"""

    stats: tuple[IngestStats, ...]
    census: CensusReport | None
    candidates: LexiconCandidates


def run_census(
    paths: Sequence[Path], *, script_path: Path | None = None
) -> CensusReport:
    """调用普查脚本（显式传语料文件，不传映射表）。"""
    script = Path(script_path) if script_path is not None else CENSUS_SCRIPT
    if not script.is_file():
        raise CorpusError(f"普查脚本不存在：{script}")
    resolved = [Path(path) for path in paths]
    missing = [str(path) for path in resolved if not path.is_file()]
    if missing:
        raise CorpusError(f"语料文件不存在：{missing}")
    completed = subprocess.run(
        [sys.executable, "-X", "utf8", str(script), *(str(path) for path in resolved)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if completed.returncode not in (0, 2):
        message = (completed.stderr or completed.stdout).strip()[:300]
        raise CorpusError(f"普查脚本执行失败（exit={completed.returncode}）：{message}")
    output = completed.stdout
    gap_lines = tuple(
        line.strip() for line in output.splitlines() if line.strip().startswith("!! 条号缺口")
    )
    issue_lines = tuple(
        line.strip()
        for line in output.splitlines()
        if line.strip().startswith("!!") and line.strip() not in gap_lines
    )
    return CensusReport(
        files=tuple(path.name for path in resolved),
        returncode=completed.returncode,
        number_gap_lines=gap_lines,
        marked_issue_lines=issue_lines,
        output=output,
    )


def ingest_corpus(
    store: SqliteStore,
    standard_map: Mapping[str, Standard],
    *,
    corpus_dir: Path,
    count_tokens: Callable[[str], int],
    files: Sequence[str] | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    run_census_first: bool = True,
    census_script: Path | None = None,
) -> IngestOutcome:
    """按文件名列表入库；默认全部；任一步失败由 store 回滚该标准。"""
    selected = list(files) if files is not None else list(standard_map)
    unknown = [name for name in selected if name not in standard_map]
    if unknown:
        raise CorpusError(f"映射表中没有这些语料文件：{unknown}")
    paths = [Path(corpus_dir) / name for name in selected]
    census: CensusReport | None = None
    if run_census_first:
        census = run_census(paths, script_path=census_script)
        if census.number_gap_lines:
            raise CorpusError(
                "条号数量或连续性异常，已阻断入库："
                + "；".join(census.number_gap_lines[:3])
            )
    parsed_list = [
        parse_file(path, standard_map[name]) for name, path in zip(selected, paths, strict=True)
    ]
    candidates = build_candidates(parsed_list)
    stats: list[IngestStats] = []
    for parsed, path in zip(parsed_list, paths, strict=True):
        digest = _sha256(path)
        chunks = build_chunks(
            parsed,
            version=digest[:12],
            count_tokens=count_tokens,
            max_tokens=max_tokens,
        )
        references = extract_references(parsed)
        stats.append(
            store.replace_standard(
                parsed,
                chunks,
                references,
                source_sha256=digest,
                version=digest[:12],
                aliases=candidates.aliases,
                expansions=candidates.expansions,
            )
        )
    return IngestOutcome(stats=tuple(stats), census=census, candidates=candidates)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
