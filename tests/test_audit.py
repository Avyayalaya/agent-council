"""Unit tests for the `audit` subcommand — D3.

Builds a synthetic council_log.jsonl with 30 entries spanning 4 weeks across
5 artifact_types and mixed verdicts. Asserts:

  - markdown report contains all 5 sections
  - --json emits valid JSON with the same aggregates
  - --since=1d filters to the most-recent slice (deterministic)
  - empty log produces a graceful "no data" message + exit code 0
  - missing log file produces EXIT_NOT_FOUND (4)
  - malformed JSON lines are skipped and counted
  - drift detection flags a deliberately monotonic trend in the fixture
  - --out writes to a file instead of stdout
  - override count tracks parth_override entries

The fixture is built deterministically so the assertions stay stable across
runs and across operating systems.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from agent_council.audit import build_report, render_markdown, run_audit  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

ARTIFACT_TYPES = [
    "linkedin_post",
    "substack_post",
    "learnings",
    "memory",
    "resume",
]
DELIBERATORS = ["skeptic", "voice_identity", "evidence", "strategy"]


def _build_record(
    ts: datetime,
    verdict: str,
    artifact_type: str,
    deliberators: dict[str, dict[str, object]] | None = None,
    override: bool = False,
    elapsed: float = 12.0,
    tokens: int | None = None,
) -> dict[str, object]:
    """Build a single verdict record matching the W4 schema."""
    delibs = deliberators or {
        d: {
            "role": d,
            "r1_score": 3,
            "r1_would_block": False,
            "r2_score": 4,
            "r2_would_block": False,
            "r2_irreducible": False,
            "top_issues": [],
            "succeeded": True,
            "error": None,
            "schema_failed": False,
            "reprompts": 0,
        }
        for d in DELIBERATORS
    }
    rec: dict[str, object] = {
        "v": 2,
        "span_id": f"council-{ts.strftime('%Y%m%d%H%M%S')}",
        "parent_id": None,
        "sid": "council-cli",
        "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "agent": "council",
        "event": "verdict",
        "artifact_path": f"./fixture/{artifact_type}_{ts.strftime('%Y%m%d')}.md",
        "artifact_sha256": f"sha-{ts.strftime('%Y%m%d%H%M%S')}",
        "tier": 1,
        "artifact_type": artifact_type,
        "verdict": verdict,
        "deliberators": delibs,
        "elapsed_seconds": elapsed,
        "persisted": True,
    }
    if override:
        rec["parth_override"] = True
    if tokens is not None:
        rec["tokens"] = {"total": tokens}
    return rec


def _build_fixture_30(log_path: Path, now: datetime) -> None:
    """Write a 30-record JSONL spanning 4 weeks across 5 artifact_types.

    Verdict mix is intentionally varied. The ``linkedin_post`` type has a
    monotonic *tightening* trend across weeks 1-3 (verdict score goes from
    1.0 → 0.5 → 0.0) with >=5 records per week, so drift detection should
    flag it.
    """
    lines: list[str] = []
    # Weeks indexed backward from now: week0 = current; week3 = oldest.
    week_anchors = [now - timedelta(days=7 * i) for i in range(4)]

    # 5 linkedin_post records per week — engineer a tightening trend.
    linkedin_verdicts = [
        ["SHIP"] * 5,                                # week3 mean 1.0
        ["SHIP", "SHIP", "REVISE", "REVISE", "REVISE"],  # week2 mean 0.7
        ["REVISE", "REVISE", "HOLD", "HOLD", "HOLD"],    # week1 mean 0.2
        ["HOLD", "HOLD", "HOLD", "HOLD", "HOLD"],         # week0 mean 0.0
    ]
    for i, anchor in enumerate(reversed(week_anchors)):  # oldest -> newest
        for j, verdict in enumerate(linkedin_verdicts[i]):
            ts = anchor + timedelta(hours=j)
            lines.append(json.dumps(
                _build_record(ts, verdict, "linkedin_post", tokens=1200)
            ))

    # 2 substack_post records (small sample — no drift flag expected).
    for i, verdict in enumerate(["SHIP", "REVISE"]):
        ts = week_anchors[0] + timedelta(hours=10 + i)
        lines.append(json.dumps(
            _build_record(ts, verdict, "substack_post", tokens=2400)
        ))

    # 3 learnings records (one with parth_override=True).
    for i, (verdict, override) in enumerate([
        ("SHIP", False), ("REVISE", True), ("SHIP", False),
    ]):
        ts = week_anchors[1] + timedelta(hours=14 + i)
        lines.append(json.dumps(_build_record(
            ts, verdict, "learnings", override=override, tokens=800,
        )))

    # 3 memory records (one with a schema_failed deliberator).
    schema_fail_delibs = {
        d: {
            "role": d, "r1_score": 3, "r1_would_block": False,
            "r2_score": 3, "r2_would_block": False, "r2_irreducible": False,
            "top_issues": [], "succeeded": True, "error": None,
            "schema_failed": (d == "voice_identity"),
            "reprompts": 1 if d == "voice_identity" else 0,
        }
        for d in DELIBERATORS
    }
    for i, verdict in enumerate(["SHIP", "REVISE", "SHIP"]):
        ts = week_anchors[2] + timedelta(hours=8 + i)
        delibs = schema_fail_delibs if i == 0 else None
        lines.append(json.dumps(_build_record(
            ts, verdict, "memory", deliberators=delibs, tokens=600,
        )))

    # 2 resume records (one with a r2_would_block + irreducible).
    block_delibs = {
        d: {
            "role": d, "r1_score": 2, "r1_would_block": True,
            "r2_score": 2,
            "r2_would_block": (d == "skeptic"),
            "r2_irreducible": (d == "skeptic"),
            "top_issues": ["claim X unverified"] if d == "skeptic" else [],
            "succeeded": True, "error": None,
            "schema_failed": False, "reprompts": 0,
        }
        for d in DELIBERATORS
    }
    for i, (verdict, delibs) in enumerate([
        ("HOLD", block_delibs), ("REVISE", None),
    ]):
        ts = week_anchors[3] + timedelta(hours=11 + i)
        lines.append(json.dumps(_build_record(
            ts, verdict, "resume", deliberators=delibs, tokens=1800,
        )))

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class AuditMarkdownTest(unittest.TestCase):
    """End-to-end coverage of the markdown report path."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)
        self.log_path = self.tmp_path / "council_log.jsonl"
        self.now = datetime.now(timezone.utc).replace(microsecond=0)  # date-relative so fixtures don't age out
        _build_fixture_30(self.log_path, self.now)

    def _run(self, **overrides) -> tuple[int, str]:
        """Invoke run_audit with an argparse Namespace; capture stdout."""
        args = argparse.Namespace(
            command="audit",
            log=str(self.log_path),
            since="all",
            config=None,
            output=None,
            json=False,
            min_drift_records=5,
        )
        for k, v in overrides.items():
            setattr(args, k, v)
        buf = io.StringIO()
        real_stdout = sys.stdout
        sys.stdout = buf
        try:
            code = run_audit(args)
        finally:
            sys.stdout = real_stdout
        return code, buf.getvalue()

    def test_total_fixture_size(self) -> None:
        """Sanity — 5+2+3+3+2 = 15 in week1-3, plus 5*4 in linkedin lookups."""
        # We embedded 20 linkedin + 2 substack + 3 learnings + 3 memory +
        # 2 resume = 30 total. Confirm via the report metadata.
        code, md = self._run()
        self.assertEqual(0, code)
        self.assertIn("record count: 30", md)

    def test_markdown_has_all_five_sections(self) -> None:
        code, md = self._run()
        self.assertEqual(0, code)
        # All required H2 headings present.
        self.assertIn("## 1. Verdict Distribution", md)
        self.assertIn("## 2. Deliberator Behavior", md)
        self.assertIn("## 3. Token Spend", md)
        self.assertIn("## 4. Drift Detection", md)
        self.assertIn("## 5. Override Rate", md)

    def test_markdown_verdict_table_has_artifact_types(self) -> None:
        code, md = self._run()
        self.assertEqual(0, code)
        for atype in ARTIFACT_TYPES:
            self.assertIn(atype, md)

    def test_markdown_deliberator_table_lists_all_four(self) -> None:
        code, md = self._run()
        self.assertEqual(0, code)
        for did in DELIBERATORS:
            self.assertIn(did, md)

    def test_markdown_flags_drift_on_linkedin(self) -> None:
        """The linkedin_post fixture trend should be flagged as tightening."""
        code, md = self._run()
        self.assertEqual(0, code)
        # Find the linkedin section of the drift report.
        lp_idx = md.find("### linkedin_post")
        self.assertGreater(lp_idx, 0, "linkedin_post drift section missing")
        section = md[lp_idx: lp_idx + 800]
        self.assertIn("DRIFT FLAGGED", section)
        self.assertIn("tightening", section)

    def test_markdown_override_count_matches_fixture(self) -> None:
        """Fixture has exactly 1 parth_override:true record."""
        code, md = self._run()
        self.assertEqual(0, code)
        # Override section reports "**1** of 30".
        self.assertIn("**1** of 30", md)

    def test_writes_to_output_file_when_set(self) -> None:
        out_file = self.tmp_path / "audit.md"
        code, stdout = self._run(output=str(out_file))
        self.assertEqual(0, code)
        # Nothing on stdout when writing to file.
        self.assertEqual("", stdout.strip())
        self.assertTrue(out_file.exists())
        body = out_file.read_text(encoding="utf-8")
        self.assertIn("Council Audit", body)
        self.assertIn("## 1. Verdict Distribution", body)


class AuditJsonTest(unittest.TestCase):
    """JSON-mode mirror of the markdown coverage."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)
        self.log_path = self.tmp_path / "council_log.jsonl"
        self.now = datetime.now(timezone.utc).replace(microsecond=0)  # date-relative so fixtures don't age out
        _build_fixture_30(self.log_path, self.now)

    def _run_json(self) -> tuple[int, dict]:
        args = argparse.Namespace(
            command="audit",
            log=str(self.log_path),
            since="all",
            config=None,
            output=None,
            json=True,
            min_drift_records=5,
        )
        buf = io.StringIO()
        real_stdout = sys.stdout
        sys.stdout = buf
        try:
            code = run_audit(args)
        finally:
            sys.stdout = real_stdout
        return code, json.loads(buf.getvalue())

    def test_json_has_all_five_sections(self) -> None:
        code, data = self._run_json()
        self.assertEqual(0, code)
        for key in (
            "verdict_distribution",
            "deliberator_behavior",
            "token_spend",
            "drift_detection",
            "override_rate",
            "metadata",
        ):
            self.assertIn(key, data)

    def test_json_drift_linkedin_flagged(self) -> None:
        code, data = self._run_json()
        self.assertEqual(0, code)
        drift = data["drift_detection"]
        self.assertIn("linkedin_post", drift)
        self.assertTrue(drift["linkedin_post"]["flagged"])
        self.assertEqual("tightening", drift["linkedin_post"]["direction"])

    def test_json_override_count_is_one(self) -> None:
        code, data = self._run_json()
        self.assertEqual(0, code)
        self.assertEqual(1, data["override_rate"]["count"])
        self.assertEqual(30, data["override_rate"]["total_records"])

    def test_json_deliberator_block_rate_present(self) -> None:
        code, data = self._run_json()
        self.assertEqual(0, code)
        for did in DELIBERATORS:
            self.assertIn(did, data["deliberator_behavior"])
            self.assertIn("block_rate", data["deliberator_behavior"][did])

    def test_json_token_spend_aggregates(self) -> None:
        code, data = self._run_json()
        self.assertEqual(0, code)
        ts = data["token_spend"]
        self.assertTrue(ts["has_token_field"])
        # 30 records, all have tokens.
        per_type = ts["tokens_by_artifact_type"]
        self.assertEqual(20, per_type["linkedin_post"]["n"])
        self.assertEqual(20 * 1200, per_type["linkedin_post"]["total"])


class AuditFilteringAndEdgeCasesTest(unittest.TestCase):
    """Window filtering, malformed lines, empty log, missing log."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)
        self.now = datetime.now(timezone.utc).replace(microsecond=0)  # date-relative so fixtures don't age out

    def _args(self, log_path: Path, since: str = "all", **kw) -> argparse.Namespace:
        ns = argparse.Namespace(
            command="audit",
            log=str(log_path),
            since=since,
            config=None,
            output=None,
            json=False,
            min_drift_records=5,
        )
        for k, v in kw.items():
            setattr(ns, k, v)
        return ns

    def _capture_run(self, args: argparse.Namespace) -> tuple[int, str]:
        buf = io.StringIO()
        real_stdout = sys.stdout
        sys.stdout = buf
        try:
            code = run_audit(args)
        finally:
            sys.stdout = real_stdout
        return code, buf.getvalue()

    def test_since_1d_window_filters_to_recent_records(self) -> None:
        log_path = self.tmp_path / "council_log.jsonl"
        # Mix: 2 records inside last 24h, 3 records older than 24h.
        recent_ts = self.now - timedelta(hours=2)
        old_ts = self.now - timedelta(days=3)
        recs = (
            [_build_record(recent_ts + timedelta(minutes=i), "SHIP",
                           "linkedin_post") for i in range(2)]
            + [_build_record(old_ts + timedelta(hours=i), "REVISE",
                             "linkedin_post") for i in range(3)]
        )
        log_path.write_text(
            "\n".join(json.dumps(r) for r in recs) + "\n",
            encoding="utf-8",
        )

        args = self._args(log_path, since="1d", json=True)
        buf = io.StringIO()
        real_stdout = sys.stdout
        sys.stdout = buf
        try:
            code = run_audit(args)
        finally:
            sys.stdout = real_stdout
        self.assertEqual(0, code)
        data = json.loads(buf.getvalue())
        self.assertEqual(2, data["metadata"]["record_count"])

    def test_empty_log_exits_clean_with_no_data_message(self) -> None:
        log_path = self.tmp_path / "council_log.jsonl"
        log_path.write_text("", encoding="utf-8")
        code, md = self._capture_run(self._args(log_path, since="all"))
        self.assertEqual(0, code)
        self.assertIn("No gates recorded in window", md)

    def test_missing_log_returns_not_found(self) -> None:
        log_path = self.tmp_path / "absent.jsonl"
        code, stderr = self._capture_run(self._args(log_path, since="all"))
        self.assertEqual(4, code)

    def test_malformed_lines_skipped_and_counted(self) -> None:
        log_path = self.tmp_path / "council_log.jsonl"
        # 2 valid records + 2 malformed lines.
        valid = [
            _build_record(self.now - timedelta(hours=i), "SHIP",
                          "linkedin_post")
            for i in range(2)
        ]
        lines = [
            json.dumps(valid[0]),
            "not valid json {",
            json.dumps(valid[1]),
            "[also broken",
        ]
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        args = self._args(log_path, since="all", json=True)
        buf = io.StringIO()
        real_stdout = sys.stdout
        sys.stdout = buf
        try:
            code = run_audit(args)
        finally:
            sys.stdout = real_stdout
        self.assertEqual(0, code)
        data = json.loads(buf.getvalue())
        self.assertEqual(2, data["metadata"]["record_count"])
        self.assertEqual(2, data["metadata"]["malformed_lines"])

    def test_missing_artifact_type_buckets_as_unknown(self) -> None:
        log_path = self.tmp_path / "council_log.jsonl"
        rec = _build_record(self.now, "SHIP", "linkedin_post")
        del rec["artifact_type"]
        log_path.write_text(json.dumps(rec) + "\n", encoding="utf-8")
        args = self._args(log_path, since="all", json=True)
        buf = io.StringIO()
        real_stdout = sys.stdout
        sys.stdout = buf
        try:
            code = run_audit(args)
        finally:
            sys.stdout = real_stdout
        self.assertEqual(0, code)
        data = json.loads(buf.getvalue())
        self.assertIn(
            "unknown_type",
            data["verdict_distribution"]["by_artifact_type"],
        )


class AuditUnitTest(unittest.TestCase):
    """Direct coverage of pure-function aggregators (no I/O)."""

    def test_build_report_with_empty_records_returns_zeroed_aggregates(self) -> None:
        report = build_report(
            records=[],
            log_path=Path("/tmp/none.jsonl"),
            cutoff=None,
            since_label="all",
            malformed=0,
        )
        self.assertEqual(0, report["metadata"]["record_count"])
        self.assertEqual({}, report["verdict_distribution"]["overall"])
        self.assertEqual({}, report["deliberator_behavior"])
        self.assertEqual(0, report["override_rate"]["count"])

    def test_render_markdown_empty_returns_no_data_message(self) -> None:
        report = build_report(
            records=[],
            log_path=Path("/tmp/none.jsonl"),
            cutoff=None,
            since_label="7d",
            malformed=0,
        )
        md = render_markdown(report)
        self.assertIn("No gates recorded in window", md)

    def test_drift_min_records_gate_prevents_false_positive(self) -> None:
        """Below the min_records floor, a steep trend should NOT flag."""
        # 3 weeks × 3 records (under floor of 5) with extreme trend.
        recs = []
        now = datetime(2026, 5, 11, tzinfo=timezone.utc)
        for week_offset in range(3):
            verdict = ["SHIP", "REVISE", "HOLD"][week_offset]
            anchor = now - timedelta(days=7 * week_offset)
            for j in range(3):
                recs.append(_build_record(
                    anchor + timedelta(hours=j),
                    verdict,
                    "linkedin_post",
                ))
        report = build_report(
            records=recs,
            log_path=Path("/tmp/none.jsonl"),
            cutoff=None,
            since_label="all",
            malformed=0,
            min_drift_records=5,
        )
        self.assertFalse(
            report["drift_detection"]["linkedin_post"]["flagged"],
            "Drift should not flag below min_records floor",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
