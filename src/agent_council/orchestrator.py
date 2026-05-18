"""Council orchestrator — 2-round async protocol with cross-read and synthesis.

Flow (per design §4):

    Round 0 — load artifact + config + per-deliberator context refs
    Round 1 — fan out N deliberator calls in parallel (asyncio.gather)
    Round 2 — fan out N deliberator rebuttals (each sees all R1 critiques)
    Round 3 — single Adjudicator synthesis call → SHIP / REVISE / HOLD verdict

The orchestrator depends only on the ``RuntimeAdapter`` interface and the
config dict. It never imports anything from a host operator system. The artifact and any
context refs are loaded as raw text and passed to the runtime opaquely.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from agent_council.log import CouncilLog
from agent_council.runtimes import build_adapter
from agent_council.runtimes.base import RuntimeAdapter
from agent_council.schema import (
    MAX_REPROMPTS,
    ROLE_ADJUDICATOR,
    stricter_format_instruction,
    validate as schema_validate,
)
from agent_council.tier import TierClassifier
from agent_council.verdict import (
    DeliberatorResult,
    Verdict,
    VerdictPolicy,
)

ROUND_2_MARKER = "[ROUND_2_REBUTTAL]"

# Cap prior-verdict reasoning per record to keep adjudicator context bounded
# (design v0.2 §6 / failure mode F6.5).
_PRIOR_REASONING_MAX_CHARS = 500
# How many prior verdicts to inject into the adjudicator context.
_PRIOR_VERDICT_LIMIT = 5


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class Council:
    """High-level entry point: load config, run protocol, return Verdict."""

    def __init__(
        self,
        config: dict[str, Any],
        config_dir: Path | None = None,
    ) -> None:
        """Initialize Council from a parsed ``council.yaml`` dict.

        Args:
            config: parsed council.yaml as nested dicts/lists/scalars.
            config_dir: directory where prompt paths resolve from. Defaults
                to current working directory.
        """
        self.config = config
        self.config_dir = config_dir or Path.cwd()
        self.adapter: RuntimeAdapter = build_adapter(config.get("runtime") or {})
        self.policy = VerdictPolicy((config.get("adjudicator") or {}).get("verdict_policy"))
        log_cfg = config.get("logging") or {}
        log_path = log_cfg.get("log_path") or "./council_log.jsonl"
        self.log = CouncilLog(
            self._resolve(log_path),
            redact_patterns=log_cfg.get("redact_patterns") or [],
        )
        self._archive_dir = self._resolve(
            log_cfg.get("archive_dir") or "./council_archive"
        )

    # ------------------------------------------------------------------
    # Top-level orchestration
    # ------------------------------------------------------------------
    async def run(
        self,
        artifact_path: str | Path,
        tier: int = 1,
        artifact_type: str | None = None,
    ) -> Verdict:
        """Execute the 2-round protocol on an artifact.

        Args:
            artifact_path: path to the file under review.
            tier: tier classification (passed through to the log).
            artifact_type: controlled-vocabulary label (e.g. ``"linkedin_post"``).
                If None, derived from the configured TierClassifier — this is
                what wires the prior-verdicts compounding loop (D6).

        Returns:
            Verdict with full deliberator records and Adjudicator synthesis.
        """
        artifact_path = Path(artifact_path)
        if not artifact_path.exists():
            raise FileNotFoundError(f"Artifact not found: {artifact_path}")

        artifact_text = artifact_path.read_text(encoding="utf-8", errors="replace")
        artifact_sha = CouncilLog.hash_artifact(artifact_text)
        span_id = CouncilLog.new_span_id()

        # Derive artifact_type from tier rules if the caller didn't supply one.
        # This is the field D6 keys on for prior-verdicts lookup (§6 compounding loop).
        if artifact_type is None:
            classifier = TierClassifier(rules=self.config.get("tier_rules") or {})
            _, artifact_type = classifier.classify(artifact_path)

        delibs_cfg = list(self.config.get("deliberators") or [])
        adj_cfg = self.config.get("adjudicator") or {}
        proto = self.config.get("protocol") or {}
        min_delibs = int(proto.get("min_deliberators_for_verdict", 3))
        cross_read = bool(proto.get("cross_read", True))
        rounds = int(proto.get("rounds", 2))

        # Load all prompts upfront.
        deliberator_prompts: dict[str, str] = {}
        deliberator_contexts: dict[str, list[str]] = {}
        for d in delibs_cfg:
            did = d["id"]
            ppath = self._resolve(d["prompt"])
            deliberator_prompts[did] = ppath.read_text(encoding="utf-8", errors="replace")
            deliberator_contexts[did] = self._load_context_refs(d.get("context_refs") or [])

        adjudicator_prompt = self._resolve(adj_cfg["prompt"]).read_text(
            encoding="utf-8", errors="replace"
        )

        # Pull prior verdicts on the same artifact_type for the adjudicator
        # context (D6 — design v0.2 §6 compounding loop). Deliberators do NOT
        # see this; only the Adjudicator does.
        prior_verdicts = self.log.read_prior_verdicts(
            artifact_type=artifact_type or "unknown",
            limit=_PRIOR_VERDICT_LIMIT,
        )

        start = time.time()

        # ---- Round 1: independent critique ----
        r1_results = await self._fan_out(
            delibs_cfg, deliberator_prompts, deliberator_contexts, artifact_text, r2_inputs=None
        )

        if rounds >= 2:
            # ---- Round 2: cross-read rebuttal ----
            r2_results = await self._fan_out(
                delibs_cfg,
                deliberator_prompts,
                deliberator_contexts,
                artifact_text,
                r2_inputs=r1_results,
                cross_read=cross_read,
            )
        else:
            r2_results = {}

        # ---- Round 3: adjudicator synthesis ----
        adj_raw, adj_payload, adj_schema_meta = await self._invoke_adjudicator(
            adjudicator_prompt,
            artifact_text,
            r1_results,
            r2_results,
            prior_verdicts=prior_verdicts,
        )

        # Assemble DeliberatorResult records.
        # D5: schema_failed deliberators are treated as no_dissent per design F2.
        # They keep their record (with the schema_failed flag in the log) but
        # contribute zero blocks/irreducible to the verdict policy.
        results: dict[str, DeliberatorResult] = {}
        for d in delibs_cfg:
            did = d["id"]
            r1 = r1_results.get(did)
            r2 = r2_results.get(did) if rounds >= 2 else None
            r1_schema_failed = bool(r1.get("schema_failed")) if r1 else True
            r2_schema_failed = bool(r2.get("schema_failed")) if r2 else False

            dr = DeliberatorResult(
                role=did,
                raw_r1=r1.get("payload") if r1 and r1.get("payload") is not None else None,
                error=r1.get("error") if r1 else "no R1 result",
            )
            if r1 and r1.get("payload") and not r1_schema_failed:
                payload = r1["payload"]
                dr.r1_score = _coerce_int(payload.get("score"))
                dr.r1_would_block = bool(payload.get("would_block"))
                top_issues = (
                    payload.get("top_3_issues")
                    or payload.get("top_3_failure_modes")
                    or payload.get("voice_violations")
                    or payload.get("calibration_issues")
                    or []
                )
                if isinstance(top_issues, list):
                    dr.top_issues = [str(x) for x in top_issues[:5]]
            if r2 and r2.get("payload") and not r2_schema_failed:
                payload = r2["payload"]
                dr.raw_r2 = payload
                dr.r2_score = _coerce_int(payload.get("score"))
                dr.r2_would_block = bool(payload.get("would_block"))
                dr.r2_irreducible = bool(payload.get("irreducible"))
            # If schema failed, raw_r1 is the parsed (but invalid) payload — leave
            # it so the archive captures what was attempted, but the verdict
            # policy sees no_dissent because r1_would_block defaults to False.
            results[did] = dr

        # Compute verdict via policy. Adjudicator's own verdict is used for
        # reasoning/revision_brief, but the policy guards against runaway
        # SHIPs when deliberators would have blocked.
        policy_verdict, policy_reason = self.policy.apply(results, min_deliberators=min_delibs)
        adj_schema_failed = adj_schema_meta.get("schema_failed", False)
        adj_verdict = (adj_payload or {}).get("verdict") if adj_payload else None

        # Merge policy + adjudicator verdicts via the extracted helper so the
        # logic is unit-testable without running the full Council.run() flow.
        final_verdict = merge_verdicts(
            policy_verdict=policy_verdict,
            adj_verdict=adj_verdict,
            adj_schema_failed=adj_schema_failed,
            results=results,
        )

        reasoning = (adj_payload or {}).get("reasoning") or policy_reason
        if adj_schema_failed:
            reasoning = (
                "Adjudicator output failed schema validation after one re-prompt. "
                "Verdict cannot be rendered. See council_log.jsonl for errors."
            )
        revision_brief = (adj_payload or {}).get("revision_brief")
        dissent_summary = (adj_payload or {}).get("dissent_summary") or ""

        verdict = Verdict(
            verdict=final_verdict,
            reasoning=reasoning,
            revision_brief=revision_brief if final_verdict in ("REVISE", "HOLD") else None,
            dissent_summary=dissent_summary,
            deliberators=results,
            adjudicator_raw=adj_payload,
            span_id=span_id,
        )

        # Persist log + archive.
        elapsed = time.time() - start
        self._persist(
            verdict=verdict,
            artifact_path=str(artifact_path),
            artifact_sha=artifact_sha,
            tier=tier,
            artifact_type=artifact_type or "unknown",
            elapsed=elapsed,
            r1_results=r1_results,
            r2_results=r2_results,
            adjudicator_raw=adj_raw,
            adjudicator_schema=adj_schema_meta,
            prior_verdicts_used=len(prior_verdicts),
        )
        return verdict

    # ------------------------------------------------------------------
    # Round mechanics
    # ------------------------------------------------------------------
    async def _fan_out(
        self,
        delibs_cfg: list[dict[str, Any]],
        prompts: dict[str, str],
        contexts: dict[str, list[str]],
        artifact_text: str,
        r2_inputs: dict[str, dict[str, Any]] | None,
        cross_read: bool = True,
    ) -> dict[str, dict[str, Any]]:
        """Fire one round of deliberator calls in parallel with schema enforcement.

        D5: each deliberator response is validated against its role+round
        schema. On schema failure, a single re-prompt is fired with a stricter
        format instruction. If the second attempt also fails, the result is
        flagged schema_failed=True and treated as no_dissent for verdict
        purposes (design v0.2 §9 F2).

        Args:
            delibs_cfg: list of deliberator config dicts.
            prompts: id -> prompt text.
            contexts: id -> list of context blobs (preloaded).
            artifact_text: the artifact under review.
            r2_inputs: if not None, this is Round 2; each call sees the other
                deliberators' R1 critiques.
            cross_read: if False, R2 only sees the deliberator's own R1.

        Returns:
            Mapping id -> {
              "payload": parsed_json_or_None,
              "raw": raw_str,
              "error": str_or_None,
              "schema_failed": bool,
              "schema_errors": [str, ...],
              "reprompts": int,
              "raw_retry": str_or_None,
            }
        """
        round_num = 2 if r2_inputs is not None else 1
        tasks: list[asyncio.Task] = []
        ids: list[str] = []
        for d in delibs_cfg:
            did = d["id"]
            ids.append(did)
            prompt_text = prompts[did]
            ctx = [artifact_text, *contexts[did]]
            if r2_inputs is not None:
                # R2: inject the cross-read pack + marker.
                cross_pack = _format_cross_read(r2_inputs, focus_id=did, cross_read=cross_read)
                ctx = [artifact_text, cross_pack, *contexts[did]]
                prompt_text = f"{prompt_text}\n\n{ROUND_2_MARKER}\n\n_See the other deliberators' Round 1 critiques in context. Produce a Round 2 rebuttal: updated score, concessions, escalations, final would_block, final irreducible. Respond ONLY with JSON inside a fenced code block._"
            tasks.append(
                asyncio.create_task(
                    self._invoke_with_schema(
                        self.adapter, prompt_text, ctx, role=did, round_num=round_num
                    )
                )
            )

        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        results: dict[str, dict[str, Any]] = {}
        for did, outcome in zip(ids, gathered):
            if isinstance(outcome, Exception):
                results[did] = {
                    "payload": None,
                    "raw": "",
                    "error": f"{type(outcome).__name__}: {outcome}",
                    "schema_failed": True,
                    "schema_errors": [f"adapter raised: {type(outcome).__name__}"],
                    "reprompts": 0,
                    "raw_retry": None,
                }
            else:
                results[did] = outcome
        return results

    @staticmethod
    async def _invoke_with_schema(
        adapter: RuntimeAdapter,
        prompt_text: str,
        context: list[str],
        role: str,
        round_num: int,
    ) -> dict[str, Any]:
        """Invoke one deliberator with schema validation + single re-prompt.

        Returns the result dict expected by ``_fan_out``. See D5 in the
        Build Handoff Spec.
        """
        raw = await adapter.invoke(prompt_text, context)
        payload = _extract_json_block(raw)
        ok, errors = schema_validate(payload, role, round_num)
        if ok:
            return {
                "payload": payload,
                "raw": raw,
                "error": None,
                "schema_failed": False,
                "schema_errors": [],
                "reprompts": 0,
                "raw_retry": None,
            }

        # Schema failure — log to stderr (operator-visible) and re-prompt once.
        print(
            f"[schema] {role}/R{round_num} failed validation; re-prompting once. "
            f"errors={errors}",
            file=sys.stderr,
        )
        retry_prompt = prompt_text + stricter_format_instruction(role, round_num, errors)
        raw_retry: str | None = None
        try:
            raw_retry = await adapter.invoke(retry_prompt, context)
            payload_retry = _extract_json_block(raw_retry)
            ok2, errors2 = schema_validate(payload_retry, role, round_num)
        except Exception as e:  # F5.2 — re-prompt adapter exception
            errors2 = [f"retry raised: {type(e).__name__}: {e}"]
            ok2 = False
            payload_retry = None

        if ok2:
            return {
                "payload": payload_retry,
                "raw": raw,
                "error": None,
                "schema_failed": False,
                "schema_errors": errors,
                "reprompts": 1,
                "raw_retry": raw_retry,
            }

        # Still invalid after one retry — flag schema_failed for verdict policy.
        print(
            f"[schema] {role}/R{round_num} failed AGAIN after re-prompt; "
            f"treating as no_dissent. errors={errors2}",
            file=sys.stderr,
        )
        return {
            "payload": payload_retry if payload_retry is not None else payload,
            "raw": raw,
            "error": None,
            "schema_failed": True,
            "schema_errors": errors + errors2,
            "reprompts": MAX_REPROMPTS,
            "raw_retry": raw_retry,
        }

    async def _invoke_adjudicator(
        self,
        prompt_text: str,
        artifact_text: str,
        r1: dict[str, dict[str, Any]],
        r2: dict[str, dict[str, Any]],
        prior_verdicts: list[dict[str, Any]] | None = None,
    ) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
        """Run the Adjudicator synthesis call with schema enforcement.

        D6: prepends a prior-verdicts context block (if any) so the Adjudicator
        can weight settled patterns from prior gates on the same artifact_type.

        Returns:
            (raw_response, parsed_payload, schema_meta) where schema_meta
            includes ``schema_failed``, ``schema_errors``, ``reprompts``,
            ``raw_retry``, and ``prior_verdicts_count``.
        """
        pack_parts: list[str] = []
        if prior_verdicts:
            pack_parts.append(_format_prior_verdicts(prior_verdicts))
        pack_parts.append(_format_adjudicator_pack(r1, r2))
        pack = "\n\n".join(pack_parts)
        ctx = [artifact_text, pack]

        raw = await self.adapter.invoke(prompt_text, ctx)
        payload = _extract_json_block(raw)
        ok, errors = schema_validate(payload, ROLE_ADJUDICATOR, 3)
        if ok:
            return raw, payload, {
                "schema_failed": False,
                "schema_errors": [],
                "reprompts": 0,
                "raw_retry": None,
                "prior_verdicts_count": len(prior_verdicts or []),
            }

        # F5.5 — Adjudicator schema is permissive (only verdict + reasoning
        # required). If it still fails, re-prompt once.
        print(
            f"[schema] adjudicator/R3 failed validation; re-prompting once. "
            f"errors={errors}",
            file=sys.stderr,
        )
        retry_prompt = prompt_text + stricter_format_instruction(
            ROLE_ADJUDICATOR, 3, errors
        )
        raw_retry: str | None = None
        try:
            raw_retry = await self.adapter.invoke(retry_prompt, ctx)
            payload_retry = _extract_json_block(raw_retry)
            ok2, errors2 = schema_validate(payload_retry, ROLE_ADJUDICATOR, 3)
        except Exception as e:
            errors2 = [f"retry raised: {type(e).__name__}: {e}"]
            ok2 = False
            payload_retry = None

        if ok2:
            return raw, payload_retry, {
                "schema_failed": False,
                "schema_errors": errors,
                "reprompts": 1,
                "raw_retry": raw_retry,
                "prior_verdicts_count": len(prior_verdicts or []),
            }

        print(
            f"[schema] adjudicator/R3 failed AGAIN after re-prompt; "
            f"verdict will be INCOMPLETE. errors={errors2}",
            file=sys.stderr,
        )
        return raw, payload_retry if payload_retry is not None else payload, {
            "schema_failed": True,
            "schema_errors": errors + errors2,
            "reprompts": MAX_REPROMPTS,
            "raw_retry": raw_retry,
            "prior_verdicts_count": len(prior_verdicts or []),
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _persist(
        self,
        verdict: Verdict,
        artifact_path: str,
        artifact_sha: str,
        tier: int,
        artifact_type: str,
        elapsed: float,
        r1_results: dict[str, dict[str, Any]],
        r2_results: dict[str, dict[str, Any]],
        adjudicator_raw: str,
        adjudicator_schema: dict[str, Any],
        prior_verdicts_used: int,
    ) -> None:
        """Write the verdict line to JSONL + dump full transcripts to archive."""
        # Decorate the per-deliberator records with schema metadata (D5).
        deliberators_dict = verdict.to_dict()["deliberators"]
        for did, dr_dict in deliberators_dict.items():
            r1 = r1_results.get(did) or {}
            r2 = r2_results.get(did) or {}
            dr_dict["schema_failed"] = bool(r1.get("schema_failed") or r2.get("schema_failed"))
            dr_dict["reprompts"] = int(r1.get("reprompts", 0)) + int(r2.get("reprompts", 0))
            errs = list(r1.get("schema_errors") or []) + list(r2.get("schema_errors") or [])
            if errs:
                dr_dict["schema_errors"] = errs

        record = {
            "span_id": verdict.span_id,
            "agent": "council",
            "event": "verdict",
            "artifact_path": artifact_path,
            "artifact_sha256": artifact_sha,
            "tier": tier,
            "artifact_type": artifact_type,
            "verdict": verdict.verdict,
            "deliberators": deliberators_dict,
            "adjudicator_reasoning": verdict.reasoning,
            "revision_brief": verdict.revision_brief,
            "adjudicator_schema_failed": bool(adjudicator_schema.get("schema_failed")),
            "adjudicator_reprompts": int(adjudicator_schema.get("reprompts", 0)),
            "prior_verdicts_used": int(prior_verdicts_used),
            "runtime": self.adapter.adapter_name(),
            "model": getattr(self.adapter, "default_model", "") or "",
            "elapsed_seconds": round(elapsed, 3),
            "reasoning": verdict.reasoning,
        }
        if adjudicator_schema.get("schema_errors"):
            record["adjudicator_schema_errors"] = adjudicator_schema["schema_errors"]
        self.log.append(record)

        # Archive full transcripts for audit.
        try:
            arch_dir = Path(self._archive_dir) / verdict.span_id
            arch_dir.mkdir(parents=True, exist_ok=True)
            (arch_dir / "artifact.md").write_text(
                Path(artifact_path).read_text(encoding="utf-8", errors="replace"),
                encoding="utf-8",
            )
            for did, r in r1_results.items():
                raw = r.get("raw") or ""
                if r.get("raw_retry"):
                    raw = raw + "\n\n=== SCHEMA_RETRY ===\n\n" + (r.get("raw_retry") or "")
                (arch_dir / f"r1_{did}.md").write_text(raw, encoding="utf-8")
            for did, r in r2_results.items():
                raw = r.get("raw") or ""
                if r.get("raw_retry"):
                    raw = raw + "\n\n=== SCHEMA_RETRY ===\n\n" + (r.get("raw_retry") or "")
                (arch_dir / f"r2_{did}.md").write_text(raw, encoding="utf-8")
            adj_text = adjudicator_raw or ""
            if adjudicator_schema.get("raw_retry"):
                adj_text = adj_text + "\n\n=== SCHEMA_RETRY ===\n\n" + (
                    adjudicator_schema.get("raw_retry") or ""
                )
            (arch_dir / "adjudicator_synthesis.md").write_text(adj_text, encoding="utf-8")
        except OSError as e:
            # Archive failure should not fail the verdict; surface to stderr.
            print(f"warning: archive write failed: {e}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _resolve(self, p: str | Path) -> Path:
        """Resolve a path relative to ``self.config_dir`` and expand ``~``.

        Used for prompt files, log paths, archive dirs — files that live
        inside the council package or adjacent to the config. For arbitrary
        context_refs that may live anywhere on disk (voice corpus, life
        goals, persona DNA), use ``_resolve_context_ref`` instead — it
        tries host operator system root + env-var override + package-data fallback.
        """
        candidate = Path(p).expanduser()
        if not candidate.is_absolute():
            candidate = (self.config_dir / candidate).resolve()
        return candidate

    def _resolve_context_ref(self, ref: str) -> tuple[Path, str]:
        """Resolve a context_ref path with cross-platform fallbacks.

        Resolution order (returns the FIRST existing match):
            1. Absolute path (after ``~`` expansion).
            2. Path relative to current working directory.
            3. Path relative to ``$AGENT_PRIME_ROOT`` env var (if set).
               The env var name is back-compat with the original host system
               (Agent Prime). Set it to any directory you want context_refs
               resolved against.
            4. Path relative to a heuristic host-system root — walks up from
               ``self.config_dir`` looking for a parent that contains both
               ``shared/`` and ``projects/`` directories, or a ``CLAUDE.md``
               file. Useful when context_refs are relative paths into a
               larger operator workspace.
            5. Path relative to the council package's ``data/`` dir
               (for shipping fixtures with the public release).
            6. Path relative to ``self.config_dir`` (legacy behavior, kept
               so existing relative refs still work).

        Returns:
            (resolved_path, resolution_source) where resolution_source is a
            short label for the transparent logging path (``absolute``,
            ``cwd``, ``env``, ``agent_prime_root``, ``package_data``,
            ``config_dir``, or ``missing``).
        """
        raw = Path(ref).expanduser()

        # 1. Absolute (post ``~`` expansion) — straight check.
        if raw.is_absolute():
            return raw, "absolute" if raw.exists() else "missing"

        # 2. CWD-relative.
        cwd_candidate = (Path.cwd() / raw).resolve()
        if cwd_candidate.exists():
            return cwd_candidate, "cwd"

        # 3. AGENT_PRIME_ROOT env override (name retained for back-compat with
        # the original host system; treat as a generic "host root" override).
        env_root = os.environ.get("AGENT_PRIME_ROOT")
        if env_root:
            env_candidate = (Path(env_root).expanduser() / raw).resolve()
            if env_candidate.exists():
                return env_candidate, "env"

        # 4. Heuristic host-system root.
        ap_root = _find_agent_prime_root(self.config_dir)
        if ap_root is not None:
            ap_candidate = (ap_root / raw).resolve()
            if ap_candidate.exists():
                return ap_candidate, "agent_prime_root"

        # 5. Package data dir (./data/ adjacent to agent_council package).
        pkg_data = Path(__file__).resolve().parent / "data"
        pkg_candidate = (pkg_data / raw).resolve()
        if pkg_candidate.exists():
            return pkg_candidate, "package_data"

        # 6. config_dir fallback (preserves legacy behavior).
        cfg_candidate = (self.config_dir / raw).resolve()
        if cfg_candidate.exists():
            return cfg_candidate, "config_dir"

        # Nothing matched — return the env/agent-prime-root candidate (best
        # diagnostic shape) and mark missing.
        diag = None
        if env_root:
            diag = (Path(env_root).expanduser() / raw).resolve()
        elif ap_root is not None:
            diag = (ap_root / raw).resolve()
        else:
            diag = cfg_candidate
        return diag, "missing"

    def _load_context_refs(self, refs: list[str]) -> list[str]:
        """Read each context file; missing files become a clearly marked stub.

        We do NOT fail-fast on missing context refs in v0.1 — the orchestrator
        surfaces missing files inline so the deliberator can still produce a
        critique with reduced context. The Context Verification Gate inside
        each prompt then catches degraded loads at the model layer.

        Resolution uses ``_resolve_context_ref`` so context refs declared in
        council.yaml as relative paths (or absolute paths that fail to resolve
        on a different machine — e.g., OneDrive vs non-OneDrive home dirs on
        Windows) get fixed up against the host-system root or the
        ``AGENT_PRIME_ROOT`` env override. The resolution source is echoed
        to stderr for transparency.
        """
        out: list[str] = []
        for r in refs:
            path, source = self._resolve_context_ref(r)
            if source == "missing" or not path.exists():
                print(
                    f"[context_ref] MISSING: {r!r} (last-tried: {path})",
                    file=sys.stderr,
                )
                out.append(f"[CONTEXT_REF_MISSING: {r}]\n")
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                print(
                    f"[context_ref] resolved {r!r} via {source} -> {path}",
                    file=sys.stderr,
                )
                out.append(f"# === Context: {r} ===\n\n" + text)
            except OSError as e:
                print(
                    f"[context_ref] READ_ERROR: {r!r} ({path}): {e}",
                    file=sys.stderr,
                )
                out.append(f"[CONTEXT_REF_READ_ERROR: {r}: {e}]\n")
        return out


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_BARE_JSON_RE = re.compile(r"(\{[\s\S]*\})", re.DOTALL)


def merge_verdicts(
    policy_verdict: str,
    adj_verdict: str | None,
    adj_schema_failed: bool,
    results: dict[str, DeliberatorResult],
) -> str:
    """Merge the policy-computed and Adjudicator-claimed verdicts into a final.

    Extracted from ``Council.run()`` so the merge logic can be unit-tested
    directly without running a full Council deliberation. The rules:

    1. **Adjudicator schema failure** — return INCOMPLETE (the synthesis
       cannot be trusted; downstream consumers see exit code 3).
    2. **Adjudicator verdict missing or invalid** — fall back to policy.
    3. **Adjudicator verdict valid + policy verdict not INCOMPLETE** —
       default to the STRICTER of the two (Adjudicator can escalate; it
       cannot bypass blockers to SHIP).
    4. **Constrained HOLD → REVISE downgrade** — if policy says HOLD and
       Adjudicator says REVISE AND zero deliberators flagged ``irreducible``,
       trust the Adjudicator. The 3+ block-count rule is a coarse heuristic
       for structural rework; the actual structural signal is
       ``r2_irreducible:true``. When no deliberator marks irreducible, the
       Adjudicator's contextual judgment (line-level editorial vs. rework)
       wins.

    Args:
        policy_verdict: output of ``VerdictPolicy.apply()`` — one of
            SHIP, REVISE, HOLD, INCOMPLETE.
        adj_verdict: the Adjudicator's claimed verdict from its R3 synthesis;
            may be None or invalid if synthesis failed.
        adj_schema_failed: True if the Adjudicator's output failed schema
            validation even after one re-prompt.
        results: mapping of role-id to DeliberatorResult — used to check
            ``r2_irreducible`` flags for the HOLD → REVISE downgrade.

    Returns:
        Final verdict string: SHIP | REVISE | HOLD | INCOMPLETE.
    """
    if adj_schema_failed:
        return "INCOMPLETE"
    if adj_verdict not in ("SHIP", "REVISE", "HOLD") or policy_verdict == "INCOMPLETE":
        return policy_verdict

    order = {"SHIP": 0, "REVISE": 1, "HOLD": 2, "INCOMPLETE": 3}
    final = max(adj_verdict, policy_verdict, key=lambda v: order[v])

    # Constrained downgrade: policy HOLD + Adjudicator REVISE + no irreducible.
    if policy_verdict == "HOLD" and adj_verdict == "REVISE":
        any_irreducible = any(r.r2_irreducible for r in results.values() if r.succeeded)
        if not any_irreducible:
            final = "REVISE"
    return final


# Cache for the host-system root walk (idempotent per process).
_AGENT_PRIME_ROOT_CACHE: dict[str, Path | None] = {}


def _find_agent_prime_root(start: Path) -> Path | None:
    """Walk up from ``start`` looking for the host operator system root.

    The function name is retained for back-compat with the original host
    system (Agent Prime); semantically it locates any operator-workspace
    root that contains the expected sentinel files.

    Heuristic: a directory containing BOTH ``shared/`` and ``projects/`` and
    either ``CLAUDE.md`` or ``prime/`` is treated as the host-system root.
    This handles the OneDrive vs non-OneDrive home-directory split on Windows
    without hard-coding any operator-specific path.

    Falls back to ``None`` if no such ancestor is found — callers should
    treat that as "use cwd / package_data / config_dir instead."
    """
    start = Path(start).resolve()
    key = str(start)
    if key in _AGENT_PRIME_ROOT_CACHE:
        return _AGENT_PRIME_ROOT_CACHE[key]

    current = start if start.is_dir() else start.parent
    # Walk up at most 10 levels — anything deeper is a misuse.
    for _ in range(10):
        has_shared = (current / "shared").is_dir()
        has_projects = (current / "projects").is_dir()
        has_marker = (current / "CLAUDE.md").is_file() or (current / "prime").is_dir()
        if has_shared and has_projects and has_marker:
            _AGENT_PRIME_ROOT_CACHE[key] = current
            return current
        if current.parent == current:
            break
        current = current.parent

    _AGENT_PRIME_ROOT_CACHE[key] = None
    return None


def _extract_json_block(text: str) -> dict[str, Any] | None:
    """Pull the first JSON object out of a raw model response.

    Strategy:
        1. Try a fenced ```json block (the canonical shape).
        2. Try the first ``{...}`` substring as a fallback.
        3. Return None if neither parses.
    """
    if not text:
        return None
    # Try fenced block first.
    m = _JSON_FENCE_RE.search(text)
    candidates: list[str] = []
    if m:
        candidates.append(m.group(1))
    # Fallback: first balanced {...}
    bare = _BARE_JSON_RE.search(text)
    if bare:
        candidates.append(bare.group(1))
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            continue
    return None


def _format_cross_read(
    r1_results: dict[str, dict[str, Any]],
    focus_id: str,
    cross_read: bool,
) -> str:
    """Render the cross-read context bundle a deliberator sees in R2."""
    lines = ["# === Round 1 critique pack ===\n"]
    for did, r in r1_results.items():
        if not cross_read and did != focus_id:
            continue
        lines.append(f"\n## Deliberator: {did}\n")
        if r.get("error"):
            lines.append(f"_(R1 errored: {r['error']})_\n")
            continue
        if r.get("payload"):
            lines.append("```json\n" + json.dumps(r["payload"], indent=2, ensure_ascii=False) + "\n```\n")
        else:
            lines.append(r.get("raw", "") + "\n")
    lines.append("\n# === End Round 1 critique pack ===\n")
    return "".join(lines)


def _format_prior_verdicts(prior: list[dict[str, Any]]) -> str:
    """Render the prior-verdicts context blob the Adjudicator sees (D6 / §6).

    Each prior verdict is summarized — verdict + ts + truncated reasoning +
    revision_brief tail. Full reasoning lives in the archive; the blob caps
    each reasoning at ``_PRIOR_REASONING_MAX_CHARS`` to bound context size.
    """
    lines = [
        "# === Prior verdicts on this artifact_type ===\n",
        "_(For Adjudicator weighting only. The Council learns from itself: "
        "settled patterns earn weight; flips against prior consensus deserve "
        "explicit reasoning.)_\n",
    ]
    for i, rec in enumerate(prior, start=1):
        ts = rec.get("ts") or "?"
        verdict = rec.get("verdict") or "?"
        sha = (rec.get("artifact_sha256") or "")[:10]
        reasoning = (rec.get("reasoning") or "")[:_PRIOR_REASONING_MAX_CHARS]
        rb = rec.get("revision_brief")
        rb_excerpt = ""
        if isinstance(rb, str) and rb.strip():
            rb_excerpt = "\n  revision_brief (excerpt): " + rb[:_PRIOR_REASONING_MAX_CHARS]
        lines.append(
            f"\n## Prior {i}/{len(prior)} — {verdict} @ {ts} (sha {sha})\n"
            f"  reasoning: {reasoning}{rb_excerpt}\n"
        )
    lines.append("\n# === End prior verdicts ===\n")
    return "".join(lines)


def _format_adjudicator_pack(
    r1: dict[str, dict[str, Any]],
    r2: dict[str, dict[str, Any]],
) -> str:
    """Render the full R1+R2 transcript the Adjudicator synthesizes from."""
    parts = ["# === Round 1 critiques ===\n"]
    for did, r in r1.items():
        parts.append(f"\n## R1: {did}\n")
        if r.get("payload"):
            parts.append("```json\n" + json.dumps(r["payload"], indent=2, ensure_ascii=False) + "\n```\n")
        else:
            parts.append(r.get("raw", "") + "\n")
    parts.append("\n# === Round 2 rebuttals ===\n")
    for did, r in r2.items():
        parts.append(f"\n## R2: {did}\n")
        if r.get("payload"):
            parts.append("```json\n" + json.dumps(r["payload"], indent=2, ensure_ascii=False) + "\n```\n")
        else:
            parts.append(r.get("raw", "") + "\n")
    parts.append(
        "\n# === Verdict policy ===\n"
        "- SHIP   = 0 deliberators would_block after R2\n"
        "- REVISE = 1-2 would_block AND no irreducible\n"
        "- HOLD   = 3+ would_block OR any irreducible\n\n"
        "Respond ONLY with JSON in a fenced code block, with fields: "
        "verdict, reasoning, revision_brief (null if SHIP), dissent_summary.\n"
    )
    return "".join(parts)


def _coerce_int(value: Any) -> int | None:
    """Best-effort int coercion (handles '3', 3, 3.0, None)."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
