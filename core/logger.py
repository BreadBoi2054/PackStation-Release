"""Centralized file logging for PackStation.

Writes logs to both console AND rotating log files so factory issues can be debugged
even after the app is closed. Log files are kept for 7 days.
"""
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

_logger = None


def get_logger(log_dir: str = None) -> logging.Logger:
    """Get or create the singleton PackStation logger."""
    global _logger
    if _logger is not None:
        return _logger

    _logger = logging.getLogger("PackStation")
    _logger.setLevel(logging.DEBUG)

    # Determine log directory
    if not log_dir:
        if getattr(sys, 'frozen', False):
            log_dir = os.path.join(os.path.dirname(sys.executable), "logs")
        else:
            log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)

    # File handler — rotating 2MB × 5 files = max 10MB log storage
    log_file = os.path.join(log_dir, "packstation.log")
    file_handler = RotatingFileHandler(
        log_file, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_fmt)

    # Console handler — same format but INFO level only
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(file_fmt)

    _logger.addHandler(file_handler)
    _logger.addHandler(console_handler)

    _logger.info("=" * 50)
    _logger.info("PackStation started — v1.5.3")
    _logger.info(f"Log file: {log_file}")
    _logger.info("=" * 50)

    return _logger


def cleanup_old_logs(log_dir: str, max_days: int = 7):
    """Delete log files older than max_days."""
    try:
        cutoff = datetime.now().timestamp() - (max_days * 86400)
        for f in os.listdir(log_dir):
            if not f.endswith(".log"):
                continue
            fp = os.path.join(log_dir, f)
            if os.path.getmtime(fp) < cutoff:
                os.remove(fp)
    except Exception:
        pass
