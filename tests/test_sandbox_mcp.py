from mcp_servers.sandbox_mcp import validate_test_file
import subprocess

import pytest

from mcp_servers.sandbox_mcp import (
    TARGET_REPOS,
    validate_repo_path,
    run_docker,
)


def test_valid_repository_path():
    repo = validate_repo_path(str(TARGET_REPOS / "demo"))

    assert repo.is_dir()
    assert repo == (TARGET_REPOS / "demo").resolve()


def test_rejects_path_outside_target_repos():
    outside_path = TARGET_REPOS.parent / "README.md"

    with pytest.raises(ValueError):
        validate_repo_path(str(outside_path))


def test_rejects_nonexistent_repository():
    missing = TARGET_REPOS / "does_not_exist"

    with pytest.raises(ValueError):
        validate_repo_path(str(missing))


def test_run_docker_returns_structured_result(monkeypatch):
    expected = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="2 passed",
        stderr="",
    )

    def fake_run(command, **kwargs):
        assert "docker" in command[0]
        assert "--network" in command
        assert "none" in command
        assert "--memory" in command
        assert "--read-only" in command
        return expected

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_docker(
        str(TARGET_REPOS / "demo"),
        ["pytest", "-q"],
    )

    assert result["success"] is True
    assert result["exit_code"] == 0
    assert result["stdout"] == "2 passed"
    assert result["timed_out"] is False


def test_run_docker_reports_timeout(monkeypatch):
    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(
            command,
            timeout=30,
            output="Running tests",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_docker(
        str(TARGET_REPOS / "demo"),
        ["pytest", "-q"],
    )

    assert result["success"] is False
    assert result["timed_out"] is True


def test_accepts_valid_test_file():
    repo = TARGET_REPOS / "demo"

    result = validate_test_file(repo, "test_math.py")

    assert result == "test_math.py"


def test_rejects_path_traversal():
    repo = TARGET_REPOS / "demo"

    with pytest.raises(ValueError):
        validate_test_file(repo, "../../README.md")


def test_rejects_absolute_test_path():
    repo = TARGET_REPOS / "demo"

    with pytest.raises(ValueError):
        validate_test_file(repo, str((repo / "test_math.py").resolve()))


def test_rejects_missing_test_file():
    repo = TARGET_REPOS / "demo"

    with pytest.raises(ValueError):
        validate_test_file(repo, "missing_test.py")


def test_rejects_non_python_file():
    repo = TARGET_REPOS / "demo"

    with pytest.raises(ValueError):
        validate_test_file(repo, "README.md")
