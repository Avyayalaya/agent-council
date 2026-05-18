"""ClaudeCLIAdapter — shells out to the ``claude`` CLI binary.

Invocation pattern (v0.1): ``claude --print --model <model>`` via stdin/stdout.
UTF-8 encoding is explicit on both ends (P29 — Windows + PowerShell + UTF-8 lesson).

If ``claude`` is not on PATH, ``health_check()`` returns False and the orchestrator
will fail fast with a clear message before any deliberator call is made.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from typing import Iterable

from agent_council.runtimes.base import RuntimeAdapter


class ClaudeCLIAdapter(RuntimeAdapter):
    """Adapter that drives the ``claude`` CLI via async subprocess."""

    def adapter_name(self) -> str:
        return "claude_cli"

    def health_check(self) -> bool:
        """Check the binary is on PATH and ``--version`` exits cleanly."""
        binary = self.binary or "claude"
        if shutil.which(binary) is None:
            return False
        try:
            # Synchronous version check — cheap and Windows-safe.
            import subprocess

            res = subprocess.run(
                [binary, "--version"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return res.returncode == 0
        except (subprocess.TimeoutExpired, OSError, ValueError):
            return False

    async def invoke(
        self,
        prompt: str,
        context: Iterable[str],
        model: str | None = None,
    ) -> str:
        """Invoke ``claude --print --model <model>`` with the composed prompt.

        Raises:
            asyncio.TimeoutError: if the call exceeds ``self.timeout_seconds``.
            RuntimeError: on non-zero exit code from the CLI.
        """
        binary = self.binary or "claude"
        chosen_model = model or self.default_model
        # Build CLI args: respect declared flags, append --model if not present.
        args: list[str] = [binary, *self.flags]
        if chosen_model and not any(f.startswith("--model") for f in self.flags):
            args.extend(["--model", chosen_model])

        full = self.build_full_prompt(prompt, context)

        # Ensure ProactorEventLoop on Windows (required for asyncio subprocess).
        if sys.platform == "win32":
            # asyncio in Python 3.10+ defaults to Proactor on Windows already,
            # but explicit is better than implicit per RP0-2.
            try:
                asyncio.get_event_loop_policy()
            except RuntimeError:
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(full.encode("utf-8")),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            # Best-effort kill — let the OS reap the process.
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            raise

        if proc.returncode != 0:
            err = stderr_b.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"claude CLI exited with code {proc.returncode}: {err}"
            )

        return stdout_b.decode("utf-8", errors="replace")
