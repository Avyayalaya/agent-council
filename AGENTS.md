# AGENTS.md — Agent Council capability manifest

This file declares the Council to other AI systems and orchestrators. Three layers: **identity**, **evaluability**, **composability**. They are all in this file.

---

## Identity

**Name:** `agent_council` (Python package); `agent-council` (CLI binary).
**Version:** 0.1.0 (P0 — Week 1 scaffold).
**One-paragraph capability:**

> The Agent Council is a runtime-portable quality gate. Given any text artifact and a config, it runs five role-conditioned LLM deliberators in a 2-round async protocol with cross-read rebuttal, then synthesizes a single verdict — SHIP, REVISE, or HOLD — plus a revision brief and a full audit transcript. It depends on no SDK and no API keys: a runtime adapter shells out to whatever CLI is configured (`claude`, `gh copilot`, `ollama`, etc.). It is designed to gate tier-1 artifacts — external-facing, irreversible, identity-shaping, or memory writes — before they persist or publish.

**What it does well:**

- Catches voice violations, evidence gaps, and strategic mis-alignment that the artifact's producing agent missed.
- Surfaces dissent transparently — every deliberator's score, blocking flag, and irreducible flag is logged.
- Compounds across runs — prior verdicts on the same `artifact_type` are loaded into the Adjudicator's context.
- Stays portable — adding a new LLM CLI is one new file in `runtimes/`.

**What it is not:**

- It is not a writing tool. It does not produce artifacts; it gates them.
- It is not a generic LLM-as-judge. It is structured around five named roles, each with a Context Verification Gate and a typed output schema.
- It is not a fact-checker for the open web. Source verification stays inside the Evidence deliberator's tiered framework — accuracy is the operator's responsibility.
- It is not a replacement for the operator's own review. It is the gate before the operator's review, not after.

**When to invoke:**

- An artifact is tier-1 (external, irreversible, identity-shaping, or a memory write).
- The artifact has cleared its producing agent's quality gate but has not yet been published / committed / persisted.
- The operator wants structured dissent before shipping — not just "looks good."

**When NOT to invoke:**

- The artifact is tier-2 (internal drafts, dashboards, infra, dispatch updates, registry edits). Skip — Council burn is real.
- The artifact is a single sentence or a tweet of <100 chars. The deliberators have nothing to bite into.
- The artifact is in a language the deliberators are not configured for. V1 is English-only.

---

## Evaluability

The Council ships with a reproducible test fixture and a passing end-to-end test.

**Sample artifact:** `tests/sample_artifact.md` — a ~600-word mock LinkedIn-style post with seeded violations (V1 "not X but Y" construction, V3 hype word "recontextualize," one T5 underspecified pricing claim, one weakly-addressed counter-position).

**Example invocation:**

```bash
python -m agent_council review tests/sample_artifact.md \
  --tier=1 \
  --config=tests/council.example.yaml
```

**Expected verdict (using `mock_cli` runtime):** `REVISE`. Two of four deliberators block (Skeptic, Voice & Identity); none flag irreducible. The Adjudicator's revision brief contains four numbered items addressing the seeded violations.

**Test suite:**

```bash
python -m unittest tests.test_orchestrator tests.test_modularity_invariant -v
```

Seven tests cover:

1. `test_config_loads_and_validates` — YAML config parses and structural validation passes.
2. `test_end_to_end_verdict_shape` — full 2-round protocol returns a typed Verdict.
3. `test_jsonl_log_persisted` — Rule 35 v2 schema written with `v:2`, `span_id`, `persisted:true`.
4. `test_archive_written` — 10 transcript files + artifact snapshot land under `council_archive/<span_id>/`.
5. `test_elapsed_time_under_five_minutes` — mock-runtime SLA.
6. `test_no_emitting_agent_prompt_references_council` — modularity invariant; greps any host operator system's `agents/*/prompt.md` (if present) and asserts zero Council references. Skipped when run outside a host system.
7. `test_council_package_has_no_agent_prime_imports` — walks `src/agent_council/` AST and asserts no imports outside stdlib + the package + declared optional deps.

**Empirical claim (P3):** `Composite_with_Council > Composite_without_Council` on AgentOS-Bench v1 (Categories 1, 2, 3, 7), predicted delta ≥ +10 points. P3 spec is in `plan/stage3_architecture.md`; harness lives at `bench/` (not yet built — P1 deliverable).

---

## Composability

### CLI surface

```
python -m agent_council review <artifact> --tier=N --config=<path>
python -m agent_council audit  --log=<path>
python -m agent_council health --config=<path>
python -m agent_council validate-config <path>
```

### Exit codes

| Code | Verdict | Meaning |
|------|---------|---------|
| 0 | SHIP | No deliberator blocked. |
| 1 | REVISE | 1–2 blocks, no irreducible flag. |
| 2 | HOLD | 3+ blocks OR any irreducible flag. |
| 3 | INCOMPLETE | Fewer than `min_deliberators_for_verdict` succeeded. |
| 4 | NOT_FOUND | Artifact path does not exist. |
| 5 | CONFIG_ERROR | Council YAML invalid. |

### Output schemas

**Verdict (returned by `Council.run()`, dumped by `--json`):**

```json
{
  "verdict": "SHIP | REVISE | HOLD | INCOMPLETE",
  "reasoning": "≤3 sentences",
  "revision_brief": "numbered list as string (null if SHIP)",
  "dissent_summary": "≤4 sentences",
  "deliberators": {
    "<role_id>": {
      "role": "skeptic | voice_identity | evidence | strategy",
      "r1_score": 1-5,
      "r1_would_block": true,
      "r2_score": 1-5,
      "r2_would_block": true,
      "r2_irreducible": false,
      "top_issues": ["..."],
      "succeeded": true,
      "error": null
    }
  },
  "span_id": "council-<12hex>"
}
```

**Per-deliberator R1 critique** — see `prompts/<role>.md` for each role's output schema. Common keys: `role`, `round`, `score` (1–5), `would_block` (bool), `irreducible` (bool). Role-specific keys vary: Skeptic has `top_3_failure_modes`, Voice has `voice_violations` (list of `{line, rule, snippet, fix}` records), Evidence has `claim_tier_map`, Strategy has `goal_alignment`.

**Log line (Rule 35 v2 — `council_log.jsonl`):**

```json
{
  "v": 2,
  "span_id": "council-<12hex>",
  "parent_id": null,
  "sid": "council-cli",
  "ts": "2026-05-11T10:23:11Z",
  "agent": "council",
  "event": "verdict",
  "artifact_path": "...",
  "artifact_sha256": "<64hex>",
  "tier": 1,
  "verdict": "REVISE",
  "deliberators": { ... },
  "adjudicator_reasoning": "...",
  "revision_brief": "...",
  "runtime": "claude_cli",
  "model": "claude-opus-4-7",
  "elapsed_seconds": 187.4,
  "persisted": true
}
```

### Runtime adapters

| Adapter | When to use | Health check | Notes |
|---------|-------------|--------------|-------|
| `claude_cli` | Production gating with Anthropic's CLI | `claude --version` exits 0 | UTF-8 explicit; Windows-safe |
| `mock_cli` | Tests, demos, offline development | Always True | Deterministic canned output |

Adding a new adapter (e.g., `ollama`, `copilot_cli`): one file under `src/agent_council/runtimes/`, subclass `RuntimeAdapter`, implement `invoke` / `health_check` / `adapter_name`, register in `runtimes/__init__.py:build_adapter`. No orchestrator changes required.

### Modularity invariant (Condition 3)

The Council package does not import anything outside stdlib and its own modules. Verified mechanically in `tests/test_modularity_invariant.py`. No emitting-agent prompt in the host operator system references the Council — when wired into one, the same test enforces this. Verified mechanically in the same file.

---

## Versioning + compatibility

- **0.1.0** — Initial public release. Architecture + design + 5 deliberator prompts + 4 runtime adapters (claude_cli, lmstudio, ollama, mock_cli). No empirical claims; evaluation forthcoming in 0.2.
- **0.2.0** — Forthcoming. Empirical evaluation: AgentOS-Bench-style 3-arm benchmark (baseline / unified-judge / Council) and a recursive Council-on-Council validation study. Paper released to arXiv.
- **0.3.0** — Forthcoming. Adjudicator improvements + verdict-policy refinements based on 0.2 findings. Additional runtime adapters.

Breaking changes will bump the minor version until 1.0. The verdict JSON schema, exit codes, and CLI subcommand names are the public surface; everything else is internal.

---

*Authored 2026-05-11 by Builder for P0. Updated each phase as the surface stabilizes.*
