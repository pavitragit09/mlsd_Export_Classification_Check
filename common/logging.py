"""Structured JSON logging with correlation ID propagation."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict
from common.security import redact_sensitive_text
from common.telemetry import get_correlation_id


class JSONFormatter(logging.Formatter):
    """Formats log records as structured JSON with sensitive token redaction."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_sensitive_text(record.getMessage()),
            "correlation_id": get_correlation_id(),
        }

        # Include custom attributes if passed via extra
        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            clean_extra = {}
            for k, v in record.extra_data.items():
                if isinstance(v, str):
                    clean_extra[k] = redact_sensitive_text(v)
                else:
                    clean_extra[k] = v
            log_obj.update(clean_extra)

        if record.exc_info:
            log_obj["exception"] = redact_sensitive_text(self.formatException(record.exc_info))

        return json.dumps(log_obj)


def setup_logger(name: str = "mlsd_service", level: str = "INFO") -> logging.Logger:
    """Configures and returns a logger emitting JSON lines."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid duplicate handlers if called multiple times
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)

    logger.propagate = False
    return logger


logger = setup_logger()
