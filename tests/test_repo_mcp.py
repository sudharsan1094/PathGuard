
import pytest

from mcp_servers.repo_mcp import (
    TARGET_REPOS,
    validate_repo_path,
    validate_relative_file,
    search_files,
    read_file,
)


DEMO_REPO = TARGET_REPOS / "demo"


def test_valid_repository_path():
    repo = validate_repo_path(str(DEMO_REPO))
    assert repo == DEMO_REPO.resolve()


def test_rejects_repository_outside_target_repos():
    with pytest.raises(ValueError):
        validate_repo_path(str(TARGET_REPOS.parent))


def test_search_files_finds_function():
    result = search_files(
        str(DEMO_REPO),
        "def add",
    )

    assert len(result["matches"]) >= 1
    assert result["matches"][0]["file"] == "test_math.py"


def test_read_file_returns_numbered_lines():
    result = read_file(
        str(DEMO_REPO),
        "test_math.py",
        1,
        10,
    )

    assert result["total_lines"] > 0
    assert "1:" in result["content"]
    assert "def add" in result["content"]


def test_rejects_path_traversal():
    repo = validate_repo_path(str(DEMO_REPO))

    with pytest.raises(ValueError):
        validate_relative_file(repo, "../../README.md")


def test_rejects_absolute_file_path():
    repo = validate_repo_path(str(DEMO_REPO))

    with pytest.raises(ValueError):
        validate_relative_file(
            repo,
            str((DEMO_REPO / "test_math.py").resolve()),
        )


def test_rejects_empty_search_query():
    with pytest.raises(ValueError):
        search_files(str(DEMO_REPO), "   ")


def test_rejects_invalid_line_range():
    with pytest.raises(ValueError):
        read_file(str(DEMO_REPO), "test_math.py", 10, 1)
