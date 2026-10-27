import hashlib
import os
import tempfile
from pathlib import Path

import pytest
from unittest.mock import patch

# --- Real-database protection -------------------------------------------------
# Many test modules historically wrote to the developer's real xarrtools.db (DELETE FROM cache, settings
# writes, imports) whenever they ran on their own, or before their own module-level DB_PATH override was
# applied. conftest.py is imported before any test module, so redirect ``core.db.DB_PATH`` to a throwaway
# location *here*, for the whole session, and fail loudly if the real file is ever modified.
import core.db  # noqa: E402  (importing core.db has no database side effects)

REAL_DB_PATH: Path = Path(core.db.DB_PATH)
_SESSION_TMP = tempfile.TemporaryDirectory(prefix="xarrtools-tests-")
SESSION_DB_PATH: Path = Path(_SESSION_TMP.name) / "xarrtools.db"
core.db.DB_PATH = SESSION_DB_PATH
# Keep the log directory out of the repo too (it defaults to <db dir>/logs).
os.environ.setdefault("XARRTOOLS_LOG_DIR", str(Path(_SESSION_TMP.name) / "logs"))


def _fingerprint(path: Path):
    """Content hash of the real DB (None if it does not exist) used to detect accidental writes."""
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


_REAL_DB_FINGERPRINT = _fingerprint(REAL_DB_PATH)


@pytest.fixture(autouse=True)
def _never_use_real_db():
    """Guarantee every test runs against a temp DB, even a module that resets ``core.db.DB_PATH`` itself.

    Test modules may point ``DB_PATH`` at their own temp file; that is fine. Anything resolving to the real
    database is redirected to the session temp DB before the test runs.
    """
    if Path(core.db.DB_PATH).resolve() == REAL_DB_PATH.resolve():
        core.db.DB_PATH = SESSION_DB_PATH
    yield
    if Path(core.db.DB_PATH).resolve() == REAL_DB_PATH.resolve():
        core.db.DB_PATH = SESSION_DB_PATH


def pytest_sessionfinish(session, exitstatus):
    """Fail the run if the developer's real database changed while the suite ran."""
    if _fingerprint(REAL_DB_PATH) != _REAL_DB_FINGERPRINT:
        session.exitstatus = 1
        print(f"\nERROR: the real database {REAL_DB_PATH} was modified by the test run. "
              "A test is bypassing the temp-DB isolation in tests/conftest.py.")


@pytest.fixture(autouse=True)
def _no_real_tmdb_key():
    """Keep the test suite offline: never pick up a real TMDB key from the developer's local DB/.env.

    Tests that exercise TMDB patch ``core.tmdb.get_api_key`` themselves (an inner patch wins).
    """
    with patch("core.tmdb.get_api_key", return_value=""):
        yield
