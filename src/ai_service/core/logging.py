import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include standard context fields if attached to the record
        context_fields = (
            "request_id",
            "tenant_id",
            "user_id",
            "duration_ms",
            "path",
            "method",
            "status_code",
            # one line per language-model call (services/llm_accounting.py)
            "feature",
            "prompt_name",
            "prompt_version",
            "backend",
            "model",
            "operation",
            "status",
            "error_type",
            "stop_reason",
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "cost_usd",
            "latency_ms",
        )
        for attr in context_fields:
            if hasattr(record, attr):
                log_entry[attr] = getattr(record, attr)

        # Include exception info if available
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(debug: bool = False) -> None:
    """Configure the root logger to output structured JSON."""
    log_level = logging.DEBUG if debug else logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Replace existing handlers to ensure single JSON output
    root_logger.handlers = [handler]

    # Silence overly verbose third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

