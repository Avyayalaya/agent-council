"""Modularity invariant test — asserts no emitting-agent prompt references Council.

This is the CI test that protects the system's headline architectural promise:
**emitting agents (Writer, Synthesizer, Builder, Patent Analyst, Industry Analyst,
Investment Analyst) have ZERO hard dependency on the Council.** They produce
artifacts the same way regardless of whether Council exists.

The test runs from day 1 (P0 Condition #3 per the Build Handoff Spec). Two
sub-tests:

  1. **grep test** — scan ../../agents/*/prompt.md for any mention of
     "council", "agent_council", "council_review", or "from agent_council".
     Zero matches allowed.

  2. **import test** — walk src/agent_council/ and assert no imports from
     anywhere outside ``agent_council``, stdlib, or declared deps.
     Catches accidental coupling in the other direction.

Run with:
    python -m unittest tests.test_modularity_invariant
or:
    pytest tests/test_modularity_invariant.py
"""

from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
# Agent Prime root is two levels above projects/SYS-024_agent_council/.
AGENT_PRIME_ROOT = PROJECT_ROOT.parent.parent
AGENTS_DIR = AGENT_PRIME_ROOT / "agents"

# Council references — case-insensitive, word-boundaries to avoid false positives
# on "councilman" style false matches.
COUNCIL_REGEX = re.compile(
    r"\bagent[-_]council\b|\bcouncil[-_]review\b|\bfrom\s+agent_council\b|"
    r"\bimport\s+agent_council\b",
    re.IGNORECASE,
)

# Agents that are INTENTIONALLY allowed to reference Council. Per the design
# (docs/superpowers/specs/2026-05-11-agent-council-design.md §2.2):
#
#   "The ONLY agent prompt that mentions Council is Emissary's (it's the
#    chokepoint, not an artifact producer)."
#
# Emissary is the boundary between Agent Prime and the world (Rule 41). Its
# Layer 3 action queue routes every Tier-2 external action through Council
# before execution. Because Emissary does not produce artifacts — it only
# routes them — it remains "modular" in the sense that matters: emitting
# agents (Writer, Synthesizer, Builder, Patent Analyst, Industry/Investment
# Analyst) have zero Council references and can be lifted to any other
# context. The Emissary exemption is intentional and documented; if a NEW
# agent is added to this set, it must be justified in the design spec.
EXEMPTED_AGENTS = {"emissary"}


class ModularityInvariantTest(unittest.TestCase):
    """The Council must be invisible to emitting agents."""

    def test_no_emitting_agent_prompt_references_council(self) -> None:
        """Grep across a host operator system's agents/*/prompt.md — must return zero matches.

        Skipped when run outside a host system (no agents/ dir found, or the dir
        exists but contains no prompt.md files — e.g., the public-extract repo or
        a clean clone with no host system wired in).
        """
        if not AGENTS_DIR.exists():
            self.skipTest(
                f"Host operator system agents directory not found at {AGENTS_DIR}; "
                "test is informational only when run outside a host system."
            )

        all_prompts = list(AGENTS_DIR.glob("*/prompt.md"))
        if not all_prompts:
            self.skipTest(
                f"No prompt.md files found under {AGENTS_DIR}; "
                "test is informational only when run outside a host system."
            )

        # Emitting-only: skip Council-exempt agents (Emissary is the chokepoint,
        # not an artifact producer — see EXEMPTED_AGENTS comment above).
        prompts = [p for p in all_prompts if p.parent.name not in EXEMPTED_AGENTS]
        skipped = sorted(p.parent.name for p in all_prompts if p.parent.name in EXEMPTED_AGENTS)

        violations: list[tuple[str, int, str]] = []
        for p in prompts:
            text = p.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if COUNCIL_REGEX.search(line):
                    violations.append((str(p.relative_to(AGENT_PRIME_ROOT)), lineno, line.strip()[:140]))

        # Useful trace when the invariant is investigated — shows which agents
        # were scanned and which were exempted.
        if skipped:
            print(f"\n[modularity invariant] scanned {len(prompts)} prompts; exempted: {skipped}")

        if violations:
            msg = "Emitting-agent prompts reference Council. Violations:\n" + "\n".join(
                f"  {path}:{lineno}  {line}" for path, lineno, line in violations
            )
            self.fail(msg)

    def test_council_package_has_no_agent_prime_imports(self) -> None:
        """Walk src/agent_council/ — no imports outside stdlib + declared deps."""
        package_root = PROJECT_ROOT / "src" / "agent_council"
        self.assertTrue(package_root.exists(), f"Package not found at {package_root}")

        # Permitted import roots. stdlib is checked separately via sys.builtin/std module names.
        allowed_first_segments = {
            "agent_council",
            # stdlib (sampled — full check below uses sys.stdlib_module_names).
        }

        violations: list[tuple[str, str]] = []
        for py_file in package_root.rglob("*.py"):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError as e:
                self.fail(f"Could not parse {py_file}: {e}")

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        head = alias.name.split(".")[0]
                        if not _is_allowed(head, allowed_first_segments):
                            violations.append(
                                (str(py_file.relative_to(PROJECT_ROOT)), f"import {alias.name}")
                            )
                elif isinstance(node, ast.ImportFrom):
                    if node.level > 0:
                        continue  # relative imports inside the package are fine.
                    module = node.module or ""
                    head = module.split(".")[0]
                    if head and not _is_allowed(head, allowed_first_segments):
                        violations.append(
                            (str(py_file.relative_to(PROJECT_ROOT)), f"from {module} import ...")
                        )

        if violations:
            msg = "agent_council package imports from outside stdlib + declared deps:\n" + "\n".join(
                f"  {path}: {imp}" for path, imp in violations
            )
            self.fail(msg)

    def test_bench_has_no_external_imports(self) -> None:
        """W2 extension: walk src/agent_council/bench/ — same invariant as P0.

        The bench sub-package must not import anything outside
        ``agent_council`` + stdlib + declared deps (``yaml`` is whitelisted
        since it is the only declared optional dep). This is the
        invariant extension required by W2 Condition 4 + B25.
        """
        bench_root = PROJECT_ROOT / "src" / "agent_council" / "bench"
        self.assertTrue(bench_root.exists(), f"Bench dir not found at {bench_root}")

        allowed_first_segments = {"agent_council"}
        violations: list[tuple[str, str]] = []
        for py_file in bench_root.rglob("*.py"):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError as e:
                self.fail(f"Could not parse {py_file}: {e}")

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        head = alias.name.split(".")[0]
                        if not _is_allowed(head, allowed_first_segments):
                            violations.append(
                                (str(py_file.relative_to(PROJECT_ROOT)), f"import {alias.name}")
                            )
                elif isinstance(node, ast.ImportFrom):
                    if node.level > 0:
                        continue
                    module = node.module or ""
                    head = module.split(".")[0]
                    if head and not _is_allowed(head, allowed_first_segments):
                        violations.append(
                            (str(py_file.relative_to(PROJECT_ROOT)), f"from {module} import ...")
                        )

        if violations:
            msg = (
                "agent_council.bench imports from outside stdlib + declared deps:\n"
                + "\n".join(f"  {path}: {imp}" for path, imp in violations)
            )
            self.fail(msg)


def _is_allowed(module_head: str, package_roots: set[str]) -> bool:
    """True if ``module_head`` is the package, stdlib, or an explicit dependency."""
    if module_head in package_roots:
        return True
    # stdlib detection — use the module-names list shipped with 3.10+.
    stdlib = getattr(sys, "stdlib_module_names", None)
    if stdlib is not None and module_head in stdlib:
        return True
    # Declared optional deps (pyyaml) — yaml may be imported but only inside try.
    if module_head in {"yaml", "pytest"}:
        return True
    return False


if __name__ == "__main__":
    unittest.main(verbosity=2)
