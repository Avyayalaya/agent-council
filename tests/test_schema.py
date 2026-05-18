"""Unit tests for src/agent_council/schema.py (D5 — load-bearing).

Covers:
    - valid R1/R2/R3 payloads for every role
    - missing required keys → invalid
    - out-of-range score → invalid
    - wrong type (str instead of number) → invalid
    - wrong enum value for verdict → invalid
    - mock_cli canned shapes all validate without re-prompt
    - stricter_format_instruction is non-empty and references the role
    - unknown role/round returns (False, [...]) instead of raising
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from agent_council.schema import (  # noqa: E402
    ROLE_ADJUDICATOR,
    ROLE_EVIDENCE,
    ROLE_SKEPTIC,
    ROLE_STRATEGY,
    ROLE_VOICE,
    stricter_format_instruction,
    validate,
)


class SchemaValidatorTest(unittest.TestCase):
    """validate() must accept gold shapes and reject defective ones."""

    def test_valid_skeptic_r1(self) -> None:
        ok, errs = validate(
            {"score": 3, "would_block": True}, ROLE_SKEPTIC, 1
        )
        self.assertTrue(ok, f"unexpected errors: {errs}")

    def test_valid_skeptic_r2_with_irreducible(self) -> None:
        ok, errs = validate(
            {"score": 2, "would_block": True, "irreducible": False},
            ROLE_SKEPTIC,
            2,
        )
        self.assertTrue(ok, f"unexpected errors: {errs}")

    def test_valid_adjudicator_ship(self) -> None:
        ok, errs = validate(
            {
                "verdict": "SHIP",
                "reasoning": "no blocks after R2",
                "revision_brief": None,
                "dissent_summary": "",
            },
            ROLE_ADJUDICATOR,
            3,
        )
        self.assertTrue(ok, f"unexpected errors: {errs}")

    def test_valid_adjudicator_revise(self) -> None:
        ok, errs = validate(
            {
                "verdict": "REVISE",
                "reasoning": "two would_block, no irreducible",
                "revision_brief": "fix V1 and add a source",
                "dissent_summary": "skeptic + voice",
            },
            ROLE_ADJUDICATOR,
            3,
        )
        self.assertTrue(ok, f"unexpected errors: {errs}")

    def test_missing_required_key(self) -> None:
        ok, errs = validate({"score": 3}, ROLE_SKEPTIC, 1)
        self.assertFalse(ok)
        self.assertTrue(any("would_block" in e for e in errs))

    def test_score_out_of_range(self) -> None:
        ok, errs = validate(
            {"score": 7, "would_block": False}, ROLE_VOICE, 1
        )
        self.assertFalse(ok)
        self.assertTrue(any("out of allowed range" in e for e in errs))

    def test_wrong_type_for_score(self) -> None:
        ok, errs = validate(
            {"score": "high", "would_block": False}, ROLE_VOICE, 1
        )
        self.assertFalse(ok)
        self.assertTrue(any("expected type number" in e for e in errs))

    def test_bool_not_accepted_as_score(self) -> None:
        """Python bool is a subclass of int; we explicitly reject it as a score."""
        ok, errs = validate(
            {"score": True, "would_block": False}, ROLE_EVIDENCE, 1
        )
        self.assertFalse(ok)

    def test_wrong_verdict_enum(self) -> None:
        ok, errs = validate(
            {"verdict": "MAYBE", "reasoning": "x"}, ROLE_ADJUDICATOR, 3
        )
        self.assertFalse(ok)
        self.assertTrue(any("not in allowed values" in e for e in errs))

    def test_empty_reasoning_rejected(self) -> None:
        ok, errs = validate(
            {"verdict": "SHIP", "reasoning": "   "},
            ROLE_ADJUDICATOR,
            3,
        )
        self.assertFalse(ok)
        self.assertTrue(any("non-empty string" in e for e in errs))

    def test_none_payload_rejected(self) -> None:
        ok, errs = validate(None, ROLE_SKEPTIC, 1)
        self.assertFalse(ok)
        self.assertTrue(any("None" in e for e in errs))

    def test_non_dict_payload_rejected(self) -> None:
        ok, errs = validate([1, 2, 3], ROLE_SKEPTIC, 1)
        self.assertFalse(ok)
        self.assertTrue(any("JSON object" in e for e in errs))

    def test_unknown_role_returns_false_not_raise(self) -> None:
        ok, errs = validate({"score": 3}, "unknown_role", 1)
        self.assertFalse(ok)
        self.assertTrue(any("no schema defined" in e for e in errs))

    def test_unknown_round_returns_false_not_raise(self) -> None:
        ok, errs = validate({"score": 3}, ROLE_SKEPTIC, 9)
        self.assertFalse(ok)

    def test_stricter_instruction_mentions_role_and_round(self) -> None:
        msg = stricter_format_instruction(
            ROLE_SKEPTIC, 1, ["missing required key: 'would_block'"]
        )
        self.assertIn("[SCHEMA_RETRY]", msg)
        self.assertIn("skeptic", msg)
        self.assertIn("would_block", msg)
        # Voice rule (V1) — no "not X but Y" framing.
        self.assertNotIn("not just", msg.lower())
        self.assertNotIn("not a ", msg.lower())

    def test_stricter_instruction_lists_required_fields(self) -> None:
        msg = stricter_format_instruction(
            ROLE_ADJUDICATOR, 3, ["wrong verdict"]
        )
        self.assertIn("verdict", msg)
        self.assertIn("reasoning", msg)
        self.assertIn("SHIP", msg)


class SchemaCalibrationTest(unittest.TestCase):
    """The mock_cli canned payloads must validate without re-prompt (F5.1 mitigation).

    If this test fails, the schema is too strict for actual W1 output and the
    end-to-end orchestrator test will start re-prompting on every run.
    """

    def test_mock_r1_payloads_all_valid(self) -> None:
        from agent_council.runtimes.mock_cli import _R1_CRITIQUES

        for role, payload in _R1_CRITIQUES.items():
            with self.subTest(role=role, round=1):
                ok, errs = validate(payload, role, 1)
                self.assertTrue(
                    ok, f"R1 mock for {role} failed schema: {errs}"
                )

    def test_mock_r2_payloads_all_valid(self) -> None:
        from agent_council.runtimes.mock_cli import _R2_REBUTTALS

        for role, payload in _R2_REBUTTALS.items():
            with self.subTest(role=role, round=2):
                ok, errs = validate(payload, role, 2)
                self.assertTrue(
                    ok, f"R2 mock for {role} failed schema: {errs}"
                )

    def test_mock_adjudicator_payload_valid(self) -> None:
        from agent_council.runtimes.mock_cli import _ADJUDICATOR_SYNTHESIS

        ok, errs = validate(_ADJUDICATOR_SYNTHESIS, ROLE_ADJUDICATOR, 3)
        self.assertTrue(ok, f"adjudicator mock failed schema: {errs}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
