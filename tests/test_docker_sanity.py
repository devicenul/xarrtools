"""Sanity tests for Dockerfile, docker-compose.yml, and container requirements packaging."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_dockerfile_sanity():
    dockerfile_path = ROOT / "Dockerfile"
    assert dockerfile_path.is_file(), "Dockerfile must exist at repo root"
    content = dockerfile_path.read_text(encoding="utf-8")

    # Multi-stage frontend build
    assert "FROM node:20-alpine" in content
    assert "npm run build" in content

    # Python base and non-root user
    assert "FROM python:3.12-slim" in content
    assert "useradd" in content
    assert "USER appuser" in content

    # Environment and volumes
    assert "ENV XARRTOOLS_CONFIG_DIR=/config" in content
    assert "XARRTOOLS_VERSION" in content
    assert "ARG VERSION" in content
    assert "org.opencontainers.image" in content
    assert "VOLUME [\"/config\"]" in content or "VOLUME /config" in content
    assert "EXPOSE 5000" in content

    # Health check on /api/health
    assert "/api/health" in content
    assert "HEALTHCHECK" in content

    # Server mode without browser
    assert "--server" in content
    assert "--no-browser" in content


def test_runtime_dependencies_headless_clean():
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = pyproject["project"]["dependencies"]
    gui_deps = pyproject["project"]["optional-dependencies"]["gui"]

    assert not any("pywebview" in dep for dep in deps), "Runtime dependencies in pyproject.toml must be headless-clean"
    assert any("pywebview" in dep for dep in gui_deps), "gui extra in pyproject.toml must contain pywebview"


def test_docker_compose_sanity():
    compose_path = ROOT / "docker-compose.yml"
    assert compose_path.is_file(), "docker-compose.yml must exist at repo root"
    content = compose_path.read_text(encoding="utf-8")

    assert "5000:5000" in content
    assert "./config:/config" in content
    assert "XARRTOOLS_CONFIG_DIR=/config" in content
    assert "XARRTOOLS_AUTH_USER" in content
    assert "XARRTOOLS_AUTH_PASSWORD" in content


def test_dockerignore_sanity():
    dockerignore_path = ROOT / ".dockerignore"
    assert dockerignore_path.is_file(), ".dockerignore must exist at repo root"
    content = dockerignore_path.read_text(encoding="utf-8")

    for entry in (".git", ".venv", "node_modules", "tests", "*.db"):
        assert entry in content
