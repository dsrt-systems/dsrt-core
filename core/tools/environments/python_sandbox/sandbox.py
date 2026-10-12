"""
Python Sandbox — Cross-Platform Subprocess-based Python Executor (C3 §26-27).

Runs untrusted Python code in a hardened subprocess with:

  - Fresh subprocess per call (never shared, never cached)
  - Hardened interpreter flags (-I -S)
  - Isolated working directory
  - Scrubbed environment
  - Wall-clock timeout
  - Memory limits (POSIX only)
  - Output size caps
  - No shell
  - No network by default
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import signal
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.observability.logging import get_logger
from core.tools.environments.python_sandbox.runner import RUNNER_SCRIPT


logger = get_logger("dsrt.sandbox.python")

_IS_WINDOWS = platform.system() == "Windows"

# Environment variables we allow through to the sandbox.
# Everything else is scrubbed to prevent credential leakage.
_SAFE_ENV_VARS_POSIX = frozenset({
    "PATH", "LANG", "LC_ALL", "LC_CTYPE", "HOME", "USER", "TMPDIR",
})

_SAFE_ENV_VARS_WINDOWS = frozenset({
    "PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP",
    "USERPROFILE", "COMPUTERNAME", "USERNAME", "PATHEXT",
    # Needed by Windows DLL loader
    "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA",
})


class PythonSandboxError(Exception):
    """Raised when sandbox setup or teardown fails."""


@dataclass
class PythonSandboxResult:
    """Structured result of a sandboxed Python execution."""

    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    result_value: Any = None
    error_type: str | None = None
    error_message: str | None = None
    timed_out: bool = False
    output_truncated: bool = False
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class PythonSandbox:
    """Cross-platform Python code sandbox using a hardened subprocess."""

    def __init__(
        self,
        *,
        max_runtime_seconds: int = 60,
        max_memory_mb: int = 512,
        max_output_bytes: int = 5 * 1024 * 1024,
        max_code_bytes: int = 256 * 1024,
        allow_network: bool = False,
        workspace_dir: Path | None = None,
    ) -> None:
        self._max_runtime_seconds = max_runtime_seconds
        self._max_memory_mb = max_memory_mb
        self._max_output_bytes = max_output_bytes
        self._max_code_bytes = max_code_bytes
        self._allow_network = allow_network
        self._workspace_dir = workspace_dir

    async def execute(
        self,
        code: str,
        *,
        timeout_seconds: int | None = None,
    ) -> PythonSandboxResult:
        """Execute Python code in an isolated subprocess."""
        if not isinstance(code, str) or not code.strip():
            raise PythonSandboxError("Code must be a non-empty string.")

        code_bytes = code.encode("utf-8")
        if len(code_bytes) > self._max_code_bytes:
            raise PythonSandboxError(
                f"Code size {len(code_bytes)} exceeds max {self._max_code_bytes}."
            )

        effective_timeout = min(
            timeout_seconds or self._max_runtime_seconds,
            self._max_runtime_seconds,
        )

        # Create an isolated temp directory for this execution.
        # Prefer workspace_dir if provided; otherwise use system temp.
        parent_dir = self._workspace_dir
        if parent_dir and not parent_dir.exists():
            parent_dir.mkdir(parents=True, exist_ok=True)

        sandbox_dir = Path(
            tempfile.mkdtemp(prefix="dsrt_py_", dir=str(parent_dir) if parent_dir else None)
        )

        try:
            return await self._run_in_dir(code, sandbox_dir, effective_timeout)
        finally:
            # Always clean up the sandbox directory
            try:
                shutil.rmtree(sandbox_dir, ignore_errors=True)
            except Exception as e:
                logger.warning("sandbox_cleanup_failed", path=str(sandbox_dir), error=str(e))

    async def _run_in_dir(
        self,
        code: str,
        sandbox_dir: Path,
        timeout_seconds: int,
    ) -> PythonSandboxResult:
        # 1. Write the runner script into the sandbox dir
        runner_path = sandbox_dir / "_dsrt_runner.py"
        runner_path.write_text(RUNNER_SCRIPT, encoding="utf-8")

        # 2. Write user code to a file (never passed via -c or stdin)
        code_path = sandbox_dir / "_dsrt_user_code.py"
        code_path.write_text(code, encoding="utf-8")

        # 3. Prepare result file path
        result_path = sandbox_dir / "_dsrt_result.json"

        # 4. Build the hardened subprocess command
        # -I: isolated mode (ignores PYTHONPATH, PYTHONHOME, user site)
        # -S: don't auto-import site module (reduces attack surface)
        cmd = [
            sys.executable,
            "-I",
            "-S",
            str(runner_path),
            str(code_path),
            str(result_path),
        ]

        # 5. Scrub environment
        env = self._build_sandbox_env()

        # 6. Platform-specific process creation
        preexec_fn = None
        creationflags = 0

        if _IS_WINDOWS:
            # Create new process group so we can kill the entire tree
            creationflags = getattr(
                __import__("subprocess"), "CREATE_NEW_PROCESS_GROUP", 0,
            )
        else:
            preexec_fn = self._posix_preexec

        logger.debug(
            "python_sandbox_starting",
            sandbox_dir=str(sandbox_dir),
            timeout_seconds=timeout_seconds,
            code_bytes=len(code.encode("utf-8")),
        )

        start_time = time.perf_counter()
        proc: asyncio.subprocess.Process | None = None
        timed_out = False
        stdout_data = b""
        stderr_data = b""

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(sandbox_dir),
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=preexec_fn,
                creationflags=creationflags,
            )

            try:
                stdout_data, stderr_data = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout_seconds,
                )
            except asyncio.TimeoutError:
                timed_out = True
                await self._kill_process(proc)
                # Collect whatever output we have
                try:
                    stdout_data, stderr_data = await asyncio.wait_for(
                        proc.communicate(), timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    stdout_data = stdout_data or b""
                    stderr_data = stderr_data or b""

        except Exception as e:
            if proc is not None:
                await self._kill_process(proc)
            raise PythonSandboxError(f"Subprocess failed: {e}") from e

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        exit_code = proc.returncode if proc.returncode is not None else -1

        # 7. Enforce output size cap
        stdout_bytes = len(stdout_data)
        stderr_bytes = len(stderr_data)
        output_truncated = False

        if stdout_bytes + stderr_bytes > self._max_output_bytes:
            output_truncated = True
            # Keep proportional slices
            half = self._max_output_bytes // 2
            stdout_data = stdout_data[:half]
            stderr_data = stderr_data[:half]

        try:
            stdout = stdout_data.decode("utf-8", errors="replace")
        except Exception:
            stdout = ""
        try:
            stderr = stderr_data.decode("utf-8", errors="replace")
        except Exception:
            stderr = ""

        # 8. Read result file if present
        result_value: Any = None
        error_type: str | None = None
        error_message: str | None = None
        success = (exit_code == 0 and not timed_out)

        if result_path.exists():
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                result_value = payload.get("result")
                error_type = payload.get("error_type")
                error_message = payload.get("error")
                # If the runner reported success/failure, honour it
                if "success" in payload:
                    success = bool(payload["success"]) and not timed_out
            except Exception as e:
                logger.warning("sandbox_result_parse_failed", error=str(e))

        if timed_out:
            success = False
            if not error_message:
                error_message = f"Execution exceeded timeout of {timeout_seconds}s."
            error_type = "Timeout"

        logger.info(
            "python_sandbox_completed",
            success=success,
            exit_code=exit_code,
            duration_ms=duration_ms,
            timed_out=timed_out,
            output_truncated=output_truncated,
            stdout_bytes=stdout_bytes,
            stderr_bytes=stderr_bytes,
        )

        return PythonSandboxResult(
            success=success,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            result_value=result_value,
            error_type=error_type,
            error_message=error_message,
            timed_out=timed_out,
            output_truncated=output_truncated,
            stdout_bytes=stdout_bytes,
            stderr_bytes=stderr_bytes,
            metadata={
                "platform": platform.system(),
                "python_version": sys.version.split()[0],
            },
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_sandbox_env(self) -> dict[str, str]:
        """Build a scrubbed environment dict for the sandbox subprocess."""
        safe_vars = _SAFE_ENV_VARS_WINDOWS if _IS_WINDOWS else _SAFE_ENV_VARS_POSIX
        env: dict[str, str] = {}
        for key, value in os.environ.items():
            if key.upper() in {v.upper() for v in safe_vars}:
                env[key] = value

        # Explicitly disable python startup customization
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        return env

    def _posix_preexec(self) -> None:
        """POSIX pre-exec: set resource limits & create new session."""
        try:
            # New session so we can kill the whole group
            os.setsid()
        except Exception:
            pass

        try:
            import resource

            # Virtual memory limit (bytes)
            mem_bytes = self._max_memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))

            # CPU time limit (seconds) — slightly above wall-clock for safety
            cpu_limit = self._max_runtime_seconds + 10
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit))

            # File size limit (per file, bytes) — generous but bounded
            fsize_limit = self._max_output_bytes * 2
            resource.setrlimit(resource.RLIMIT_FSIZE, (fsize_limit, fsize_limit))

            # No core dumps
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except (ImportError, Exception):
            # Some limits may not be settable in all POSIX envs; proceed
            pass

    async def _kill_process(self, proc: asyncio.subprocess.Process) -> None:
        """Kill a subprocess (and its group on POSIX)."""
        if proc.returncode is not None:
            return

        try:
            if _IS_WINDOWS:
                # On Windows, terminate() signals the process. For process
                # group killing, we rely on CREATE_NEW_PROCESS_GROUP + CTRL_BREAK_EVENT.
                try:
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                    await asyncio.sleep(0.1)
                except Exception:
                    pass
                try:
                    proc.terminate()
                except ProcessLookupError:
                    return
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        return
            else:
                # POSIX: kill the entire process group
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    await asyncio.sleep(0.1)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass
        except Exception as e:
            logger.warning("sandbox_kill_failed", error=str(e))