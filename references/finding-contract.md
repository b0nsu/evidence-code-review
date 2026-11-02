# Review / handoff contract v1.1

## Default report (Markdown)

Use a clear split, not a three-column scorecard that implies correctness is proved:

1. **Findings**: actionable `code_defect`, `test_defect` or `contract_defect` newly introduced or exposed by the reviewed change, grounded in a precise defect location and evidence linking it to the change. Sort P0-P3, then confidence; consolidate the same root cause.
2. **Assurance gaps**: meaningful evidence missing for a relevant behavior, without claiming an implementation bug. Say what discriminating test would help.
3. **Contract unknowns**: unclear or conflicting expectations that prevent a justified conclusion. Say what source/decision is missing; do not guess.
4. **Quality assessment**: direction / execution / verification with `supported`, `risk`, or `unknown` **within the inspected scope** and a sentence of evidence or limitation each.
5. **Scope and checks**: exact diff, files examined, executed command outcomes, static-only claims, limitations, and verdict.

A finding must contain: `[P0-P3]` + finding kind/axis + changed source location, or the unchanged defect location that a changed entry point or call path newly exposes; contract/invariant source; triggering state; code/test mechanism; actual or reasoned impact; contrary evidence inspected; verification status (`executed` or `static_trace`); smallest correction. In the JSON form each of these is a required field (`location`, `contract`, `verification` are objects); `scripts/validate_review.py` rejects a finding that omits any of them. For an unchanged defect location, the `observation` or `trigger` must cite the changed entry point/call path and explain the new reachability; `location` remains the actual defect site. A test defect should include a **counterexample that current test would wrongly accept/reject**. A passing test or missing negative test alone is not a production bug.

### Severity

- `P0`: catastrophic and imminently reachable with concrete proof.
- `P1`: serious, credibly reachable security, production, or data-integrity failure.
- `P2`: meaningful, reachable correctness or test-oracle defect.
- `P3`: limited-impact but concrete behavior defect.

`confidence=high` when directly observed or the precise static trace is unambiguous; `medium` only when a concrete path exists and a stated bounded assumption remains. Unresolved speculation goes in gaps/unknowns, not findings. No finding does **not** certify safety.

## Optional JSON schema_version 1.1

The following is an **example document**, not a claim about a real repository. All strings concerning evidence must still be checked by the reviewer. The validator checks fields and logical consistency, not the truth of the claims.

```json
{
  "schema_version": "1.1",
  "scope": {
    "base": "HEAD",
    "target": "working-tree",
    "files_reviewed": ["src/orders.py", "tests/test_orders.py"],
    "limitations": ["No live database available"]
  },
  "checks": [
    {"command": "python -m unittest tests.test_orders", "status": "not_run", "result": "Database fixture unavailable"}
  ],
  "quality_assessment": {
    "direction": {"status": "supported", "support": "Documented owner-only access invariant checked for this endpoint"},
    "execution": {"status": "risk", "support": "Changed lookup does not filter by owner"},
    "verification": {"status": "risk", "support": "New test asserts only the owner's successful request"}
  },
  "findings": [
    {
      "id": "F1",
      "kind": "code_defect",
      "axis": "execution",
      "severity": "P1",
      "confidence": "high",
      "title": "Cross-tenant order retrieval",
      "location": {"path": "src/orders.py", "line_start": 42, "line_end": 43},
      "contract": {"source": "docs/access-control.md#orders", "expectation": "Orders are readable only by their owners"},
      "observation": "The new read filters only on ID, not owner",
      "trigger": "Authenticated B requests a known order ID owned by A",
      "impact": "B can read A's order if this route is reachable",
      "counterevidence": "Looked for authorization middleware and downstream owner filtering; none is present in the supplied path",
      "verification": {"status": "static_trace", "detail": "Traced route to repository query; code was not run"},
      "recommendation": "Apply owner scope to the query and test cross-tenant denial"
    }
  ],
  "assurance_gaps": [
    {
      "area": "tests/test_orders.py:17",
      "risk": "The owner-success case does not discriminate an unscoped order query",
      "discriminating_check": "Call as another authenticated user and assert the documented deny response",
      "evidence": "Only same-owner lookup is asserted in the inspected test"
    }
  ],
  "contract_unknowns": [],
  "conclusion": {"status": "issues_found", "summary": "One concrete cross-tenant read defect"}
}
```

`kind`: `code_defect | test_defect | contract_defect`. `axis`: `direction | execution | verification`. `quality_assessment.*.status`: `supported | risk | unknown`. `checks.*.status`: `pass | fail | not_run`; `verification.status`: `executed | static_trace`; `conclusion.status`: `issues_found | no_actionable_findings | incomplete`.

A `test_defect` additionally requires `test_counterexample` (nonempty string explaining how the test accepts incorrect behavior or rejects correct behavior). The `assurance_gaps` list is permitted with `no_actionable_findings` and must not force `issues_found`. The same root cause can have both a code finding and test gap without inflating finding count. A true missing or inaccessible scope must use `incomplete`.

Each `assurance_gaps` entry requires nonempty `area`, `risk`, `discriminating_check`, `evidence`. Each `contract_unknowns` entry requires nonempty `question` (the expectation that cannot be grounded), `blocked_decision` (the conclusion it prevents), and `evidence` (the sources inspected and how they conflict or are missing).

### Older JSON

`schema_version=1.0` belongs to the v0.1 contract; it is not silently accepted by the v1.1 validator. Consumers should migrate explicitly. This prevents downstream tools from interpreting absent test-quality fields as positive evidence.
