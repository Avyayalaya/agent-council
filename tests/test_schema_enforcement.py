"""Integration test for D5 — schema enforcement in the orchestrator.

We use a tiny custom adapter that returns scripted outputs per role, so we can
drive specific schema-fail scenarios and assert the re-prompt path.

Covers:
    - re-prompt success (R1 malformed → retry returns valid → reprompts=1)
    - re-prompt failure → schema_failed=True, treated as no_dissent
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
        # scripts[(role, attempt)] -> response str
        self.scripts: dict[str, list[str]] = {}
        self.call_count: dict[str, int] = {}

    def set_script(self, role: str, responses: list[str]) -> None:
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
        return resp


def _build_council_with_scripted(adapter: ScriptedAdapter) -> Council:
    config = load_config(HERE / "council.example.yaml")
    council = Council(config=config, config_dir=HERE)
    # Swap in the scripted adapter.
    council.adapter = adapter
    return council


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

    def test_reprompt_failure_treated_as_no_dissent(self) -> None:
        """Schema fails twice → schema_failed=True; verdict still renders (no_dissent)."""
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
