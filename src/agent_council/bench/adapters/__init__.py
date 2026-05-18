"""Mode adapters for the AgentOS-Bench harness.

Each adapter implements one of the 3 locked bench arms:
    baseline       — single runtime call, no Council
    unified_judge  — single runtime call + 5-criteria synthetic judge prompt
    council        — runtime produces artifact; agent_council.Council adjudicates

The 3 arms are locked per Build Handoff Spec P1 W2 Condition 2 (2026-05-11
amendment). No fourth arm; no silent merging.
"""

from agent_council.bench.adapters.baseline import BaselineModeAdapter
from agent_council.bench.adapters.council import CouncilModeAdapter
from agent_council.bench.adapters.unified_judge import UnifiedJudgeModeAdapter

MODES = {
    "baseline": BaselineModeAdapter,
    "unified_judge": UnifiedJudgeModeAdapter,
    "council": CouncilModeAdapter,
}


def build_mode_adapter(mode: str):
    """Look up the adapter class for ``mode``.

    Args:
        mode: one of ``baseline``, ``unified_judge``, ``council``.

    Returns:
        The adapter *class* (not an instance). Caller instantiates with
        runtime + config_dir.

    Raises:
        ValueError: if mode is not one of the locked 3 arms.
    """
    mode_lower = mode.lower().strip()
    if mode_lower not in MODES:
        raise ValueError(
            f"Unknown bench mode: {mode!r}. "
            f"Locked to 3 arms per P1 W2 Condition 2: {sorted(MODES)}."
        )
    return MODES[mode_lower]


__all__ = [
    "BaselineModeAdapter",
    "UnifiedJudgeModeAdapter",
    "CouncilModeAdapter",
    "MODES",
    "build_mode_adapter",
]
