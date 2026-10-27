import os
import io
import json
import zipfile
import logging
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest

# 1. Isolate the database path BEFORE importing web.server
import xarrtools.core.db; from xarrtools import core
fd, temp_db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
core.db.DB_PATH = Path(temp_db_path)
core.db.init_db()

import xarrtools.core.logging_setup; from xarrtools import core
from xarrtools.core.logging_setup import (
    setup_logging,
    reset_logging,
    get_logger,
    get_log_dir,
    redact_sensitive_data,
    RedactingFilter,
    RedactingFormatter,
    parse_log_level,
)
from xarrtools.core.config import config

with patch("threading.Thread"):
    from xarrtools.web.server import app


@pytest.fixture(autouse=True)
def cleanup_test_env(tmp_path, monkeypatch):
    """Isolates logs directory and resets database settings between tests."""
    test_logs_dir = tmp_path / "logs"
    test_logs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(core.logging_setup, "LOG_DIR", test_logs_dir)
    monkeypatch.setenv("XARRTOOLS_LOG_DIR", str(test_logs_dir))

    # Reset logging handlers
    reset_logging()

    # Reset settings table
    conn = core.db.get_db_connection()
    conn.execute("DELETE FROM settings")
    conn.commit()
    conn.close()

    core.db.init_db()
    core.db.set_setting("api_key", "test_api_key")
    config.refresh()

    yield test_logs_dir

    reset_logging()
    core.logging_setup.LOG_DIR = None


@pytest.fixture
def client():
    app.config["TESTING"] = True

    class TestClientAPIKeyWrapper:
        def __init__(self, inner):
            self.inner = inner

        def _get_api_key(self):
            key = core.db.get_setting("api_key", "")
            if not key:
                key = "test_api_key"
                core.db.set_setting("api_key", key)
                config.refresh()
            return key

        def get(self, *args, **kwargs):
            return self.inner.get(*args, **kwargs)

        def post(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-API-Key"] = self._get_api_key()
            kwargs["headers"] = headers
            return self.inner.post(*args, **kwargs)

        def put(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-API-Key"] = self._get_api_key()
            kwargs["headers"] = headers
            return self.inner.put(*args, **kwargs)

        def delete(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-API-Key"] = self._get_api_key()
            kwargs["headers"] = headers
            return self.inner.delete(*args, **kwargs)

    with app.test_client() as c:
        yield TestClientAPIKeyWrapper(c)


def test_setup_logging_idempotent(cleanup_test_env):
    """Calling setup_logging repeatedly should not duplicate handlers."""
    test_logs_dir = cleanup_test_env
    logger1 = setup_logging(level="INFO", log_dir=test_logs_dir)
    assert len(logger1.handlers) == 2  # StreamHandler + RotatingFileHandler

    # Second call should update in-place without adding new handlers
    logger2 = setup_logging(level="DEBUG", log_dir=test_logs_dir)
    assert logger2 is logger1
    assert len(logger2.handlers) == 2
    assert logger2.level == logging.DEBUG
    for h in logger2.handlers:
        assert h.level == logging.DEBUG

    # force=True should reset and cleanly recreate 2 handlers
    logger3 = setup_logging(level="WARNING", log_dir=test_logs_dir, force=True)
    assert len(logger3.handlers) == 2
    assert logger3.level == logging.WARNING


def test_log_rotation_max_two_files(cleanup_test_env):
    """Log rotation must cap at a maximum of 2 files: xarrtools.log and xarrtools.log.1."""
    test_logs_dir = cleanup_test_env
    # Use small max_bytes (120 bytes) to force rapid rotation
    setup_logging(level="INFO", log_dir=test_logs_dir, max_bytes=120, force=True)
    logger = get_logger("rotator")

    # Write enough messages to trigger multiple rotations
    for i in range(50):
        logger.info(f"Rotation test entry line number {i:04d} filling bytes")

    # Flush all handlers
    for h in logging.getLogger("xarrtools").handlers:
        h.flush()

    log_files = sorted([f.name for f in test_logs_dir.glob("xarrtools.log*")])
    assert "xarrtools.log" in log_files
    assert "xarrtools.log.1" in log_files
    # Ensure there is no xarrtools.log.2 or higher
    assert "xarrtools.log.2" not in log_files
    assert len(log_files) == 2


def test_log_level_live_change(cleanup_test_env):
    """Changing log level via setup_logging updates root logger and all handlers live."""
    test_logs_dir = cleanup_test_env
    setup_logging(level="INFO", log_dir=test_logs_dir, force=True)
    root = logging.getLogger("xarrtools")
    assert root.level == logging.INFO
    for h in root.handlers:
        assert h.level == logging.INFO

    # Change to DEBUG
    setup_logging(level="DEBUG")
    assert root.level == logging.DEBUG
    for h in root.handlers:
        assert h.level == logging.DEBUG

    # Change to ERROR
    setup_logging(level="ERROR")
    assert root.level == logging.ERROR
    for h in root.handlers:
        assert h.level == logging.ERROR


def test_redaction_filter_patterns(cleanup_test_env):
    """Redaction filter must strip query credentials, header keys, and Bearer tokens."""
    test_logs_dir = cleanup_test_env
    setup_logging(level="DEBUG", log_dir=test_logs_dir, force=True)
    logger = get_logger("redact_test")

    logger.info("Calling https://api.themoviedb.org/3/discover/movie?api_key=tmdb_secret_key_12345&language=en")
    logger.info("Header test: X-Api-Key: arr_secret_header_key_abcde")
    logger.info("Auth test: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0")
    logger.info("Sonarr query: https://sonarr.local/api/v3/series?apikey=sonarr_secret_key_99999")

    for h in logging.getLogger("xarrtools").handlers:
        h.flush()

    log_content = (test_logs_dir / "xarrtools.log").read_text(encoding="utf-8")

    assert "tmdb_secret_key_12345" not in log_content
    assert "arr_secret_header_key_abcde" not in log_content
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in log_content
    assert "sonarr_secret_key_99999" not in log_content
    assert "***REDACTED***" in log_content


def test_redaction_filter_args(cleanup_test_env):
    """Redaction filter must strip secrets when passed as format args (dict and tuple)."""
    test_logs_dir = cleanup_test_env
    setup_logging(level="DEBUG", log_dir=test_logs_dir, force=True)
    logger = get_logger("args_test")

    logger.info("Request details: %s", "https://api.test/v1?token=arg_secret_token_123")
    logger.info("Request params: %s", {"api_key": "arg_dict_secret_456", "safe": "normal_val"})

    for h in logging.getLogger("xarrtools").handlers:
        h.flush()

    log_content = (test_logs_dir / "xarrtools.log").read_text(encoding="utf-8")
    assert "arg_secret_token_123" not in log_content
    assert "arg_dict_secret_456" not in log_content
    assert "normal_val" in log_content
    assert "***REDACTED***" in log_content


def test_redaction_configured_secrets(cleanup_test_env):
    """Redaction must strip raw configured API keys even if not matched by standard patterns."""
    test_logs_dir = cleanup_test_env
    core.db.set_setting("radarr_api_key", "custom_radarr_key_xyz123")
    core.db.set_setting("tmdb_api_key", "custom_tmdb_key_abc789")
    config.refresh()

    setup_logging(level="DEBUG", log_dir=test_logs_dir, force=True)
    logger = get_logger("secrets_test")

    logger.info("Custom keys payload: custom_radarr_key_xyz123 and custom_tmdb_key_abc789 here")

    for h in logging.getLogger("xarrtools").handlers:
        h.flush()

    log_content = (test_logs_dir / "xarrtools.log").read_text(encoding="utf-8")
    assert "custom_radarr_key_xyz123" not in log_content
    assert "custom_tmdb_key_abc789" not in log_content
    assert "***REDACTED***" in log_content


def test_redaction_traceback(cleanup_test_env):
    """Exceptions containing secrets in URLs or messages must have secrets redacted."""
    test_logs_dir = cleanup_test_env
    setup_logging(level="DEBUG", log_dir=test_logs_dir, force=True)
    logger = get_logger("exc_test")

    try:
        raise ValueError("Failed connecting to https://arr.local/api?apikey=leaked_secret_val_in_exc")
    except Exception:
        logger.error("An error occurred during sync", exc_info=True)

    for h in logging.getLogger("xarrtools").handlers:
        h.flush()

    log_content = (test_logs_dir / "xarrtools.log").read_text(encoding="utf-8")
    assert "leaked_secret_val_in_exc" not in log_content
    assert "***REDACTED***" in log_content


def test_api_settings_log_level_validation(client):
    """POST /api/settings should validate log_level and apply valid levels live."""
    # Invalid log_level returns 400
    res_bad = client.post("/api/settings", json={"log_level": "INVALID_LEVEL"})
    assert res_bad.status_code == 400
    data_bad = res_bad.get_json()
    assert data_bad["status"] == "error"
    assert "Invalid value for log_level" in data_bad["message"]

    # Valid log_level returns 200 and updates DB & config & logger
    res_good = client.post("/api/settings", json={"log_level": "DEBUG"})
    assert res_good.status_code == 200
    data_good = res_good.get_json()
    assert data_good["status"] == "success"
    assert core.db.get_setting("log_level") == "DEBUG"
    assert config.log_level == "DEBUG"
    assert logging.getLogger("xarrtools").level == logging.DEBUG

    # Test another valid level
    res_warn = client.post("/api/settings", json={"log_level": "WARNING"})
    assert res_warn.status_code == 200
    assert config.log_level == "WARNING"
    assert logging.getLogger("xarrtools").level == logging.WARNING


def test_api_logs_download_with_files(client, cleanup_test_env):
    """GET /api/logs/download returns in-memory ZIP containing xarrtools.log and xarrtools.log.1."""
    test_logs_dir = cleanup_test_env
    (test_logs_dir / "xarrtools.log").write_text("2026-10-26 [INFO] main: system started", encoding="utf-8")
    (test_logs_dir / "xarrtools.log.1").write_text("2026-10-25 [INFO] main: previous session", encoding="utf-8")

    res = client.get("/api/logs/download")
    assert res.status_code == 200
    assert res.headers["Content-Type"] == "application/zip"
    assert "attachment; filename=xarrtools_logs.zip" in res.headers["Content-Disposition"]

    # Verify zip content
    with zipfile.ZipFile(io.BytesIO(res.data)) as zf:
        namelist = zf.namelist()
        assert "xarrtools.log" in namelist
        assert "xarrtools.log.1" in namelist
        assert zf.read("xarrtools.log").decode("utf-8") == "2026-10-26 [INFO] main: system started"
        assert zf.read("xarrtools.log.1").decode("utf-8") == "2026-10-25 [INFO] main: previous session"


def test_api_logs_download_empty_graceful(client, cleanup_test_env):
    """GET /api/logs/download returns a zip with README.txt if no log files are present."""
    test_logs_dir = cleanup_test_env
    # Ensure directory is empty
    for f in test_logs_dir.glob("*"):
        f.unlink()

    res = client.get("/api/logs/download")
    assert res.status_code == 200
    assert res.headers["Content-Type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(res.data)) as zf:
        namelist = zf.namelist()
        assert "README.txt" in namelist
        readme_text = zf.read("README.txt").decode("utf-8")
        assert "No log files currently exist or logs are empty." in readme_text


def test_get_logger_naming():
    """get_logger returns the proper hierarchical xarrtools logger."""
    assert get_logger().name == "xarrtools"
    assert get_logger("xarrtools").name == "xarrtools"
    assert get_logger("xarrtools.db").name == "xarrtools.db"
    assert get_logger("scraper").name == "xarrtools.scraper"
    assert get_logger("core.enricher").name == "xarrtools.enricher"


def test_parse_log_level():
    """parse_log_level handles strings, ints, None, and unknown names gracefully."""
    assert parse_log_level("DEBUG") == logging.DEBUG
    assert parse_log_level("info") == logging.INFO
    assert parse_log_level("WARNING") == logging.WARNING
    assert parse_log_level("ERROR") == logging.ERROR
    assert parse_log_level(logging.DEBUG) == logging.DEBUG
    assert parse_log_level("NOT_A_LEVEL") == logging.INFO
