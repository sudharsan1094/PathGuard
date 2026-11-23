from __future__ import annotations

import json
import os
import re
from pathlib import Path

from core.config import Settings, get_settings
from core.paths import resolve_file, validate_repo
from core.process import run_bounded

EXCLUDED_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache"}
_REVISION = re.compile(r"[A-Za-z0-9_./~^{}-]+")


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1", GIT_PAGER="cat", LC_ALL="C")
    return env


def _git(repo: Path, args: list[str], settings: Settings, timeout: int = 15) -> str:
    result = run_bounded(["git", "--no-pager", "-c", "core.fsmonitor=false",
                          "-c", f"core.hooksPath={os.devnull}", *args], cwd=repo,
                         timeout=timeout, max_output=settings.max_tool_output_chars,
                         env=_git_env())
    if result.timed_out:
        raise TimeoutError("Git command timed out.")
    if result.stdout_truncated or result.stderr_truncated:
        raise RuntimeError("Git output exceeded the configured limit; narrow the request.")
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip() or "Git command failed.")
    return result.stdout.decode("utf-8", errors="replace")


def _require_git(repo: Path, settings: Settings) -> None:
    if _git(repo, ["rev-parse", "--is-inside-work-tree"], settings).strip() != "true":
        raise ValueError("Target directory is not a Git repository.")


def search_files(repo_path: str, query: str, max_results: int = 20,
                 settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    repo = validate_repo(repo_path, settings)
    if not query.strip():
        raise ValueError("Search query cannot be empty.")
    if len(query) > 1_000:
        raise ValueError("Search query exceeds the maximum supported length.")
    max_results = max(1, min(max_results, settings.max_search_results))
    matches, scanned = [], 0
    for root, dirs, files in os.walk(repo, followlinks=False):
        dirs[:] = [d for d in dirs if d.lower() not in EXCLUDED_DIRS
                   and d.lower() != ".env" and not d.lower().startswith(".env.")
                   and not (Path(root) / d).is_symlink()]
        for filename in sorted(files):
            path = Path(root) / filename
            if (path.is_symlink() or filename.lower() == ".env"
                    or filename.lower().startswith(".env.")):
                continue
            try:
                if path.stat().st_size > settings.max_file_bytes:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            scanned += 1
            if scanned > settings.max_search_files:
                return {"query": query, "matches": matches, "scanned_files": scanned - 1,
                        "truncated": True}
            for number, line in enumerate(text.splitlines(), 1):
                if query.casefold() in line.casefold():
                    matches.append({"file": path.relative_to(repo).as_posix(), "line": number,
                                    "text": line.strip()[:200]})
                    if len(matches) >= max_results:
                        return _bounded_search_result(query, matches, scanned, True, settings)
    return _bounded_search_result(query, matches, scanned, False, settings)


def _bounded_search_result(query: str, matches: list[dict], scanned: int,
                           truncated: bool, settings: Settings) -> dict:
    result = {"query": query, "matches": matches, "scanned_files": scanned, "truncated": truncated}
    while matches and len(json.dumps(result, ensure_ascii=False)) > settings.max_tool_output_chars:
        matches.pop()
        result["truncated"] = True
    return result


def read_file(repo_path: str, file_path: str, start_line: int = 1, end_line: int = 200,
              settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    repo = validate_repo(repo_path, settings)
    target = resolve_file(repo, file_path)
    if start_line < 1 or end_line < start_line:
        raise ValueError("Invalid line range.")
    if end_line - start_line > 500:
        raise ValueError("Maximum range is 500 lines.")
    if target.stat().st_size > settings.max_file_bytes:
        raise ValueError("File exceeds maximum readable size.")
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    content = "\n".join(f"{n}: {line}" for n, line in enumerate(lines[start_line - 1:end_line], start_line))
    return {"file": target.relative_to(repo).as_posix(), "start_line": start_line,
            "end_line": min(end_line, len(lines)), "total_lines": len(lines),
            "content": content[:settings.max_tool_output_chars]}


def git_log(repo_path: str, max_count: int = 10, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    repo = validate_repo(repo_path, settings)
    _require_git(repo, settings)
    max_count = max(1, min(max_count, 50))
    output = _git(repo, ["log", f"-{max_count}", "--pretty=format:%H%x1f%an%x1f%aI%x1f%s"], settings)
    commits = []
    for line in output.splitlines():
        sha, author, date, subject = (line.split("\x1f") + [""] * 4)[:4]
        commits.append({"sha": sha, "author": author, "date": date, "subject": subject})
    return {"repository": repo.name, "commits": commits}


def _resolve_commit(repo: Path, revision: str, settings: Settings) -> str:
    if not revision or len(revision) > 100 or revision.startswith("-") or not _REVISION.fullmatch(revision):
        raise ValueError("Invalid Git revision.")
    try:
        return _git(repo, ["rev-parse", "--verify", f"{revision}^{{commit}}"], settings).strip()
    except RuntimeError as error:
        raise ValueError(f"Git revision not found: {revision}") from error


def git_diff(repo_path: str, base: str = "HEAD~1", target: str = "HEAD",
             settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    repo = validate_repo(repo_path, settings)
    _require_git(repo, settings)
    base_sha, target_sha = _resolve_commit(repo, base, settings), _resolve_commit(repo, target, settings)
    diff = _git(repo, ["diff", "--no-ext-diff", "--no-textconv", "--unified=3",
                       base_sha, target_sha, "--"], settings)
    return {"base": base_sha, "target": target_sha, "diff": diff}
