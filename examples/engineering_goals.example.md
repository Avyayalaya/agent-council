# Engineering Goals Corpus — Architecture & Scope

This is the canonical goals doc for the **Architecture & Scope** deliberator
(council slot `strategy`). It plays the role the life-goals doc plays for
personal writing: the north-star, objectives, non-goals, and kill-criteria the
deliberator checks a design against.

The deliberator asks the question the design's own author cannot: *given
everything else this codebase is trying to stay, is this the right thing to
build, structured the right way, at the right cost?*

Target stack: Python / Flask / pytest, standard-library-first, small teams.

---

## North Star

Ship **correct, maintainable, secure** software with the **least complexity that
solves the real problem**. Every change should leave the codebase easier to
reason about, not harder. Boring, explicit, well-tested code beats clever code.

## Objectives (the `primary_goal` / `secondary_goal` enum)

Every design primarily serves one of these. Name it.

- **Correctness** — it does the right thing, including on the error and edge paths.
- **Maintainability** — the next engineer can read, change, and test it safely.
- **Simplicity** — it removes or contains complexity; fewer moving parts, fewer deps.
- **Security** — it protects data and trust boundaries (authz, input validation, injection, secrets).
- **Operability** — it can be observed, debugged, and recovered in production (logging, status codes, failure modes).
- **Velocity** — it unblocks delivery without mortgaging the above.

A design that can't articulate which objective it serves, or that trades a
durable objective (Correctness/Security/Maintainability) for a transient one
(Velocity), is a **would_block**.

## Architectural Principles

- **A1 — Separation of concerns.** Route → service → repository/data. Logic lives in services; views orchestrate; data access is isolated. A design that smears these layers is misaligned.
- **A2 — Standard-library-first / minimize dependencies.** A new third-party dependency must earn its place: significant, hard-to-replicate value. Adding a dep for something stdlib does is a kill-criterion.
- **A3 — Explicit over implicit.** No hidden global state, no magic. Behavior is traceable from the call site.
- **A4 — Small surface area.** Prefer the smallest public API / smallest schema change / smallest new abstraction that works. Narrow interfaces age well.
- **A5 — Testability is a design property.** If a design can't be tested without standing up the world, the design is wrong, not the test.
- **A6 — Boring, proven patterns.** Prefer the well-worn Flask/SQL/pytest pattern already in the repo over a novel one. Consistency with the existing codebase is itself a goal.
- **A7 — Reversibility.** Prefer changes that are easy to roll back or feature-flag over one-way doors.

## Non-Goals (do NOT reward these)

- **N1 — Premature abstraction.** Building a framework/plugin system/generic layer for one caller. YAGNI.
- **N2 — Speculative generality.** Config knobs, hooks, and extension points nobody asked for.
- **N3 — Architecture inflation.** Microservices, queues, caches, or new datastores for a small CRUD app.
- **N4 — Rewrites disguised as features.** Sweeping refactors bundled into a scoped change.
- **N5 — Novelty for its own sake.** A new pattern when an existing repo pattern would do.

## Kill-Criteria (fire `kill_check.triggered = true` when any hold)

- **K1** — Introduces a new external dependency whose value doesn't clearly exceed its maintenance + supply-chain cost (violates A2).
- **K2** — Duplicates a capability the codebase already has instead of extending it.
- **K3** — Cannot be covered by a test without disproportionate scaffolding (violates A5).
- **K4** — Its complexity cost (new concepts, new layers, new state) exceeds the value delivered — it does not "earn its complexity."
- **K5** — Creates a one-way door (irreversible migration, public API you must support forever) for a reversible problem.
- **K6** — Widens a trust boundary or touches authz/secret handling without a security rationale (defer the blocking call to the Skeptic/Evidence deliberators, but flag it).

An artifact that trips a kill-criterion that **cannot be edited away — only
re-scoped or shelved** is `irreducible: true`.

## Opportunity-Cost Lens

Complexity is the budget. For each design ask: what does the codebase *pay*
(new abstraction, new dep, more surface to test and maintain), and is there a
**simpler alternative** that buys most of the value for a fraction of the cost?
Name the concrete cheaper option when one exists ("a single service function +
one status code, instead of a new blueprint + manager class"). "There's a
simpler way" with no named alternative is not a finding.

## Scoring anchor (1–5)

- **1** — Wrong thing to build, or right thing built wrong: trips a kill-criterion, or a non-goal masquerading as the design.
- **2** — Serves a real objective but over-built / mis-layered; a materially simpler alternative exists.
- **3** — Sound scope and layering; one architectural trade-off worth surfacing, none blocking.
- **4** — Well-scoped, well-layered, earns its complexity; minor notes.
- **5** — Minimal, correctly-layered, reversible, testable; clearly the right build.
