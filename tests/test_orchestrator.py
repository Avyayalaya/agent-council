"""End-to-end orchestrator test using the mock_cli runtime.

This test exercises the full 2-round protocol + Adjudicator synthesis +
verdict policy + JSONL log + archive write — all offline, no real LLM
calls. It is the load-bearing W1 deliverable.

Run with either:
    python -m unittest tests.test_orchestrator
or:
    pytest tests/test_orchestrator.py
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import unittest
from pathlib import Path

# Make the package importable without installation.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from agent_council.config import load_config, validate_config  # noqa: E402
from agent_council.orchestrator import Council  # noqa: E402
from agent_council.verdict import (  # noqa: E402
    EXIT_REVISE,
    EXIT_SHIP,
    Verdict,
)


class CouncilEndToEndTest(unittest.TestCase):
    """Validates the W1 happy path: sample artifact → REVISE verdict."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.config_path = HERE / "council.example.yaml"
        cls.artifact_path = HERE / "sample_artifact.md"
        cls.log_path = HERE / "test_council_log.jsonl"
        cls.archive_dir = HERE / "test_council_archive"
        cls._clean()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._clean()

    @classmethod
    def _clean(cls) -> None:
        if cls.log_path.exists():
            cls.log_path.unlink()
        if cls.archive_dir.exists():
            shutil.rmtree(cls.archive_dir)

    def test_config_loads_and_validates(self) -> None:
        """council.example.yaml parses without errors."""
        config = load_config(self.config_path)
        errors = validate_config(config)
        self.assertEqual([], errors, f"Config validation errors: {errors}")

    def test_end_to_end_verdict_shape(self) -> None:
        """Run the Council and assert verdict + log + archive are produced."""
        config = load_config(self.config_path)
        council = Council(config=config, config_dir=self.config_path.parent)
        verdict: Verdict = asyncio.run(council.run(self.artifact_path, tier=1))

        # 1. Verdict shape is correct.
        self.assertIsInstance(verdict, Verdict)
        self.assertIn(verdict.verdict, {"SHIP", "REVISE", "HOLD", "INCOMPLETE"})
        self.assertTrue(verdict.span_id.startswith("council-"))
        self.assertTrue(len(verdict.span_id) > len("council-"))

        # 2. With the canned mock outputs (2 blocks, 0 irreducible), verdict
        #    must be REVISE.
        self.assertEqual(
            "REVISE",
            verdict.verdict,
            f"Expected REVISE from canned mock; got {verdict.verdict}",
        )
        self.assertEqual(EXIT_REVISE, verdict.exit_code)

        # 3. All 4 deliberators succeeded.
        self.assertEqual(4, len(verdict.deliberators))
        for role, r in verdict.deliberators.items():
            self.assertTrue(r.succeeded, f"Deliberator {role} failed: {r.error}")
            self.assertIsNotNone(r.r1_score)
            self.assertIsNotNone(r.r2_score)

        # 4. Skeptic + Voice should have blocked (matches canned mock).
        self.assertTrue(verdict.deliberators["skeptic"].r2_would_block)
        self.assertTrue(verdict.deliberators["voice_identity"].r2_would_block)
        self.assertFalse(verdict.deliberators["evidence"].r2_would_block)
        self.assertFalse(verdict.deliberators["strategy"].r2_would_block)

        # 5. Revision brief is populated (REVISE always carries one).
        self.assertIsNotNone(verdict.revision_brief)
        self.assertGreater(len(verdict.revision_brief or ""), 50)

        # 6. JSON serializes cleanly.
        as_dict = verdict.to_dict()
        json_str = json.dumps(as_dict, ensure_ascii=False)
        self.assertGreater(len(json_str), 100)

    def test_jsonl_log_persisted(self) -> None:
        """The verdict line is appended with Rule 35 v2 fields."""
        config = load_config(self.config_path)
        council = Council(config=config, config_dir=self.config_path.parent)
        asyncio.run(council.run(self.artifact_path, tier=1))

        # The log path is resolved relative to the config file directory.
        log_path = self.config_path.parent / "test_council_log.jsonl"
        self.assertTrue(log_path.exists(), f"No log at {log_path}")
        lines = [
            line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        self.assertGreaterEqual(len(lines), 1)
        rec = json.loads(lines[-1])
        # Rule 35 v2 schema fields.
        for field in ("v", "span_id", "sid", "ts", "agent", "event", "persisted"):
            self.assertIn(field, rec, f"Missing required field: {field}")
        self.assertEqual(2, rec["v"])
        self.assertEqual("council", rec["agent"])
        self.assertEqual("verdict", rec["event"])
        self.assertTrue(rec["persisted"])
        self.assertIn("artifact_sha256", rec)
        self.assertEqual(64, len(rec["artifact_sha256"]))  # SHA-256 hex length.
        self.assertEqual("mock_cli", rec["runtime"])

    def test_archive_written(self) -> None:
        """The archive captures every R1 + R2 transcript and the synthesis."""
        config = load_config(self.config_path)
        council = Council(config=config, config_dir=self.config_path.parent)
        verdict = asyncio.run(council.run(self.artifact_path, tier=1))

        archive_root = self.config_path.parent / "test_council_archive" / verdict.span_id
        self.assertTrue(archive_root.exists(), f"No archive at {archive_root}")
        expected = {
            "artifact.md",
            "r1_skeptic.md",
            "r1_voice_identity.md",
            "r1_evidence.md",
            "r1_strategy.md",
            "r2_skeptic.md",
            "r2_voice_identity.md",
            "r2_evidence.md",
            "r2_strategy.md",
            "adjudicator_synthesis.md",
        }
        actual = {p.name for p in archive_root.iterdir()}
        self.assertTrue(
            expected.issubset(actual),
            f"Missing archive files: {expected - actual}",
        )

    def test_elapsed_time_under_five_minutes(self) -> None:
        """The mock-runtime run should complete well under the 5-min SLA."""
        import time
        config = load_config(self.config_path)
        council = Council(config=config, config_dir=self.config_path.parent)
        t0 = time.time()
        asyncio.run(council.run(self.artifact_path, tier=1))
        elapsed = time.time() - t0
        self.assertLess(elapsed, 300, f"Run took {elapsed:.1f}s; SLA is 300s")


if __name__ == "__main__":
    unittest.main(verbosity=2)
