# Agent 1 — Tech Lead  ·  Rahul Singh

**Owns:** architecture, the key decisions, the clock, merges/reviews, unblocking,
the Ideation doc and the Presentation. You are also the **integrator** — you keep the
end-to-end slice alive and run the checkpoints in `00-orchestration.md §0.4`.
**Scored areas you anchor:** Business alignment (10), Engineering quality (15), overall Functional (20).

> You spend less time generating code and more time deciding, reviewing and merging.
> Read `00-orchestration.md` first.

## Dependencies & handoffs
- **Blocks everyone** until the contract (§0.2) and decisions are frozen — do this first.
- You **receive** branches from A2/A3/A4/A5 and merge them after a review.

## Phase 1 — Kick-off & architecture (0:00–1:00)

**Tasks**
1. Read the card twice. Restate the problem in your own words to the team.
2. Freeze the two+ key decisions (engine, idempotency, SCD2) with reasons.
3. Fill the `<<...>>` markers in `CLAUDE.md`, `docs/lld.md` §1–§3, `docs/ideation.md`.
4. Confirm/adjust the shared contract in `00-orchestration.md §0.2`; announce it.
5. Assign each agent its brief; set checkpoints on the clock.

**Session prompts (paste one at a time, approve the plan each time)**
- `Read docs card <<paste the revealed card>>. List the gaps, ambiguities and risks in it as a numbered list. Do not propose solutions yet — I will decide each answer with the team.`
- `Here is our decision: engine = <<X>>, idempotency = <<Y>>, SCD = <<Z>>. For each, write 3 sentences: the option chosen, the main alternative, and why we chose it. Put it in docs/lld.md section 3 and docs/ideation.md section 3.`
- `Draft a context diagram (ascii) of the medallion flow for this card and a component list with one-line responsibilities. Put it in docs/lld.md section 2.`

**Definition of done:** contract frozen; two decisions recorded with reasons; CLAUDE.md
and LLD §1–3 and ideation filled; everyone has their brief.

## Phase 2–3 — Integrate & review (1:00–3:30)

**Tasks**
1. Keep a runnable end-to-end slice alive from hour 1 (fake rows are fine at first).
2. Review every PR: run it, read it, confirm it has a test. Merge or send back.
3. Run the §0.4 checkpoints at T+2:00 and T+3:00. Rebalance people to the critical path.
4. Guard scope: if a must-have is red, freeze all stretch work (scope-creep pitfall).

**Session prompts**
- `Review this diff for our standards (snake_case, idempotency, a test exists, no dead code). List concrete issues only. Diff: <<paste>>.`
- `Our end-to-end slice must stay runnable. Given these merged components <<list>>, write the thinnest make run that chains them for one day, even where a step is a stub.`

**Definition of done (3:00):** `make run` works end to end on real synthetic data; CI green; gold+marts populated.

## Phase 4 — SRE drill support (3:30–4:15)
You pick which hypothesis the team tests and you approve the runbook before the drill ends.
Let A4 (DevOps/SRE) drive; you make the call and keep time.

## Phase 5 — Presentation & demo (4:15–4:45)

**Tasks:** finish the presentation (business alignment, IT security, performance testing);
make sure the 5-beat demo traces back to the problem statement.

**Session prompt**
- `Draft a 10-slide presentation outline covering: problem & user value, architecture + key decision, how data quality is enforced, security (synthetic data, no secrets, PII handling), performance testing result, and the SRE drill RCA. Tie each back to the problem statement.`

## Your pitfalls
- Becoming a sixth coder instead of the integrator — your job is decisions, reviews, the clock.
- Letting the slice break during integration — protect the working demo above all.
