# Risk-sensitive verification playbook

Load selectively after identifying a relevant changed surface. This is **not a mandatory coverage checklist**. Inspect independent contract and test-oracle validity alongside execution behavior.

| Changed surface | Direction/contract question | Implementation failure | Test-oracle trap |
|---|---|---|---|
| Authentication / authorization | Who may read/write which object? | missing or bypassed principal/tenant filter | owner-only success test passes unauthorized implementation; `!= 500` is not a denial assertion |
| API / consumer contract | Required response/status/schema and compatibility? | new type/status breaks callers | golden snapshot regenerated from changed code without checking contract |
| Data writes / migrations | Invariants, old/new readers, rollback requirements? | partial state, duplicate write, lost rows | test checks that method returns, not committed state or rollback |
| Error handling / retries | Failure surfaced, retried, or intentionally swallowed? | exception hidden, false success | mocked dependency cannot fail or assertion checks only log output |
| Billing / side effects | Exact amount and idempotency requirements? | duplicate charge or missing compensating action | only first request tested; repeated requests absent |
| Cache / concurrency / jobs | Consistency and ordering promises? | stale data, interleaving race | test runs sequentially and claims concurrency safety |
| Parsing / serialization | Accepted input and rejection semantics? | injection or malformed input handling | only valid payload tested, unsafe/empty input not asserted |
| UI/state | User-facing flow and accessibility expectation? | stale UI, invalid transition | render/no-exception test never triggers interaction |
| Performance | Target and bounded workload? | multiplicative work or regression | benchmark measures a proxy without evidence it tracks user outcome |

For a candidate, distinguish:

- **Change trigger and executable reachability**: what new path is available?
- **Trusted expected outcome**: where does it come from? Is it code-derived or independently justified?
- **Concrete bad state**: input, actor, timing, prior state and expected/actual mechanism.
- **Contradicting evidence**: existing guards, policies, retries, compensations, flags, safe default.
- **Proposed discriminating check**: good behavior passes; a realistic wrong behavior fails.

Do not automatically turn missing tests, merely theoretical races, style, or unrelated pre-existing issues into findings. If test confidence is deficient but code behavior remains unproven, record an `assurance_gap`. When intent is absent or disputed, use `contract_unknowns`.

## Safe verification

Prefer `git status --short`, `git diff --check`, specific `git diff`, `rg`, and reading local files. Narrow existing tests only if the runtime is trusted and side effects controlled; do not treat `npm test` or repo scripts as intrinsically read-only. Never run migrations, install dependencies, use production credentials, call external services, or write into the source tree to prove a test deficit. Mutation testing requires an explicit request in the current task and a trusted local harness plus an isolated disposable copy with controlled side effects; otherwise skip it. Do not request routine extra approval. State exactly what was executed.
