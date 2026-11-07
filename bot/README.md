# GitHub review bot

`.github/workflows/evidence-code-review.yml` runs the skill on a pull request and posts the result as one PR review. Nothing in `bot/` is installed with the skill.

## Use

Add the `ai-review` label to a pull request, or comment `/review` on it. Only a PR whose branch is in the same repository is reviewed. A maintainer can also start it from the Actions tab with a PR number.

| Trigger | Who can use it | Where the workflow file must be |
|---|---|---|
| `ai-review` label | triage access or higher | the PR's base branch (for example `develop`) |
| `/review` comment | owner, member, collaborator | the default branch |
| Actions tab | write access | the branch picked in the run dialog |

The bot removes the label after a run, so adding it again reviews the PR again. Pick the label when PRs merge into a branch other than the default branch.

The bot posts one review with event `COMMENT`. It never approves or requests changes.

- A P0-P2 finding with `confidence=high` becomes an inline comment when its lines are inside a diff hunk.
- Every other finding goes into the review body with the reason: below the inline threshold, outside the diff, or rejected by GitHub.
- Assurance gaps, contract unknowns, the three-lens assessment and the scope are in the review body.
- A finding already posted inline by an earlier run is listed once in the body and not commented again. The match uses the path, kind and title, so a reworded title counts as a new finding.
- If Claude Code fails, or its JSON does not pass `scripts/validate_review.py`, the bot posts a short comment with the reason and a link to the run.

## Setup

1. Add the repository secret `ECR_ANTHROPIC_API_KEY`, or `ECR_CLAUDE_CODE_OAUTH_TOKEN` for a Claude subscription (make one with `claude setup-token`). The API key wins when both are set. The `ECR_` prefix keeps the bot off credentials that other workflows in the repository use. Create the `ai-review` label.
   Anyone who can push a branch to the repository can run a workflow that reads these secrets, so a personal token is shared with every writer of that repository.
2. To use the bot in another repository, copy the workflow file there. It checks out the skill and the bot from `ECR_SKILL_REPO` at `ECR_SKILL_REF`, so that repository must be readable from the other one.
3. Adjust the workflow `env` block: `ECR_MODEL`, `ECR_MAX_BUDGET_USD`, and `ECR_CLAUDE_CODE_VERSION`. The bot was tested with Claude Code 2.1.318. The flags it uses (`--restricted`, `--plugin-dir`, `--permission-prompts`, `--max-budget-usd`) may not exist in older versions.

## Security model

The PR under review is untrusted input. The workflow separates the model from the write token.

| Job | Token | Runs the model | Runs PR code |
|---|---|---|---|
| `review` | `contents: read`, `pull-requests: read`; the model's step gets only `ANTHROPIC_API_KEY` | yes | no |
| `publish` | `pull-requests: write` | no | no |

- Claude Code runs with `--restricted`. It ignores user, project and local settings files, so hooks in the PR's `.claude/settings.json` do not run. A local run without `--restricted` executed such a hook; with it, the hook did not run.
- The tools are `Read`, `Grep`, `Glob` and `Skill`. The model cannot run commands or fetch URLs, and the file tools are confined to the checkout, the context directory and the skill plugin.
- `.claude/` and `.mcp.json` are deleted from the checkout before the run, so the PR cannot add skills, agents or MCP servers.
- The skill, the prompt and `post_review.py` come from `ECR_SKILL_REPO`, never from the PR. A PR that changes the skill is reviewed with the skill on `ECR_SKILL_REF`. With the label trigger, GitHub reads the workflow file itself from the PR's merge ref, so a writer who edits that file in a PR controls the run; anyone with write access can already push a workflow.
- GitHub does not start `pull_request` workflows for a PR with merge conflicts, so the label does nothing until the conflict is resolved. If the review job fails before publishing, the label stays; remove it and add it again to retry.
- Fork PRs are refused. `issue_comment` workflows run with repository secrets, so running the model on fork code would expose `ANTHROPIC_API_KEY` to a prompt-injection attempt in that code.
- `post_review.py` breaks `@mentions` and HTML comments in model text, so a review cannot ping people or forge the bot's markers.

The model can still be misled by text in the PR. The validator checks structure, not truth, so a misled review can still be posted. It is posted as a comment and never as an approval.

## Files

| File | Role |
|---|---|
| `post_review.py` | Extracts the JSON from Claude Code output, validates it, anchors findings, posts the review |
| `review-prompt.md` | Prompt template; the workflow fills `$PR_NUMBER`, `$BASE_SHA`, `$HEAD_SHA`, `$CTX_DIR` |
| `verify-prompt.md` | Verify-mode prompt for candidates in `$CTX_DIR/candidates.md`; not wired into the workflow yet |
| `../tests/test_post_review.py` | Tests, using the JSON example in `references/finding-contract.md` as the fixture |

To check the posting step without GitHub, pass saved API responses and `--dry-run`:

```bash
python3 bot/post_review.py --repo OWNER/NAME --pr 1 --head-sha SHA \
  --claude-output claude-output.json --files-json files.json --comments-json comments.json --dry-run
```

## Not in v0

- Verify mode with candidates taken from other bots' PR comments.
- Hiding the summaries of earlier runs.
- Reviewing fork PRs.
