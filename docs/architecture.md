---
title: Architecture
layout: default
nav_order: 2
---

# Architecture

Four reviewers, a separate Adjudicator, and an enforced verdict policy.
{: .fs-6 .fw-300 }

---

## The 2-round protocol

```text
Artifact + role-specific context
  -> R1: Skeptic / Evidence / Voice / Strategy, independent parallel reviews
  -> R2: full available R1 findings shared, including each reviewer's own
  -> Adjudicator: artifact + both rounds + prior same-type verdict summaries
  -> Policy enforcement: SHIP / REVISE / HOLD / INCOMPLETE
  -> Decision, revision brief or explicit limitation, audit row and transcripts
```

R1 preserves distinct starting perspectives. R2 can expose new questions across responsibilities: whether a stronger-sounding claim was measured, whether the evidence supports causation, or whether an assumption changes the strategic recommendation. It is one cross-read round, not a continuous debate or a vote to force consensus. The output preserves reviewer concessions and escalations alongside the synthesis.

The Adjudicator has no R1 position of its own to defend. It groups related findings, explains useful disagreement and recommends required changes. The runtime separately enforces its verdict policy. `rounds: 1` omits R2; a later review of a revised artifact is a new caller-initiated run.

An optional review brief supplies purpose, audience, constraints and support to every reviewer and synthesis. Role-specific files remain separate; the brief does not cause extra retrieval or tool access. The prompts prioritize material concerns, preserved strengths and minimal resolution rather than a quota of criticism.

Optional structured findings carry `location`, `concern`, `basis`, `impact` and `resolution`. Both rounds' normalized findings are returned/logged without silently dropping unfamiliar headline aliases such as `violations`. Legacy missing details stay blank. A supplied R2 `findings` list describes the complete remaining set, so an explicit empty list does not revive R1 concerns in a missing-brief fallback. These are recorded model assessments, not proof that their citations or conclusions are correct.

The [personal workflow diagram](assets/ai-review-loop-v1.0.png), **How I use AI to review my work**, covers authored, AI-generated and co-created content. Its stricter "required reviews complete" standard is not the runtime default: three valid R1 reviews may suffice, with R1 fallback when R2 fails. The image is a workflow illustration, not an exact executable state machine or automatic publication authority.

## Completion, failures and stopping

Only schema-valid R1 reviews count toward `min_deliberators_for_verdict` (default 3). An invalid R1 object cannot count merely because it parsed as JSON, and valid R2 cannot repair that R1 quorum failure. For a participating reviewer, valid R2 flags/scores take precedence; missing/failed R2 uses valid R1.

Each malformed output gets at most one schema reprompt. Runtime errors do not trigger extra retries. An initial synthesis timeout/runtime failure, a runtime failure during its schema retry, or exhausted synthesis schema validation returns `INCOMPLETE` with an error and available review transcripts. No strict all-four/all-round completeness rule is added.

The verdict exposes R1 `error`, `r1_schema_failed`, `r2_error`, `r2_schema_failed`, and top-level `adjudicator_error`. R2 failure does not change `succeeded` when R1 is valid. Human-readable dissent also names failures and fallback. Setup and unexpected programming errors may raise; log-write errors propagate and archive-write errors produce the existing warning rather than a false archive-success claim.

The built-in subprocess adapters normalize expected process-launch errors and drain the directly launched child after killing it on timeout/cancellation. Cleanup is bounded to five seconds; failure is warned on stderr. Cancellation still propagates. This does not promise termination of every descendant a provider may launch, restrict its tools, or add retries.

## Recommendation versus enforced policy

[`VerdictPolicy.apply`](https://github.com/Avyayalaya/agent-council/blob/main/src/agent_council/verdict.py) computes the policy result. At defaults:

| Condition | Policy result |
|---|---|
| Fewer than three valid R1 reviews | INCOMPLETE |
| Any participating valid-R2 irreducible flag | HOLD |
| Three or more hard/soft blocks | HOLD |
| No hard/soft blocks and all present scores at least 3 | SHIP |
| Otherwise, including scores of 2 or one/two blocks | REVISE |

A hard block is `would_block=true`. A score at or below `soft_block_score` (default 1) counts as a soft block only when the reviewer has no hard block. `ship_min_score` defaults to 3 and `hold_block_count` to 3. Only R2 supplies the irreducible flag in the existing policy; fallback R1 supplies scores and blocking flags.

The synthesis receives these effective settings. [`merge_verdicts`](https://github.com/Avyayalaya/agent-council/blob/main/src/agent_council/orchestrator.py) normally takes the stricter recommendation, while permitting policy HOLD to become REVISE if the model recommends REVISE and no participating reviewer flagged irreducible. INCOMPLETE and irreducible HOLD cannot be bypassed.

The final explanation identifies an overridden recommendation or the downgrade exception. Valid synthesis briefs are preserved. Missing/empty briefs do not change the verdict or cause extra model calls: the result explicitly reports the missing actionable plan, includes available reviewer findings, and directs the operator to the full critiques. It does not invent repairs.

Synthesis is instructed to keep necessary edits in `revision_brief`, non-blocking ideas in `optional_suggestions`, and preserved choices in `strengths`. Suggestions/strengths may be omitted by legacy outputs or returned as empty lists. Their types are validated when supplied; they do not participate in the score/block policy. The final lists remove exact duplicates only. The runtime does not infer that two differently phrased actions are equivalent or mechanically verify that a replacement introduces no new commitment.

Each reviewer invocation explicitly requests only the current round as one flat JSON object, preventing ambiguity between the two schema examples in a role prompt. This adds no round, retry or model call.

---

## Tier classification

The Council is designed for **tier-1 artifacts**:

| Tier | Definition | Council? |
|---|---|---|
| **Tier 1** | External-facing OR irreversible OR identity-shaping OR memory writes | YES — every artifact |
| **Tier 2** | Internal drafts, dashboards, infrastructure, dispatch updates | Skip |
| **Tier 3** | Daily briefings, internal analyses, planning artifacts | Sample 1-in-5 |

Tier classification is rule-based (glob patterns in `council.yaml#tier_rules`). Skipping/sampling applies to the sweep; an explicit `review` or `Council.run()` still reviews the requested artifact and records its tier.

---

## The compounding loop (D6)

Only the Adjudicator receives up to five prior verdict summaries on the same `artifact_type`, with bounded reasoning/brief excerpts. First reviewers do not see this history. It may help identify recurring concerns, but also carries a risk of reinforcing prior errors. Context reuse does not establish learning or improved quality.

The repository's mock/scripted tests establish protocol mechanics, not superiority over a unified judge or unreviewed output. Comparative evaluation remains planned. Evidence review is similarly bounded: it assesses support supplied in the artifact or context files, not sources retrieved from the web. A citation alone is not proof that a source was read.

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

Each completed protocol run, including structured failure, appends a flat Rule 35 v2 record. This abridged shape omits per-role detail:

```json
{
  "v": 2,
  "span_id": "council-0123456789ab",
  "artifact_path": "path/to/artifact.md",
  "artifact_type": "linkedin_post",
  "verdict": "REVISE",
  "deliberators": {},
  "adjudicator_reasoning": "Enforced decision and reasons.",
  "revision_brief": "1. Required change.",
  "dissent_summary": "Remaining disagreement or review failures.",
  "adjudicator_error": null,
  "adjudicator_schema_failed": false,
  "adjudicator_reprompts": 0,
  "prior_verdicts_used": 3,
  "persisted": true
}
```

The complete record also includes timestamp, artifact hash, runtime/model identity and elapsed time. Per-role records include validity, errors, scores, flags and R2 changes. Raw attempts and retries live in the archive under `span_id`, including invalid evidence. `adjudicator_synthesis.md` includes synthesis failure details when no usable synthesis is available.

`artifact_sha256` is also returned in the verdict. `artifact.md` is written from the captured text used for the calls, never a later read of the source path. Its hash identifies the UTF-8 text after the artifact reader's newline normalization. A supplied brief is saved as `review_brief.md` with `review_brief_sha256` in the result/log. The brief's exact UTF-8 bytes, including its supplied line endings, are preserved; verify that hash against the archive bytes rather than a text reader that normalizes newlines. Callers must check that a current artifact still matches before treating a verdict as applicable.

The optional Python `Council(..., adapter=runtime)` entry point changes only adapter selection; omitting it uses the configured factory. One adapter serves the whole protocol, and logs use that adapter's identity. Per-role runtime overrides and configured fail-fast behavior are not implemented.
