"""Integration test for D5 — schema enforcement in the orchestrator.

We use a tiny custom adapter that returns scripted outputs per role, so we can
drive specific schema-fail scenarios and assert the re-prompt path.

Covers:
    - re-prompt success (R1 malformed → retry returns valid → reprompts=1)
    - invalid reviews do not count toward quorum; valid R1 survives R2 failure
    - adjudicator schema failure after re-prompt → verdict INCOMPLETE
    - schema_errors persisted in council_log.jsonl
    - mock_cli end-to-end still passes (canned outputs are valid; D5 invisible)
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import unittest
from pathlib import Path
from typing import Iterable
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from agent_council.config import load_config  # noqa: E402
from agent_council.orchestrator import Council  # noqa: E402
from agent_council.runtimes.base import RuntimeAdapter  # noqa: E402


def _wrap(payload: dict) -> str:
    return "```json\n" + json.dumps(payload) + "\n```"


class ScriptedAdapter(RuntimeAdapter):
    """Returns scripted responses keyed by role; supports per-call sequencing."""

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.scripts: dict[str, list[str | Exception]] = {}
        self.call_count: dict[str, int] = {}
        self.contexts: dict[str, list[list[str]]] = {}

    def set_script(self, role: str, responses: list[str | Exception]) -> None:
        self.scripts[role] = list(responses)
        self.call_count[role] = 0

    def adapter_name(self) -> str:
        return "scripted_test"

    def health_check(self) -> bool:
        return True

    async def invoke(
        self,
        prompt: str,
        context: Iterable[str],
        model: str | None = None,
    ) -> str:
        # Identify role from prompt header (loose — matches mock_cli pattern).
        head = prompt.lower()[:500]
        if "adjudicator" in head:
            role = "adjudicator"
        elif "voice_identity" in head or "voice & identity" in head:
            role = "voice_identity"
        elif "evidence" in head:
            role = "evidence"
        elif "strategy" in head:
            role = "strategy"
        else:
            role = "skeptic"

        bucket = self.scripts.get(role, [_wrap({"score": 3, "would_block": False, "irreducible": False, "verdict": "SHIP", "reasoning": "default", "revision_brief": None, "dissent_summary": ""})])
        idx = self.call_count.get(role, 0)
        resp = bucket[idx] if idx < len(bucket) else bucket[-1]
        self.call_count[role] = idx + 1
        self.contexts.setdefault(role, []).append(list(context))
        if isinstance(resp, Exception):
            raise resp
        return resp


def _build_council_with_scripted(adapter: ScriptedAdapter) -> Council:
    config = load_config(HERE / "council.example.yaml")
    return Council(config=config, config_dir=HERE, adapter=adapter)


class SchemaEnforcementTest(unittest.TestCase):
    """End-to-end schema enforcement paths (D5)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact_path = HERE / "sample_artifact.md"
        cls.log_path = HERE / "test_council_log.jsonl"
        cls.archive_dir = HERE / "test_council_archive"

    def setUp(self) -> None:
        if self.log_path.exists():
            self.log_path.unlink()
        if self.archive_dir.exists():
            shutil.rmtree(self.archive_dir)

    def tearDown(self) -> None:
        if self.log_path.exists():
            self.log_path.unlink()
        if self.archive_dir.exists():
            shutil.rmtree(self.archive_dir)

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------
    def test_reprompt_success_path(self) -> None:
        """A malformed first response + valid retry yields reprompts=1, schema_failed=False."""
        adapter = ScriptedAdapter({})
        # All other roles return valid R1+R2 + valid adjudicator.
        valid_r1 = _wrap({"score": 3, "would_block": False})
        valid_r2 = _wrap({"score": 3, "would_block": False, "irreducible": False})
        valid_adj = _wrap({
            "verdict": "SHIP",
            "reasoning": "no blocks",
            "revision_brief": None,
            "dissent_summary": "",
        })
        # Skeptic: malformed first (score out of range), valid retry.
        malformed = _wrap({"score": 99, "would_block": True})
        adapter.set_script("skeptic", [malformed, valid_r1, valid_r2, valid_r2])
        adapter.set_script("voice_identity", [valid_r1, valid_r2])
        adapter.set_script("evidence", [valid_r1, valid_r2])
        adapter.set_script("strategy", [valid_r1, valid_r2])
        adapter.set_script("adjudicator", [valid_adj])

        council = _build_council_with_scripted(adapter)
        verdict = asyncio.run(council.run(self.artifact_path, tier=1))

        self.assertIn(verdict.verdict, {"SHIP", "REVISE", "HOLD"})
        # Read the persisted record and check the skeptic was re-prompted.
        log_path = HERE / "test_council_log.jsonl"
        rec = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
        sk = rec["deliberators"]["skeptic"]
        self.assertGreaterEqual(sk["reprompts"], 1, "skeptic should have been re-prompted")
        self.assertFalse(sk["schema_failed"], "after valid retry, schema_failed should be False")

    def test_reprompt_failure_preserves_three_valid_review_quorum(self) -> None:
        """One invalid review does not prevent the other three reaching quorum."""
        adapter = ScriptedAdapter({})
        valid_r1 = _wrap({"score": 3, "would_block": False})
        valid_r2 = _wrap({"score": 3, "would_block": False, "irreducible": False})
        valid_adj = _wrap({
            "verdict": "SHIP",
            "reasoning": "ok",
            "revision_brief": None,
            "dissent_summary": "",
        })
        malformed = "no json at all just words"
        # Skeptic returns malformed both times.
        adapter.set_script("skeptic", [malformed, malformed, malformed, malformed])
        adapter.set_script("voice_identity", [valid_r1, valid_r2])
        adapter.set_script("evidence", [valid_r1, valid_r2])
        adapter.set_script("strategy", [valid_r1, valid_r2])
        adapter.set_script("adjudicator", [valid_adj])

        council = _build_council_with_scripted(adapter)
        verdict = asyncio.run(council.run(self.artifact_path, tier=1))

        # 3 valid deliberators is >= min_deliberators=3, so verdict still renders.
        self.assertIn(verdict.verdict, {"SHIP", "REVISE", "HOLD"})
        log_path = HERE / "test_council_log.jsonl"
        rec = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
        sk = rec["deliberators"]["skeptic"]
        self.assertTrue(sk["schema_failed"], f"skeptic should be schema_failed: {sk}")
        self.assertIn("schema_errors", sk)

    def test_invalid_objects_do_not_count_toward_quorum(self) -> None:
        roles = ("skeptic", "voice_identity", "evidence", "strategy")
        for invalid_count in (1, 2, 4):
            with self.subTest(invalid_count=invalid_count):
                adapter = ScriptedAdapter({})
                for role in roles[:invalid_count]:
                    adapter.set_script(role, [_wrap({})])
                council = _build_council_with_scripted(adapter)
                verdict = asyncio.run(council.run(self.artifact_path))
                expected = "SHIP" if invalid_count == 1 else "INCOMPLETE"
                self.assertEqual(expected, verdict.verdict)
                self.assertEqual(4 - invalid_count, sum(
                    result.succeeded for result in verdict.deliberators.values()
                ))
                for role in roles[:invalid_count]:
                    result = verdict.to_dict()["deliberators"][role]
                    self.assertFalse(result["succeeded"])
                    self.assertTrue(result["r1_schema_failed"])
                    self.assertTrue(result["error"])
                    self.assertEqual(4, adapter.call_count[role])
                    transcript = self.archive_dir / verdict.span_id / f"r1_{role}.md"
                    self.assertIn("{}", transcript.read_text(encoding="utf-8"))
                if expected == "INCOMPLETE":
                    self.assertIn("minimum is 3", verdict.reasoning)

    def test_failed_r2_preserves_valid_r1_and_reports_failure(self) -> None:
        for blocked in (False, True):
            for failure in (_wrap({}), RuntimeError("review unavailable")):
                with self.subTest(blocked=blocked, failure=failure):
                    adapter = ScriptedAdapter({})
                    r1 = _wrap({"score": 3, "would_block": blocked})
                    adapter.set_script("skeptic", [r1, failure, failure])
                    council = _build_council_with_scripted(adapter)
                    verdict = asyncio.run(council.run(self.artifact_path))
                    self.assertEqual("REVISE" if blocked else "SHIP", verdict.verdict)
                    sk = verdict.to_dict()["deliberators"]["skeptic"]
                    self.assertTrue(sk["succeeded"])
                    self.assertIsNone(sk["error"])
                    self.assertTrue(sk["r2_error"])
                    self.assertIsNone(verdict.deliberators["skeptic"].raw_r2)
                    self.assertIn("using valid R1", verdict.dissent_summary)
                    rec = json.loads(self.log_path.read_text(encoding="utf-8").splitlines()[-1])
                    self.assertEqual(sk["r2_error"], rec["deliberators"]["skeptic"]["r2_error"])

    def test_valid_r2_does_not_repair_invalid_r1_quorum(self) -> None:
        adapter = ScriptedAdapter({})
        valid_r2 = _wrap({"score": 3, "would_block": False, "irreducible": False})
        for role in ("skeptic", "evidence"):
            adapter.set_script(role, [_wrap({}), _wrap({}), valid_r2])
        verdict = asyncio.run(_build_council_with_scripted(adapter).run(self.artifact_path))
        self.assertEqual("INCOMPLETE", verdict.verdict)
        self.assertFalse(verdict.deliberators["skeptic"].succeeded)
        self.assertIsNotNone(verdict.deliberators["skeptic"].raw_r2)

    def test_one_round_configuration_does_not_report_r2_failure(self) -> None:
        adapter = ScriptedAdapter({})
        config = load_config(HERE / "council.example.yaml")
        config["protocol"]["rounds"] = 1
        council = Council(config, HERE, adapter=adapter)
        verdict = asyncio.run(council.run(self.artifact_path))
        self.assertEqual("SHIP", verdict.verdict)
        self.assertEqual(5, sum(adapter.call_count.values()))
        for result in verdict.deliberators.values():
            self.assertTrue(result.succeeded)
            self.assertIsNone(result.r2_error)
            self.assertFalse(result.r2_schema_failed)

    def test_synthesis_runtime_failure_is_audited_without_extra_retries(self) -> None:
        for error in (asyncio.TimeoutError("synthesis timed out"), RuntimeError("unavailable")):
            for first_response in ([], ["not JSON"]):
                with self.subTest(error=error, first_response=first_response):
                    adapter = ScriptedAdapter({})
                    adapter.set_script("adjudicator", [*first_response, error])
                    council = _build_council_with_scripted(adapter)
                    verdict = asyncio.run(council.run(self.artifact_path))
                    self.assertEqual("INCOMPLETE", verdict.verdict)
                    self.assertEqual(3, verdict.exit_code)
                    self.assertIn(str(error), verdict.adjudicator_error)
                    self.assertIn("runtime", verdict.reasoning.lower())
                    self.assertEqual(len(first_response) + 1, adapter.call_count["adjudicator"])
                    self.assertEqual(9 + len(first_response), sum(adapter.call_count.values()))
                    rec = json.loads(self.log_path.read_text(encoding="utf-8").splitlines()[-1])
                    self.assertEqual(verdict.adjudicator_error, rec["adjudicator_error"])
                    self.assertEqual(len(first_response), rec["adjudicator_reprompts"])
                    archive = self.archive_dir / verdict.span_id
                    self.assertEqual(10, len(list(archive.iterdir())))
                    self.assertIn('"score": 3', (archive / "r2_evidence.md").read_text(encoding="utf-8"))
                    synthesis = (archive / "adjudicator_synthesis.md").read_text(encoding="utf-8")
                    self.assertIn(str(error), synthesis)
                    if first_response:
                        self.assertIn(first_response[0], synthesis)

    def test_synthesis_programming_errors_are_not_hidden(self) -> None:
        for first_response in ([], ["not JSON"]):
            with self.subTest(first_response=first_response):
                adapter = ScriptedAdapter({})
                adapter.set_script("adjudicator", [*first_response, ValueError("adapter bug")])
                council = _build_council_with_scripted(adapter)
                with self.assertRaisesRegex(ValueError, "adapter bug"):
                    asyncio.run(council.run(self.artifact_path))

    def test_reviewer_retry_programming_error_preserves_partial_diagnostics(self) -> None:
        for round_num in (1, 2):
            for malformed in ("first malformed response", _wrap({"score": 99})):
                with self.subTest(round_num=round_num, malformed=malformed):
                    adapter = ScriptedAdapter({})
                    valid = _wrap({"score": 3, "would_block": True, "irreducible": False})
                    failure = ValueError("reviewer retry bug")
                    responses = (
                        [malformed, failure, valid] if round_num == 1
                        else [valid, malformed, failure]
                    )
                    adapter.set_script("skeptic", responses)
                    council = _build_council_with_scripted(adapter)
                    verdict = asyncio.run(council.run(self.artifact_path))
                    self.assertEqual("SHIP" if round_num == 1 else "REVISE", verdict.verdict)
                    result = verdict.deliberators["skeptic"]
                    self.assertEqual(round_num == 2, result.succeeded)
                    error = result.error if round_num == 1 else result.r2_error
                    self.assertEqual("ValueError: reviewer retry bug", error)
                    self.assertIn(error, verdict.dissent_summary)
                    self.assertEqual(3, adapter.call_count["skeptic"])
                    self.assertEqual(10, sum(adapter.call_count.values()))

                    record = json.loads(self.log_path.read_text(encoding="utf-8").splitlines()[-1])
                    diagnostic = record["deliberators"]["skeptic"]
                    self.assertTrue(diagnostic[f"r{round_num}_schema_failed"])
                    self.assertEqual(1, diagnostic["reprompts"])
                    self.assertTrue(any(
                        "no JSON block" in entry or "missing required key" in entry
                        for entry in diagnostic["schema_errors"]
                    ))
                    self.assertIn("adapter raised: ValueError", diagnostic["schema_errors"])
                    transcript = self.archive_dir / verdict.span_id / f"r{round_num}_skeptic.md"
                    self.assertEqual(malformed, transcript.read_text(encoding="utf-8"))
                    if round_num == 1 and malformed.startswith("```"):
                        self.assertEqual({"score": 99}, result.raw_r1)

    def test_reviewer_retry_programming_error_still_raises_from_invocation(self) -> None:
        adapter = ScriptedAdapter({})
        failure = ValueError("reviewer retry bug")
        adapter.set_script("skeptic", ["first malformed response", failure])
        with self.assertRaises(ValueError) as raised:
            asyncio.run(Council._invoke_with_schema(adapter, "skeptic", [], "skeptic", 1))
        self.assertIs(failure, raised.exception)
        self.assertEqual(2, adapter.call_count["skeptic"])

    def test_audit_write_errors_are_not_hidden(self) -> None:
        council = _build_council_with_scripted(ScriptedAdapter({}))
        with patch.object(council.log, "append", side_effect=OSError("disk unavailable")):
            with self.assertRaisesRegex(OSError, "disk unavailable"):
                asyncio.run(council.run(self.artifact_path))

    def test_enforced_verdict_and_explanation_agree(self) -> None:
        for score, irreducible, expected in ((2, False, "REVISE"), (3, True, "HOLD")):
            with self.subTest(expected=expected):
                adapter = ScriptedAdapter({})
                review = _wrap({
                    "score": score, "would_block": False, "irreducible": irreducible,
                    "top_3_failure_modes": ["Pricing claim lacks supplied evidence."],
                })
                adapter.set_script("skeptic", [review])
                adapter.set_script("adjudicator", [_wrap({
                    "verdict": "SHIP", "reasoning": "Ready to ship.", "revision_brief": None,
                })])
                verdict = asyncio.run(_build_council_with_scripted(adapter).run(self.artifact_path))
                self.assertEqual(expected, verdict.verdict)
                self.assertIn(expected, verdict.reasoning)
                self.assertIn("recommendation SHIP", verdict.reasoning)
                self.assertNotIn("Ready to ship", verdict.reasoning)
                self.assertIn("Pricing claim lacks supplied evidence.", verdict.revision_brief)
                self.assertIn("No actionable revision brief", verdict.revision_brief)

    def test_configured_policy_and_full_findings_reach_synthesis(self) -> None:
        adapter = ScriptedAdapter({})
        review = _wrap({
            "score": 4, "would_block": False, "irreducible": False,
            "claim_tier_map": [{"claim": "unique supporting detail", "tier": "T5"}],
        })
        adapter.set_script("evidence", [review])
        config = load_config(HERE / "council.example.yaml")
        config["adjudicator"]["verdict_policy"] = {
            "ship_min_score": 4, "soft_block_score": 2, "hold_block_count": 4,
        }
        council = Council(config=config, config_dir=HERE, adapter=adapter)
        asyncio.run(council.run(self.artifact_path))
        pack = "\n".join(adapter.contexts["adjudicator"][0])
        for setting in ("ship_min_score=4", "soft_block_score=2", "hold_block_count=4"):
            self.assertIn(setting, pack)
        self.assertIn("minimum of 3", pack)
        self.assertIn("unique supporting detail", pack)
        self.assertIn("unique supporting detail", "\n".join(adapter.contexts["skeptic"][1]))

    def test_adjudicator_schema_failure_returns_incomplete(self) -> None:
        """Adjudicator output malformed even after re-prompt → verdict INCOMPLETE."""
        adapter = ScriptedAdapter({})
        valid_r1 = _wrap({"score": 3, "would_block": False})
        valid_r2 = _wrap({"score": 3, "would_block": False, "irreducible": False})
        # Adjudicator returns malformed BOTH times.
        bad_adj = _wrap({"verdict": "MAYBE", "reasoning": ""})
        adapter.set_script("skeptic", [valid_r1, valid_r2])
        adapter.set_script("voice_identity", [valid_r1, valid_r2])
        adapter.set_script("evidence", [valid_r1, valid_r2])
        adapter.set_script("strategy", [valid_r1, valid_r2])
        adapter.set_script("adjudicator", [bad_adj, bad_adj])

        council = _build_council_with_scripted(adapter)
        verdict = asyncio.run(council.run(self.artifact_path, tier=1))

        self.assertEqual("INCOMPLETE", verdict.verdict)
        self.assertEqual(3, verdict.exit_code)
        log_path = HERE / "test_council_log.jsonl"
        rec = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertTrue(rec["adjudicator_schema_failed"])
        self.assertGreaterEqual(rec["adjudicator_reprompts"], 1)

    def test_partial_range_failure_reprompts(self) -> None:
        """A score:7 out-of-range payload triggers re-prompt; valid retry accepted."""
        adapter = ScriptedAdapter({})
        valid_r1 = _wrap({"score": 3, "would_block": False})
        valid_r2 = _wrap({"score": 3, "would_block": False, "irreducible": False})
        valid_adj = _wrap({
            "verdict": "SHIP",
            "reasoning": "ok",
            "revision_brief": None,
            "dissent_summary": "",
        })
        out_of_range = _wrap({"score": 7, "would_block": False})
        adapter.set_script("evidence", [out_of_range, valid_r1, valid_r2, valid_r2])
        adapter.set_script("skeptic", [valid_r1, valid_r2])
        adapter.set_script("voice_identity", [valid_r1, valid_r2])
        adapter.set_script("strategy", [valid_r1, valid_r2])
        adapter.set_script("adjudicator", [valid_adj])

        council = _build_council_with_scripted(adapter)
        verdict = asyncio.run(council.run(self.artifact_path, tier=1))
        log_path = HERE / "test_council_log.jsonl"
        rec = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
        ev = rec["deliberators"]["evidence"]
        self.assertGreaterEqual(ev["reprompts"], 1)
        self.assertFalse(ev["schema_failed"])

    def test_artifact_type_persisted_in_log(self) -> None:
        """Every persisted record now includes artifact_type (D6 prerequisite)."""
        adapter = ScriptedAdapter({})
        valid_r1 = _wrap({"score": 3, "would_block": False})
        valid_r2 = _wrap({"score": 3, "would_block": False, "irreducible": False})
        valid_adj = _wrap({
            "verdict": "SHIP",
            "reasoning": "ok",
            "revision_brief": None,
            "dissent_summary": "",
        })
        for role in ("skeptic", "voice_identity", "evidence", "strategy"):
            adapter.set_script(role, [valid_r1, valid_r2])
        adapter.set_script("adjudicator", [valid_adj])

        council = _build_council_with_scripted(adapter)
        asyncio.run(council.run(self.artifact_path, tier=1))
        log_path = HERE / "test_council_log.jsonl"
        rec = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertIn("artifact_type", rec)
        # tests/council.example.yaml routes *sample_artifact* to "linkedin_post".
        self.assertEqual("linkedin_post", rec["artifact_type"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
