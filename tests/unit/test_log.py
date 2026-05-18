import logging
from pathlib import Path
import pytest

from avadex import log as log_module


@pytest.fixture(autouse=True)
def _reset_logging():
    """Clear AvaDex's root logger between tests so handlers don't accumulate."""
    root = logging.getLogger("avadex")
    for h in list(root.handlers):
        root.removeHandler(h)
    log_module._CONFIGURED = False
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
    log_module._CONFIGURED = False


def test_setup_non_debug_adds_only_stderr_handler():
    log_module.setup(debug=False)
    root = logging.getLogger("avadex")
    assert len(root.handlers) == 1
    assert root.level == logging.WARNING


def test_setup_debug_adds_file_and_stderr_handlers(tmp_path):
    log_path = tmp_path / "debug.log"
    log_module.setup(debug=True, log_file=log_path)
    root = logging.getLogger("avadex")
    assert len(root.handlers) == 2
    assert root.level == logging.DEBUG


def test_debug_writes_to_log_file(tmp_path):
    log_path = tmp_path / "debug.log"
    log_module.setup(debug=True, log_file=log_path)
    logger = log_module.get_logger("test_mod")
    logger.debug("hello debug")
    # Flush handlers
    for h in logging.getLogger("avadex").handlers:
        h.flush()
    contents = log_path.read_text()
    assert "hello debug" in contents
    assert "avadex.test_mod" in contents


def test_non_debug_skips_debug_messages_to_stderr(tmp_path, capsys):
    log_module.setup(debug=False)
    logger = log_module.get_logger("test_mod")
    logger.debug("should not appear")
    logger.warning("should appear")
    err = capsys.readouterr().err
    assert "should not appear" not in err
    assert "should appear" in err
    assert "[warn]" in err


def test_get_logger_auto_configures():
    """If setup() never ran, get_logger should configure with debug=False."""
    assert not log_module._CONFIGURED
    logger = log_module.get_logger("auto")
    assert log_module._CONFIGURED
    assert logger.name == "avadex.auto"


def test_error_level_uses_error_prefix(capsys):
    log_module.setup(debug=False)
    logger = log_module.get_logger("test_mod")
    logger.error("boom")
    err = capsys.readouterr().err
    assert "[error]" in err
    assert "boom" in err


def test_rotation_config(tmp_path):
    """Debug file handler is a RotatingFileHandler with the expected size cap."""
    import logging.handlers
    log_path = tmp_path / "debug.log"
    log_module.setup(debug=True, log_file=log_path)
    file_handlers = [
        h for h in logging.getLogger("avadex").handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    fh = file_handlers[0]
    assert fh.maxBytes == 1_000_000
    assert fh.backupCount == 5
