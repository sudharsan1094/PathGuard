from __future__ import annotations

import os
import shutil
import sys

import typer
from dotenv import load_dotenv

from core.config import get_settings
from core.process import run_bounded

app = typer.Typer(help="PathGuard V1: execution-verified patch validation.", no_args_is_help=True)


def _ok(command: list[str], timeout: int = 15) -> bool:
    try:
        result = run_bounded(command, timeout=timeout, max_output=2_000)
        return not result.timed_out and result.returncode == 0
    except OSError:
        return False


@app.command()
def doctor() -> None:
    load_dotenv()
    settings = get_settings()
    checks = [
        ("Python >= 3.11", sys.version_info >= (3, 11), sys.version.split()[0]),
        ("Git installed", shutil.which("git") is not None, ""),
        ("Docker installed", shutil.which("docker") is not None, ""),
        ("Docker daemon running", bool(shutil.which("docker") and _ok(["docker", "info"], 20)), ""),
        (f"Runner image '{settings.docker_image}' available",
         bool(shutil.which("docker") and _ok(["docker", "image", "inspect", settings.docker_image])),
         f"docker build -f sandbox/Dockerfile.runner -t {settings.docker_image} ."),
        ("GEMINI_API_KEY set", bool(os.getenv("GEMINI_API_KEY")), "value never printed"),
        ("GEMINI_MODEL set", bool(os.getenv("GEMINI_MODEL")), ""),
        ("target_repos exists", settings.target_repos.is_dir(), str(settings.target_repos)),
    ]
    failed = False
    for name, ok, hint in checks:
        typer.echo(f"[{'ok' if ok else 'FAIL'}] {name}" + (f" ({hint})" if not ok and hint else ""))
        failed |= not ok
    raise typer.Exit(code=1 if failed else 0)


@app.command()
def version() -> None:
    typer.echo("PathGuard V1 0.1.0")


if __name__ == "__main__":
    app()
