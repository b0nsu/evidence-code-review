# Test quality — verify the oracle, not just the green indicator

Load when the diff changes tests, tests are cited as proof, coverage is prominent, or a high-impact path is under review. This reference guides judgment; it is not an exhaustive mandatory checklist.

## Independent oracle

For a cited test, identify **what failure would cause it to fail** and **why its expected output is correct**. Good independent sources include explicit requirements, protocol standards, previously agreed invariants, and validated reference behavior. Existing code, generated tests, and snapshots are not automatically independent.

Distinguish:

- **Wrong oracle**: assertion expects behavior that the supported contract forbids. Actionable `test_defect` if the erroneous test is within the review change.
- **Weak oracle**: asserts only status, no exception, or nonempty output; could pass when contract is violated. May be a `test_defect` if the changed test explicitly promises protection for a named behavior and its counterexample demonstrably passes; otherwise an `assurance_gap`.
- **Incomplete sample**: positive case only; important forbidden and edge behavior untested. Normally a gap, not evidence the implementation is broken.
- **Shared assumption**: production code and tests derived from the same wrong interpretation. Cross-check both against independent contract, not each other.
- **False green**: swallowed exceptions, wrong mock boundary, test not discovered/skipped, early return, lack of assertion or assertion in dead code, CI failure ignored. Require trace/observed result.

## High-value contrasting scenarios

Select by relevance, not quota: authorized/unauthorized principal; same-tenant/cross-tenant; missing/null/empty; duplicate/idempotent; insufficient balance and partial rollback; concurrency interleaving; old/new consumer; invalid input; error and retry; cache invalidate/refresh. For each, state intended outcome, source, and observable failure, not merely an input list.

## Matcher traps

Forms that look like protection but pass for a plausible defect. The principle is what matters; these are examples, in Jest terms, and the same shapes exist in other frameworks.

- Negated conjunction: a negated matcher whose argument lists several items (array or object containment, partial object match) fails only when every listed item matches, so one leaked item passes. Assert each forbidden item on its own.
- Presence without content: `toHaveBeenCalled()`, `toBeDefined()`, `toBeTruthy()`, `expect.anything()`, `expect.any(T)` where the value is what the test name promises.
- Partial matchers (`toMatchObject`, `objectContaining`, substring `toContain`) ignore fields they do not name, so they cannot catch a leaked extra field.
- Async: a promise assertion that is not returned or awaited, assertions in `.then`/`.catch` without `expect.assertions(n)`, an unused `done`. If the branch never runs the test passes.
- Assertions inside loops, callbacks or conditionals that can run zero times.
- Expected values or snapshots copied from current output.

For each one found, state the one-change counterexample (the implementation edit or input) that still passes.

## Test sensitivity, mutation, and limitations

- **Counterexample inspection**: propose a small incorrect behavior (e.g., skip ownership check). Determine whether the test would detect it. Prefer deterministic static demonstration or an isolated toy fixture.
- **Mutation testing**: run only when the user's current request explicitly asks for mutation analysis and an existing, trusted, locally runnable harness plus an isolated disposable copy are available without uncontrolled side effects. This task-level request is the required authorization; do not ask again as routine review. If any condition is absent, do not run mutation tests; explain the limitation and use a static counterexample instead. Mutate only disposable copies or isolated test fixtures, never the user's working tree. Count *surviving relevant non-equivalent mutants* only where validity can be established; equivalent mutants and unreachable paths can survive for non-bug reasons.
- Killing a mutant means a test is sensitive to **that mutation**, not that the test oracle is correct. A wrong expected value can kill correct implementations.
- Coverage measures what ran, not whether assertions were appropriate. A passing suite is neither proof of product intent nor absence of regression.
- Resource limits, flaky tests, unmet dependencies, and external side effects reduce the strength of a conclusion; report them as verification limitations.

## Reporting

For each material test issue or assurance gap, supply:

- tested claim / relevant requirement and independent source;
- observed assertion and whether it checks positive, forbidden, and important failure conditions;
- **discriminating counterexample** (implementation change or input that should be rejected);
- what current tests would do *if known* (observed vs reasoned); and
- one minimal test that would distinguish good from bad behavior, with no automatic edits.

Never elevate “no test” to a P1 implementation defect without code evidence. Do not claim all tests were inspected if only selected files were read.
