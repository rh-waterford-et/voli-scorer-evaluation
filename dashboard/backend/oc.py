"""oc command execution for cluster-mutating operations.

The oc binary can be overridden with VOLI_OC_CMD (a script path) so the
builder's apply flow can be tested offline against dashboard/dev/fake_oc.py,
exactly like VOLI_BENCH_CMD does for the benchmark.
"""

import json
import os
import subprocess
import sys


class OcError(RuntimeError):
    pass


def oc_command() -> list[str]:
    override = os.environ.get("VOLI_OC_CMD")
    if not override:
        return ["oc"]
    if override.endswith(".py"):
        # Dev stubs are Python scripts; run them with this interpreter.
        return [sys.executable, override]
    return [override]


def oc_run(args: list[str], timeout: float = 60.0) -> subprocess.CompletedProcess:
    """Run an oc command; raise OcError with stderr detail on failure."""
    command = oc_command() + args
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as error:
        raise OcError(f"oc {' '.join(args[:3])} timed out after {timeout:.0f}s") from error
    except OSError as error:
        raise OcError(f"cannot run {command[0]!r}: {error}") from error
    if completed.returncode:
        detail = completed.stderr.strip()[:400] or f"oc exited {completed.returncode}"
        raise OcError(f"oc {' '.join(args[:3])} failed: {detail}")
    return completed


def oc_json(args: list[str], timeout: float = 60.0) -> dict:
    completed = oc_run(args, timeout)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise OcError(f"oc {' '.join(args[:3])} output was not JSON: {error}") from error
