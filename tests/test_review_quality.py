"""Review-contract regression tests; scripted outputs do not measure model quality."""

import asyncio
import contextlib
import io
import json
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_council.cli import main
from agent_council.config import load_config
from agent_council.log import CouncilLog
from agent_council.orchestrator import Council
from agent_council.schema import validate
from tests.test_schema_enforcement import ScriptedAdapter, _wrap


FINDING = {
    "location": 'Paragraph 2: "The new process caused a 50% reduction."',
    "concern": "The causal claim goes beyond the supplied evidence.",
    "basis": "The supplied two-team report has no comparison group.",
    "impact": "Readers could mistake an early observation for an established effect.",
    "resolution": "Describe the observed reduction without attributing its cause.",
}


class ReviewQualityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.artifact = self.folder / "artifact.md"
        self.original = "Two teams reported shorter review times. This is an early observation.\n"
        self.artifact.write_text(self.original, encoding="utf-8")
        self.config = load_config(ROOT / "tests" / "council.example.yaml")
        for role in self.config["deliberators"]:
            role["prompt"] = str((ROOT / "tests" / role["prompt"]).resolve())
        self.config["adjudicator"]["prompt"] = str(ROOT / "prompts" / "adjudicator.md")
        self.config["logging"] = {
            "log_path": str(self.folder / "log.jsonl"),
            "archive_dir": str(self.folder / "archive"),
        }

    def council(self, adapter):
        return Council(self.config, ROOT, adapter=adapter)

    def record(self):
        return json.loads((self.folder / "log.jsonl").read_text(encoding="utf-8").splitlines()[-1])

    def test_archive_and_returned_hash_identify_the_reviewed_version(self):
        artifact = self.artifact

        class EditingAdapter(ScriptedAdapter):
            async def invoke(self, prompt, context, model=None):
                artifact.write_text("Changed while the review was running.\n", encoding="utf-8")
                return await super().invoke(prompt, context, model)

        result = asyncio.run(self.council(EditingAdapter({})).run(self.artifact))
        archive = self.folder / "archive" / result.span_id / "artifact.md"
        self.assertEqual(self.original, archive.read_text(encoding="utf-8"))
        expected_hash = CouncilLog.hash_artifact(self.original)
        self.assertEqual(expected_hash, result.artifact_sha256)
        self.assertEqual(expected_hash, result.to_dict()["artifact_sha256"])
        self.assertEqual(expected_hash, self.record()["artifact_sha256"])
        self.assertNotEqual(expected_hash, CouncilLog.hash_artifact(self.artifact.read_text(encoding="utf-8")))

    def test_brief_reaches_each_round_and_synthesis_and_is_archived(self):
        brief = "Audience: team leads. Purpose: share an early result, not promise a causal effect."
        adapter = ScriptedAdapter({})
        result = asyncio.run(self.council(adapter).run(self.artifact, review_brief=brief))
        self.assertEqual(9, sum(adapter.call_count.values()))
        for contexts in adapter.contexts.values():
            for context in contexts:
                self.assertIn(brief, "\n".join(context))
        archive = self.folder / "archive" / result.span_id / "review_brief.md"
        self.assertEqual(brief, archive.read_text(encoding="utf-8"))
        self.assertEqual(CouncilLog.hash_artifact(brief), self.record()["review_brief_sha256"])

    def test_invalid_brief_fails_before_any_review(self):
        for brief in (" ", 4):
            with self.subTest(brief=brief):
                adapter = ScriptedAdapter({})
                with self.assertRaisesRegex(ValueError, "review_brief"):
                    asyncio.run(self.council(adapter).run(self.artifact, review_brief=brief))
                self.assertEqual({}, adapter.call_count)
        self.assertFalse((self.folder / "log.jsonl").exists())

    def test_multiline_brief_archive_preserves_exact_reviewed_bytes(self):
        for newline in ("\r\n", "\n", "\r"):
            with self.subTest(newline=repr(newline)):
                brief = newline.join((
                    "Audience: caf\u00e9 owners.",
                    "Purpose: report an early observation.",
                    "",
                    "Constraint: do not invent a rollout promise.",
                )) + newline
                adapter = ScriptedAdapter({})
                result = asyncio.run(self.council(adapter).run(self.artifact, review_brief=brief))
                archive = self.folder / "archive" / result.span_id / "review_brief.md"
                archived_bytes = archive.read_bytes()
                self.assertEqual(brief.encode("utf-8"), archived_bytes)
                expected_hash = CouncilLog.hash_artifact(brief)
                self.assertEqual(expected_hash, CouncilLog.hash_artifact(archived_bytes.decode("utf-8")))
                self.assertEqual(expected_hash, result.review_brief_sha256)
                self.assertEqual(expected_hash, result.to_dict()["review_brief_sha256"])
                self.assertEqual(expected_hash, self.record()["review_brief_sha256"])
                self.assertEqual(9, sum(adapter.call_count.values()))
                for contexts in adapter.contexts.values():
                    for context in contexts:
                        self.assertIn(brief, "\n".join(context))

    def test_good_work_can_ship_without_invented_changes(self):
        adapter = ScriptedAdapter({})
        clean = {"score": 4, "would_block": False, "irreducible": False, "findings": [],
                 "strengths": ["The conclusion accurately describes the evidence's limits."]}
        for role in ("skeptic", "voice_identity", "evidence", "strategy"):
            adapter.set_script(role, [_wrap(clean)])
        adapter.set_script("adjudicator", [_wrap({
            "verdict": "SHIP", "reasoning": "The claims match the supplied support.",
            "strengths": clean["strengths"],
        })])
        result = asyncio.run(self.council(adapter).run(self.artifact))
        self.assertEqual("SHIP", result.verdict)
        self.assertIsNone(result.revision_brief)
        self.assertEqual(clean["strengths"], result.strengths)
        self.assertEqual(9, sum(adapter.call_count.values()))
        for review in result.deliberators.values():
            self.assertEqual([], review.r1_findings)
            self.assertEqual([], review.r2_findings)

    def test_material_finding_preserves_basis_impact_and_resolution(self):
        adapter = ScriptedAdapter({})
        payload = {"score": 2, "would_block": True, "irreducible": False, "findings": [FINDING]}
        adapter.set_script("evidence", [_wrap(payload)])
        result = asyncio.run(self.council(adapter).run(self.artifact))
        self.assertEqual("REVISE", result.verdict)
        evidence = result.to_dict()["deliberators"]["evidence"]
        self.assertEqual([FINDING], evidence["r1_findings"])
        self.assertEqual([FINDING], evidence["r2_findings"])
        for key in ("basis", "impact", "resolution"):
            self.assertIn(FINDING[key], result.revision_brief)
        self.assertIn(FINDING["basis"], "\n".join(adapter.contexts["adjudicator"][0]))
        self.assertEqual(evidence["r2_findings"], self.record()["deliberators"]["evidence"]["r2_findings"])

    def test_retracted_r1_finding_is_not_reintroduced_by_fallback_brief(self):
        adapter = ScriptedAdapter({})
        adapter.set_script("evidence", [
            _wrap({"score": 2, "would_block": True, "findings": [FINDING]}),
            _wrap({"score": 4, "would_block": False, "irreducible": False, "findings": [],
                   "concessions": ["The supplied wording already limits the claim."]}),
        ])
        adapter.set_script("adjudicator", [_wrap({"verdict": "REVISE", "reasoning": "An unrelated decision remains."})])
        result = asyncio.run(self.council(adapter).run(self.artifact))
        self.assertNotIn(FINDING["concern"], result.revision_brief)
        self.assertIn("The supplied wording already limits the claim.", result.dissent_summary)
        self.assertEqual([FINDING], result.to_dict()["deliberators"]["evidence"]["r1_findings"])

    def test_omitted_r2_findings_are_distinct_from_an_explicit_empty_list(self):
        adapter = ScriptedAdapter({})
        adapter.set_script("evidence", [
            _wrap({"score": 2, "would_block": True, "findings": [FINDING]}),
            _wrap({"score": 2, "would_block": True, "irreducible": False}),
        ])
        result = asyncio.run(self.council(adapter).run(self.artifact))
        self.assertIsNone(result.to_dict()["deliberators"]["evidence"]["r2_findings"])
        self.assertIn(FINDING["resolution"], result.revision_brief)

    def test_legacy_violations_remain_visible_without_inventing_missing_detail(self):
        adapter = ScriptedAdapter({})
        legacy = {"score": 2, "would_block": True, "irreducible": False,
                  "violations": [{"line": 2, "rule": "C9", "snippet": "except: pass", "fix": "Report the failure."}]}
        adapter.set_script("voice_identity", [_wrap(legacy)])
        result = asyncio.run(self.council(adapter).run(self.artifact))
        finding = result.to_dict()["deliberators"]["voice_identity"]["r1_findings"][0]
        self.assertIn("except: pass", finding["location"])
        self.assertEqual("C9", finding["basis"])
        self.assertEqual("Report the failure.", finding["resolution"])
        self.assertEqual("", finding["impact"])
        self.assertTrue(result.deliberators["voice_identity"].top_issues)

    def test_optional_finding_shape_is_validated_but_legacy_output_still_works(self):
        base = {"score": 4, "would_block": False}
        self.assertTrue(validate(base, "skeptic", 1)[0])
        self.assertTrue(validate({**base, "findings": [FINDING], "strengths": []}, "skeptic", 1)[0])
        for invalid in ([{}], ["vague concern"], [{**FINDING, "resolution": ""}]):
            with self.subTest(invalid=invalid):
                self.assertFalse(validate({**base, "findings": invalid}, "skeptic", 1)[0])
        self.assertFalse(validate({**base, "strengths": [False]}, "skeptic", 1)[0])

    def test_malformed_findings_get_only_the_existing_schema_retry(self):
        adapter = ScriptedAdapter({})
        valid = {"score": 3, "would_block": False, "irreducible": False, "findings": []}
        adapter.set_script("evidence", [
            _wrap({**valid, "findings": [{"concern": "vague"}]}), _wrap(valid), _wrap(valid),
        ])
        result = asyncio.run(self.council(adapter).run(self.artifact))
        self.assertEqual("SHIP", result.verdict)
        self.assertEqual(3, adapter.call_count["evidence"])
        self.assertEqual(1, self.record()["deliberators"]["evidence"]["reprompts"])

    def test_optional_suggestions_and_strengths_are_separate_and_exact_duplicates_removed(self):
        adapter = ScriptedAdapter({})
        optional = "Consider defining the metric before a later experiment."
        keep = "Keep the cautious wording."
        adapter.set_script("adjudicator", [_wrap({
            "verdict": "SHIP", "reasoning": "The note can stand as written.",
            "optional_suggestions": [optional, optional], "strengths": [keep, keep],
        })])
        result = asyncio.run(self.council(adapter).run(self.artifact))
        self.assertEqual("SHIP", result.verdict)
        self.assertIsNone(result.revision_brief)
        self.assertEqual([optional], result.optional_suggestions)
        self.assertEqual([keep], result.strengths)
        self.assertEqual([optional], result.to_dict()["optional_suggestions"])
        self.assertEqual([optional], self.record()["optional_suggestions"])
        self.assertEqual([optional, optional], result.adjudicator_raw["optional_suggestions"])

    def test_optional_suggestions_do_not_substitute_for_a_missing_required_brief(self):
        adapter = ScriptedAdapter({})
        optional = "Consider a follow-up study if you later need a broader claim."
        adapter.set_script("adjudicator", [_wrap({
            "verdict": "REVISE", "reasoning": "A required change was not specified.",
            "optional_suggestions": [optional],
        })])
        result = asyncio.run(self.council(adapter).run(self.artifact))
        self.assertEqual("REVISE", result.verdict)
        self.assertIn("No actionable revision brief", result.revision_brief)
        self.assertNotIn(optional, result.revision_brief)
        self.assertEqual([optional], result.optional_suggestions)

    def test_optional_suggestion_shape_is_validated_and_omission_is_compatible(self):
        for role, round_num, base in (
            ("skeptic", 1, {"score": 4, "would_block": False}),
            ("evidence", 2, {"score": 4, "would_block": False, "irreducible": False}),
            ("adjudicator", 3, {"verdict": "SHIP", "reasoning": "Sound work."}),
        ):
            with self.subTest(role=role):
                self.assertTrue(validate(base, role, round_num)[0])
                self.assertTrue(validate({**base, "optional_suggestions": []}, role, round_num)[0])
                for invalid in ("not a list", [False], [None], [" "]):
                    self.assertFalse(validate({**base, "optional_suggestions": invalid}, role, round_num)[0])

    def test_cli_keeps_required_optional_and_preserved_content_in_separate_sections(self):
        adapter = ScriptedAdapter({})
        required = "1. Narrow the unsupported claim in paragraph 2."
        optional = "Consider a definition for future measurement."
        keep = "Keep the short invitation."
        adapter.set_script("adjudicator", [_wrap({
            "verdict": "REVISE", "reasoning": "One necessary correction.",
            "revision_brief": required, "optional_suggestions": [optional], "strengths": [keep],
        })])
        output = io.StringIO()
        with patch("agent_council.cli.load_config", return_value=self.config), \
             patch("agent_council.orchestrator.build_adapter", return_value=adapter), \
             contextlib.redirect_stdout(output):
            code = main(["review", str(self.artifact), "--config=unused.yaml"])
        self.assertEqual(1, code)
        text = output.getvalue()
        self.assertIn("Required changes:\n  " + required, text)
        self.assertIn("Optional suggestions (not required to ship):\n  - " + optional, text)
        self.assertIn("What to preserve:\n  - " + keep, text)
        self.assertLess(text.index(required), text.index(optional))
        self.assertEqual(1, text.count(required))

    def test_invocations_request_only_the_current_round(self):
        class RecordingAdapter(ScriptedAdapter):
            def __init__(self):
                super().__init__({})
                self.prompts = []

            async def invoke(self, prompt, context, model=None):
                self.prompts.append(prompt)
                return await super().invoke(prompt, context, model)

        adapter = RecordingAdapter()
        asyncio.run(self.council(adapter).run(self.artifact))
        self.assertEqual(9, len(adapter.prompts))
        for prompt in adapter.prompts[:4]:
            self.assertIn("This invocation is Round 1 only", prompt)
            self.assertIn("one flat JSON object", prompt)
        for prompt in adapter.prompts[4:8]:
            self.assertIn("This invocation is Round 2 only", prompt)

    def test_cli_displays_preserved_strengths_and_r1_fallback_block(self):
        adapter = ScriptedAdapter({})
        adapter.set_script("skeptic", [
            _wrap({"score": 3, "would_block": True}), RuntimeError("R2 unavailable"),
        ])
        adapter.set_script("adjudicator", [_wrap({
            "verdict": "REVISE", "reasoning": "One concern remains.",
            "strengths": ["Preserve the measured introduction."],
        })])
        output = io.StringIO()
        with patch("agent_council.cli.load_config", return_value=self.config), \
             patch("agent_council.orchestrator.build_adapter", return_value=adapter), \
             contextlib.redirect_stdout(output):
            code = main(["review", str(self.artifact), "--config=unused.yaml"])
        self.assertEqual(1, code)
        self.assertIn("What to preserve:", output.getvalue())
        self.assertIn("Preserve the measured introduction.", output.getvalue())
        line = next(line for line in output.getvalue().splitlines() if "skeptic" in line and "r1=" in line)
        self.assertIn("BLOCK", line)

    def test_mcp_forwards_brief_and_preserves_new_result_fields(self):
        class StubMCP:
            def __init__(self, name):
                self.name = name

            def tool(self):
                return lambda function: function

        module = types.ModuleType("mcp.server.fastmcp")
        module.FastMCP = StubMCP
        with patch.dict(sys.modules, {"mcp.server.fastmcp": module}):
            namespace = runpy.run_path(str(ROOT / "mcp" / "agent_council_mcp_server.py"))
        callback = namespace["council_review"]
        adapter = ScriptedAdapter({})
        brief = "Share a measured observation with team leads."
        with patch.dict(callback.__globals__, {"load_config": lambda path: self.config}), \
             patch("agent_council.orchestrator.build_adapter", return_value=adapter):
            result = asyncio.run(callback(str(self.artifact), config="unused.yaml", review_brief=brief))
        self.assertEqual(CouncilLog.hash_artifact(self.original), result["artifact_sha256"])
        self.assertIn("r1_findings", result["deliberators"]["skeptic"])
        self.assertEqual([], result["optional_suggestions"])
        self.assertIn(brief, "\n".join(adapter.contexts["adjudicator"][0]))

    def test_all_reviewer_surfaces_allow_clean_work_and_ground_findings(self):
        pairs = {
            "skeptic": "skeptic-review", "voice_identity": "voice-identity-review",
            "evidence": "evidence-calibration-review", "strategy": "strategy-stakes-review",
        }
        for prompt, skill in pairs.items():
            for path in (ROOT / "prompts" / f"{prompt}.md", ROOT / "skills" / skill / "SKILL.md"):
                with self.subTest(path=path):
                    text = path.read_text(encoding="utf-8").lower()
                    for principle in ("no quota", "empty findings are valid", "preserve", "resolution"):
                        self.assertIn(principle, text)
                    self.assertIn("facts, commitments or scope", text)
                    self.assertIn("optional_suggestions", text)
        # These are prompt-contract checks, not a claim that real models follow every instruction.

    def test_synthesis_guidance_separates_actions_without_new_promises(self):
        for path in (
            ROOT / "prompts" / "adjudicator.md",
            ROOT / "skills" / "adjudicator-synthesis" / "SKILL.md",
        ):
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8").lower()
                self.assertIn("commitments", text)
                self.assertIn("author did not supply", text)
                self.assertIn("optional_suggestions", text)
                self.assertIn("each required change once", text)

    def test_cli_brief_file_and_human_output(self):
        brief_file = self.folder / "brief.md"
        brief_file.write_text("Preserve the author's measured tone.", encoding="utf-8")
        adapter = ScriptedAdapter({})
        output = io.StringIO()
        with patch("agent_council.cli.load_config", return_value=self.config), \
             patch("agent_council.orchestrator.build_adapter", return_value=adapter), \
             contextlib.redirect_stdout(output):
            code = main(["review", str(self.artifact), "--config=unused.yaml", "--brief-file", str(brief_file)])
        self.assertEqual(0, code)
        self.assertIn("Reviewed version:", output.getvalue())
        self.assertIn(brief_file.read_text(encoding="utf-8"), "\n".join(adapter.contexts["adjudicator"][0]))

    def test_cli_missing_brief_does_not_start_model_calls(self):
        adapter = ScriptedAdapter({})
        with patch("agent_council.cli.load_config", return_value=self.config), \
             patch("agent_council.orchestrator.build_adapter", return_value=adapter), \
             contextlib.redirect_stderr(io.StringIO()):
            code = main(["review", str(self.artifact), "--config=unused.yaml",
                         "--brief-file", str(self.folder / "absent.md")])
        self.assertNotEqual(0, code)
        self.assertEqual({}, adapter.call_count)


if __name__ == "__main__":
    unittest.main()
