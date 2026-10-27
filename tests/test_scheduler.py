"""Tests for background scheduled refreshes (core.scheduler and web.server scheduler endpoints).

Verifies:
- core.scheduler.validate_time_of_day
- core.scheduler.parse_time_of_day
- core.scheduler.compute_next_run
- core.scheduler.is_due (startup delay, overdue check, interval and daily triggers)
- web.server.run_scan (works without request context, raises RuntimeError if busy)
- web.server.run_scheduler_job (updates DB last_run and last_result, handles errors)
- GET /api/scheduler/status
- POST /api/scheduler/run-now (API key protected, 409 if busy, 200 if started)
- POST /api/settings validation for scheduler fields (400 on invalid)
"""
import os
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

# 1. Isolate the database path BEFORE importing web.server or core.config
import xarrtools.core.db; from xarrtools import core
fd, temp_db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
core.db.DB_PATH = Path(temp_db_path)
core.db.init_db()

# 2. Intercept background thread startup so tests don't run background loops
with patch("threading.Thread"):
    from xarrtools.web.server import (
        app,
        run_scan,
        run_scheduler_job,
        scan_progress,
        scan_progress_lock,
        scheduler_job_lock
    )

import xarrtools.core.scheduler as scheduler; from xarrtools import core
from xarrtools.core.config import config


@pytest.fixture(autouse=True)
def cleanup_db():
    """Wipes test DB tables and resets default settings between test cases."""
    scan_progress["status"] = "idle"
    if scheduler_job_lock.locked():
        try:
            scheduler_job_lock.release()
        except RuntimeError:
            pass

    conn = core.db.get_db_connection()
    conn.execute("DELETE FROM cache")
    conn.execute("DELETE FROM settings")
    conn.commit()
    conn.close()

    core.db.init_db()
    core.db.set_setting("api_key", "test_api_key")
    config.refresh()
    yield
    scan_progress["status"] = "idle"
    if scheduler_job_lock.locked():
        try:
            scheduler_job_lock.release()
        except RuntimeError:
            pass


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
            if "X-API-Key" not in headers:
                headers["X-API-Key"] = self._get_api_key()
            kwargs["headers"] = headers
            return self.inner.post(*args, **kwargs)

    with app.test_client() as c:
        yield TestClientAPIKeyWrapper(c)


# ============================================================================
# Unit Tests: core.scheduler
# ============================================================================

def test_validate_time_of_day():
    # Empty / None cases
    assert scheduler.validate_time_of_day(None) is True
    assert scheduler.validate_time_of_day("") is True
    assert scheduler.validate_time_of_day("   ") is True

    # Valid times
    assert scheduler.validate_time_of_day("00:00") is True
    assert scheduler.validate_time_of_day("03:30") is True
    assert scheduler.validate_time_of_day("23:59") is True

    # Invalid types
    assert scheduler.validate_time_of_day(1234) is False

    # Invalid formats / ranges
    for invalid in ["24:00", "12:60", "3:30", "03:5", "abc", "12:34:56", "25:99"]:
        assert scheduler.validate_time_of_day(invalid) is False, f"Expected {invalid} to be invalid"


def test_parse_time_of_day():
    assert scheduler.parse_time_of_day(None) is None
    assert scheduler.parse_time_of_day("") is None
    assert scheduler.parse_time_of_day("   ") is None
    assert scheduler.parse_time_of_day("04:15") == (4, 15)
    assert scheduler.parse_time_of_day("23:59") == (23, 59)

    with pytest.raises(ValueError):
        scheduler.parse_time_of_day("invalid")


def test_compute_next_run_interval_mode():
    now = datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc)

    # No last_run: next_run is now + interval
    next_run = scheduler.compute_next_run(None, 24, None, now=now)
    assert next_run == now + timedelta(hours=24)

    # With last_run: next_run is last_run + interval
    last_run = datetime(2026, 5, 10, 10, 0, 0, tzinfo=timezone.utc)
    next_run = scheduler.compute_next_run(last_run, 6, None, now=now)
    assert next_run == last_run + timedelta(hours=6)

    # Clamping: interval < 1 clamped to 1
    next_run = scheduler.compute_next_run(last_run, 0, None, now=now)
    assert next_run == last_run + timedelta(hours=1)

    # Clamping: interval > 168 clamped to 168
    next_run = scheduler.compute_next_run(last_run, 500, None, now=now)
    assert next_run == last_run + timedelta(hours=168)


def test_compute_next_run_daily_time_mode():
    # Target time: 03:00 UTC
    # Case 1: now is 02:00 UTC (before target), last_run was yesterday
    now = datetime(2026, 5, 10, 2, 0, 0, tzinfo=timezone.utc)
    last_run = datetime(2026, 5, 9, 3, 0, 0, tzinfo=timezone.utc)
    next_run = scheduler.compute_next_run(last_run, 24, "03:00", now=now, tz=timezone.utc)
    assert next_run == datetime(2026, 5, 10, 3, 0, 0, tzinfo=timezone.utc)

    # Case 2: now is 04:00 UTC (after target), last_run was today at 03:00
    now = datetime(2026, 5, 10, 4, 0, 0, tzinfo=timezone.utc)
    last_run = datetime(2026, 5, 10, 3, 0, 0, tzinfo=timezone.utc)
    next_run = scheduler.compute_next_run(last_run, 24, "03:00", now=now, tz=timezone.utc)
    assert next_run == datetime(2026, 5, 11, 3, 0, 0, tzinfo=timezone.utc)

    # Case 3: now is 02:00 UTC, but last_run is already today at 03:00 (e.g. run manually or clock shift)
    now = datetime(2026, 5, 10, 2, 0, 0, tzinfo=timezone.utc)
    last_run = datetime(2026, 5, 10, 3, 0, 0, tzinfo=timezone.utc)
    next_run = scheduler.compute_next_run(last_run, 24, "03:00", now=now, tz=timezone.utc)
    assert next_run == datetime(2026, 5, 11, 3, 0, 0, tzinfo=timezone.utc)


def test_compute_next_run_daily_time_mode_local_timezone():
    # 03:00 local in UTC+2 is 01:00 UTC
    tz = timezone(timedelta(hours=2))
    now = datetime(2026, 5, 10, 0, 30, 0, tzinfo=timezone.utc)  # 02:30 local, before target
    assert scheduler.compute_next_run(None, 24, "03:00", now=now, tz=tz) == datetime(2026, 5, 10, 1, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 5, 10, 1, 30, 0, tzinfo=timezone.utc)  # 03:30 local, after target
    assert scheduler.compute_next_run(None, 24, "03:00", now=now, tz=tz) == datetime(2026, 5, 11, 1, 0, 0, tzinfo=timezone.utc)


def test_is_due_disabled():
    now = datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc)
    assert not scheduler.is_due(None, 24, None, now=now, enabled=False)


def test_is_due_never_run_startup_delay():
    now = datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc)
    # 30 seconds after startup -> not due yet
    startup_30s_ago = now - timedelta(seconds=30)
    assert not scheduler.is_due(None, 24, None, now=now, startup_time=startup_30s_ago, enabled=True)

    # 65 seconds after startup -> due!
    startup_65s_ago = now - timedelta(seconds=65)
    assert scheduler.is_due(None, 24, None, now=now, startup_time=startup_65s_ago, enabled=True)

    # No startup_time provided -> due immediately
    assert scheduler.is_due(None, 24, None, now=now, startup_time=None, enabled=True)


def test_is_due_restart_does_not_rescan_unless_overdue():
    now = datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc)
    # Server just started 10 seconds ago
    startup = now - timedelta(seconds=10)

    # Last run was 2 hours ago, interval 24 hours -> NOT overdue -> NOT due
    last_run_recent = now - timedelta(hours=2)
    assert not scheduler.is_due(last_run_recent, 24, None, now=now, startup_time=startup, enabled=True)

    # Last run was 25 hours ago, interval 24 hours -> OVERDUE -> DUE
    last_run_old = now - timedelta(hours=25)
    assert scheduler.is_due(last_run_old, 24, None, now=now, startup_time=startup, enabled=True)


# ============================================================================
# Route Tests: web.server scheduler endpoints & settings validation
# ============================================================================

def test_scheduler_status_endpoint(client):
    res = client.get("/api/scheduler/status")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["enabled"] is False
    assert data["interval_hours"] == 24
    assert data["time_of_day"] is None
    assert data["last_run"] is None
    assert data["running"] is False
    assert "next_run" in data


def test_settings_validation_scheduler_fields(client):
    # Invalid interval (too small)
    res = client.post("/api/settings", json={"scheduler_interval_hours": 0})
    assert res.status_code == 400
    assert "between 1 and 168" in res.get_json()["message"]

    # Invalid interval (too large)
    res = client.post("/api/settings", json={"scheduler_interval_hours": 169})
    assert res.status_code == 400
    assert "between 1 and 168" in res.get_json()["message"]

    # Invalid interval (non-integer)
    res = client.post("/api/settings", json={"scheduler_interval_hours": "abc"})
    assert res.status_code == 400

    # Invalid time_of_day format
    res = client.post("/api/settings", json={"scheduler_time_of_day": "25:00"})
    assert res.status_code == 400
    assert "HH:MM" in res.get_json()["message"]

    # Valid settings update
    res = client.post(
        "/api/settings",
        json={
            "scheduler_enabled": True,
            "scheduler_interval_hours": 12,
            "scheduler_time_of_day": "03:30",
        },
    )
    assert res.status_code == 200

    # Verify status endpoint reflects updated settings
    status_res = client.get("/api/scheduler/status")
    assert status_res.status_code == 200
    status_data = status_res.get_json()
    assert status_data["enabled"] is True
    assert status_data["interval_hours"] == 12
    assert status_data["time_of_day"] == "03:30"

    # Clearing time_of_day
    res_clear = client.post("/api/settings", json={"scheduler_time_of_day": ""})
    assert res_clear.status_code == 200
    status_res2 = client.get("/api/scheduler/status")
    assert status_res2.get_json()["time_of_day"] is None


def test_scheduler_run_now_auth(client):
    # Test unauthenticated / bad key
    res = client.inner.post("/api/scheduler/run-now", headers={"X-API-Key": "wrong_key"})
    assert res.status_code == 401


def test_scheduler_run_now_success_and_busy(client):
    with patch("xarrtools.web.server.run_scheduler_job"):
        # 1. Trigger run-now when idle
        res = client.post("/api/scheduler/run-now")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "started"

        # 2. Trigger run-now when busy
        scan_progress["status"] = "scraping"
        try:
            res_busy = client.post("/api/scheduler/run-now")
            assert res_busy.status_code == 409
            assert res_busy.get_json()["status"] == "busy"
        finally:
            scan_progress["status"] = "idle"


# ============================================================================
# Execution Tests: run_scan & run_scheduler_job
# ============================================================================

def test_run_scan_without_request_context():
    """run_scan must execute cleanly without Flask request context."""
    with patch("xarrtools.web.server.get_discoveries") as mock_disc, \
         patch("xarrtools.web.server.enrich_tv_show") as mock_tv, \
         patch("xarrtools.web.server.enrich_movie") as mock_movie, \
         patch("xarrtools.web.server.get_clients", return_value=(None, None)), \
         patch("xarrtools.web.server.sync_library_cache"):

        now = datetime.now()
        mock_disc.return_value = (
            [{
                "title": "Test TV",
                "release_date": "2026-05-15",
                "date_obj": now,
                "date_str": "2026-05-15",
                "type": "tv",
                "description": "Show description",
                "href": "http://example.com/show"
            }],
            [{
                "title": "Test Movie",
                "release_date": "2026-05-20",
                "date_obj": now,
                "date_str": "2026-05-20",
                "type": "movie",
                "description": "Movie description",
                "href": "http://example.com/movie"
            }],
        )
        mock_tv.side_effect = lambda title, year, client: {
            "title": title, "year": year, "type": "tv",
            "plot": "Show plot", "genres": [], "cast": "", "trailer": "",
            "poster_url": "", "tvdbId": 1, "imdbId": "tt123", "network": ""
        }
        mock_movie.side_effect = lambda title, year, client, imdb: {
            "title": title, "year": year, "type": "movie",
            "plot": "Movie plot", "genres": [], "cast": "", "trailer": "",
            "poster_url": "", "tmdbId": 1, "imdbId": "tt456"
        }

        res = run_scan(past_months=1, future_months=2)
        assert "tv" in res
        assert "movies" in res
        assert len(res["tv"]) == 1
        assert len(res["movies"]) == 1
        assert scan_progress["status"] == "idle"


def test_run_scan_concurrency_lock():
    """Concurrent run_scan must raise RuntimeError."""
    scan_progress["status"] = "scraping"
    try:
        with pytest.raises(RuntimeError, match="A scan is already in progress"):
            run_scan()
    finally:
        scan_progress["status"] = "idle"


def test_run_scheduler_job_updates_db_and_records_result():
    def mock_scan_side_effect(*args, **kwargs):
        core.db.add_cached_item("tv", {"title": "Show A", "year": 2026, "date_obj": "2026-05-01"})
        core.db.add_cached_item("movie", {"title": "Movie B", "year": 2026, "date_obj": "2026-05-01"})
        core.db.add_cached_item("movie", {"title": "Movie C", "year": 2026, "date_obj": "2026-05-01"})
        return {
            "tv": [{"title": "Show A"}],
            "movies": [{"title": "Movie B"}, {"title": "Movie C"}]
        }

    with patch("xarrtools.web.server.run_scan", side_effect=mock_scan_side_effect):
        run_scheduler_job()

        last_run = core.db.get_setting("scheduler_last_run", None)
        last_result_json = core.db.get_setting("scheduler_last_result", None)

        assert last_run is not None
        assert last_result_json is not None
        result = json.loads(last_result_json)
        assert result["status"] in ("ok", "success")
        assert result["tv_count"] == 1
        assert result["movie_count"] == 2
        assert result["new_items"] == 3


def test_run_scheduler_job_records_error_on_failure():
    with patch("xarrtools.web.server.run_scan", side_effect=Exception("Database boom")):
        run_scheduler_job()

        last_result_json = core.db.get_setting("scheduler_last_result", None)
        assert last_result_json is not None
        result = json.loads(last_result_json)
        assert result["status"] == "error"
        assert "Database boom" in result["error"]
