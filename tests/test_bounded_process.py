import sys

from core.process import run_bounded


def test_subprocess_output_is_bounded():
    result = run_bounded([sys.executable, "-c", "print('x' * 100000)"],
                         timeout=5, max_output=100)
    assert result.returncode == 0
    assert len(result.stdout) == 100
    assert result.stdout_truncated


def test_subprocess_timeout_is_reported_and_process_stopped():
    result = run_bounded([sys.executable, "-c", "import time; time.sleep(10)"],
                         timeout=0.1, max_output=100)
    assert result.timed_out
    assert result.returncode is None
