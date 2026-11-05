"""ClaudeCLIAdapter — shells out to the ``claude`` CLI binary.

Invocation pattern (v0.1): ``claude --print --model <model>`` via stdin/stdout.
UTF-8 encoding is explicit on both ends (P29 — Windows + PowerShell + UTF-8 lesson).

``health_check()`` is an explicit availability probe. Invocation errors are
reported as runtime failures; no implicit version check or provider call is made.
"""

from __future__ import annotations

import shutil
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
        flags = list(self.flags)
        if model is not None:
            if not model.strip():
                raise ValueError("model override must not be empty")
            kept = []
            index = 0
            while index < len(flags):
                flag = flags[index]
                if flag == "--model":
                    if index + 1 >= len(flags) or flags[index + 1].startswith("-"):
                        raise ValueError("--model in runtime.flags requires a value")
                    index += 2
                elif flag.startswith("--model="):
                    index += 1
                else:
                    kept.append(flag)
                    index += 1
            flags = [*kept, "--model", model]
        elif self.default_model and not any(
            flag == "--model" or flag.startswith("--model=") for flag in flags
        ):
            flags.extend(["--model", self.default_model])
        args: list[str] = [binary, *flags]

        full = self.build_full_prompt(prompt, context)

        return await self.run_subprocess(args, full)
