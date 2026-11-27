Run the pass/fail GATE check before we submit. These disqualify us if breached. For each,
inspect the repo and report PASS or FAIL with the evidence:

1. Synthetic/public data only — scan the repo and data/ for anything that looks like real
   or client data. Confirm only synthetic/public data is present.
2. Open-source / free tools only — no subscription-only tools in the stack.
3. Code stays local / in company Git — no code pushed anywhere outside the approved repo.
4. No pre-built solution code — confirm the solution was built today from the starter/these
   templates, and the prompt log in docs/claude-log.md shows the build happening.
5. No secrets in the repo — grep for keys/passwords; confirm .env is git-ignored and only
   .env.example (dummy values) is committed; check PII handling in dim_customer.

End with: ALL GATES PASS, or a list of what to fix. Be strict — a breach removes us from ranking.
