"""Structured JSON logging configuration (NFR-07).

Call :func:`setup_logging` once at process startup (worker or API). All
pipeline stages then emit JSON log entries with ``timestamp``, ``level``,
``task``, ``stage``, ``message`` and optional ``duration_ms`` /
``episode_id`` fields.
"""

from __future__ import annotations

import logging
import sys

from pythonjsonlogger.json import JsonFormatter


_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


class PodlettersJsonFormatter(JsonFormatter):
    """Extends python-json-logger with default fields for observability."""

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record.setdefault("timestamp", log_record.pop("asctime", None))
        log_record.setdefault("level", record.levelname)
        log_record.setdefault("logger", record.name)


def setup_logging(*, level: int = logging.INFO, json_output: bool = True) -> None:
    """Configure the root logger for structured output.

    Parameters
    ----------
    level:
        Minimum log level.
    json_output:
        If ``True`` (default), emit newline-delimited JSON to stderr.
        If ``False``, use a human-readable format (useful during local dev).
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers to avoid double output.
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    if json_output:
        handler.setFormatter(PodlettersJsonFormatter(_LOG_FORMAT))
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s - %(message)s")
        )
    root.addHandler(handler)

    # Reduce noise from noisy libraries.
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.INFO)


__all__ = ["setup_logging"]
