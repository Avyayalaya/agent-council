"""CouncilLog — append-only JSONL writer for verdict records.

Schema follows Rule 35 v2 (span-traced session journal):
    {
      "v": 2,
      "span_id": "council-<uuid>",
      "parent_id": null,
      "sid": "council-cli",
      "ts": "2026-05-15T10:23:11Z",
      "agent": "council",
      "event": "verdict",
      "artifact_path": "...",
      "artifact_sha256": "...",
      ...verdict + deliberators...
    }

Writes are append-only — never edit or delete an existing line. The CouncilLog
also computes the SHA-256 of the reviewed artifact so identical inputs can be
correlated across runs.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CouncilLog:
    """Append-only JSONL log for council verdicts (Rule 35 v2 compatible)."""

    def __init__(
        self,
        log_path: str | Path,
        sid: str = "council-cli",
        redact_patterns: list[str] | None = None,
    ) -> None:
        """Configure where verdicts are appended.

        Args:
            log_path: Filesystem path (absolute or relative to cwd).
            sid: Session identifier injected into every record.
            redact_patterns: Regex patterns whose matches are scrubbed from
                ``reasoning`` and ``revision_brief`` before persistence.
        """
        self.log_path = Path(log_path)
        self.sid = sid
        self._redact = [re.compile(p) for p in (redact_patterns or [])]

    @staticmethod
    def hash_artifact(content: str) -> str:
        """SHA-256 of an artifact's bytes (UTF-8)."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def new_span_id() -> str:
        """Generate a fresh council span id."""
        return f"council-{uuid.uuid4().hex[:12]}"

    @staticmethod
    def now_iso() -> str:
        """Current UTC time, ISO-8601 with Z suffix."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _redact_text(self, text: str | None) -> str | None:
        if text is None:
            return None
        for pat in self._redact:
            text = pat.sub("[REDACTED]", text)
        return text

    def append(self, record: dict[str, Any]) -> None:
        """Persist one verdict record to disk.

        Missing standard fields (``v``, ``ts``, ``sid``, ``span_id``,
        ``agent``, ``event``, ``persisted``) are filled in with defaults.
        """
        full = {
            "v": 2,
            "span_id": record.get("span_id") or self.new_span_id(),
            "parent_id": record.get("parent_id"),
            "sid": record.get("sid") or self.sid,
            "ts": record.get("ts") or self.now_iso(),
            "agent": record.get("agent") or "council",
            "event": record.get("event") or "verdict",
            **record,
            "persisted": True,
        }
        # Apply redaction on the user-readable fields only.
        if "reasoning" in full:
            full["reasoning"] = self._redact_text(full["reasoning"])
        if "revision_brief" in full:
            full["revision_brief"] = self._redact_text(full["revision_brief"])

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(full, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # D6 — Prior-verdicts reader (compounding loop, design v0.2 §6)
    # ------------------------------------------------------------------
    def read_prior_verdicts(
        self,
        artifact_type: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Return the last ``limit`` verdict records for ``artifact_type``.

        Args:
            artifact_type: controlled-vocabulary label. Records without this
                field are skipped (backwards-compat — pre-D6 records had no
                artifact_type). Records with ``artifact_type == "unknown"``
                are returned only when ``artifact_type`` matches exactly.
            limit: max records to return; oldest is dropped beyond this.

        Returns:
            Up to ``limit`` compact dicts, newest-first, with keys:
            ``ts, span_id, verdict, deliberators_summary, revision_brief,
            artifact_sha256, reasoning``. Records whose JSON parse fails are
            silently skipped (don't crash the orchestrator).

        Performance: O(n) full-file scan. Fine for v1 (≤10K records on SSD
        is <1s). Flag for v2 if council_log.jsonl exceeds 50K records.
        """
        if not self.log_path.exists() or limit <= 0:
            return []

        matches: list[dict[str, Any]] = []
        try:
            with self.log_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("artifact_type") != artifact_type:
                        continue
                    if rec.get("event") and rec.get("event") != "verdict":
                        continue
                    delibs = rec.get("deliberators") or {}
                    if isinstance(delibs, dict):
                        summary = {
                            did: {
                                "r2_would_block": (d or {}).get("r2_would_block"),
                                "r2_irreducible": (d or {}).get("r2_irreducible"),
                                "r2_score": (d or {}).get("r2_score"),
                            }
                            for did, d in delibs.items()
                        }
                    else:
                        summary = {}
                    matches.append({
                        "ts": rec.get("ts"),
                        "span_id": rec.get("span_id"),
                        "verdict": rec.get("verdict"),
                        "deliberators_summary": summary,
                        "revision_brief": rec.get("revision_brief"),
                        "artifact_sha256": rec.get("artifact_sha256"),
                        "reasoning": rec.get("reasoning") or rec.get("adjudicator_reasoning"),
                    })
        except OSError:
            return []

        # Return last ``limit``, newest-first.
        if not matches:
            return []
        matches.reverse()
        return matches[:limit]
