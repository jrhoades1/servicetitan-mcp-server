"""
Structured logging configuration using structlog.

Security guarantees enforced here:
  - Sensitive field names (tokens, secrets, keys) are REDACTED before any output
  - PII fields (customer names, emails, phones) are REDACTED at the processor level
  - No stack traces are emitted to users — only server-side logs
  - JSON output format for machine-parseable log aggregation
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import structlog

# ---------------------------------------------------------------------------
# Fields that must never appear in logs in plaintext
# Checked case-insensitively against all log event_dict keys
# ---------------------------------------------------------------------------
_REDACTED_FIELDS: frozenset[str] = frozenset(
    {
        # Auth / credentials
        "access_token",
        "refresh_token",
        "client_secret",
        "client_id",
        "st_app_key",
        "app_key",
        "authorization",
        "password",
        "token",
        "secret",
        "api_key",
        "bearer",
        # PII (customer data must never reach logs)
        "customer_name",
        "customer_email",
        "customer_phone",
        "customer_address",
        "email",
        "phone",
        "address",
        "ssn",
        "dob",
    }
)


def _scrub_sensitive(
    logger: Any,  # noqa: ANN401 — structlog typing requirement
    method: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """
    structlog processor: replace sensitive field values with [REDACTED].

    Applied before any renderer so nothing sensitive reaches the output.
    Checked case-insensitively; matching key's value is replaced in-place.
    """
    for key in list(event_dict.keys()):
        if key.lower() in _REDACTED_FIELDS:
            event_dict[key] = "[REDACTED]"
    return event_dict


def configure_logging(log_level: str = "INFO", log_file: str | None = None) -> None:
    """
    Configure structlog for structured JSON logging.

    Call once at application startup before any log calls are made.

    Args:
        log_level: One of DEBUG / INFO / WARNING / ERROR / CRITICAL.
        log_file:  Optional file path. Parent directories are created if needed.
                   Logs are always written to stderr; file output is additive.
    """
    if log_file:
        try:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            log_file = None  # Fall back to stderr-only if directory can't be created

    # Processors shared between structlog and stdlib (foreign loggers via
    # ProcessorFormatter so httpx, etc. also go through PII scrubbing)
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _scrub_sensitive,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionRenderer(),
    ]

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    handlers: list[logging.Handler] = []

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    handlers.append(stderr_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    root = logging.getLogger()
    root.handlers = handlers
    root.setLevel(getattr(logging, log_level, logging.INFO))

    # Reduce noise from HTTP internals — they should not produce INFO-level chatter
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("mcp").setLevel(logging.WARNING)
