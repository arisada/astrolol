"""Configure structlog + stdlib logging with optional file output."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog


class _DropMessageFilter(logging.Filter):
    """Drop log records whose message starts with a given prefix."""

    def __init__(self, prefix: str) -> None:
        super().__init__()
        self._prefix = prefix

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.getMessage().startswith(self._prefix)


def setup_logging(log_file: Path | None = None) -> None:
    """
    Wire structlog to stdlib logging and optionally tee to a rotating log file.

    Output format: one JSON object per line (machine-readable, grep-friendly).
    The log file rotates at 10 MB and keeps 5 backups.
    """
    shared_processors: list = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=shared_processors + [
            event_bus_forwarder,   # forward to EventBus before JSON rendering
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Console: human-readable with colors when attached to a TTY
    use_colors = sys.stderr.isatty()
    console_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=use_colors),
        ],
        foreign_pre_chain=shared_processors,
    )

    # File (and non-TTY pipes): newline-delimited JSON for grep/logstash
    json_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=shared_processors,
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Remove any handlers added by uvicorn/FastAPI before we configure ours
    root.handlers.clear()

    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(console_formatter)
    root.addHandler(stderr_handler)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(json_formatter)
        root.addHandler(file_handler)

    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)

    # When PYTHONASYNCIODEBUG=1 is set, expose asyncio's slow-callback warnings.
    # asyncio logs any callback/coroutine taking > 100 ms at WARNING level.
    if os.getenv("PYTHONASYNCIODEBUG"):
        logging.getLogger("asyncio").setLevel(logging.DEBUG)

    # uvicorn emits WARNING-level "Invalid HTTP request received." whenever a
    # browser/proxy sends a non-HTTP probe (e.g. h2 ALPN, health checks using raw
    # TCP, or the OS closing an idle keep-alive).  It is harmless noise.
    _invalid_http_filter = _DropMessageFilter("Invalid HTTP request received.")
    logging.getLogger("uvicorn.error").addFilter(_invalid_http_filter)


# ── EventBus log bridge ───────────────────────────────────────────────────────
# This processor sits in the structlog chain and forwards each INFO+ log entry
# to the EventBus as a LogEvent so the UI shows application logs alongside
# domain events.  Call set_event_bus() after the EventBus is created.

# Loggers whose output would cause feedback loops or is too noisy to forward
_SKIP_LOGGERS = frozenset({
    "astrolol.core.events.bus",
    "asyncio",
})

# Keys added by structlog processors themselves — not user context, skip in extras
_STRUCTLOG_META_KEYS = frozenset({
    "event", "level", "logger", "timestamp", "_record", "_from_structlog",
    "exc_info", "stack_info",
})

# Map logger module path segments → short component labels shown in the UI
_COMPONENT_MAP = {
    "devices": "device",
    "indi":    "indi",
    "mount":   "mount",
    "imaging": "imager",
    "focuser": "focuser",
    "profiles": "profiles",
    "api":        "api",
    "phd2":       "phd2",
    "platesolve": "platesolve",
}


def _logger_to_component(logger_name: str) -> str:
    parts = (logger_name or "").split(".")
    # "indi" is a sub-package of "devices" — check it before the generic loop
    # so "astrolol.devices.indi.client" → "indi", not "device".
    if "indi" in parts:
        return "indi"
    for part in parts:
        if part in _COMPONENT_MAP:
            return _COMPONENT_MAP[part]
    return parts[-1] or "app"


class EventBusForwarder:
    """Structlog processor that also publishes log entries to the EventBus."""

    def __init__(self) -> None:
        self._bus: Any = None  # EventBus, set after creation

    def set_bus(self, bus: Any) -> None:
        self._bus = bus

    def __call__(self, logger_inst: Any, method: str, event_dict: dict) -> dict:
        if (
            self._bus is not None
            and method in ("info", "warning", "error", "critical")
            and event_dict.get("logger") not in _SKIP_LOGGERS
        ):
            try:
                from astrolol.core.events.models import LogEvent
                level = event_dict.get("level", method)
                component = _logger_to_component(str(event_dict.get("logger", "")))
                event_name = str(event_dict.get("event", ""))
                # Append extra context fields (driver=, device=, error=, …) so the
                # UI log panel shows the full structured entry, not just the name.
                extras = {
                    k: v for k, v in event_dict.items()
                    if k not in _STRUCTLOG_META_KEYS and not k.startswith("_")
                }
                if extras:
                    extra_str = " ".join(f"{k}={v}" for k, v in extras.items())
                    message = f"{event_name} {extra_str}"
                else:
                    message = event_name
                evt = LogEvent(level=level, component=component, message=message)
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._bus.publish(evt))
                except RuntimeError:
                    pass  # no running loop (startup/shutdown) — skip
            except Exception:
                pass  # never let log forwarding crash the app
        return event_dict


# Singleton — set_bus() called from main.py after EventBus is created
event_bus_forwarder = EventBusForwarder()
