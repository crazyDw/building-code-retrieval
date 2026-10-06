"""JSON Lines 日志的行为测试。"""

from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path

from archrag.logging_setup import LOG_FILE_NAME, setup_logging


def _read_records(log_dir: Path) -> list[dict[str, object]]:
    text = (log_dir / LOG_FILE_NAME).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line]


def _read_raw(log_dir: Path) -> str:
    return (log_dir / LOG_FILE_NAME).read_text(encoding="utf-8")


def test_writes_one_json_object_per_record(tmp_path: Path) -> None:
    logger = setup_logging(tmp_path, console=False)
    logger.info("检索命中 %s", "5.3.9")
    records = _read_records(tmp_path)
    assert len(records) == 1
    assert records[0]["message"] == "检索命中 5.3.9"
    assert records[0]["level"] == "INFO"


def test_chinese_is_written_as_utf8(tmp_path: Path) -> None:
    logger = setup_logging(tmp_path, console=False)
    logger.info("中文日志")
    assert "中文日志" in _read_raw(tmp_path)


def test_extra_fields_are_serialized(tmp_path: Path) -> None:
    logger = setup_logging(tmp_path, console=False)
    logger.warning(
        "degraded",
        extra={"clause_id": "GB 55031-2022_5.3.9", "duration_ms": 12},
    )
    record = _read_records(tmp_path)[0]
    assert record["clause_id"] == "GB 55031-2022_5.3.9"
    assert record["duration_ms"] == 12


def test_secret_like_extra_fields_are_dropped(tmp_path: Path) -> None:
    logger = setup_logging(tmp_path, console=False)
    logger.info(
        "call",
        extra={"api_key": "sk-secret-value", "authorization": "Bearer secret-token"},
    )
    raw = _read_raw(tmp_path)
    assert "sk-secret-value" not in raw
    assert "Bearer secret-token" not in raw
    record = _read_records(tmp_path)[0]
    assert "api_key" not in record
    assert "authorization" not in record


def test_repeated_setup_does_not_duplicate_records(tmp_path: Path) -> None:
    setup_logging(tmp_path, console=False)
    logger = setup_logging(tmp_path, console=False)
    logger.info("once")
    assert len(_read_records(tmp_path)) == 1


def test_file_handler_rotates_daily_and_keeps_backup_count(tmp_path: Path) -> None:
    logger = setup_logging(tmp_path, console=False, backup_days=7)
    handler = next(
        item
        for item in logger.handlers
        if isinstance(item, logging.handlers.TimedRotatingFileHandler)
    )
    assert handler.when == "MIDNIGHT"
    assert handler.backupCount == 7
