"""Logging configuration for the COPOM pipeline."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path


def setup_logging(log_dir: str = "./logs", level: str = "INFO") -> None:
    """Configure root logger with console + rotating file handlers.

    Args:
        log_dir: Directory for log files.
        level:   Logging level string (DEBUG, INFO, WARNING, ERROR).
    """
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"pipeline_{timestamp}.log")

    fmt = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
