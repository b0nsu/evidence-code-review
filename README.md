# evidence-code-review

A Claude Code skill that reviews code and tests from evidence. It sorts what it finds into three groups and keeps them apart.

| Group | Meaning |
|---|---|
| Findings | Defects with a concrete trigger, a causal path and a grounded contract |
| Assurance gaps | Behavior that no current test distinguishes from a plausible bug, with no proof of a bug |
| Contract unknowns | Points where the requirement is missing or sources conflict, so no conclusion is justified |

"There is no test for refunds over the original amount" is an assurance gap. "User B can read user A's order by ID" is a finding.

The skill only reads. It may run existing, narrow local checks such as a project's own unit tests. It does not edit files, add tests, commit, install dependencies or fetch from the network.

## Install

Copy the skill files into your personal skills directory:

```bash
rsync -a --delete --delete-excluded --exclude __pycache__ \
  --include /SKILL.md --include '/references/***' --include '/scripts/***' --exclude '*' \
  ./ ~/.claude/skills/evidence-code-review/
```

Claude Code watches `~/.claude/skills/`, so the skill is available in the current session without a restart. To install it for one repository only, copy it to that repository's `.claude/skills/evidence-code-review/` instead.

Check the installed version in the `metadata.version` field of `~/.claude/skills/evidence-code-review/SKILL.md`.

## Usage

Ask for a review in plain language or invoke `/evidence-code-review`. What you pass decides the mode.

| You pass | Mode | What gets reported |
|---|---|---|
| A PR, commit, diff, base/target, or "my pending changes" | Diff review | Defects the change introduces or newly exposes |
| Files, a module, a function or a `path:line` range, with no change | Snapshot review | Defects present in that code now, with no claim about which change caused them |
| Candidate findings from another reviewer or tool | Verify mode | One verdict per candidate |

```text
/evidence-code-review HEAD~1..HEAD
Review this PR: https://github.com/org/repo/pull/123
Check the test quality of refund() in src/billing/refund.ts
Verify whether these review comments are real bugs: <paste the list>
```

If the scope cannot be resolved, the conclusion is `incomplete`. A review with no findings ends with "확인 가능한 결함을 발견하지 못했습니다" (no verifiable defect found) and states that this does not prove the code is safe.

### Review lenses

Every review looks through three lenses. Each lens ends as `supported`, `risk` or `unknown`. `supported` means the inspected evidence supports the narrow claim within the reviewed scope.

| Lens | Question |
|---|---|
| direction | Does the change match a grounded contract (requirements, API, security invariants)? |
| execution | Does it behave correctly on normal, negative, boundary, concurrency and error paths? |
| verification | Do the tests tell correct behavior apart from incorrect behavior? |

### Verify mode verdicts

| Verdict | Condition |
|---|---|
| `confirmed` | The premise is true, the path is reachable, and the behavior breaks a grounded contract |
| `plausible` | Premise and reachability are checked, but the contract is unclear or the trigger is unproven |
| `rejected` | The premise is false, the path is unreachable, or an independently grounded contract allows the behavior |
| `unverified` | The evidence needed to check it (repository, commit, file, call path) was not accessible |

The skill does not inherit a candidate's severity or wording. If any candidate is `unverified`, the conclusion cannot be `no_actionable_findings`. Missing evidence is never filled in from outside the reviewed repository.

## JSON output and validator

Output meant for automation follows schema `1.2` in [references/finding-contract.md](references/finding-contract.md). Verify mode verdicts go in `candidate_verdicts`. The review kind goes in `scope.kind` (`diff` or `snapshot`).

```bash
python3 scripts/validate_review.py review.json
```

| Exit code | Meaning |
|---|---|
| 0 | Valid |
| 1 | Structural errors, listed on output |
| 2 | Unreadable input: missing file, invalid JSON or non-UTF-8 bytes |

The validator checks field structure and internal consistency. It does not check whether a claimed defect exists. Some of the rules it enforces:

- A `confirmed` verdict points to an existing finding id.
- `plausible` and `unverified` verdicts carry a `limitation`.
- A snapshot review has a `target` and no `base`.

Documents with `schema_version: "1.1"` are still accepted under the 1.1 rules. New output should use 1.2.

## Repository layout

```text
SKILL.md                              Skill body: review procedure, verify mode, final response
references/finding-contract.md        Report format, P0-P3 severity, JSON schema 1.2
references/three-quality-lenses.md    Criteria and examples for the three lenses
references/test-quality.md            Test oracles, matcher traps, counterexamples
references/verification-playbook.md   Checks per risk type and allowed execution
scripts/validate_review.py            JSON output validator
tests/test_validate_review.py         Validator regression tests
tests/test_post_review.py             Review bot posting tests
bot/                                  GitHub review bot: posting script, prompt, setup notes
.github/workflows/evidence-code-review.yml   Runs the bot on an `ai-review` label or `/review` comment
docs/audits/                          Prompt audit report and patch
```

The installed skill needs only `SKILL.md`, `references/` and `scripts/`. `README.md`, `tests/`, `bot/`, `.github/` and `docs/` stay in the repository.

## GitHub review bot

Add the `ai-review` label to a pull request, or comment `/review`, to get the skill's review on the PR: each finding as an inline comment on its lines, and the summary, assurance gaps and contract unknowns in one separate comment that reruns edit in place. The model runs in a job without a write token, and a separate job validates the JSON and posts it. Setup and the security model are in [bot/README.md](bot/README.md).

## Development

### Tests

```bash
python3 -m unittest discover -s tests
```

The tests load the JSON examples in `finding-contract.md` as fixtures. When you change an example or a field in the contract, change the validator and the tests in the same commit.

### Release steps

1. Bump `metadata.version` in `SKILL.md`.
2. If the schema changed, update the Versions section of `finding-contract.md`, `SCHEMA_VERSIONS` in `validate_review.py`, and the tests.
3. Add a row to the version table below.
4. Commit and tag `v<version>`.
5. Run the install command.

### Evals

The eval workspace lives outside this repository at `~/.claude/skills/evidence-code-review-workspace/`. It holds two real commit reviews, one verify-mode case, one snapshot fixture and one hold-out verify case, all graded blind. Each iteration records its results and conclusions in `iteration-N/notes.md`. The cases are commits from a private codebase, so the cases and notes are not published. This README reports aggregate results only.

An eval subagent loads the installed skill through the Skill tool, so one run can only measure one version. Install each version from its `skill-snapshot-<version>` directory in turn.

When comparing two versions, rerun the baseline version in the same session. Regrading an earlier iteration's outputs mixes model and tool changes into the version difference. Iteration 13 showed this: a regression blamed on 0.4.0 also appeared in a same-day 0.3.5 run.

## Versions

| Version | Change |
|---|---|
| 0.4.1 | Leave `unverified` candidates unverified instead of filling evidence from outside the repository (network, other projects' dependencies) |
| 0.4.0 | `unverified` verdict, JSON `candidate_verdicts`, snapshot review (`scope.kind`), schema 1.2, no forced test-reading order, non-UTF-8 input handling |
| 0.3.5 | Clearer negative-test example |
| 0.3.4 | Cleaned up the 1.0 schema description; lens example switched to idempotent payments |
| 0.3.3 | `rejected` limited to independent contract evidence; a missing outcome is an assurance gap only with contract evidence; outcome lists reported only when checked; validator enum type guards |
| 0.3.2 | Sibling-outcome check |
| 0.3.1 | Assertion breaking, matcher traps |
| 0.3.0 | Verify mode |
| 0.2.8 | Initial snapshot, including producer/consumer tracing |

## Eval status

Iteration 10 measured 0.4.0. In verify mode, unchecked candidates promoted to `plausible` fell from 13 to 2, and JSON-only output listed every candidate. Single-review quality did not differ from 0.3.x at n=3.

In iterations 10 to 12, 0.4.x looked worse on the admin case. Iteration 13 reran 0.3.5 on the same day and saw the same shifts: more false claims, an inflated severity, and SDK source fetched from the network. The cause was a change in the run environment.

After 0.4.1 added the boundary sentence, its 9 runs made 0 web calls. The same-day 0.3.5 runs made web calls in 1 of 3.

Iteration 14 tested a proposed 0.4.2 (B1): rewording the `plausible` verdict so author-stated intent routes to "state what the design gives up". Three runs per version on one verify case, blind-graded, showed no benefit (author-intent grader 0.4.1 6/8, 0.4.2 3/8, within n=3 noise); 0.4.1 already routed those candidates to `plausible`, so B1's premise did not hold here. B1 was held; the skill stays at 0.4.1.

Iteration 15 ran the same comparison on a hold-out commit that was not used to design the skill, taken from another area of the same codebase. Both versions verified the same candidate list, three runs each, blind-graded. The content graders passed in all six runs. On the author-intent grader 0.4.1 scored 10/12 and 0.4.2 scored 11/12, a one-instance gap within n=3 noise that stricter grading could reverse. Across iterations 14 and 15, B1 shows no consistent direction, so it stays held.

The hold-out also checked whether the skill overfits the cases it was tuned on. No run confirmed a false finding. Candidates that depended on code outside the reviewed repository stayed `unverified`. The strongest runs noticed that a contract file updated in the same commit was the author's own claim, not an independent contract.

## License

MIT. See [LICENSE](LICENSE).
