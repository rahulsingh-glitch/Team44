# START HERE — Team 44 (read this first, it's short)

This repo makes Claude Code do the heavy lifting. You tell the agents what to build with
simple slash commands; they write the code, the tests, and bring up Docker. Here is the
whole thing in plain language.

## The idea in one picture

```
You  ──paste a command──▶  an Agent  ──writes code / runs Docker──▶  a Tester agent checks it
                                                                   └─▶ you review & merge
```

- **Agents** = pre-written job descriptions in `.claude/agents/`. Claude Code reads them.
- **Commands** = one-line shortcuts in `.claude/commands/`. You type `/name` to run them.
- **CLAUDE.md** = the rules all agents follow. It loads automatically. Don't delete it.

## This week (before 27 Nov) — do this once

1. Download and unzip the repo. Open the folder in VS Code.
2. On every laptop, run the environment check from the prerequisites, then `make test`.
   You should see tests pass. Any failure = tell the lead now, not on the day.
3. Open Claude Code in the repo folder. Ask it "what are the rules here?" — it should
   answer from CLAUDE.md. That means it's working.
4. Do ONE full practice run as a team on the sample use case (see "How to run it" below).
   The goal is that each person has done their part once before the real day.

## On the day (27 Nov) — the order

1. **Lead (Rahul):** open `MASTER-PROMPT.md`, paste the card into that prompt in Claude Code.
   It plans the whole build and assigns the pieces.
2. **DevOps (Nabi):** in his own Claude Code session, type `/setup-stack`. This brings up
   Docker (Postgres, Airflow, Superset) and proves it starts from a fresh clone.
3. **Builders (Jitesh, Adarsh, Chetan):** each in their own session, build their layers:
   `/build-layer <thing>` → `/test-feature <thing>` → `/grill` → lead merges.
4. **Everyone:** after real work, type `/logprompt` (this is 15 scored points — don't skip).
5. **3:30 SRE drill:** when the fault hits, use `/rca` with the trimmed logs.
6. **Before the demo:** run `/verify-e2e` to prove the whole thing runs end to end.

## How to run it (the four commands you'll use most)

```
make up      # start everything (Docker stack, or the DuckDB script fallback)
make seed    # generate the synthetic data
make run     # run the pipeline for one day
make test    # run all the tests
```

## The commands you can type in Claude Code

| Command | What it does |
|---|---|
| `/setup-stack` | Brings up Docker end to end, proves fresh-clone start |
| `/build-layer <x>` | Builds one layer (e.g. `/build-layer silver`), plan-first |
| `/test-feature <x>` | A tester agent writes + runs tests for that layer |
| `/grill` | Strict review of your branch before merge |
| `/logprompt` | Logs what you just did (scored Claude evidence) |
| `/rca` | Helps with the SRE drill root-cause + write-up |
| `/verify-e2e` | Runs the whole pipeline and checks it end to end |
| `/ship` | Commit + push + open PR + update the status sheet, enforcing the rules |
| `/gates` | Pass/fail disqualifying-gate check before submitting |
| `/syncboard` | Reads the status tracker, tells you your next task |

## Where things live

- `MASTER-PROMPT.md` — the lead's kickoff prompt.
- `.claude/agents/` — the agent job descriptions (setup, pipeline-builder, tester, reviewer).
- `.claude/commands/` — the slash commands above.
- `docs/agents/` — the detailed per-person plan (read your own: 01 Rahul … 05 Chetan).
- `WORKFLOW.md` — the build→test→review→ship→sheet loop, git rules, role↔agent map.
- `SUBMISSION.md` — the gates + ten artifacts + demo checklist (run near the end).
- `docs/status.csv` — the status board the tracker/`/ship` keep updated.
- `docs/` — LLD, runbook, test plan, ideation, Claude log, clock. Fill the `<<...>>` on the day.

## Three rules that win points

1. **Plan first, then let the agent code.** (Use Plan Mode: Shift+Tab.)
2. **Every feature gets a test** — that's why builder and tester are separate agents.
3. **Log your prompts and corrections** with `/logprompt` — it's worth 15 points.

## One caution
On the day, the safest move against the "no pre-built code" rule is to let the agents
build fresh in your real repo using these files as the guide — or clear reuse with a mentor.
The value is the plan and the agents, not pre-written solution code.
