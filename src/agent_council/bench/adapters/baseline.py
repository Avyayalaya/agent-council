"""BaselineModeAdapter — single runtime call, no Council.

This is the bench's control arm: invoke the runtime once with the task brief
and return whatever it produced. No critique, no judge, no Council loop. It
sets the floor against which ``unified_judge`` and ``council`` are measured.

Output schema (matches ``Artifact`` contract used by all 3 mode adapters):
    {
      "mode": "baseline",
      "artifact": <raw model output, str>,
      "elapsed_seconds": float,
      "tokens": {"input": int, "output": int, "total": int},
      "synthetic_verdict": None,   # baseline has no judge
      "council_verdict": None,     # baseline has no Council
    }
"""

from __future__ import annotations

import time
from typing import Any

from agent_council.bench.task_brief import TaskBrief
from agent_council.runtimes.base import RuntimeAdapter


class BaselineModeAdapter:
    """One-shot brief-to-artifact mode (no quality gate)."""

    mode_name = "baseline"

    def __init__(self, runtime: RuntimeAdapter, config_dir: Any = None) -> None:
        """Configure the adapter.

        Args:
            runtime: a concrete RuntimeAdapter (mock_cli for W2 tests).
            config_dir: present for API parity with the other mode adapters;
                not used by baseline.
        """
        self.runtime = runtime
        self.config_dir = config_dir

    async def run(self, brief: TaskBrief) -> dict[str, Any]:
        """Invoke the runtime once and wrap the result.

        Args:
            brief: the task brief to send to the runtime.

        Returns:
            Dict matching the standard mode-adapter shape (see module docstring).
        """
        t0 = time.time()
        prompt = _format_baseline_prompt(brief)
        raw = await self.runtime.invoke(prompt=prompt, context=[brief.prompt])
        elapsed = time.time() - t0
        # Token counts are approximate (str-len/4 heuristic) — runtime adapters
        # do not currently expose true counts. The mock returns deterministic
        # strings so this stays stable across runs.
        approx_in = max(1, len(prompt) // 4 + len(brief.prompt) // 4)
        approx_out = max(1, len(raw) // 4)
        return {
            "mode": self.mode_name,
            "artifact": raw,
            "elapsed_seconds": round(elapsed, 4),
            "tokens": {
                "input": approx_in,
                "output": approx_out,
                "total": approx_in + approx_out,
            },
            "synthetic_verdict": None,
            "council_verdict": None,
        }


def _format_baseline_prompt(brief: TaskBrief) -> str:
    """Compose the prompt fed to the runtime for baseline mode."""
    return (
        f"# Bench task — category {brief.category} — {brief.brief_id}\n\n"
        f"Produce a complete response to the task below. No external Council "
        f"review; you are the only respondent.\n\n"
        f"## Task\n\n{brief.prompt}\n"
    )
