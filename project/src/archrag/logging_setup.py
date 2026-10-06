"""JSON Lines 日志：UTF-8、按天轮转、默认不落密钥。

入口在启动时调用一次 `setup_logging(log_dir)`；业务代码只用标准库
`logging.getLogger(__name__)` 记录，不经过本模块的其他函数。
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

APP_LOGGER_NAME = "archrag"
LOG_FILE_NAME = "archrag.log"

_SECRET_FIELD_PATTERN = re.compile(
    r"(api[_-]?key|authorization|secret|token|password)", re.IGNORECASE
)
_STANDARD_ATTRS = frozenset(vars(logging.LogRecord("", logging.NOTSET, "", 0, "", (), None)))
_HANDLER_MARKER = "_archrag_json_handler"


class JsonLineFormatter(logging.Formatter):
    """把一条日志记录序列化为单行 JSON。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC)
            .astimezone()
            .isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key in _STANDARD_ATTRS or key.startswith("_"):
                continue
            if _SECRET_FIELD_PATTERN.search(key):
                continue
            payload[key] = _jsonable(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def setup_logging(
    log_dir: Path,
    *,
    level: str | int = "INFO",
    backup_days: int = 14,
    console: bool = True,
    logger_name: str = APP_LOGGER_NAME,
) -> logging.Logger:
    """配置并返回应用日志器；重复调用不会叠加 handler。

    日志写入 `log_dir/archrag.log`，按天轮转，保留 `backup_days` 天。
    始终使用 UTF-8 与 JSON Lines 格式；带密钥样式的 extra 字段会被丢弃。
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = False
    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()

    formatter = JsonLineFormatter()
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_dir / LOG_FILE_NAME,
        when="midnight",
        backupCount=backup_days,
        encoding="utf-8",
        delay=True,
    )
    setattr(file_handler, _HANDLER_MARKER, True)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if console:
        stream_handler = logging.StreamHandler()
        setattr(stream_handler, _HANDLER_MARKER, True)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
    return logger


def _jsonable(value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
