"""Tests for GET /api/health and optional HTTP Basic Auth protection across routes."""
import base64
import os
import pytest
from unittest.mock import patch

from web.server import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _basic_auth_header(user: str, password: str) -> dict:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {token}"}


def test_health_check_endpoint_success(client):
    """GET /api/health returns 200 and {'status': 'ok'} without secrets or path info."""
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data == {"status": "ok"}
    # Verify no leaked credentials or environment details
    assert "token" not in str(data).lower()
    assert "password" not in str(data).lower()
    assert "config" not in str(data).lower()


def test_health_check_endpoint_db_failure(client):
    """GET /api/health returns 503 if the database query fails."""
    with patch("web.server.get_db_connection", side_effect=Exception("DB down")):
        res = client.get("/api/health")
        assert res.status_code == 503
        data = res.get_json()
        assert data["status"] == "error"
        assert "Database unavailable" in data["message"]


def test_routes_accessible_when_basic_auth_unset(client):
    """When XARRTOOLS_AUTH_USER / XARRTOOLS_AUTH_PASSWORD are not set, normal behaviour is unchanged."""
    env_patch = {
        "XARRTOOLS_AUTH_USER": "",
        "XARRTOOLS_AUTH_PASSWORD": ""
    }
    with patch.dict(os.environ, env_patch, clear=False):
        res_index = client.get("/")
        assert res_index.status_code == 200

        res_settings = client.get("/api/settings")
        assert res_settings.status_code == 200

        res_health = client.get("/api/health")
        assert res_health.status_code == 200


def test_routes_gated_when_basic_auth_set(client):
    """When XARRTOOLS_AUTH_USER and XARRTOOLS_AUTH_PASSWORD are set, ALL routes (incl GET / and /api/*) require auth, except /api/health."""
    env_patch = {
        "XARRTOOLS_AUTH_USER": "testuser",
        "XARRTOOLS_AUTH_PASSWORD": "supersecretpassword123"
    }
    with patch.dict(os.environ, env_patch, clear=False):
        # 1. Unauthenticated requests to standard routes are rejected with 401 and WWW-Authenticate
        for route in ("/", "/api/settings", "/api/stats"):
            res = client.get(route)
            assert res.status_code == 401, f"Route {route} should be gated"
            assert 'Basic realm="xarrtools"' in res.headers.get("WWW-Authenticate", "")
            data = res.get_json() if res.is_json else None
            if data:
                assert data.get("status") == "error"

        # 2. Health endpoint remains accessible unauthenticated
        res_health = client.get("/api/health")
        assert res_health.status_code == 200
        assert res_health.get_json() == {"status": "ok"}

        # 3. Bad credentials rejected
        bad_headers = _basic_auth_header("testuser", "wrongpassword")
        res_bad = client.get("/", headers=bad_headers)
        assert res_bad.status_code == 401

        bad_user_headers = _basic_auth_header("wronguser", "supersecretpassword123")
        res_bad_user = client.get("/", headers=bad_user_headers)
        assert res_bad_user.status_code == 401

        # 4. Valid credentials succeed
        valid_headers = _basic_auth_header("testuser", "supersecretpassword123")
        res_good_index = client.get("/", headers=valid_headers)
        assert res_good_index.status_code == 200

        res_good_settings = client.get("/api/settings", headers=valid_headers)
        assert res_good_settings.status_code == 200

        # 5. POST /api/settings requires both Basic Auth and X-API-Key
        from core.db import get_setting
        api_key = get_setting("api_key")
        
        # Valid basic auth + valid API key
        combined_headers = {**valid_headers, "X-API-Key": api_key}
        res_post = client.post("/api/settings", headers=combined_headers, json={"default_past_months": "2"})
        assert res_post.status_code == 200

        # Valid basic auth + missing API key -> 401
        res_post_nokey = client.post("/api/settings", headers=valid_headers, json={"default_past_months": "2"})
        assert res_post_nokey.status_code == 401


def test_auth_password_redacted_in_logging():
    """XARRTOOLS_AUTH_PASSWORD is masked by the redacting logging filter."""
    from core.logging_setup import redact_sensitive_data
    with patch.dict(os.environ, {"XARRTOOLS_AUTH_PASSWORD": "supersecretpassword123"}):
        text = "User logged in with password supersecretpassword123 and continued"
        redacted = redact_sensitive_data(text)
        assert "supersecretpassword123" not in redacted
        assert "***REDACTED***" in redacted
