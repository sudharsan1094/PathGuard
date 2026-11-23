from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from core.config import Settings, get_settings
from core.paths import check_relative

_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_FILE = re.compile(r"^(?:---|\+\+\+) (?:a/|b/)?(.+?)(?:\t.*)?$")
_RENAME = re.compile(r"^(?:rename|copy) (?:from|to) (.+)$")
_HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")
_PROTECTED = {"conftest.py", "pytest.ini", "tox.ini", "setup.cfg", "setup.py",
              "pyproject.toml", "poetry.lock", "pipfile", "pipfile.lock",
              "package.json", "package-lock.json", "makefile", "docker-compose.yml",
              "docker-compose.yaml", ".gitignore", ".gitattributes"}
_CI_DIRS = {".github", ".gitlab", ".circleci"}


@dataclass(frozen=True)
class PolicyResult:
    ok: bool
    violations: list[str] = field(default_factory=list)
    touched_files: list[str] = field(default_factory=list)


def extract_touched_files(patch: str) -> list[str]:
    touched: list[str] = []
    old_left = new_left = 0
    for line in patch.splitlines():
        if old_left > 0 or new_left > 0:
            if line.startswith("\\"):
                continue
            if line.startswith("-"):
                old_left -= 1
            elif line.startswith("+"):
                new_left -= 1
            else:
                old_left -= 1
                new_left -= 1
            continue
        hunk = _HUNK.match(line)
        if hunk:
            old_left = int(hunk.group(1) or 1)
            new_left = int(hunk.group(2) or 1)
            continue
        for pattern in (_HEADER, _FILE, _RENAME):
            match = pattern.match(line)
            if match:
                for raw in match.groups():
                    if raw and raw != "/dev/null" and raw not in touched:
                        touched.append(raw)
                break
    return touched


def _protected(path: PurePosixPath) -> str | None:
    lower_parts = [part.lower() for part in path.parts]
    name = path.name.lower()
    if any(part in {"tests", "test", "testing"} for part in lower_parts[:-1]) \
            or name.startswith("test") or name.endswith("_test.py") or name == "conftest.py":
        return "test files cannot be modified by a patch"
    if any(part in _CI_DIRS for part in lower_parts):
        return "CI configuration cannot be modified"
    if name in _PROTECTED or name.startswith(("requirements", "dockerfile")):
        return "build, dependency and tooling files cannot be modified"
    return None


def check_patch(patch: str, settings: Settings | None = None) -> PolicyResult:
    settings = settings or get_settings()
    violations: list[str] = []
    if not patch.strip():
        return PolicyResult(False, ["patch is empty"])
    if len(patch.encode("utf-8", errors="replace")) > settings.max_patch_bytes:
        violations.append("patch exceeds maximum size")
    if "GIT binary patch" in patch or re.search(r"^Binary files ", patch, re.M):
        violations.append("binary changes are not allowed")
    if re.search(r"^(?:new file|deleted file|new|old) mode 120000", patch, re.M):
        violations.append("symlinks are not allowed")
    if re.search(r"^(old|new) mode ", patch, re.M):
        violations.append("file mode changes are not allowed")
    touched = extract_touched_files(patch)
    if not touched:
        violations.append("patch is not a unified diff")
    if len(touched) > settings.max_patch_files:
        violations.append("patch touches too many files")
    for raw in touched:
        try:
            clean = check_relative(raw)
        except ValueError as error:
            violations.append(f"{raw}: {error}")
            continue
        reason = _protected(clean)
        if reason:
            violations.append(f"{raw}: {reason}")
    return PolicyResult(not violations, violations, touched)
