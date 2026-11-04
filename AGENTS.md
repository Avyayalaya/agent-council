# AGENTS.md — Agent Council capability manifest

This file declares the Council to other AI systems and orchestrators. Three layers: **identity**, **evaluability**, **composability**. They are all in this file.

---

## Identity

**Name:** `agent_council` (Python package); `agent-council` (CLI binary).
**Python package version:** 0.1.0. Plugin releases are tracked separately in [CHANGELOG.md](CHANGELOG.md).
**One-paragraph capability:**

> Agent Council reviews authored, AI-generated or co-created text. Four role-conditioned reviewers (Skeptic, Evidence, Voice, Strategy) run independently, then receive the full available first-round findings for one cross-read round. A separate Adjudicator synthesizes both rounds and remaining disagreements; code enforces SHIP, REVISE, HOLD or INCOMPLETE. The core has no required SDK or API key; adapters use supported CLIs, LM Studio HTTP, or an offline mock. Provider authentication remains the caller's responsibility. Council targets tier-1 artifacts before persistence or publication.

**What it does well:**

- Provides distinct review responsibilities for voice, evidence, argument and strategic fit.
- Surfaces dissent transparently — every deliberator's score, blocking flag, and irreducible flag is logged.
- Reuses context across runs: up to five prior verdicts on the same `artifact_type` are loaded into synthesis. This does not establish learning or improved judgment.
- Stays portable — adding a new LLM CLI is one new file in `runtimes/`.

**What it is not:**

- It is not a writing tool. It does not produce artifacts; it gates them.
- It has four reviewer roles and a separate synthesis role. Runtime validation checks common output fields, not every role-specific finding or prompt-level context requirement.
- It does not browse or retrieve sources. Evidence review assesses supplied support and identifies gaps; a cited URL alone is not verified source content.
- It is not continuous debate or an automatic edit/review loop. The default runs two review rounds plus synthesis; `rounds: 1` skips R2.
- It is not a replacement for the operator's own review. It is the gate before the operator's review, not after.

**When to invoke:**

- An artifact is tier-1 (external, irreversible, identity-shaping, or a memory write).
- The artifact has cleared its producing agent's quality gate but has not yet been published / committed / persisted.
- The operator wants structured dissent before shipping — not just "looks good."

**When NOT to invoke:**

- The artifact is tier-2 (internal drafts, dashboards, infra, dispatch updates, registry edits). The sweep skips these; an explicit `review` or `Council.run()` still runs and records the supplied tier.
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

These test modules cover:

1. `test_config_loads_and_validates` — YAML config parses and structural validation passes.
2. `test_end_to_end_verdict_shape` — full 2-round protocol returns a typed Verdict.
3. `test_jsonl_log_persisted` — Rule 35 v2 schema written with `v:2`, `span_id`, `persisted:true`.
4. `test_archive_written` — nine transcript files + artifact snapshot land under `council_archive/<span_id>/` for the default two-round panel.
5. `test_elapsed_time_under_five_minutes` — mock-runtime SLA.
6. `test_no_emitting_agent_prompt_references_council` — modularity invariant; greps any host operator system's `agents/*/prompt.md` (if present) and asserts zero Council references. Skipped when run outside a host system.
7. `test_council_package_has_no_external_imports` — walks `src/agent_council/` AST and asserts no imports outside stdlib + the package + declared optional deps.

Additional focused modules cover invalid-review accounting, synthesis errors, policy/explanation consistency, R2 changes and prior-verdict context. Use `python -m unittest discover tests -v` for the suite, with this checkout's `src` on `PYTHONPATH`.

**Evidence status:** Mock/scripted tests establish protocol behavior, not a quality advantage over a single judge. Benchmark scaffolding exists under `src/agent_council/bench/`, but published comparative results and the root benchmark fixtures are not supplied. A measured improvement, effect size or completed paper is not claimed; empirical evaluation remains planned.

---

## Composability

### CLI surface

```
python -m agent_council review <artifact> --tier=N --config=<path>
python -m agent_council sweep --since=24h --config=<path>
python -m agent_council audit  --log=<path>
python -m agent_council health --config=<path>
python -m agent_council validate-config <path>
```

### Exit codes

| Code | Verdict | Meaning |
|------|---------|---------|
| 0 | SHIP | Policy and synthesis permit shipping; no participating hard/soft blocks and all present scores clear the configured bar. |
| 1 | REVISE | Changes needed; includes below-bar scores, blocks below the HOLD threshold, or the permitted non-irreducible HOLD downgrade. |
| 2 | HOLD | Enforced blocking/irreducible concern or stricter synthesis recommendation. |
| 3 | INCOMPLETE | Fewer than the minimum valid R1 reviews, or synthesis runtime/schema failure. |
| 4 | NOT_FOUND | Artifact path does not exist. |
| 5 | CONFIG_ERROR | Council YAML invalid. |

These are verdict/handled CLI statuses, not a guarantee that every setup or programming error maps to one of them. Unexpected exceptions and log-write errors propagate.

### Completion and stopping contract

Default quorum is **three schema-valid R1 reviews**, not all four. Valid R2 takes precedence; failed or disabled R2 falls back to valid R1. Valid R2 cannot rescue an invalid R1 for quorum. Invalid payloads remain in the archive but do not become approvals. The returned `error` reports R1 failure; `r2_error` reports R2 failure without disqualifying valid R1.

Each malformed response gets one schema reprompt. Runtime failures get no additional retries. Initial synthesis timeout/runtime failure, retry runtime failure, or exhausted synthesis schema validation yields persisted INCOMPLETE with `adjudicator_error` and available transcripts. Setup, unexpected programming and log-write failures are not silently converted to success; archive-write errors retain the existing stderr warning behavior.

Policy uses `ship_min_score=3`, `soft_block_score=1`, `hold_block_count=3` by default. A hard block and low-score soft block count only once per reviewer. Only participating valid-R2 irreducible flags are used. The stricter of policy and model recommendation wins except that policy HOLD may become REVISE when the model recommends REVISE and there is no participating irreducible dissent. The runtime explains enforcement differences and reports missing actionable briefs rather than inventing repairs. See [architecture](docs/architecture.md).

### Output schemas

**Verdict (returned by `Council.run()`, dumped by `--json`):**

```json
{
  "verdict": "SHIP | REVISE | HOLD | INCOMPLETE",
  "reasoning": "Final decision grounds; identifies an overridden model recommendation",
  "revision_brief": "Required changes or explicit missing-brief limitation",
  "dissent_summary": "Model summary plus recorded R2 changes and review failures",
  "deliberators": {
    "<role_id>": {
      "role": "skeptic | voice_identity | evidence | strategy",
      "r1_score": 3,
      "r1_would_block": true,
      "r2_score": 3,
      "r2_would_block": true,
      "r2_irreducible": false,
      "top_issues": ["..."],
      "r2_concessions": ["..."],
      "r2_escalations": ["..."],
      "succeeded": true,
      "error": null,
      "r1_schema_failed": false,
      "r2_schema_failed": false,
      "r2_error": null
    }
  },
  "span_id": "council-<12hex>",
  "adjudicator_error": null
}
```

This is a shape illustration: absent scores are null, and `revision_brief` is null on SHIP/INCOMPLETE. The new failure fields are additive; existing field names and verdict/exit-code enums are preserved. `succeeded` describes R1 validity, not completion of both rounds.

**Reviewer schemas:** R1 requires numeric `score` in [1,5] and boolean `would_block`; R2 additionally requires boolean `irreducible`. Prompts request richer role-specific findings, but runtime validation does not require all of them. **Model synthesis schema:** SHIP/REVISE/HOLD plus nonempty reasoning; revision brief and dissent summary remain optional. INCOMPLETE is produced by runtime enforcement, not the synthesis model's accepted enum.

**Log line (Rule 35 v2 — `council_log.jsonl`, per-role records omitted here):**

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
  "artifact_type": "linkedin_post",
  "tier": 1,
  "verdict": "REVISE",
  "deliberators": {},
  "adjudicator_reasoning": "...",
  "revision_brief": "...",
  "dissent_summary": "...",
  "adjudicator_error": null,
  "adjudicator_schema_failed": false,
  "adjudicator_reprompts": 0,
  "prior_verdicts_used": 0,
  "runtime": "claude_cli",
  "model": "sonnet",
  "elapsed_seconds": 187.4,
  "persisted": true
}
```

### Runtime adapters

| Adapter | When to use | Health check | Notes |
|---------|-------------|--------------|-------|
| `claude_cli` | Reviews using Anthropic's CLI | CLI version check | Provider authentication required |
| `lmstudio` | Local model server | See adapter health check | OpenAI-compatible HTTP, not a CLI invocation |
| `ollama` | Local model runtime | See adapter health check | Requires Ollama and an available model |
| `mock_cli` | Tests, demos, offline development | Always True | Deterministic canned output |
| `gh_models` | Placeholder only | Not a usable review runtime | No working GitHub Models invocation |

For a configured adapter, subclass `RuntimeAdapter`, implement `invoke(prompt, context, model=None)`, `health_check` and `adapter_name`, then register in `runtimes/__init__.py:build_adapter`. Python callers may instead supply `Council(config, config_dir, adapter=runtime)`: this keyword-only parameter skips factory construction, while omission/None preserves the configured default. One adapter handles all calls; per-role runtime overrides are not implemented. See the [Python example](README.md#use-a-caller-supplied-runtime).

### Modularity invariant (Condition 3)

The Council package does not import anything outside stdlib and its own modules. Verified mechanically in `tests/test_modularity_invariant.py`. No emitting-agent prompt in the host operator system references the Council — when wired into one, the same test enforces this. Verified mechanically in the same file.

---

## Versioning + compatibility

- **0.1.0** — Initial Python release: four reviewer prompts, separate synthesis and four usable runtime adapters (claude_cli, lmstudio, ollama, mock_cli). No demonstrated empirical quality lift.
- **0.2.0** — Planned evaluation: three-arm benchmark and recursive Council-on-Council validation study; companion paper proposed, not published by this repository.
- **0.3.0** — Forthcoming. Adjudicator improvements + verdict-policy refinements based on 0.2 findings. Additional runtime adapters.

Breaking changes will bump the minor version until 1.0. The verdict JSON schema, exit codes, and CLI subcommand names are the public surface; everything else is internal.

---

*Authored 2026-05-11 by Builder for P0. Updated each phase as the surface stabilizes.*
