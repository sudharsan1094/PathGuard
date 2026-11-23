from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from core.config import get_settings
from core.paths import check_relative, validate_repo
from core.sandbox import DockerSandbox
from core.verify import verify_patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TARGET_REPOS = get_settings().target_repos
DOCKER_IMAGE = get_settings().docker_image
MAX_TIMEOUT = get_settings().max_timeout_s
MEMORY_LIMIT = get_settings().memory_limit
CPU_LIMIT = get_settings().cpu_limit
PID_LIMIT = str(get_settings().pids_limit)
mcp = FastMCP("pathguard-sandbox")


def validate_repo_path(repo_path: str) -> Path:
    settings = get_settings()
    repo = validate_repo(repo_path, settings)
    if not repo.is_relative_to(settings.target_repos):
        raise ValueError("Repository must be inside target_repos.")
    return repo


def validate_test_file(repo: Path, test_file: str) -> str:
    rel = check_relative(test_file)
    resolved = (repo.joinpath(*rel.parts)).resolve()
    if not resolved.is_relative_to(repo) or not resolved.is_file():
        raise ValueError("Test file does not exist inside the repository.")
    if resolved.suffix.lower() != ".py":
        raise ValueError("Only Python test files are supported.")
    return resolved.relative_to(repo).as_posix()


def run_docker(repo_path: str, command: list[str], timeout: int = 30) -> dict:
    """Compatibility helper that runs only pytest in an ephemeral, read-only workspace."""
    repo = validate_repo_path(repo_path)
    if not command or Path(command[0]).name.lower() not in {"pytest", "pytest.exe"}:
        raise ValueError("Sandbox commands must invoke pytest.")
    args = command[1:]
    # The old helper accepted pytest argv. Preserve common callers while rejecting shell-like options.
    allowed_value_opts = {"-p", "--timeout"}
    safe_args, targets = [], []
    skip_value = False
    for arg in args:
        if skip_value:
            if arg not in {"no:cacheprovider"} and not arg.startswith("--timeout="):
                raise ValueError("Unsupported pytest option value.")
            safe_args.append(arg)
            skip_value = False
            continue
        if arg in allowed_value_opts:
            safe_args.append(arg)
            skip_value = True
        elif arg.startswith("--timeout=") or arg in {"-x", "-q", "-v", "--tb=short"}:
            safe_args.append(arg)
        elif arg.startswith("-"):
            raise ValueError("Unsupported pytest option.")
        else:
            targets.append(check_relative(arg).as_posix())
    if skip_value:
        raise ValueError("Missing pytest option value.")
    result = DockerSandbox().run_pytest(repo, targets, timeout_s=timeout, extra_args=safe_args)
    return {"success": result.passed, "exit_code": result.exit_code,
            "stdout": result.stdout_tail, "stderr": result.stderr_tail,
            "duration_seconds": round(result.duration_ms / 1000, 3),
            "timed_out": result.status == "timeout", "status": result.status,
            "detail": result.detail}


@mcp.tool()
def run_repro_test(repo_path: str, test_file: str, test_source: str | None = None,
                   patch: str | None = None, timeout_s: int | None = None) -> dict:
    repo = validate_repo_path(repo_path)
    test = validate_test_file(repo, test_file) if test_source is None else check_relative(test_file).as_posix()
    if Path(test).suffix.lower() != ".py":
        raise ValueError("Only Python reproduction tests are supported.")
    files = {test: test_source} if test_source is not None else None
    return DockerSandbox().run_pytest(repo, [test], files=files, patch=patch,
                                      timeout_s=timeout_s).model_dump()


@mcp.tool()
def run_regression_suite(repo_path: str, patch: str | None = None,
                         timeout_s: int | None = None) -> dict:
    validate_repo_path(repo_path)
    return DockerSandbox().run_pytest(repo_path, None, patch=patch,
                                      timeout_s=timeout_s).model_dump()


@mcp.tool()
def apply_patch_dry_run(repo_path: str, patch: str) -> dict:
    validate_repo_path(repo_path)
    return DockerSandbox().dry_run_patch(repo_path, patch)


@mcp.tool()
def verify_candidate_patch(repo_path: str, repro_file: str, repro_source: str,
                           patch: str, timeout_s: int | None = None) -> dict:
    validate_repo_path(repo_path)
    name = check_relative(repro_file).as_posix()
    return verify_patch(DockerSandbox(), repo_path, repro_name=name,
                        repro_source=repro_source, patch=patch,
                        timeout_s=timeout_s).model_dump()


if __name__ == "__main__":
    mcp.run(transport="stdio")
