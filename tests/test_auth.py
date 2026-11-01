"""Tests for authentication, first-run setup, session cookies, throttling, and recovery."""
import base64
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from flask.testing import FlaskClient

from xarrtools.core.auth import (
    MIN_PASSWORD_LENGTH,
    SESSION_COOKIE_NAME,
    create_session_token,
    disable_auth_login,
    get_auth_mode,
    get_session_secret,
    get_session_version,
    hash_password,
    is_auth_configured,
    is_auth_disabled,
    is_env_auth_enabled,
    is_existing_install_exempt,
    is_network_exposed,
    login_throttle,
    needs_setup,
    reset_auth,
    rotate_session_version,
    sanitize_next_url,
    set_user_credentials,
    should_show_unauthenticated_banner,
    validate_password_strength,
    verify_password,
    verify_session_token,
)
from xarrtools.core.db import (
    AUTH_SETTINGS_KEYS,
    export_to_dict,
    get_all_settings,
    get_setting,
    import_from_dict,
    init_db,
    set_setting,
)
from xarrtools.web.server import app


@pytest.fixture(autouse=True)
def clean_auth_env():
    """Ensures test environment has no residual auth environment variables or DB credentials."""
    login_throttle.reset()
    orig_bind = app.config.get("SERVER_BIND_HOST")
    reset_auth()
    env_clean = {
        "XARRTOOLS_AUTH_USER": "",
        "XARRTOOLS_AUTH_PASSWORD": "",
        "XARRTOOLS_AUTH_DISABLED": "",
        "XARRTOOLS_RESET_AUTH": "",
    }
    with patch.dict(os.environ, env_clean, clear=False):
        yield
    login_throttle.reset()
    reset_auth()
    if orig_bind is not None:
        app.config["SERVER_BIND_HOST"] = orig_bind
    else:
        app.config.pop("SERVER_BIND_HOST", None)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# --- 1. Password Hashing & Verification Tests ---

def test_password_hashing_and_verification():
    """Passwords are hashed with scrypt and verified in constant time."""
    pw = "superSecretPassword123!"
    hashed = hash_password(pw)
    assert hashed.startswith("scrypt$16384$8$1$")
    assert verify_password(pw, hashed) is True
    assert verify_password("wrongPassword", hashed) is False
    assert verify_password("", hashed) is False
    assert verify_password(pw, "") is False
    assert verify_password(pw, "invalid$format") is False
    assert verify_password(pw, "scrypt$invalid$params$here$12$34") is False


def test_password_strength_validation():
    """Passwords must be at least 8 characters long."""
    valid, msg = validate_password_strength("12345678")
    assert valid is True
    assert msg == ""

    valid, msg = validate_password_strength("short")
    assert valid is False
    assert f"at least {MIN_PASSWORD_LENGTH}" in msg

    valid, msg = validate_password_strength("")
    assert valid is False


# --- 2. Session Token & Cookie Tests ---

def test_session_token_issuance_and_verification():
    """Session tokens are HMAC-signed, verify active user and expire gracefully."""
    reset_auth()
    set_user_credentials("alice", "Password123")

    token = create_session_token("alice")
    assert "." in token

    user = verify_session_token(token)
    assert user == "alice"

    # Tampered signature rejected
    tampered_sig = token[:-4] + "abcd"
    assert verify_session_token(tampered_sig) is None

    # Tampered payload rejected
    b64, sig = token.split(".", 1)
    fake_b64 = base64.urlsafe_b64encode(b'{"u":"bob","v":"1","exp":9999999999}').decode('ascii').rstrip('=')
    assert verify_session_token(f"{fake_b64}.{sig}") is None

    # Expired token rejected
    expired_token = create_session_token("alice", ttl_days=-1)
    assert verify_session_token(expired_token) is None


def test_session_invalidation_on_password_change_or_logout():
    """Rotating session version or changing password invalidates previously issued tokens."""
    reset_auth()
    set_user_credentials("alice", "OldPassword123")
    token1 = create_session_token("alice")
    assert verify_session_token(token1) == "alice"

    # Rotate session version (e.g. on logout)
    rotate_session_version()
    assert verify_session_token(token1) is None

    # Changing credentials invalidates tokens
    token2 = create_session_token("alice")
    assert verify_session_token(token2) == "alice"
    set_user_credentials("alice", "NewPassword456")
    assert verify_session_token(token2) is None


# --- 3. Login Throttling Tests ---

def test_login_throttling_after_repeated_failures():
    """Client IP is throttled (HTTP 429) after 5 consecutive failed login attempts."""
    ip = "192.168.1.50"
    login_throttle.reset()

    for _ in range(4):
        login_throttle.record_failure(ip)
        throttled, wait_sec = login_throttle.is_throttled(ip)
        assert throttled is False
        assert wait_sec == 0

    # 5th failure triggers throttle
    login_throttle.record_failure(ip)
    throttled, wait_sec = login_throttle.is_throttled(ip)
    assert throttled is True
    assert 0 < wait_sec <= 60

    # Clear failures resets throttle
    login_throttle.clear_failures(ip)
    throttled, _ = login_throttle.is_throttled(ip)
    assert throttled is False


# --- 4. Open Redirect Sanitization Tests ---

def test_sanitize_next_url():
    """Only safe relative paths are allowed for post-login redirection."""
    assert sanitize_next_url("/movies") == "/movies"
    assert sanitize_next_url("/api/settings?param=1") == "/api/settings?param=1"
    assert sanitize_next_url("") == "/"
    assert sanitize_next_url(None) == "/"
    assert sanitize_next_url("https://attacker.com") == "/"
    assert sanitize_next_url("http://attacker.com") == "/"
    assert sanitize_next_url("//attacker.com") == "/"
    assert sanitize_next_url("/\\attacker.com") == "/"
    assert sanitize_next_url("javascript:alert(1)") == "/"
    assert sanitize_next_url("/movies\n/evil") == "/"
    assert sanitize_next_url("/movies\r/evil") == "/"
    assert sanitize_next_url("/movies\t/evil") == "/"


# --- 5. Network Exposure Calculation Tests ---

def test_network_exposure_detection():
    """Correctly differentiates loopback from network-exposed host bindings."""
    assert is_network_exposed("127.0.0.1") is False
    assert is_network_exposed("localhost") is False
    assert is_network_exposed("::1") is False
    assert is_network_exposed("127.0.0.2") is False

    assert is_network_exposed("0.0.0.0") is True
    assert is_network_exposed("::") is True
    assert is_network_exposed("") is True
    assert is_network_exposed(None) is True
    assert is_network_exposed("192.168.1.100") is True
    assert is_network_exposed("10.0.0.5") is True
    assert is_network_exposed("xarrtools.myhomelab.net") is True


# --- 6. First-Run Setup Flow Tests ---

def test_setup_redirect_when_network_exposed(client):
    """When bound to 0.0.0.0 without credentials, requests redirect to /setup; health and static stay open."""
    reset_auth()
    app.config["SERVER_BIND_HOST"] = "0.0.0.0"

    # Root redirects to /setup
    res = client.get("/")
    assert res.status_code == 302
    assert res.headers["Location"].endswith("/setup")

    # API endpoints return 403 with setup_required flag
    res_api = client.get("/api/settings")
    assert res_api.status_code == 403
    assert res_api.get_json()["setup_required"] is True

    # Setup page is accessible
    res_setup = client.get("/setup")
    assert res_setup.status_code == 200
    assert b"Welcome to xarrtools" in res_setup.data
    # API key is never exposed on the setup page
    assert b"x-api-key" not in res_setup.data

    # Health check remains open
    res_health = client.get("/api/health")
    assert res_health.status_code == 200
    assert res_health.get_json()["status"] == "ok"


def test_setup_form_submission_validation_and_success(client):
    """POST /api/setup enforces password length, confirmation, sets credentials, and sets session cookie."""
    reset_auth()
    app.config["SERVER_BIND_HOST"] = "0.0.0.0"

    # Password too short
    res_short = client.post("/api/setup", json={"username": "admin", "password": "123", "confirm_password": "123"})
    assert res_short.status_code == 400
    assert "at least 8" in res_short.get_json()["message"]

    # Password mismatch
    res_mismatch = client.post("/api/setup", json={"username": "admin", "password": "Password123", "confirm_password": "Password456"})
    assert res_mismatch.status_code == 400
    assert "do not match" in res_mismatch.get_json()["message"]

    # Valid submission
    res_good = client.post("/api/setup", json={"username": "admin", "password": "Password123", "confirm_password": "Password123"})
    assert res_good.status_code == 200
    assert res_good.get_json()["status"] == "success"

    # Verify session cookie was attached
    cookie_header = res_good.headers.get("Set-Cookie", "")
    assert SESSION_COOKIE_NAME in cookie_header
    assert "HttpOnly" in cookie_header
    assert "SameSite=Lax" in cookie_header

    # Authenticated user can now view /
    res_index = client.get("/")
    assert res_index.status_code == 200
    assert b"x-api-key" in res_index.data


def test_setup_continue_without_login(client):
    """Selecting 'Continue without a login' records auth_disabled and unblocks the app with banner."""
    reset_auth()
    app.config["SERVER_BIND_HOST"] = "0.0.0.0"

    res = client.post("/api/setup", json={"disable": True})
    assert res.status_code == 200
    assert res.get_json()["status"] == "success"

    # Now accessible without redirect
    res_index = client.get("/")
    assert res_index.status_code == 200

    # Status reports unauthenticated warning banner
    res_status = client.get("/api/auth/status")
    assert res_status.status_code == 200
    data = res_status.get_json()
    assert data["auth_mode"] == "none"
    assert data["auth_configured"] is False
    assert data["unauthenticated_banner"] is True


# --- 7. Form-Based Login & Logout Tests ---

def test_login_flow_and_session_cookie(client):
    """Users authenticate at /api/auth/login and can log out at /api/auth/logout."""
    reset_auth()
    set_user_credentials("admin", "AdminSecret123")
    app.config["SERVER_BIND_HOST"] = "0.0.0.0"

    # Unauthenticated request to / redirects to /login
    res_unauth = client.get("/")
    assert res_unauth.status_code == 302
    assert "/login" in res_unauth.headers["Location"]

    # Unauthenticated API request returns 401
    res_api_unauth = client.get("/api/settings")
    assert res_api_unauth.status_code == 401

    # Login with bad credentials fails
    res_bad = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert res_bad.status_code == 401

    # Login with correct credentials succeeds
    res_ok = client.post("/api/auth/login", json={"username": "admin", "password": "AdminSecret123"})
    assert res_ok.status_code == 200
    assert SESSION_COOKIE_NAME in res_ok.headers.get("Set-Cookie", "")

    # Now / is accessible
    res_auth = client.get("/")
    assert res_auth.status_code == 200

    # Logout revokes session
    res_logout = client.post("/api/auth/logout")
    assert res_logout.status_code == 200

    # Old session is now rejected
    res_after = client.get("/")
    assert res_after.status_code == 302
    assert "/login" in res_after.headers["Location"]


def test_login_endpoint_throttled_under_repeated_bad_attempts(client):
    """Failed login attempts at POST /api/auth/login return 429 when throttled."""
    reset_auth()
    set_user_credentials("admin", "AdminSecret123")
    app.config["SERVER_BIND_HOST"] = "0.0.0.0"

    for _ in range(5):
        res = client.post("/api/auth/login", json={"username": "admin", "password": "bad"})
        assert res.status_code == 401

    # 6th attempt should be throttled
    res_throttled = client.post("/api/auth/login", json={"username": "admin", "password": "bad"})
    assert res_throttled.status_code == 429
    assert "Too many failed login attempts" in res_throttled.get_json()["message"]


# --- 8. Existing Install Upgrade Safety Tests ---

def test_existing_install_never_locked_out_on_upgrade(client):
    """A database that already contains settings from prior versions shows banner but never redirects."""
    reset_auth()
    # Simulate an upgraded database
    set_setting("auth_is_existing_install", "1")
    app.config["SERVER_BIND_HOST"] = "0.0.0.0"

    # Needs setup should be False (not locked out)
    assert needs_setup("0.0.0.0") is False

    # GET / is accessible
    res = client.get("/")
    assert res.status_code == 200

    # Persistent banner is shown
    assert should_show_unauthenticated_banner("0.0.0.0") is True
    res_status = client.get("/api/auth/status")
    assert res_status.get_json()["unauthenticated_banner"] is True


def test_desktop_loopback_no_prompt_and_no_banner(client):
    """Loopback bind (127.0.0.1) requires no setup prompt and displays no exposure banner."""
    reset_auth()
    app.config["SERVER_BIND_HOST"] = "127.0.0.1"

    assert needs_setup("127.0.0.1") is False
    assert should_show_unauthenticated_banner("127.0.0.1") is False

    res = client.get("/")
    assert res.status_code == 200


# --- 9. Environment Precedence Tests ---

def test_environment_credentials_take_precedence(client):
    """Environment credentials (XARRTOOLS_AUTH_USER/PASSWORD) override stored login and force Basic auth."""
    reset_auth()
    set_user_credentials("dbuser", "DbUserPassword123")
    app.config["SERVER_BIND_HOST"] = "0.0.0.0"

    env_patch = {
        "XARRTOOLS_AUTH_USER": "envuser",
        "XARRTOOLS_AUTH_PASSWORD": "envpassword123",
    }
    with patch.dict(os.environ, env_patch):
        # Basic auth required
        res = client.get("/")
        assert res.status_code == 401
        assert 'Basic realm="xarrtools"' in res.headers["WWW-Authenticate"]

        # Valid Basic auth succeeds
        token = base64.b64encode(b"envuser:envpassword123").decode("utf-8")
        res_ok = client.get("/", headers={"Authorization": f"Basic {token}"})
        assert res_ok.status_code == 200

        # Auth status indicates env mode and cannot manage from UI
        res_status = client.get("/api/auth/status", headers={"Authorization": f"Basic {token}"})
        data = res_status.get_json()
        assert data["auth_mode"] == "env"
        assert data["can_manage"] is False


def test_environment_auth_disabled_takes_precedence(client):
    """XARRTOOLS_AUTH_DISABLED=true unblocks all routes regardless of stored auth."""
    reset_auth()
    set_user_credentials("admin", "AdminPassword123")
    app.config["SERVER_BIND_HOST"] = "0.0.0.0"

    with patch.dict(os.environ, {"XARRTOOLS_AUTH_DISABLED": "true"}):
        res = client.get("/")
        assert res.status_code == 200


# --- 10. Backup Exclusion & Restore Safety Tests ---

def test_auth_credentials_excluded_from_api_settings(client):
    """GET /api/settings never leaks password hash, session secret, or any auth_* keys."""
    reset_auth()
    set_user_credentials("admin", "SecretPassword123")

    # In-memory settings
    settings = get_all_settings()
    for key in AUTH_SETTINGS_KEYS:
        assert key not in settings, f"{key} should not be returned by get_all_settings"

    # API endpoint
    token = create_session_token("admin")
    client.set_cookie(SESSION_COOKIE_NAME, token)
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.get_json()
    for key in AUTH_SETTINGS_KEYS:
        assert key not in data
    assert "password" not in str(data).lower()
    assert "scrypt" not in str(data).lower()


def test_auth_credentials_excluded_from_backup_and_cannot_be_restored():
    """export_to_dict excludes auth keys, and import_from_dict ignores injected auth keys."""
    reset_auth()
    set_user_credentials("admin", "OriginalSecret123")
    orig_hash = get_setting("auth_password_hash")
    orig_secret = get_setting("auth_session_secret")

    # 1. Export backup dictionary
    backup = export_to_dict(include_media=False)
    assert "settings" in backup
    for key in AUTH_SETTINGS_KEYS:
        assert key not in backup["settings"], f"{key} must be excluded from backup export"

    # 2. Simulate restoring a backup injected with malicious auth keys
    malicious_data = {
        "settings": {
            "radarr_url": "http://localhost:7878",
            "auth_username": "hacker",
            "auth_password_hash": "scrypt$16384$8$1$fake$fake",
            "auth_session_secret": "hackedsecret",
            "auth_disabled": "1",
        }
    }
    import_from_dict(malicious_data)

    # Verify original credentials remain untouched
    assert get_setting("auth_username") == "admin"
    assert get_setting("auth_password_hash") == orig_hash
    assert get_setting("auth_session_secret") == orig_secret
    assert get_setting("auth_disabled") == "0"


def test_full_zip_backup_excludes_auth_and_restore_safeguard():
    """ZIP export excludes auth keys, and import_full_backup ignores injected auth keys."""
    from xarrtools.core.backup import export_full_backup, import_full_backup
    import io

    reset_auth()
    set_user_credentials("admin", "ZipPassword123")
    orig_hash = get_setting("auth_password_hash")

    bio = io.BytesIO()
    export_full_backup(bio, include_media=False)
    bio.seek(0)

    import zipfile
    with zipfile.ZipFile(bio, "r") as zf:
        backup_json = json.loads(zf.read("backup.json").decode("utf-8"))
        for key in AUTH_SETTINGS_KEYS:
            assert key not in backup_json.get("settings", {})

    # Restore backup
    bio.seek(0)
    import_full_backup(bio)
    assert get_setting("auth_username") == "admin"
    assert get_setting("auth_password_hash") == orig_hash


# --- 11. Auth Recovery & CLI Reset Tests ---

def test_reset_auth_clears_all_credentials_and_state():
    """reset_auth() clears all auth keys from DB, returning the app to unconfigured state."""
    reset_auth()
    set_user_credentials("admin", "ResetPassword123")
    assert is_auth_configured() is True

    reset_auth()
    assert is_auth_configured() is False
    assert get_setting("auth_username") == ""
    assert get_setting("auth_password_hash") == ""
    assert needs_setup("0.0.0.0") is True


def test_main_cli_reset_auth_flag(capsys):
    """python -m xarrtools --reset-auth clears credentials and exits cleanly."""
    from xarrtools.main import main
    set_user_credentials("admin", "CliResetPass123")
    assert is_auth_configured() is True

    exit_code = main(["--reset-auth"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "successfully reset" in captured.out
    assert is_auth_configured() is False


# --- 12. Settings Security API Endpoints ---

def test_change_credentials_endpoint(client):
    """POST /api/auth/change_credentials allows updating credentials with current password check."""
    reset_auth()
    set_user_credentials("admin", "OldPassword123")
    token = create_session_token("admin")
    client.set_cookie(SESSION_COOKIE_NAME, token)

    api_key = get_setting("api_key")

    # Bad current password rejected
    res_bad = client.post(
        "/api/auth/change_credentials",
        headers={"X-API-Key": api_key},
        json={"current_password": "wrong", "new_username": "admin", "new_password": "NewPassword123", "confirm_password": "NewPassword123"}
    )
    assert res_bad.status_code == 400
    assert "Current password is incorrect" in res_bad.get_json()["message"]

    # Valid update succeeds
    res_good = client.post(
        "/api/auth/change_credentials",
        headers={"X-API-Key": api_key},
        json={"current_password": "OldPassword123", "new_username": "newadmin", "new_password": "NewPassword123", "confirm_password": "NewPassword123"}
    )
    assert res_good.status_code == 200
    assert get_setting("auth_username") == "newadmin"
    assert verify_password("NewPassword123", get_setting("auth_password_hash")) is True


def test_disable_auth_endpoint(client):
    """POST /api/auth/disable requires current password and disables auth."""
    reset_auth()
    set_user_credentials("admin", "TurnOffPassword123")
    token = create_session_token("admin")
    client.set_cookie(SESSION_COOKIE_NAME, token)

    api_key = get_setting("api_key")

    # Incorrect password rejected
    res_bad = client.post("/api/auth/disable", headers={"X-API-Key": api_key}, json={"current_password": "wrong"})
    assert res_bad.status_code == 400

    # Correct password succeeds
    res_good = client.post("/api/auth/disable", headers={"X-API-Key": api_key}, json={"current_password": "TurnOffPassword123"})
    assert res_good.status_code == 200
    assert is_auth_configured() is False
    assert is_auth_disabled() is True
