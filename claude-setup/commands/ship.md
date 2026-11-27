Ship the current feature, enforcing our rules in order. Stop and tell me if any check fails.

1. Confirm a test exists for this feature and `make test` is green. If not, STOP.
2. Confirm this work was logged in docs/claude-log.md. If not, run /logprompt first.
3. Run `make lint` (ruff + black). Fix formatting if needed.
4. Stage changes. Commit with an imperative message prefixed feat|fix|test|docs|ci|chore,
   one change per commit. Branch must be feature/<thing> or fix/<thing> (never commit to main).
5. Push the branch: `git push -u origin <branch>`.
6. Open a PR: use `gh pr create` if the GitHub CLI is available; otherwise print the compare
   URL for me to open. PR body: what changed, the rule it implements, the test name.
7. Act as the `tracker` agent: set this task's row in docs/status.csv to state=in_review,
   test_state=pass, with the branch name and updated_at. Mirror to the Google Sheet if configured.
8. Tell me the branch, the PR link, and that the board is updated. The Master merges to main.
