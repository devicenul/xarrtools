"""Authentication, session management, credential hashing, and security helpers.

Provides:
- salted hashlib.scrypt password hashing and verification.
- Signed HMAC session tokens with server-side revocation on logout/password change.
- Client-address login throttling to prevent brute-force attacks.
- Open redirect sanitization for post-login redirects.
- Network exposure and first-run setup mode state calculation.
- Auth credential reset and recovery functions.
"""
import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import threading
import time
from typing import Dict, List, Optional, Tuple

from xarrtools.core.config import config
from xarrtools.core.db import (
    AUTH_SETTINGS_KEYS,
    get_db_connection,
    get_setting,
    set_setting,
)

logger = logging.getLogger("xarrtools.auth")

SESSION_COOKIE_NAME: str = "xarrtools_session"
MIN_PASSWORD_LENGTH: int = 8
SCRYPT_N: int = 16384  # 2**14
SCRYPT_R: int = 8
SCRYPT_P: int = 1
SCRYPT_KEY_LEN: int = 64
SCRYPT_MAXMEM: int = 32 * 1024 * 1024


def hash_password(password: str) -> str:
    """Generates a salted scrypt hash of the given plaintext password."""
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        maxmem=SCRYPT_MAXMEM,
        dklen=SCRYPT_KEY_LEN,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${key.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verifies a plaintext password against a stored scrypt hash string using constant-time comparison."""
    if not password or not stored_hash:
        return False
    parts = stored_hash.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False
    try:
        n = int(parts[1])
        r = int(parts[2])
        p = int(parts[3])
        salt = bytes.fromhex(parts[4])
        expected_key = bytes.fromhex(parts[5])
        computed_key = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            maxmem=SCRYPT_MAXMEM,
            dklen=len(expected_key),
        )
        return hmac.compare_digest(computed_key, expected_key)
    except Exception as e:
        logger.debug(f"Password verification error: {e}")
        return False


def validate_password_strength(password: str) -> Tuple[bool, str]:
    """Validates that a password satisfies minimum complexity requirements (min 8 characters)."""
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
    return True, ""


def get_session_secret() -> str:
    """Retrieves or lazily initializes the HMAC session signing secret key."""
    secret = get_setting("auth_session_secret", "")
    if not secret:
        secret = secrets.token_hex(32)
        set_setting("auth_session_secret", secret)
        config.refresh()
    return secret


def get_session_version() -> str:
    """Retrieves current session version used to revoke older issued sessions."""
    version = get_setting("auth_session_version", "")
    if not version:
        version = secrets.token_hex(16)
        set_setting("auth_session_version", version)
        config.refresh()
    return version


def rotate_session_version() -> str:
    """Rotates the session version, instantly invalidating all existing session cookies."""
    new_version = secrets.token_hex(16)
    set_setting("auth_session_version", new_version)
    config.refresh()
    return new_version


def create_session_token(username: str, ttl_days: int = 30) -> str:
    """Issues a signed, tamper-evident session token containing username, version, and expiry."""
    secret = get_session_secret()
    version = get_session_version()
    expiry = int(time.time()) + (ttl_days * 86400)
    payload_dict = {
        "u": username,
        "v": version,
        "exp": expiry,
    }
    payload_json = json.dumps(payload_dict, separators=(",", ":")).encode("utf-8")
    b64_payload = base64.urlsafe_b64encode(payload_json).decode("ascii").rstrip("=")
    sig = hmac.new(secret.encode("utf-8"), b64_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{b64_payload}.{sig}"


def verify_session_token(token: Optional[str]) -> Optional[str]:
    """Verifies a signed session token. Returns username if valid, otherwise None."""
    if not token or "." not in token:
        return None
    parts = token.split(".", 1)
    if len(parts) != 2:
        return None
    b64_payload, signature = parts
    secret = get_session_secret()
    expected_sig = hmac.new(secret.encode("utf-8"), b64_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_sig, signature):
        return None

    # Restore base64 padding
    padding = len(b64_payload) % 4
    padded_b64 = b64_payload + ("=" * (4 - padding) if padding else "")
    try:
        raw_json = base64.urlsafe_b64decode(padded_b64.encode("ascii")).decode("utf-8")
        data = json.loads(raw_json)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    # Validate expiration
    exp = data.get("exp")
    if not isinstance(exp, (int, float)) or exp < time.time():
        return None

    # Validate version against current server session version
    current_version = get_session_version()
    if not hmac.compare_digest(str(data.get("v", "")), current_version):
        return None

    # Validate username against stored active user
    username = data.get("u")
    stored_username = get_setting("auth_username", "")
    if not username or not stored_username or not hmac.compare_digest(str(username), stored_username):
        return None

    # Ensure auth is still configured and not disabled
    if not is_auth_configured():
        return None

    return str(username)


class LoginThrottle:
    """Thread-safe in-memory failed login attempt rate limiter per client IP address."""

    def __init__(self, max_failures: int = 5, window_seconds: int = 900, lockout_seconds: int = 60) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self._failures: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def record_failure(self, ip: str) -> None:
        """Records a failed login attempt for the given IP address."""
        now = time.time()
        with self._lock:
            history = self._failures.setdefault(ip, [])
            cutoff = now - self.window_seconds
            history = [t for t in history if t > cutoff]
            history.append(now)
            self._failures[ip] = history

    def is_throttled(self, ip: str) -> Tuple[bool, int]:
        """Checks if client IP is currently throttled. Returns (is_throttled, wait_seconds)."""
        now = time.time()
        with self._lock:
            history = self._failures.get(ip, [])
            cutoff = now - self.window_seconds
            valid_history = [t for t in history if t > cutoff]
            self._failures[ip] = valid_history
            if len(valid_history) >= self.max_failures:
                last_failure = valid_history[-1]
                elapsed = now - last_failure
                if elapsed < self.lockout_seconds:
                    wait_seconds = max(1, int(self.lockout_seconds - elapsed))
                    return True, wait_seconds
            return False, 0

    def clear_failures(self, ip: str) -> None:
        """Clears failed login attempt history for client IP upon successful authentication."""
        with self._lock:
            self._failures.pop(ip, None)

    def reset(self) -> None:
        """Wipes all throttle records (primarily for test execution)."""
        with self._lock:
            self._failures.clear()


login_throttle = LoginThrottle()


def sanitize_next_url(next_url: Optional[str]) -> str:
    """Sanitizes redirection target to ensure it is a safe local relative path without open redirects."""
    if not next_url:
        return "/"
    target = str(next_url).strip()
    # Must start with single slash and not scheme-relative or protocol-relative
    if not target.startswith("/") or target.startswith("//") or target.startswith("/\\"):
        return "/"
    # Must not contain backslashes, control characters, or protocol schemes
    if "\\" in target or "\t" in target or "\r" in target or "\n" in target:
        return "/"
    if "://" in target:
        return "/"
    return target


def is_network_exposed(host: Optional[str]) -> bool:
    """Returns True if the server bind host is reachable from other machines on the network."""
    if host is None or host == "":
        return True
    h = host.strip().lower()
    if h in ("0.0.0.0", "::", "*"):
        return True
    if h in ("127.0.0.1", "localhost", "::1"):
        return False
    try:
        ip = ipaddress.ip_address(h)
        return not ip.is_loopback
    except ValueError:
        # Non-loopback hostname
        return True


def is_env_auth_enabled() -> bool:
    """Returns True if authentication is configured via environment variables (HTTP Basic auth)."""
    user = os.environ.get("XARRTOOLS_AUTH_USER", "").strip()
    pw = os.environ.get("XARRTOOLS_AUTH_PASSWORD", "").strip()
    return bool(user and pw)


def is_auth_disabled() -> bool:
    """Returns True if authentication was explicitly disabled via env var or user setting."""
    env_disabled = os.environ.get("XARRTOOLS_AUTH_DISABLED", "").strip().lower()
    if env_disabled in ("1", "true", "yes", "on"):
        return True
    db_disabled = get_setting("auth_disabled", "").strip().lower()
    return db_disabled in ("1", "true", "yes", "on")


def is_auth_configured() -> bool:
    """Returns True if username and scrypt password hash are stored and auth is not disabled."""
    if is_auth_disabled():
        return False
    user = get_setting("auth_username", "").strip()
    pw_hash = get_setting("auth_password_hash", "").strip()
    return bool(user and pw_hash)


def is_existing_install_exempt() -> bool:
    """Returns True if the database was migrated from an existing unauthenticated installation."""
    if is_auth_configured():
        return False
    val = get_setting("auth_is_existing_install", "").strip()
    return val == "1"


def needs_setup(bind_host: Optional[str]) -> bool:
    """Determines whether the server must enter first-run setup mode."""
    if not is_network_exposed(bind_host):
        return False
    if is_env_auth_enabled():
        return False
    if is_auth_disabled():
        return False
    if is_auth_configured():
        return False
    if is_existing_install_exempt():
        return False
    return True


def should_show_unauthenticated_banner(bind_host: Optional[str]) -> bool:
    """Returns True if the server is network-exposed without authentication, requiring a warning banner."""
    if not is_network_exposed(bind_host):
        return False
    if is_env_auth_enabled():
        return False
    if is_auth_configured():
        return False
    # If explicitly disabled or existing install exempt, show the banner
    return is_auth_disabled() or is_existing_install_exempt()


def get_auth_mode() -> str:
    """Returns current auth mode string: 'env', 'form', or 'none'."""
    if is_env_auth_enabled():
        return "env"
    if is_auth_configured():
        return "form"
    return "none"


def set_user_credentials(username: str, password: str) -> Tuple[bool, str]:
    """Stores user credentials, creates scrypt hash, and invalidates older sessions."""
    clean_username = username.strip()
    if not clean_username:
        return False, "Username cannot be empty."
    valid, msg = validate_password_strength(password)
    if not valid:
        return False, msg

    pw_hash = hash_password(password)
    set_setting("auth_username", clean_username)
    set_setting("auth_password_hash", pw_hash)
    set_setting("auth_disabled", "0")
    set_setting("auth_is_existing_install", "0")
    rotate_session_version()
    config.refresh()
    logger.info(f"Authentication credentials updated for user '{clean_username}'.")
    return True, "Credentials updated successfully."


def disable_auth_login() -> None:
    """Explicitly disables authentication and removes stored credentials."""
    set_setting("auth_disabled", "1")
    set_setting("auth_username", "")
    set_setting("auth_password_hash", "")
    rotate_session_version()
    config.refresh()
    logger.info("Authentication has been disabled by user.")


def reset_auth() -> None:
    """Wipes all stored authentication credentials and flags, resetting to unconfigured setup state."""
    conn = get_db_connection()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.cursor()
        for key in AUTH_SETTINGS_KEYS:
            cursor.execute("DELETE FROM settings WHERE key = ?", (key,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Error resetting authentication settings: {e}")
        raise
    finally:
        conn.close()
    config.refresh()
    logger.info("Authentication credentials and state have been completely reset.")
