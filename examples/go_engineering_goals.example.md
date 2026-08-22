# Engineering Goals Corpus — Go Architecture & Package Design

This is the canonical goals doc for the **Go Architecture & Package Design**
deliberator (council slot `strategy`, running the Go preset). It is the Go
counterpart of `engineering_goals.example.md`: the north-star, objectives,
non-goals, and kill-criteria the deliberator checks a design against.

The deliberator asks the question the design's own author cannot: *given
everything else this Go codebase is trying to stay, is this the right thing to
build, packaged and layered the Go way, at the right cost?*

Target stack: Go 1.21+, standard-library-first, small teams, `gofmt`/`vet`/`-race`
clean.

---

## North Star

Ship **correct, maintainable, concurrent-safe** Go with the **least complexity
that solves the real problem**. Prefer clear over clever; a little copying is
cheaper than the wrong abstraction. Every change should leave the packages easier
to reason about and the concurrency easier to prove safe.

## Objectives (the `primary_goal` / `secondary_goal` enum)

Every design primarily serves one of these. Name it.

- **Correctness** — right behavior including error and cancellation paths; no data races.
- **Maintainability** — the next engineer can read the packages and change them safely.
- **Simplicity** — fewer moving parts, fewer deps; the smallest interface that works.
- **Security** — protects data and trust boundaries (input validation, `crypto/rand`, secrets).
- **Operability** — observable and recoverable (context deadlines, structured logging, clean shutdown).
- **Velocity** — unblocks delivery without mortgaging the above.

A design that can't name which objective it serves, or that trades a durable
objective (Correctness/Security/Maintainability) for Velocity, is a
**would_block**.

## Architectural Principles

- **A1 — Package boundaries by responsibility, not by layer-name.** Packages are
  cohesive and named for what they provide (`store`, `billing`), not `utils`/`common`/
  `models`. No import cycles. Dependencies point inward toward stable core types.
- **A2 — Standard-library-first / minimize dependencies.** A new module must earn
  its place with significant, hard-to-replicate value. Adding a dep for what
  `net/http`, `encoding/json`, `context`, or `slices` already do is a kill-criterion.
- **A3 — Accept interfaces, return structs; define interfaces at the consumer.**
  Abstractions are introduced where they are used, kept small, and grown only when a
  second implementation actually exists.
- **A4 — Small surface area.** Export the minimum. The smallest public API / smallest
  interface / smallest struct that works. Unexported by default; promote to exported
  only on demand. A one-way exported API is expensive forever.
- **A5 — Concurrency is a design property, not an add-on.** Every goroutine's
  lifetime and ownership is explicit; cancellation flows through `context`; shared
  state is owned by one goroutine or guarded by a lock. If a design can't state how
  its goroutines stop, the design is wrong.
- **A6 — Boring, proven patterns.** Prefer the well-worn Go idiom already in the
  repo (table tests, `context` plumbing, worker pools) over a novel framework.
  Consistency with the existing packages is itself a goal.
- **A7 — Reversibility.** Prefer changes that are easy to roll back or feature-flag;
  an exported API or an on-disk/wire format is a commitment you must support.

## Non-Goals (do NOT reward these)

- **N1 — Premature abstraction.** An interface, generic, or plugin registry for a
  single implementation. Add the interface when the second caller arrives.
- **N2 — Speculative generality.** Config knobs, functional-option explosions, and
  extension points nobody asked for.
- **N3 — Architecture inflation.** Microservices, queues, caches, or a new datastore
  for a small service; channels where a plain function call would do.
- **N4 — Rewrites disguised as features.** Sweeping package reshuffles bundled into
  a scoped change.
- **N5 — Novelty for its own sake.** A new pattern (reflection, `interface{}`
  soup, a DI framework) where an existing repo idiom would do.

## Kill-Criteria (fire `kill_check.triggered = true` when any hold)

- **K1** — Adds an external dependency whose value doesn't clearly exceed its
  maintenance + supply-chain cost (violates A2).
- **K2** — Duplicates a capability the codebase or stdlib already provides.
- **K3** — Cannot be tested without disproportionate scaffolding, or is inherently
  racy/nondeterministic (violates A5).
- **K4** — Its complexity cost (new packages, new concurrency, new state) exceeds the
  value delivered — it does not "earn its complexity."
- **K5** — Creates a one-way door: an irreversible migration, or an exported
  API / wire format you must support forever, for a reversible problem.
- **K6** — Introduces a goroutine/channel design with no stated shutdown or ownership,
  or widens a trust boundary (authz, secrets, input) without a security rationale.

An artifact that trips a kill-criterion that **cannot be edited away — only
re-scoped or shelved** is `irreducible: true`.

## Opportunity-Cost Lens

Complexity is the budget. For each design ask: what does the codebase *pay* (a new
package, a new dep, more concurrency to reason about, more exported surface), and is
there a **simpler alternative** that buys most of the value for a fraction of the
cost? Name the concrete cheaper option ("a single `context`-aware function, not a
worker-pool + result-channel", "a struct field, not a functional-option builder").
"There's a simpler way" with no named alternative is not a finding.

## Scoring anchor (1–5)

- **1** — Wrong thing to build, or right thing built wrong: trips a kill-criterion,
  or a non-goal masquerading as the design (goroutine soup, premature interface).
- **2** — Serves a real objective but over-built / mis-packaged; a materially simpler
  alternative exists.
- **3** — Sound scope, packaging, and concurrency ownership; one trade-off worth
  surfacing, none blocking.
- **4** — Well-scoped, well-packaged, earns its complexity; minor notes.
- **5** — Minimal, correctly-packaged, concurrency-safe, reversible, testable;
  clearly the right build.
