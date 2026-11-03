# Three quality lenses — separate the target from evidence for it

This is a **review framework synthesized for this Skill**, not a validated three-factor quality law or an existing project's formal standard.

| Lens | Question | Good evidence | Misleading shortcut |
|---|---|---|---|
| Direction | Is this the correct requirement/behavior? | user acceptance, schema/API/security contracts, explicit invariants, compatibility promises | existing implementation or tests alone |
| Execution | Does code satisfy that requirement in reachable conditions? | observed targeted behavior, concrete static path and guards | compiler success, suppressed exception, author's summary |
| Verification | Do tests discriminate desired from forbidden behavior? | justified oracle, negative/counterexample behavior, meaningful assertion, reliable isolation | green tests, coverage %, snapshots or mocked success alone |

Direction and execution concern **product correctness**. Verification concerns the **trustworthiness of evidence about correctness**; it may uncover errors in the other two but is not a separate independent proof of correctness.

## Contract map

1. Record relevant named requirement and where it comes from. If the only source is test expectation inferred from the same code, label `derived_from_implementation` and question independence.
2. Distinguish safety/security invariants from product choices. For instance cross-tenant isolation may be justified by explicit access-control design or data ownership semantics; an unspecified sorting preference cannot be fabricated as a requirement.
3. If formal requirements are absent or mutually inconsistent, classify the aspect `unknown`; avoid silently inventing a business decision.
4. Separate **actual output**, **claimed expected output**, and **source of that expectation**. Never assume a passing assertion makes its expected value correct.

## Which issues become findings?

- **Code defect:** concrete reachable implementation violates a supported requirement/invariant; e.g., new lookup crosses tenant boundary.
- **Test defect:** changed test encodes a wrong expected result, asserts an irrelevant property while purporting to check a contract, or demonstrably cannot detect the regression it claims to guard against. Require changed test lines and concrete counterexample. Other missing cases become `assurance_gap`, not a production defect.
- **Contract defect:** changed public schema/documented API contract itself contradicts an independently supported compatibility/requirement. Do not use this label merely because no one provided a spec.
- **Assurance gap:** test doesn't cover a credible, important negative path but implementation has not been shown faulty. Suggest a discriminating test without claiming a bug.
- **Contract unknown:** competing or missing sources prevent judging expected behavior. State exactly which decision cannot be grounded.

## Mini-review example (illustrative, not an actual PR)

Requirement: retrying a payment request with the same idempotency key charges at most once.

- `test_first_charge_succeeds` expects one charge. It passes whether or not retries are deduplicated; it is **not** an idempotency proof.
- `test_retry_with_same_key_charges_once` sends the request twice and asserts exactly one charge row. It probes the forbidden outcome.
- `test_retry_charges_again` expects two charges. If added in the diff, its **oracle is wrong** relative to the requirement, even if it passes.
- If the new handler actually charges twice, that is **a code defect**; report separately from test weakness only when fixes/action owners differ and avoid double-counting one root cause.

A negative test is useful only if it asserts the correct outcome derived from a credible source; `expect(chargeMock).toHaveBeenCalled()` does not show the second call was suppressed.
