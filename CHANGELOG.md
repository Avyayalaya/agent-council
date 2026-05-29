# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned for 0.2.0

- Empirical evaluation: AgentOS-Bench-style 3-arm benchmark (baseline / unified-judge / Council) with statistical confidence intervals
- Recursive Council-on-Council validation study
- Cross-model sanity check (one deliberator on a different model family)
- Companion paper released to arXiv
- BibTeX appendix with verified citations

## [0.1.1] — 2026-05-29

### Added

- 5 deliberator-as-Skills under `skills/`: `skeptic-review`, `voice-identity-review`, `evidence-calibration-review`, `strategy-stakes-review`, `adjudicator-synthesis` — each ~200-260 lines following the Anthropic Skill format (frontmatter + Purpose + When to Use / NOT use + Standalone vs Composed + Method + Output Format + Worked Example + Failure Modes + Related)
- `composes_with` relations between the 5 skills (use-together, produces-input-for, consumes-output-of) so any APM harness can route between them
- `composes_with` relations to `pm-skills` (specification-writing, executive-writing, narrative-building, discovery-research, competitive-market-analysis, metric-design-experimentation, product-strategy, go-to-market-strategy, stakeholder-alignment, multi-channel-publishing) — the Council deliberators are pre-wired to review pm-skills outputs
- `apm.yml` and `.claude-plugin/marketplace.json` updated to list the new skills with paths
- README "Use in Copilot CLI / any APM harness" section documenting the Skills as the interactive single-perspective review surface alongside the CLI as the automated multi-round Council

### Changed

- Package description updated to surface Skills + slash commands + MCP server as three distinct surfaces with clear use cases
- `keywords` in apm.yml added `copilot-cli` and `skills`

### Notes for reviewers

This release addresses awesome-copilot review feedback (github/awesome-copilot#1850) flagging that Claude Code slash commands are not respected by Copilot CLI. The slash commands stay in place for Claude Code ergonomics. The new Skills give Copilot CLI (and any APM-installed harness) the methodology inline — install one Skill to play a single deliberator role on a doc you are editing, compose 2-3 Skills for richer ad-hoc review, or run the full automated 5-deliberator Council via the unchanged CLI / MCP surface. The Python package, MCP server, runtime adapters, and 105 unit tests are unchanged from v0.1.0.

## [0.1.0] — 2026-05-18

### Added

- Initial public release
- 5 role-conditioned deliberators: Skeptic, Voice & Identity, Evidence & Calibration, Strategy & Stakes, Adjudicator
- 2-round async protocol with cross-read rebuttal
- Adjudicator merge + D6 compounding loop (prior-verdict lookup on same artifact_type)
- Verdict-policy override (Adjudicator can downgrade HOLD → REVISE on non-irreducible 3+ blocks)
- 4 runtime adapters: `claude_cli`, `lmstudio`, `ollama`, `mock_cli`
- Documented fallback stub for `gh_models`
- CLI subcommands: `review`, `sweep`, `audit`
- Schema enforcement with single re-prompt and no-dissent fallback
- Audit log in `council_log.jsonl` (append-only, Rule 35 v2 format)
- Tier classification (rule-based)
- Modularity invariant test — CI-tested separation from any host operator system
- 105 unit tests
- Claude Code plugin manifest (`.claude-plugin/`) with `/council-review` and `/council-sweep` slash commands
- Example stub files for voice corpus, goals doc, and persona DNA

### Known limitations

- Empirical evaluation deferred to 0.2 — v0.1.0 ships architecture + design only
- Same-model self-style risk when all deliberators run on the same underlying model
- Adjudicator non-determinism on same artifact across runs (honest LLM-as-judge variance)
- LM Studio HTTP 500 on large parallel prompts at default concurrency

[Unreleased]: https://github.com/Avyayalaya/agent-council/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/Avyayalaya/agent-council/releases/tag/v0.1.1
[0.1.0]: https://github.com/Avyayalaya/agent-council/releases/tag/v0.1.0
