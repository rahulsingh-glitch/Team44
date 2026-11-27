# The Master Prompt (Tech Lead pastes this first, on the day)

Open Claude Code in the repo root (so CLAUDE.md loads). Paste the block below, with the
revealed card pasted in where shown. This sets up the whole build; the agents do the work.

---

```
You are the master/orchestrator for Team 44 at AI Manthan, Track B (data platform).
Read CLAUDE.md and docs/agents/00-orchestration.md before doing anything.

Here is the revealed use-case card:
<<PASTE THE FULL CARD HERE>>

Do these in order, stopping for my approval at each step:

1. Read the card twice and restate the problem in your own words. Then list the gaps,
   ambiguities and risks as a numbered list. I will decide each answer with the team.

2. Propose: the transform engine (dbt+DuckDB default, or Postgres/Spark if the card
   demands it), the idempotency strategy, and which dimensions are SCD2 — each with a
   one-line reason. Wait for my decision, then write them into docs/lld.md §3 and
   docs/ideation.md, and update the shared contract in docs/agents/00-orchestration.md §2.

3. Fill the <<...>> markers in CLAUDE.md, docs/lld.md §1-4, and docs/ideation.md from the card.

4. Give me a build plan mapped to our five people and the 5-hour clock, using the agent
   briefs in docs/agents/. For each component name the owner, the dependency, and the test
   that will prove it.

Then I will have each teammate run their own Claude Code session and their own agents:
- Nabi runs `/setup-stack` to bring up Docker end to end and prove a fresh-clone start.
- Builders run `/build-layer <layer>`, then `/test-feature <layer>`, then `/grill` before merge.
- Everyone runs `/logprompt` after meaningful work.
- At 3:30 we run the SRE drill with `/rca`. Before the demo we run `/verify-e2e`.

Rules: plan first every time; idempotent transforms; a test per must-have; synthetic data
only; no secrets; keep a working end-to-end slice alive from hour one.
```

---

## What each teammate pastes in their own session

| Person | First command | Then |
|---|---|---|
| Nabi (DevOps) | `/setup-stack` | `/verify-e2e` once builders are done |
| Jitesh (Bronze/Silver) | `/build-layer synthetic data` then `/build-layer bronze` then `/build-layer silver` | `/test-feature <each>`, `/grill`, `/logprompt` |
| Adarsh (Gold/Marts) | `/build-layer gold` then `/build-layer marts` | `/test-feature <each>`, `/grill`, `/logprompt` |
| Chetan (DQ/Dashboard) | `/build-layer data quality` then `/build-layer dashboard` | `/test-feature dq`, `/logprompt` |
| Rahul (Lead) | the master prompt above | review branches, `/grill`, run the clock |
