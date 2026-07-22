"""Structured logging with secret scrubbing.

The integration clients log request/response metadata for debuggability. That is
only safe if credentials can never reach a log sink, so scrubbing happens here —
in a processor every logger shares — rather than relying on each call site to
remember.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

# Keys whose values are replaced wholesale, matched case-insensitively on substring.
SENSITIVE_KEY_PARTS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "cookie",
    "session",
    "csrf",
    "x-api-key",
    "lexware_api_key",
    "clockify_api_key",
    "clockify-signature",
    "private",
    "credential",
    "signature",
)

REDACTED = "***redacted***"

# Bearer tokens / API keys that end up inside free-text messages or URLs.
_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)
_QUERY_SECRET_RE = re.compile(
    r"([?&](?:token|key|secret|api_key|apikey|signature)=)[^&\s]+", re.IGNORECASE
)


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _scrub_value(value: Any, depth: int = 0) -> Any:
    if depth > 6:  # Defensive: don't walk pathological structures forever.
        return value
    if isinstance(value, dict):
        return {
            k: (REDACTED if _is_sensitive_key(str(k)) else _scrub_value(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        scrubbed = [_scrub_value(v, depth + 1) for v in value]
        return type(value)(scrubbed) if isinstance(value, tuple) else scrubbed
    if isinstance(value, str):
        value = _BEARER_RE.sub(r"\1" + REDACTED, value)
        value = _QUERY_SECRET_RE.sub(r"\1" + REDACTED, value)
        return value
    return value


def scrub_secrets(
    logger: object, method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """structlog processor removing credentials from every log record."""
    return {
        key: (REDACTED if _is_sensitive_key(str(key)) else _scrub_value(value))
        for key, value in event_dict.items()
    }


def configure_structlog() -> None:
    """Configure structlog once at app startup (called from CoreConfig.ready)."""
    from django.conf import settings

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if getattr(settings, "LOG_JSON", False)
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            scrub_secrets,  # Last before rendering: nothing added after can leak.
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger under the ``coreflow`` namespace."""
    if not name.startswith("coreflow"):
        name = f"coreflow.{name}"
    return structlog.stdlib.get_logger(name)
