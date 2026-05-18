#!/usr/bin/env python3
"""
Agent Council MCP Server — exposes the Council quality gate to MCP-aware
clients (Claude Desktop, Cursor, Cline, custom agents).

Tools:
  - council_review(artifact_path, tier=1, artifact_type=None, config=None)
      Run the 5-deliberator Council on an artifact. Returns the full Verdict
      structure (round1, round2, adjudicator synthesis, final_verdict, revision
      brief). The audit row is also appended to council_log.jsonl.

Future tools (v0.1.2+):
  - council_sweep: bulk review over watch paths
  - council_audit: query the append-only log

Start (manual): python mcp/agent_council_mcp_server.py
Register in your client's MCP config:

  {
    "mcpServers": {
      "agent-council": {
        "command": "python",
        "args": ["<absolute-path>/agent-council/mcp/agent_council_mcp_server.py"],
        "env": {
          "COUNCIL_CONFIG": "<absolute-path>/agent-council/council.yaml"
        }
      }
    }
  }

Requires:
  - The `agent-council` package installed (pip install -e .)
  - A council.yaml in the working directory OR the COUNCIL_CONFIG env var set
  - The `mcp` package (pip install mcp>=1.0)
"""
from __future__ import annotations

import os
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

# Make sure src/ is importable when running from the repo root
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:
    print(
        "ERROR: The `mcp` package is required. Install with: pip install mcp>=1.0",
        file=sys.stderr,
    )
    raise SystemExit(1) from e

try:
    from agent_council.orchestrator import Council
    from agent_council.config import load_config
except ImportError as e:
    print(
        f"ERROR: agent_council package not found. Install with: pip install -e .\n"
        f"  Detail: {e}",
        file=sys.stderr,
    )
    raise SystemExit(1) from e


def _resolve_config(explicit: str | None) -> Path:
    """Resolve the council.yaml location.

    Order: explicit arg > COUNCIL_CONFIG env var > ./council.yaml > error.
    """
    if explicit:
        return Path(explicit).expanduser().resolve()
    env_path = os.environ.get("COUNCIL_CONFIG")
    if env_path:
        return Path(env_path).expanduser().resolve()
    cwd_candidate = Path.cwd() / "council.yaml"
    if cwd_candidate.exists():
        return cwd_candidate
    raise FileNotFoundError(
        "No council.yaml found. Pass `config=` explicitly, set COUNCIL_CONFIG, "
        "or run from a directory containing council.yaml."
    )


def _verdict_to_dict(verdict: Any) -> dict[str, Any]:
    """Convert a Verdict dataclass (or already-dict) into JSON-safe dict."""
    if is_dataclass(verdict):
        return asdict(verdict)
    if isinstance(verdict, dict):
        return verdict
    # Fall back: rely on attribute access
    return {k: getattr(verdict, k) for k in dir(verdict) if not k.startswith("_")}


mcp = FastMCP("agent-council")


@mcp.tool()
async def council_review(
    artifact_path: str,
    tier: int = 1,
    artifact_type: str | None = None,
    config: str | None = None,
) -> dict[str, Any]:
    """Run the 5-deliberator Council on a single text artifact.

    Args:
        artifact_path: Absolute or relative path to the artifact to review.
        tier: Tier classification — 1 (always review), 2 (skip), 3 (sample).
        artifact_type: Optional controlled-vocabulary label (e.g. "linkedin_post").
            Used for the D6 compounding loop — verdict history is keyed on this.
            If omitted, derived from tier_rules globs in council.yaml.
        config: Optional path to council.yaml. Defaults to $COUNCIL_CONFIG or
            ./council.yaml.

    Returns:
        Full verdict dict with round1/round2 deliberator outputs, Adjudicator
        synthesis, final_verdict (SHIP/REVISE/HOLD), and revision_brief.
        The audit row is also appended to council_log.jsonl.
    """
    cfg_path = _resolve_config(config)
    cfg = load_config(cfg_path)
    artifact = Path(artifact_path).expanduser().resolve()
    if not artifact.exists():
        raise FileNotFoundError(f"Artifact not found: {artifact}")

    council = Council(cfg, config_dir=cfg_path.parent)
    verdict = await council.run(artifact, tier=tier, artifact_type=artifact_type)
    return _verdict_to_dict(verdict)


if __name__ == "__main__":
    # FastMCP handles stdio transport by default
    mcp.run()
