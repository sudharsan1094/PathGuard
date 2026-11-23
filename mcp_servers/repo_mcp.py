
import os
import re
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TARGET_REPOS = (PROJECT_ROOT / "target_repos").resolve()

MAX_FILE_BYTES = 1_000_000
MAX_OUTPUT_CHARS = 20_000
MAX_SEARCH_RESULTS = 50

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
}

mcp = FastMCP("pathguard-repo")


def validate_repo_path(repo_path: str) -> Path:
    """Allow access only to existing repositories inside target_repos."""

    repo = Path(repo_path).resolve()

    if not repo.is_relative_to(TARGET_REPOS):
        raise ValueError("Repository must be inside target_repos.")

    if not repo.is_dir():
        raise ValueError("Repository directory does not exist.")

    return repo


def validate_relative_file(repo: Path, file_path: str) -> Path:
    """Resolve a file path and prevent traversal outside the repository."""

    requested = Path(file_path)

    if requested.is_absolute():
        raise ValueError("File path must be relative to the repository.")

    resolved = (repo / requested).resolve()

    if not resolved.is_relative_to(repo):
        raise ValueError("File path must remain inside the repository.")

    if not resolved.is_file():
        raise ValueError("File does not exist.")

    return resolved


def validate_git_repo(repo: Path) -> None:
    """Ensure the target directory is a Git working tree."""

    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    if result.returncode != 0 or result.stdout.strip() != "true":
        raise ValueError("Target directory is not a Git repository.")


def run_git(repo: Path, args: list[str]) -> str:
    """Execute a read-only Git command with a timeout."""

    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Git command failed.")

    return result.stdout[:MAX_OUTPUT_CHARS]


@mcp.tool()
def search_files(
    repo_path: str,
    query: str,
    max_results: int = 20,
) -> dict:
    """Search repository text files for a case-insensitive query."""

    repo = validate_repo_path(repo_path)

    if not query.strip():
        raise ValueError("Search query cannot be empty.")

    max_results = max(1, min(max_results, MAX_SEARCH_RESULTS))
    matches = []
    scanned_files = 0

    for root, dirs, files in os.walk(repo, followlinks=False):
        dirs[:] = [
            name for name in dirs
            if name not in EXCLUDED_DIRS
            and not (Path(root) / name).is_symlink()
        ]

        for filename in files:
            file_path = Path(root) / filename

            if file_path.is_symlink():
                continue

            try:
                if file_path.stat().st_size > MAX_FILE_BYTES:
                    continue

                content = file_path.read_text(
                    encoding="utf-8",
                    errors="ignore",
                )
            except (OSError, UnicodeError):
                continue

            scanned_files += 1

            for line_number, line in enumerate(content.splitlines(), start=1):
                if query.casefold() in line.casefold():
                    matches.append({
                        "file": file_path.relative_to(repo).as_posix(),
                        "line": line_number,
                        "text": line.strip()[:500],
                    })

                    if len(matches) >= max_results:
                        return {
                            "query": query,
                            "matches": matches,
                            "scanned_files": scanned_files,
                            "truncated": True,
                        }

    return {
        "query": query,
        "matches": matches,
        "scanned_files": scanned_files,
        "truncated": False,
    }


@mcp.tool()
def read_file(
    repo_path: str,
    file_path: str,
    start_line: int = 1,
    end_line: int = 200,
) -> dict:
    """Read a repository file with line numbers."""

    repo = validate_repo_path(repo_path)
    target = validate_relative_file(repo, file_path)

    if start_line < 1 or end_line < start_line:
        raise ValueError("Invalid line range.")

    if end_line - start_line > 500:
        raise ValueError("Maximum range is 500 lines.")

    if target.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("File exceeds the maximum readable size.")

    lines = target.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines()

    selected = lines[start_line - 1:end_line]

    numbered = [
        f"{line_number}: {line}"
        for line_number, line in enumerate(
            selected,
            start=start_line,
        )
    ]

    return {
        "file": target.relative_to(repo).as_posix(),
        "start_line": start_line,
        "end_line": min(end_line, len(lines)),
        "total_lines": len(lines),
        "content": "\n".join(numbered)[:MAX_OUTPUT_CHARS],
    }


@mcp.tool()
def git_log(
    repo_path: str,
    max_count: int = 10,
) -> dict:
    """Return recent Git commit history."""

    repo = validate_repo_path(repo_path)
    validate_git_repo(repo)

    max_count = max(1, min(max_count, 50))

    output = run_git(
        repo,
        [
            "log",
            f"-{max_count}",
            "--date=iso-strict",
            "--pretty=format:%H%n%an%n%ad%n%s",
        ],
    )

    return {
        "repository": repo.name,
        "commits": output,
    }


@mcp.tool()
def git_diff(
    repo_path: str,
    base: str = "HEAD~1",
    target: str = "HEAD",
) -> dict:
    """Show a diff between two verified Git commits."""

    repo = validate_repo_path(repo_path)
    validate_git_repo(repo)

    def resolve_commit(revision: str) -> str:
        if (
            not revision
            or len(revision) > 100
            or revision.startswith("-")
            or not re.fullmatch(r"[A-Za-z0-9_./~^{}-]+", revision)
        ):
            raise ValueError("Invalid Git revision.")

        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        if result.returncode != 0:
            raise ValueError(f"Git revision not found: {revision}")

        return result.stdout.strip()

    base_commit = resolve_commit(base)
    target_commit = resolve_commit(target)

    output = run_git(
        repo,
        [
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--unified=3",
            base_commit,
            target_commit,
            "--",
        ],
    )

    return {
        "base": base_commit,
        "target": target_commit,
        "diff": output,
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
