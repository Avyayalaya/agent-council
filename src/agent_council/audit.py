"""D3 — `audit` subcommand: legible markdown over ``council_log.jsonl``.

Reads the verdict log line-by-line (streaming, no full-file load), filters by
``--since`` window, and emits a markdown report covering:

  1. **Verdict distribution** — count + % of SHIP / REVISE / HOLD /
     INCOMPLETE, broken down by ``artifact_type`` and by ISO week.
  2. **Deliberator behavior** — per-deliberator: block rate, irreducible
     rate, avg R1/R2 score, mean delta R1→R2.
  3. **Token spend** — total + per-artifact_type, mean/median per gate.
     Tokens come from an explicit ``tokens.total`` field (forward-compat;
     not present in W4 records). Where unavailable, ``elapsed_seconds`` is
     surfaced as a proxy.
  4. **Drift detection** — rolling 4-week verdict means per artifact_type,
     flagged if monotonic over 3+ weeks (Voice tightening OR Council
     instability — operator interprets).
  5. **Override rate** — count of ``parth_override: true`` entries (F8
     signal from design v0.2 §9).

CLI flags:
  --since=Nh|Nd|Nw|all   time window (default 7d)
  --config               point to council.yaml for log path (optional)
  --log                  override log path directly
  --out / --output       optional output file
  --json                 emit JSON instead of markdown
  --min-drift-records    minimum N records per side for drift (default 5)

Edge cases:
  - Missing log file: returns EXIT_NOT_FOUND (4) with a clear message.
  - Empty log (after filtering): emits "no data" message; exit code 0
    (graceful "no data" per F3.4 in the W4 spec, mirrored in the D3 spec).
  - Malformed JSON lines: skipped, counted in a footer field.
  - Missing ``artifact_type``: bucketed as ``unknown_type`` with a note.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

# Reuse the centralised since-parser from sweep.py so the two subcommands
# accept the same time-window grammar.
from agent_council.sweep import parse_since

EXIT_SHIP = 0
EXIT_NOT_FOUND = 4
EXIT_CONFIG_ERROR = 5


# ---------------------------------------------------------------------------
# Public entry — wired by cli.py
# ---------------------------------------------------------------------------

def run_audit(args: argparse.Namespace) -> int:
    """Execute an audit based on parsed CLI args.

    Resolves the log path (CLI flag > config), parses the window, scans the
    log, builds aggregates, and writes the rendered report to stdout or a
    file. Returns ``EXIT_SHIP`` on success, ``EXIT_NOT_FOUND`` if the log is
    absent, ``EXIT_CONFIG_ERROR`` on bad input.
    """
    log_path = _resolve_log_path(args)
    if log_path is None:
        return EXIT_CONFIG_ERROR

    if not log_path.exists():
        print(f"error: log file not found: {log_path}", file=sys.stderr)
        return EXIT_NOT_FOUND

    try:
        cutoff = _resolve_cutoff(args.since)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    records, malformed = list(_stream_records(log_path, cutoff))

    min_drift = getattr(args, "min_drift_records", 5) or 5
    report = build_report(
        records=records,
        log_path=log_path,
        cutoff=cutoff,
        since_label=args.since,
        malformed=malformed,
        min_drift_records=min_drift,
    )

    if args.json:
        rendered = json.dumps(report, indent=2, default=str)
    else:
        rendered = render_markdown(report)

    out = getattr(args, "output", None)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(rendered, encoding="utf-8")
    else:
        # Stdout — ensure UTF-8 even on Windows consoles.
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass
        print(rendered)
    return EXIT_SHIP


# ---------------------------------------------------------------------------
# Streaming reader — never loads the full log into memory.
# ---------------------------------------------------------------------------

def _stream_records(
    log_path: Path,
    cutoff: datetime | None,
) -> tuple[list[dict[str, Any]], int]:
    """Yield verdict records newer than ``cutoff``; count malformed lines.

    Filtering happens line-by-line. Non-verdict events (anything where
    ``event`` is set but not ``"verdict"``) are skipped. Records that fail
    JSON parse are counted but not surfaced to the report body.

    Returns a (records, malformed_count) tuple. Records are returned in
    file order (chronological for an append-only log).
    """
    records: list[dict[str, Any]] = []
    malformed = 0
    try:
        with log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                # Skip non-verdict events (e.g. schema_failure_log, sweep_complete).
                event = rec.get("event")
                if event and event != "verdict":
                    continue
                ts = _parse_record_ts(rec.get("ts"))
                if cutoff is not None and ts is not None and ts < cutoff:
                    continue
                records.append(rec)
    except OSError as e:
        print(f"warning: error reading log: {e}", file=sys.stderr)
    return records, malformed


def _parse_record_ts(raw: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp from a record; return None if invalid."""
    if not isinstance(raw, str):
        return None
    try:
        norm = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(norm)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _resolve_cutoff(since: str) -> datetime | None:
    """``--since`` may be a window expression OR ``all``."""
    if since and since.strip().lower() in {"all", "*", "any"}:
        return None
    return parse_since(since)


def _resolve_log_path(args: argparse.Namespace) -> Path | None:
    """Resolve the log path from CLI args (config-aware).

    Priority: ``--log`` flag (if set and non-default) > config file's
    ``logging.log_path`` > default ``./council_log.jsonl``.
    """
    config_path: Path | None = None
    config: dict[str, Any] = {}

    if getattr(args, "config", None):
        config_path = Path(args.config).expanduser().resolve()
        try:
            from agent_council.config import load_config

            config = load_config(config_path)
        except (FileNotFoundError, ValueError) as e:
            print(f"error: cannot load config: {e}", file=sys.stderr)
            return None

    # Was --log explicitly set away from the default?
    log_flag = getattr(args, "log", None)
    explicit_log = log_flag and log_flag != "./council_log.jsonl"
    if explicit_log:
        return Path(log_flag).expanduser().resolve()

    if config:
        log_cfg = config.get("logging") or {}
        cfg_log = log_cfg.get("log_path")
        if cfg_log:
            p = Path(cfg_log).expanduser()
            if not p.is_absolute() and config_path is not None:
                p = (config_path.parent / p).resolve()
            return p

    return Path(log_flag or "./council_log.jsonl").expanduser().resolve()


# ---------------------------------------------------------------------------
# Aggregation — pure functions over the records list.
# ---------------------------------------------------------------------------

def build_report(
    records: list[dict[str, Any]],
    log_path: Path,
    cutoff: datetime | None,
    since_label: str,
    malformed: int,
    min_drift_records: int = 5,
) -> dict[str, Any]:
    """Assemble the full report dict (used by both markdown + JSON renderers)."""
    return {
        "metadata": _metadata(records, log_path, cutoff, since_label, malformed),
        "verdict_distribution": _verdict_distribution(records),
        "deliberator_behavior": _deliberator_behavior(records),
        "token_spend": _token_spend(records),
        "drift_detection": _drift_detection(records, min_drift_records),
        "override_rate": _override_rate(records),
    }


def _metadata(
    records: list[dict[str, Any]],
    log_path: Path,
    cutoff: datetime | None,
    since_label: str,
    malformed: int,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "log_path": str(log_path),
        "now": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "since_label": since_label,
        "since_cutoff": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ") if cutoff else "all",
        "record_count": len(records),
        "malformed_lines": malformed,
    }


def _verdict_distribution(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Verdict counts/percents overall + by artifact_type + by ISO week."""
    overall: dict[str, int] = defaultdict(int)
    by_type: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_week: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for rec in records:
        verdict = (rec.get("verdict") or "UNKNOWN").upper()
        atype = rec.get("artifact_type") or "unknown_type"
        overall[verdict] += 1
        by_type[atype][verdict] += 1
        week = _iso_week(_parse_record_ts(rec.get("ts")))
        by_week[week][verdict] += 1

    total = sum(overall.values())
    overall_pct = {
        v: (overall[v] / total * 100.0) if total else 0.0
        for v in overall
    }
    return {
        "overall": dict(overall),
        "overall_pct": overall_pct,
        "total": total,
        "by_artifact_type": {k: dict(v) for k, v in by_type.items()},
        "by_week": {k: dict(v) for k, v in sorted(by_week.items())},
    }


def _iso_week(dt: datetime | None) -> str:
    if dt is None:
        return "unknown"
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _deliberator_behavior(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-deliberator stats across all records."""
    stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "gates_seen": 0,
        "blocks": 0,
        "irreducible": 0,
        "r1_scores": [],
        "r2_scores": [],
        "deltas": [],
        "schema_failures": 0,
        "reprompts": 0,
    })
    for rec in records:
        delibs = rec.get("deliberators") or {}
        if not isinstance(delibs, dict):
            continue
        for did, d in delibs.items():
            if not isinstance(d, dict):
                continue
            s = stats[did]
            s["gates_seen"] += 1
            if d.get("r2_would_block"):
                s["blocks"] += 1
            if d.get("r2_irreducible"):
                s["irreducible"] += 1
            r1 = d.get("r1_score")
            r2 = d.get("r2_score")
            if isinstance(r1, (int, float)):
                s["r1_scores"].append(float(r1))
            if isinstance(r2, (int, float)):
                s["r2_scores"].append(float(r2))
            if isinstance(r1, (int, float)) and isinstance(r2, (int, float)):
                s["deltas"].append(float(r2) - float(r1))
            if d.get("schema_failed"):
                s["schema_failures"] += 1
            reprompts = d.get("reprompts")
            if isinstance(reprompts, int):
                s["reprompts"] += reprompts

    out: dict[str, dict[str, Any]] = {}
    for did, s in stats.items():
        n = s["gates_seen"]
        out[did] = {
            "gates_seen": n,
            "block_rate": (s["blocks"] / n) if n else 0.0,
            "irreducible_rate": (s["irreducible"] / n) if n else 0.0,
            "avg_r1_score": (sum(s["r1_scores"]) / len(s["r1_scores"]))
                if s["r1_scores"] else None,
            "avg_r2_score": (sum(s["r2_scores"]) / len(s["r2_scores"]))
                if s["r2_scores"] else None,
            "mean_delta_r1_to_r2": (sum(s["deltas"]) / len(s["deltas"]))
                if s["deltas"] else None,
            "schema_failures": s["schema_failures"],
            "total_reprompts": s["reprompts"],
        }
    return out


def _token_spend(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Token spend stats — explicit field if present, else elapsed proxy."""
    total_tokens = 0
    by_type_tokens: dict[str, list[int]] = defaultdict(list)
    elapsed_secs: list[float] = []
    by_type_elapsed: dict[str, list[float]] = defaultdict(list)
    has_token_field = False

    for rec in records:
        atype = rec.get("artifact_type") or "unknown_type"
        tokens = _extract_tokens(rec)
        if tokens is not None:
            has_token_field = True
            total_tokens += tokens
            by_type_tokens[atype].append(tokens)
        elapsed = rec.get("elapsed_seconds")
        if isinstance(elapsed, (int, float)):
            elapsed_secs.append(float(elapsed))
            by_type_elapsed[atype].append(float(elapsed))

    def _stats(values: list[float]) -> dict[str, float | int]:
        if not values:
            return {"n": 0, "total": 0, "mean": 0.0, "median": 0.0}
        return {
            "n": len(values),
            "total": sum(values),
            "mean": sum(values) / len(values),
            "median": statistics.median(values),
        }

    return {
        "has_token_field": has_token_field,
        "total_tokens": total_tokens,
        "tokens_by_artifact_type": {
            k: _stats([float(x) for x in v]) for k, v in by_type_tokens.items()
        },
        "elapsed_overall": _stats(elapsed_secs),
        "elapsed_by_artifact_type": {
            k: _stats(v) for k, v in by_type_elapsed.items()
        },
        "estimation_note": (
            "Token figures sourced from explicit ``tokens.total`` field when "
            "present; otherwise N/A. ``elapsed_seconds`` is surfaced as a "
            "proxy operators can calibrate against their runtime's tokens/sec."
        ),
    }


def _extract_tokens(rec: dict[str, Any]) -> int | None:
    """Look for tokens in a few plausible spots; return None if absent."""
    tokens = rec.get("tokens")
    if isinstance(tokens, dict):
        total = tokens.get("total")
        if isinstance(total, int):
            return total
        if isinstance(total, float):
            return int(total)
    if isinstance(tokens, int):
        return tokens
    total = rec.get("tokens_total")
    if isinstance(total, int):
        return total
    return None


def _drift_detection(
    records: list[dict[str, Any]],
    min_records: int,
) -> dict[str, Any]:
    """Per-artifact_type rolling weekly verdict means; flag monotonic streaks.

    For each artifact_type, group records by ISO week and compute a numeric
    verdict score (SHIP=1.0, REVISE=0.5, HOLD=0.0, INCOMPLETE=0.0). If 3+
    consecutive weeks trend strictly monotonically (each step >= 0.05 in the
    same direction) AND each week has >= min_records records, flag drift.

    Returns a dict per artifact_type with weekly means + a ``flagged`` bool.
    """
    by_type_week: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for rec in records:
        atype = rec.get("artifact_type") or "unknown_type"
        verdict = (rec.get("verdict") or "").upper()
        score = _verdict_score(verdict)
        if score is None:
            continue
        week = _iso_week(_parse_record_ts(rec.get("ts")))
        by_type_week[atype][week].append(score)

    out: dict[str, Any] = {}
    for atype, weeks in by_type_week.items():
        sorted_weeks = sorted(weeks.items())
        weekly_means: list[tuple[str, float, int]] = [
            (w, sum(scores) / len(scores), len(scores))
            for w, scores in sorted_weeks
        ]
        eligible = [(w, m, n) for w, m, n in weekly_means if n >= min_records]
        flagged = False
        direction: str | None = None
        streak: list[str] = []
        if len(eligible) >= 3:
            for i in range(len(eligible) - 2):
                a = eligible[i][1]
                b = eligible[i + 1][1]
                c = eligible[i + 2][1]
                if (b - a) >= 0.05 and (c - b) >= 0.05:
                    flagged = True
                    direction = "improving"
                    streak = [w for w, _, _ in eligible[i:i + 3]]
                    break
                if (a - b) >= 0.05 and (b - c) >= 0.05:
                    flagged = True
                    direction = "tightening"
                    streak = [w for w, _, _ in eligible[i:i + 3]]
                    break
        out[atype] = {
            "weekly_means": [
                {"week": w, "verdict_mean": m, "n": n}
                for w, m, n in weekly_means
            ],
            "flagged": flagged,
            "direction": direction,
            "streak_weeks": streak,
            "min_records_per_week": min_records,
        }
    return out


def _verdict_score(verdict: str) -> float | None:
    if verdict == "SHIP":
        return 1.0
    if verdict == "REVISE":
        return 0.5
    if verdict in {"HOLD", "INCOMPLETE"}:
        return 0.0
    return None


def _override_rate(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Count ``parth_override: true`` entries (failure-mode F8 signal)."""
    overrides = 0
    overrides_by_type: dict[str, int] = defaultdict(int)
    for rec in records:
        if rec.get("parth_override") is True:
            overrides += 1
            atype = rec.get("artifact_type") or "unknown_type"
            overrides_by_type[atype] += 1
    total = len(records)
    return {
        "count": overrides,
        "total_records": total,
        "rate": (overrides / total) if total else 0.0,
        "by_artifact_type": dict(overrides_by_type),
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def render_markdown(report: dict[str, Any]) -> str:
    """Render the aggregate report as a single markdown string."""
    meta = report["metadata"]
    if meta["record_count"] == 0:
        return _render_empty_report(report)

    parts: list[str] = []
    parts.append(_render_header(meta))
    parts.append(_render_verdict_section(report["verdict_distribution"]))
    parts.append(_render_deliberator_section(report["deliberator_behavior"]))
    parts.append(_render_token_section(report["token_spend"]))
    parts.append(_render_drift_section(report["drift_detection"]))
    parts.append(_render_override_section(report["override_rate"]))
    parts.append(_render_footer(meta))
    return "\n\n".join(parts)


def _render_empty_report(report: dict[str, Any]) -> str:
    meta = report["metadata"]
    return (
        f"# Council Audit — {meta['since_label']} through {meta['now']}\n\n"
        f"No gates recorded in window.\n\n"
        f"- log_path: `{meta['log_path']}`\n"
        f"- malformed lines: {meta['malformed_lines']}\n"
    )


def _render_header(meta: dict[str, Any]) -> str:
    return (
        f"# Council Audit — {meta['since_label']} through {meta['now']}\n\n"
        f"- log: `{meta['log_path']}`\n"
        f"- record count: {meta['record_count']}\n"
        f"- malformed lines: {meta['malformed_lines']}\n"
        f"- window cutoff: {meta['since_cutoff']}"
    )


def _render_verdict_section(vd: dict[str, Any]) -> str:
    total = vd["total"]
    pct = vd["overall_pct"]
    overall = vd["overall"]

    lines: list[str] = []
    lines.append("## 1. Verdict Distribution")
    lines.append("")
    lines.append("### Overall")
    lines.append("")
    lines.append("| Verdict | Count | % |")
    lines.append("|---|---:|---:|")
    for v in sorted(overall.keys()):
        lines.append(f"| {v} | {overall[v]} | {pct.get(v, 0.0):.1f}% |")
    lines.append(f"| **Total** | **{total}** | **100.0%** |")

    lines.append("")
    lines.append("### By artifact_type")
    lines.append("")
    by_type = vd["by_artifact_type"]
    if not by_type:
        lines.append("_No records._")
    else:
        verdicts_sorted = sorted({v for d in by_type.values() for v in d})
        head = "| artifact_type | " + " | ".join(verdicts_sorted) + " | total |"
        sep = "|---|" + "|".join(["---:" for _ in verdicts_sorted]) + "|---:|"
        lines.append(head)
        lines.append(sep)
        for atype in sorted(by_type.keys()):
            d = by_type[atype]
            row_total = sum(d.values())
            row = (
                f"| {atype} | "
                + " | ".join(str(d.get(v, 0)) for v in verdicts_sorted)
                + f" | {row_total} |"
            )
            lines.append(row)

    lines.append("")
    lines.append("### By ISO week")
    lines.append("")
    by_week = vd["by_week"]
    if not by_week:
        lines.append("_No records._")
    else:
        verdicts_sorted = sorted({v for d in by_week.values() for v in d})
        head = "| Week | " + " | ".join(verdicts_sorted) + " | total |"
        sep = "|---|" + "|".join(["---:" for _ in verdicts_sorted]) + "|---:|"
        lines.append(head)
        lines.append(sep)
        for week in sorted(by_week.keys()):
            d = by_week[week]
            row_total = sum(d.values())
            row = (
                f"| {week} | "
                + " | ".join(str(d.get(v, 0)) for v in verdicts_sorted)
                + f" | {row_total} |"
            )
            lines.append(row)

    return "\n".join(lines)


def _render_deliberator_section(db: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("## 2. Deliberator Behavior")
    lines.append("")
    if not db:
        lines.append("_No deliberators observed._")
        return "\n".join(lines)
    lines.append(
        "| deliberator | gates | block_rate | irreducible | avg_r1 | avg_r2 |"
        " mean_delta | schema_fail | reprompts |"
    )
    lines.append(
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|"
    )
    for did in sorted(db.keys()):
        s = db[did]
        lines.append(
            f"| {did} | {s['gates_seen']} | "
            f"{s['block_rate']:.1%} | {s['irreducible_rate']:.1%} | "
            f"{_fmt_num(s['avg_r1_score'])} | {_fmt_num(s['avg_r2_score'])} | "
            f"{_fmt_num(s['mean_delta_r1_to_r2'])} | "
            f"{s['schema_failures']} | {s['total_reprompts']} |"
        )
    return "\n".join(lines)


def _render_token_section(ts: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("## 3. Token Spend")
    lines.append("")
    if ts["has_token_field"]:
        overall = ts["total_tokens"]
        lines.append(f"- total tokens: {overall:,}")
        lines.append("")
        lines.append("| artifact_type | n gates | total | mean/gate | median/gate |")
        lines.append("|---|---:|---:|---:|---:|")
        for atype in sorted(ts["tokens_by_artifact_type"].keys()):
            s = ts["tokens_by_artifact_type"][atype]
            lines.append(
                f"| {atype} | {s['n']} | {int(s['total']):,} | "
                f"{s['mean']:.0f} | {s['median']:.0f} |"
            )
    else:
        lines.append(
            "_No `tokens.total` field present in records. "
            "Falling back to elapsed-seconds proxy._"
        )
        lines.append("")
        overall = ts["elapsed_overall"]
        if overall["n"] == 0:
            lines.append("_No `elapsed_seconds` field either._")
        else:
            lines.append(
                f"- elapsed_seconds: n={overall['n']}, "
                f"total={overall['total']:.0f}s, "
                f"mean={overall['mean']:.1f}s, "
                f"median={overall['median']:.1f}s"
            )
            lines.append("")
            lines.append("| artifact_type | n gates | total_s | mean_s | median_s |")
            lines.append("|---|---:|---:|---:|---:|")
            for atype in sorted(ts["elapsed_by_artifact_type"].keys()):
                s = ts["elapsed_by_artifact_type"][atype]
                lines.append(
                    f"| {atype} | {s['n']} | {s['total']:.0f} | "
                    f"{s['mean']:.1f} | {s['median']:.1f} |"
                )
    lines.append("")
    lines.append(f"_{ts['estimation_note']}_")
    return "\n".join(lines)


def _render_drift_section(drift: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("## 4. Drift Detection")
    lines.append("")
    lines.append(
        "_Verdict scores: SHIP=1.0, REVISE=0.5, HOLD/INCOMPLETE=0.0. "
        "A run of 3+ consecutive weeks with monotonic step >= 0.05 flags "
        "drift — operator interprets whether that's voice tightening, "
        "Council instability, or genuine quality movement._"
    )
    lines.append("")
    if not drift:
        lines.append("_No artifact types observed._")
        return "\n".join(lines)
    for atype in sorted(drift.keys()):
        info = drift[atype]
        flag = (
            f" **DRIFT FLAGGED** ({info['direction']} over "
            f"{', '.join(info['streak_weeks'])})"
            if info["flagged"] else ""
        )
        lines.append(f"### {atype}{flag}")
        lines.append("")
        weekly = info["weekly_means"]
        if not weekly:
            lines.append("_No weekly data._")
            lines.append("")
            continue
        lines.append("| week | n | verdict_mean |")
        lines.append("|---|---:|---:|")
        for w in weekly:
            lines.append(f"| {w['week']} | {w['n']} | {w['verdict_mean']:.2f} |")
        lines.append("")
    return "\n".join(lines).rstrip()


def _render_override_section(ov: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("## 5. Override Rate (F8 signal)")
    lines.append("")
    lines.append(
        f"- `parth_override: true` entries: **{ov['count']}** "
        f"of {ov['total_records']} records "
        f"({ov['rate']:.1%})"
    )
    if ov["by_artifact_type"]:
        lines.append("")
        lines.append("| artifact_type | overrides |")
        lines.append("|---|---:|")
        for atype in sorted(ov["by_artifact_type"].keys()):
            lines.append(f"| {atype} | {ov['by_artifact_type'][atype]} |")
    return "\n".join(lines)


def _render_footer(meta: dict[str, Any]) -> str:
    return (
        "---\n\n"
        "## Audit Metadata\n\n"
        f"- log_path: `{meta['log_path']}`\n"
        f"- generated_at: {meta['now']}\n"
        f"- record_count: {meta['record_count']}\n"
        f"- malformed_lines: {meta['malformed_lines']}\n"
        f"- since_label: `{meta['since_label']}`\n"
    )


def _fmt_num(x: float | int | None) -> str:
    if x is None:
        return "—"
    return f"{x:.2f}"


__all__ = ["run_audit", "build_report", "render_markdown"]
