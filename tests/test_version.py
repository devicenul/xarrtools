"""Tests for application version resolution, overrides, and health reporting."""
import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from web.server import app
import core.version


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_default_version():
    """Default version is 0.0.0-dev in development environments without overrides."""
    with patch.dict(os.environ, {}, clear=True):
        # Remove XARRTOOLS_VERSION if present
        os.environ.pop("XARRTOOLS_VERSION", None)
        importlib.reload(core.version)
        assert core.version.__version__ == "0.0.0-dev"


def test_version_env_var_override():
    """XARRTOOLS_VERSION environment variable overrides default version."""
    with patch.dict(os.environ, {"XARRTOOLS_VERSION": "1.2.3"}):
        importlib.reload(core.version)
        assert core.version.__version__ == "1.2.3"
    # Reset
    importlib.reload(core.version)


def test_stamped_release_version(tmp_path):
    """core/_version.py stamped version takes effect when no env var is present."""
    version_file = Path(core.version.__file__).parent / "_version.py"
    try:
        version_file.write_text('__version__ = "2.0.0"\n', encoding="utf-8")
        sys.modules.pop("core._version", None)
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("XARRTOOLS_VERSION", None)
            importlib.reload(core.version)
            assert core.version.__version__ == "2.0.0"
    finally:
        if version_file.exists():
            version_file.unlink()
        sys.modules.pop("core._version", None)
        importlib.reload(core.version)


def test_health_api_reports_version(client):
    """GET /api/health exposes the active version string."""
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["version"] == core.version.__version__


def test_frontend_system_version():
    """Verify loadSystemVersion populates stat-app-version with health API version."""
    if shutil.which("node") is None:
        pytest.skip("Node not available")
    dist_settings_ui = Path(__file__).resolve().parent.parent / "web" / "static" / "dist" / "settings-ui.js"
    if not dist_settings_ui.is_file():
        pytest.skip("web/static/dist/settings-ui.js missing; build frontend first")
    code = f"""
    const element = {{ textContent: "" }};
    globalThis.document = {{
      getElementById: (id) => (id === "stat-app-version" ? element : null)
    }};
    globalThis.fetch = async (url) => {{
      if (url === "/api/health") {{
        return {{ ok: true, json: async () => ({{ status: "ok", version: "9.8.7" }}) }};
      }}
      return {{ ok: false, json: async () => ({{}}) }};
    }};
    import({json.dumps(dist_settings_ui.as_uri())}).then(async (m) => {{
      await m.loadSystemVersion();
      console.log(JSON.stringify({{ textContent: element.textContent }}));
    }}).catch(err => {{
      console.error(err);
      process.exit(1);
    }});
    """
    out = subprocess.run(["node", "--input-type=module", "-e", code], capture_output=True, text=True, timeout=10)
    assert out.returncode == 0, f"Error: {out.stderr}"
    data = json.loads(out.stdout.strip().splitlines()[-1])
    assert data["textContent"] == "9.8.7"

