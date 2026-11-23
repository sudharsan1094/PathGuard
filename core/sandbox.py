from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, Field

from core.config import Settings, get_settings
from core.paths import check_relative, validate_repo
from core.policy import check_patch, _protected
from core.process import run_bounded

Status = Literal["passed", "failed", "error", "timeout", "no_tests", "patch_rejected"]
_EXCLUDED = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache",
             ".mypy_cache", ".ruff_cache"}


def _ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name.lower() in _EXCLUDED
            or name.lower() == ".env" or name.lower().startswith(".env.")
            or name.lower().endswith(".pyc")}


class SandboxResult(BaseModel):
    status: Status
    exit_code: int | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    duration_ms: int = 0
    truncated: bool = False
    summary: dict[str, int] = Field(default_factory=dict)
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "passed"


def _tail(data: bytes, limit: int) -> tuple[str, bool]:
    cut = len(data) > limit
    text = data[-limit:].decode("utf-8", errors="replace")
    return (("[...truncated...]\n" + text) if cut else text, cut)


def _summary(text: str) -> dict[str, int]:
    import re
    line = text.strip().splitlines()[-1] if text.strip() else ""
    return {("errors" if word.startswith("error") else word): int(count)
            for count, word in re.findall(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)", line)}


def _fingerprint(root: Path) -> dict[str, str]:
    result = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            result[path.relative_to(root).as_posix()] = "SYMLINK"
        elif path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _classify(code: int | None) -> Status:
    if code == 0:
        return "passed"
    if code == 1:
        return "failed"
    if code == 5:
        return "no_tests"
    return "error"


class DockerSandbox:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def run_pytest(self, repo_path: str | Path, targets: list[str] | None = None, *,
                   patch: str | None = None, files: dict[str, str] | None = None,
                   timeout_s: int | None = None, extra_args: list[str] | None = None) -> SandboxResult:
        settings = self.settings
        repo = validate_repo(repo_path, settings)
        clean_targets = [check_relative(t).as_posix() for t in (targets or [])]
        timeout = max(1, min(timeout_s or settings.default_timeout_s, settings.max_timeout_s))
        if patch is not None:
            verdict = check_patch(patch, settings)
            if not verdict.ok:
                return SandboxResult(status="patch_rejected", detail="; ".join(verdict.violations))
        if len(files or {}) > 10:
            return SandboxResult(status="error", detail="Synthesized files exceed configured limits.")
        synthesized_bytes = 0
        for value in (files or {}).values():
            if not isinstance(value, str) or len(value) > settings.max_synthesized_file_bytes:
                return SandboxResult(status="error", detail="Synthesized files exceed configured limits.")
            synthesized_bytes += len(value.encode("utf-8"))
            if synthesized_bytes > settings.max_synthesized_file_bytes:
                return SandboxResult(status="error", detail="Synthesized files exceed configured limits.")
        started = time.perf_counter()
        try:
            with tempfile.TemporaryDirectory(prefix="pathguard-") as temp:
                workspace = Path(temp) / "repo"
                self._copy_repo(repo, workspace)
                self._write_files(workspace, files or {})
                if patch is not None:
                    error = self._apply_patch_checked(workspace, patch)
                    if error:
                        return SandboxResult(status="patch_rejected", detail=error)
                return self._run_container(workspace, clean_targets, extra_args or [], timeout, started)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            return SandboxResult(status="error", duration_ms=int((time.perf_counter() - started) * 1000),
                                 detail=str(error))

    def _copy_repo(self, repo: Path, workspace: Path) -> None:
        total = 0
        count = 0
        for path in repo.rglob("*"):
            lower_parts = [part.lower() for part in path.parts]
            if ".git" in lower_parts or path.name.lower() == ".env" \
                    or path.name.lower().startswith(".env."):
                continue
            if path.is_symlink():
                raise ValueError(f"Repository contains an unsafe symlink: {path.relative_to(repo)}")
            if path.is_file():
                count += 1
                if count > self.settings.max_workspace_files:
                    raise ValueError("Repository contains too many files to sandbox.")
                total += path.stat().st_size
                if total > self.settings.max_workspace_bytes:
                    raise ValueError("Repository is too large to sandbox.")
        shutil.copytree(repo, workspace, ignore=_ignore, symlinks=False)

    @staticmethod
    def _write_files(workspace: Path, files: dict[str, str]) -> None:
        for name, content in files.items():
            rel = check_relative(name)
            if rel.suffix.lower() != ".py" or not (
                    rel.name.lower().startswith("test_")
                    or rel.name.lower().endswith("_test.py")):
                raise ValueError("Synthesized files must use pytest test-file names.")
            destination = workspace.joinpath(*rel.parts)
            if destination.exists() or destination.is_symlink():
                raise ValueError("Synthesized test files must not overwrite repository files.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")

    @staticmethod
    def _apply_patch_checked(workspace: Path, patch: str) -> str:
        before = _fingerprint(workspace)
        applied = run_bounded(["git", "apply", "--whitespace=nowarn", "-"], cwd=workspace,
                              input_data=patch.encode("utf-8"), timeout=20, max_output=4_000)
        if applied.timed_out:
            return "git apply timed out"
        if applied.returncode != 0:
            return _tail(applied.stderr, 2_000)[0].strip() or "git apply failed"
        after = _fingerprint(workspace)
        changed = [name for name in set(before) | set(after) if before.get(name) != after.get(name)]
        for name in changed:
            reason = _protected(PurePosixPath(name))
            if reason:
                return f"policy: {name}: {reason}"
        if any(value == "SYMLINK" for value in after.values()):
            return "policy: patch introduced a symlink"
        return ""

    def dry_run_patch(self, repo_path: str | Path, patch: str) -> dict:
        repo = validate_repo(repo_path, self.settings)
        verdict = check_patch(patch, self.settings)
        if not verdict.ok:
            return {"valid": False, "violations": verdict.violations, "detail": "", "touched_files": verdict.touched_files}
        try:
            with tempfile.TemporaryDirectory(prefix="pathguard-check-") as temp:
                workspace = Path(temp) / "repo"
                self._copy_repo(repo, workspace)
                error = self._apply_patch_checked(workspace, patch)
            return {"valid": not error, "violations": [], "detail": error, "touched_files": verdict.touched_files}
        except (OSError, ValueError) as error:
            return {"valid": False, "violations": [], "detail": str(error), "touched_files": verdict.touched_files}

    def _docker_command(self, name: str, workspace: Path, pytest_args: list[str]) -> list[str]:
        s = self.settings
        return ["docker", "run", "--rm", "--name", name, "--pull", "never",
                "--network", "none", "--memory", s.memory_limit, "--memory-swap", s.memory_limit,
                "--cpus", s.cpu_limit, "--pids-limit", str(s.pids_limit), "--ulimit", "nofile=256:256",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "1000:1000",
                "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "--env", "HOME=/tmp",
                "--mount", f"type=bind,source={workspace},target=/workspace,readonly",
                "--workdir", "/workspace", s.docker_image, "pytest", "-q",
                f"--timeout={s.pytest_timeout_s}", "-p", "no:cacheprovider", *pytest_args]

    def _run_container(self, workspace: Path, targets: list[str], extra: list[str],
                       timeout: int, started: float) -> SandboxResult:
        name = f"pathguard-{uuid.uuid4().hex[:12]}"
        command = self._docker_command(name, workspace, [*extra, *targets])
        try:
            raw = run_bounded(command, timeout=timeout, max_output=self.settings.max_output_bytes)
        except OSError as error:
            return SandboxResult(status="error", detail=f"Could not start Docker: {error}")
        finally:
            # `docker run` can leave its named container alive if the client is killed or fails.
            try:
                cleanup = run_bounded(["docker", "rm", "-f", name], timeout=15, max_output=1_000)
                # A successful --rm run has already removed its container; rm failure is expected.
                _ = cleanup
            except OSError:
                pass
        stdout, cut_out = _tail(raw.stdout, self.settings.max_output_bytes)
        stderr, cut_err = _tail(raw.stderr, self.settings.max_output_bytes)
        duration = int((time.perf_counter() - started) * 1000)
        if raw.timed_out:
            return SandboxResult(status="timeout", stdout_tail=stdout, stderr_tail=stderr,
                                 duration_ms=duration, truncated=(cut_out or cut_err
                                     or raw.stdout_truncated or raw.stderr_truncated),
                                 detail=f"Docker execution exceeded {timeout}s.")
        status = _classify(raw.returncode)
        detail = ""
        if raw.returncode in (125, 126, 127):
            status, detail = "error", "Docker failed to start the container."
        elif raw.returncode == 2:
            detail = "pytest was interrupted or encountered a collection error."
        return SandboxResult(status=status, exit_code=raw.returncode, stdout_tail=stdout,
                             stderr_tail=stderr, duration_ms=duration,
                             truncated=(cut_out or cut_err or raw.stdout_truncated
                                        or raw.stderr_truncated),
                             summary=_summary(raw.stdout.decode("utf-8", errors="replace")), detail=detail)
