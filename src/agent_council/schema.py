"""Per-role JSON output schemas + validator (design v0.2 §3.4, F2 from §9).

The Council protocol expects each deliberator and the Adjudicator to return a
JSON payload with a known shape. If a payload is malformed (missing keys, wrong
types, out-of-range scores), the orchestrator re-prompts once with stricter
format instructions; if the re-prompt still fails, the result is treated as
no_dissent for verdict purposes and the failure is flagged in the log.

This module exposes:

    SCHEMAS[role][round_num] -> dict spec
    validate(payload, role, round_num) -> (ok, errors)
    stricter_format_instruction(role, round_num, errors) -> str

The schema specs are plain dicts (no external library). Each spec declares
required keys with their expected types and allowed value ranges. Scores are
integers in [1..5]; ``would_block`` and ``irreducible`` are booleans; ``score``
may be present as int or float (we coerce). The Adjudicator schema is
deliberately permissive — verdict is a fixed enum and reasoning must be a
non-empty string, but ``revision_brief`` and ``dissent_summary`` are optional
because adjudicators legitimately omit them on SHIP verdicts.

The schemas are calibrated against the W1 mock_cli canned shapes (the gold
standard for what valid output looks like). They are intentionally loose where
real-Claude outputs are known to vary (e.g., ``top_3_issues`` vs
``top_3_failure_modes`` vs ``voice_violations`` are all accepted as the
top-issues list under different role conventions).
"""

from __future__ import annotations

from typing import Any

# Canonical role identifiers — must match council.yaml#deliberators[].id.
ROLE_SKEPTIC = "skeptic"
ROLE_VOICE = "voice_identity"
ROLE_EVIDENCE = "evidence"
ROLE_STRATEGY = "strategy"
ROLE_ADJUDICATOR = "adjudicator"

# Single re-prompt only — design §9 F2 + RW4-2 mitigation.
MAX_REPROMPTS = 1


# ---------------------------------------------------------------------------
# Schema specs
# ---------------------------------------------------------------------------
# Each spec is { "required": [keys...], "types": {key: type_name}, "ranges": {key: (lo, hi)}, "enums": {key: [allowed]} }
# ``types`` keys: "int", "str", "bool", "list", "dict", "number" (int|float).

_SCORE_SPEC = {"required": ["score"], "types": {"score": "number"}, "ranges": {"score": (1, 5)}}

_R1_COMMON = {
    "required": ["score", "would_block"],
    "types": {
        "score": "number",
        "would_block": "bool",
    },
    "ranges": {"score": (1, 5)},
    # ``irreducible`` is optional at R1 (some deliberators only set it at R2).
    "optional_types": {
        "irreducible": "bool",
    },
}

_R2_COMMON = {
    "required": ["score", "would_block", "irreducible"],
    "types": {
        "score": "number",
        "would_block": "bool",
        "irreducible": "bool",
    },
    "ranges": {"score": (1, 5)},
}

_ADJUDICATOR_R3 = {
    "required": ["verdict", "reasoning"],
    "types": {
        "verdict": "str",
        "reasoning": "str",
    },
    "enums": {"verdict": ["SHIP", "REVISE", "HOLD"]},
    # ``revision_brief`` is None when SHIP; ``dissent_summary`` is permissive.
    "optional_types": {
        "revision_brief": "str_or_null",
        "dissent_summary": "str",
    },
    "nonempty": ["reasoning"],
}


SCHEMAS: dict[str, dict[int, dict[str, Any]]] = {
    ROLE_SKEPTIC: {1: _R1_COMMON, 2: _R2_COMMON},
    ROLE_VOICE: {1: _R1_COMMON, 2: _R2_COMMON},
    ROLE_EVIDENCE: {1: _R1_COMMON, 2: _R2_COMMON},
    ROLE_STRATEGY: {1: _R1_COMMON, 2: _R2_COMMON},
    ROLE_ADJUDICATOR: {3: _ADJUDICATOR_R3},
}


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def validate(
    payload: Any,
    role: str,
    round_num: int,
) -> tuple[bool, list[str]]:
    """Validate ``payload`` against the schema for (role, round_num).

    Args:
        payload: the JSON-parsed deliberator response (dict expected).
        role: one of skeptic / voice_identity / evidence / strategy / adjudicator.
        round_num: 1 (R1 critique), 2 (R2 rebuttal), or 3 (adjudicator R3).

    Returns:
        (ok, errors). ``ok`` is True iff ``errors`` is empty.

    Unknown roles or rounds return ``(False, ["schema not defined ..."])`` rather
    than raising — the orchestrator can then treat the response as schema-failed.
    """
    errors: list[str] = []

    if payload is None:
        return False, ["payload is None (no JSON block extracted)"]
    if not isinstance(payload, dict):
        return False, [f"payload must be a JSON object, got {type(payload).__name__}"]

    spec = SCHEMAS.get(role, {}).get(round_num)
    if spec is None:
        return False, [f"no schema defined for role={role!r} round={round_num}"]

    # 1. Required keys present.
    for key in spec.get("required", []):
        if key not in payload:
            errors.append(f"missing required key: {key!r}")

    # 2. Type checks (required + optional).
    type_map = {**spec.get("types", {}), **spec.get("optional_types", {})}
    for key, expected in type_map.items():
        if key not in payload:
            continue  # optional key absent is fine
        val = payload[key]
        if not _type_ok(val, expected):
            errors.append(
                f"key {key!r} expected type {expected}, got {type(val).__name__}"
            )

    # 3. Range checks (for numeric keys).
    for key, (lo, hi) in spec.get("ranges", {}).items():
        if key not in payload:
            continue
        val = payload[key]
        try:
            num = float(val)
        except (TypeError, ValueError):
            continue  # type error already recorded above
        if num < lo or num > hi:
            errors.append(f"key {key!r}={val} out of allowed range [{lo}..{hi}]")

    # 4. Enum checks.
    for key, allowed in spec.get("enums", {}).items():
        if key not in payload:
            continue
        if payload[key] not in allowed:
            errors.append(
                f"key {key!r}={payload[key]!r} not in allowed values {allowed}"
            )

    # 5. Nonempty checks (for required strings).
    for key in spec.get("nonempty", []):
        if key in payload and isinstance(payload[key], str) and not payload[key].strip():
            errors.append(f"key {key!r} must be a non-empty string")

    return (not errors), errors


def stricter_format_instruction(
    role: str,
    round_num: int,
    errors: list[str],
) -> str:
    """Build the re-prompt suffix the orchestrator appends after a schema failure.

    Voice rules: states the schema directly, no "not X but Y" framing.
    """
    spec = SCHEMAS.get(role, {}).get(round_num) or {}
    required = spec.get("required", [])
    types = spec.get("types", {})
    ranges = spec.get("ranges", {})
    enums = spec.get("enums", {})

    shape_lines: list[str] = []
    for key in required:
        kind = types.get(key, "any")
        extra = ""
        if key in ranges:
            lo, hi = ranges[key]
            extra = f" (range [{lo}..{hi}])"
        elif key in enums:
            extra = f" (one of {enums[key]})"
        shape_lines.append(f"  - {key}: {kind}{extra}")

    # Append optional fields so the model knows they're recognized.
    opt = spec.get("optional_types") or {}
    if opt:
        shape_lines.append("  Optional fields:")
        for key, kind in opt.items():
            shape_lines.append(f"    - {key}: {kind}")

    err_block = "\n".join(f"  - {e}" for e in errors)
    shape_block = "\n".join(shape_lines)

    return (
        "\n\n---\n"
        "[SCHEMA_RETRY]\n"
        f"Your previous response did not match the required schema for role "
        f"{role!r} round {round_num}.\n"
        f"Errors:\n{err_block}\n\n"
        "Respond ONLY with a single fenced JSON block matching this exact shape "
        "(no prose, no preamble):\n"
        f"{shape_block}\n\n"
        "Do not include any additional commentary outside the JSON block.\n"
    )


# ---------------------------------------------------------------------------
# Type helpers
# ---------------------------------------------------------------------------

def _type_ok(value: Any, expected: str) -> bool:
    """Check ``value`` against a string type tag."""
    if expected == "int":
        # Strict int — but allow bool=False because Python bool is subclass of int;
        # exclude bool here so we don't accept ``True`` as a score of 1.
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "str":
        return isinstance(value, str)
    if expected == "bool":
        return isinstance(value, bool)
    if expected == "list":
        return isinstance(value, list)
    if expected == "dict":
        return isinstance(value, dict)
    if expected == "str_or_null":
        return value is None or isinstance(value, str)
    if expected == "any":
        return True
    return False


__all__ = [
    "SCHEMAS",
    "MAX_REPROMPTS",
    "validate",
    "stricter_format_instruction",
    "ROLE_SKEPTIC",
    "ROLE_VOICE",
    "ROLE_EVIDENCE",
    "ROLE_STRATEGY",
    "ROLE_ADJUDICATOR",
]
