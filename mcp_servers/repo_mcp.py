from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from core.config import get_settings
from core.paths import resolve_file, validate_repo
from core import repo_tools

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TARGET_REPOS = get_settings().target_repos
mcp = FastMCP("pathguard-repo")


def validate_repo_path(repo_path: str) -> Path:
    # MCP inspection is intentionally limited to configured target repositories.
    settings = get_settings()
    repo = validate_repo(repo_path, settings)
    if not repo.is_relative_to(settings.target_repos):
        raise ValueError("Repository must be inside target_repos.")
    return repo


def validate_relative_file(repo: Path, file_path: str) -> Path:
    return resolve_file(repo, file_path)


@mcp.tool()
def search_files(repo_path: str, query: str, max_results: int = 20) -> dict:
    validate_repo_path(repo_path)
    return repo_tools.search_files(repo_path, query, max_results)


@mcp.tool()
def read_file(repo_path: str, file_path: str, start_line: int = 1, end_line: int = 200) -> dict:
    validate_repo_path(repo_path)
    return repo_tools.read_file(repo_path, file_path, start_line, end_line)


@mcp.tool()
def git_log(repo_path: str, max_count: int = 10) -> dict:
    validate_repo_path(repo_path)
    return repo_tools.git_log(repo_path, max_count)


@mcp.tool()
def git_diff(repo_path: str, base: str = "HEAD~1", target: str = "HEAD") -> dict:
    validate_repo_path(repo_path)
    return repo_tools.git_diff(repo_path, base, target)


if __name__ == "__main__":
    mcp.run(transport="stdio")
