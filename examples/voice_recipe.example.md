# voice_recipe.example.md — template for the Voice & Identity deliberator

> **This is a template, not a working corpus.** The Voice & Identity deliberator
> reads this file to learn the operator's voice DNA. To produce real verdicts,
> replace this with your own voice corpus — derived from your published
> writing, edited drafts, and explicit voice rules.
>
> The structure below shows what the deliberator expects. Section names matter
> (the prompt references them); content within each section is yours.

---

## 1. Voice DNA (5–10 sentences)

Describe your voice in operator's-eye-view sentences. Examples of the dimensions
to cover:

- Sentence length distribution (e.g., "Short blunt sentences with the occasional
  load-bearing longer one").
- Posture (e.g., "Self-implicating, never preachy").
- Stance toward authority (e.g., "Treats CEOs as peers, not as the prize").
- Domain register (e.g., "Speaks in product/strategy idiom; avoids consultant
  vocabulary").

## 2. Banned patterns (numbered, with examples)

List the specific phrases, syntactic patterns, or tonal moves the deliberator
should flag. Number them so the deliberator can cite the violation precisely.

- **V1** — Ban "not X but Y" constructions. Say the positive thing directly.
- **V2** — No false-discovery framing ("Here's what I learned…", "I came to realize…").
- **V3** — No hype words ("recontextualize", "visceral", "question reality").
- **V4** — No "I'm excited to share…" LinkedIn cliches.
- *(continue with your own rules)*

For each rule, provide one concrete violation example and the preferred rewrite.

## 3. Channel-specific register

Voice rules can vary by channel. Define the register for each surface you ship to:

- **Substack** — long-form, structural argument, full thesis with evidence layers.
- **LinkedIn (post)** — short, punchy, one structural insight + one product implication.
- **LinkedIn (article)** — middle ground; structural argument but tighter than Substack.
- **Conference talk** — spoken cadence; shorter sentences; rhetorical anchors.
- **Operator memo / brief** — direct, decision-first, headline-then-detail.
- *(add your channels)*

## 4. Anti-patterns to avoid

Patterns that aren't single phrases but tonal modes — easier to describe than enumerate.

- "Junior PM in clever-mode" — over-reaching for novelty, under-supporting claims.
- "AI-coach LinkedIn influencer" — empty exhortation, no substance.
- "Philosophy professor" — long subordinate clauses, abstract framing without grounding.
- *(add your own)*

## 5. Quality bar

A short statement of the bar the deliberator should enforce. Example:

> "Would a CXO of a growth-stage company own this on stage? If yes, ship. If no,
> revise. If it sounds like a junior PM cosplaying as a strategist, hold."

---

*Replace this template with your own voice corpus before running real Council
verdicts. The prompt at `prompts/voice_identity.md` reads this file as
the source of truth for V-rule enforcement.*
