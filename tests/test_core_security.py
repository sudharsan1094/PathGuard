from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.config import Settings
from core.paths import resolve_file, validate_repo
from core.policy import check_patch
from core.repo_tools import search_files
from core.sandbox import DockerSandbox
from core.process import ProcessResult
from core.verify import verify_patch
from core.sandbox import SandboxResult


@pytest.fixture
def settings(tmp_path):
    roots = tmp_path / "targets"
    repos = roots / "repo"
    repos.mkdir(parents=True)
    return Settings(target_repos=roots), repos


def test_sensitive_paths_and_traversal_are_rejected(settings):
    config, repo = settings
    (repo / ".env.local").write_text("secret")
    (repo / ".git").mkdir()
    with pytest.raises(ValueError):
        resolve_file(repo, ".env.local")
    with pytest.raises(ValueError):
        resolve_file(repo, ".git/config")
    with pytest.raises(ValueError):
        resolve_file(repo, "../outside")
    with pytest.raises(ValueError):
        resolve_file(repo, "-file.py")
    with pytest.raises(ValueError):
        validate_repo(config.target_repos, config)
    with pytest.raises(ValueError):
        validate_repo(repo / ".git", config)


def test_search_and_sandbox_copy_exclude_environment_files_and_git(settings, tmp_path):
    config, repo = settings
    (repo / ".ENV.local").write_text("SECRET_TOKEN")
    (repo / ".env.private").mkdir()
    (repo / ".env.private" / "secret.txt").write_text("SECRET_TOKEN")
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("SECRET_TOKEN")
    assert search_files(str(repo), "SECRET_TOKEN", settings=config)["matches"] == []
    copy = tmp_path / "copy"
    DockerSandbox(config)._copy_repo(repo, copy)
    assert not (copy / ".ENV.local").exists()
    assert not (copy / ".env.private").exists()
    assert not (copy / ".git").exists()


def test_symlink_files_are_not_followed(settings, tmp_path):
    _, repo = settings
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    try:
        (repo / "link.txt").symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation is unavailable on this platform.")
    with pytest.raises(ValueError):
        resolve_file(repo, "link.txt")
    with pytest.raises(ValueError, match="symlink"):
        DockerSandbox(settings[0])._copy_repo(repo, tmp_path / "copy")


def test_patch_policy_rejects_tests_and_dependencies():
    for path in ("tests/test_bug.py", "pyproject.toml", ".env.production", ".git/config",
                 ".GIT/config", ".ENV.production"):
        patch = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+new\n"
        assert not check_patch(patch).ok


def test_patch_policy_accepts_source_change():
    patch = "diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n@@ -1 +1 @@\n-return 1\n+return 2\n"
    assert check_patch(patch).ok


def test_synthesized_test_source_has_a_size_limit(settings):
    config, repo = settings
    result = DockerSandbox(config).run_pytest(repo, ["test_repro.py"],
                                              files={"test_repro.py": "x" * 100_001})
    assert result.status == "error"
    assert "limits" in result.detail


def test_synthesized_files_cannot_overwrite_source_or_existing_tests(settings):
    config, repo = settings
    source = repo / "calc.py"
    source.write_text("def calc(): return 1\n")
    (repo / "test_existing.py").write_text("def test_existing(): pass\n")
    sandbox = DockerSandbox(config)
    with tempfile.TemporaryDirectory() as temp:
        copy = Path(temp) / "copy"
        sandbox._copy_repo(repo, copy)
        with pytest.raises(ValueError, match="test-file names"):
            sandbox._write_files(copy, {"calc.py": "def calc(): return 2\n"})
        with pytest.raises(ValueError, match="must not overwrite"):
            sandbox._write_files(copy, {"test_existing.py": "def test_x(): pass\n"})
        assert (copy / "calc.py").read_text() == "def calc(): return 1\n"


def test_sandbox_marks_subprocess_output_as_truncated(monkeypatch, settings, tmp_path):
    config, _ = settings
    config = Settings(target_repos=config.target_repos, max_output_bytes=10)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[1:3] == ["rm", "-f"]:
            return ProcessResult(returncode=1, stdout=b"", stderr=b"")
        return ProcessResult(returncode=1, stdout=b"x" * 10, stderr=b"", stdout_truncated=True)

    monkeypatch.setattr("core.sandbox.run_bounded", fake_run)
    result = DockerSandbox(config)._run_container(tmp_path, [], [], 10, 0.0)
    assert result.status == "failed"
    assert result.truncated


def test_patch_applies_only_to_temp_copy_and_original_stays_unchanged(settings):
    config, repo = settings
    source = "def calc():\n    return 1\n"
    (repo / "calc.py").write_text(source)
    patch = ("diff --git a/calc.py b/calc.py\n"
             "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def calc():\n-    return 1\n+    return 2\n")
    with tempfile.TemporaryDirectory() as temp:
        workspace = Path(temp) / "copy"
        DockerSandbox(config)._copy_repo(repo, workspace)
        assert DockerSandbox._apply_patch_checked(workspace, patch) == ""
        assert "return 2" in (workspace / "calc.py").read_text()
    assert (repo / "calc.py").read_text() == source


class FakeSandbox:
    def __init__(self, *statuses):
        self.results = [SandboxResult(status=s) for s in statuses]
        self.settings = Settings()
        self.calls = []

    def run_pytest(self, repo, targets=None, **kwargs):
        self.calls.append({"targets": targets, "patch": kwargs.get("patch"), **kwargs})
        return self.results.pop(0)


PATCH = "diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n@@ -1 +1 @@\n-return 1\n+return 2\n"


def test_verification_requires_all_three_execution_stages():
    sandbox = FakeSandbox("failed", "passed", "passed")
    result = verify_patch(sandbox, "repo", repro_name="test_repro.py",
                          repro_source="def test_repro(): assert True\n", patch=PATCH)
    assert result.verified
    assert list(result.steps) == ["repro_before", "repro_after", "regression"]
    assert [call["patch"] is not None for call in sandbox.calls] == [False, True, True]


@pytest.mark.parametrize("statuses", [("passed",), ("error",), ("failed", "failed"),
                                      ("failed", "passed", "failed"),
                                      ("failed", "timeout", "passed")])
def test_verification_never_reports_partial_success(statuses):
    result = verify_patch(FakeSandbox(*statuses), "repo", repro_name="test_repro.py",
                          repro_source="def test_repro(): pass\n", patch=PATCH)
    assert not result.verified


def test_policy_failure_runs_no_tests():
    sandbox = FakeSandbox()
    result = verify_patch(sandbox, "repo", repro_name="test_repro.py",
                          repro_source="", patch=PATCH.replace("calc.py", "tests/test_x.py"))
    assert not result.policy_ok and sandbox.calls == []
