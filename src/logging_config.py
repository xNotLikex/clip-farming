import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.config import DATA_DIR

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_CONFIGURED = False


def setup_logging(
    level: str | int = "INFO",
    log_dir: Path | None = None,
) -> logging.Logger:
    """Konfiguriert zentrales Logging mit RotatingFileHandler in data/logs/ und Konsole."""
    global _CONFIGURED
    root_logger = logging.getLogger()

    resolved_level = (
        getattr(logging, level.upper(), logging.INFO) if isinstance(level, str) else level
    )
    root_logger.setLevel(resolved_level)

    if _CONFIGURED and log_dir is None:
        return root_logger

    target_dir = log_dir or (DATA_DIR / "logs")
    target_dir.mkdir(parents=True, exist_ok=True)
    log_file = target_dir / "clip_farming.log"

    formatter = logging.Formatter(_LOG_FORMAT)

    # Bestehende Clip-Farming-Handler nicht doppelt anhängen
    existing_files = {
        getattr(h, "baseFilename", None)
        for h in root_logger.handlers
        if isinstance(h, RotatingFileHandler)
    }
    if str(log_file.resolve()) not in existing_files:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    if log_dir is None:
        _CONFIGURED = True
    return root_logger
