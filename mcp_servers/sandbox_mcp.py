
import os
import subprocess
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TARGET_REPOS = (PROJECT_ROOT / "target_repos").resolve()

DOCKER_IMAGE = "bug-agent-runner"

MAX_TIMEOUT = 60
MEMORY_LIMIT = "512m"
CPU_LIMIT = "1"
PID_LIMIT = "128"

mcp = FastMCP("pathguard-sandbox")


def validate_repo_path(repo_path: str) -> Path:
    """Ensure the repository is inside target_repos."""

    path = Path(repo_path).resolve()

    if not path.is_relative_to(TARGET_REPOS):
        raise ValueError("Repository must be inside target_repos.")

    if not path.is_dir():
        raise ValueError("Repository directory does not exist.")

    return path

def validate_test_file(repo: Path, test_file: str) -> str:
    """Validate that a test file exists inside the target repository."""

    requested = Path(test_file)

    if requested.is_absolute():
        raise ValueError("Test path must be relative to the repository.")

    resolved = (repo / requested).resolve()

    if not resolved.is_relative_to(repo):
        raise ValueError("Test file must remain inside the repository.")

    if not resolved.is_file():
        raise ValueError("Test file does not exist.")

    if resolved.suffix.lower() != ".py":
        raise ValueError("Only Python test files are supported.")

    return resolved.relative_to(repo).as_posix()



def run_docker(
    repo_path: str,
    command: list[str],
    timeout: int = 30,
) -> dict:
    """Execute a command inside an isolated Docker container."""

    repo = validate_repo_path(repo_path)
    timeout = max(1, min(timeout, MAX_TIMEOUT))

    docker_command = [
        "docker", "run", "--rm",
        "--network", "none",
        "--memory", MEMORY_LIMIT,
        "--cpus", CPU_LIMIT,
        "--pids-limit", PID_LIMIT,
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
        "--mount",
        f"type=bind,source={repo},target=/workspace,readonly",
        "--workdir", "/workspace",
        DOCKER_IMAGE,
        *command,
    ]

    started = time.perf_counter()

    try:
        result = subprocess.run(
            docker_command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

        return {
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_seconds": round(
                time.perf_counter() - started, 3
            ),
            "timed_out": False,
        }

    except subprocess.TimeoutExpired as error:
        return {
            "success": False,
            "exit_code": None,
            "stdout": error.stdout or "",
            "stderr": error.stderr or "",
            "duration_seconds": round(
                time.perf_counter() - started, 3
            ),
            "timed_out": True,
        }

    except FileNotFoundError:
        raise RuntimeError("Docker executable was not found.")



@mcp.tool()
def run_repro_test(
    repo_path: str,
    test_file: str,
) -> dict:
    """Run one validated reproduction test inside Docker."""

    repo = validate_repo_path(repo_path)
    validated_test = validate_test_file(repo, test_file)

    return run_docker(
        str(repo),
        [
            "pytest",
            "-x",
            "-q",
            validated_test,
            "--timeout=30",
            "-p",
            "no:cacheprovider",
        ],
    )


@mcp.tool()
def run_regression_suite(
    repo_path: str,
) -> dict:
    """Run the repository's complete pytest suite."""

    return run_docker(
        repo_path,
        ["pytest", "-x", "-q",
         "--timeout=30", "-p", "no:cacheprovider"],
    )


@mcp.tool()
def apply_patch_dry_run(
    repo_path: str,
    patch: str,
) -> dict:
    """Validate a patch without modifying the repository."""

    repo = validate_repo_path(repo_path)

    if not patch.strip():
        return {
            "valid": False,
            "error": "Patch is empty.",
        }

    result = subprocess.run(
        ["git", "apply", "--check", "--whitespace=error", "-"],
        input=patch,
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    return {
        "valid": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
