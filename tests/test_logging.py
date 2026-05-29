# Add to tests/test_logging.py
import logging
from unittest.mock import patch, MagicMock
from app.core.logging import JSONFormatter, PlainFormatter, configure_logging, get_logger


def test_json_formatter_basic():
    formatter = JSONFormatter()
    record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
    output = formatter.format(record)
    import json
    parsed = json.loads(output)
    assert parsed["message"] == "hello"
    assert parsed["level"] == "INFO"


def test_json_formatter_with_exception():
    formatter = JSONFormatter()
    try:
        raise ValueError("test error")
    except ValueError:
        import sys
        record = logging.LogRecord("test", logging.ERROR, "", 0, "err", (), sys.exc_info())
        output = formatter.format(record)
        assert "exception" in output


def test_plain_formatter():
    formatter = PlainFormatter()
    record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
    output = formatter.format(record)
    assert "hello" in output


def test_configure_logging_plain():
    with patch("app.core.logging.get_settings") as mock_settings:
        mock_settings.return_value.log_level = "DEBUG"
        mock_settings.return_value.log_json = False
        configure_logging()
        assert logging.getLogger().level == logging.DEBUG


def test_configure_logging_json():
    with patch("app.core.logging.get_settings") as mock_settings:
        mock_settings.return_value.log_level = "INFO"
        mock_settings.return_value.log_json = True
        configure_logging()


def test_get_logger_returns_logger():
    logger = get_logger("test.module")
    assert logger.name == "test.module"