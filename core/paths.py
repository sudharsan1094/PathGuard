from __future__ import annotations

from pathlib import Path, PurePosixPath

from core.config import Settings


def validate_repo(repo_path: str | Path, settings: Settings) -> Path:
    repo = Path(repo_path).resolve()
    allowed_root = next((root for root in settings.allowed_roots if repo.is_relative_to(root)), None)
    if allowed_root is None:
        raise ValueError("Repository must be inside an allowed repository or workspace root.")
    if repo == allowed_root:
        raise ValueError("Pass a repository directory, not the allowed root itself.")
    relative_parts = repo.relative_to(allowed_root).parts
    if any(part.lower() == ".git" or part.lower() == ".env"
           or part.lower().startswith(".env.") for part in relative_parts):
        raise ValueError("Repository path points into protected metadata or environment files.")
    if not repo.is_dir():
        raise ValueError("Repository directory does not exist.")
    return repo


def check_relative(value: str | Path) -> PurePosixPath:
    text = str(value).replace("\\", "/")
    if len(text) > 4_096:
        raise ValueError("Path exceeds the maximum supported length.")
    path = PurePosixPath(text)
    if not text.strip() or text.startswith("-") or path.is_absolute() \
            or (len(text) > 1 and text[1] == ":"):
        raise ValueError("Path must be a non-empty relative path.")
    if ".." in path.parts:
        raise ValueError("Path traversal is not allowed.")
    if any(part.lower() == ".git" for part in path.parts):
        raise ValueError("Access to .git is not allowed.")
    if any(part.lower() == ".env" or part.lower().startswith(".env.") for part in path.parts):
        raise ValueError("Access to environment files is not allowed.")
    return path


def resolve_file(repo: Path, value: str | Path) -> Path:
    clean = check_relative(value)
    target = (repo / Path(*clean.parts)).resolve()
    if not target.is_relative_to(repo):
        raise ValueError("Path must remain inside the repository.")
    check_relative(target.relative_to(repo).as_posix())
    if not target.is_file():
        raise ValueError("File does not exist.")
    return target
