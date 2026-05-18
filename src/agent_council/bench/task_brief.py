"""TaskBrief — single bench task input + per-category loader.

A ``TaskBrief`` is the unit of work for the bench: one scenario for the SUT
to produce output against. Each of the 4 W2 categories (1 Continuity, 2
Correction Compounding, 3 Quality Escalation, 7 Guardrail Enforcement)
declares its briefs as JSONL or markdown alongside a YAML manifest. This
loader normalizes them to a uniform ``TaskBrief`` shape so the runner does
not need to know each category's storage format.

Layout (relative to the project root ``bench/``):
    tasks/category_1/continuity_sets.jsonl
    tasks/category_1/manifest.yaml
    tasks/category_2/correction_set_v1.jsonl
    tasks/category_2/manifest.yaml
    tasks/category_3/q_analysis.md
    tasks/category_3/q_writing.md
    tasks/category_3/manifest.yaml
    tasks/category_7/guardrail_scenarios.jsonl
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Category integer -> directory name. Keep in sync with bench/tasks/.
CATEGORY_DIRS = {
    1: "category_1",
    2: "category_2",
    3: "category_3",
    7: "category_7",
}

# Human label for each category (used in summary.md and composite.json).
CATEGORY_LABELS = {
    1: "Session Continuity",
    2: "Correction Compounding",
    3: "Quality Escalation",
    7: "Guardrail Enforcement",
}


@dataclass
class TaskBrief:
    """One bench task brief.

    Fields are intentionally permissive — different categories store
    different metadata, and the loader normalizes them into this shape.
    Required fields (always present): ``category``, ``brief_id``, ``prompt``.

    ``expected_violations`` and ``scoring_keys`` carry category-specific
    metadata the judge / scorer consume; they are not interpreted by the
    runner itself.
    """

    category: int
    brief_id: str
    prompt: str
    expected_violations: list[str] = field(default_factory=list)
    scoring_keys: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSONL persistence."""
        return {
            "category": self.category,
            "brief_id": self.brief_id,
            "prompt": self.prompt,
            "expected_violations": list(self.expected_violations),
            "scoring_keys": dict(self.scoring_keys),
        }


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------

def load_briefs(category: int, bench_root: Path | str) -> list[TaskBrief]:
    """Load all briefs for ``category`` from ``bench_root/tasks/category_N/``.

    Args:
        category: one of ``1, 2, 3, 7`` (W2 scope).
        bench_root: the ``bench/`` directory holding ``tasks/``.

    Returns:
        Non-empty list of TaskBrief in deterministic order (sorted by brief_id
        within a file, files traversed in alphabetical order).

    Raises:
        ValueError: if category is not in W2 scope.
        FileNotFoundError: if the category directory does not exist.
    """
    if category not in CATEGORY_DIRS:
        raise ValueError(
            f"Unknown bench category: {category!r}. "
            f"W2 scope: {sorted(CATEGORY_DIRS)}."
        )
    root = Path(bench_root).expanduser()
    cat_dir = root / "tasks" / CATEGORY_DIRS[category]
    if not cat_dir.exists():
        raise FileNotFoundError(
            f"Category {category} task directory not found: {cat_dir}"
        )

    # Each category has its own assembly. Keep loaders specific so the
    # different on-disk shapes never accidentally mix.
    if category == 7:
        return _load_category_7(cat_dir)
    if category == 1:
        return _load_category_1(cat_dir)
    if category == 2:
        return _load_category_2(cat_dir)
    if category == 3:
        return _load_category_3(cat_dir)
    # Unreachable, but keeps type-checkers happy.
    raise ValueError(f"No loader for category {category}.")  # pragma: no cover


# ---------------------------------------------------------------------------
# Per-category loaders
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Parse a JSONL file into a list of dicts."""
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"Invalid JSON in {path} line {lineno}: {e}"
                ) from e
    return out


def _load_category_7(cat_dir: Path) -> list[TaskBrief]:
    """Category 7: Guardrail Enforcement — one JSONL with 30 scenarios."""
    rows = _load_jsonl(cat_dir / "guardrail_scenarios.jsonl")
    briefs: list[TaskBrief] = []
    for row in rows:
        sid = row.get("scenario_id") or row.get("brief_id")
        if not sid:
            continue
        brief = row.get("brief") or row.get("prompt") or ""
        guardrail = row.get("guardrail", "")
        kind = row.get("kind", "violation")
        expected = []
        if kind == "violation" and guardrail:
            expected.append(guardrail)
        briefs.append(
            TaskBrief(
                category=7,
                brief_id=str(sid),
                prompt=str(brief),
                expected_violations=expected,
                scoring_keys={
                    "guardrail": guardrail,
                    "kind": kind,
                    "expected_catch": row.get("expected_catch", kind == "violation"),
                },
                raw=row,
            )
        )
    briefs.sort(key=lambda b: b.brief_id)
    return briefs


def _load_category_1(cat_dir: Path) -> list[TaskBrief]:
    """Category 1: Continuity — 3 sets x 10 context + 10 probes = 60 rows."""
    rows = _load_jsonl(cat_dir / "continuity_sets.jsonl")
    briefs: list[TaskBrief] = []
    for row in rows:
        sid = row.get("brief_id") or row.get("id")
        if not sid:
            continue
        briefs.append(
            TaskBrief(
                category=1,
                brief_id=str(sid),
                prompt=str(row.get("brief") or row.get("prompt") or ""),
                expected_violations=[],
                scoring_keys={
                    "set_id": row.get("set_id"),
                    "kind": row.get("kind"),  # "context" or "probe"
                    "session": row.get("session"),
                    "expected_answer": row.get("expected_answer"),
                },
                raw=row,
            )
        )
    briefs.sort(key=lambda b: b.brief_id)
    return briefs


def _load_category_2(cat_dir: Path) -> list[TaskBrief]:
    """Category 2: Correction Compounding — 3 sets x 10 violations = 30 rows."""
    rows = _load_jsonl(cat_dir / "correction_set_v1.jsonl")
    briefs: list[TaskBrief] = []
    for row in rows:
        sid = row.get("violation_id") or row.get("brief_id")
        if not sid:
            continue
        briefs.append(
            TaskBrief(
                category=2,
                brief_id=str(sid),
                prompt=str(row.get("probe_brief") or row.get("brief") or row.get("prompt") or ""),
                expected_violations=[str(row.get("type", "unknown"))],
                scoring_keys={
                    "set_id": row.get("set_id"),
                    "violation_type": row.get("type"),
                    "correction_phrase": row.get("correction_phrase"),
                },
                raw=row,
            )
        )
    briefs.sort(key=lambda b: b.brief_id)
    return briefs


def _load_category_3(cat_dir: Path) -> list[TaskBrief]:
    """Category 3: Quality Escalation — same brief repeated `sessions_per_brief` times.

    Quality Escalation measures whether quality improves across N attempts at
    the SAME task brief. The on-disk shape is one markdown file per brief type
    (q_analysis, q_writing, ...). The bench must iterate each brief
    ``sessions_per_brief`` times so the scorer can compute a delta from
    session 1 → session N (or specifically at checkpoint sessions 1, 5, 10, 20
    per agentos_bench_spec §2.4).

    Session iteration count is read from ``<cat_dir>/manifest.yaml`` if
    available; falls back to 20 (spec default). Each iteration produces a
    TaskBrief with the SAME prompt but a unique ``brief_id`` of the form
    ``{stem}_S{NN}`` (e.g. ``q_analysis_S01``) so the writer can index
    per-session results without collisions.

    Honest caveat: at ~160s per Cat 3 session on Opus 4.7 and 40 sessions per
    arm (20 × 2 briefs), the baseline + treatment runs are ~3.5 hours total.
    Council mode on Cat 3 is 5-10× slower per session and is impractical for
    a single cliff window — the v1 delta_report defers Cat 3 council-mode
    measurement to v2. The fixed loader still produces correct counts in case
    a future run wants them.
    """
    # Default session count per spec; override from manifest if present.
    sessions_per_brief = 20
    manifest_path = cat_dir / "manifest.yaml"
    if manifest_path.exists():
        try:
            text = manifest_path.read_text(encoding="utf-8", errors="replace")
            # Tiny inline parse — avoids requiring yaml at import time.
            for line in text.splitlines():
                line_strip = line.strip()
                if line_strip.startswith("sessions_per_brief:"):
                    try:
                        sessions_per_brief = int(line_strip.split(":", 1)[1].strip())
                    except (ValueError, IndexError):
                        pass
                    break
        except OSError:
            pass

    briefs: list[TaskBrief] = []
    for md_file in sorted(cat_dir.glob("q_*.md")):
        text = md_file.read_text(encoding="utf-8", errors="replace")
        stem = md_file.stem  # e.g. "q_analysis"
        for session_idx in range(1, sessions_per_brief + 1):
            brief_id = f"{stem}_S{session_idx:02d}"
            briefs.append(
                TaskBrief(
                    category=3,
                    brief_id=brief_id,
                    prompt=text,
                    expected_violations=[],
                    scoring_keys={
                        "brief_kind": stem.removeprefix("q_"),
                        "brief_stem": stem,
                        "session_index": session_idx,
                        "is_checkpoint": session_idx in (1, 5, 10, 20),
                    },
                    raw={"path": str(md_file), "session_index": session_idx},
                )
            )
    return briefs
