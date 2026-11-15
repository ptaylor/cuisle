"""A thin subprocess runner that every external tool call goes through."""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(slots=True)
class Result:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_ms: float
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.error is None


class Runner:
    """Run a command with a timeout, never raising for a missing tool or timeout."""

    def run(
        self,
        argv: Sequence[str],
        timeout: float = 10.0,
        input: str | None = None,
        env: dict[str, str] | None = None,
    ) -> Result:
        args = tuple(str(a) for a in argv)
        started = time.perf_counter()
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout,
                input=input,
                env=env,
                check=False,
            )
            return Result(
                argv=args,
                returncode=proc.returncode,
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        except FileNotFoundError:
            return Result(
                argv=args,
                returncode=127,
                stdout="",
                stderr=f"{args[0]}: command not found",
                duration_ms=(time.perf_counter() - started) * 1000,
                error="not found",
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", "replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", "replace")
            return Result(
                argv=args,
                returncode=124,
                stdout=stdout,
                stderr=stderr,
                duration_ms=(time.perf_counter() - started) * 1000,
                error="timeout",
            )
        except OSError as exc:
            return Result(
                argv=args,
                returncode=126,
                stdout="",
                stderr=str(exc),
                duration_ms=(time.perf_counter() - started) * 1000,
                error=str(exc),
            )


def which(tool: str) -> str | None:
    return shutil.which(tool)
