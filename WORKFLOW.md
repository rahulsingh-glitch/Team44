# WORKFLOW — how the agents and the team actually work together

This is the canonical loop. It covers your six-point vision: a role↔agent map, the
multi-agent session model, documenting every prompt, the build→test handoff, and a tracker
that keeps the status sheet updated. Two points are adapted for safety — see §6.

## 1. The core loop (your diagram, made concrete)

```
MASTER (Tech Lead) assigns a task
      │
      ▼
BUILDER agent ── plan-first ─▶ writes code ─▶ /logprompt (documents the prompt in repo)
      │  hands off
      ▼
TESTER agent ── writes test cases for that feature ─▶ make test ─▶ pass/fail
      │  pass
      ▼
REVIEWER agent ── /grill ─▶ APPROVE
      │
      ▼
/ship ── commit (correct prefix) + push + open PR + TRACKER updates the status sheet
      │
      ▼
MASTER merges to main
```

Nothing is "done" until: a test proves it, the review passes, it's pushed, and the sheet row says `done`.

## 2. Role ↔ agent mapping (point 1: every agent has a scope)

| Person | Human role | Agents they drive | Owns (scored) |
|---|---|---|---|
| Rahul | Master / Tech Lead | (orchestrator prompt), `reviewer` | Business alignment, Engineering, Functional |
| Jitesh | Bronze + Silver | `pipeline-builder`, `tester` | Functional, Data quality |
| Adarsh | Gold + Marts | `pipeline-builder`, `tester` | Functional, Engineering |
| Nabi | DevOps + SRE | `setup`, `pipeline-builder`(DAG), `tester` | SRE, Deployment/CI, Performance |
| Chetan | DQ + Dashboard + Evidence | `pipeline-builder`, `tester`, `tracker` | Claude usage, Dashboard, DQ, Demo |

Agent definitions live in `.claude/agents/`. Detailed per-person briefs live in `docs/agents/`.

## 3. Session model (point 2: single vs multi session)

**Use multi-session + subagents. Do NOT run everyone in one session, and do NOT build a mod.**
- **Multi-session:** each person runs their own Claude Code session = separate context.
  One giant shared session causes the "context bloat" pitfall the deck warns about.
- **Subagents within a session:** `builder → tester → reviewer` are subagents, so the
  handoff happens with clean context, no copy-paste.
- **Why not mods:** a mod is custom JS/TS you'd have to write, debug, and get IT to approve
  during the 5-hour clock. It earns zero rubric points and risks the approved-tools rule.
  Subagents + commands give you the same teamwork with nothing to build.

## 4. Documenting every prompt (point 3: for the demo + scored evidence)

- After any meaningful build, the owner runs `/logprompt` → appends to `docs/claude-log.md`.
- `/ship` refuses to proceed unless the prompt was logged (keeps it honest under pressure).
- This is the Claude-usage evidence (15 pts): prompt quality, plan-first, and corrections made.

## 5. Build → test handoff (point 5 + 6)

- The builder NEVER writes its own tests. On handoff it says "ready for tester" + branch name.
- A different agent (`tester`) writes rule-stating tests and runs them.
- If a test fails, it goes back to the builder — the tester does not fix the feature.
- This separation is what the rubric rewards (QA owns "test cases from the rules").

## 6. The status sheet + docs (point 4, adapted for safety)

**The deck mandates a shared Excel workbook for tracking and says no subscriptions / code
stays local.** So the tracker is built to work BOTH ways, and git is always the source of truth:

- **Default (always safe):** the `tracker` agent writes status to `docs/status.csv` in the
  repo (opens in Excel, travels with git). `/ship` updates it automatically.
- **If a mentor approves Google Sheets MCP:** connect it once with `/mcp` → pick Google
  Sheets, put the sheet URL in `.env` as `STATUS_SHEET_URL`, and the `tracker` agent will
  also write the same row to that sheet. Same for Google Docs (optional doc sync).
- Either way, **one agent (Chetan's `tracker`) owns the board**; only the Master changes
  assignments, so two agents never grab the same task (avoids last-write races).

## 7. Git rules (from the deck — enforce these)

- Repo name: `manthan-w2-b-team44` (lowercase, `manthan-<wave>-<track>-team<NN>`).
- `main` is protected. Work on short-lived `feature/<thing>` or `fix/<thing>` branches.
- Merge only after one teammate reviews (`/grill` + a human).
- Commit messages: imperative, one change each, prefixed `feat|fix|test|docs|ci|chore`.
  e.g. `feat: add checksum ledger for re-delivery skip`
- No secrets or data in the repo: `.env` is git-ignored; commit only `.env.example`.

`/ship` does the commit + push + PR + sheet update in one step so these rules happen
automatically instead of from memory.
