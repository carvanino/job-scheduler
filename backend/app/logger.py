"""
Structured logging using structlog.
Every log entry is a JSON object with:
  - timestamp
  - level
  - event
  - job_id (when applicable)
  - worker_id (when applicable)
  - any extra kwargs passed at the call site

Usage:
    from app.logger import get_logger
    log = get_logger(__name__)
    log.info("job.created", job_id=str(job.id), priority=job.priority)
"""

import logging
import sys

import structlog


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )


def get_logger(name: str = __name__) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
