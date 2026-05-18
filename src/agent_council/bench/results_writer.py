"""ResultsWriter — emits per-session JSONL + summary.md + composite.json.

A single ``ResultsWriter`` instance owns one bench run's output directory.
For each scored session, the runner calls :meth:`write_session`. When the
run completes, :meth:`finalize` emits the human-readable summary and the
machine-readable composite score.

Output layout (matches design.md §7 + Build Handoff Spec §2):
    <out_dir>/
        sessions.jsonl       — one JSONL line per session
        summary.md           — human-readable per-category summary
        composite.json       — final composite + per-category numeric scores
        meta.json            — run metadata (category, mode, seed, timestamps)
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_council.bench.task_brief import CATEGORY_LABELS


class ResultsWriter:
    """One-run results writer (one bench run = one output directory)."""

    def __init__(
        self,
        out_dir: Path | str,
        category: int,
        mode: str,
        seed: int | None = None,
        runtime_name: str = "unknown",
    ) -> None:
        """Configure the writer.

        Args:
            out_dir: destination directory (created if missing).
            category: bench category number (1, 2, 3, 7).
            mode: one of ``baseline | unified_judge | council``.
            seed: deterministic seed for the run (None = unseeded).
            runtime_name: adapter name (``mock_cli``, ``claude_cli``, ...).
        """
        self.out_dir = Path(out_dir).expanduser()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.category = int(category)
        self.mode = str(mode)
        self.seed = seed
        self.runtime_name = runtime_name
        self.session_count = 0
        self.skipped_count = 0
        self._sessions_path = self.out_dir / "sessions.jsonl"
        self._summary_path = self.out_dir / "summary.md"
        self._composite_path = self.out_dir / "composite.json"
        self._meta_path = self.out_dir / "meta.json"
        self._start_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._scores: list[float] = []
        self._catches: int = 0
        self._violations: int = 0
        self._fp: int = 0
        self._controls: int = 0
        self._skips_by_reason: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Per-session writes
    # ------------------------------------------------------------------
    def write_session(self, record: dict[str, Any]) -> None:
        """Persist one session's result.

        Args:
            record: dict expected to contain at minimum
                ``brief_id``, ``mode``, ``artifact_preview``, ``uqr_score``
                (numeric, 0-100), and optionally ``catch`` (bool) +
                ``kind`` (``violation``/``control``) for Category 7.
        """
        self.session_count += 1
        # Track aggregates for finalize().
        uqr = record.get("uqr_score")
        if isinstance(uqr, (int, float)):
            self._scores.append(float(uqr))
        kind = record.get("kind")
        caught = bool(record.get("catch", False))
        if kind == "violation":
            self._violations += 1
            if caught:
                self._catches += 1
        elif kind == "control":
            self._controls += 1
            if caught:
                self._fp += 1

        line = dict(record)
        line.setdefault("category", self.category)
        line.setdefault("mode", self.mode)
        line.setdefault("session_index", self.session_count)
        with self._sessions_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def write_skipped(
        self,
        brief: Any,
        reason: str,
        error: str,
        elapsed_seconds: float = 0.0,
    ) -> None:
        """Persist a skip marker for a session that failed before scoring.

        A skipped row does NOT advance ``session_count`` (so composite-score
        averages remain over scored sessions only). It DOES advance
        ``skipped_count`` and is appended to ``sessions.jsonl`` with the
        ``skipped: true`` flag so post-hoc inspection can find it.

        Args:
            brief: the TaskBrief that was being processed (we only read
                ``brief_id`` and ``category`` off it).
            reason: short tag — ``"timeout"`` or ``"error"``.
            error: human-readable error class/message for logs.
            elapsed_seconds: wall-clock spent before the failure.
        """
        self.skipped_count += 1
        self._skips_by_reason[reason] = self._skips_by_reason.get(reason, 0) + 1
        line = {
            "brief_id": getattr(brief, "brief_id", "unknown"),
            "mode": self.mode,
            "category": getattr(brief, "category", self.category),
            "session_index": self.session_count + self.skipped_count,
            "skipped": True,
            "skip_reason": reason,
            "error": error,
            "elapsed_seconds": round(float(elapsed_seconds), 4),
        }
        with self._sessions_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # Finalize the run
    # ------------------------------------------------------------------
    def finalize(self) -> dict[str, Any]:
        """Write ``summary.md`` + ``composite.json`` + ``meta.json``.

        Returns:
            The composite score record (also written to ``composite.json``).
        """
        end_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        mean_uqr = round(statistics.fmean(self._scores), 2) if self._scores else 0.0
        median_uqr = round(statistics.median(self._scores), 2) if self._scores else 0.0
        max_uqr = round(max(self._scores), 2) if self._scores else 0.0
        min_uqr = round(min(self._scores), 2) if self._scores else 0.0

        # Category 7 has a different headline metric — catch rate.
        if self.category == 7 and self._violations > 0:
            catch_rate = round(100.0 * self._catches / self._violations, 2)
            fp_rate = (
                round(100.0 * self._fp / self._controls, 2) if self._controls else 0.0
            )
            composite_score = catch_rate
        else:
            catch_rate = None
            fp_rate = None
            composite_score = mean_uqr

        composite = {
            "category": self.category,
            "category_label": CATEGORY_LABELS.get(self.category, str(self.category)),
            "mode": self.mode,
            "runtime": self.runtime_name,
            "session_count": self.session_count,
            "skipped_count": self.skipped_count,
            "skipped_by_reason": dict(self._skips_by_reason),
            "seed": self.seed,
            "uqr": {
                "mean": mean_uqr,
                "median": median_uqr,
                "min": min_uqr,
                "max": max_uqr,
            },
            "guardrail": {
                "violations_evaluated": self._violations,
                "violations_caught": self._catches,
                "controls_evaluated": self._controls,
                "false_positives": self._fp,
                "catch_rate_pct": catch_rate,
                "false_positive_rate_pct": fp_rate,
            } if self.category == 7 else None,
            "composite_score": composite_score,
            "start_ts": self._start_ts,
            "end_ts": end_ts,
        }
        self._composite_path.write_text(
            json.dumps(composite, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Human-readable summary.
        lines: list[str] = []
        lines.append(f"# Bench run summary — Category {self.category} ({CATEGORY_LABELS.get(self.category, '')})\n")
        lines.append(f"- **Mode:** `{self.mode}`")
        lines.append(f"- **Runtime:** `{self.runtime_name}`")
        lines.append(f"- **Sessions scored:** {self.session_count}")
        if self.skipped_count:
            reason_str = ", ".join(
                f"{k}={v}" for k, v in sorted(self._skips_by_reason.items())
            )
            lines.append(f"- **Sessions skipped:** {self.skipped_count} ({reason_str})")
        else:
            lines.append(f"- **Sessions skipped:** 0")
        lines.append(f"- **Seed:** {self.seed if self.seed is not None else 'unseeded'}")
        lines.append(f"- **Start:** {self._start_ts}")
        lines.append(f"- **End:** {end_ts}\n")
        lines.append("## UQR scores (0-100)\n")
        lines.append(f"- mean = {mean_uqr}")
        lines.append(f"- median = {median_uqr}")
        lines.append(f"- min = {min_uqr}")
        lines.append(f"- max = {max_uqr}\n")
        if self.category == 7:
            lines.append("## Guardrail enforcement (Category 7)\n")
            lines.append(f"- violations evaluated: {self._violations}")
            lines.append(f"- violations caught: {self._catches}")
            lines.append(f"- catch rate: {catch_rate}%")
            lines.append(f"- controls evaluated: {self._controls}")
            lines.append(f"- false positives: {self._fp}")
            lines.append(f"- false positive rate: {fp_rate}%\n")
        lines.append("## Composite score\n")
        lines.append(f"- **{composite_score}** (0-100 scale)\n")
        lines.append("> W2 scaffold — scores against mock_cli are not meaningful as model-quality signal.")
        self._summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Run metadata.
        meta = {
            "category": self.category,
            "mode": self.mode,
            "runtime": self.runtime_name,
            "seed": self.seed,
            "session_count": self.session_count,
            "skipped_count": self.skipped_count,
            "start_ts": self._start_ts,
            "end_ts": end_ts,
            "out_dir": str(self.out_dir),
            "files": {
                "sessions": str(self._sessions_path.name),
                "summary": str(self._summary_path.name),
                "composite": str(self._composite_path.name),
            },
        }
        self._meta_path.write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return composite
