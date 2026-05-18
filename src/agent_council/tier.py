"""TierClassifier — map an artifact path to a council-review tier.

Tier 1: External-facing OR irreversible OR identity-shaping OR memory write
        — Council fires every time.
Tier 2: Internal drafts, dashboards, infra, dispatch updates, registry edits
        — Council skips.
Tier 3: Daily briefings, internal analyses, Scout signals, dashboards
        — Council samples 1-in-5.

The classifier is rules-driven from council.yaml. Unclassified paths default
to ``default_tier`` (2 in v0.1) to prevent silent quality regressions on new
artifact types.
"""

from __future__ import annotations

import fnmatch
import hashlib
from pathlib import Path


class TierClassifier:
    """Rules-based tier classification.

    Rules format (parsed from council.yaml#tier_rules):
        tier_1:
          - "*_substack_*.md"
          - "*_linkedin_*.md"
          - "shared/learnings.md"
        tier_3:
          - "prime/briefing.md"
    """

    def __init__(
        self,
        rules: dict | None = None,
        default_tier: int = 2,
        sample_rate_tier_3: int = 5,
    ) -> None:
        """Configure the classifier.

        Args:
            rules: Mapping like ``{"tier_1": [glob, ...], "tier_3": [...]}``.
            default_tier: Tier used when no rule matches.
            sample_rate_tier_3: Tier-3 artifacts fire on ``1-in-N`` runs;
                sampling is deterministic on a path hash (so re-runs are stable).
        """
        self.rules = rules or {}
        self.default_tier = default_tier
        self.sample_rate_tier_3 = max(1, sample_rate_tier_3)

    def classify(self, artifact_path: str | Path) -> tuple[int, str]:
        """Return (tier, artifact_type) for ``artifact_path``.

        ``artifact_type`` is a controlled-vocabulary label drawn from the
        first matching rule key (e.g. ``"linkedin_post"`` if the glob was
        listed under ``tier_1.linkedin_post: [...]``). If rules are a flat
        list, ``artifact_type`` falls back to the file extension stem.
        """
        path = Path(artifact_path)
        name = path.name

        # Match tier_1 rules first.
        artifact_type = self._match("tier_1", path, name)
        if artifact_type:
            return 1, artifact_type

        artifact_type = self._match("tier_3", path, name)
        if artifact_type:
            return 3, artifact_type

        return self.default_tier, path.suffix.lstrip(".") or "unknown"

    def should_fire(self, artifact_path: str | Path) -> bool:
        """Return True if the Council should review this artifact.

        Tier 1 always fires. Tier 2 never fires. Tier 3 fires when a stable
        hash of the artifact path lands in the 1-in-N sampling slot.
        """
        tier, _ = self.classify(artifact_path)
        if tier == 1:
            return True
        if tier == 2:
            return False
        # Tier 3 — deterministic sample.
        digest = hashlib.sha256(str(artifact_path).encode("utf-8")).digest()
        return (digest[0] % self.sample_rate_tier_3) == 0

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _match(self, tier_key: str, path: Path, name: str) -> str | None:
        bucket = self.rules.get(tier_key)
        if not bucket:
            return None
        # Two shapes supported: flat list of globs, or dict {artifact_type: [globs]}.
        if isinstance(bucket, list):
            for pat in bucket:
                if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(str(path), pat):
                    return Path(pat).stem.lstrip("*").lstrip("_") or "unknown"
            return None
        if isinstance(bucket, dict):
            for artifact_type, patterns in bucket.items():
                for pat in patterns or []:
                    if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(str(path), pat):
                        return artifact_type
        return None
