"""Logging setup shared by the app and the scripts.

Libraries that log request URLs (httpx, httpcore, huggingface_hub) are kept at WARNING so provider
and CDN URLs never reach the logs. Our own loggers stay at INFO.
"""

from __future__ import annotations

import logging

QUIET_LOGGERS = ("httpx", "httpcore", "huggingface_hub")


def configure_logging(fmt: str = "%(asctime)s %(levelname)s %(name)s %(message)s") -> None:
    logging.basicConfig(level=logging.INFO, format=fmt)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
