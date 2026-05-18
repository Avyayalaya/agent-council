"""Bench subcommand handler — wired into the top-level ``agent-council`` CLI.

This module exposes:
    - ``add_bench_parser(sub)``: append the ``bench`` subparser to the parent
      argparse subparsers object (called from ``agent_council.cli``).
    - ``cmd_bench(args)``: handler invoked when ``bench`` is selected.

Exit codes:
    0 = run succeeded; results directory written.
    3 = INCOMPLETE (run started but did not produce a usable composite).
    4 = NOT_FOUND (config or category fixtures missing).
    5 = CONFIG_ERROR (invalid arguments or config).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from agent_council.bench.runner import BenchRunner
from agent_council.config import load_config, validate_config

# Mirror the parent module's exit codes (kept here to avoid circular import).
EXIT_OK = 0
EXIT_INCOMPLETE = 3
EXIT_NOT_FOUND = 4
EXIT_CONFIG_ERROR = 5

# 3 locked bench arms per Build Handoff Spec P1 W2 Condition 2.
LOCKED_MODES = ("baseline", "unified_judge", "council")
LOCKED_CATEGORIES = (1, 2, 3, 7)


def add_bench_parser(sub: "argparse._SubParsersAction") -> None:
    """Register the ``bench`` subcommand on the parent parser.

    Args:
        sub: the parent argparse subparsers handle (the same object returned
            by ``parser.add_subparsers(...)`` in ``agent_council.cli``).
    """
    p = sub.add_parser(
        "bench",
        help="Run one category/mode cell of the AgentOS-Bench harness.",
        description=(
            "Run the AgentOS-Bench harness for one category against one of "
            "the 3 locked arms (baseline | unified_judge | council). W2 "
            "scaffold: self-tests run against mock_cli only — real Claude "
            "burn is W3 work."
        ),
    )
    p.add_argument(
        "--category",
        type=int,
        required=True,
        choices=list(LOCKED_CATEGORIES),
        help="Bench category: 1=Continuity, 2=Correction Compounding, 3=Quality Escalation, 7=Guardrail Enforcement.",
    )
    p.add_argument(
        "--mode",
        type=str,
        required=True,
        choices=list(LOCKED_MODES),
        help="Locked bench arm. No 4th arm; do not collapse arms.",
    )
    p.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path to a council.yaml (drives the runtime).",
    )
    p.add_argument(
        "--out",
        type=str,
        required=True,
        help="Directory to write results into (created if missing).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap on briefs evaluated (default: all). Use 2-3 for fast tests.",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Deterministic seed for brief shuffling (default: unseeded).",
    )
    p.add_argument(
        "--bench-root",
        type=str,
        default=None,
        help="Override the bench/ directory (default: project bench/).",
    )


def cmd_bench(args: argparse.Namespace) -> int:
    """Handle the ``bench`` subcommand.

    Args:
        args: parsed argparse namespace from ``add_bench_parser``.

    Returns:
        Exit code (0 = success).
    """
    # Validate config first — fail fast before launching async work.
    config_path = Path(args.config).expanduser().resolve()
    if not config_path.exists():
        print(f"error: config not found: {config_path}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    try:
        config = load_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: cannot load config: {e}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    errors = validate_config(config)
    if errors:
        for e in errors:
            print(f"config error: {e}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    bench_root = Path(args.bench_root).expanduser() if args.bench_root else None
    out_dir = Path(args.out).expanduser()

    try:
        runner = BenchRunner.from_council_config(
            config=config,
            bench_root=bench_root,
            config_dir=config_path.parent,
        )
        result = asyncio.run(
            runner.run(
                category=args.category,
                mode=args.mode,
                out_dir=out_dir,
                limit=args.limit,
                seed=args.seed,
            )
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_NOT_FOUND
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except RuntimeError as e:
        # CouncilModeAdapter raises this when a non-mock runtime is used
        # without the explicit AGENT_COUNCIL_BENCH_REAL_OK override.
        print(f"error: {e}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    # Print a compact human-readable summary.
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    if result.session_count == 0:
        return EXIT_INCOMPLETE
    return EXIT_OK
