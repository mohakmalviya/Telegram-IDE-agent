"""
TEAM_001: Command executor service.
Runs shell commands asynchronously with timeout and output capture.
"""

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Commands that require confirmation before execution
DANGEROUS_PATTERNS = [
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",
    "chmod -R 777 /",
    "shutdown",
    "reboot",
    "init 0",
    "init 6",
    "> /dev/sda",
    "mv /* ",
]


class ExecutionResult:
    """Result of a command execution."""

    def __init__(
        self,
        return_code: int,
        stdout: str,
        stderr: str,
        timed_out: bool = False,
    ) -> None:
        self.return_code = return_code
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out

    @property
    def output(self) -> str:
        """Combined stdout + stderr output."""
        parts = []
        if self.stdout.strip():
            parts.append(self.stdout.strip())
        if self.stderr.strip():
            parts.append(f"[stderr]\n{self.stderr.strip()}")
        if self.timed_out:
            parts.append("⏱️ Command timed out!")
        return "\n".join(parts) if parts else "(no output)"

    @property
    def success(self) -> bool:
        return self.return_code == 0 and not self.timed_out


class Executor:
    """Async shell command executor with timeout and safety checks."""

    def __init__(self, timeout: int = 60) -> None:
        self.timeout = timeout

    def is_dangerous(self, command: str) -> bool:
        """Check if a command matches known dangerous patterns."""
        cmd_lower = command.lower().strip()
        return any(pattern in cmd_lower for pattern in DANGEROUS_PATTERNS)

    async def run(
        self,
        command: str,
        cwd: Path | None = None,
        timeout: int | None = None,
    ) -> ExecutionResult:
        """Execute a shell command asynchronously.

        Args:
            command: The shell command string.
            cwd: Working directory for the command.
            timeout: Override default timeout (seconds).

        Returns:
            ExecutionResult with output and status.
        """
        effective_timeout = timeout or self.timeout
        logger.info("Executing: %s (cwd=%s, timeout=%ds)", command, cwd, effective_timeout)

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd) if cwd else None,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=effective_timeout
                )
                return ExecutionResult(
                    return_code=process.returncode or 0,
                    stdout=stdout_bytes.decode("utf-8", errors="replace"),
                    stderr=stderr_bytes.decode("utf-8", errors="replace"),
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                return ExecutionResult(
                    return_code=-1,
                    stdout="",
                    stderr=f"Command timed out after {effective_timeout}s",
                    timed_out=True,
                )

        except Exception as e:
            logger.exception("Command execution failed: %s", command)
            return ExecutionResult(
                return_code=-1,
                stdout="",
                stderr=str(e),
            )
