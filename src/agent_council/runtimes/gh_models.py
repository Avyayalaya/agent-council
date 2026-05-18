"""GhModelsAdapter — documented fallback to ``gh models run`` (GitHub Models).

**Status: documented stub.** P2 W4 selected ``ollama`` as the second runtime
adapter (see ``plan/decision_memo_p2_w4_adapter_choice.md``) because:

  - The ``gh models`` extension (``github/gh-models``) exposes ``gh models run
    <model>`` which accepts stdin in non-interactive mode, but requires:
      (a) ``gh extension install github/gh-models`` (one-time install)
      (b) GitHub authentication (``gh auth login``) — the user must already
          be authenticated with a token that has access to GitHub Models.
      (c) Subject to GitHub Models rate limits per token.
  - ``gh copilot suggest`` / ``gh copilot explain`` are **interactive-only**
    by design (they print prompts to a TTY and wait for confirmation), so
    they cannot back a Council deliberator call.

This stub exists so the adapter registry can resolve ``type: gh_models``
without crashing — but invocation raises ``NotImplementedError`` until the
adapter is promoted to a real implementation. The skeleton below is the
intended shape; if W5 or later promotes ``gh models`` to a primary adapter,
swap the ``invoke`` body for the ``ollama.py`` pattern with these changes:

    args = [binary, "models", "run", chosen_model, *self.flags]

The rest (stdin pipe, UTF-8, ProactorEventLoop, timeout, exit-code check)
is identical to ``ollama.py``.

Documented per design v0.2 §3.3 (runtime adapter pattern) so future
contributors don't re-discover the trade-off.
"""

from __future__ import annotations

import shutil
from typing import Iterable

from agent_council.runtimes.base import RuntimeAdapter


class GhModelsAdapter(RuntimeAdapter):
    """Stub for ``gh models run`` — promotion path documented in module docstring."""

    def adapter_name(self) -> str:
        return "gh_models"

    def health_check(self) -> bool:
        """Check ``gh`` is on PATH AND the ``gh-models`` extension is installed.

        Conservative: returns False if either is missing. Adopters should
        run ``gh extension install github/gh-models`` once before flipping
        to this adapter in council.yaml.
        """
        binary = self.binary or "gh"
        if shutil.which(binary) is None:
            return False
        try:
            import subprocess

            # ``gh extension list`` exits 0 even when no extensions exist.
            res = subprocess.run(
                [binary, "extension", "list"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if res.returncode != 0:
                return False
            # Look for the gh-models extension in the output.
            return "gh-models" in (res.stdout or "")
        except (subprocess.TimeoutExpired, OSError, ValueError):
            return False

    async def invoke(
        self,
        prompt: str,
        context: Iterable[str],
        model: str | None = None,
    ) -> str:
        """Stub — raises until promoted to a real adapter (see module docstring)."""
        raise NotImplementedError(
            "GhModelsAdapter is a documented fallback stub. "
            "P2 W4 selected OllamaAdapter as the second runtime. "
            "To promote gh_models: implement subprocess invocation following "
            "ollama.py's pattern with args = [binary, 'models', 'run', "
            "chosen_model, *self.flags]. See docs/adapters.md for the choice "
            "rationale."
        )
