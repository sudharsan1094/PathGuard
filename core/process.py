from __future__ import annotations

import os
import subprocess
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessResult:
    returncode: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False


def run_bounded(command: list[str], *, cwd=None, input_data: bytes | None = None,
                timeout: int = 15, max_output: int = 16_000,
                env: dict[str, str] | None = None) -> ProcessResult:
    """Drain child pipes while retaining at most max_output bytes from each stream."""
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(command, cwd=cwd, env=env,
                               stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    collected = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = {"stdout": False, "stderr": False}

    def drain(name: str, stream) -> None:
        while chunk := stream.read(8192):
            data = collected[name]
            if len(data) + len(chunk) > max_output:
                truncated[name] = True
            data.extend(chunk)
            if len(data) > max_output:
                del data[:len(data) - max_output]

    readers = [threading.Thread(target=drain, args=("stdout", process.stdout), daemon=True),
               threading.Thread(target=drain, args=("stderr", process.stderr), daemon=True)]
    for reader in readers:
        reader.start()
    if input_data is not None and process.stdin is not None:
        try:
            process.stdin.write(input_data)
            process.stdin.close()
        except BrokenPipeError:
            pass
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait()
    for reader in readers:
        reader.join()
    return ProcessResult(None if timed_out else process.returncode,
                         bytes(collected["stdout"]), bytes(collected["stderr"]), timed_out,
                         truncated["stdout"], truncated["stderr"])
