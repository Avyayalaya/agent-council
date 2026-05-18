"""D2 — Daily sweep across watch paths (design v0.2 §5.2 trigger surface #2).

Walks ``config["watch"]["paths"]``, finds artifacts newer than ``--since``,
classifies via ``TierClassifier``, and queues tier-1 (and deterministically
sampled tier-3) artifacts through the Council.

Public surface:

    run_sweep(args: argparse.Namespace) -> int

CLI exit codes match the rest of the package (0 success, 5 config-error).

Idempotency contract: an artifact whose ``artifact_sha256`` already appears
in the council log is skipped unless ``--force`` is set. JSONL appends are
atomic on both POSIX and Windows; concurrent sweeps + manual reviews are
safe to interleave (per F2.4 in the spec).

Output: one JSON line per artifact to stderr describing the action taken
(queued | skipped | dryrun | errored). The D3 audit subcommand can be
extended to read these if operator wants per-sweep stats; the canonical
verdict log is the durable record.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from agent_council.config import load_config, validate_config
from agent_council.log import CouncilLog
from agent_council.orchestrator import Council
from agent_council.tier import TierClassifier
from agent_council.verdict import EXIT_INCOMPLETE, EXIT_SHIP

EXIT_CONFIG_ERROR = 5

# Sweep safety ceiling (F2.5) — operator can raise via config later.
MAX_FILES_PER_SWEEP = 200

# ``--since`` formats: Nh, Nd, Nw, or ISO-8601.
_SINCE_RE = re.compile(r"^(\d+)\s*([hdw])$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public entry — wired by cli.py
# ---------------------------------------------------------------------------

def run_sweep(args: argparse.Namespace) -> int:
    """Execute a sweep based on parsed CLI args.

    Reads ``config["watch"]["paths"]``, walks them, classifies and queues
    eligible artifacts. Logs one structured line per decision to stderr.
    """
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

    try:
        cutoff = parse_since(args.since)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    watch_cfg = config.get("watch") or {}
    paths_cfg = watch_cfg.get("paths") or []
    if not paths_cfg:
        print(
            "warning: no watch.paths declared in config; sweep is a no-op.",
            file=sys.stderr,
        )
        return EXIT_SHIP

    classifier = TierClassifier(rules=config.get("tier_rules") or {})

    # Discover artifacts.
    discovered: list[Path] = []
    for raw in paths_cfg:
        for found in _walk_one(raw, config_path.parent, cutoff):
            discovered.append(found)
            if len(discovered) >= MAX_FILES_PER_SWEEP:
                print(
                    json.dumps({
                        "action": "max_files_reached",
                        "limit": MAX_FILES_PER_SWEEP,
                    }),
                    file=sys.stderr,
                )
                break
        if len(discovered) >= MAX_FILES_PER_SWEEP:
            break

    # Read prior shas for idempotency.
    log_cfg = config.get("logging") or {}
    log_path = Path(log_cfg.get("log_path") or "./council_log.jsonl")
    if not log_path.is_absolute():
        log_path = (config_path.parent / log_path).resolve()
    prior_shas = _read_prior_shas(log_path) if not args.force else set()

    # Queue + run.
    council = Council(config=config, config_dir=config_path.parent)
    queued = 0
    for artifact_path in discovered:
        try:
            text = artifact_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(
                json.dumps({"action": "errored", "path": str(artifact_path), "reason": str(e)}),
                file=sys.stderr,
            )
            continue
        sha = CouncilLog.hash_artifact(text)
        tier, artifact_type = classifier.classify(artifact_path)

        if tier == 2:
            print(
                json.dumps({"action": "skipped", "path": str(artifact_path),
                            "tier": 2, "reason": "tier_2"}),
                file=sys.stderr,
            )
            continue
        if tier == 3 and not classifier.should_fire(artifact_path):
            print(
                json.dumps({"action": "skipped", "path": str(artifact_path),
                            "tier": 3, "reason": "tier_3_sampled_out"}),
                file=sys.stderr,
            )
            continue
        if sha in prior_shas and not args.force:
            print(
                json.dumps({"action": "skipped", "path": str(artifact_path),
                            "tier": tier, "reason": "already_in_log"}),
                file=sys.stderr,
            )
            continue
        if args.dry_run:
            print(
                json.dumps({"action": "dryrun", "path": str(artifact_path),
                            "tier": tier, "artifact_type": artifact_type}),
                file=sys.stderr,
            )
            queued += 1
            continue

        # Real run.
        print(
            json.dumps({"action": "queued", "path": str(artifact_path),
                        "tier": tier, "artifact_type": artifact_type}),
            file=sys.stderr,
        )
        try:
            asyncio.run(council.run(artifact_path, tier=tier, artifact_type=artifact_type))
        except Exception as e:
            print(
                json.dumps({"action": "errored", "path": str(artifact_path),
                            "reason": f"{type(e).__name__}: {e}"}),
                file=sys.stderr,
            )
            continue
        queued += 1
        # After the run, add the new sha to prior_shas so subsequent files in
        # the same sweep don't re-queue duplicates.
        prior_shas.add(sha)

    print(
        json.dumps({"action": "sweep_complete", "queued": queued,
                    "discovered": len(discovered)}),
        file=sys.stderr,
    )
    return EXIT_SHIP


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_since(raw: str) -> datetime:
    """Convert ``Nh|Nd|Nw|ISO-8601`` into a cutoff datetime (UTC).

    Raises:
        ValueError: if the format is unrecognized.
    """
    raw = raw.strip()
    m = _SINCE_RE.match(raw)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit == "h":
            delta = timedelta(hours=n)
        elif unit == "d":
            delta = timedelta(days=n)
        elif unit == "w":
            delta = timedelta(weeks=n)
        else:
            raise ValueError(f"unrecognized --since unit: {unit!r}")
        return datetime.now(timezone.utc) - delta
    # ISO-8601 attempt.
    try:
        # Accept trailing Z.
        norm = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(norm)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        raise ValueError(
            f"--since must be 'Nh', 'Nd', 'Nw', or ISO-8601; got {raw!r}"
        )


def _walk_one(raw: str, base: Path, cutoff: datetime) -> Iterator[Path]:
    """Yield Paths under ``raw`` newer than ``cutoff``.

    ``raw`` may be a directory, a file, or contain ``~``. Missing paths
    log to stderr and yield nothing (F2.1 — don't fail the whole sweep).
    """
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (base / path).resolve()
    if not path.exists():
        print(
            json.dumps({"action": "skipped", "path": str(path),
                        "reason": "not_found"}),
            file=sys.stderr,
        )
        return
    cutoff_ts = cutoff.timestamp()
    if path.is_file():
        try:
            if path.stat().st_mtime >= cutoff_ts:
                yield path
        except OSError:
            return
        return
    # Directory — walk recursively for files.
    for fp in path.rglob("*"):
        if not fp.is_file():
            continue
        try:
            if fp.stat().st_mtime >= cutoff_ts:
                yield fp
        except OSError:
            continue


def _read_prior_shas(log_path: Path) -> set[str]:
    """Read all ``artifact_sha256`` values from the council log."""
    out: set[str] = set()
    if not log_path.exists():
        return out
    try:
        with log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sha = rec.get("artifact_sha256")
                if isinstance(sha, str):
                    out.add(sha)
    except OSError:
        return out
    return out


__all__ = ["run_sweep", "parse_since", "MAX_FILES_PER_SWEEP"]
