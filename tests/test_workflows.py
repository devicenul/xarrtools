"""Tests for GitHub Actions workflow definitions and referenced repo assets."""
import re
from pathlib import Path
import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = ROOT / ".github" / "workflows"


def test_workflow_files_exist_and_parse_yaml():
    """Verify that CI and Release workflow files exist and parse as valid YAML."""
    ci_path = WORKFLOWS_DIR / "ci.yml"
    release_path = WORKFLOWS_DIR / "release.yml"

    assert ci_path.is_file(), "ci.yml workflow file missing"
    assert release_path.is_file(), "release.yml workflow file missing"

    ci_data = yaml.safe_load(ci_path.read_text(encoding="utf-8"))
    release_data = yaml.safe_load(release_path.read_text(encoding="utf-8"))

    assert isinstance(ci_data, dict)
    assert isinstance(release_data, dict)
    assert "jobs" in ci_data
    assert "jobs" in release_data


def test_workflow_permissions_and_triggers():
    """Verify workflow permissions, triggers, and dry-run dispatch inputs."""
    ci_data = yaml.safe_load((WORKFLOWS_DIR / "ci.yml").read_text(encoding="utf-8"))
    release_data = yaml.safe_load((WORKFLOWS_DIR / "release.yml").read_text(encoding="utf-8"))

    # CI permissions
    assert ci_data.get("permissions") == {"contents": "read"}

    # Release triggers and dry_run dispatch
    on = release_data.get("on") or release_data.get(True)  # PyYAML parses 'on' as True if unquoted
    assert on is not None
    assert "workflow_dispatch" in on
    dispatch = on["workflow_dispatch"]
    assert "dry_run" in dispatch.get("inputs", {})
    assert dispatch["inputs"]["dry_run"]["default"] is True

    # Release permissions
    release_job = release_data["jobs"]["release"]
    assert release_job.get("permissions") == {"contents": "write", "packages": "write"}


def test_release_matrix_targets():
    """Verify binary packaging matrix covers all required OS and architecture targets."""
    release_data = yaml.safe_load((WORKFLOWS_DIR / "release.yml").read_text(encoding="utf-8"))
    binaries_job = release_data["jobs"]["binaries"]
    matrix_includes = binaries_job["strategy"]["matrix"]["include"]

    targets = {entry["target"] for entry in matrix_includes}
    assert targets == {"macos-arm64", "macos-x64", "windows-x64", "linux-x64"}

    # Verify macOS Intel runner label
    intel_entry = next(entry for entry in matrix_includes if entry["target"] == "macos-x64")
    assert intel_entry["os"] == "macos-15-intel"


def test_workflow_referenced_scripts_and_files_exist():
    """Verify that all scripts and files referenced across workflow steps exist on disk."""
    for wf in (WORKFLOWS_DIR / "ci.yml", WORKFLOWS_DIR / "release.yml"):
        content = wf.read_text(encoding="utf-8")
        # Find references to python scripts, text requirements, Dockerfile, package files
        for match in re.findall(r"(?:python\s+([A-Za-z0-9_./-]+\.py)|-r\s+([A-Za-z0-9_.-]+\.txt)|([A-Za-z0-9_.-]+\.json)|(Dockerfile))", content):
            ref = next(group for group in match if group)
            assert (ROOT / ref).exists(), f"Workflow {wf.name} references non-existent file: {ref}"
