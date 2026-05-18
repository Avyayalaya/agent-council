"""Unit tests for ``orchestrator.merge_verdicts`` — verdict-policy merge logic.

Extracted from the inline Council.run() flow on 2026-05-12 so the merge
rules are testable without running a full Council deliberation. Pins the
semantics surfaced by the 2026-05-11 Council Sweep:

  - Policy SHIP + Adjudicator SHIP → SHIP
  - Policy REVISE + Adjudicator SHIP → REVISE (Adjudicator cannot bypass)
  - Policy HOLD + Adjudicator SHIP → HOLD (Adjudicator cannot bypass)
  - Policy REVISE + Adjudicator HOLD → HOLD (Adjudicator escalation works)
  - Policy HOLD + Adjudicator REVISE + zero irreducible → REVISE (downgrade)
  - Policy HOLD + Adjudicator REVISE + at least one irreducible → HOLD
  - Policy INCOMPLETE always wins (irrespective of Adjudicator)
  - Adjudicator schema-failure always → INCOMPLETE
  - Adjudicator verdict missing / invalid → policy result
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from agent_council.orchestrator import merge_verdicts  # noqa: E402
from agent_council.verdict import DeliberatorResult  # noqa: E402


def _make_result(
    role: str,
    *,
    blocked: bool = False,
    irreducible: bool = False,
    succeeded: bool = True,
) -> DeliberatorResult:
    """Build a DeliberatorResult quickly for tests."""
    return DeliberatorResult(
        role=role,
        r1_score=3,
        r1_would_block=blocked,
        r2_score=3,
        r2_would_block=blocked,
        r2_irreducible=irreducible,
        raw_r1={"score": 3} if succeeded else None,
        raw_r2={"score": 3} if succeeded else None,
        error=None if succeeded else "RuntimeError: test",
    )


def _four_blockers(any_irreducible: bool = False) -> dict[str, DeliberatorResult]:
    """Four deliberators, all blocking, optional irreducible on Skeptic."""
    return {
        "skeptic": _make_result("skeptic", blocked=True, irreducible=any_irreducible),
        "voice_identity": _make_result("voice_identity", blocked=True),
        "evidence": _make_result("evidence", blocked=True),
        "strategy": _make_result("strategy", blocked=True),
    }


def _three_blockers(any_irreducible: bool = False) -> dict[str, DeliberatorResult]:
    """Three deliberators blocking, one approving."""
    return {
        "skeptic": _make_result("skeptic", blocked=True, irreducible=any_irreducible),
        "voice_identity": _make_result("voice_identity", blocked=True),
        "evidence": _make_result("evidence", blocked=True),
        "strategy": _make_result("strategy", blocked=False),
    }


def _two_blockers() -> dict[str, DeliberatorResult]:
    """Two deliberators blocking — policy returns REVISE."""
    return {
        "skeptic": _make_result("skeptic", blocked=True),
        "voice_identity": _make_result("voice_identity", blocked=True),
        "evidence": _make_result("evidence", blocked=False),
        "strategy": _make_result("strategy", blocked=False),
    }


def _zero_blockers() -> dict[str, DeliberatorResult]:
    """All deliberators approve — policy returns SHIP."""
    return {
        "skeptic": _make_result("skeptic"),
        "voice_identity": _make_result("voice_identity"),
        "evidence": _make_result("evidence"),
        "strategy": _make_result("strategy"),
    }


class MergeVerdictsTest(unittest.TestCase):
    """Pin the merge semantics directly."""

    # ------------------------------------------------------------------
    # Schema-failure: always INCOMPLETE.
    # ------------------------------------------------------------------
    def test_adjudicator_schema_failed_returns_incomplete(self) -> None:
        verdict = merge_verdicts(
            policy_verdict="SHIP",
            adj_verdict="SHIP",
            adj_schema_failed=True,
            results=_zero_blockers(),
        )
        self.assertEqual("INCOMPLETE", verdict)

    def test_schema_failed_overrides_even_clean_ship(self) -> None:
        """Schema failure invalidates the synthesis no matter what the policy says."""
        verdict = merge_verdicts(
            policy_verdict="SHIP",
            adj_verdict=None,
            adj_schema_failed=True,
            results=_zero_blockers(),
        )
        self.assertEqual("INCOMPLETE", verdict)

    # ------------------------------------------------------------------
    # Adjudicator missing / invalid → fall back to policy.
    # ------------------------------------------------------------------
    def test_no_adjudicator_falls_back_to_policy(self) -> None:
        verdict = merge_verdicts(
            policy_verdict="REVISE",
            adj_verdict=None,
            adj_schema_failed=False,
            results=_two_blockers(),
        )
        self.assertEqual("REVISE", verdict)

    def test_invalid_adjudicator_verdict_falls_back_to_policy(self) -> None:
        verdict = merge_verdicts(
            policy_verdict="HOLD",
            adj_verdict="MAYBE",  # not a valid verdict
            adj_schema_failed=False,
            results=_four_blockers(),
        )
        self.assertEqual("HOLD", verdict)

    # ------------------------------------------------------------------
    # Policy INCOMPLETE always wins.
    # ------------------------------------------------------------------
    def test_policy_incomplete_overrides_adjudicator_ship(self) -> None:
        verdict = merge_verdicts(
            policy_verdict="INCOMPLETE",
            adj_verdict="SHIP",
            adj_schema_failed=False,
            results=_zero_blockers(),
        )
        self.assertEqual("INCOMPLETE", verdict)

    # ------------------------------------------------------------------
    # Adjudicator cannot bypass policy: stricter of the two wins
    # (except the constrained HOLD → REVISE downgrade — tested below).
    # ------------------------------------------------------------------
    def test_policy_ship_adj_ship_yields_ship(self) -> None:
        verdict = merge_verdicts(
            policy_verdict="SHIP",
            adj_verdict="SHIP",
            adj_schema_failed=False,
            results=_zero_blockers(),
        )
        self.assertEqual("SHIP", verdict)

    def test_policy_revise_adj_ship_stays_revise(self) -> None:
        """Adjudicator SHIP cannot bypass policy REVISE (2 blockers)."""
        verdict = merge_verdicts(
            policy_verdict="REVISE",
            adj_verdict="SHIP",
            adj_schema_failed=False,
            results=_two_blockers(),
        )
        self.assertEqual("REVISE", verdict)

    def test_policy_hold_adj_ship_stays_hold(self) -> None:
        """Adjudicator SHIP cannot bypass policy HOLD (4 blockers)."""
        verdict = merge_verdicts(
            policy_verdict="HOLD",
            adj_verdict="SHIP",
            adj_schema_failed=False,
            results=_four_blockers(),
        )
        self.assertEqual("HOLD", verdict)

    def test_adj_can_escalate_revise_to_hold(self) -> None:
        """Adjudicator HOLD escalates a policy REVISE."""
        verdict = merge_verdicts(
            policy_verdict="REVISE",
            adj_verdict="HOLD",
            adj_schema_failed=False,
            results=_two_blockers(),
        )
        self.assertEqual("HOLD", verdict)

    def test_adj_can_escalate_ship_to_revise(self) -> None:
        """Adjudicator REVISE escalates a policy SHIP."""
        verdict = merge_verdicts(
            policy_verdict="SHIP",
            adj_verdict="REVISE",
            adj_schema_failed=False,
            results=_zero_blockers(),
        )
        self.assertEqual("REVISE", verdict)

    # ------------------------------------------------------------------
    # Constrained HOLD → REVISE downgrade (the headline 2026-05-11 fix).
    # ------------------------------------------------------------------
    def test_policy_hold_adj_revise_no_irreducible_downgrades(self) -> None:
        """4 blockers, 0 irreducible, Adjudicator says REVISE → REVISE."""
        verdict = merge_verdicts(
            policy_verdict="HOLD",
            adj_verdict="REVISE",
            adj_schema_failed=False,
            results=_four_blockers(any_irreducible=False),
        )
        self.assertEqual("REVISE", verdict,
                         "Adjudicator REVISE should downgrade HOLD when zero irreducible.")

    def test_policy_hold_adj_revise_with_irreducible_stays_hold(self) -> None:
        """4 blockers, at least one irreducible → HOLD regardless of Adjudicator."""
        verdict = merge_verdicts(
            policy_verdict="HOLD",
            adj_verdict="REVISE",
            adj_schema_failed=False,
            results=_four_blockers(any_irreducible=True),
        )
        self.assertEqual("HOLD", verdict,
                         "Irreducible dissent blocks the Adjudicator's REVISE downgrade.")

    def test_three_block_hold_adj_revise_no_irreducible_downgrades(self) -> None:
        """3 blockers (the minimum for policy HOLD), no irreducible → REVISE."""
        verdict = merge_verdicts(
            policy_verdict="HOLD",
            adj_verdict="REVISE",
            adj_schema_failed=False,
            results=_three_blockers(any_irreducible=False),
        )
        self.assertEqual("REVISE", verdict)


if __name__ == "__main__":
    unittest.main(verbosity=2)
