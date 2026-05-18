"""D6 — Prior-verdicts lookup (compounding loop, design v0.2 §6).

Tests:
    - empty log → []
    - log with mixed types → only matching artifact_type returned
    - limit honored; newest-first ordering
    - malformed lines silently skipped
    - record shape: ts, span_id, verdict, deliberators_summary, revision_brief,
      artifact_sha256, reasoning
    - integration: a second Council run on a similar artifact sees the first
      verdict in its adjudicator context blob (visible in the archive).
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from agent_council.config import load_config  # noqa: E402
from agent_council.log import CouncilLog  # noqa: E402
from agent_council.orchestrator import Council  # noqa: E402


def _make_record(
    artifact_type: str,
    verdict: str = "SHIP",
    ts: str = "2026-05-11T10:00:00Z",
    span_id: str = "council-abc",
    sha: str = "deadbeef" * 8,
    reasoning: str = "ok",
    rb: str | None = None,
) -> dict:
    return {
        "v": 2,
        "ts": ts,
        "span_id": span_id,
        "agent": "council",
        "event": "verdict",
        "artifact_type": artifact_type,
        "verdict": verdict,
        "artifact_sha256": sha,
        "reasoning": reasoning,
        "revision_brief": rb,
        "deliberators": {
            "skeptic": {"r2_score": 3, "r2_would_block": False, "r2_irreducible": False},
            "voice_identity": {"r2_score": 4, "r2_would_block": False, "r2_irreducible": False},
        },
        "persisted": True,
    }


class CouncilLogPriorVerdictsTest(unittest.TestCase):
    """CouncilLog.read_prior_verdicts contract tests."""

    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
        self.tmp.close()
        self.log_path = Path(self.tmp.name)
        self.log = CouncilLog(self.log_path)

    def tearDown(self) -> None:
        self.log_path.unlink(missing_ok=True)

    def _write_lines(self, records: list[dict]) -> None:
        with self.log_path.open("w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")

    def test_empty_log_returns_empty_list(self) -> None:
        # Truncate the log to ensure it's empty.
        self.log_path.write_text("", encoding="utf-8")
        self.assertEqual([], self.log.read_prior_verdicts("linkedin_post"))

    def test_nonexistent_log_returns_empty(self) -> None:
        path = self.log_path.parent / "definitely_not_a_file.jsonl"
        log = CouncilLog(path)
        self.assertEqual([], log.read_prior_verdicts("linkedin_post"))

    def test_filters_by_artifact_type(self) -> None:
        self._write_lines([
            _make_record("linkedin_post", span_id="c-1"),
            _make_record("substack_post", span_id="c-2"),
            _make_record("linkedin_post", span_id="c-3"),
            _make_record("resume", span_id="c-4"),
        ])
        out = self.log.read_prior_verdicts("linkedin_post")
        self.assertEqual(2, len(out))
        spans = [r["span_id"] for r in out]
        # newest-first → c-3 then c-1
        self.assertEqual(["c-3", "c-1"], spans)

    def test_limit_honored(self) -> None:
        records = [
            _make_record("linkedin_post", span_id=f"c-{i}") for i in range(10)
        ]
        self._write_lines(records)
        out = self.log.read_prior_verdicts("linkedin_post", limit=3)
        self.assertEqual(3, len(out))
        self.assertEqual("c-9", out[0]["span_id"])

    def test_malformed_lines_skipped(self) -> None:
        with self.log_path.open("w", encoding="utf-8") as f:
            f.write(json.dumps(_make_record("linkedin_post", span_id="c-1")) + "\n")
            f.write("this is not json at all\n")
            f.write("{partial json\n")
            f.write("\n")
            f.write(json.dumps(_make_record("linkedin_post", span_id="c-2")) + "\n")
        out = self.log.read_prior_verdicts("linkedin_post")
        self.assertEqual(2, len(out))

    def test_record_shape(self) -> None:
        self._write_lines([
            _make_record(
                "linkedin_post",
                verdict="REVISE",
                ts="2026-05-10T00:00:00Z",
                span_id="c-fixed",
                reasoning="needed sourcing",
                rb="add a citation",
            )
        ])
        out = self.log.read_prior_verdicts("linkedin_post")
        self.assertEqual(1, len(out))
        rec = out[0]
        for key in ("ts", "span_id", "verdict", "deliberators_summary",
                    "revision_brief", "artifact_sha256", "reasoning"):
            self.assertIn(key, rec, f"missing key: {key}")
        self.assertEqual("REVISE", rec["verdict"])
        self.assertEqual("c-fixed", rec["span_id"])
        self.assertEqual("add a citation", rec["revision_brief"])
        self.assertIn("skeptic", rec["deliberators_summary"])

    def test_missing_artifact_type_skipped(self) -> None:
        """Backwards-compat: records without artifact_type are not returned."""
        rec = _make_record("linkedin_post")
        del rec["artifact_type"]
        self._write_lines([rec, _make_record("linkedin_post", span_id="c-real")])
        out = self.log.read_prior_verdicts("linkedin_post")
        self.assertEqual(1, len(out))
        self.assertEqual("c-real", out[0]["span_id"])

    def test_unknown_type_does_not_match_specific(self) -> None:
        """artifact_type='unknown' must NOT match a specific request."""
        self._write_lines([
            _make_record("unknown", span_id="c-unk"),
            _make_record("linkedin_post", span_id="c-li"),
        ])
        out = self.log.read_prior_verdicts("linkedin_post")
        self.assertEqual(1, len(out))
        self.assertEqual("c-li", out[0]["span_id"])

    def test_zero_limit_returns_empty(self) -> None:
        self._write_lines([_make_record("linkedin_post")])
        self.assertEqual([], self.log.read_prior_verdicts("linkedin_post", limit=0))


class PriorVerdictsIntegrationTest(unittest.TestCase):
    """Run Council twice on the same artifact; assert prior verdicts surface."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.config_path = HERE / "council.example.yaml"
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

    def test_second_run_sees_first_verdict_in_adjudicator_context(self) -> None:
        """First run leaves a record; second run injects it into adjudicator context."""
        config = load_config(self.config_path)
        # Run #1.
        c1 = Council(config=config, config_dir=self.config_path.parent)
        v1 = asyncio.run(c1.run(self.artifact_path, tier=1))
        self.assertGreater(len(v1.span_id), len("council-"))

        # Run #2.
        c2 = Council(config=config, config_dir=self.config_path.parent)
        v2 = asyncio.run(c2.run(self.artifact_path, tier=1))
        self.assertNotEqual(v1.span_id, v2.span_id)

        # The second run's adjudicator archive must mention the prior verdict.
        adj_path = (
            self.config_path.parent
            / "test_council_archive"
            / v2.span_id
            / "adjudicator_synthesis.md"
        )
        # Note: adjudicator_synthesis.md captures the model's response, not the
        # prompt. To verify the prior block was injected, we check the
        # persisted log instead — prior_verdicts_used should be > 0.
        rec = json.loads(self.log_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(1, rec["prior_verdicts_used"])

    def test_first_run_has_zero_prior_verdicts(self) -> None:
        config = load_config(self.config_path)
        c = Council(config=config, config_dir=self.config_path.parent)
        asyncio.run(c.run(self.artifact_path, tier=1))
        rec = json.loads(self.log_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(0, rec["prior_verdicts_used"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
