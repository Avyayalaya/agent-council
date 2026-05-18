"""UnifiedJudgeModeAdapter — single runtime call + 5-criteria synthetic verdict.

This is the steel-manned "obvious simpler alternative" arm: instead of five
parallel deliberators with cross-read, do everything in a single prompt that
asks the model to (a) produce the artifact and (b) self-score on 5 criteria
(Skepticism, Voice/Identity, Evidence, Strategy, Synthesis).

Faithfully represents the single-judge alternative per locked Condition 2 —
must NOT be straw-manned (see RW2 + Synthesizer review note in the build spec).

Output schema (matches ``Artifact`` contract):
    {
      "mode": "unified_judge",
      "artifact": <raw model output, str>,
      "elapsed_seconds": float,
      "tokens": {...},
      "synthetic_verdict": {
        "skepticism": int 1-5,
        "voice_identity": int 1-5,
        "evidence": int 1-5,
        "strategy": int 1-5,
        "synthesis": int 1-5,
        "would_block": bool,
        "revision_brief": str | None,
      },
      "council_verdict": None,
    }
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from agent_council.bench.task_brief import TaskBrief
from agent_council.runtimes.base import RuntimeAdapter

# 5 locked criteria. Order is canonical and used by the judge prompt schema.
UNIFIED_CRITERIA = (
    "skepticism",
    "voice_identity",
    "evidence",
    "strategy",
    "synthesis",
)

_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE
)
_BARE_JSON_RE = re.compile(r"(\{[\s\S]*\})", re.DOTALL)


class UnifiedJudgeModeAdapter:
    """Single-prompt produce-and-judge mode (the strong-judge alternative)."""

    mode_name = "unified_judge"

    def __init__(self, runtime: RuntimeAdapter, config_dir: Path | str | None = None) -> None:
        """Configure the adapter.

        Args:
            runtime: a concrete RuntimeAdapter (mock_cli for W2 tests).
            config_dir: directory containing ``bench/prompts/unified_judge_prompt.md``
                if not the default. Defaults to the project ``bench/`` directory
                resolved relative to this file.
        """
        self.runtime = runtime
        self.config_dir = Path(config_dir) if config_dir else _default_bench_dir()
        self._prompt_text: str | None = None

    def _load_prompt(self) -> str:
        """Lazy-load the unified-judge prompt from disk (cached)."""
        if self._prompt_text is None:
            path = self.config_dir / "prompts" / "unified_judge_prompt.md"
            if not path.exists():
                # Fall back to a tiny inline prompt; tests should still pass
                # but real runs require the on-disk version.
                self._prompt_text = _MINIMAL_PROMPT_FALLBACK
            else:
                self._prompt_text = path.read_text(encoding="utf-8", errors="replace")
        return self._prompt_text

    async def run(self, brief: TaskBrief) -> dict[str, Any]:
        """Invoke the runtime once and parse the synthetic verdict.

        Args:
            brief: the task brief.

        Returns:
            Dict matching the standard mode-adapter shape.
        """
        t0 = time.time()
        judge_prompt = self._load_prompt()
        # Header order is load-bearing: the "unified_judge" marker must
        # appear in the first 500 chars so mock_cli routes deterministically
        # even for long Cat-3 briefs. Real LLMs treat headers as plain prose.
        wrapped_prompt = (
            f"# unified_judge — bench task category {brief.category} — "
            f"{brief.brief_id}\n\n"
            f"Produce an artifact for the task below, THEN evaluate your own "
            f"artifact using the 5-criteria rubric.\n\n"
            f"## Task\n\n{brief.prompt}\n\n"
            f"---\n\n{judge_prompt}\n"
        )
        raw = await self.runtime.invoke(prompt=wrapped_prompt, context=[brief.prompt])
        elapsed = time.time() - t0
        synthetic = _parse_synthetic_verdict(raw)
        approx_in = max(1, len(wrapped_prompt) // 4 + len(brief.prompt) // 4)
        approx_out = max(1, len(raw) // 4)
        return {
            "mode": self.mode_name,
            "artifact": raw,
            "elapsed_seconds": round(elapsed, 4),
            "tokens": {
                "input": approx_in,
                "output": approx_out,
                "total": approx_in + approx_out,
            },
            "synthetic_verdict": synthetic,
            "council_verdict": None,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_bench_dir() -> Path:
    """Locate the project's ``bench/`` directory relative to the package.

    Walks up from this file (src/agent_council/bench/adapters/) to the project
    root, then drops into ``bench/``.
    """
    here = Path(__file__).resolve()
    # adapters -> bench -> agent_council -> src -> project root
    project_root = here.parents[4]
    return project_root / "bench"


def _parse_synthetic_verdict(raw: str) -> dict[str, Any]:
    """Extract the JSON synthetic-verdict block from raw model output.

    Returns a fully-shaped dict (all 5 criteria default to None) so the runner
    never has to defend against missing keys.
    """
    payload = _extract_json_block(raw)
    out: dict[str, Any] = {c: None for c in UNIFIED_CRITERIA}
    out["would_block"] = False
    out["revision_brief"] = None
    if not payload:
        return out
    # Real schema lives under "criteria" or at top level. Accept both.
    src = payload.get("criteria") if isinstance(payload.get("criteria"), dict) else payload
    for c in UNIFIED_CRITERIA:
        v = src.get(c)
        if isinstance(v, dict) and "score" in v:
            out[c] = _coerce_int(v["score"])
        else:
            out[c] = _coerce_int(v)
    out["would_block"] = bool(payload.get("would_block", False))
    rb = payload.get("revision_brief")
    out["revision_brief"] = str(rb) if rb else None
    return out


def _extract_json_block(text: str) -> dict[str, Any] | None:
    """Pull the first JSON object out of a raw model response."""
    if not text:
        return None
    candidates: list[str] = []
    m = _JSON_FENCE_RE.search(text)
    if m:
        candidates.append(m.group(1))
    bare = _BARE_JSON_RE.search(text)
    if bare:
        candidates.append(bare.group(1))
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            continue
    return None


def _coerce_int(value: Any) -> int | None:
    """Best-effort int coercion."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


_MINIMAL_PROMPT_FALLBACK = (
    "## Unified Judge — Self-Evaluation\n\n"
    "After producing the artifact above, evaluate it on five criteria and "
    "respond with a JSON code block (no other commentary):\n\n"
    "```json\n"
    "{\n"
    '  "criteria": {\n'
    '    "skepticism":     {"score": 1-5, "notes": ""},\n'
    '    "voice_identity": {"score": 1-5, "notes": ""},\n'
    '    "evidence":       {"score": 1-5, "notes": ""},\n'
    '    "strategy":       {"score": 1-5, "notes": ""},\n'
    '    "synthesis":      {"score": 1-5, "notes": ""}\n'
    "  },\n"
    '  "would_block": false,\n'
    '  "revision_brief": null\n'
    "}\n"
    "```\n"
)
