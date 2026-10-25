import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def _no_real_tmdb_key():
    """Keep the test suite offline: never pick up a real TMDB key from the developer's local DB/.env.

    Tests that exercise TMDB patch ``core.tmdb.get_api_key`` themselves (an inner patch wins).
    """
    with patch("core.tmdb.get_api_key", return_value=""):
        yield
