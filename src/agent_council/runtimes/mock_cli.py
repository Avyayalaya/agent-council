"""MockCLIAdapter — deterministic canned outputs for offline testing.

This adapter never shells out to anything. It returns role-specific JSON-shaped
outputs keyed off the deliberator name found in the prompt header (e.g.
"Skeptic — Agent Council Deliberator"). It is the test substrate for the W1
end-to-end fixture — it lets the orchestrator and verdict policy run without
burning real Claude tokens.

The canned outputs intentionally include 1-2 ``would_block:true`` deliberators
plus a REVISE verdict from the Adjudicator, so the end-to-end test exercises
the full verdict-policy code path (not just SHIP).

W2 extension (2026-05-12, RW2-1 mitigation): Added bench-mode canned payloads
for ``bench_baseline``, ``unified_judge``, and ``uqr_judge`` roles. The new
routes are detected via explicit header markers ("# uqr_judge", "Unified
Judge", "Bench task") that the bench-mode adapters inject, so existing P0
Council routes (skeptic / voice_identity / evidence / strategy / adjudicator)
remain unchanged. P0 tests continue to pass.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Iterable

from agent_council.runtimes.base import RuntimeAdapter


# ---------------------------------------------------------------------------
# Canned outputs — one per role. JSON is wrapped in a markdown code fence so
# the orchestrator's JSON extraction path is exercised exactly like the real
# claude_cli adapter would deliver it.
# ---------------------------------------------------------------------------

_R1_CRITIQUES = {
    "skeptic": {
        "role": "skeptic",
        "round": 1,
        "score": 2,
        "top_3_issues": [
            "Claim about Stratum's pricing tier (“$7,500 standard”) is asserted without a source link.",
            "The strongest counter-position — that Stratum's facilitator-mediated model caps scale — is not addressed.",
            "Conclusion implies causality (“this is why we ship”) but the evidence is correlational at best."
        ],
        "top_3_failure_modes": [
            "Buyer pushes back on $7,500 number, post has no defense.",
            "Reader asks ‘what about self-serve?’, post has no answer.",
            "Smart practitioner spots the unsupported causality and dismisses the rest."
        ],
        "would_block": True,
        "irreducible": False,
        "notes": "Defensible position with two specific gaps. Fixable with one revision pass."
    },
    "voice_identity": {
        "role": "voice_identity",
        "round": 1,
        "score": 3,
        "voice_violations": [
            {"line": 4, "rule": "V1", "snippet": "not a product but a protocol", "fix": "Drop ‘not X but Y’; say ‘this is a protocol’ directly."},
            {"line": 12, "rule": "V3", "snippet": "we recontextualize", "fix": "Hype word ‘recontextualize’; replace with ‘we reframe’ or specific verb."}
        ],
        "identity_fit": "Mostly the operator's register — evidence-led, blunt. Two voice slips above let it down.",
        "cxo_test": "Would a CPO say this in a board meeting? Mostly yes. The ‘not X but Y’ line would get a raised eyebrow.",
        "would_block": True,
        "irreducible": False,
        "notes": "Two specific voice violations; structural voice is sound."
    },
    "evidence": {
        "role": "evidence",
        "round": 1,
        "score": 3,
        "claim_tier_map": [
            {"claim": "Stratum priced $7,500/standard", "tier": "T5", "status": "underspecified", "fix": "Add source link to Stratum spec entry or pricing page."},
            {"claim": "150M MAU on Copilot", "tier": "T2", "status": "verified", "fix": None},
            {"claim": "Most PM frameworks fail in agentic systems", "tier": "T6", "status": "asserted_without_evidence", "fix": "Either cite a specific failure or weaken to ‘in my experience’."}
        ],
        "calibration_issues": [
            "Confidence on the ‘most frameworks fail’ claim should be M, not stated as fact.",
            "No counter-evidence acknowledged for the pricing claim."
        ],
        "would_block": False,
        "irreducible": False,
        "notes": "One T5 claim and one T6 claim; both fixable with one revision pass."
    },
    "strategy": {
        "role": "strategy",
        "round": 1,
        "score": 4,
        "goal_alignment": {"primary_goal": "Matter", "secondary_goal": "Lead", "fit": "Strong"},
        "opportunity_cost": "Drafting this post takes ~2 hours. PRG-003 Session 2 prep is overdue. Worth shipping if revision is fast.",
        "kill_check": "No kill-criteria triggers. Position is defensible; topic is on-brand.",
        "would_block": False,
        "irreducible": False,
        "notes": "Strategically aligned. Move forward after voice + evidence fixes."
    }
}

_R2_REBUTTALS = {
    "skeptic": {
        "role": "skeptic",
        "round": 2,
        "score": 2,
        "concessions": [
            "Voice & Identity's V1 catch is the same root cause as my ‘causality’ concern — both are hedge-avoidance gone wrong."
        ],
        "escalations": [],
        "would_block": True,
        "irreducible": False
    },
    "voice_identity": {
        "role": "voice_identity",
        "round": 2,
        "score": 3,
        "concessions": [],
        "escalations": [
            "Skeptic's pricing gap is also a voice issue — unsupported confidence reads as performance, not depth."
        ],
        "would_block": True,
        "irreducible": False
    },
    "evidence": {
        "role": "evidence",
        "round": 2,
        "score": 3,
        "concessions": [
            "Skeptic raised the same T5 pricing gap I did — we agree."
        ],
        "escalations": [],
        "would_block": False,
        "irreducible": False
    },
    "strategy": {
        "role": "strategy",
        "round": 2,
        "score": 4,
        "concessions": [],
        "escalations": [],
        "would_block": False,
        "irreducible": False
    }
}

_ADJUDICATOR_SYNTHESIS = {
    "verdict": "REVISE",
    "reasoning": (
        "Two deliberators flag would_block (Skeptic, Voice & Identity); none flag irreducible. "
        "Per verdict_policy, 1-2 would_blocks without irreducible = REVISE. "
        "Both blocking issues converge on the same root cause: one unsupported claim "
        "(Stratum pricing) and one voice violation pattern ('not X but Y' construction). "
        "A single revision pass addresses both."
    ),
    "revision_brief": (
        "1. Replace 'not a product but a protocol' with 'Stratum is a protocol.' "
        "(Voice V1 — see voice_identity R1, line 4.)\n"
        "2. Add a source for the '$7,500 standard pricing' claim — either link the "
        "Stratum spec entry or remove the number. (Evidence T5 — see evidence R1.)\n"
        "3. Soften 'we recontextualize' to a concrete verb. (Voice V3 — see voice_identity R1, line 12.)\n"
        "4. Acknowledge the self-serve counter-position in one sentence. (Skeptic R1.)"
    ),
    "dissent_summary": (
        "Skeptic and Voice & Identity blocked; Evidence and Strategy did not. "
        "No deliberator flagged irreducible. Concessions show convergence on the "
        "pricing-gap issue across Skeptic and Evidence."
    )
}


def _wrap_json(payload: dict) -> str:
    """Wrap a JSON payload in a markdown code fence (matches real-CLI output)."""
    return "```json\n" + json.dumps(payload, indent=2, ensure_ascii=False) + "\n```\n"


# ---------------------------------------------------------------------------
# W2: bench-mode canned payloads (RW2-1 strict canned-response mode).
# These are deterministic; the calibration test asserts variance <= tolerance
# against the reference set.
# ---------------------------------------------------------------------------

_BENCH_BASELINE_ARTIFACT = (
    "## Baseline artifact (mock_cli canned)\n\n"
    "This is a deterministic mock response for bench testing. It contains "
    "three short paragraphs with one citation and one explicit assumption, "
    "calibrated to produce a mid-range UQR score against the canned judge.\n\n"
    "**Key claims:** (1) deterministic outputs let the bench exercise its "
    "scoring path without burning real Claude tokens; (2) the artifact has "
    "enough structure to score above the floor on Structural Clarity and "
    "Voice Consistency; (3) evidence density is intentionally moderate so "
    "calibration shows non-zero variance across reference outputs.\n\n"
    "_Assumption:_ scoring against this mock is for harness validation only, "
    "not for measuring real model quality. W3 real-bench runs replace this "
    "string with actual model output."
)

_UNIFIED_JUDGE_PAYLOAD = {
    "artifact_preview": "[unified_judge mode — see produced artifact above]",
    "criteria": {
        "skepticism":     {"score": 3, "notes": "Identifies obvious failure modes; misses one structural counter."},
        "voice_identity": {"score": 3, "notes": "Mostly consistent register; one hype-word slip."},
        "evidence":       {"score": 3, "notes": "Two claims cited; one underspecified."},
        "strategy":       {"score": 4, "notes": "Aligned with stated goal; opportunity cost named."},
        "synthesis":      {"score": 3, "notes": "Conclusions follow from premises; transitions are workable."},
    },
    "would_block": False,
    "revision_brief": None,
}

# UQR judge canned payload — deterministic 6-dimension score.
# total_weighted = 0.15*3 + 0.20*3 + 0.25*3 + 0.20*4 + 0.10*3 + 0.10*3 = 3.20
# total_normalized_100 = (3.20 - 1) / 4 * 100 = 55.0
_UQR_REFERENCE = {
    "structural_clarity": {"score": 3, "justification": "Sections present; one transition weak."},
    "evidence_density":   {"score": 3, "justification": "Most claims backed; one bare assertion."},
    "analytical_depth":   {"score": 3, "justification": "Second-order effects acknowledged; not exhaustive."},
    "actionability":      {"score": 4, "justification": "Concrete next steps with owners and dates."},
    "calibration":        {"score": 3, "justification": "Hedges present but inconsistent."},
    "voice_consistency":  {"score": 3, "justification": "Register holds; two ambient AI-tone slips."},
    "total_weighted": 3.20,
    "total_normalized_100": 55.0,
}


def _identify_role(prompt: str) -> str:
    """Detect which deliberator role the prompt belongs to.

    Looks for explicit role markers in the prompt header. Falls back to
    ``skeptic`` for unrecognized inputs.

    Order matters: bench-mode header markers are checked before the P0
    Council role markers, because bench briefs can naturally contain words
    like "strategy" or "evidence" that would mis-route to a Council role.
    Bench adapters inject explicit, unambiguous header markers
    ("# uqr_judge", "Unified Judge — Self-Evaluation", "# Bench task —")
    so this detector can route them without consulting the brief body.
    """
    head = prompt.lower()[:500]
    # W2 bench-mode routes — checked FIRST.
    if "# uqr_judge" in head or "uqr judge" in head or "universal quality rubric" in head:
        return "uqr_judge"
    if "unified judge — self-evaluation" in head or "unified_judge" in head:
        return "unified_judge"
    if "# bench task" in head:
        # Baseline mode header is "# Bench task — category N — brief_id".
        # The unified-judge wrapper ALSO starts with "# Bench task" but is
        # caught above via its self-evaluation marker. If we get here, this
        # is the baseline path.
        return "bench_baseline"
    # Legacy P0 Council routes.
    if "adjudicator" in head:
        return "adjudicator"
    if "voice_identity" in head or "voice & identity" in head or "voice and identity" in head:
        return "voice_identity"
    if "evidence" in head:
        return "evidence"
    if "strategy" in head:
        return "strategy"
    if "skeptic" in head:
        return "skeptic"
    return "skeptic"


def _identify_round(context: Iterable[str], prompt: str) -> int:
    """Detect whether this is a Round 1 critique or a Round 2 rebuttal.

    R2 invocations include the marker ``[ROUND_2_REBUTTAL]`` injected by the
    orchestrator before invoking. Anything else is R1.
    """
    if "[ROUND_2_REBUTTAL]" in prompt:
        return 2
    for c in context:
        if "[ROUND_2_REBUTTAL]" in c:
            return 2
    return 1


class MockCLIAdapter(RuntimeAdapter):
    """Returns canned, deterministic, role-aware JSON for testing."""

    def adapter_name(self) -> str:
        return "mock_cli"

    def health_check(self) -> bool:
        return True

    async def invoke(
        self,
        prompt: str,
        context: Iterable[str],
        model: str | None = None,
    ) -> str:
        """Return a canned response keyed off the role found in the prompt."""
        # Optional small delay so async fan-out behavior is visible in tests.
        delay_ms = float(os.environ.get("AGENT_COUNCIL_MOCK_DELAY_MS", "0"))
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)

        # Coerce context to a concrete list so we can iterate twice if needed.
        ctx_list = list(context)
        role = _identify_role(prompt)

        # W2 bench routes — produce artifacts / judge scores, not critiques.
        if role == "bench_baseline":
            return _BENCH_BASELINE_ARTIFACT
        if role == "unified_judge":
            return (
                _BENCH_BASELINE_ARTIFACT
                + "\n\n---\n\n"
                + _wrap_json(_UNIFIED_JUDGE_PAYLOAD)
            )
        if role == "uqr_judge":
            return _wrap_json(_UQR_REFERENCE)

        # P0 Council routes — unchanged.
        if role == "adjudicator":
            return _wrap_json(_ADJUDICATOR_SYNTHESIS)

        round_num = _identify_round(ctx_list, prompt)
        if round_num == 2:
            payload = _R2_REBUTTALS.get(role, _R2_REBUTTALS["skeptic"])
        else:
            payload = _R1_CRITIQUES.get(role, _R1_CRITIQUES["skeptic"])
        return _wrap_json(payload)
