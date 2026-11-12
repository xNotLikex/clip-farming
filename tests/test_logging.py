import logging
from logging.handlers import RotatingFileHandler

from src.logging_config import setup_logging


def test_setup_logging_creates_rotating_log_and_is_idempotent(tmp_path):
    log_dir = tmp_path / "logs"
    logger = setup_logging(level="INFO", log_dir=log_dir)

    test_logger = logging.getLogger("clip_farming_test")
    test_logger.info("Test-Logzeile")

    for h in logger.handlers:
        h.flush()

    log_file = log_dir / "clip_farming.log"
    assert log_file.exists()
    assert "Test-Logzeile" in log_file.read_text(encoding="utf-8")

    # Zweiter Aufruf mit demselben log_dir darf keinen doppelten RotatingFileHandler anlegen
    setup_logging(level="INFO", log_dir=log_dir)
    matching = [
        h
        for h in logger.handlers
        if isinstance(h, RotatingFileHandler) and h.baseFilename == str(log_file.resolve())
    ]
    assert len(matching) == 1
