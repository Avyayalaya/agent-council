"""OllamaAdapter — drives the local ``ollama`` CLI via async subprocess.

The runtime portability claim (design v0.2 §3.3) needs at least one second
production adapter beyond ``claude_cli``. Ollama is the chosen default for
P2 W4 because:

  1. **Clean stdin contract.** ``ollama run <model>`` reads a prompt from
     stdin and writes the completion to stdout. No interactive TTY,
     no escaped-arg gymnastics, no environment-variable juggling.
  2. **Local + offline.** No API key, no network. Aligned with the cliff-burn
     constraint (no provider lock-in) and with running the bench in a sealed
     environment.
  3. **Model neutrality.** Any locally-pulled model (llama3, mistral, qwen,
     deepseek) works behind the same adapter — that's the point of the
     RuntimeAdapter abstraction.

Invocation pattern (W4): ``ollama run <model>`` piped from stdin/stdout with
UTF-8 explicit on both ends (P29 — Windows + UTF-8 lesson from ClaudeCLIAdapter).
If ``ollama`` is not on PATH, ``health_check()`` returns False and the
orchestrator fails fast.

See ``docs/adapters.md`` for the adapter-choice Decision Memo
(``plan/decision_memo_p2_w4_adapter_choice.md``) explaining why ollama
was picked over ``gh copilot``/``gh models``.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from typing import Iterable

from agent_council.runtimes.base import RuntimeAdapter


class OllamaAdapter(RuntimeAdapter):
    """Adapter that drives the local ``ollama`` CLI via async subprocess.

    Config (from council.yaml#runtime):
        type: ollama
        binary: ollama                 # PATH-resolvable
        model: llama3.1                # passed as positional arg
        flags: []                      # optional extra flags
        invocation_pattern: stdin
        timeout_seconds: 180
    """

    def adapter_name(self) -> str:
        return "ollama"

    def health_check(self) -> bool:
        """Check the binary is on PATH and ``ollama --version`` exits cleanly."""
        binary = self.binary or "ollama"
        if shutil.which(binary) is None:
            return False
        try:
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
        """Invoke ``ollama run <model>`` with the composed prompt over stdin.

        Args:
            prompt: deliberator (or adjudicator) prompt text.
            context: ordered iterable of context blobs (artifact + role
                context); joined with separators by the base class.
            model: optional override; falls back to ``self.default_model``
                and finally to ``"llama3.1"`` as a sensible default.

        Returns:
            Raw model output (stdout) as a UTF-8 string.

        Raises:
            asyncio.TimeoutError: if the call exceeds ``self.timeout_seconds``.
            RuntimeError: on non-zero exit code from the CLI.
        """
        binary = self.binary or "ollama"
        chosen_model = model or self.default_model or "llama3.1"

        # ollama positional args: ``run <model>``. Extra flags from config
        # are appended verbatim (e.g. ``--keepalive 5m``). The model is NOT
        # passed via --model (ollama uses a positional arg).
        args: list[str] = [binary, "run", chosen_model, *self.flags]

        full = self.build_full_prompt(prompt, context)

        # Ensure ProactorEventLoop on Windows (B26 — required for asyncio
        # subprocess on win32; matches ClaudeCLIAdapter pattern).
        if sys.platform == "win32":
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
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            raise

        if proc.returncode != 0:
            err = stderr_b.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"ollama exited with code {proc.returncode}: {err}"
            )

        return stdout_b.decode("utf-8", errors="replace")
