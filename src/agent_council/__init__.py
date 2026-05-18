"""agent_council — a runtime-portable 5-agent adjudicator council for universal quality gating.

The Agent Council reviews any text artifact through five role-conditioned deliberators
(Skeptic, Voice & Identity, Evidence & Calibration, Strategy & Stakes, and an Adjudicator
who synthesizes the verdict). It uses a 2-round async protocol with cross-read rebuttal,
and returns a verdict of SHIP, REVISE, or HOLD plus a full debate transcript.

Public API:
    Council        — high-level orchestrator entry point
    Verdict        — structured verdict dataclass returned by Council.run()
    VerdictPolicy  — SHIP/REVISE/HOLD decision logic per council.yaml
    CouncilLog     — append-only JSONL log writer (Rule 35 v2 schema)
    TierClassifier — artifact-path → tier classification
    RuntimeAdapter — abstract base class for runtime adapters
"""

from agent_council.log import CouncilLog
from agent_council.orchestrator import Council
from agent_council.runtimes.base import RuntimeAdapter
from agent_council.tier import TierClassifier
from agent_council.verdict import Verdict, VerdictPolicy

__version__ = "0.1.0"

__all__ = [
    "Council",
    "Verdict",
    "VerdictPolicy",
    "CouncilLog",
    "TierClassifier",
    "RuntimeAdapter",
    "__version__",
]
