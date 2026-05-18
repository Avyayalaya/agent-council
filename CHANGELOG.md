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

[Unreleased]: https://github.com/Avyayalaya/agent-council/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Avyayalaya/agent-council/releases/tag/v0.1.0
