"""CLI entrypoint — `python -m agent_council` and the `agent-council` script.

Subcommands:
    review  — gate a single artifact through the Council
    sweep   — placeholder for daily sweep (P2; raises NotImplementedError)
    audit   — summarize the JSONL log (verdict distribution, etc.)
    health  — health-check the configured runtime
    bench   — run one category/mode cell of the AgentOS-Bench harness (W2)

Exit codes:
    0 SHIP, 1 REVISE, 2 HOLD, 3 INCOMPLETE, 4 NOT_FOUND, 5 CONFIG_ERROR.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

# --- Windows UTF-8 stdout patch (Wave 7 / 2026-05-11) -----------------------
# Windows default console codepage is cp1252, which crashes on common unicode
# glyphs the council emits (arrows, em-dashes, smart-quotes). Verdicts are
# persisted to JSONL BEFORE the print, but stdout output is lost. Reconfigure
# stdout/stderr to UTF-8 so the human-readable verdict survives.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            # AttributeError: redirected stream lacks reconfigure (e.g. test capture).
            # ValueError: stream already detached. Either way, ignore — best effort.
            pass

from agent_council.config import load_config, validate_config
from agent_council.orchestrator import Council
from agent_council.tier import TierClassifier
from agent_council.verdict import (
    EXIT_HOLD,
    EXIT_INCOMPLETE,
    EXIT_NOT_FOUND,
    EXIT_REVISE,
    EXIT_SHIP,
)

EXIT_CONFIG_ERROR = 5


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="agent-council",
        description=(
            "A runtime-portable 5-agent adjudicator council for universal quality "
            "gating. Reviews an artifact via 5 deliberators in 2 async rounds, "
            "returns SHIP / REVISE / HOLD."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # review
    p_review = sub.add_parser("review", help="Gate a single artifact.")
    p_review.add_argument("artifact", help="Path to the artifact file.")
    p_review.add_argument("--tier", type=int, default=None, help="Override tier classification.")
    p_review.add_argument("--config", required=True, help="Path to council.yaml.")
    p_review.add_argument("--json", action="store_true", help="Print verdict as JSON.")

    # sweep
    p_sweep = sub.add_parser(
        "sweep",
        help="Daily artifact harvester — walks watch paths and queues eligible tier-1/3 artifacts.",
    )
    p_sweep.add_argument("--since", default="24h", help="Time window: Nh/Nd/Nw or ISO-8601.")
    p_sweep.add_argument("--config", required=True, help="Path to council.yaml.")
    p_sweep.add_argument(
        "--force",
        action="store_true",
        help="Re-gate artifacts already in council_log.jsonl.",
    )
    p_sweep.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify + filter without invoking the orchestrator.",
    )

    # audit
    p_audit = sub.add_parser(
        "audit",
        help="Markdown audit of council_log.jsonl — verdicts, behavior, drift.",
    )
    p_audit.add_argument("--log", default="./council_log.jsonl", help="Path to council_log.jsonl.")
    p_audit.add_argument(
        "--since",
        default="7d",
        help="Window: Nh/Nd/Nw or ISO-8601 (default 7d).",
    )
    p_audit.add_argument("--config", help="Optional: path to council.yaml for path-resolving the log.")
    p_audit.add_argument("--output", "--out", dest="output", help="Write report to file instead of stdout.")
    p_audit.add_argument("--json", action="store_true", help="Emit JSON instead of markdown.")
    p_audit.add_argument(
        "--min-drift-records",
        type=int,
        default=5,
        help="Minimum N records per side for drift detection (default 5).",
    )

    # health
    p_health = sub.add_parser("health", help="Health-check the configured runtime.")
    p_health.add_argument("--config", required=True)

    # validate-config helper
    p_val = sub.add_parser("validate-config", help="Validate a council.yaml file.")
    p_val.add_argument("config")

    # bench (W2) — register via the bench module so the parent CLI stays thin.
    from agent_council.bench.cli import add_bench_parser

    add_bench_parser(sub)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point used by ``python -m agent_council`` and the console script."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "review":
        return _cmd_review(args)
    if args.command == "sweep":
        from agent_council.sweep import run_sweep

        return run_sweep(args)
    if args.command == "audit":
        from agent_council.audit import run_audit

        return run_audit(args)
    if args.command == "health":
        return _cmd_health(args)
    if args.command == "validate-config":
        return _cmd_validate(args)
    if args.command == "bench":
        from agent_council.bench.cli import cmd_bench

        return cmd_bench(args)
    parser.print_help()
    return EXIT_INCOMPLETE


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def _cmd_review(args: argparse.Namespace) -> int:
    """Run a single artifact through the Council."""
    artifact_path = Path(args.artifact)
    if not artifact_path.exists():
        print(f"error: artifact not found: {artifact_path}", file=sys.stderr)
        return EXIT_NOT_FOUND

    config_path = Path(args.config).expanduser().resolve()
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

    tier = args.tier
    if tier is None:
        tc = TierClassifier(rules=config.get("tier_rules") or {})
        tier, _ = tc.classify(artifact_path)

    council = Council(config=config, config_dir=config_path.parent)
    verdict = asyncio.run(council.run(artifact_path, tier=tier))

    if args.json:
        print(verdict.to_json())
    else:
        _print_human(verdict, tier)
    return verdict.exit_code


def _cmd_audit(args: argparse.Namespace) -> int:
    """Print verdict distribution from the JSONL log."""
    log_path = Path(args.log)
    if not log_path.exists():
        print(f"no log file at {log_path}", file=sys.stderr)
        return EXIT_NOT_FOUND
    verdicts: Counter[str] = Counter()
    tiers: Counter[int] = Counter()
    n = 0
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            verdicts[rec.get("verdict", "UNKNOWN")] += 1
            tiers[int(rec.get("tier", 0))] += 1
            n += 1
    print(f"Council audit: {n} verdicts")
    print("Verdict distribution:")
    for v, c in verdicts.most_common():
        print(f"  {v:11s} {c}")
    print("Tier distribution:")
    for t, c in tiers.most_common():
        print(f"  tier {t}     {c}")
    return EXIT_SHIP


def _cmd_health(args: argparse.Namespace) -> int:
    """Check the configured runtime can be invoked."""
    config_path = Path(args.config).expanduser().resolve()
    try:
        config = load_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: cannot load config: {e}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    from agent_council.runtimes import build_adapter

    try:
        adapter = build_adapter(config.get("runtime") or {})
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    ok = adapter.health_check()
    print(f"{adapter.adapter_name()}: {'OK' if ok else 'FAIL'}")
    return EXIT_SHIP if ok else EXIT_INCOMPLETE


def _cmd_validate(args: argparse.Namespace) -> int:
    """Validate a council.yaml file's structure."""
    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    errors = validate_config(config)
    if errors:
        for e in errors:
            print(f"config error: {e}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    print("config OK")
    return EXIT_SHIP


# ---------------------------------------------------------------------------
# Human-readable verdict printer
# ---------------------------------------------------------------------------

def _print_human(verdict, tier: int) -> None:
    """Pretty-print a verdict for stdout."""
    print(f"Verdict: {verdict.verdict}  (tier {tier})")
    print(f"span_id: {verdict.span_id}")
    print()
    print("Reasoning:")
    print(f"  {verdict.reasoning}")
    if verdict.revision_brief:
        print()
        print("Revision brief:")
        for line in verdict.revision_brief.splitlines():
            print(f"  {line}")
    if verdict.dissent_summary:
        print()
        print("Dissent summary:")
        for line in verdict.dissent_summary.splitlines():
            print(f"  {line}")
    print()
    print("Deliberators:")
    for did, r in verdict.deliberators.items():
        if not r.succeeded:
            print(f"  {did:18s}  ERROR: {r.error}")
            continue
        block = "BLOCK" if r.r2_would_block else "ok   "
        irr = " IRREDUCIBLE" if r.r2_irreducible else ""
        print(
            f"  {did:18s}  r1={r.r1_score} r2={r.r2_score}  {block}{irr}"
        )
