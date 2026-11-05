"""Verdict dataclass + SHIP/REVISE/HOLD policy engine.

Numeric score and block thresholds come from
``council.yaml#adjudicator.verdict_policy``. Only successful R1 reviewers
participate; valid R2 takes precedence, with valid-R1 fallback.

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
LEGACY_FINDING_FIELDS = (
    "voice_violations", "violations", "top_3_failure_modes",
    "top_3_issues", "calibration_issues",
)


@dataclass
class ReviewFinding:
    """One reviewer's stated concern and grounds, not independently verified evidence."""

    location: str = ""
    concern: str = ""
    basis: str = ""
    impact: str = ""
    resolution: str = ""

    def describe(self) -> str:
        parts = [self.concern]
        for label, value in (
            ("Location", self.location), ("Basis", self.basis),
            ("Why it matters", self.impact), ("Resolution", self.resolution),
        ):
            if value:
                parts.append(f"{label}: {value}")
        return "; ".join(parts)


def normalize_findings(payload: dict[str, Any]) -> list[ReviewFinding]:
    """Preserve new findings and known legacy shapes without inventing absent detail."""
    if "findings" in payload:
        return [
            ReviewFinding(
                location=item["location"], concern=item["concern"], basis=item["basis"],
                impact=item["impact"], resolution=item["resolution"],
            )
            for item in payload["findings"]
        ]

    def text(value: Any) -> str:
        return value if isinstance(value, str) else ""

    # Prefer structured legacy records to headline-only summaries.
    items = next((payload[key] for key in LEGACY_FINDING_FIELDS if payload.get(key)), [])
    findings: list[ReviewFinding] = []
    if not isinstance(items, list):
        return findings
    for item in items:
        if isinstance(item, str):
            findings.append(ReviewFinding(concern=item))
        elif isinstance(item, dict):
            snippet = text(item.get("snippet"))
            rule = text(item.get("rule"))
            line = item.get("line")
            location = f"Line {line}: {snippet}" if isinstance(line, (int, str)) else snippet
            findings.append(ReviewFinding(
                location=location, concern=text(item.get("concern")) or snippet or rule,
                basis=rule, resolution=text(item.get("fix")),
            ))
    return findings


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
    r2_concessions: list[str] = field(default_factory=list)
    r2_escalations: list[str] = field(default_factory=list)
    raw_r1: dict[str, Any] | None = None
    raw_r2: dict[str, Any] | None = None
    error: str | None = None  # R1 failure; R2 failure permits valid-R1 fallback
    r1_schema_failed: bool = False
    r2_schema_failed: bool = False
    r2_error: str | None = None
    r1_findings: list[ReviewFinding] = field(default_factory=list)
    r2_findings: list[ReviewFinding] | None = None

    @property
    def succeeded(self) -> bool:
        """True if R1 is present and has no reported runtime/schema failure."""
        return (
            self.error is None
            and self.raw_r1 is not None
            and not self.r1_schema_failed
        )


@dataclass
class Verdict:
    """The Council's final verdict on an artifact.

    Verdict values: SHIP | REVISE | HOLD | INCOMPLETE.
    INCOMPLETE means fewer than ``min_deliberators_for_verdict`` produced valid
    R1 output, or synthesis failed. R2 failures permit valid-R1 fallback.
    """

    verdict: str
    reasoning: str = ""
    revision_brief: str | None = None
    dissent_summary: str = ""
    deliberators: dict[str, DeliberatorResult] = field(default_factory=dict)
    adjudicator_raw: dict[str, Any] | None = None
    span_id: str = ""
    adjudicator_error: str | None = None
    artifact_sha256: str = ""
    review_brief_sha256: str | None = None
    strengths: list[str] = field(default_factory=list)
    optional_suggestions: list[str] = field(default_factory=list)

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
                    "r2_concessions": v.r2_concessions,
                    "r2_escalations": v.r2_escalations,
                    "top_issues": v.top_issues,
                    "succeeded": v.succeeded,
                    "error": v.error,
                    "r1_schema_failed": v.r1_schema_failed,
                    "r2_schema_failed": v.r2_schema_failed,
                    "r2_error": v.r2_error,
                    "r1_findings": [asdict(finding) for finding in v.r1_findings],
                    "r2_findings": (
                        [asdict(finding) for finding in v.r2_findings]
                        if v.r2_findings is not None else None
                    ),
                }
                for k, v in self.deliberators.items()
            },
            "span_id": self.span_id,
            "adjudicator_error": self.adjudicator_error,
            "artifact_sha256": self.artifact_sha256,
            "review_brief_sha256": self.review_brief_sha256,
            "strengths": self.strengths,
            "optional_suggestions": self.optional_suggestions,
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


def summarize_round2_changes(results: dict[str, DeliberatorResult]) -> str:
    """Deterministic summary of R2 concessions/escalations, in the deliberators'
    own words. Returns "" when nothing moved in Round 2.

    This consumes the cross-read deltas directly rather than trusting the
    Adjudicator to retell them, so the dissent surface reflects ground truth.
    """
    lines: list[str] = []
    for role, r in results.items():
        for c in r.r2_concessions:
            lines.append(f"- {role} conceded: {c}")
        for e in r.r2_escalations:
            lines.append(f"- {role} escalated: {e}")
    if not lines:
        return ""
    return "Round 2 cross-read deltas:\n" + "\n".join(lines)


class VerdictPolicy:
    """Applies the SHIP / REVISE / HOLD rules to a set of deliberator results."""

    def __init__(self, policy_config: dict | None = None) -> None:
        """Initialize from ``council.yaml#adjudicator.verdict_policy``.

        Numeric thresholds configure the otherwise fixed score-aware rules.
        """
        self.config = policy_config or {}

    def describe(self, min_deliberators: int = 3) -> str:
        """Describe the effective rules supplied to the synthesis model."""
        ship, soft, hold = self._thresholds()
        return (
            f"- Require a minimum of {min_deliberators} schema-valid R1 reviews. "
            "Invalid R1 does not count; valid R2 cannot repair missing/invalid R1.\n"
            "- Use valid R2 flags/scores where present; otherwise use valid R1. "
            "Only valid R2 irreducible flags participate in this policy.\n"
            f"- Thresholds: ship_min_score={ship}, soft_block_score={soft}, "
            f"hold_block_count={hold}.\n"
            "- A hard block is would_block=true. A score at or below soft_block_score "
            "counts as a soft block only when that reviewer has no hard block.\n"
            "- HOLD: any participating R2 irreducible flag, or hard+soft blocks "
            "reach hold_block_count.\n"
            "- SHIP: no hard/soft blocks and every present score clears ship_min_score. "
            "Otherwise REVISE. Missing scores fall back to binary flags.\n"
            "- The runtime enforces INCOMPLETE on insufficient valid R1 or failed synthesis. "
            "Otherwise the stricter of policy and model recommendation wins, except "
            "policy HOLD may become REVISE when the model recommends REVISE and "
            "no participating reviewer has irreducible dissent. Explain that exception.\n"
        )

    def _thresholds(self) -> tuple[int, int, int]:
        return (
            int(self.config.get("ship_min_score", 3)),
            int(self.config.get("soft_block_score", 1)),
            int(self.config.get("hold_block_count", 3)),
        )

    def apply(
        self,
        results: dict[str, DeliberatorResult],
        min_deliberators: int = 3,
    ) -> tuple[str, str]:
        """Compute (verdict, reasoning) from R2 flags AND calibration scores.

        Moderate, score-aware policy — the 1-5 calibration score is
        load-bearing, not decorative. Configurable via
        ``council.yaml#adjudicator.verdict_policy``:

          - ``ship_min_score`` (default 3): SHIP requires 0 hard blocks AND
            every *present* R2 score >= this.
          - ``soft_block_score`` (default 1): an R2 score <= this is a SOFT
            BLOCK — it counts toward HOLD even without ``would_block``.
          - ``hold_block_count`` (default 3): HOLD when hard+soft blocks reach
            this count, or on any ``irreducible`` flag.

        A score of 2 (above ``soft_block_score`` but below ``ship_min_score``)
        blocks SHIP -> REVISE but is not a soft block. Missing scores fall back
        to binary block logic, so absent calibration never forces HOLD/REVISE.

        Args:
            results: mapping of role-id to DeliberatorResult.
            min_deliberators: minimum number that must have succeeded; below
                this, the verdict is INCOMPLETE.

        Returns:
            (verdict, reasoning) tuple. Verdict is one of
            SHIP | REVISE | HOLD | INCOMPLETE.
        """
        ship_min_score, soft_block_score, hold_block_count = self._thresholds()

        succeeded = [r for r in results.values() if r.succeeded]
        if len(succeeded) < min_deliberators:
            return (
                "INCOMPLETE",
                (
                    f"Only {len(succeeded)} of {len(results)} deliberators produced "
                    f"schema-valid R1 output; minimum is {min_deliberators}. "
                    "Verdict cannot be rendered."
                ),
            )

        # R2 takes precedence; fall back to R1 if a deliberator failed at R2.
        hard_block: list[str] = []
        soft_block: list[str] = []
        irreducible: list[str] = []
        weak: list[int] = []  # present scores below the ship bar
        for r in succeeded:
            r2 = r.raw_r2 is not None
            would_block = r.r2_would_block if r2 else r.r1_would_block
            score = r.r2_score if r2 else r.r1_score
            if would_block:
                hard_block.append(r.role)
            elif score is not None and score <= soft_block_score:
                soft_block.append(r.role)
            if r.r2_irreducible:
                irreducible.append(r.role)
            if score is not None and score < ship_min_score:
                weak.append(score)

        if irreducible:
            return (
                "HOLD",
                (
                    f"Irreducible dissent from {', '.join(irreducible)}. "
                    "No revision can address this without structural rework."
                ),
            )

        effective = hard_block + soft_block
        if len(effective) >= hold_block_count:
            detail = ", ".join(
                hard_block + [f"{r} (score<={soft_block_score})" for r in soft_block]
            )
            return (
                "HOLD",
                (
                    f"{len(effective)} blocking signals: {detail}. "
                    f"{hold_block_count} or more indicates structural issues — recommend HOLD."
                ),
            )

        if not hard_block and not soft_block and not weak:
            return (
                "SHIP",
                "No participating deliberator blocked and all present scores cleared the bar.",
            )

        reasons: list[str] = []
        if hard_block:
            reasons.append(f"{len(hard_block)} hard block(s): {', '.join(hard_block)}")
        if soft_block:
            reasons.append(
                f"{len(soft_block)} soft block(s) (score<={soft_block_score})"
            )
        if weak:
            reasons.append(
                f"score(s) {sorted(weak)} below the ship bar ({ship_min_score})"
            )
        return (
            "REVISE",
            "; ".join(reasons) + ". No irreducible dissent — fixable with a revision pass.",
        )
