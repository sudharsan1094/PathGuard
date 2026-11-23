"""Real Docker checks; skipped only when Docker Desktop or the runner image is unavailable."""

import shutil
import subprocess

import pytest

from core.config import Settings
from core.sandbox import DockerSandbox
from core.verify import verify_patch

pytestmark = pytest.mark.docker
IMAGE = "pathguard-runner"


def _ready() -> bool:
    if not shutil.which("docker"):
        return False
    daemon = subprocess.run(["docker", "info"], capture_output=True, timeout=15)
    image = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, timeout=15)
    return daemon.returncode == 0 and image.returncode == 0


@pytest.fixture
def sandbox(tmp_path):
    if not _ready():
        pytest.skip("Docker daemon and pathguard-runner image are required")
    settings = Settings(target_repos=tmp_path / "targets", docker_image=IMAGE)
    repo = settings.target_repos / "sample"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (repo / "tests" / "test_existing.py").write_text(
        "from calc import add\ndef test_existing():\n    assert add(4, 2) == 6\n")
    return DockerSandbox(settings), repo


def test_verification_pipeline_runs_all_stages_and_preserves_source(sandbox):
    runner, repo = sandbox
    original_files = {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in repo.rglob("*") if path.is_file()
    }
    patch = ("diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n"
             "@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n")
    repro = "from calc import add\ndef test_repro():\n    assert add(2, 3) == 5\n"
    report = verify_patch(runner, str(repo), repro_name="test_repro.py",
                          repro_source=repro, patch=patch)
    assert report.verified, report.model_dump_json(indent=2)
    final_files = {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in repo.rglob("*") if path.is_file()
    }
    assert final_files == original_files


def test_container_has_no_network_and_workspace_is_read_only(sandbox):
    runner, repo = sandbox
    (repo / "test_probe.py").write_text(
        "import os, pytest\ndef test_isolation():\n"
        "    assert os.getuid() == 1000\n"
        "    with pytest.raises(OSError): open('/workspace/probe', 'w')\n"
        "def test_network_is_disabled():\n"
        "    import urllib.request\n"
        "    with pytest.raises(Exception): urllib.request.urlopen('http://example.com', timeout=2)\n")
    assert runner.run_pytest(repo, ["test_probe.py"]).status == "passed"
