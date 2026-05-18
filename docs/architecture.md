---
title: Architecture
layout: default
nav_order: 2
---

# Architecture

How the 5-deliberator council works.
{: .fs-6 .fw-300 }

---

## The 2-round protocol

```
   ┌──────────┐
   │ artifact │ ───► tier-1?  No  ───► skip
   └────┬─────┘        │
        │ Yes
        ▼
   ┌────────────────────────────────────────────────────────┐
   │  ROUND 1 — 4 deliberators run in parallel              │
   │                                                        │
   │   Skeptic        Voice &      Evidence &     Strategy  │
   │   (adversarial)  Identity     Calibration    & Stakes  │
   │                                                        │
   │   each → {verdict, scores, would_block, irreducible,   │
   │           revision_brief}                              │
   └─────────────────────────────┬──────────────────────────┘
                                 │
                                 ▼
   ┌────────────────────────────────────────────────────────┐
   │  ROUND 2 — same 4 deliberators, with cross-read        │
   │                                                        │
   │   Each sees the other 3 R1 verdicts; may update.       │
   │   Single-deliberator misfires get corrected; indep-    │
   │   endent first reads preserved.                        │
   └─────────────────────────────┬──────────────────────────┘
                                 │
                                 ▼
   ┌────────────────────────────────────────────────────────┐
   │  ADJUDICATOR (single call)                             │
   │                                                        │
   │   Merges 4 R2 verdicts + reads prior verdicts on same  │
   │   artifact_type from council_log.jsonl (D6 loop).      │
   │                                                        │
   │   Verdict policy:                                      │
   │     3+ block on irreducible       → HOLD               │
   │     3+ block on reducible +                            │
   │       Adjudicator reasons downgrade → REVISE           │
   │     otherwise                       → SHIP             │
   │                                  + revision_brief      │
   └─────────────────────────────┬──────────────────────────┘
                                 │
                                 ▼
                      SHIP / REVISE / HOLD
                      + revision_brief
                      + audit row → council_log.jsonl
```

---

## Tier classification

The Council is designed for **tier-1 artifacts**:

| Tier | Definition | Council? |
|---|---|---|
| **Tier 1** | External-facing OR irreversible OR identity-shaping OR memory writes | YES — every artifact |
| **Tier 2** | Internal drafts, dashboards, infrastructure, dispatch updates | Skip |
| **Tier 3** | Daily briefings, internal analyses, planning artifacts | Sample 1-in-5 |

Tier classification is rule-based in v0.1 (glob patterns in `council.yaml#tier_rules`). Model-based and hybrid classifiers are on the v0.3 roadmap.

---

## The compounding loop (D6)

The Adjudicator reads prior verdicts on the same `artifact_type` from `council_log.jsonl` before merging the current round's verdicts. This means:

- Two consecutive HOLDs on the same artifact_type sharpen the Adjudicator's reasoning on the third pass.
- Voice patterns flagged across multiple artifacts ("V1 + V3 keep appearing in linkedin_post") compound into stronger pattern recognition.
- The producing agent's drift gets surfaced — not just the artifact's flaws.

This is what makes the Council a *system* rather than a stateless judge.

---

## Modularity invariant

Emitting agents have **zero hard dependency on Council**. CI-tested in [`tests/test_modularity_invariant.py`](https://github.com/Avyayalaya/agent-council/blob/main/tests/test_modularity_invariant.py):

```bash
PYTHONPATH=src python -m unittest tests.test_modularity_invariant -v
```

The test scans any host operator system's `agents/*/prompt.md` files and asserts zero references to Council. If a producing agent's prompt starts to know about the gate that reviews it, the build fails.

This means:

- An orchestrator can route any artifact to Council without touching the producing agent.
- Removing the Council leaves every producing agent functional.
- The Council ships as a standalone runtime that wires into Emissary, MCP, slash commands, CI pipelines, or any custom agent system without coupling.

---

## Verdict log schema

Every Council invocation appends one line to `council_log.jsonl` following Rule 35 v2 format:

```json
{
  "v": 2,
  "ts": "2026-05-18T...Z",
  "artifact": "path/to/artifact.md",
  "artifact_type": "linkedin_post",
  "round1": [{"deliberator": "skeptic", "verdict": "revise", "scores": {...}, ...}, ...],
  "round2": [...],
  "adjudicator": {
    "final_verdict": "REVISE",
    "reasoning": "...",
    "revision_brief": "...",
    "applied_compounding": true,
    "prior_verdicts_consulted": 3
  }
}
```

Append-only. The Adjudicator reads prior entries on the same `artifact_type` to apply the D6 compounding loop.
