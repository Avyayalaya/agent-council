"""CouncilModeAdapter — two-stage: runtime produces artifact, Council adjudicates.

Stage 1: invoke the runtime once with the task brief. This yields the artifact
to be reviewed (same as the baseline arm).
Stage 2: write the artifact to a temp file, pass it through
``agent_council.orchestrator.Council`` for the 5-deliberator 2-round protocol,
and return the resulting verdict alongside the artifact.

Hard safety rail (RW2-4 mitigation): if the underlying runtime is NOT
``mock_cli`` and the environment variable ``AGENT_COUNCIL_BENCH_REAL_OK`` is
unset, the adapter refuses to run. Bench arms never accidentally hit real
``claude_cli`` during W2 self-tests.

Output schema (matches ``Artifact`` contract):
    {
      "mode": "council",
      "artifact": <raw model output, str>,
      "elapsed_seconds": float,
      "tokens": {...},
      "synthetic_verdict": None,
      "council_verdict": {
        "verdict": "SHIP" | "REVISE" | "HOLD" | "INCOMPLETE",
        "reasoning": str,
        "revision_brief": str | None,
        "deliberators": {...},
      },
    }
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from agent_council.bench.task_brief import TaskBrief
from agent_council.orchestrator import Council
from agent_council.runtimes.base import RuntimeAdapter


REAL_RUNTIME_ENV = "AGENT_COUNCIL_BENCH_REAL_OK"


class CouncilModeAdapter:
    """Two-stage adapter: produce artifact, then run Council adjudication."""

    mode_name = "council"

    def __init__(
        self,
        runtime: RuntimeAdapter,
        config_dir: Path | str | None = None,
        council_config: dict[str, Any] | None = None,
    ) -> None:
        """Configure the adapter.

        Args:
            runtime: a concrete RuntimeAdapter for artifact production.
            config_dir: directory where ``council.yaml`` and prompts resolve.
                Defaults to the test ``council.example.yaml`` directory.
            council_config: optional pre-loaded council config dict. If None,
                the adapter expects ``config_dir`` to contain a usable
                ``council.example.yaml`` or compatible file (loaded lazily).

        Raises:
            RuntimeError: if a non-mock runtime is used without the explicit
                ``AGENT_COUNCIL_BENCH_REAL_OK`` env override.
        """
        adapter_name = runtime.adapter_name()
        if adapter_name != "mock_cli" and not os.environ.get(REAL_RUNTIME_ENV):
            raise RuntimeError(
                f"CouncilModeAdapter refuses to run with runtime {adapter_name!r} "
                f"without {REAL_RUNTIME_ENV}=1. W2 bench must use mock_cli; real "
                f"runs are W3 work and require explicit authorization."
            )
        self.runtime = runtime
        self.config_dir = Path(config_dir) if config_dir else None
        self.council_config = council_config

    async def run(self, brief: TaskBrief) -> dict[str, Any]:
        """Produce the artifact, then adjudicate it via Council.

        Args:
            brief: the task brief.

        Returns:
            Dict matching the standard mode-adapter shape.
        """
        t0 = time.time()
        artifact_prompt = (
            f"# Bench task — category {brief.category} — {brief.brief_id}\n\n"
            f"Produce an artifact for the task below. It will be reviewed by "
            f"a 5-agent Council afterward.\n\n"
            f"## Task\n\n{brief.prompt}\n"
        )
        artifact_text = await self.runtime.invoke(
            prompt=artifact_prompt, context=[brief.prompt]
        )

        # Stage 2: write artifact to a temp file and run Council against it.
        council_verdict = await self._adjudicate(artifact_text, tier=1)
        elapsed = time.time() - t0

        approx_in = max(1, len(artifact_prompt) // 4 + len(brief.prompt) // 4)
        approx_out = max(1, len(artifact_text) // 4)
        return {
            "mode": self.mode_name,
            "artifact": artifact_text,
            "elapsed_seconds": round(elapsed, 4),
            "tokens": {
                "input": approx_in,
                "output": approx_out,
                "total": approx_in + approx_out,
            },
            "synthetic_verdict": None,
            "council_verdict": council_verdict,
        }

    # ------------------------------------------------------------------
    # Stage 2: Council adjudication
    # ------------------------------------------------------------------
    async def _adjudicate(self, artifact_text: str, tier: int) -> dict[str, Any]:
        """Write artifact to a temp file and run the Council on it."""
        config = self._resolve_council_config()
        if config is None:
            # Cannot find a council config — surface as INCOMPLETE rather than
            # crashing the whole bench run.
            return {
                "verdict": "INCOMPLETE",
                "reasoning": (
                    "CouncilModeAdapter could not locate a council config; "
                    "bench scaffold is expected to ship one alongside the test."
                ),
                "revision_brief": None,
                "deliberators": {},
            }

        # Write artifact to a temp file. Council reads from a path.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".md",
            delete=False,
        ) as tf:
            tf.write(artifact_text)
            artifact_path = Path(tf.name)

        try:
            council = Council(
                config=config,
                config_dir=self.config_dir or artifact_path.parent,
            )
            verdict = await council.run(artifact_path, tier=tier)
            return {
                "verdict": verdict.verdict,
                "reasoning": verdict.reasoning,
                "revision_brief": verdict.revision_brief,
                "deliberators": {
                    role: {
                        "r1_score": r.r1_score,
                        "r2_score": r.r2_score,
                        "r2_would_block": r.r2_would_block,
                        "r2_irreducible": r.r2_irreducible,
                    }
                    for role, r in verdict.deliberators.items()
                },
            }
        finally:
            try:
                artifact_path.unlink(missing_ok=True)
            except OSError:
                # Best-effort cleanup; don't mask a real bench error.
                pass

    def _resolve_council_config(self) -> dict[str, Any] | None:
        """Return the council config dict, loading from disk if needed."""
        if self.council_config is not None:
            return self.council_config
        # Try the test fixture path first; it ships with the repo.
        from agent_council.config import load_config  # local import — stays modular.

        candidates: list[Path] = []
        if self.config_dir:
            candidates.append(self.config_dir / "council.example.yaml")
        # Project tests/ has the canonical mock_cli config.
        here = Path(__file__).resolve()
        project_root = here.parents[4]
        candidates.append(project_root / "tests" / "council.example.yaml")
        for c in candidates:
            if c.exists():
                self.config_dir = c.parent
                self.council_config = load_config(c)
                return self.council_config
        return None
