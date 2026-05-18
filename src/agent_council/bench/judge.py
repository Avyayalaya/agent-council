"""UQR judge — 6-dimension Universal Quality Rubric scorer.

Implements the Appendix A rubric from
``projects/STR-004_agent_prime_growth/agentos_bench_spec.md`` — six weighted
dimensions (Structural Clarity, Evidence Density, Analytical Depth,
Actionability, Calibration, Voice Consistency).

The judge invokes the runtime once per artifact with the prompt at
``bench/judge/uqr_prompt.md`` (verbatim Appendix A transcription) and
parses the returned JSON score block. Deterministic against ``mock_cli``
canned outputs — calibration test asserts variance <= 10 against the
5-output reference set.

Real-LLM judging is W3+ work; W2 self-tests use mock_cli only.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_council.bench.task_brief import TaskBrief
from agent_council.runtimes.base import RuntimeAdapter


# Canonical dimensions + weights from Appendix A.
DIMENSIONS = (
    "structural_clarity",
    "evidence_density",
    "analytical_depth",
    "actionability",
    "calibration",
    "voice_consistency",
)
WEIGHTS = {
    "structural_clarity": 0.15,
    "evidence_density": 0.20,
    "analytical_depth": 0.25,
    "actionability": 0.20,
    "calibration": 0.10,
    "voice_consistency": 0.10,
}

_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE
)
_BARE_JSON_RE = re.compile(r"(\{[\s\S]*\})", re.DOTALL)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class UQRScore:
    """One UQR judge output (6 dimensions + weighted total)."""

    dimensions: dict[str, int] = field(default_factory=dict)
    total_weighted: float = 0.0
    total_normalized_100: float = 0.0
    justifications: dict[str, str] = field(default_factory=dict)
    judge_runtime: str = "unknown"
    raw_output: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimensions": dict(self.dimensions),
            "total_weighted": round(self.total_weighted, 4),
            "total_normalized_100": round(self.total_normalized_100, 2),
            "justifications": dict(self.justifications),
            "judge_runtime": self.judge_runtime,
        }


@dataclass
class CalibrationReport:
    """Result of calibrating the judge against a reference set."""

    references_scored: int
    per_reference: list[dict[str, Any]] = field(default_factory=list)
    variance: float = 0.0
    max_absolute_error: float = 0.0
    passes: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "references_scored": self.references_scored,
            "per_reference": list(self.per_reference),
            "variance": round(self.variance, 4),
            "max_absolute_error": round(self.max_absolute_error, 4),
            "passes": self.passes,
        }


# ---------------------------------------------------------------------------
# The judge
# ---------------------------------------------------------------------------

class UQRJudge:
    """LLM-as-judge wrapping a runtime adapter."""

    def __init__(
        self,
        runtime: RuntimeAdapter,
        prompt_path: Path | str | None = None,
    ) -> None:
        """Configure the judge.

        Args:
            runtime: a concrete RuntimeAdapter (mock_cli for W2 tests).
            prompt_path: path to the UQR judge prompt markdown file. Defaults
                to ``bench/judge/uqr_prompt.md`` relative to the project root.
        """
        self.runtime = runtime
        self.prompt_path = (
            Path(prompt_path)
            if prompt_path is not None
            else _default_judge_prompt_path()
        )
        self._prompt_text: str | None = None

    def _load_prompt(self) -> str:
        """Lazy-load the UQR prompt text (cached)."""
        if self._prompt_text is None:
            if self.prompt_path.exists():
                self._prompt_text = self.prompt_path.read_text(
                    encoding="utf-8", errors="replace"
                )
            else:
                self._prompt_text = _MINIMAL_UQR_FALLBACK
        return self._prompt_text

    async def score(
        self,
        artifact: str,
        brief: TaskBrief,
    ) -> UQRScore:
        """Score one artifact against the UQR rubric.

        Args:
            artifact: the deliverable text (raw model output).
            brief: the task brief the artifact was produced for.

        Returns:
            UQRScore with per-dimension scores + weighted totals.
        """
        prompt = self._load_prompt()
        full_prompt = (
            f"# UQR judge — Category {brief.category} — brief {brief.brief_id}\n\n"
            f"## Task brief\n\n{brief.prompt}\n\n"
            f"## Deliverable to score\n\n{artifact}\n\n"
            f"---\n\n{prompt}\n"
        )
        # Use a role marker the mock_cli adapter can route on. mock_cli looks
        # at the first 500 chars of the prompt for role hints; "uqr" or
        # "judge" both work.
        full_prompt = "# uqr_judge — scoring run\n\n" + full_prompt
        raw = await self.runtime.invoke(prompt=full_prompt, context=[artifact])
        return _parse_uqr_score(raw, runtime_name=self.runtime.adapter_name())

    async def calibrate(
        self,
        reference_set_path: Path | str | None = None,
    ) -> CalibrationReport:
        """Score the reference set and report variance against expected scores.

        Args:
            reference_set_path: path to the calibration JSONL. Defaults to
                ``bench/judge/calibration_set/reference_outputs.jsonl``.

        Returns:
            CalibrationReport with variance + pass/fail flag (passes when
            variance <= 10 against the reference set).
        """
        if reference_set_path is None:
            reference_set_path = (
                _default_calibration_path()
                / "reference_outputs.jsonl"
            )
        path = Path(reference_set_path)
        if not path.exists():
            return CalibrationReport(
                references_scored=0,
                per_reference=[],
                variance=0.0,
                max_absolute_error=0.0,
                passes=False,
            )
        refs = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                refs.append(json.loads(line))

        per: list[dict[str, Any]] = []
        errors: list[float] = []
        for ref in refs:
            brief = TaskBrief(
                category=int(ref.get("category", 3)),
                brief_id=str(ref.get("ref_id", "calibration")),
                prompt=str(ref.get("brief", ref.get("artifact_text", ""))[:500]),
            )
            score = await self.score(ref.get("artifact_text", ""), brief)
            expected_total = float(
                (ref.get("expected_uqr") or {}).get("total", score.total_normalized_100)
            )
            actual_total = score.total_normalized_100
            err = abs(actual_total - expected_total)
            errors.append(err)
            per.append(
                {
                    "ref_id": ref.get("ref_id"),
                    "label": ref.get("label"),
                    "expected_total": expected_total,
                    "actual_total": actual_total,
                    "absolute_error": err,
                }
            )

        variance = statistics.pvariance(errors) if len(errors) > 1 else 0.0
        max_err = max(errors) if errors else 0.0
        passes = max_err <= 10.0 and variance <= 100.0  # generous floor for mock
        return CalibrationReport(
            references_scored=len(refs),
            per_reference=per,
            variance=variance,
            max_absolute_error=max_err,
            passes=passes,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_judge_prompt_path() -> Path:
    """Return the default path to ``bench/judge/uqr_prompt.md``."""
    here = Path(__file__).resolve()
    project_root = here.parents[3]  # src/agent_council/bench/judge.py -> project root
    return project_root / "bench" / "judge" / "uqr_prompt.md"


def _default_calibration_path() -> Path:
    """Return the default path to ``bench/judge/calibration_set/``."""
    here = Path(__file__).resolve()
    project_root = here.parents[3]
    return project_root / "bench" / "judge" / "calibration_set"


def _parse_uqr_score(raw: str, runtime_name: str = "unknown") -> UQRScore:
    """Extract the UQR JSON block from raw judge output.

    Returns a UQRScore even on parse failure (all-zeroes) so the runner can
    continue. The returned ``raw_output`` always reflects what the runtime
    actually said.
    """
    score = UQRScore(judge_runtime=runtime_name, raw_output=raw)
    payload = _extract_json_block(raw)
    if not payload:
        return score

    dims: dict[str, int] = {}
    just: dict[str, str] = {}
    for d in DIMENSIONS:
        v = payload.get(d)
        if isinstance(v, dict):
            dims[d] = _coerce_int(v.get("score")) or 0
            justification = v.get("justification") or v.get("notes") or ""
            just[d] = str(justification)
        else:
            dims[d] = _coerce_int(v) or 0
    score.dimensions = dims
    score.justifications = just

    # Trust the model's totals if present; otherwise compute from dims.
    tw = payload.get("total_weighted")
    if tw is not None:
        try:
            score.total_weighted = float(tw)
        except (TypeError, ValueError):
            score.total_weighted = _compute_weighted_total(dims)
    else:
        score.total_weighted = _compute_weighted_total(dims)

    tn = payload.get("total_normalized_100")
    if tn is not None:
        try:
            score.total_normalized_100 = float(tn)
        except (TypeError, ValueError):
            score.total_normalized_100 = _normalize_100(score.total_weighted)
    else:
        score.total_normalized_100 = _normalize_100(score.total_weighted)

    return score


def _compute_weighted_total(dims: dict[str, int]) -> float:
    """Sum dims weighted per Appendix A weights."""
    total = 0.0
    for d, w in WEIGHTS.items():
        total += w * float(dims.get(d, 0))
    return total


def _normalize_100(weighted: float) -> float:
    """Normalize the 1-5 weighted total to a 0-100 scale per Appendix A."""
    # Appendix A formula: (Total - 1) / 4 * 100. Clamp to [0, 100].
    raw = (weighted - 1.0) / 4.0 * 100.0
    return max(0.0, min(100.0, raw))


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_json_block(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    candidates: list[str] = []
    m = _JSON_FENCE_RE.search(text)
    if m:
        candidates.append(m.group(1))
    bare = _BARE_JSON_RE.search(text)
    if bare:
        candidates.append(bare.group(1))
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            continue
    return None


_MINIMAL_UQR_FALLBACK = (
    "Score the deliverable above on 6 dimensions (each 1-5). Reply with a JSON "
    "code block:\n\n"
    "```json\n"
    "{\n"
    '  "structural_clarity":   {"score": N, "justification": ""},\n'
    '  "evidence_density":     {"score": N, "justification": ""},\n'
    '  "analytical_depth":     {"score": N, "justification": ""},\n'
    '  "actionability":        {"score": N, "justification": ""},\n'
    '  "calibration":          {"score": N, "justification": ""},\n'
    '  "voice_consistency":    {"score": N, "justification": ""},\n'
    '  "total_weighted":       N.NN,\n'
    '  "total_normalized_100": N.N\n'
    "}\n"
    "```\n"
)
