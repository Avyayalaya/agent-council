"""agent_council.bench — AgentOS-Bench harness for the 3-arm Council bench.

This sub-package implements the W2 scaffold for the AgentOS-Bench validation
harness (design.md §7). It is locked to 3 arms: ``baseline | unified_judge |
council`` (Build Handoff Spec P1 W2, locked Condition 2, 2026-05-11 amendment).

Public surface:
    BenchRunner      — orchestrates a (category x mode) run end-to-end
    TaskBrief        — single benchmark task brief (input)
    BenchResult      — summary of one bench run
    load_briefs      — load all briefs for a category from disk
    ResultsWriter    — JSONL + summary.md + composite.json emitter
    UQRJudge         — 6-dimension UQR judge (Appendix A of agentos_bench_spec)
    UQRScore         — judge output dataclass

W2 status: scaffold complete; all self-tests run against mock_cli. Real
``claude_cli`` runs are W3 work, separately authorized.
"""

from agent_council.bench.judge import UQRJudge, UQRScore
from agent_council.bench.results_writer import ResultsWriter
from agent_council.bench.runner import BenchResult, BenchRunner
from agent_council.bench.task_brief import TaskBrief, load_briefs

__all__ = [
    "BenchRunner",
    "BenchResult",
    "TaskBrief",
    "load_briefs",
    "ResultsWriter",
    "UQRJudge",
    "UQRScore",
]
