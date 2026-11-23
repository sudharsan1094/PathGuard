from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_demo_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request):
    """Create a fresh demo under a temporary target root for every test."""
    target_repos = tmp_path / "target_repos"
    demo_repo = target_repos / "demo"
    demo_repo.mkdir(parents=True)
    (demo_repo / "test_math.py").write_text(
        "def add(a, b):\n"
        "    return a + b\n"
        "\n"
        "\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n"
        "\n"
        "\n"
        "def test_add_negative():\n"
        "    assert add(-2, 3) == 1\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("PATHGUARD_TARGET_REPOS", str(target_repos))

    # The MCP modules and existing tests expose this value as a module constant.
    from mcp_servers import repo_mcp, sandbox_mcp

    monkeypatch.setattr(repo_mcp, "TARGET_REPOS", target_repos)
    monkeypatch.setattr(sandbox_mcp, "TARGET_REPOS", target_repos)
    monkeypatch.setattr(request.module, "TARGET_REPOS", target_repos, raising=False)
    monkeypatch.setattr(request.module, "DEMO_REPO", demo_repo, raising=False)
    return demo_repo
