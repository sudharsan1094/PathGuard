from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    target_repos: Path = field(default_factory=lambda: Path(
        os.getenv("PATHGUARD_TARGET_REPOS") or PROJECT_ROOT / "target_repos").resolve())
    docker_image: str = field(default_factory=lambda: os.getenv(
        "PATHGUARD_DOCKER_IMAGE", "pathguard-runner"))
    memory_limit: str = "512m"
    cpu_limit: str = "1"
    pids_limit: int = 128
    default_timeout_s: int = 30
    max_timeout_s: int = 120
    pytest_timeout_s: int = 30
    max_output_bytes: int = 8_000
    max_file_bytes: int = 1_000_000
    max_tool_output_chars: int = 20_000
    max_search_results: int = 50
    max_search_files: int = 10_000
    max_workspace_bytes: int = 100_000_000
    max_workspace_files: int = 20_000
    max_synthesized_file_bytes: int = 100_000
    max_patch_bytes: int = 100_000
    max_patch_files: int = 10

    @property
    def allowed_roots(self) -> tuple[Path, ...]:
        return (self.target_repos,)


def get_settings() -> Settings:
    from dotenv import load_dotenv

    load_dotenv()
    return Settings()
