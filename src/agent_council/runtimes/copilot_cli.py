"""CopilotCLIAdapter — shells out to the GitHub ``copilot`` CLI binary.

Invocation pattern (v0.1): ``copilot -p <prompt>`` with the composed prompt
passed as the **final argument** (Copilot reads the prompt from an argument via
``-p/--prompt``, not from stdin — this differs from ClaudeCLIAdapter and
OllamaAdapter, which pipe the prompt over stdin). ``stdin`` is closed
(``DEVNULL``) so a deliberator call can never block waiting for a TTY.

Why args, not stdin: a live probe of ``copilot -p "..." -s`` confirmed the prompt
is accepted as an argument, ``-s/--silent`` yields clean stdout (only the model
answer, no banner/stats), and pure-text prompts complete without triggering an
interactive tool-permission prompt. ``create_subprocess_exec`` (no shell) makes
newlines and quotes inside the prompt arg safe.

Recommended flags (set in ``council.yaml#runtime.flags``):
    -s                        clean, script-friendly output
    --no-color                strip ANSI so stdout is plain text
    --no-custom-instructions  CRITICAL — otherwise the repo's AGENTS.md (which
                              describes the Council itself) is injected into
                              every deliberator call and pollutes critiques
    --disable-builtin-mcps    avoid MCP startup latency
    --allow-all-tools         Copilot's documented requirement for
                              non-interactive mode; guarantees no TTY block

If ``copilot`` is not on PATH, ``health_check()`` returns False and the
orchestrator fails fast with a clear message before any deliberator call.

UTF-8 encoding is explicit on decode (P29 — Windows + UTF-8 lesson). The Windows
Proactor event-loop guard matches the other subprocess adapters.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from typing import Iterable

from agent_council.runtimes.base import RuntimeAdapter


class CopilotCLIAdapter(RuntimeAdapter):
    """Adapter that drives the GitHub ``copilot`` CLI via async subprocess.

    Config (from council.yaml#runtime):
        type: copilot_cli
        binary: copilot                    # PATH-resolvable
        model: auto                        # "auto" lets Copilot pick; or a model id
        flags: [-s, --no-color, --no-custom-instructions,
                --disable-builtin-mcps, --allow-all-tools]
        invocation_pattern: args           # prompt is passed via -p, not stdin
        timeout_seconds: 600               # each call is a full agent turn
    """

    def adapter_name(self) -> str:
        return "copilot_cli"

    def health_check(self) -> bool:
        """Check the binary is on PATH and ``copilot --version`` exits cleanly."""
        binary = self.binary or "copilot"
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
        """Invoke ``copilot -p <prompt>`` with the composed prompt as an arg.

        Args:
            prompt: deliberator (or adjudicator) prompt text.
            context: ordered iterable of context blobs (artifact + role
                context); joined with separators by the base class.
            model: optional override; falls back to ``self.default_model``.

        Returns:
            Raw model output (stdout) as a UTF-8 string. With ``-s`` in flags
            this is already the bare answer, so no post-processing is applied.

        Raises:
            asyncio.TimeoutError: if the call exceeds ``self.timeout_seconds``.
            RuntimeError: on non-zero exit code from the CLI.
        """
        binary = self.binary or "copilot"
        chosen_model = model or self.default_model

        # Build CLI args: declared flags first, then --model (only if a model is
        # set and not already declared in flags), then -p <prompt> LAST so the
        # composed prompt is unambiguously the final positional argument.
        args: list[str] = [binary, *self.flags]
        if chosen_model and not any(f.startswith("--model") for f in self.flags):
            args.extend(["--model", chosen_model])

        full = self.build_full_prompt(prompt, context)
        args.extend(["-p", full])

        # Ensure ProactorEventLoop on Windows (required for asyncio subprocess;
        # matches ClaudeCLIAdapter / OllamaAdapter pattern).
        if sys.platform == "win32":
            try:
                asyncio.get_event_loop_policy()
            except RuntimeError:
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

        # stdin=DEVNULL: the prompt is an arg, and closing stdin guarantees the
        # subprocess never blocks trying to read from a TTY in non-interactive use.
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(),
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
                f"copilot CLI exited with code {proc.returncode}: {err}"
            )

        return stdout_b.decode("utf-8", errors="replace")
