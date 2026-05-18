"""Verdict dataclass + SHIP/REVISE/HOLD policy engine.

The policy is data-driven from ``council.yaml#adjudicator.verdict_policy``:
    ship:   "0 deliberators set would_block:true after R2"
    revise: "1-2 would_block AND no 'irreducible' flag"
    hold:   "3+ would_block OR any 'irreducible' flag"

The Adjudicator's own verdict (from its synthesis output) is normally trusted,
but `VerdictPolicy.apply` recomputes from raw deliberator flags so a buggy
Adjudicator can't silently SHIP an artifact 3 deliberators wanted held.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


# Exit codes — documented in AGENTS.md and README.md.
EXIT_SHIP = 0
EXIT_REVISE = 1
EXIT_HOLD = 2
EXIT_INCOMPLETE = 3
EXIT_NOT_FOUND = 4


@dataclass
class DeliberatorResult:
    """One deliberator's R1 + R2 contribution to the verdict.

    R1 fields come from the round-1 critique; R2 fields come from the
    round-2 rebuttal after cross-read. The R2 values take precedence in
    verdict calculation.
    """

    role: str
    r1_score: int | None = None
    r1_would_block: bool = False
    r2_score: int | None = None
    r2_would_block: bool = False
    r2_irreducible: bool = False
    top_issues: list[str] = field(default_factory=list)
    raw_r1: dict[str, Any] | None = None
    raw_r2: dict[str, Any] | None = None
    error: str | None = None  # populated if this deliberator failed

    @property
    def succeeded(self) -> bool:
        """True if the deliberator produced a parseable R1 critique."""
        return self.error is None and self.raw_r1 is not None


@dataclass
class Verdict:
    """The Council's final verdict on an artifact.

    Verdict values: SHIP | REVISE | HOLD | INCOMPLETE.
    INCOMPLETE means fewer than ``min_deliberators_for_verdict`` produced
    parseable output (see council.yaml#protocol.min_deliberators_for_verdict).
    """

    verdict: str
    reasoning: str = ""
    revision_brief: str | None = None
    dissent_summary: str = ""
    deliberators: dict[str, DeliberatorResult] = field(default_factory=dict)
    adjudicator_raw: dict[str, Any] | None = None
    span_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serializable representation suitable for JSON output."""
        return {
            "verdict": self.verdict,
            "reasoning": self.reasoning,
            "revision_brief": self.revision_brief,
            "dissent_summary": self.dissent_summary,
            "deliberators": {
                k: {
                    "role": v.role,
                    "r1_score": v.r1_score,
                    "r1_would_block": v.r1_would_block,
                    "r2_score": v.r2_score,
                    "r2_would_block": v.r2_would_block,
                    "r2_irreducible": v.r2_irreducible,
                    "top_issues": v.top_issues,
                    "succeeded": v.succeeded,
                    "error": v.error,
                }
                for k, v in self.deliberators.items()
            },
            "span_id": self.span_id,
        }

    def to_json(self, indent: int = 2) -> str:
        """Pretty-printed JSON."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @property
    def exit_code(self) -> int:
        """CLI exit code matching the verdict."""
        return {
            "SHIP": EXIT_SHIP,
            "REVISE": EXIT_REVISE,
            "HOLD": EXIT_HOLD,
            "INCOMPLETE": EXIT_INCOMPLETE,
        }.get(self.verdict, EXIT_INCOMPLETE)


class VerdictPolicy:
    """Applies the SHIP / REVISE / HOLD rules to a set of deliberator results."""

    def __init__(self, policy_config: dict | None = None) -> None:
        """Initialize from ``council.yaml#adjudicator.verdict_policy``.

        The config is mostly documentation in v0.1; the rule logic is hardcoded
        but stays open to override via subclass when the rules evolve.
        """
        self.config = policy_config or {}

    def apply(
        self,
        results: dict[str, DeliberatorResult],
        min_deliberators: int = 3,
    ) -> tuple[str, str]:
        """Compute (verdict, reasoning) from the deliberators' R2 flags.

        Args:
            results: mapping of role-id to DeliberatorResult.
            min_deliberators: minimum number that must have succeeded; below
                this, the verdict is INCOMPLETE.

        Returns:
            (verdict, reasoning) tuple. Verdict is one of
            SHIP | REVISE | HOLD | INCOMPLETE.
        """
        succeeded = [r for r in results.values() if r.succeeded]
        if len(succeeded) < min_deliberators:
            return (
                "INCOMPLETE",
                (
                    f"Only {len(succeeded)} of {len(results)} deliberators produced "
                    f"parseable output; minimum is {min_deliberators}. "
                    "Verdict cannot be rendered."
                ),
            )

        # R2 takes precedence; fall back to R1 if a deliberator failed at R2.
        blocking = []
        irreducible = []
        for r in succeeded:
            would_block = r.r2_would_block if r.raw_r2 is not None else r.r1_would_block
            if would_block:
                blocking.append(r.role)
            if r.r2_irreducible:
                irreducible.append(r.role)

        if irreducible:
            return (
                "HOLD",
                (
                    f"Irreducible dissent from {', '.join(irreducible)}. "
                    "No revision can address this without structural rework."
                ),
            )

        n_block = len(blocking)
        if n_block == 0:
            return "SHIP", "No deliberator blocked after Round 2."
        if n_block >= 3:
            return (
                "HOLD",
                (
                    f"{n_block} deliberators blocked: {', '.join(blocking)}. "
                    "Three or more blocks indicates structural issues — recommend HOLD."
                ),
            )
        return (
            "REVISE",
            (
                f"{n_block} deliberator(s) blocked: {', '.join(blocking)}. "
                "No irreducible dissent — fixable with a revision pass."
            ),
        )
