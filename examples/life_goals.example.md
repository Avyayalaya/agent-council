# life_goals.example.md — template for the Strategy & Stakes deliberator

> **This is a template, not a working goals doc.** The Strategy & Stakes
> deliberator reads this file to learn the operator's north-star, active
> objectives, and kill-criteria. To produce real verdicts, replace this with
> your own goals doc.
>
> Section names matter (the prompt references them). Content within each
> section is yours.

---

## North-Star

A single sentence describing what the operator is optimizing for at the
life-or-career level. Example structure:

> "Become a [role / outcome] within [timeframe], measured by [evidence type]."

## Active Objectives (3–6)

The objectives currently in flight. Each gets:

- **Title** — short name.
- **Why it matters** — connection to north-star.
- **Success criteria** — what "done" looks like.
- **Current status** — sentence on where this stands.

Example:

### Objective 1 — Build authority in [domain]

- **Why** — direct path to north-star outcome X.
- **Success** — Y published artifacts + Z inbound conversations within 12 months.
- **Status** — 3 of Y published; inbound rate currently 1 / quarter.

*(continue with your own objectives)*

## Active Projects

Current concrete work streams executing toward the objectives. Two-line entries:

- **PROJ-001** — short description. Targeting objective 1. Status: in flight.
- **PROJ-002** — short description. Targeting objective 3. Status: blocked on X.

The deliberator uses these to assess whether an artifact's stakes are
proportional to the project it advances.

## Kill-Criteria

Conditions under which the operator would stop pursuing each objective. Example:

- **Objective 1 kill** — if 18 months of effort produces zero qualified inbound,
  the thesis is wrong and the work is cancelled.
- **Project X kill** — if [signal Y] fails to materialize by [date Z], stop.

The deliberator uses kill-criteria to flag artifacts that drift toward dead
objectives or contradict explicit stops.

## Non-Goals

Things the operator deliberately is NOT pursuing. Example:

- Generalist consulting (would dilute the specialist signal).
- Speaking circuits in unrelated domains.
- Content optimized for clicks rather than the right audience.

The deliberator uses non-goals to flag artifacts that wander into excluded
territory.

---

*Replace this template with your own goals doc before running real Council
verdicts. The prompt at `prompts/strategy.md` reads this file as the source of
truth for goal-fit / stake-calibration assessment.*
