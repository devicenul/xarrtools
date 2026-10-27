"""Central logging setup and redaction architecture for xarrtools.

Provides:
- setup_logging: Idempotent initialization of console and rotating file handlers
  attached to the 'xarrtools' hierarchy root.
- RedactingFilter & RedactingFormatter: Strips API keys, bearer tokens, query parameters,
  and configured credentials before records hit stdout or disk.
- Log rotation capped at a maximum of 2 files (xarrtools.log and xarrtools.log.1).
- Dynamic log level changes applied live without restart.
"""
import os
import re
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import List, Optional, Pattern, Set, Tuple, Union

# Module-level log directory override (used by tests or custom setups)
LOG_DIR: Optional[Path] = None

DEFAULT_LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DEFAULT_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
ALLOWED_LOG_LEVELS: Tuple[str, ...] = ("DEBUG", "INFO", "WARNING", "ERROR")

# Credential masking patterns
REDACTION_PATTERNS: List[Pattern[str]] = [
    # Query parameters & header keys: apikey=..., api_key=..., access_token=..., token=..., secret=...
    re.compile(r"(?i)([?&](?:api[_-]?key|apikey|access_token|token|secret|password)=)([^&\s'\"`]+)"),
    # Header format: X-Api-Key: ... or X-Api-Key=...
    re.compile(r"(?i)(X-Api-Key\s*[:=]\s*)([^\s'\"`]+)"),
    # General api_key / apikey key-value pairs (e.g. in JSON, dicts, or logs)
    re.compile(r"(?i)(['\"]?(?:api[_-]?key|apikey|token|access_token)['\"]?\s*[:=]\s*['\"]?)([^&\s'\"`,}]+)"),
    # Bearer authorization tokens
    re.compile(r"(?i)(Bearer\s+)([A-Za-z0-9_\-\.]+)"),
    # Standard Authorization headers
    re.compile(r"(?i)(Authorization\s*:\s*)([^\s\r\n]+)")
]


def get_log_dir() -> Path:
    """Returns the resolved log directory, ensuring it exists."""
    global LOG_DIR
    if LOG_DIR is not None:
        target = Path(LOG_DIR)
    elif os.environ.get("XARRTOOLS_LOG_DIR"):
        target = Path(os.environ["XARRTOOLS_LOG_DIR"])
    else:
        from xarrtools.core.db import DB_PATH
        target = DB_PATH.resolve().parent / "logs"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _get_configured_secrets() -> Set[str]:
    """Retrieves all non-empty configured secret keys that should be masked."""
    secrets: Set[str] = set()
    try:
        from xarrtools.core.config import config
        for key in (
            getattr(config, "radarr_api_key", None),
            getattr(config, "sonarr_api_key", None),
            getattr(config, "tmdb_api_key", None),
        ):
            if key and len(str(key).strip()) >= 4:
                secrets.add(str(key).strip())
        srv_key = config._get_setting("api_key")
        if srv_key and len(str(srv_key).strip()) >= 4:
            secrets.add(str(srv_key).strip())
        auth_pw = os.environ.get("XARRTOOLS_AUTH_PASSWORD")
        if auth_pw and len(str(auth_pw).strip()) >= 4:
            secrets.add(str(auth_pw).strip())
    except Exception:
        pass
    return secrets


def redact_sensitive_data(text: str) -> str:
    """Masks credentials, API keys, tokens, and query parameters in a text string."""
    if not text or not isinstance(text, str):
        return text

    redacted = text

    # 1. Mask pattern-based credentials (query params, headers, bearer tokens)
    for pattern in REDACTION_PATTERNS:
        redacted = pattern.sub(r"\g<1>***REDACTED***", redacted)

    # 2. Mask explicit configured secret values
    for secret in _get_configured_secrets():
        if secret in redacted:
            redacted = redacted.replace(secret, "***REDACTED***")

    return redacted


class RedactingFilter(logging.Filter):
    """Logging filter that redacts sensitive credentials from LogRecord messages and args."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_sensitive_data(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: (redact_sensitive_data(v) if isinstance(v, str) else v)
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(
                    redact_sensitive_data(a) if isinstance(a, str) else a
                    for a in record.args
                )

        if record.exc_text and isinstance(record.exc_text, str):
            record.exc_text = redact_sensitive_data(record.exc_text)

        return True


class RedactingFormatter(logging.Formatter):
    """Logging formatter that ensures full message and traceback redaction."""

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        return redact_sensitive_data(formatted)


def parse_log_level(level: Optional[Union[str, int]]) -> int:
    """Converts a string or int log level to a valid logging numeric level."""
    if level is None:
        try:
            from xarrtools.core.config import config
            lvl_name = config.log_level
        except Exception:
            lvl_name = "INFO"
    elif isinstance(level, int):
        return level
    else:
        lvl_name = str(level).strip().upper()

    if lvl_name not in ALLOWED_LOG_LEVELS:
        lvl_name = "INFO"
    return getattr(logging, lvl_name, logging.INFO)


def reset_logging() -> None:
    """Removes and closes all handlers attached to the 'xarrtools' root logger."""
    root_logger = logging.getLogger("xarrtools")
    for handler in list(root_logger.handlers):
        handler.close()
        root_logger.removeHandler(handler)


def setup_logging(
    level: Optional[Union[str, int]] = None,
    log_dir: Optional[Union[str, Path]] = None,
    max_bytes: int = 1024 * 1024,
    force: bool = False
) -> logging.Logger:
    """Initializes structured logging for xarrtools.

    - Attaches console and rotating file handlers to the 'xarrtools' hierarchy root.
    - Ensures max 2 log files (xarrtools.log, xarrtools.log.1).
    - Idempotent: Subsequent calls update logger/handler levels live without adding duplicates.
    - Sets propagate = False on 'xarrtools' logger so output does not double in root.
    """
    global LOG_DIR
    if log_dir is not None:
        LOG_DIR = Path(log_dir)

    target_level = parse_log_level(level)
    root_logger = logging.getLogger("xarrtools")
    root_logger.propagate = False
    root_logger.setLevel(target_level)

    # If handlers already exist and force is False, update levels and return
    if root_logger.handlers and not force:
        for handler in root_logger.handlers:
            handler.setLevel(target_level)
        return root_logger

    if force:
        reset_logging()

    # Formatter & Filter instances
    formatter = RedactingFormatter(DEFAULT_LOG_FORMAT, datefmt=DEFAULT_DATE_FORMAT)
    redaction_filter = RedactingFilter()

    # 1. Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(target_level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(redaction_filter)
    root_logger.addHandler(console_handler)

    # 2. Rotating File Handler (max 2 files: xarrtools.log + xarrtools.log.1)
    resolved_dir = get_log_dir()
    log_file_path = resolved_dir / "xarrtools.log"
    file_handler = RotatingFileHandler(
        filename=str(log_file_path),
        maxBytes=max_bytes,
        backupCount=1,
        encoding="utf-8"
    )
    file_handler.setLevel(target_level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(redaction_filter)
    root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Returns a logger inside the 'xarrtools' hierarchy."""
    if not name or name == "xarrtools":
        return logging.getLogger("xarrtools")
    if name.startswith("xarrtools."):
        return logging.getLogger(name)
    clean_name = name.split(".")[-1]
    return logging.getLogger(f"xarrtools.{clean_name}")
